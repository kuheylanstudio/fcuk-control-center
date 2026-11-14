# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""Arayuz penceresi: kendi baslik cubugu, simgesi ve gorev cubugu dugmesi olan ayri surec
(control_center.py --window). Icerik pywebview ile gomulu WebView2'de gosterilir; Edge'in --app penceresi,
adres cubugu ve ayri Edge profili artik gerekmez.

Neden ayri surec: pencere kapaninca yalnizca bu surec biter; motor ve tepsi etkilenmez. Tepsiden "Ac" ya da
ikinci bir baslatma yeni pencere acmaz, var olani one getirir (tek ornek).
"""
import ctypes
import ctypes.wintypes as wt
import os
import webbrowser

TITLE = "FCUK Control Center"
MUTEX = "Local\\FCUKControlCenterPencere"
SIZE = (1320, 860)
MIN_SIZE = (960, 640)
ERROR_ALREADY_EXISTS = 183
SW_RESTORE = 9

u32 = ctypes.WinDLL("user32", use_last_error=True)
k32 = ctypes.WinDLL("kernel32", use_last_error=True)
u32.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
u32.FindWindowW.restype = wt.HWND
u32.IsIconic.argtypes = [wt.HWND]
u32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
u32.SetForegroundWindow.argtypes = [wt.HWND]
k32.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR]
k32.CreateMutexW.restype = wt.HANDLE

_mutex = None  # surec boyunca acik kalir


def single_instance():
    """True: bu surec tek pencere sahibidir. False: pencere zaten var, one getirildi."""
    global _mutex
    _mutex = k32.CreateMutexW(None, False, MUTEX)
    if ctypes.get_last_error() != ERROR_ALREADY_EXISTS:
        return True
    hwnd = u32.FindWindowW(None, TITLE)
    if hwnd:
        if u32.IsIconic(hwnd):
            u32.ShowWindow(hwnd, SW_RESTORE)
        u32.SetForegroundWindow(hwnd)
    return False


class Api:
    """Sayfanin (window.pywebview.api) cagirabildigi tek yuzey: yalnizca bu iki islem."""

    def __init__(self):
        self.window = None

    def kapat(self):
        if self.window is not None:
            self.window.destroy()

    def ac(self, url):
        """Dis baglanti: yalnizca https, varsayilan tarayicida (pencere icinde acilmaz)."""
        if isinstance(url, str) and url.startswith("https://"):
            webbrowser.open(url)


def fit_size():
    """(genislik, yukseklik, x, y): istenen boyutu (mantiksal piksel) calisma alanina sigdirip ortalar.
    pywebview boyutu DPI ile carpar ve sigdirmaz: %125 olcekte 1320x860, 1080p ekrandan tasardi
    (Edge bunu kendisi sinirlardi)."""
    try:
        u32.SetProcessDPIAware()
        scale = u32.GetDpiForSystem() / 96.0
        area = wt.RECT()
        if not u32.SystemParametersInfoW(0x30, 0, ctypes.byref(area), 0):  # SPI_GETWORKAREA
            return SIZE + (None, None)
        aw, ah = (area.right - area.left) / scale, (area.bottom - area.top) / scale
        w, h = max(min(SIZE[0], int(aw * 0.94)), 640), max(min(SIZE[1], int(ah * 0.94)), 480)
        return w, h, int(area.left / scale + (aw - w) / 2), int(area.top / scale + (ah - h) / 2)
    except (OSError, AttributeError):
        return SIZE + (None, None)


def run(url, storage, icon=None):
    """Pencereyi acar ve kapanana dek doner. pywebview ya da WebView2 yoksa ImportError/Exception firlatir;
    cagiran Edge penceresine duser."""
    import webview  # gec yukleme: --window disindaki modlar pythonnet'i yuklemez
    api = Api()
    w, h, x, y = fit_size()
    api.window = webview.create_window(TITLE, url, width=w, height=h, x=x, y=y,
                                       min_size=(min(MIN_SIZE[0], w), min(MIN_SIZE[1], h)),
                                       js_api=api, background_color="#0a0c0f")
    os.makedirs(storage, exist_ok=True)
    # edgechromium zorunlu: yoksa pywebview sessizce eski IE motoruna (mshtml) duserdi.
    webview.start(gui="edgechromium", storage_path=storage, private_mode=False,
                  icon=icon if icon and os.path.isfile(icon) else None)
