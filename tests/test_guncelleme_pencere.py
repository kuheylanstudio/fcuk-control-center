# -*- coding: utf-8 -*-
"""Bagimsiz guncelleme penceresi: setup.exe adim eslemesi (kurulum/setup.py) ve motorun kurulum durumlari
(guncelleme.Updater: izin bekleme, UAC reddi, baslamayan kurulum)."""
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "kurulum"))
import guncelleme as g  # noqa: E402
import setup as kurulum  # noqa: E402

SIGNED = {"status": "Valid", "subject": "CN=Ben"}


class Adimlar(unittest.TestCase):
    def test_script_steps_map_in_order(self):
        steps = [
            ("AcpiBridge sürücüleri yedekleniyor", 0),
            ("Eski Control Center taranıyor", 0),
            ("Çalışan FCUK Control Center kapatılıyor", 1),
            ("Dosyalar kopyalanıyor: C:\\Program Files\\FCUK Control Center", 2),
            ("Windows açılış görevleri kuruluyor (motor yönetici, tepsi normal yetki)", 3),
            ("Kısayollar ve Uygulamalar listesi kaydı", 3),
            ("Başlatılıyor ve doğrulanıyor", 4),
        ]
        cur = 0
        for text, want in steps:
            cur = kurulum.update_step(text, cur)
            self.assertEqual(cur, want, text)

    def test_step_never_goes_back(self):
        self.assertEqual(kurulum.update_step("Çalışan FCUK Control Center kapatılıyor", 3), 3)
        self.assertEqual(kurulum.update_step("", 2), 2)
        self.assertEqual(kurulum.update_step(None, 1), 1)

    def test_unknown_step_keeps_current(self):
        self.assertEqual(kurulum.update_step("Sürücüler geri yükleniyor", 1), 1)

    def test_progress_starts_increase(self):
        starts = [s[1] for s in kurulum.UPDATE_STEPS]
        self.assertEqual(starts, sorted(starts))
        self.assertLess(starts[-1], 100)

    def test_titles_match_app_window_lookup(self):
        import pencere
        self.assertEqual(pencere.UPDATE_TITLE, kurulum.UPDATE_TITLE)


class Motor(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.file = os.path.join(self.dir, "FCUK-Control-Center-Setup-9.0.0.exe")
        with open(self.file, "wb") as f:
            f.write(b"x" * 10)
        self.u = g.Updater("2.6.0", self.dir, can_install=True, is_admin=lambda: False)
        self.u.asset = {"name": os.path.basename(self.file), "url": "", "size": 10, "digest": g.sha256(self.file)}
        self.u.state, self.u.file, self.u.latest = "ready", self.file, "9.0.0"
        self.u.signature = lambda p: SIGNED

    def test_uses_update_window_flag(self):
        self.assertEqual(g.SETUP_ARGS, "/guncelle")
        with mock.patch("ctypes.windll.shell32.ShellExecuteW", return_value=42) as run:
            self.u.install()
        self.assertEqual(run.call_args[0][3], "/guncelle")

    def test_waits_for_permission_then_installing(self):
        seen = []

        def uac(*a):
            seen.append(self.u.status()["state"])  # UAC penceresi acikken arayuz izin ister
            return 42
        with mock.patch("ctypes.windll.shell32.ShellExecuteW", side_effect=uac):
            ok, _ = self.u.install()
        self.assertTrue(ok)
        self.assertEqual(seen, ["permission"])
        self.assertEqual(self.u.status()["state"], "installing")

    def test_uac_denied_returns_to_ready(self):
        with mock.patch("ctypes.windll.shell32.ShellExecuteW", return_value=5):
            ok, why = self.u.install()
        self.assertFalse(ok)
        self.assertIn("izni", why)
        self.assertEqual(self.u.status()["state"], "ready")  # arayuz yeniden deneyebilsin
        self.assertTrue(self.u.status()["error"])

    def test_check_does_not_interrupt_permission(self):
        self.u.state = "permission"
        self.assertEqual(self.u.check()["state"], "permission")

    def test_install_that_never_starts_recovers(self):
        self.u.state, self.u.installing_at = "installing", time.time() - g.INSTALL_TIMEOUT - 1
        st = self.u.status()
        self.assertEqual(st["state"], "ready")
        self.assertIn("başlamadı", st["error"])

    def test_running_install_not_reset_early(self):
        self.u.state, self.u.installing_at = "installing", time.time() - 30
        self.assertEqual(self.u.status()["state"], "installing")


if __name__ == "__main__":
    unittest.main()
