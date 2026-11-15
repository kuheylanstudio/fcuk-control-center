# -*- coding: utf-8 -*-
"""Guncelleyicinin Authenticode yayinci denetimi (guncelleme.signer_ok, Updater.install)."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import guncelleme as g  # noqa: E402

ME = {"status": "Valid", "subject": "CN=Kuheylan Studio, O=Kuheylan Studio"}
OTHER = {"status": "Valid", "subject": "CN=Baskasi"}
UNSIGNED = {"status": "NotSigned", "subject": ""}


class SignerOk(unittest.TestCase):
    def test_unsigned_current_skips_check(self):
        self.assertEqual(g.signer_ok(UNSIGNED, UNSIGNED), (True, ""))
        self.assertTrue(g.signer_ok(OTHER, {"status": "Unknown", "subject": ""})[0])

    def test_same_publisher(self):
        self.assertTrue(g.signer_ok(dict(ME, subject=ME["subject"].upper()), ME)[0])

    def test_rejects_unsigned_or_other(self):
        self.assertFalse(g.signer_ok(UNSIGNED, ME)[0])
        self.assertFalse(g.signer_ok({"status": "HashMismatch", "subject": ME["subject"]}, ME)[0])
        self.assertFalse(g.signer_ok(OTHER, ME)[0])


class Install(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.file = os.path.join(self.dir, "FCUK-Control-Center-Setup-9.0.0.exe")
        with open(self.file, "wb") as f:
            f.write(b"x" * 10)
        self.u = g.Updater("2.6.0", self.dir, can_install=True, is_admin=lambda: False)
        self.u.asset = {"name": os.path.basename(self.file), "url": "", "size": 10, "digest": g.sha256(self.file)}
        self.u.state, self.u.file, self.u.latest = "ready", self.file, "9.0.0"

    def test_other_publisher_not_started(self):
        sigs = {self.file: OTHER, self.u.current_exe: ME}
        self.u.signature = lambda p: sigs[p]
        with mock.patch("ctypes.windll.shell32.ShellExecuteW") as run:
            ok, why = self.u.install()
        self.assertFalse(ok)
        self.assertIn("yayıncı", why)
        self.assertEqual(self.u.state, "error")
        run.assert_not_called()

    def test_same_publisher_started(self):
        self.u.signature = lambda p: ME
        with mock.patch("ctypes.windll.shell32.ShellExecuteW", return_value=42) as run:
            ok, why = self.u.install()
        self.assertEqual((ok, why), (True, ""))
        run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
