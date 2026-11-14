# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""USB HID aygitlarina ozellik raporu (feature report) gonderme, ek paket olmadan (hid.dll + setupapi).

Yalnizca VID/PID VE kullanim sayfasi/ozellik raporu uzunlugu bilinen bir arayuz acilir; klavyenin tus
arayuzu (Windows'un kendine ayirdigi) zaten acilamaz, ona hicbir sey yazilmaz.
"""
import ctypes
from ctypes import wintypes as wt

c_void_p = ctypes.c_void_p
INVALID_HANDLE = c_void_p(-1).value


class _GUID(ctypes.Structure):
    _fields_ = [("d1", ctypes.c_ulong), ("d2", ctypes.c_ushort), ("d3", ctypes.c_ushort), ("d4", ctypes.c_ubyte * 8)]


class _Attr(ctypes.Structure):  # HIDD_ATTRIBUTES
    _fields_ = [("Size", wt.ULONG), ("VendorID", wt.USHORT), ("ProductID", wt.USHORT), ("Version", wt.USHORT)]


class _Caps(ctypes.Structure):  # HIDP_CAPS
    _fields_ = [("Usage", wt.USHORT), ("UsagePage", wt.USHORT), ("InputReportByteLength", wt.USHORT),
                ("OutputReportByteLength", wt.USHORT), ("FeatureReportByteLength", wt.USHORT),
                ("Reserved", wt.USHORT * 17), ("rest", wt.USHORT * 10)]


class _IfData(ctypes.Structure):  # SP_DEVICE_INTERFACE_DATA
    _fields_ = [("cbSize", wt.DWORD), ("guid", _GUID), ("flags", wt.DWORD), ("res", c_void_p)]


def _libs():
    hid = ctypes.WinDLL("hid")
    sapi = ctypes.WinDLL("setupapi", use_last_error=True)
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    sapi.SetupDiGetClassDevsW.argtypes = [c_void_p, wt.LPCWSTR, wt.HWND, wt.DWORD]
    sapi.SetupDiGetClassDevsW.restype = c_void_p
    sapi.SetupDiEnumDeviceInterfaces.argtypes = [c_void_p, c_void_p, c_void_p, wt.DWORD, c_void_p]
    sapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [c_void_p, c_void_p, c_void_p, wt.DWORD, c_void_p, c_void_p]
    sapi.SetupDiDestroyDeviceInfoList.argtypes = [c_void_p]
    k32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, c_void_p, wt.DWORD, wt.DWORD, c_void_p]
    k32.CreateFileW.restype = c_void_p
    k32.CloseHandle.argtypes = [c_void_p]
    hid.HidD_GetHidGuid.argtypes = [c_void_p]
    hid.HidD_GetAttributes.argtypes = [c_void_p, c_void_p]
    hid.HidD_GetPreparsedData.argtypes = [c_void_p, c_void_p]
    hid.HidD_FreePreparsedData.argtypes = [c_void_p]
    hid.HidP_GetCaps.argtypes = [c_void_p, c_void_p]
    hid.HidP_GetCaps.restype = ctypes.c_long
    hid.HidD_SetFeature.argtypes = [c_void_p, c_void_p, wt.ULONG]
    hid.HidD_GetFeature.argtypes = [c_void_p, c_void_p, wt.ULONG]
    return hid, sapi, k32


def device_paths():
    """Takili tum HID arayuzlerinin yollari."""
    hid, sapi, _ = _libs()
    g = _GUID()
    hid.HidD_GetHidGuid(ctypes.byref(g))
    h = sapi.SetupDiGetClassDevsW(ctypes.byref(g), None, None, 0x2 | 0x10)  # PRESENT | DEVICEINTERFACE
    if not h or h == INVALID_HANDLE:
        return []
    out = []
    try:
        i = 0
        while True:
            d = _IfData()
            d.cbSize = ctypes.sizeof(d)
            if not sapi.SetupDiEnumDeviceInterfaces(h, None, ctypes.byref(g), i, ctypes.byref(d)):
                break
            i += 1
            need = wt.DWORD(0)
            sapi.SetupDiGetDeviceInterfaceDetailW(h, ctypes.byref(d), None, 0, ctypes.byref(need), None)
            if not need.value:
                continue
            buf = ctypes.create_string_buffer(need.value)
            # SP_DEVICE_INTERFACE_DETAIL_DATA_W.cbSize: 8 (64 bit), 6 (32 bit)
            ctypes.cast(buf, ctypes.POINTER(wt.DWORD))[0] = 8 if ctypes.sizeof(c_void_p) == 8 else 6
            if sapi.SetupDiGetDeviceInterfaceDetailW(h, ctypes.byref(d), buf, need, None, None):
                out.append(ctypes.wstring_at(ctypes.addressof(buf) + 4))
    finally:
        sapi.SetupDiDestroyDeviceInfoList(h)
    return out


class HidDevice:
    """Acik bir HID arayuzu: vid, pid, usage_page, usage, feature_len."""

    def __init__(self, path):
        self.hid, _, self.k32 = _libs()
        self.path = path
        # Erisim 0 ile acilir (yalnizca oznitelik okumak icin); yazmak icin open_rw()
        self.h = self.k32.CreateFileW(path, 0, 3, None, 3, 0, None)  # FILE_SHARE_READ|WRITE, OPEN_EXISTING
        if not self.h or self.h == INVALID_HANDLE:
            raise OSError("HID acilamadi")
        a = _Attr()
        a.Size = ctypes.sizeof(a)
        self.hid.HidD_GetAttributes(self.h, ctypes.byref(a))
        self.vid, self.pid = a.VendorID, a.ProductID
        self.usage_page = self.usage = self.feature_len = 0
        pp = c_void_p()
        if self.hid.HidD_GetPreparsedData(self.h, ctypes.byref(pp)):
            try:
                c = _Caps()
                if self.hid.HidP_GetCaps(pp, ctypes.byref(c)) & 0xFFFFFFFF == 0x00110000:  # HIDP_STATUS_SUCCESS
                    self.usage_page, self.usage = c.UsagePage, c.Usage
                    self.feature_len = c.FeatureReportByteLength
            finally:
                self.hid.HidD_FreePreparsedData(pp)

    def open_rw(self):
        h = self.k32.CreateFileW(self.path, 0xC0000000, 3, None, 3, 0, None)  # GENERIC_READ|WRITE
        if not h or h == INVALID_HANDLE:
            raise OSError("HID yazmaya acilamadi (hata %d)" % ctypes.get_last_error())
        self.k32.CloseHandle(self.h)
        self.h = h

    def set_feature(self, data):
        """data[0] rapor kimligi. Basarisizsa OSError."""
        b = (ctypes.c_ubyte * len(data))(*data)
        if not self.hid.HidD_SetFeature(self.h, b, len(data)):
            raise OSError("HidD_SetFeature basarisiz (hata %d)" % ctypes.get_last_error())

    def get_feature(self, report_id, n):
        b = (ctypes.c_ubyte * n)()
        b[0] = report_id
        if not self.hid.HidD_GetFeature(self.h, b, n):
            raise OSError("HidD_GetFeature basarisiz (hata %d)" % ctypes.get_last_error())
        return bytes(b)

    def close(self):
        if self.h and self.h != INVALID_HANDLE:
            self.k32.CloseHandle(self.h)
            self.h = None


def find(match):
    """match(vid, pid, usage_page, usage, feature_len) True olan ilk arayuz (acik) ya da None."""
    for p in device_paths():
        try:
            d = HidDevice(p)
        except OSError:
            continue
        if match(d.vid, d.pid, d.usage_page, d.usage, d.feature_len):
            return d
        d.close()
    return None


def list_devices():
    """[(vid, pid, usage_page, usage, feature_len)] tanilama icin."""
    out = []
    for p in device_paths():
        try:
            d = HidDevice(p)
        except OSError:
            continue
        out.append((d.vid, d.pid, d.usage_page, d.usage, d.feature_len))
        d.close()
    return out
