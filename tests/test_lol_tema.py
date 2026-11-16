# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""LoL skin renk temasi: renk cikarma, secim okuma, onbellek ve oyun modu entegrasyonu. Aga ve oyuna dokunmaz.

    python -m unittest discover -s tests
"""
import colorsys
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import control_center  # noqa: E402
import klavye_rgb  # noqa: E402
import lol_tema  # noqa: E402
import oyun  # noqa: E402

try:
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover
    Image = None


def hue(hx):
    r, g, b = lol_tema._rgb(hx)
    return colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)[0] * 360


def tile(center, bg=(10, 10, 14), accent=None, size=200):
    """Ortada sampiyonu temsil eden renkli daire, koyu arka plan, istege bagli kucuk ikinci renk."""
    img = Image.new("RGB", (size, size), bg)
    d = ImageDraw.Draw(img)
    d.ellipse((40, 40, 160, 160), fill=center)
    if accent:
        d.rectangle((80, 80, 120, 120), fill=accent)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=92)
    return buf.getvalue()


EVELYNN = {
    "id": 28, "name": "Evelynn",
    "skins": [
        {"id": 28000, "name": "Evelynn", "tilePath": "/lol-game-data/assets/ASSETS/Characters/Evelynn/Skins/Base/Images/evelynn_splash_tile_0.jpg"},
        {"id": 28006, "name": "K/DA Evelynn", "tilePath": "/lol-game-data/assets/ASSETS/Characters/Evelynn/Skins/Skin06/Images/evelynn_splash_tile_6.jpg",
         "chromas": [{"id": 28007, "name": "K/DA Evelynn (Gold)", "colors": ["#E8C34B", "#E8C34B"]}]},
    ],
}


class FakeAssets:
    def __init__(self, files):
        self.files = files
        self.calls = []

    def get(self, path, raw=False):
        self.calls.append(path)
        if path not in self.files:
            raise OSError("404")
        v = self.files[path]
        return v if raw else json.loads(json.dumps(v))


@unittest.skipIf(Image is None, "Pillow yok")
class ColorTest(unittest.TestCase):
    def theme(self, data, prefer=()):
        return lol_tema.build_theme(lol_tema.hue_peaks(lol_tema.image_pixels(data)), prefer)

    def test_purple_champion_gives_purple_q(self):
        th = self.theme(tile((120, 40, 190)))
        self.assertTrue(260 <= hue(th["q"]) <= 300, th)
        self.assertEqual(set(th), {"q", "w", "e", "r"})

    def test_dark_background_ignored(self):
        th = self.theme(tile((30, 150, 230), bg=(5, 5, 5)))
        self.assertTrue(190 <= hue(th["q"]) <= 220, th)

    def test_second_hue_used(self):
        th = self.theme(tile((120, 40, 190), accent=(250, 170, 20)))
        hs = [hue(th[k]) for k in ("q", "w", "e")]
        self.assertTrue(any(25 <= h <= 50 for h in hs), (th, hs))

    def test_led_colors_are_bright(self):
        th = self.theme(tile((70, 30, 90)))
        for k in ("q", "w", "e"):
            self.assertEqual(max(lol_tema._rgb(th[k])), 255)

    def test_grey_image_gives_none(self):
        self.assertIsNone(self.theme(tile((128, 128, 128))))

    def test_chroma_colors_lead(self):
        th = self.theme(tile((120, 40, 190)), ["#E8C34B"])
        self.assertTrue(35 <= hue(th["q"]) <= 55, th)

    def test_broken_image(self):
        self.assertEqual(lol_tema.image_pixels(b"not an image"), [])


class SelectionTest(unittest.TestCase):
    def test_lockfile(self):
        self.assertEqual(lol_tema.read_lockfile("LeagueClient:1234:54321:abcXYZ:https"), (54321, "abcXYZ"))
        self.assertIsNone(lol_tema.read_lockfile("garbage"))
        self.assertIsNone(lol_tema.read_lockfile("LeagueClient:1:99999999:x:https"))

    def test_champ_select(self):
        s = {"localPlayerCellId": 3, "myTeam": [{"cellId": 1, "championId": 99, "selectedSkinId": 99001},
                                                 {"cellId": 3, "championId": 28, "selectedSkinId": 28007}]}
        self.assertEqual(lol_tema.champ_select_pick(s), (28, 28007))
        s["myTeam"][1]["championId"] = 0  # henuz secmedi
        self.assertIsNone(lol_tema.champ_select_pick(s))
        s["myTeam"][1].update(championId=28, selectedSkinId=0)
        self.assertEqual(lol_tema.champ_select_pick(s), (28, 28000))

    def test_alias(self):
        self.assertEqual(lol_tema.alias_of("game_character_displayname_MissFortune"), "MissFortune")
        self.assertEqual(lol_tema.alias_of("Evelynn"), "Evelynn")

    def test_find_skin_chroma_and_fallback(self):
        s, cols, name = lol_tema.find_skin(EVELYNN, 28007)
        self.assertEqual((s["id"], cols, name), (28006, ["#E8C34B", "#E8C34B"], "K/DA Evelynn (Gold)"))
        s, cols, _ = lol_tema.find_skin(EVELYNN, 28999)  # bilinmeyen skin: temel gorunum
        self.assertEqual((s["id"], cols), (28000, []))

    def test_unsafe_paths_rejected(self):
        for p in ("/lol-game-data/assets/../../secret", "https://evil/x", "/other/x.jpg", None):
            with self.assertRaises(ValueError):
                lol_tema.cdragon_url(p)
        self.assertEqual(lol_tema.cdragon_url("/lol-game-data/assets/v1/champions/28.json"),
                         lol_tema.CDRAGON + "v1/champions/28.json")
        self.assertTrue(lol_tema.cdragon_url(EVELYNN["skins"][0]["tilePath"]).endswith(
            "assets/characters/evelynn/skins/base/images/evelynn_splash_tile_0.jpg"))

    def test_assets_prefers_local_client(self):
        class L:
            auth = (1, "x")

            def get(self, path, raw=False):
                return "local"
        a = lol_tema.Assets(L(), remote=lambda p, raw=False: "remote")
        self.assertEqual(a.get("/lol-game-data/assets/v1/x.json"), "local")
        L.auth = None
        self.assertEqual(a.get("/lol-game-data/assets/v1/x.json"), "remote")

    def test_live_playerlist(self):
        c = oyun.LolClient()
        c._me = oyun._ids("Ben#TR1")
        players = [{"riotId": "Baska#EU", "rawChampionName": "game_character_displayname_Ahri", "skinID": 3},
                   {"riotId": "Ben#TR1", "rawChampionName": "game_character_displayname_Evelynn", "skinID": 6}]
        self.assertEqual(c.champion(players), ("game_character_displayname_Evelynn", 6))
        self.assertIsNone(c.champion("bozuk"))


class LiveStub:
    connected = False
    champ = None


class NoLcu:
    auth = None

    def find(self):
        return False


@unittest.skipIf(Image is None, "Pillow yok")
class WatcherTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.assets = FakeAssets({
            "/lol-game-data/assets/v1/champions/28.json": EVELYNN,
            "/lol-game-data/assets/v1/champion-summary.json": [{"id": 28, "alias": "Evelynn"}, {"id": 103, "alias": "Ahri"}],
            EVELYNN["skins"][0]["tilePath"]: tile((120, 40, 190)),
            EVELYNN["skins"][1]["tilePath"]: tile((230, 60, 160)),
        })

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def watcher(self, live, lcu=None):
        return lol_tema.ThemeWatcher(live, self.dir, lcu=lcu or NoLcu(), assets=self.assets)

    def test_live_game_resolves_and_caches(self):
        live = LiveStub()
        live.connected, live.champ = True, ("game_character_displayname_Evelynn", 0)
        w = self.watcher(live)
        w.step(now=100.0)
        self.assertTrue(260 <= hue(w.theme["colors"]["q"]) <= 300, w.theme)
        self.assertEqual(w.theme["name"], "Evelynn")
        n = len(self.assets.calls)
        w2 = self.watcher(live)  # yeni oturum: diskteki onbellekten, hic istek yok
        w2.step(now=100.0)
        self.assertEqual(len(self.assets.calls), n)
        self.assertEqual(w2.theme, w.theme)

    def test_champ_select_chroma_kept_in_game(self):
        class Lcu:
            auth = (1, "x")

            def find(self):
                return True

            def get(self, path, raw=False):
                return {"localPlayerCellId": 0, "myTeam": [{"cellId": 0, "championId": 28, "selectedSkinId": 28007}]}
        live = LiveStub()
        w = self.watcher(live, Lcu())
        w.step(now=10.0)
        self.assertEqual(w.pick, (28, 28007))
        self.assertTrue(35 <= hue(w.theme["colors"]["q"]) <= 55, w.theme)  # altin kroma
        live.connected, live.champ = True, ("game_character_displayname_Evelynn", 6)
        w.step(now=20.0)
        self.assertEqual(w.pick, (28, 28007))  # oyun ici kaba kayit (skin 6) kromayi ezmez

    def test_failure_retries_later(self):
        live = LiveStub()
        live.connected, live.champ = True, ("game_character_displayname_Ahri", 0)  # Ahri verisi yok
        w = self.watcher(live)
        w.step()
        self.assertIsNone(w.theme)
        n = len(self.assets.calls)
        w.step()
        self.assertEqual(len(self.assets.calls), n)  # 60 sn dolmadan yeniden indirmeye calismaz


class IntegrationTest(unittest.TestCase):
    def test_snapshot_and_sanitize(self):
        cfg = json.loads(json.dumps(klavye_rgb.DEFAULTS))
        cfg["mode"] = "oyun"
        self.assertEqual(klavye_rgb.snapshot(cfg)[5], {"skin": True})
        cfg["modes"]["oyun"]["skin"] = False
        self.assertEqual(klavye_rgb.snapshot(cfg)[5], {"skin": False})
        base = klavye_rgb.DEFAULTS["modes"]["oyun"]
        self.assertFalse(control_center._mode_values("oyun", {"skin": False}, base)["skin"])
        self.assertTrue(control_center._mode_values("oyun", {"skin": "evet"}, base)["skin"])  # gecersiz: varsayilan

    def test_theme_overrides_qwer_flash(self):
        fx = klavye_rgb.GameFx()

        class Tema:
            wanted = False
            theme = {"name": "Evelynn", "colors": {"q": "#9a00ff", "w": "#ff00aa", "e": "#5000ff", "r": "#c266ff"}}
        fx.tema = Tema()
        fx.sources["lol"] = oyun.LolClient()  # baslatilmaz: aga gitmez
        fx.keys.poll = lambda layout, now: (["q"], {"q"})
        pal = [klavye_rgb.hex_to_rgb(h) for h in klavye_rgb.GAME_PALETTE]
        col, info, _ = fx.frame(pal, 55, "lol", 1.0, skin=True)
        self.assertEqual(tuple(round(c) for c in col), (0x9a, 0x00, 0xff))
        self.assertIn("Evelynn", info)
        self.assertIs(fx.theme_now, Tema.theme)  # arayuz bu temayi "Otomatik" kutularda gosterir
        self.assertTrue(fx.tema.wanted and fx.sources["lol"].want_champ)
        fx.flashes.clear()
        col, info, _ = fx.frame(pal, 55, "lol", 2.0, skin=False)  # kapali: kullanicinin Q rengi
        self.assertEqual(tuple(round(c) for c in col), tuple(klavye_rgb.hex_to_rgb(klavye_rgb.GAME_PALETTE[2])))
        self.assertFalse(fx.tema.wanted)
        self.assertIsNone(fx.theme_now)  # "Kendi renklerim": tema gosterilmez
        self.assertNotIn("Evelynn", info)

    def test_meta_lists_slot_ids_and_defaults(self):
        self.assertEqual(klavye_rgb.GAME_SLOTS[2:6], ["q", "w", "e", "r"])  # arayuz Q/W/E/R yuvalarini buradan bulur
        cfg = json.loads(json.dumps(klavye_rgb.DEFAULTS))
        cfg["cc"] = {}
        raw = {"mode": "oyun", "modes": {"oyun": {"palette": klavye_rgb.GAME_PALETTE, "skin": False}},
               "presets": {"Benim": {"mode": "oyun", "palette": klavye_rgb.GAME_PALETTE, "skin": False}}}
        out = control_center.sanitize(raw, cfg)
        self.assertFalse(out["modes"]["oyun"]["skin"])
        self.assertFalse(out["presets"]["Benim"]["skin"])  # kayitli modlar secimi korur


if __name__ == "__main__":
    unittest.main()
