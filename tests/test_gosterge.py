# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""Oyun ici gosterge: olcumlerden serit parcalarina donusum (pencere acilmaz)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ceviri  # noqa: E402
import gosterge  # noqa: E402


class SegmentsTest(unittest.TestCase):
    def setUp(self):
        ceviri.set_lang("en")

    def test_full(self):
        segs = gosterge.segments({"cpu_temp": 78, "cpu_power": 45.3, "gpu_state": "active", "gpu_temp": 88,
                                  "gpu_power": 95, "cpu_rpm": 4200, "gpu_rpm": 0}, "Ultra")
        self.assertEqual([s[0] for s in segs], ["CPU", "GPU", "Fan", ""])
        self.assertEqual(segs[0][1], "78°  45 W")
        self.assertEqual(segs[1][2], gosterge.C_OFF)  # 88 C kart: sicak
        self.assertEqual(segs[2][1], ceviri.num(4200))
        self.assertEqual(segs[3][1], "Ultra")

    def test_gpu_asleep_and_empty(self):
        segs = gosterge.segments({"cpu_temp": 50, "gpu_state": "sleep", "gpu_temp": 0})
        self.assertEqual(len(segs), 1)
        self.assertEqual(gosterge.segments({})[0][0], ceviri.t("ovl.noData"))

    def test_colors(self):
        self.assertEqual(gosterge.level_color(None, 80, 90), gosterge.C_VALUE)
        self.assertEqual(gosterge.level_color(85, 80, 90), gosterge.C_WARN)
        self.assertEqual(gosterge.level_color(79, 80, 90), gosterge.C_VALUE)


if __name__ == "__main__":
    unittest.main()
