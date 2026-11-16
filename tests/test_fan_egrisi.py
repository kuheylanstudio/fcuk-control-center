# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""Fan sayfasindaki "Kendi egrim": kaydetme, profillerde korunma, isi bekcisi ve fabrika donusu. Donanima dokunmaz."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import donanim as hw  # noqa: E402
import profiller  # noqa: E402


class FakeEc:
    """Egri destekli sahte denetleyici: yazilan egri ve fan modu kaydedilir."""
    vendor = "clevo"

    def __init__(self, curve=True):
        self._curve = curve
        self.curves = []
        self.mode = hw.FAN_AUTO

    def caps(self):
        return {"power": True, "fan_max": True, "fan_curve": self._curve, "temp": True}

    def set_fan_curve(self, cpu, gpu):
        self.curves.append((tuple(cpu), tuple(gpu)))
        self.mode = 6

    def set_fan_mode(self, mode):
        self.mode = mode

    def fan_mode(self):
        return self.mode


class FakeSensors:
    gpu_name = ""

    def __init__(self):
        self.listeners = []


def manager(curve=True):
    saves = []
    cfg = {}
    mgr = profiller.Manager(FakeEc(curve), FakeSensors(), cfg, lambda: saves.append(dict(cfg)))
    return mgr, cfg, saves


class UserCurve(unittest.TestCase):
    def test_clean(self):
        u = profiller.clean_user_curve([60, 40, 80, 90])
        self.assertEqual(u, {"cpu": [60, 40, 80, 90], "gpu": [60, 40, 80, 90]})  # kart verilmezse ayni egri
        u = profiller.clean_user_curve([60, 40, 80, 90], [55, 30, 75, 70])
        self.assertEqual(u["gpu"], [55, 30, 75, 70])
        for bad in (None, [1, 2], ["60", 1, 2, 3], {"a": 1}):
            with self.assertRaises(ValueError):
                profiller.clean_user_curve(bad)

    def test_save_applies_and_persists(self):
        mgr, cfg, saves = manager()
        mgr.set_user_curve([62, 35, 82, 80], [58, 30, 78, 75])
        self.assertEqual(mgr.dchu.curves[-1], ((62, 35, 82, 80), (58, 30, 78, 75)))
        self.assertEqual(cfg["fan_sel"], "user")
        self.assertEqual(cfg["fan_user"], {"cpu": [62, 35, 82, 80], "gpu": [58, 30, 78, 75]})
        self.assertTrue(saves)

    def test_profiles_keep_user_curve(self):
        mgr, cfg, _ = manager()
        mgr.set_user_curve([62, 35, 82, 80])
        for pid in ("tam_sessiz", "performans", "ultra"):  # egri, otomatik ve egri profilleri
            msg = mgr._fan(profiller.BY_ID[pid])
            self.assertEqual(mgr.dchu.curves[-1], ((62, 35, 82, 80), (62, 35, 82, 80)), pid)
            self.assertEqual(msg, profiller.t("msg.userCurve"))
            self.assertEqual(mgr.dchu.mode, 6)

    def test_clear_returns_to_profile_curve(self):
        mgr, cfg, _ = manager()
        mgr.set_user_curve([62, 35, 82, 80])
        mgr.clear_user_curve()
        self.assertNotIn("fan_sel", cfg)
        self.assertIn("fan_user", cfg)  # kayitli egri silinmez
        p = profiller.BY_ID["tam_sessiz"]
        mgr._fan(p)
        self.assertEqual(mgr.dchu.curves[-1], (p["fan"][1], p["fan"][2]))
        mgr._fan(profiller.BY_ID["performans"])  # profil otomatik fan
        self.assertEqual(mgr.dchu.mode, hw.FAN_AUTO)

    def test_unsupported_machine(self):
        mgr, cfg, _ = manager(curve=False)
        with self.assertRaises(hw.Unsupported):
            mgr.set_user_curve([62, 35, 82, 80])
        cfg.update({"fan_sel": "user", "fan_user": {"cpu": [62, 35, 82, 80], "gpu": [62, 35, 82, 80]}})
        p = profiller.BY_ID["tam_sessiz"]
        self.assertIs(mgr.fan_spec(p), p["fan"])  # egri yoksa kayitli secim yok sayilir

    def test_broken_saved_curve_falls_back(self):
        mgr, cfg, _ = manager()
        cfg.update({"fan_sel": "user", "fan_user": {"cpu": [1, 2]}})
        p = profiller.BY_ID["sessiz_oyun"]
        self.assertIs(mgr.fan_spec(p), p["fan"])

    def test_guard_restores_user_curve(self):
        mgr, cfg, _ = manager()
        mgr.set_user_curve([62, 35, 82, 80])
        mgr.applied = "performans"  # profil otomatik fan; kendi egrin yine de bekcinin korumasinda
        mgr._last_ac = True
        hot = {"cpu_temp": 95, "gpu_temp": 60, "battery": {"ac": True}}
        for _ in range(5):
            mgr._tick(hot, 1.0)
        self.assertEqual(mgr.dchu.mode, hw.FAN_AUTO)
        self.assertTrue(mgr.guard)
        cool = {"cpu_temp": 60, "gpu_temp": 50, "battery": {"ac": True}}
        for _ in range(30):
            mgr._tick(cool, 1.0)
        self.assertEqual(mgr.guard, "")
        self.assertEqual(mgr.dchu.curves[-1], ((62, 35, 82, 80), (62, 35, 82, 80)))

    def test_factory_drops_selection(self):
        mgr, cfg, _ = manager()
        mgr.set_user_curve([62, 35, 82, 80])
        mgr.dchu.set_power_mode = lambda m: None
        mgr._restore_scheme = lambda: None
        mgr.factory()
        self.assertNotIn("fan_sel", cfg)
        self.assertIn("fan_user", cfg)


if __name__ == "__main__":
    unittest.main()
