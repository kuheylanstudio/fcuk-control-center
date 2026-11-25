# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""Tasarruf profili: NVIDIA kartini kapatma / geri acma kararlari. Donanima dokunmaz (aygit cagrilari sahte).

    python -m unittest discover -s tests
"""
import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import donanim as hw  # noqa: E402
import profiller  # noqa: E402

NV = "PCI\\VEN_10DE&DEV_25AC&SUBSYS_A5541558&REV_A1\\4&24D0EA3&0&0008"
INTEL = "PCI\\VEN_8086&DEV_46A3&SUBSYS_A5541558&REV_0C\\3&11583659&0&10"


def devices(nv_disabled=False, igpu=True):
    out = [{"id": NV, "name": "NVIDIA GeForce RTX 3050", "nvidia": True, "disabled": nv_disabled,
            "running": not nv_disabled}]
    if igpu:
        out.insert(0, {"id": INTEL, "name": "Intel UHD", "nvidia": False, "disabled": False, "running": True})
    return out


def manager(cfg=None, gpu_name="NVIDIA GeForce RTX 3050"):
    m = profiller.Manager.__new__(profiller.Manager)
    m.cfg = dict(cfg or {})
    m.saves = 0

    def save():
        m.saves += 1
    m.save = save
    m._gpu_locked = False
    m.sensors = types.SimpleNamespace(gpu_name=gpu_name, gpu_off=False, nvml=object(),
                                      detect_gpus=lambda: None)
    return m


class ProfileTest(unittest.TestCase):
    def test_profile_shape(self):
        p = profiller.BY_ID["tasarruf"]
        self.assertIs(profiller.PROFILES[0], p)  # listede en basta: en az guc -> en cok guc
        self.assertTrue(p["gpu_off"])
        self.assertEqual(p["ec"], 1)  # denetleyici guc tasarrufu modu
        self.assertEqual(p["cpu"]["boost"], 0)
        self.assertEqual(p["refresh"], "min")
        for curve in p["fan"][1:]:
            self.assertEqual(profiller.clean_curve(curve), curve)
        # en sessiz egri: Tam Sessiz'den daha gec ve daha yavas
        quiet = profiller.BY_ID["tam_sessiz"]["fan"][1]
        self.assertGreaterEqual(p["fan"][1][0], quiet[0])
        self.assertLessEqual(p["fan"][1][1], quiet[1])

    def test_level_zero_is_kept(self):
        p = profiller.BY_ID["tasarruf"]
        self.assertEqual(profiller.level_of(p), 0)
        self.assertEqual(profiller.level_of(profiller.BY_ID["ultra"]), 5)
        built = profiller.build_custom(profiller.clean_custom([{"name": "x", "base": "tasarruf", "fan": "auto"}])[0])
        self.assertEqual(profiller.level_of(built), 0)
        self.assertTrue(built["gpu_off"])


class OffTest(unittest.TestCase):
    def test_disables_and_flags_before(self):
        m = manager()
        seen = {}

        def set_dgpu(dev_id, enabled):
            seen["flag_at_call"] = m.cfg.get("gpu_off")
            seen["call"] = (dev_id, enabled)
            return 0, ""
        with mock.patch.object(hw, "display_devices", return_value=devices()), \
                mock.patch.object(hw, "dgpu_off_blocker", return_value=None), \
                mock.patch.object(hw, "is_admin", return_value=True), \
                mock.patch.object(hw, "set_dgpu", side_effect=set_dgpu):
            msg = m._gpu(profiller.BY_ID["tasarruf"])
        self.assertEqual(seen["call"], (NV, False))
        self.assertTrue(seen["flag_at_call"])  # bayrak kapatmadan ONCE kaydedildi
        self.assertTrue(m.cfg["gpu_off"])
        self.assertTrue(m.sensors.gpu_off)
        self.assertIsNone(m.sensors.nvml)
        self.assertEqual(msg, profiller.t("val.gpuOff"))

    def test_blocker_keeps_card_on(self):
        m = manager()
        with mock.patch.object(hw, "display_devices", return_value=devices()), \
                mock.patch.object(hw, "dgpu_off_blocker", return_value="err.gpuOffDisplay"), \
                mock.patch.object(hw, "is_admin", return_value=True), \
                mock.patch.object(hw, "set_dgpu") as sd:
            with self.assertRaises(RuntimeError):
                m._gpu(profiller.BY_ID["tasarruf"])
        sd.assert_not_called()
        self.assertNotIn("gpu_off", m.cfg)
        self.assertFalse(m.sensors.gpu_off)

    def test_failure_clears_flag(self):
        m = manager()
        with mock.patch.object(hw, "display_devices", return_value=devices()), \
                mock.patch.object(hw, "dgpu_off_blocker", return_value=None), \
                mock.patch.object(hw, "is_admin", return_value=True), \
                mock.patch.object(hw, "set_dgpu", return_value=(5, "erisim engellendi")):
            with self.assertRaises(RuntimeError):
                m._gpu(profiller.BY_ID["tasarruf"])
        self.assertNotIn("gpu_off", m.cfg)

    def test_reboot_needed(self):
        m = manager()
        with mock.patch.object(hw, "display_devices", return_value=devices()), \
                mock.patch.object(hw, "dgpu_off_blocker", return_value=None), \
                mock.patch.object(hw, "is_admin", return_value=True), \
                mock.patch.object(hw, "set_dgpu", return_value=(hw.PNP_REBOOT, "")):
            msg = m._gpu(profiller.BY_ID["tasarruf"])
        self.assertEqual(msg, profiller.t("msg.gpuOffReboot"))
        self.assertTrue(m.cfg["gpu_off"])

    def test_not_admin(self):
        m = manager()
        with mock.patch.object(hw, "display_devices", return_value=devices()), \
                mock.patch.object(hw, "is_admin", return_value=False), \
                mock.patch.object(hw, "set_dgpu") as sd:
            with self.assertRaises(RuntimeError):
                m._gpu(profiller.BY_ID["tasarruf"])
        sd.assert_not_called()

    def test_no_nvidia_is_skip(self):
        m = manager(gpu_name="")
        with mock.patch.object(hw, "display_devices", return_value=devices()[:1]):
            with self.assertRaises(hw.Unsupported):
                m._gpu(profiller.BY_ID["tasarruf"])

    def test_user_disabled_card_not_flagged(self):
        """Kart zaten kapali (kullanici Aygit Yoneticisi'nden kapatmis): bayrak konmaz, sonra da acilmaz."""
        m = manager()
        with mock.patch.object(hw, "display_devices", return_value=devices(nv_disabled=True)), \
                mock.patch.object(hw, "set_dgpu") as sd:
            m._gpu(profiller.BY_ID["tasarruf"])
        sd.assert_not_called()
        self.assertNotIn("gpu_off", m.cfg)


class OnTest(unittest.TestCase):
    def test_other_profile_reenables_our_card(self):
        m = manager({"gpu_off": True}, gpu_name="")

        def detect():
            m.sensors.gpu_name = "NVIDIA GeForce RTX 3050"
        m.sensors.detect_gpus = detect
        m.sensors.gpu_off = True
        with mock.patch.object(hw, "display_devices", return_value=devices(nv_disabled=True)), \
                mock.patch.object(hw, "is_admin", return_value=True), \
                mock.patch.object(hw, "set_dgpu", return_value=(0, "")) as sd, \
                mock.patch.object(hw, "nvidia_lock_clocks", return_value=(0, "")) as lock, \
                mock.patch.object(profiller.time, "sleep"):
            msg = m._gpu(profiller.BY_ID["performans"])
        sd.assert_called_once_with(NV, True)
        lock.assert_called_once_with(0, None)
        self.assertNotIn("gpu_off", m.cfg)
        self.assertFalse(m.sensors.gpu_off)
        self.assertTrue(msg.startswith(profiller.t("msg.gpuOn")))

    def test_foreign_disabled_card_left_alone(self):
        m = manager({}, gpu_name="")
        with mock.patch.object(hw, "display_devices", return_value=devices(nv_disabled=True)), \
                mock.patch.object(hw, "set_dgpu") as sd:
            with self.assertRaises(hw.Unsupported):
                m._gpu(profiller.BY_ID["performans"])
        sd.assert_not_called()

    def test_stale_flag_cleared_when_card_already_on(self):
        m = manager({"gpu_off": True})
        with mock.patch.object(hw, "display_devices", return_value=devices()), \
                mock.patch.object(hw, "is_admin", return_value=True), \
                mock.patch.object(hw, "set_dgpu") as sd, \
                mock.patch.object(hw, "nvidia_lock_clocks", return_value=(0, "")):
            m._gpu(profiller.BY_ID["performans"])
        sd.assert_not_called()
        self.assertNotIn("gpu_off", m.cfg)


class BlockerTest(unittest.TestCase):
    def test_no_igpu(self):
        with mock.patch.object(hw, "nvidia_outputs", return_value=0):
            self.assertEqual(hw.dgpu_off_blocker(devices(igpu=False)), "err.gpuOffNoIgpu")

    def test_display_on_card(self):
        with mock.patch.object(hw, "nvidia_outputs", return_value=1):
            self.assertEqual(hw.dgpu_off_blocker(devices()), "err.gpuOffDisplay")

    def test_safe(self):
        with mock.patch.object(hw, "nvidia_outputs", return_value=0):
            self.assertIsNone(hw.dgpu_off_blocker(devices()))

    def test_unreadable_outputs_is_not_a_block(self):
        # DXGI okunamadi (None): tumlesik grafik calisiyorsa engel sayilmaz
        with mock.patch.object(hw, "nvidia_outputs", return_value=None):
            self.assertIsNone(hw.dgpu_off_blocker(devices()))


class ConfigTest(unittest.TestCase):
    def test_flag_survives_restart(self):
        import control_center as cc
        self.assertTrue(cc.sanitize_cc({"gpu_off": True}).get("gpu_off"))
        self.assertNotIn("gpu_off", cc.sanitize_cc({"gpu_off": "evet"}))
        self.assertNotIn("gpu_off", cc.sanitize_cc({}))

    def test_user_fan_curve_survives_restart(self):
        import control_center as cc
        u = {"cpu": [62, 35, 82, 80], "gpu": [58, 30, 78, 75]}
        out = cc.sanitize_cc({"fan_sel": "user", "fan_user": u})
        self.assertEqual(out["fan_sel"], "user")
        self.assertEqual(out["fan_user"], u)
        # secim kapaliyken egri yine saklanir
        out = cc.sanitize_cc({"fan_user": u})
        self.assertNotIn("fan_sel", out)
        self.assertEqual(out["fan_user"], u)
        # bozuk egri atilir, secim de onunla gider
        out = cc.sanitize_cc({"fan_sel": "user", "fan_user": {"cpu": [1, 2]}})
        self.assertNotIn("fan_user", out)
        self.assertNotIn("fan_sel", out)
        self.assertNotIn("fan_sel", cc.sanitize_cc({"fan_sel": "baska"}))


if __name__ == "__main__":
    unittest.main()
