# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""Islemci ayarlari: modele gore yalnizca o islemcide gercekten etkisi olan kollar gosterilir.

Tum ayarlar Windows guc planiyla yapilir (uygulamanin kendi plani, profillerin de kullandigi plan); surucu
ya da MSR yazimi yok. Bu yuzden guvenlidir ve her Windows'ta calisir. Guc siniri (PL1/PL2) ve gerilim
dusurme (undervolt) islemci yazmaclari (MSR) ister: bunlar bir cekirdek surucusu gerektirdigi icin bilerek
eklenmedi; dizustulerde guc sinirini zaten gomulu denetleyicinin guc modu belirler (Performans sekmesi).

Melez Intel islemcide (12. nesil ve sonrasi) P ve E cekirdeklerin ayri frekans tavani ve EPP'si vardir,
zamanlayici hangi isi hangi cekirdege verecegini "heterojen politika" ile secer. Melez olmayan islemcide bu
ayrim yoktur; tek tavan gosterilir. Etiketler ceviride: cpuset.<kimlik>, cpuset.<kimlik>.desc.
"""
import ctypes

import profiller as pf
from ceviri import t

BOOST = [0, 1, 2, 3, 4]           # ceviri: boost.N
SCHED = [5, 0, 2, 1, 4, 3]        # ceviri: sched.N

# (kimlik, guc plani anahtar(lar)i, tur, secenekler/aralik, kosul)
CONTROLS = [
    ("boost", ("boost",), "select", BOOST, None),
    ("epp", ("epp", "epp1"), "range", (0, 100, 5), "epp"),
    ("fmax_p", ("fmax1",), "mhz", None, "hybrid"),
    ("fmax_e", ("fmax",), "mhz", None, "hybrid"),
    ("fmax", ("fmax", "fmax1"), "mhz", None, "single"),
    ("pmax", ("pmax", "pmax1"), "range", (20, 100, 1), None),
    ("pmin", ("pmin", "pmin1"), "range", (0, 100, 5), None),
    ("sched", ("sched",), "select", SCHED, "hybrid"),
    ("sched_short", ("sched_short",), "select", SCHED, "hybrid"),
    ("park", ("park", "park1"), "range", (0, 100, 10), None),
]
BY_ID = {c[0]: c for c in CONTROLS}


def _shown(cpu):
    feat = (cpu or {}).get("features") or {}
    for c in CONTROLS:
        cond = c[4]
        if cond == "hybrid" and not feat.get("hybrid"):
            continue
        if cond == "single" and feat.get("hybrid"):
            continue
        if cond == "epp" and not feat.get("epp"):
            continue
        yield c


def visible(cpu):
    """Bu islemcide anlamli olan kontroller (secili dilde)."""
    out = []
    for cid, _, kind, opts, _ in _shown(cpu):
        prefix = "boost" if opts is BOOST else "sched"
        out.append({"id": cid, "label": t("cpuset." + cid), "desc": t("cpuset.%s.desc" % cid), "kind": kind,
                    "opts": [{"v": v, "t": t("%s.%d" % (prefix, v))} for v in opts] if kind == "select" else None,
                    "range": list(opts) if kind == "range" else None})
    return out


def read(cpu):
    """Etkin plandaki degerler (kullanici kendi planindaysa onunkiler gosterilir)."""
    scheme = pf.active_scheme() or pf.BALANCED
    vals = {c[0]: pf._read(scheme, c[1][0]) for c in _shown(cpu)}
    return {"values": vals, "own_scheme": scheme == pf.SCHEME}


def write(cid, value, cpu):
    """Tek bir ayari uygulamanin guc planina yazar ve plani etkinlestirir. Bir profil uygulaninca profilin
    degerleri bunlarin yerine gecer."""
    if cid not in {c[0] for c in _shown(cpu)}:
        raise ValueError(t("err.cpuNoSetting"))
    _, keys, kind, opts, _ = BY_ID[cid]
    try:
        value = int(value)
    except (TypeError, ValueError):
        raise ValueError(t("err.badValue"))
    if kind == "select" and value not in opts:
        raise ValueError(t("err.badValue"))
    if kind == "range":
        value = max(opts[0], min(opts[1], value))
    if kind == "mhz":
        value = 0 if value <= 0 else max(400, min(6500, value))
    pf.ensure_scheme()
    ok = [pf._write(k, value) for k in keys]
    if not ok[0]:
        raise RuntimeError(t("err.cpuWrite", name=t("cpuset." + cid)))
    if pf.POWRPROF.PowerSetActiveScheme(None, ctypes.byref(pf._g(pf.SCHEME))) != 0:
        raise RuntimeError(t("err.schemeActivate"))
    return value
