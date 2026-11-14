# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""Klavye RGB - Monster / Clevo ve MSI dizustu klavyeleri icin ozel renk modlari.

Clevo'da Control Center'in kendi kitapligi (InsydeDCHU.dll), MSI'da USB HID klavye (msi_klavye.py), Acer
Predator/Nitro'da WMI (acer_predator.AcerGaming, 4 bolge) uzerinden klavye rengini ayarlar; motor icin hepsi ayni
set_color(r, g, b) cagrisidir.
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

import ceviri
import donanim
import oyun

APP_NAME = "FCUKControlCenter"
_APPDATA = os.environ.get("APPDATA", os.path.expanduser("~"))
USER_DIR = os.path.join(_APPDATA, APP_NAME)
USER_CONFIG_PATH = os.path.join(USER_DIR, "config.json")
CONFIG_DIR = USER_DIR      # yonetici motorda set_data_dir() ile Program Files altindaki veri klasorune doner
CONFIG_PATH = USER_CONFIG_PATH
PREV_CONFIG_PATH = os.path.join(_APPDATA, "KendiControlCenter", "config.json")  # onceki surumun ayarlari tasinir
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
    ("oyun", "Oyun tepkisi", True, "Tepki hızı",
     "Can yüksekken yeşil, azaldıkça kırmızıya döner; %35'in altında kalp atışı. Ateş, yetenek, kill ve "
     "ölümde parlar. LoL ve Counter-Strike 2."),
    # Yalnizca bolgeli klavyede (Acer Predator/Nitro 4 bolge) listelenir: her bolgeye ayri sabit renk
    ("bolgeler", "Bölge renkleri", True, None, "Klavyenin dört bölgesi soldan sağa ayrı renkte sabit yanar."),
]
MODE_IDS = [m[0] for m in MODES]
SOURCES = [
    ("cpu_temp", "İşlemci sıcaklığı (40-95 °C)"),
    ("gpu_temp", "Ekran kartı sıcaklığı (40-85 °C)"),
    ("cpu_load", "İşlemci kullanımı (%0-100)"),
    ("battery", "Pil seviyesi (%0-100)"),
]
# Oyun modu tus duzenleri ve renk yuvalari (palet sirasi sabittir)
GAME_LAYOUTS = ["lol", "cs"]
GAME_SLOTS_USED = {"lol": [0, 1, 2, 3, 4, 5, 6], "cs": [0, 1]}  # duzende kullanilan yuvalar
GAME_SLOTS = ["bg", "fire", "q", "w", "e", "r", "spell"]
DEFAULTS = {
    "mode": "gecis",
    "brightness": 100,
    "autostart": False,
    "lang": "auto",  # "auto": Windows ulke ayarina gore (ceviri.detect), ya da dil kodu
    "modes": {
        "sabit": {"palette": ["#00a2ff"], "speed": 50},
        "nefes": {"palette": ["#ff2d55", "#7a5cff", "#00d1ff"], "speed": 45},
        "gecis": {"palette": ["#ff0040", "#ff8a00", "#00e0ff", "#7a00ff"], "speed": 50},
        "gokkusagi": {"palette": [], "speed": 50},
        "nabiz": {"palette": ["#ff0020"], "speed": 50},
        "ses": {"palette": ["#1b00ff", "#00e5ff", "#ff00c8", "#ff2a00"], "speed": 60},
        "sistem": {"palette": ["#0060ff", "#00ff60", "#ffd000", "#ff0000"], "speed": 50, "source": "cpu_temp"},
        "ekran": {"palette": [], "speed": 55},
        "oyun": {"palette": ["#140a33", "#ffffff", "#00b4ff", "#00ff6a", "#ffb000", "#ff0040", "#c000ff"],
                 "speed": 55, "keys": "lol"},
        "bolgeler": {"palette": ["#ff0040", "#ff8a00", "#00e0ff", "#7a00ff"], "speed": 50},
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


# ----------------------------------------------------------------------------- oyun efektleri
# LoL / CS2 olaylarinin renkleri ve sureleri (sn): (renk ya da None=gokkusagi, sure, bicim)
GAME_EVENTS = {
    "kill": ((255, 196, 0), 0.9, "pop"),
    "assist": ((0, 229, 255), 0.5, "pop"),
    "death": ((255, 0, 0), 1.4, "pop"),
    "objective": ((160, 64, 255), 1.4, "double"),
    "multi2": (None, 1.2, "rainbow"),
    "multi3": (None, 1.8, "rainbow"),
    "multi4": (None, 2.4, "rainbow"),
    "multi5": (None, 3.5, "rainbow"),
    "ace": ((255, 255, 255), 1.6, "double"),
    "win": (None, 5.0, "rainbow"),
    "lose": ((255, 0, 0), 3.0, "slow"),
    "hit": ((255, 0, 0), 0.35, "pop"),          # CS2: hasar aldin
    "bomb": ((255, 0, 0), 1.5, "double"),       # CS2: bomba kuruldu
    "defused": ((0, 120, 255), 1.5, "double"),  # CS2: bomba imha edildi
    "exploded": ((255, 120, 0), 2.0, "pop"),    # CS2: bomba patladi
}
HEALTH_GREEN = 0.5   # bu oranin ustunde tam yesil
HEALTH_BEAT = 0.35   # bu oran ve altinda kalp atisi


def health_color(h):
    """Can orani -> renk: %50 ve ustu yesil, %50'den %1'e dogru sariya ve kirmiziya kayar."""
    if h >= HEALTH_GREEN:
        return (0.0, 255.0, 0.0)
    t = clamp((HEALTH_GREEN - h) / (HEALTH_GREEN - 0.01))
    r, g, b = colorsys.hsv_to_rgb((1.0 - t) / 3.0, 1.0, 1.0)  # ton 120 derece -> 0 derece
    return (r * 255, g * 255, b * 255)


def heartbeat(x):
    """Kalp atisi bicimi (0..1 periyot): guclu vurus + daha zayif ikinci vurus."""
    return max(math.exp(-((x - 0.12) / 0.06) ** 2), 0.65 * math.exp(-((x - 0.34) / 0.08) ** 2))


def game_envelope(shape, x):
    """Bir parlamanin 0..1 suresi boyunca siddeti (0..1)."""
    if shape == "pop":
        return (1.0 - x) ** 2
    if shape == "double":  # ulti / hedef: iki guclu vurus
        return max(math.exp(-(x / 0.12) ** 2), 0.9 *math.exp(-((x - 0.35) / 0.1) ** 2), (1.0 - x) ** 3 * 0.5)
    if shape == "rainbow":
        return 1.0 - x ** 3
    if shape == "slow":
        return math.sin(math.pi * x) ** 2
    return 1.0 - x


class GameFx:
    """Oyun modunun durumu -> renk. Taban renk cana gore (yesil -> kirmizi), uzerine aksiyon parlamalari.

    Her karede yapilan is: birkac GetAsyncKeyState cagrisi ve bir kac carpma; ag/disk isi ayri is
    parcaciklarinda (LoL yoklamasi) ya da yalnizca oyun veri yolladiginda (CS2) yapilir."""
    SLOT = {name: i for i, name in enumerate(GAME_SLOTS)}

    def __init__(self):
        self.keys = oyun.KeyWatcher()
        self.sources = {}  # duzen -> kaynak (ilk kullanildiginda olusur)
        self.flashes = []  # [renk ya da None, baslangic, sure, bicim]
        self.shown = None  # yumusatilmis can orani
        self.beat = 0.0
        self.last = None
        self.on = False

    def source(self, layout):
        src = self.sources.get(layout)
        if src is None:
            if layout == "lol":
                src = oyun.LolClient()
                src.start()
            else:
                src = oyun.CsClient()
            self.sources[layout] = src
        return src

    def flash(self, col, now, dur, shape):
        self.flashes.append([col, now, dur, shape])
        del self.flashes[:-6]

    def frame(self, pal, speed, layout, now):
        """(renk, bilgi metni, olculen deger ya da None)."""
        self.on = True
        if layout not in GAME_LAYOUTS:
            layout = GAME_LAYOUTS[0]
        dt = 0.0 if self.last is None else min(0.5, max(0.0, now - self.last))
        self.last = now
        pal = list(pal) + [(255, 255, 255)] * (len(GAME_SLOTS) - len(pal))
        src = self.source(layout)
        for name, other in self.sources.items():  # yalnizca secili oyun dinlenir
            other.wanted = name == layout
        if isinstance(src, oyun.CsClient):
            src.tick(now)
        fade = period(speed, 1.0, 0.12)
        pressed, held = self.keys.poll(layout, now)
        for fx in pressed:
            col = pal[self.SLOT[fx]]
            if fx == "r":
                self.flash(col, now, fade * 3.0, "double")
            elif fx == "fire":
                self.flash(col, now, fade * 0.7, "pop")
            else:
                self.flash(col, now, fade, "pop")
        live = src.connected
        for ev in src.pop_events():
            col, dur, shape = GAME_EVENTS.get(ev, ((255, 255, 255), 0.6, "pop"))
            self.flash(col, now, dur, shape)
        health = src.health if live else None
        if health is None:
            self.shown = None
            base = pal[0]
        else:
            self.shown = health if self.shown is None else self.shown + (health - self.shown) * min(1.0, dt * 6.0)
            h = self.shown
            if src.dead or health <= 0.0:
                base = (25.0, 25.0, 30.0)
            else:
                base = health_color(h)
                if h <= HEALTH_BEAT:  # can azaldikca hizlanan kalp atisi (yaklasik 65 -> 160 vurus/dk)
                    self.beat += dt * (1.1 + clamp((HEALTH_BEAT - h) / (HEALTH_BEAT - 0.01)) * 1.6)
                    base = scale(base, 0.22 + 0.78 * heartbeat(self.beat % 1.0))
            if src.burning:
                base = mix(base, (255, 90, 0), 0.45 + 0.35 * math.sin(now * 2 * math.pi * 7) ** 2)
        col = base
        alive = []
        for f in self.flashes:
            x = (now - f[1]) / f[2]
            if x >= 1.0:
                continue
            alive.append(f)
            c = f[0]
            if c is None:
                r, g, b = colorsys.hsv_to_rgb((now * 0.9 + f[1]) % 1.0, 1.0, 1.0)
                c = (r * 255, g * 255, b * 255)
            col = mix(col, c, clamp(game_envelope(f[3], x)))
        self.flashes = alive
        if "fire" in held:  # otomatik silah: basili tutuldukca titresin
            col = mix(col, pal[1], 0.55 + 0.45 * math.sin(now * 2 * math.pi * 12) ** 2)
        if live and src.flashed > 0.0:  # CS2 flas bombasi: gozun kadar klavye de beyaz
            col = mix(col, (255, 255, 255), src.flashed)
        return col, self.describe(layout, src, live, health), health

    def warning(self, layout):
        """Kullaniciya gosterilecek uyari: on plandaki program tanimlanamiyorsa tus tepkisi calismaz."""
        if self.keys.unrecognized:
            return ceviri.t("info.gameUnknown", game="LoL" if layout == "lol" else "CS2")
        return ""

    def describe(self, layout, src, live, health):
        game = "LoL" if layout == "lol" else "CS2"
        if live and health is not None:
            if src.dead or health <= 0.0:
                return ceviri.t("info.gameDead", game=game)
            return ceviri.t("info.gameLive", game=game, v=ceviri.pct(round(health * 100)))
        if layout == "cs" and src.problem == "nocfg":
            return ceviri.t("info.csNoCfg")
        if layout == "cs" and src.problem == "port":
            return ceviri.t("info.csPort", port=oyun.CS_PORT)
        if self.keys.active(layout):
            return ceviri.t("info.lolWait" if layout == "lol" else "info.csWait")
        return ceviri.t("info.gameWaitLol" if layout == "lol" else "info.gameWaitCs")

    def stop(self):
        self.on = False
        self.last = None
        for src in self.sources.values():
            src.wanted = False
            if isinstance(src, oyun.CsClient):
                src.tick(time.monotonic())


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
        self.warn = ""  # kalici olmayan uyari (ornegin oyun penceresi tanimlanamadi)
        self.running = True

    def run(self):
        audio = screen = game = None
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
            warn = ""
            kb_ok = getattr(self.kb, "kb_available", getattr(self.kb, "available", True))  # isik ayri olabilir (Alienware, Lenovo, MSI USB klavye)
            zones = None
            if not kb_ok and mode in ("ses", "ekran", "sistem", "oyun"):
                mode = "sabit"  # klavye isigi yok: ses/ekran ornekleme ve olcum bosuna calismasin
            if mode != "oyun" and game is not None and game.on:
                game.stop()  # oyun kaynaklari yalnizca Oyun modundayken dinlenir (moddan cikista bir kez)
            try:
                if mode == "sabit":
                    col = pal[0] if pal else (255, 255, 255)
                    self.info = ""
                elif mode == "bolgeler":  # bolgeli klavye: her bolge kendi rengi; yoksa ilk renk sabit
                    col = pal[0] if pal else (255, 255, 255)
                    if pal and hasattr(self.kb, "set_zones"):
                        zones = tuple(pal[min(i, len(pal) - 1)] for i in range(4))
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
                    self.info = ceviri.t("info.audio", v=ceviri.pct(round(p * 100)))
                elif mode == "sistem":
                    if now - sys_at > 1.0:
                        sys_at = now
                        if source == "cpu_load":
                            v = sysinfo.cpu_load()
                            sys_target, self.info = v, ceviri.t("info.cpuLoad", v=ceviri.pct(round(v * 100)))
                        elif source == "battery":
                            v = sysinfo.battery()
                            sys_target, self.info = v, ceviri.t("info.battery", v=ceviri.pct(round(v * 100)))
                        else:
                            cpu, gpu = self.kb.temps()
                            if source == "gpu_temp":
                                sys_target, self.info = clamp((gpu - 40) / 45.0), ceviri.t("info.gpuTemp", t=int(gpu))
                            else:
                                sys_target, self.info = clamp((cpu - 40) / 55.0), ceviri.t("info.cpuTemp", t=int(cpu))
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
                elif mode == "oyun":
                    if game is None:
                        game = GameFx()
                    col, self.info, value = game.frame(pal, speed, source, now)
                    warn = game.warning(source if source in GAME_LAYOUTS else GAME_LAYOUTS[0])
                else:
                    col = (255, 255, 255)
                out = tuple(int(clamp(c * bright / 255.0) * 255 + 0.5) for c in col)
                self.current = out
                self.value = value
                self.warn = warn
                key = out if zones is None else tuple(
                    tuple(int(clamp(c * bright / 255.0) * 255 + 0.5) for c in z) for z in zones)
                if key != sent or now - sent_at > 1.0:  # uyku/Fn tusu sonrasi rengi geri getirmek icin tekrar yolla
                    if zones is None:
                        self.kb.set_color(*out)
                    else:
                        self.kb.set_zones(key)
                    sent, sent_at = key, now
                self.error = ""
            except Exception as exc:  # motor hic durmasin
                self.error = "%s: %s" % (type(exc).__name__, exc)
                time.sleep(0.5)
            # Klavye isigi yoksa yalnizca arayuzun vurgu rengi icin saniyede 2 kare (islemciyi yormaz)
            spare = 1.0 / (self.FPS if kb_ok else 2) - (time.monotonic() - now)
            if spare > 0:
                time.sleep(spare)


# ----------------------------------------------------------------------------- ayarlar
def set_data_dir(path):
    """Ayar ve gunluk klasorunu degistirir. Yonetici motor kullanicinin yazabildigi %APPDATA%'ya yazmaz:
    orada bir baglanti (junction/symlink) yonetici yazmasini istenen herhangi bir dosyaya yonlendirebilir."""
    global CONFIG_DIR, CONFIG_PATH
    CONFIG_DIR = path
    CONFIG_PATH = os.path.join(path, "config.json")


def read_config():
    """Kayitli ayarlari HAM olarak okur: (sozluk ya da None, sorun metni). Hicbir girdide hata firlatmaz;
    alanlarin dogrulanmasi cagiranin isidir (control_center.sanitize_loaded).
    Okunamayan/bozuk dosya config.bozuk.json adiyla kenara alinir ki sonraki kayit onu ezmesin."""
    paths = []
    for p in (CONFIG_PATH, USER_CONFIG_PATH, PREV_CONFIG_PATH, OLD_CONFIG_PATH):  # yonetici motor ilk acilista kullanicininkini tasir
        if p not in paths:
            paths.append(p)
    for path in paths:
        if not os.path.exists(path):
            continue
        problem = ""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data, ""
            problem = "ayar dosyası beklenen biçimde değil"
        except (OSError, ValueError, RecursionError) as exc:
            problem = "ayar dosyası okunamadı (%s)" % type(exc).__name__
        if path == CONFIG_PATH:
            try:
                os.replace(path, os.path.join(CONFIG_DIR, "config.bozuk.json"))
                problem += "; eski dosya config.bozuk.json olarak saklandı"
            except OSError:
                pass
        return None, problem
    return None, ""


def save_config(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_PATH)


def snapshot(cfg):
    m = cfg["modes"][cfg["mode"]]
    pal = tuple(hex_to_rgb(h) for h in m.get("palette", []))
    src = m.get("keys", "lol") if cfg["mode"] == "oyun" else m.get("source", "cpu_temp")  # oyunda: tus duzeni
    return (cfg["mode"], pal, m.get("speed", 50), src, cfg["brightness"] / 100.0)


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
