# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""Bu bilgisayarda hangi ozellik calisir.

Clevo tabanli her model ayni ozellikleri tasimaz: gomulu denetleyici (EC) ayni komut setini konusmayabilir,
bazi ozellikler (fan egrisi, RGB klavye, bazi guc modlari) hic olmayabilir. Bu yuzden her ozellik acilista
YALNIZCA OKUYARAK yoklanir; kaynak, orijinal Control Center'in de kullandigi BIOS ozellik bayraklaridir:

  ok       calisir
  partial  calisir ama bir kismi eksik (neden metninde yazar)
  no       yok; arayuzde gizlenir, profil adiminda "desteklenmiyor" yazar

Yoklama sonucu ayni zamanda bir guvenlik kapisidir: donanim.DCHU desteklenmeyen bir ozellik icin denetleyiciye
yazma komutunu HIC gondermez (Unsupported). Bilinmeyen bir denetleyiciye bilinmeyen bir komut yazmak, fanlari
durdurmak gibi tehlikeli sonuclar dogurabilir; okumak dogurmaz.

clevo(): Clevo denetleyicisinin ozellikleri (DCHU.support bunu kullanir).
detect(): tum bilgisayarin raporu (arayuzdeki 'Bu bilgisayarda destek' listesi); Clevo disi arka uclarda
denetleyici ozellikleri arka ucun kendi caps bayraklarindan gelir.
"""
import donanim as hw
from ceviri import t

OK, PARTIAL, NO = "ok", "partial", "no"

# (kimlik, bagli oldugu arayuz bolumu); sira arayuzdeki ve rapordaki siradir
FEATURES = [
    ("ec", "genel"),               # gomulu denetleyici ve yaniti
    ("fan_read", "fan"),           # fan devri, gorevi, denetleyici sicakliklari
    ("fan_control", "fan"),        # fabrika tablosu / maksimum
    ("fan_curve", "fan"),          # ozel fan egrisi
    ("power_mode", "performans"),  # denetleyici guc modu
    ("keyboard", "klavye"),        # klavye isigi
    ("fn_keys", "ayarlar"),        # Fn tuslari ve ekran bildirimi (yalnizca Clevo AcpiBridge)
    ("cpu_tuning", "performans"),  # Windows guc plani: turbo, EPP, frekans tavani
    ("gpu", "performans"),         # NVIDIA saat siniri ve olcumu
    ("refresh", "ses"),            # ekran yenileme hizi
    ("audio", "ses"),              # hoparlor ve mikrofon
]
EC_FEATURES = ("fan_read", "fan_control", "fan_curve", "power_mode", "keyboard")


def _item(state, why=""):
    return {"state": state, "why": why}


def usable(support, feature):
    return (support.get(feature) or {}).get("state") in (OK, PARTIAL)


def _plausible_temp(v):
    return isinstance(v, int) and 15 <= v <= 110


def _fan_table_ok(fd):
    """Fabrika fan tablosu (tampon 13) anlamli mi: sicakliklar artan ve makul, gorevler %0-100."""
    if not fd or not fd.get("cpu"):
        return False
    for key in ("cpu", "gpu"):
        pts = fd.get(key) or []
        temps = [p[0] for p in pts]
        duties = [p[1] for p in pts]
        if len(pts) != 4 or temps != sorted(temps) or len(set(temps)) != 4:
            return False
        if not (20 <= temps[0] <= 80) or any(not 0 <= d <= 100 for d in duties):
            return False
    return True


# ----------------------------------------------------------------------------- Clevo denetleyicisi
def _probe_ec(dchu):
    """Denetleyici gercekten yanit veriyor mu (yalnizca okuma)."""
    try:
        st = dchu.status()
    except Exception as exc:
        return _item(NO, t("sup.why.ecError", err=exc))
    if not _plausible_temp(st.get("cpu_temp")):
        # Kitaplik yuklendi ama tampon bos ya da anlamsiz: bu denetleyici Clevo komut setini konusmuyor
        return _item(NO, t("sup.why.ecSilent"))
    return _item(OK)


def _probe_keyboard(dchu):
    """Renk komutu (103) tek ve 3 bolgeli RGB'de calisir; tek renkli klavyede parlaklik seviyesi (komut 39).
    Cok bolgeli ve tus basina RGB ayri komutlar ister: bu surumde desteklenmez, rapor bunu soyler."""
    try:
        kind = dchu.keyboard_type() or "unknown"
    except Exception:
        kind = "unknown"
    if kind == "rgb":
        return _item(OK)
    if kind == "white":
        return _item(PARTIAL, t("sup.why.kbWhite"))
    if kind == "zones":
        return _item(NO, t("sup.why.kbZones"))
    if kind == "perkey":
        return _item(NO, t("sup.why.kbPerKey"))
    if kind == "none":
        return _item(NO, t("sup.why.kbNone"))
    return _item(PARTIAL, t("sup.why.kbUnknown"))


def _from_reads(dchu):
    """Bayraklar okunamadiysa: yalnizca denetleyicinin dondurdugu degerlerin akla yatkinligina bakilir."""
    out = {"fan_read": _item(OK)}
    try:
        mode = dchu.fan_mode()
    except Exception:
        mode = None
    out["fan_control"] = _item(OK) if mode is not None else _item(NO, t("sup.why.fanMode"))
    try:
        fd = dchu.fan_default()
    except Exception:
        fd = None
    out["fan_curve"] = _item(OK) if _fan_table_ok(fd) and fd.get("count") == 2 else _item(NO, t("sup.why.fanTable"))
    try:
        raw = dchu.read_app(1, 1, 1)[0]
    except Exception:
        raw = None
    out["power_mode"] = _item(OK) if raw in hw.POWER_MODES else _item(NO, t("sup.why.powerMode"))
    return out


def _from_flags(dchu, f):
    """BIOS'un bildirdigi ozellik bayraklari (orijinal Control Center'in kullandigi kaynak):
      WMI16  b0 guc modu, b7 fan uygulamasi       WMI122 b0 fan hizi, b4 ozel fan, b16 fan yok
      Pkg13  [12] fan sayisi, [43] b1 ozel egri yok
      Ex4(8) [17] alt 4 bit: desteklenen guc modlari (0 = hepsi), [20] b4 devir tabanli fan tablosu"""
    w16, w122, p13, ex = f["wmi16"], f["wmi122"], f["pkg13"], f["ex8"]
    out = {}
    if w122 >> 16 & 1:
        out["fan_read"] = _item(PARTIAL, t("sup.why.noFan"))
        out["fan_control"] = out["fan_curve"] = _item(NO, t("sup.why.noFan"))
    else:
        out["fan_read"] = _item(OK)
        if not (w16 >> 7 & 1 and w122 & 1):
            out["fan_control"] = out["fan_curve"] = _item(NO, t("sup.why.fanApp"))
        else:
            out["fan_control"] = _item(OK)
            count = p13[12]
            rpm_table = bool(ex and len(ex) > 20 and ex[20] >> 4 & 1)
            try:
                fd = dchu.fan_default()
            except Exception:
                fd = None
            if not w122 >> 4 & 1 or p13[43] >> 1 & 1:
                out["fan_curve"] = _item(NO, t("sup.why.noCustomFan"))
            elif rpm_table:
                out["fan_curve"] = _item(NO, t("sup.why.rpmFan"))
            elif count != 2:
                # egri tamponu yalnizca islemci + 1 kart fani icin dolduruluyor: 3. fana sifir yazmamak icin
                out["fan_curve"] = _item(NO, t("sup.why.fanCount", n=count))
            elif not _fan_table_ok(fd):
                out["fan_curve"] = _item(NO, t("sup.why.fanTable"))
            else:
                out["fan_curve"] = _item(OK)
    if not w16 & 1:
        out["power_mode"] = _item(NO, t("sup.why.powerMode"))
    else:
        mask = (ex[17] & 0x0F) if ex and len(ex) > 17 else 0
        modes = [m for m in hw.POWER_MODES if not mask or mask >> m & 1]
        missing = [m for m in hw.POWER_MODES if m not in modes]
        if not modes:
            item = _item(NO, t("sup.why.powerMode"))
        elif missing:
            item = _item(PARTIAL, t("sup.why.someModes", list=", ".join(t("power.%d" % m) for m in missing)))
        else:
            item = _item(OK)
        item["modes"] = modes
        out["power_mode"] = item
    return out


def clevo(dchu):
    """Clevo denetleyicisinin ozellikleri: {ec, fan_read, fan_control, fan_curve, power_mode, keyboard}.
    Hicbir sey yazmaz. Beklenmeyen bir hata 'yok' sayilir: suphede donanima yazilmaz."""
    out = {"ec": _probe_ec(dchu)}
    if out["ec"]["state"] != OK:
        for f in EC_FEATURES:
            out[f] = _item(NO, t("sup.why.noEc"))
        return out
    try:
        f = dchu.flags()
    except Exception:
        f = None
    try:
        out.update(_from_flags(dchu, f) if f else _from_reads(dchu))
    except Exception as exc:
        for k in ("fan_read", "fan_control", "fan_curve", "power_mode"):
            out[k] = _item(NO, t("sup.why.ecError", err=exc))
    out["keyboard"] = _probe_keyboard(dchu)
    return out


# ----------------------------------------------------------------------------- tum bilgisayar
def _from_caps(dev):
    """Clevo disi arka uclar (ya da denetleyici yok): arka ucun kendi bayraklari, nedeni arka ucun metni."""
    c = hw.caps(dev)
    why = getattr(dev, "reason", "") or getattr(dev, "message", "") or t("sup.why.noEc")
    out = {"ec": _item(OK) if getattr(dev, "available", False) else _item(NO, why)}

    def pick(ok, reason=why):
        return _item(OK) if ok else _item(NO, reason)
    out["fan_read"] = pick(c["fan_read"] or c["temp"])
    out["fan_control"] = pick(c["fan_max"])
    out["fan_curve"] = pick(c["fan_curve"])
    out["power_mode"] = pick(c["power"])
    out["keyboard"] = pick(c["kb"], getattr(dev, "kb_reason", "") or why)
    return out


def detect(dev, display=None, audio=None, gpu_names=None):
    """Tum ozellikler, arayuzdeki sirayla: [{"id", "state", "why", "section", "label"}]. Hicbir donanima yazmaz."""
    clevo_dev = getattr(dev, "kind", "") == "clevo" and callable(getattr(dev, "support", None))
    out = {k: dict(v) for k, v in dev.support().items()} if clevo_dev else _from_caps(dev)

    if clevo_dev:
        try:
            import fntus
            bridge = fntus.bridge_path()
        except Exception:
            bridge = None
        out["fn_keys"] = _item(OK) if bridge else _item(NO, t("sup.why.noBridge"))
    else:
        out["fn_keys"] = _item(NO, t("sup.why.fnOther"))

    out["cpu_tuning"] = _item(OK)  # Windows guc plani: her bilgisayarda var

    try:
        names = gpu_names if gpu_names is not None else [a[0] for a in hw.gpu_adapters() if a[1] == 0x10DE]
    except Exception:
        names = []
    if not names:
        out["gpu"] = _item(NO, t("sup.why.noNvidia"))
    elif not hw.tool_path("nvidia-smi"):
        out["gpu"] = _item(PARTIAL, t("sup.why.noSmi"))
    else:
        out["gpu"] = _item(OK)

    try:
        rates = display.rates() if display else []
    except Exception:
        rates = []
    out["refresh"] = _item(OK) if len(rates) > 1 else _item(NO, t("sup.why.oneRate"))

    try:
        a = audio.get() if audio else {}
    except Exception:
        a = {}
    if a.get("speaker") and a.get("mic"):
        out["audio"] = _item(OK)
    elif a.get("speaker") or a.get("mic"):
        out["audio"] = _item(PARTIAL, t("sup.why.noMic") if a.get("speaker") else t("sup.why.noSpeaker"))
    else:
        out["audio"] = _item(NO, t("sup.why.noAudio"))

    sections = dict(FEATURES)
    return [dict(out[k], id=k, section=sections[k], label=t("sup." + k)) for k, _ in FEATURES]
