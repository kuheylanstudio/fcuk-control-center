# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""Acer Predator / Nitro donanim katmani: WMI 'AcerGamingFunction' (root\\wmi).

donanim.DCHU (Clevo/Monster) ile ayni yuzu sunar: status(), temps(), power_mode(), set_power_mode(),
fan_mode(), set_fan_mode(), set_color() ... Boylece profiller, sensorler ve klavye motoru degismeden calisir.

Protokol (kod kopyalanmadi; yalnizca protokol bilgisi) su kaynaklarla karsilastirildi:
  - Linux acer-wmi.c (predator_v4, torvalds/linux master)
  - JafarAkhondali/acer-predator-turbo-and-rgb-keyboard-linux-module (klavye)
  - aishend/predator-sense docs/REVERSE_ENGINEERING.md (PHN16-72 MOF'undaki yontem adlari ve tipleri)
  - rafradek/Acer-Predator-Scripts (Windows'ta yontemleri adla cagiran PowerShell betikleri)

Ortak kural: Get* yontemleri gmInput uint32 -> gmOutput uint64, Set* yontemleri gmInput uint64 -> gmOutput
uint32. Sonucun en dusuk bayti durum kodudur (0 = basarili), veri 8. bitten baslar. Parametre tipleri her
makinede sinif imzasindan okunur; bekledigimiz tipte olmayan yontem "yok" sayilir ve hic cagrilmaz.

  GetGamingSysInfo(0)                 desteklenen algilayicilar: 24-39. bitler, bit k -> algilayici k+1
  GetGamingSysInfo(1 | id<<8)         algilayici degeri: 8-23. bitler (C ya da rpm)
  Get/SetGamingMiscSetting            dizin 0-7. bit, deger 8-15. bit; 0x0B guc profili, 0x0A desteklenenler
  SetGamingFanBehavior                fan bit esleme 0-15 (islemci bit0, kart bit3), islemci kipi 16-17,
                                      kart kipi 22-23. bit; kip 1 otomatik, 2 en yuksek, 3 ozel
  GetGamingFanBehavior(esleme)        islemci kipi 8-9, kart kipi 14-15. bit
  Set/GetGamingFanSpeed               fan kimligi 0-7 (islemci 1, kart 4), yuzde 8-15. bit
  SetGamingRgbKb                      bolge maskesi 0-7 (bolge n: 1<<(n-1)), R 8-15, G 16-23, B 24-31
  SetGamingKBBacklight(uint8[16])     [efekt, hiz, parlaklik, 0, yon, R, G, B, 0, aygit=1, 0...]
                                      efekt 0 = sabit (bolge renkleri SetGamingRgbKb'den gelir)

Desteklenmeyen hicbir ozellik icin komut gonderilmez: acilista yalnizca OKUMA yontemleriyle yoklanir
(algilayici listesi, guc profili, fan kipi, 1. bolge rengi); yoklama basarisizsa ozellik kapali kalir ve
yazma yontemi Unsupported verir.
"""
import threading
import time

import ceviri
import donanim as hw

CLASS = "AcerGamingFunction"
NAMESPACE = r"root\wmi"

# yontem adlari
SYSINFO = "GetGamingSysInfo"
MISC_GET, MISC_SET = "GetGamingMiscSetting", "SetGamingMiscSetting"
FAN_GET, FAN_SET = "GetGamingFanBehavior", "SetGamingFanBehavior"
SPEED_GET, SPEED_SET = "GetGamingFanSpeed", "SetGamingFanSpeed"
RGB_GET, RGB_SET = "GetGamingRgbKb", "SetGamingRgbKb"
KBBL_SET = "SetGamingKBBacklight"

# guc profilleri (predator_v4)
QUIET, BALANCED, PERFORMANCE, TURBO, ECO = 0x00, 0x01, 0x04, 0x05, 0x06
PROFILE_NAMES = {QUIET: "quiet", BALANCED: "balanced", PERFORMANCE: "performance", TURBO: "turbo", ECO: "eco"}
NAME_TO_PROFILE = {v: k for k, v in PROFILE_NAMES.items()}
MISC_PROFILE, MISC_SUPPORTED = 0x0B, 0x0A
# Desteklenen-profil bit eslemesi bazi modellerde guvenilmez (Linux surucusu notu). Okunamazsa yalnizca
# her predator_v4 modelinde bulunan uc temel profil kullanilir; turbo ve eco yalnizca bit eslemesi soylerse.
SAFE_PROFILES = (QUIET, BALANCED, PERFORMANCE)
# istenen profil yoksa sirayla denenecek yakin profiller
FALLBACK = {TURBO: (TURBO, PERFORMANCE, BALANCED), PERFORMANCE: (PERFORMANCE, BALANCED),
            BALANCED: (BALANCED,), QUIET: (QUIET, ECO, BALANCED), ECO: (ECO, QUIET, BALANCED)}
# Clevo guc modu (profiller.py "ec" alani) -> Acer: 0 sessiz, 1 tasarruf, 2 performans, 3 eglence (dengeli)
FROM_CLEVO = {0: QUIET, 1: ECO, 2: PERFORMANCE, 3: BALANCED}
# Uygulamanin profilleri -> Acer guc profili (Ultra yalnizca fiste ve turbo destekliyse turbo)
BY_APP_PROFILE = {"tam_sessiz": QUIET, "sessiz_kullanim": BALANCED, "sessiz_oyun": BALANCED,
                  "performans": PERFORMANCE, "ultra": TURBO}

# algilayicilar
S_CPU_TEMP, S_CPU_FAN, S_GPU_FAN, S_GPU_TEMP = 0x01, 0x02, 0x06, 0x0A

# fanlar
FAN_BIT_CPU, FAN_BIT_GPU = 0x01, 0x08
FAN_ID_CPU, FAN_ID_GPU = 0x01, 0x04
FM_AUTO, FM_MAX, FM_CUSTOM = 1, 2, 3
FAN_CUSTOM_SPEED = 7  # uygulamanin fan kipi kodu: donanim.FAN_AUTO 0, FAN_MAX 1, FAN_CUSTOM (egri) 6
MIN_CUSTOM_PCT = 20   # elle hizda alt sinir: fan tamamen durdurulamaz

ZONES = 4
KB_MIN_INTERVAL = 0.1  # klavyeye en fazla 10 kare/sn (her kare 1-5 WMI cagrisi)
KB_MAX_FAILS = 5

CIM_UINT8_ARRAY = 0x2000 | 17
INT_TYPES = (17, 18, 19, 21, 3, 20, 2, 16)  # uint8/16/32/64, sint32/64/16/8


class AcerError(RuntimeError):
    """Yontem calisti ama durum kodu hata dondurdu."""

    def __init__(self, method, code):
        super().__init__(ceviri.t("err.acerStatus", method=method, code=code))
        self.method, self.code = method, code


# ----------------------------------------------------------------------------- tasima katmani
class WmiTransport:
    """AcerGamingFunction ornegine gercek WMI cagrilari (wmi_istemci). Testler bunun yerine sahte bir nesne verir."""

    def __init__(self, client, path):
        self.client = client
        self.path = path

    def params(self, method):
        """{parametre: CIM tipi}; yontem yoksa None."""
        if not self.client.has_method(CLASS, method):
            return None
        return self.client.in_params(CLASS, method)

    def invoke(self, method, args):
        return self.client.call(self.path, CLASS, method, args)


# ----------------------------------------------------------------------------- aygit
class AcerGaming:
    """Acer Predator/Nitro arka ucu. Her ozellik ayri yoklanir; caps hangilerinin acik oldugunu soyler."""
    vendor = kind = "acer"  # kurulum.ps1 ve /api/state ec_kind ile ayni anahtar
    clevo = False
    reason = ""
    fan_curve_ok = False  # Acer WMI'da sicakliga bagli egri yok: profiller egri yerine guc modunu kullanir

    def __init__(self, transport, model=""):
        self.t = transport
        self.model = model
        self.path = "WMI %s %s" % (NAMESPACE, CLASS)
        self.lock = threading.Lock()
        self._sig = {}
        self.sensors = set()
        self.profiles = []
        self.fan_ok = self.fan_speed_ok = self.kb_ok = self.power_ok = False
        self._custom = None       # elle fan hizi (islemci %, kart %) ya da None
        self._hot = 0
        self._kb_sent = None
        self._kb_at = 0.0
        self._kb_bright_at = -1e9
        self._kb_fails = 0
        self._kb_group = True     # ayni renkteki bolgeler tek cagrida (maske birlesimi); reddedilirse tek tek
        self.probe_log = []
        self._probe()

    # ------------------------------------------------------------------ ham cagrilar
    def _types(self, method):
        if method not in self._sig:
            try:
                self._sig[method] = self.t.params(method)
            except Exception as exc:
                self.probe_log.append("%s: %s" % (method, exc))
                self._sig[method] = None
        return self._sig[method]

    def _has_int(self, method):
        """Yontem var ve tek, tamsayi tipinde giris parametresi aliyor mu?"""
        p = self._types(method)
        return bool(p) and len(p) == 1 and next(iter(p.values())) in INT_TYPES

    def _has_bytes(self, method):
        p = self._types(method)
        return bool(p) and len(p) == 1 and next(iter(p.values())) == CIM_UINT8_ARRAY

    @staticmethod
    def _output(method, out):
        if "gmOutput" in out:
            v = out["gmOutput"]
        else:
            vals = [v for k, v in out.items() if k != "ReturnValue"]
            if len(vals) != 1:
                raise RuntimeError("%s: beklenmeyen cikti %r" % (method, sorted(out)))
            v = vals[0]
        if isinstance(v, (bytes, list)) or v is None:
            raise RuntimeError("%s: beklenmeyen cikti tipi" % method)
        return int(v)

    def _int(self, method, value):
        """Tamsayi girisli yontem; durum kodu 0 degilse AcerError. Ham ciktiyi dondurur."""
        if not self._has_int(method):
            raise hw.Unsupported(ceviri.t("err.acerNoMethod", method=method))
        name = next(iter(self._types(method)))
        with self.lock:
            out = self.t.invoke(method, {name: int(value)})
        v = self._output(method, out)
        if v & 0xFF:
            raise AcerError(method, v & 0xFF)
        return v

    def _bytes(self, method, data):
        if not self._has_bytes(method):
            raise hw.Unsupported(ceviri.t("err.acerNoMethod", method=method))
        name = next(iter(self._types(method)))
        with self.lock:
            out = self.t.invoke(method, {name: bytes(data)})
        v = self._output(method, out)
        if v & 0xFF:
            raise AcerError(method, v & 0xFF)
        return v

    def _try(self, what, fn):
        try:
            return fn()
        except Exception as exc:
            self.probe_log.append("%s: %s" % (what, exc))
            return None

    # ------------------------------------------------------------------ yoklama (yalnizca okuma)
    def _probe(self):
        v = self._try("sensors", lambda: self._int(SYSINFO, 0))
        if v is not None:
            bits = (v >> 24) & 0xFFFF
            self.sensors = {k + 1 for k in range(16) if bits >> k & 1}
        if self._try("profile", lambda: self._int(MISC_GET, MISC_PROFILE)) is not None and self._has_int(MISC_SET):
            self.power_ok = True
            v = self._try("profiles", lambda: self._int(MISC_GET, MISC_SUPPORTED))
            bits = (v >> 8) & 0xFF if v is not None else 0
            sup = [p for p in PROFILE_NAMES if bits >> p & 1]
            self.profiles = sup if (QUIET in sup or BALANCED in sup) else list(SAFE_PROFILES)
        if self._try("fan", lambda: self._int(FAN_GET, FAN_BIT_CPU | FAN_BIT_GPU)) is not None \
                and self._has_int(FAN_SET):
            self.fan_ok = True
            if self._try("speed", lambda: self._int(SPEED_GET, FAN_ID_CPU)) is not None and self._has_int(SPEED_SET):
                self.fan_speed_ok = True
        if self._has_int(RGB_SET) and self._has_bytes(KBBL_SET) \
                and self._try("kb", lambda: self._int(RGB_GET, 1)) is not None:
            self.kb_ok = True

    @property
    def available(self):
        return bool(self.power_ok or self.fan_ok or self.kb_ok or self.sensors)

    @property
    def kb_available(self):
        return self.kb_ok

    @property
    def temps_ok(self):
        return S_CPU_TEMP in self.sensors

    @property
    def caps(self):
        return {"power": self.power_ok, "power_modes": [PROFILE_NAMES[p] for p in self.profiles],
                "fan": self.fan_ok, "fan_speed": self.fan_speed_ok, "fan_curve": False,
                "kb": self.kb_ok, "kb_zones": ZONES if self.kb_ok else 0,
                "sensors": sorted(self.sensors), "model": self.model}

    # ------------------------------------------------------------------ olcumler
    def _sensor(self, sid):
        return (self._int(SYSINFO, 0x0001 | sid << 8) >> 8) & 0xFFFF

    def status(self):
        out = {}
        for key, sid in (("cpu_temp", S_CPU_TEMP), ("gpu_temp", S_GPU_TEMP),
                         ("cpu_rpm", S_CPU_FAN), ("gpu_rpm", S_GPU_FAN)):
            if sid in self.sensors:
                try:
                    out[key] = self._sensor(sid)
                except AcerError:
                    pass
        if self._custom:
            out["cpu_duty"], out["gpu_duty"] = self._custom
        return out

    def temps(self):
        s = self.status()
        return s.get("cpu_temp", 0), s.get("gpu_temp", 0)

    # ------------------------------------------------------------------ guc profili
    def power_mode(self):
        """Etkin Acer profili (ham deger) ya da None."""
        if not self.power_ok:
            return None
        try:
            return (self._int(MISC_GET, MISC_PROFILE) >> 8) & 0xFF
        except Exception:
            return None

    def power_name(self):
        return PROFILE_NAMES.get(self.power_mode())

    def resolve(self, want):
        """Istenen profil -> bu modelde desteklenen en yakin profil (ham) ya da None.
        want: Acer adi ("turbo"), ("acer", ham deger) ya da Clevo modu (0-3, profiller ve 'Fabrika' bunu verir)."""
        if isinstance(want, str):
            if want not in NAME_TO_PROFILE:
                raise ValueError(ceviri.t("err.unknownPower"))
            want = NAME_TO_PROFILE[want]
        elif isinstance(want, tuple):
            want = want[1]
        else:
            want = FROM_CLEVO.get(want, want)
        for p in FALLBACK.get(want, (want,)):
            if p in self.profiles:
                return p
        return None

    def set_power_mode(self, mode):
        if not self.power_ok:
            raise hw.Unsupported(ceviri.t("err.acerNoPower"))
        p = self.resolve(mode)
        if p is None:
            raise hw.Unsupported(ceviri.t("err.acerNoPower"))
        self._int(MISC_SET, MISC_PROFILE | p << 8)
        now = self.power_mode()
        if now is not None and now != p:
            raise RuntimeError(ceviri.t("err.acerVerify", want=self.power_label(p), got=self.power_label(now)))
        return PROFILE_NAMES[p]

    def power_label(self, p):
        return ceviri.t("acer.power." + PROFILE_NAMES.get(p, "balanced"))

    def profile_power(self, prof, on_ac=True):
        """Uygulama profili -> Acer profili (ham) ya da None. Turbo yalnizca fiste."""
        want = BY_APP_PROFILE.get(prof.get("id"), FROM_CLEVO.get(prof.get("ec"), BALANCED))
        if want == TURBO and not on_ac:
            want = PERFORMANCE
        return self.resolve(("acer", want))

    def profile_power_label(self, prof):
        p = self.profile_power(prof)
        return ceviri.t("val.unsupported") if (p is None or not self.power_ok) else self.power_label(p)

    def apply_profile_power(self, prof, on_ac=True):
        p = self.profile_power(prof, on_ac)
        if not self.power_ok or p is None:
            raise hw.Unsupported(ceviri.t("err.acerNoPower"))
        self.set_power_mode(("acer", p))
        return self.power_label(p)

    # ------------------------------------------------------------------ fan
    def fan_mode(self):
        if not self.fan_ok:
            return None
        try:
            v = self._int(FAN_GET, FAN_BIT_CPU | FAN_BIT_GPU)
        except Exception:
            return None
        cpu = (v >> 8) & 0x3
        return {FM_AUTO: hw.FAN_AUTO, FM_MAX: hw.FAN_MAX, FM_CUSTOM: FAN_CUSTOM_SPEED}.get(cpu)

    @staticmethod
    def behavior_word(cpu_mode, gpu_mode):
        return (FAN_BIT_CPU | FAN_BIT_GPU) | (cpu_mode & 3) << 16 | (gpu_mode & 3) << 22

    def set_fan_mode(self, mode):
        if not self.fan_ok:
            raise hw.Unsupported(ceviri.t("err.acerNoFan"))
        if mode == hw.FAN_AUTO:
            fm = FM_AUTO
        elif mode == hw.FAN_MAX:
            fm = FM_MAX
        else:
            raise hw.Unsupported(ceviri.t("err.acerNoCurve"))
        self._int(FAN_SET, self.behavior_word(fm, fm))
        self._custom = None
        self._hot = 0

    def set_fan_speed(self, cpu_pct, gpu_pct):
        """Elle fan hizi (%). Once iki fan 'ozel' kipe alinir, sonra hizlar yazilir."""
        if not self.fan_speed_ok:
            raise hw.Unsupported(ceviri.t("err.acerNoFan"))
        cpu = max(MIN_CUSTOM_PCT, min(100, int(cpu_pct)))
        gpu = max(MIN_CUSTOM_PCT, min(100, int(gpu_pct)))
        self._int(FAN_SET, self.behavior_word(FM_CUSTOM, FM_CUSTOM))
        try:
            self._int(SPEED_SET, FAN_ID_CPU | cpu << 8)
            self._int(SPEED_SET, FAN_ID_GPU | gpu << 8)
        except Exception:
            # Yarim kalan ayar fanlari bilinmeyen hizda birakmasin: otomatige don
            self._try("fan-rollback", lambda: self._int(FAN_SET, self.behavior_word(FM_AUTO, FM_AUTO)))
            raise
        self._custom = (cpu, gpu)
        self._hot = 0
        return cpu, gpu

    def fan_default(self):
        return None  # fabrika egrisi okunamaz (arayuz egri cizmez)

    def set_fan_curve(self, cpu, gpu):
        raise hw.Unsupported(ceviri.t("err.acerNoCurve"))

    def custom_guard(self, s):
        """Elle fan hizi acikken isi korumasi: islemci >= 93 C ya da kart >= 87 C (ya da sicaklik okunamiyor)
        5 olcum surerse otomatige doner. Sensorler her olcumde cagirir; uyari metni ya da None dondurur."""
        if not self._custom:
            return None
        cpu, gpu = s.get("cpu_temp"), s.get("gpu_temp") or 0
        if not isinstance(cpu, (int, float)) or cpu <= 0 or cpu >= 93 or gpu >= 87:
            self._hot += 1
        else:
            self._hot = 0
        if self._hot >= 5:
            try:
                self.set_fan_mode(hw.FAN_AUTO)
            except Exception:
                return None
            return ceviri.t("guard.acerHot")
        return None

    # ------------------------------------------------------------------ klavye
    def _kb_static(self, brightness=100):
        data = [0] * 16
        data[2] = max(0, min(100, int(brightness)))
        data[9] = 1  # aygit: klavye
        self._bytes(KBBL_SET, data)

    @staticmethod
    def rgb_word(mask, r, g, b):
        return (mask & 0xFF) | (int(r) & 255) << 8 | (int(g) & 255) << 16 | (int(b) & 255) << 24

    def _send_zones(self, cols):
        if self._kb_group:
            groups = {}
            for i, c in enumerate(cols):
                groups[c] = groups.get(c, 0) | 1 << i
            try:
                for c, mask in groups.items():
                    self._int(RGB_SET, self.rgb_word(mask, *c))
                return
            except AcerError:
                if all(bin(m).count("1") == 1 for m in groups.values()):
                    raise
                self._kb_group = False  # birlesik maske reddedildi: bundan sonra bolge bolge
        for i, c in enumerate(cols):
            self._int(RGB_SET, self.rgb_word(1 << i, *c))

    def set_zones(self, cols, force=False):
        """cols: 4 bolgenin (r, g, b) renkleri (soldan saga). Hiz sinirli; ayni renk tekrar gonderilmez,
        motor zaten saniyede bir yeniden ister."""
        if not self.kb_ok:
            return 0
        cols = tuple(tuple(max(0, min(255, int(round(x)))) for x in c) for c in list(cols)[:ZONES])
        if len(cols) < ZONES:
            cols = cols + (cols[-1] if cols else (0, 0, 0),) * (ZONES - len(cols))
        now = time.monotonic()
        if not force and now - self._kb_at < KB_MIN_INTERVAL:
            return 0
        if not force and cols == self._kb_sent and now - self._kb_at < 1.0:
            return 0
        self._kb_at = now
        try:
            if now - self._kb_bright_at > 10.0:  # sabit kip + tam parlaklik (Fn ile degistirilmis olabilir)
                self._kb_static(100)
                self._kb_bright_at = now
            self._send_zones(cols)
            self._kb_sent = cols
            self._kb_fails = 0
        except Exception:
            self._kb_fails += 1
            if self._kb_fails >= KB_MAX_FAILS:  # surekli hata: klavyeyi birak, her karede denenmesin
                self.kb_ok = False
            raise
        return 0

    def set_color(self, r, g, b):
        return self.set_zones([(r, g, b)] * ZONES)


# ----------------------------------------------------------------------------- tespit
def _text(v):
    return str(v or "").strip()


def identify(cimv2):
    """(uretici Acer mi, Predator/Nitro mu, model adi). cimv2: root\\cimv2'ye bagli istemci."""
    rows = cimv2.query("SELECT Manufacturer, Model, SystemFamily FROM Win32_ComputerSystem",
                       ["Manufacturer", "Model", "SystemFamily"])
    if not rows:
        return False, False, ""
    r = rows[0]
    maker, model, fam = _text(r.get("Manufacturer")), _text(r.get("Model")), _text(r.get("SystemFamily"))
    is_acer = "acer" in maker.lower()
    gaming = any(w in (model + " " + fam).lower() for w in ("predator", "nitro"))
    return is_acer, gaming, (fam + " " + model).strip() if fam and fam not in model else model


def detect(client_factory=None):
    """Acer Predator/Nitro ve AcerGamingFunction varsa AcerGaming, yoksa None. Hata da None: suphede dokunma."""
    try:
        if client_factory is None:
            import wmi_istemci
            client_factory = wmi_istemci.WmiClient
        cim = client_factory(r"root\cimv2")
        try:
            is_acer, gaming, model = identify(cim)
        finally:
            _close(cim)
        if not (is_acer and gaming):
            return None
        wmi = client_factory(NAMESPACE)
        dev = None
        try:
            if wmi.class_exists(CLASS):
                rows = wmi.query("SELECT * FROM " + CLASS, ["__PATH"])
                path = next((r["__PATH"] for r in rows if r.get("__PATH")), None)
                if path:
                    dev = AcerGaming(WmiTransport(wmi, path), model)
        finally:
            if dev is None or not dev.available:
                _close(wmi)
        return dev if dev is not None and dev.available else None
    except Exception:
        return None


def _close(client):
    try:
        client.close()
    except Exception:
        pass
