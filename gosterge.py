# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""Oyun ici gosterge (HUD): ekranin bir kosesinde her zaman ustte, tiklamayi geciren, odak calmayan pencere.

    CPU  72 °C  45 W │ GPU  65 °C  95 W │ PLAN  ULTRA            (serit duzeni, varsayilan degerler)

Kullanici Oyun ici gosterge sayfasinda hangi degerlerin gorunecegini (profiller.OVERLAY_ITEMS), duzeni (serit /
panel), boyutu ve saydamligi secer. Tepsi sureci (normal yetki) olusturur ve saniyede bir gunceller;
Ctrl+Alt+O ile acilip kapanir. FPS motorun ETW olcumunden gelir (kare.py), oyuna hicbir sey enjekte edilmez.
Tam ekran (exclusive) oyunlarda Windows ust pencereleri gostermez; kenarliksiz pencere kipinde gorunur.

Netlik ve performans:
- Tepsi sureci DPI farkindadir (tepsi.run): yazi Windows tarafindan buyutulup bulaniklasmaz, ClearType ile cizilir.
- Her deger icin sabit genislikte yuva ("888" gibi kalip) ayrilir: degerler degisince gosterge zipmaz ve pencere
  yeniden boyutlanmaz. Yerlesim yalnizca secim / dil / profil adi degisince yeniden hesaplanir; her saniye
  yalnizca bellekte cizilip tek BitBlt ile kopyalanir.
"""
import ctypes
import time
from ctypes import wintypes as wt

import ceviri
import fntus
from ceviri import t
from fntus import (C_EDGE, C_LABEL, C_OFF, C_VALUE, HWND_TOPMOST, LWA_ALPHA, PAINTSTRUCT, SW_HIDE,
                   SWP_NOACTIVATE, SWP_SHOWWINDOW, WM_ERASEBKGND, WM_PAINT, WNDCLASSEXW, WNDPROC, WS_EX_LAYERED,
                   WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW, WS_EX_TOPMOST, WS_EX_TRANSPARENT, WS_POPUP, _font_face, _rgb,
                   gdi, k32, u32)

C_WARN = (255, 184, 77)    # uyari turuncusu
C_DIM = (112, 120, 133)    # olcum yok
C_HUD_BG = (14, 17, 22)    # oyun ustunde daha iyi okunsun diye arayuz yuzeyinden koyu
C_SEP = (40, 46, 57)       # ayirici cizgi
ACCENT = {"cpu": (92, 170, 255), "gpu": (118, 214, 114), "fps": (255, 214, 64), "sys": (190, 198, 210),
          "plan": (200, 160, 255)}
CORNERS = ("tl", "tc", "tr", "bl", "br")
SIZES = {"s": 0.85, "m": 1.0, "l": 1.25, "xl": 1.6}
DASH = "–"

TA_LEFT, TA_RIGHT, TA_BASELINE = 0, 2, 24
SWP_NOSIZE, SWP_NOMOVE = 0x0001, 0x0002
gdi.SetTextAlign.argtypes = [wt.HDC, wt.UINT]
try:
    u32.GetDpiForWindow.argtypes = [wt.HWND]
    u32.GetDpiForWindow.restype = wt.UINT
except AttributeError:  # Windows 10 1607 oncesi
    pass


def level_color(temp, warn, hot):
    """Sicaklik rengi: normal beyaz, uyari turuncu, sicak kirmizi."""
    if temp is None:
        return C_VALUE
    return C_OFF if temp >= hot else C_WARN if temp >= warn else C_VALUE


def _n(v, d=0):
    return None if v is None else ceviri.num(v, d)


def _pair(used, total, div, d=1):
    """'6,2/8' gibi kullanilan/toplam."""
    if used is None or not total:
        return None
    return "%s/%s" % (ceviri.num(used / div, d), ceviri.num(total / div, 0))


def build(s, keys, profile_name=""):
    """/api/tray yanitindan gosterge gruplari: [(grup, etiket, [(deger, birim, renk, kalip), ...]), ...].
    Secilmis ama olculemeyen deger '–' olarak kalir (yerlesim sabit kalsin)."""
    keys = set(keys or ())
    gpu_on = s.get("gpu_state") == "active"
    out = []

    def cell(v, unit, tmpl, color=C_VALUE):
        return (DASH, unit, C_DIM, tmpl) if v is None else (v, unit, color, tmpl)

    cpu = []
    if "cpu_temp" in keys:
        cpu.append(cell(_n(s.get("cpu_temp")), "°C", "888", level_color(s.get("cpu_temp"), 85, 95)))
    if "cpu_power" in keys:
        cpu.append(cell(_n(s.get("cpu_power")), "W", "888"))
    if "cpu_clock" in keys:
        cpu.append(cell(_n(s.get("cpu_mhz") or None), "MHz", "8888"))
    if "cpu_load" in keys:
        cpu.append(cell(_n(s.get("cpu_load")), "%", "888"))
    if cpu:
        out.append(("cpu", t("hud.cpu"), cpu))

    def g(k):
        return s.get(k) if gpu_on else None
    gpu = []
    if "gpu_temp" in keys:
        gpu.append(cell(_n(g("gpu_temp")), "°C", "888", level_color(g("gpu_temp"), 80, 87)))
    if "gpu_power" in keys:
        gpu.append(cell(_n(g("gpu_power")), "W", "888"))
    if "gpu_clock" in keys:
        gpu.append(cell(_n(g("gpu_clock")), "MHz", "8888"))
    if "gpu_mem_clock" in keys:
        gpu.append(cell(_n(g("gpu_mem_clock")), "MHz", "88888"))
    if "gpu_load" in keys:
        gpu.append(cell(_n(g("gpu_load")), "%", "888"))
    if "gpu_vram" in keys:
        gpu.append(cell(_pair(g("gpu_vram_used"), s.get("gpu_vram_total"), 1024.0), "GB", "88.8/88"))
    if gpu:
        out.append(("gpu", t("hud.gpu"), gpu))

    fps = []
    f = s.get("fps")
    if "fps" in keys:
        fps.append(cell(_n(f), "FPS", "8888"))
    if "frametime" in keys:
        fps.append(cell(_n(1000.0 / f, 1) if f else None, "ms", "888.8"))
    if fps:
        out.append(("fps", t("hud.fps"), fps))

    if "fan" in keys:
        rpm = [v for v in (s.get("cpu_rpm"), s.get("gpu_rpm")) if v is not None]
        val = "/".join(ceviri.num(v, 0) for v in rpm) if rpm else None
        out.append(("sys", t("hud.fan"), [cell(val, "RPM", "8888/8888")]))
    if "ram" in keys:
        out.append(("sys", t("hud.ram"), [cell(_pair(s.get("ram_used"), s.get("ram_total"), 1.0), "GB",
                                               "88.8/88")]))
    if "battery" in keys:
        pct = s.get("battery_pct")
        col = C_OFF if pct is not None and pct <= 15 and not s.get("battery_ac", True) else C_VALUE
        out.append(("sys", t("hud.battery"), [cell(_n(pct), "%", "888", col)]))
    if "time" in keys:
        out.append(("sys", t("hud.time"), [cell(time.strftime("%H:%M"), "", "88:88")]))
    if "profile" in keys:
        name = profile_name or None
        out.append(("plan", t("hud.plan"), [cell(name, "", name or DASH, ACCENT["plan"])]))
    if not out:
        out.append(("sys", "", [(t("ovl.noData"), "", C_DIM, t("ovl.noData"))]))
    return out


class Overlay:
    """Kalici gosterge: show(groups, corner, layout, size, opacity) / hide().
    Pencereyi olusturan (tepsi) is parcacigindan cagrilmali."""

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
        self.alpha = None
        self.fonts, self.em = {}, {}
        self.font_key = None
        self.brushes = {c: gdi.CreateSolidBrush(_rgb(*c)) for c in (C_HUD_BG, C_EDGE, C_SEP)}
        self.groups = []
        self.sig = None
        self.ops = []        # cizim plani: yalnizca yerlesim degisince yeniden kurulur
        self.lines = []      # ayirici cizgiler (x, y, w, h)
        self.rows = []       # satir ortalari (y)
        self.size = (0, 0)
        self.radius = 0
        self.visible = False

    # -- yazi tipleri
    def _scale(self, size):
        try:
            dpi = u32.GetDpiForWindow(self.hwnd) or u32.GetDpiForSystem() or 96
        except (AttributeError, OSError):
            dpi = u32.GetDpiForSystem() or 96
        return dpi / 96.0 * SIZES.get(size, 1.0)

    def _fonts(self, s):
        face = _font_face()
        key = (face, round(s, 3))
        if key == self.font_key:
            return
        for f in self.fonts.values():
            gdi.DeleteObject(f)

        def mk(px, weight):  # 5: CLEARTYPE_QUALITY
            return gdi.CreateFontW(-max(8, round(px * s)), 0, 0, 0, weight, 0, 0, 0, 1, 0, 0, 5, 0, face)
        self.fonts = {"val": mk(17, 600), "unit": mk(11, 500), "tag": mk(11, 700)}
        self.em = {"val": 17 * s, "unit": 11 * s, "tag": 11 * s}
        self.font_key = key

    def _w(self, hdc, font, text):
        if not text:
            return 0
        gdi.SelectObject(hdc, self.fonts[font])
        sz = wt.SIZE()
        gdi.GetTextExtentPoint32W(hdc, text, len(text), ctypes.byref(sz))
        return sz.cx

    # -- yerlesim
    def _layout(self, layout, s):
        hdc = u32.GetDC(self.hwnd)
        old = gdi.SelectObject(hdc, self.fonts["val"])
        pad_x, pad_y = round(12 * s), round(7 * s)
        tag_gap, unit_gap, cell_gap, group_gap = round(7 * s), round(3 * s), round(11 * s), round(22 * s)
        # her hucre: (deger yuvasi genisligi, birim genisligi)
        meas = [[(max(self._w(hdc, "val", tm), self._w(hdc, "val", v)), self._w(hdc, "unit", u))
                 for v, u, _, tm in cells] for _, _, cells in self.groups]
        tags = [self._w(hdc, "tag", tag) for _, tag, _ in self.groups]
        gdi.SelectObject(hdc, old)
        u32.ReleaseDC(self.hwnd, hdc)
        ops, lines = [], []  # ops: (tur, grup, hucre, x, satir); tur: tag | val | unit
        if layout == "panel":
            tag_w = max(tags) if tags else 0
            ncol = max(len(c) for _, _, c in self.groups)
            col_slot = [max((m[i][0] for m in meas if i < len(m)), default=0) for i in range(ncol)]
            col_unit = [max((m[i][1] for m in meas if i < len(m)), default=0) for i in range(ncol)]
            row_h = round(self.em["val"] * 1.65)
            x0 = pad_x + (tag_w + tag_gap * 2 if tag_w else 0)

            def step(i):
                return col_slot[i] + (unit_gap + col_unit[i] if col_unit[i] else 0)
            w = x0 + sum(step(i) for i in range(ncol)) + cell_gap * (ncol - 1) + pad_x
            for r, (_, _, cells) in enumerate(self.groups):
                ops.append(("tag", r, 0, pad_x, r))
                x = x0
                for i in range(len(cells)):
                    ops.append(("val", r, i, x + col_slot[i], r))
                    ops.append(("unit", r, i, x + col_slot[i] + unit_gap, r))
                    x += step(i) + cell_gap
                if r:
                    lines.append((pad_x, pad_y + r * row_h, w - 2 * pad_x, 1))
            h = pad_y * 2 + row_h * len(self.groups)
            self.rows = [pad_y + r * row_h + row_h / 2 for r in range(len(self.groups))]
        else:
            h = round(self.em["val"] * 1.75) + pad_y
            x, seps = pad_x, []
            for gi, (_, tag, cells) in enumerate(self.groups):
                if gi:
                    seps.append(x - group_gap // 2)
                if tag:
                    ops.append(("tag", gi, 0, x, 0))
                    x += tags[gi] + tag_gap
                for i, (slot, uw) in enumerate(meas[gi]):
                    ops.append(("val", gi, i, x + slot, 0))
                    ops.append(("unit", gi, i, x + slot + unit_gap, 0))
                    x += slot + (unit_gap + uw if uw else 0) + cell_gap
                x += group_gap - cell_gap
            w = x - group_gap + pad_x
            inset = round(h * 0.28)
            lines = [(sx, inset, 1, h - 2 * inset) for sx in seps]
            self.rows = [h / 2]
        self.ops, self.lines, self.size = ops, lines, (w, h)
        self.radius = round(8 * s)

    def show(self, groups, corner="tl", layout="row", size="m", opacity=90):
        s = self._scale(size)
        self._fonts(s)
        self.groups = [(gid, ceviri.upper(tag), list(cells)) for gid, tag, cells in groups]
        corner = corner if corner in CORNERS else "tl"
        layout = layout if layout in ("row", "panel") else "row"
        try:
            op = min(100, max(40, int(opacity)))
        except (TypeError, ValueError):
            op = 90
        alpha = round(255 * op / 100)
        if alpha != self.alpha:
            u32.SetLayeredWindowAttributes(self.hwnd, 0, alpha, LWA_ALPHA)
            self.alpha = alpha
        # yerlesim imzasi: degerler degil, yalnizca yapi (etiketler, birimler, kaliplar) ve secenekler
        sig = (tuple((gid, tag, tuple((u, tm) for _, u, _, tm in cells)) for gid, tag, cells in self.groups),
               corner, layout, self.font_key)
        flags = SWP_NOACTIVATE | SWP_SHOWWINDOW
        if sig != self.sig:
            self.sig = sig
            work = wt.RECT()
            u32.SystemParametersInfoW(0x0030, 0, ctypes.byref(work), 0)  # SPI_GETWORKAREA
            m = round(14 * s)
            self._layout(layout, s)
            if layout == "row" and self.size[0] > work.right - work.left - 2 * m:
                self._layout("panel", s)  # serit ekrana sigmiyor (cok deger secilmis): alt alta
            w, h = self.size
            if corner == "tc":
                px = work.left + (work.right - work.left - w) // 2
            else:
                px = work.left + m if corner in ("tl", "bl") else work.right - w - m
            py = work.top + m if corner in ("tl", "tc", "tr") else work.bottom - h - m
            r = self.radius * 2
            u32.SetWindowRgn(self.hwnd, gdi.CreateRoundRectRgn(0, 0, w + 1, h + 1, r, r), True)
            u32.SetWindowPos(self.hwnd, wt.HWND(HWND_TOPMOST), px, py, w, h, flags)
        else:  # yalnizca degerler degisti: en ustte kalsin (kenarliksiz oyun one gecmis olabilir), yeniden ciz
            u32.SetWindowPos(self.hwnd, wt.HWND(HWND_TOPMOST), 0, 0, 0, 0, flags | SWP_NOMOVE | SWP_NOSIZE)
        u32.InvalidateRect(self.hwnd, None, False)
        self.visible = True

    def hide(self):
        u32.ShowWindow(self.hwnd, SW_HIDE)
        self.visible = False
        self.sig = None

    # -- cizim
    def _paint(self, hwnd):
        ps = PAINTSTRUCT()
        hdc = u32.BeginPaint(hwnd, ctypes.byref(ps))
        w, h = self.size
        mem = gdi.CreateCompatibleDC(hdc)  # titremesiz: once bellege ciz
        bmp = gdi.CreateCompatibleBitmap(hdc, max(1, w), max(1, h))
        old_bmp = gdi.SelectObject(mem, bmp)
        r = self.radius * 2
        rgn = gdi.CreateRoundRectRgn(0, 0, w + 1, h + 1, r, r)
        gdi.FillRgn(mem, rgn, self.brushes[C_HUD_BG])
        gdi.FrameRgn(mem, rgn, self.brushes[C_EDGE], 1, 1)
        gdi.DeleteObject(rgn)
        for lx, ly, lw, lh in self.lines:
            rc = wt.RECT(lx, ly, lx + lw, ly + lh)
            u32.FillRect(mem, ctypes.byref(rc), self.brushes[C_SEP])
        gdi.SetBkMode(mem, 1)  # TRANSPARENT
        old_font = gdi.SelectObject(mem, self.fonts["val"])
        lift = self.em["val"] * 0.36  # buyuk deger ile kucuk birim/etiket ayni taban cizgisinde (TA_BASELINE)
        for kind, gi, ci, x, row in self.ops:
            gid, tag, cells = self.groups[gi]
            if kind == "tag":
                text, font, color, align = tag, "tag", ACCENT.get(gid, C_LABEL), TA_LEFT
            elif kind == "val":
                text, font, color, align = cells[ci][0], "val", cells[ci][2], TA_RIGHT
            else:
                text, font, color, align = cells[ci][1], "unit", C_LABEL, TA_LEFT
            if not text:
                continue
            gdi.SelectObject(mem, self.fonts[font])
            gdi.SetTextAlign(mem, align | TA_BASELINE)
            gdi.SetTextColor(mem, _rgb(*color))
            gdi.TextOutW(mem, x, round(self.rows[row] + lift), text, len(text))
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
