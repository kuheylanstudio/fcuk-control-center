# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""Arayuz dilleri.

Tum metinler ui/lang/<kod>.json dosyalarindadir (duz anahtar -> metin). Ayni dosyalar hem Python tarafinda
(profiller, tepsi menusu, ekran bildirimi, hata iletileri) hem arayuzde kullanilir. Eksik bir anahtar once
Ingilizceye, sonra Turkceye (kaynak dil) duser.

Dil ayari config.json'daki "lang" alanidir: "auto" (varsayilan) ya da bir dil kodu. "auto" iken dil,
Windows'un bolge (ulke) ayarindan secilir; ulkede birden cok dil konusuluyorsa Windows arayuz dili
belirleyicidir. Ulke desteklenmiyorsa Windows arayuz dili, o da desteklenmiyorsa Ingilizce.
"""
import ctypes
import json
import os
import sys
import threading

HERE = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
LANG_DIR = os.path.join(HERE, "ui", "lang")
SOURCE = "tr"
FALLBACK = "en"

# (kod, kendi dilindeki adi): en yaygin kullanilan diller, Clevo tabanli oyuncu dizustu pazarlarina gore
LANGS = [
    ("tr", "Türkçe"),
    ("en", "English"),
    ("de", "Deutsch"),
    ("fr", "Français"),
    ("es", "Español"),
    ("pt", "Português (Brasil)"),
    ("it", "Italiano"),
    ("nl", "Nederlands"),
    ("pl", "Polski"),
    ("ru", "Русский"),
    ("uk", "Українська"),
    ("zh", "简体中文"),
    ("ja", "日本語"),
    ("ko", "한국어"),
]
CODES = [c for c, _ in LANGS]

# Ulke (ISO 3166-1 alfa-2) -> o ulkede konusulan desteklenen diller, oncelik sirasiyla
_C = {
    "tr": "TR",
    "de": "DE AT LI",
    "fr": "FR MC SN CI CM ML BF NE TD GN BJ TG CD CG GA MG HT RE GP MQ GF NC PF YT PM WF DZ MA TN",
    "es": "ES MX AR CO PE VE CL EC GT CU BO DO HN PY SV NI CR PA UY PR GQ",
    "pt": "BR PT AO MZ GW CV ST TL",
    "it": "IT SM VA",
    "nl": "NL SR AW CW SX BQ",
    "pl": "PL",
    "ru": "RU BY KZ KG TJ TM UZ AM AZ GE MD",
    "zh": "CN TW HK MO",
    "ja": "JP",
    "ko": "KR KP",
}
COUNTRY = {cc: [code] for code, ccs in _C.items() for cc in ccs.split()}
COUNTRY.update({  # cok dilli ulkeler: Windows arayuz dili bunlardan biriyse o, degilse ilki
    "CH": ["de", "fr", "it"], "BE": ["nl", "fr", "de"], "LU": ["fr", "de"], "CA": ["en", "fr"],
    "CY": ["tr", "en"], "SG": ["en", "zh"], "UA": ["uk", "ru"],
})

_lock = threading.Lock()
_cache = {}
_lang = SOURCE


def _load(code):
    with _lock:
        if code not in _cache:
            try:
                with open(os.path.join(LANG_DIR, code + ".json"), encoding="utf-8") as f:
                    data = json.load(f)
                _cache[code] = data if isinstance(data, dict) else {}
            except (OSError, ValueError):
                _cache[code] = {}
        return _cache[code]


def catalog(code=None):
    """Bir dilin tam metin sozlugu: eksikler Ingilizce, sonra Turkce ile doldurulur."""
    out = dict(_load(SOURCE))
    out.update(_load(FALLBACK))
    out.update(_load(code or _lang))
    return out


def set_lang(code):
    global _lang
    _lang = code if code in CODES else FALLBACK


def lang():
    return _lang


def t(key, **kw):
    s = _load(_lang).get(key) or _load(FALLBACK).get(key) or _load(SOURCE).get(key) or key
    if kw:
        try:
            return s.format(**kw)
        except (KeyError, IndexError, ValueError):
            return s
    return s


def num(v, d=0):
    """Dile gore ondalik ayiraci ile sayi (2,4 / 2.4)."""
    s = "%.*f" % (d, v)
    return s.replace(".", t("fmt.dec")) if d else s


def pct(v):
    """Dile gore yuzde: %50 (Turkce), 50% (Ingilizce), 50 % (Almanca, Fransizca)."""
    return t("fmt.pct", v=v)


def upper(text):
    """Dile gore buyuk harf: Turkcede i -> İ, ı -> I."""
    if _lang == "tr":
        text = text.replace("i", "İ")
    return text.upper()


# ----------------------------------------------------------------------------- algilama
def country():
    """Windows'taki 'Ulke veya bolge' ayari (ISO2), okunamazsa ''."""
    k32 = ctypes.windll.kernel32
    buf = ctypes.create_unicode_buffer(16)
    try:
        if k32.GetUserDefaultGeoName(buf, 16) and len(buf.value) == 2:  # Windows 10 1709+
            return buf.value.upper()
    except (AttributeError, OSError):
        pass
    try:  # eski yol: GEO kimligi -> ISO2
        if k32.GetGeoInfoW(k32.GetUserGeoID(16), 4, buf, 16, 0):  # GEOCLASS_NATION, GEO_ISO2
            return buf.value.upper()
    except (AttributeError, OSError):
        pass
    try:  # son care: bicim yerel ayarindaki bolge (tr-TR -> TR)
        if k32.GetUserDefaultLocaleName(buf, 16):
            part = buf.value.split("-")[-1]
            if len(part) == 2:
                return part.upper()
    except (AttributeError, OSError):
        pass
    return ""


def ui_lang():
    """Windows arayuz dilinin iki harfli kodu (tr, en, de...), okunamazsa ''."""
    try:
        n, size = ctypes.c_ulong(0), ctypes.c_ulong(256)
        buf = ctypes.create_unicode_buffer(256)
        if ctypes.windll.kernel32.GetUserPreferredUILanguages(8, ctypes.byref(n), buf, ctypes.byref(size)):
            return buf.value.split("-")[0].lower()  # MUI_LANGUAGE_NAME: ilk tercih
    except (AttributeError, OSError):
        pass
    return ""


def detect():
    """Bilgisayarin ulke ayarina gore dil kodu."""
    options = COUNTRY.get(country())
    ui = ui_lang()
    if options:
        return ui if ui in options else options[0]
    return ui if ui in CODES else FALLBACK


def resolve(setting):
    """Ayardan ("auto" ya da kod) etkin dil."""
    return setting if setting in CODES else detect()


def languages():
    return [{"code": c, "name": n} for c, n in LANGS]
