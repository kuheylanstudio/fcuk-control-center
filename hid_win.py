# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""Ek paket gerektirmeyen USB HID erisimi (Windows hid.dll + setupapi, ctypes).

Alienware klavye isigi (AlienFX) bir HID aygitidir; renk komutlari HID raporlariyla (ozellik ya da cikis
raporu) gonderilir. Bu modul yalnizca aygit bulma, acma ve rapor gonderme/okuma yapar; protokol alienware.py'de.
"""
import ctypes
from ctypes import wintypes as wt

c_void_p = ctypes.c_void_p
INVALID = c_void_p(-1).value

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_sapi = ctypes.WinDLL("setupapi", use_last_error=True)
_hid = ctypes.WinDLL("hid", use_last_error=True)

_k32.CreateFileW.restype = c_void_p
_k32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, c_void_p, wt.DWORD, wt.DWORD, c_void_p]
_k32.CloseHandle.argtypes = [c_void_p]
_k32.WriteFile.argtypes = [c_void_p, c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD), c_void_p]
_sapi.SetupDiGetClassDevsW.restype = c_void_p
_sapi.SetupDiGetClassDevsW.argtypes = [c_void_p, wt.LPCWSTR, wt.HWND, wt.DWORD]
_sapi.SetupDiEnumDeviceInterfaces.argtypes = [c_void_p, c_void_p, c_void_p, wt.DWORD, c_void_p]
_sapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [c_void_p, c_void_p, c_void_p, wt.DWORD,
                                                    ctypes.POINTER(wt.DWORD), c_void_p]
_sapi.SetupDiDestroyDeviceInfoList.argtypes = [c_void_p]
_hid.HidD_GetHidGuid.argtypes = [c_void_p]
_hid.HidD_GetAttributes.argtypes = [c_void_p, c_void_p]
_hid.HidD_GetPreparsedData.argtypes = [c_void_p, ctypes.POINTER(c_void_p)]
_hid.HidD_FreePreparsedData.argtypes = [c_void_p]
_hid.HidP_GetCaps.argtypes = [c_void_p, c_void_p]
_hid.HidP_GetCaps.restype = ctypes.c_ulong
_hid.HidD_SetFeature.argtypes = [c_void_p, c_void_p, wt.ULONG]
_hid.HidD_GetFeature.argtypes = [c_void_p, c_void_p, wt.ULONG]
_hid.HidD_SetOutputReport.argtypes = [c_void_p, c_void_p, wt.ULONG]


class _GUID(ctypes.Structure):
    _fields_ = [("d1", ctypes.c_ulong), ("d2", ctypes.c_ushort), ("d3", ctypes.c_ushort), ("d4", ctypes.c_ubyte * 8)]


class _IFDATA(ctypes.Structure):  # SP_DEVICE_INTERFACE_DATA
    _fields_ = [("cbSize", wt.DWORD), ("guid", _GUID), ("flags", wt.DWORD), ("res", c_void_p)]


class _ATTR(ctypes.Structure):  # HIDD_ATTRIBUTES
    _fields_ = [("Size", wt.ULONG), ("VendorID", wt.USHORT), ("ProductID", wt.USHORT), ("Version", wt.USHORT)]


class _CAPS(ctypes.Structure):  # HIDP_CAPS
    _fields_ = [("Usage", wt.USHORT), ("UsagePage", wt.USHORT), ("InputReportByteLength", wt.USHORT),
                ("OutputReportByteLength", wt.USHORT), ("FeatureReportByteLength", wt.USHORT),
                ("Reserved", wt.USHORT * 17), ("Counts", wt.USHORT * 10)]


def _open(path, access):
    return _k32.CreateFileW(path, access, 3, None, 3, 0, None)  # FILE_SHARE_READ|WRITE, OPEN_EXISTING


def enumerate_devices(vids=None):
    """[{path, vid, pid, version, usage_page, usage, in_len, out_len, feat_len}] (vids verilirse yalnizca onlar)."""
    g = _GUID()
    _hid.HidD_GetHidGuid(ctypes.byref(g))
    h = _sapi.SetupDiGetClassDevsW(ctypes.byref(g), None, None, 0x12)  # DIGCF_PRESENT | DIGCF_DEVICEINTERFACE
    out = []
    if not h or h == INVALID:
        return out
    try:
        i = 0
        while True:
            ifd = _IFDATA()
            ifd.cbSize = ctypes.sizeof(ifd)
            if not _sapi.SetupDiEnumDeviceInterfaces(h, None, ctypes.byref(g), i, ctypes.byref(ifd)):
                break
            i += 1
            need = wt.DWORD()
            _sapi.SetupDiGetDeviceInterfaceDetailW(h, ctypes.byref(ifd), None, 0, ctypes.byref(need), None)
            buf = ctypes.create_string_buffer(need.value + 8)
            ctypes.cast(buf, ctypes.POINTER(wt.DWORD))[0] = 8 if ctypes.sizeof(c_void_p) == 8 else 6
            if not _sapi.SetupDiGetDeviceInterfaceDetailW(h, ctypes.byref(ifd), buf, need, None, None):
                continue
            path = ctypes.wstring_at(ctypes.addressof(buf) + 4)
            dev = _open(path, 0)  # erisim istemeden: klavye gibi ozel aygitlarin da ozellikleri okunur
            if not dev or dev == INVALID:
                continue
            try:
                a = _ATTR()
                a.Size = ctypes.sizeof(a)
                if not _hid.HidD_GetAttributes(dev, ctypes.byref(a)):
                    continue
                if vids and a.VendorID not in vids:
                    continue
                info = {"path": path, "vid": a.VendorID, "pid": a.ProductID, "version": a.Version}
                pp = c_void_p()
                if _hid.HidD_GetPreparsedData(dev, ctypes.byref(pp)):
                    c = _CAPS()
                    if _hid.HidP_GetCaps(pp, ctypes.byref(c)) == 0x00110000:  # HIDP_STATUS_SUCCESS
                        info.update(usage_page=c.UsagePage, usage=c.Usage, in_len=c.InputReportByteLength,
                                    out_len=c.OutputReportByteLength, feat_len=c.FeatureReportByteLength)
                    _hid.HidD_FreePreparsedData(pp)
                out.append(info)
            finally:
                _k32.CloseHandle(dev)
    finally:
        _sapi.SetupDiDestroyDeviceInfoList(h)
    return out


class HidDevice:
    def __init__(self, info):
        self.info = info
        self.h = _open(info["path"], 0xC0000000)  # GENERIC_READ | GENERIC_WRITE
        if not self.h or self.h == INVALID:
            raise OSError(ctypes.get_last_error(), "HID aygiti acilamadi")

    def close(self):
        if self.h and self.h != INVALID:
            _k32.CloseHandle(self.h)
        self.h = None

    @staticmethod
    def _buf(data, length):
        b = (ctypes.c_ubyte * max(length, len(data)))()
        for i, x in enumerate(data):
            b[i] = x & 0xFF
        return b

    def set_feature(self, data, length=None):
        """data[0] rapor kimligidir. length: aygitin ozellik raporu boyu (sifirla doldurulur)."""
        b = self._buf(data, length or self.info.get("feat_len") or len(data))
        if not _hid.HidD_SetFeature(self.h, b, len(b)):
            raise OSError(ctypes.get_last_error(), "HidD_SetFeature")

    def get_feature(self, report_id=0, length=None):
        b = self._buf([report_id], length or self.info.get("feat_len") or 65)
        if not _hid.HidD_GetFeature(self.h, b, len(b)):
            raise OSError(ctypes.get_last_error(), "HidD_GetFeature")
        return bytes(b)

    def write(self, data, length=None):
        """Cikis raporu (WriteFile). data[0] rapor kimligidir."""
        b = self._buf(data, length or self.info.get("out_len") or len(data))
        n = wt.DWORD()
        if not _k32.WriteFile(self.h, b, len(b), ctypes.byref(n), None):
            raise OSError(ctypes.get_last_error(), "WriteFile")
        return n.value
