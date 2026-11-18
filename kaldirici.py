# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""Kaldirici: yuklu uygulamalar, uygulamanin kendi kaldiricisi ve geride kalan artiklarin temizligi.

Akis:
  1. installed_apps(): Windows'un "Programlar ve Ozellikler" listesi (Uninstall kayit anahtarlari).
  2. Uninstaller.start(): istenirse once sistem geri yukleme noktasi, sonra uygulamanin kendi kaldiricisi.
  3. scan(): geride kalan klasorler, kisayollar, kayit defteri anahtarlari / degerleri, servisler,
     zamanlanmis gorevler ve guvenlik duvari kurallari. Uc tarama duzeyi:
       safe      ad birebir eslesir, yalnizca bilinen yerler (AppData, ProgramData, Program Files,
                 Baslat menusu, HKCU/HKLM\\Software)
       moderate  + ad on ek eslesmesi, LocalLow / Temp / masaustu, yayinci klasoru, baslangic girdileri,
                 App Paths, servisler ve gorevler (yalnizca kurulum klasorune isaret edenler)
       advanced  + ad icerik eslesmesi, Belgeler / Kayitli oyunlar, guvenlik duvari kurallari
     Gelismis duzeyin bulduklari ve uygulama hala kayitliyken bulunan her sey varsayilan olarak SECILMEZ.
  4. clean(): yalnizca son taramadaki ve kullanicinin sectigi ogeler. Kayit defteri ve gorevler once
     yedek klasorune (.reg / .xml) aktarilir, dosyalar Geri Donusum Kutusu'na gider.

Guvenlik kurallari (hem taramada hem silmeden hemen once yeniden denetlenir):
  * Kok klasorler (Program Files, AppData, Windows ...), suruculer ve bunlarin ustleri asla onerilmez.
  * Windows klasorunun ve Control Center'in kendi klasorunun icindeki hicbir sey onerilmez.
  * Baska bir yuklu uygulamanin klasoru (ya da onu iceren / onun icindeki bir klasor) onerilmez.
  * Ad eslesmesi baska bir yuklu uygulamaya daha iyi uyuyorsa (Discord / Discord PTB) oneri yapilmaz.
  * Genel adlar (Microsoft, Common Files, Temp, Update ...) ve kisa adlar eslesmeye katilmaz.
  * Kayit defterinde yalnizca izin verilen yerlerdeki anahtarlar silinebilir (Software\\<ad>,
    Software\\<yayinci>\\<ad>, Uninstall\\<ad>, App Paths\\<ad>, Services\\<ad>); Software\\Microsoft,
    Classes, Policies gibi dallar asla.
"""
import ctypes
import json
import os
import re
import shutil
import subprocess
import threading
import time
from ctypes import wintypes as wt

try:
    import winreg
except ImportError:  # testler Windows disinda da ice aktarilabilsin
    winreg = None

CREATE_NO_WINDOW = 0x08000000
SAFE, MODERATE, ADVANCED = 0, 1, 2
MODES = {"safe": SAFE, "moderate": MODERATE, "advanced": ADVANCED}

UNINSTALL = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
UNINSTALL_ROOTS = (
    "HKLM\\" + UNINSTALL,
    "HKLM\\SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall",
    "HKCU\\" + UNINSTALL,
)
REG_BASES = ("HKCU\\Software", "HKLM\\SOFTWARE", "HKLM\\SOFTWARE\\WOW6432Node")
RUN_KEYS = (
    "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run",
    "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\RunOnce",
    "HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run",
    "HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\RunOnce",
    "HKLM\\SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Run",
)
APP_PATHS = (
    "HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths",
    "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\App Paths",
)
SERVICES = "HKLM\\SYSTEM\\CurrentControlSet\\Services"
FIREWALL = "HKLM\\SYSTEM\\CurrentControlSet\\Services\\SharedAccess\\Parameters\\FirewallPolicy\\FirewallRules"
CLASSES_APPS = "HKCU\\Software\\Classes\\Applications"

# Dosya kokleri: (anahtar, en dusuk duzey). Kisayol kokleri disinda yalnizca klasorler onerilir.
FILE_ROOTS = (
    ("appdata", SAFE), ("local", SAFE), ("programdata", SAFE), ("pf", SAFE), ("pf86", SAFE),
    ("start_user", SAFE), ("start_common", SAFE),
    ("locallow", MODERATE), ("temp", MODERATE), ("desktop", MODERATE), ("public_desktop", MODERATE),
    ("documents", ADVANCED), ("saved_games", ADVANCED),
)
LINK_ROOTS = {"start_user", "start_common", "desktop", "public_desktop"}

# Eslesmeye asla katilmayan genel adlar (norm() bicimiyle)
GENERIC = set("""
microsoft windows windowsapps commonfiles packages temp tmp programs startup system32 syswow64 installer
packagecache nvidia nvidiacorporation intel intelcorporation amd advancedmicrodevices realtek dell hp
lenovo asus app apps application applications data cache caches common shared update updater updates user users
default public program programfiles programfilesx86 programdata appdata local locallow roaming documents desktop
downloads games game launcher client tools tool bin lib plugins setup uninstall install installs system software
support help logs log config settings crashdumps crashreports d3dscache fonts history inetcache classes policies
wow6432node clients registeredapplications odbc services microsoftcorporation package runtime drivers
driver khronos partner savedgames mygames steamapps steamlibrary
""".split())
# Sistem bileseni sayilan uygulamalar: kaldirmak baska programlari bozabilir (arayuz uyari gosterir)
CRITICAL = re.compile(r"redistributable|runtime|\.net|directx|driver|sürücü|visual c\+\+|webview2|framework|"
                      r"chipset|management engine|platform|firmware|update health|windows sdk", re.I)
CRITICAL_PUB = re.compile(r"microsoft|nvidia|intel|advanced micro|amd|realtek|qualcomm|mediatek|dolby|waves", re.I)

GUID = re.compile(r"\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}")
_SUFFIX = re.compile(r"[\s,]+(inc|incorporated|ltd|limited|llc|l\.l\.c|corp|corporation|gmbh|co|company|s\.?a|srl|"
                     r"s\.r\.l|ag|bv|b\.v|oy|ab|pty|plc|kk|sas)\.?$", re.I)


class Error(Exception):
    """Arayuze gidecek hata: code -> ceviri anahtari un.err.<code>."""

    def __init__(self, code):
        Exception.__init__(self, code)
        self.code = code


# ------------------------------------------------------------------ ad isleme
def norm(s):
    """Karsilastirma bicimi: kucuk harf, yalnizca harf ve rakam (Unicode)."""
    return re.sub(r"[\W_]+", "", (s or "").casefold())


def clean_name(name):
    """'7-Zip 23.01 (x64)' -> '7-Zip'; surum, mimari ve parantez icleri atilir."""
    s = re.sub(r"\(.*?\)|\[.*?\]", " ", name or "")
    s = re.sub(r"\b(v(er(sion)?)?\.?\s*)?\d+([._]\d+)+[a-z]?\b", " ", s, flags=re.I)
    s = re.sub(r"\b(x64|x86|amd64|arm64|win64|win32|64-bit|32-bit|64 bit|32 bit|en-us|remove only)\b", " ", s, flags=re.I)
    s = " ".join(s.split()).strip(" -_,.:")
    return s or (name or "").strip()


def clean_publisher(pub):
    s = (pub or "").strip()
    for _ in range(3):
        t = _SUFFIX.sub("", s).strip(" ,.")
        if t == s:
            break
        s = t
    return s


def candidates(app):
    """Uygulamanin artiklarda arayacagimiz ad bicimleri (norm)."""
    name = clean_name(app.get("name", ""))
    pub = clean_publisher(app.get("publisher", ""))
    out = {norm(name)}
    if pub and name.casefold().startswith(pub.casefold() + " "):  # 'Mozilla Firefox' -> 'Firefox'
        out.add(norm(name[len(pub):]))
    loc = app.get("location")
    if loc:
        out.add(norm(os.path.basename(loc.rstrip("\\/"))))
    key = app.get("key", "")
    if key and not GUID.fullmatch(key) and re.search(r"[A-Za-z]", key):
        out.add(norm(clean_name(key)))
    return {c for c in out if len(c) >= 3 and not c.isdigit() and c not in GENERIC}


def publishers(app):
    pubs = {norm(app.get("publisher", "")), norm(clean_publisher(app.get("publisher", "")))}
    return {p for p in pubs if len(p) >= 3 and p not in GENERIC}


def match_level(name, cands):
    """Klasor / anahtar adi uygulamaya ne kadar uyuyor: SAFE (birebir), MODERATE (on ek), ADVANCED (icerir)."""
    n = norm(name)
    if not n or n in GENERIC:
        return None, ""
    if n in cands:
        return SAFE, n
    long = sorted((c for c in cands if len(c) >= 5), key=len, reverse=True)
    for c in long:
        if n.startswith(c):
            return MODERATE, c
    for c in long:
        if c in n:
            return ADVANCED, c
    return None, ""


# ------------------------------------------------------------------ kayit defteri
class WinReg:
    """Kayit defteri; her zaman 64 bit gorunumu (32 bit dallar acik WOW6432Node yoluyla)."""

    def _open(self, path, access=None):
        hive, _, sub = path.partition("\\")
        root = {"HKLM": winreg.HKEY_LOCAL_MACHINE, "HKCU": winreg.HKEY_CURRENT_USER}[hive.upper()]
        return winreg.OpenKey(root, sub, 0, (access or winreg.KEY_READ) | winreg.KEY_WOW64_64KEY)

    def subkeys(self, path):
        out = []
        try:
            with self._open(path) as k:
                i = 0
                while True:
                    try:
                        out.append(winreg.EnumKey(k, i))
                    except OSError:
                        break
                    i += 1
        except OSError:
            pass
        return out

    def values(self, path):
        out = {}
        try:
            with self._open(path) as k:
                i = 0
                while True:
                    try:
                        name, val, _ = winreg.EnumValue(k, i)
                    except OSError:
                        break
                    out[name] = val
                    i += 1
        except OSError:
            pass
        return out

    def exists(self, path):
        try:
            with self._open(path):
                return True
        except OSError:
            return False

    def delete_key(self, path):
        parent, _, name = path.rpartition("\\")
        with self._open(parent, winreg.KEY_ALL_ACCESS) as k:
            fn = ctypes.windll.advapi32.RegDeleteTreeW
            fn.argtypes = [wt.HKEY, wt.LPCWSTR]
            rc = fn(wt.HKEY(k.handle), name)
            if rc not in (0, 2):  # 2: zaten yok
                raise ctypes.WinError(rc)
            try:
                winreg.DeleteKeyEx(k, name, winreg.KEY_WOW64_64KEY, 0)
            except OSError:
                pass

    def delete_value(self, path, name):
        with self._open(path, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, name)


# ------------------------------------------------------------------ klasorler
class _GUID(ctypes.Structure):
    _fields_ = [("a", ctypes.c_ulong), ("b", ctypes.c_ushort), ("c", ctypes.c_ushort), ("d", ctypes.c_ubyte * 8)]


def _known_folder(guid):
    try:
        h = guid.strip("{}").replace("-", "")
        g = _GUID(int(h[:8], 16), int(h[8:12], 16), int(h[12:16], 16), (ctypes.c_ubyte * 8)(*bytes.fromhex(h[16:])))
        p = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(p)) != 0:
            return ""
        value = p.value or ""
        ctypes.windll.ole32.CoTaskMemFree(p)
        return value
    except (OSError, AttributeError, ValueError):
        return ""


def default_roots():
    e = os.environ.get
    prof = e("USERPROFILE", "")
    appdata = e("APPDATA", os.path.join(prof, "AppData", "Roaming"))
    pdata = e("PROGRAMDATA", r"C:\ProgramData")
    return {
        "appdata": appdata,
        "local": e("LOCALAPPDATA", os.path.join(prof, "AppData", "Local")),
        "locallow": _known_folder("{A520A1A4-1780-4FF6-BD18-167343C5AF16}") or os.path.join(prof, "AppData", "LocalLow"),
        "programdata": pdata,
        "pf": e("ProgramW6432") or e("ProgramFiles", r"C:\Program Files"),
        "pf86": e("ProgramFiles(x86)", ""),
        "start_user": _known_folder("{A77F5D77-2E2B-44C3-A6A2-ABA601054A51}") or os.path.join(appdata, r"Microsoft\Windows\Start Menu\Programs"),
        "start_common": _known_folder("{0139D44E-6AFE-49F2-8690-3DAFCAE6FFB8}") or os.path.join(pdata, r"Microsoft\Windows\Start Menu\Programs"),
        "temp": e("TEMP", ""),
        "desktop": _known_folder("{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}") or os.path.join(prof, "Desktop"),
        "public_desktop": _known_folder("{C4AA340D-F20F-4863-AFEF-F87EF2E6BA25}"),
        "documents": _known_folder("{FDD39AD0-238F-46AF-ADB4-6C85480369C7}") or os.path.join(prof, "Documents"),
        "saved_games": _known_folder("{4C5C32FF-BB9D-43B0-B5B4-2D72E54EAAA4}") or os.path.join(prof, "Saved Games"),
    }


def _np(p):
    return os.path.normcase(os.path.normpath(p)).rstrip("\\") if p else ""


class Env:
    """Taramanin baktigi dunya: klasor kokleri, kayit defteri ve korunan yollar (testlerde sahtesi verilir)."""

    def __init__(self, roots=None, reg=None, tasks_dir=None, protect=()):
        self.roots = {k: v for k, v in (roots if roots is not None else default_roots()).items() if v}
        self.reg = reg if reg is not None else WinReg()
        windir = os.environ.get("WINDIR", r"C:\Windows")
        self.tasks_dir = tasks_dir if tasks_dir is not None else os.path.join(windir, "System32", "Tasks")
        e = os.environ.get
        extra = [windir, e("USERPROFILE"), e("PUBLIC"), e("SystemDrive", "C:") + "\\",
                 e("CommonProgramFiles"), e("CommonProgramFiles(x86)"), e("CommonProgramW6432"),
                 os.path.join(e("LOCALAPPDATA"), "Programs") if e("LOCALAPPDATA") else ""]
        self.protected = {_np(p) for p in list(self.roots.values()) + extra if p}
        self.own = {_np(p) for p in protect if p}
        self.never_inside = {_np(windir)} | self.own

    def path_blocked(self, path):
        n = _np(path)
        if not n or len(n) <= 3 or not os.path.isabs(n):  # surucu koku ya da goreli yol
            return True
        for q in self.protected | self.own:
            if n == q or q.startswith(n + "\\"):  # korunan kokun kendisi ya da ustu
                return True
        return any(n.startswith(q + "\\") for q in self.never_inside)


# Silinebilecek kayit anahtarlari (kucuk harf). Software altinda korunan ilk duzey adlari ayrica elenir.
_KEY_SOFTWARE = re.compile(r"^hk(cu|lm)\\software\\(wow6432node\\)?([^\\]+)(\\[^\\]+)?$")
_KEY_OK = (
    re.compile(r"^hk(cu|lm)\\software\\(wow6432node\\)?microsoft\\windows\\currentversion\\(uninstall|app paths)\\[^\\]+$"),
    re.compile(r"^hklm\\system\\currentcontrolset\\services\\[^\\]+$"),
    re.compile(r"^hkcu\\software\\classes\\applications\\[^\\]+\.exe$"),
)
_VALUE_PARENTS = {k.lower() for k in RUN_KEYS} | {FIREWALL.lower()}


def key_blocked(path):
    low = (path or "").lower()
    if any(r.match(low) for r in _KEY_OK):
        return False
    m = _KEY_SOFTWARE.match(low)
    return not m or norm(m.group(3)) in GENERIC


# ------------------------------------------------------------------ yuklu uygulamalar
def _str(v):
    return v.strip() if isinstance(v, str) else ""


def _guess_location(vals):
    """InstallLocation bossa simge ya da kaldirici yolundan tahmin (Temp / Installer / Package Cache haric)."""
    for raw in (_str(vals.get("DisplayIcon")), _str(vals.get("UninstallString"))):
        if not raw or "msiexec" in raw.lower():
            continue
        exe = split_command(re.sub(r",\s*-?\d+$", "", raw))[0]
        d = os.path.dirname(os.path.expandvars(exe))
        low = d.lower()
        if d and not any(x in low for x in ("\\temp", "\\installer", "package cache", "\\windows\\")):
            return d
    return ""


def parse_entry(path, key, vals):
    name = _str(vals.get("DisplayName"))
    if not name or vals.get("SystemComponent") == 1 or _str(vals.get("ParentKeyName")):
        return None
    if _str(vals.get("ReleaseType")).lower() in ("update", "hotfix", "security update", "service pack"):
        return None
    uninst = _str(vals.get("UninstallString"))
    msi = vals.get("WindowsInstaller") == 1 and bool(GUID.fullmatch(key))
    if not uninst and not msi:
        return None
    loc = _str(vals.get("InstallLocation")).strip('"').rstrip("\\/")
    guessed = False
    if not loc:
        loc, guessed = _guess_location(vals), True
    size = vals.get("EstimatedSize")
    app = {
        "id": path, "key": key, "name": name, "publisher": _str(vals.get("Publisher")),
        "version": _str(vals.get("DisplayVersion")), "size_kb": size if isinstance(size, int) and size > 0 else None,
        "date": _str(vals.get("InstallDate")), "location": os.path.expandvars(loc) if loc else "",
        "uninstall": uninst, "msi": msi,
        "user": path.upper().startswith("HKCU"), "x86": "\\WOW6432NODE\\" in path.upper(),
    }
    if guessed and app["location"]:  # tahmin edilen klasor yalnizca uygulamanin / yayincinin adini tasiyorsa
        base = norm(os.path.basename(app["location"]))
        names = {norm(clean_name(name)), norm(clean_publisher(app["publisher"]))} - {""}
        if len(base) < 3 or base in GENERIC or not any(n in base or base in n for n in names):
            app["location"] = ""
    app["critical"] = bool(CRITICAL.search(name)) and bool(CRITICAL_PUB.search(app["publisher"] or name))
    return app


def installed_apps(reg):
    apps, seen = [], set()
    for root in UNINSTALL_ROOTS:
        for key in reg.subkeys(root):
            app = parse_entry(root + "\\" + key, key, reg.values(root + "\\" + key))
            if not app:
                continue
            sig = (app["name"].casefold(), app["version"])
            if sig in seen:
                continue
            seen.add(sig)
            apps.append(app)
    apps.sort(key=lambda a: a["name"].casefold())
    return apps


def valid_id(app_id):
    if not isinstance(app_id, str):
        return False
    for root in UNINSTALL_ROOTS:
        if app_id.upper().startswith(root.upper() + "\\"):
            rest = app_id[len(root) + 1:]
            return bool(rest) and "\\" not in rest and len(rest) < 260
    return False


# ------------------------------------------------------------------ kaldirici komutu
def split_command(s):
    """'"C:\\a b\\unins.exe" /x' ya da 'C:\\a b\\unins.exe /x' -> (exe, argumanlar)."""
    s = (s or "").strip()
    if s.startswith('"'):
        end = s.find('"', 1)
        if end < 0:
            return s[1:], ""
        return s[1:end], s[end + 1:].strip()
    m = re.search(r"\.exe\b", s, re.I)
    if m:
        return s[:m.end()], s[m.end():].strip()
    head, _, tail = s.partition(" ")
    return head, tail.strip()


def msiexec():
    return os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "System32", "msiexec.exe")


def uninstall_command(app):
    """Calistirilacak komut satiri ve calistirilabilir dosya. MSI paketleri her zaman msiexec /x {GUID}."""
    s = app.get("uninstall") or ""
    if app.get("msi") or re.search(r"msiexec", s, re.I):
        m = GUID.search(s) or GUID.search(app.get("key", ""))
        if m:
            return '"%s" /x %s' % (msiexec(), m.group(0)), msiexec()
    if not s:
        raise Error("noUninstaller")
    exe, args = split_command(os.path.expandvars(s))
    if not os.path.isabs(exe):
        exe = shutil.which(exe) or exe
    return ('"%s" %s' % (exe, args)).strip(), exe


# ------------------------------------------------------------------ tarama
class _Scan:
    def __init__(self, app, others, env, level):
        self.app, self.env, self.level = app, env, level
        self.cands = candidates(app)
        self.pubs = publishers(app)
        self.primary = norm(clean_name(app.get("name", "")))
        self.other_cands, self.other_pubs, self.other_locs = set(), set(), []
        for o in others:
            if o.get("id") == app.get("id"):
                continue
            self.other_cands |= candidates(o)
            self.other_pubs |= publishers(o)
            if o.get("location") and not env.path_blocked(o["location"]):
                self.other_locs.append(_np(o["location"]))
        # Ayni adli baska kurulum (Blender 4.5 / 5.3): ad eslesmeleri ortak, yalnizca Gelismis'te ve secilmeden
        self.shared = self.cands & self.other_cands
        self.other_cands -= self.cands
        loc = app.get("location") or ""
        base = norm(os.path.basename(loc.rstrip("\\/")))
        # Kurulum klasoru: kok / ortak uretici klasoru (Program Files\Intel) ya da baska uygulamayi iceriyorsa kullanilmaz
        ok = (loc and not env.path_blocked(loc) and not self._other_app_path(loc) and len(base) >= 3
              and base not in GENERIC and not (base in self.pubs and self.pubs & self.other_pubs and base != self.primary))
        self.loc = _np(loc) if ok else ""
        self.items = []

    # --- korumalar
    def _other_app_path(self, path):
        n = _np(path)
        return any(n == o or o.startswith(n + "\\") or n.startswith(o + "\\") for o in self.other_locs)

    def match(self, name):
        lvl, hit = match_level(name, self.cands)
        if lvl is None:
            return None
        n = norm(name)
        if n in self.other_cands:  # baska uygulamanin adi birebir
            return None
        if n in self.pubs and self.pubs & self.other_pubs and n != self.primary:
            return None  # yayincinin baska uygulamalari da var: ortak klasor (uygulamanin kendi adi degilse)
        for c in self.other_cands:  # baska uygulamaya daha iyi uyuyor
            if len(c) > len(hit) and (n.startswith(c) or c in n):
                return None
        return ADVANCED if hit in self.shared else lvl

    def loc_in(self, data):
        if not self.loc or not isinstance(data, str):
            return False
        d = _np(os.path.expandvars(data).replace("/", "\\").strip().strip('"')) if len(data) < 2048 else ""
        return (self.loc + "\\") in os.path.normcase(os.path.expandvars(data)) or d == self.loc

    def _exe_in_loc(self, data):
        if not self.loc or not isinstance(data, str):
            return False
        exe = split_command(os.path.expandvars(data))[0]
        return _np(exe).startswith(self.loc + "\\")

    # --- ekleme
    def add(self, kind, path, level, note="", name="", strong=None):
        """strong: kanit guclu mu (birebir ad ya da kurulum klasorune isaret). Yalnizca guclu ogeler on secilir."""
        if level > self.level:
            return
        if kind in ("dir", "file"):
            if self.env.path_blocked(path) or (self._other_app_path(path) and _np(path) != self.loc):
                return
        elif kind in ("key", "service"):
            if key_blocked(path):
                return
        elif kind == "value" and path.lower() not in _VALUE_PARENTS:
            return
        if strong is None:
            strong = level == SAFE
        self.items.append({"kind": kind, "path": path, "name": name, "level": level, "note": note, "strong": bool(strong)})

    # --- dosyalar
    @staticmethod
    def children(path):
        out = []
        try:
            with os.scandir(path) as it:
                for e in it:
                    try:
                        if e.is_symlink() or getattr(e, "is_junction", lambda: False)():
                            continue  # baglantilar izlenmez, silinmez
                        out.append((e.name, e.path, e.is_dir(follow_symlinks=False)))
                    except OSError:
                        continue
        except OSError:
            pass
        return out

    def files(self):
        if self.loc and os.path.isdir(self.loc):
            base = os.path.basename(self.loc)
            lvl = SAFE if (match_level(base, self.cands)[0] is not None or norm(base) in self.pubs) else MODERATE
            self.add("dir", self.app["location"], lvl, "install", strong=True)
        for key, rlvl in FILE_ROOTS:
            root = self.env.roots.get(key)
            if not root or rlvl > self.level:
                continue
            for name, path, isdir in self.children(root):
                if not isdir:
                    stem, ext = os.path.splitext(name)
                    if key in LINK_ROOTS and ext.lower() in (".lnk", ".url"):
                        lvl = self.match(stem)
                        if lvl is not None:
                            self.add("file", path, max(rlvl, lvl), "shortcut", strong=lvl == SAFE)
                    continue
                lvl = self.match(name)
                if lvl is not None:
                    if key == "temp" and lvl == ADVANCED:  # Temp'te ad icerik eslesmesi gurultu: yalnizca birebir / on ek
                        continue
                    self.add("dir", path, max(rlvl, lvl), strong=lvl == SAFE)
                elif norm(name) in self.pubs:
                    self._publisher(name, path, rlvl, self.children(path), "dir")

    def _publisher(self, name, path, rlvl, kids, kind):
        """Yayinci klasoru / anahtari: icindeki eslesenler; hepsi eslesiyorsa yayincinin kendisi de
        (yayincinin baska yuklu uygulamasi yoksa)."""
        hits = 0
        for kname, kpath, is_dir in kids:
            if not is_dir:
                continue
            lvl = self.match(kname)
            if lvl is not None:
                self.add(kind, kpath, max(rlvl, lvl), strong=lvl == SAFE)
                hits += 1
        if (hits and hits == len(kids) and not (self.pubs & self.other_pubs)
                and norm(name) not in self.other_cands):
            self.add(kind, path, max(rlvl, MODERATE), "publisher", strong=False)

    # --- kayit defteri
    def registry(self):
        reg = self.env.reg
        if reg.exists(self.app["id"]):
            self.add("key", self.app["id"], SAFE, "uninst", strong=True)
        for base in REG_BASES:
            for sub in reg.subkeys(base):
                if sub.lower() == "wow6432node":
                    continue
                path = base + "\\" + sub
                lvl = self.match(sub)
                if lvl is not None:
                    self.add("key", path, lvl, strong=lvl == SAFE)
                elif norm(sub) in self.pubs:
                    kids = [(k, path + "\\" + k, True) for k in reg.subkeys(path)]
                    if reg.values(path):  # yayincinin kendi degerleri varsa yayinci anahtari silinmez
                        kids.append(("", "", False))
                    self._publisher(sub, path, SAFE, kids, "key")
        if self.level >= MODERATE:
            for run in RUN_KEYS:
                for vname, data in reg.values(run).items():
                    if self.loc_in(data) or self._exe_in_loc(data):
                        self.add("value", run, MODERATE, "run", vname, strong=True)
                    else:
                        lvl = self.match(vname)
                        if lvl is not None:
                            self.add("value", run, MODERATE if lvl == SAFE else ADVANCED, "run", vname, strong=lvl == SAFE)
            for ap in APP_PATHS:
                for sub in reg.subkeys(ap):
                    vals = reg.values(ap + "\\" + sub)
                    stem = os.path.splitext(sub)[0]
                    if self.loc_in(vals.get("")) or self.loc_in(vals.get("Path")) or (
                            self.match(stem) == SAFE and not self._exists_target(vals.get(""))):
                        self.add("key", ap + "\\" + sub, MODERATE, "apppath", strong=True)
            if self.loc:
                for sub in reg.subkeys(SERVICES):
                    img = reg.values(SERVICES + "\\" + sub).get("ImagePath")
                    if self._exe_in_loc(img) or self.loc_in(img):
                        self.add("service", SERVICES + "\\" + sub, MODERATE, "service", sub, strong=True)
        if self.level >= ADVANCED:
            if self.loc:
                for vname, data in reg.values(FIREWALL).items():
                    if isinstance(data, str) and any(self.loc_in(p[4:]) for p in data.split("|") if p.lower().startswith("app=")):
                        self.add("value", FIREWALL, ADVANCED, "firewall", vname)
            for sub in reg.subkeys(CLASSES_APPS):
                if sub.lower().endswith(".exe") and self.match(sub[:-4]) == SAFE:
                    self.add("key", CLASSES_APPS + "\\" + sub, ADVANCED, "assoc")

    @staticmethod
    def _exists_target(data):
        if not isinstance(data, str) or not data.strip():
            return False
        return os.path.exists(split_command(os.path.expandvars(data))[0])

    # --- zamanlanmis gorevler
    def tasks(self):
        top = self.env.tasks_dir
        if self.level < MODERATE or not top or not os.path.isdir(top):
            return
        for dirpath, dirnames, filenames in os.walk(top):
            if dirpath == top:
                dirnames[:] = [d for d in dirnames if d.lower() != "microsoft"]
            for f in filenames:
                full = os.path.join(dirpath, f)
                name = "\\" + os.path.relpath(full, top)
                try:
                    with open(full, "rb") as fh:
                        raw = fh.read(262144)
                    text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8", "replace")
                except (OSError, UnicodeDecodeError):
                    continue
                if self.loc and (self.loc + "\\") in os.path.normcase(os.path.expandvars(text)):
                    self.add("task", name, MODERATE, "task", name, strong=True)
                    continue
                lvl = self.match(f)
                if lvl is not None:
                    self.add("task", name, MODERATE if lvl == SAFE else ADVANCED, "task", name, strong=lvl == SAFE)

    # --- sonuc: tekrarlar ve bir ust ogeye dahil olanlar atilir
    def result(self):
        out, dirs, keys = [], [], []
        order = {"dir": 0, "file": 0, "key": 1, "value": 1, "service": 2, "task": 2}
        for it in sorted(self.items, key=lambda i: (order[i["kind"]], len(i["path"]), i["path"].lower())):
            kind = it["kind"]
            if kind in ("dir", "file"):
                p = _np(it["path"])
                if any(p == d or p.startswith(d + "\\") for d in dirs):
                    continue
                if kind == "dir":
                    dirs.append(p)
            elif kind in ("key", "service"):
                p = it["path"].lower()
                if any(p == k or p.startswith(k + "\\") for k in keys):
                    continue
                keys.append(p)
            else:
                p = it["path"].lower()
                if kind == "value" and any(p == k or p.startswith(k + "\\") for k in keys):
                    continue
                if any(x["kind"] == kind and x["path"].lower() == p and x["name"] == it["name"] for x in out):
                    continue
            out.append(it)
        return out


def dir_size(path, limit=20000):
    total, n = 0, 0
    for dirpath, _, filenames in os.walk(path):
        for f in filenames:
            try:
                total += os.lstat(os.path.join(dirpath, f)).st_size
            except OSError:
                pass
            n += 1
            if n >= limit:
                return total
    return total


def scan(app, mode, env, apps):
    """Artik taramasi. Donus: {'installed': bool, 'items': [{id, kind, path, name, level, note, size, checked}]}"""
    level = MODES.get(mode, MODERATE)
    s = _Scan(app, apps, env, level)
    s.files()
    s.registry()
    s.tasks()
    items = s.result()
    installed = env.reg.exists(app["id"])
    for i, it in enumerate(items):
        it["id"] = str(i)
        it["checked"] = it.pop("strong") and it["level"] <= MODERATE and not installed
        it["size"] = None
        if it["kind"] == "dir":
            it["size"] = dir_size(it["path"])
        elif it["kind"] == "file":
            try:
                it["size"] = os.path.getsize(it["path"])
            except OSError:
                pass
    return {"installed": installed, "items": items}


# ------------------------------------------------------------------ silme
class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [("hwnd", wt.HWND), ("wFunc", wt.UINT), ("pFrom", wt.LPCWSTR), ("pTo", wt.LPCWSTR),
                ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wt.BOOL),
                ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wt.LPCWSTR)]


def recycle(path):
    """Dosya / klasoru Geri Donusum Kutusu'na gonderir (sessiz, onaysiz, hata penceresiz)."""
    flags = 0x0004 | 0x0010 | 0x0040 | 0x0400  # SILENT | NOCONFIRMATION | ALLOWUNDO | NOERRORUI
    op = SHFILEOPSTRUCTW(None, 3, path + "\0", None, flags, False, None, None)
    rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if rc != 0 or op.fAnyOperationsAborted:
        raise OSError("SHFileOperation 0x%X" % rc)
    if os.path.lexists(path):
        raise Error("inUse")


def _run(args, timeout=60):
    r = subprocess.run(args, capture_output=True, timeout=timeout, creationflags=CREATE_NO_WINDOW)
    out = (r.stdout or b"") + (r.stderr or b"")
    try:
        text = out.decode("oem", "replace")
    except LookupError:
        text = out.decode("utf-8", "replace")
    return r.returncode, text.strip()


def _sys32(exe):
    return os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "System32", exe)


def create_restore_point(label):
    """Sistem geri yukleme noktasi. Windows 24 saatte birden fazlasina izin vermez; Sistem Koruma kapaliysa olmaz."""
    desc = re.sub(r"[^\w .,+()-]", "", "Control Center: " + (label or ""))[:64]
    cmd = ("Checkpoint-Computer -Description '%s' -RestorePointType APPLICATION_UNINSTALL "
           "-WarningAction Stop -ErrorAction Stop" % desc)
    try:
        rc, text = _run([_sys32(r"WindowsPowerShell\v1.0\powershell.exe"), "-NoProfile", "-NonInteractive",
                         "-ExecutionPolicy", "Bypass", "-Command", cmd], timeout=240)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "reason": "failed", "detail": str(exc)[:200]}
    if rc == 0:
        return {"ok": True}
    reason = "recent" if "1440" in text else "off" if re.search(r"0x80070422|disabled|devre d", text, re.I) else "failed"
    return {"ok": False, "reason": reason, "detail": text.splitlines()[0][:200] if text else ""}


def _safe_name(s):
    return re.sub(r"[^\w .-]+", "_", s or "app").strip(" .")[:48] or "app"


def clean(selected, env, backup_root, label):
    """Secilen ogeleri siler. Kayit defteri / gorevler once yedeklenir; dosyalar Geri Donusum Kutusu'na."""
    folder = os.path.join(backup_root, time.strftime("%Y%m%d-%H%M%S") + " " + _safe_name(label))
    os.makedirs(folder, exist_ok=True)
    removed, failed, log = 0, [], []
    exported = set()

    def export(key):
        if key.lower() in exported:
            return
        exported.add(key.lower())
        fn = os.path.join(folder, "%03d %s.reg" % (len(exported), _safe_name(key.rsplit("\\", 1)[-1])))
        rc, text = _run([_sys32("reg.exe"), "export", key, fn, "/y", "/reg:64"])
        if rc != 0:  # yedeklenemeyen anahtar silinmez
            raise OSError("reg export: " + text)

    for it in selected:
        kind, path, name = it["kind"], it["path"], it.get("name", "")
        try:
            if kind in ("dir", "file"):  # korumalar silmeden hemen once yeniden denetlenir
                if env.path_blocked(path):
                    raise Error("blocked")
                if os.path.lexists(path):
                    recycle(path)
            elif kind == "key":
                if key_blocked(path):
                    raise Error("blocked")
                if env.reg.exists(path):
                    export(path)
                    env.reg.delete_key(path)
            elif kind == "value":
                if path.lower() not in _VALUE_PARENTS:
                    raise Error("blocked")
                export(path)
                env.reg.delete_value(path, name)
            elif kind == "service":
                if key_blocked(path):
                    raise Error("blocked")
                export(path)
                _run([_sys32("sc.exe"), "stop", name], timeout=30)
                rc, text = _run([_sys32("sc.exe"), "delete", name])
                if rc not in (0, 1060):  # 1060: servis zaten yok
                    raise OSError(text)
            elif kind == "task":
                rc, xml = _run([_sys32("schtasks.exe"), "/query", "/tn", path, "/xml"])
                if rc == 0:
                    with open(os.path.join(folder, _safe_name(path.replace("\\", " ")) + ".xml"), "w", encoding="utf-8") as f:
                        f.write(xml)
                rc, text = _run([_sys32("schtasks.exe"), "/delete", "/tn", path, "/f"])
                if rc != 0:
                    raise OSError(text)
            removed += 1
            log.append({"kind": kind, "path": path, "name": name, "ok": True})
        except Error as exc:
            failed.append({"path": path, "name": name, "error": exc.code})
            log.append({"kind": kind, "path": path, "name": name, "ok": False, "error": exc.code})
        except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
            msg = (str(exc).strip() or exc.__class__.__name__)[:200]
            failed.append({"path": path, "name": name, "error": msg})
            log.append({"kind": kind, "path": path, "name": name, "ok": False, "error": msg})
    try:
        with open(os.path.join(folder, "silinenler.json"), "w", encoding="utf-8") as f:
            json.dump({"app": label, "time": time.strftime("%Y-%m-%d %H:%M:%S"), "items": log}, f, ensure_ascii=False, indent=1)
    except OSError:
        pass
    return {"removed": removed, "failed": failed, "backup": folder}


# ------------------------------------------------------------------ durum (motor tek ornek tutar)
class Uninstaller:
    """Motorun kaldirici durumu: son liste, calisan kaldirici, son tarama ve geri yukleme noktalari."""

    def __init__(self, env_factory, backup_root):
        self.env_factory = env_factory
        self.backup_root = backup_root
        self.lock = threading.Lock()
        self.apps = {}
        self.job = {"phase": "idle"}
        self.last = None
        self.restored = set()
        self.last_backup = ""
        self.proc = None  # calisan kaldirici sureci (iptal icin)

    def list(self):
        env = self.env_factory()
        apps = installed_apps(env.reg)
        for a in apps:
            loc = _np(a["location"])
            a["self"] = bool(loc) and any(loc == o or o.startswith(loc + "\\") or loc.startswith(o + "\\") for o in env.own)
        with self.lock:
            self.apps.update({a["id"]: a for a in apps})
        return apps

    def app(self, app_id):
        if not valid_id(app_id):
            raise Error("noApp")
        with self.lock:
            a = self.apps.get(app_id)
        if a is None:
            self.list()
            with self.lock:
                a = self.apps.get(app_id)
        if a is None:
            raise Error("noApp")
        return a

    def _restore(self, app):
        if app["id"] in self.restored:
            return {"ok": True, "reused": True}
        res = create_restore_point(app["name"])
        if res.get("ok"):
            self.restored.add(app["id"])
        return res

    def start(self, app_id, restore):
        app = self.app(app_id)
        if app.get("self"):
            raise Error("self")
        cmd, exe = uninstall_command(app)
        if not os.path.isfile(exe):
            raise Error("noUninstaller")
        with self.lock:
            if self.job.get("phase") in ("restore", "running"):
                raise Error("busy")
            self.job = {"phase": "restore" if restore else "running", "id": app_id, "started": time.time()}

        job = self.job

        def work():
            res = self._restore(app) if restore else None
            with self.lock:
                if job.get("phase") == "cancelled":  # geri yukleme noktasi beklenirken iptal edildi
                    job["restore"] = res
                    return
                job.update(phase="running", restore=res, started=time.time())
            try:
                p = subprocess.Popen(cmd, cwd=os.path.dirname(exe) or None)
            except OSError as exc:
                with self.lock:
                    job.update(phase="error", error=str(exc)[:200])
                return
            with self.lock:
                self.proc = p
            code = p.wait()
            with self.lock:
                self.proc = None
                if job.get("phase") != "cancelled":
                    job.update(phase="done", code=code)
        threading.Thread(target=work, name="kaldirici", daemon=True).start()
        return self.status()

    def cancel(self):
        """Takilan / yanit vermeyen kaldiriciyi (ve actigi alt surecleri) sonlandirir; arayuz serbest kalir."""
        with self.lock:
            active = self.job.get("phase") in ("restore", "running")
            if active:
                self.job["phase"] = "cancelled"
            p = self.proc
        if active and p is not None and p.poll() is None:
            try:
                _run([_sys32("taskkill.exe"), "/PID", str(p.pid), "/T", "/F"], timeout=20)
            except (OSError, subprocess.TimeoutExpired):
                pass
            if p.poll() is None:
                try:
                    p.kill()
                except OSError:
                    pass
        return self.status()

    def status(self):
        with self.lock:
            st = dict(self.job)
        if st.get("started"):
            st["elapsed"] = int(time.time() - st["started"])
        if st.get("id"):
            st["installed"] = self.env_factory().reg.exists(st["id"])
        return st

    def scan(self, app_id, mode):
        app = self.app(app_id)
        if app.get("self"):
            raise Error("self")
        with self.lock:
            if self.job.get("phase") in ("restore", "running") and self.job.get("id") == app_id:
                raise Error("busy")
        env = self.env_factory()
        res = scan(app, mode, env, installed_apps(env.reg))
        with self.lock:
            self.last = {"app": app, "items": {it["id"]: it for it in res["items"]}}
        res.update(app=app["name"], mode=mode if mode in MODES else "moderate")
        return res

    def clean(self, ids, restore):
        with self.lock:
            last = self.last
        if not last:
            raise Error("noScan")
        chosen = [last["items"][i] for i in ids if isinstance(i, str) and i in last["items"]] if isinstance(ids, list) else []
        if not chosen:
            raise Error("nothing")
        res = {"restore": self._restore(last["app"]) if restore else None}
        res.update(clean(chosen, self.env_factory(), self.backup_root, last["app"]["name"]))
        with self.lock:
            self.last_backup = res["backup"]
            self.last = None  # ayni tarama ikinci kez kullanilmasin: once yeniden taranir
        return res

    def open_backup(self):
        path = self.last_backup or self.backup_root
        os.makedirs(path, exist_ok=True)
        os.startfile(path)
