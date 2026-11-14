# -*- coding: utf-8 -*-
"""Performans profilleri.

Her profil ayni anda alti kolu birden ceker:
  1. Gomulu denetleyici (EC) guc modu: islemcinin guc sinirini ve fabrika fan tablosunu belirler
  2. Fan egrisi: hangi sicaklikta ne kadar hava
  3. Islemci: turbo davranisi, enerji tercihi (EPP), P ve E cekirdek frekans tavani, cekirdek park, zamanlayici
  4. Ekran karti: saat tavani (NVIDIA, yonetici modu ister)
  5. Ekran yenileme hizi
  6. PCIe guc tasarrufu (ASPM) ve Windows guc modu katmani

Verimlilik mantigi: guc, frekansla dogrusal degil, gerilimle birlikte karesel artar. Islemcinin ve ekran
kartinin son %15-20'lik hiz dilimi en pahali dilimdir; tavani oradan cekmek isiyi ve fan sesini buyuk
oranda keser, hissedilen hizi az etkiler. Sessiz profillerin hepsi bunun uzerine kurulu.
"""
import ctypes
import threading

import donanim as hw

POWRPROF = ctypes.WinDLL("powrprof")
BALANCED = "381b4222-f694-41f0-9685-ff5bb260df2e"
SCHEME = "7d5c0c1e-4b3a-4c2e-9f1a-6b2d8e0c4a11"  # uygulamanin kendi guc plani
SCHEME_NAME = "Kendi Control Center"

SUB_PROC = "54533251-82be-4824-96c1-47b60b740d00"
SUB_PCIE = "501a4d13-42af-4429-9fd1-a8218c268e20"
S = {  # (alt grup, ayar)
    "boost": (SUB_PROC, "be337238-0d82-4146-a960-4f3749d470c7"),
    "epp": (SUB_PROC, "36687f9e-e3a5-4dbf-b1dc-15eb381c6863"),
    "epp1": (SUB_PROC, "36687f9e-e3a5-4dbf-b1dc-15eb381c6864"),
    "fmax": (SUB_PROC, "75b0ae3f-bce0-45a7-8c89-c9611c25e100"),   # verimlilik sinifi 0: E cekirdekler
    "fmax1": (SUB_PROC, "75b0ae3f-bce0-45a7-8c89-c9611c25e101"),  # verimlilik sinifi 1: P cekirdekler
    "park": (SUB_PROC, "0cc5b647-c1df-4637-891a-dec35c318583"),
    "park1": (SUB_PROC, "0cc5b647-c1df-4637-891a-dec35c318584"),
    "sched": (SUB_PROC, "93b8b6dc-0698-4d1c-9ee4-0644e900c85d"),
    "sched_short": (SUB_PROC, "bae08b81-2d5e-4688-ad6a-13243356654b"),
    "aspm": (SUB_PCIE, "ee12f906-d277-404b-b6da-e5fa1a576df5"),
}
OVERLAY = {"eff": "961cc777-2547-4f9d-8174-7d86181b8a7a", "bal": "00000000-0000-0000-0000-000000000000",
           "perf": "ded574b5-45a0-4f42-8737-46345c09c238"}
BOOST_TXT = {0: "kapalı", 1: "açık", 2: "agresif", 3: "verimli", 4: "verimli agresif"}
SCHED_TXT = {0: "tüm çekirdekler", 1: "yalnız P", 2: "P öncelikli", 3: "yalnız E", 4: "E öncelikli", 5: "otomatik"}

# fan: ("auto",) | ("max",) | ("curve", (T2, D2, T3, D3) islemci, (T2, D2, T3, D3) ekran karti)
# cpu.fmax_p / fmax_e: MHz, 0 = sinir yok.  gpu: (alt, ust) MHz ya da None = kilit yok
PROFILES = [
    {
        "id": "tam_sessiz", "name": "Tam Sessiz", "tag": "Fan en alt devirde, duyulmaz",
        "desc": "Turbo kapalı, denetleyici sessiz modda (işlemci ~15 W'ta kilitli). Fanlar 70 °C'ye kadar en alt "
                "devirde. Ekran kartı 600 MHz'e kilitli, ekran 60 Hz. Ölçüm, 12 iş parçacığı tam yükte: 15 W, "
                "59 °C, fan %29. Ekran kartı tam yükte: 600 MHz, 19 W (serbestken 65 W). Okuma, yazı, film, gece.",
        "ec": 0, "fan": ("curve", (70, 30, 84, 50), (70, 30, 84, 50)),
        "cpu": {"boost": 0, "epp": 100, "fmax_p": 0, "fmax_e": 0, "sched": 4, "sched_short": 4, "park": None},
        "gpu": (210, 600), "refresh": "min", "aspm": 2, "overlay": "eff",
    },
    {
        "id": "sessiz_kullanim", "name": "Sessiz Kullanım", "tag": "Hızlı tepki, düşük ses",
        "desc": "Turbo açık ama P çekirdekler 2,4 GHz, E çekirdekler 1,6 GHz tavanında: hızın en pahalı dilimi "
                "kesik. Tam Sessiz'e göre iki kat hızlı, hâlâ sakin. Ölçüm, tam yükte: 24 W, 69 °C, fan %39. "
                "Ekran kartı 1100 MHz tavanında: tam yükte 24 W. Tarayıcı, kod, ofis, toplantı, hafif oyun.",
        "ec": 3, "fan": ("curve", (64, 32, 80, 55), (64, 32, 80, 55)),
        "cpu": {"boost": 3, "epp": 60, "fmax_p": 2400, "fmax_e": 1600, "sched": 5, "sched_short": 4, "park": None},
        "gpu": (210, 1100), "refresh": "max", "aspm": 2, "overlay": "bal",
    },
    {
        "id": "sessiz_oyun", "name": "Sessiz Oyun", "tag": "Oynanabilir FPS, kontrollü ses",
        "desc": "Ekran kartı 1500 MHz'e kilitli: Ampere'nin verimli bölgesi, gücün büyük kısmı kesilir, FPS az "
                "düşer. İşlemci P 2,8 / E 2,0 GHz tavanında, oyun iş parçacıkları P çekirdeklere. Ölçüm, işlemci "
                "tam yükte: 32 W, 73 °C, fan %50 (tavansız hali 45 W ve fan %78 idi). Ekran kartı tam yükte: "
                "34 W, serbest halin (65 W) yarısı; saat %78'de kalır.",
        "ec": 3, "fan": ("curve", (62, 38, 80, 60), (62, 38, 80, 60)),
        "cpu": {"boost": 4, "epp": 40, "fmax_p": 2800, "fmax_e": 2000, "sched": 2, "sched_short": 5, "park": None},
        "gpu": (210, 1500), "refresh": "max", "aspm": 1, "overlay": "bal",
    },
    {
        "id": "performans", "name": "Performans", "tag": "Tam güç, fabrika soğutması",
        "desc": "Denetleyici performans modunda (en yüksek güç sınırı), tavan yok, turbo agresif, ekran kartı "
                "serbest. Fanları denetleyicinin kendi performans tablosu yönetir. Ölçüm, tam yükte: 61 W "
                "(ilk saniyelerde 74 W), 98 °C, fan %100.",
        "ec": 2, "fan": ("auto",),
        "cpu": {"boost": 2, "epp": 15, "fmax_p": 0, "fmax_e": 0, "sched": 5, "sched_short": 5, "park": None},
        "gpu": None, "refresh": "max", "aspm": 1, "overlay": "perf",
    },
    {
        "id": "ultra", "name": "Ultra Performans", "tag": "Ses umurunda değil, en yüksek FPS",
        "desc": "Performans'ın üstüne: fanlar 50 °C'de devreye girip 62 °C'de %90'a çıkar, böylece oyunda "
                "ekran kartı ısısı birikmeden atılır. EPP 0, çekirdek park kapalı, PCIe tasarrufu kapalı: en düşük "
                "gecikme, boştayken bile yüksek güç. Dürüst ölçüm: işlemci ve kart birlikte tam yükteyken "
                "Performans'la aynı (kart ~70 W / 1960 MHz, işlemci ~32 W); bu kasanın tavanı. Fark yalnızca "
                "gecikme ayarları ve erken devreye giren fan. Yalnızca fişte; pile geçince Performans'a iner.",
        "ec": 2, "fan": ("curve", (50, 60, 62, 90), (50, 60, 62, 90)),
        "cpu": {"boost": 2, "epp": 0, "fmax_p": 0, "fmax_e": 0, "sched": 2, "sched_short": 2, "park": 100},
        "gpu": None, "refresh": "max", "aspm": 0, "overlay": "perf", "ac_only": True,
    },
]
BY_ID = {p["id"]: p for p in PROFILES}
DEFAULTS = {"profile": "", "on_battery": "", "on_ac": "", "refresh": True}


# ----------------------------------------------------------------------------- guc plani
def _g(s):
    return hw.guid(s)


def _read(scheme, key, ac=True):
    sub, setting = S[key]
    v = ctypes.c_ulong()
    fn = POWRPROF.PowerReadACValueIndex if ac else POWRPROF.PowerReadDCValueIndex
    r = fn(None, ctypes.byref(_g(scheme)), ctypes.byref(_g(sub)), ctypes.byref(_g(setting)), ctypes.byref(v))
    return v.value if r == 0 else None


def _write(key, value):
    sub, setting = S[key]
    args = (None, ctypes.byref(_g(SCHEME)), ctypes.byref(_g(sub)), ctypes.byref(_g(setting)), ctypes.c_ulong(value))
    r1 = POWRPROF.PowerWriteACValueIndex(*args)
    r2 = POWRPROF.PowerWriteDCValueIndex(*args)
    return r1 == 0 and r2 == 0


def ensure_scheme():
    """Uygulamanin kendi guc planini (Dengeli'nin kopyasi) yoksa olusturur."""
    rc, _ = hw.run(["powercfg", "/query", SCHEME, SUB_PROC, S["boost"][1]])
    if rc != 0:
        rc, out = hw.run(["powercfg", "/duplicatescheme", BALANCED, SCHEME])
        if rc != 0:
            raise RuntimeError("Güç planı oluşturulamadı: " + out)
        hw.run(["powercfg", "/changename", SCHEME, SCHEME_NAME, "Kendi Control Center profilleri"])


def active_scheme():
    p = ctypes.POINTER(hw.GUID)()
    if POWRPROF.PowerGetActiveScheme(None, ctypes.byref(p)) != 0:
        return ""
    g = p.contents
    s = "%08x-%04x-%04x-%s-%s" % (g.d1, g.d2, g.d3, bytes(g.d4[:2]).hex(), bytes(g.d4[2:]).hex())
    ctypes.windll.kernel32.LocalFree(p)
    return s


# ----------------------------------------------------------------------------- yonetici
class Manager:
    def __init__(self, dchu, sensors, cfg, save):
        self.dchu = dchu
        self.sensors = sensors
        self.cfg = cfg  # cfg["cc"] sozlugu, kaydetme save() ile
        self.save = save
        self.display = hw.Display()
        self.lock = threading.Lock()
        self.report = []
        self.applied = ""
        self.guard = ""       # bekci devredeyse aciklama
        self._hot = 0
        self._cool = 0
        self._last_ac = None
        self._gpu_locked = False
        self.defaults = {k: _read(BALANCED, k) for k in ("park", "park1")}
        sensors.listeners.append(self._tick)

    # ------------------------------------------------------------------ bilgi
    def describe(self, p):
        """Arayuzde gosterilecek somut ayar satirlari."""
        c = p["cpu"]
        fan = p["fan"]
        if fan[0] == "curve":
            fan_txt = "%d °C'de %%%d, %d °C'de %%%d" % fan[1]
        else:
            fan_txt = {"auto": "denetleyici tablosu", "max": "sürekli maksimum"}[fan[0]]
        caps = "sınır yok"
        if c["boost"] == 0:
            caps = "turbo kapalı, taban hız"
        elif c["fmax_p"] or c["fmax_e"]:
            caps = "P %.1f GHz, E %.1f GHz" % (c["fmax_p"] / 1000.0, c["fmax_e"] / 1000.0)
        return [
            ("Güç modu", hw.POWER_MODES[p["ec"]]),
            ("İşlemci tavanı", caps),
            ("Turbo / EPP", "%s / %d" % (BOOST_TXT[c["boost"]], c["epp"])),
            ("Zamanlayıcı", SCHED_TXT[c["sched"]]),
            ("Ekran kartı", "%d MHz tavan" % p["gpu"][1] if p["gpu"] else "serbest"),
            ("Fan", fan_txt),
            ("Ekran", "60 Hz" if p["refresh"] == "min" else "en yüksek Hz"),
        ]

    def public(self):
        return [{"id": p["id"], "name": p["name"], "tag": p["tag"], "desc": p["desc"],
                 "ac_only": bool(p.get("ac_only")), "rows": self.describe(p),
                 "fan": [list(p["fan"][1]), list(p["fan"][2])] if p["fan"][0] == "curve" else p["fan"][0]}
                for p in PROFILES]

    def status(self):
        return {"profile": self.applied, "report": self.report, "guard": self.guard,
                "power_mode": self.dchu.power_mode(), "fan_mode": self.dchu.fan_mode(),
                "scheme_active": active_scheme() == SCHEME, "admin": hw.is_admin(), "rules": self.cfg}

    # ------------------------------------------------------------------ uygula
    def apply(self, pid, reason="Elle"):
        p = BY_ID.get(pid)
        if not p:
            raise ValueError("bilinmeyen profil")
        on_ac = hw.power_status()["ac"]
        if p.get("ac_only") and not on_ac:
            p = BY_ID["performans"]
        with self.lock:
            rep = []

            def step(name, fn):
                try:
                    msg = fn()
                    rep.append({"step": name, "ok": True, "msg": msg or ""})
                except Exception as exc:
                    rep.append({"step": name, "ok": False, "msg": str(exc)})

            step("Denetleyici güç modu", lambda: self._ec(p))
            step("Fan", lambda: self._fan(p))
            step("İşlemci", lambda: self._cpu(p))
            step("Ekran kartı", lambda: self._gpu(p))
            if self.cfg.get("refresh", True):
                step("Ekran", lambda: self._refresh(p))
            if p["id"] != pid:
                rep.insert(0, {"step": "Not", "ok": True, "msg": "Pildesin: Ultra yerine Performans uygulandı."})
            rep.insert(0, {"step": "Neden", "ok": True, "msg": reason})
            self.applied = p["id"]
            self.guard = ""
            self._hot = self._cool = 0
            self.report = rep
            self.cfg["profile"] = pid
            self.save()
            return rep

    def _ec(self, p):
        self.dchu.set_power_mode(p["ec"])
        return hw.POWER_MODES[p["ec"]]

    def _fan(self, p):
        kind = p["fan"][0]
        if kind == "curve":
            self.dchu.set_fan_curve(p["fan"][1], p["fan"][2])
            return "özel eğri"
        self.dchu.set_fan_mode(hw.FAN_MAX if kind == "max" else hw.FAN_AUTO)
        return "otomatik" if kind == "auto" else "maksimum"

    def _cpu(self, p):
        c = p["cpu"]
        ensure_scheme()
        vals = {"boost": c["boost"], "epp": c["epp"], "epp1": c["epp"], "fmax": c["fmax_e"], "fmax1": c["fmax_p"],
                "sched": c["sched"], "sched_short": c["sched_short"], "aspm": p["aspm"]}
        park = c["park"]
        vals["park"] = park if park is not None else (self.defaults.get("park") or 10)
        vals["park1"] = park if park is not None else (self.defaults.get("park1") or 10)
        bad = [k for k, v in vals.items() if not _write(k, v)]
        if POWRPROF.PowerSetActiveScheme(None, ctypes.byref(_g(SCHEME))) != 0:
            raise RuntimeError("güç planı etkinleştirilemedi")
        try:
            POWRPROF.PowerSetActiveOverlayScheme(ctypes.byref(_g(OVERLAY[p["overlay"]])))
        except AttributeError:
            pass
        if bad:
            raise RuntimeError("yazılamayan ayarlar: " + ", ".join(bad))
        return "turbo %s, EPP %d" % (BOOST_TXT[c["boost"]], c["epp"])

    def _gpu(self, p):
        if not hw.is_admin():
            if p["gpu"]:
                raise RuntimeError("saat kilidi için yönetici modu gerekli (Ayarlar)")
            return "serbest"
        # Not: guc sinirini 75 W'a cikarmak (nvidia-smi -pl) denendi, olculebilir fark yok: Dynamic Boost
        # karta zaten 74 W'a kadar pay veriyor (2026-11-13, kart ve kart+islemci yukunde olculdu).
        if p["gpu"]:
            rc, out = hw.nvidia_lock_clocks(*p["gpu"])
            if rc != 0:
                raise RuntimeError(out[:160])
            self._gpu_locked = True
            return "%d MHz tavan" % p["gpu"][1]
        rc, out = hw.nvidia_lock_clocks(0, None)
        self._gpu_locked = False
        if rc != 0:
            raise RuntimeError(out[:160])
        return "serbest"

    def _refresh(self, p):
        rates = self.display.rates()
        if not rates:
            return "değişmedi"
        hz = rates[0] if p["refresh"] == "min" else rates[-1]
        if not self.display.set_rate(hz):
            raise RuntimeError("%d Hz ayarlanamadı" % hz)
        return "%d Hz" % hz

    # ------------------------------------------------------------------ bekci
    def _tick(self, s, dt):
        """Sensor her olcumde cagirir: uykudan donus, fis/pil kurali ve isi korumasi."""
        if dt > 15 and self.applied:  # uyku veya hazirda bekletmeden dondu: denetleyici ayarlari sifirlanmis olabilir
            threading.Thread(target=self.apply, args=(self.applied, "Uykudan dönüş"), daemon=True).start()
        ac = (s.get("battery") or {}).get("ac")
        if self._last_ac is not None and ac != self._last_ac:
            target = self.cfg.get("on_ac" if ac else "on_battery") or ""
            cur = BY_ID.get(self.applied)
            if not target and not ac and cur and cur.get("ac_only"):
                target = "performans"
            if target:
                why = "Fişe takıldı" if ac else "Pile geçildi"
                threading.Thread(target=self.apply, args=(target, why), daemon=True).start()
        self._last_ac = ac
        p = BY_ID.get(self.applied)
        if not p or p["fan"][0] != "curve":
            return
        hot = s.get("cpu_temp", 0) >= 93 or s.get("gpu_temp", 0) >= 87
        if hot:
            self._hot += 1
            self._cool = 0
            if self._hot == 5 and not self.guard:
                self.dchu.set_fan_mode(hw.FAN_AUTO)
                self.guard = "Sıcaklık yüksek: fanlar geçici olarak denetleyiciye bırakıldı."
        else:
            self._hot = 0
            if self.guard and s.get("cpu_temp", 0) < 80 and s.get("gpu_temp", 0) < 75:
                self._cool += 1
                if self._cool >= 30:
                    self.dchu.set_fan_curve(p["fan"][1], p["fan"][2])
                    self.guard = ""
                    self._cool = 0

    def factory(self):
        """Fabrika durumuna don: Eglence modu, fanlar denetleyicide, Dengeli plan, ekran karti serbest.
        Profiller uygulama kapaliyken de guvenlidir (egriyi denetleyici calistirir, 100 C'de %100);
        bu yuzden kapanista otomatik cagrilmaz, yalnizca istenince."""
        with self.lock:
            rep = []
            for name, fn in (("Denetleyici güç modu", lambda: self.dchu.set_power_mode(3)),
                             ("Fan", lambda: self.dchu.set_fan_mode(hw.FAN_AUTO)),
                             ("Güç planı", lambda: POWRPROF.PowerSetActiveScheme(None, ctypes.byref(_g(BALANCED)))),
                             ("Ekran kartı", lambda: hw.is_admin() and hw.nvidia_lock_clocks(0, None))):
                try:
                    fn()
                    rep.append({"step": name, "ok": True, "msg": "fabrika"})
                except Exception as exc:
                    rep.append({"step": name, "ok": False, "msg": str(exc)})
            self.applied = ""
            self.guard = ""
            self.cfg["profile"] = ""
            self.save()
            self.report = rep
            return rep
