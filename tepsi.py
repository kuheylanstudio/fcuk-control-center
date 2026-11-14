# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""Sistem tepsisi simgesi: ayri, NORMAL yetkili hafif bir surec (pythonw control_center.py --tray).

Neden ayri surec: motor yonetici olarak calisir. Windows (UIPI) normal yetkili Gezgin'den yonetici
penceresine gelen tepsi tiklamalarini engeller; ayrica simgeden acilan pencere de yonetici olurdu.
Simge motorla, arayuzun kullandigi yerel API uzerinden konusur.

Sol tik: pencereyi ac.  Sag tik: profiller, fan, pencere, cikis.
Simge rengi ve yay uzunlugu etkin profilin seviyesini gosterir; ipucu canli sicaklik ve gucu yazar.
"""
import ctypes
import json
import os
import threading
import time
import urllib.request
from ctypes import wintypes as wt

import ceviri
import fntus
import klavye_rgb as core
from ceviri import t

u32 = ctypes.WinDLL("user32", use_last_error=True)
k32 = ctypes.WinDLL("kernel32", use_last_error=True)
sh32 = ctypes.WinDLL("shell32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)

WM_DESTROY, WM_NULL = 0x0002, 0x0000
WM_LBUTTONUP, WM_RBUTTONUP, WM_CONTEXTMENU = 0x0202, 0x0205, 0x007B
WM_APP = 0x8000
WM_TRAY = WM_APP + 1      # simgeden gelen fare olaylari
WM_REFRESH = WM_APP + 2   # yoklayici yeni durum getirdi
WM_CLOSE_TRAY = WM_APP + 3
WM_FNKEY = WM_APP + 4     # Fn tusu dinleyicisi bir kod yakaladi (wparam)
WM_OSD = WM_APP + 5       # arka plan is parcacigindan OSD istegi (self.osd_req)
TRAY_CLASS = "KendiControlCenterTray"             # setup.exe bu sinifla tepsi penceresini bulur
OPEN_MESSAGE = "FCUKControlCenter.PencereyiAc"    # setup.exe'deki ad ile ayni olmali
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO, NIF_SHOWTIP = 0x01, 0x02, 0x04, 0x10, 0x80
NIIF_NOSOUND = 0x10
MF_STRING, MF_GRAYED, MF_CHECKED, MF_POPUP, MF_SEPARATOR, MF_RADIOCHECK = 0, 0x1, 0x8, 0x10, 0x800, 0x200
TPM_RIGHTBUTTON, TPM_RETURNCMD, TPM_NONOTIFY = 0x2, 0x100, 0x80
IMAGE_ICON, LR_LOADFROMFILE = 1, 0x10
ERROR_ALREADY_EXISTS = 183

# Seviye ve renk: soguk maviden uyari kirmizisina (ui/index.html --warn ve --danger ile ayni aile)
LEVELS = {"tam_sessiz": 1, "sessiz_kullanim": 2, "sessiz_oyun": 3, "performans": 4, "ultra": 5}
COLORS = {0: (129, 138, 153), 1: (88, 166, 255), 2: (64, 200, 200), 3: (92, 214, 120),
          4: (255, 180, 84), 5: (255, 107, 107)}


class GUID(ctypes.Structure):
    _fields_ = [("a", wt.DWORD), ("b", wt.WORD), ("c", wt.WORD), ("d", ctypes.c_ubyte * 8)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("hWnd", wt.HWND), ("uID", wt.UINT), ("uFlags", wt.UINT),
                ("uCallbackMessage", wt.UINT), ("hIcon", wt.HICON), ("szTip", wt.WCHAR * 128),
                ("dwState", wt.DWORD), ("dwStateMask", wt.DWORD), ("szInfo", wt.WCHAR * 256),
                ("uVersion", wt.UINT), ("szInfoTitle", wt.WCHAR * 64), ("dwInfoFlags", wt.DWORD),
                ("guidItem", GUID), ("hBalloonIcon", wt.HICON)]


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", wt.UINT), ("style", wt.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
                ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH), ("lpszMenuName", wt.LPCWSTR),
                ("lpszClassName", wt.LPCWSTR), ("hIconSm", wt.HICON)]


u32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
u32.DefWindowProcW.restype = LRESULT
u32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
u32.RegisterClassExW.restype = wt.ATOM
u32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
u32.CreateWindowExW.restype = wt.HWND
u32.RegisterWindowMessageW.argtypes = [wt.LPCWSTR]
u32.RegisterWindowMessageW.restype = wt.UINT
u32.LoadImageW.argtypes = [wt.HINSTANCE, wt.LPCWSTR, wt.UINT, ctypes.c_int, ctypes.c_int, wt.UINT]
u32.LoadImageW.restype = wt.HANDLE
u32.GetSystemMetrics.argtypes = [ctypes.c_int]
u32.CreatePopupMenu.restype = wt.HMENU
u32.AppendMenuW.argtypes = [wt.HMENU, wt.UINT, ctypes.c_size_t, wt.LPCWSTR]
u32.TrackPopupMenu.argtypes = [wt.HMENU, wt.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HWND, wt.LPVOID]
u32.TrackPopupMenu.restype = ctypes.c_int
u32.DestroyMenu.argtypes = [wt.HMENU]
u32.SetForegroundWindow.argtypes = [wt.HWND]
u32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
u32.GetCursorPos.argtypes = [ctypes.POINTER(wt.POINT)]
u32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
u32.TranslateMessage.argtypes = [ctypes.POINTER(wt.MSG)]
u32.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]
u32.DestroyWindow.argtypes = [wt.HWND]
u32.DestroyIcon.argtypes = [wt.HICON]
sh32.Shell_NotifyIconW.argtypes = [wt.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
sh32.Shell_NotifyIconW.restype = wt.BOOL
k32.CreateMutexW.argtypes = [wt.LPVOID, wt.BOOL, wt.LPCWSTR]
k32.CreateMutexW.restype = wt.HANDLE
k32.CloseHandle.argtypes = [wt.HANDLE]
k32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
k32.GetModuleHandleW.restype = wt.HMODULE


# ----------------------------------------------------------------------------- simge cizimi
def icon_path(level):
    return os.path.join(core.CONFIG_DIR, "tepsi_%d.ico" % level)


def draw(level, n=256):
    """Koyu yuvarlak kare + seviye kadar dolu gosterge yayi + merkez nokta (PIL Image)."""
    from PIL import Image, ImageDraw
    rgb = COLORS[level]
    im = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((8, 8, n - 8, n - 8), radius=56, fill=(17, 20, 25, 255), outline=(59, 67, 80, 255), width=6)
    box, w = (40, 40, n - 40, n - 40), 34
    d.arc(box, 135, 405, fill=(37, 42, 51, 255), width=w)            # bos iz
    if level:
        d.arc(box, 135, 135 + 270 * level / 5.0, fill=rgb + (255,), width=w)
    c = n // 2
    d.ellipse((c - 26, c - 26, c + 26, c + 26), fill=rgb + (255,))   # merkez nokta: 16 pikselde de gorunur
    return im


def make_app_icon(path):
    """Exe simgesi: tepsiyle ayni tasarim, Sessiz Oyun seviyesi; 16-256 piksel."""
    draw(3).save(path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def make_icons():
    """Her seviye icin tepsi .ico'su uretir (PIL varsa)."""
    try:
        import PIL  # noqa: F401
    except ImportError:
        return False
    os.makedirs(core.CONFIG_DIR, exist_ok=True)
    for level in COLORS:
        path = icon_path(level)
        if not os.path.exists(path):
            draw(level).save(path, sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (48, 48), (64, 64)])
    return True


def load_icon(level):
    size = u32.GetSystemMetrics(49)  # SM_CXSMICON, DPI'ya gore 16/20/24
    h = u32.LoadImageW(None, icon_path(level), IMAGE_ICON, size, size, LR_LOADFROMFILE)
    return h or u32.LoadImageW(None, ctypes.c_wchar_p(32512), IMAGE_ICON, 0, 0, 0x8000)  # IDI_APPLICATION


# ----------------------------------------------------------------------------- motorla konusma
class Api:
    def __init__(self, base):
        self.base = base
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def get(self, path, timeout=1.5):
        with self.opener.open(self.base + path, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def post(self, path, body, timeout=30):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json"})
        with self.opener.open(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))


# ----------------------------------------------------------------------------- tepsi
class Tray:
    ID_OPEN, ID_FAN_PROFILE, ID_FAN_AUTO, ID_FAN_MAX, ID_QUIT, ID_START = 1, 2, 3, 4, 5, 6
    ID_PROFILE = 100  # + profil sirasi

    def __init__(self, base, open_window, start_engine):
        self.api = Api(base)
        self.open_window = open_window
        self.start_engine = start_engine
        self.state = None          # son /api/tray yaniti; None: motor yok
        self.notice_seen = 0       # motorun bildirdigi en son uyari (balon olarak bir kez gosterilir)
        self.down_since = None
        self.seen_engine = False
        self.level = 0
        self.icons = {}
        self.running = True
        self._proc = WNDPROC(self._wndproc)  # referans canli kalmali
        self.taskbar_created = u32.RegisterWindowMessageW("TaskbarCreated")
        # setup.exe "Bitince ac": yonetici kurulum pencereyi kendisi acmaz, bu mesajla tepsiden (normal yetki,
        # sag tik > Ac ile ayni yol) acilmasini ister. Yuksek yetkiden dusuge PostMessage UIPI'ye takilmaz.
        self.open_request = u32.RegisterWindowMessageW(OPEN_MESSAGE)

    # -- pencere ve simge
    def create(self):
        hinst = k32.GetModuleHandleW(None)
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = self._proc
        wc.hInstance = hinst
        wc.lpszClassName = TRAY_CLASS
        u32.RegisterClassExW(ctypes.byref(wc))
        # Gorunmez ust duzey pencere (yalnizca-mesaj penceresi TaskbarCreated yayinini alamaz)
        self.hwnd = u32.CreateWindowExW(0, wc.lpszClassName, "FCUK Control Center", 0, 0, 0, 0, 0,
                                        None, None, hinst, None)
        self.nid = NOTIFYICONDATAW()
        self.nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        self.nid.hWnd = self.hwnd
        self.nid.uID = 1
        self.nid.uCallbackMessage = WM_TRAY
        self._add()
        # Fn tuslari + ekran bildirimi (Monster FnKey.exe yerine)
        self.osd_req = None
        try:
            self.osd = fntus.Osd()
            fntus.log("OSD penceresi hazir (hwnd %s)" % self.osd.hwnd)
        except Exception:
            import traceback
            fntus.log("OSD olusturulamadi: " + traceback.format_exc().replace("\n", " | "))
        self.fn = fntus.Listener(lambda code: u32.PostMessageW(self.hwnd, WM_FNKEY, code, 0))
        self.fn.start()

    # -- Fn tuslari
    def _osd_later(self, label, value="", level=None, state=None):
        """Arka plan is parcacigindan: OSD'yi pencere is parcacigina gosterttir."""
        self.osd_req = (label, value, level, state)
        u32.PostMessageW(self.hwnd, WM_OSD, 0, 0)

    def _kb(self, action):
        try:
            r = self.api.post("/api/kb", {"action": action}, timeout=5)
            if action == "next":
                self._osd_later(t("osd.kb"), r.get("mode_label", ""), state=True)
            else:
                b = r.get("brightness", 0)
                self._osd_later(t("osd.kbLight"), t("osd.off") if b == 0 else ceviri.pct(b), b, b > 0)
        except (OSError, ValueError):
            self._osd_later(t("osd.kbLight"), t("tray.engineDown"), state=False)

    def _touchpad(self):
        time.sleep(0.4)  # donanim cevirsin, Windows durumu yazsin
        on = fntus.touchpad_enabled()
        self._osd_later(t("osd.touchpad"), "" if on is None else t("osd.on" if on else "osd.off"), state=on)

    def fn_key(self, code):
        bg = lambda f, *a: threading.Thread(target=f, args=a, daemon=True).start()
        if code == fntus.FN_TOUCHPAD:
            bg(self._touchpad)
        elif code == fntus.FN_SCREEN_OFF:
            bg(fntus.screen_off)
        elif code == fntus.FN_CAMERA_OFF:
            self.osd.show(t("osd.camera"), t("osd.off"), state=False)
        elif code == fntus.FN_CAMERA_ON:
            self.osd.show(t("osd.camera"), t("osd.on"), state=True)
        elif code == fntus.FN_AIRPLANE:
            self.osd.show(t("osd.airplane"), t("osd.changed"))
        elif code in (fntus.FN_KB_TOGGLE, fntus.FN_KB_UP, fntus.FN_KB_DOWN, fntus.FN_KB_NEXT):
            bg(self._kb, {fntus.FN_KB_TOGGLE: "toggle", fntus.FN_KB_UP: "up",
                          fntus.FN_KB_DOWN: "down", fntus.FN_KB_NEXT: "next"}[code])
        # FN_MUTE / FN_VOLUME: Windows kendi bildirimini gosterir

    def _icon(self, level):
        if level not in self.icons:
            self.icons[level] = load_icon(level)
        return self.icons[level]

    def _add(self):
        self.nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP | NIF_SHOWTIP
        self.nid.hIcon = self._icon(self.level)
        self.nid.szTip = self._tip()
        sh32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(self.nid))

    def _update(self):
        s = self.state
        self.level = LEVELS.get(s.get("profile"), 0) if s else 0
        self.nid.uFlags = NIF_ICON | NIF_TIP | NIF_SHOWTIP
        self.nid.hIcon = self._icon(self.level)
        self.nid.szTip = self._tip()
        sh32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self.nid))

    def notify(self, title, text):
        nid = NOTIFYICONDATAW()
        nid.cbSize, nid.hWnd, nid.uID = self.nid.cbSize, self.hwnd, 1
        nid.uFlags = NIF_INFO
        nid.szInfoTitle = title[:63]
        nid.szInfo = text[:255]
        nid.dwInfoFlags = NIIF_NOSOUND
        sh32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    def _name(self, pid):
        for p in (self.state or {}).get("profiles", []):
            if p["id"] == pid:
                return p["name"]
        return ""

    def _tip(self):
        s = self.state
        if not s:
            return "FCUK Control Center\n" + (t("tray.engineDown") if self.seen_engine else t("tray.engineStarting"))
        line = t("tray.profile", name=self._name(s.get("profile")) or t("tray.none"))
        if s.get("guard"):
            line += " (%s)" % t("tray.guard")
        cpu = t("tray.cpu", t=s.get("cpu_temp", "?"))
        if s.get("cpu_power") is not None:
            cpu += " · %s W" % s["cpu_power"]
        g = t("tray.gpu", t=s.get("gpu_temp", "?")) if s.get("gpu_state") == "active" else t("tray.gpuAsleep")
        return "\n".join(["FCUK Control Center", line, cpu, g])[:127]

    # -- yoklama (ayri is parcacigi; simgeyi ana is parcacigi gunceller)
    def poll(self):
        while self.running:
            try:
                self.state = self.api.get("/api/tray")
                if self.state.get("lang") and self.state["lang"] != ceviri.lang():
                    ceviri.set_lang(self.state["lang"])  # arayuzden dil degisti
                self.seen_engine = True
                self.down_since = None
                self._show_notices()
            except (OSError, ValueError):
                self.state = None
                self.down_since = self.down_since or time.monotonic()
                # Motor kapatildiysa (arayuzden "Cik") simge de gider. Bekcinin yeniden baslatmasi ~3 sn surer.
                if self.seen_engine and time.monotonic() - self.down_since > 8:
                    u32.PostMessageW(self.hwnd, WM_CLOSE_TRAY, 0, 0)
                    return
            u32.PostMessageW(self.hwnd, WM_REFRESH, 0, 0)
            time.sleep(2.0)

    def _show_notices(self):
        """Motorun kullaniciya iletmek istedigi sorunlar (bozuk ayar, isi bekcisi, okunamayan sensor...)."""
        for n in (self.state or {}).get("notices") or []:
            if isinstance(n, dict) and isinstance(n.get("id"), int) and n["id"] > self.notice_seen:
                self.notice_seen = n["id"]
                self.notify("FCUK Control Center uyarısı", str(n.get("text", "")))

    # -- menu
    def menu(self):
        s = self.state
        m = u32.CreatePopupMenu()
        u32.AppendMenuW(m, MF_STRING, self.ID_OPEN, t("tray.open"))
        u32.AppendMenuW(m, MF_SEPARATOR, 0, None)
        if s:
            for i, p in enumerate(s.get("profiles", [])):
                flags = MF_STRING | MF_RADIOCHECK
                label = p["name"]
                if p["id"] == s.get("profile"):
                    flags |= MF_CHECKED
                if p.get("ac_only") and not s.get("ac", True):
                    flags |= MF_GRAYED
                    label += " (%s)" % t("tray.acOnly")
                u32.AppendMenuW(m, flags, self.ID_PROFILE + i, label)
            if s.get("ec", True):  # fan menusu yalnizca Clevo/Monster denetleyicisi varsa
                u32.AppendMenuW(m, MF_SEPARATOR, 0, None)
                fan = u32.CreatePopupMenu()
                fm = s.get("fan_mode")
                for cid, label, on in ((self.ID_FAN_PROFILE, t("tray.fanProfile"), fm == 6),
                                       (self.ID_FAN_AUTO, t("tray.fanAuto"), fm == 0),
                                       (self.ID_FAN_MAX, t("tray.fanMax"), fm == 1)):
                    u32.AppendMenuW(fan, MF_STRING | MF_RADIOCHECK | (MF_CHECKED if on else 0), cid, label)
                u32.AppendMenuW(m, MF_POPUP, fan,
                                t("tray.fan", mode=t("trayfan.%s" % fm) if fm in (0, 1, 6) else "?"))
        else:
            u32.AppendMenuW(m, MF_STRING, self.ID_START, t("tray.start"))
        u32.AppendMenuW(m, MF_SEPARATOR, 0, None)
        u32.AppendMenuW(m, MF_STRING, self.ID_QUIT, t("tray.quit"))
        pt = wt.POINT()
        u32.GetCursorPos(ctypes.byref(pt))
        u32.SetForegroundWindow(self.hwnd)  # yoksa menu disina tiklayinca kapanmaz
        cmd = u32.TrackPopupMenu(m, TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY, pt.x, pt.y, 0, self.hwnd, None)
        u32.PostMessageW(self.hwnd, WM_NULL, 0, 0)
        u32.DestroyMenu(m)  # alt menuyu de yok eder
        if cmd:
            self.command(cmd)

    def command(self, cmd):
        s = self.state or {}
        if cmd == self.ID_OPEN:
            threading.Thread(target=self.open_window, daemon=True).start()
        elif cmd == self.ID_START:
            threading.Thread(target=self.start_engine, daemon=True).start()
        elif cmd == self.ID_QUIT:
            def quit_all():
                try:
                    self.api.post("/api/quit", {}, timeout=3)
                except (OSError, ValueError):
                    pass
                u32.PostMessageW(self.hwnd, WM_CLOSE_TRAY, 0, 0)
            threading.Thread(target=quit_all, daemon=True).start()
        elif cmd >= self.ID_PROFILE:
            profiles = s.get("profiles", [])
            i = cmd - self.ID_PROFILE
            if 0 <= i < len(profiles):
                threading.Thread(target=self._apply, args=(profiles[i],), daemon=True).start()
        elif cmd in (self.ID_FAN_PROFILE, self.ID_FAN_AUTO, self.ID_FAN_MAX):
            mode = {self.ID_FAN_PROFILE: "profile", self.ID_FAN_AUTO: "auto", self.ID_FAN_MAX: "max"}[cmd]
            threading.Thread(target=self._fan, args=(mode,), daemon=True).start()

    def _refresh_now(self):
        try:
            self.state = self.api.get("/api/tray")
        except (OSError, ValueError):
            pass
        u32.PostMessageW(self.hwnd, WM_REFRESH, 0, 0)

    def _apply(self, p):
        try:
            r = self.api.post("/api/profile", {"id": p["id"]})
            bad = [x for x in r.get("report", []) if not x.get("ok")]
            if bad:
                self.notify(t("tray.partial", name=p["name"]), "; ".join("%s: %s" % (x["step"], x["msg"]) for x in bad))
            else:
                self.notify(p["name"], t("tray.applied"))
        except (OSError, ValueError) as exc:
            self.notify(t("tray.applyFail"), str(exc))
        self._refresh_now()

    def _fan(self, mode):
        try:
            r = self.api.post("/api/fan", {"mode": mode})
            if r.get("error"):
                self.notify(t("step.fan"), r["error"])
        except (OSError, ValueError) as exc:
            self.notify(t("tray.fanFail"), str(exc))
        self._refresh_now()

    # -- mesajlar
    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_TRAY:
                ev = lparam & 0xFFFF
                if ev == WM_LBUTTONUP:
                    self.command(self.ID_OPEN)
                elif ev in (WM_RBUTTONUP, WM_CONTEXTMENU):
                    self.menu()
                return 0
            if msg == WM_REFRESH:
                self._update()
                return 0
            if msg == WM_FNKEY:
                try:
                    self.fn_key(int(wparam))
                except Exception:
                    import traceback
                    fntus.log("fn_key hatasi: " + traceback.format_exc().replace("\n", " | "))
                return 0
            if msg == WM_OSD:
                try:
                    if self.osd_req:
                        self.osd.show(*self.osd_req)
                except Exception:
                    import traceback
                    fntus.log("osd hatasi: " + traceback.format_exc().replace("\n", " | "))
                return 0
            if msg == self.open_request and msg:
                self.command(self.ID_OPEN)
                return 0
            if msg == self.taskbar_created:  # Gezgin yeniden basladi: simgeyi geri koy
                self._add()
                return 0
            if msg == WM_CLOSE_TRAY:
                u32.DestroyWindow(hwnd)
                return 0
            if msg == WM_DESTROY:
                self.running = False
                sh32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self.nid))
                u32.PostQuitMessage(0)
                return 0
        except Exception:  # bir hata pencere yordamindan disari tasmasin
            pass
        return u32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def loop(self):
        threading.Thread(target=self.poll, daemon=True).start()
        msg = wt.MSG()
        while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            u32.TranslateMessage(ctypes.byref(msg))
            u32.DispatchMessageW(ctypes.byref(msg))
        self.running = False
        for h in self.icons.values():
            if h:
                u32.DestroyIcon(h)


def run(base, open_window, start_engine):
    """Tek ornek: ikinci --tray sessizce cikar. Simge kapanana dek doner."""
    mutex = k32.CreateMutexW(None, False, "Local\\KendiControlCenterTray")
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        return
    try:
        make_icons()
    except Exception as exc:  # simge cizilemezse varsayilan simgeyle surer
        fntus.log("tepsi simgeleri olusturulamadi: %r" % exc)
    tray = Tray(base, open_window, start_engine)
    tray.create()
    tray.loop()
    k32.CloseHandle(mutex)
