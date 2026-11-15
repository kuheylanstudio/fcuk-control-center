# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""Olcum gecmisi ve pil asinma gecmisi.

Recorder: sensor dongusunun her olcumunu (saniyede bir) bellekte son 1 saat tutar; istenirse gunluk CSV
dosyalarina da yazar (veri\\kayit\\YYYY-MM-DD.csv, 7 gun saklanir). Gecmis sayfasi grafigi ve "CSV olarak kaydet"
buradan beslenir. Kisilma: ekran karti guc/isi siniri bitleri ya da islemci 95 C ve ustu.

BatteryLog: gunde bir kez tam sarj ve tasarim kapasitesini kaydeder (veri\\pil.json); aylar icindeki asinma
egrisi Gecmis sayfasinda gosterilir.
"""
import csv
import io
import json
import os
import threading
import time
from collections import deque

HOUR = 3600
KEEP_DAYS = 7
FIELDS = ("cpu_temp", "gpu_temp", "cpu_power", "gpu_power", "cpu_load", "gpu_load", "cpu_mhz", "gpu_clock",
          "cpu_rpm", "gpu_rpm")
GPU_POWER_BITS = 0x4 | 0x80          # guc siniri, guc freni
GPU_THERMAL_BITS = 0x8 | 0x20 | 0x40  # donanim yavaslatmasi, isi siniri (yazilim / donanim)
CPU_HOT = 95


def throttle_kind(s):
    """'' | 'power' | 'thermal': o saniyede hiz neden kisildi (isi gucten once gelir)."""
    mask = s.get("gpu_throttle") or 0
    cpu = s.get("cpu_temp")
    if mask & GPU_THERMAL_BITS or (isinstance(cpu, (int, float)) and cpu >= CPU_HOT):
        return "thermal"
    if mask & GPU_POWER_BITS:
        return "power"
    return ""


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _empty():
    return {"t": [], "throttle": [], "profile": [], "app": [], **{k: [] for k in FIELDS}}


class Recorder:
    def __init__(self, folder, enabled=lambda: False, context=lambda: ("", "")):
        """folder: gunluk CSV klasoru. enabled(): diske yazilsin mi. context(): (profil, uygulama)."""
        self.folder = folder
        self.enabled = enabled
        self.context = context
        self.rows = deque(maxlen=HOUR)
        self.lock = threading.Lock()
        self._file = None
        self._writer = None
        self._day = None
        self._pending = 0

    # ---------------------------------------------------------------- olcum
    def tick(self, s, dt=1.0):
        """Sensors.listeners imzasi (s, dt). Hata firlatmaz: kayit, olcum dongusunu durduramaz."""
        try:
            profile, app = self.context()
            row = {"t": time.time(), "throttle": throttle_kind(s), "profile": profile or "", "app": app or ""}
            for k in FIELDS:
                row[k] = _num(s.get(k))
            with self.lock:
                self.rows.append(row)
            if self.enabled():
                self._disk(row)
            elif self._file:
                self._close()
        except Exception:
            pass

    def _since(self, minutes):
        since = time.time() - minutes * 60
        with self.lock:
            return [r for r in self.rows if r["t"] >= since]

    # ---------------------------------------------------------------- sorgu
    def series(self, minutes=60, points=600):
        """Son `minutes` dakika, en fazla `points` noktaya indirgenmis (kova ortalamasi; kisilma kovada bir kez
        bile olduysa isaretlenir; profil/uygulama kovanin sonundaki)."""
        rows = self._since(minutes)
        out = _empty()
        if not rows:
            return out
        step = max(1, -(-len(rows) // points))
        for i in range(0, len(rows), step):
            b = rows[i:i + step]
            out["t"].append(round(b[-1]["t"], 1))
            kinds = {r["throttle"] for r in b}
            out["throttle"].append("thermal" if "thermal" in kinds else "power" if "power" in kinds else "")
            out["profile"].append(b[-1]["profile"])
            out["app"].append(b[-1]["app"])
            for k in FIELDS:
                vals = [r[k] for r in b if r[k] is not None]
                out[k].append(round(sum(vals) / len(vals), 1) if vals else None)
        return out

    def summary(self, minutes=60):
        """Ozet: en yuksek / ortalama sicaklik ve guc, kisilma suresi (sn)."""
        rows = self._since(minutes)
        out = {"seconds": len(rows), "thermal_s": sum(r["throttle"] == "thermal" for r in rows),
               "power_s": sum(r["throttle"] == "power" for r in rows)}
        for k in ("cpu_temp", "gpu_temp", "cpu_power", "gpu_power"):
            vals = [r[k] for r in rows if r[k] is not None]
            out[k] = {"max": max(vals), "avg": round(sum(vals) / len(vals), 1)} if vals else None
        return out

    def csv_text(self, minutes=60):
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\r\n")
        w.writerow(("time",) + FIELDS + ("throttle", "profile", "app"))
        for r in self._since(minutes):
            w.writerow(self._csv_row(r))
        return buf.getvalue()

    @staticmethod
    def _csv_row(r):
        return ((time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(r["t"])),)
                + tuple("" if r[k] is None else r[k] for k in FIELDS) + (r["throttle"], r["profile"], r["app"]))

    # ---------------------------------------------------------------- disk
    def _disk(self, row):
        day = time.strftime("%Y-%m-%d", time.localtime(row["t"]))
        if day != self._day:
            self._close()
            os.makedirs(self.folder, exist_ok=True)
            path = os.path.join(self.folder, day + ".csv")
            new = not os.path.isfile(path)
            self._file = open(path, "a", encoding="utf-8", newline="")
            self._writer = csv.writer(self._file, lineterminator="\r\n")
            if new:
                self._writer.writerow(("time",) + FIELDS + ("throttle", "profile", "app"))
            self._day = day
            self.prune()
        self._writer.writerow(self._csv_row(row))
        self._pending += 1
        if self._pending >= 15:  # disk her saniye uyandirilmasin
            self._file.flush()
            self._pending = 0

    def _close(self):
        if self._file:
            try:
                self._file.close()
            except OSError:
                pass
        self._file = self._writer = self._day = None
        self._pending = 0

    def flush(self):
        if self._file:
            try:
                self._file.flush()
            except OSError:
                pass

    def prune(self, now=None):
        """KEEP_DAYS gunden eski gunluk dosyalari siler (yalnizca YYYY-MM-DD.csv adli dosyalar)."""
        now = now or time.time()
        limit = time.strftime("%Y-%m-%d", time.localtime(now - KEEP_DAYS * 86400))
        try:
            names = os.listdir(self.folder)
        except OSError:
            return []
        gone = []
        for n in names:
            stem = n[:-4]
            if n.endswith(".csv") and len(stem) == 10 and stem[4] == "-" and stem[7] == "-" and stem < limit:
                try:
                    os.remove(os.path.join(self.folder, n))
                    gone.append(n)
                except OSError:
                    pass
        return gone

    def files(self):
        try:
            return sorted((n for n in os.listdir(self.folder) if n.endswith(".csv")), reverse=True)
        except OSError:
            return []


# ----------------------------------------------------------------------------- pil
def read_battery():
    """(tam_sarj_mWh, tasarim_mWh, dongu) ya da None. root\\WMI siniflari; pil yoksa None."""
    import wmi_com
    w = wmi_com.Wmi(r"root\WMI")
    try:
        full = sum(r.get("FullChargedCapacity") or 0 for r in
                   w.query("SELECT FullChargedCapacity FROM BatteryFullChargedCapacity", ["FullChargedCapacity"]))
        design = sum(r.get("DesignedCapacity") or 0 for r in
                     w.query("SELECT DesignedCapacity FROM BatteryStaticData", ["DesignedCapacity"]))
        try:
            cycles = sum(r.get("CycleCount") or 0 for r in
                         w.query("SELECT CycleCount FROM BatteryCycleCount", ["CycleCount"]))
        except Exception:
            cycles = 0
    finally:
        w.close()
    if not full or not design:
        return None
    return full, design, cycles


class BatteryLog:
    MAX = 3650  # ~10 yil gunluk kayit

    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return []
        out = []
        for r in data if isinstance(data, list) else []:
            if (isinstance(r, dict) and isinstance(r.get("date"), str) and len(r["date"]) == 10
                    and _num(r.get("full_wh")) and _num(r.get("design_wh"))):
                out.append({"date": r["date"], "full_wh": r["full_wh"], "design_wh": r["design_wh"],
                            "cycles": _num(r.get("cycles")) or 0})
        return out

    def record(self, full_mwh, design_mwh, cycles=0, day=None):
        """Gunde bir kayit; ayni gun yeniden cagrilirsa o gunun degeri guncellenir. Kayit listesini dondurur."""
        day = day or time.strftime("%Y-%m-%d")
        row = {"date": day, "full_wh": round(full_mwh / 1000.0, 2), "design_wh": round(design_mwh / 1000.0, 2),
               "cycles": int(cycles or 0)}
        with self.lock:
            rows = [r for r in self.load() if r["date"] != day] + [row]
            rows.sort(key=lambda r: r["date"])
            rows = rows[-self.MAX:]
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(rows, f)
            os.replace(tmp, self.path)
        return rows

    def payload(self):
        rows = self.load()
        out = {"rows": rows}
        if rows:
            first, last = rows[0], rows[-1]
            out["health"] = round(last["full_wh"] * 100.0 / last["design_wh"], 1)
            days = (time.mktime(time.strptime(last["date"], "%Y-%m-%d"))
                    - time.mktime(time.strptime(first["date"], "%Y-%m-%d"))) / 86400.0
            if days >= 30:  # yillik kayip: en az bir aylik veriyle anlamli
                out["loss_per_year"] = round((first["full_wh"] - last["full_wh"]) * 100.0 / last["design_wh"]
                                             * 365.0 / days, 1)
        return out

    def loop(self, log=None, every=6 * 3600):
        """Acilista ve her 6 saatte bir: bugunun kaydi yoksa olcup yazar."""
        while True:
            try:
                today = time.strftime("%Y-%m-%d")
                if not any(r["date"] == today for r in self.load()):
                    b = read_battery()
                    if b:
                        self.record(*b)
            except Exception as exc:
                if log:
                    log("pil gecmisi: %s" % exc)
            time.sleep(every)
