# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""Olcum gecmisi (Recorder) ve pil asinma gecmisi (BatteryLog). Donanima dokunmaz; gecici klasor kullanir."""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import kayit  # noqa: E402


class ThrottleTest(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(kayit.throttle_kind({}), "")
        self.assertEqual(kayit.throttle_kind({"gpu_throttle": 0x1}), "")          # bosta: kisilma degil
        self.assertEqual(kayit.throttle_kind({"gpu_throttle": 0x4}), "power")
        self.assertEqual(kayit.throttle_kind({"gpu_throttle": 0x20 | 0x4}), "thermal")
        self.assertEqual(kayit.throttle_kind({"cpu_temp": 96}), "thermal")
        self.assertEqual(kayit.throttle_kind({"cpu_temp": 94}), "")


class RecorderTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.on = False
        self.rec = kayit.Recorder(self.dir, lambda: self.on, lambda: ("ultra", "game.exe"))

    def tearDown(self):
        self.rec._close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def feed(self, n, start, **extra):
        for i in range(n):
            with mock.patch("kayit.time.time", return_value=start + i):
                self.rec.tick(dict({"cpu_temp": 60 + i % 10, "cpu_power": 20.0, "gpu_temp": None}, **extra))

    def test_series_downsample_and_summary(self):
        now = time.time()
        self.feed(1200, now - 1200)
        s = self.rec.series(60, points=100)
        self.assertLessEqual(len(s["t"]), 100)
        self.assertEqual(len(s["t"]), len(s["cpu_temp"]))
        self.assertTrue(all(v is None for v in s["gpu_temp"]))
        self.assertEqual(s["profile"][-1], "ultra")
        sm = self.rec.summary(60)
        self.assertEqual(sm["seconds"], 1200)
        self.assertEqual(sm["cpu_temp"]["max"], 69)
        self.assertIsNone(sm["gpu_temp"])

    def test_range_filter_and_bad_values(self):
        now = time.time()
        self.feed(10, now - 3000)                        # 50 dk once
        self.feed(5, now - 5, cpu_power=True)            # bool sayi sayilmaz
        self.assertEqual(self.rec.summary(5)["seconds"], 5)
        self.assertIsNone(self.rec.summary(5)["cpu_power"])
        self.assertEqual(self.rec.summary(60)["seconds"], 15)

    def test_throttle_marked_in_bucket(self):
        now = time.time()
        self.feed(9, now - 10)
        self.feed(1, now - 1, gpu_throttle=0x40)
        s = self.rec.series(60, points=1)
        self.assertEqual(s["throttle"], ["thermal"])
        self.assertEqual(self.rec.summary(60)["thermal_s"], 1)

    def test_csv_text(self):
        self.feed(3, time.time() - 3)
        lines = self.rec.csv_text(60).strip().splitlines()
        self.assertEqual(lines[0].split(",")[0], "time")
        self.assertEqual(len(lines), 4)
        self.assertTrue(lines[1].endswith(",ultra,game.exe"))

    def test_disk_log_and_prune(self):
        self.on = True
        self.feed(20, time.time() - 20)
        self.rec.flush()
        files = self.rec.files()
        self.assertEqual(len(files), 1)
        with open(os.path.join(self.dir, files[0]), encoding="utf-8") as f:
            self.assertEqual(len(f.read().strip().splitlines()), 21)
        old = os.path.join(self.dir, "2000-01-01.csv")
        keep = os.path.join(self.dir, "notlar.csv")
        for p in (old, keep):
            open(p, "w").close()
        self.assertEqual(self.rec.prune(), ["2000-01-01.csv"])
        self.assertTrue(os.path.exists(keep))
        self.on = False
        self.feed(1, time.time())
        self.assertIsNone(self.rec._file)  # kapaninca dosya birakilir

    def test_tick_never_raises(self):
        self.rec.context = lambda: 1 / 0
        self.rec.tick({"cpu_temp": 50})  # hata yutulur
        self.assertEqual(len(self.rec.rows), 0)


class BatteryTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.log = kayit.BatteryLog(os.path.join(self.dir, "pil.json"))

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_record_and_payload(self):
        self.assertEqual(self.log.payload(), {"rows": []})
        self.log.record(50000, 52000, 10, day="2026-01-01")
        self.log.record(49000, 52000, 12, day="2026-01-01")   # ayni gun: guncellenir
        p = self.log.payload()
        self.assertEqual(len(p["rows"]), 1)
        self.assertEqual(p["rows"][0]["full_wh"], 49.0)
        self.assertNotIn("loss_per_year", p)                 # bir aydan kisa
        self.log.record(46400, 52000, 60, day="2026-07-01")
        p = self.log.payload()
        self.assertAlmostEqual(p["health"], 89.2, places=1)
        self.assertGreater(p["loss_per_year"], 0)

    def test_corrupt_file(self):
        with open(self.log.path, "w", encoding="utf-8") as f:
            f.write("{bozuk")
        self.assertEqual(self.log.load(), [])
        with open(self.log.path, "w", encoding="utf-8") as f:
            json.dump([{"date": "x"}, {"date": "2026-01-02", "full_wh": 40, "design_wh": 50}, 5], f)
        self.assertEqual(len(self.log.load()), 1)


if __name__ == "__main__":
    unittest.main()
