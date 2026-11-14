# -*- coding: utf-8 -*-
"""HP Omen / Victus arka ucu: sahte (mock) BIOS WMI ile birim testleri. Gercek donanim gerekmez.

Calistirma (depo kokunden):  python -m unittest discover -s tests -v
"""
import os
import queue
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import donanim as hw  # noqa: E402
import hp_omen as hp  # noqa: E402

OMEN = {"manufacturer": "HP", "model": "OMEN by HP Laptop 16-b0xxx", "family": "103C_5335KV HP OMEN", "board": "88F7"}
VICTUS = {"manufacturer": "HP", "model": "Victus by HP Laptop 16-d0xxx", "family": "103C_5335KV HP Victus", "board": "88F8"}

WRITES = {(hp.CMD_GM, hp.GM_PERF_MODE), (hp.CMD_GM, hp.GM_FAN_MAX_SET), (hp.CMD_KB, hp.KB_COLOR_SET),
          (hp.CMD_KB, hp.KB_BACKLIGHT_SET), (hp.CMD_WRITE, hp.GPU_MUX), (hp.CMD_GM, 0x2E)}


def pad(b, n):
    return bytes(b) + bytes(n - len(b))


class FakeBios:
    """Sahte hpqBIOSInt: (komut, tip) -> (donus kodu, veri). Tanimsiz komut 4 (bilinmeyen tip) dondurur."""

    def __init__(self, policy=1, kbd_type=0, backlight=True, zones_last=3, temp=45, fan_speed=True,
                 fan_level=True, max_fan=0, design_ok=True, overrides=None):
        table = bytearray(128)
        table[0] = zones_last
        table[5] = 0xAB  # okunan tablonun diger baytlari korunmali
        self.r = {
            (hp.CMD_GM, hp.GM_DESIGN): (0, pad([0xE6, 0, 0x35, policy, 1, 0xD7, 0, 0x0C], 128)) if design_ok else (4, b""),
            (hp.CMD_GM, hp.GM_FAN_COUNT): (0, pad([2], 4)),
            (hp.CMD_GM, hp.GM_FAN_MAX_GET): (0, pad([max_fan], 4)),
            (hp.CMD_GM, hp.GM_TEMP): (0, pad([temp], 4)),
            (hp.CMD_KB, hp.KB_HAS_BACKLIGHT): (0, pad([0x07 if backlight else 0x06], 4)),
            (hp.CMD_GM, hp.GM_KBD_TYPE): (0, pad([kbd_type], 4)),
            (hp.CMD_KB, hp.KB_COLOR_GET): (0, bytes(table)),
            (hp.CMD_KB, hp.KB_BACKLIGHT_GET): (0, pad([hp.BACKLIGHT_ON], 4)),
            (hp.CMD_READ, hp.GPU_MUX): (0, pad([0], 4)),
            (hp.CMD_GM, hp.GM_PERF_MODE): (0, b""),
            (hp.CMD_GM, hp.GM_FAN_MAX_SET): (0, b""),
            (hp.CMD_KB, hp.KB_COLOR_SET): (0, b""),
            (hp.CMD_KB, hp.KB_BACKLIGHT_SET): (0, b""),
        }
        if fan_speed:
            self.r[(hp.CMD_GM, hp.GM_FAN_SPEED)] = None  # fan indeksine gore: call() icinde
        if fan_level:
            self.r[(hp.CMD_GM, hp.GM_FAN_LEVEL)] = (0, pad([0x1E, 0x22], 128))
        self.r.update(overrides or {})
        self.calls = []

    def call(self, command, ctype, data=b"", outsize=0):
        self.calls.append((command, ctype, bytes(data), outsize))
        key = (command, ctype)
        if key not in self.r:
            return 4, b""
        if key == (hp.CMD_GM, hp.GM_FAN_SPEED) and self.r[key] is None:
            rpm = 2400 if data[:1] == b"\x00" else 2650
            return 0, pad([0, 0, rpm >> 8, rpm & 255], 4)
        rc, out = self.r[key]
        return rc, out[:max(outsize, 0)] if outsize else b""

    def close(self):
        pass

    def writes(self):
        return [c for c in self.calls if (c[0], c[1]) in WRITES]


def make(info=OMEN, family="omen", **kw):
    bios = FakeBios(**kw)
    return hp.HpOmen(info, family, bios), bios


class Detection(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(hp.classify(OMEN), "omen")
        self.assertEqual(hp.classify(VICTUS), "victus")
        self.assertEqual(hp.classify({"manufacturer": "Hewlett-Packard", "model": "OMEN 17"}), "omen")
        self.assertIsNone(hp.classify({"manufacturer": "HP", "model": "HP Pavilion 15", "family": "Pavilion"}))
        self.assertIsNone(hp.classify({"manufacturer": "Notebook", "model": "OMEN clone"}))
        self.assertIsNone(hp.classify({"manufacturer": "Monster", "model": "Tulpar T5", "family": "Tulpar"}))
        self.assertIsNone(hp.classify({}))

    def test_method_for(self):
        self.assertEqual([hp.method_for(n) for n in (0, 1, 4, 5, 128, 129, 1024, 4096)],
                         [0, 4, 4, 128, 128, 1024, 1024, 4096])
        with self.assertRaises(ValueError):
            hp.method_for(4097)

    def test_non_hp_never_opens_bridge(self):
        factory = mock.Mock()
        self.assertEqual(hp.open_backend({"manufacturer": "Monster"}, bridge_factory=factory), (None, ""))
        factory.assert_not_called()

    def test_bridge_failure_falls_back(self):
        class Broken:
            closed = False

            def call(self, *a):
                raise hp.BridgeError("NOCLASS")

            def close(self):
                Broken.closed = True
        dev, why = hp.open_backend(OMEN, bridge_factory=Broken)
        self.assertIsNone(dev)
        self.assertIn("NOCLASS", why)
        self.assertTrue(Broken.closed)

    def test_hp_path_never_runs_clevo_code(self):
        sentinel = object()
        with mock.patch("hp_omen.system_info", return_value=OMEN), \
                mock.patch.object(hw, "clevo_present") as cp, mock.patch.object(hw, "DCHU") as dchu, \
                mock.patch("hp_omen.open_backend", return_value=(sentinel, "")):
            self.assertEqual(hw.vendor_kind(), "hp")
            self.assertIs(hw.open_dchu(), sentinel)
            cp.assert_not_called()
            dchu.assert_not_called()
        # HP ama BIOS WMI yok: NullDCHU, yine Clevo'ya bakilmaz
        with mock.patch("hp_omen.system_info", return_value=OMEN), \
                mock.patch.object(hw, "clevo_present") as cp, \
                mock.patch("hp_omen.open_backend", return_value=(None, "NOCLASS")):
            dev = hw.open_dchu()
            self.assertIsInstance(dev, hw.NullDCHU)
            self.assertFalse(any(hw.caps(dev).values()))
            cp.assert_not_called()

    def test_clevo_path_unchanged(self):
        monster = {"manufacturer": "MONSTER", "model": "ABRA A5 V21.1", "family": "ABRA"}
        with mock.patch("hp_omen.system_info", return_value=monster), \
                mock.patch.object(hw, "clevo_present", return_value=True), \
                mock.patch.object(hw, "DCHU", return_value="clevo"), \
                mock.patch("hp_omen.open_backend") as ob:
            self.assertIsNone(hw.vendor_kind())
            self.assertEqual(hw.open_dchu(), "clevo")
            ob.assert_not_called()

    def test_same_rule_as_setup(self):
        # kurulum.ps1: Uretici ^HP|Hewlett, Model OMEN|Victus (aile adi tek basina yetmez)
        self.assertIsNone(hp.classify({"manufacturer": "HP", "model": "HP EliteBook 840", "family": "OMEN"}))
        self.assertEqual(hp.classify({"manufacturer": "HP Inc.", "model": "victus 15"}), "victus")
        self.assertEqual(make()[0].kind, "hp")

    def test_caps_for_clevo_like(self):
        class Clevo:
            available = True
        self.assertTrue(hw.caps(Clevo())["fan_curve"])
        self.assertFalse(hw.caps(Clevo())["gpu_mux"])


class Probe(unittest.TestCase):
    def test_probe_is_read_only(self):
        dev, bios = make()
        self.assertEqual(bios.writes(), [])
        self.assertTrue(all(c[1] not in (0x2E, 0x32) for c in bios.calls))

    def test_omen_v1(self):
        dev, bios = make(policy=1)
        self.assertEqual(dev.thermal, "omen_v1")
        c = dev.caps
        self.assertTrue(c["power"] and c["fan_max"] and c["fan_read"] and c["temp"] and c["kb"])
        self.assertFalse(c["fan_curve"])
        self.assertTrue(c["gpu_mux"])
        self.assertEqual(dev.zones, 4)
        self.assertEqual(dev.gpu_mode(), "hybrid")

    def test_omen_v0_and_forced_v0(self):
        self.assertEqual(make(policy=0)[0].thermal, "omen_v0")
        forced = dict(OMEN, board="8746")
        self.assertEqual(make(info=forced, policy=1)[0].thermal, "omen_v0")

    def test_omen_without_design_data_sends_no_thermal_mode(self):
        dev, bios = make(design_ok=False)
        self.assertFalse(dev.caps["power"])
        with self.assertRaises(hw.Unsupported):
            dev.set_power_mode(2)
        self.assertEqual(bios.writes(), [])

    def test_per_key_keyboard_not_driven(self):
        dev, bios = make(kbd_type=hp.KBD_PER_KEY)
        self.assertFalse(dev.caps["kb"])
        self.assertFalse(dev.kb_available)
        dev.set_color(255, 0, 0)
        self.assertEqual(bios.writes(), [])

    def test_no_backlight(self):
        dev, bios = make(backlight=False)
        self.assertFalse(dev.caps["kb"])
        dev.set_color(10, 20, 30)
        self.assertEqual(bios.writes(), [])


class Thermal(unittest.TestCase):
    def last_mode(self, bios):
        w = [c for c in bios.calls if c[1] == hp.GM_PERF_MODE]
        return w[-1][2]

    def test_omen_v1_values(self):
        dev, bios = make(policy=1)
        for mode, val in ((2, 0x31), (3, 0x30), (0, 0x50), (1, 0x50)):
            dev.set_power_mode(mode)
            self.assertEqual(self.last_mode(bios), bytes([0xFF, val, 0, 0]))
            self.assertEqual(dev.power_mode(), mode)
        self.assertEqual(bios.calls[-1][3], 0)  # cikissiz: hpqBIOSInt0

    def test_omen_v0_values(self):
        dev, bios = make(policy=0)
        dev.set_power_mode(0)
        self.assertEqual(self.last_mode(bios), bytes([0xFF, 0x02, 0, 0]))
        dev.set_power_mode(2)
        self.assertEqual(self.last_mode(bios), bytes([0xFF, 0x01, 0, 0]))

    def test_victus_quiet_and_fallback(self):
        dev, bios = make(info=VICTUS, family="victus")
        dev.set_power_mode(0)
        self.assertEqual(self.last_mode(bios), bytes([0xFF, 0x03, 0, 0]))
        # Victus S benzeri: sessiz mod 'gecersiz parametre' -> dengeli
        dev2, bios2 = make(info=VICTUS, family="victus")
        orig = bios2.call

        def call(command, ctype, data=b"", outsize=0):
            if ctype == hp.GM_PERF_MODE and data[1:2] == b"\x03":
                bios2.calls.append((command, ctype, bytes(data), outsize))
                return 5, b""
            return orig(command, ctype, data, outsize)
        bios2.call = call
        msg = dev2.set_power_mode(0)
        self.assertEqual(self.last_mode(bios2), bytes([0xFF, 0x00, 0, 0]))
        self.assertTrue(dev2.no_quiet)
        self.assertIsInstance(msg, str)

    def test_unknown_command_disables_feature(self):
        dev, bios = make(overrides={(hp.CMD_GM, hp.GM_PERF_MODE): (4, b"")})
        with self.assertRaises(hw.Unsupported):
            dev.set_power_mode(2)
        n = len(bios.calls)
        with self.assertRaises(hw.Unsupported):
            dev.set_power_mode(3)
        self.assertEqual(len(bios.calls), n)  # bir daha komut gitmez

    def test_other_error_is_reported(self):
        dev, _ = make(overrides={(hp.CMD_GM, hp.GM_PERF_MODE): (6, b"")})
        with self.assertRaises(RuntimeError) as ctx:
            dev.set_power_mode(2)
        self.assertNotIsInstance(ctx.exception, hw.Unsupported)
        self.assertTrue(dev.caps["power"])

    def test_power_text(self):
        dev, _ = make(policy=1)
        self.assertEqual(dev.power_key(2), "hp.power.perf")
        self.assertEqual(dev.power_key(0), "hp.power.quiet")
        self.assertEqual(dev.power_key(3), "hp.power.balanced")
        self.assertIsInstance(hw.power_text(dev, 2), str)


class Fans(unittest.TestCase):
    def test_status_fan_speed(self):
        dev, _ = make()
        s = dev.status()
        self.assertEqual(s, {"cpu_temp": 45, "cpu_rpm": 2400, "gpu_rpm": 2650})

    def test_status_fan_level_fallback(self):
        dev, _ = make(fan_speed=False)
        self.assertEqual(dev.fan_method, hp.GM_FAN_LEVEL)
        s = dev.status()
        self.assertEqual((s["cpu_rpm"], s["gpu_rpm"]), (3000, 3400))

    def test_no_fan_read(self):
        dev, _ = make(fan_speed=False, fan_level=False)
        self.assertFalse(dev.caps["fan_read"])
        self.assertNotIn("cpu_rpm", dev.status())

    def test_bad_temperature_ignored(self):
        dev, _ = make(temp=0)
        self.assertFalse(dev.caps["temp"])
        self.assertNotIn("cpu_temp", dev.status())

    def test_max_fan(self):
        dev, bios = make()
        self.assertEqual(dev.fan_mode(), hw.FAN_AUTO)
        dev.set_fan_mode(hw.FAN_MAX)
        self.assertEqual(bios.writes()[-1][:3], (hp.CMD_GM, hp.GM_FAN_MAX_SET, b"\x01\x00\x00\x00"))
        self.assertEqual(dev.fan_mode(), hw.FAN_MAX)
        dev.set_fan_mode(hw.FAN_AUTO)
        self.assertEqual(bios.writes()[-1][2], b"\x00\x00\x00\x00")
        with self.assertRaises(hw.Unsupported):
            dev.set_fan_mode(hw.FAN_CUSTOM)
        with self.assertRaises(hw.Unsupported):
            dev.set_fan_curve((50, 30, 70, 60), (50, 30, 70, 60))
        self.assertIsNone(dev.fan_default())

    def test_max_fan_keep_alive(self):
        dev, bios = make()
        dev.set_fan_mode(hw.FAN_MAX)
        n = len(bios.writes())
        dev._max_at -= hp.MAX_FAN_REFRESH + 1
        dev.status()
        self.assertEqual(len(bios.writes()), n + 1)

    def test_max_fan_unsupported(self):
        dev, bios = make(overrides={(hp.CMD_GM, hp.GM_FAN_MAX_GET): (3, b"")})
        self.assertFalse(dev.caps["fan_max"])
        self.assertIsNone(dev.fan_mode())
        with self.assertRaises(hw.Unsupported):
            dev.set_fan_mode(hw.FAN_MAX)
        self.assertEqual(bios.writes(), [])

    def test_clevo_raw_commands_refused(self):
        dev, bios = make()
        for fn in (lambda: dev.set_wmi(0x46, 0), lambda: dev.set_data(14, b"x"), lambda: dev.write_app(1, 1, b"x")):
            with self.assertRaises(hw.Unsupported):
                fn()
        self.assertEqual(bios.writes(), [])


class Keyboard(unittest.TestCase):
    def test_color_table(self):
        dev, bios = make()
        dev.set_color(10, 20, 30)
        sent = [c for c in bios.calls if c[1] == hp.KB_COLOR_SET][-1][2]
        self.assertEqual(len(sent), 128)
        self.assertEqual(sent[0], 3)
        self.assertEqual(sent[5], 0xAB)
        for i in range(4):
            o = hp.COLOR_OFFSET + 3 * i
            self.assertEqual(sent[o:o + 3], bytes([10, 20, 30]))

    def test_black_turns_backlight_off_then_on(self):
        dev, bios = make()
        dev.set_color(0, 0, 0)
        self.assertEqual(bios.writes()[-1][:3], (hp.CMD_KB, hp.KB_BACKLIGHT_SET, bytes([hp.BACKLIGHT_OFF, 0, 0, 0])))
        dev._kb_at -= 1
        dev.set_color(255, 0, 0)
        w = bios.writes()[-2:]
        self.assertEqual(w[0][2], bytes([hp.BACKLIGHT_ON, 0, 0, 0]))
        self.assertEqual(w[1][1], hp.KB_COLOR_SET)

    def test_rate_limit_and_repeat(self):
        dev, bios = make()
        dev.set_color(1, 2, 3)
        n = len(bios.writes())
        dev.set_color(4, 5, 6)  # ayni an: kare atlanir
        dev.set_color(1, 2, 3)  # ayni renk 1 sn icinde: tekrar gonderilmez
        self.assertEqual(len(bios.writes()), n)

    def test_two_zone_keyboard(self):
        dev, bios = make(zones_last=1)
        self.assertEqual(dev.zones, 2)
        dev.set_zones([(1, 1, 1), (2, 2, 2), (3, 3, 3), (4, 4, 4)])
        sent = [c for c in bios.calls if c[1] == hp.KB_COLOR_SET][-1][2]
        self.assertEqual(sent[hp.COLOR_OFFSET + 6:hp.COLOR_OFFSET + 9], bytes(3))


class Bridge(unittest.TestCase):
    def fake(self, answer):
        b = hp.PsBridge()

        class Proc:
            def __init__(self):
                self.stdin = mock.Mock()

            def poll(self):
                return None

            def kill(self):
                pass
        b.proc = Proc()
        b.lines = queue.Queue()
        b.lines.put(answer)
        return b

    def test_call_ok(self):
        b = self.fake("OK 0 0a0bff")
        stdin = b.proc.stdin
        self.assertEqual(b.call(hp.CMD_GM, hp.GM_TEMP, b"\x01\x00\x00\x00", 4), (0, b"\x0a\x0b\xff"))
        stdin.write.assert_called_with(b"131080 35 4 01000000\n")

    def test_call_empty_and_error(self):
        self.assertEqual(self.fake("OK 3 -").call(hp.CMD_GM, 0x99, b"", 0), (3, b""))
        with self.assertRaises(hp.BridgeError):
            self.fake("ERR Access denied").call(hp.CMD_GM, hp.GM_TEMP, b"", 4)

    def test_timeout_kills_process(self):
        b = self.fake(None)
        b.lines = queue.Queue()
        b.TIMEOUT = 0.05
        with self.assertRaises(hp.BridgeError):
            b.call(hp.CMD_GM, hp.GM_TEMP, b"", 4)
        self.assertIsNone(b.proc)


class Profiles(unittest.TestCase):
    def manager(self, dev):
        import profiller
        m = profiller.Manager.__new__(profiller.Manager)
        m.dchu = dev
        m.sensors = mock.Mock(gpu_name="")
        return m, profiller

    def test_curve_profile_falls_back_to_bios_table(self):
        dev, bios = make()
        dev.set_fan_mode(hw.FAN_MAX)
        m, profiller = self.manager(dev)
        p = profiller.BY_ID["tam_sessiz"]
        self.assertEqual(p["fan"][0], "curve")
        m._fan(p)
        self.assertEqual(dev.fan_mode(), hw.FAN_AUTO)
        self.assertFalse(any(c[1] == 0x2E for c in bios.calls))
        rows = dict(m.describe(p))
        self.assertTrue(all(isinstance(v, str) for v in rows.values()))

    def test_ec_step_uses_hp_text(self):
        dev, _ = make()
        m, profiller = self.manager(dev)
        self.assertIsInstance(m._ec(profiller.BY_ID["tam_sessiz"]), str)


if __name__ == "__main__":
    unittest.main()
