# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""Donanim katmani: Monster/Clevo gomulu denetleyicisi (InsydeDCHU.dll), Windows sayaclari,
NVIDIA (NVML), ekran yenileme hizi ve ses seviyesi.

InsydeDCHU.dll yoksa (Clevo tabanli olmayan bilgisayar) NullDCHU devreye girer: fan, guc modu ve klavye
isigi kapanir; izleme ve diger tum ozellikler calisir.

DCHU komutlari Control Center v6.093'un kendi kodundan cikarildi:
  SetWMI(121, mod, alt=25)  guc modu   0 sessiz, 1 guc tasarrufu, 2 performans, 3 eglence
  SetWMI(121, mod, alt=1)   fan modu   0 otomatik, 1 maksimum, 6 ozel egri
  SetDCHU_Data(14, 256 bayt)           ozel fan egrisi
  GetDCHU_Data_Buffer(12)              fan devri, fan gorevi, sicakliklar
  GetDCHU_Data_Buffer(13)              fabrika fan egrisi
"""
import ctypes
import os
import subprocess
import sys
import threading
import time
from collections import deque
from ctypes import wintypes as wt

import ceviri

c_void_p = ctypes.c_void_p
c_int = ctypes.c_int
c_ubyte = ctypes.c_ubyte

HERE = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))  # exe: paket klasoru
DLL_CANDIDATES = [
    os.path.join(HERE, "lib", "InsydeDCHU.dll"),
    r"C:\Program Files (x86)\ControlCenter\DCHU\InsydeDCHU.dll",
    r"C:\Program Files (x86)\ControlCenter\AppInstall\InsydeDCHU.dll",
]
NO_WINDOW = 0x08000000

POWER_MODES = {0: "Sessiz", 1: "Güç tasarrufu", 2: "Performans", 3: "Eğlence"}
FAN_AUTO, FAN_MAX, FAN_CUSTOM = 0, 1, 6


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


def run(args, timeout=8):
    """Konsol penceresi acmadan komut calistirir; (donus kodu, cikti)."""
    try:
        p = subprocess.run(args, capture_output=True, timeout=timeout, creationflags=NO_WINDOW)
        out = (p.stdout or b"") + (p.stderr or b"")
        return p.returncode, out.decode("utf-8", "replace").strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return -1, str(exc)


# ============================================================================= gomulu denetleyici
class DCHU:
    """InsydeDCHU.dll sarmalayicisi. Tum cagrilar tek kilitten gecer (motor, sensor ve sunucu ayni anda cagirir)."""
    available = True

    def __init__(self):
        path = next((p for p in DLL_CANDIDATES if os.path.exists(p)), None)
        if not path:
            raise RuntimeError(ceviri.t("err.dll"))
        self.path = path
        os.add_dll_directory(os.path.dirname(path))
        d = ctypes.WinDLL(path)
        d.SetDCHU_Data.argtypes = [c_int, ctypes.POINTER(c_ubyte), c_int]
        d.SetDCHU_Data.restype = c_int
        d.SetDCHU_DataEx.argtypes = [c_int, ctypes.POINTER(c_ubyte), c_int, ctypes.POINTER(c_ubyte)]
        d.SetDCHU_DataEx.restype = c_int
        d.GetDCHU_Data_Buffer.argtypes = [c_int, ctypes.POINTER(c_ubyte)]
        d.GetDCHU_Data_Buffer.restype = c_int
        d.GetDCHU_Data_Integer.argtypes = [c_int, ctypes.POINTER(c_int)]
        d.GetDCHU_Data_Integer.restype = c_int
        d.ReadAppSettings.argtypes = [c_int, c_int, c_int, ctypes.POINTER(c_ubyte)]
        d.WriteAppSettings.argtypes = [c_int, c_int, c_int, ctypes.POINTER(c_ubyte)]
        self.dll = d
        self.lock = threading.Lock()
        self._fan_default = None

    # ------------------------------------------------------------------ ham erisim
    def get_int(self, cmd):
        v = c_int(0)
        with self.lock:
            self.dll.GetDCHU_Data_Integer(cmd, ctypes.byref(v))
        return v.value

    def get_buf(self, cmd):
        b = (c_ubyte * 256)()
        with self.lock:
            self.dll.GetDCHU_Data_Buffer(cmd, b)
        return bytes(b)

    def set_data(self, cmd, data):
        b = (c_ubyte * len(data))(*data)
        with self.lock:
            return self.dll.SetDCHU_Data(cmd, b, len(data))

    def set_wmi(self, cmd, data, sub=None):
        raw = bytearray(int(data & 0xFFFFFFFF).to_bytes(4, "little"))
        if sub is not None:
            raw[3] = sub & 0xFF
        return self.set_data(cmd, raw)

    def read_app(self, page, offset, n):
        b = (c_ubyte * n)()
        with self.lock:
            self.dll.ReadAppSettings(page, offset, n, b)
        return bytes(b)

    def write_app(self, page, offset, data):
        b = (c_ubyte * len(data))(*data)
        with self.lock:
            self.dll.WriteAppSettings(page, offset, len(data), b)

    # ------------------------------------------------------------------ klavye
    def set_color(self, r, g, b):
        return self.set_data(103, (g & 255, r & 255, b & 255, 0xF0))

    # ------------------------------------------------------------------ olcumler
    @staticmethod
    def _rpm(raw):
        return int(round(2156250.0 / raw)) if raw else 0

    def status(self):
        b = self.get_buf(12)
        return {
            "cpu_temp": b[18], "gpu_temp": b[21],
            "cpu_rpm": self._rpm((b[2] << 8) | b[3]), "gpu_rpm": self._rpm((b[4] << 8) | b[5]),
            "cpu_duty": round(b[16] / 2.55), "gpu_duty": round(b[19] / 2.55),
        }

    def temps(self):
        s = self.status()
        return s["cpu_temp"], s["gpu_temp"]

    # ------------------------------------------------------------------ guc modu
    def power_mode(self):
        m = self.read_app(1, 1, 1)[0]
        return m if m in POWER_MODES else 3

    def set_power_mode(self, mode):
        if mode not in POWER_MODES:
            raise ValueError(ceviri.t("err.unknownPower"))
        self.write_app(1, 1, bytes([mode]))
        self.set_wmi(121, mode, 25)
        # Control Center'in yaptigi gibi enerji tercihi ipucu: performans 0, tasarruf 1, digerleri 2
        self.set_wmi(79, {2: 0, 1: 1}.get(mode, 2))

    # ------------------------------------------------------------------ fan
    def fan_mode(self):
        return self.read_app(4, 5, 1)[0]

    def set_fan_mode(self, mode):
        self.set_wmi(121, mode, 1)
        self.write_app(4, 5, bytes([mode]))

    def fan_default(self):
        """Fabrika egrisi: {cpu: [(T,D%),...4 nokta], gpu: [...]} ; T1/D1 ve T4/D4 denetleyicide sabit."""
        if self._fan_default is None:
            b = self.get_buf(13)

            def pts(o):
                return [(b[o], round(b[o + 1] / 2.55)), (b[o + 2], round(b[o + 3] / 2.55)),
                        (b[o + 4], round(b[o + 5] / 2.55)), (100, 100)]
            self._fan_default = {"count": b[12], "cpu": pts(16), "gpu": pts(24)}
        return self._fan_default

    @staticmethod
    def _slope(d_a, d_b, t_a, t_b):
        return int(round((d_b - d_a) / float(t_b - t_a) * 2.55 * 16.0)) if t_b != t_a else 0

    def set_fan_curve(self, cpu, gpu):
        """cpu/gpu: (T2, D2%, T3, D3%). Ilk nokta (T1, D1) ve son nokta (100 C, %100) denetleyicide sabittir."""
        base = self.fan_default()
        out = bytearray(256)
        slopes = []
        for i, (key, pts) in enumerate((("cpu", cpu), ("gpu", gpu))):
            t1, d1 = base[key][0]
            t2, d2, t3, d3 = validate_curve(pts, t1, d1)
            o = 2 + i * 4
            out[o:o + 4] = bytes([t2, round(d2 * 2.55), t3, round(d3 * 2.55)])
            slopes.append((self._slope(d1, d2, t1, t2), self._slope(d2, d3, t2, t3), self._slope(d3, 100, t3, 100)))
        for i, (r12, r23, r34) in enumerate(slopes):
            o = 14 + i * 6
            for j, r in enumerate((r12, r23, r34)):
                out[o + j * 2] = (r >> 8) & 0xFF
                out[o + j * 2 + 1] = r & 0xFF
        self.set_data(14, out)
        self.set_fan_mode(FAN_CUSTOM)


class NullDCHU:
    """Gomulu denetleyici kitapligi olmayan bilgisayarlar icin: okumalar bos, yazmalar acik bir hata verir.
    Profil adimlari bu hatayi raporda 'desteklenmiyor' olarak gosterir; geri kalan her sey calisir."""
    available = False
    path = ""

    def __init__(self, reason=""):
        self.reason = reason

    def _no(self, *args, **kwargs):
        raise RuntimeError(ceviri.t("err.noEc"))

    set_wmi = set_data = write_app = set_power_mode = set_fan_mode = set_fan_curve = _no

    def set_color(self, r, g, b):  # klavye motoru her karede cagirir: sessizce yok say
        return 0

    def status(self):
        return {}

    def power_mode(self):
        return None

    def fan_mode(self):
        return None

    def fan_default(self):
        return None


def open_dchu():
    """Gercek denetleyici ya da (kitaplik yoksa / yuklenemezse) NullDCHU."""
    try:
        return DCHU()
    except Exception as exc:
        return NullDCHU(str(exc))


def validate_curve(pts, t1, d1):
    """Fan egrisini guvenli sinirlara ceker: artan sicaklik ve gorev, sicak bolgede yeterli hava."""
    t2, d2, t3, d3 = (int(x) for x in pts)
    t2 = max(t1 + 1, min(t2, 87))
    t3 = max(t2 + 1, min(t3, 88))
    d2 = max(d1 + 1, min(d2, 97))
    d3 = max(d2 + 1, min(d3, 99))
    d3 = max(d3, 45)  # 88 C'den once en az %45: denetleyici 100 C'de zaten %100'e cikar
    if d2 >= d3:
        d2 = d3 - 1
    return t2, d2, t3, d3


# ============================================================================= Windows sayaclari (PDH)
class _PdhItem(ctypes.Structure):
    _fields_ = [("name", wt.LPWSTR), ("status", wt.DWORD), ("pad", wt.DWORD), ("value", ctypes.c_double)]


class Pdh:
    """Ingilizce sayac adlariyla (Turkce Windows'ta da calisir) dizi sayaclar."""
    FMT_DOUBLE_NOCAP = 0x00000200 | 0x00008000

    def __init__(self, paths):
        self.pdh = ctypes.WinDLL("pdh")
        self.q = c_void_p()
        self.pdh.PdhOpenQueryW(None, 0, ctypes.byref(self.q))
        self.counters = {}
        for key, path in paths.items():
            c = c_void_p()
            if self.pdh.PdhAddEnglishCounterW(self.q, path, 0, ctypes.byref(c)) == 0:
                self.counters[key] = c
        self.pdh.PdhCollectQueryData(self.q)

    def collect(self):
        self.pdh.PdhCollectQueryData(self.q)
        out = {}
        for key, c in self.counters.items():
            size, n = wt.DWORD(0), wt.DWORD(0)
            self.pdh.PdhGetFormattedCounterArrayW(c, self.FMT_DOUBLE_NOCAP, ctypes.byref(size), ctypes.byref(n), None)
            if not size.value:
                out[key] = {}
                continue
            # Bol pay: GPU Engine gibi surec basina ornekli sayaclarda ornek sayisi iki cagri arasinda degisir;
            # tam olcu tampon tasarsa Python yigini bozulur ve cokus sonradan cop toplamada patlar.
            size.value = size.value * 2 + 65536
            buf = (ctypes.c_byte * size.value)()
            if self.pdh.PdhGetFormattedCounterArrayW(c, self.FMT_DOUBLE_NOCAP, ctypes.byref(size),
                                                     ctypes.byref(n), buf) != 0:
                out[key] = {}
                continue
            items = ctypes.cast(buf, ctypes.POINTER(_PdhItem))
            vals = {}
            for i in range(n.value):
                if items[i].status in (0, 1):
                    vals[items[i].name] = vals.get(items[i].name, 0.0) + items[i].value
            out[key] = vals
        return out


# ============================================================================= NVIDIA
def _vcall(ptr, index, restype, *argtypes):
    vtbl = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(c_void_p))).contents
    return ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)(vtbl[index])


class GUID(ctypes.Structure):
    _fields_ = [("d1", ctypes.c_ulong), ("d2", ctypes.c_ushort), ("d3", ctypes.c_ushort), ("d4", ctypes.c_ubyte * 8)]


def guid(s):
    g = GUID()
    ctypes.windll.ole32.CLSIDFromString(ctypes.c_wchar_p("{%s}" % s.strip("{}")), ctypes.byref(g))
    return g


class _DXGIDesc1(ctypes.Structure):
    _fields_ = [("desc", ctypes.c_wchar * 128), ("vendor", ctypes.c_uint), ("device", ctypes.c_uint),
                ("subsys", ctypes.c_uint), ("rev", ctypes.c_uint), ("vram", ctypes.c_size_t),
                ("sysmem", ctypes.c_size_t), ("shared", ctypes.c_size_t), ("luid_lo", ctypes.c_ulong),
                ("luid_hi", ctypes.c_long), ("flags", ctypes.c_uint)]


def gpu_adapters():
    """DXGI ile ekran kartlari: [(ad, ureticiKimligi, 'luid_0x..._0x...')]. GPU'yu uyandirmaz."""
    out = []
    try:
        dxgi = ctypes.WinDLL("dxgi")
        f = c_void_p()
        iid = guid("770aae78-f26f-4dba-a829-253c83d1b387")
        if dxgi.CreateDXGIFactory1(ctypes.byref(iid), ctypes.byref(f)) != 0:
            return out
        i = 0
        while True:
            a = c_void_p()
            if _vcall(f, 12, ctypes.c_long, ctypes.c_uint, c_void_p)(f, i, ctypes.byref(a)) != 0:
                break
            d = _DXGIDesc1()
            _vcall(a, 10, ctypes.c_long, c_void_p)(a, ctypes.byref(d))
            _vcall(a, 2, ctypes.c_ulong)(a)
            if not d.flags & 2:  # yazilim bagdastiricisi degil
                out.append((d.desc, d.vendor, "luid_0x%08X_0x%08X" % (d.luid_hi & 0xFFFFFFFF, d.luid_lo)))
            i += 1
        _vcall(f, 2, ctypes.c_ulong)(f)
    except OSError:
        pass
    return out


THROTTLE = [  # nvmlClocksEventReasons bitleri: kart neden en yuksek saatinde degil
    0x1, 0x2, 0x4, 0x8, 0x20, 0x40, 0x80, 0x100,  # metinleri ui/lang: "throttle.<bit, ondalik>"
]


def throttle_text(mask):
    return [ceviri.t("throttle.%d" % bit) for bit in THROTTLE if mask & bit]


class _NvMem(ctypes.Structure):
    _fields_ = [("total", ctypes.c_ulonglong), ("free", ctypes.c_ulonglong), ("used", ctypes.c_ulonglong)]


class NVML:
    """Yalnizca kart zaten uyanikken sorgulanir: bos karti uyandirmak pil ve isi demektir."""

    def __init__(self):
        self.h = None
        self.lib = None
        try:
            lib = ctypes.WinDLL(r"C:\Windows\System32\nvml.dll")
            if lib.nvmlInit_v2() != 0:
                return
            h = c_void_p()
            if lib.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(h)) == 0:
                self.lib, self.h = lib, h
        except OSError:
            pass

    def read(self):
        if not self.h:
            return {}
        L, h, v = self.lib, self.h, ctypes.c_uint()
        out = {}
        if L.nvmlDeviceGetPowerUsage(h, ctypes.byref(v)) == 0:
            out["power"] = round(v.value / 1000.0, 1)
        if L.nvmlDeviceGetClockInfo(h, 0, ctypes.byref(v)) == 0:
            out["clock"] = v.value
        if L.nvmlDeviceGetClockInfo(h, 2, ctypes.byref(v)) == 0:
            out["mem_clock"] = v.value
        if L.nvmlDeviceGetPerformanceState(h, ctypes.byref(v)) == 0:
            out["pstate"] = v.value
        m = _NvMem()
        if L.nvmlDeviceGetMemoryInfo(h, ctypes.byref(m)) == 0:
            out["vram_used"] = round(m.used / 2 ** 20)
            out["vram_total"] = round(m.total / 2 ** 20)
        if L.nvmlDeviceGetTemperature(h, 0, ctypes.byref(v)) == 0:
            out["temp_nv"] = v.value
        if L.nvmlDeviceGetCurrPcieLinkGeneration(h, ctypes.byref(v)) == 0:
            gen = v.value
            if L.nvmlDeviceGetCurrPcieLinkWidth(h, ctypes.byref(v)) == 0:
                out["pcie"] = "Gen%d ×%d" % (gen, v.value)
        reasons = ctypes.c_ulonglong()
        if L.nvmlDeviceGetCurrentClocksEventReasons(h, ctypes.byref(reasons)) == 0:
            out["throttle"] = reasons.value
        return out


def nvidia_lock_clocks(lo, hi):
    """Ekran karti saatini [lo, hi] MHz araligina kilitler; hi None ise kilidi kaldirir. Yonetici ister."""
    if hi is None:
        return run(["nvidia-smi", "-rgc"])
    return run(["nvidia-smi", "-lgc", "%d,%d" % (lo, hi)])


# ============================================================================= ekran
class DEVMODEW(ctypes.Structure):
    _fields_ = [("dmDeviceName", ctypes.c_wchar * 32), ("dmSpecVersion", wt.WORD), ("dmDriverVersion", wt.WORD),
                ("dmSize", wt.WORD), ("dmDriverExtra", wt.WORD), ("dmFields", wt.DWORD),
                ("dmUnion", ctypes.c_byte * 16), ("dmColor", ctypes.c_short), ("dmDuplex", ctypes.c_short),
                ("dmYResolution", ctypes.c_short), ("dmTTOption", ctypes.c_short), ("dmCollate", ctypes.c_short),
                ("dmFormName", ctypes.c_wchar * 32), ("dmLogPixels", wt.WORD), ("dmBitsPerPel", wt.DWORD),
                ("dmPelsWidth", wt.DWORD), ("dmPelsHeight", wt.DWORD), ("dmDisplayFlags", wt.DWORD),
                ("dmDisplayFrequency", wt.DWORD), ("dmICM", wt.DWORD * 8)]


class Display:
    DM_DISPLAYFREQUENCY = 0x00400000

    @staticmethod
    def _mode(i):
        dm = DEVMODEW()
        dm.dmSize = ctypes.sizeof(DEVMODEW)
        ok = ctypes.windll.user32.EnumDisplaySettingsW(None, i, ctypes.byref(dm))
        return dm if ok else None

    def current(self):
        dm = self._mode(-1)  # ENUM_CURRENT_SETTINGS
        return (dm.dmPelsWidth, dm.dmPelsHeight, dm.dmDisplayFrequency) if dm else (0, 0, 0)

    def rates(self):
        w, h, _ = self.current()
        out, i = set(), 0
        while True:
            dm = self._mode(i)
            if dm is None:
                break
            if dm.dmPelsWidth == w and dm.dmPelsHeight == h and dm.dmBitsPerPel == 32:
                out.add(int(dm.dmDisplayFrequency))
            i += 1
        return sorted(out)

    def set_rate(self, hz):
        if self.current()[2] == hz:
            return True
        dm = self._mode(-1)
        dm.dmDisplayFrequency = hz
        dm.dmFields = self.DM_DISPLAYFREQUENCY
        return ctypes.windll.user32.ChangeDisplaySettingsExW(None, ctypes.byref(dm), None, 1, None) == 0


# ============================================================================= ses
class Audio:
    """Varsayilan hoparlor ve mikrofon: seviye ve sessiz. Her cagri kendi COM baglamini acar."""
    CLSID_ENUM = "BCDE0395-E52F-467C-8E3D-C4579291692E"
    IID_ENUM = "A95664D2-9614-4F35-A746-DE8DB63617E6"
    IID_VOL = "5CDF2C82-841E-4546-9722-0CF74078229A"

    def _endpoint(self, flow):
        ole = ctypes.windll.ole32
        ole.CoInitializeEx(None, 0)
        ole.CoCreateInstance.argtypes = [c_void_p, c_void_p, ctypes.c_ulong, c_void_p, c_void_p]
        clsid, iid_e, iid_v = guid(self.CLSID_ENUM), guid(self.IID_ENUM), guid(self.IID_VOL)
        enum, dev, vol = c_void_p(), c_void_p(), c_void_p()
        if ole.CoCreateInstance(ctypes.byref(clsid), None, 23, ctypes.byref(iid_e), ctypes.byref(enum)) != 0:
            return None
        try:
            if _vcall(enum, 4, ctypes.c_long, c_int, c_int, c_void_p)(enum, flow, 0, ctypes.byref(dev)) != 0:
                return None
            try:
                if _vcall(dev, 3, ctypes.c_long, c_void_p, ctypes.c_ulong, c_void_p, c_void_p)(
                        dev, ctypes.byref(iid_v), 23, None, ctypes.byref(vol)) != 0:
                    return None
                return vol
            finally:
                _vcall(dev, 2, ctypes.c_ulong)(dev)
        finally:
            _vcall(enum, 2, ctypes.c_ulong)(enum)

    def get(self):
        out = {}
        for key, flow in (("speaker", 0), ("mic", 1)):
            vol = self._endpoint(flow)
            if not vol:
                out[key] = None
                continue
            try:
                lvl, mute = ctypes.c_float(), wt.BOOL()
                _vcall(vol, 9, ctypes.c_long, c_void_p)(vol, ctypes.byref(lvl))
                _vcall(vol, 15, ctypes.c_long, c_void_p)(vol, ctypes.byref(mute))
                out[key] = {"level": round(lvl.value * 100), "mute": bool(mute.value)}
            finally:
                _vcall(vol, 2, ctypes.c_ulong)(vol)
        return out

    def set(self, which, level=None, mute=None):
        vol = self._endpoint(0 if which == "speaker" else 1)
        if not vol:
            return False
        try:
            if level is not None:
                _vcall(vol, 7, ctypes.c_long, ctypes.c_float, c_void_p)(vol, max(0.0, min(1.0, level / 100.0)), None)
            if mute is not None:
                _vcall(vol, 14, ctypes.c_long, wt.BOOL, c_void_p)(vol, bool(mute), None)
            return True
        finally:
            _vcall(vol, 2, ctypes.c_ulong)(vol)


# ============================================================================= sensor toplayici
class _PowerStatus(ctypes.Structure):
    _fields_ = [("ac", c_ubyte), ("flag", c_ubyte), ("percent", c_ubyte), ("ssf", c_ubyte),
                ("life", ctypes.c_uint32), ("full", ctypes.c_uint32)]


def power_status():
    st = _PowerStatus()
    ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(st))
    return {"ac": st.ac == 1, "percent": None if st.percent > 100 else st.percent,
            "life": None if st.life == 0xFFFFFFFF else st.life}


def base_mhz():
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
        try:
            return int(winreg.QueryValueEx(k, "~MHz")[0])
        finally:
            winreg.CloseKey(k)
    except OSError:
        return 0


class Sensors(threading.Thread):
    """Saniyede bir tum olcumleri toplar; son 180 saniyelik gecmisi tutar."""
    HISTORY = 180

    def __init__(self, dchu):
        super().__init__(daemon=True)
        self.dchu = dchu
        self.running = True
        self.snapshot = {}
        self.seq = 0
        self.history = {k: deque(maxlen=self.HISTORY) for k in
                        ("cpu_temp", "gpu_temp", "cpu_power", "cpu_load", "gpu_load", "cpu_rpm", "gpu_rpm", "cpu_mhz")}
        self.listeners = []  # her olcumden sonra cagrilir (profil bekcisi)
        self.base = base_mhz()
        adapters = gpu_adapters()
        nv = [a for a in adapters if a[1] == 0x10DE]
        self.gpu_name = nv[0][0] if nv else ""
        self.nv_luid = nv[0][2].lower() if nv else ""
        other = [a for a in adapters if a[1] != 0x10DE]  # tumlesik grafik (Intel / AMD)
        self.igpu_name = other[0][0] if other else ""
        self.igpu_luid = other[0][2].lower() if other else ""
        self.nvml = None
        self.disk_ids = lambda: []  # envanter hazir olunca control_center baglar
        self.disks = {}

    def _disk_health(self, now):
        """Disk sicakligi ve NVMe sagligi: 30 sn'de bir (IOCTL ucuz ama SMART gunlugu her saniye gereksiz)."""
        if now < getattr(self, "_disk_next", 0):
            return
        self._disk_next = now + 30
        import envanter
        for n in self.disk_ids():
            try:
                self.disks[str(n)] = envanter.disk_health(n)
            except Exception:
                pass

    def run(self):
        import psutil
        counters = {
            "perf": r"\Processor Information(*)\% Processor Performance",
            "nominal": r"\Processor Information(*)\Processor Frequency",  # P 2000, E 1500 MHz
            "util": r"\Processor Information(*)\% Processor Utility",
            "energy": r"\Energy Meter(*)\Power",
            "gpu": r"\GPU Engine(*)\Utilization Percentage",
        }
        if not self.dchu.available:  # denetleyici yoksa islemci sicakligi icin ACPI isi bolgesi (Kelvin)
            counters["tz"] = r"\Thermal Zone Information(*)\Temperature"
        pdh = Pdh(counters)
        last_net = psutil.net_io_counters()
        last_disk = psutil.disk_io_counters()
        try:
            last_per = psutil.disk_io_counters(perdisk=True) or {}
        except Exception:
            last_per = {}
        last_t = time.monotonic()
        nv_awake_until = 0.0
        while self.running:
            t0 = time.monotonic()
            dt = max(t0 - last_t, 0.001)
            last_t = t0
            s = {"t": time.time()}
            try:
                s.update(self.dchu.status())
            except Exception as exc:  # denetleyici yanit vermezse olcum surer
                s["dchu_error"] = str(exc)
            try:
                c = pdh.collect()
                perf, util, nom = c.get("perf", {}), c.get("util", {}), c.get("nominal", {})
                cores = sorted((k for k in perf if "_Total" not in k), key=lambda k: [int(x) for x in k.split(",")])
                # % Processor Performance, cekirdegin kendi nominal frekansina goredir (melez islemcide P ve E farkli)
                s["cores"] = [{"mhz": round((nom.get(k) or self.base) * perf[k] / 100.0),
                               "load": round(min(util.get(k, 0.0), 100))}
                              for k in cores]
                s["cpu_load"] = round(min(util.get("_Total", 0.0), 100), 1)
                s["cpu_mhz"] = max((x["mhz"] for x in s["cores"]), default=0)
                e = c.get("energy", {})
                if "RAPL_Package0_PKG" in e:
                    s["cpu_power"] = round(e["RAPL_Package0_PKG"] / 1000.0, 1)
                    s["igpu_power"] = round(e.get("RAPL_Package0_PP1", 0.0) / 1000.0, 1)
                busy = {}
                for name, v in c.get("gpu", {}).items():
                    low = name.lower()
                    if "luid_" not in low:
                        continue
                    luid = "luid_" + low.split("luid_", 1)[1].split("_phys", 1)[0]
                    eng = name.rsplit("engtype_", 1)[-1]
                    busy.setdefault(luid, {})
                    busy[luid][eng] = busy[luid].get(eng, 0.0) + v
                nvb = busy.get(self.nv_luid, {})
                peak = max(nvb.values(), default=0.0)
                s["gpu_load"] = round(min(peak, 100), 1)
                s["gpu_active"] = peak > 0.5
                if self.igpu_luid:
                    s["igpu_load"] = round(min(max(busy.get(self.igpu_luid, {}).values(), default=0.0), 100), 1)
                tz = [v for v in c.get("tz", {}).values() if v > 200]
                if tz and "cpu_temp" not in s:
                    s["cpu_temp"] = round(max(tz) - 273.15)
                    s["cpu_temp_src"] = "acpi"
            except Exception as exc:
                s["pdh_error"] = str(exc)
            if s.get("gpu_active"):
                nv_awake_until = t0 + 5.0
            if t0 < nv_awake_until:
                if self.nvml is None:
                    self.nvml = NVML()
                try:
                    s.update({"gpu_" + k: v for k, v in self.nvml.read().items()})
                except Exception:
                    pass
                if "gpu_throttle" in s:
                    s["gpu_throttle_txt"] = throttle_text(s["gpu_throttle"])
                if "gpu_temp" not in s and "gpu_temp_nv" in s:
                    s["gpu_temp"] = s["gpu_temp_nv"]
                s["gpu_state"] = "active"
            else:
                s["gpu_state"] = "sleep"
            vm = psutil.virtual_memory()
            s["ram_used"], s["ram_total"] = round(vm.used / 2 ** 30, 1), round(vm.total / 2 ** 30, 1)
            net = psutil.net_io_counters()
            s["net_down"] = round((net.bytes_recv - last_net.bytes_recv) / dt / 1024)
            s["net_up"] = round((net.bytes_sent - last_net.bytes_sent) / dt / 1024)
            last_net = net
            try:
                disk = psutil.disk_io_counters()
                s["disk_read"] = round((disk.read_bytes - last_disk.read_bytes) / dt / 2 ** 20, 1)
                s["disk_write"] = round((disk.write_bytes - last_disk.write_bytes) / dt / 2 ** 20, 1)
                last_disk = disk
            except (AttributeError, TypeError):
                pass
            try:
                du = psutil.disk_usage("C:\\")
                s["disk_used"], s["disk_total"] = round(du.used / 2 ** 30), round(du.total / 2 ** 30)
            except OSError:
                pass
            try:  # disk basina okuma/yazma hizi ve doluluk (PhysicalDriveN)
                per = psutil.disk_io_counters(perdisk=True) or {}
                io = {}
                for name, cur in per.items():
                    prev = last_per.get(name)
                    if prev and name.startswith("PhysicalDrive"):
                        io[name[13:]] = {"r": round((cur.read_bytes - prev.read_bytes) / dt / 2 ** 20, 1),
                                         "w": round((cur.write_bytes - prev.write_bytes) / dt / 2 ** 20, 1),
                                         "busy": round(min(100.0, (cur.read_time + cur.write_time - prev.read_time
                                                                   - prev.write_time) / (dt * 10.0)), 0)}
                s["disk_io"] = io
                last_per = per
            except Exception:
                pass
            self._disk_health(t0)
            if self.disks:
                s["disks"] = self.disks
            s["battery"] = power_status()
            for k, h in self.history.items():
                if k in s:
                    h.append(s[k])
            self.snapshot = s
            self.seq += 1
            for fn in list(self.listeners):
                try:
                    fn(s, dt)
                except Exception:
                    pass
            spare = 1.0 - (time.monotonic() - t0)
            if spare > 0:
                time.sleep(spare)

    def payload(self):
        return {"now": self.snapshot, "hist": {k: list(v) for k, v in self.history.items()}}
