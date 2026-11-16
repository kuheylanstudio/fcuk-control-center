# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""Oyun modu kaynaklari: tus/fare basimlari, League of Legends ve Counter-Strike 2 canli oyun verisi.

Hile korumasi (Vanguard, VAC) acisindan guvenli olacak sekilde yalnizca su yollar kullanilir:
  - Tuslar: GetAsyncKeyState ile genel tus durumu okunur (kanca kurulmaz, oyuna dokunulmaz).
  - LoL: Riot'un resmi Live Client Data API'si (https://127.0.0.1:2999), oyun sirasinda kendisi acar.
  - CS2: Valve'in resmi Game State Integration'i; oyun durumu bu uygulamaya kendisi gonderir (POST).
Oyun bellegi okunmaz, oyuna kod enjekte edilmez.

Performans: hicbiri her karede ag ya da disk isi yapmaz. LoL kucuk uc noktalarla (activeplayer, eventdata)
tek bir kalici baglanti uzerinden yoklanir; oyun yokken 3 sn'de bir tek bir yerel baglanti denemesi yapilir.
CS2 sunucusu yalnizca CS duzeni seciliyken acilir ve yalnizca oyun veri gonderdiginde calisir.
"""
import ctypes
import http.client
import json
import os
import re
import secrets
import ssl
import threading
import time
from ctypes import wintypes as wt
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOL_EXE = "league of legends.exe"
CS_EXE = "cs2.exe"
GAME_EXE = {"lol": LOL_EXE, "cs": CS_EXE}

VK_LBUTTON, VK_RETURN, VK_ESCAPE = 0x01, 0x0D, 0x1B
# Tus duzenleri: (sanal tus kodu, efekt kimligi). Efekt kimligi Engine'deki renk yuvasini secer.
LAYOUTS = {
    "lol": [(ord("Q"), "q"), (ord("W"), "w"), (ord("E"), "e"), (ord("R"), "r"),
            (ord("D"), "spell"), (ord("F"), "spell")],
    "cs": [(VK_LBUTTON, "fire")],
}

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32
_user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
_user32.GetAsyncKeyState.restype = ctypes.c_short
_user32.GetForegroundWindow.restype = wt.HWND
_user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
_kernel32.OpenProcess.restype = wt.HANDLE
_kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
_kernel32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
_kernel32.CloseHandle.argtypes = [wt.HANDLE]


class _ProcEntry(ctypes.Structure):  # PROCESSENTRY32W
    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
                ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", wt.DWORD),
                ("szExeFile", ctypes.c_wchar * 260)]


_kernel32.CreateToolhelp32Snapshot.restype = wt.HANDLE
_kernel32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
_kernel32.Process32FirstW.argtypes = [wt.HANDLE, ctypes.POINTER(_ProcEntry)]
_kernel32.Process32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(_ProcEntry)]
_INVALID_HANDLE = ctypes.c_void_p(-1).value


def _exe_by_handle(pid):
    """Surecin kendisinden (yalnizca ad sorgulama izni). Hile korumasi tutamagi reddederse ''."""
    h = _kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(520)
        n = wt.DWORD(len(buf))
        if _kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
            return os.path.basename(buf.value).lower()
        return ""
    finally:
        _kernel32.CloseHandle(h)


def _exe_by_snapshot(pid):
    """Sistem surec listesinden: oyunun surecine hic tutamak acilmaz. Bulunamazsa ''."""
    snap = _kernel32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if not snap or snap == _INVALID_HANDLE:
        return ""
    try:
        e = _ProcEntry()
        e.dwSize = ctypes.sizeof(e)
        ok = _kernel32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            if e.th32ProcessID == pid:
                return e.szExeFile.lower()
            ok = _kernel32.Process32NextW(snap, ctypes.byref(e))
        return ""
    finally:
        _kernel32.CloseHandle(snap)


class Foreground:
    """On plandaki pencerenin program adi. Pencere degismedikce saniyede en fazla bir kez sorgulanir.

    Once surecin kendisine ad sorgusu yapilir; hile korumasi bunu reddederse sistem surec listesine bakilir
    (oyuna tutamak acilmaz). unknown: on planda bir pencere var ama programi hicbir yolla belirlenemedi; bu
    durumda tus tepkisi verilemez ve arayuz kullaniciyi uyarir."""

    def __init__(self):
        self.hwnd = None
        self.exe = ""
        self.unknown = False
        self.at = 0.0

    def update(self, now):
        hwnd = _user32.GetForegroundWindow()
        if hwnd == self.hwnd and now - self.at < 1.0:
            return
        self.hwnd, self.at, self.exe, self.unknown = hwnd, now, "", False
        if not hwnd:
            return
        pid = wt.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value:
            self.exe = _exe_by_handle(pid.value) or _exe_by_snapshot(pid.value)
        self.unknown = not self.exe


class KeyWatcher:
    """Secili tus duzenindeki tuslarin basilma anlarini ve basili tutulma durumunu verir.

    Tepki yalnizca o oyunun penceresi on plandayken verilir. LoL'de Enter sohbeti acar; sohbet acikken
    yazilan Q/W/E/R harfleri yetenek sayilmaz (Enter ya da Esc ile kapanana kadar)."""

    def __init__(self):
        self.fg = Foreground()
        self.down = set()
        self.chat = False

    def active(self, layout):
        return self.fg.exe == GAME_EXE.get(layout)

    @property
    def unrecognized(self):
        """On plandaki program tanimlanamadi: tus tepkisi su an calismaz."""
        return self.fg.unknown

    def poll(self, layout, now):
        """(yeni basilan efektler listesi, basili tutulan efektler kumesi)."""
        self.fg.update(now)
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
        for vk, fx in LAYOUTS.get(layout, ()):
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


class GameSource:
    """Ortak durum: connected, health (0..1 ya da None), dead, flashed (0..1), burning ve olay kuyrugu."""

    def __init__(self):
        self.wanted = False
        self.connected = False
        self.health = None
        self.dead = False
        self.flashed = 0.0
        self.burning = False
        self.problem = ""  # kullaniciya gosterilecek kalici sorun (ornegin CS2 kurulumu bulunamadi)
        self._events = []
        self._lock = threading.Lock()

    def push(self, events):
        if events:
            with self._lock:
                self._events.extend(events)
                del self._events[:-20]

    def pop_events(self):
        with self._lock:
            ev, self._events = self._events, []
        return ev

    def _clear(self):
        self.connected, self.health, self.dead, self.flashed, self.burning = False, None, False, 0.0, False


# ----------------------------------------------------------------------------- League of Legends
class LolClient(GameSource, threading.Thread):
    """Riot Live Client Data API'sini ayri is parcaciginda yoklar; yalnizca istendiginde (wanted).

    Canli: /activeplayer (kucuk, saglik) 4 kez/sn, /eventdata 2 kez/sn, tek kalici HTTPS baglantisi."""
    HOST, PORT = "127.0.0.1", 2999

    def __init__(self):
        GameSource.__init__(self)
        threading.Thread.__init__(self, daemon=True)
        self.running = True
        self._seen = -1
        self._me = set()
        self._conn = None
        self.want_champ = False  # skin temasi isteniyorsa mac basina bir kez playerlist okunur
        self.champ = None        # (rawChampionName, skinID): kendi sampiyonun
        self._champ_tries = 0
        # API yalnizca 127.0.0.1'de, Riot'un kendi imzali sertifikasiyla calisir. Adres sabit ve yerel oldugu
        # icin sertifika dogrulamasi atlanir; hicbir veri gonderilmez, yalnizca okunur.
        self._ctx = ssl.create_default_context()
        self._ctx.check_hostname = False
        self._ctx.verify_mode = ssl.CERT_NONE

    def _get(self, path):
        if self._conn is None:
            self._conn = http.client.HTTPSConnection(self.HOST, self.PORT, timeout=0.8, context=self._ctx)
        try:
            self._conn.request("GET", "/liveclientdata/" + path, headers={"Accept": "application/json"})
            r = self._conn.getresponse()
            body = r.read()
        except Exception:
            self._close()
            raise
        if r.status != 200:
            raise OSError("HTTP %d" % r.status)
        return json.loads(body.decode("utf-8", "replace"))

    def _close(self):
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def player(self, active):
        """activeplayer verisinden saglik ve olum durumu (oluyken can 0'dir)."""
        active = active if isinstance(active, dict) else {}
        me = _ids(active.get("summonerName"), active.get("riotId"), active.get("riotIdGameName"))
        if me:
            self._me = me
        stats = active.get("championStats") or {}
        try:
            mx = float(stats.get("maxHealth") or 0)
            self.health = max(0.0, min(1.0, float(stats.get("currentHealth", 0)) / mx)) if mx > 0 else None
        except (TypeError, ValueError):
            self.health = None
        self.dead = self.health is not None and self.health <= 0.0

    def events(self, data):
        """eventdata'dan yeni olaylarin efekt kimlikleri."""
        me, new = self._me, []
        for e in ((data or {}).get("Events")) or []:
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

    def champion(self, players):
        """playerlist'ten kendi sampiyonun: (rawChampionName, skinID) ya da None."""
        me = self._me
        for p in players if isinstance(players, list) else []:
            if not isinstance(p, dict):
                continue
            if me & _ids(p.get("summonerName"), p.get("riotId"), p.get("riotIdGameName")):
                raw = p.get("rawChampionName") or p.get("championName")
                num = p.get("skinID", 0)
                if isinstance(raw, str) and raw:
                    return raw, num if isinstance(num, int) and 0 <= num < 1000 else 0
        return None

    def _reset(self):
        self._close()
        self._clear()
        self._seen = -1
        self.champ = None
        self._champ_tries = 0

    def run(self):
        ev_at = 0.0
        while self.running:
            if not self.wanted:
                if self.connected or self._conn is not None:
                    self._reset()
                time.sleep(0.5)
                continue
            try:
                self.player(self._get("activeplayer"))
                now = time.monotonic()
                if now - ev_at >= 0.5:
                    ev_at = now
                    new = self.events(self._get("eventdata"))
                    if self.connected:  # baglanirken gecmis olaylari yeniden oynatma
                        self.push(new)
                    if self.want_champ and self.champ is None and self._me and self._champ_tries < 5:
                        self._champ_tries += 1  # mac basina en fazla birkac kez; bulununca bir daha sorulmaz
                        self.champ = self.champion(self._get("playerlist"))
                self.connected = True
                time.sleep(0.25)
            except Exception:  # oyun yok, yukleme ekrani ya da gecici hata
                self._reset()
                time.sleep(3.0)


# ----------------------------------------------------------------------------- Counter-Strike 2
CS_PORT = 47816
CS_CFG_NAME = "gamestate_integration_fcuk.cfg"
CS_CFG = '''"FCUK Control Center"
{
 "uri" "http://127.0.0.1:%d"
 "timeout" "1.0"
 "buffer" "0.0"
 "throttle" "0.05"
 "heartbeat" "10.0"
 "auth"
 {
  "token" "%s"
 }
 "data"
 {
  "provider" "1"
  "map" "1"
  "round" "1"
  "player_id" "1"
  "player_state" "1"
  "player_match_stats" "1"
 }
}
'''


def steam_libraries():
    """Steam kutuphane klasorleri (kayit defteri + libraryfolders.vdf)."""
    import winreg
    roots = []
    for hive, key, name in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
                            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath")):
        try:
            with winreg.OpenKey(hive, key) as k:
                v = winreg.QueryValueEx(k, name)[0]
            if isinstance(v, str) and v:
                roots.append(os.path.normpath(v))
        except OSError:
            pass
    libs = []
    for root in roots:
        for p in [root] + _vdf_paths(os.path.join(root, "steamapps", "libraryfolders.vdf")):
            p = os.path.normpath(p)
            if p.lower() not in [x.lower() for x in libs]:
                libs.append(p)
    return libs


def _vdf_paths(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read(1 << 20)
    except OSError:
        return []
    return [m.replace("\\\\", "\\") for m in re.findall(r'"path"\s+"([^"]+)"', text)]


def cs_cfg_dirs():
    out = []
    for lib in steam_libraries():
        d = os.path.join(lib, "steamapps", "common", "Counter-Strike Global Offensive", "game", "csgo", "cfg")
        if os.path.isdir(d):
            out.append(d)
    return out


def install_cs_cfg():
    """CS2'nin cfg klasorune GSI dosyasini yazar (yoksa ya da farkliysa). Kimlik dogrulama anahtarini dondurur;
    CS2 kurulu degilse None. Var olan dosyadaki anahtar korunur (oyun yeniden baslatilmadan da gecerli kalir)."""
    dirs = cs_cfg_dirs()
    if not dirs:
        return None
    token = None
    for d in dirs:
        try:
            with open(os.path.join(d, CS_CFG_NAME), "r", encoding="utf-8") as f:
                m = re.search(r'"token"\s+"([0-9a-f]{32})"', f.read())
            if m:
                token = m.group(1)
                break
        except OSError:
            pass
    token = token or secrets.token_hex(16)
    body = CS_CFG % (CS_PORT, token)
    ok = False
    for d in dirs:
        p = os.path.join(d, CS_CFG_NAME)
        try:
            try:
                with open(p, "r", encoding="utf-8") as f:
                    if f.read() == body:
                        ok = True
                        continue
            except OSError:
                pass
            with open(p, "w", encoding="utf-8", newline="\n") as f:
                f.write(body)
            ok = True
        except OSError:
            pass
    return token if ok else None


class CsClient(GameSource):
    """CS2 Game State Integration alicisi: yalnizca 127.0.0.1:CS_PORT, yalnizca dogru anahtarla gelen veri.

    Sunucu wanted True oldugunda acilir, False olunca kapanir; bos dururken islemci kullanmaz."""
    TIMEOUT = 25.0  # oyun 10 sn'de bir durum yollar; bu kadar sessizlik: oyun kapandi

    def __init__(self):
        GameSource.__init__(self)
        self.token = None
        self.server = None
        self.last = 0.0
        self.problem_at = 0.0
        self._prev = {}
        self._lock2 = threading.Lock()

    def tick(self, now):
        """Motor her karede cagirir: sunucuyu ac/kapat, zaman asimini denetle (ucuz)."""
        if self.problem and self.wanted and now - self.problem_at > 60.0:
            self.problem = ""  # dakikada bir yeniden dene (CS2 sonradan kurulduysa / port bosaldiysa)
            self.token = None
        if self.wanted and self.server is None and not self.problem:
            self._start()
        elif not self.wanted and self.server is not None:
            self._stop()
        if self.connected and time.monotonic() - self.last > self.TIMEOUT:
            self._clear()
            self._prev = {}

    def _start(self):
        if self.problem:  # CS2 bulunamadi ya da port dolu: bu oturumda her karede yeniden denenmez
            return
        if self.token is None:
            self.token = install_cs_cfg()  # bir kez: disk taramasi
            if self.token is None:
                self.problem, self.problem_at = "nocfg", time.monotonic()
                return
        client = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    n = 0
                data = None
                if 0 < n <= 65536:
                    try:
                        data = json.loads(self.rfile.read(n).decode("utf-8", "replace"))
                    except ValueError:
                        data = None
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()
                if isinstance(data, dict):
                    client.receive(data)

            def log_message(self, *a):
                pass

        try:
            self.server = ThreadingHTTPServer(("127.0.0.1", CS_PORT), Handler)
            self.server.daemon_threads = True
        except OSError:
            self.server = None
            self.problem, self.problem_at = "port", time.monotonic()
            return
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 1.0}, daemon=True).start()

    def _stop(self):
        srv, self.server = self.server, None
        threading.Thread(target=lambda: (srv.shutdown(), srv.server_close()), daemon=True).start()
        self._clear()
        self._prev = {}

    def receive(self, data):
        """Oyundan gelen tek bir durum paketi."""
        auth = (data.get("auth") or {}).get("token")
        if not self.token or not isinstance(auth, str) or not secrets.compare_digest(auth, self.token):
            return
        with self._lock2:
            self.push(self.process(data))
            self.last = time.monotonic()
            self.connected = True

    def process(self, data):
        """Durumu gunceller, onceki pakete gore olusan olaylari dondurur."""
        prev, new = self._prev, []
        prov = (data.get("provider") or {}).get("steamid")
        pl = data.get("player") or {}
        st = pl.get("state") if isinstance(pl.get("state"), dict) else None
        mine = bool(prov) and pl.get("steamid") == prov and st is not None
        rnd = data.get("round") or {}
        mp = data.get("map") or {}
        if mine:
            hp = _num(st.get("health"), 0, 100)
            self.health = hp / 100.0
            self.dead = hp <= 0
            self.flashed = _num(st.get("flashed"), 0, 255) / 255.0
            self.burning = _num(st.get("burning"), 0, 255) > 0
            php = prev.get("hp")
            if php is not None and hp < php:
                new.append("death" if hp <= 0 else "hit")
            kills = _num(st.get("round_kills"), 0, 10)
            pk = prev.get("kills")
            if pk is not None and kills > pk:
                new.append("multi%d" % min(5, kills) if kills >= 3 else "kill")
            prev["hp"], prev["kills"] = hp, kills
            if pl.get("team") in ("CT", "T"):
                prev["team"] = pl["team"]
        elif prov and pl.get("steamid") and pl.get("steamid") != prov:
            self.dead, self.flashed, self.burning = True, 0.0, False  # olunce takim arkadasini izliyorsun
            self.health = 0.0
            prev["hp"] = 0
        else:  # ana menu
            self.health, self.dead, self.flashed, self.burning = None, False, 0.0, False
            prev.pop("hp", None)
        bomb = rnd.get("bomb")
        if "bomb" in prev and bomb != prev["bomb"] and bomb in ("planted", "defused", "exploded"):
            new.append({"planted": "bomb", "defused": "defused", "exploded": "exploded"}[bomb])
        prev["bomb"] = bomb
        key = (mp.get("name"), mp.get("round"), rnd.get("phase"))
        if rnd.get("phase") == "over" and rnd.get("win_team") and key != prev.get("over"):
            prev["over"] = key
            if prev.get("team"):
                new.append("win" if rnd["win_team"] == prev["team"] else "lose")
        return new


def _num(v, lo, hi):
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return lo
