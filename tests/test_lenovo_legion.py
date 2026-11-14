# -*- coding: utf-8 -*-
"""Lenovo Legion arka ucu: sahte (mock) WMI ve HID ile birim testleri. Gercek Legion donanimi gerekmez.

Calistirma (depo kokunden):  python -m unittest discover -s tests -v
Gercek PowerShell tasiyicisini da denemek icin:  LENOVO_PS_TEST=1 ile calistir.
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import donanim  # noqa: E402
import lenovo_kb  # noqa: E402
import lenovo_legion as L  # noqa: E402

LEGION = {"SystemManufacturer": "LENOVO", "SystemProductName": "82JU", "SystemFamily": "Legion 5 15ACH6H",
          "SystemVersion": "Legion 5 15ACH6H"}
MONSTER = {"SystemManufacturer": "MONSTER", "SystemProductName": "ABRA A5 V21.1", "SystemFamily": "ABRA",
           "SystemVersion": "Not Applicable"}
GZ_ALL = {"IsSupportSmartFan", "GetSmartFanMode", "SetSmartFanMode", "IsSupportGSync", "GetGSyncStatus",
          "SetGSyncStatus", "IsSupportIGPUMode", "GetIGPUModeStatus", "SetIGPUModeStatus", "GetCPUTemp",
          "GetGPUTemp", "GetFan1Speed", "GetFan2Speed", "SetLightControlOwner"}
SET_METHODS = ("Set", "Fan_Set", "Notify")


class FakeWmi:
    """root\\WMI yerine: yanitlar (sinif, yontem, args) -> deger; olmayan yontem hata verir. Tum cagrilar kaydedilir."""

    def __init__(self, gz=GZ_ALL, answers=None, classes=None, tables=None):
        self.gz = set(gz)
        self.answers = dict(answers or {})
        self.classes = classes if classes is not None else {L.GAMEZONE: self.gz}
        self.tables = tables or []
        self.log = []
        self.closed = False
        self.state = {}

    def class_methods(self, cls):
        self.log.append(("methods", cls))
        if cls not in self.classes:
            raise RuntimeError("Not found")
        return list(self.classes[cls])

    def query(self, cls, props):
        self.log.append(("query", cls))
        if cls != L.FAN_TABLE:
            raise RuntimeError("Not found")
        return [{p: r.get(p) for p in props} for r in self.tables]

    def _one(self, cls, method, args):
        self.log.append((cls, method, json.dumps(args, sort_keys=True) if args else None))
        if cls not in self.classes or method not in self.classes[cls]:
            raise RuntimeError("yontem yok")
        if method.startswith(SET_METHODS):
            self.state[(cls, method)] = args
            follow = {"SetSmartFanMode": ("GetSmartFanMode", "Data"), "SetGSyncStatus": ("GetGSyncStatus", "Data"),
                      "SetIGPUModeStatus": ("GetIGPUModeStatus", "mode"),
                      "Fan_Set_FullSpeed": ("Fan_Get_FullSpeed", "Status")}.get(method)
            if follow:
                self.answers[(cls, follow[0], None)] = args[follow[1]]
            return None
        key = (cls, method, json.dumps(args, sort_keys=True) if args else None)
        if key not in self.answers:
            raise RuntimeError("yanit yok: %r" % (key,))
        return self.answers[key]

    def calls(self, cls, items):
        out = []
        for m, a, _o in items:
            try:
                out.append((True, self._one(cls, m, a)))
            except Exception as exc:
                out.append((False, str(exc)))
        return out

    def call(self, cls, method, args=None, out="Data"):
        return self._one(cls, method, args)

    def close(self):
        self.closed = True

    def writes(self):
        return [e for e in self.log if len(e) == 3 and e[1].startswith(SET_METHODS)]


class FakeEnergy:
    def __init__(self, available=True, mode="normal"):
        self.available, self.mode, self.sent = available, mode, []

    def get(self):
        return self.mode

    def set(self, mode):
        self.sent.append(mode)
        self.mode = mode


def gz_answers(mode=2, smartfan=5, gsync_sup=1, igpu_sup=1, gsync=0, igpu=0):
    g = L.GAMEZONE
    return {(g, "IsSupportSmartFan", None): smartfan, (g, "GetSmartFanMode", None): mode,
            (g, "IsSupportGSync", None): gsync_sup, (g, "GetGSyncStatus", None): gsync,
            (g, "IsSupportIGPUMode", None): igpu_sup, (g, "GetIGPUModeStatus", None): igpu,
            (g, "GetCPUTemp", None): 55, (g, "GetGPUTemp", None): 48,
            (g, "GetFan1Speed", None): 2100, (g, "GetFan2Speed", None): 2300}


TABLE_ROW = {"Fan_Id": 0, "Sensor_ID": 3,
             "FanTable_Data": [1600, 1900, 2200, 2500, 2800, 3100, 3400, 3700, 4000, 4400],
             "SensorTable_Data": [45, 50, 55, 60, 65, 70, 75, 80, 85, 90], "CurrentFanMaxSpeed": 4400}


def full_wmi(mode=2, custom=True, fullspeed=True, **kw):
    ans = gz_answers(mode=mode, **kw)
    ans[(L.OTHER, "GetSupportThermalMode", None)] = 0b111 | ((1 << 16) if custom else 0)
    fan_methods = {"Fan_Set_Table", "Fan_GetCurrentSensorTemperature", "Fan_GetCurrentFanSpeed"}
    if fullspeed:
        fan_methods |= {"Fan_Get_FullSpeed", "Fan_Set_FullSpeed"}
        ans[(L.FAN_METHOD, "Fan_Get_FullSpeed", None)] = 0
    for sid, v in ((3, 61), (4, 52)):
        ans[(L.FAN_METHOD, "Fan_GetCurrentSensorTemperature", json.dumps({"SensorID": sid}))] = v
    for fid, v in ((0, 2200), (1, 2000)):
        ans[(L.FAN_METHOD, "Fan_GetCurrentFanSpeed", json.dumps({"FanID": fid}))] = v
    classes = {L.GAMEZONE: GZ_ALL, L.OTHER: {"GetSupportThermalMode"}, L.FAN_METHOD: fan_methods}
    return FakeWmi(answers=ans, classes=classes, tables=[dict(TABLE_ROW)])


def legion(wmi, kb=None, energy=None):
    return L.open_legion(info=LEGION, wmi=wmi, kb=kb, energy=energy or FakeEnergy(available=False))


# ============================================================================= tespit
class Detection(unittest.TestCase):
    def test_monster_is_not_touched(self):
        w = FakeWmi()
        self.assertIsNone(L.open_legion(info=MONSTER, wmi=w))
        self.assertEqual(w.log, [])  # Clevo/Monster'da WMI'ye bile sorulmaz

    def test_lenovo_but_not_legion(self):
        w = FakeWmi()
        info = dict(LEGION, SystemFamily="ThinkPad X1", SystemVersion="ThinkPad X1 Carbon")
        self.assertIsNone(L.open_legion(info=info, wmi=w))
        self.assertEqual(w.log, [])

    def test_legion_without_gamezone(self):
        w = FakeWmi(classes={})
        self.assertIsNone(L.open_legion(info=LEGION, wmi=w, kb=None, energy=FakeEnergy(False)))
        self.assertTrue(w.closed)
        self.assertEqual(w.writes(), [])

    def test_legion_detected_and_probe_is_read_only(self):
        w = full_wmi()
        ec = legion(w)
        self.assertIsInstance(ec, L.LegionEC)
        self.assertEqual(ec.kind, "lenovo")
        self.assertTrue(ec.available)
        self.assertEqual(w.writes(), [])  # yetenek taramasi hicbir sey yazmaz

    def test_unsupported_is_shared_with_donanim(self):
        self.assertIs(L.Unsupported, donanim.Unsupported)


# ============================================================================= guc modu
class Power(unittest.TestCase):
    def test_mapping_read(self):
        for lenovo, app in ((1, 0), (2, 3), (3, 2), (255, 2), (224, 2)):
            self.assertEqual(legion(full_wmi(mode=lenovo)).power_mode(), app)

    def test_set_sends_only_when_different(self):
        w = full_wmi(mode=2)
        ec = legion(w)
        ec.set_power_mode(3)  # Eglence -> Dengeli: zaten dengeli
        self.assertEqual(w.writes(), [])
        ec.set_power_mode(0)
        self.assertEqual(w.state[(L.GAMEZONE, "SetSmartFanMode")], {"Data": 1})
        ec.set_power_mode(2)
        self.assertEqual(w.state[(L.GAMEZONE, "SetSmartFanMode")], {"Data": 3})

    def test_no_smartfan_support_sends_nothing(self):
        w = full_wmi(smartfan=0)
        ec = legion(w)
        with self.assertRaises(donanim.Unsupported):
            ec.set_power_mode(2)
        self.assertIsNone(ec.power_mode())
        self.assertEqual(w.writes(), [])

    def test_mode_not_in_supported_bits(self):
        w = full_wmi()
        w.answers[(L.OTHER, "GetSupportThermalMode", None)] = 0b011  # performans yok
        ec = legion(w)
        with self.assertRaises(donanim.Unsupported):
            ec.set_power_mode(2)
        self.assertEqual(w.writes(), [])

    def test_unknown_mode(self):
        with self.assertRaises(ValueError):
            legion(full_wmi()).set_power_mode(9)


# ============================================================================= sensorler
class Sensors(unittest.TestCase):
    def test_fan_method_preferred_over_gamezone(self):
        ec = legion(full_wmi())
        self.assertEqual(ec.caps["sensor"], "fan")
        s = ec.status()
        self.assertEqual((s["cpu_temp"], s["gpu_temp"], s["cpu_rpm"], s["gpu_rpm"]), (61, 52, 2200, 2000))
        self.assertEqual(s["cpu_duty"], 50)  # 2200 / 4400
        self.assertEqual(ec.temps(), (61, 52))

    def test_other_method_v3(self):
        w = full_wmi()
        w.classes[L.OTHER] = {"GetSupportThermalMode", "GetFeatureValue"}
        for k, v in (("cpu_temp", 70), ("gpu_temp", 60), ("cpu_rpm", 3000), ("gpu_rpm", 3100)):
            w.answers[(L.OTHER, "GetFeatureValue", json.dumps({"IDs": L.OTHER_IDS[k]}))] = v
        ec = legion(w)
        self.assertEqual(ec.caps["sensor"], "other")
        self.assertEqual(ec.status()["cpu_temp"], 70)

    def test_gamezone_fallback(self):
        ec = legion(FakeWmi(answers=gz_answers()))
        self.assertEqual(ec.caps["sensor"], "gz")
        self.assertEqual(ec.status()["cpu_temp"], 55)

    def test_zero_temperature_is_unknown(self):
        ans = gz_answers()
        ans[(L.GAMEZONE, "GetCPUTemp", None)] = 0
        ec = legion(FakeWmi(answers=ans))
        self.assertEqual(ec.caps["sensor"], "")
        self.assertEqual(ec.status(), {})


# ============================================================================= fanlar
class Fans(unittest.TestCase):
    def test_build_table_layout(self):
        t = L.build_table([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
        self.assertEqual(len(t), 64)
        self.assertEqual(t[:6], [1, 0, 0, 0, 0, 0])
        self.assertEqual(t[6:26], [1, 0, 2, 0, 3, 0, 4, 0, 5, 0, 6, 0, 7, 0, 8, 0, 9, 0, 10, 0])
        self.assertEqual(set(t[26:]), {0})
        with self.assertRaises(ValueError):
            L.build_table([11] * 10)
        with self.assertRaises(ValueError):
            L.build_table([1] * 9)

    def test_max_and_auto(self):
        w = full_wmi()
        ec = legion(w)
        self.assertEqual(ec.fan_mode(), donanim.FAN_AUTO)
        ec.set_fan_mode(donanim.FAN_MAX)
        self.assertEqual(ec.fan_mode(), donanim.FAN_MAX)
        ec.set_fan_mode(donanim.FAN_AUTO)
        self.assertEqual(w.state[(L.FAN_METHOD, "Fan_Set_FullSpeed")], {"Status": 0})
        self.assertEqual(ec.fan_mode(), donanim.FAN_AUTO)

    def test_no_fullspeed(self):
        w = full_wmi(fullspeed=False)
        ec = legion(w)
        with self.assertRaises(donanim.Unsupported):
            ec.set_fan_mode(donanim.FAN_MAX)
        ec.set_fan_mode(donanim.FAN_AUTO)  # yapilacak bir sey yok: komut gitmez
        self.assertEqual(w.writes(), [])
        self.assertFalse(ec.extras()["fullspeed"])

    def test_curve_requires_custom_mode(self):
        w = full_wmi(mode=2)
        ec = legion(w)
        self.assertTrue(ec.caps["curve"])
        with self.assertRaises(donanim.Unsupported):
            ec.set_fan_curve((64, 32, 80, 55), (64, 32, 80, 55))
        self.assertEqual(w.writes(), [])  # ozel modda degil: tablo yazilmaz, moda da gecilmez

    def test_curve_written_in_custom_mode(self):
        w = full_wmi(mode=255)
        ec = legion(w)
        levels = ec.set_fan_curve((64, 32, 80, 55), (62, 38, 80, 60))
        sent = w.state[(L.FAN_METHOD, "Fan_Set_Table")]["FanTable"]
        self.assertEqual(sent, L.build_table(levels))
        self.assertEqual(levels, sorted(levels))  # azalmayan
        self.assertTrue(all(lv >= m for lv, m in zip(levels, L.MIN_LEVELS_V1)))
        self.assertTrue(all(lv <= 10 for lv in levels))
        self.assertEqual(ec.fan_mode(), donanim.FAN_CUSTOM)
        ec.set_fan_mode(donanim.FAN_AUTO)  # bekci / fabrika: varsayilan tablo geri
        self.assertEqual(w.state[(L.FAN_METHOD, "Fan_Set_Table")]["FanTable"],
                         L.build_table([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]))
        self.assertEqual(ec.fan_mode(), donanim.FAN_AUTO)

    def test_leaving_custom_mode_forgets_curve(self):
        w = full_wmi(mode=255)
        ec = legion(w)
        ec.set_fan_curve((64, 32, 80, 55), (64, 32, 80, 55))
        ec.set_power_mode(0)
        self.assertEqual(ec.fan_mode(), donanim.FAN_AUTO)

    def test_no_custom_mode_no_curve(self):
        ec = legion(full_wmi(custom=False))
        self.assertFalse(ec.caps["curve"])
        self.assertIsNone(ec.fan_default())

    def test_bad_table_rejected(self):
        w = full_wmi()
        w.tables = [dict(TABLE_ROW, FanTable_Data=[0] * 10)]
        self.assertFalse(legion(w).caps["curve"])

    def test_fan_default_shape(self):
        d = legion(full_wmi()).fan_default()
        self.assertEqual(len(d["cpu"]), 4)
        self.assertEqual(d["cpu"][-1], (100, 100))
        temps = [p[0] for p in d["cpu"]]
        self.assertEqual(temps, sorted(temps))

    def test_curve_levels(self):
        rpms = TABLE_ROW["FanTable_Data"]
        lv = L.curve_levels([(45, 0), (60, 50), (80, 90), (100, 100)], TABLE_ROW["SensorTable_Data"], rpms,
                            L.MIN_LEVELS_V2)
        self.assertEqual(lv[0], 1)
        self.assertGreaterEqual(lv[-1], 9)
        self.assertEqual(lv, sorted(lv))
        unused = L.curve_levels([(45, 0), (100, 100)], [45] + [127] * 9, rpms, L.MIN_LEVELS_V1)
        self.assertEqual(unused[1:], [10] * 9)


# ============================================================================= Clevo komutlari
class ClevoCommands(unittest.TestCase):
    def test_raw_clevo_commands_never_reach_lenovo(self):
        w = full_wmi()
        ec = legion(w)
        for fn in (lambda: ec.set_wmi(0x46, 0), lambda: ec.set_data(14, b"\0"), lambda: ec.write_app(1, 1, b"\0")):
            with self.assertRaises(donanim.Unsupported):
                fn()
        self.assertEqual(w.writes(), [])


# ============================================================================= ekran karti ve pil
class GpuBattery(unittest.TestCase):
    def test_gpu_options_and_switch(self):
        w = full_wmi()
        ec = legion(w)
        self.assertEqual(ec.gpu_options(), ["hybrid", "igpu", "auto", "dgpu"])
        self.assertEqual(ec.gpu_mode(), "hybrid")
        self.assertFalse(ec.set_gpu_mode("igpu"))
        self.assertEqual(w.state[(L.GAMEZONE, "SetIGPUModeStatus")], {"mode": 1})
        self.assertTrue(ec.set_gpu_mode("dgpu"))  # yeniden baslatma ister
        self.assertEqual(ec.gpu_mode(), "dgpu")
        self.assertTrue(ec.set_gpu_mode("hybrid"))
        self.assertEqual(w.state[(L.GAMEZONE, "SetGSyncStatus")], {"Data": 0})

    def test_gpu_unsupported(self):
        w = full_wmi(gsync_sup=0, igpu_sup=0)
        ec = legion(w)
        self.assertEqual(ec.gpu_options(), [])
        self.assertNotIn("gpu", ec.extras())
        with self.assertRaises(donanim.Unsupported):
            ec.set_gpu_mode("dgpu")
        self.assertEqual(w.writes(), [])

    def test_battery(self):
        en = FakeEnergy(available=True)
        ec = legion(full_wmi(), energy=en)
        self.assertEqual(ec.extras()["battery"]["value"], "normal")
        ec.set_battery_mode("conservation")
        self.assertEqual(en.sent, ["conservation"])
        with self.assertRaises(ValueError):
            ec.set_battery_mode("bogus")

    def test_battery_unavailable(self):
        ec = legion(full_wmi(), energy=FakeEnergy(available=False))
        self.assertNotIn("battery", ec.extras())
        with self.assertRaises(donanim.Unsupported):
            ec.set_battery_mode("conservation")

    def test_energy_protocol(self):
        def raw(v):  # surucu ciktisi bayt sirasi ters gelir
            return int.from_bytes(v.to_bytes(4, "big"), "little")
        self.assertEqual(L.EnergyDrv.decode(raw(1 << 29)), "conservation")
        self.assertEqual(L.EnergyDrv.decode(raw((1 << 17) | (1 << 26))), "rapid")
        self.assertEqual(L.EnergyDrv.decode(raw(1 << 17)), "normal")
        self.assertEqual(L.EnergyDrv.decode(0), "normal")
        self.assertEqual(L.EnergyDrv.sequence("normal", "conservation"), [0x3])
        self.assertEqual(L.EnergyDrv.sequence("rapid", "conservation"), [0x8, 0x3])
        self.assertEqual(L.EnergyDrv.sequence("conservation", "rapid"), [0x5, 0x7])
        self.assertEqual(L.EnergyDrv.sequence("conservation", "normal"), [0x5])
        self.assertEqual(L.EnergyDrv.sequence("rapid", "normal"), [0x8])
        self.assertEqual(L.EnergyDrv.sequence("normal", "normal"), [])

    def test_energy_missing_device(self):
        e = L.EnergyDrv(path=r"\\.\YokBoyleBirAygit_FCUK")
        self.assertFalse(e.available)
        with self.assertRaises(donanim.Unsupported):
            e.set("conservation")


# ============================================================================= klavye
class Keyboard(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(lenovo_kb.classify(0x048D, 0xC965, 33), "4zone")
        self.assertEqual(lenovo_kb.classify(0x048D, 0xC995, 960), "spectrum")
        self.assertIsNone(lenovo_kb.classify(0x048D, 0xC965, 64))
        self.assertIsNone(lenovo_kb.classify(0x048D, 0x1234, 33))
        self.assertIsNone(lenovo_kb.classify(0x1D57, 0xC965, 33))

    def test_report(self):
        r = lenovo_kb.report_4zone(10, 20, 30)
        self.assertEqual(len(r), 33)
        self.assertEqual(list(r[:5]), [0xCC, 0x16, 1, 1, 2])
        self.assertEqual(list(r[5:17]), [10, 20, 30] * 4)
        self.assertEqual((r[17], r[18], r[19]), (0, 1, 1))
        self.assertEqual(set(r[20:]), {0})

    def test_find_prefers_4zone(self):
        kb = lenovo_kb.find([("a", 0x048D, 0xC995, 960), ("b", 0x048D, 0xC975, 33), ("c", 0x046D, 0xC077, 33)])
        self.assertEqual((kb.path, kb.kind, kb.available), ("b", "4zone", True))
        self.assertIsNone(lenovo_kb.find([("c", 0x046D, 0xC077, 33)]))

    def test_spectrum_sends_nothing(self):
        sent = []
        kb = lenovo_kb.Keyboard("a", 0xC995, "spectrum", sender=sent.append)
        self.assertFalse(kb.available)
        self.assertEqual(kb.set_color(1, 2, 3), 0)
        ec = legion(full_wmi(), kb=kb)
        self.assertFalse(ec.kb_available)
        self.assertTrue(ec.kb_reason)
        ec.set_color(1, 2, 3)
        self.assertEqual(sent, [])

    def test_4zone_through_ec(self):
        sent = []
        kb = lenovo_kb.Keyboard("b", 0xC975, "4zone", sender=sent.append)
        w = full_wmi()
        ec = legion(w, kb=kb)
        self.assertTrue(ec.kb_available)
        ec.set_color(255, 0, 128)
        ec.set_color(0, 0, 0)
        self.assertEqual(len(sent), 2)
        self.assertEqual(list(sent[0][5:8]), [255, 0, 128])
        owner = [e for e in w.writes() if e[1] == "SetLightControlOwner"]
        self.assertEqual(len(owner), 1)  # isik sahipligi yalnizca bir kez

    def test_no_keyboard(self):
        ec = legion(full_wmi(), kb=None)
        self.assertFalse(ec.kb_available)
        self.assertEqual(ec.set_color(1, 2, 3), 0)


class EngineIntegration(unittest.TestCase):
    """klavye_rgb.Engine gercek dongusuyle: oyun dahil tum modlar Lenovo 4 bolgeli klavyeye renk gonderir."""

    def _run(self, kb_kind, mode):
        import time
        import klavye_rgb
        sent = []
        kb = lenovo_kb.Keyboard("b", 0xC975, kb_kind, sender=sent.append)
        ec = legion(full_wmi(), kb=kb)
        eng = klavye_rgb.Engine(ec)
        cfg = json.loads(json.dumps(klavye_rgb.DEFAULTS))
        cfg["mode"] = mode
        eng.settings = klavye_rgb.snapshot(cfg)
        eng.start()
        time.sleep(0.6)
        eng.running = False
        eng.join(2)
        return sent, eng

    def test_modes_send_on_4zone(self):
        for mode in ("sabit", "nefes", "gokkusagi", "sistem", "oyun"):
            sent, eng = self._run("4zone", mode)
            self.assertTrue(sent, mode)
            self.assertEqual(eng.error, "", mode)
            self.assertTrue(all(len(r) == 33 and r[0] == 0xCC for r in sent))

    def test_spectrum_engine_sends_nothing(self):
        sent, _eng = self._run("spectrum", "gokkusagi")
        self.assertEqual(sent, [])


class ProfileSteps(unittest.TestCase):
    """profiller.Manager'in denetleyici adimlari (guc modu, fan) Lenovo nesnesiyle. Guc plani adimlari
    (gercek sistemi degistirir) burada calistirilmaz."""

    def _mgr(self, ec):
        import profiller

        class _Sensors:
            listeners = []
            gpu_name = ""
        return profiller, profiller.Manager(ec, _Sensors(), {}, lambda: None)

    def test_quiet_profile_on_lenovo(self):
        w = full_wmi(mode=2)
        profiller, mgr = self._mgr(legion(w))
        p = profiller.BY_ID["tam_sessiz"]
        mgr._ec(p)
        self.assertEqual(w.state[(L.GAMEZONE, "SetSmartFanMode")], {"Data": 1})
        with self.assertRaises(donanim.Unsupported):  # egri: ozel modda degil -> raporda "atlandi"
            mgr._fan(p)
        self.assertNotIn((L.FAN_METHOD, "Fan_Set_Table"), w.state)

    def test_performance_profile_on_lenovo(self):
        w = full_wmi(mode=1)
        profiller, mgr = self._mgr(legion(w))
        p = profiller.BY_ID["performans"]
        mgr._ec(p)
        mgr._fan(p)  # fan "auto": tam devir kapali, ek komut yok
        self.assertEqual(w.state[(L.GAMEZONE, "SetSmartFanMode")], {"Data": 3})

    def test_guard_on_lenovo_never_writes_table_outside_custom(self):
        w = full_wmi(mode=1)
        profiller, mgr = self._mgr(legion(w))
        mgr.applied = "tam_sessiz"
        for _ in range(6):
            mgr._guard_step({"cpu_temp": 95, "gpu_temp": 50}, profiller.BY_ID["tam_sessiz"])
        self.assertTrue(mgr.guard)
        self.assertNotIn((L.FAN_METHOD, "Fan_Set_Table"), w.state)


# ============================================================================= donanim.open_dchu
class OpenDchu(unittest.TestCase):
    def test_non_clevo_tries_lenovo(self):
        sentinel = object()
        old_c, old_o = donanim.clevo_present, L.open_legion
        try:
            donanim.clevo_present = lambda: False
            L.open_legion = lambda: sentinel
            self.assertIs(donanim.open_dchu(), sentinel)
            L.open_legion = lambda: None
            d = donanim.open_dchu()
            self.assertIsInstance(d, donanim.NullDCHU)
            self.assertFalse(d.available)

            def boom():
                raise RuntimeError("x")
            L.open_legion = boom
            self.assertIsInstance(donanim.open_dchu(), donanim.NullDCHU)
        finally:
            donanim.clevo_present, L.open_legion = old_c, old_o

    def test_clevo_never_asks_lenovo(self):
        called = []
        old_c, old_o, old_d = donanim.clevo_present, L.open_legion, donanim.DCHU
        try:
            donanim.clevo_present = lambda: True
            L.open_legion = lambda: called.append(1)

            class FakeDchu:
                available = True
                kind = "clevo"
            donanim.DCHU = FakeDchu
            self.assertIsInstance(donanim.open_dchu(), FakeDchu)
            self.assertEqual(called, [])
        finally:
            donanim.clevo_present, L.open_legion, donanim.DCHU = old_c, old_o, old_d


@unittest.skipUnless(os.name == "nt" and os.environ.get("LENOVO_PS_TEST") == "1",
                     "gercek PowerShell tasiyicisi: LENOVO_PS_TEST=1 ile")
class PowerShellTransport(unittest.TestCase):
    def test_roundtrip(self):
        import lenovo_wmi
        p = lenovo_wmi.PsWmi(timeout=60)
        try:
            rows = p.query("Win32_ComputerSystem", ["Manufacturer"], ns=r"root\cimv2")
            self.assertTrue(rows and "Manufacturer" in rows[0])
            with self.assertRaises(lenovo_wmi.WmiError):
                p.class_methods("LENOVO_GAMEZONE_DATA_YOK")
            res = p.calls("Win32_Process", [("GetOwner", None, "ReturnValue"), ("Yok", None, "X")],
                          ns=r"root\cimv2")
            self.assertTrue(res[0][0])
            self.assertFalse(res[1][0])
        finally:
            p.close()


if __name__ == "__main__":
    unittest.main()
