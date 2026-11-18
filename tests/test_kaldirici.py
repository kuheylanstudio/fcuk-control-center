# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""Kaldirici: ad isleme, kaldirici komutu, artik taramasi ve korumalar. Gercek kayit defterine ve diske
dokunmaz: sahte kayit defteri ve gecici klasorler kullanilir; hicbir sey silinmez."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import kaldirici as k  # noqa: E402

U = k.UNINSTALL_ROOTS[0]
U32 = k.UNINSTALL_ROOTS[1]


class FakeReg:
    """{'HKCU\\Software\\X': {'deger': 1}} bicimli sahte kayit defteri; ust anahtarlar kendiliginden vardir."""

    def __init__(self, keys):
        self.keys = {}
        for path, vals in keys.items():
            parts = path.split("\\")
            for i in range(1, len(parts)):
                sub = "\\".join(parts[:i])
                self.keys.setdefault(sub.lower(), (sub, {}))
            self.keys[path.lower()] = (path, dict(vals))

    def subkeys(self, path):
        low = path.lower() + "\\"
        out = set()
        for p, (orig, _) in self.keys.items():
            if p.startswith(low):
                out.add(orig[len(low):].split("\\")[0])
        return sorted(out)

    def values(self, path):
        return dict(self.keys.get(path.lower(), ("", {}))[1])

    def exists(self, path):
        return path.lower() in self.keys


def entry(name, publisher="", location="", uninstall="", **extra):
    v = {"DisplayName": name, "Publisher": publisher, "InstallLocation": location,
         "UninstallString": uninstall or (r'"%s\unins000.exe"' % location if location else "")}
    v.update(extra)
    return v


class NameTest(unittest.TestCase):
    def test_clean_name(self):
        self.assertEqual(k.clean_name("7-Zip 23.01 (x64)"), "7-Zip")
        self.assertEqual(k.clean_name("Mozilla Firefox (x64 en-US)"), "Mozilla Firefox")
        self.assertEqual(k.clean_name("HandBrake 1.11.2"), "HandBrake")
        self.assertEqual(k.clean_name("Blender"), "Blender")

    def test_clean_publisher(self):
        self.assertEqual(k.clean_publisher("Discord Inc."), "Discord")
        self.assertEqual(k.clean_publisher("Epic Games, Inc."), "Epic Games")
        self.assertEqual(k.clean_publisher("Valve Corporation"), "Valve")

    def test_candidates(self):
        c = k.candidates({"name": "Mozilla Firefox (x64 en-US)", "publisher": "Mozilla", "key": "Mozilla Firefox 120.0 (x64 en-US)",
                          "location": r"C:\Program Files\Mozilla Firefox"})
        self.assertIn("firefox", c)
        self.assertIn("mozillafirefox", c)
        # genel ve kisa adlar ve GUID'ler eslesmeye girmez
        self.assertEqual(k.candidates({"name": "Update", "key": "{11111111-2222-3333-4444-555555555555}"}), set())
        self.assertEqual(k.candidates({"name": "Go"}), set())

    def test_match_level(self):
        c = {"discord", "hwinfo64"}
        self.assertEqual(k.match_level("Discord", c)[0], k.SAFE)
        self.assertEqual(k.match_level("discord-updater", c)[0], k.MODERATE)
        self.assertEqual(k.match_level("my discord stuff", c)[0], k.ADVANCED)
        self.assertIsNone(k.match_level("Microsoft", c | {"microsoft"})[0])
        self.assertIsNone(k.match_level("Spotify", c)[0])


class CommandTest(unittest.TestCase):
    def test_split(self):
        self.assertEqual(k.split_command(r'"C:\Program Files\A B\unins000.exe" /SILENT'), (r"C:\Program Files\A B\unins000.exe", "/SILENT"))
        self.assertEqual(k.split_command(r"C:\Program Files\A B\uninstall.exe --x"), (r"C:\Program Files\A B\uninstall.exe", "--x"))
        self.assertEqual(k.split_command(r'"C:\x\u.exe"'), (r"C:\x\u.exe", ""))

    def test_msi_uses_guid(self):
        g = "{0AEFF9A4-32F7-470A-BD1F-4B11511F1FB4}"
        cmd, exe = k.uninstall_command({"uninstall": "MsiExec.exe /I" + g, "key": g, "msi": True})
        self.assertTrue(exe.lower().endswith("msiexec.exe"))
        self.assertTrue(cmd.endswith("/x " + g))  # /I (onar / kur) asla calistirilmaz

    def test_no_uninstaller(self):
        with self.assertRaises(k.Error):
            k.uninstall_command({"uninstall": "", "key": "X"})

    def test_valid_id(self):
        self.assertTrue(k.valid_id(U + "\\Discord"))
        self.assertFalse(k.valid_id(U + "\\Discord\\..\\x"))
        self.assertFalse(k.valid_id("HKLM\\SOFTWARE\\Discord"))
        self.assertFalse(k.valid_id(None))


class ParseTest(unittest.TestCase):
    def test_skips_components_and_updates(self):
        self.assertIsNone(k.parse_entry(U + "\\a", "a", entry("Hotfix", ReleaseType="Update", uninstall="x.exe")))
        self.assertIsNone(k.parse_entry(U + "\\a", "a", entry("Part", SystemComponent=1, uninstall="x.exe")))
        self.assertIsNone(k.parse_entry(U + "\\a", "a", {"DisplayName": "NoUninstall"}))

    def test_guessed_location_needs_app_name(self):
        a = k.parse_entry(U + "\\a", "a", {"DisplayName": "Foo", "UninstallString": r"C:\Tools\bar\uninst.exe"})
        self.assertEqual(a["location"], "")  # klasor adi uygulamayla ilgisiz: kullanilmaz
        b = k.parse_entry(U + "\\a", "a", {"DisplayName": "Foo", "UninstallString": r"C:\Apps\Foo\uninst.exe"})
        self.assertEqual(b["location"], r"C:\Apps\Foo")

    def test_critical(self):
        a = k.parse_entry(U + "\\a", "a", entry("Microsoft Visual C++ 2015 Redistributable", "Microsoft Corporation", uninstall="x.exe"))
        self.assertTrue(a["critical"])
        b = k.parse_entry(U + "\\b", "b", entry("Discord", "Discord Inc.", uninstall="x.exe"))
        self.assertFalse(b["critical"])


class KeyGuardTest(unittest.TestCase):
    def test_allowed(self):
        for p in ("HKCU\\Software\\Discord", "HKCU\\Software\\Epic Games\\EpicGamesLauncher",
                  "HKLM\\SOFTWARE\\WOW6432Node\\AnyDesk", U + "\\Discord",
                  "HKLM\\SYSTEM\\CurrentControlSet\\Services\\AnyDesk", k.APP_PATHS[0] + "\\7zFM.exe"):
            self.assertFalse(k.key_blocked(p), p)

    def test_blocked(self):
        for p in ("HKCU\\Software", "HKLM\\SOFTWARE", "HKCU\\Software\\Microsoft", "HKCU\\Software\\Microsoft\\Teams",
                  "HKCU\\Software\\Classes", "HKCU\\Software\\Classes\\.txt", "HKLM\\SOFTWARE\\Policies\\X",
                  "HKLM\\SOFTWARE\\WOW6432Node", "HKLM\\SYSTEM\\CurrentControlSet", "HKLM\\SOFTWARE\\A\\B\\C",
                  "HKLM\\SYSTEM\\CurrentControlSet\\Services", U):
            self.assertTrue(k.key_blocked(p), p)


class ScanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kaldirici_test_")
        names = {"appdata": "Roaming", "local": "Local", "locallow": "LocalLow", "programdata": "ProgramData",
                 "pf": "PF", "pf86": "PF86", "start_user": "StartU", "start_common": "StartC", "temp": "Temp",
                 "desktop": "Desktop", "public_desktop": "PubDesk", "documents": "Docs", "saved_games": "Saved"}
        self.roots = {key: os.path.join(self.tmp, n) for key, n in names.items()}
        for p in self.roots.values():
            os.makedirs(p)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def r(self, *parts):
        return os.path.join(self.tmp, *parts)

    def mk(self, *parts, file=False):
        p = self.r(*parts)
        if file:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "w").close()
        else:
            os.makedirs(p, exist_ok=True)
        return p

    def run_scan(self, reg_keys, name, mode="moderate", protect=()):
        reg = FakeReg(reg_keys)
        env = k.Env(roots=self.roots, reg=reg, tasks_dir="", protect=protect)
        apps = k.installed_apps(reg)
        app = [a for a in apps if a["name"] == name][0]
        return k.scan(app, mode, env, apps), app

    @staticmethod
    def paths(res, checked=None):
        return {(i["path"], i["name"]) if i["kind"] == "value" else i["path"]
                for i in res["items"] if checked is None or i["checked"] == checked}

    def test_after_uninstall_finds_leftovers(self):
        loc = self.mk("Local", "Discord")
        self.mk("Roaming", "discord", "Cache")
        self.mk("StartU", "Discord.lnk", file=True)
        self.mk("Roaming", "Spotify")
        keys = {U + "\\Discord": entry("Discord", "Discord Inc.", loc),
                "HKCU\\Software\\Discord": {"x": 1},
                "HKCU\\Software\\Spotify": {},
                k.RUN_KEYS[0]: {"Discord": '"%s\\Update.exe" --processStart Discord.exe' % loc, "Spotify": r"C:\s\Spotify.exe"}}
        reg = FakeReg(keys)
        env = k.Env(roots=self.roots, reg=reg, tasks_dir="")
        app = k.installed_apps(reg)[0]
        del reg.keys[(U + "\\Discord").lower()]  # kaldirici kendi kaydini sildi
        res = k.scan(app, "moderate", env, [])
        got = self.paths(res, checked=True)
        self.assertFalse(res["installed"])
        self.assertIn(loc, got)
        self.assertIn(self.r("Roaming", "discord"), got)
        self.assertIn(self.r("StartU", "Discord.lnk"), got)
        self.assertIn("HKCU\\Software\\Discord", got)
        self.assertIn((k.RUN_KEYS[0], "Discord"), got)
        everything = self.paths(res)
        self.assertNotIn(self.r("Roaming", "Spotify"), everything)
        self.assertNotIn("HKCU\\Software\\Spotify", everything)
        self.assertNotIn((k.RUN_KEYS[0], "Spotify"), everything)
        self.assertNotIn(self.r("Roaming", "discord", "Cache"), everything)  # ust klasor zaten listede

    def test_still_installed_nothing_preselected(self):
        loc = self.mk("PF", "Foo")
        res, _ = self.run_scan({U + "\\Foo": entry("Foo App", "Foo Soft", loc)}, "Foo App")
        self.assertTrue(res["installed"])
        self.assertTrue(res["items"])
        self.assertFalse(any(i["checked"] for i in res["items"]))

    def test_roots_and_ancestors_never_proposed(self):
        # kurulum klasoru olarak kok klasor yazan (bozuk) kayit: koke ve ustune dokunulmaz
        res, _ = self.run_scan({U + "\\Bad": entry("Bad App", "", self.roots["pf"])}, "Bad App", "advanced")
        self.assertNotIn(self.roots["pf"], self.paths(res))
        res, _ = self.run_scan({U + "\\Bad": entry("Bad App", "", self.tmp)}, "Bad App", "advanced")
        self.assertNotIn(self.tmp, self.paths(res))

    def test_own_folder_protected(self):
        own = self.mk("PF", "FCUK Control Center")
        res, _ = self.run_scan({U + "\\FCUK": entry("FCUK Control Center", "", own)}, "FCUK Control Center", "advanced", protect=[own])
        self.assertNotIn(own, self.paths(res))

    def test_other_app_folder_protected(self):
        steam = self.mk("PF86", "Steam")
        game = self.mk("PF86", "Steam", "steamapps", "common", "Hades")
        keys = {U32 + "\\Steam": entry("Steam", "Valve Corporation", steam),
                U + "\\Steam App 1145360": entry("Hades", "Supergiant Games", game)}
        res, _ = self.run_scan(keys, "Steam", "advanced")
        self.assertNotIn(steam, self.paths(res))  # icinde baska uygulama (oyun) var

    def test_similar_name_belongs_to_other_app(self):
        self.mk("Roaming", "discord")
        self.mk("Roaming", "discordptb")
        keys = {U + "\\Discord": entry("Discord", "Discord Inc.", self.r("Local", "Discord")),
                U + "\\DiscordPTB": entry("Discord PTB", "Discord Inc.", self.r("Local", "DiscordPTB"))}
        res, _ = self.run_scan(keys, "Discord", "advanced")
        got = self.paths(res)
        self.assertIn(self.r("Roaming", "discord"), got)
        self.assertNotIn(self.r("Roaming", "discordptb"), got)

    def test_shared_vendor_folder_not_used(self):
        # "Intel Wireless" kurulum klasoru olarak ortak Intel klasorunu yaziyor: kullanilmaz
        intel = self.mk("PF86", "Intel")
        self.mk("PF86", "Intel", "Other")
        res, _ = self.run_scan({U + "\\{00000070-0240-1055-84C8-B8D95FA3C8C3}": entry(
            "Intel Wireless Bluetooth", "Intel Corporation", intel, uninstall="x.exe")}, "Intel Wireless Bluetooth", "advanced")
        self.assertNotIn(intel, self.paths(res))

    def test_same_name_other_version_only_advanced_unchecked(self):
        self.mk("Roaming", "Blender Foundation", "Blender")
        keys = {U + "\\{A}": entry("Blender", "Blender Foundation", self.mk("PF", "Blender Foundation", "Blender 4.5"), DisplayVersion="4.5"),
                U + "\\{B}": entry("Blender", "Blender Foundation", self.mk("PF", "Blender Foundation", "Blender 5.3"), DisplayVersion="5.3")}
        reg = FakeReg(keys)
        env = k.Env(roots=self.roots, reg=reg, tasks_dir="")
        apps = k.installed_apps(reg)
        a = [x for x in apps if x["version"] == "4.5"][0]
        mod = k.scan(a, "moderate", env, apps)
        self.assertNotIn(self.r("Roaming", "Blender Foundation", "Blender"), self.paths(mod))
        adv = k.scan(a, "advanced", env, apps)
        shared = [i for i in adv["items"] if "Roaming" in i["path"]]
        self.assertTrue(shared)
        self.assertFalse(any(i["checked"] for i in shared))

    def test_levels(self):
        loc = self.mk("PF", "Foobar")
        self.mk("Roaming", "Foobar")             # birebir: guvenli
        self.mk("LocalLow", "Foobar")            # LocalLow: orta
        self.mk("Roaming", "Foobar-cache")       # on ek: orta, secilmeden
        self.mk("Docs", "My Foobar Projects")    # Belgeler: gelismis
        keys = {U + "\\Foobar": entry("Foobar", "Acme", loc)}
        safe, _ = self.run_scan(keys, "Foobar", "safe")
        mod, _ = self.run_scan(keys, "Foobar", "moderate")
        adv, _ = self.run_scan(keys, "Foobar", "advanced")
        self.assertIn(self.r("Roaming", "Foobar"), self.paths(safe))
        self.assertNotIn(self.r("LocalLow", "Foobar"), self.paths(safe))
        self.assertIn(self.r("LocalLow", "Foobar"), self.paths(mod))
        self.assertIn(self.r("Roaming", "Foobar-cache"), self.paths(mod))
        self.assertNotIn(self.r("Docs", "My Foobar Projects"), self.paths(mod))
        docs = [i for i in adv["items"] if i["path"] == self.r("Docs", "My Foobar Projects")]
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["level"], k.ADVANCED)

    def test_prefix_match_not_preselected(self):
        self.mk("Local", "chrome-devtools-mcp")
        keys = {U + "\\Chrome": entry("Google Chrome", "Google LLC", self.mk("PF", "Google", "Chrome", "Application"))}
        reg = FakeReg(keys)
        env = k.Env(roots=self.roots, reg=reg, tasks_dir="")
        app = k.installed_apps(reg)[0]
        del reg.keys[(U + "\\Chrome").lower()]
        res = k.scan(app, "moderate", env, [])
        hit = [i for i in res["items"] if i["path"] == self.r("Local", "chrome-devtools-mcp")]
        self.assertEqual(len(hit), 1)
        self.assertFalse(hit[0]["checked"])  # yalnizca ad on eki: kullanici kendisi secmeli

    def test_publisher_folder_only_when_all_children_match(self):
        self.mk("LocalLow", "Panik Arcade", "CloverPit")
        self.mk("LocalLow", "Team Cherry", "Hollow Knight")
        self.mk("LocalLow", "Team Cherry", "Silksong")
        keys = {U + "\\a": entry("CloverPit", "Panik Arcade", uninstall="x.exe"),
                U + "\\b": entry("Hollow Knight", "Team Cherry", uninstall="x.exe")}
        res, _ = self.run_scan(keys, "CloverPit")
        self.assertIn(self.r("LocalLow", "Panik Arcade"), self.paths(res))
        self.assertFalse([i for i in res["items"] if i["note"] == "publisher"][0]["checked"])  # oyun kayitlari: secilmeden
        res, _ = self.run_scan(keys, "Hollow Knight")
        got = self.paths(res)
        self.assertIn(self.r("LocalLow", "Team Cherry", "Hollow Knight"), got)
        self.assertNotIn(self.r("LocalLow", "Team Cherry"), got)  # Silksong da orada

    def test_service_only_when_pointing_into_install_folder(self):
        loc = self.mk("PF86", "AnyDesk")
        keys = {U32 + "\\AnyDesk": entry("AnyDesk", "AnyDesk Software GmbH", loc),
                k.SERVICES + "\\AnyDesk": {"ImagePath": '"%s\\AnyDesk.exe" --service' % loc},
                k.SERVICES + "\\Spooler": {"ImagePath": r"C:\Windows\System32\spoolsv.exe"}}
        res, _ = self.run_scan(keys, "AnyDesk")
        svc = [i["name"] for i in res["items"] if i["kind"] == "service"]
        self.assertEqual(svc, ["AnyDesk"])


class GuardTest(unittest.TestCase):
    def test_path_blocked(self):
        tmp = tempfile.mkdtemp(prefix="kaldirici_g_")
        try:
            env = k.Env(roots={"pf": os.path.join(tmp, "PF")}, reg=FakeReg({}), tasks_dir="", protect=[os.path.join(tmp, "Own")])
            self.assertTrue(env.path_blocked(os.path.join(tmp, "PF")))
            self.assertTrue(env.path_blocked(tmp))  # korunan kokun ustu
            self.assertTrue(env.path_blocked(os.path.join(tmp, "Own", "x")))
            self.assertTrue(env.path_blocked("C:\\"))
            self.assertTrue(env.path_blocked("relative\\path"))
            self.assertTrue(env.path_blocked(os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Temp", "x")))
            self.assertFalse(env.path_blocked(os.path.join(tmp, "PF", "App")))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_clean_rechecks_before_delete(self):
        tmp = tempfile.mkdtemp(prefix="kaldirici_c_")
        try:
            env = k.Env(roots={"pf": tmp}, reg=FakeReg({}), tasks_dir="")
            res = k.clean([{"kind": "dir", "path": tmp, "name": ""},
                           {"kind": "key", "path": "HKCU\\Software\\Microsoft", "name": ""},
                           {"kind": "value", "path": "HKCU\\Software\\Other", "name": "x"}],
                          env, os.path.join(tmp, "yedek"), "Test")
            self.assertEqual(res["removed"], 0)
            self.assertEqual([f["error"] for f in res["failed"]], ["blocked"] * 3)
            self.assertTrue(os.path.isdir(tmp))
            self.assertTrue(os.path.isfile(os.path.join(res["backup"], "silinenler.json")))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_uninstaller_clean_only_uses_last_scan(self):
        u = k.Uninstaller(lambda: k.Env(roots={}, reg=FakeReg({}), tasks_dir=""), tempfile.gettempdir())
        with self.assertRaises(k.Error) as cm:
            u.clean(["0"], False)
        self.assertEqual(cm.exception.code, "noScan")
        u.last = {"app": {"id": "x", "name": "x"}, "items": {}}
        with self.assertRaises(k.Error) as cm:
            u.clean(["0", 5, None], False)
        self.assertEqual(cm.exception.code, "nothing")

    def test_hung_uninstaller_can_be_cancelled(self):
        import time
        app_id = k.UNINSTALL_ROOTS[0] + "\Takilan"
        u = k.Uninstaller(lambda: k.Env(roots={}, reg=FakeReg({}), tasks_dir=""), tempfile.gettempdir())
        u.apps[app_id] = {"id": app_id, "key": "Takilan", "name": "Takilan", "msi": False,
                          "uninstall": '"%s" -c "import time; time.sleep(120)"' % sys.executable}
        self.assertEqual(u.start(app_id, False)["phase"], "running")
        for _ in range(100):
            if u.proc is not None:
                break
            time.sleep(0.05)
        p = u.proc
        self.assertIsNotNone(p)
        with self.assertRaises(k.Error) as cm:
            u.start(app_id, False)
        self.assertEqual(cm.exception.code, "busy")
        self.assertEqual(u.cancel()["phase"], "cancelled")
        p.wait(timeout=10)
        for _ in range(100):
            if u.proc is None:
                break
            time.sleep(0.05)
        self.assertEqual(u.status()["phase"], "cancelled")  # bitis "done" ile ezilmez
        self.assertEqual(u.cancel()["phase"], "cancelled")  # ikinci iptal zararsiz


if __name__ == "__main__":
    unittest.main()
