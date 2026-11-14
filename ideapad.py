# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""Lenovo IdeaPad arka ucu (Intel ve Ryzen): guc modu, pil modu, sicaklik ve fan devri.

donanim.DCHU ile ayni ordek tipi arayuzu uygular (kind="ideapad"); motor, profiller ve klavye motoru farki bilmez.

IdeaPad'lerde iki ayri Lenovo arayuzu vardir; hangisinin bulundugu modele gore degisir ve ikisi de yalnizca
OKUYARAK sinanir:

  LENOVO_GAMEZONE_DATA (root\\WMI)  IdeaPad Gaming ve yeni IdeaPad Pro/Slim modellerinin cogu. Fn+Q ile ayni
           guc modu: IsSupportSmartFan (>0 destek), GetSmartFanMode / SetSmartFanMode(Data: 1 sessiz, 2 dengeli,
           3 performans; 224 ve 255 bazi modellerde). Okuma: GetCPUTemp, GetGPUTemp, GetFan1Speed, GetFan2Speed.
  \\\\.\\EnergyDrv  Lenovo Energy Management surucusu (Vantage ile gelir; IdeaPad Slim/Flex dahil hemen tum
           IdeaPad'ler). IOCTL 0x831020F8, giris/cikis uint32: okuma 0xFF; koruma modu ac 0x3 / kapat 0x5,
           hizli sarj ac 0x7 / kapat 0x8. Ayar denetleyicide kalicidir (yeniden baslatmada korunur).

Protokol bilgisi (kod degil, yalnizca sabitler) Lenovo Legion Toolkit (BartoszCichecki/LenovoLegionToolkit:
GameZone ve Battery ozellikleri) ve Linux ideapad-laptop / lenovo-wmi-gamezone suruculeriyle karsilastirildi.

Guvenlik kurallari:
  * Uretici LENOVO ve model adinda "IdeaPad" yoksa hicbir arayuz acilmaz (Legion / LOQ / ThinkPad / Yoga bu
    arka uca girmez).
  * Ozellik destek yontemi ve okuma yontemi basarili olmadan o ozellige HICBIR yazma komutu gitmez; yazma
    istegi donanim.Unsupported verir ve arayuz o denetimi gostermez.
  * Ozel fan egrisi yoktur: fanlari her zaman bellenim calistirir (FAN_AUTO yazmak bos islemdir).
  * Pil koruma ile hizli sarj ayni anda acik olamaz: once digeri kapatilir (Vantage ile ayni sira).
"""
import ctypes
import threading
from ctypes import wintypes as wt

import ceviri
import donanim as hw

GAMEZONE = "LENOVO_GAMEZONE_DATA"

L_QUIET, L_BALANCED, L_PERF, L_EXTREME, L_CUSTOM = 1, 2, 3, 224, 255
# Uygulamanin guc modlari Clevo kodlariyla tutulur (donanim.POWER_MODES): 0 sessiz, 1 tasarruf, 2 performans, 3 eglence
TO_LENOVO = {0: L_QUIET, 1: L_QUIET, 2: L_PERF, 3: L_BALANCED}
FROM_LENOVO = {L_QUIET: 0, L_BALANCED: 3, L_PERF: 2, L_EXTREME: 2, L_CUSTOM: 2}

BATTERY_MODES = ("normal", "conservation", "rapid")

SENSORS = (("cpu_temp", "GetCPUTemp"), ("gpu_temp", "GetGPUTemp"),
           ("cpu_rpm", "GetFan1Speed"), ("gpu_rpm", "GetFan2Speed"))


def _no():
    raise hw.Unsupported(ceviri.t("ideapad.unsupported"))


def _int(v):
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _plausible(key, v):
    """0 'soguk' degil 'okunamadi'dir: bekci bunu bilinmiyor sayar."""
    if v is None:
        return False
    if key.endswith("temp"):
        return 0 < v < 128
    return 0 <= v < 20000


# ============================================================================= tespit
def bios_info():
    """Kayit defterinden (WMI'siz, aninda) uretici ve model."""
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\BIOS")
    except (OSError, ImportError):
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


def model_name(info):
    """Lenovo'da SystemProductName makine tipidir (82KU); okunur ad SystemVersion / SystemFamily'de."""
    for k in ("SystemVersion", "SystemFamily", "SystemProductName"):
        v = (info.get(k) or "").strip()
        if "IDEAPAD" in v.upper():
            return v
    return ""


def is_ideapad(info):
    if (info.get("SystemManufacturer") or "").strip().upper() != "LENOVO":
        return False
    text = " ".join(info.get(k) or "" for k in ("SystemFamily", "SystemVersion", "SystemProductName")).upper()
    if "LEGION" in text or "LOQ" in text:
        return False  # GameZone'u ayni olsa da fan tablosu ve ozel mod farkli: bu arka uca girmez
    return "IDEAPAD" in text


# ============================================================================= pil (EnergyDrv)
class EnergyDrv:
    """Lenovo Energy Management surucusu. Aygit acilamaz ya da okuma basarisizsa available False ve hicbir
    yazma IOCTL'i gitmez. io: testte sahte islev (kod -> uint32)."""
    IOCTL = 0x831020F8
    READ = 0xFF

    def __init__(self, path=r"\\.\EnergyDrv", io=None):
        self.path = path
        self._io_fn = io
        self.available = False
        try:
            self.available = self.get() in BATTERY_MODES
        except Exception:
            self.available = False

    def _io(self, code):
        if self._io_fn is not None:
            return self._io_fn(code)
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
        """Surucu bayt sirasi ters dondurur. Bit 17 hizli sarj destegi/ayari etkin, 26 hizli sarj acik,
        29 koruma modu acik."""
        v = int.from_bytes(int(raw & 0xFFFFFFFF).to_bytes(4, "little"), "big")
        if v & (1 << 17):
            return "rapid" if v & (1 << 26) else "normal"
        return "conservation" if v & (1 << 29) else "normal"

    @staticmethod
    def sequence(cur, mode):
        """cur -> mode icin sirayla gonderilecek kodlar (ikisi ayni anda acik olamaz)."""
        if mode == cur:
            return []
        if mode == "conservation":
            return ([0x8] if cur == "rapid" else []) + [0x3]
        if mode == "rapid":
            return ([0x5] if cur == "conservation" else []) + [0x7]
        return [0x5 if cur == "conservation" else 0x8]

    def get(self):
        return self.decode(self._io(self.READ))

    def set(self, mode):
        if not self.available:
            _no()
        if mode not in BATTERY_MODES:
            raise ValueError(mode)
        for code in self.sequence(self.get(), mode):
            self._io(code)


# ============================================================================= GameZone (WMI)
class GameZone:
    """root\\WMI LENOVO_GAMEZONE_DATA'nin ilk ornegi. wmi: wmi_com.Wmi ya da testte ayni arayuzlu sahte nesne."""

    def __init__(self, wmi=None):
        if wmi is None:
            import wmi_com
            wmi = wmi_com.Wmi(r"root\WMI")
        self.wmi = wmi
        try:
            rows = wmi.query("SELECT __PATH FROM %s" % GAMEZONE)
            if not rows:
                raise OSError("%s ornegi yok" % GAMEZONE)
            self.path = rows[0]["__PATH"]
            self.methods = set(wmi.methods(GAMEZONE))
        except Exception:
            self.close()
            raise

    def call(self, method, args=None, out="Data"):
        if method not in self.methods:
            _no()
        return self.wmi.call(self.path, GAMEZONE, method, args or {}, out)

    def read(self, method):
        """Yalnizca okuma; basarisizsa None."""
        if method not in self.methods:
            return None
        try:
            return _int(self.call(method))
        except Exception:
            return None

    def close(self):
        try:
            self.wmi.close()
        except Exception:
            pass


# ============================================================================= arka uc
class IdeaPad:
    available = True
    kind = "ideapad"
    clevo = False
    reason = ""
    path = "Lenovo IdeaPad"
    fan_control = False  # ozel egri yok: fanlari bellenim calistirir
    kb_available = False

    def __init__(self, gamezone, energy, info=None):
        self.gz = gamezone
        self.energy = energy
        self.info = info or {}
        self.model = model_name(self.info)
        self.kb_reason = ceviri.t("ideapad.noKb")
        self.lock = threading.RLock()
        self.caps = {"power": False, "battery": bool(energy is not None and getattr(energy, "available", False))}
        self.sensors = []
        self._probe()
        self.ec_temps = any(k == "cpu_temp" for k, _ in self.sensors)  # yoksa sensorler ACPI isi bolgesini kullanir

    # ------------------------------------------------------------------ yetenek taramasi (yalnizca okuma)
    def _probe(self):
        gz = self.gz
        if gz is None:
            return
        if {"IsSupportSmartFan", "GetSmartFanMode", "SetSmartFanMode"} <= gz.methods \
                and (gz.read("IsSupportSmartFan") or 0) > 0:
            self.caps["power"] = gz.read("GetSmartFanMode") in FROM_LENOVO  # mod okunamiyorsa yazilmaz
        for key, method in SENSORS:
            if _plausible(key, gz.read(method)):
                self.sensors.append((key, method))

    # ------------------------------------------------------------------ Clevo'ya ozel komutlar
    def set_wmi(self, *args, **kwargs):
        _no()

    set_data = write_app = set_wmi

    # ------------------------------------------------------------------ olcumler
    def status(self):
        out = {}
        with self.lock:
            for key, method in self.sensors:
                v = self.gz.read(method)
                if _plausible(key, v):
                    out[key] = v
        return out

    def temps(self):
        s = self.status()
        return s.get("cpu_temp"), s.get("gpu_temp")

    # ------------------------------------------------------------------ guc modu
    def lenovo_mode(self):
        if not self.caps["power"]:
            return None
        with self.lock:
            return self.gz.read("GetSmartFanMode")

    def power_modes(self):
        return [0, 2, 3] if self.caps["power"] else []

    def power_mode(self):
        return FROM_LENOVO.get(self.lenovo_mode())

    def set_power_mode(self, mode):
        if mode not in hw.POWER_MODES:
            raise ValueError(ceviri.t("err.unknownPower"))
        if not self.caps["power"]:
            _no()
        target = TO_LENOVO[mode]
        with self.lock:
            if self.lenovo_mode() != target:
                self.gz.call("SetSmartFanMode", {"Data": target}, None)

    # ------------------------------------------------------------------ fan (bellenim)
    def fan_mode(self):
        return hw.FAN_AUTO

    def set_fan_mode(self, mode):
        if mode == hw.FAN_AUTO:
            return  # fanlar zaten bellenimde: komut gonderilmez
        _no()

    def set_fan_curve(self, cpu, gpu):
        _no()

    def fan_default(self):
        return None

    # ------------------------------------------------------------------ klavye
    def set_color(self, r, g, b):  # IdeaPad klavye isigi Fn+Bosluk ile; klavye motoru her karede cagirir
        return 0

    # ------------------------------------------------------------------ pil
    def battery_mode(self):
        if not self.caps["battery"]:
            return None
        try:
            with self.lock:
                return self.energy.get()
        except Exception:
            return None

    def set_battery_mode(self, mode):
        if mode not in BATTERY_MODES:
            raise ValueError(ceviri.t("ideapad.badValue"))
        if not self.caps["battery"]:
            _no()
        with self.lock:
            self.energy.set(mode)
            return self.energy.get()

    # ------------------------------------------------------------------ arayuz
    def features(self):
        return {
            "model": self.model,
            "power_modes": self.power_modes(),
            "fan_rpm": any(k.endswith("rpm") for k, _ in self.sensors),
            "battery": self.caps["battery"],
            "battery_mode": self.battery_mode(),
            "battery_modes": list(BATTERY_MODES),
        }

    def handle(self, body):
        """/api/ideapad istegi: {'battery': 'normal'|'conservation'|'rapid'}."""
        out = {}
        if "battery" in body:
            out["battery_mode"] = self.set_battery_mode(str(body["battery"]))
        out["ideapad"] = self.features()
        return out

    def shutdown(self):
        if self.gz is not None:
            self.gz.close()


def open_ideapad(info=None, wmi=None, energy=None):
    """IdeaPad ise IdeaPad arka ucu, degilse ya da hicbir Lenovo arayuzu yoksa None (donanim.open_dchu
    NullDCHU'ya duser). wmi/energy testte sahte nesnelerle verilir."""
    info = bios_info() if info is None else info
    if not is_ideapad(info):
        return None  # IdeaPad degil: WMI bile acilmaz
    try:
        gz = GameZone(wmi)
    except Exception:
        gz = None
    if energy is None:
        energy = EnergyDrv()
    dev = IdeaPad(gz, energy, info)
    if not dev.caps["power"] and not dev.caps["battery"] and not dev.sensors:
        dev.shutdown()
        return None
    return dev
