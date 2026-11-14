# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
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

import ceviri
import donanim as hw
from ceviri import t

POWRPROF = ctypes.WinDLL("powrprof")
BALANCED = "381b4222-f694-41f0-9685-ff5bb260df2e"
SCHEME = "7d5c0c1e-4b3a-4c2e-9f1a-6b2d8e0c4a11"  # uygulamanin kendi guc plani
SCHEME_NAME = "FCUK Control Center"

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
    # islemci durumu (%): en yuksek / en dusuk; "1" ekli olanlar melez islemcide P cekirdekler icin
    "pmax": (SUB_PROC, "bc5038f7-23e0-4960-96da-33abaf5935ec"),
    "pmax1": (SUB_PROC, "bc5038f7-23e0-4960-96da-33abaf5935ed"),
    "pmin": (SUB_PROC, "893dee8e-2bef-41e0-89c6-b55d0929964c"),
    "pmin1": (SUB_PROC, "893dee8e-2bef-41e0-89c6-b55d0929964d"),
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


def name(pid):
    """Profilin etkin dildeki adi (PROFILES'taki ad Turkce kaynaktir)."""
    return t("prof." + pid)
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
            raise RuntimeError(t("err.schemeCreate", out=out))
        hw.run(["powercfg", "/changename", SCHEME, SCHEME_NAME, "FCUK Control Center profilleri"])


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
    def __init__(self, dchu, sensors, cfg, save, notify=None):
        self.notify = notify or (lambda text: None)
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
        self._blind = 0       # ust uste kac olcumde sicaklik okunamadi
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
            t1, d1, t2, d2 = fan[1]
            fan_txt = t("val.fanCurve", t1=t1, d1=ceviri.pct(d1), t2=t2, d2=ceviri.pct(d2))
        else:
            fan_txt = t({"auto": "val.fanTable", "max": "val.fanAlwaysMax"}[fan[0]])
        caps = t("val.capNone")
        if c["boost"] == 0:
            caps = t("val.capTurboOff")
        elif c["fmax_p"] or c["fmax_e"]:
            caps = t("val.capPE", p=ceviri.num(c["fmax_p"] / 1000.0, 1), e=ceviri.num(c["fmax_e"] / 1000.0, 1))
        cap = hw.caps(self.dchu)
        ec = cap["power"]
        msi = getattr(self.dchu, "kind", "") == "msi"
        if fan[0] == "curve" and not cap["fan_curve"] and cap["fan_max"] and getattr(self.dchu, "vendor", "") == "hp":
            fan_txt = t("val.hpFanTable")  # ozel egri yok (HP): fanlar BIOS tablosunda
        elif not (cap["fan_curve"] or cap["fan_max"]):
            fan_txt = t("val.unsupported")
        elif msi and fan[0] == "curve":  # MSI'da ozel egri yok: sessiz egri Silent, digerleri Auto fan modu
            quiet = fan[1][3] <= 60 and fan[2][3] <= 60
            fan_txt = t("msi.fan." + ("silent" if quiet and "silent" in self.dchu.conf["fan"] else "auto"))
        elif fan[0] == "curve" and not getattr(self.dchu, "fan_curve_ok", True):
            # egri yok (Acer): fanlari secilen guc modunun kendi tablosu yonetir
            fan_txt = t("val.fanByMode") if getattr(self.dchu, "fan_ok", True) else t("val.unsupported")
        power_txt = ((self._msi_power(p["ec"]) if msi else hw.power_text(self.dchu, p["ec"])) if ec
                     else t("val.unsupported"))
        if ec and hasattr(self.dchu, "profile_power_label"):
            power_txt = self.dchu.profile_power_label(p)
        gpu_txt = t("val.gpuCap", mhz=p["gpu"][1]) if p["gpu"] else t("val.gpuFree")
        if not self.sensors.gpu_name:
            gpu_txt = t("val.unsupported")
        return [
            (t("row.powerMode"), power_txt),
            (t("row.cpuCap"), caps),
            (t("row.turboEpp"), "%s / %d" % (t("boost.%d" % c["boost"]), c["epp"])),
            (t("row.sched"), t("sched.%d" % c["sched"])),
            (t("row.gpu"), gpu_txt),
            (t("row.fan"), fan_txt),
            (t("row.display"), t("val.disp60") if p["refresh"] == "min" else t("val.dispMax")),
        ]

    def _msi_power(self, code):
        """Clevo guc modu kodunun MSI'da karsiligi olan shift modu adi."""
        import msi
        modes = (self.dchu.conf or {}).get("shift") or {}
        name = next((n for n in msi.POWER_TO_SHIFT.get(code, ()) if n in modes), None)
        return t("msi.shift." + name) if name else t("val.unsupported")

    def public(self):
        return [{"id": p["id"], "name": name(p["id"]), "tag": t("prof.%s.tag" % p["id"]),
                 "desc": t("prof.%s.desc" % p["id"]),
                 "ac_only": bool(p.get("ac_only")), "rows": self.describe(p),
                 "fan": [list(p["fan"][1]), list(p["fan"][2])] if p["fan"][0] == "curve" else p["fan"][0]}
                for p in PROFILES]

    def status(self):
        return {"profile": self.applied, "report": self.report, "guard": self.guard,
                "power_mode": self.dchu.power_mode(), "fan_mode": self.dchu.fan_mode(),
                "power_name": getattr(self.dchu, "power_name", lambda: None)(),  # Acer profil adi
                "scheme_active": active_scheme() == SCHEME, "admin": hw.is_admin(), "rules": self.cfg}

    # ------------------------------------------------------------------ uygula
    def apply(self, pid, reason="reason.manual"):
        """reason: ceviri anahtari (reason.*); rapora o anki dilde yazilir."""
        p = BY_ID.get(pid)
        if not p:
            raise ValueError(t("err.unknownProfile"))
        on_ac = hw.power_status()["ac"]
        if p.get("ac_only") and not on_ac:
            p = BY_ID["performans"]
        with self.lock:
            rep = []

            def step(name, fn):
                try:
                    msg = fn()
                    rep.append({"step": name, "ok": True, "msg": msg or ""})
                except hw.Unsupported as exc:  # bu bilgisayarda olmayan ozellik: hata degil, atlandi
                    rep.append({"step": name, "ok": True, "skip": True, "msg": str(exc)})
                except Exception as exc:
                    rep.append({"step": name, "ok": False, "msg": str(exc)})

            step(t("step.ec"), lambda: self._ec(p))
            step(t("step.fan"), lambda: self._fan(p))
            step(t("step.cpu"), lambda: self._cpu(p))
            step(t("step.gpu"), lambda: self._gpu(p))
            if self.cfg.get("refresh", True):
                step(t("step.display"), lambda: self._refresh(p))
            if p["id"] != pid:
                rep.insert(0, {"step": t("step.note"), "ok": True, "msg": t("msg.batteryUltra")})
            rep.insert(0, {"step": t("step.reason"), "ok": True, "msg": t(reason)})
            self.applied = p["id"]
            self.guard = ""
            self._hot = self._cool = self._blind = 0
            self.report = rep
            self.cfg["profile"] = pid
            self.save()
            return rep

    def _ec(self, p):
        if hasattr(self.dchu, "apply_profile_power"):  # Acer: profil kendi guc moduna eslenir
            return self.dchu.apply_profile_power(p, hw.power_status()["ac"])
        msg = self.dchu.set_power_mode(p["ec"])
        return msg if isinstance(msg, str) and msg else t("power.%d" % p["ec"])

    def _fan(self, p):
        kind = p["fan"][0]
        if kind == "curve" and not getattr(self.dchu, "fan_curve_ok", True):
            # Egri desteklenmiyor (Acer): fanlar guc modunun fabrika tablosunda; elle hiz da kalkar
            self.dchu.set_fan_mode(hw.FAN_AUTO)
            return t("msg.fanByMode")
        if kind == "curve":
            if not hw.caps(self.dchu)["fan_curve"] and getattr(self.dchu, "vendor", "") == "hp":
                # Ozel egri yok (HP BIOS'u): fanlar uretici tablosunda kalir; NullDCHU'da bu da Unsupported verir
                self.dchu.set_fan_mode(hw.FAN_AUTO)
                return t("msg.hpCurveAuto")
            msg = self.dchu.set_fan_curve(p["fan"][1], p["fan"][2])
            return msg if isinstance(msg, str) else t("msg.customCurve")  # MSI: en yakin fan moduna cevrilir
        self.dchu.set_fan_mode(hw.FAN_MAX if kind == "max" else hw.FAN_AUTO)
        return t("msg.auto") if kind == "auto" else t("msg.max")

    def _cpu(self, p):
        c = p["cpu"]
        ensure_scheme()
        vals = {"boost": c["boost"], "epp": c["epp"], "epp1": c["epp"], "fmax": c["fmax_e"], "fmax1": c["fmax_p"],
                "sched": c["sched"], "sched_short": c["sched_short"], "aspm": p["aspm"]}
        park = c["park"]
        vals["park"] = park if park is not None else (self.defaults.get("park") or 10)
        vals["park1"] = park if park is not None else (self.defaults.get("park1") or 10)
        # Islemci sayfasinda elle degistirilmis olabilecek durum sinirlari: profil her zaman tam araligi acar
        vals.update({"pmax": 100, "pmax1": 100, "pmin": 5, "pmin1": 5})
        optional = {"pmax1", "pmin1"}  # melez olmayan islemcide bu ayarlar yok
        bad = [k for k, v in vals.items() if not _write(k, v) and k not in optional]
        cur = active_scheme()
        if cur and cur != SCHEME:  # kullanicinin (ya da ureticinin) plani: "Fabrika" buna geri doner
            self.cfg["prev_scheme"] = cur
        if POWRPROF.PowerSetActiveScheme(None, ctypes.byref(_g(SCHEME))) != 0:
            raise RuntimeError(t("err.schemeActivate"))
        try:
            POWRPROF.PowerSetActiveOverlayScheme(ctypes.byref(_g(OVERLAY[p["overlay"]])))
        except AttributeError:
            pass
        if bad:
            raise RuntimeError(t("err.settings", list=", ".join(bad)))
        return t("msg.cpuDone", boost=t("boost.%d" % c["boost"]), epp=c["epp"])

    def _gpu(self, p):
        if not self.sensors.gpu_name:  # NVIDIA kart yok: nvidia-smi hic cagrilmaz
            raise hw.Unsupported(t("err.noNvidia"))
        if not hw.is_admin():
            if p["gpu"]:
                raise RuntimeError(t("err.gpuAdmin"))
            return t("val.gpuFree")
        # Not: guc sinirini 75 W'a cikarmak (nvidia-smi -pl) denendi, olculebilir fark yok: Dynamic Boost
        # karta zaten 74 W'a kadar pay veriyor (2026-11-13, kart ve kart+islemci yukunde olculdu).
        if p["gpu"]:
            rc, out = hw.nvidia_lock_clocks(*p["gpu"])
            if rc != 0:
                raise RuntimeError(out[:160])
            self._gpu_locked = True
            return t("val.gpuCap", mhz=p["gpu"][1])
        rc, out = hw.nvidia_lock_clocks(0, None)
        self._gpu_locked = False
        if rc != 0:
            raise RuntimeError(out[:160])
        return t("val.gpuFree")

    def _refresh(self, p):
        rates = self.display.rates()
        if not rates:
            return t("msg.unchanged")
        hz = rates[0] if p["refresh"] == "min" else rates[-1]
        if not self.display.set_rate(hz):
            raise RuntimeError(t("err.hz", hz=hz))
        return "%d Hz" % hz

    # ------------------------------------------------------------------ bekci
    def _tick(self, s, dt):
        """Sensor her olcumde cagirir: uykudan donus, fis/pil kurali ve isi korumasi."""
        if dt > 15 and self.applied:  # uyku veya hazirda bekletmeden dondu: denetleyici ayarlari sifirlanmis olabilir
            threading.Thread(target=self.apply, args=(self.applied, "reason.wake"), daemon=True).start()
        ac = (s.get("battery") or {}).get("ac")
        if self._last_ac is not None and ac != self._last_ac:
            target = self.cfg.get("on_ac" if ac else "on_battery") or ""
            cur = BY_ID.get(self.applied)
            if not target and not ac and cur and cur.get("ac_only"):
                target = "performans"
            if target:
                why = "reason.ac" if ac else "reason.battery"
                threading.Thread(target=self.apply, args=(target, why), daemon=True).start()
        self._last_ac = ac
        guard = getattr(self.dchu, "custom_guard", None)
        if guard:  # Acer elle fan hizi: kendi isi korumasi
            msg = guard(s)
            if msg:
                self.guard = msg
                self.notify(msg)
        p = BY_ID.get(self.applied)
        if not p or p["fan"][0] != "curve" or not hw.caps(self.dchu)["fan_curve"]:
            return
        # Profil uygulanirken (kilit dolu) bekci dokunmaz: apply() sonunda bekci durumunu zaten sifirlar.
        if not self.lock.acquire(blocking=False):
            return
        try:
            self._guard_step(s, p)
        finally:
            self.lock.release()

    @staticmethod
    def _temp(s, key):
        """Gecerli sicaklik ya da None. Denetleyici okunamazsa 0 dondurebilir: 0 'soguk' degil 'bilinmiyor'dur."""
        v = s.get(key)
        if s.get("dchu_error") or s.get("sensor_error") or not isinstance(v, (int, float)) or v <= 0:
            return None
        return v

    def _guard_step(self, s, p):
        # GPU uykudayken denetleyici GPU sicakligini 0 verebilir; bu yuzden "bilinmiyor" karari islemciye gore.
        cpu, gpu = self._temp(s, "cpu_temp"), self._temp(s, "gpu_temp") or 0
        if cpu is None:
            # Sicaklik bilinmeden sessiz egride kalmak tehlikeli: 5 sn sonra fanlar denetleyicinin tablosuna
            self._blind += 1
            self._cool = 0
            if self._blind == 5 and not self.guard:
                self.dchu.set_fan_mode(hw.FAN_AUTO)
                self.guard = "Sıcaklık okunamıyor: fanlar güvenlik için denetleyiciye bırakıldı."
                self.notify(self.guard)
            return
        self._blind = 0
        hot = cpu >= 93 or gpu >= 87
        if hot:
            self._hot += 1
            self._cool = 0
            if self._hot == 5 and not self.guard:
                self.dchu.set_fan_mode(hw.FAN_AUTO)
                self.guard = t("guard.hot")
        else:
            self._hot = 0
            if self.guard and cpu < 80 and gpu < 75:
                self._cool += 1
                if self._cool >= 30:
                    self.dchu.set_fan_curve(p["fan"][1], p["fan"][2])
                    self.guard = ""
                    self._cool = 0

    def _restore_scheme(self):
        """Profilden onceki guc planina doner (silinmisse Dengeli). Baska bir Control Center'in plani da olabilir."""
        for g in (self.cfg.get("prev_scheme"), BALANCED):
            if g and POWRPROF.PowerSetActiveScheme(None, ctypes.byref(_g(g))) == 0:
                return
        raise RuntimeError(t("err.schemeActivate"))

    def factory(self):
        """Fabrika durumuna don: Eglence modu, fanlar denetleyicide, Dengeli plan, ekran karti serbest.
        Profiller uygulama kapaliyken de guvenlidir (egriyi denetleyici calistirir, 100 C'de %100);
        bu yuzden kapanista otomatik cagrilmaz, yalnizca istenince."""
        with self.lock:
            rep = []
            for key, fn in (("step.ec", lambda: self.dchu.set_power_mode(3)),
                            ("step.fan", lambda: self.dchu.set_fan_mode(hw.FAN_AUTO)),
                            ("step.scheme", self._restore_scheme),
                            ("step.gpu", lambda: self.sensors.gpu_name and hw.is_admin()
                             and hw.nvidia_lock_clocks(0, None))):
                try:
                    fn()
                    rep.append({"step": t(key), "ok": True, "msg": t("msg.factory")})
                except hw.Unsupported as exc:
                    rep.append({"step": t(key), "ok": True, "skip": True, "msg": str(exc)})
                except Exception as exc:
                    rep.append({"step": t(key), "ok": False, "msg": str(exc)})
            self.applied = ""
            self.guard = ""
            self.cfg["profile"] = ""
            self.save()
            self.report = rep
            return rep
