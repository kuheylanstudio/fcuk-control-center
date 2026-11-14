# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""Lenovo Legion klavye isigi (ITE denetleyici, USB HID). Ek paket gerektirmez (hid.dll + setupapi, ctypes).

Aygit: VID 0x048D, PID 0xC9xx (2020 C955, 2021 C965/C963, 2022 C975/C973, 2023 C984/C985/C983, 2024 C994/C995/
C993 ...). Ayni PID ailesinde iki tur vardir; ayrim ozellik raporu uzunluguyla yapilir (Lenovo Legion Toolkit
ile ayni yontem):
  - 33 bayt: 4 bolgeli RGB. Rapor: [0]=0xCC (rapor kimligi), [1]=0x16, [2]=efekt (1 sabit), [3]=hiz 1..4,
    [4]=parlaklik (1 dusuk, 2 yuksek), [5..16]=4 bolge x (R,G,B), [17]=0, [18]=1, [19]=1, gerisi 0.
  - 960 bayt: tus basina RGB (Spectrum). Tum tuslari tek renge boyamanin belgelenmis tek bir komutu yok
    (tus kodlariyla efekt profili yazmak gerekir); bu yuzden Spectrum'da isik ozelligi gizlenir ve
    klavyeye HICBIR rapor gonderilmez.
Protokol bilgisi Lenovo Legion Toolkit ve 4JX/L5P-Keyboard-RGB ile dogrulandi; kod kopyalanmadi.
"""
import ctypes
import threading
from ctypes import wintypes as wt

import ceviri

VID = 0x048D
PID_FAMILY = 0xC900
LEN_4ZONE = 33
LEN_SPECTRUM = 960
c_void_p = ctypes.c_void_p


def report_4zone(r, g, b, brightness=2):
    """Dort bolgeyi ayni renge boyayan 33 baytlik ozellik raporu."""
    rep = bytearray(LEN_4ZONE)
    rep[0], rep[1], rep[2], rep[3], rep[4] = 0xCC, 0x16, 0x01, 0x01, brightness
    for z in range(4):
        rep[5 + 3 * z:8 + 3 * z] = bytes((int(r) & 255, int(g) & 255, int(b) & 255))
    rep[18] = rep[19] = 1
    return bytes(rep)


def classify(vid, pid, feature_len):
    """'4zone' | 'spectrum' | None"""
    if vid != VID or (pid & 0xFF00) != PID_FAMILY:
        return None
    return {LEN_4ZONE: "4zone", LEN_SPECTRUM: "spectrum"}.get(feature_len)


# ----------------------------------------------------------------------------- Windows HID
class _GUID(ctypes.Structure):
    _fields_ = [("d1", ctypes.c_ulong), ("d2", ctypes.c_ushort), ("d3", ctypes.c_ushort), ("d4", ctypes.c_ubyte * 8)]


class _IfData(ctypes.Structure):  # SP_DEVICE_INTERFACE_DATA
    _fields_ = [("cbSize", wt.DWORD), ("guid", _GUID), ("flags", wt.DWORD), ("res", ctypes.c_size_t)]


class _Attr(ctypes.Structure):  # HIDD_ATTRIBUTES
    _fields_ = [("Size", wt.ULONG), ("VendorID", ctypes.c_ushort), ("ProductID", ctypes.c_ushort),
                ("Version", ctypes.c_ushort)]


class _Caps(ctypes.Structure):  # HIDP_CAPS
    _fields_ = [("Usage", ctypes.c_ushort), ("UsagePage", ctypes.c_ushort), ("InputLen", ctypes.c_ushort),
                ("OutputLen", ctypes.c_ushort), ("FeatureLen", ctypes.c_ushort), ("Reserved", ctypes.c_ushort * 17),
                ("rest", ctypes.c_ushort * 10)]


def _dlls():
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    sapi = ctypes.WinDLL("setupapi", use_last_error=True)
    hid = ctypes.WinDLL("hid", use_last_error=True)
    k32.CreateFileW.restype = c_void_p
    k32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, c_void_p, wt.DWORD, wt.DWORD, c_void_p]
    k32.CloseHandle.argtypes = [c_void_p]
    sapi.SetupDiGetClassDevsW.restype = c_void_p
    sapi.SetupDiGetClassDevsW.argtypes = [c_void_p, wt.LPCWSTR, wt.HWND, wt.DWORD]
    sapi.SetupDiEnumDeviceInterfaces.argtypes = [c_void_p, c_void_p, c_void_p, wt.DWORD, c_void_p]
    sapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [c_void_p, c_void_p, c_void_p, wt.DWORD,
                                                      ctypes.POINTER(wt.DWORD), c_void_p]
    sapi.SetupDiDestroyDeviceInfoList.argtypes = [c_void_p]
    hid.HidD_GetHidGuid.argtypes = [c_void_p]
    hid.HidD_GetAttributes.argtypes = [c_void_p, c_void_p]
    hid.HidD_GetPreparsedData.argtypes = [c_void_p, ctypes.POINTER(c_void_p)]
    hid.HidD_FreePreparsedData.argtypes = [c_void_p]
    hid.HidP_GetCaps.argtypes = [c_void_p, c_void_p]
    hid.HidP_GetCaps.restype = ctypes.c_ulong
    hid.HidD_SetFeature.argtypes = [c_void_p, c_void_p, wt.ULONG]
    return k32, sapi, hid


def enumerate_hid():
    """[(yol, vid, pid, ozellik_raporu_uzunlugu)] ; yalnizca VID 0x048D aygitlari acilip incelenir."""
    k32, sapi, hid = _dlls()
    guid = _GUID()
    hid.HidD_GetHidGuid(ctypes.byref(guid))
    h = sapi.SetupDiGetClassDevsW(ctypes.byref(guid), None, None, 0x12)  # DIGCF_PRESENT | DEVICEINTERFACE
    if not h or h == c_void_p(-1).value:
        return []
    out = []
    try:
        i = 0
        while True:
            ifd = _IfData()
            ifd.cbSize = ctypes.sizeof(ifd)
            if not sapi.SetupDiEnumDeviceInterfaces(h, None, ctypes.byref(guid), i, ctypes.byref(ifd)):
                break
            i += 1
            need = wt.DWORD(0)
            sapi.SetupDiGetDeviceInterfaceDetailW(h, ctypes.byref(ifd), None, 0, ctypes.byref(need), None)
            if not need.value:
                continue
            buf = ctypes.create_string_buffer(need.value + 8)
            ctypes.c_uint32.from_buffer(buf).value = 8 if ctypes.sizeof(c_void_p) == 8 else 6
            if not sapi.SetupDiGetDeviceInterfaceDetailW(h, ctypes.byref(ifd), buf, need.value, None, None):
                continue
            path = ctypes.wstring_at(ctypes.addressof(buf) + 4)
            if "vid_048d" not in path.lower():
                continue  # baska ureticinin aygitini acmaya bile gerek yok
            dev = k32.CreateFileW(path, 0, 3, None, 3, 0, None)  # erisim 0: yalnizca bilgi
            if not dev or dev == c_void_p(-1).value:
                continue
            try:
                attr = _Attr()
                attr.Size = ctypes.sizeof(attr)
                if not hid.HidD_GetAttributes(dev, ctypes.byref(attr)):
                    continue
                pp = c_void_p()
                flen = 0
                if hid.HidD_GetPreparsedData(dev, ctypes.byref(pp)):
                    caps = _Caps()
                    if hid.HidP_GetCaps(pp, ctypes.byref(caps)) == 0x00110000:  # HIDP_STATUS_SUCCESS
                        flen = caps.FeatureLen
                    hid.HidD_FreePreparsedData(pp)
                out.append((path, attr.VendorID, attr.ProductID, flen))
            finally:
                k32.CloseHandle(dev)
    finally:
        sapi.SetupDiDestroyDeviceInfoList(h)
    return out


class Keyboard:
    """Bulunan klavye. available False ise set_color hicbir sey gondermez."""

    def __init__(self, path, pid, kind, sender=None):
        self.path, self.pid, self.kind = path, pid, kind
        self.available = kind == "4zone"
        self.reason = "" if self.available else ceviri.t("unsup.kbSpectrum")
        self._send = sender  # testte sahte gonderici
        self._h = None
        self._lock = threading.Lock()

    def _write(self, data):
        if self._send:
            return self._send(data)
        k32, _sapi, hid = _dlls()
        if self._h is None:
            h = k32.CreateFileW(self.path, 0xC0000000, 3, None, 3, 0, None)
            if not h or h == c_void_p(-1).value:
                raise OSError(ctypes.get_last_error(), "klavye acilamadi")
            self._h = h
        buf = ctypes.create_string_buffer(bytes(data), len(data))
        if not hid.HidD_SetFeature(self._h, buf, len(data)):
            err = ctypes.get_last_error()
            k32.CloseHandle(self._h)  # uykudan sonra tanitici gecersiz olabilir: sonraki karede yeniden ac
            self._h = None
            raise OSError(err, "HidD_SetFeature")
        return 1

    def set_color(self, r, g, b):
        if not self.available:
            return 0
        with self._lock:
            return self._write(report_4zone(r, g, b))


def find(devices=None):
    """Ilk Legion klavyesi (4 bolgeli once) ya da None. devices testte verilir."""
    if devices is None:
        devices = enumerate_hid()
    found = [(classify(v, p, n), path, p) for path, v, p, n in devices]
    found = [f for f in found if f[0]]
    found.sort(key=lambda f: f[0] != "4zone")
    if not found:
        return None
    kind, path, pid = found[0]
    return Keyboard(path, pid, kind)
