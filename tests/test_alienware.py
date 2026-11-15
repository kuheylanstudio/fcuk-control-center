# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""Alienware arka ucu testleri: gercek donanim olmadan, sahte AWCC WMI ve sahte AlienFX HID ile.

Sahte aygit bir Alienware 16X Aurora'yi taklit eder: 2 fan (0x32 CPU, 0x33 GPU), 2 sensor (0x01 CPU,
0x06 GPU), USTT profilleri ve G-mode. Calistirma: python -m unittest test_alienware -v
"""
import time
import unittest

import alienware as aw
import donanim


class FakeAwcc:
    """AWCCWmiMethodFunction davranisi (Linux surucusundeki kodlama ile)."""

    def __init__(self, profiles=(0xA0, 0xA1, 0xA3, 0xA4), fans=(0x32, 0x33), gmode=True):
        self.fans = list(fans)
        self.sensors = [0x01, 0x06]
        self.profiles = list(profiles)
        self.gmode_supported = gmode
        self.temps = {0x01: 50, 0x06: 45}
        self.rpm = {f: 2000 for f in self.fans}
        self.boost = {f: 0 for f in self.fans}
        self.profile = 0xA0
        self.gmode = 0
        self.calls = []
        self.fail_temps = False

    def query(self, wql, props=None):
        assert "AWCCWmiMethodFunction" in wql
        return [{"__PATH": r"\\.\root\WMI:AWCCWmiMethodFunction.InstanceName=\"ACPI\\PNP0C14\\0_0\""}]

    def call(self, path, cls, method, args, out_name):
        assert cls == aw.CLASS and out_name == "argr" and set(args) == {"arg2"}
        a = args["arg2"]
        op, a1, a2 = a & 0xFF, (a >> 8) & 0xFF, (a >> 16) & 0xFF
        self.calls.append((method, op, a1, a2))
        err = 0xFFFFFFFF
        res = self.fans + [0x100 | s for s in self.sensors] + self.profiles
        if method == aw.M_INFO:
            if op == 0x02:
                return len(self.fans) | len(self.sensors) << 8 | 0 << 16 | len(self.profiles) << 24
            if op == 0x03:
                return res[a1] if a1 < len(res) else err
            if op == 0x04:
                return err if self.fail_temps or a1 not in self.temps else self.temps[a1]
            if op == 0x05:
                return self.rpm.get(a1, err)
            if op == 0x09:
                return 5000 if a1 in self.fans else err
            if op == 0x0B:
                return self.profile
        if method == aw.M_CONTROL:
            if op == 0x01:
                if a1 not in self.profiles + [0x00] + ([0xAB] if self.gmode_supported else []):
                    return err
                self.profile = a1
                return 0
            if op == 0x02:
                if a1 not in self.fans:
                    return err
                self.boost[a1] = a2
                return 0
        if method == aw.M_FANSENS:
            if op == 0x01:
                return 1
            if op == 0x02:
                return {0x32: 0x01, 0x33: 0x06}[a1]
        if method == aw.M_GAMESHIFT and self.gmode_supported:
            if op == 0x01:
                self.gmode ^= 1
                return 0
            if op == 0x02:
                return self.gmode
        return err


class FakeHidDevice:
    sent = []

    def __init__(self, info):
        self.info = info

    def write(self, data, length=None):
        FakeHidDevice.sent.append(("out", tuple(data), length))

    def set_feature(self, data, length=None):
        FakeHidDevice.sent.append(("feat", tuple(data), length))

    def close(self):
        pass


class FakeHid:
    HidDevice = FakeHidDevice

    def __init__(self, devices):
        self.devices = devices

    def enumerate_devices(self, vids=None):
        return [d for d in self.devices if not vids or d["vid"] in vids]


V4 = {"path": "x", "vid": 0x187C, "pid": 0x0550, "usage_page": 0xFF00, "usage": 0x01, "out_len": 34, "feat_len": 0}
V5 = {"path": "y", "vid": 0x0D62, "pid": 0x1A1C, "usage_page": 0xFF00, "usage": 0xCC, "out_len": 0, "feat_len": 64}


def make(fake=None, hid=None, period=0.05):
    return aw.AlienwareEC(fake or FakeAwcc(), hid, curve_period=period)


class TestDiscovery(unittest.TestCase):
    def test_description(self):
        ec = make()
        self.assertEqual(ec.th.fans, [0x32, 0x33])
        self.assertEqual(ec.th.sensors, [0x01, 0x06])
        self.assertEqual(ec.th.profiles, [0xA0, 0xA1, 0xA3, 0xA4])
        self.assertTrue(ec.th.gmode)
        self.assertEqual(ec.th.fan_sensors, {0x32: [0x01], 0x33: [0x06]})
        self.assertEqual(ec.kind, "alienware")
        self.assertTrue(ec.available)

    def test_bad_description_rejected(self):
        with self.assertRaises(aw.AwccError):
            make(FakeAwcc(fans=()))

    def test_overreported_profiles_stop(self):
        f = FakeAwcc()
        orig = f.call

        def call(path, cls, method, args, out):
            r = orig(path, cls, method, args, out)
            if method == aw.M_INFO and args["arg2"] & 0xFF == 0x02:
                r = (r & 0x00FFFFFF) | (9 << 24)  # 9 profil bildir, 4 tane var
            return r
        f.call = call
        self.assertEqual(make(f).th.profiles, [0xA0, 0xA1, 0xA3, 0xA4])

    def test_status(self):
        f = FakeAwcc()
        f.rpm = {0x32: 2500, 0x33: 5000}
        s = make(f).status()
        self.assertEqual(s, {"cpu_temp": 50, "gpu_temp": 45, "cpu_rpm": 2500, "gpu_rpm": 5000,
                             "cpu_duty": 50, "gpu_duty": 100})

    def test_nonsense_temperature_is_unknown(self):
        f = FakeAwcc()
        f.temps[0x01] = 4000
        self.assertEqual(make(f).status()["cpu_temp"], 0)  # 0 = bilinmiyor (profiller._temp)

    def test_error_codes(self):
        with self.assertRaises(aw.AwccError):
            make().awcc.info(0x04, 0x77)


class TestPower(unittest.TestCase):
    def test_mode_mapping(self):
        f = FakeAwcc()
        ec = make(f)
        ec.set_power_mode(0)
        self.assertEqual(f.profile, 0xA3)          # Sessiz -> USTT Quiet
        ec.set_power_mode(1)
        self.assertEqual(f.profile, 0xA3)          # Low-power yok -> Quiet
        ec.set_power_mode(2)
        self.assertEqual((f.profile, f.gmode), (0xAB, 1))  # Performans -> G-mode, anahtar acik
        ec.set_power_mode(3)
        self.assertEqual((f.profile, f.gmode), (0xA0, 0))  # Eglence -> Balanced, G-mode kapandi
        self.assertEqual(ec.power_mode(), 3)

    def test_without_gmode_uses_performance(self):
        f = FakeAwcc(gmode=False)
        make(f).set_power_mode(2)
        self.assertEqual(f.profile, 0xA4)

    def test_legacy_profiles(self):
        f = FakeAwcc(profiles=(0x96, 0x97, 0x99), gmode=False)
        ec = make(f)
        ec.set_power_mode(0)
        self.assertEqual(f.profile, 0x96)
        ec.set_power_mode(2)
        self.assertEqual(f.profile, 0x99)

    def test_power_mode_read_from_controller(self):
        f = FakeAwcc()
        f.profile = 0xA3
        self.assertEqual(make(f).power_mode(), 0)

    def test_unknown_mode(self):
        with self.assertRaises(ValueError):
            make().set_power_mode(9)


class TestFans(unittest.TestCase):
    def test_curve_applies_custom_and_boost(self):
        f = FakeAwcc()
        f.temps = {0x01: 70, 0x06: 40}
        ec = make(f, period=10)
        ec.set_fan_curve((60, 40, 80, 70), (60, 40, 80, 70))
        self.assertEqual(f.profile, 0x00)
        self.assertEqual(ec.fan_mode(), aw.FAN_CUSTOM)
        self.assertEqual(f.boost[0x32], 55)   # 60->40, 80->70: 70 C -> 55
        self.assertEqual(f.boost[0x33], 20)   # 45 C alti: ilk nokta (45, 20)
        ec.shutdown()

    def test_curve_thread_follows_temperature(self):
        f = FakeAwcc()
        f.temps = {0x01: 50, 0x06: 50}
        ec = make(f, period=0.03)
        ec.set_fan_curve((60, 40, 80, 70), (60, 40, 80, 70))
        f.temps[0x01] = 80
        time.sleep(0.2)
        self.assertEqual(f.boost[0x32], 70)
        f.temps[0x01] = 50                    # soguma: inis adim basina en cok 3
        time.sleep(0.07)
        self.assertGreater(f.boost[0x32], 40)
        ec.shutdown()
        self.assertEqual(ec.fan_mode(), aw.FAN_AUTO)

    def test_auto_restores_requested_profile(self):
        f = FakeAwcc()
        ec = make(f, period=10)
        ec.set_power_mode(0)
        ec.set_fan_curve((60, 40, 80, 70), (60, 40, 80, 70))
        ec.set_power_mode(0)                  # ozel fan modunda profil degismez
        self.assertEqual(f.profile, 0x00)
        ec.set_fan_mode(aw.FAN_AUTO)
        self.assertEqual(f.profile, 0xA3)
        self.assertEqual(f.boost, {0x32: 0, 0x33: 0})

    def test_max(self):
        f = FakeAwcc()
        ec = make(f)
        ec.set_fan_mode(aw.FAN_MAX)
        self.assertEqual((f.profile, f.boost), (0x00, {0x32: 100, 0x33: 100}))
        self.assertEqual(ec.fan_mode(), aw.FAN_MAX)

    def test_blind_falls_back_to_controller(self):
        f = FakeAwcc()
        ec = make(f, period=0.02)
        ec.set_fan_curve((60, 40, 80, 70), (60, 40, 80, 70))
        f.fail_temps = True
        time.sleep(0.4)
        self.assertEqual(ec.fan_mode(), aw.FAN_AUTO)
        self.assertEqual(f.profile, 0xA0)

    def test_curve_refused_without_temperature(self):
        f = FakeAwcc()
        f.fail_temps = True
        ec = make(f)
        with self.assertRaises(RuntimeError):
            ec.set_fan_curve((60, 40, 80, 70), (60, 40, 80, 70))
        self.assertEqual((ec.fan_mode(), f.profile), (aw.FAN_AUTO, 0xA0))

    def test_curve_is_validated(self):
        f = FakeAwcc()
        f.temps = {0x01: 95, 0x06: 95}
        ec = make(f, period=10)
        ec.set_fan_curve((99, 0, 99, 0), (99, 0, 99, 0))  # anlamsiz egri guvenli sinira cekilir
        self.assertGreaterEqual(f.boost[0x32], 45)
        ec.shutdown()

    def test_fan_default_shape(self):
        d = make().fan_default()
        self.assertEqual(len(d["cpu"]), 4)
        self.assertEqual(d["cpu"][-1], (100, 100))
        self.assertTrue(d["reference"])

    def test_interpolate(self):
        pts = [(45, 20), (60, 40), (80, 70), (100, 100)]
        self.assertEqual(aw.interpolate(pts, 30), 20)
        self.assertEqual(aw.interpolate(pts, 70), 55)
        self.assertEqual(aw.interpolate(pts, 120), 100)


class TestExternalChange(unittest.TestCase):
    """Alienware Fn tuslari (G-mode, Stealth) ya da AWCC profili uygulamadan bagimsiz degistirir."""

    def test_gmode_key_stops_curve(self):
        f = FakeAwcc()
        f.temps = {0x01: 75, 0x06: 70}
        ec = make(f, period=0.03)
        ec.set_power_mode(0)
        ec.set_fan_curve((60, 40, 80, 70), (60, 40, 80, 70))
        self.assertGreater(f.boost[0x32], 0)
        f.profile, f.gmode = 0xAB, 1          # kullanici G-mode tusuna basti
        time.sleep(0.2)
        self.assertEqual(ec.fan_mode(), aw.FAN_AUTO)
        self.assertEqual(f.boost, {0x32: 0, 0x33: 0})   # takviye birakildi
        self.assertEqual(f.profile, 0xAB)               # uygulama profili geri ALMADI
        self.assertEqual(ec.power_mode(), 2)            # arayuz Performans gosterir
        n = len(f.calls)
        time.sleep(0.15)
        self.assertFalse([c for c in f.calls[n:] if c[0] == aw.M_CONTROL])  # dongu bitti, yazma yok

    def test_stealth_key_while_auto(self):
        f = FakeAwcc()
        ec = make(f)
        ec.set_power_mode(2)
        f.profile, f.gmode = 0xA3, 0          # Stealth: sessiz profil
        self.assertEqual(ec.power_mode(), 0)
        ec.set_fan_mode(aw.FAN_AUTO)          # sonraki otomatik donus kullanicinin secimini korur
        self.assertEqual(f.profile, 0xA3)

    def test_external_change_while_max(self):
        f = FakeAwcc()
        ec = make(f)
        ec.set_fan_mode(aw.FAN_MAX)
        f.profile = 0xA0
        self.assertEqual(ec.fan_mode(), aw.FAN_AUTO)
        self.assertEqual(f.boost, {0x32: 0, 0x33: 0})

    def test_own_mode_not_misread(self):
        """Guc tasarrufu, bu cihazda Quiet profiline duser; bu dis degisiklik sanilmamali."""
        f = FakeAwcc()
        ec = make(f)
        ec.set_power_mode(1)
        self.assertEqual(f.profile, 0xA3)
        self.assertEqual(ec.power_mode(), 1)

    def test_own_custom_mode_is_not_external(self):
        f = FakeAwcc()
        ec = make(f, period=10)
        ec.set_power_mode(0)
        ec.set_fan_curve((60, 40, 80, 70), (60, 40, 80, 70))
        self.assertEqual((ec.fan_mode(), ec.power_mode()), (aw.FAN_CUSTOM, 0))
        ec.shutdown()


class TestKeyboard(unittest.TestCase):
    def setUp(self):
        FakeHidDevice.sent = []

    def test_no_rgb_keyboard(self):
        ec = make(hid=FakeHid([]))
        self.assertFalse(ec.kb_available)
        self.assertTrue(ec.kb_reason)
        self.assertEqual(ec.set_color(1, 2, 3), 0)  # sessizce yok sayilir

    def test_v4_sequence(self):
        ec = make(hid=FakeHid([V4]))
        self.assertTrue(ec.kb_available)
        ec.set_color(255, 10, 0)
        kinds = [s[1][:3] for s in FakeHidDevice.sent]
        self.assertEqual(kinds, [(0, 3, 0x21), (0, 3, 0x21), (0, 3, 0x27), (0, 3, 0x21)])
        color = FakeHidDevice.sent[2][1]
        self.assertEqual(color[3:8], (255, 10, 0, 0, aw.AlienFx.LIGHTS))
        self.assertTrue(all(s[2] == 34 for s in FakeHidDevice.sent))
        ec.set_color(255, 10, 0)                  # ayni renk tekrar gonderilmez
        self.assertEqual(len(FakeHidDevice.sent), 4)

    def test_v5_sequence(self):
        ec = make(hid=FakeHid([V5]))
        ec.set_color(0, 0, 255)
        first, last = FakeHidDevice.sent[0][1], FakeHidDevice.sent[-1][1]
        self.assertEqual(first, (0xCC, 0x94))
        self.assertEqual(last, (0xCC, 0x8B, 0x01, 0xFF))
        colors = [s[1] for s in FakeHidDevice.sent if s[1][:3] == (0xCC, 0x8C, 0x02)]
        self.assertEqual(sum((len(c) - 4) // 4 for c in colors), aw.AlienFx.V5_KEYS)
        self.assertEqual(colors[0][4:8], (1, 0, 0, 255))
        self.assertTrue(all(len(c) <= 64 for c in colors))

    def test_other_vendor_ignored(self):
        self.assertFalse(make(hid=FakeHid([dict(V4, vid=0x1234)])).kb_available)


class TestDetection(unittest.TestCase):
    def test_vendor(self):
        self.assertTrue(aw.vendor_ok("Alienware"))
        self.assertTrue(aw.vendor_ok("Dell Inc."))
        self.assertFalse(aw.vendor_ok("MONSTER"))
        self.assertFalse(aw.vendor_ok(None))

    def test_open_on_this_pc(self):
        """Bu (Clevo/Monster) bilgisayarda Alienware yolu secilmemeli ve hata vermemeli."""
        ec, err = aw.open_alienware()
        self.assertIsNone(ec)
        self.assertEqual(err, "")

    def test_open_dchu_unchanged_here(self):
        self.assertIn(donanim.open_dchu().kind, ("clevo", ""))


class TestProfileIntegration(unittest.TestCase):
    """profiller.Manager'in denetleyici adimlari Alienware nesnesiyle calisir."""

    def test_manager_steps(self):
        import profiller
        f = FakeAwcc()
        f.temps = {0x01: 60, 0x06: 55}
        ec = make(f, period=10)

        class M:
            dchu = ec
        for p in profiller.PROFILES:
            profiller.Manager._ec(M, p)
            profiller.Manager._fan(M, p)
            custom = p["fan"][0] == "curve"
            self.assertEqual(f.profile == 0x00, custom, p["id"])
            if not custom:
                self.assertEqual(f.profile, ec.th.profile_for_mode(p["ec"]), p["id"])
        ec.shutdown()


if __name__ == "__main__":
    unittest.main()
