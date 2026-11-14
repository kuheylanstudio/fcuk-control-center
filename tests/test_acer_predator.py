# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""Acer Predator/Nitro arka ucu: sahte (mock) AcerGamingFunction ile birim testleri.

Calistirma (depo kokunden):  python -m unittest discover -s tests -v

Sahte aygit Linux acer-wmi (predator_v4) ve Windows betiklerinden derlenen protokolu taklit eder; gercek
Predator donanimi olmadan bit paketlemeyi, durum kodu denetimini ve "desteklenmeyen ozellige komut
gitmez" kuralini sinar. Gercek donanimdaki davranisi KANITLAMAZ.
"""
import os
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import acer_predator as ap  # noqa: E402
import donanim as hw  # noqa: E402

U32, U64, U8A = 19, 21, 0x2000 | 17
# Windows MOF tipleri (PHN16-72): Get* uint32 -> uint64, Set* uint64 -> uint32, KBBacklight uint8[16]
FULL_SIG = {
    ap.SYSINFO: U32, ap.MISC_GET: U32, ap.MISC_SET: U64, ap.FAN_GET: U32, ap.FAN_SET: U64,
    ap.SPEED_GET: U32, ap.SPEED_SET: U64, ap.RGB_GET: U32, ap.RGB_SET: U64, ap.KBBL_SET: U8A,
}
READ_METHODS = {ap.SYSINFO, ap.MISC_GET, ap.FAN_GET, ap.SPEED_GET, ap.RGB_GET}


class FakeAcer:
    """AcerGamingFunction'in durumlu taklidi (tasima katmani yuzu: params / invoke)."""

    def __init__(self, sig=None, sensors=(1, 2, 6, 10), supported=(0, 1, 4, 5, 6), fail=None,
                 single_zone_only=False):
        self.sig = dict(FULL_SIG if sig is None else sig)
        self.sensor_bits = sum(1 << (s - 1) for s in sensors)
        self.supported = supported      # None: destek sorgusu hata dondurur
        self.fail = dict(fail or {})    # yontem -> durum kodu
        self.single_zone_only = single_zone_only
        self.profile = ap.BALANCED
        self.fan = {"cpu": ap.FM_AUTO, "gpu": ap.FM_AUTO}
        self.speed = {ap.FAN_ID_CPU: 0, ap.FAN_ID_GPU: 0}
        self.zones = [(0, 0, 0)] * 4
        self.kbbl = None
        self.values = {1: 61, 2: 2850, 6: 3100, 10: 54}
        self.calls = []
        self.ignore_profile = False     # True: yazma kabul edilir ama profil degismez (dogrulama testi)

    def params(self, method):
        t = self.sig.get(method)
        return None if t is None else {"gmInput": t}

    def writes(self):
        return [c for c in self.calls if c[0] not in READ_METHODS]

    def invoke(self, method, args):
        assert list(args) == ["gmInput"], args
        x = args["gmInput"]
        self.calls.append((method, x))
        if method in self.fail:
            return {"gmOutput": self.fail[method]}
        if method == ap.SYSINFO:
            if x == 0:
                return {"gmOutput": self.sensor_bits << 24}
            if x & 0xFF == 1:
                return {"gmOutput": self.values.get(x >> 8, 0) << 8}
            return {"gmOutput": 3}
        if method == ap.MISC_GET:
            if x == ap.MISC_PROFILE:
                return {"gmOutput": self.profile << 8}
            if x == ap.MISC_SUPPORTED:
                if self.supported is None:
                    return {"gmOutput": 1}
                return {"gmOutput": sum(1 << p for p in self.supported) << 8}
            return {"gmOutput": 2}
        if method == ap.MISC_SET:
            idx, val = x & 0xFF, (x >> 8) & 0xFF
            if idx != ap.MISC_PROFILE:
                return {"gmOutput": 2}
            if not self.ignore_profile:
                self.profile = val
            return {"gmOutput": 0}
        if method == ap.FAN_GET:
            return {"gmOutput": self.fan["cpu"] << 8 | self.fan["gpu"] << 14}
        if method == ap.FAN_SET:
            bits = x & 0xFFFF
            if bits & ap.FAN_BIT_CPU:
                self.fan["cpu"] = (x >> 16) & 3
            if bits & ap.FAN_BIT_GPU:
                self.fan["gpu"] = (x >> 22) & 3
            return {"gmOutput": 0}
        if method == ap.SPEED_GET:
            return {"gmOutput": self.speed.get(x & 0xFF, 0) << 8}
        if method == ap.SPEED_SET:
            fid, pct = x & 0xFF, (x >> 8) & 0xFF
            if fid not in self.speed:
                return {"gmOutput": 1}
            if pct > 100:
                return {"gmOutput": 2}
            self.speed[fid] = pct
            return {"gmOutput": 0}
        if method == ap.RGB_GET:
            return {"gmOutput": 0}
        if method == ap.RGB_SET:
            mask = x & 0xFF
            if self.single_zone_only and bin(mask).count("1") != 1:
                return {"gmOutput": 2}
            col = ((x >> 8) & 255, (x >> 16) & 255, (x >> 24) & 255)
            for i in range(4):
                if mask >> i & 1:
                    self.zones[i] = col
            return {"gmOutput": 0}
        if method == ap.KBBL_SET:
            assert isinstance(x, bytes) and len(x) == 16
            self.kbbl = x
            return {"gmOutput": 0}
        raise AssertionError("bilinmeyen yontem " + method)


def dev(**kw):
    f = FakeAcer(**kw)
    return ap.AcerGaming(f, "Predator PH315-55"), f


# ----------------------------------------------------------------------------- yoklama
class ProbeTests(unittest.TestCase):
    def test_full_model_probe_reads_only(self):
        d, f = dev()
        self.assertTrue(d.available and d.power_ok and d.fan_ok and d.fan_speed_ok and d.kb_ok)
        self.assertEqual(d.sensors, {1, 2, 6, 10})
        self.assertEqual(sorted(d.profiles), [0, 1, 4, 5, 6])
        self.assertEqual(f.writes(), [], "yoklama hicbir yazma yontemi cagirmamali")
        self.assertEqual(d.caps["kb_zones"], 4)
        self.assertEqual(d.caps["power_modes"], ["quiet", "balanced", "performance", "turbo", "eco"])

    def test_unreliable_supported_bitmap_uses_safe_set(self):
        d, _ = dev(supported=None)
        self.assertEqual(sorted(d.profiles), [0, 1, 4])  # turbo / eco yalnizca bit eslemesi soylerse
        d2, _ = dev(supported=())
        self.assertEqual(sorted(d2.profiles), [0, 1, 4])

    def test_missing_methods_disable_features(self):
        sig = dict(FULL_SIG)
        for m in (ap.RGB_SET, ap.RGB_GET, ap.KBBL_SET, ap.SPEED_SET):
            sig.pop(m)
        d, f = dev(sig=sig)
        self.assertFalse(d.kb_ok)
        self.assertFalse(d.fan_speed_ok)
        self.assertTrue(d.fan_ok)
        d.set_color(255, 0, 0)  # klavye motoru her karede cagirir: sessizce yok sayilir
        self.assertEqual(f.writes(), [])
        with self.assertRaises(hw.Unsupported):
            d.set_fan_speed(50, 50)
        self.assertEqual(f.writes(), [])

    def test_unexpected_param_type_is_not_called(self):
        sig = dict(FULL_SIG)
        sig[ap.KBBL_SET] = U64   # bu makinede tip farkli: bayt dizisi beklenirken tamsayi
        sig[ap.MISC_SET] = U8A
        d, f = dev(sig=sig)
        self.assertFalse(d.kb_ok)
        self.assertFalse(d.power_ok)
        with self.assertRaises(hw.Unsupported):
            d.set_power_mode("turbo")
        self.assertEqual(f.writes(), [])

    def test_failing_status_disables_feature(self):
        d, f = dev(fail={ap.FAN_GET: 1, ap.MISC_GET: 3})
        self.assertFalse(d.fan_ok)
        self.assertFalse(d.power_ok)
        with self.assertRaises(hw.Unsupported):
            d.set_fan_mode(hw.FAN_MAX)
        with self.assertRaises(hw.Unsupported):
            d.set_power_mode(2)
        self.assertEqual(f.writes(), [])
        self.assertIsNone(d.fan_mode())
        self.assertIsNone(d.power_mode())

    def test_nothing_supported_is_unavailable(self):
        d, _ = dev(sig={})
        self.assertFalse(d.available)


# ----------------------------------------------------------------------------- olcum
class SensorTests(unittest.TestCase):
    def test_status_unpacks_bits(self):
        d, f = dev()
        s = d.status()
        self.assertEqual(s, {"cpu_temp": 61, "gpu_temp": 54, "cpu_rpm": 2850, "gpu_rpm": 3100})
        self.assertIn((ap.SYSINFO, 0x0101), f.calls)   # islemci sicakligi: 1 | 0x01 << 8
        self.assertIn((ap.SYSINFO, 0x0A01), f.calls)   # kart sicakligi:    1 | 0x0A << 8
        self.assertEqual(d.temps(), (61, 54))

    def test_only_supported_sensors_are_read(self):
        d, f = dev(sensors=(1,))
        f.calls.clear()
        self.assertEqual(d.status(), {"cpu_temp": 61})
        self.assertEqual(f.calls, [(ap.SYSINFO, 0x0101)])
        self.assertTrue(d.temps_ok)
        d2, _ = dev(sensors=())
        self.assertFalse(d2.temps_ok)  # Sensors ACPI isi bolgesine gecer


# ----------------------------------------------------------------------------- guc modu
class PowerTests(unittest.TestCase):
    def test_set_by_name_packs_index_and_value(self):
        d, f = dev()
        self.assertEqual(d.set_power_mode("turbo"), "turbo")
        self.assertIn((ap.MISC_SET, 0x0B | 0x05 << 8), f.calls)
        self.assertEqual(f.profile, ap.TURBO)
        self.assertEqual(d.power_name(), "turbo")

    def test_clevo_modes_map(self):
        d, f = dev()
        for clevo, acer in ((0, ap.QUIET), (1, ap.ECO), (2, ap.PERFORMANCE), (3, ap.BALANCED)):
            d.set_power_mode(clevo)
            self.assertEqual(f.profile, acer)

    def test_fallback_to_nearest_supported(self):
        d, f = dev(supported=(0, 1, 4))
        self.assertEqual(d.set_power_mode("turbo"), "performance")
        self.assertEqual(d.set_power_mode("eco"), "quiet")
        d2, f2 = dev(supported=(1, 4))
        self.assertEqual(d2.set_power_mode(0), "balanced")

    def test_app_profiles(self):
        d, f = dev()
        prof = {"id": "ultra", "ec": 2}
        self.assertEqual(d.profile_power(prof, on_ac=True), ap.TURBO)
        self.assertEqual(d.profile_power(prof, on_ac=False), ap.PERFORMANCE)
        self.assertEqual(d.profile_power({"id": "tam_sessiz", "ec": 0}), ap.QUIET)
        self.assertEqual(d.profile_power({"id": "bilinmeyen", "ec": 3}), ap.BALANCED)
        d.apply_profile_power({"id": "performans", "ec": 2})
        self.assertEqual(f.profile, ap.PERFORMANCE)

    def test_write_error_and_verification(self):
        d, f = dev()
        f.fail[ap.MISC_SET] = 2
        with self.assertRaises(ap.AcerError):
            d.set_power_mode("quiet")
        del f.fail[ap.MISC_SET]
        f.ignore_profile = True
        with self.assertRaises(RuntimeError):  # yazildi ama okunan farkli: sessizce basarili sayilmaz
            d.set_power_mode("quiet")

    def test_unknown_name(self):
        d, _ = dev()
        with self.assertRaises(ValueError):
            d.set_power_mode("roket")


# ----------------------------------------------------------------------------- fan
class FanTests(unittest.TestCase):
    def test_words_match_known_values(self):
        # Windows betiklerinde gorulen degerler: iki fan otomatik 0x410009, iki fan en yuksek 0x820009
        self.assertEqual(ap.AcerGaming.behavior_word(ap.FM_AUTO, ap.FM_AUTO), 0x410009)
        self.assertEqual(ap.AcerGaming.behavior_word(ap.FM_MAX, ap.FM_MAX), 0x820009)

    def test_modes_roundtrip(self):
        d, f = dev()
        d.set_fan_mode(hw.FAN_MAX)
        self.assertEqual(f.fan, {"cpu": ap.FM_MAX, "gpu": ap.FM_MAX})
        self.assertEqual(d.fan_mode(), hw.FAN_MAX)
        d.set_fan_mode(hw.FAN_AUTO)
        self.assertEqual(d.fan_mode(), hw.FAN_AUTO)
        with self.assertRaises(hw.Unsupported):
            d.set_fan_mode(hw.FAN_CUSTOM)  # Clevo egri kodu: Acer'da yok
        with self.assertRaises(hw.Unsupported):
            d.set_fan_curve((60, 30, 80, 60), (60, 30, 80, 60))
        self.assertIsNone(d.fan_default())

    def test_custom_speed_sequence_and_clamp(self):
        d, f = dev()
        f.calls.clear()
        self.assertEqual(d.set_fan_speed(5, 150), (ap.MIN_CUSTOM_PCT, 100))
        w = f.writes()
        self.assertEqual(w[0], (ap.FAN_SET, ap.AcerGaming.behavior_word(3, 3)))  # once ozel kip
        self.assertEqual(w[1], (ap.SPEED_SET, 0x01 | 20 << 8))
        self.assertEqual(w[2], (ap.SPEED_SET, 0x04 | 100 << 8))
        self.assertEqual(d.fan_mode(), ap.FAN_CUSTOM_SPEED)
        self.assertEqual(d.status()["cpu_duty"], 20)

    def test_custom_speed_failure_rolls_back_to_auto(self):
        d, f = dev()
        f.fail[ap.SPEED_SET] = 2
        with self.assertRaises(ap.AcerError):
            d.set_fan_speed(40, 40)
        self.assertEqual(f.fan, {"cpu": ap.FM_AUTO, "gpu": ap.FM_AUTO})

    def test_custom_guard(self):
        d, f = dev()
        d.set_fan_speed(30, 30)
        self.assertIsNone(d.custom_guard({"cpu_temp": 70, "gpu_temp": 60}))
        for _ in range(4):
            self.assertIsNone(d.custom_guard({"cpu_temp": 95, "gpu_temp": 60}))
        self.assertTrue(d.custom_guard({"cpu_temp": 95, "gpu_temp": 60}))
        self.assertEqual(f.fan["cpu"], ap.FM_AUTO)
        # sicaklik bilinmiyorsa da ayni koruma
        d.set_fan_speed(30, 30)
        msgs = [d.custom_guard({}) for _ in range(5)]
        self.assertTrue(msgs[-1])
        # elle hiz yokken hicbir sey yapmaz
        f.calls.clear()
        self.assertIsNone(d.custom_guard({"cpu_temp": 99}))
        self.assertEqual(f.calls, [])


# ----------------------------------------------------------------------------- klavye
class KeyboardTests(unittest.TestCase):
    def setUp(self):
        self._old = ap.KB_MIN_INTERVAL
        ap.KB_MIN_INTERVAL = 0.0

    def tearDown(self):
        ap.KB_MIN_INTERVAL = self._old

    def test_static_zones(self):
        d, f = dev()
        cols = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255)]
        d.set_zones(cols)
        self.assertEqual(f.zones, cols)
        self.assertEqual(f.kbbl[0], 0)    # efekt: sabit
        self.assertEqual(f.kbbl[2], 100)  # parlaklik
        self.assertEqual(f.kbbl[9], 1)    # aygit: klavye
        self.assertIn((ap.RGB_SET, 0x01 | 255 << 8), f.calls)
        self.assertIn((ap.RGB_SET, 0x08 | 255 << 8 | 255 << 16 | 255 << 24), f.calls)

    def test_same_colour_zones_grouped(self):
        d, f = dev()
        f.calls.clear()
        d.set_color(10, 20, 30)
        rgb = [c for c in f.calls if c[0] == ap.RGB_SET]
        self.assertEqual(rgb, [(ap.RGB_SET, 0x0F | 10 << 8 | 20 << 16 | 30 << 24)])
        self.assertEqual(f.zones, [(10, 20, 30)] * 4)

    def test_combined_mask_rejected_falls_back_per_zone(self):
        d, f = dev(single_zone_only=True)
        d.set_color(1, 2, 3)
        self.assertEqual(f.zones, [(1, 2, 3)] * 4)
        self.assertFalse(d._kb_group)
        f.calls.clear()
        d.set_color(4, 5, 6)
        self.assertEqual(len([c for c in f.calls if c[0] == ap.RGB_SET]), 4)

    def test_rate_limit_and_dedupe(self):
        ap.KB_MIN_INTERVAL = 10.0
        d, f = dev()
        d.set_color(1, 1, 1)
        n = len(f.calls)
        d.set_color(2, 2, 2)  # aralik dolmadi: gonderilmez (motor saniyede bir yeniden ister)
        self.assertEqual(len(f.calls), n)
        ap.KB_MIN_INTERVAL = 0.0
        d.set_color(1, 1, 1)  # klavyede zaten bu renk var (2,2,2 gonderilmedi): 1 sn icinde tekrar gonderilmez
        self.assertEqual(len([c for c in f.calls if c[0] == ap.RGB_SET]), 1)
        d.set_color(3, 3, 3)
        self.assertEqual(len([c for c in f.calls if c[0] == ap.RGB_SET]), 2)

    def test_repeated_errors_disable_keyboard(self):
        d, f = dev()
        f.fail[ap.RGB_SET] = 3
        for i in range(ap.KB_MAX_FAILS):
            with self.assertRaises(ap.AcerError):
                d.set_color(i, 0, 0)
        self.assertFalse(d.kb_available)
        f.calls.clear()
        d.set_color(9, 9, 9)
        self.assertEqual(f.calls, [])


# ----------------------------------------------------------------------------- tespit
class FakeClient:
    def __init__(self, ns, world):
        self.ns, self.world = ns, world
        world["connected"].append(ns)

    def query(self, wql, props=None):
        if "Win32_ComputerSystem" in wql:
            return [self.world["cs"]]
        if "AcerGamingFunction" in wql:
            return [{"__PATH": r'\\PC\root\wmi:AcerGamingFunction.InstanceName="ACPI\\PNP0C14\\APGe_0"'}]
        return []

    def class_exists(self, cls):
        return self.world["has_class"]

    def has_method(self, cls, m):
        return m in FULL_SIG

    def in_params(self, cls, m):
        return {"gmInput": FULL_SIG[m]}

    def call(self, path, cls, method, args):
        return self.world["fake"].invoke(method, args)

    def close(self):
        self.world["closed"].append(self.ns)


def world(maker="Acer", model="Predator PH315-55", fam="Predator Helios 300", has_class=True):
    w = {"cs": {"Manufacturer": maker, "Model": model, "SystemFamily": fam}, "has_class": has_class,
         "fake": FakeAcer(), "connected": [], "closed": []}
    return w, (lambda ns: FakeClient(ns, w))


class DetectTests(unittest.TestCase):
    def test_predator_detected(self):
        w, fac = world()
        d = ap.detect(fac)
        self.assertIsInstance(d, ap.AcerGaming)
        self.assertEqual(d.vendor, "acer")
        self.assertIn("Predator", d.model)
        self.assertNotIn(r"root\wmi", w["closed"])  # aygitin baglantisi acik kalir

    def test_nitro_detected(self):
        w, fac = world(model="Nitro AN515-58", fam="Nitro 5")
        self.assertIsInstance(ap.detect(fac), ap.AcerGaming)

    def test_non_acer_never_touches_root_wmi(self):
        w, fac = world(maker="MONSTER", model="ABRA A5 V21.1", fam="ABRA")
        self.assertIsNone(ap.detect(fac))
        self.assertEqual(w["connected"], [r"root\cimv2"])
        self.assertEqual(w["fake"].calls, [])

    def test_acer_non_gaming_or_missing_class(self):
        w, fac = world(model="Aspire A515-56", fam="Aspire 5")
        self.assertIsNone(ap.detect(fac))
        self.assertEqual(w["connected"], [r"root\cimv2"])
        w, fac = world(has_class=False)
        self.assertIsNone(ap.detect(fac))
        self.assertEqual(w["fake"].calls, [])
        self.assertIn(r"root\wmi", w["closed"])

    def test_errors_mean_none(self):
        def boom(ns):
            raise OSError("WMI yok")
        self.assertIsNone(ap.detect(boom))


# ----------------------------------------------------------------------------- uygulamayla birlesim
class FakeSensors:
    gpu_name = "NVIDIA GeForce RTX 3060 Laptop GPU"

    def __init__(self):
        self.listeners = []


class IntegrationTests(unittest.TestCase):
    def test_profiles_use_power_mode_instead_of_curve(self):
        import profiller
        d, f = dev()
        mgr = profiller.Manager(d, FakeSensors(), {}, lambda: None)
        d.set_fan_speed(30, 30)
        quiet = profiller.BY_ID["tam_sessiz"]   # egri profili
        mgr._ec(quiet)
        self.assertEqual(f.profile, ap.QUIET)
        msg = mgr._fan(quiet)
        self.assertEqual(f.fan, {"cpu": ap.FM_AUTO, "gpu": ap.FM_AUTO})  # egri yok: guc modunun tablosu
        self.assertEqual(msg, profiller.t("msg.fanByMode"))
        rows = dict(mgr.describe(quiet))
        self.assertEqual(rows[profiller.t("row.powerMode")], profiller.t("acer.power.quiet"))
        self.assertEqual(rows[profiller.t("row.fan")], profiller.t("val.fanByMode"))
        self.assertEqual(mgr.status()["power_name"], "quiet")

    def test_guard_does_not_send_curve_on_acer(self):
        import profiller
        d, f = dev()
        mgr = profiller.Manager(d, FakeSensors(), {}, lambda: None)
        mgr.applied = "tam_sessiz"
        mgr._last_ac = True
        f.calls.clear()
        for _ in range(40):
            mgr._tick({"cpu_temp": 99, "gpu_temp": 90, "battery": {"ac": True}}, 1.0)
        self.assertEqual(f.writes(), [])  # Clevo egri bekcisi Acer'da calismaz

    def test_engine_zones_mode(self):
        import klavye_rgb as core
        calls = []

        class KB:
            available = True
            kb_available = True

            def set_zones(self, cols):
                calls.append(("z", cols))

            def set_color(self, *c):
                calls.append(("c", c))

            def temps(self):
                return 50, 40

        eng = core.Engine(KB())
        cfg = {"mode": "bolgeler", "brightness": 50,
               "modes": {"bolgeler": {"palette": ["#ff0000", "#00ff00", "#0000ff", "#ffffff"]}}}
        eng.settings = core.snapshot(cfg)
        eng.start()
        time.sleep(0.3)
        eng.running = False
        eng.join(2)
        self.assertEqual(eng.error, "")
        self.assertTrue(calls and calls[0][0] == "z")
        self.assertEqual(calls[0][1], ((128, 0, 0), (0, 128, 0), (0, 0, 128), (128, 128, 128)))

    def test_engine_static_on_acer_device(self):
        import klavye_rgb as core
        d, f = dev()
        eng = core.Engine(d)
        cfg = {"mode": "sabit", "brightness": 100, "modes": {"sabit": {"palette": ["#123456"]}}}
        eng.settings = core.snapshot(cfg)
        eng.start()
        time.sleep(0.3)
        eng.running = False
        eng.join(2)
        self.assertEqual(eng.error, "")
        self.assertEqual(f.zones, [(0x12, 0x34, 0x56)] * 4)

    def test_null_and_clevo_classes_unchanged(self):
        n = hw.NullDCHU("x")
        self.assertFalse(n.available)
        self.assertFalse(n.kb_available)
        self.assertEqual(n.vendor, "")
        with self.assertRaises(hw.Unsupported):
            n.set_power_mode(0)
        self.assertEqual(hw.DCHU.vendor, "clevo")
        self.assertTrue(hw.DCHU.fan_curve_ok and hw.DCHU.kb_available and hw.DCHU.available)


if __name__ == "__main__":
    unittest.main()
