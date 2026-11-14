# -*- coding: utf-8 -*-
"""Fn tuslari ve ekran bildirimi (OSD): Monster/Clevo "Fn hotkeys and OSD" (FnKey.exe) yerine.

Kanal: AcpiBridge surucusu (ACPI\\CLV0001, arayuz {86994c74-...}). Denetleyici bir Fn tusuna basildiginda
ACPI bildirimi uretir; surucu bunu kayitli olaya isaret eder, deger IOCTL_ACPIBIOS_GET_NOTIFY_VALUE ile okunur.
(Kodlar ve IOCTL'ler Monster'in DCHUService.exe'sinden ve 14.11.2026 tus denemelerinden.)

Olculen davranis: touchpad, kamera, ucak modu, ses ve parlaklik tuslarini donanim/Windows KENDISI yapar;
bize yalnizca bildirim gelir. Klavye isigi tuslarini ise bizim RGB motorumuz uygular (yoksa motor ezer).
Bu modul normal yetkili tepsi surecinde calisir (OSD kullanici masaustunde gorunmeli).
"""
import ctypes
import threading
import time
import uuid
from ctypes import wintypes as wt

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
u32 = ctypes.WinDLL("user32", use_last_error=True)
gdi = ctypes.WinDLL("gdi32", use_last_error=True)
sapi = ctypes.WinDLL("setupapi", use_last_error=True)

BRIDGE_IF = "86994c74-ad43-4812-b7e7-0c420b5c5fd7"
IOCTL_WAIT_EVENT = 0x322404
IOCTL_GET_NOTIFY_VALUE = 0x322408

# Fn kodlari (Monster Abra A5 V21.1)
FN_TOUCHPAD = 0x5D      # Fn+F1 (touchpad'i donanim cevirir)
FN_SCREEN_OFF = 0xD7    # Fn+F2
FN_MUTE = 0xFB          # Fn+F3 (Windows'un kendi OSD'si var)
FN_VOLUME = 0xFA        # Fn+F5/F6 (Windows'un kendi OSD'si var)
FN_CAMERA_OFF = 0xF6    # Fn+F10
FN_CAMERA_ON = 0xF7
FN_AIRPLANE = 0x86      # Fn+F11
FN_KB_DOWN = 0x81       # Fn+ sayi takimi -
FN_KB_UP = 0x82         # Fn+ sayi takimi +
FN_KB_NEXT = 0x83       # Fn+ sayi takimi /
FN_KB_TOGGLE = 0x9F     # Fn+ sayi takimi *

k32.CreateFileW.restype = ctypes.c_void_p
k32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p, wt.DWORD, wt.DWORD, ctypes.c_void_p]
k32.CreateEventW.restype = ctypes.c_void_p
k32.CreateEventW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.BOOL, wt.LPCWSTR]
k32.DeviceIoControl.argtypes = [ctypes.c_void_p, wt.DWORD, ctypes.c_void_p, wt.DWORD, ctypes.c_void_p, wt.DWORD,
                                ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, wt.DWORD]
k32.WaitForSingleObject.restype = wt.DWORD
k32.CloseHandle.argtypes = [ctypes.c_void_p]
k32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
k32.GetModuleHandleW.restype = wt.HMODULE
sapi.SetupDiGetClassDevsW.restype = ctypes.c_void_p
sapi.SetupDiGetClassDevsW.argtypes = [ctypes.c_void_p, wt.LPCWSTR, wt.HWND, wt.DWORD]
sapi.SetupDiEnumDeviceInterfaces.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wt.DWORD, ctypes.c_void_p]
sapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wt.DWORD,
                                                  ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
sapi.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]


def log(msg):
    """CONFIG_DIR\\fn.log: dinleyici durumu, gelen kodlar ve hatalar (64 KB'yi gecince sifirlanir)."""
    try:
        import os
        import klavye_rgb as core
        p = os.path.join(core.CONFIG_DIR, "fn.log")
        mode = "w" if os.path.exists(p) and os.path.getsize(p) > 65536 else "a"
        with open(p, mode, encoding="utf-8") as f:
            f.write("%s %s\n" % (time.strftime("%d.%m %H:%M:%S"), msg))
    except Exception:
        pass


class _GUID(ctypes.Structure):
    _fields_ = [("d", ctypes.c_ubyte * 16)]


class _IFDATA(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("guid", _GUID), ("Flags", wt.DWORD), ("Reserved", ctypes.c_size_t)]


def bridge_path():
    g = _GUID()
    ctypes.memmove(g.d, uuid.UUID(BRIDGE_IF).bytes_le, 16)
    h = sapi.SetupDiGetClassDevsW(ctypes.byref(g), None, None, 0x12)  # DIGCF_PRESENT | DIGCF_DEVICEINTERFACE
    if not h or h == ctypes.c_void_p(-1).value:
        return None
    try:
        d = _IFDATA()
        d.cbSize = ctypes.sizeof(d)
        if not sapi.SetupDiEnumDeviceInterfaces(h, None, ctypes.byref(g), 0, ctypes.byref(d)):
            return None
        need = wt.DWORD()
        sapi.SetupDiGetDeviceInterfaceDetailW(h, ctypes.byref(d), None, 0, ctypes.byref(need), None)
        buf = ctypes.create_string_buffer(max(need.value, 8))
        ctypes.cast(buf, ctypes.POINTER(wt.DWORD))[0] = 8  # x64 SP_DEVICE_INTERFACE_DETAIL_DATA_W.cbSize
        if not sapi.SetupDiGetDeviceInterfaceDetailW(h, ctypes.byref(d), buf, need, None, None):
            return None
        return ctypes.wstring_at(ctypes.addressof(buf) + 4)
    finally:
        sapi.SetupDiDestroyDeviceInfoList(h)


class Listener(threading.Thread):
    """Fn bildirimlerini dinler, her kod icin on_key(kod) cagirir. Aygit yoksa bekleyip yeniden dener
    (uyku/uyanma sonrasi surucu yeniden baslayabilir)."""

    def __init__(self, on_key):
        super().__init__(daemon=True)
        self.on_key = on_key
        self.running = True

    def run(self):
        while self.running:
            try:
                self._session()
            except Exception as exc:
                log("dinleyici hatasi: %r" % exc)
            time.sleep(3)

    def _session(self):
        path = bridge_path()
        if not path:
            log("kopru aygiti bulunamadi")
            return
        h = k32.CreateFileW(path, 0xC0000000, 3, None, 3, 0, None)
        if not h or h == ctypes.c_void_p(-1).value:
            log("kopru acilamadi, hata %d" % ctypes.get_last_error())
            return
        ev = k32.CreateEventW(None, False, False, None)
        try:
            ret = wt.DWORD()
            handle = ctypes.c_void_p(ev)
            if not k32.DeviceIoControl(h, IOCTL_WAIT_EVENT, ctypes.byref(handle), 8, None, 0, ctypes.byref(ret), None):
                log("WAIT_EVENT kaydi basarisiz, hata %d" % ctypes.get_last_error())
                return
            log("dinleniyor")
            while self.running:
                r = k32.WaitForSingleObject(ev, 1000)
                if r == 0x102:  # zaman asimi
                    continue
                if r != 0:
                    return
                val = ctypes.c_int64(0)
                dummy = ctypes.c_int32(0)
                if not k32.DeviceIoControl(h, IOCTL_GET_NOTIFY_VALUE, ctypes.byref(dummy), 4, ctypes.byref(val), 8,
                                           ctypes.byref(ret), None):
                    return  # aygit gitti (uyku vb.): yeniden ac
                code = val.value & 0xFFFFFFFF
                log("kod 0x%X" % code)
                try:
                    self.on_key(code)
                except Exception as exc:
                    log("on_key hatasi: %r" % exc)
        finally:
            k32.CloseHandle(ev)
            k32.CloseHandle(h)


# ----------------------------------------------------------------------------- ekran bildirimi (OSD)
LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
WS_POPUP = 0x80000000
WS_EX_TOPMOST, WS_EX_TOOLWINDOW, WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_NOACTIVATE = 0x8, 0x80, 0x80000, 0x20, 0x8000000
WM_PAINT, WM_TIMER, WM_ERASEBKGND = 0x000F, 0x0113, 0x0014
SW_HIDE = 0
HWND_TOPMOST = -1
SWP_NOACTIVATE, SWP_SHOWWINDOW = 0x10, 0x40
LWA_ALPHA = 0x2
DT_CENTER, DT_VCENTER, DT_SINGLELINE = 0x1, 0x4, 0x20
TIMER_HIDE = 7


class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [("hdc", wt.HDC), ("fErase", wt.BOOL), ("rcPaint", wt.RECT), ("fRestore", wt.BOOL),
                ("fIncUpdate", wt.BOOL), ("rgbReserved", ctypes.c_byte * 32)]


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", wt.UINT), ("style", wt.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
                ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH), ("lpszMenuName", wt.LPCWSTR),
                ("lpszClassName", wt.LPCWSTR), ("hIconSm", wt.HICON)]


# Not: tepsi.py de user32 islevlerine argtypes atar; ayni tanimlar (ayni DLL nesnesi) catismasin diye
# bu modulde ayri bir user32 ornegi kullaniliyor.
u32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
u32.DefWindowProcW.restype = LRESULT
u32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
u32.CreateWindowExW.restype = wt.HWND
u32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
u32.SetLayeredWindowAttributes.argtypes = [wt.HWND, wt.COLORREF, wt.BYTE, wt.DWORD]
u32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.UINT]
u32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
u32.SetTimer.argtypes = [wt.HWND, ctypes.c_size_t, wt.UINT, ctypes.c_void_p]
u32.KillTimer.argtypes = [wt.HWND, ctypes.c_size_t]
u32.InvalidateRect.argtypes = [wt.HWND, ctypes.c_void_p, wt.BOOL]
u32.BeginPaint.argtypes = [wt.HWND, ctypes.POINTER(PAINTSTRUCT)]
u32.BeginPaint.restype = wt.HDC
u32.EndPaint.argtypes = [wt.HWND, ctypes.POINTER(PAINTSTRUCT)]
u32.GetClientRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
u32.FillRect.argtypes = [wt.HDC, ctypes.POINTER(wt.RECT), wt.HBRUSH]
u32.DrawTextW.argtypes = [wt.HDC, wt.LPCWSTR, ctypes.c_int, ctypes.POINTER(wt.RECT), wt.UINT]
u32.SystemParametersInfoW.argtypes = [wt.UINT, wt.UINT, ctypes.c_void_p, wt.UINT]
u32.GetDpiForSystem.restype = wt.UINT
u32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
u32.SetWindowRgn.argtypes = [wt.HWND, wt.HRGN, wt.BOOL]
gdi.CreateSolidBrush.argtypes = [wt.COLORREF]
gdi.CreateSolidBrush.restype = wt.HBRUSH
gdi.CreateFontW.restype = wt.HFONT
gdi.CreateFontW.argtypes = [ctypes.c_int] * 5 + [wt.DWORD] * 8 + [wt.LPCWSTR]
gdi.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
gdi.SelectObject.restype = wt.HGDIOBJ
gdi.SetTextColor.argtypes = [wt.HDC, wt.COLORREF]
gdi.SetBkMode.argtypes = [wt.HDC, ctypes.c_int]
gdi.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6
gdi.CreateRoundRectRgn.restype = wt.HRGN


u32.GetDC.argtypes = [wt.HWND]
u32.GetDC.restype = wt.HDC
u32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
gdi.CreateCompatibleDC.argtypes = [wt.HDC]
gdi.CreateCompatibleDC.restype = wt.HDC
gdi.CreateCompatibleBitmap.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int]
gdi.CreateCompatibleBitmap.restype = wt.HBITMAP
gdi.BitBlt.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HDC, ctypes.c_int,
                       ctypes.c_int, wt.DWORD]
gdi.DeleteDC.argtypes = [wt.HDC]
gdi.DeleteObject.argtypes = [wt.HGDIOBJ]
gdi.FillRgn.argtypes = [wt.HDC, wt.HRGN, wt.HBRUSH]
gdi.FrameRgn.argtypes = [wt.HDC, wt.HRGN, wt.HBRUSH, ctypes.c_int, ctypes.c_int]
gdi.SetTextCharacterExtra.argtypes = [wt.HDC, ctypes.c_int]
gdi.GetTextExtentPoint32W.argtypes = [wt.HDC, wt.LPCWSTR, ctypes.c_int, ctypes.POINTER(wt.SIZE)]
gdi.TextOutW.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int, wt.LPCWSTR, ctypes.c_int]


def _rgb(r, g, b):
    return r | (g << 8) | (b << 16)


def _upper_tr(text):
    """Turkce buyuk harf: i -> I degil İ."""
    return text.replace("i", "İ").upper()


# ui/index.html belirteclerinden: --surface-2, --line-strong, --line, --text-2, --text-hi, --text-3, --danger
C_BG, C_EDGE, C_TRACK = (24, 28, 35), (59, 67, 80), (37, 42, 51)
C_LABEL, C_VALUE = (169, 177, 190), (255, 255, 255)
C_ON, C_OFF, C_NEUTRAL = (88, 166, 255), (255, 107, 107), (129, 138, 153)
TIMER_FADE = 8
ALPHA = 245


class Osd:
    """Ekranin alt ortasinda, odak calmayan, tiklamayi geciren kompakt hap bildirim (uygulama arayuzunun
    dilinde: koyu yuzey, ince kenar, Bahnschrift buyuk harf, renkli durum karesi, istege bagli ince seviye
    cubugu). Pencereyi olusturan (tepsi) is parcacigindan cagrilmali."""

    def __init__(self):
        self._proc = WNDPROC(self._wndproc)  # referans canli kalmali
        hinst = k32.GetModuleHandleW(None)
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = self._proc
        wc.hInstance = hinst
        wc.lpszClassName = "KendiControlCenterOSD"
        u32.RegisterClassExW(ctypes.byref(wc))
        self.hwnd = u32.CreateWindowExW(WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_LAYERED | WS_EX_TRANSPARENT |
                                        WS_EX_NOACTIVATE, wc.lpszClassName, "OSD", WS_POPUP,
                                        0, 0, 10, 10, None, None, hinst, None)
        u32.SetLayeredWindowAttributes(self.hwnd, 0, ALPHA, LWA_ALPHA)
        self.scale = s = (u32.GetDpiForSystem() or 96) / 96.0
        self.brushes = {c: gdi.CreateSolidBrush(_rgb(*c))
                        for c in (C_BG, C_EDGE, C_TRACK, C_ON, C_OFF, C_NEUTRAL)}
        self.font = gdi.CreateFontW(-int(12.5 * s), 0, 0, 0, 600, 0, 0, 0, 1, 0, 0, 5, 0, "Bahnschrift")
        self.extra = max(1, round(0.9 * s))  # harf araligi (~.07em, arayuzdeki .chip/.btn gibi)
        self.label = self.value = ""
        self.level = self.state = None
        self.alpha = ALPHA
        self.size = (0, 0)
        self.widths = (0, 0)
        self.text_h = 0

    def _measure(self, *texts):
        hdc = u32.GetDC(self.hwnd)
        old = gdi.SelectObject(hdc, self.font)
        gdi.SetTextCharacterExtra(hdc, self.extra)
        out = []
        for t in texts:
            sz = wt.SIZE()
            gdi.GetTextExtentPoint32W(hdc, t or " ", len(t or " "), ctypes.byref(sz))
            out.append((sz.cx if t else 0, sz.cy))
        gdi.SelectObject(hdc, old)
        u32.ReleaseDC(self.hwnd, hdc)
        return out

    def show(self, label, value="", level=None, state=None):
        """label: ne (KAMERA), value: durum (KAPALI), level: 0-100 ince cubuk, state: True acik / False kapali /
        None notr (durum karesinin rengi)."""
        self.label, self.value = _upper_tr(label), _upper_tr(value or "")
        self.level, self.state = level, state
        s = self.scale
        (lw, th), (vw, _) = self._measure(self.label, self.value)
        pad, dot, gap = int(12 * s), int(8 * s), int(10 * s)
        w = pad + dot + gap + lw + (int(8 * s) + vw if self.value else 0) + pad
        h = int((40 if level is not None else 34) * s)
        self.size, self.widths, self.text_h = (w, h), (lw, vw), th
        work = wt.RECT()
        u32.SystemParametersInfoW(0x0030, 0, ctypes.byref(work), 0)  # SPI_GETWORKAREA
        x = work.left + (work.right - work.left - w) // 2
        y = work.bottom - h - int(56 * s)
        r = int(6 * s) * 2  # --r-2
        u32.SetWindowRgn(self.hwnd, gdi.CreateRoundRectRgn(0, 0, w + 1, h + 1, r, r), True)
        u32.KillTimer(self.hwnd, TIMER_FADE)
        self.alpha = ALPHA
        u32.SetLayeredWindowAttributes(self.hwnd, 0, ALPHA, LWA_ALPHA)
        u32.SetWindowPos(self.hwnd, wt.HWND(HWND_TOPMOST), x, y, w, h, SWP_NOACTIVATE | SWP_SHOWWINDOW)
        u32.InvalidateRect(self.hwnd, None, False)
        u32.SetTimer(self.hwnd, TIMER_HIDE, 1400, None)

    def _paint(self, hwnd):
        ps = PAINTSTRUCT()
        hdc = u32.BeginPaint(hwnd, ctypes.byref(ps))
        w, h = self.size
        s = self.scale
        mem = gdi.CreateCompatibleDC(hdc)  # titremesiz: once bellege ciz
        bmp = gdi.CreateCompatibleBitmap(hdc, w, h)
        old_bmp = gdi.SelectObject(mem, bmp)
        b = self.brushes
        r = int(6 * s) * 2
        rgn = gdi.CreateRoundRectRgn(0, 0, w + 1, h + 1, r, r)
        gdi.FillRgn(mem, rgn, b[C_BG])
        gdi.FrameRgn(mem, rgn, b[C_EDGE], 1, 1)
        gdi.DeleteObject(rgn)

        pad, dot, gap = int(12 * s), int(8 * s), int(10 * s)
        has_bar = self.level is not None
        mid = (h - int(6 * s)) // 2 if has_bar else h // 2  # cubuk varsa satir biraz yukari
        color = C_ON if self.state else (C_OFF if self.state is False else C_NEUTRAL)
        d = gdi.CreateRoundRectRgn(pad, mid - dot // 2, pad + dot + 1, mid + dot // 2 + 1, int(3 * s), int(3 * s))
        gdi.FillRgn(mem, d, b[color])
        gdi.DeleteObject(d)

        old_font = gdi.SelectObject(mem, self.font)
        gdi.SetBkMode(mem, 1)  # TRANSPARENT
        gdi.SetTextCharacterExtra(mem, self.extra)
        ty = mid - self.text_h // 2
        x = pad + dot + gap
        gdi.SetTextColor(mem, _rgb(*C_LABEL))
        gdi.TextOutW(mem, x, ty, self.label, len(self.label))
        if self.value:
            x += self.widths[0] + int(8 * s)
            gdi.SetTextColor(mem, _rgb(*C_VALUE))
            gdi.TextOutW(mem, x, ty, self.value, len(self.value))
        gdi.SelectObject(mem, old_font)

        if has_bar:
            top = h - int(9 * s)
            bar = wt.RECT(pad, top, w - pad, top + max(2, int(3 * s)))
            u32.FillRect(mem, ctypes.byref(bar), b[C_TRACK])
            bar.right = bar.left + int((bar.right - bar.left) * max(0, min(100, self.level)) / 100)
            if bar.right > bar.left:
                u32.FillRect(mem, ctypes.byref(bar), b[color])

        gdi.BitBlt(hdc, 0, 0, w, h, mem, 0, 0, 0x00CC0020)  # SRCCOPY
        gdi.SelectObject(mem, old_bmp)
        gdi.DeleteObject(bmp)
        gdi.DeleteDC(mem)
        u32.EndPaint(hwnd, ctypes.byref(ps))

    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_PAINT:
                self._paint(hwnd)
                return 0
            if msg == WM_ERASEBKGND:
                return 1
            if msg == WM_TIMER and wparam == TIMER_HIDE:
                u32.KillTimer(hwnd, TIMER_HIDE)
                u32.SetTimer(hwnd, TIMER_FADE, 15, None)  # ~160 ms'lik solma
                return 0
            if msg == WM_TIMER and wparam == TIMER_FADE:
                self.alpha -= 24
                if self.alpha <= 0:
                    u32.KillTimer(hwnd, TIMER_FADE)
                    u32.ShowWindow(hwnd, SW_HIDE)
                    self.alpha = ALPHA
                    u32.SetLayeredWindowAttributes(hwnd, 0, ALPHA, LWA_ALPHA)
                else:
                    u32.SetLayeredWindowAttributes(hwnd, 0, self.alpha, LWA_ALPHA)
                return 0
        except Exception:
            pass
        return u32.DefWindowProcW(hwnd, msg, wparam, lparam)


# ----------------------------------------------------------------------------- eylemler
def touchpad_enabled():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\PrecisionTouchPad\Status") as k:
            return bool(winreg.QueryValueEx(k, "Enabled")[0])
    except OSError:
        return None


def screen_off():
    time.sleep(0.6)  # tusun birakilmasi ekrani hemen geri uyandirmasin
    u32.PostMessageW(wt.HWND(0xFFFF), 0x0112, 0xF170, 2)  # HWND_BROADCAST, WM_SYSCOMMAND, SC_MONITORPOWER, kapat
