# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""asus_rog birim testleri: sahte ATK tasimasi, sahte WMI ve sahte HID ile (donanima hicbir komut gitmez).

Calistirma:  python -m unittest test_asus_rog -v
"""
import os
import tempfile
import unittest
from unittest import mock

import asus_rog as ar
import donanim as hw

P = ar.PRESENCE
FACTORY = bytes([30, 40, 50, 60, 70, 80, 90, 100]) + bytes([0, 10, 20, 35, 50, 65, 80, 100])


class FakeAtk:
    """dsts degerleri: {aygit: ham}; egriler: {(aygit, arg): 16 bayt}. Tum yazmalar self.writes'a kaydedilir."""
    name = "FAKE"

    def __init__(self, regs=None, curves=None, buffers=True):
        self.regs = dict(regs or {})
        self.curves = dict(curves or {})
        self.buffers = buffers
        self.writes = []
        self.buf_reads = []

    def dsts(self, dev, arg=0):
        return self.regs.get(dev, ar.UNSUPPORTED)

    def dsts_buf(self, dev, arg=0):
        self.buf_reads.append((dev, arg))
        return self.curves.get((dev, arg), bytes(16))

    def devs(self, dev, val):
        self.writes.append((dev, val))
        if dev in (ar.DEV_ECO, ar.DEV_MUX, ar.DEV_MUX_VIVO):
            self.regs[dev] = P | val
        return 1

    def devs_buf(self, dev, payload):
        self.writes.append((dev, bytes(payload)))
        return 1


def full_regs(**over):
    regs = {ar.DEV_THROTTLE: P | 0, ar.DEV_FAN_CPU: P | 35, ar.DEV_FAN_GPU: P | 28, ar.DEV_BATTERY: P | 100,
            ar.DEV_MUX: P | 1, ar.DEV_ECO: P | 0, ar.DEV_TEMP_CPU: P | 62, ar.DEV_KBD_LIGHT: P | 3}
    for k, v in over.items():
        regs[getattr(ar, k)] = v
    return regs


def full_curves():
    return {(d, a): FACTORY for d in (ar.DEV_CURVE_CPU, ar.DEV_CURVE_GPU) for a in (0, 1, 2)}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfg = os.path.join(self.tmp, "asus.json")

    def make(self, regs=None, curves=None, kb=None, buffers=True):
        t = FakeAtk(full_regs() if regs is None else regs, full_curves() if curves is None else curves, buffers)
        return ar.AsusRog(t, kb, self.cfg), t


class TestDsts(unittest.TestCase):
    def test_presence_bit(self):
        self.assertTrue(ar.supported(P | 5))
        self.assertTrue(ar.supported(P))
        self.assertFalse(ar.supported(5))
        self.assertFalse(ar.supported(0))
        self.assertFalse(ar.supported(ar.UNSUPPORTED))
        self.assertFalse(ar.supported(0xFFFFFFFF))
        self.assertFalse(ar.supported(None))
        self.assertEqual(ar.value(P | 0x23), 0x23)


class TestDetection(unittest.TestCase):
    @staticmethod
    def factory(maker, has_class=True, fail=False):
        calls = []

        class W:
            def __init__(self, ns):
                if fail:
                    raise OSError("WMI yok")
                calls.append(ns)

            def query(self, wql, props=None):
                if "Win32_ComputerSystem" in wql:
                    return [{"Manufacturer": maker}]
                return [{"__PATH": "x"}] if has_class else []

            def close(self):
                pass
        return W, calls

    def test_asus(self):
        W, _ = self.factory("ASUSTeK COMPUTER INC.")
        self.assertTrue(ar.asus_present(W))

    def test_asus_without_atk_class(self):
        W, _ = self.factory("ASUSTeK COMPUTER INC.", has_class=False)
        self.assertFalse(ar.asus_present(W))

    def test_other_vendor_never_touches_root_wmi(self):
        for maker in ("Monster", "Dell Inc.", "Alienware", "", None):
            W, calls = self.factory(maker)
            self.assertFalse(ar.asus_present(W))
            self.assertNotIn(r"root\WMI", calls)

    def test_wmi_error_is_false(self):
        W, _ = self.factory("ASUSTeK", fail=True)
        self.assertFalse(ar.asus_present(W))


class TestNothingSupported(Base):
    """Hicbir ozellik yoksa hicbir yazma gitmemeli; her yazma Unsupported."""

    def test_no_commands(self):
        dev, t = self.make(regs={}, curves={})
        for fn in (lambda: dev.set_power_mode(2), lambda: dev.set_fan_curve((60, 40, 80, 60), (60, 40, 80, 60)),
                   lambda: dev.set_fan_mode(hw.FAN_MAX), lambda: dev.set_battery_limit(80),
                   lambda: dev.set_gpu_mode("eco"), lambda: dev.set_wmi(0x46, 0)):
            with self.assertRaises(hw.Unsupported):
                fn()
        dev.set_fan_mode(hw.FAN_AUTO)  # profiller ve isi bekcisi cagirir: sessizce hicbir sey yapmaz
        dev.set_color(255, 0, 0)       # klavye yok: sessiz
        self.assertEqual(t.writes, [])
        self.assertEqual(dev.status(), {})
        self.assertIsNone(dev.fan_default())
        self.assertIsNone(dev.power_mode())
        f = dev.features()
        self.assertEqual(f["power_modes"], [])
        self.assertEqual(f["gpu_modes"], [])
        self.assertIsNone(f["gpu"])
        self.assertFalse(f["battery"] or f["fan_curve"] or f["kb"])
        self.assertFalse(dev.fan_control or dev.ec_temps or dev.kb_available)

    def test_probe_exceptions_mean_unsupported(self):
        class Broken(FakeAtk):
            def dsts(self, dev, arg=0):
                raise OSError("io")
        dev = ar.AsusRog(Broken(), None, self.cfg)
        self.assertFalse(any(dev.feat.values()))


class TestPower(Base):
    def test_mapping(self):
        dev, t = self.make()
        self.assertEqual(dev.power_mode(), 3)  # okunan dengeli (0) -> uygulamada "eglence" (3)
        for m in (2, 0, 3, 1):
            dev.set_power_mode(m)
        self.assertEqual(t.writes, [(ar.DEV_THROTTLE, ar.ASUS_TURBO), (ar.DEV_THROTTLE, ar.ASUS_SILENT),
                                    (ar.DEV_THROTTLE, ar.ASUS_BALANCED), (ar.DEV_THROTTLE, ar.ASUS_SILENT)])
        self.assertEqual(dev.power_mode(), 0)
        self.assertEqual(dev.power_modes(), [0, 2, 3])
        with self.assertRaises(ValueError):
            dev.set_power_mode(7)


class TestFans(Base):
    def test_rpm_and_temp(self):
        dev, _ = self.make()
        s = dev.status()
        self.assertEqual((s["cpu_rpm"], s["gpu_rpm"], s["cpu_temp"]), (3500, 2800, 62))
        self.assertEqual(dev.temps(), (62, None))

    def test_invalid_rpm_dropped(self):
        dev, _ = self.make(regs=full_regs(DEV_FAN_CPU=P | 500))
        self.assertNotIn("cpu_rpm", dev.status())

    def test_curve_read_swaps_modes(self):
        dev, t = self.make(regs=full_regs(DEV_THROTTLE=P | ar.ASUS_TURBO))
        self.assertIn((ar.DEV_CURVE_CPU, 2), t.buf_reads)  # turbo (1) icin arguman 2
        dev.set_power_mode(0)  # sessiz (2) -> arguman 1
        dev.fan_default()
        self.assertIn((ar.DEV_CURVE_CPU, 1), t.buf_reads)

    def test_fan_default_shape(self):
        dev, _ = self.make()
        d = dev.fan_default()
        self.assertEqual(d["count"], 2)
        self.assertEqual(d["cpu"][0], (30, 0))
        self.assertEqual(d["cpu"][-1], (100, 100))
        self.assertEqual(len(d["gpu"]), 4)

    def test_set_curve(self):
        dev, t = self.make()
        dev.set_fan_curve((60, 40, 80, 70), (55, 30, 85, 60))
        self.assertEqual(dev.fan_mode(), hw.FAN_CUSTOM)
        self.assertEqual([w[0] for w in t.writes], [ar.DEV_CURVE_CPU, ar.DEV_CURVE_GPU])
        for _, payload in t.writes:
            self.assertEqual(len(payload), 16)
            temps, pct = list(payload[:8]), list(payload[8:])
            self.assertEqual(temps, list(FACTORY[:8]))
            self.assertEqual(pct, sorted(pct))
            self.assertTrue(all(0 <= p <= 100 for p in pct))
            self.assertEqual(pct[-1], 100)  # 100 C'de %100
        cpu_pct = list(t.writes[0][1][8:])
        self.assertEqual((cpu_pct[3], cpu_pct[5]), (40, 70))  # 60 C -> %40, 80 C -> %70

    def test_curve_safety_floor(self):
        """donanim.validate_curve: 88 C'den once en az %45; daha dusuk istense de yazilan egri altina inmez."""
        _, pct = ar.AsusRog.curve_points(FACTORY, (50, 5, 60, 10))
        self.assertGreaterEqual(pct[5], 45)  # 80 C

    def test_gpu_curve_missing(self):
        dev, t = self.make(curves={(ar.DEV_CURVE_CPU, a): FACTORY for a in (0, 1, 2)})
        self.assertTrue(dev.feat["curve_cpu"])
        self.assertFalse(dev.feat["curve_gpu"])
        dev.set_fan_curve((60, 40, 80, 70), (60, 40, 80, 70))
        self.assertEqual([w[0] for w in t.writes], [ar.DEV_CURVE_CPU])  # kart egrisine hic yazilmadi

    def test_implausible_curve_is_unsupported(self):
        bad = bytes([90, 80, 70, 60, 50, 40, 30, 20]) + bytes(8)
        dev, t = self.make(curves={(d, a): bad for d in (ar.DEV_CURVE_CPU, ar.DEV_CURVE_GPU) for a in (0, 1, 2)})
        self.assertFalse(dev.fan_control)
        with self.assertRaises(hw.Unsupported):
            dev.set_fan_curve((60, 40, 80, 70), (60, 40, 80, 70))
        self.assertEqual(t.writes, [])

    def test_wmi_transport_has_no_curves(self):
        dev, t = self.make(buffers=False)
        self.assertFalse(dev.fan_control)
        self.assertEqual(t.buf_reads, [])

    def test_max_and_auto(self):
        dev, t = self.make()
        dev.set_fan_mode(hw.FAN_MAX)
        self.assertEqual(dev.fan_mode(), hw.FAN_MAX)
        self.assertEqual(t.writes[0], (ar.DEV_CURVE_CPU, FACTORY[:8] + bytes([100] * 8)))
        t.writes.clear()
        dev.set_fan_mode(hw.FAN_AUTO)
        self.assertEqual(t.writes, [(ar.DEV_THROTTLE, ar.ASUS_BALANCED)])  # politika yeniden yazilir
        self.assertEqual(dev.fan_mode(), hw.FAN_AUTO)
        with self.assertRaises(ValueError):
            dev.set_fan_mode(42)


class TestBattery(Base):
    def test_clamp_save_restore(self):
        dev, t = self.make()
        self.assertEqual(dev.set_battery_limit(10), ar.BATTERY_MIN)
        self.assertEqual(dev.set_battery_limit(80), 80)
        self.assertEqual(t.writes[-1], (ar.DEV_BATTERY, 80))
        dev2, t2 = self.make()
        dev2.restore()
        self.assertEqual(t2.writes, [(ar.DEV_BATTERY, 80)])
        self.assertEqual(dev2.battery_limit(), 80)

    def test_handle(self):
        dev, _ = self.make()
        out = dev.handle({"battery": "60"})
        self.assertEqual(out["battery_limit"], 60)
        self.assertTrue(out["asus"]["battery"])
        with self.assertRaises(ValueError):
            dev.handle({"battery": "abc"})


class TestGpu(Base):
    def test_modes_listed(self):
        dev, _ = self.make()
        self.assertEqual(dev.gpu_modes(), ["eco", "standard", "ultimate"])
        self.assertEqual(dev.gpu_state()["mode"], "standard")
        dev2, _ = self.make(regs=full_regs(DEV_MUX=ar.UNSUPPORTED))
        self.assertEqual(dev2.gpu_modes(), ["eco", "standard"])

    def test_vivo_mux(self):
        dev, t = self.make(regs=full_regs(DEV_MUX=ar.UNSUPPORTED, DEV_MUX_VIVO=P | 1))
        self.assertEqual(dev.mux_dev, ar.DEV_MUX_VIVO)
        self.assertTrue(dev.set_gpu_mode("ultimate")["reboot"])
        self.assertEqual(t.writes, [(ar.DEV_MUX_VIVO, 0)])

    def test_eco(self):
        dev, t = self.make()
        self.assertFalse(dev.set_gpu_mode("eco")["reboot"])
        self.assertEqual(t.writes, [(ar.DEV_ECO, 1)])
        self.assertEqual(dev.gpu_state()["mode"], "eco")

    def test_eco_refused_in_ultimate(self):
        dev, t = self.make(regs=full_regs(DEV_MUX=P | 0))
        with self.assertRaises(hw.Unsupported):
            dev.set_gpu_mode("eco")
        self.assertEqual(t.writes, [])

    def test_ultimate_turns_eco_off_first(self):
        dev, t = self.make(regs=full_regs(DEV_ECO=P | 1))
        self.assertTrue(dev.set_gpu_mode("ultimate")["reboot"])
        self.assertEqual(t.writes, [(ar.DEV_ECO, 0), (ar.DEV_MUX, 0)])

    def test_standard_from_ultimate(self):
        dev, t = self.make(regs=full_regs(DEV_MUX=P | 0))
        self.assertTrue(dev.set_gpu_mode("standard")["reboot"])
        self.assertEqual(t.writes, [(ar.DEV_MUX, 1)])

    def test_xg_mobile_blocks(self):
        dev, t = self.make(regs=full_regs(DEV_EGPU=P | 1))
        for m in ("eco", "standard", "ultimate"):
            with self.assertRaises(hw.Unsupported):
                dev.set_gpu_mode(m)
        self.assertEqual(t.writes, [])

    def test_unknown_mode_rejected(self):
        dev, t = self.make()
        with self.assertRaises(hw.Unsupported):
            dev.set_gpu_mode("turbo")
        self.assertEqual(t.writes, [])

    def test_unreadable_state_writes_nothing(self):
        class Flaky(FakeAtk):
            reads = 0

            def dsts(self, dev, arg=0):
                if dev == ar.DEV_MUX:
                    if self.reads:  # acilistan sonra MUX okunamaz
                        raise OSError("io")
                    self.reads += 1
                return super().dsts(dev, arg)
        t = Flaky(full_regs(), full_curves())
        dev = ar.AsusRog(t, None, self.cfg)
        with self.assertRaises(hw.Unsupported):
            dev.set_gpu_mode("ultimate")
        self.assertEqual(t.writes, [])


class FakeHidDev:
    def __init__(self, info):
        self.info = info
        self.sent = []

    def set_feature(self, data, length=None):
        self.sent.append(list(data))

    def write(self, data, length=None):
        raise AssertionError("set_feature calisiyorken write cagrilmamali")

    def close(self):
        pass


class FakeHid:
    def __init__(self, infos):
        self.infos = infos

    def enumerate_devices(self, vids=None):
        return [i for i in self.infos if not vids or i["vid"] in vids]

    @staticmethod
    def HidDevice(info):
        return FakeHidDev(info)


class TestAura(Base):
    INFOS = [
        {"path": "kbd", "vid": 0x0B05, "pid": 0x19B6, "usage_page": 0x0001, "feat_len": 0},     # klavye girisi
        {"path": "other", "vid": 0x0B05, "pid": 0x9999, "usage_page": 0xFF31, "feat_len": 65},  # bilinmeyen PID
        {"path": "aura", "vid": 0x0B05, "pid": 0x19B6, "usage_page": 0xFF31, "feat_len": 65},
    ]

    def test_find_and_init(self):
        kb = ar.AuraKeyboard.find(FakeHid(self.INFOS))
        self.assertIsNotNone(kb)
        self.assertEqual(kb.dev.info["path"], "aura")
        self.assertEqual(kb.dev.sent[0], [0x5D, 0xB9])
        self.assertEqual(bytes(kb.dev.sent[1][1:]), b"ASUS Tech.Inc.")

    def test_not_found(self):
        self.assertIsNone(ar.AuraKeyboard.find(FakeHid(self.INFOS[:2])))
        self.assertIsNone(ar.AuraKeyboard.find(FakeHid([])))

    def test_color_frames_and_debounced_save(self):
        kb = ar.AuraKeyboard.find(FakeHid(self.INFOS))
        sent = kb.dev.sent
        sent.clear()
        clock = [100.0]
        with mock.patch.object(ar.time, "monotonic", lambda: clock[0]):
            kb.set_color(255, 10, 0)
            self.assertEqual(sent[0][:9], [0x5D, 0xB3, 0, 0, 255, 10, 0, 0xEB, 0])
            self.assertEqual(sent[1], [0x5D, 0xB5, 0, 0, 0])
            n = len(sent)
            clock[0] += 0.05
            kb.set_color(255, 10, 0)  # ayni renk: gonderilmez
            self.assertEqual(len(sent), n)
            clock[0] += 2.5
            kb.set_color(255, 10, 0)  # 2 sn sabit: bir kez kaydet
            self.assertEqual(sent[-1], [0x5D, 0xB4])
            kb.set_color(255, 10, 0)
            self.assertEqual(sent.count([0x5D, 0xB4]), 1)
            for i in range(50):  # animasyon: kaydetme yok
                clock[0] += 0.05
                kb.set_color(i, 0, 0)
            self.assertEqual(sent.count([0x5D, 0xB4]), 1)

    def test_backend_turns_backlight_on_once(self):
        kb = ar.AuraKeyboard.find(FakeHid(self.INFOS))
        dev, t = self.make(kb=kb)
        self.assertTrue(dev.kb_available)
        dev.set_color(0, 0, 0)
        self.assertEqual(t.writes, [])
        dev.set_color(10, 20, 30)
        dev.set_color(40, 50, 60)
        self.assertEqual(t.writes, [(ar.DEV_KBD_LIGHT, 0x83)])
        self.assertEqual(kb.last, (40, 50, 60))

    def test_brightness_device_missing(self):
        kb = ar.AuraKeyboard.find(FakeHid(self.INFOS))
        dev, t = self.make(regs=full_regs(DEV_KBD_LIGHT=ar.UNSUPPORTED), kb=kb)
        dev.set_color(10, 20, 30)
        self.assertEqual(t.writes, [])
        self.assertEqual(kb.last, (10, 20, 30))


class TestWmiTransport(unittest.TestCase):
    def test_calls(self):
        calls = []

        class W:
            def query(self, wql, props=None):
                return [{"__PATH": "ATK_0"}]

            def call(self, path, cls, method, args, out):
                calls.append((cls, method, args, out))
                return P | 1

            def close(self):
                pass
        t = ar.WmiAtk(W())
        self.assertEqual(t.dsts(ar.DEV_MUX), P | 1)
        t.devs(ar.DEV_BATTERY, 80)
        self.assertEqual(calls[0], ("AsusAtkWmi_WMNB", "DSTS", {"Device_ID": ar.DEV_MUX}, "device_status"))
        self.assertEqual(calls[1], ("AsusAtkWmi_WMNB", "DEVS", {"Device_ID": ar.DEV_BATTERY, "Control_status": 80},
                                    "result"))
        with self.assertRaises(hw.Unsupported):
            t.dsts_buf(ar.DEV_CURVE_CPU)

    def test_no_instance(self):
        class W:
            def query(self, wql, props=None):
                return []
        with self.assertRaises(OSError):
            ar.WmiAtk(W())


class TestOpenDchu(unittest.TestCase):
    """donanim.open_dchu secimi: Clevo once, sonra Alienware, sonra Asus; hicbiri yoksa NullDCHU."""

    @staticmethod
    def _alien(ec=None, err=None):
        import alienware
        return mock.patch.object(alienware, "open_alienware", return_value=(ec, err))

    def test_clevo_never_probes_asus(self):
        sentinel = object()
        with mock.patch.object(hw, "clevo_present", return_value=True), \
                mock.patch.object(hw, "DCHU", return_value=sentinel), \
                mock.patch.object(ar, "asus_present", side_effect=AssertionError("Clevo'da Asus sinanmamali")):
            self.assertIs(hw.open_dchu(), sentinel)

    def test_alienware_wins(self):
        sentinel = object()
        with mock.patch.object(hw, "clevo_present", return_value=False), self._alien(sentinel), \
                mock.patch.object(ar, "asus_present", side_effect=AssertionError("Alienware'de Asus sinanmamali")):
            self.assertIs(hw.open_dchu(), sentinel)

    def test_asus_selected(self):
        """Asus yolunda InsydeDCHU (donanim.DCHU) hic yuklenmez; arka ucun kind degeri tam olarak 'asus'."""
        dev = ar.AsusRog(FakeAtk(full_regs(), full_curves()), None, None)
        with mock.patch.object(hw, "clevo_present", return_value=False), self._alien(), \
                mock.patch.object(hw, "DCHU", side_effect=AssertionError("Asus'ta InsydeDCHU yuklenmemeli")), \
                mock.patch.object(ar, "asus_present", return_value=True), \
                mock.patch.object(ar, "open_asus", return_value=dev):
            got = hw.open_dchu()
        self.assertIs(got, dev)
        self.assertEqual(got.kind, "asus")
        self.assertFalse(got.clevo)

    def test_control_center_gates_clevo_code_on_kind(self):
        """Fn olaylari (0x46) ve Monster Fn engeli (engelle.py) yalnizca kind == 'clevo' iken calisir."""
        import re
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "control_center.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertRegex(src, r'if App\.dchu\.kind == "clevo":\s*\n\s*try:\s*\n\s*App\.dchu\.set_wmi\(0x46')
        self.assertRegex(src, r'App\.dchu\.kind == "clevo".*\n\s*threading\.Thread\(target=fn_block_loop')
        self.assertEqual(len(re.findall(r"set_wmi\(0x46", src)), 1)

    def test_asus_open_failure_is_null(self):
        with mock.patch.object(hw, "clevo_present", return_value=False), self._alien(), \
                mock.patch.object(ar, "asus_present", return_value=True), \
                mock.patch.object(ar, "open_asus", side_effect=OSError("erisim reddedildi")):
            d = hw.open_dchu()
        self.assertIsInstance(d, hw.NullDCHU)
        self.assertIn("erisim reddedildi", d.reason)
        with self.assertRaises(hw.Unsupported):
            d.set_power_mode(2)

    def test_nothing(self):
        with mock.patch.object(hw, "clevo_present", return_value=False), self._alien(), \
                mock.patch.object(ar, "asus_present", return_value=False):
            d = hw.open_dchu()
        self.assertIsInstance(d, hw.NullDCHU)
        self.assertFalse(d.available)


class TestSensorsFallback(Base):
    def test_acpi_thermal_zone_when_no_ec_temp(self):
        """Asus'ta islemci sicakligi DSTS'den gelmiyorsa sensorler ACPI isi bolgesine duser."""
        dev, _ = self.make(regs=full_regs(DEV_TEMP_CPU=ar.UNSUPPORTED))
        self.assertFalse(getattr(dev, "ec_temps", dev.available))
        dev2, _ = self.make()
        self.assertTrue(getattr(dev2, "ec_temps", dev2.available))


if __name__ == "__main__":
    unittest.main()
