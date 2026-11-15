# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""ideapad birim testleri: sahte WMI ve sahte EnergyDrv ile (donanima hicbir komut gitmez).

Calistirma:  python -m unittest tests.test_ideapad -v
"""
import unittest
from unittest import mock
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import donanim as hw
import ideapad as ip

IDEAPAD = {"SystemManufacturer": "LENOVO", "SystemProductName": "82KU",
           "SystemFamily": "IdeaPad 5 14ALC05", "SystemVersion": "IdeaPad 5 14ALC05"}
GAMING = {"SystemManufacturer": "LENOVO", "SystemProductName": "82K2",
          "SystemFamily": "IdeaPad Gaming 3 15ACH6", "SystemVersion": "IdeaPad Gaming 3 15ACH6"}
LEGION = {"SystemManufacturer": "LENOVO", "SystemProductName": "82JW",
          "SystemFamily": "Legion 5 15ACH6H", "SystemVersion": "Legion 5 15ACH6H"}


def swap(v):
    """EnergyDrv'nin dondurdugu ham deger: bayt sirasi ters."""
    return int.from_bytes(v.to_bytes(4, "big"), "little")


RAW = {"normal": swap(0), "conservation": swap(1 << 29), "rapid": swap((1 << 17) | (1 << 26)),
       "rapid_off": swap(1 << 17)}


class FakeWmi:
    """reads: {yontem: deger | Exception}; Set* yazmalari self.writes'a kaydedilir."""

    def __init__(self, reads=None, instance=True):
        self.reads = dict(reads or {})
        self.instance = instance
        self.writes = []
        self.closed = False

    def query(self, wql, props=None):
        return [{"__PATH": "LENOVO_GAMEZONE_DATA.InstanceName=\"ACPI\\\\PNP0C14\\\\GMZN_0\""}] if self.instance else []

    def methods(self, cls):
        return list(self.reads) + ["SetSmartFanMode"]

    def call(self, path, cls, method, args, out_name):
        assert cls == ip.GAMEZONE
        if method.startswith("Set"):
            self.writes.append((method, dict(args)))
            if method == "SetSmartFanMode":
                self.reads["GetSmartFanMode"] = args["Data"]
            return 0
        v = self.reads[method]
        if isinstance(v, Exception):
            raise v
        return v

    def close(self):
        self.closed = True


class FakeEnergy:
    def __init__(self, state="normal", fail=False):
        self.state = state
        self.fail = fail
        self.codes = []

    def __call__(self, code):
        if self.fail:
            raise OSError(2, "EnergyDrv yok")
        self.codes.append(code)
        if code == 0xFF:
            return RAW[self.state]
        self.state = {0x3: "conservation", 0x5: "normal", 0x7: "rapid", 0x8: "normal"}[code]
        return 0


def gz_reads(**over):
    r = {"IsSupportSmartFan": 1, "GetSmartFanMode": 2, "GetCPUTemp": 58, "GetGPUTemp": 0,
         "GetFan1Speed": 2400, "GetFan2Speed": 2300}
    r.update(over)
    return r


def make(reads=None, energy_state="normal", energy_fail=False, info=IDEAPAD):
    w = FakeWmi(gz_reads() if reads is None else reads)
    fe = FakeEnergy(energy_state, energy_fail)
    dev = ip.open_ideapad(info, wmi=w, energy=ip.EnergyDrv(io=fe))
    return dev, w, fe


class TestDetect(unittest.TestCase):
    def test_ideapad(self):
        self.assertTrue(ip.is_ideapad(IDEAPAD))
        self.assertTrue(ip.is_ideapad(GAMING))
        self.assertTrue(ip.is_ideapad(dict(IDEAPAD, SystemManufacturer=" lenovo ")))

    def test_not_ideapad(self):
        self.assertFalse(ip.is_ideapad(LEGION))
        self.assertFalse(ip.is_ideapad(dict(IDEAPAD, SystemFamily="LOQ 15APH8", SystemVersion="LOQ 15APH8")))
        self.assertFalse(ip.is_ideapad(dict(IDEAPAD, SystemManufacturer="ASUSTeK COMPUTER INC.")))
        self.assertFalse(ip.is_ideapad({"SystemManufacturer": "LENOVO", "SystemFamily": "ThinkPad T14 Gen 3"}))
        self.assertFalse(ip.is_ideapad({}))

    def test_model_name(self):
        self.assertEqual(ip.model_name(IDEAPAD), "IdeaPad 5 14ALC05")

    def test_non_ideapad_touches_nothing(self):
        w = mock.Mock()
        energy = mock.Mock()
        self.assertIsNone(ip.open_ideapad(LEGION, wmi=w, energy=energy))
        w.assert_not_called()
        self.assertEqual(w.method_calls, [])
        self.assertEqual(energy.method_calls, [])

    def test_no_interface_returns_none(self):
        w = FakeWmi({}, instance=False)
        fe = FakeEnergy(fail=True)
        self.assertIsNone(ip.open_ideapad(IDEAPAD, wmi=w, energy=ip.EnergyDrv(io=fe)))
        self.assertTrue(w.closed)


class TestPower(unittest.TestCase):
    def test_probe_and_read(self):
        dev, w, _ = make()
        self.assertEqual(dev.kind, "ideapad")
        self.assertEqual(dev.power_modes(), [0, 2, 3])
        self.assertEqual(dev.power_mode(), 3)  # Lenovo dengeli -> uygulamanin Eglence modu
        self.assertEqual(w.writes, [])  # acilista yalnizca okuma

    def test_set_power_mode(self):
        dev, w, _ = make()
        dev.set_power_mode(2)
        self.assertEqual(w.writes, [("SetSmartFanMode", {"Data": ip.L_PERF})])
        dev.set_power_mode(2)  # ayni mod: yeniden yazilmaz
        self.assertEqual(len(w.writes), 1)
        dev.set_power_mode(1)  # guc tasarrufu -> sessiz
        self.assertEqual(w.writes[-1], ("SetSmartFanMode", {"Data": ip.L_QUIET}))
        self.assertEqual(dev.power_mode(), 0)

    def test_bad_mode(self):
        dev, w, _ = make()
        with self.assertRaises(ValueError):
            dev.set_power_mode(9)
        self.assertEqual(w.writes, [])

    def test_unsupported_smartfan(self):
        dev, w, _ = make(gz_reads(IsSupportSmartFan=0))
        self.assertEqual(dev.power_modes(), [])
        self.assertIsNone(dev.power_mode())
        with self.assertRaises(hw.Unsupported):
            dev.set_power_mode(2)
        self.assertEqual(w.writes, [])

    def test_mode_unreadable_no_write(self):
        dev, w, _ = make(gz_reads(GetSmartFanMode=RuntimeError("WMI")))
        with self.assertRaises(hw.Unsupported):
            dev.set_power_mode(2)
        self.assertEqual(w.writes, [])

    def test_unknown_mode_value_no_write(self):
        dev, w, _ = make(gz_reads(GetSmartFanMode=7))
        self.assertEqual(dev.power_modes(), [])
        self.assertEqual(w.writes, [])

    def test_energy_only(self):
        """GameZone yok (IdeaPad Slim): yalnizca pil modu; guc modu atlanir."""
        w = FakeWmi({}, instance=False)
        fe = FakeEnergy("conservation")
        dev = ip.open_ideapad(IDEAPAD, wmi=w, energy=ip.EnergyDrv(io=fe))
        self.assertIsNotNone(dev)
        self.assertEqual(dev.power_modes(), [])
        with self.assertRaises(hw.Unsupported):
            dev.set_power_mode(2)
        self.assertEqual(dev.features()["battery_mode"], "conservation")
        self.assertFalse(dev.ec_temps)
        self.assertEqual(dev.status(), {})


class TestSensorsAndFans(unittest.TestCase):
    def test_status_filters_implausible(self):
        dev, _, _ = make()
        self.assertEqual(dev.status(), {"cpu_temp": 58, "cpu_rpm": 2400, "gpu_rpm": 2300})  # kart 0 C: okunamadi
        self.assertTrue(dev.ec_temps)
        self.assertEqual(dev.temps(), (58, None))
        self.assertTrue(dev.features()["fan_rpm"])

    def test_fans_firmware_only(self):
        dev, w, fe = make()
        self.assertFalse(dev.fan_control)
        self.assertEqual(dev.fan_mode(), hw.FAN_AUTO)
        dev.set_fan_mode(hw.FAN_AUTO)  # bos islem
        with self.assertRaises(hw.Unsupported):
            dev.set_fan_mode(hw.FAN_MAX)
        with self.assertRaises(hw.Unsupported):
            dev.set_fan_curve((60, 40, 75, 70), (60, 40, 75, 70))
        self.assertIsNone(dev.fan_default())
        self.assertEqual(w.writes, [])
        self.assertEqual(dev.set_color(255, 0, 0), 0)
        with self.assertRaises(hw.Unsupported):
            dev.set_wmi(0x46, 0)


class TestEnergy(unittest.TestCase):
    def test_decode(self):
        for state in ("normal", "conservation", "rapid"):
            self.assertEqual(ip.EnergyDrv.decode(RAW[state]), state)
        self.assertEqual(ip.EnergyDrv.decode(RAW["rapid_off"]), "normal")

    def test_sequence(self):
        seq = ip.EnergyDrv.sequence
        self.assertEqual(seq("normal", "normal"), [])
        self.assertEqual(seq("normal", "conservation"), [0x3])
        self.assertEqual(seq("rapid", "conservation"), [0x8, 0x3])
        self.assertEqual(seq("normal", "rapid"), [0x7])
        self.assertEqual(seq("conservation", "rapid"), [0x5, 0x7])
        self.assertEqual(seq("conservation", "normal"), [0x5])
        self.assertEqual(seq("rapid", "normal"), [0x8])

    def test_switch_conservation_to_rapid(self):
        dev, _, fe = make(energy_state="conservation")
        fe.codes.clear()
        out = dev.handle({"battery": "rapid"})
        self.assertEqual(out["battery_mode"], "rapid")
        self.assertEqual([c for c in fe.codes if c != 0xFF], [0x5, 0x7])

    def test_missing_driver(self):
        dev, _, fe = make(energy_fail=True)
        self.assertFalse(dev.features()["battery"])
        self.assertIsNone(dev.battery_mode())
        with self.assertRaises(hw.Unsupported):
            dev.set_battery_mode("conservation")

    def test_bad_value(self):
        dev, _, fe = make()
        fe.codes.clear()
        with self.assertRaises(ValueError):
            dev.handle({"battery": "turbo"})
        self.assertEqual(fe.codes, [])


class TestOpenDchu(unittest.TestCase):
    def test_ideapad_selected_after_asus(self):
        sentinel = object()
        with mock.patch.object(hw, "clevo_present", return_value=False), \
                mock.patch("alienware.open_alienware", return_value=(None, "")), \
                mock.patch("asus_rog.asus_present", return_value=False), \
                mock.patch.object(ip, "open_ideapad", return_value=sentinel):
            self.assertIs(hw.open_dchu(), sentinel)

    def test_falls_back_to_null(self):
        with mock.patch.object(hw, "clevo_present", return_value=False), \
                mock.patch("alienware.open_alienware", return_value=(None, "")), \
                mock.patch("asus_rog.asus_present", return_value=False), \
                mock.patch.object(ip, "open_ideapad", return_value=None):
            dev = hw.open_dchu()
        self.assertIsInstance(dev, hw.NullDCHU)
        self.assertFalse(dev.available)


if __name__ == "__main__":
    unittest.main()
