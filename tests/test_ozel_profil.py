# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""Ozel profiller: dogrulama, PROFILES'a yerlestirme, mutlak tavanlar. Donanima dokunmaz."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import profiller  # noqa: E402


class CustomTest(unittest.TestCase):
    def tearDown(self):
        profiller.set_custom([])

    def test_curve_limits(self):
        c = profiller.clean_curve
        self.assertEqual(c([60, 40, 80, 90]), (60, 40, 80, 90))
        self.assertEqual(c([10, -5, 200, 10]), (40, 0, 95, 30))   # sinirlar ve en az %30 tam devir
        self.assertEqual(c([85, 90, 70, 50]), (85, 50, 90, 50))    # ters sira duzeltilir, D2 <= D3
        with self.assertRaises(ValueError):
            c([True, 1, 2, 3])
        with self.assertRaises(ValueError):
            c(["60", 1, 2, 3])

    def test_clean_and_ids(self):
        raw = [{"name": " A  b ", "fan": "auto"}, {"id": "ozel1", "name": "x", "fan": "max"},
               {"name": "", "fan": "auto"},                         # adsiz: atlanir, kimlik harcamaz
               {"name": "y", "fan": {"cpu": [60, 30, 80, 70]}}, {"name": "fazla", "fan": "auto"},
               {"name": "bozuk", "fan": {"cpu": [1, 2]}}, "metin"]
        out = profiller.clean_custom(raw)
        self.assertEqual([(x["id"], x["name"]) for x in out], [("ozel2", "A b"), ("ozel1", "x"), ("ozel3", "y")])
        self.assertEqual(out[2]["fan"]["gpu"], [60, 30, 80, 70])  # kart egrisi verilmezse islemcininki
        self.assertEqual(out[0]["base"], "sessiz_oyun")           # bilinmeyen temel -> varsayilan

    def test_minimum_caps(self):
        out = profiller.clean_custom([{"name": "a", "fan": "auto", "fmax_p": 100, "fmax_e": 0, "gpu_max": 50,
                                       "boost": 9, "epp": -3}])[0]
        self.assertEqual((out["fmax_p"], out["fmax_e"], out["gpu_max"]), (800, 0, 300))
        self.assertEqual((out["boost"], out["epp"]), (4, 0))

    def test_set_custom_and_build(self):
        built = profiller.set_custom([{"name": "Gece", "base": "ultra", "fan": {"cpu": [55, 40, 75, 80]},
                                       "boost": 3, "epp": 20, "fmax_p": 3000, "gpu_max": 1200, "refresh": "min"}])
        p = profiller.BY_ID["ozel1"]
        self.assertIs(p, built[0])
        self.assertEqual(profiller.name("ozel1"), "Gece")
        self.assertEqual(p["ec"], profiller.BY_ID["ultra"]["ec"])
        self.assertTrue(p["ac_only"])
        self.assertEqual(p["fan"], ("curve", (55, 40, 75, 80), (55, 40, 75, 80)))
        self.assertEqual(profiller.cpu_caps(p["cpu"]), (3000, 0))      # mutlak: olceklenmez
        self.assertEqual(profiller.gpu_caps(p["gpu"], absolute=True), (210, 1200))
        self.assertEqual(profiller.spec(p)["gpu_max"], 1200)
        self.assertEqual(len(profiller.PROFILES), len(profiller.BUILTIN) + 1)
        profiller.set_custom([])
        self.assertNotIn("ozel1", profiller.BY_ID)
        self.assertEqual(profiller.PROFILES, profiller.BUILTIN)

    def test_app_rules_accept_custom(self):
        profiller.set_custom([{"id": "ozel2", "name": "G", "fan": "auto"}])
        rules = profiller.clean_apps([{"exe": "g.exe", "profile": "ozel2"}, {"exe": "h.exe", "profile": "ozel3"}])
        self.assertEqual(rules, [{"exe": "g.exe", "profile": "ozel2"}])


if __name__ == "__main__":
    unittest.main()
