# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""Alienware / Dell G arka ucu: gomulu denetleyiciye AWCC WMI arayuzu (root\\WMI AWCCWmiMethodFunction,
GUID A70591CE-A997-11DA-B012-B622A1EF5492), klavye isigina AlienFX HID uzerinden ulasir.

donanim.DCHU ile ayni arayuzu sunar (status, temps, power_mode, set_power_mode, fan_mode, set_fan_mode,
fan_default, set_fan_curve, set_color); profiller, fan sayfasi ve klavye motoru degismeden calisir.

Protokol kaynaklari (2026-11-14): Linux drivers/platform/x86/dell/alienware-wmi-wmax.c ve
Documentation/wmi/devices/alienware-wmi.rst; T-Troll/alienfx-tools (alienfan-SDK_v2, AlienFX_SDK).
Linux bu surucude "Alienware 16 Aurora" ve "Alienware 16X Aurora" icin fan, profil ve G-mode'u acar.

  arg2 (uint32) = islem | arg1 << 8 | arg2 << 16 ; donus argr, 0xFFFFFFFF / 0xFFFFFFFE = hata
  Thermal_Information  02 sistem tanimi (fan, sensor, bilinmeyen, profil sayilari)   03 kaynak kimligi (sira)
                       04 sicaklik (sensor)  05 fan devri  09 fan en yuksek devir  0B etkin profil
  Thermal_Control      01 profil etkinlestir   02 fan takviyesi yaz (fan, 0..100)
  GetFanSensors        01 fana bagli sensor sayisi   02 o sensorun kimligi
  GameShiftStatus      01 G-mode cevir   02 G-mode durumu

Clevo'dan temel fark: Clevo'da ozel fan egrisini denetleyicinin kendisi calistirir. AWCC'de egri yoktur;
"Ozel" (0x00) profilde her fana takviye degeri yazilir. Egriyi bu yuzden bu modul saniyede bir uygular
(Alienware Command Center ve alienfx-tools da boyle yapar). Uygulama kapanirken ya da sicaklik okunamazsa
fanlar denetleyicinin kendi profiline birakilir.

Alienware Fn tuslari (Stealth, G-mode) ve AWCC profili uygulamadan bagimsiz degistirebilir; uygulama bunlari
engellemez. Etkin profil her saniye (egri dongusu) ve her durum okumasinda denetlenir: disaridan degistiyse
ozel fan egrisi durur ve arayuz gercek guc modunu gosterir (_sync).
"""
import os
import sys
import threading

import ceviri

# --------------------------------------------------------------------------- AWCC sabitleri
CLASS = "AWCCWmiMethodFunction"
M_INFO, M_CONTROL, M_FANSENS, M_GAMESHIFT = "Thermal_Information", "Thermal_Control", "GetFanSensors", "GameShiftStatus"
OP_DESC, OP_RES, OP_TEMP, OP_RPM, OP_MAXRPM, OP_PROFILE = 0x02, 0x03, 0x04, 0x05, 0x09, 0x0B
OP_ACTIVATE, OP_SETBOOST = 0x01, 0x02
ERRORS = (0xFFFFFFFF, 0xFFFFFFFE)

P_CUSTOM, P_GMODE = 0x00, 0xAB
LEGACY = {"quiet": 0x96, "balanced": 0x97, "balperf": 0x98, "perf": 0x99}
USTT = {"balanced": 0xA0, "balperf": 0xA1, "cool": 0xA2, "quiet": 0xA3, "perf": 0xA4, "lowpower": 0xA5}
PROFILE_NAMES = {v: k for k, v in list(LEGACY.items()) + list(USTT.items())}
PROFILE_NAMES.update({P_CUSTOM: "custom", P_GMODE: "gmode"})

# Uygulamanin 4 guc modu (donanim.POWER_MODES) -> tercih sirasina gore AWCC profilleri
MODE_PREFS = {
    0: ["quiet", "cool", "lowpower", "balanced"],      # Sessiz
    1: ["lowpower", "quiet", "cool", "balanced"],      # Guc tasarrufu
    2: ["gmode", "perf", "balperf", "balanced"],       # Performans
    3: ["balanced", "balperf"],                        # Eglence (gunluk denge)
}
# Disaridan (Fn tusu, AWCC) secilen bir profilin uygulamadaki karsiligi: arayuz gercek modu gostersin diye
NAME_MODE = {"quiet": 0, "cool": 0, "lowpower": 1, "balanced": 3, "balperf": 3, "perf": 2, "gmode": 2}
GPU_FANS = {0x33, 0x3C}           # GPU1, GPU2; digerleri islemci tarafi sayilir
SENSOR_CPU, SENSOR_GPU = 0x01, 0x06
FAN_AUTO, FAN_MAX, FAN_CUSTOM = 0, 1, 6  # donanim.py ile ayni

# Arayuzun "fabrika egrisi" cizgisi ve egri dogrulamasinin ilk noktasi. AWCC fabrika tablosunu vermez; bu
# olcum degil, Dengeli profile yakin bir referans egridir (arayuz bunu "referans" diye gosterir).
REFERENCE_CURVE = [(45, 20), (65, 40), (80, 70), (100, 100)]


class AwccError(RuntimeError):
    pass


class NoAwcc(AwccError):
    """Bu bilgisayarda AWCC arayuzu yok."""


def pack(op, a1=0, a2=0):
    return (op & 0xFF) | ((a1 & 0xFF) << 8) | ((a2 & 0xFF) << 16)


def interpolate(points, temp):
    """[(T, D%), ...] artan T; T1 altinda D1, son noktadan sonra son D."""
    if temp <= points[0][0]:
        return points[0][1]
    for (t0, d0), (t1, d1) in zip(points, points[1:]):
        if temp <= t1:
            return d0 + (d1 - d0) * (temp - t0) / float(t1 - t0) if t1 != t0 else d1
    return points[-1][1]


class Awcc:
    """AWCC WMI yontemleri. wmi: wmi_com.Wmi (ya da testte sahtesi)."""

    def __init__(self, wmi):
        self.wmi = wmi
        rows = wmi.query("SELECT * FROM " + CLASS, ["__PATH"])
        if not rows:
            raise NoAwcc("AWCCWmiMethodFunction ornegi yok")
        self.path = rows[0]["__PATH"]

    def call(self, method, op, a1=0, a2=0):
        r = self.wmi.call(self.path, CLASS, method, {"arg2": pack(op, a1, a2)}, "argr")
        if r is None:
            raise AwccError("%s(%02X): yanit yok" % (method, op))
        r &= 0xFFFFFFFF
        if r in ERRORS:
            raise AwccError("%s(%02X, %02X): denetleyici reddetti" % (method, op, a1))
        return r

    def info(self, op, a1=0, a2=0):
        return self.call(M_INFO, op, a1, a2)

    def control(self, op, a1=0, a2=0):
        return self.call(M_CONTROL, op, a1, a2)


class Thermal:
    """Sistem tanimindan fanlar, sensorler ve profiller (Linux surucusunun yaptigi gibi)."""

    def __init__(self, awcc):
        self.awcc = awcc
        d = awcc.info(OP_DESC)
        nfan, ntemp, nunk, nprof = d & 0xFF, (d >> 8) & 0xFF, (d >> 16) & 0xFF, (d >> 24) & 0xFF
        if not (1 <= nfan <= 16 and ntemp <= 16 and nunk <= 16 and nprof <= 16):
            raise AwccError("gecersiz sistem tanimi 0x%08X" % d)
        self.fans = [awcc.info(OP_RES, i) & 0xFF for i in range(nfan)]
        self.sensors = [awcc.info(OP_RES, nfan + i) & 0xFF for i in range(ntemp)]
        self.profiles = []
        for i in range(nprof):
            try:  # bazi aygitlar profil sayisini fazla bildirir: ilk reddedilende durulur
                p = awcc.info(OP_RES, nfan + ntemp + nunk + i) & 0xFF
            except AwccError:
                break
            if p in PROFILE_NAMES and p not in (P_CUSTOM, P_GMODE) and p not in self.profiles:
                self.profiles.append(p)
        self.gmode = self._gmode_supported()
        self.fan_sensors = {}
        for f in self.fans:
            ids = []
            try:
                for j in range(min(awcc.call(M_FANSENS, 0x01, f) & 0xFF, 8)):
                    ids.append(awcc.call(M_FANSENS, 0x02, f, j) & 0xFF)
            except AwccError:
                pass
            self.fan_sensors[f] = ids
        self.max_rpm = {}
        for f in self.fans:
            try:
                self.max_rpm[f] = awcc.info(OP_MAXRPM, f) & 0xFFFF
            except AwccError:
                self.max_rpm[f] = 0

    def _gmode_supported(self):
        try:
            self.awcc.call(M_GAMESHIFT, 0x02)
            return True
        except Exception:
            return False

    def by_name(self, name):
        if name == "gmode":
            return P_GMODE if self.gmode else None
        for table in (USTT, LEGACY):
            pid = table.get(name)
            if pid in self.profiles:
                return pid
        return None

    def profile_for_mode(self, mode):
        for name in MODE_PREFS[mode]:
            pid = self.by_name(name)
            if pid is not None:
                return pid
        return self.profiles[0] if self.profiles else None

    def sensor(self, kind):
        """kind: SENSOR_CPU / SENSOR_GPU; sensor kimligi ya da None."""
        return kind if kind in self.sensors else None

    def describe(self):
        return {"fans": ["0x%02X" % f for f in self.fans], "sensors": ["0x%02X" % s for s in self.sensors],
                "profiles": [PROFILE_NAMES.get(p, "0x%02X" % p) for p in self.profiles], "gmode": self.gmode,
                "fan_sensors": {"0x%02X" % f: ["0x%02X" % s for s in v] for f, v in self.fan_sensors.items()},
                "max_rpm": {"0x%02X" % f: v for f, v in self.max_rpm.items()}}


# --------------------------------------------------------------------------- klavye isigi (AlienFX)
ALIENFX_VIDS = (0x187C, 0x0D62)


class AlienFx:
    """AlienFX HID klavye: APIv4 (0x187C, 34 baytlik cikis raporu) ve APIv5 (0x0D62, kullanim 0xCC, 64 baytlik
    ozellik raporu). Tek renkte v4'te 0..LIGHTS-1 kimliklerinin hepsine, v5'te tum tuslara ayni renk yazilir.

    Bolgeler (Alienware 16X Aurora: AWCC'de soldan saga 4 bolge): bolge -> isik kimligi eslemesi uretici
    tarafindan yayimlanmaz (AlienFX-SDK de model bazinda eslemeyi kullanicinin yoklamasina birakir). Varsayilan
    ZONE_IDS (bolge i = kimlik i) disarida kalan kimlikler 1. bolgenin rengini alir: esleme yanlissa bile klavye
    karanlik kalmaz. Gercek esleme 'python alienware.py --bolge-testi' ile bulunur ve ayar klasorundeki
    alienfx.json'a {"zones": [[kimlikler], [..], [..], [..]]} olarak yazilir."""
    LIGHTS = 16      # v4: tek bolgeli klavyede kimlik bu aralikta (alienfx-tools probe araligi)
    V5_KEYS = 128
    ZONES = 4
    ZONE_IDS = ([0], [1], [2], [3])
    ZONE_FILE = "alienfx.json"

    def __init__(self, hid, info, zone_ids=None):
        self.dev = hid.HidDevice(info)
        self.info = info
        self.api = 4 if info["vid"] == 0x187C else 5
        self.last = None
        self.zone_ids = self._valid_zones(zone_ids) or self._load_zones() or [list(z) for z in self.ZONE_IDS]

    @property
    def count(self):
        return self.LIGHTS if self.api == 4 else self.V5_KEYS

    def _valid_zones(self, zones):
        """[[kimlik..] x ZONES] gecerliyse tamsayi listesi, degilse None."""
        if not isinstance(zones, (list, tuple)) or len(zones) != self.ZONES:
            return None
        out = []
        for z in zones:
            if not isinstance(z, (list, tuple)) or not z:
                return None
            ids = [i for i in z if isinstance(i, int) and not isinstance(i, bool) and 0 <= i < self.count]
            if len(ids) != len(z):
                return None
            out.append(ids)
        return out

    def _load_zones(self):
        try:
            import json
            import klavye_rgb  # gec ice aktarma: motor yuklu; yonetici motorda veri klasoru Program Files altinda
            with open(os.path.join(klavye_rgb.CONFIG_DIR, self.ZONE_FILE), encoding="utf-8") as f:
                return self._valid_zones(json.load(f).get("zones"))
        except Exception:
            return None

    @staticmethod
    def find(hid):
        """Uygun ilk aygitin bilgisi ya da None."""
        for d in hid.enumerate_devices(ALIENFX_VIDS):
            if d["vid"] == 0x187C and d.get("out_len") == 34:
                return d
            if d["vid"] == 0x0D62 and d.get("usage") == 0xCC and not d.get("out_len") and d.get("feat_len"):
                return d
        return None

    def _v4(self, *data):
        self.dev.write((0x00, 0x03) + data, 34)

    def _write(self, lights):
        """lights: {kimlik: (r, g, b)}, tum kimlikler. v4'te ayni renkteki kimlikler tek pakette gider."""
        if self.api == 4:
            groups = {}
            for i in sorted(lights):  # donanim kisiti: kimlikler kucukten buyuge (AlienFX-SDK notu)
                groups.setdefault(lights[i], []).append(i)
            self._v4(0x21, 0x00, 0x04, 0xFF, 0xFF)          # yeni kare
            self._v4(0x21, 0x00, 0x01, 0xFF, 0xFF)
            for (r, g, b), ids in groups.items():
                self._v4(0x27, r, g, b, 0x00, len(ids), *ids)  # duz renk
            self._v4(0x21, 0x00, 0x03, 0xFF, 0xFF)          # uygula
        else:
            n = self.info.get("feat_len") or 64
            self.dev.set_feature((0xCC, 0x94), n)            # sifirla
            per = (n - 4) // 4
            keys = sorted(lights)
            for start in range(0, len(keys), per):
                pkt = [0xCC, 0x8C, 0x02, 0x00]
                for k in keys[start:start + per]:
                    pkt += [k + 1] + list(lights[k])
                self.dev.set_feature(pkt, n)
            self.dev.set_feature((0xCC, 0x8C, 0x13), n)     # dongu
            self.dev.set_feature((0xCC, 0x8B, 0x01, 0xFF), n)  # uygula

    def set_color(self, r, g, b):
        col = (r, g, b)
        if col == self.last:
            return 0
        self._write(dict.fromkeys(range(self.count), col))
        self.last = col
        return 0

    def set_zones(self, cols):
        """cols: soldan saga ZONES renk. Esleme disindaki kimlikler 1. bolgenin rengini alir."""
        cols = tuple(tuple(int(v) & 255 for v in c) for c in cols[:self.ZONES])
        if len(cols) < self.ZONES:
            cols += (cols[-1] if cols else (0, 0, 0),) * (self.ZONES - len(cols))
        if len(set(cols)) == 1:
            return self.set_color(*cols[0])
        if cols == self.last:
            return 0
        lights = dict.fromkeys(range(self.count), cols[0])
        for z, ids in enumerate(self.zone_ids):
            for i in ids:
                lights[i] = cols[z]
        self._write(lights)
        self.last = cols
        return 0

    def close(self):
        self.dev.close()


# --------------------------------------------------------------------------- denetleyici
class AlienwareEC:
    """donanim.DCHU'nun Alienware karsiligi."""
    available = True
    kind = "alienware"
    clevo = False
    reason = ""

    def __init__(self, wmi, hid=None, curve_period=1.0):
        self.wmi = wmi
        self.awcc = Awcc(wmi)
        self.th = Thermal(self.awcc)
        self.path = "AWCC WMI (root\\WMI %s)" % CLASS
        self.lock = threading.RLock()
        self._mode = None            # son istenen guc modu (0..3)
        self._fan = FAN_AUTO
        self._curve = None           # {"cpu": [(T,D)...], "gpu": [...]}
        self._boost = {}
        self._period = curve_period
        self._stop = None            # calisan egri is parcaciginin durdurma olayi
        self.kb = None
        self.kb_available = False
        self.kb_reason = ceviri.t("err.awKbNone")
        if hid is not None:
            try:
                info = AlienFx.find(hid)
                if info:
                    self.kb = AlienFx(hid, info)
                    self.kb_available = True
                    self.kb_reason = ""
            except Exception as exc:
                self.kb_reason = "%s: %s" % (ceviri.t("err.awKbOpen"), exc)

    # ------------------------------------------------------------------ olcumler
    def _temp(self, sensor):
        if sensor is None:
            return None
        try:
            v = self.awcc.info(OP_TEMP, sensor) & 0xFFFF
        except AwccError:
            return None
        return v if 0 < v <= 150 else None  # bazi surumler anlamsiz buyuk deger verir

    def _rpm(self, fan):
        try:
            return self.awcc.info(OP_RPM, fan) & 0xFFFF
        except AwccError:
            return 0

    def _fan_of(self, gpu):
        for f in self.th.fans:
            if (f in GPU_FANS) == gpu:
                return f
        if gpu and len(self.th.fans) > 1:  # GPU kimligi tanimsiz: ikinci fan
            return self.th.fans[1]
        return None

    def status(self):
        cpu_t = self._temp(self.th.sensor(SENSOR_CPU))
        gpu_t = self._temp(self.th.sensor(SENSOR_GPU))
        out = {"cpu_temp": cpu_t or 0, "gpu_temp": gpu_t or 0}
        for key, gpu in (("cpu", False), ("gpu", True)):
            f = self._fan_of(gpu)
            rpm = self._rpm(f) if f is not None else 0
            top = self.th.max_rpm.get(f) or 0
            out[key + "_rpm"] = rpm
            out[key + "_duty"] = round(min(rpm * 100.0 / top, 100)) if top else 0
        return out

    def temps(self):
        s = self.status()
        return s["cpu_temp"], s["gpu_temp"]

    # ------------------------------------------------------------------ guc modu
    def _sync(self):
        """Etkin profili denetleyiciden okur ve disaridan bir degisikligi (Alienware Fn tuslari: Stealth, G-mode;
        Alienware Command Center) benimser: uygulamanin ozel fan modu biter (takviye sifirlanir, fanlar o profilin
        tablosuna kalir) ve guc modu o profilden okunur. Uygulama profili GERI ALMAZ; son secen kazanir.
        Donus: etkin profil kimligi ya da (okunamazsa) None."""
        with self.lock:
            try:
                cur = self.awcc.info(OP_PROFILE) & 0xFF
            except AwccError:
                return None
            if cur == P_CUSTOM:  # bizim ozel fan modumuz (ya da AWCC'de elle ozel mod)
                return cur
            if self._fan != FAN_AUTO:  # biz "Ozel"deydik, biri baska profile gecti
                self._stop_curve()
                self._fan = FAN_AUTO
                for f in self.th.fans:
                    try:
                        self._set_boost(f, 0)
                    except AwccError:
                        pass
            if self._mode is None or self.th.profile_for_mode(self._mode) != cur:
                m = NAME_MODE.get(PROFILE_NAMES.get(cur))
                if m is not None:
                    self._mode = m
            return cur

    def power_mode(self):
        cur = self._sync()
        if self._mode is not None:
            return self._mode
        return None if cur is None else 3

    def _gmode_on(self):
        return bool(self.awcc.call(M_GAMESHIFT, 0x02) & 0xFF)

    def _activate(self, pid):
        if self.th.gmode:  # G-mode anahtari hedefle ayni durumda olmali (Linux surucusu de boyle yapar)
            try:
                if self._gmode_on() != (pid == P_GMODE):
                    self.awcc.call(M_GAMESHIFT, 0x01)
            except AwccError:
                pass
        self.awcc.control(OP_ACTIVATE, pid)

    def set_power_mode(self, mode):
        import donanim
        if mode not in donanim.POWER_MODES:
            raise ValueError(ceviri.t("err.unknownPower"))
        pid = self.th.profile_for_mode(mode)
        if pid is None:
            raise donanim.Unsupported(ceviri.t("err.awNoProfile"))
        with self.lock:
            self._mode = mode
            if self._fan == FAN_AUTO:  # ozel fan modunda "Ozel" profil etkin; profil fan otomatige donunce gelir
                self._activate(pid)

    # ------------------------------------------------------------------ fan
    def fan_mode(self):
        if self._fan != FAN_AUTO:  # en cok fan modu icin dongu yok: dis degisiklik burada yakalanir
            self._sync()
        return self._fan

    def _base_profile(self):
        return self.th.profile_for_mode(self._mode if self._mode is not None else 3)

    def _set_boost(self, fan, value):
        value = int(max(0, min(100, round(value))))
        if self._boost.get(fan) != value:
            self.awcc.control(OP_SETBOOST, fan, value)
            self._boost[fan] = value

    def _to_auto(self):
        self._fan = FAN_AUTO
        for f in self.th.fans:  # takviyeyi sifirla: profil kendi tablosunu kullansin
            try:
                self._set_boost(f, 0)
            except AwccError:
                pass
        pid = self._base_profile()
        if pid is not None:
            self._activate(pid)

    def set_fan_mode(self, mode):
        with self.lock:
            self._stop_curve()
            if mode == FAN_AUTO:
                self._to_auto()
            elif mode == FAN_MAX:
                self.awcc.control(OP_ACTIVATE, P_CUSTOM)
                self._boost.clear()
                for f in self.th.fans:
                    self._set_boost(f, 100)
                self._fan = FAN_MAX
            elif mode == FAN_CUSTOM:
                if not self._curve:
                    raise ValueError(ceviri.t("err.fanMode"))
                self.awcc.control(OP_ACTIVATE, P_CUSTOM)
                self._boost.clear()
                self._fan = FAN_CUSTOM
                if not self._curve_step():
                    self._to_auto()
                    raise RuntimeError(ceviri.t("err.awNoTemp"))
                self._start_curve()
            else:
                raise ValueError(ceviri.t("err.fanMode"))

    def fan_default(self):
        pts = [tuple(p) for p in REFERENCE_CURVE]
        return {"count": len(self.th.fans), "cpu": pts, "gpu": pts, "reference": True}

    def set_fan_curve(self, cpu, gpu):
        """cpu/gpu: (T2, D2%, T3, D3%) ; Clevo ile ayni dogrulama, ilk nokta referans egriden."""
        import donanim
        t1, d1 = REFERENCE_CURVE[0]
        curve = {}
        for key, pts in (("cpu", cpu), ("gpu", gpu)):
            t2, d2, t3, d3 = donanim.validate_curve(pts, t1, d1)
            curve[key] = [(t1, d1), (t2, d2), (t3, d3), (100, 100)]
        with self.lock:
            self._curve = curve
            self.set_fan_mode(FAN_CUSTOM)

    # ------------------------------------------------------------------ yazilim egrisi
    def _curve_step(self):
        """Her fan icin kendi sensorlerinin en sicak degerine gore takviye. Sicaklik okunamazsa False."""
        cpu_t = self._temp(self.th.sensor(SENSOR_CPU))
        gpu_t = self._temp(self.th.sensor(SENSOR_GPU))
        if cpu_t is None and gpu_t is None:
            return False
        for f in self.th.fans:
            gpu = f in GPU_FANS
            temps = [self._temp(s) for s in self.th.fan_sensors.get(f) or []]
            temps = [x for x in temps if x is not None] or \
                [x for x in ((gpu_t if gpu else cpu_t), cpu_t) if x is not None]
            want = interpolate(self._curve["gpu" if gpu else "cpu"], max(temps))
            cur = self._boost.get(f)
            if cur is not None and want < cur:  # inis yumusak (saniyede en cok %3): fan pompalamasin
                want = max(want, cur - 3)
            self._set_boost(f, want)
        return True

    def _loop(self, stop):
        blind = 0
        while not stop.wait(self._period):
            with self.lock:
                if stop.is_set() or self._fan != FAN_CUSTOM:
                    return
                self._sync()  # Fn tusu ya da AWCC profili degistirdiyse egri durur, takviye yazilmaz
                if self._fan != FAN_CUSTOM:
                    return
                try:
                    ok = self._curve_step()
                except Exception:
                    ok = False
                blind = 0 if ok else blind + 1
                if blind >= 5:  # 5 sn sicaklik yok: fanlar denetleyicinin profiline
                    try:
                        self._to_auto()
                    except Exception:
                        pass
                    return

    def _start_curve(self):
        self._stop = threading.Event()
        threading.Thread(target=self._loop, args=(self._stop,), name="aw-fan", daemon=True).start()

    def _stop_curve(self):
        if self._stop is not None:
            self._stop.set()  # is parcacigi kilidi alinca durdugunu gorur ve cikar
            self._stop = None

    def shutdown(self):
        """Uygulama kapanirken: yazilim egrisi bu surecle olur, fanlar denetleyicinin profiline birakilir."""
        try:
            if self._fan != FAN_AUTO:
                self.set_fan_mode(FAN_AUTO)
        except Exception:
            pass

    # ------------------------------------------------------------------ klavye
    @property
    def kb_zones(self):
        """Bolgeli klavye: 4 (AWCC'deki soldan saga 4 bolge); isik yoksa 0. donanim.caps 'kb_zones' buradan okur."""
        return AlienFx.ZONES if self.kb is not None else 0

    def set_color(self, r, g, b):
        if self.kb is None:
            return 0
        return self.kb.set_color(r & 255, g & 255, b & 255)

    def set_zones(self, cols):
        if self.kb is None:
            return 0
        return self.kb.set_zones(cols)

    def describe(self):
        d = self.th.describe()
        d["keyboard"] = None if self.kb is None else {"api": self.kb.api, "vid": "0x%04X" % self.kb.info["vid"],
                                                      "pid": "0x%04X" % self.kb.info["pid"],
                                                      "zones": self.kb.zone_ids}
        return d


# --------------------------------------------------------------------------- algilama
def vendor_ok(manufacturer):
    m = (manufacturer or "").strip().lower()
    return "alienware" in m or m.startswith("dell")


def open_alienware():
    """(AlienwareEC, "") ya da (None, neden). Neden "" ise bilgisayar Alienware/Dell degildir."""
    import wmi_com
    try:
        cim = wmi_com.Wmi(r"root\cimv2")
        try:
            rows = cim.query("SELECT Manufacturer FROM Win32_ComputerSystem", ["Manufacturer"])
        finally:
            cim.close()
    except Exception as exc:
        return None, str(exc)
    if not rows or not vendor_ok(rows[0].get("Manufacturer")):
        return None, ""
    try:
        w = wmi_com.Wmi(r"root\WMI")
    except Exception as exc:
        return None, str(exc)
    try:
        import hid_win
    except Exception:
        hid_win = None
    try:
        return AlienwareEC(w, hid_win), ""
    except Exception as exc:
        w.close()
        # Sinif ya da ornek yok (WBEM_E_INVALID_CLASS / NOT_FOUND): AWCC'siz bir Dell (Latitude, XPS...), hata degil
        if isinstance(exc, NoAwcc) or any(c in str(exc) for c in ("0x80041010", "0x80041002")):
            return None, ""
        return None, str(exc)


def zone_probe(hid, wait=1.5, limit=32):
    """Bolge eslemesini bulmak icin: isik kimliklerini sirayla beyaz yakar (digerleri soluk kirmizi) ve kimligi
    yazar. Kullanici hangi kimligin klavyenin hangi bolgesini yaktigini not eder; sonuc alienfx.json'a girer."""
    import time
    info = AlienFx.find(hid)
    if not info:
        print("AlienFX klavye bulunamadi.")
        return
    kb = AlienFx(hid, info)
    print("AlienFX API v%d (%04X:%04X). Her kimlik %.1f sn beyaz yanar; hangi bolgenin yandigini not et." % (
        kb.api, info["vid"], info["pid"], wait))
    try:
        for i in range(min(kb.count, limit)):
            lights = dict.fromkeys(range(kb.count), (40, 0, 0))
            lights[i] = (255, 255, 255)
            kb._write(lights)
            print("  kimlik %d" % i)
            time.sleep(wait)
    finally:
        kb._write(dict.fromkeys(range(kb.count), (255, 255, 255)))
        kb.close()
    print('Sonucu ayar klasorundeki %s dosyasina yaz, ornegin: {"zones": [[0], [1], [2], [3]]}' % AlienFx.ZONE_FILE)


def main():
    """Alienware'de tani: python alienware.py (yonetici). Donanima yalnizca okuma komutlari gider.
    python alienware.py --bolge-testi: klavye isik kimliklerini sirayla yakar (bolge eslemesi icin)."""
    import json
    if "--bolge-testi" in sys.argv:
        import hid_win
        zone_probe(hid_win)
        return
    ec, err = open_alienware()
    if ec is None:
        print("Alienware AWCC arayuzu acilamadi:", err or "Alienware/Dell degil")
    else:
        print(json.dumps(ec.describe(), indent=2))
        print("etkin profil: 0x%02X" % (ec.awcc.info(OP_PROFILE) & 0xFF))
        print("olcum:", ec.status())
    try:
        import hid_win
        for d in hid_win.enumerate_devices(ALIENFX_VIDS):
            print("HID %04X:%04X kullanim %04X/%04X cikis %s ozellik %s" % (
                d["vid"], d["pid"], d.get("usage_page", 0), d.get("usage", 0), d.get("out_len"), d.get("feat_len")))
    except Exception as exc:
        print("HID listesi alinamadi:", exc)


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
