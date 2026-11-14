# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""Asus ROG / TUF arka ucu: ATK ACPI-WMI (DSTS/DEVS) ve Aura klavye isigi (USB HID).

donanim.DCHU ile ayni ordek tipi arayuzu uygular (kind="asus"); motor, profiller ve klavye motoru farki bilmez.

Protokol bilgisi (kod degil, yalnizca sabitler) G-Helper (seerge/g-helper: AsusACPI.cs, AsusHid.cs, Aura.cs) ve
Linux include/linux/platform_data/x86/asus-wmi.h ile karsilastirildi:

  Tasima   \\\\.\\ATKACPI + DeviceIoControl 0x0022240C, giris [yontem u32][arg boyu u32][arg...], cikis 16 bayt;
           acilamazsa root\\WMI AsusAtkWmi_WMNB.DSTS(Device_ID) / DEVS(Device_ID, Control_status) (yalnizca tamsayi)
  DSTS 0x53545344, DEVS 0x53564544
  Varlik   DSTS sonucunda 0x00010000 biti; bit yoksa ya da 0xFFFFFFFE (desteklenmeyen yontem) ise ozellik YOK
  0x00120075  isil politika  0 dengeli, 1 turbo, 2 sessiz
  0x00110013 / 0x00110014  islemci / kart fan devri (dusuk 16 bit, 100 rpm birimi; >120 gecersiz)
  0x00110024 / 0x00110025  islemci / kart fan egrisi: 16 bayt, 8 sicaklik + 8 yuzde (okuma argumani mod, 1<->2 takasli)
  0x00120057  sarj siniri (%)        0x00050021  klavye arka isigi (0x80 | seviye 0-3)
  0x00090016 (0x00090026 Vivo)  MUX: 0 = yalnizca harici kart (Ultimate), 1 = Optimus
  0x00090020  harici karti kapat (Eco)   0x00090019 / 0x00090018  XG Mobile etkin / takili
  0x00120094  islemci sicakligi (yalnizca G-Helper kullaniyor; Linux basliginda yok)

Guvenlik kurallari:
  * Her ozellik acilista DSTS ile bir kez sinanir; varlik biti olmayan ozellige HICBIR DEVS gonderilmez,
    yazma istegi donanim.Unsupported verir ve arayuz o denetimi gizler.
  * MUX "yalnizca harici kart" iken Eco acilmaz; Eco acikken MUX harici karta alinmaz (once Eco kapanir);
    XG Mobile etkinken ikisine de dokunulmaz (Linux asus-wmi'nin de reddettigi durumlar).
"""
import ctypes
import json
import os
import threading
import time
from ctypes import wintypes as wt

import ceviri
import donanim as hw

# ----------------------------------------------------------------------------- sabitler
DSTS, DEVS = 0x53545344, 0x53564544
IOCTL = 0x0022240C
PRESENCE = 0x00010000
UNSUPPORTED = 0xFFFFFFFE

DEV_THROTTLE = 0x00120075
DEV_FAN_CPU, DEV_FAN_GPU = 0x00110013, 0x00110014
DEV_CURVE_CPU, DEV_CURVE_GPU = 0x00110024, 0x00110025
DEV_BATTERY = 0x00120057
DEV_MUX, DEV_MUX_VIVO = 0x00090016, 0x00090026
DEV_ECO = 0x00090020
DEV_EGPU, DEV_EGPU_CONNECTED = 0x00090019, 0x00090018
DEV_KBD_LIGHT = 0x00050021
DEV_TEMP_CPU = 0x00120094

ASUS_BALANCED, ASUS_TURBO, ASUS_SILENT = 0, 1, 2
# Uygulamanin guc modlari Clevo kodlariyla tutulur (donanim.POWER_MODES): 0 sessiz, 1 tasarruf, 2 performans, 3 eglence
TO_ASUS = {0: ASUS_SILENT, 1: ASUS_SILENT, 2: ASUS_TURBO, 3: ASUS_BALANCED}
FROM_ASUS = {ASUS_SILENT: 0, ASUS_TURBO: 2, ASUS_BALANCED: 3}

BATTERY_MIN, BATTERY_MAX = 40, 100

AURA_VID = 0x0B05
AURA_PIDS = frozenset((0x1A30, 0x1854, 0x1869, 0x1866, 0x19B6, 0x1822, 0x1837, 0x184A, 0x183D, 0x8502, 0x1807,
                       0x17E0, 0x1ABE, 0x1B4C, 0x1B6E, 0x1B2C, 0x8854, 0x1CE7, 0x1CE6, 0x1BF2, 0x1BF3, 0x1CD7,
                       0x1CD8, 0x4B42))
AURA_ID = 0x5D
AURA_USAGE_PAGE = 0xFF31


def supported(raw):
    """DSTS ham sonucu: ozellik bu bilgisayarda var mi?"""
    if raw is None:
        return False
    raw &= 0xFFFFFFFF
    return raw not in (UNSUPPORTED, 0xFFFFFFFF) and bool(raw & PRESENCE)


def value(raw):
    """Varlik bitinin altindaki deger (G-Helper: ham - 65536)."""
    return raw & 0xFFFF


# ----------------------------------------------------------------------------- tasimalar
class AtkAcpi:
    """\\\\.\\ATKACPI aygiti (Asus System Control Interface surucusu). Arabellek de tasir: fan egrileri icin gerekli."""
    name = "ATKACPI"
    buffers = True

    def __init__(self):
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateFileW.restype = ctypes.c_void_p
        k32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p, wt.DWORD, wt.DWORD,
                                    ctypes.c_void_p]
        k32.DeviceIoControl.argtypes = [ctypes.c_void_p, wt.DWORD, ctypes.c_void_p, wt.DWORD, ctypes.c_void_p,
                                        wt.DWORD, ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        self.k32 = k32
        h = k32.CreateFileW(r"\\.\ATKACPI", 0xC0000000, 3, None, 3, 0, None)
        if not h or h == ctypes.c_void_p(-1).value:
            raise OSError(ctypes.get_last_error(), "ATKACPI acilamadi")
        self.h = h
        self.lock = threading.Lock()

    def _call(self, method, args, out_len=16):
        buf = method.to_bytes(4, "little") + len(args).to_bytes(4, "little") + bytes(args)
        inb = (ctypes.c_ubyte * len(buf)).from_buffer_copy(buf)
        out = (ctypes.c_ubyte * out_len)()
        n = wt.DWORD()
        with self.lock:
            ok = self.k32.DeviceIoControl(self.h, IOCTL, inb, len(buf), out, out_len, ctypes.byref(n), None)
        if not ok:
            raise OSError(ctypes.get_last_error(), "DeviceIoControl")
        return bytes(out)

    @staticmethod
    def _args(dev, arg):
        return dev.to_bytes(4, "little") + (arg & 0xFFFFFFFF).to_bytes(4, "little")

    def dsts(self, dev, arg=0):
        return int.from_bytes(self._call(DSTS, self._args(dev, arg))[:4], "little")

    def dsts_buf(self, dev, arg=0):
        return self._call(DSTS, self._args(dev, arg))

    def devs(self, dev, val):
        return int.from_bytes(self._call(DEVS, self._args(dev, val))[:4], "little")

    def devs_buf(self, dev, payload):
        return int.from_bytes(self._call(DEVS, dev.to_bytes(4, "little") + bytes(payload))[:4], "little")

    def close(self):
        if self.h:
            self.k32.CloseHandle(self.h)
            self.h = None


class WmiAtk:
    """root\\WMI AsusAtkWmi_WMNB: ATKACPI acilamazsa. Yalnizca tamsayi tasir (fan egrisi yok)."""
    name = "WMI"
    buffers = False
    CLS = "AsusAtkWmi_WMNB"

    def __init__(self, wmi=None):
        if wmi is None:
            import wmi_com
            wmi = wmi_com.Wmi(r"root\WMI")
        self.wmi = wmi
        rows = wmi.query("SELECT __PATH FROM %s" % self.CLS)
        if not rows:
            raise OSError("%s ornegi yok" % self.CLS)
        self.path = rows[0]["__PATH"]

    def dsts(self, dev, arg=0):
        return self.wmi.call(self.path, self.CLS, "DSTS", {"Device_ID": dev}, "device_status")

    def dsts_buf(self, dev, arg=0):
        raise hw.Unsupported("WMI arabellek tasimaz")

    def devs(self, dev, val):
        return self.wmi.call(self.path, self.CLS, "DEVS", {"Device_ID": dev, "Control_status": val}, "result")

    def devs_buf(self, dev, payload):
        raise hw.Unsupported("WMI arabellek tasimaz")

    def close(self):
        try:
            self.wmi.close()
        except Exception:
            pass


# ----------------------------------------------------------------------------- tespit
def asus_present(wmi_factory=None):
    """Uretici ASUSTeK VE root\\WMI'de AsusAtkWmi_WMNB ornegi var mi? Suphede False (donanima dokunulmaz)."""
    try:
        if wmi_factory is None:
            import wmi_com
            wmi_factory = wmi_com.Wmi
        cs = wmi_factory(r"root\cimv2")
        try:
            rows = cs.query("SELECT Manufacturer FROM Win32_ComputerSystem", ["Manufacturer"])
        finally:
            cs.close()
        maker = ((rows[0].get("Manufacturer") if rows else "") or "").strip().upper()
        if not maker.startswith("ASUSTEK"):
            return False
        w = wmi_factory(r"root\WMI")
        try:
            return bool(w.query("SELECT __PATH FROM AsusAtkWmi_WMNB"))
        finally:
            w.close()
    except Exception:
        return False


def open_transport():
    try:
        return AtkAcpi()
    except Exception:
        return WmiAtk()


# ----------------------------------------------------------------------------- Aura klavye
class AuraKeyboard:
    """Tek bolge Aura klavye (USB HID, rapor 0x5D). Her renk: 0xB3 (statik) + 0xB5 (uygula). 0xB4 yalnizca renk
    2 sn degismeden durunca bir kez gider: animasyonda her karede kalici bellege yazilmasin."""
    SPEED = 0xEB
    SAVE_AFTER = 2.0

    def __init__(self, dev):
        self.dev = dev
        self.last = None
        self.changed_at = 0.0
        self.saved = True
        self.lock = threading.Lock()
        for msg in ([AURA_ID, 0xB9], [AURA_ID] + list(b"ASUS Tech.Inc."), [AURA_ID, 0x05, 0x20, 0x31, 0x00, 0x1A]):
            self._send(msg)

    @classmethod
    def find(cls, hid=None):
        """Aura arayuzu: VID 0x0B05, bilinen PID, ozellik raporu olan satici kullanim sayfasi 0xFF31."""
        if hid is None:
            import hid_win as hid
        for info in hid.enumerate_devices([AURA_VID]):
            if info["pid"] in AURA_PIDS and info.get("feat_len", 0) > 0 \
                    and info.get("usage_page") == AURA_USAGE_PAGE:
                try:
                    return cls(hid.HidDevice(info))
                except OSError:
                    continue
        return None

    def _send(self, msg):
        try:
            self.dev.set_feature(msg)
        except OSError:
            self.dev.write(msg)

    def set_color(self, r, g, b):
        rgb = (int(r) & 255, int(g) & 255, int(b) & 255)
        now = time.monotonic()
        with self.lock:
            if rgb != self.last:
                self._send([AURA_ID, 0xB3, 0x00, 0x00, rgb[0], rgb[1], rgb[2], self.SPEED, 0x00])
                self._send([AURA_ID, 0xB5, 0x00, 0x00, 0x00])
                self.last, self.changed_at, self.saved = rgb, now, False
            elif not self.saved and now - self.changed_at >= self.SAVE_AFTER:
                self._send([AURA_ID, 0xB4])
                self.saved = True
        return 0

    def close(self):
        try:
            self.dev.close()
        except Exception:
            pass


# ----------------------------------------------------------------------------- arka uc
def _plausible_curve(buf):
    """16 baytlik fabrika egrisi akla yatkin mi: artan sicakliklar 20-110 C, artan yuzdeler 0-100."""
    if not buf or len(buf) < 16:
        return False
    temps, pct = list(buf[:8]), list(buf[8:16])
    if not all(20 <= t <= 110 for t in temps) or not all(0 <= p <= 100 for p in pct):
        return False
    return all(a <= b for a, b in zip(temps, temps[1:])) and all(a <= b for a, b in zip(pct, pct[1:])) \
        and temps[-1] > temps[0]


class AsusRog:
    available = True
    kind = "asus"
    clevo = False
    reason = ""

    def __init__(self, transport, keyboard=None, settings_path=None):
        self.t = transport
        self.path = "Asus ATK (%s)" % transport.name
        self.lock = threading.RLock()
        self.settings_path = settings_path
        self.kb = keyboard
        self.kb_available = keyboard is not None
        self.kb_reason = "" if keyboard else ceviri.t("asus.noAura")
        self._kb_lit = False
        self.feat, self.raw = {}, {}
        for key, dev in (("throttle", DEV_THROTTLE), ("fan_cpu", DEV_FAN_CPU), ("fan_gpu", DEV_FAN_GPU),
                         ("battery", DEV_BATTERY), ("mux", DEV_MUX), ("mux_vivo", DEV_MUX_VIVO), ("eco", DEV_ECO),
                         ("egpu", DEV_EGPU), ("kbd_light", DEV_KBD_LIGHT), ("temp_cpu", DEV_TEMP_CPU)):
            self.raw[key] = self._probe(dev)
            self.feat[key] = supported(self.raw[key])
        self.mux_dev = DEV_MUX if self.feat["mux"] else (DEV_MUX_VIVO if self.feat["mux_vivo"] else None)
        v = value(self.raw["throttle"]) if self.feat["throttle"] else None
        self._mode = v if v in FROM_ASUS else None
        self._curves = {}  # (aygit, asus modu) -> fabrika egrisi 16 bayt
        self.feat["curve_cpu"] = self._factory(DEV_CURVE_CPU) is not None
        self.feat["curve_gpu"] = self._factory(DEV_CURVE_GPU) is not None
        self.fan_control = self.feat["curve_cpu"]
        self.ec_temps = self.feat["temp_cpu"]  # yoksa sensorler ACPI isi bolgesini kullanir
        self._fan = hw.FAN_AUTO
        self._battery = None

    # ------------------------------------------------------------------ ham erisim
    def _probe(self, dev):
        try:
            return self.t.dsts(dev)
        except Exception:
            return None

    def _read(self, dev):
        try:
            return value(self.t.dsts(dev))
        except Exception:
            return None

    def _need(self, key):
        if not self.feat.get(key):
            raise hw.Unsupported(ceviri.t("asus.unsupported"))

    def _devs(self, dev, val):
        with self.lock:
            return self.t.devs(dev, val)

    def _factory(self, dev, asus_mode=None):
        """Fabrika egrisi (16 bayt) ya da None. G-Helper notu: okuma argumaninda 1 ve 2 takaslidir."""
        if not getattr(self.t, "buffers", False):
            return None
        mode = self._mode or 0 if asus_mode is None else asus_mode
        key = (dev, mode)
        if key not in self._curves:
            try:
                buf = self.t.dsts_buf(dev, {1: 2, 2: 1}.get(mode, 0))
            except Exception:
                buf = None
            self._curves[key] = bytes(buf[:16]) if _plausible_curve(buf) else None
        return self._curves[key]

    # ------------------------------------------------------------------ Clevo'ya ozel komutlar
    def set_wmi(self, *args, **kwargs):  # ornek: Clevo Fn olaylari 0x46
        raise hw.Unsupported(ceviri.t("asus.unsupported"))

    set_data = write_app = set_wmi

    # ------------------------------------------------------------------ olcumler
    def status(self):
        out = {}
        for key, dev, name in (("fan_cpu", DEV_FAN_CPU, "cpu_rpm"), ("fan_gpu", DEV_FAN_GPU, "gpu_rpm")):
            if self.feat[key]:
                v = self._read(dev)
                if v is not None and v <= 120:
                    out[name] = v * 100
        if self.feat["temp_cpu"]:
            v = self._read(DEV_TEMP_CPU)
            if v is not None and 1 <= v <= 110:
                out["cpu_temp"] = v
        return out

    def temps(self):
        s = self.status()
        return s.get("cpu_temp"), s.get("gpu_temp")

    # ------------------------------------------------------------------ guc modu
    def power_modes(self):
        return [0, 2, 3] if self.feat["throttle"] else []

    def power_mode(self):
        return FROM_ASUS.get(self._mode)

    def set_power_mode(self, mode):
        if mode not in hw.POWER_MODES:
            raise ValueError(ceviri.t("err.unknownPower"))
        self._need("throttle")
        a = TO_ASUS[mode]
        self._devs(DEV_THROTTLE, a)
        self._mode = a
        self._fan = hw.FAN_AUTO  # politika degisince bellenim ozel egriyi fabrikaya dondurur

    # ------------------------------------------------------------------ fan
    def fan_mode(self):
        return self._fan

    def set_fan_mode(self, mode):
        if mode == hw.FAN_AUTO:
            # Ozel egriyi birakmanin yolu isil politikayi yeniden yazmak (G-Helper da boyle yapar)
            if self.fan_control and self.feat["throttle"] and self._mode is not None:
                self._devs(DEV_THROTTLE, self._mode)
            self._fan = hw.FAN_AUTO
            return
        if mode == hw.FAN_MAX:
            self._need("curve_cpu")
            for key, dev in (("curve_cpu", DEV_CURVE_CPU), ("curve_gpu", DEV_CURVE_GPU)):
                base = self._factory(dev)
                if self.feat[key] and base:
                    self._write_curve(dev, list(base[:8]), [100] * 8)
            self._fan = hw.FAN_MAX
            return
        raise ValueError(ceviri.t("err.fanMode"))

    def fan_default(self):
        """Arayuzun 4 noktali bicimi [(T1,D1), (T,D), (T,D), (100,100)]: 8 noktalik fabrika egrisinden."""
        if not self.fan_control:
            return None
        out = {"count": 2 if self.feat["curve_gpu"] else 1}
        for key, dev in (("cpu", DEV_CURVE_CPU), ("gpu", DEV_CURVE_GPU)):
            base = self._factory(dev) or self._factory(DEV_CURVE_CPU)
            t, p = list(base[:8]), list(base[8:16])
            out[key] = [(t[0], p[0]), (t[3], p[3]), (t[6], p[6]), (100, 100)]
        return out

    @staticmethod
    def curve_points(base, pts):
        """Uygulamanin (T2,D2,T3,D3) egrisini fabrika egrisinin 8 sicakligina yayar: (sicakliklar, yuzdeler)."""
        temps = list(base[:8])
        t1, d1 = temps[0], base[8]
        t2, d2, t3, d3 = hw.validate_curve(pts, t1, d1)
        knots = [(t1, d1), (t2, d2), (t3, d3), (100, 100)]

        def f(t):
            if t <= t1:
                return d1
            for (ta, da), (tb, db) in zip(knots, knots[1:]):
                if t <= tb:
                    return da + (db - da) * (t - ta) / float(tb - ta)
            return 100
        pct, prev = [], 0
        for t in temps:
            prev = max(prev, min(100, int(round(f(t)))))
            pct.append(prev)
        return temps, pct

    def _write_curve(self, dev, temps, pct):
        with self.lock:
            return self.t.devs_buf(dev, bytes(temps) + bytes(pct))

    def set_fan_curve(self, cpu, gpu):
        self._need("curve_cpu")
        for key, dev, pts in (("curve_cpu", DEV_CURVE_CPU, cpu), ("curve_gpu", DEV_CURVE_GPU, gpu)):
            base = self._factory(dev)
            if self.feat[key] and base:
                self._write_curve(dev, *self.curve_points(base, pts))
        self._fan = hw.FAN_CUSTOM

    # ------------------------------------------------------------------ klavye
    def set_color(self, r, g, b):
        if not self.kb:
            return 0
        if not self._kb_lit and (r or g or b):
            self._kb_lit = True
            if self.feat["kbd_light"]:
                try:  # arka isik Fn ile kapatilmissa renk gorunmez: Clevo'daki gibi tam parlaklik (seviye 3)
                    self._devs(DEV_KBD_LIGHT, 0x80 | 3)
                except Exception:
                    pass
        try:
            return self.kb.set_color(r, g, b)
        except OSError:
            return 0

    # ------------------------------------------------------------------ sarj siniri
    def battery_limit(self):
        return self._battery

    def set_battery_limit(self, pct, save=True):
        self._need("battery")
        pct = max(BATTERY_MIN, min(BATTERY_MAX, int(pct)))
        self._devs(DEV_BATTERY, pct)
        self._battery = pct
        if save:
            self._save({"battery": pct})
        return pct

    # ------------------------------------------------------------------ ekran karti
    def gpu_state(self):
        """{'mux': 0/1/None, 'eco': 0/1/None, 'xg': bool, 'mode': 'eco'|'standard'|'ultimate'|None}"""
        bit = lambda v: None if v is None else v & 1  # noqa: E731
        mux = bit(self._read(self.mux_dev)) if self.mux_dev else None
        eco = bit(self._read(DEV_ECO)) if self.feat["eco"] else None
        xg = bool(bit(self._read(DEV_EGPU))) if self.feat["egpu"] else False
        mode = None
        if mux == 0:
            mode = "ultimate"
        elif eco == 1:
            mode = "eco"
        elif mux is not None or eco is not None:
            mode = "standard"
        return {"mux": mux, "eco": eco, "xg": xg, "mode": mode}

    def gpu_modes(self):
        out = []
        if self.feat["eco"]:
            out.append("eco")
        if self.feat["eco"] or self.mux_dev:
            out.append("standard")
        if self.mux_dev:
            out.append("ultimate")
        return out

    def set_gpu_mode(self, mode):
        """Donus: {'reboot': bool}. MUX degisikligi yeniden baslatmadan sonra gecerli olur."""
        if mode not in self.gpu_modes():
            raise hw.Unsupported(ceviri.t("asus.unsupported"))
        st = self.gpu_state()
        if st["xg"]:
            raise hw.Unsupported(ceviri.t("asus.gpu.xg"))
        if st["mode"] is None or (self.mux_dev and st["mux"] is None) or (self.feat["eco"] and st["eco"] is None):
            raise hw.Unsupported(ceviri.t("asus.gpu.unknown"))  # durum okunamadi: tahminle yazilmaz
        reboot = False
        if mode == "eco":
            if st["mux"] == 0:  # yalnizca harici kart modunda harici kart kapatilamaz
                raise hw.Unsupported(ceviri.t("asus.gpu.ecoUltimate"))
            if st["eco"] != 1:
                self._devs(DEV_ECO, 1)
        elif mode == "standard":
            if st["eco"] == 1:
                self._devs(DEV_ECO, 0)
            if st["mux"] == 0:
                self._devs(self.mux_dev, 1)
                reboot = True
        elif mode == "ultimate":
            if st["eco"] == 1:  # kapali karta MUX gecirilmez: once Eco kapanir
                self._devs(DEV_ECO, 0)
            if st["mux"] != 0:
                self._devs(self.mux_dev, 0)
                reboot = True
        return {"reboot": reboot}

    # ------------------------------------------------------------------ arayuz ve kalicilik
    def features(self):
        modes = self.gpu_modes()
        return {
            "power_modes": self.power_modes(),
            "fan_rpm": self.feat["fan_cpu"] or self.feat["fan_gpu"],
            "fan_curve": self.fan_control,
            "battery": self.feat["battery"],
            "battery_limit": self._battery,
            "battery_range": [BATTERY_MIN, BATTERY_MAX],
            "gpu_modes": modes,
            "gpu": self.gpu_state() if modes else None,
            "kb": self.kb_available,
            "transport": self.t.name,
        }

    def _path(self):
        """Ayar dosyasi: verilmediyse motorun ayar klasorunde asus.json (yonetici motorda Program Files/veri)."""
        if self.settings_path:
            return self.settings_path
        import klavye_rgb  # gec yukleme: set_data_dir() sonrasi klasor
        return os.path.join(klavye_rgb.CONFIG_DIR, "asus.json")

    def _load(self):
        try:
            with open(self._path(), "r", encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError, TypeError, ImportError):
            return {}

    def _save(self, upd):
        path = self._path()
        d = self._load()
        d.update(upd)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(d, f)
            os.replace(tmp, path)
        except OSError:
            pass

    def restore(self):
        """Bellenim sarj sinirini yeniden baslatmada unutabilir (G-Helper da acilista yeniden yazar)."""
        b = self._load().get("battery")
        if isinstance(b, int) and self.feat["battery"]:
            try:
                self.set_battery_limit(b, save=False)
            except Exception:
                pass

    def handle(self, body):
        """/api/asus istegi: {'battery': yuzde} ve/veya {'gpu': 'eco'|'standard'|'ultimate'}."""
        out = {}
        if "battery" in body:
            try:
                pct = int(body["battery"])
            except (TypeError, ValueError):
                raise ValueError(ceviri.t("asus.badValue"))
            out["battery_limit"] = self.set_battery_limit(pct)
        if "gpu" in body:
            out.update(self.set_gpu_mode(str(body["gpu"])))
        out["asus"] = self.features()
        return out


def open_asus(settings_path=None):
    """Asus arka ucu; ATK tasimasi hic acilamazsa istisna (donanim.open_dchu NullDCHU'ya duser)."""
    t = open_transport()
    try:
        kb = AuraKeyboard.find()
    except Exception:
        kb = None
    dev = AsusRog(t, kb, settings_path)
    dev.restore()
    return dev
