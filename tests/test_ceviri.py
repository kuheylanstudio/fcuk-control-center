# -*- coding: utf-8 -*-
"""Ceviri dosyalari tutarli mi (tools/ceviri_denetle.py): eksik / fazla anahtar, yer tutucu, koddaki anahtarlar."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import ceviri_denetle  # noqa: E402


class Ceviri(unittest.TestCase):
    def test_languages_consistent(self):
        problems, _ = ceviri_denetle.check()
        self.assertEqual(problems[:20], [], "%d ceviri sorunu (python tools/ceviri_denetle.py)" % len(problems))

    def test_finds_used_keys(self):
        keys = ceviri_denetle.used_keys()
        self.assertIn("diag.save", keys)
        self.assertFalse(any(k.endswith(".") for k in keys))


if __name__ == "__main__":
    unittest.main()
