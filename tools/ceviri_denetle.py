# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""Ceviri denetimi: ui/lang/*.json dosyalari birbiriyle ve kodla uyumlu mu?

Denetlenenler:
  1. Kodda kullanilan her anahtar (data-i18n*, t('...'), Python'da t("...")) tr.json ve en.json'da var mi.
  2. tr.json'daki her anahtar her dilde var mi (eksikler) ve dillerde fazladan anahtar var mi.
  3. Yer tutucular ({ad}) her dilde Turkce ile ayni mi.
  4. Bos ceviri var mi.

    python tools/ceviri_denetle.py          # sorun varsa cikis kodu 1
    python tools/ceviri_denetle.py --ozet   # yalnizca dil basina sayilar
"""
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LANG = os.path.join(ROOT, "ui", "lang")
BASE = "tr"
PH = re.compile(r"\{(\w+)\}")
# Sayfada: data-i18n="k", data-i18n-title="k", data-i18n-placeholder="k" ...; betikte t('k' / t("k"
HTML_KEY = re.compile(r"""data-i18n(?:-[a-z]+)?=["']([\w.\-]+)["']""")
JS_KEY = re.compile(r"""\bt\(\s*['"]([\w.\-]+)['"]""")
PY_KEY = re.compile(r"""\b(?:ceviri\.)?t\(\s*["']([a-z][\w\-]*\.[\w.\-]+)["']""")


def load(code):
    with open(os.path.join(LANG, code + ".json"), encoding="utf-8") as f:
        return json.load(f)


def languages():
    return sorted(os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(LANG, "*.json")))


def used_keys():
    keys = set()
    for path in glob.glob(os.path.join(ROOT, "ui", "*.html")) + glob.glob(os.path.join(ROOT, "ui", "*.js")):
        text = open(path, encoding="utf-8").read()
        keys |= set(HTML_KEY.findall(text)) | set(JS_KEY.findall(text))
    for path in glob.glob(os.path.join(ROOT, "*.py")):
        keys |= set(PY_KEY.findall(open(path, encoding="utf-8").read()))
    # t('msi.fan.' + kip) gibi on ekler tam anahtar degildir
    return {k for k in keys if not k.endswith(".")}


def check():
    """Sorun listesi (bos ise her sey yolunda) ve dil basina eksik sayisi."""
    problems, counts = [], {}
    base = load(BASE)
    for code in ("tr", "en"):
        data = load(code)
        for k in sorted(used_keys() - set(data)):
            problems.append("%s: kodda kullanilan anahtar yok: %s" % (code, k))
    for code in languages():
        if code == BASE:
            continue
        data = load(code)
        missing = sorted(set(base) - set(data))
        extra = sorted(set(data) - set(base))
        counts[code] = len(missing)
        problems += ["%s: eksik: %s" % (code, k) for k in missing]
        problems += ["%s: fazla (tr'de yok): %s" % (code, k) for k in extra]
        for k in sorted(set(base) & set(data)):
            if not isinstance(data[k], str) or not data[k].strip():
                problems.append("%s: bos ceviri: %s" % (code, k))
            elif set(PH.findall(data[k])) != set(PH.findall(base[k])):
                problems.append("%s: yer tutucu farkli: %s (%s / %s)" % (
                    code, k, sorted(PH.findall(base[k])), sorted(PH.findall(data[k]))))
    return problems, counts


def main(argv):
    problems, counts = check()
    if "--ozet" in argv:
        for code, n in sorted(counts.items()):
            print("%s: %d eksik" % (code, n))
    else:
        for p in problems:
            print(p)
    print("%d sorun" % len(problems))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
