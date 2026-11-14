# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""FCUK Control Center - giris noktasi.

  pythonw control_center.py              pencereyle ac (motor calismiyorsa once motoru baslatir)
  pythonw control_center.py --service    yalnizca arka plan motoru (Windows acilisi, yonetici gorevi)
  pythonw control_center.py --install-task   yonetici gorevini kurar (UAC ile, bir kez)
  python  control_center.py --dev        gelistirme: motoru bu surecte calistirir, gorevi kullanmaz

Motor yerel bir sunucudur (yalnizca 127.0.0.1); arayuz ui/index.html, Edge'in cercevesiz penceresinde acilir.
Yonetici modu: motor, Gorev Zamanlayici'daki "en yuksek ayricalik" goreviyle UAC sormadan yonetici olarak
baslar; ekran karti saat kilidi bunu ister. Pencere her zaman normal kullanici olarak acilir.
"""
import ctypes
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import ceviri
import donanim as hw
import envanter
import islemci
import klavye_rgb as core
import nvidia
import profiller
from ceviri import t

VERSION = "2.0"
PORT = 47815
HOSTS = ("127.0.0.1:%d" % PORT, "localhost:%d" % PORT)
BASE = "http://127.0.0.1:%d" % PORT
# Exe (PyInstaller, tek klasor) ya da betik: ui/ ve lib/ exe'de paketin icindedir (_internal).
FROZEN = bool(getattr(sys, "frozen", False))
HERE = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(sys.executable) if FROZEN else HERE
SCRIPT = sys.executable if FROZEN else os.path.abspath(__file__)
UI_PATH = os.path.join(HERE, "ui", "index.html")
TASK = "KendiControlCenter"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
PAL_KIND = {"sabit": "one", "nefes": "steps", "gecis": "loop", "gokkusagi": None,
            "nabiz": "steps", "ses": "range", "sistem": "range", "ekran": None}
BROWSERS = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
)
HEX = re.compile(r"#[0-9a-fA-F]{6}")
SPEED_KEY = {"Hız": "mode.speed", "Tepki hızı": "mode.react"}  # klavye_rgb.MODES hiz etiketi -> ceviri


def use_lang(setting):
    """Dil ayarini ("auto" ya da kod) bu surecte etkinlestirir."""
    ceviri.set_lang(ceviri.resolve(setting))


def localize(html):
    """Arayuzu etkin dile hazirlar: <html lang> ve metin sozlugu sayfaya gomulur, ilk boyamada dogru dil."""
    data = json.dumps(ceviri.catalog(), ensure_ascii=False).replace("</", "<\\/")
    html = html.replace('<html lang="tr">', '<html lang="%s">' % ceviri.lang(), 1)
    return html.replace("</head>", "<script>window.I18N=%s;</script>\n</head>" % data, 1)


def pythonw():
    exe = sys.executable
    pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    return pyw if os.path.exists(pyw) else exe


def self_cmd(*args):
    """Bu uygulamayi verilen argumanlarla baslatan komut (exe ya da pythonw + betik)."""
    return [sys.executable, *args] if FROZEN else [pythonw(), SCRIPT, *args]


def self_cmdline(*args):
    return " ".join('"%s"' % a if " " in a or not a.startswith("--") else a for a in self_cmd(*args))


class App:
    cfg = None
    dchu = None
    engine = None
    sensors = None
    manager = None
    audio = None
    display = None
    server = None
    lock = threading.Lock()
    device = ""
    restart_elevated = False
    inventory = None
    nvapi = None
    nvcard = None  # NVML sabit bilgileri: karti uyandirdigi icin NVIDIA sayfasi ilk acilinca okunur


def device_name():
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\BIOS")
        try:
            maker = winreg.QueryValueEx(key, "SystemManufacturer")[0]
            model = winreg.QueryValueEx(key, "SystemProductName")[0]
        finally:
            winreg.CloseKey(key)
        return ("%s %s" % (maker, model)).strip()
    except OSError:
        return ""


def save():
    with App.lock:
        core.save_config(App.cfg)


# ----------------------------------------------------------------------------- RGB ayar dogrulama
def _int(v, lo, hi, default):
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


def _palette(v, kind, default):
    if kind is None:
        return []
    if not isinstance(v, list):
        return list(default)
    pal = [h.lower() for h in v if isinstance(h, str) and HEX.fullmatch(h)][:8]
    return pal or list(default)


def _mode_values(mid, vals, base):
    vals = vals if isinstance(vals, dict) else {}
    out = {"palette": _palette(vals.get("palette"), PAL_KIND[mid], base.get("palette", [])),
           "speed": _int(vals.get("speed"), 0, 100, base.get("speed", 50))}
    if mid == "sistem":
        src = vals.get("source")
        out["source"] = src if src in [s[0] for s in core.SOURCES] else base.get("source", "cpu_temp")
    return out


def sanitize(raw, current):
    """Arayuzden gelen klavye ayarlarini guvenli bir yapiya indirger; profil ayarlarina dokunmaz."""
    raw = raw if isinstance(raw, dict) else {}
    cfg = {"mode": raw.get("mode") if raw.get("mode") in core.MODE_IDS else current["mode"],
           "brightness": _int(raw.get("brightness"), 0, 100, current["brightness"]),
           "autostart": bool(current.get("autostart")),
           "modes": {}, "presets": {}, "cc": current["cc"], "lang": current.get("lang", "auto")}
    modes = raw.get("modes") if isinstance(raw.get("modes"), dict) else {}
    for mid in core.MODE_IDS:
        cfg["modes"][mid] = _mode_values(mid, modes.get(mid), current["modes"][mid])
    presets = raw.get("presets") if isinstance(raw.get("presets"), dict) else {}
    for name, p in list(presets.items())[:60]:
        if not isinstance(name, str) or not name.strip() or not isinstance(p, dict):
            continue
        mid = p.get("mode")
        if mid not in core.MODE_IDS:
            continue
        item = _mode_values(mid, p, core.DEFAULTS["modes"][mid])
        item["mode"] = mid
        item["brightness"] = _int(p.get("brightness"), 0, 100, 100)
        cfg["presets"][name.strip()[:40]] = item
    return cfg


def rgb_config():
    return {k: v for k, v in App.cfg.items() if k != "cc"}


# ----------------------------------------------------------------------------- yonetici gorevi ve acilis
def task_exists():
    rc, _ = hw.run(["schtasks", "/query", "/tn", TASK])
    return rc == 0


def logon_trigger_enabled():
    """Motor gorevinin oturum acilisi tetikleyicisi acik mi? Gorev yoksa/okunamazsa None."""
    rc, out = hw.run(["schtasks", "/query", "/tn", TASK, "/xml"])
    if rc != 0:
        return None
    m = re.search(r"<LogonTrigger>.*?<Enabled>\s*(true|false)\s*</Enabled>", out or "", re.S | re.I)
    if m:
        return m.group(1).lower() == "true"
    return "<LogonTrigger>" in (out or "")  # Enabled yazilmamissa varsayilan: acik


def _xml(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


TASK_TRAY = TASK + " Tepsi"


def _task_xml(desc, user, level, args, logon, restart):
    return """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.3" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>{desc}</Description></RegistrationInfo>
  <Triggers><LogonTrigger><Enabled>{logon}</Enabled><UserId>{user}</UserId></LogonTrigger></Triggers>
  <Principals><Principal id="Author"><UserId>{user}</UserId><LogonType>InteractiveToken</LogonType><RunLevel>{level}</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>5</Priority>
    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>{restart}
  </Settings>
  <Actions Context="Author"><Exec><Command>{exe}</Command><Arguments>{args}</Arguments><WorkingDirectory>{here}</WorkingDirectory></Exec></Actions>
</Task>
""".format(desc=_xml(desc), user=_xml(user), level=level, logon="true" if logon else "false",
           restart="\n    <RestartOnFailure><Interval>PT1M</Interval><Count>5</Count></RestartOnFailure>" if restart else "",
           exe=_xml(self_cmd()[0]),
           args=_xml(" ".join('"%s"' % a if not a.startswith("--") else a for a in self_cmd(*args)[1:])),
           here=_xml(APP_DIR))


def install_task():
    """Yonetici olarak calisir (UAC ile): iki gorev kurar, sonucu dosyaya yazar.
    KendiControlCenter        : motor, yonetici, oturum acilisinda hemen (Run kaydi gibi gecikmez), cokunce yeniden.
    KendiControlCenter Tepsi  : tepsi simgesi, NORMAL yetki (UIPI), oturum acilisinda.
    Kurulum acilis tetikleyicilerini HER ZAMAN acar; 'Windows ile baslat' kapatilirsa motor onlari kapatir
    ve acilista ayari gorevin gercek durumundan okur (config dosyasina guvenilmez: paketli bir uygulamadan
    baslatilan kurulum AppData'nin sanal/bayat bir kopyasini gorebilir)."""
    result = os.path.join(core.CONFIG_DIR, "task_result.txt")
    os.makedirs(core.CONFIG_DIR, exist_ok=True)
    user = "%s\\%s" % (os.environ.get("USERDOMAIN", ""), os.environ.get("USERNAME", ""))
    logon = True
    errors = []
    for name, xml in ((TASK, _task_xml("FCUK Control Center motoru (yonetici)", user, "HighestAvailable",
                                       ["--service"], logon, True)),
                      (TASK_TRAY, _task_xml("FCUK Control Center tepsi simgesi", user, "LeastPrivilege",
                                            ["--tray"], logon, False))):
        path = os.path.join(core.CONFIG_DIR, "gorev_%s.xml" % ("tepsi" if name == TASK_TRAY else "motor"))
        with open(path, "w", encoding="utf-16") as f:
            f.write(xml)
        rc, out = hw.run(["schtasks", "/create", "/tn", name, "/xml", path, "/f"])
        if rc != 0:
            errors.append("%s: %s" % (name, out or "schtasks %d" % rc))
    remove_run_entry()  # acilis artik gorevlerle
    with open(result, "w", encoding="utf-8") as f:
        f.write("; ".join(errors) if errors else "0")


def request_admin():
    """UAC penceresini acar; kullanici onaylarsa gorev kurulur. (ok, mesaj)"""
    result = os.path.join(core.CONFIG_DIR, "task_result.txt")
    try:
        os.remove(result)
    except OSError:
        pass
    cmd = self_cmd("--install-task")
    params = " ".join('"%s"' % a if not a.startswith("--") else a for a in cmd[1:])
    r = ctypes.windll.shell32.ShellExecuteW(None, "runas", cmd[0], params, APP_DIR, 0)
    if r <= 32:
        return False, t("err.adminDenied")
    for _ in range(300):
        if os.path.exists(result):
            with open(result, encoding="utf-8") as f:
                txt = f.read().strip()
            return (True, "") if txt == "0" else (False, txt)
        time.sleep(0.1)
    return False, t("err.taskTimeout")


def remove_run_entry():
    import winreg
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE)
    try:
        for name in ("KlavyeRGB", TASK):  # eski klavye uygulamasi ve Run ile acilis
            try:
                winreg.DeleteValue(key, name)
            except FileNotFoundError:
                pass
    finally:
        winreg.CloseKey(key)


def set_logon_triggers(enabled):
    """Iki gorevin oturum acilisi tetikleyicisini acar/kapatir (yonetici ister). (rc, cikti)"""
    ps = ("$ErrorActionPreference='Stop'; foreach($n in @('%s','%s')){ $t = Get-ScheduledTask -TaskName $n; "
          "foreach($g in $t.Triggers){ $g.Enabled = $%s }; Set-ScheduledTask -InputObject $t | Out-Null }"
          % (TASK, TASK_TRAY, "true" if enabled else "false"))
    return hw.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], timeout=30)


def set_autostart(enabled):
    if hw.is_admin() and task_exists():  # yonetici modu: acilis gorevlerle (gecikmesiz)
        remove_run_entry()
        rc, out = set_logon_triggers(enabled)
        if rc != 0:
            raise RuntimeError(t("err.autostart", out=(out or str(rc))[:160]))
        return
    import winreg  # yonetici modu yoksa: Run kaydi
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE)
    try:
        try:
            winreg.DeleteValue(key, "KlavyeRGB")  # eski uygulamanin kaydi
        except FileNotFoundError:
            pass
        if enabled:
            winreg.SetValueEx(key, TASK, 0, winreg.REG_SZ, self_cmdline("--service"))
        else:
            try:
                winreg.DeleteValue(key, TASK)
            except FileNotFoundError:
                pass
    finally:
        winreg.CloseKey(key)


# ----------------------------------------------------------------------------- durum
def state():
    disp = App.display
    w, h, hz = disp.current()
    return {
        "version": VERSION,
        "config": rgb_config(),
        "device": App.device,
        "gpu_name": App.sensors.gpu_name,
        "modes": [{"id": m[0], "label": t("mode." + m[0]), "pal": PAL_KIND[m[0]],
                   "speed": SPEED_KEY.get(m[3]) and t(SPEED_KEY[m[3]]), "desc": t("mode.%s.desc" % m[0])}
                  for m in core.MODES],
        "sources": [{"id": s[0], "label": t("src." + s[0])} for s in core.SOURCES],
        "lang": ceviri.lang(),
        "lang_setting": App.cfg.get("lang", "auto"),
        "lang_detected": ceviri.detect(),
        "languages": ceviri.languages(),
        "profiles": App.manager.public(),
        "cc": App.manager.status(),
        "fan_default": App.dchu.fan_default(),
        "display": {"width": w, "height": h, "hz": hz, "rates": disp.rates()},
        "admin": hw.is_admin(),
        "task": task_exists(),
        "autostart": bool(App.cfg.get("autostart")),
        "dll": App.dchu.path,
        "ec": App.dchu.available,
        "cpu": App.inventory.data.get("cpu"),
        "nvidia": bool(App.sensors.gpu_name),
        "igpu_name": App.sensors.igpu_name,
    }


def nvidia_state():
    if App.nvcard is None and App.sensors.gpu_name:
        try:
            App.nvcard = nvidia.card_info() or {}
        except Exception:
            App.nvcard = {}
    gpus = App.inventory.data.get("gpus") or []
    optimus = bool(App.sensors.gpu_name) and any(g.get("vendor") != "NVIDIA" for g in gpus)
    try:
        values, err = App.nvapi.read(), ""
    except Exception as exc:
        values, err = {}, str(exc)
    return {"present": bool(App.sensors.gpu_name), "api": App.nvapi.ok, "card": App.nvcard or {},
            "settings": nvidia.public(optimus), "values": values, "error": err, "admin": hw.is_admin()}


def cpu_state():
    cpu = App.inventory.data.get("cpu") or {}
    return {"cpu": cpu, "controls": islemci.visible(cpu), **islemci.read(cpu),
            "profile": App.manager.applied}


# ----------------------------------------------------------------------------- sunucu
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "KendiControlCenter"

    def log_message(self, *args):  # pythonw altinda stderr yok
        pass

    def _allowed(self):
        """Yalnizca kendi penceremizden gelen istekler: baska site veya DNS oyunu kabul edilmez."""
        if self.headers.get("Host") not in HOSTS:
            return False
        origin = self.headers.get("Origin")
        return origin is None or origin in ["http://" + h for h in HOSTS]

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self):
        if not self._allowed():
            return self._json({"error": "forbidden"}, 403)
        path = self.path.split("?")[0]
        if path == "/":
            try:
                with open(UI_PATH, encoding="utf-8") as f:
                    html = f.read()
            except OSError:
                return self._send(500, t("err.ui", path=UI_PATH).encode("utf-8"), "text/plain; charset=utf-8")
            try:  # Donanim / NVIDIA / Islemci sayfalari ayri dosyada; menu dugmelerini ve sayfalari kendisi kurar
                with open(os.path.join(HERE, "ui", "sayfalar.js"), encoding="utf-8") as f:
                    extra = f.read().replace("</", "<\\/")
                html = html.replace("</body>", "<script>\n%s\n</script>\n</body>" % extra, 1)
            except OSError:
                pass
            return self._send(200, localize(html).encode("utf-8"), "text/html; charset=utf-8")
        if path == "/api/ping":
            return self._json({"app": core.APP_NAME, "path": HERE, "admin": hw.is_admin(), "version": VERSION})
        if path == "/api/state":
            return self._json(state())
        if path == "/api/sensors":
            return self._json(App.sensors.payload())
        if path == "/api/audio":
            return self._json(App.audio.get())
        if path == "/api/tray":  # tepsi simgesi 2 sn'de bir yoklar: hafif tutuldu
            s, mgr = App.sensors.snapshot, App.manager
            return self._json({
                "profile": mgr.applied, "guard": mgr.guard, "lang": ceviri.lang(),
                "profiles": [{"id": p["id"], "name": profiller.name(p["id"]), "ac_only": bool(p.get("ac_only"))}
                             for p in profiller.PROFILES],
                "fan_mode": App.dchu.fan_mode(), "cpu_temp": s.get("cpu_temp"), "gpu_temp": s.get("gpu_temp"),
                "gpu_state": s.get("gpu_state"), "cpu_power": s.get("cpu_power"),
                "ac": (s.get("battery") or {}).get("ac", True)})
        if path == "/api/now":  # yalnizca son olcum (gecmissiz): ek sayfalar saniyede bir okur
            return self._json(App.sensors.snapshot)
        if path == "/api/hardware":
            return self._json(App.inventory.data)
        if path == "/api/nvidia":
            return self._json(nvidia_state())
        if path == "/api/cpu":
            return self._json(cpu_state())
        if path == "/api/events":
            return self._events()
        return self._json({"error": "not found"}, 404)

    def _events(self):
        """Canli akis (Server-Sent Events): klavye rengi ~20 kare/sn, sensorler saniyede bir."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        eng, sen = App.engine, App.sensors
        seq = -1
        try:
            while eng.running:
                v = eng.value
                msg = {"c": eng.current, "info": eng.info, "err": eng.error,
                       "v": None if v is None else round(v, 3)}
                if sen.seq != seq:
                    seq = sen.seq
                    msg["s"] = sen.snapshot
                    msg["p"] = {"profile": App.manager.applied, "guard": App.manager.guard}
                self.wfile.write(("data: %s\n\n" % json.dumps(msg, ensure_ascii=False)).encode("utf-8"))
                self.wfile.flush()
                time.sleep(0.05)
        except OSError:
            pass

    def do_POST(self):
        if not self._allowed():
            return self._json({"error": "forbidden"}, 403)
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size > 262144:
                return self._json({"error": "too large"}, 413)
            body = json.loads(self.rfile.read(size).decode("utf-8")) if size else {}
        except (ValueError, UnicodeDecodeError):
            return self._json({"error": "bad json"}, 400)
        body = body if isinstance(body, dict) else {}
        try:
            return self._post(self.path.split("?")[0], body)
        except Exception as exc:  # her hata arayuzde okunur bir mesaj olsun
            return self._json({"error": str(exc)}, 500)

    def _post(self, path, body):
        mgr = App.manager
        if path == "/api/config":
            with App.lock:
                App.cfg = sanitize(body, App.cfg)
                App.engine.settings = core.snapshot(App.cfg)
                core.save_config(App.cfg)
            return self._json({"ok": True})
        if path == "/api/profile":
            rep = mgr.apply(str(body.get("id", "")))
            return self._json({"ok": True, "report": rep, "cc": mgr.status()})
        if path == "/api/factory":
            rep = mgr.factory()
            return self._json({"ok": True, "report": rep, "cc": mgr.status()})
        if path == "/api/rules":
            ids = set(profiller.BY_ID) | {""}
            for k in ("on_battery", "on_ac"):
                if k in body and body[k] in ids:
                    mgr.cfg[k] = body[k]
            if "refresh" in body:
                mgr.cfg["refresh"] = bool(body["refresh"])
            save()
            return self._json({"ok": True, "cc": mgr.status()})
        if path == "/api/fan":
            mode = body.get("mode")
            if mode == "profile" and mgr.applied:
                mgr.apply(mgr.applied, "reason.fanProfile")
            elif mode in ("auto", "max"):
                App.dchu.set_fan_mode(hw.FAN_MAX if mode == "max" else hw.FAN_AUTO)
            else:
                return self._json({"error": t("err.fanMode")}, 400)
            return self._json({"ok": True, "cc": mgr.status()})
        if path == "/api/audio":
            which = body.get("which")
            if which not in ("speaker", "mic"):
                return self._json({"error": t("err.device")}, 400)
            level = _int(body["level"], 0, 100, None) if "level" in body else None
            mute = bool(body["mute"]) if "mute" in body else None
            App.audio.set(which, level, mute)
            return self._json(App.audio.get())
        if path == "/api/display":
            hz = _int(body.get("hz"), 1, 1000, 0)
            if hz not in App.display.rates():
                return self._json({"error": t("err.rate")}, 400)
            ok = App.display.set_rate(hz)
            return self._json({"ok": ok, "hz": App.display.current()[2]})
        if path == "/api/kb":  # Fn klavye isigi tuslari (tepsi surecinden)
            act = body.get("action")
            with App.lock:
                b = int(App.cfg.get("brightness", 100))
                if act == "toggle":
                    if b > 0:
                        App.kb_last = b
                        b = 0
                    else:
                        b = getattr(App, "kb_last", 0) or 100
                elif act in ("up", "down"):
                    b = max(0, min(100, b + (20 if act == "up" else -20)))
                elif act == "next":
                    ids = list(core.MODE_IDS)
                    cur = App.cfg.get("mode")
                    App.cfg["mode"] = ids[(ids.index(cur) + 1) % len(ids)] if cur in ids else ids[0]
                    if b == 0:
                        b = getattr(App, "kb_last", 0) or 100
                else:
                    return self._json({"error": t("err.action")}, 400)
                App.cfg["brightness"] = b
                App.engine.settings = core.snapshot(App.cfg)
                core.save_config(App.cfg)
                label = t("mode." + App.cfg["mode"])
            return self._json({"ok": True, "brightness": b, "mode": App.cfg["mode"], "mode_label": label})
        if path == "/api/autostart":
            enabled = bool(body.get("enabled"))
            set_autostart(enabled)
            with App.lock:
                App.cfg["autostart"] = enabled
                core.save_config(App.cfg)
            return self._json({"ok": True, "autostart": enabled})
        if path == "/api/admin":
            if hw.is_admin():
                return self._json({"ok": True, "admin": True})
            ok, msg = request_admin()
            if not ok:
                return self._json({"ok": False, "error": msg})
            App.restart_elevated = True
            self._json({"ok": True, "restarting": True})
            threading.Thread(target=shutdown, daemon=True).start()
            return None
        if path == "/api/lang":
            setting = body.get("lang")
            if setting != "auto" and setting not in ceviri.CODES:
                return self._json({"error": t("err.lang")}, 400)
            with App.lock:
                App.cfg["lang"] = setting
                core.save_config(App.cfg)
            use_lang(setting)
            return self._json({"ok": True, "lang": ceviri.lang()})
        if path == "/api/nvidia":
            if "clock_max" in body:  # elle saat siniri; None kilidi kaldirir. Profil uygulaninca profilinki gecer.
                if not hw.is_admin():
                    return self._json({"error": t("err.nvAdmin")}, 403)
                cap = body["clock_max"]
                rc, out = hw.nvidia_lock_clocks(210, _int(cap, 300, 4000, 0)) if cap else hw.nvidia_lock_clocks(0, None)
                if rc != 0:
                    return self._json({"error": out[:200]}, 500)
                return self._json({"ok": True, "clock_max": cap or None})
            App.nvapi.write(str(body.get("key", "")), None if body.get("value") is None else _int(body["value"], -2 ** 31, 2 ** 32, 0))
            return self._json(nvidia_state())
        if path == "/api/cpu":
            islemci.write(str(body.get("id", "")), body.get("value"), App.inventory.data.get("cpu"))
            return self._json(cpu_state())
        if path == "/api/quit":
            self._json({"ok": True})
            threading.Thread(target=shutdown, daemon=True).start()
            return None
        return self._json({"error": "not found"}, 404)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def handle_error(self, request, client_address):  # kopan baglantilar gurultu yapmasin
        pass


def shutdown():
    time.sleep(0.2)
    App.engine.running = False
    App.sensors.running = False
    App.engine.join(1.5)
    save()
    App.server.shutdown()


# ----------------------------------------------------------------------------- baslatici
def _opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def ping():
    try:
        with _opener().open(BASE + "/api/ping", timeout=0.6) as r:
            return json.loads(r.read().decode("utf-8"))
    except (OSError, ValueError):
        return None


def ask_quit():
    req = urllib.request.Request(BASE + "/api/quit", data=b"{}", method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        _opener().open(req, timeout=2).read()
    except (OSError, ValueError):
        pass


def wait_ping(seconds, want=True):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        p = ping()
        if bool(p) == want:
            return p or True
        time.sleep(0.15)
    return None


def open_window():
    url = BASE + "/"
    for exe in BROWSERS:
        if os.path.exists(exe):
            subprocess.Popen([exe, "--app=" + url, "--window-size=1320,860",
                              "--user-data-dir=" + os.path.join(core.CONFIG_DIR, "pencere"),
                              "--no-first-run", "--no-default-browser-check"], close_fds=True)
            return
    webbrowser.open(url)


DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP


def ensure_tray():
    """Tepsi simgesini normal yetkili ayri surec olarak baslatir; zaten varsa yeni surec hemen cikar."""
    try:
        subprocess.Popen(self_cmd("--tray"), cwd=APP_DIR, creationflags=DETACHED, close_fds=True)
    except OSError:
        pass


def start_engine():
    """Tepsiden 'Motoru baslat': normal acilis yolu (gorev varsa yonetici motoru)."""
    subprocess.Popen(self_cmd("--service"), cwd=APP_DIR, creationflags=DETACHED, close_fds=True)


def alert(text, icon=0x10):
    ctypes.windll.user32.MessageBoxW(None, text, "FCUK Control Center", icon)


def serve():
    """Motoru bu surecte calistirir; sunucu kapanana dek doner."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (OSError, AttributeError):
        pass
    # InsydeDCHU.dll yoksa (Clevo tabanli olmayan bilgisayar) NullDCHU: fan/guc modu/klavye isigi kapanir,
    # izleme, NVIDIA ve islemci ayarlari calisir.
    App.dchu = hw.open_dchu()
    App.inventory = envanter.Inventory()
    App.inventory.start()
    App.nvapi = nvidia.NvApi()
    # Fn tusu olaylarini ac (Clevo "events enabled", komut 0x46). Bunu eskiden FnKey.exe acilista yapiyordu;
    # gonderilmezse denetleyici Fn bildirimlerini AcpiBridge'e iletmez (14.11.2026 olculdu). Yeniden
    # baslatmaya dek kalicidir; her acilista gonderilir.
    try:
        App.dchu.set_wmi(0x46, 0)
    except Exception:
        pass
    try:
        App.server = Server(("127.0.0.1", PORT), Handler)
    except OSError as exc:
        alert(t("err.port", port=PORT, err=exc))
        return False
    App.cfg = core.load_config()
    if hw.is_admin():  # 'Windows ile baslat' ayarinin dogrusu gorevin kendisidir
        real = logon_trigger_enabled()
        if real is not None and real != bool(App.cfg.get("autostart")):
            App.cfg["autostart"] = real
            core.save_config(App.cfg)
    cc = dict(profiller.DEFAULTS)
    cc.update(App.cfg.get("cc") or {})
    App.cfg["cc"] = cc
    App.device = device_name()
    App.audio = hw.Audio()
    App.display = hw.Display()
    App.sensors = hw.Sensors(App.dchu)
    App.sensors.disk_ids = lambda: App.inventory.disk_ids
    App.manager = profiller.Manager(App.dchu, App.sensors, cc, save)
    App.engine = core.Engine(App.dchu)
    App.engine.settings = core.snapshot(App.cfg)
    App.engine.start()
    App.sensors.start()
    if cc.get("profile") in profiller.BY_ID:  # yeniden baslatmadan sonra denetleyici ayarlari geri gelsin
        threading.Thread(target=App.manager.apply, args=(cc["profile"], "reason.startup"), daemon=True).start()
    App.server.serve_forever()
    App.server.server_close()
    return True


def enable_crash_log():
    """pythonw'da konsol yok: yerel bir cokuste (erisim ihlali) tum is parcaciklarinin yigini crash.log'a yazilir."""
    import faulthandler
    try:
        os.makedirs(core.CONFIG_DIR, exist_ok=True)
        f = open(os.path.join(core.CONFIG_DIR, "crash.log"), "a", encoding="utf-8")
        f.write("\n--- %s pid %d admin=%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), os.getpid(),
                                                  hw.is_admin(), " ".join(sys.argv[1:])))
        f.flush()
        faulthandler.enable(f, all_threads=True)
        App.crash_log = f  # dosya acik kalmali
    except OSError:
        pass


def supervise():
    """Gorevden gelen yonetici motoru: motoru alt surec olarak calistirir; yerel bir cokuste (crash.log'a
    yazilir) 2 sn sonra yeniden baslatir, motor son profili geri yukler. Normal kapanis (cikis kodu 0) bekciyi
    de bitirir. 10 dakikada 5'ten fazla cokus olursa vazgecer."""
    crashes = []
    while True:
        rc = subprocess.call(self_cmd("--engine"), cwd=APP_DIR, creationflags=0x08000000)
        if rc == 0:
            return
        now = time.time()
        crashes = [t for t in crashes if now - t < 600] + [now]
        if len(crashes) > 5:
            return
        time.sleep(2)


def main():
    enable_crash_log()
    # Dil: ilk acilista ayar "auto"dur, Windows'un ulke/bolge ayarindan secilir (ceviri.detect)
    use_lang(core.load_config().get("lang", "auto"))
    if "--install-task" in sys.argv:
        install_task()
        return
    if "--tray" in sys.argv:
        import tepsi
        tepsi.run(BASE, open_window, start_engine)
        return
    if "--service" in sys.argv and hw.is_admin():
        supervise()
        return
    service = "--service" in sys.argv or "--minimized" in sys.argv or "--engine" in sys.argv
    if not hw.is_admin():  # yonetici surecten baslatilirsa simge de yonetici olur: tiklamalar engellenir
        ensure_tray()
    p = ping()
    if p and p.get("app") == core.APP_NAME and p.get("path") == HERE:
        if not service:
            open_window()
        return
    if p:  # baska klasorden ya da eski surumden kalan motor: kapatip yerine gec
        ask_quit()
        wait_ping(4, want=False)
    dev = "--dev" in sys.argv  # gelistirme: kurulu gorevi baslatma, bu kodu bu surecte calistir
    if not dev and not hw.is_admin() and task_exists():
        hw.run(["schtasks", "/run", "/tn", TASK])
        if wait_ping(8):
            if not service:
                open_window()
            return
    if not service:
        threading.Thread(target=lambda: wait_ping(8) and open_window(), daemon=True).start()
    serve()
    if App.restart_elevated:  # yonetici gorevi yeni kuruldu: motoru yonetici olarak yeniden baslat
        hw.run(["schtasks", "/run", "/tn", TASK])


if __name__ == "__main__":
    main()
    # Her sey kaydedildi. Yorumlayicinin kapanis temizligi, ctypes/COM/PDH nesnelerini toplarken
    # erisim ihlaline dusuyor (olculdu); temizligi atlayip sureci dogrudan bitir.
    os._exit(0)
