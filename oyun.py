# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""Oyun modu kaynaklari: tus/fare basimlari ve League of Legends canli oyun verisi.

Hile korumasi (Vanguard, VAC) acisindan guvenli olacak sekilde yalnizca su yollar kullanilir:
  - Tuslar: GetAsyncKeyState ile genel tus durumu okunur (kanca kurulmaz, oyuna dokunulmaz).
  - LoL: Riot'un resmi Live Client Data API'si (https://127.0.0.1:2999), oyun sirasinda kendisi acar.
Oyun bellegi okunmaz, oyuna kod enjekte edilmez.
"""
import ctypes
import json
import os
import ssl
import threading
import time
import urllib.request
from ctypes import wintypes as wt

LOL_EXE = "league of legends.exe"
LOL_URL = "https://127.0.0.1:2999/liveclientdata/allgamedata"

VK_LBUTTON, VK_RETURN, VK_ESCAPE = 0x01, 0x0D, 0x1B
# Tus duzenleri: (sanal tus kodu, efekt kimligi). Efekt kimligi Engine'deki renk yuvasini secer.
LAYOUTS = {
    "lol": [(VK_LBUTTON, "fire"), (ord("Q"), "q"), (ord("W"), "w"), (ord("E"), "e"), (ord("R"), "r"),
            (ord("D"), "spell"), (ord("F"), "spell")],
    "fps": [(VK_LBUTTON, "fire")],
}

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32
_user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
_user32.GetAsyncKeyState.restype = ctypes.c_short
_user32.GetForegroundWindow.restype = wt.HWND
_user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
_user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
_user32.MonitorFromWindow.argtypes = [wt.HWND, wt.DWORD]
_user32.MonitorFromWindow.restype = wt.HANDLE
_user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
_kernel32.OpenProcess.restype = wt.HANDLE
_kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
_kernel32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
_kernel32.CloseHandle.argtypes = [wt.HANDLE]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]


_user32.GetMonitorInfoW.argtypes = [wt.HANDLE, ctypes.POINTER(MONITORINFO)]


class Foreground:
    """On plandaki pencere: hangi programin ve tam ekran mi. Masaustu/gorev cubugu oyun sayilmaz."""
    SHELL = ("progman", "workerw", "shell_traywnd")

    def __init__(self):
        self.hwnd = None
        self.exe = ""
        self.full = False
        self.at = 0.0

    def update(self, now):
        hwnd = _user32.GetForegroundWindow()
        if hwnd == self.hwnd and now - self.at < 1.0:
            return
        self.hwnd, self.at = hwnd, now
        self.exe, self.full = "", False
        if not hwnd:
            return
        pid = wt.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        h = _kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
        if h:
            try:
                buf = ctypes.create_unicode_buffer(520)
                n = wt.DWORD(len(buf))
                if _kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
                    self.exe = os.path.basename(buf.value).lower()
            finally:
                _kernel32.CloseHandle(h)
        cls = ctypes.create_unicode_buffer(64)
        _user32.GetClassNameW(hwnd, cls, 64)
        if cls.value.lower() in self.SHELL:
            return
        r = wt.RECT()
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        mon = _user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
        if _user32.GetWindowRect(hwnd, ctypes.byref(r)) and mon and _user32.GetMonitorInfoW(mon, ctypes.byref(mi)):
            m = mi.rcMonitor
            self.full = r.left <= m.left and r.top <= m.top and r.right >= m.right and r.bottom >= m.bottom


class KeyWatcher:
    """Secili tus duzenindeki tuslarin basilma anlarini ve basili tutulma durumunu verir.

    Tepki yalnizca oyun on plandayken verilir: LoL duzeninde LoL oyun penceresi, FPS duzeninde tam ekran
    (ya da kenarliksiz tam ekran) herhangi bir pencere. LoL'de Enter sohbeti acar; sohbet acikken yazilan
    Q/W/E/R harfleri yetenek sayilmaz (Enter ya da Esc ile kapanana kadar)."""

    def __init__(self):
        self.fg = Foreground()
        self.down = set()
        self.chat = False

    def active(self, layout):
        if layout == "lol":
            return self.fg.exe == LOL_EXE
        return self.fg.full and self.fg.exe not in ("explorer.exe", "")

    def poll(self, layout, now):
        """(yeni basilan efektler listesi, basili tutulan efektler kumesi)."""
        self.fg.update(now)
        keys = LAYOUTS.get(layout, LAYOUTS["fps"])
        if not self.active(layout):
            self.down.clear()
            self.chat = False
            return [], set()
        state = _user32.GetAsyncKeyState
        if layout == "lol":
            for vk in (VK_RETURN, VK_ESCAPE):
                pressed = bool(state(vk) & 0x8000)
                if pressed and vk not in self.down:
                    self.chat = (not self.chat) if vk == VK_RETURN else False
                (self.down.add if pressed else self.down.discard)(vk)
        pressed_now, held = [], set()
        for vk, fx in keys:
            if self.chat and vk != VK_LBUTTON:
                continue
            pressed = bool(state(vk) & 0x8000)
            if pressed:
                held.add(fx)
                if vk not in self.down:
                    pressed_now.append(fx)
                self.down.add(vk)
            else:
                self.down.discard(vk)
        return pressed_now, held


def _ids(*values):
    """Oyuncu adlarini karsilastirilabilir hale getirir: 'Ad#TAG' ve 'Ad', kucuk harf."""
    out = set()
    for v in values:
        if isinstance(v, str) and v:
            out.add(v.lower())
            out.add(v.split("#")[0].lower())
    return out


class LolClient(threading.Thread):
    """Riot Live Client Data API'sini ayri is parcaciginda yoklar; yalnizca Oyun modu seciliyken (wanted).
    Oyun yokken 3 sn'de bir dener.

    Disari verilenler: connected, health (0..1 ya da None), dead ve olay kuyrugu (pop_events)."""

    def __init__(self):
        super().__init__(daemon=True)
        self.running = True
        self.wanted = False
        self.connected = False
        self.health = None
        self.dead = False
        self._events = []
        self._seen = -1
        self._lock = threading.Lock()
        # API yalnizca 127.0.0.1'de, Riot'un kendi imzali sertifikasiyla calisir. Adres sabit ve yerel oldugu
        # icin sertifika dogrulamasi atlanir; hicbir veri gonderilmez, yalnizca okunur.
        self._ctx = ssl.create_default_context()
        self._ctx.check_hostname = False
        self._ctx.verify_mode = ssl.CERT_NONE

    def pop_events(self):
        with self._lock:
            ev, self._events = self._events, []
        return ev

    def _fetch(self):
        req = urllib.request.Request(LOL_URL, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=0.8, context=self._ctx) as r:
            return json.loads(r.read().decode("utf-8", "replace"))

    def process(self, data):
        """Gelen veriden saglik/olum durumunu gunceller, yeni olaylarin efekt kimliklerini dondurur."""
        active = data.get("activePlayer") or {}
        me = _ids(active.get("summonerName"), active.get("riotId"), active.get("riotIdGameName"))
        stats = active.get("championStats") or {}
        mx = stats.get("maxHealth") or 0
        try:
            self.health = max(0.0, min(1.0, float(stats.get("currentHealth", 0)) / mx)) if mx > 0 else None
        except (TypeError, ValueError):
            self.health = None
        dead = False
        for p in data.get("allPlayers") or []:
            if me & _ids(p.get("summonerName"), p.get("riotId"), p.get("riotIdGameName")):
                dead = bool(p.get("isDead"))
                break
        self.dead = dead
        new = []
        for e in ((data.get("events") or {}).get("Events")) or []:
            eid = e.get("EventID", -1)
            if not isinstance(eid, int) or eid <= self._seen:
                continue
            self._seen = eid
            kind = e.get("EventName")
            mine = bool(me & _ids(e.get("KillerName")))
            assist = bool(me & _ids(*(e.get("Assisters") or [])))
            if kind == "ChampionKill":
                if mine:
                    new.append("kill")
                elif me & _ids(e.get("VictimName")):
                    new.append("death")
                elif assist:
                    new.append("assist")
            elif kind == "Multikill" and mine:
                try:
                    n = int(e.get("KillStreak", 2))
                except (TypeError, ValueError):
                    n = 2
                new.append("multi%d" % max(2, min(5, n)))
            elif kind in ("DragonKill", "BaronKill", "HeraldKill", "HordeKill") and (mine or assist):
                new.append("objective")
            elif kind == "Ace":
                new.append("ace")
            elif kind == "GameEnd":
                new.append("win" if e.get("Result") == "Win" else "lose")
        return new

    def _reset(self):
        self.connected, self.health, self.dead = False, None, False
        self._seen = -1

    def run(self):
        while self.running:
            if not self.wanted:
                if self.connected:
                    self._reset()
                time.sleep(0.5)
                continue
            try:
                data = self._fetch()
                fresh = not self.connected
                self.connected = True
                new = self.process(data)
                if new and not fresh:  # baglanirken gecmis olaylari yeniden oynatma
                    with self._lock:
                        self._events.extend(new)
                time.sleep(0.25)
            except Exception:  # oyun yok, yukleme ekrani ya da gecici hata
                self._reset()
                time.sleep(3.0)
