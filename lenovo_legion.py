# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""Lenovo Legion arka ucu: donanim.DCHU ile ayni arayuz (motor, profiller, sensorler ve arayuz degismeden calisir).

Tespit (open_legion): kayit defterindeki BIOS bilgisi (SystemManufacturer "LENOVO" + SystemFamily/SystemVersion/
SystemProductName icinde "Legion") ve root\\WMI altinda LENOVO_GAMEZONE_DATA sinifinin varligi. Biri yoksa
None: cagiran NullDCHU kullanir ve hicbir Lenovo komutu gitmez. Clevo/Monster'da bu modul hic cagrilmaz.

Protokol bilgisi (kod kopyalanmadi, yalnizca sinif/yontem adlari ve degerler) Lenovo Legion Toolkit
(BartoszCichecki/LenovoLegionToolkit) ve Linux legion-laptop surucusu (johnfanv2/LenovoLegionLinux) ile
dogrulandi:
  - LENOVO_GAMEZONE_DATA: IsSupportSmartFan (>0 destek), Get/SetSmartFanMode (Data: 1 sessiz, 2 dengeli,
    3 performans, 255 ozel; 224 'extreme' bazi modellerde), IsSupportGSync/Get/SetGSyncStatus (1 = yalnizca
    harici kart, yeniden baslatma ister), IsSupportIGPUMode/GetIGPUModeStatus (Data) / SetIGPUModeStatus (mode:
    0 hibrit, 1 yalnizca tumlesik, 2 otomatik), SetLightControlOwner (Data=1, klavye isigini uygulamaya verir).
  - Sicaklik/fan: LENOVO_FAN_METHOD Fan_GetCurrentSensorTemperature(SensorID 3 islemci, 4 kart) ->
    CurrentSensorTemperature, Fan_GetCurrentFanSpeed(FanID 0/1) -> CurrentFanSpeed; yeni modellerde
    LENOVO_OTHER_METHOD GetFeatureValue(IDs) -> Value; en son care GAMEZONE GetCPUTemp/GetGPUTemp/GetFan1Speed/
    GetFan2Speed. Hangisinin calistigi acilista yalnizca OKUYARAK denenir.
  - Tam devir: LENOVO_FAN_METHOD Fan_Get_FullSpeed (Status) / Fan_Set_FullSpeed(Status 0/1).
  - Fan tablosu: LENOVO_FAN_METHOD Fan_Set_Table(FanTable: 64 bayt; [0]=1, [1]=0, [2..5]=0, [6..25] on adet
    uint16 LE fan seviyesi 1..10). Sicaklik noktalari ve seviye basina devir LENOVO_FAN_TABLE_DATA'dan
    (SensorTable_Data, FanTable_Data). Tablo yalnizca OZEL (255) guc modunda gecerlidir; bu yuzden yalnizca
    makine zaten ozel moddayken yazilir, uygulama kendiliginden ozel moda gecmez.
  - Pil: \\\\.\\EnergyDrv, IOCTL 0x831020F8 (giris/cikis uint32). Okuma 0xFF; koruma 0x3, normal 0x5/0x8,
    hizli sarj 0x7.
"""
import ctypes
import threading
from ctypes import wintypes as wt

import ceviri
from donanim import FAN_AUTO, FAN_CUSTOM, FAN_MAX, Unsupported, validate_curve

GAMEZONE = "LENOVO_GAMEZONE_DATA"
FAN_METHOD = "LENOVO_FAN_METHOD"
FAN_TABLE = "LENOVO_FAN_TABLE_DATA"
OTHER = "LENOVO_OTHER_METHOD"

L_QUIET, L_BALANCED, L_PERF, L_EXTREME, L_CUSTOM = 1, 2, 3, 224, 255
# Uygulamanin guc modlari (donanim.POWER_MODES: 0 Sessiz, 1 Guc tasarrufu, 2 Performans, 3 Eglence) -> Lenovo
TO_LENOVO = {0: L_QUIET, 1: L_QUIET, 2: L_PERF, 3: L_BALANCED}
FROM_LENOVO = {L_QUIET: 0, L_BALANCED: 3, L_PERF: 2, L_EXTREME: 2, L_CUSTOM: 2}

IGPU_VALUE = {"hybrid": 0, "igpu": 1, "auto": 2}
BATTERY_MODES = ("normal", "conservation", "rapid")

# LLT'nin uyguladigi nokta basina en dusuk seviye; daha azi fani durdurabilir
MIN_LEVELS_V1 = (0, 0, 0, 0, 0, 0, 0, 1, 3, 5)
MIN_LEVELS_V2 = (1, 1, 1, 1, 1, 1, 1, 1, 3, 5)

OTHER_IDS = {"cpu_temp": 0x05040000, "gpu_temp": 0x05050000, "cpu_rpm": 0x04030001, "gpu_rpm": 0x04030002}


def _no(key="err.lenovoNo"):
    raise Unsupported(ceviri.t(key))


def _int(v):
    if isinstance(v, bool):
        return int(v)
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# ============================================================================= tespit
def bios_info():
    """Kayit defterinden (PowerShell'siz, aninda) uretici ve model."""
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\BIOS")
    except OSError:
        return {}
    out = {}
    try:
        for name in ("SystemManufacturer", "SystemProductName", "SystemFamily", "SystemVersion"):
            try:
                out[name] = str(winreg.QueryValueEx(key, name)[0]).strip()
            except OSError:
                out[name] = ""
    finally:
        winreg.CloseKey(key)
    return out


def is_legion(info):
    if (info.get("SystemManufacturer") or "").strip().upper() != "LENOVO":
        return False
    text = " ".join(info.get(k) or "" for k in ("SystemFamily", "SystemVersion", "SystemProductName"))
    return "LEGION" in text.upper()


def open_legion(info=None, wmi=None, kb=None, energy=None):
    """Legion ise LegionEC, degilse None. wmi/kb/energy testte sahte nesnelerle verilir."""
    info = bios_info() if info is None else info
    if not is_legion(info):
        return None  # Lenovo/Legion degil: PowerShell bile acilmaz
    if wmi is None:
        import lenovo_wmi
        wmi = lenovo_wmi.PsWmi()
    try:
        methods = set(wmi.class_methods(GAMEZONE))
    except Exception:
        methods = set()
    if not methods:
        try:
            wmi.close()
        except Exception:
            pass
        return None  # GameZone arayuzu yok: Lenovo'ya hicbir komut gitmez
    if kb is None:
        try:
            import lenovo_kb
            kb = lenovo_kb.find()
        except Exception:
            kb = None
    if energy is None:
        energy = EnergyDrv()
    return LegionEC(wmi, info, methods, kb, energy)


# ============================================================================= pil (EnergyDrv)
class EnergyDrv:
    """Lenovo Energy Management surucusu. Aygit yoksa available False ve baska hicbir IOCTL gitmez."""
    IOCTL = 0x831020F8

    def __init__(self, path=r"\\.\EnergyDrv"):
        self.path = path
        self.available = False
        try:
            self.available = self.get() in BATTERY_MODES
        except Exception:
            self.available = False

    def _io(self, code):
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateFileW.restype = ctypes.c_void_p
        k32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p, wt.DWORD, wt.DWORD,
                                    ctypes.c_void_p]
        k32.DeviceIoControl.argtypes = [ctypes.c_void_p, wt.DWORD, ctypes.c_void_p, wt.DWORD, ctypes.c_void_p,
                                        wt.DWORD, ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        h = k32.CreateFileW(self.path, 0xC0000000, 3, None, 3, 0, None)
        if not h or h == ctypes.c_void_p(-1).value:
            raise OSError(ctypes.get_last_error(), "EnergyDrv acilamadi")
        try:
            inp, out, n = wt.DWORD(code), wt.DWORD(0), wt.DWORD(0)
            if not k32.DeviceIoControl(h, self.IOCTL, ctypes.byref(inp), 4, ctypes.byref(out), 4,
                                       ctypes.byref(n), None):
                raise OSError(ctypes.get_last_error(), "EnergyDrv IOCTL")
            return out.value
        finally:
            k32.CloseHandle(h)

    @staticmethod
    def decode(raw):
        v = int.from_bytes(int(raw & 0xFFFFFFFF).to_bytes(4, "little"), "big")  # bayt sirasi ters
        if v & (1 << 17):
            return "rapid" if v & (1 << 26) else "normal"
        return "conservation" if v & (1 << 29) else "normal"

    @staticmethod
    def sequence(cur, mode):
        """cur -> mode icin sirayla gonderilecek kodlar."""
        if mode == cur:
            return []
        if mode == "conservation":
            return ([0x8] if cur == "rapid" else []) + [0x3]
        if mode == "rapid":
            return ([0x5] if cur == "conservation" else []) + [0x7]
        return [0x5 if cur == "conservation" else 0x8]

    def get(self):
        return self.decode(self._io(0xFF))

    def set(self, mode):
        if not self.available:
            _no()
        if mode not in BATTERY_MODES:
            raise ValueError(mode)
        for code in self.sequence(self.get(), mode):
            self._io(code)


# ============================================================================= fan tablosu
def build_table(levels):
    """10 seviyeyi Fan_Set_Table'in 64 baytlik FanTable'ina cevirir."""
    if len(levels) != 10 or any(not 0 <= int(x) <= 10 for x in levels):
        raise ValueError("fan tablosu 10 seviye (0..10) olmali")
    out = bytearray(64)
    out[0] = 1  # FSTM; FSID ve FSTL sifir
    for i, lv in enumerate(levels):
        out[6 + 2 * i] = int(lv) & 0xFF  # uint16 LE, ust bayt 0
    return list(out)


def interp(pts, x):
    """Parca parca dogrusal: pts [(T, D%)] artan T."""
    if x <= pts[0][0]:
        return pts[0][1]
    for (t0, d0), (t1, d1) in zip(pts, pts[1:]):
        if x <= t1:
            return d0 + (d1 - d0) * (x - t0) / float(t1 - t0) if t1 != t0 else d1
    return pts[-1][1]


def curve_levels(curve_pts, temps, rpms, minimum):
    """Egriyi (T, %) Lenovo noktalarina cevirir: her sicaklik noktasinda istenen devri karsilayan en dusuk
    seviye; nokta basina en az 'minimum', azalmayan sira, en fazla 10. Kullanilmayan nokta (>=127) 10."""
    top = max(rpms) or 1
    levels = []
    prev = 0
    for i, temp in enumerate(temps):
        if temp is None or temp >= 127:
            lv = 10
        else:
            want = interp(curve_pts, temp) / 100.0 * top
            lv = next((k + 1 for k, r in enumerate(rpms) if r >= want - 0.5), 10)
        lv = min(max(lv, minimum[i], prev), 10)
        levels.append(lv)
        prev = lv
    return levels


# ============================================================================= denetleyici
class LegionEC:
    """donanim.DCHU arayuzu. Desteklenmeyen her yazma Unsupported verir ve donanima komut GITMEZ."""
    available = True
    kind = "lenovo"
    clevo = False

    def __init__(self, wmi, info, gz_methods, kb=None, energy=None):
        self.wmi = wmi
        self.info = info
        self.gz = set(gz_methods)
        self.kbd = kb
        self.energy = energy
        self.lock = threading.RLock()
        self.reason = ""
        self.model = info.get("SystemVersion") or info.get("SystemFamily") or info.get("SystemProductName") or ""
        self.path = "Lenovo WMI (%s) %s" % (GAMEZONE, self.model)
        self.table = None
        self._custom = False       # fan tablosunu biz yazdik (ozel modda)
        self._owner = False        # SetLightControlOwner gonderildi
        self._fan_default = None
        self.caps = {}
        self._probe()
        self.kb_available = bool(kb is not None and getattr(kb, "available", False))
        self.kb_reason = "" if self.kb_available else (getattr(kb, "reason", "") or ceviri.t("unsup.kbLenovo"))

    # ------------------------------------------------------------------ yardimcilar
    def _gz(self, method, args=None, out="Data"):
        if method not in self.gz:
            _no()
        with self.lock:
            return self.wmi.call(GAMEZONE, method, args, out)

    def _try(self, cls, items):
        try:
            with self.lock:
                res = self.wmi.calls(cls, items)
            return res if len(res) == len(items) else [(False, "")] * len(items)
        except Exception:
            return [(False, "")] * len(items)

    def _support(self, method):
        if method not in self.gz:
            return 0
        ok, v = self._try(GAMEZONE, [(method, None, "Data")])[0]
        return (_int(v) or 0) if ok else 0

    # ------------------------------------------------------------------ yetenek taramasi (yalnizca okuma)
    def _probe(self):
        c = self.caps
        c["power"] = self._support("IsSupportSmartFan") > 0 and {"GetSmartFanMode", "SetSmartFanMode"} <= self.gz
        modes = {L_QUIET, L_BALANCED, L_PERF}
        ok, bits = self._try(OTHER, [("GetSupportThermalMode", None, "mode")])[0]
        bits = _int(bits) if ok else None
        if bits:
            modes = {m for b, m in ((0, L_QUIET), (1, L_BALANCED), (2, L_PERF), (16, L_CUSTOM)) if bits >> b & 1}
        c["power_modes"] = sorted(modes)
        c["gsync"] = self._support("IsSupportGSync") > 0 and {"GetGSyncStatus", "SetGSyncStatus"} <= self.gz
        c["igpu"] = self._support("IsSupportIGPUMode") > 0 and {"GetIGPUModeStatus", "SetIGPUModeStatus"} <= self.gz
        ok, _ = self._try(FAN_METHOD, [("Fan_Get_FullSpeed", None, "Status")])[0]
        c["fullspeed"] = bool(ok)
        c["sensor"] = self._probe_sensors()
        c["battery"] = bool(self.energy is not None and getattr(self.energy, "available", False))
        self._probe_table()

    def _probe_sensors(self):
        """Sicaklik/fan okuyucusunu sec: yalnizca okuma cagrilari; makul islemci sicakligi veren ilk yol."""
        for kind in ("other", "fan", "gz"):
            if "cpu_temp" in self._read(kind):
                return kind
        return ""

    def _read(self, kind):
        if kind == "other":
            keys = list(OTHER_IDS)
            res = self._try(OTHER, [("GetFeatureValue", {"IDs": OTHER_IDS[k]}, "Value") for k in keys])
        elif kind == "fan":
            keys = ["cpu_temp", "gpu_temp", "cpu_rpm", "gpu_rpm"]
            res = self._try(FAN_METHOD, [
                ("Fan_GetCurrentSensorTemperature", {"SensorID": 3}, "CurrentSensorTemperature"),
                ("Fan_GetCurrentSensorTemperature", {"SensorID": 4}, "CurrentSensorTemperature"),
                ("Fan_GetCurrentFanSpeed", {"FanID": 0}, "CurrentFanSpeed"),
                ("Fan_GetCurrentFanSpeed", {"FanID": 1}, "CurrentFanSpeed")])
        elif kind == "gz":
            pairs = [(k, m) for k, m in (("cpu_temp", "GetCPUTemp"), ("gpu_temp", "GetGPUTemp"),
                                         ("cpu_rpm", "GetFan1Speed"), ("gpu_rpm", "GetFan2Speed")) if m in self.gz]
            keys = [k for k, _ in pairs]
            res = self._try(GAMEZONE, [(m, None, "Data") for _, m in pairs]) if pairs else []
        else:
            return {}
        out = {}
        for k, (ok, v) in zip(keys, res):
            v = _int(v) if ok else None
            if v is None:
                continue
            if k.endswith("temp") and not 0 < v < 128:
                continue  # 0 'soguk' degil 'okunamadi'; bekci bunu bilinmiyor sayar
            if k.endswith("rpm") and not 0 <= v < 20000:
                continue
            out[k] = v
        return out

    def _probe_table(self):
        """Fan egrisi destegi: ozel mod + fan tablosu verisi + Fan_Set_Table. Biri eksikse egri yok."""
        self.caps["curve"] = False
        if not self.caps["power"] or L_CUSTOM not in self.caps["power_modes"]:
            return
        try:
            with self.lock:
                methods = set(self.wmi.class_methods(FAN_METHOD))
                rows = self.wmi.query(FAN_TABLE, ["Mode", "Fan_Id", "Sensor_ID", "FanTable_Data",
                                                  "SensorTable_Data", "CurrentFanMaxSpeed"])
        except Exception:
            return
        if "Fan_Set_Table" not in methods:
            return
        rows = [r for r in rows if isinstance(r.get("SensorTable_Data"), list)
                and isinstance(r.get("FanTable_Data"), list) and len(r["SensorTable_Data"]) == 10
                and len(r["FanTable_Data"]) == 10]
        custom = [r for r in rows if _int(r.get("Mode")) == L_CUSTOM]
        v2 = bool(custom)  # Mode ozelligi yalnizca ikinci nesil tablolarda var
        rows = custom or rows
        pick = None
        for fan, sensor in (((1, 4), (0, 3)) if v2 else ((0, 3), (1, 4))):  # islemci fani satiri
            pick = next((r for r in rows if _int(r.get("Fan_Id")) == fan and _int(r.get("Sensor_ID")) == sensor),
                        None)
            if pick:
                break
        if not pick:
            return
        temps = [_int(x) for x in pick["SensorTable_Data"]]
        rpms = [_int(x) or 0 for x in pick["FanTable_Data"]]
        if temps[0] is None or not 20 <= temps[0] < 127 or max(rpms) <= 0 \
                or any(b < a for a, b in zip(rpms, rpms[1:])):
            return
        self.table = {"temps": temps, "rpms": rpms, "min": MIN_LEVELS_V2 if v2 else MIN_LEVELS_V1,
                      "max_rpm": _int(pick.get("CurrentFanMaxSpeed")) or max(rpms)}
        self.caps["curve"] = True

    # ------------------------------------------------------------------ Clevo'ya ozgu ham komutlar: asla
    def set_wmi(self, *args, **kwargs):
        _no()

    set_data = write_app = read_app = get_buf = get_int = set_wmi

    # ------------------------------------------------------------------ klavye
    def set_color(self, r, g, b):
        """Motor her karede cagirir; klavye yoksa sessizce yok sayilir (komut gitmez)."""
        if not self.kb_available:
            return 0
        if not self._owner and "SetLightControlOwner" in self.gz:
            self._owner = True
            try:
                self._gz("SetLightControlOwner", {"Data": 1}, None)
            except Exception:
                pass
        return self.kbd.set_color(r, g, b)

    # ------------------------------------------------------------------ olcumler
    def status(self):
        kind = self.caps.get("sensor")
        if not kind:
            return {}
        s = self._read(kind)
        top = (self.table or {}).get("max_rpm")
        if top:
            for f in ("cpu", "gpu"):
                if f + "_rpm" in s:
                    s[f + "_duty"] = min(100, round(s[f + "_rpm"] * 100.0 / top))
        return s

    def temps(self):
        s = self.status()
        return s.get("cpu_temp", 0), s.get("gpu_temp", 0)

    # ------------------------------------------------------------------ guc modu
    def lenovo_mode(self):
        if not self.caps["power"]:
            return None
        try:
            return _int(self._gz("GetSmartFanMode"))
        except Exception:
            return None

    def power_mode(self):
        m = self.lenovo_mode()
        return FROM_LENOVO.get(m) if m is not None else None

    def set_power_mode(self, mode):
        if mode not in TO_LENOVO:
            raise ValueError(ceviri.t("err.unknownPower"))
        if not self.caps["power"]:
            _no()
        target = TO_LENOVO[mode]
        if target not in self.caps["power_modes"]:
            _no()
        if self.lenovo_mode() != target:
            self._gz("SetSmartFanMode", {"Data": target}, None)
            self._custom = False  # ozel moddan cikinca firmanin tablosu gecerli

    # ------------------------------------------------------------------ fan
    def _fullspeed(self):
        if not self.caps["fullspeed"]:
            return False
        ok, v = self._try(FAN_METHOD, [("Fan_Get_FullSpeed", None, "Status")])[0]
        return bool(ok and _int(v))

    def fan_mode(self):
        if self._fullspeed():
            return FAN_MAX
        return FAN_CUSTOM if self._custom else FAN_AUTO

    def set_fan_mode(self, mode):
        if mode == FAN_MAX:
            if not self.caps["fullspeed"]:
                _no()
            with self.lock:
                self.wmi.call(FAN_METHOD, "Fan_Set_FullSpeed", {"Status": 1}, None)
            return
        if mode != FAN_AUTO:
            raise ValueError(mode)
        if self._fullspeed():
            with self.lock:
                self.wmi.call(FAN_METHOD, "Fan_Set_FullSpeed", {"Status": 0}, None)
        if self._custom:
            # Firmanin varsayilan tablosu (seviye 1..10, en dusuk sinirlarla)
            levels = [max(i + 1, m) for i, m in enumerate(self.table["min"])]
            with self.lock:
                self.wmi.call(FAN_METHOD, "Fan_Set_Table", {"FanTable": build_table(levels)}, None)
            self._custom = False
        # Ikisi de degilse fanlar zaten firmada: gonderilecek komut yok

    def fan_default(self):
        """Arayuz/profil icin Clevo bicimi: {count, cpu: 4 nokta (T, %), gpu: ...}; egri yoksa None."""
        if not self.caps.get("curve"):
            return None
        if self._fan_default is None:
            tb = self.table
            top = max(tb["rpms"]) or 1
            used = [(t, tb["rpms"][i]) for i, t in enumerate(tb["temps"]) if t is not None and t < 100]
            idx = sorted({0, len(used) // 3, 2 * len(used) // 3})
            pts = [(used[i][0], round(used[i][1] * 100.0 / top)) for i in idx]
            while len(pts) < 3:
                pts.append((min(pts[-1][0] + 5, 99), min(pts[-1][1] + 5, 99)))
            pts = pts[:3] + [(100, 100)]
            self._fan_default = {"count": 2, "cpu": pts, "gpu": list(pts)}
        return self._fan_default

    def set_fan_curve(self, cpu, gpu):
        """Profil egrisi (T2, D2%, T3, D3%). Yalnizca destekli modelde ve makine OZEL moddayken yazilir;
        uygulama ozel moda kendisi gecmez (o mod guc sinirlarini da degistirir)."""
        if not self.caps.get("curve"):
            _no()
        if self.lenovo_mode() != L_CUSTOM:
            _no("err.lenovoCustomOnly")
        t1, d1 = self.fan_default()["cpu"][0]
        curves = []
        for pts in (cpu, gpu):
            t2, d2, t3, d3 = validate_curve(pts, t1, d1)
            curves.append([(t1, d1), (t2, d2), (t3, d3), (100, 100)])
        tb = self.table
        a = curve_levels(curves[0], tb["temps"], tb["rpms"], tb["min"])
        b = curve_levels(curves[1], tb["temps"], tb["rpms"], tb["min"])
        levels = [max(x, y) for x, y in zip(a, b)]  # tek tablo iki fani surer: daha cok sogutan kazanir
        with self.lock:
            self.wmi.call(FAN_METHOD, "Fan_Set_Table", {"FanTable": build_table(levels)}, None)
        self._custom = True
        return levels

    # ------------------------------------------------------------------ Lenovo'ya ozel: ekran karti, pil
    def gpu_options(self):
        opts = []
        if self.caps["igpu"]:
            opts += ["hybrid", "igpu", "auto"]
        elif self.caps["gsync"]:
            opts.append("hybrid")
        if self.caps["gsync"]:
            opts.append("dgpu")
        return opts

    def gpu_mode(self):
        try:
            if self.caps["gsync"] and _int(self._gz("GetGSyncStatus")) == 1:
                return "dgpu"
            if self.caps["igpu"]:
                return {0: "hybrid", 1: "igpu", 2: "auto"}.get(_int(self._gz("GetIGPUModeStatus")))
        except Exception:
            return None
        return "hybrid" if self.caps["gsync"] else None

    def set_gpu_mode(self, mode):
        """Donus: yeniden baslatma gerekiyor mu."""
        if mode not in self.gpu_options():
            _no()
        cur = self.gpu_mode()
        if mode == cur:
            return False
        if mode == "dgpu":
            self._gz("SetGSyncStatus", {"Data": 1}, None)
            return True
        reboot = False
        if cur == "dgpu":
            self._gz("SetGSyncStatus", {"Data": 0}, None)
            reboot = True
        if self.caps["igpu"]:
            self._gz("SetIGPUModeStatus", {"mode": IGPU_VALUE[mode]}, None)
        return reboot

    def battery_mode(self):
        if not self.caps["battery"]:
            return None
        try:
            return self.energy.get()
        except Exception:
            return None

    def set_battery_mode(self, mode):
        if not self.caps["battery"]:
            _no()
        if mode not in BATTERY_MODES:
            raise ValueError(mode)
        self.energy.set(mode)

    def extras(self):
        """Arayuze: yalnizca bu modelde olan Lenovo ozellikleri."""
        out = {"model": self.model, "power_raw": self.lenovo_mode(), "curve": bool(self.caps.get("curve")),
               "fullspeed": bool(self.caps.get("fullspeed"))}
        opts = self.gpu_options()
        if opts:
            out["gpu"] = {"value": self.gpu_mode(), "options": opts}
        if self.caps["battery"]:
            out["battery"] = {"value": self.battery_mode(), "options": list(BATTERY_MODES)}
        return out
