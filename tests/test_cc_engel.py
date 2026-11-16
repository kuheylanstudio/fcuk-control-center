# -*- coding: utf-8 -*-
"""Eski Control Center geri yukleme engeli: kurulum secenegi (kurulum/setup.py) ve motor bekcisi (engelle.py)."""
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "kurulum"))
import engelle  # noqa: E402
import setup as kurulum  # noqa: E402


class KurulumAdimlari(unittest.TestCase):
    def test_install_steps_map_in_order(self):
        steps = [
            ("Sistem geri yükleme noktası oluşturuluyor", 0),
            ("AcpiBridge sürücüleri yedekleniyor", 0),
            ("Eski Control Center taranıyor", 0),
            ("Çalışan FCUK Control Center kapatılıyor", 1),
            ("Eski Fn / Control Center programları tam yollarıyla engelleniyor", 1),
            ("AcpiBridge sürücüleri ve donanım hizmeti doğrulanıyor", 1),
            ("Dosyalar kopyalanıyor: C:\\Program Files\\FCUK Control Center", 2),
            ("Windows açılış görevleri kuruluyor (motor yönetici, tepsi normal yetki)", 3),
            ("Eski Control Center geri yükleme engeli", 3),
            ("Başlatılıyor ve doğrulanıyor", 4),
        ]
        cur = 0
        for text, want in steps:
            cur = kurulum.update_step(text, cur, kurulum.INSTALL_STEPS)
            self.assertEqual(cur, want, text)

    def test_progress_starts_increase(self):
        starts = [s[1] for s in kurulum.INSTALL_STEPS]
        self.assertEqual(starts, sorted(starts))
        self.assertEqual(len(kurulum.INSTALL_STEPS), len(kurulum.UPDATE_STEPS))


class KurulumBayragi(unittest.TestCase):
    def _cmd(self, **kw):
        with mock.patch("subprocess.Popen") as p:
            p.return_value.stdout = []
            p.return_value.wait.return_value = 0
            kurulum.run_script("Install", lambda k, m: None, **kw)
        return p.call_args[0][0]

    def test_guard_on_off_keep(self):
        on = self._cmd(guard=True)
        self.assertEqual(on[on.index("-CCGuard") + 1], "On")
        off = self._cmd(guard=False)
        self.assertEqual(off[off.index("-CCGuard") + 1], "Off")
        self.assertNotIn("-CCGuard", self._cmd())  # guncelleme: onceki secim korunur


class Bekci(unittest.TestCase):
    def test_off_does_nothing(self):
        with mock.patch.object(engelle, "guard_enabled", return_value=False), \
                mock.patch.object(engelle, "_ps") as ps:
            self.assertEqual(engelle.guard_check(), ([], []))
        ps.assert_not_called()

    def test_nothing_returned(self):
        with mock.patch.object(engelle, "guard_enabled", return_value=True), \
                mock.patch.object(engelle, "_ps", return_value=[]) as ps, \
                mock.patch.object(engelle, "refresh") as ref:
            self.assertEqual(engelle.guard_check(), ([], []))
        self.assertEqual(ps.call_count, 1)
        ref.assert_not_called()

    def test_returned_package_blocked_then_removed(self):
        calls = []
        found = ["PKG|CLEVOCO.FnhotkeysandOSD|CLEVOCO.FnhotkeysandOSD_7.2.0.0_x64__6h6z29zh29qx0",
                 "PKG|CLEVOCO.CPUOverclocking|CLEVOCO.CPUOverclocking_1.0.0.0_x64__6h6z29zh29qx0",  # kapsam disi
                 "garip satir"]

        def ps(script, env, timeout=120):
            calls.append(env)
            return found if "FCUK_PKGS" in env else ["OK|CLEVOCO.FnhotkeysandOSD"]

        order = []
        with mock.patch.object(engelle, "guard_enabled", return_value=True), \
                mock.patch.object(engelle, "_ps", side_effect=ps), \
                mock.patch.object(engelle, "refresh", side_effect=lambda: order.append("ifeo") or (3, [])):
            removed, lines = engelle.guard_check()
        self.assertEqual(removed, ["CLEVOCO.FnhotkeysandOSD"])
        self.assertEqual(order, ["ifeo"])  # once tam yol engeli, sonra kaldirma
        self.assertNotIn("CPUOverclocking", calls[1]["FCUK_ITEMS"])  # dokunulmayacak paketler kaldirilmaz
        self.assertTrue(any("kaldirildi" in l for l in lines))

    def test_scope_excludes_kept_packages(self):
        for kept in ("CLEVOCO.CPUOverclocking", "CLEVOCO.GPUOverclocking", "CLEVOCO.Flexikey",
                     "CLEVOCO.BatteryPackUtility"):
            self.assertNotIn(kept, engelle.REPLACED)

    def test_replaced_matches_installer(self):
        with open(os.path.join(ROOT, "kurulum", "kurulum.ps1"), encoding="utf-8-sig") as f:
            src = f.read()
        block = src.split("$Replaced = [ordered]@{", 1)[1].split("}", 1)[0]
        names = [l.split("'")[1] for l in block.splitlines() if l.strip().startswith("'")]
        self.assertEqual(sorted(names), sorted(engelle.REPLACED))


if __name__ == "__main__":
    unittest.main()
