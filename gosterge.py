# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""Oyun ici gosterge: ekranin bir kosesinde her zaman ustte, tiklamayi geciren ince bir serit.

    ISLEMCI 78°  45 W   KART 70°  95 W   FAN 4200   ULTRA

Tepsi sureci (normal yetki) olusturur ve 2 sn'lik yoklamada gunceller; Ctrl+Alt+O ile acilip kapanir.
FPS gostermez: FPS icin oyunun cizim zincirine baglanmak (PresentMon / ETW) gerekir; bu uygulama oyuna dokunmaz.
Tam ekran (exclusive) oyunlarda Windows ust pencereleri gostermez; kenarliksiz pencere kipinde gorunur.
Cizim fntus.Osd ile ayni belirteclerle (koyu yuzey, ince kenar, Bahnschrift) yapilir.
"""
import ctypes
from ctypes import wintypes as wt

import ceviri
import fntus
from ceviri import t
from fntus import (ALPHA, C_BG, C_EDGE, C_LABEL, C_NEUTRAL, C_OFF, C_VALUE, HWND_TOPMOST, LWA_ALPHA, PAINTSTRUCT,
                   SW_HIDE, SWP_NOACTIVATE, SWP_SHOWWINDOW, WM_ERASEBKGND, WM_PAINT, WNDCLASSEXW, WNDPROC,
                   WS_EX_LAYERED, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW, WS_EX_TOPMOST, WS_EX_TRANSPARENT, WS_POPUP,
                   _font_face, _rgb, gdi, k32, u32)

C_WARN = (255, 184, 77)  # uyari turuncusu
CORNERS = ("tl", "tr", "bl", "br")


def level_color(temp, warn, hot):
    """Sicaklik rengi: normal beyaz, uyari turuncu, sicak kirmizi."""
    if temp is None:
        return C_VALUE
    return C_OFF if temp >= hot else C_WARN if temp >= warn else C_VALUE


def segments(s, profile_name=""):
    """/api/tray yanitindan (etiket, deger, renk) parcalari. Olmayan olcum atlanir."""
    out = []

    def num(v, unit):
        return None if v is None else ceviri.num(v, 0) + unit

    cpu = [x for x in (num(s.get("cpu_temp"), "°"), num(s.get("cpu_power"), " W")) if x]
    if cpu:
        out.append((t("ovl.cpu"), "  ".join(cpu), level_color(s.get("cpu_temp"), 85, 95)))
    if s.get("gpu_state") == "active":
        gpu = [x for x in (num(s.get("gpu_temp"), "°"), num(s.get("gpu_power"), " W")) if x]
        if gpu:
            out.append((t("ovl.gpu"), "  ".join(gpu), level_color(s.get("gpu_temp"), 80, 87)))
    rpm = [v for v in (s.get("cpu_rpm"), s.get("gpu_rpm")) if v]
    if rpm:
        out.append((t("ovl.fan"), " / ".join(ceviri.num(v, 0) for v in rpm), C_VALUE))
    if profile_name:
        out.append(("", profile_name, C_NEUTRAL))
    if not out:
        out.append((t("ovl.noData"), "", C_NEUTRAL))
    return out


class Overlay:
    """Kalici serit: show(segs, corner) / hide(). Pencereyi olusturan (tepsi) is parcacigindan cagrilmali."""

    def __init__(self):
        self._proc = WNDPROC(self._wndproc)  # referans canli kalmali
        hinst = k32.GetModuleHandleW(None)
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = self._proc
        wc.hInstance = hinst
        wc.lpszClassName = "KendiControlCenterOverlay"
        u32.RegisterClassExW(ctypes.byref(wc))
        self.hwnd = u32.CreateWindowExW(WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_LAYERED | WS_EX_TRANSPARENT |
                                        WS_EX_NOACTIVATE, wc.lpszClassName, "Overlay", WS_POPUP,
                                        0, 0, 10, 10, None, None, hinst, None)
        u32.SetLayeredWindowAttributes(self.hwnd, 0, int(ALPHA * 0.86), LWA_ALPHA)
        self.scale = (u32.GetDpiForSystem() or 96) / 96.0
        self.face = None
        self.font = self.font_lbl = None
        self.brushes = {c: gdi.CreateSolidBrush(_rgb(*c)) for c in (C_BG, C_EDGE)}
        self.segs = []
        self.layout = []
        self.size = (0, 0)
        self.visible = False
        self.corner = "tl"

    def _fonts(self):
        face = _font_face()
        if face == self.face:
            return
        for f in (self.font, self.font_lbl):
            if f:
                gdi.DeleteObject(f)
        s = self.scale
        self.face = face
        self.font = gdi.CreateFontW(-int(13 * s), 0, 0, 0, 600, 0, 0, 0, 1, 0, 0, 5, 0, face)
        self.font_lbl = gdi.CreateFontW(-int(11 * s), 0, 0, 0, 600, 0, 0, 0, 1, 0, 0, 5, 0, face)

    @staticmethod
    def _width(hdc, font, text):
        if not text:
            return 0
        gdi.SelectObject(hdc, font)
        sz = wt.SIZE()
        gdi.GetTextExtentPoint32W(hdc, text, len(text), ctypes.byref(sz))
        return sz.cx

    def show(self, segs, corner="tl"):
        self._fonts()
        self.segs = [(ceviri.upper(a), ceviri.upper(b), c) for a, b, c in segs]
        self.corner = corner if corner in CORNERS else "tl"
        s = self.scale
        pad, gap, inner = int(10 * s), int(16 * s), int(6 * s)
        hdc = u32.GetDC(self.hwnd)
        old = gdi.SelectObject(hdc, self.font)
        x, self.layout = pad, []
        for lbl, val, _ in self.segs:
            lw = self._width(hdc, self.font_lbl, lbl) + (inner if lbl and val else 0)
            vw = self._width(hdc, self.font, val)
            self.layout.append((x, x + lw))
            x += lw + vw + gap
        gdi.SelectObject(hdc, old)
        u32.ReleaseDC(self.hwnd, hdc)
        w, h = x - gap + pad, int(28 * s)
        self.size = (w, h)
        work = wt.RECT()
        u32.SystemParametersInfoW(0x0030, 0, ctypes.byref(work), 0)  # SPI_GETWORKAREA
        m = int(12 * s)
        px = work.left + m if self.corner in ("tl", "bl") else work.right - w - m
        py = work.top + m if self.corner in ("tl", "tr") else work.bottom - h - m
        r = int(6 * s) * 2
        u32.SetWindowRgn(self.hwnd, gdi.CreateRoundRectRgn(0, 0, w + 1, h + 1, r, r), True)
        u32.SetWindowPos(self.hwnd, wt.HWND(HWND_TOPMOST), px, py, w, h, SWP_NOACTIVATE | SWP_SHOWWINDOW)
        u32.InvalidateRect(self.hwnd, None, False)
        self.visible = True

    def hide(self):
        u32.ShowWindow(self.hwnd, SW_HIDE)
        self.visible = False

    def _paint(self, hwnd):
        ps = PAINTSTRUCT()
        hdc = u32.BeginPaint(hwnd, ctypes.byref(ps))
        w, h = self.size
        s = self.scale
        mem = gdi.CreateCompatibleDC(hdc)  # titremesiz: once bellege ciz
        bmp = gdi.CreateCompatibleBitmap(hdc, max(1, w), max(1, h))
        old_bmp = gdi.SelectObject(mem, bmp)
        r = int(6 * s) * 2
        rgn = gdi.CreateRoundRectRgn(0, 0, w + 1, h + 1, r, r)
        gdi.FillRgn(mem, rgn, self.brushes[C_BG])
        gdi.FrameRgn(mem, rgn, self.brushes[C_EDGE], 1, 1)
        gdi.DeleteObject(rgn)
        gdi.SetBkMode(mem, 1)  # TRANSPARENT
        old_font = gdi.SelectObject(mem, self.font)
        for (lbl, val, color), (lx, vx) in zip(self.segs, self.layout):
            if lbl:
                gdi.SelectObject(mem, self.font_lbl)
                gdi.SetTextColor(mem, _rgb(*C_LABEL))
                gdi.TextOutW(mem, lx, (h - int(11 * s)) // 2 - int(1 * s), lbl, len(lbl))
            if val:
                gdi.SelectObject(mem, self.font)
                gdi.SetTextColor(mem, _rgb(*color))
                gdi.TextOutW(mem, vx, (h - int(13 * s)) // 2 - int(2 * s), val, len(val))
        gdi.SelectObject(mem, old_font)
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
        except Exception:
            fntus.log("gosterge cizim hatasi")
        return u32.DefWindowProcW(hwnd, msg, wparam, lparam)
