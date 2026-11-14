# -*- coding: utf-8 -*-
"""Klavye RGB - Monster / Clevo dizustu klavyeleri icin ozel renk modlari.

Control Center'in kendi kitapligi (InsydeDCHU.dll) uzerinden klavye rengini ayarlar.
Bu dosya motor ve donanim katmanidir; uygulama control_center.py ile baslar.
"""
import colorsys
import ctypes
import json
import math
import os
import sys
import threading
import time

c_void_p = ctypes.c_void_p
c_int = ctypes.c_int

import donanim

APP_NAME = "KendiControlCenter"
_APPDATA = os.environ.get("APPDATA", os.path.expanduser("~"))
CONFIG_DIR = os.path.join(_APPDATA, APP_NAME)
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
OLD_CONFIG_PATH = os.path.join(_APPDATA, "KlavyeRGB", "config.json")  # eski Klavye RGB ayarlari tasinir

# (kimlik, ad, palet kullanir mi, hiz etiketi, aciklama)
MODES = [
    ("sabit", "Sabit renk", True, None, "Paletteki ilk renk sabit yanar."),
    ("nefes", "Nefes alma", True, "Hız", "Işık yavaşça yanıp söner; her nefeste paletteki sıradaki renge geçer."),
    ("gecis", "Renk geçişi", True, "Hız", "Paletteki renkler arasında yumuşak geçiş yapar."),
    ("gokkusagi", "Gökkuşağı", False, "Hız", "Tüm renk çemberini dolaşır."),
    ("nabiz", "Nabız", True, "Hız", "Kalp atışı gibi çift vuruş; her atışta sıradaki renk."),
    ("ses", "Ses / müzik", True, "Tepki hızı", "Bilgisayardan çıkan sese göre: sessizken ilk renk, yüksek seste son renk."),
    ("sistem", "Sistem durumu", True, None, "Seçtiğin değere göre: düşükken ilk renk, yüksekken son renk."),
    ("ekran", "Ekran rengi", False, "Tepki hızı", "Ekrandaki baskın rengi klavyeye yansıtır."),
]
MODE_IDS = [m[0] for m in MODES]
SOURCES = [
    ("cpu_temp", "İşlemci sıcaklığı (40-95 °C)"),
    ("gpu_temp", "Ekran kartı sıcaklığı (40-85 °C)"),
    ("cpu_load", "İşlemci kullanımı (%0-100)"),
    ("battery", "Pil seviyesi (%0-100)"),
]
DEFAULTS = {
    "mode": "gecis",
    "brightness": 100,
    "autostart": False,
    "modes": {
        "sabit": {"palette": ["#00a2ff"], "speed": 50},
        "nefes": {"palette": ["#ff2d55", "#7a5cff", "#00d1ff"], "speed": 45},
        "gecis": {"palette": ["#ff0040", "#ff8a00", "#00e0ff", "#7a00ff"], "speed": 50},
        "gokkusagi": {"palette": [], "speed": 50},
        "nabiz": {"palette": ["#ff0020"], "speed": 50},
        "ses": {"palette": ["#1b00ff", "#00e5ff", "#ff00c8", "#ff2a00"], "speed": 60},
        "sistem": {"palette": ["#0060ff", "#00ff60", "#ffd000", "#ff0000"], "speed": 50, "source": "cpu_temp"},
        "ekran": {"palette": [], "speed": 55},
    },
    "presets": {},
}


# ----------------------------------------------------------------------------- yardimcilar
def hex_to_rgb(h):
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def rgb_to_hex(c):
    return "#%02x%02x%02x" % (int(c[0]), int(c[1]), int(c[2]))


def clamp(x, lo=0.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


def mix(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


def scale(c, k):
    return (c[0] * k, c[1] * k, c[2] * k)


def sample(pal, x, loop):
    """Paletten renk ornekle. loop=True: x renk sayisi kadar birimde doner. loop=False: x 0..1."""
    n = len(pal)
    if n == 0:
        return (255, 255, 255)
    if n == 1:
        return pal[0]
    if loop:
        x = x % n
        i = int(x)
        return mix(pal[i], pal[(i + 1) % n], x - i)
    x = clamp(x) * (n - 1)
    i = min(int(x), n - 2)
    return mix(pal[i], pal[i + 1], x - i)


def period(speed, slow, fast):
    """speed 0..100 -> saniye cinsinden sure (ustel olcek)."""
    return slow * (fast / slow) ** (clamp(speed / 100.0))


# ----------------------------------------------------------------------------- donanim
# Klavye rengi (komut 103) ve sicakliklar (komut 12) ortak donanim katmanindan gelir.
Keyboard = donanim.DCHU


class GUID(ctypes.Structure):
    _fields_ = [("d1", ctypes.c_ulong), ("d2", ctypes.c_ushort), ("d3", ctypes.c_ushort), ("d4", ctypes.c_ubyte * 8)]


def _guid(s):
    g = GUID()
    ctypes.windll.ole32.CLSIDFromString(ctypes.c_wchar_p(s), ctypes.byref(g))
    return g


def _vcall(ptr, index, *argtypes):
    vtbl = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(c_void_p))).contents
    return ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p, *argtypes)(vtbl[index])


class AudioMeter:
    """Varsayilan hoparlor cikisinin anlik ses seviyesi (0..1). Kullanildigi is parcaciginda olusturulmali."""

    def __init__(self):
        ctypes.windll.ole32.CoInitializeEx(None, 0)
        self.meter = None
        self.opened = 0.0

    def _release(self, p):
        if p:
            _vcall(p, 2)(p)

    def _open(self):
        self._release(self.meter)
        self.meter = None
        ole32 = ctypes.windll.ole32
        clsid = _guid("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
        iid_enum = _guid("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
        iid_meter = _guid("{C02216F6-8C67-4B5B-9D00-D008E73E0064}")
        enum = c_void_p()
        ole32.CoCreateInstance.argtypes = [c_void_p, c_void_p, ctypes.c_ulong, c_void_p, c_void_p]
        if ole32.CoCreateInstance(ctypes.byref(clsid), None, 23, ctypes.byref(iid_enum), ctypes.byref(enum)) != 0:
            return
        dev = c_void_p()
        try:
            if _vcall(enum, 4, c_int, c_int, c_void_p)(enum, 0, 1, ctypes.byref(dev)) != 0:
                return
            meter = c_void_p()
            if _vcall(dev, 3, c_void_p, ctypes.c_ulong, c_void_p, c_void_p)(
                    dev, ctypes.byref(iid_meter), 23, None, ctypes.byref(meter)) == 0:
                self.meter = meter
        finally:
            self._release(dev)
            self._release(enum)

    def peak(self):
        now = time.monotonic()
        if self.meter is None or now - self.opened > 5.0:  # varsayilan cihaz degisirse yakala
            self.opened = now
            self._open()
        if self.meter is None:
            return 0.0
        v = ctypes.c_float()
        if _vcall(self.meter, 3, c_void_p)(self.meter, ctypes.byref(v)) != 0:
            self.meter = None
            return 0.0
        return float(v.value)


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32), ("biHeight", ctypes.c_int32),
                ("biPlanes", ctypes.c_uint16), ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
                ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32), ("biClrImportant", ctypes.c_uint32)]


class ScreenSampler:
    """Ekrani kucuk bir izgaraya indirip baskin rengi bulur."""
    W, H = 32, 18

    def __init__(self):
        u, g = ctypes.windll.user32, ctypes.windll.gdi32
        u.GetDC.restype = c_void_p
        u.GetDC.argtypes = [c_void_p]
        u.ReleaseDC.argtypes = [c_void_p, c_void_p]
        g.CreateCompatibleDC.restype = c_void_p
        g.CreateCompatibleDC.argtypes = [c_void_p]
        g.CreateCompatibleBitmap.restype = c_void_p
        g.CreateCompatibleBitmap.argtypes = [c_void_p, c_int, c_int]
        g.SelectObject.restype = c_void_p
        g.SelectObject.argtypes = [c_void_p, c_void_p]
        g.SetStretchBltMode.argtypes = [c_void_p, c_int]
        g.StretchBlt.argtypes = [c_void_p, c_int, c_int, c_int, c_int, c_void_p, c_int, c_int, c_int, c_int,
                                 ctypes.c_ulong]
        g.GetDIBits.argtypes = [c_void_p, c_void_p, ctypes.c_uint, ctypes.c_uint, c_void_p, c_void_p, ctypes.c_uint]
        g.DeleteObject.argtypes = [c_void_p]
        g.DeleteDC.argtypes = [c_void_p]
        self.u, self.g = u, g
        self.buf = (ctypes.c_ubyte * (self.W * self.H * 4))()
        self.bmi = BITMAPINFOHEADER(40, self.W, -self.H, 1, 32, 0, 0, 0, 0, 0, 0)

    def color(self):
        u, g = self.u, self.g
        sw, sh = u.GetSystemMetrics(0), u.GetSystemMetrics(1)
        screen = u.GetDC(None)
        mem = g.CreateCompatibleDC(screen)
        bmp = g.CreateCompatibleBitmap(screen, self.W, self.H)
        old = g.SelectObject(mem, bmp)
        try:
            g.SetStretchBltMode(mem, 4)  # HALFTONE: tum pikselleri ortalar
            g.StretchBlt(mem, 0, 0, self.W, self.H, screen, 0, 0, sw, sh, 0x00CC0020)
            g.SelectObject(mem, old)
            g.GetDIBits(mem, bmp, 0, self.H, self.buf, ctypes.byref(self.bmi), 0)
        finally:
            g.DeleteObject(bmp)
            g.DeleteDC(mem)
            u.ReleaseDC(None, screen)
        raw = bytes(self.buf)
        tr = tg = tb = tw = 0.0
        lum = 0.0
        for i in range(0, len(raw), 4):
            b, gr, r = raw[i], raw[i + 1], raw[i + 2]
            mx, mn = max(r, gr, b), min(r, gr, b)
            w = (mx - mn) * mx / 65025.0 + 0.02  # canli pikseller daha agir basar
            tr += r * w
            tg += gr * w
            tb += b * w
            tw += w
            lum += mx
        r, gr, b = tr / tw / 255.0, tg / tw / 255.0, tb / tw / 255.0
        h, s, v = colorsys.rgb_to_hsv(r, gr, b)
        avg = lum / (self.W * self.H) / 255.0
        s = clamp(s * 1.5)
        v = clamp(max(0.06, min(1.0, avg * 1.6 + 0.1)))
        r, gr, b = colorsys.hsv_to_rgb(h, s, v)
        return (r * 255, gr * 255, b * 255)


class FILETIME(ctypes.Structure):
    _fields_ = [("lo", ctypes.c_uint32), ("hi", ctypes.c_uint32)]


class POWERSTATUS(ctypes.Structure):
    _fields_ = [("ac", ctypes.c_ubyte), ("flag", ctypes.c_ubyte), ("percent", ctypes.c_ubyte),
                ("ssf", ctypes.c_ubyte), ("life", ctypes.c_uint32), ("full", ctypes.c_uint32)]


class SystemInfo:
    def __init__(self):
        self.last = None

    def cpu_load(self):
        idle, kern, user = FILETIME(), FILETIME(), FILETIME()
        ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user))
        cur = tuple((f.hi << 32) | f.lo for f in (idle, kern, user))
        prev, self.last = self.last, cur
        if not prev:
            return 0.0
        d_idle = cur[0] - prev[0]
        d_all = (cur[1] - prev[1]) + (cur[2] - prev[2])
        return clamp(1.0 - d_idle / d_all) if d_all > 0 else 0.0

    @staticmethod
    def battery():
        st = POWERSTATUS()
        ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(st))
        return 1.0 if st.percent > 100 else st.percent / 100.0


# ----------------------------------------------------------------------------- motor
class Engine(threading.Thread):
    FPS = 30

    def __init__(self, kb):
        super().__init__(daemon=True)
        self.kb = kb
        # (mod, palet[(r,g,b)..], hiz 0..100, kaynak, parlaklik 0..1) - arayuz tek seferde degistirir
        self.settings = ("sabit", ((255, 255, 255),), 50, "cpu_temp", 1.0)
        self.current = (0, 0, 0)
        self.info = ""
        self.value = None  # ses/sistem modlarinda 0..1 arasi olculen deger
        self.error = ""
        self.running = True

    def run(self):
        audio = screen = None
        sysinfo = SystemInfo()
        phase = 0.0
        level = 0.0
        gain = 0.2
        sys_val, sys_target, sys_at = 0.0, 0.0, 0.0
        scr, scr_target, scr_at = (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), 0.0
        sent, sent_at = None, 0.0
        last = time.monotonic()
        while self.running:
            now = time.monotonic()
            dt = min(now - last, 0.5)
            last = now
            mode, pal, speed, source, bright = self.settings
            value = None
            try:
                if mode == "sabit":
                    col = pal[0] if pal else (255, 255, 255)
                    self.info = ""
                elif mode == "nefes":
                    phase += dt / period(speed, 9.0, 1.0)
                    x = phase % 1.0
                    env = 0.03 + 0.97 * math.sin(math.pi * x) ** 2
                    col = scale(pal[int(phase) % len(pal)] if pal else (255, 255, 255), env)
                    self.info = ""
                elif mode == "gecis":
                    phase += dt / period(speed, 12.0, 0.4)
                    col = sample(pal, phase, True)
                    self.info = ""
                elif mode == "gokkusagi":
                    phase += dt / period(speed, 40.0, 2.0)
                    r, g, b = colorsys.hsv_to_rgb(phase % 1.0, 1.0, 1.0)
                    col = (r * 255, g * 255, b * 255)
                    self.info = ""
                elif mode == "nabiz":
                    phase += dt / period(speed, 2.2, 0.45)
                    x = phase % 1.0
                    env = max(math.exp(-((x - 0.12) / 0.05) ** 2), 0.65 * math.exp(-((x - 0.34) / 0.07) ** 2))
                    col = scale(pal[int(phase) % len(pal)] if pal else (255, 0, 0), 0.06 + 0.94 * env)
                    self.info = ""
                elif mode == "ses":
                    if audio is None:
                        audio = AudioMeter()
                    p = audio.peak()
                    gain = max(gain * (1.0 - 0.08 * dt), p, 0.05)  # sese gore otomatik hassasiyet
                    x = clamp(p / gain) ** 1.4
                    fall = period(speed, 1.2, 0.08)
                    level = x if x > level else max(x, level - dt / fall)
                    col = scale(sample(pal, level, False), 0.12 + 0.88 * level)
                    value = level
                    self.info = "Ses seviyesi: %%%d" % round(p * 100)
                elif mode == "sistem":
                    if now - sys_at > 1.0:
                        sys_at = now
                        if source == "cpu_load":
                            v = sysinfo.cpu_load()
                            sys_target, self.info = v, "İşlemci kullanımı: %%%d" % round(v * 100)
                        elif source == "battery":
                            v = sysinfo.battery()
                            sys_target, self.info = v, "Pil: %%%d" % round(v * 100)
                        else:
                            cpu, gpu = self.kb.temps()
                            if source == "gpu_temp":
                                sys_target, self.info = clamp((gpu - 40) / 45.0), "Ekran kartı: %d °C" % gpu
                            else:
                                sys_target, self.info = clamp((cpu - 40) / 55.0), "İşlemci: %d °C" % cpu
                    sys_val += (sys_target - sys_val) * min(1.0, dt * 2.0)
                    col = sample(pal, sys_val, False)
                    value = sys_val
                elif mode == "ekran":
                    if now - scr_at > 0.12:
                        scr_at = now
                        if screen is None:
                            screen = ScreenSampler()
                        scr_target = screen.color()
                    k = min(1.0, dt / period(speed, 1.5, 0.05))
                    scr = mix(scr, scr_target, k)
                    col = scr
                    self.info = ""
                else:
                    col = (255, 255, 255)
                out = tuple(int(clamp(c * bright / 255.0) * 255 + 0.5) for c in col)
                self.current = out
                self.value = value
                if out != sent or now - sent_at > 1.0:  # uyku/Fn tusu sonrasi rengi geri getirmek icin tekrar yolla
                    self.kb.set_color(*out)
                    sent, sent_at = out, now
                self.error = ""
            except Exception as exc:  # motor hic durmasin
                self.error = "%s: %s" % (type(exc).__name__, exc)
                time.sleep(0.5)
            spare = 1.0 / self.FPS - (time.monotonic() - now)
            if spare > 0:
                time.sleep(spare)


# ----------------------------------------------------------------------------- ayarlar
def load_config():
    cfg = json.loads(json.dumps(DEFAULTS))
    path = CONFIG_PATH if os.path.exists(CONFIG_PATH) else OLD_CONFIG_PATH
    try:
        with open(path, "r", encoding="utf-8") as f:
            saved = json.load(f)
        if isinstance(saved.get("cc"), dict):
            cfg["cc"] = saved["cc"]
        for key in ("mode", "brightness", "autostart", "presets"):
            if key in saved:
                cfg[key] = saved[key]
        for mid, vals in saved.get("modes", {}).items():
            if mid in cfg["modes"] and isinstance(vals, dict):
                cfg["modes"][mid].update(vals)
    except (OSError, ValueError):
        pass
    if cfg["mode"] not in MODE_IDS:
        cfg["mode"] = "gecis"
    return cfg


def save_config(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_PATH)


def snapshot(cfg):
    m = cfg["modes"][cfg["mode"]]
    pal = tuple(hex_to_rgb(h) for h in m.get("palette", []))
    return (cfg["mode"], pal, m.get("speed", 50), m.get("source", "cpu_temp"), cfg["brightness"] / 100.0)


def set_autostart(enabled, script):
    import winreg
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                         winreg.KEY_SET_VALUE)
    try:
        if enabled:
            exe = sys.executable
            pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
            if os.path.exists(pyw):
                exe = pyw
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ,
                              '"%s" "%s" --minimized' % (exe, os.path.abspath(script)))
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
    finally:
        winreg.CloseKey(key)


def selftest(kb):
    """Arayuz acmadan tum kaynaklari bir kez okur."""
    print("sicaklik (islemci, ekran karti):", kb.temps())
    s = SystemInfo()
    s.cpu_load()
    time.sleep(0.5)
    print("islemci kullanimi: %.2f  pil: %.2f" % (s.cpu_load(), s.battery()))
    print("ekran rengi:", rgb_to_hex(ScreenSampler().color()))
    a = AudioMeter()
    peaks = []
    for _ in range(10):
        peaks.append(round(a.peak(), 3))
        time.sleep(0.05)
    print("ses olcer:", "acildi" if a.meter else "ACILAMADI", peaks)
    eng = Engine(kb)
    for mid in MODE_IDS:
        cfg = json.loads(json.dumps(DEFAULTS))
        cfg["mode"] = mid
        eng.settings = snapshot(cfg)
        if not eng.is_alive():
            eng.start()
        time.sleep(1.5)
        print("mod %-10s renk=%s hata=%r bilgi=%r" % (mid, rgb_to_hex(eng.current), eng.error, eng.info))
    eng.running = False
    eng.join(2)
    kb.set_color(255, 255, 255)


def main():
    """Motoru arayuzsuz sinar. Uygulamanin kendisi control_center.py ile baslar."""
    selftest(Keyboard())


if __name__ == "__main__":
    main()
