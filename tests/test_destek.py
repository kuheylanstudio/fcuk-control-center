# -*- coding: utf-8 -*-
"""destek.py ve Clevo DCHU yazma kapisi: baska Clevo modellerinin BIOS bayraklarini taklit eden sahte
denetleyici kitapligiyla. Gercek donanima dokunmaz.

Calistirma (depo kokunden):  python -m unittest discover -s tests -v
"""
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ceviri  # noqa: E402
import destek  # noqa: E402
import donanim as hw  # noqa: E402

ceviri.set_lang("tr")


class FakeDll:
    """InsydeDCHU.dll taklidi: okumalar bayraklari doner, yazmalar kaydedilir."""

    def __init__(self, wmi16=0x893, wmi122=0x70020053, wmi96=0x21C, kb=6, fans=2, p43=1, ex17=0, ex20=0,
                 temp=60, table=True, ex=True):
        self.ints = {16: wmi16, 122: wmi122, 96: wmi96}
        p13 = bytearray(256)
        p13[12], p13[15], p13[43] = fans, kb, p43
        if table:  # fabrika egrisi: 45/27 60/39 75/63 (gorevler 0-255 olcekte)
            for o in (16, 24):
                p13[o:o + 6] = bytes([45, 69, 60, 99, 75, 161])
        self.p13 = bytes(p13)
        p12 = bytearray(256)
        p12[18], p12[21] = temp, 50
        self.p12 = bytes(p12)
        self.ex = bytearray(256)
        self.ex[17], self.ex[20] = ex17, ex20
        if not ex:
            self.SetDCHU_DataEx = None
        self.writes = []

    def GetDCHU_Data_Integer(self, cmd, ref):
        ref._obj.value = self.ints.get(cmd, 0)

    def GetDCHU_Data_Buffer(self, cmd, buf):
        src = {12: self.p12, 13: self.p13}.get(cmd, bytes(256))
        for i, v in enumerate(src):
            buf[i] = v

    def SetDCHU_DataEx(self, cmd, inp, n, out):
        for i, v in enumerate(self.ex):
            out[i] = v

    def ReadAppSettings(self, page, off, n, buf):
        buf[0] = 3

    def SetDCHU_Data(self, cmd, buf, n):
        self.writes.append(("data", cmd, bytes(buf[:n])))
        return 0

    def WriteAppSettings(self, page, off, n, buf):
        self.writes.append(("app", page, off))


def make(**kw):
    """Gercek DCHU sinifi, kitaplik yerine FakeDll ile (DLL aranmaz, yuklenmez)."""
    d = hw.DCHU.__new__(hw.DCHU)
    d.dll = FakeDll(**kw)
    d.path = "sahte"
    d.lock = threading.Lock()
    d._fan_default = d._features = d._flags = d._kb_kind = d._kb_level = d._support = None
    return d


def state(d, f):
    return d.support()[f]["state"]


class Algilama(unittest.TestCase):
    def test_gelistirme_bilgisayari(self):
        d = make()
        for f in ("ec", "fan_read", "fan_control", "fan_curve", "power_mode", "keyboard"):
            self.assertEqual(state(d, f), "ok", f)
        c = hw.caps(d)
        self.assertTrue(all(c[k] for k in ("power", "fan_max", "fan_curve", "fan_read", "temp", "kb")))

    def test_ozellik_listesi_olmayan_kitaplik(self):
        d = make(ex=False)  # eski InsydeDCHU: SetDCHU_DataEx yok; bayraklar yine okunur
        self.assertIsNone(d.feature_list())
        self.assertEqual(state(d, "power_mode"), "ok")

    def test_denetleyici_sessiz(self):
        d = make(temp=0)
        self.assertEqual(state(d, "ec"), "no")
        self.assertFalse(hw.caps(d)["temp"])
        with self.assertRaises(hw.Unsupported):
            d.set_wmi(0x46, 0)
        self.assertEqual(d.dll.writes, [])

    def test_uc_fan_egri_yazilmaz(self):
        d = make(fans=3)
        self.assertEqual(state(d, "fan_curve"), "no")
        self.assertFalse(d.fan_curve_ok)
        with self.assertRaises(hw.Unsupported):
            d.set_fan_curve((60, 40, 75, 60), (60, 40, 75, 60))
        self.assertEqual(d.dll.writes, [])
        d.set_fan_mode(hw.FAN_AUTO)  # fabrika tablosu yine kullanilabilir
        self.assertTrue(d.dll.writes)

    def test_ozel_egri_yasak(self):
        self.assertEqual(state(make(p43=0b11), "fan_curve"), "no")
        self.assertEqual(state(make(wmi122=0x70020043), "fan_curve"), "no")  # b4 yok

    def test_devir_tablolu_fan(self):
        self.assertEqual(state(make(ex20=0x10), "fan_curve"), "no")

    def test_gecersiz_fabrika_tablosu(self):
        self.assertEqual(state(make(table=False), "fan_curve"), "no")

    def test_fan_yok(self):
        d = make(wmi122=0x70030053)  # b16
        self.assertEqual(state(d, "fan_control"), "no")
        with self.assertRaises(hw.Unsupported):
            d.set_fan_mode(hw.FAN_MAX)
        self.assertEqual(d.dll.writes, [])

    def test_eksik_guc_modu(self):
        d = make(ex17=0b1110)  # sessiz (0) yok
        self.assertEqual(state(d, "power_mode"), "partial")
        with self.assertRaises(hw.Unsupported):
            d.set_power_mode(0)
        self.assertEqual(d.dll.writes, [])
        d.set_power_mode(2)
        self.assertTrue(d.dll.writes)

    def test_guc_modu_yok(self):
        d = make(wmi16=0x892)
        self.assertEqual(state(d, "power_mode"), "no")
        self.assertFalse(hw.caps(d)["power"])

    def test_klavye_tipleri(self):
        cases = {6: "ok", 2: "ok", 1: "partial", 23: "no", 3: "no", 243: "no", 0: "no"}
        for kb, want in cases.items():
            self.assertEqual(state(make(kb=kb), "keyboard"), want, kb)

    def test_klavye_yoksa_renk_gonderilmez(self):
        d = make(kb=0)
        self.assertFalse(d.kb_available)
        self.assertTrue(d.kb_reason)
        d.set_color(255, 0, 0)
        self.assertEqual(d.dll.writes, [])

    def test_uc_bolgeli_rgb(self):
        d = make(kb=6)
        d.set_color(255, 0, 0)
        d.set_color(0, 255, 0)
        # once donanim parlakligi tam (0xF4), sonra uc bolge; parlaklik her karede degil, araliklarla
        self.assertEqual([w[2][3] for w in d.dll.writes], [0xF4, 0xF0, 0xF1, 0xF2, 0xF0, 0xF1, 0xF2])
        self.assertEqual(d.dll.writes[0][2][0], 0xFF)

    def test_klavye_parlakligi_yeniden_acilir(self):
        # Fn tusu / uyku donanim parlakligini 0'a indirirse renk gorunmez: arayla yeniden tam acilir
        d = make(kb=6)
        d.set_color(255, 0, 0)
        d._kb_bright_at -= hw.KB_BRIGHT_EVERY
        d.set_color(255, 0, 0)
        self.assertEqual([w[2][3] for w in d.dll.writes].count(0xF4), 2)

    def test_tek_renkli_klavye_parlaklik(self):
        d = make(kb=1)
        d.set_color(255, 255, 255)
        d.set_color(250, 250, 250)  # ayni seviye: tekrar gonderilmez
        self.assertEqual(d.dll.writes, [("data", 39, bytes([5, 0, 0, 0]))])


class Rapor(unittest.TestCase):
    def test_clevo_raporu(self):
        rows = destek.detect(make(fans=3), gpu_names=[])
        ids = [r["id"] for r in rows]
        self.assertEqual(ids, [f for f, _ in destek.FEATURES])
        curve = rows[ids.index("fan_curve")]
        self.assertEqual(curve["state"], "no")
        self.assertIn("3", curve["why"])
        self.assertTrue(all(r["label"] for r in rows))

    def test_denetleyicisiz(self):
        rows = {r["id"]: r for r in destek.detect(hw.NullDCHU("yok"), gpu_names=[])}
        for f in destek.EC_FEATURES:
            self.assertEqual(rows[f]["state"], "no")
        self.assertEqual(rows["fn_keys"]["state"], "no")
        self.assertEqual(rows["cpu_tuning"]["state"], "ok")


if __name__ == "__main__":
    unittest.main()
