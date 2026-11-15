# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""Oyun ici gosterge: olcumlerden gosterge gruplarina donusum, ayar dogrulama ve FPS hesabi (pencere acilmaz)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ceviri  # noqa: E402
import gosterge  # noqa: E402
import kare  # noqa: E402
import profiller  # noqa: E402

FULL = {"cpu_temp": 78, "cpu_power": 45.3, "cpu_mhz": 4820, "cpu_load": 37.5, "gpu_state": "active",
        "gpu_temp": 88, "gpu_power": 95, "gpu_clock": 2205, "gpu_mem_clock": 8001, "gpu_load": 97,
        "gpu_vram_used": 6350, "gpu_vram_total": 8192, "fps": 125.0, "cpu_rpm": 4200, "gpu_rpm": 4100,
        "ram_used": 12.4, "ram_total": 32, "battery_pct": 10, "battery_ac": False}


class BuildTest(unittest.TestCase):
    def setUp(self):
        ceviri.set_lang("en")

    def test_default_items(self):
        groups = gosterge.build(FULL, profiller.OVERLAY_DEFAULT, "Ultra")
        self.assertEqual([g[0] for g in groups], ["cpu", "gpu", "plan"])
        cpu = groups[0][2]
        self.assertEqual([(c[0], c[1]) for c in cpu], [("78", "°C"), ("45", "W")])
        self.assertEqual(groups[1][2][0][2], gosterge.C_OFF)  # 88 C kart: sicak
        self.assertEqual(groups[2][2][0][0], "Ultra")

    def test_all_items_order_and_units(self):
        groups = gosterge.build(FULL, profiller.OVERLAY_ITEMS, "Ultra")
        self.assertEqual([g[0] for g in groups], ["fps", "cpu", "gpu", "sys", "sys", "sys", "sys", "plan"])
        self.assertEqual(groups[0][2][0][0], "125")  # FPS ve kare suresi en basta
        self.assertEqual(groups[0][2][1][0], ceviri.num(8.0, 1))  # 1000/125 ms
        self.assertEqual([c[1] for c in groups[1][2]], ["°C", "W", "MHz", "%"])
        self.assertEqual(groups[1][2][2][0], ceviri.num(4820))
        self.assertEqual([c[1] for c in groups[2][2]], ["°C", "W", "MHz", "MHz", "%", "GB"])
        self.assertEqual(groups[5][2][0][2], gosterge.C_OFF)  # pilde %10: kirmizi

    def test_missing_values_keep_slot(self):
        groups = gosterge.build({"gpu_state": "sleep", "gpu_temp": 50}, ["cpu_temp", "gpu_temp", "fps"])
        self.assertEqual([g[0] for g in groups], ["fps", "cpu", "gpu"])
        self.assertEqual(len(groups), 3)
        for g in groups:
            self.assertEqual(g[2][0][0], gosterge.DASH)
            self.assertEqual(g[2][0][2], gosterge.C_DIM)

    def test_template_covers_value(self):
        """Kalip, olagan en genis degerden kisa olmamali (gosterge zipmasin)."""
        for _, _, cells in gosterge.build(FULL, profiller.OVERLAY_ITEMS, "Ultra"):
            for v, _, _, tm in cells:
                self.assertGreaterEqual(len(tm), len(v), (v, tm))

    def test_colors(self):
        self.assertEqual(gosterge.level_color(None, 80, 90), gosterge.C_VALUE)
        self.assertEqual(gosterge.level_color(85, 80, 90), gosterge.C_WARN)
        self.assertEqual(gosterge.level_color(79, 80, 90), gosterge.C_VALUE)


class CleanOverlayTest(unittest.TestCase):
    def test_items_filtered_and_ordered(self):
        out = profiller.clean_overlay({"overlay_items": ["fps", "bogus", "cpu_temp", 5]}, {})
        self.assertEqual(out["overlay_items"], ["fps", "cpu_temp"])

    def test_empty_falls_back_to_default(self):
        out = profiller.clean_overlay({"overlay_items": []}, {})
        self.assertEqual(out["overlay_items"], profiller.OVERLAY_DEFAULT)

    def test_options(self):
        out = profiller.clean_overlay({"overlay_corner": "tc", "overlay_layout": "panel", "overlay_size": "xl",
                                       "overlay_opacity": 5}, {})
        self.assertEqual(out, {"overlay_corner": "tc", "overlay_layout": "panel", "overlay_size": "xl",
                               "overlay_opacity": 40})
        self.assertEqual(profiller.clean_overlay({"overlay_corner": "x", "overlay_opacity": True}, {}), {})


class FpsTest(unittest.TestCase):
    F = 10_000_000  # QPC frekansi (100 ns)

    def test_steady_rate(self):
        stamps = [i * self.F // 120 for i in range(240)]  # 2 sn, 120 FPS
        self.assertAlmostEqual(kare.fps_from(stamps, self.F, stamps[-1]), 120, delta=0.5)

    def test_stale_and_too_few(self):
        stamps = [0, self.F // 60]
        self.assertIsNone(kare.fps_from(stamps, self.F, stamps[-1] + 3 * self.F))
        self.assertIsNone(kare.fps_from([5], self.F, 5))

    def test_batched_delivery_does_not_matter(self):
        """Olaylar toplu gelse de (ETW tamponu) sonuc zaman damgalarindan: okuma ani 0,8 sn sonra."""
        stamps = [i * self.F // 60 for i in range(120)]
        self.assertAlmostEqual(kare.fps_from(stamps, self.F, stamps[-1] + int(0.8 * self.F)), 60, delta=0.5)

    def test_event_filter_layout(self):
        self.assertEqual(bytes(kare._event_filter([42, 55])), b"\x01\x00\x02\x00\x2a\x00\x37\x00")


if __name__ == "__main__":
    unittest.main()
