# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""Uygulamaya gore profil: kural temizleme ve app_step durum makinesi. Donanima dokunmaz.

    python -m unittest discover -s tests
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import profiller  # noqa: E402


def manager(rules, profile="sessiz_kullanim", apps_on=True):
    """apply() yerine cagrilari kaydeden sahte bir Manager (EC, fan, islemci adimlari calismaz)."""
    m = profiller.Manager.__new__(profiller.Manager)
    m.cfg = {"profile": profile, "apps": profiller.clean_apps(rules), "apps_on": apps_on}
    m.applied = profile
    m.app = m._app_rule = m._app_prev = m._app_applied = ""
    m.calls = []

    def apply(pid, reason="reason.manual", persist=True):
        m.calls.append((pid, reason, persist))
        m.applied = pid
        if persist:
            m.cfg["profile"] = pid
    m.apply = apply
    return m


class CleanTest(unittest.TestCase):
    def test_clean_exe(self):
        c = profiller.clean_exe
        self.assertEqual(c("Valorant.exe"), "valorant.exe")
        self.assertEqual(c(r'"C:\Games\Riot\VALORANT.exe"'), "valorant.exe")
        self.assertEqual(c("C:/Games/cs2.exe"), "cs2.exe")
        self.assertEqual(c("  eldenring  "), "eldenring.exe")
        self.assertEqual(c("Cyberpunk 2077.exe"), "cyberpunk 2077.exe")
        for bad in ("", "   ", ".exe", "a*b.exe", "a?.exe", 'a"b.exe', "x" * 90 + ".exe", None, 5, ["a.exe"]):
            self.assertEqual(c(bad), "", bad)

    def test_clean_apps(self):
        raw = [{"exe": "A.exe", "profile": "ultra"}, {"exe": "a.exe", "profile": "sessiz_kullanim"},  # tekrar
               {"exe": "b.exe", "profile": "yok"}, {"exe": "", "profile": "ultra"}, "metin", None,
               {"exe": "c", "profile": "tam_sessiz"}]
        self.assertEqual(profiller.clean_apps(raw),
                         [{"exe": "a.exe", "profile": "ultra"}, {"exe": "c.exe", "profile": "tam_sessiz"}])
        self.assertEqual(profiller.clean_apps("bozuk"), [])
        many = [{"exe": "o%d.exe" % i, "profile": "ultra"} for i in range(100)]
        self.assertEqual(len(profiller.clean_apps(many)), profiller.APP_MAX)

    def test_defaults_have_apps(self):
        self.assertEqual(profiller.DEFAULTS["apps"], [])
        self.assertTrue(profiller.DEFAULTS["apps_on"])


class StepTest(unittest.TestCase):
    def test_start_and_close_restores(self):
        m = manager([{"exe": "game.exe", "profile": "ultra"}])
        m.app_step({"explorer.exe"})
        self.assertEqual(m.calls, [])
        m.app_step({"explorer.exe", "game.exe"})
        self.assertEqual(m.calls, [("ultra", ("reason.app", {"app": "game.exe"}), False)])
        self.assertEqual(m.app, "game.exe")
        self.assertEqual(m.cfg["profile"], "sessiz_kullanim")  # kural kayitli profili degistirmez
        m.app_step({"game.exe"})  # hala acik: yeniden uygulanmaz
        self.assertEqual(len(m.calls), 1)
        m.app_step({"explorer.exe"})
        self.assertEqual(m.calls[-1], ("sessiz_kullanim", ("reason.appClosed", {"app": "game.exe"}), True))
        self.assertEqual(m.app, "")
        self.assertEqual(m.applied, "sessiz_kullanim")

    def test_manual_change_is_kept(self):
        m = manager([{"exe": "game.exe", "profile": "ultra"}])
        m.app_step({"game.exe"})
        m.apply("sessiz_oyun")  # kullanici oyun sirasinda elle secti
        m.app_step({"game.exe"})
        self.assertEqual(m.applied, "sessiz_oyun")  # kural ezmez
        m.app_step(set())
        self.assertEqual(m.applied, "sessiz_oyun")  # kapaninca da geri donulmez
        self.assertEqual(len(m.calls), 2)

    def test_priority_and_switch(self):
        m = manager([{"exe": "a.exe", "profile": "ultra"}, {"exe": "b.exe", "profile": "tam_sessiz"}])
        m.app_step({"b.exe"})
        self.assertEqual(m.applied, "tam_sessiz")
        m.app_step({"a.exe", "b.exe"})  # ustteki kural da acildi: o kazanir
        self.assertEqual(m.applied, "ultra")
        self.assertEqual(m.app, "a.exe")
        m.app_step({"b.exe"})
        self.assertEqual(m.applied, "tam_sessiz")
        m.app_step(set())
        self.assertEqual(m.applied, "sessiz_kullanim")  # ilk uygulamadan onceki profil hatirlandi

    def test_ac_only_downgrade_still_owned(self):
        m = manager([{"exe": "game.exe", "profile": "ultra"}])
        real = m.apply

        def battery_apply(pid, reason="reason.manual", persist=True):  # pilde Ultra -> Performans
            real("performans" if pid == "ultra" else pid, reason, persist)
        m.apply = battery_apply
        m.app_step({"game.exe"})
        self.assertEqual(m.applied, "performans")
        self.assertTrue(m._app_owns())
        m.app_step(set())
        self.assertEqual(m.applied, "sessiz_kullanim")

    def test_disable_and_remove_rule_restore(self):
        m = manager([{"exe": "game.exe", "profile": "ultra"}])
        m.app_step({"game.exe"})
        m.cfg["apps_on"] = False
        m.app_step({"game.exe"})
        self.assertEqual(m.applied, "sessiz_kullanim")
        m.cfg["apps_on"] = True
        m.app_step({"game.exe"})
        self.assertEqual(m.applied, "ultra")
        m.cfg["apps"] = []
        m.app_step({"game.exe"})
        self.assertEqual(m.applied, "sessiz_kullanim")

    def test_no_previous_profile(self):
        m = manager([{"exe": "game.exe", "profile": "ultra"}], profile="")
        m.app_step({"game.exe"})
        m.app_step(set())
        self.assertEqual(m.applied, "ultra")  # once profil yoktu: geri donulecek bir sey yok
        self.assertEqual(m.app, "")


if __name__ == "__main__":
    unittest.main()
