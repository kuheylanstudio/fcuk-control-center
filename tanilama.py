# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""Tanilama raporu ve son hatalar.

Rapor, GitHub'da sorun bildirirken yapistirilmak icin duz metindir: surum, Windows, model / BIOS, hangi arka ucun
secildigi, ozellik yoklama sonuclari (destek.py, yalnizca okuyarak), etkin profil, olcumlerin hangilerinin
geldigi ve gunlugun son satirlari. Kisisel bilgi icermez: kullanici klasoru yolu %USERPROFILE% ile, bilgisayar ve
kullanici adi <bilgisayar> / <kullanici> ile degistirilir. Rapor hicbir yere gonderilmez; kullanici kaydeder ya da
kopyalar.
"""
import os
import platform
import re
import time

LOG_TAIL = 80
ERROR_WORDS = ("hata", "error", "traceback", "exception", "basarisiz", "reddedildi", "zaman asimi")


def redact(text):
    """Kullanici klasoru, kullanici adi ve bilgisayar adi metinden cikarilir."""
    home = os.path.expanduser("~")
    user = os.environ.get("USERNAME") or os.path.basename(home)
    host = os.environ.get("COMPUTERNAME") or platform.node()
    if home and len(home) > 3:
        text = re.sub(re.escape(home), "%USERPROFILE%", text, flags=re.I)
    for word, rep in ((user, "<kullanici>"), (host, "<bilgisayar>")):
        if word and len(word) >= 3:
            text = re.sub(r"(?<![\w])" + re.escape(word) + r"(?![\w])", rep, text, flags=re.I)
    return text


def tail(path, n=LOG_TAIL):
    """Gunlugun son n satiri (dosya yoksa bos liste)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        return []
    return lines[-n:]


def errors(path, n=20):
    """Gunlukteki son n hata satiri (hata sozcugu gecenler), kisisel bilgiden arindirilmis."""
    out = []
    for line in tail(path, 2000):
        low = line.lower()
        if any(w in low for w in ERROR_WORDS):
            out.append(redact(line[:400]))
    return out[-n:]


def _kv(rows):
    w = max((len(k) for k, _ in rows), default=0)
    return "\n".join("%s : %s" % (k.ljust(w), v) for k, v in rows)


def build(info, support, log_lines):
    """info: duz sozluk (anahtar -> deger). support: destek.detect listesi. log_lines: gunluk satirlari."""
    rows = [("olusturuldu", time.strftime("%Y-%m-%d %H:%M"))]
    rows += [(k, "" if v is None else v) for k, v in info.items()]
    parts = ["FCUK Control Center - tanilama raporu", "=" * 40, _kv(rows)]
    if support:
        parts += ["", "Ozellik destegi (yalnizca okuyarak yoklandi)", "-" * 40]
        for s in support:
            line = "[%-7s] %s" % (s.get("state", "?"), s.get("label") or s.get("id"))
            if s.get("why"):
                line += " - " + s["why"]
            parts.append(line)
    parts += ["", "Gunluk (son %d satir)" % len(log_lines), "-" * 40] + list(log_lines)
    return redact("\n".join(str(p) for p in parts)) + "\n"
