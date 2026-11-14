# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""GitHub uzerinden guncelleme: yeni surum var mi denetler, kurulum dosyasini indirir, sessiz kurar.

Kaynak: github.com/kuheylanstudio/fcuk-control-center son yayini (releases/latest). Yayin etiketi v<surum>,
kurulum dosyasi FCUK-Control-Center-Setup-<surum>.exe (setup_olustur.ps1 -Dagitim boyle uretir).

Guvenlik:
  * Yalnizca bu deponun releases/download/ adresinden, HTTPS ile indirilir.
  * GitHub'in yayin bilgisindeki SHA-256 ozeti (asset "digest") indirilen dosyayla karsilastirilir; ozet
    yoksa boyut denetlenir. Dosya kurulmadan hemen once yeniden dogrulanir.
  * Yonetici motor dosyayi kendi veri klasorune (Program Files altinda, yalnizca yonetici yazabilir) indirir:
    kullanici yetkisindeki bir program dogrulama ile baslatma arasinda dosyayi degistiremez.

Kurulum setup.exe /S ile yapilir: motoru kapatir, dosyalari degistirir, motoru ve tepsiyi yeniden baslatir.
Yonetici motor Gorev Zamanlayici'nin is nesnesi (job) icinde calisir ve kurulum o gorevi sonlandirir; bu
yuzden setup.exe WMI (Win32_Process.Create) ile o is nesnesinin DISINDA baslatilir. Standart yetkili motor
setup.exe'yi UAC ile (runas) baslatir.
"""
import hashlib
import json
import os
import re
import subprocess
import threading
import time
import urllib.request

REPO = "kuheylanstudio/fcuk-control-center"
API = "https://api.github.com/repos/%s/releases?per_page=30" % REPO  # atlanan surumlerin notlari icin liste
PAGE = "https://github.com/%s/releases/latest" % REPO
DOWNLOAD_PREFIX = "https://github.com/%s/releases/download/" % REPO
ASSET = re.compile(r"^FCUK-Control-Center-Setup-(\d+(?:\.\d+){1,3})\.exe$")
CHECK_EVERY = 6 * 3600   # otomatik denetim araligi
FIRST_DELAY = 90         # acilistan sonra ilk denetim (ag ve motor otursun)
AUTO_DELAY = 45          # otomatik modda kurulumdan once yeniliklerin gosterildigi sure (sn)
MAX_NOTES = 10           # en fazla bu kadar surumun notu gosterilir
# Yayin metnindeki indirme sayfasina ozgu satirlar (uygulama ici guncellemede anlamsiz)
_NOTE_SKIP = re.compile(r"^\s*(#+\s*FCUK Control Center\b|Windows SmartScreen|\**SHA-256\**)", re.I)
MAX_SIZE = 300 * 1024 * 1024
NO_WINDOW = 0x08000000


def parse(v):
    """'v2.0.10' -> (2, 0, 10); gecersizse None."""
    m = re.fullmatch(r"v?(\d+(?:\.\d+){0,3})", (v or "").strip())
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


def newer(a, b):
    """a, b'den yeni mi? (surum metinleri)"""
    pa, pb = parse(a), parse(b)
    if not pa or not pb:
        return False
    n = max(len(pa), len(pb))
    return pa + (0,) * (n - len(pa)) > pb + (0,) * (n - len(pb))


def clean_notes(body):
    """GitHub yayin metninden (Markdown) indirme sayfasina ozgu satirlari atar."""
    lines = [l for l in str(body or "").replace("\r", "").split("\n") if not _NOTE_SKIP.match(l)]
    return "\n".join(lines).strip()[:4000]


def summary(body, n=2):
    """Bildirim balonu icin ilk birkac madde/cumle, bicimlendirme isaretleri olmadan."""
    out = []
    for l in clean_notes(body).split("\n"):
        l = re.sub(r"[*`#]", "", l).strip().lstrip("-• ").strip()
        if l:
            out.append(l if len(l) <= 110 else l[:107] + "…")
        if len(out) >= n:
            break
    return " · ".join(out)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Updater:
    """Durum: idle | checking | uptodate | available | downloading | ready | installing | error"""

    def __init__(self, version, folder, can_install, is_admin, log=lambda m: None, on_ready=lambda v: None,
                 on_available=lambda v: None, on_scheduled=lambda v, s: None):
        self.version = version
        self.folder = folder
        self.can_install = can_install      # exe olarak kurulu mu (betikten calisirken yalnizca denetlenir)
        self.is_admin = is_admin
        self.log = log
        self.on_ready = on_ready            # indirme bitince (tepsi/arayuz bildirimi icin)
        self.on_available = on_available    # elle modda yeni surum bulununca
        self.on_scheduled = on_scheduled    # otomatik modda kurulumdan AUTO_DELAY sn once (surum, ozet)
        self.changes = []                   # [{"version", "date", "notes"}]: kurulu surumden yeni olanlar, yeniden eskiye
        self.install_at = 0.0
        self._cancel = False
        self.lock = threading.Lock()
        self.state = "idle"
        self.latest = ""
        self.asset = None                   # {"name", "url", "size", "digest"}
        self.notes = ""
        self.error = ""
        self.done = 0
        self.checked_at = 0.0
        self.file = ""
        self._busy = False

    # ------------------------------------------------------------------ durum
    def status(self):
        with self.lock:
            return {"state": self.state, "current": self.version, "latest": self.latest,
                    "notes": self.notes[:4000], "changes": list(self.changes), "error": self.error, "page": PAGE,
                    "install_in": max(0, int(self.install_at - time.time() + 0.99)) if self.state == "scheduled" else 0,
                    "size": (self.asset or {}).get("size", 0), "done": self.done,
                    "checked_at": int(self.checked_at), "can_install": self.can_install,
                    "busy": self._busy}

    def _set(self, **kw):
        with self.lock:
            for k, v in kw.items():
                setattr(self, k, v)

    def _ua(self):
        return {"User-Agent": "FCUK-Control-Center/%s" % self.version, "Accept": "application/vnd.github+json"}

    # ------------------------------------------------------------------ denetim
    def check(self):
        """Son yayini okur. Yeni surum varsa durum 'available' (indirilmis dosya gecerliyse 'ready')."""
        if self.state in ("downloading", "installing", "scheduled"):
            return self.status()
        self._set(state="checking", error="")
        try:
            req = urllib.request.Request(API, headers=self._ua())
            with urllib.request.urlopen(req, timeout=15) as r:
                items = json.loads(r.read(4 << 20).decode("utf-8"))
            rels = [d for d in (items if isinstance(items, list) else [])
                    if isinstance(d, dict) and not d.get("draft") and not d.get("prerelease")
                    and parse(str(d.get("tag_name") or ""))]
            if not rels:
                raise ValueError("geçersiz yayın bilgisi")
            rels.sort(key=lambda d: parse(d["tag_name"]) + (0,) * (4 - len(parse(d["tag_name"]))), reverse=True)
            data = rels[0]
            tag = str(data["tag_name"])
            latest = ".".join(str(x) for x in parse(tag))
            notes = clean_notes(data.get("body"))
            changes = [{"version": ".".join(str(x) for x in parse(d["tag_name"])),
                        "date": str(d.get("published_at") or "")[:10], "notes": clean_notes(d.get("body"))}
                       for d in rels if newer(d["tag_name"], self.version)][:MAX_NOTES]
            self._set(changes=changes)
            if not newer(latest, self.version):
                self._set(state="uptodate", latest=latest, asset=None, notes=notes, checked_at=time.time())
                self.cleanup()
                return self.status()
            asset = None
            for a in data.get("assets") or []:
                m = ASSET.match(str(a.get("name") or ""))
                url = str(a.get("browser_download_url") or "")
                if m and parse(m.group(1)) == parse(latest) and url.startswith(DOWNLOAD_PREFIX):
                    digest = str(a.get("digest") or "")
                    asset = {"name": a["name"], "url": url, "size": int(a.get("size") or 0),
                             "digest": digest[7:].lower() if digest.startswith("sha256:") else ""}
                    break
            if not asset or not 0 < asset["size"] <= MAX_SIZE:
                raise ValueError("%s yayınında kurulum dosyası yok" % tag)
            self._set(latest=latest, asset=asset, notes=notes, checked_at=time.time(), done=0)
            path = os.path.join(self.folder, asset["name"])
            if self._valid(path):
                self._set(state="ready", file=path, done=asset["size"])
            else:
                self._set(state="available")
        except Exception as exc:
            self.log("guncelleme denetimi: %s" % exc)
            self._set(state="error", error=str(exc)[:200], checked_at=time.time())
        return self.status()

    # ------------------------------------------------------------------ indirme
    def _valid(self, path):
        a = self.asset
        try:
            if not a or os.path.getsize(path) != a["size"]:
                return False
            return not a["digest"] or sha256(path) == a["digest"]
        except OSError:
            return False

    def download(self):
        """Kurulum dosyasini indirir ve dogrular (cagiran is parcacigini bekletir)."""
        a = self.asset
        if not a or self.state not in ("available", "error"):
            return self.state == "ready"
        self._set(state="downloading", error="", done=0)
        path = os.path.join(self.folder, a["name"])
        part = path + ".part"
        try:
            os.makedirs(self.folder, exist_ok=True)
            req = urllib.request.Request(a["url"], headers={"User-Agent": self._ua()["User-Agent"]})
            h = hashlib.sha256()
            done = 0
            with urllib.request.urlopen(req, timeout=30) as r, open(part, "wb") as f:
                while True:
                    chunk = r.read(256 * 1024)
                    if not chunk:
                        break
                    done += len(chunk)
                    if done > a["size"]:
                        raise ValueError("dosya beklenenden büyük")
                    h.update(chunk)
                    f.write(chunk)
                    self._set(done=done)
            if done != a["size"]:
                raise ValueError("indirme yarım kaldı (%d / %d bayt)" % (done, a["size"]))
            if a["digest"] and h.hexdigest() != a["digest"]:
                raise ValueError("SHA-256 özeti tutmuyor; dosya kurulmadı")
            os.replace(part, path)
            self._set(state="ready", file=path)
            self.log("guncelleme indirildi: %s" % path)
            try:
                self.on_ready(self.latest)
            except Exception:
                pass
            return True
        except Exception as exc:
            self.log("guncelleme indirme: %s" % exc)
            self._set(state="error", error=str(exc)[:200])
            try:
                os.remove(part)
            except OSError:
                pass
            return False

    def cleanup(self):
        """Kurulmus ya da eski kurulum dosyalarini ve yarim indirmeleri siler."""
        try:
            names = os.listdir(self.folder)
        except OSError:
            return
        for n in names:
            m = ASSET.match(n)
            if n.endswith(".part") or (m and not newer(m.group(1), self.version)):
                try:
                    os.remove(os.path.join(self.folder, n))
                except OSError:
                    pass

    # ------------------------------------------------------------------ kurulum
    def install(self):
        """Indirilmis kurulumu sessiz baslatir. (ok, hata metni). Basarida motor kisa sure sonra kapanir."""
        if not self.can_install:
            return False, "not_installed"
        if self.state != "ready" or not self._valid(self.file):
            if self.state == "ready":
                self._set(state="available")
            return False, "not_ready"
        self._set(state="installing", error="")
        exe = self.file
        try:
            if self.is_admin():
                # Gorev Zamanlayici is nesnesinin disinda: kurulum gorevi sonlandirinca setup.exe olmesin
                ps = ("$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create "
                      "-Arguments @{CommandLine='\"%s\" /S'}; exit [int]$r.ReturnValue" % exe.replace("'", "''"))
                rc = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps],
                                    creationflags=NO_WINDOW, capture_output=True, timeout=60).returncode
                if rc != 0:
                    raise OSError("setup.exe başlatılamadı (WMI kodu %d)" % rc)
            else:
                import ctypes
                r = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, "/S", os.path.dirname(exe), 0)
                if r <= 32:
                    raise OSError("Yönetici izni verilmedi" if r == 5 else "setup.exe başlatılamadı (kod %d)" % r)
        except Exception as exc:
            self.log("guncelleme kurulum: %s" % exc)
            self._set(state="ready", error=str(exc)[:200])
            return False, str(exc)
        self.log("guncelleme kuruluyor: %s -> %s" % (self.version, self.latest))
        return True, ""

    # ------------------------------------------------------------------ arka plan
    def run_async(self, fn):
        """fn'i ayri is parcaciginda calistirir; ayni anda tek is."""
        with self.lock:
            if self._busy:
                return False
            self._busy = True

        def go():
            try:
                fn()
            finally:
                with self.lock:
                    self._busy = False
        threading.Thread(target=go, daemon=True).start()
        return True

    def automatic(self, mode):
        """Zamanlanmis/elle denetim. mode "auto": yeni surum indirilir ve hemen kurulur;
        "manual": yalnizca denetlenir, indirme ve kurulum kullanicinin dugmesiyle olur."""
        self.check()
        if mode != "auto" or not self.can_install:
            if self.state in ("available", "ready"):
                try:
                    self.on_available(self.latest)
                except Exception:
                    pass
            return
        if self.state == "available":
            self.download()
        if self.state == "ready":
            self.scheduled_install()

    def scheduled_install(self):
        """Otomatik kurulum: once yenilikler bildirilir (tepsi balonu, acik pencerede yenilikler penceresi),
        AUTO_DELAY sn sonra kurulur. Kullanici bu surede 'Simdi kur' ya da 'Bu sefer kurma' diyebilir."""
        self._set(state="scheduled", install_at=time.time() + AUTO_DELAY, _cancel=False)
        try:
            self.on_scheduled(self.latest, summary(self.changes[0]["notes"] if self.changes else self.notes))
        except Exception:
            pass
        while time.time() < self.install_at and not self._cancel:
            time.sleep(0.25)
        if self._cancel:
            self._set(state="ready", install_at=0.0)
            self.log("otomatik guncelleme ertelendi: %s" % self.latest)
            return
        self._set(state="ready", install_at=0.0)
        self.install()

    def install_now(self):
        """Zamanlanmis kurulumu beklemeden baslatir."""
        if self.state == "scheduled":
            self._set(install_at=0.0)
            return True
        return False

    def cancel(self):
        """Zamanlanmis kurulumu bu seferlik iptal eder (sonraki denetimde yeniden zamanlanir)."""
        if self.state == "scheduled":
            self._set(_cancel=True)
            return True
        return False

    def fetch_and_install(self):
        """'Simdi kur': gerekiyorsa once indirir, sonra kurar."""
        if self.state in ("idle", "uptodate", "error") and not self.asset:
            self.check()
        if self.state in ("available", "error") and self.asset:
            self.download()
        if self.state == "ready":
            self.install()

    def loop(self, mode, running=lambda: True):
        """Denetim: acilistan FIRST_DELAY sn sonra, sonra CHECK_EVERY'de bir. mode(): "auto" | "manual"."""
        time.sleep(FIRST_DELAY)
        while running():
            m = mode()
            self.run_async(lambda: self.automatic(m))
            end = time.monotonic() + CHECK_EVERY
            while running() and time.monotonic() < end:
                time.sleep(30)
