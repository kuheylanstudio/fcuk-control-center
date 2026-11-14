# -*- coding: utf-8 -*-
"""Gigabyte/AORUS arka ucu: sahte WMI ve HID ile birim testleri (gercek donanim gerekmez).

    python -m unittest discover -s tests
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ceviri  # noqa: E402
import donanim as hw  # noqa: E402
import gigabyte_aorus as gb  # noqa: E402

ceviri.set_lang("tr")

ALL_GET = set(gb.WANTED_METHODS[0][1])
ALL_SET = set(gb.WANTED_METHODS[1][1]) - {"SetSmartCool"}  # yeni (P75 sinifi) model
INST = "ACPI\\PNP0C14\\0_0"
BIOS = {"SystemManufacturer": "GIGABYTE", "BaseBoardManufacturer": "GIGABYTE", "SystemFamily": "AORUS",
        "SystemProductName": "AORUS 15 XE4"}


class FakeWmi:
    """GB_WMIACPI'yi taklit eder: Set'ler bir durum sozlugune yazar, Get'ler oradan okur."""

    SET_TO_GET = {"SetFixedFanStatus": "GetFixedFanStatus", "SetFixedFanSpeed": "GetFixedFanSpeed",
                  "SetStepFanStatus": "GetStepFanStatus", "SetAutoFanStatus": "GetAutoFanStatus",
                  "SetChargePolicy": "GetChargePolicy", "SetChargeStop": "GetChargeStop"}

    def __init__(self, get=ALL_GET, set_=ALL_SET, classes=True, broken=None):
        self.methods = {gb.GET_CLASS: set(get), gb.SET_CLASS: set(set_)}
        self.classes = classes
        self.calls = []        # (sinif, yontem, girdiler)
        self.executed = []     # yalnizca call() (has_method/instances degil)
        self.broken = broken or {}  # Get yontemi -> zorla donecek deger
        self.state = {"getCpuTemp": 61, "getGpuTemp1": 55, "getRpm1": 0x8C0A, "getRpm2": 0x0000,
                      "GetCPUFanDuty": 115, "GetGPUFanDuty": 229, "GetChargePolicy": 0, "GetChargeStop": 100,
                      "GetFixedFanStatus": 0, "GetFixedFanSpeed": 0, "GetStepFanStatus": 0, "GetAutoFanStatus": 0}
        self.closed = False

    def has_class(self, cls):
        return self.classes and cls in self.methods

    def instances(self, cls):
        return [{"InstanceName": INST, "Active": True}]

    def has_method(self, cls, method):
        return method in self.methods.get(cls, ())

    def call(self, path, method, inargs=None, outnames=()):
        cls = path.split(".", 1)[0]
        assert method in self.methods[cls], "MOF'ta olmayan yontem cagrildi: " + method
        assert path == gb.wmi_path(cls, INST)
        self.calls.append((cls, method, dict(inargs or {})))
        self.executed.append(method)
        if cls == gb.GET_CLASS:
            if method in self.broken:
                return {"Data": self.broken[method]}
            return {"Data": self.state[method]}
        g = self.SET_TO_GET.get(method)
        if g:
            self.state[g] = inargs["Data"]
        return {"DataOut": 0}

    def close(self):
        self.closed = True

    def sets(self):
        return [(m, a) for c, m, a in self.calls if c == gb.SET_CLASS]


class FakeHid:
    def __init__(self, vid=0x1044, pid=0x7A3F, page=0xFF01, usage=1, flen=9, rw_ok=True):
        self.vid, self.pid, self.usage_page, self.usage, self.feature_len = vid, pid, page, usage, flen
        self.rw_ok = rw_ok
        self.reports = []
        self.closed = False

    def open_rw(self):
        if not self.rw_ok:
            raise OSError("erisim reddedildi")

    def set_feature(self, data):
        self.reports.append(bytes(data))

    def close(self):
        self.closed = True


def hid_finder(dev):
    def find(match):
        if dev is not None and match(dev.vid, dev.pid, dev.usage_page, dev.usage, dev.feature_len):
            return dev
        return None
    return find


def make(wmi=None, kb=None, family="AORUS"):
    wmi = wmi or FakeWmi()
    methods = {m for c in wmi.methods.values() for m in c}
    return gb.Gigabyte(wmi, INST, INST, methods, family, gb.AorusKeyboard(kb) if kb else None), wmi


# ============================================================================= tespit
class Detection(unittest.TestCase):
    def test_not_gigabyte_touches_nothing(self):
        called = []
        r = gb.open_backend({"SystemManufacturer": "MONSTER", "BaseBoardManufacturer": "MONSTER"},
                            wmi_factory=lambda: called.append(1), hid_find=lambda m: called.append(2))
        self.assertIsNone(r)
        self.assertEqual(called, [])

    def test_maker_strings(self):
        self.assertTrue(gb.is_gigabyte({"SystemManufacturer": "AORUS"}))
        self.assertTrue(gb.is_gigabyte({"SystemManufacturer": "", "BaseBoardManufacturer": "GIGABYTE"}))
        self.assertFalse(gb.is_gigabyte({"SystemManufacturer": "Micro-Star International"}))
        self.assertFalse(gb.is_gigabyte({}))

    def test_full_detection_executes_no_method(self):
        w = FakeWmi()
        dev = FakeHid()
        g = gb.open_backend(BIOS, wmi_factory=lambda: w, hid_find=hid_finder(dev))
        self.assertIsInstance(g, gb.Gigabyte)
        self.assertEqual(w.executed, [])  # tespit yalnizca imza okur
        self.assertEqual(dev.reports, [])
        self.assertTrue(g.available)
        self.assertTrue(g.kb_available)
        self.assertEqual(g.vendor, "gigabyte")
        self.assertLessEqual({"power", "fan_auto", "fan_max", "fan_fixed", "fan_curve", "charge", "kb", "temps"},
                             set(g.caps))

    def test_no_wmi_classes_no_keyboard(self):
        w = FakeWmi(classes=False)
        self.assertIsNone(gb.open_backend(BIOS, wmi_factory=lambda: w, hid_find=hid_finder(None)))
        self.assertTrue(w.closed)

    def test_wmi_error_during_detection(self):
        def boom():
            raise OSError("WMI yok")
        self.assertIsNone(gb.open_backend(BIOS, wmi_factory=boom, hid_find=hid_finder(None)))

    def test_keyboard_only(self):
        w = FakeWmi(classes=False)
        g = gb.open_backend(BIOS, wmi_factory=lambda: w, hid_find=hid_finder(FakeHid()))
        self.assertFalse(g.available)
        self.assertTrue(g.kb_available)
        self.assertEqual(g.status(), {})
        with self.assertRaises(hw.Unsupported):
            g.set_power_mode(2)
        self.assertEqual(w.executed, [])

    def test_unknown_keyboard_hidden(self):
        for dev in (FakeHid(pid=0x1234), FakeHid(page=0x0001), FakeHid(flen=0), FakeHid(rw_ok=False)):
            g = gb.open_backend(BIOS, wmi_factory=FakeWmi, hid_find=hid_finder(dev))
            self.assertFalse(g.kb_available, dev.__dict__)
            self.assertNotIn("kb", g.caps)
            g.set_color(255, 0, 0)  # sessizce yok sayilir
            self.assertEqual(dev.reports, [])

    def test_partial_mof_limits_caps(self):
        w = FakeWmi(get={"getCpuTemp", "getRpm1"}, set_={"SetAutoFanStatus", "SetSmartCool"})
        g = gb.open_backend(BIOS, wmi_factory=lambda: w, hid_find=hid_finder(None))
        self.assertEqual(set(g.caps), {"temps", "power", "fan_auto"})
        for fn in (lambda: g.set_fan_fixed(50), lambda: g.set_fan_mode(hw.FAN_MAX),
                   lambda: g.set_fan_curve((60, 40, 80, 60), (60, 40, 80, 60)), lambda: g.set_charge_limit(80)):
            with self.assertRaises(hw.Unsupported):
                fn()
        self.assertEqual(w.executed, [])
        self.assertIsNone(g.charge_limit())

    def test_wmi_path_escaping(self):
        self.assertEqual(gb.wmi_path("GB_WMIACPI_Get", "ACPI\\PNP0C14\\0_0"),
                         'GB_WMIACPI_Get.InstanceName="ACPI\\\\PNP0C14\\\\0_0"')


class DonanimOrder(unittest.TestCase):
    """Clevo yolu her zaman once: Clevo tabanli bir Aorus'ta Gigabyte WMI'sine hic bakilmaz."""

    def setUp(self):
        self.saved = (hw.clevo_present, hw.DCHU, gb.open_backend)

    def tearDown(self):
        hw.clevo_present, hw.DCHU, gb.open_backend = self.saved

    def test_clevo_wins(self):
        asked = []
        hw.clevo_present = lambda: True
        hw.DCHU = lambda: "clevo-dchu"
        gb.open_backend = lambda *a, **k: asked.append(1)
        self.assertEqual(hw.open_dchu(), "clevo-dchu")
        self.assertEqual(asked, [])

    def test_gigabyte_when_not_clevo(self):
        hw.clevo_present = lambda: False
        gb.open_backend = lambda *a, **k: "gb"
        self.assertEqual(hw.open_dchu(), "gb")

    def test_null_when_neither(self):
        hw.clevo_present = lambda: False
        gb.open_backend = lambda *a, **k: None
        d = hw.open_dchu()
        self.assertIsInstance(d, hw.NullDCHU)
        self.assertFalse(d.available)
        self.assertFalse(d.kb_available)

    def test_detection_crash_is_null(self):
        hw.clevo_present = lambda: False

        def boom(*a, **k):
            raise RuntimeError("x")
        gb.open_backend = boom
        self.assertIsInstance(hw.open_dchu(), hw.NullDCHU)


# ============================================================================= olcumler
class Readings(unittest.TestCase):
    def test_status(self):
        g, w = make()
        s = g.status()
        self.assertEqual(s["cpu_temp"], 61)
        self.assertEqual(s["gpu_temp"], 55)
        self.assertEqual(s["cpu_rpm"], 0x0A8C)  # ters bayt sirasi: 2700 rpm
        self.assertEqual(s["gpu_rpm"], 0)
        self.assertEqual(s["cpu_duty"], 50)
        self.assertEqual(s["gpu_duty"], 100)
        self.assertEqual(g.temps(), (61, 55))
        self.assertTrue(all(c == gb.GET_CLASS for c, _, _ in w.calls))  # olcum hicbir sey yazmaz

    def test_rpm_native_family(self):
        w = FakeWmi()
        w.state["getRpm1"] = 2700
        g, _ = make(w, family="GIGABYTE AERO")
        self.assertEqual(g.status()["cpu_rpm"], 2700)

    def test_rpm_implausible_falls_back(self):
        w = FakeWmi()
        w.state["getRpm1"] = 2700  # duz sirada ama aile listede yok: ters cevirmek 35850 verirdi
        g, _ = make(w, family="AORUS")
        self.assertEqual(g.status()["cpu_rpm"], 2700)

    def test_bad_reply_raises(self):
        w = FakeWmi(broken={"getCpuTemp": None})
        g, _ = make(w)
        with self.assertRaises(gb.GigabyteError):
            g.status()


# ============================================================================= kipler ve fan
class Modes(unittest.TestCase):
    def test_power_modes(self):
        g, w = make()
        g.set_power_mode(0)  # sessiz
        self.assertIn(("SetNvThermalTarget", {"Data": 1}), w.sets())
        self.assertIn(("SetAutoFanStatus", {"Data": 0}), w.sets())
        self.assertEqual(g.power_mode(), 0)
        self.assertEqual(g.fan_mode(), hw.FAN_AUTO)
        self.assertEqual(g.power_key(0), "gbmode.quiet")
        w.calls.clear()
        g.set_power_mode(2)  # performans -> oyun
        self.assertIn(("SetNvThermalTarget", {"Data": 0}), w.sets())
        self.assertIn(("SetAutoFanStatus", {"Data": 1}), w.sets())
        self.assertEqual(w.state["GetAutoFanStatus"], 1)
        self.assertEqual(g.power_key(2), "gbmode.gaming")
        g.set_power_mode(3)
        self.assertEqual(w.state["GetAutoFanStatus"], 0)
        self.assertEqual(g.power_key(3), "gbmode.normal")
        with self.assertRaises(ValueError):
            g.set_power_mode(9)

    def test_old_model_uses_smartcool(self):
        w = FakeWmi(set_=(ALL_SET - {"SetNvThermalTarget"}) | {"SetSmartCool"})
        g, _ = make(w)
        g.set_power_mode(0)
        self.assertIn(("SetSmartCool", {"Data": 1}), w.sets())

    def test_mode_clears_manual_fan(self):
        g, w = make()
        g.set_fan_fixed(70)
        g.set_power_mode(3)
        self.assertEqual(w.state["GetFixedFanStatus"], 0)
        self.assertEqual(w.state["GetStepFanStatus"], 0)
        self.assertEqual(g.fan_mode(), hw.FAN_AUTO)

    def test_fixed_speed(self):
        g, w = make()
        g.set_fan_fixed(50)
        self.assertEqual(w.state["GetFixedFanStatus"], 1)
        self.assertEqual(w.state["GetStepFanStatus"], 1)
        self.assertEqual(w.state["GetFixedFanSpeed"], round(50 * 229 / 100))
        self.assertIn(("SetGPUFanDuty", {"Data": 114}), w.sets())
        self.assertEqual(g.fan_mode(), hw.FAN_FIXED)
        self.assertEqual(g.fan_fixed(), 50)
        g.set_fan_fixed(5)  # en az %30
        self.assertEqual(g.fan_fixed(), 30)
        g.set_fan_fixed(500)
        self.assertEqual(w.state["GetFixedFanSpeed"], 229)

    def test_max(self):
        g, w = make()
        g.set_fan_mode(hw.FAN_MAX)
        self.assertEqual(w.state["GetFixedFanSpeed"], 229)
        self.assertEqual(g.fan_mode(), hw.FAN_MAX)
        g.set_fan_mode(hw.FAN_AUTO)
        self.assertEqual(w.state["GetFixedFanStatus"], 0)
        with self.assertRaises(hw.Unsupported):
            g.set_fan_mode(hw.FAN_CUSTOM)

    def test_verify_mismatch_reported(self):
        w = FakeWmi(broken={"GetFixedFanStatus": 0})
        g, _ = make(w)
        with self.assertRaises(gb.GigabyteError):
            g.set_fan_fixed(60)
        self.assertNotEqual(g.fan_mode(), hw.FAN_FIXED)

    def test_curve(self):
        pts = gb.Gigabyte.curve_points((64, 32, 80, 55))
        self.assertEqual(len(pts), 15)
        self.assertEqual(pts[0][0], 40)
        self.assertEqual(pts[-1], (100, 229))
        for a, b in zip(pts, pts[1:]):
            self.assertLessEqual(a[0], b[0])
            self.assertLessEqual(a[1], b[1])
        self.assertTrue(all(0 <= d <= 229 and 0 <= t <= 100 for t, d in pts))
        g, w = make()
        g.set_fan_curve((64, 32, 80, 55), (1, 1, 1, 1))
        idx = [(m, a) for m, a in w.sets() if m == "SetFanIndexValue"]
        self.assertEqual([a["Index"] for _, a in idx], list(range(15)))
        self.assertEqual(set(idx[0][1]), {"Index", "Temperture", "Value"})
        self.assertEqual(w.state["GetStepFanStatus"], 1)
        self.assertEqual(w.state["GetFixedFanStatus"], 0)
        self.assertEqual(g.fan_mode(), hw.FAN_CUSTOM)

    def test_curve_rejects_unsafe_input(self):
        # Profil ne verirse versin sicak bolgede yeterli hava (donanim.validate_curve)
        pts = gb.Gigabyte.curve_points((90, 0, 99, 0))
        self.assertEqual(len(pts), 15)
        d = dict(pts)
        self.assertEqual(d[100], 229)
        self.assertEqual(d[88], round(0.45 * 229))  # 88 C'de en az %45 (kirilma noktasi korunur)
        self.assertEqual(d[87], round(0.21 * 229))

    def test_clevo_raw_commands_refused(self):
        g, w = make()
        for fn in (lambda: g.set_wmi(0x46, 0), lambda: g.set_data(14, b"x"), lambda: g.write_app(1, 1, b"x")):
            with self.assertRaises(hw.Unsupported):
                fn()
        self.assertEqual(w.executed, [])

    def test_set_arg_range_checked(self):
        g, w = make()
        with self.assertRaises(ValueError):
            g._set("SetFixedFanSpeed", 300)
        self.assertEqual(w.executed, [])


class Charge(unittest.TestCase):
    def test_limit(self):
        g, w = make()
        self.assertEqual(g.charge_limit(), {"enabled": False, "stop": 100})
        g.set_charge_limit(80)
        self.assertEqual(w.state["GetChargePolicy"], 4)
        self.assertEqual(w.state["GetChargeStop"], 80)
        self.assertEqual(g.charge_limit(), {"enabled": True, "stop": 80})
        g.set_charge_limit(None)
        self.assertEqual(w.state["GetChargePolicy"], 0)
        for bad in (59, 101):
            n = len(w.calls)
            with self.assertRaises(ValueError):
                g.set_charge_limit(bad)
            self.assertEqual(len(w.calls), n)  # gecersiz deger hicbir sey yazmaz

    def test_garbage_stop_hidden(self):
        w = FakeWmi()
        w.state["GetChargeStop"] = 0x1234
        g, _ = make(w)
        self.assertIsNone(g.charge_limit()["stop"])


# ============================================================================= klavye
class Keyboard(unittest.TestCase):
    def test_report_layout(self):
        r = gb.kb_color_report(0, 0, 255)
        self.assertEqual(len(r), 9)
        self.assertEqual(r[:8], bytes([0, 0x08, 0x01, 0, 0, 255, 0x32, 0]))
        self.assertEqual(r[8], 0xC5)  # OpenRGB'deki ornek: 08 01 00 00 FF 32 00 C5
        self.assertEqual(sum(r) & 0xFF, 0xFF)

    def test_throttle_and_resend(self):
        dev = FakeHid()
        g, _ = make(kb=dev)
        g.set_color(255, 0, 0)
        g.set_color(0, 255, 0)  # 50 ms icinde: atlanir
        self.assertEqual(len(dev.reports), 1)
        g.kb._at -= 0.06
        g.set_color(0, 255, 0)
        self.assertEqual(len(dev.reports), 2)
        g.set_color(0, 255, 0)  # ayni renk, 1 sn dolmadi
        self.assertEqual(len(dev.reports), 2)
        g.kb._at -= 1.1
        g.set_color(0, 255, 0)  # 1 sn sonra yeniden (uyku sonrasi geri getirmek icin)
        self.assertEqual(len(dev.reports), 3)

    def test_engine_drives_keyboard(self):
        import klavye_rgb as core
        dev = FakeHid()
        g, w = make(kb=dev)
        eng = core.Engine(g)
        cfg = {"mode": "sabit", "brightness": 50, "modes": {"sabit": {"palette": ["#ff0000"], "speed": 50}}}
        eng.settings = core.snapshot(cfg)
        eng.start()
        try:
            deadline = time.time() + 3
            while not dev.reports and time.time() < deadline:
                time.sleep(0.05)
        finally:
            eng.running = False
            eng.join(2)
        self.assertEqual(eng.error, "")
        self.assertTrue(dev.reports)
        self.assertEqual(dev.reports[0][3:6], bytes([128, 0, 0]))

    def test_engine_without_keyboard_sends_nothing(self):
        import klavye_rgb as core
        g, w = make(kb=None)
        eng = core.Engine(g)
        cfg = {"mode": "sistem", "brightness": 100,
               "modes": {"sistem": {"palette": ["#0000ff", "#ff0000"], "speed": 50, "source": "cpu_temp"}}}
        eng.settings = core.snapshot(cfg)
        eng.start()
        time.sleep(0.8)
        eng.running = False
        eng.join(2)
        self.assertEqual(eng.error, "")
        self.assertEqual(w.executed, [])  # klavye yokken sistem modu sabite iner, sicaklik bile okunmaz


# ============================================================================= profiller
class Profiles(unittest.TestCase):
    def manager(self, dchu):
        import profiller

        class S:
            gpu_name = ""
            listeners = []
        m = profiller.Manager.__new__(profiller.Manager)
        m.dchu, m.sensors, m.notify = dchu, S(), (lambda text: None)
        m.guard, m._hot, m._cool, m._blind, m.applied = "", 0, 0, 0, ""
        return m, profiller

    def test_profile_steps_on_gigabyte(self):
        g, w = make()
        m, profiller = self.manager(g)
        for p in profiller.PROFILES:
            m._ec(p)
            m._fan(p)
            rows = dict(m.describe(p))
            self.assertIn(rows[ceviri.t("row.powerMode")],
                          [ceviri.t("gbmode." + k) for k in ("quiet", "normal", "gaming")])
        self.assertTrue(all(x in g.methods for x in w.executed))

    def test_fixed_guard(self):
        g, w = make()
        m, _ = self.manager(g)
        g.set_fan_fixed(30)
        for _ in range(5):
            m._fixed_guard({"cpu_temp": 95, "gpu_temp": 50})
        self.assertEqual(g.fan_mode(), hw.FAN_AUTO)
        self.assertTrue(m.guard)
        g.set_fan_fixed(30)
        m.guard = ""
        for _ in range(5):
            m._fixed_guard({"sensor_error": "x"})  # sicaklik bilinmiyor: guvenli tarafa
        self.assertEqual(g.fan_mode(), hw.FAN_AUTO)

    def test_clevo_power_key_unchanged(self):
        class Clevo:
            available = True
        m, _ = self.manager(Clevo())
        self.assertEqual(m._power_key(2), "power.2")


class Lang(unittest.TestCase):
    KEYS = ["fan.fixed", "fan.fixedSpeed", "fanmode.7", "fan.intro.gb", "charge.title", "charge.on", "charge.hint",
            "charge.fail", "unsup.fanGb", "unsup.kbGb", "gbmode.quiet", "gbmode.normal", "gbmode.gaming",
            "guard.fixed", "err.gbNoMethod", "err.gbBadReply", "err.gbVerify", "err.gbNoFeature", "err.gbCharge"]

    def test_all_languages_have_keys(self):
        import glob
        import json
        files = glob.glob(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                       "ui", "lang", "*.json"))
        self.assertEqual(len(files), 14)
        for f in files:
            with open(f, encoding="utf-8") as fh:
                d = json.load(fh)
            for k in self.KEYS:
                self.assertTrue(d.get(k), "%s: %s" % (os.path.basename(f), k))


if __name__ == "__main__":
    unittest.main()
