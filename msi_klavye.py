# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""MSI dizustu klavye isigi (USB HID): tum klavyeye tek renk. Parlaklik, rengin olceklenmesidir (klavye_rgb
motoru zaten olcekli renk gonderir). Ek surucu gerekmez: Windows'un kendi hid.dll'i.

Desteklenen aygitlar (protokoller acik kaynak projelerden: MSIKLM, msi-perkeyrgb, OpenRGB; donanimda
DOGRULANMADI):
  1770:FF00  eski 3 bolgeli SteelSeries/MSI EPF klavye. 8 baytlik ozellik raporu:
             [01 02 40 bolge R G B EC] bolge 1..7, ardindan kayit [01 02 41 01 00 00 00 EC] (normal mod)
  1038:1122  tus basina RGB (GE63/GS65 kusagi, msi-perkeyrgb): 4 bolge icin 524 baytlik ozellik raporu
             [0E 00 bolge 00] + 42 x [R G B 00x6 01 00 tus] + 14x00 08 39; ardindan cikis raporu [09 00..]
  1038:1122 (Raider A18) ve 1038:113A (GE68HX): OpenRGB MSILaptopController, 525 baytlik ozellik raporu
             [00 0C 00 66 00] + [tus R G B] kayitlari (kullanilmayan tus FF)
Ayni 1038:1122 kimligi iki farkli protokolle gelir: model adi Raider A18 ise yeni, degilse eski protokol.
Listede olmayan aygit (ya da rapor uzunlugu beklenene uymayan arayuz) desteklenmez: hicbir rapor gonderilmez.
"""
import ctypes
import threading
import time
from ctypes import wintypes as wt

# ----------------------------------------------------------------------------- protokoller (saf, test edilebilir)
ZONE3_REGIONS = (1, 2, 3, 4, 5, 6, 7)  # sol, orta, sag, logo, on sol, on sag, fare


def zone3_reports(r, g, b):
    """3 bolgeli klavye: [(tur, rapor bayt)]. Ilk bayt rapor kimligi (1)."""
    out = [("feature", bytes([0x01, 0x02, 0x40, reg, r & 255, g & 255, b & 255, 0xEC])) for reg in ZONE3_REGIONS]
    out.append(("feature", bytes([0x01, 0x02, 0x41, 0x01, 0, 0, 0, 0xEC])))
    return out


PERKEY_REGIONS = {  # bolge kimligi -> tus kodlari (USB HID kullanim kodlari)
    0x2A: list(range(4, 40)) + list(range(58, 64)),
    0x0B: [40, 49, 50, 100, 135, 136, 137, 138, 139, 144, 145],
    0x18: list(range(41, 49)) + list(range(51, 58)) + [101] + list(range(224, 231)) + [240],
    0x24: list(range(64, 100)),
}


def perkey_v1_reports(r, g, b):
    """Eski tus basina RGB (msi-perkeyrgb). Windows cercevesi: ilk bayt rapor kimligi 0."""
    out = []
    for region, keys in PERKEY_REGIONS.items():
        body = bytearray([0x0E, 0x00, region, 0x00])
        for i in range(42):
            if i < len(keys):
                body += bytes([r & 255, g & 255, b & 255, 0, 0, 0, 0, 0, 0, 0x01, 0x00, keys[i]])
            else:
                body += bytes(12)
        body += bytes(14) + bytes([0x08, 0x39])
        out.append(("feature", bytes([0x00]) + bytes(body)))
    out.append(("output", bytes([0x00, 0x09]) + bytes(63)))
    return out


PERKEY_V2_KEYS = list(range(0x04, 0x64)) + [0x64, 0x66] + list(range(0xE0, 0xE7)) + [0xF0]


def perkey_v2_reports(r, g, b):
    """Yeni tus basina RGB (OpenRGB MSILaptopController, klavye 'KLC')."""
    buf = bytearray(525)
    buf[1], buf[3] = 0x0C, 0x66
    i = 5
    for k in PERKEY_V2_KEYS:
        buf[i:i + 4] = bytes([k, r & 255, g & 255, b & 255])
        i += 4
    while i + 4 <= 525:
        buf[i] = 0xFF
        i += 4
    return [("feature", bytes(buf))]


# protokol -> (rapor uretici, beklenen ozellik raporu uzunlugu, iki gonderim arasi en az sn, ad)
PROTOCOLS = {
    "zone3": (zone3_reports, 8, 0.03, "MSI 3 bölgeli klavye"),
    "perkey1": (perkey_v1_reports, 525, 0.12, "SteelSeries tuş başına RGB"),
    "perkey2": (perkey_v2_reports, 525, 0.05, "SteelSeries tuş başına RGB"),
}


def pick_protocol(vid, pid, model=""):
    """Bilinen aygit icin protokol adi, yoksa None."""
    model = (model or "").lower()
    if (vid, pid) == (0x1770, 0xFF00):
        return "zone3"
    if (vid, pid) == (0x1038, 0x113A):
        return "perkey2"
    if (vid, pid) == (0x1038, 0x1122):
        return "perkey2" if "raider a18" in model else "perkey1"
    return None


class Keyboard:
    """Bir HID aygitina tek renk gonderir. dev: set_feature(bayt), write(bayt), close()."""
    ok = True

    def __init__(self, dev, protocol, name=""):
        self.dev = dev
        self.protocol = protocol
        fn, _, gap, label = PROTOCOLS[protocol]
        self.reports = fn
        self.gap = gap          # denetleyici cok hizli gelen komutlarda takiliyor (msi-perkeyrgb notu)
        self.name = name or label
        self.lock = threading.Lock()
        self._last = -1e9

    def set_color(self, r, g, b):
        now = time.monotonic()
        if now - self._last < self.gap:
            return 0  # motor rengi en gec 1 sn'de bir yeniden yollar: son renk kaybolmaz
        with self.lock:
            self._last = now
            for kind, data in self.reports(int(r), int(g), int(b)):
                if kind == "feature":
                    self.dev.set_feature(data)
                else:
                    self.dev.write(data)
                if self.protocol == "perkey1":
                    time.sleep(0.01)
        return 0

    def close(self):
        try:
            self.dev.close()
        except Exception:
            pass


# ----------------------------------------------------------------------------- Windows HID
class _GUID(ctypes.Structure):
    _fields_ = [("d1", ctypes.c_ulong), ("d2", ctypes.c_ushort), ("d3", ctypes.c_ushort), ("d4", ctypes.c_ubyte * 8)]


class _IFDATA(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("guid", _GUID), ("flags", wt.DWORD), ("res", ctypes.c_void_p)]


class _ATTR(ctypes.Structure):
    _fields_ = [("Size", wt.ULONG), ("VendorID", wt.USHORT), ("ProductID", wt.USHORT), ("Version", wt.USHORT)]


class _CAPS(ctypes.Structure):
    _fields_ = [("Usage", wt.USHORT), ("UsagePage", wt.USHORT), ("InputReportByteLength", wt.USHORT),
                ("OutputReportByteLength", wt.USHORT), ("FeatureReportByteLength", wt.USHORT),
                ("Reserved", wt.USHORT * 17), ("rest", wt.USHORT * 10)]


GENERIC_RW = 0x80000000 | 0x40000000
SHARE_RW = 0x1 | 0x2
OPEN_EXISTING = 3
INVALID = ctypes.c_void_p(-1).value


def _apis():
    hid = ctypes.WinDLL("hid", use_last_error=True)
    sapi = ctypes.WinDLL("setupapi", use_last_error=True)
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    sapi.SetupDiGetClassDevsW.restype = ctypes.c_void_p
    sapi.SetupDiGetClassDevsW.argtypes = [ctypes.c_void_p, wt.LPCWSTR, wt.HWND, wt.DWORD]
    sapi.SetupDiEnumDeviceInterfaces.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wt.DWORD,
                                                 ctypes.c_void_p]
    sapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wt.DWORD,
                                                      ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
    sapi.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]
    k32.CreateFileW.restype = ctypes.c_void_p
    k32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p, wt.DWORD, wt.DWORD, ctypes.c_void_p]
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    k32.WriteFile.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
    hid.HidD_GetHidGuid.argtypes = [ctypes.POINTER(_GUID)]
    hid.HidD_GetAttributes.argtypes = [ctypes.c_void_p, ctypes.POINTER(_ATTR)]
    hid.HidD_SetFeature.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wt.ULONG]
    hid.HidD_GetPreparsedData.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    hid.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
    hid.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.POINTER(_CAPS)]
    return hid, sapi, k32


def enumerate_hid(vids=(0x1770, 0x1038)):
    """[{vid, pid, path, feature_len, output_len}] (yalnizca istenen ureticiler; aygit erisimsiz acilir)."""
    hid, sapi, k32 = _apis()
    g = _GUID()
    hid.HidD_GetHidGuid(ctypes.byref(g))
    h = sapi.SetupDiGetClassDevsW(ctypes.byref(g), None, None, 0x2 | 0x10)  # PRESENT | DEVICEINTERFACE
    out = []
    if not h or h == INVALID:
        return out
    try:
        i = 0
        while True:
            d = _IFDATA()
            d.cbSize = ctypes.sizeof(d)
            if not sapi.SetupDiEnumDeviceInterfaces(h, None, ctypes.byref(g), i, ctypes.byref(d)):
                break
            i += 1
            need = wt.DWORD(0)
            sapi.SetupDiGetDeviceInterfaceDetailW(h, ctypes.byref(d), None, 0, ctypes.byref(need), None)
            if not need.value:
                continue
            buf = ctypes.create_string_buffer(need.value)
            ctypes.cast(buf, ctypes.POINTER(wt.DWORD))[0] = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
            if not sapi.SetupDiGetDeviceInterfaceDetailW(h, ctypes.byref(d), buf, need, None, None):
                continue
            path = ctypes.wstring_at(ctypes.addressof(buf) + 4)
            fh = k32.CreateFileW(path, 0, SHARE_RW, None, OPEN_EXISTING, 0, None)  # erisimsiz: yalnizca bilgi
            if not fh or fh == INVALID:
                continue
            try:
                a = _ATTR()
                a.Size = ctypes.sizeof(a)
                if not hid.HidD_GetAttributes(fh, ctypes.byref(a)) or a.VendorID not in vids:
                    continue
                caps = _CAPS()
                pp = ctypes.c_void_p()
                if hid.HidD_GetPreparsedData(fh, ctypes.byref(pp)):
                    try:
                        hid.HidP_GetCaps(pp, ctypes.byref(caps))
                    finally:
                        hid.HidD_FreePreparsedData(pp)
                out.append({"vid": a.VendorID, "pid": a.ProductID, "path": path,
                            "feature_len": caps.FeatureReportByteLength, "output_len": caps.OutputReportByteLength})
            finally:
                k32.CloseHandle(fh)
    finally:
        sapi.SetupDiDestroyDeviceInfoList(h)
    return out


class HidDevice:
    def __init__(self, path):
        self.hid, _, self.k32 = _apis()
        self.h = self.k32.CreateFileW(path, GENERIC_RW, SHARE_RW, None, OPEN_EXISTING, 0, None)
        if not self.h or self.h == INVALID:
            raise OSError("HID aygıtı açılamadı (%d)" % ctypes.get_last_error())

    def set_feature(self, data):
        b = ctypes.create_string_buffer(bytes(data), len(data))
        if not self.hid.HidD_SetFeature(self.h, b, len(data)):
            raise OSError("HidD_SetFeature başarısız (%d)" % ctypes.get_last_error())

    def write(self, data):
        b = ctypes.create_string_buffer(bytes(data), len(data))
        n = wt.DWORD()
        if not self.k32.WriteFile(self.h, b, len(data), ctypes.byref(n), None):
            raise OSError("WriteFile başarısız (%d)" % ctypes.get_last_error())

    def close(self):
        if self.h:
            self.k32.CloseHandle(self.h)
            self.h = None


def model_name():
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\BIOS")
        try:
            return str(winreg.QueryValueEx(k, "SystemProductName")[0])
        finally:
            winreg.CloseKey(k)
    except OSError:
        return ""


def choose(devices, model=""):
    """Aygit listesinden (enumerate_hid bicimi) kullanilacak (aygit, protokol) ya da None.
    Rapor uzunlugu protokolun bekledigine uymayan arayuz secilmez (yanlis arayuze rapor gitmez)."""
    for d in devices:
        proto = pick_protocol(d["vid"], d["pid"], model)
        if proto and d.get("feature_len") == PROTOCOLS[proto][1]:
            if proto == "perkey1" and d.get("output_len", 0) < 65:
                continue
            return d, proto
    return None


def open_keyboard(enum=enumerate_hid, opener=HidDevice, model=None):
    """Desteklenen bir MSI klavyesi varsa Keyboard, yoksa None."""
    pick = choose(enum(), model_name() if model is None else model)
    if not pick:
        return None
    d, proto = pick
    try:
        return Keyboard(opener(d["path"]), proto)
    except OSError:
        return None
