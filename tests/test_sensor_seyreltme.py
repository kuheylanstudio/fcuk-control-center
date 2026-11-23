# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""Denetleyici durum okumasinin seyreltilmesi: kimse izlemiyor, sistem serin ve bostaysa 5 sn'de bir okunur.
Donanima dokunmaz; sahte denetleyici ve sahte basarim sayaclariyla calisir."""
import os
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import donanim as hw  # noqa: E402


def bare_sensors():
    """Donanim sorgusu yapmadan Sensors: yalnizca status_due icin gereken alanlar."""
    s = hw.Sensors.__new__(hw.Sensors)
    s.need_fast = lambda: False
    s._viewers = 0
    s._vlock = threading.Lock()
    return s


COOL = {"cpu_temp": 50, "gpu_temp": 45, "cpu_load": 5.0, "gpu_active": False}


class StatusDueTest(unittest.TestCase):
    def test_cool_idle_waits(self):
        s = bare_sensors()
        self.assertFalse(s.status_due(COOL, 1.0))
        self.assertTrue(s.status_due(COOL, s.STATUS_IDLE))

    def test_warm_or_busy_reads_every_second(self):
        s = bare_sensors()
        for k, v in (("cpu_temp", 75), ("gpu_temp", 70), ("cpu_load", 50.0), ("gpu_active", True)):
            self.assertTrue(s.status_due(dict(COOL, **{k: v}), 1.0), k)

    def test_open_window_reads_every_second(self):
        s = bare_sensors()
        s.watch(True)
        self.assertTrue(s.status_due(COOL, 1.0))
        s.watch(False)
        self.assertFalse(s.status_due(COOL, 1.0))
        s.watch(False)  # fazladan kapanis sayaci eksiye dusurmez
        self.assertEqual(s._viewers, 0)

    def test_overlay_log_or_guard_reads_every_second(self):
        s = bare_sensors()
        s.need_fast = lambda: True
        self.assertTrue(s.status_due(COOL, 1.0))

    def test_broken_hook_fails_safe(self):
        s = bare_sensors()
        s.need_fast = lambda: 1 / 0
        self.assertTrue(s.status_due(COOL, 1.0))

    def test_missing_or_bad_values_count_as_cool(self):
        s = bare_sensors()
        self.assertFalse(s.status_due({}, 1.0))
        self.assertFalse(s.status_due({"cpu_temp": None, "sensor_error": "x"}, 1.0))


class FakeDchu:
    def __init__(self):
        self.calls = 0
        self.temp = 50

    def status(self):
        self.calls += 1
        return {"cpu_temp": self.temp, "gpu_temp": 40, "cpu_rpm": 2000}

    def temps(self):
        return self.temp, 40


class FakePdh:
    def __init__(self, counters):
        pass

    def collect(self):
        return {}  # yuk 0, ekran karti uykuda


class LoopTest(unittest.TestCase):
    def run_loop(self, seconds, dchu, before=None):
        with mock.patch.object(hw, "Pdh", FakePdh), mock.patch.object(hw, "caps", lambda d: {"temp": True}):
            s = hw.Sensors(dchu)
            s.disk_ids = lambda: []
            if before:
                before(s)
            seen = []
            s.listeners.append(lambda snap, dt: seen.append(snap))
            th = threading.Thread(target=s._loop, daemon=True)
            th.start()
            time.sleep(seconds)
            s.running = False
            th.join(3)
        return s, seen

    def test_idle_reads_once_and_carries_values(self):
        d = FakeDchu()
        _, seen = self.run_loop(3.3, d)
        self.assertGreaterEqual(len(seen), 3)
        self.assertEqual(d.calls, 1)  # ilk olcum okur, sonraki saniyeler son degeri tasir
        self.assertTrue(all(x.get("cpu_temp") == 50 and x.get("cpu_rpm") == 2000 for x in seen))

    def test_open_window_reads_every_tick(self):
        d = FakeDchu()
        _, seen = self.run_loop(3.3, d, before=lambda s: s.watch(True))
        self.assertEqual(d.calls, len(seen))

    def test_warm_reads_every_tick(self):
        d = FakeDchu()
        d.temp = 80
        _, seen = self.run_loop(3.3, d)
        self.assertEqual(d.calls, len(seen))


if __name__ == "__main__":
    unittest.main()
