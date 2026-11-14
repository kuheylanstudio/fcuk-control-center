# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""MSI arka ucu: sahte MSI_ACPI (bellekte EC) ve sahte HID ile birim testleri. Donanima dokunmaz.

    python -m unittest discover -s tests
"""
import os
import sys
import time
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import donanim  # noqa: E402
import klavye_rgb  # noqa: E402
import msi  # noqa: E402
import msi_klavye  # noqa: E402
import msi_wmi  # noqa: E402


# ----------------------------------------------------------------------------- sahte MSI_ACPI
class FakeAcpi:
    """MSI_ACPI yontemlerini 256 baytlik bir EC bellegiyle taklit eder (msi-wmi-platform belgesindeki duzen)."""

    def __init__(self, fw="17F2EMS1.106", mirror=None, regs=None, stuck=()):
        self.mem = bytearray(256)
        self.fw_text = fw
        m = (fw if mirror is None else mirror).encode("latin-1")[:12]
        self.mem[0xA0:0xA0 + len(m)] = m
        for a, v in (regs or {}).items():
            self.mem[a] = v
        self.stuck = set(stuck)   # bu adreslere yazma tutmaz (geri okuma denetimi)
        self.writes = []
        self.calls = []
        self.rpm_raw = (160, 200)  # 480000/160 = 3000, 480000/200 = 2400

    def call(self, method, data):
        assert len(data) == 32
        self.calls.append(method)
        out = bytearray(32)
        out[0] = 1
        if method == "Get_EC":
            out[1] = 0x21
            t = self.fw_text.encode("latin-1")[:28]
            out[2:2 + len(t)] = t
        elif method == "Get_Data":
            out[1] = self.mem[data[0]]
        elif method == "Set_Data":
            self.writes.append((data[0], data[1]))
            if data[0] not in self.stuck:
                self.mem[data[0]] = data[1]
        elif method == "Get_Fan":
            for i, raw in enumerate(self.rpm_raw):
                out[1 + 2 * i], out[2 + 2 * i] = raw >> 8, raw & 0xFF
        else:
            out[0] = 0
        return bytes(out)


def make(fw="17F2EMS1.106", **kw):
    acpi = FakeAcpi(fw, **kw)
    return msi.MsiEC(msi_wmi.MsiWmi(acpi), None, donanim.Unsupported), acpi


BASE = {0x68: 55, 0x80: 48, 0x71: 35, 0x89: 30, 0xF2: 0xC1, 0xF4: 0x0D, 0x98: 0x02, 0xEF: 0x80 | 100}


class FakeHid:
    def __init__(self):
        self.sent = []

    def set_feature(self, data):
        self.sent.append(("feature", bytes(data)))

    def write(self, data):
        self.sent.append(("output", bytes(data)))

    def close(self):
        pass


# ----------------------------------------------------------------------------- tablo ve tasima
class TableTest(unittest.TestCase):
    def test_lookup_uses_first_ten_chars(self):
        self.assertEqual(msi.lookup("17F2EMS1.106")["name"], "G1_1")
        self.assertEqual(msi.lookup("1582EMS1.107")["name"], "G2_1")
        self.assertIsNone(msi.lookup("17F2EMS1.2"))   # ayni model, tabloda olmayan surum
        self.assertIsNone(msi.lookup("XXXX"))
        self.assertIsNone(msi.lookup(""))

    def test_tables_are_consistent(self):
        seen = set()
        for c in msi.CONFS:
            for fw in c["fw"]:
                self.assertEqual(len(fw), 10, fw)
                self.assertTrue(msi.FW_RE.match(fw), fw)
                self.assertNotIn(fw, seen)
                seen.add(fw)
            self.assertTrue(set(c["shift"]) <= set(msi.SHIFT_IDS))
            self.assertTrue(set(c["fan"]) <= set(msi.FAN_IDS))
            self.assertIn("auto", c["fan"])
            self.assertIn(c["shift_addr"], (0xF2, 0xD2))
            self.assertIn(c["fan_addr"], (0xF4, 0xD4))
            self.assertIn(c["charge"], (0xEF, 0xD7, None))

    def test_wmi_layout(self):
        acpi = FakeAcpi(regs={0x68: 61})
        w = msi_wmi.MsiWmi(acpi)
        self.assertEqual(w.read(0x68), 61)
        self.assertTrue(bytes(w.fw()).startswith(b"17F2EMS1.106"))
        w.write(0xF2, 0xC4)
        self.assertEqual(acpi.writes, [(0xF2, 0xC4)])
        self.assertEqual(w.fan_rpm(), [3000, 2400])
        with self.assertRaises(ValueError):
            w.read(0x100)
        with self.assertRaises(msi_wmi.WmiError):
            w._call("Set_EC", [0])        # izinsiz yontem hic cagrilmaz
        self.assertNotIn("Set_EC", acpi.calls)

    def test_wmi_failure_status(self):
        bad = types.SimpleNamespace(call=lambda m, d: bytes(32))  # durum bayti 0
        with self.assertRaises(msi_wmi.WmiError):
            msi_wmi.MsiWmi(bad).read(0x68)


# ----------------------------------------------------------------------------- guvenlik kurallari
class SafetyTest(unittest.TestCase):
    def test_known_firmware_writes_table_values(self):
        ec, acpi = make(regs=BASE)
        self.assertTrue(ec.available and ec.read_ok)
        self.assertEqual(ec.caps(), {"power": True, "fan": True, "fan_curve": False, "kb": False, "temps": True})
        ec.set_shift_mode("turbo")
        ec.set_msi_fan_mode("advanced")
        self.assertEqual(acpi.writes, [(0xF2, 0xC4), (0xF4, 0x8D)])
        self.assertEqual(ec.shift_mode(), "turbo")
        self.assertEqual(ec.msi_fan_mode(), "advanced")

    def test_mode_not_in_table_is_rejected(self):
        ec, acpi = make(regs=BASE)  # G1_1: fan modlarinda silent yok
        with self.assertRaises(donanim.Unsupported):
            ec.set_msi_fan_mode("silent")
        with self.assertRaises(donanim.Unsupported):
            ec.set_shift_mode("ludicrous")
        self.assertEqual(acpi.writes, [])

    def test_cooler_boost_only_touches_its_bit(self):
        ec, acpi = make(regs=BASE)
        ec.set_cooler_boost(True)
        self.assertEqual(acpi.mem[0x98], 0x82)
        self.assertTrue(ec.cooler_boost())
        ec.set_cooler_boost(False)
        self.assertEqual(acpi.mem[0x98], 0x02)
        ec.set_cooler_boost(False)                 # zaten kapali: yazma yok
        self.assertEqual(len(acpi.writes), 2)

    def test_charge_limit(self):
        ec, acpi = make(regs=BASE)
        self.assertEqual(ec.charge_limit(), 100)
        ec.set_charge_limit(80)
        self.assertEqual(acpi.mem[0xEF], 0x80 | 80)
        for bad in (5, 81, 101, "x", None):
            with self.assertRaises(ValueError):
                ec.set_charge_limit(bad)
        self.assertEqual(acpi.writes, [(0xEF, 0xD0)])

    def test_charge_limit_disabled_when_bit7_off(self):
        regs = dict(BASE)
        regs[0xEF] = 0x00
        ec, acpi = make(regs=regs)
        self.assertEqual(ec.msi_state()["charge_steps"], [])
        with self.assertRaises(donanim.Unsupported):
            ec.set_charge_limit(80)
        self.assertEqual(acpi.writes, [])

    def test_unknown_firmware_is_read_only(self):
        ec, acpi = make(fw="17F2EMS9.999", regs=BASE)
        self.assertTrue(ec.read_ok)
        self.assertFalse(ec.available)
        self.assertEqual(ec.status()["cpu_temp"], 55)
        for fn in (lambda: ec.set_shift_mode("eco"), lambda: ec.set_msi_fan_mode("auto"),
                   lambda: ec.set_cooler_boost(True), lambda: ec.set_charge_limit(80),
                   lambda: ec.set_power_mode(2), lambda: ec.set_fan_mode(msi.FAN_AUTO),
                   lambda: ec.set_fan_mode(msi.FAN_MAX), lambda: ec.set_fan_curve((60, 30, 80, 50), (60, 30, 80, 50)),
                   lambda: ec.set_wmi(0x46, 0)):
            with self.assertRaises(donanim.Unsupported):
                fn()
        self.assertEqual(acpi.writes, [])
        st = ec.msi_state()
        self.assertEqual((st["shifts"], st["fans"], st["cooler"], st["charge_steps"]), ([], [], False, []))
        self.assertEqual(ec.caps()["fan"], False)
        self.assertIsNone(ec.fan_mode())

    def test_mirror_mismatch_disables_everything(self):
        # Get_EC firmware'i soyluyor ama Get_Data 0xA0'da baska sey okuyor: erisim bicimini anlamiyoruz
        ec, acpi = make(mirror="\x00" * 12, regs=BASE)
        self.assertFalse(ec.read_ok)
        self.assertFalse(ec.available)
        self.assertEqual(ec.status(), {})
        with self.assertRaises(donanim.Unsupported):
            ec.set_shift_mode("eco")
        self.assertEqual(acpi.writes, [])

    def test_garbage_firmware_string(self):
        ec, acpi = make(fw="\xff\xfe??", regs=BASE)
        self.assertFalse(ec.read_ok)
        self.assertEqual(acpi.writes, [])
        self.assertNotIn("Get_Data", acpi.calls)  # bicimsiz metinde EC'ye hic okuma bile gitmez

    def test_failed_verify_locks_all_writes(self):
        ec, acpi = make(regs=BASE, stuck={0xF2})
        with self.assertRaises(msi.EcWriteError):
            ec.set_shift_mode("eco")
        self.assertFalse(ec.available)
        with self.assertRaises(donanim.Unsupported):
            ec.set_msi_fan_mode("auto")
        self.assertEqual(acpi.writes, [(0xF2, 0xC2)])

    def test_no_wmi(self):
        ec = msi.MsiEC(None, None, donanim.Unsupported)
        self.assertFalse(ec.read_ok or ec.available or ec.kb_available)
        self.assertEqual(ec.status(), {})
        self.assertEqual(ec.temps(), (0, 0))
        self.assertEqual(ec.set_color(1, 2, 3), 0)

    def test_gpu_sensor_missing_in_table(self):
        ec, _ = make(fw="14JKEMS1.104", regs=BASE)  # G1_5: ekran karti sensoru yok
        s = ec.status()
        self.assertIn("cpu_temp", s)
        self.assertNotIn("gpu_temp", s)

    def test_status_sanity(self):
        regs = dict(BASE)
        regs[0x68] = 0xFF
        ec, _ = make(regs=regs)
        s = ec.status()
        self.assertNotIn("cpu_temp", s)
        self.assertEqual((s["gpu_temp"], s["cpu_duty"], s["cpu_rpm"], s["gpu_rpm"]), (48, 35, 3000, 2400))


# ----------------------------------------------------------------------------- Clevo arayuzu (profiller)
class CommonInterfaceTest(unittest.TestCase):
    def test_power_mode_mapping(self):
        ec, acpi = make(regs=BASE)                 # G1_1: turbo var
        self.assertEqual(ec.set_power_mode(2), "turbo")
        self.assertEqual(ec.power_mode(), 2)
        ec.set_power_mode(0)
        self.assertEqual(acpi.mem[0xF2], 0xC2)
        ec.set_power_mode(3)
        self.assertEqual(acpi.mem[0xF2], 0xC1)
        ec2, acpi2 = make(fw="14JKEMS1.104", regs=BASE)  # turbo yok: sport
        self.assertEqual(ec2.set_power_mode(2), "sport")
        self.assertEqual(acpi2.mem[0xF2], 0xC0)

    def test_fan_mode_mapping(self):
        ec, acpi = make(fw="16R1EMS1.104", regs=BASE)  # G1_7: tum fan modlari
        ec.set_fan_mode(msi.FAN_MAX)
        self.assertEqual(ec.fan_mode(), msi.FAN_MAX)
        ec.set_fan_mode(msi.FAN_AUTO)
        self.assertEqual(acpi.mem[0x98] & 0x80, 0)
        self.assertEqual(ec.fan_mode(), msi.FAN_AUTO)
        with self.assertRaises(donanim.Unsupported):
            ec.set_fan_mode(msi.FAN_CUSTOM)
        ec.set_fan_curve((70, 30, 84, 50), (70, 30, 84, 50))
        self.assertEqual(ec.msi_fan_mode(), "silent")
        self.assertEqual(ec.fan_mode(), msi.FAN_CUSTOM)
        ec.set_fan_curve((50, 60, 62, 90), (50, 60, 62, 90))
        self.assertEqual(ec.msi_fan_mode(), "auto")
        ec3, _ = make(regs=BASE)                     # G1_1: silent yok -> auto
        ec3.set_fan_curve((70, 30, 84, 50), (70, 30, 84, 50))
        self.assertEqual(ec3.msi_fan_mode(), "auto")

    def test_profiles_on_msi(self):
        import profiller
        ec, acpi = make(fw="16R1EMS1.104", regs=BASE)
        m = profiller.Manager.__new__(profiller.Manager)
        m.dchu = ec
        m.sensors = types.SimpleNamespace(gpu_name="")
        for p in profiller.PROFILES:
            rows = dict(m.describe(p))
            self.assertNotEqual(rows[profiller.t("row.powerMode")], profiller.t("val.unsupported"))
        quiet = profiller.BY_ID["tam_sessiz"]
        m._ec(quiet)
        self.assertEqual(acpi.mem[0xF2], 0xC2)
        msg = m._fan(quiet)
        self.assertEqual(ec.msi_fan_mode(), "silent")
        self.assertIn("MSI", msg)
        m._fan(profiller.BY_ID["performans"])
        self.assertEqual(ec.msi_fan_mode(), "auto")

    def test_profiles_on_readonly_msi_skip(self):
        import profiller
        ec, acpi = make(fw="17F2EMS9.999", regs=BASE)
        m = profiller.Manager.__new__(profiller.Manager)
        m.dchu = ec
        m.sensors = types.SimpleNamespace(gpu_name="")
        with self.assertRaises(donanim.Unsupported):
            m._ec(profiller.BY_ID["performans"])
        with self.assertRaises(donanim.Unsupported):
            m._fan(profiller.BY_ID["tam_sessiz"])
        self.assertEqual(acpi.writes, [])


# ----------------------------------------------------------------------------- klavye
class KeyboardTest(unittest.TestCase):
    def test_zone3_reports(self):
        rep = msi_klavye.zone3_reports(10, 20, 30)
        self.assertEqual(rep[0], ("feature", bytes([1, 2, 0x40, 1, 10, 20, 30, 0xEC])))
        self.assertEqual(rep[-1], ("feature", bytes([1, 2, 0x41, 1, 0, 0, 0, 0xEC])))
        self.assertTrue(all(len(d) == 8 for _, d in rep))

    def test_perkey_reports(self):
        rep = msi_klavye.perkey_v1_reports(1, 2, 3)
        feats = [d for k, d in rep if k == "feature"]
        self.assertEqual(len(feats), 4)
        self.assertTrue(all(len(d) == 525 and d[0] == 0 and d[1] == 0x0E for d in feats))
        self.assertEqual(feats[0][5:9], bytes([1, 2, 3, 0]))
        self.assertEqual(feats[0][-2:], bytes([0x08, 0x39]))
        self.assertEqual(rep[-1], ("output", bytes([0, 9]) + bytes(63)))
        v2 = msi_klavye.perkey_v2_reports(4, 5, 6)
        self.assertEqual(len(v2), 1)
        d = v2[0][1]
        self.assertEqual((len(d), d[1], d[3], d[5:9]), (525, 0x0C, 0x66, bytes([0x04, 4, 5, 6])))

    def test_choose_only_known_devices_with_right_report_size(self):
        def dev(vid, pid, f, o=65):
            return {"vid": vid, "pid": pid, "path": "p%x" % pid, "feature_len": f, "output_len": o}
        self.assertIsNone(msi_klavye.choose([dev(0x1038, 0x1234, 525)]))          # bilinmeyen PID
        self.assertIsNone(msi_klavye.choose([dev(0x1038, 0x1122, 64)]))           # yanlis arayuz
        self.assertIsNone(msi_klavye.choose([dev(0x1038, 0x1122, 525, 0)]))       # cikis raporu yok
        self.assertEqual(msi_klavye.choose([dev(0x1770, 0xFF00, 8)])[1], "zone3")
        self.assertEqual(msi_klavye.choose([dev(0x1038, 0x1122, 525)], "GS65 Stealth")[1], "perkey1")
        self.assertEqual(msi_klavye.choose([dev(0x1038, 0x1122, 525)], "Raider A18 HX")[1], "perkey2")
        self.assertEqual(msi_klavye.choose([dev(0x1038, 0x113A, 525)])[1], "perkey2")

    def test_open_and_throttle(self):
        hid = FakeHid()
        kb = msi_klavye.open_keyboard(enum=lambda: [{"vid": 0x1770, "pid": 0xFF00, "path": "x", "feature_len": 8,
                                                     "output_len": 0}], opener=lambda p: hid, model="")
        self.assertTrue(kb.ok)
        kb.set_color(255, 0, 0)
        n = len(hid.sent)
        self.assertEqual(n, 8)
        kb.set_color(0, 255, 0)            # hemen ardindan: atlanir
        self.assertEqual(len(hid.sent), n)
        kb._last -= 1
        kb.set_color(0, 255, 0)
        self.assertEqual(hid.sent[n][1][4:7], bytes([0, 255, 0]))
        self.assertIsNone(msi_klavye.open_keyboard(enum=lambda: [], opener=lambda p: hid, model=""))

    def test_engine_drives_msi_keyboard(self):
        hid = FakeHid()
        kb = msi_klavye.Keyboard(hid, "zone3")
        ec, acpi = make(fw="17F2EMS9.999", regs=BASE)   # EC yalnizca okuma, klavye yine calisir
        ec.kb = kb
        self.assertTrue(ec.kb_available and ec.caps()["kb"])
        eng = klavye_rgb.Engine(ec)
        eng.settings = ("sabit", ((0, 128, 255),), 50, "cpu_temp", 1.0)
        eng.start()
        time.sleep(0.3)
        eng.running = False
        eng.join(2)
        self.assertEqual(eng.error, "")
        self.assertIn(("feature", bytes([1, 2, 0x40, 1, 0, 128, 255, 0xEC])), hid.sent)
        self.assertEqual(acpi.writes, [])

    def test_engine_without_keyboard_sends_nothing(self):
        ec, acpi = make(regs=BASE)
        eng = klavye_rgb.Engine(ec)
        eng.settings = ("oyun", ((0, 0, 0),), 50, "lol", 1.0)
        eng.start()
        time.sleep(0.2)
        eng.running = False
        eng.join(2)
        self.assertEqual(eng.error, "")
        self.assertEqual(acpi.writes, [])


# ----------------------------------------------------------------------------- tespit ve Clevo yolu
class DetectTest(unittest.TestCase):
    def test_is_msi(self):
        self.assertTrue(msi.is_msi("Micro-Star International Co., Ltd."))
        self.assertFalse(msi.is_msi("Monster Notebook"))
        self.assertFalse(msi.is_msi("ASUSTeK COMPUTER INC."))

    def test_open_msi_non_msi_returns_none(self):
        called = []
        r = msi.open_msi(maker="Dell Inc.", wmi_factory=lambda: called.append(1), kb_factory=lambda: called.append(2))
        self.assertIsNone(r)
        self.assertEqual(called, [])          # MSI degilse WMI/HID'e hic dokunulmaz

    def test_open_msi_without_msi_acpi(self):
        r = msi.open_msi(maker="Micro-Star International Co., Ltd.", wmi_factory=lambda: None, kb_factory=lambda: None)
        self.assertIsInstance(r, msi.MsiEC)
        self.assertFalse(r.read_ok or r.available)

    def test_open_dchu_routes(self):
        with mock.patch.object(donanim, "clevo_present", return_value=False), \
                mock.patch.object(msi, "is_msi", return_value=False):
            self.assertIsInstance(donanim.open_dchu(), donanim.NullDCHU)
        fake = msi.MsiEC(None, None, donanim.Unsupported)
        with mock.patch.object(donanim, "clevo_present", return_value=False), \
                mock.patch.object(msi, "open_msi", return_value=fake):
            self.assertIs(donanim.open_dchu(), fake)
        sentinel = object()
        with mock.patch.object(donanim, "clevo_present", return_value=True), \
                mock.patch.object(donanim, "DCHU", return_value=sentinel), \
                mock.patch.object(msi, "open_msi") as om:
            self.assertIs(donanim.open_dchu(), sentinel)   # Clevo'da MSI koduna hic girilmez
            om.assert_not_called()

    def test_clevo_and_null_caps(self):
        self.assertEqual(donanim.DCHU.kind, "clevo")
        self.assertTrue(all(donanim.DCHU.caps().values()))
        n = donanim.NullDCHU("x")
        self.assertFalse(any(n.caps().values()))
        self.assertFalse(n.kb_available)

    def test_control_center_caps_and_clevo_only_steps(self):
        import control_center as cc
        ec, _ = make(regs=BASE)
        with mock.patch.object(cc.App, "dchu", ec):
            self.assertEqual(cc.caps()["fan_curve"], False)
            self.assertEqual(cc.msi_state()["fw"], "17F2EMS1.106")
        with mock.patch.object(cc.App, "dchu", donanim.NullDCHU("x")):
            self.assertIsNone(cc.msi_state())
        with open(cc.__file__, encoding="utf-8") as f:
            src = f.read()
        # Clevo'ya ozel Fn olayi komutu ve IFEO engellemesi yalnizca kind == "clevo" iken
        self.assertIn('App.dchu.available and getattr(App.dchu, "kind", "clevo") == "clevo":\n        try:\n'
                      '            App.dchu.set_wmi(0x46, 0)', src)


if __name__ == "__main__":
    unittest.main()
