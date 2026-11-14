# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""NVIDIA paneli: surucu ayarlari (NVIDIA Denetim Masasi'ndaki 3B ayarlari), kart bilgileri ve saat siniri.

Surucu ayarlari NVAPI'nin DRS (Driver Settings) arayuzuyle, NVIDIA Denetim Masasi'nin yazdigi ayni genel
profile yazilir; Denetim Masasi acildiginda ayni degerleri gosterir. Ayar kimlikleri ve gecerli degerler
surucunun kendisinden dogrulandi (NvAPI_DRS_GetSettingNameFromId / EnumAvailableSettingValues, surucu 617.42).
Yazmak yonetici ister (ayarlar ProgramData'da durur); okumak istemez.
"""
import ctypes
import threading

import donanim as hw
from ceviri import t

# ----------------------------------------------------------------------------- ayarlar
# (kimlik, ayar kimlik(leri), gecerli degerler, kosul). Etiketler ceviride: nv.<kimlik>, nv.<kimlik>.desc,
# nv.<kimlik>.<deger> (kare siniri haric: sayi + FPS).
SETTINGS = [
    ("power", (0x1057EB71,), [5, 0, 1], None),                                  # Normal, Uyarlanabilir, En yuksek
    ("lowlat", (0x007BA09E,), [0, 1], None),                                    # en fazla 1 kare onden hazirla
    ("vsync", (0x00A879CF,), [0x60925292, 0x08416747, 0x47814940, 0x18888888], None),  # uygulama, kapali, acik, hizli
    ("fps", (0x10835002,), [0, 30, 45, 60, 75, 90, 120, 141, 144, 165, 240], None),
    ("texq", (0x00CE2691,), [0xFFFFFFF6, 0, 10, 20], None),                     # yuksek kalite .. yuksek performans
    ("thread", (0x20C1221E,), [0, 1, 2], None),                                 # otomatik, acik, kapali
    ("optimus", (0x10F9DC80, 0x10F9DC81), [0x10, 1, 0], "optimus"),            # otomatik, NVIDIA, tumlesik
]
BY_ID = {s[0]: s for s in SETTINGS}


def public(optimus):
    """Arayuz icin ayar listesi (secili dilde)."""
    out = []
    for key, _, values, cond in SETTINGS:
        if cond == "optimus" and not optimus:
            continue
        opts = [{"v": v, "t": ("%d FPS" % v if v else t("nv.fps.0")) if key == "fps" else t("nv.%s.%d" % (key, v))}
                for v in values]
        out.append({"id": key, "label": t("nv." + key), "desc": t("nv.%s.desc" % key), "opts": opts})
    return out

NVAPI_SETTING_NOT_FOUND = -160


class _Setting(ctypes.Structure):  # NVDRS_SETTING_V1
    _fields_ = [("version", ctypes.c_uint), ("name", ctypes.c_wchar * 2048), ("id", ctypes.c_uint),
                ("type", ctypes.c_int), ("location", ctypes.c_int), ("isCurrentPredefined", ctypes.c_uint),
                ("isPredefinedValid", ctypes.c_uint), ("predef", ctypes.c_ubyte * 4100), ("cur", ctypes.c_ubyte * 4100)]


class _Values(ctypes.Structure):  # NVDRS_SETTING_VALUES_V1
    _fields_ = [("version", ctypes.c_uint), ("num", ctypes.c_uint), ("type", ctypes.c_int),
                ("default", ctypes.c_ubyte * 4100), ("values", ctypes.c_ubyte * (4100 * 100))]


def _ver(struct):
    return ctypes.sizeof(struct) | (1 << 16)


class NvApi:
    """nvapi64.dll ile surucu ayarlari. Her islem kendi oturumunu acip kapatir (Denetim Masasi'yla cakismasin)."""
    IDS = {"init": 0x0150E828, "create": 0x0694D52E, "destroy": 0xDAD9CFF8, "load": 0x375DBD6B,
           "save": 0xFCBC7E14, "base": 0xDA8466A0, "get": 0x73BF8338, "set": 0x577DD202,
           "restore": 0x53F0381E, "values": 0x2EC39F90}

    def __init__(self):
        self.ok = False
        self.lock = threading.Lock()
        self._defaults = {}
        try:
            dll = ctypes.WinDLL("nvapi64.dll")
        except OSError:
            return
        qi = dll.nvapi_QueryInterface
        qi.restype = ctypes.c_void_p
        qi.argtypes = [ctypes.c_uint]
        P, U, VP = ctypes.POINTER, ctypes.c_uint, ctypes.c_void_p
        sig = {"init": (), "create": (P(VP),), "destroy": (VP,), "load": (VP,), "save": (VP,),
               "base": (VP, P(VP)), "get": (VP, VP, U, P(_Setting)), "set": (VP, VP, P(_Setting)),
               "restore": (VP, VP, U), "values": (U, P(U), P(_Values))}
        self.fn = {}
        for k, fid in self.IDS.items():
            p = qi(fid)
            if not p:
                return
            self.fn[k] = ctypes.CFUNCTYPE(ctypes.c_int, *sig[k])(p)
        self.ok = self.fn["init"]() == 0

    def _session(self):
        s, prof = ctypes.c_void_p(), ctypes.c_void_p()
        if self.fn["create"](ctypes.byref(s)) != 0:
            raise RuntimeError(t("err.nvSession"))
        if self.fn["load"](s) != 0 or self.fn["base"](s, ctypes.byref(prof)) != 0:
            self.fn["destroy"](s)
            raise RuntimeError(t("err.nvRead"))
        return s, prof

    def default(self, sid):
        if sid not in self._defaults:
            v = _Values()
            v.version = _ver(_Values)
            n = ctypes.c_uint(100)
            r = self.fn["values"](sid, ctypes.byref(n), ctypes.byref(v))
            self._defaults[sid] = int.from_bytes(bytes(v.default[:4]), "little") if r == 0 else None
        return self._defaults[sid]

    def read(self):
        """Her ayarin su anki degeri (surucu varsayilanindaysa varsayilan deger)."""
        if not self.ok:
            return {}
        out = {}
        with self.lock:
            s, prof = self._session()
            try:
                for key, sids, _, _ in SETTINGS:
                    st = _Setting()
                    st.version = _ver(_Setting)
                    r = self.fn["get"](s, prof, sids[-1], ctypes.byref(st))
                    if r == 0:
                        out[key] = {"value": int.from_bytes(bytes(st.cur[:4]), "little"), "custom": True}
                    elif r == NVAPI_SETTING_NOT_FOUND:
                        out[key] = {"value": self.default(sids[-1]), "custom": False}
            finally:
                self.fn["destroy"](s)
        return out

    def write(self, key, value):
        """value None ise ayar surucu varsayilanina doner."""
        if not self.ok:
            raise RuntimeError(t("err.nvNoDll"))
        if not hw.is_admin():
            raise RuntimeError(t("err.nvAdmin"))
        item = BY_ID.get(key)
        if not item:
            raise ValueError(t("err.nvUnknown"))
        if value is not None and value not in item[2]:
            raise ValueError(t("err.badValue"))
        with self.lock:
            s, prof = self._session()
            try:
                for sid in item[1]:
                    if value is None:
                        r = self.fn["restore"](s, prof, sid)
                        if r not in (0, NVAPI_SETTING_NOT_FOUND):
                            raise RuntimeError(t("err.nvRestore", code=r))
                        continue
                    st = _Setting()
                    st.version = _ver(_Setting)
                    st.id = sid
                    st.type = 0  # DWORD
                    st.cur[:4] = list(int(value & 0xFFFFFFFF).to_bytes(4, "little"))
                    r = self.fn["set"](s, prof, ctypes.byref(st))
                    if r != 0:
                        raise RuntimeError(t("err.nvWrite", code=r))
                r = self.fn["save"](s)
                if r != 0:
                    raise RuntimeError(t("err.nvSave", code=r))
            finally:
                self.fn["destroy"](s)


# ----------------------------------------------------------------------------- kart bilgisi (NVML)
def card_info():
    """Kartin sabit bilgileri. NVML'yi baslatir: uykudaki karti kisa sure uyandirir, bu yuzden yalnizca
    NVIDIA sayfasi acilinca bir kez cagrilir ve sonuc saklanir."""
    try:
        L = ctypes.WinDLL(r"C:\Windows\System32\nvml.dll")
    except OSError:
        return None
    if L.nvmlInit_v2() != 0:
        return None
    h = ctypes.c_void_p()
    if L.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(h)) != 0:
        return None
    b = ctypes.create_string_buffer(96)
    v = ctypes.c_uint()
    out = {}

    def s(fn, key):
        if getattr(L, fn)(h, b, 96) == 0:
            out[key] = b.value.decode("utf-8", "replace")

    def u(fn, key, *args, scale=1):
        if getattr(L, fn)(h, *args, ctypes.byref(v)) == 0:
            out[key] = v.value / scale if scale != 1 else v.value

    if L.nvmlSystemGetDriverVersion(b, 96) == 0:
        out["driver"] = b.value.decode()
    s("nvmlDeviceGetName", "name")
    s("nvmlDeviceGetVbiosVersion", "vbios")
    u("nvmlDeviceGetNumGpuCores", "cores")
    u("nvmlDeviceGetMaxClockInfo", "max_clock", 0)
    u("nvmlDeviceGetMaxClockInfo", "max_mem_clock", 2)
    u("nvmlDeviceGetMaxPcieLinkGeneration", "pcie_gen_max")
    u("nvmlDeviceGetMaxPcieLinkWidth", "pcie_width_max")
    u("nvmlDeviceGetPowerManagementDefaultLimit", "power_default", scale=1000)
    u("nvmlDeviceGetEnforcedPowerLimit", "power_limit", scale=1000)
    u("nvmlDeviceGetTemperatureThreshold", "temp_shutdown", 0)
    u("nvmlDeviceGetTemperatureThreshold", "temp_slowdown", 1)
    u("nvmlDeviceGetTemperatureThreshold", "temp_max", 3)
    m = hw._NvMem()
    if L.nvmlDeviceGetMemoryInfo(h, ctypes.byref(m)) == 0:
        out["vram_mb"] = round(m.total / 2 ** 20)
    lo, hi = ctypes.c_uint(), ctypes.c_uint()
    if L.nvmlDeviceGetPowerManagementLimitConstraints(h, ctypes.byref(lo), ctypes.byref(hi)) == 0:
        out["power_min"], out["power_max"] = lo.value / 1000, hi.value / 1000
    # Kartin destekledigi cekirdek saatleri: elle saat siniri icin gecerli aralik
    cnt = ctypes.c_uint(64)
    mem = (ctypes.c_uint * 64)()
    if L.nvmlDeviceGetSupportedMemoryClocks(h, ctypes.byref(cnt), mem) == 0 and cnt.value:
        n = ctypes.c_uint(512)
        g = (ctypes.c_uint * 512)()
        if L.nvmlDeviceGetSupportedGraphicsClocks(h, mem[0], ctypes.byref(n), g) == 0 and n.value:
            clocks = sorted(set(g[:n.value]))
            out["clock_min"], out["clock_max"] = clocks[0], clocks[-1]
    return out
