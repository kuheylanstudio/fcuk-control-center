# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""HP Omen / Victus arka ucu: HP BIOS WMI arayuzu (root\\wmi, hpqBIntM.hpqBIOSInt*).

donanim.DCHU ile ayni arayuzu sunar (status, temps, power_mode, set_power_mode, fan_mode, set_fan_mode,
set_color...), boylece profiller, sensorler, klavye motoru ve sunucu degismeden calisir. Clevo'ya ozgu ham
komutlar (set_wmi, set_data, write_app) ve ozel fan egrisi HP'de yoktur: Unsupported verir.

Protokol (yalnizca bilgi olarak Linux hp-wmi surucusu ve OmenMon'dan dogrulandi, kod alinmadi):
  Giris  hpqBDataIn  { Sign "SECU", Command, CommandType, Size, hpqBData[Size] }
  Cikis  OutData     { rwReturnCode, Data[] }   yontem adi cikis boyutuna gore: hpqBIOSInt0/4/128/1024/4096
  Donus kodu: 0 tamam, 2 imza yanlis, 3 bilinmeyen komut, 4 bilinmeyen komut tipi, 5 gecersiz parametre
  Komut 0x20008 (oyun):  0x10 fan sayisi, 0x11 fan devri (bayt 2-3 buyuk-endian), 0x1A termal mod {FF, mod},
                         0x23 sicaklik, 0x26/0x27 maksimum fan oku/yaz, 0x28 sistem tasarim verisi
                         (bayt 3 termal politika surumu, bayt 7 grafik anahtari destegi), 0x2B klavye tipi,
                         0x2D fan seviyesi (x100 rpm)
  Komut 0x20009 (klavye): 0x01 arka isik var mi, 0x02/0x03 renk tablosu oku/yaz (bayt 0 = son bolge indeksi,
                         bolge i rengi 25+3i: R G B; sira sag, orta, sol, WASD), 0x04/0x05 arka isik (E4 acik, 64 kapali)
  Komut 0x00001 / 0x52: grafik modu okuma (0 hibrit, 1 ayri kart, 2 Optimus); yazma komut 0x00002 (yeniden baslatma ister)
  Termal mod degerleri: Omen V0 {dengeli 00, performans 01, serin 02}, Omen V1 {30, 31, 50},
                        Victus {00, 01, sessiz 03}

Guvenlik: acilistaki yoklama yalnizca OKUMA komutlari gonderir. Yoklamada desteklenmeyen cikan ozellik icin
hicbir yazma komutu gitmez; yazmada BIOS 3/4 dondururse ozellik o andan itibaren kapatilir.

Tasima: hpqBIntM yontemleri COM/WMI uzerinden cagrilir. Bagimlilik eklememek icin tek, kalici ve gizli bir
Windows PowerShell sureci kullanilir (satir basina bir komut); her cagri icin yeni surec acilmaz.
"""
import base64
import queue
import subprocess
import threading
import time

import ceviri
import donanim as hw

CMD_READ = 0x01      # eski (legacy) okuma
CMD_WRITE = 0x02     # eski yazma (grafik modu)
CMD_GM = 0x20008     # oyun komutlari
CMD_KB = 0x20009     # klavye

GM_FAN_COUNT = 0x10
GM_FAN_SPEED = 0x11
GM_PERF_MODE = 0x1A
GM_TEMP = 0x23
GM_FAN_MAX_GET = 0x26
GM_FAN_MAX_SET = 0x27
GM_DESIGN = 0x28
GM_KBD_TYPE = 0x2B
GM_FAN_LEVEL = 0x2D
GPU_MUX = 0x52

KB_HAS_BACKLIGHT = 0x01
KB_COLOR_GET = 0x02
KB_COLOR_SET = 0x03
KB_BACKLIGHT_GET = 0x04
KB_BACKLIGHT_SET = 0x05
BACKLIGHT_ON, BACKLIGHT_OFF = 0xE4, 0x64

RC_OK = 0
RC_NOT_SUPPORTED = (3, 4)  # bilinmeyen komut / komut tipi: bu modelde yok
RC_INVALID = 5

COLOR_OFFSET = 25
KBD_PER_KEY = 3  # tus basina RGB: renk tablosu bu klavyeleri surmez

THERMAL = {  # aile/surum -> {dengeli, performans, sessiz}
    "omen_v0": {"balanced": 0x00, "perf": 0x01, "quiet": 0x02},
    "omen_v1": {"balanced": 0x30, "perf": 0x31, "quiet": 0x50},
    "victus": {"balanced": 0x00, "perf": 0x01, "quiet": 0x03},
}
FORCE_V0_BOARDS = {"8607", "8746", "8747", "8748", "8749", "874A"}  # tasarim verisi yanlis surum bildirir
TIMED_BOARDS = {"8A15", "8A17", "8A42", "8BAD"}  # performans modu zamanlayicili (EC yazmasi ister, yapilmaz)

# Clevo profil guc modu (donanim.POWER_MODES) -> HP termal mod
CLEVO_TO_HP = {0: "quiet", 1: "quiet", 2: "perf", 3: "balanced"}
GPU_MODES = {0: "hybrid", 1: "discrete", 2: "optimus"}

MAX_FAN_REFRESH = 60.0   # bazi BIOS'lar elle fan ayarini ~120 sn sonra birakir: maksimum fan dakikada bir yenilenir
KB_MIN_INTERVAL = 1 / 12.0  # WMI cagrisi pahali: klavye en fazla 12 kare/sn (motor her saniye son rengi yeniden yollar)


def method_for(outsize):
    """Cikis boyutuna gore hpqBIOSInt yontemi (hp-wmi ile ayni esikler)."""
    for limit in (0, 4, 128, 1024, 4096):
        if outsize <= limit:
            return limit
    raise ValueError("cikis cok buyuk: %d" % outsize)


class BridgeError(RuntimeError):
    """WMI'ye ulasilamadi (PowerShell sureci yok, zaman asimi, sinif yok, erisim reddedildi)."""


# ============================================================================= algilama
def system_info():
    """SMBIOS bilgileri (Win32_ComputerSystem / Win32_BaseBoard ile ayni kaynak) kayit defterinden: surec acmaz."""
    info = {"manufacturer": "", "model": "", "family": "", "board": ""}
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\BIOS") as k:
            for key, name in (("manufacturer", "SystemManufacturer"), ("model", "SystemProductName"),
                              ("family", "SystemFamily"), ("board", "BaseBoardProduct")):
                try:
                    info[key] = str(winreg.QueryValueEx(k, name)[0] or "").strip()
                except OSError:
                    pass
    except (OSError, ImportError):
        pass
    return info


def classify(info):
    """'omen' / 'victus' ya da None. Uretici HP olmali; model ya da aile adinda OMEN / Victus gecmeli."""
    maker = (info.get("manufacturer") or "").upper()
    if not (maker == "HP" or maker.startswith("HP ") or maker.startswith("HEWLETT")):
        return None
    text = ("%s %s" % (info.get("model") or "", info.get("family") or "")).upper()
    if "OMEN" in text:
        return "omen"
    if "VICTUS" in text:
        return "victus"
    return None


# ============================================================================= WMI tasima
_PS = r"""
$ErrorActionPreference = 'Stop'
function Say($s) { [Console]::Out.WriteLine($s); [Console]::Out.Flush() }
try {
  $bios = Get-WmiObject -Namespace root\wmi -Class hpqBIntM | Select-Object -First 1
  $cls = [wmiclass]'root\wmi:hpqBDataIn'
} catch { Say ('NOCLASS ' + ($_.Exception.Message -replace '\s+', ' ')); exit }
if (-not $bios) { Say 'NOCLASS'; exit }
Say 'READY'
while ($true) {
  $line = [Console]::In.ReadLine()
  if ($line -eq $null -or $line -eq 'QUIT') { break }
  try {
    $p = $line.Split(' ')
    $hex = if ($p[3] -eq '-') { '' } else { $p[3] }
    $data = New-Object byte[] ($hex.Length / 2)
    for ($i = 0; $i -lt $data.Length; $i++) { $data[$i] = [Convert]::ToByte($hex.Substring($i * 2, 2), 16) }
    $in = $cls.CreateInstance()
    $in.Sign = [byte[]](0x53, 0x45, 0x43, 0x55)
    $in.Command = [uint32]$p[0]
    $in.CommandType = [uint32]$p[1]
    $in.Size = [uint32]$data.Length
    if ($data.Length) { $in.hpqBData = $data }
    $name = 'hpqBIOSInt' + $p[2]
    $prm = $bios.GetMethodParameters($name)
    $prm['InData'] = $in
    $r = $bios.InvokeMethod($name, $prm, $null)
    $o = $r['OutData']
    $rc = [int]$o['rwReturnCode']
    $out = ''
    if ($p[2] -ne '0') { try { $d = $o['Data']; if ($d) { $out = -join ($d | ForEach-Object { '{0:x2}' -f $_ }) } } catch {} }
    if (-not $out) { $out = '-' }
    Say ('OK ' + $rc + ' ' + $out)
  } catch { Say ('ERR ' + ($_.Exception.Message -replace '\s+', ' ')) }
}
"""


class PsBridge:
    """Kalici gizli PowerShell sureci: satir basina bir hpqBIOSInt cagrisi. Tum cagrilar tek kilitten gecer."""
    TIMEOUT = 6.0
    START_TIMEOUT = 20.0
    MAX_RESTARTS = 3

    def __init__(self):
        self.lock = threading.Lock()
        self.proc = None
        self.lines = None
        self.restarts = 0
        self.dead = ""  # kalici hata nedeni (sinif yok / surekli cokuyor)

    def _start(self):
        exe = hw.tool_path("powershell")
        if not exe:
            raise BridgeError("powershell.exe bulunamadı")
        enc = base64.b64encode(_PS.encode("utf-16-le")).decode("ascii")
        self.proc = subprocess.Popen(
            [exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", enc],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            creationflags=hw.NO_WINDOW, cwd=hw.system_dir())
        self.lines = q = queue.Queue()
        out = self.proc.stdout

        def pump():
            for raw in iter(out.readline, b""):
                q.put(raw.decode("utf-8", "replace").strip())
            q.put(None)
        threading.Thread(target=pump, daemon=True).start()
        first = self._read(self.START_TIMEOUT)
        if first != "READY":
            self._kill()
            self.dead = first or "PowerShell yanıt vermedi"
            raise BridgeError(self.dead)

    def _read(self, timeout):
        try:
            return self.lines.get(timeout=timeout)
        except queue.Empty:
            return None

    def _kill(self):
        p, self.proc = self.proc, None
        if p:
            try:
                p.kill()
            except OSError:
                pass

    def call(self, command, ctype, data=b"", outsize=0):
        """(donus kodu, cikis baytlari). WMI'ye ulasilamazsa BridgeError."""
        size = method_for(outsize)
        line = "%d %d %d %s\n" % (command, ctype, size, bytes(data).hex() or "-")
        with self.lock:
            if self.dead:
                raise BridgeError(self.dead)
            if self.proc is None or self.proc.poll() is not None:
                if self.restarts > self.MAX_RESTARTS:
                    self.dead = "PowerShell köprüsü tekrar tekrar kapandı"
                    raise BridgeError(self.dead)
                self.restarts += 1
                self._start()
            try:
                self.proc.stdin.write(line.encode("ascii"))
                self.proc.stdin.flush()
            except OSError as exc:
                self._kill()
                raise BridgeError(str(exc))
            ans = self._read(self.TIMEOUT)
            if ans is None:
                self._kill()  # takilan ya da kapanan surec: bir sonraki cagri yeniden acar
                raise BridgeError("WMI zaman aşımı")
        kind, _, rest = ans.partition(" ")
        if kind == "OK":
            rc, _, hexdata = rest.partition(" ")
            return int(rc), (b"" if hexdata in ("", "-") else bytes.fromhex(hexdata))
        raise BridgeError(rest or ans)

    def close(self):
        with self.lock:
            if self.proc and self.proc.poll() is None:
                try:
                    self.proc.stdin.write(b"QUIT\n")
                    self.proc.stdin.flush()
                except OSError:
                    pass
            self._kill()


# ============================================================================= arka uc
class HpOmen:
    """HP Omen / Victus: donanim.DCHU yerine gecer. Ozellikler yoklamayla belirlenir (self.caps)."""
    available = True
    vendor = "hp"
    clevo = False

    def __init__(self, info, family, bridge):
        self.info = dict(info)
        self.family = family
        self.board = (info.get("board") or "").upper()
        self.bridge = bridge
        self.path = "HP BIOS WMI (root\\wmi hpqBIntM)"
        self.reason = ""
        self.caps = {"power": False, "fan_max": False, "fan_curve": False, "fan_read": False, "temp": False,
                     "kb": False, "gpu_mux": False}
        self.thermal = None       # THERMAL anahtari
        self.policy = None        # tasarim verisi bayt 3
        self.fan_count = 0
        self.fan_method = None    # GM_FAN_SPEED | GM_FAN_LEVEL
        self.kbd_type = None
        self.zones = 0
        self.color_table = None
        self.gpu_mode_now = None
        self.no_quiet = False
        self._power = None        # son ayarlanan Clevo kipi (HP termal modu okunamaz: EC'dedir)
        self._max = None
        self._max_at = 0.0
        self._kb_sent = None
        self._kb_at = 0.0
        self._backlight = None
        self.probe()

    @property
    def kb_available(self):
        return self.caps["kb"]

    # ------------------------------------------------------------------ ham cagri
    def query(self, command, ctype, data=b"", outsize=0):
        rc, out = self.bridge.call(command, ctype, data, outsize)
        return rc, out + bytes(max(0, outsize - len(out)))

    def _write(self, feature, command, ctype, data):
        """Yazma: yalnizca desteklenen ozellik icin; BIOS 'yok' derse ozellik kapatilir."""
        if not self.caps.get(feature):
            raise hw.Unsupported(ceviri.t("err.hpUnsupported"))
        rc, _ = self.query(command, ctype, data, 0)
        if rc in RC_NOT_SUPPORTED:
            self.caps[feature] = False
            raise hw.Unsupported(ceviri.t("err.hpUnsupported"))
        if rc != RC_OK:
            raise RuntimeError(ceviri.t("err.hpRc", rc=rc))

    def _try(self, command, ctype, data, outsize):
        """Yoklama okumasi: (True, veri) ya da (False, None). WMI'ye hic ulasilamazsa BridgeError yukari cikar."""
        rc, out = self.query(command, ctype, data, outsize)
        return rc == RC_OK, (out if rc == RC_OK else None)

    # ------------------------------------------------------------------ yoklama (yalnizca okuma)
    def probe(self):
        zero4 = bytes(4)
        ok, design = self._try(CMD_GM, GM_DESIGN, zero4, 128)
        if ok:
            self.policy = design[3]
        if self.family == "victus":
            self.thermal = "victus"
        elif self.board in FORCE_V0_BOARDS:
            self.thermal = "omen_v0"
        elif ok:
            self.thermal = "omen_v1" if self.policy >= 1 else "omen_v0"
        self.caps["power"] = self.thermal is not None  # Omen'de surum bilinmeden termal mod gonderilmez

        ok, out = self._try(CMD_GM, GM_FAN_COUNT, zero4, 4)
        self.fan_count = out[0] if ok and 0 < out[0] <= 4 else 2
        ok, out = self._try(CMD_GM, GM_FAN_SPEED, b"\x00", 4)
        if ok:
            self.fan_method = GM_FAN_SPEED
        else:
            ok, out = self._try(CMD_GM, GM_FAN_LEVEL, zero4, 128)
            if ok:
                self.fan_method = GM_FAN_LEVEL
        self.caps["fan_read"] = self.fan_method is not None

        rc, out = self.query(CMD_GM, GM_FAN_MAX_GET, zero4, 4)
        # hp-wmi maksimum fani okumadan yazar; okuma 'bilinmeyen komut' demedikce yazma desteklenir sayilir
        self.caps["fan_max"] = rc not in RC_NOT_SUPPORTED
        if rc == RC_OK:
            self._max = bool(out[0] & 1)

        ok, out = self._try(CMD_GM, GM_TEMP, b"\x01\x00\x00\x00", 4)
        self.caps["temp"] = bool(ok and 0 < out[0] < 125)

        ok_bl, bl = self._try(CMD_KB, KB_HAS_BACKLIGHT, zero4, 4)
        ok_t, kt = self._try(CMD_GM, GM_KBD_TYPE, zero4, 4)
        self.kbd_type = kt[0] if ok_t else None
        ok_c, table = self._try(CMD_KB, KB_COLOR_GET, zero4, 128)
        if ok_bl and (bl[0] & 1) and ok_c and self.kbd_type != KBD_PER_KEY:
            last = table[0]
            self.zones = last + 1 if last <= 3 else 4
            self.color_table = bytearray(table[:128])
            self.caps["kb"] = True
        ok_b, b = self._try(CMD_KB, KB_BACKLIGHT_GET, zero4, 4)
        if ok_b:
            self._backlight = b[0] == BACKLIGHT_ON

        ok, out = self._try(CMD_READ, GPU_MUX, zero4, 4)
        if ok and out[0] in GPU_MODES:
            self.gpu_mode_now = GPU_MODES[out[0]]
            # tasarim verisi bayt 7: grafik anahtari destegi (bit 2 / bit 3)
            self.caps["gpu_mux"] = bool(design is not None and design[7] & 0x0C)

    # ------------------------------------------------------------------ olcumler
    def status(self):
        s = {}
        if self.caps["temp"]:
            rc, out = self.query(CMD_GM, GM_TEMP, b"\x01\x00\x00\x00", 4)
            if rc == RC_OK and 0 < out[0] < 125:
                s["cpu_temp"] = out[0]
        if self.fan_method == GM_FAN_SPEED:
            for i, key in enumerate(("cpu_rpm", "gpu_rpm")[:max(1, min(self.fan_count, 2))]):
                rc, out = self.query(CMD_GM, GM_FAN_SPEED, bytes([i]), 4)
                if rc == RC_OK:
                    s[key] = (out[2] << 8) | out[3]
        elif self.fan_method == GM_FAN_LEVEL:
            rc, out = self.query(CMD_GM, GM_FAN_LEVEL, bytes(4), 128)
            if rc == RC_OK:
                s["cpu_rpm"], s["gpu_rpm"] = out[0] * 100, out[1] * 100
        self._keep_alive()
        return s

    def temps(self):
        return self.status().get("cpu_temp", 0), 0

    def _keep_alive(self):
        if self._max and self.caps["fan_max"] and time.monotonic() - self._max_at > MAX_FAN_REFRESH:
            try:
                self._set_max(True)
            except Exception:
                pass

    # ------------------------------------------------------------------ termal (guc) modu
    def power_value(self, mode):
        """Clevo kipi -> (HP termal ad, deger). Sessiz modu olmayan modelde dengeliye duser."""
        name = CLEVO_TO_HP.get(mode)
        if name is None:
            raise ValueError(ceviri.t("err.unknownPower"))
        if name == "quiet" and self.no_quiet:
            name = "balanced"
        return name, THERMAL[self.thermal][name]

    def power_mode(self):
        return self._power

    def power_key(self, mode):
        """Profil kartlarindaki metnin anahtari; termal mod yoksa None."""
        if not self.caps["power"] or mode not in CLEVO_TO_HP:
            return None
        return "hp.power." + self.power_value(mode)[0]

    def set_power_mode(self, mode):
        if not self.caps["power"]:
            raise hw.Unsupported(ceviri.t("err.hpUnsupported"))
        name, value = self.power_value(mode)
        rc, _ = self.query(CMD_GM, GM_PERF_MODE, bytes([0xFF, value, 0, 0]), 0)
        if rc == RC_INVALID and name == "quiet":  # Victus S: sessiz mod yok -> dengeli
            self.no_quiet = True
            name, value = self.power_value(mode)
            rc, _ = self.query(CMD_GM, GM_PERF_MODE, bytes([0xFF, value, 0, 0]), 0)
        if rc in RC_NOT_SUPPORTED:
            self.caps["power"] = False
            raise hw.Unsupported(ceviri.t("err.hpUnsupported"))
        if rc != RC_OK:
            raise RuntimeError(ceviri.t("err.hpRc", rc=rc))
        self._power = mode
        return ceviri.t("hp.power." + name)

    # ------------------------------------------------------------------ fan
    def fan_mode(self):
        if not self.caps["fan_max"]:
            return None
        return hw.FAN_MAX if self._max else hw.FAN_AUTO

    def _set_max(self, on):
        self._write("fan_max", CMD_GM, GM_FAN_MAX_SET, bytes([1 if on else 0, 0, 0, 0]))
        self._max = on
        self._max_at = time.monotonic()

    def set_fan_mode(self, mode):
        if mode == hw.FAN_CUSTOM:
            raise hw.Unsupported(ceviri.t("err.hpNoCurve"))
        if mode not in (hw.FAN_AUTO, hw.FAN_MAX):
            raise ValueError(ceviri.t("err.fanMode"))
        self._set_max(mode == hw.FAN_MAX)

    def fan_default(self):
        return None  # HP BIOS'u fan egrisi tasimaz

    def set_fan_curve(self, cpu, gpu):
        raise hw.Unsupported(ceviri.t("err.hpNoCurve"))

    def _clevo_only(self, *args, **kwargs):
        raise hw.Unsupported(ceviri.t("err.hpUnsupported"))

    set_wmi = set_data = write_app = _clevo_only

    # ------------------------------------------------------------------ klavye
    def set_color(self, r, g, b):
        """Tek renk tum bolgelere. (0,0,0) arka isigi kapatir. Desteklenmeyen modelde hicbir komut gitmez."""
        if not self.caps["kb"]:
            return 0
        col = (int(r) & 255, int(g) & 255, int(b) & 255)
        now = time.monotonic()
        if col == self._kb_sent and now - self._kb_at < 1.0:
            return 0
        if col != self._kb_sent and now - self._kb_at < KB_MIN_INTERVAL:
            return 0  # kare atlanir; motor son rengi en gec 1 sn icinde yeniden yollar
        self._kb_at = now
        if col == (0, 0, 0):
            if self._backlight is not False:
                self._write("kb", CMD_KB, KB_BACKLIGHT_SET, bytes([BACKLIGHT_OFF, 0, 0, 0]))
                self._backlight = False
            self._kb_sent = col
            return 0
        if self._backlight is not True:
            self._write("kb", CMD_KB, KB_BACKLIGHT_SET, bytes([BACKLIGHT_ON, 0, 0, 0]))
            self._backlight = True
        self.set_zones([col] * self.zones)
        self._kb_sent = col
        return 0

    def set_zones(self, colors):
        """Bolge renkleri (sag, orta, sol, WASD). Okunan tablonun diger baytlari korunur."""
        if not self.caps["kb"]:
            raise hw.Unsupported(ceviri.t("err.hpUnsupported"))
        table = bytearray(self.color_table)
        for i, (r, g, b) in enumerate(colors[:self.zones]):
            o = COLOR_OFFSET + 3 * i
            table[o:o + 3] = bytes([int(r) & 255, int(g) & 255, int(b) & 255])
        self._write("kb", CMD_KB, KB_COLOR_SET, bytes(table))
        self.color_table = table

    # ------------------------------------------------------------------ grafik modu
    def gpu_mode(self):
        return self.gpu_mode_now

    def set_gpu_mode(self, mode):
        """'hybrid' / 'discrete' / 'optimus'. Yeniden baslatinca gecerli olur. (Arayuzde henuz dugmesi yok.)"""
        codes = {v: k for k, v in GPU_MODES.items()}
        if mode not in codes:
            raise ValueError(mode)
        self._write("gpu_mux", CMD_WRITE, GPU_MUX, bytes([codes[mode], 0, 0, 0]))

    # ------------------------------------------------------------------ bilgi
    def describe(self):
        return {"model": self.info.get("model"), "family": self.family, "board": self.board,
                "thermal": self.thermal, "policy": self.policy, "fans": self.fan_count,
                "kbd_type": self.kbd_type, "zones": self.zones, "gpu_mode": self.gpu_mode_now,
                "timed": self.board in TIMED_BOARDS, "no_quiet": self.no_quiet}

    def close(self):
        self.bridge.close()


def open_backend(info=None, bridge_factory=PsBridge):
    """(arka uc ya da None, neden). HP Omen/Victus degilse (None, ""). HP ama BIOS WMI sinifi yoksa ya da
    ulasilamazsa (None, neden): cagiran NullDCHU'ya duser ve donanima komut gitmez."""
    info = info if info is not None else system_info()
    family = classify(info)
    if not family:
        return None, ""
    bridge = bridge_factory()
    try:
        return HpOmen(info, family, bridge), ""
    except Exception as exc:
        try:
            bridge.close()
        except Exception:
            pass
        return None, "%s: %s" % (type(exc).__name__, exc)
