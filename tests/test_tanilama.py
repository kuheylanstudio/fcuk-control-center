# -*- coding: utf-8 -*-
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tanilama  # noqa: E402

ENV = {"USERNAME": "ayse", "COMPUTERNAME": "OYUN-PC"}


class Redact(unittest.TestCase):
    def test_home_user_host_removed(self):
        with mock.patch.dict(os.environ, ENV), mock.patch("os.path.expanduser", return_value=r"C:\Users\ayse"):
            out = tanilama.redact(r"C:\Users\ayse\AppData x OYUN-PC; ayse giris")
        self.assertNotIn("ayse", out.lower())
        self.assertNotIn("oyun-pc", out.lower())
        self.assertIn("%USERPROFILE%", out)
        self.assertIn("<bilgisayar>", out)
        self.assertIn("<kullanici>", out)

    def test_word_boundary(self):
        with mock.patch.dict(os.environ, ENV), mock.patch("os.path.expanduser", return_value=r"C:\Users\ayse"):
            self.assertEqual(tanilama.redact("ayseler"), "ayseler")


class Logs(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".log")
        os.close(fd)
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("\n".join(["satir %d" % i for i in range(100)] + ["DCHU hata: zaman asimi", "Traceback (most recent call last):", "son"]))

    def tearDown(self):
        os.remove(self.path)

    def test_tail(self):
        self.assertEqual(tanilama.tail(self.path, 2), ["Traceback (most recent call last):", "son"])
        self.assertEqual(tanilama.tail(self.path + ".yok"), [])

    def test_errors(self):
        self.assertEqual(tanilama.errors(self.path), ["DCHU hata: zaman asimi", "Traceback (most recent call last):"])
        self.assertEqual(tanilama.errors(self.path, 1), ["Traceback (most recent call last):"])


class Build(unittest.TestCase):
    def test_report(self):
        with mock.patch.dict(os.environ, ENV):
            text = tanilama.build({"surum": "2.7.0", "model": "OYUN-PC", "bos": None},
                                  [{"id": "fan", "state": "ok", "label": "Fan"},
                                   {"id": "gpu", "state": "missing", "why": "NVML yok"}],
                                  ["a", "b"])
        self.assertRegex(text, r"surum +: 2.7.0")
        self.assertIn("[ok     ] Fan", text)
        self.assertIn("[missing] gpu - NVML yok", text)
        self.assertIn("Gunluk (son 2 satir)", text)
        self.assertNotIn("OYUN-PC", text)
        self.assertTrue(text.endswith("b\n"))


if __name__ == "__main__":
    unittest.main()
