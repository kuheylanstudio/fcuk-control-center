# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""wmi_istemci: gercek Windows WMI'ya karsi (her bilgisayarda bulunan StdRegProv ile) tip donusumleri.

Acer yontemlerinin kullandigi tipler burada sinanir: uint32 (0x80000001 gibi isaretli tasan deger),
uint64 (WMI'da metin olarak tasinir) ve uint8[] (bayt dizisi). Yalnizca HKCU altinda gecici bir anahtar
yazilir ve silinir.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform == "win32":
    import wmi_istemci as w

HKCU = 0x80000001
KEY = r"Software\FCUKControlCenterWmiTest"


@unittest.skipUnless(sys.platform == "win32", "yalnizca Windows")
class WmiLiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reg = w.WmiClient(r"root\default")
        cls.cim = w.WmiClient(r"root\cimv2")

    @classmethod
    def tearDownClass(cls):
        try:
            cls.reg.call("StdRegProv", "StdRegProv", "DeleteKey", {"hDefKey": HKCU, "sSubKeyName": KEY})
        finally:
            cls.reg.close()
            cls.cim.close()

    def call(self, method, **kw):
        kw.setdefault("hDefKey", HKCU)
        kw.setdefault("sSubKeyName", KEY)
        return self.reg.call("StdRegProv", "StdRegProv", method, kw)

    def test_types_roundtrip(self):
        self.assertEqual(self.call("CreateKey")["ReturnValue"], 0)
        self.assertEqual(self.call("SetBinaryValue", sValueName="b", uValue=b"\x01\x02\xfa\x00\xff")["ReturnValue"], 0)
        self.assertEqual(self.call("GetBinaryValue", sValueName="b")["uValue"], b"\x01\x02\xfa\x00\xff")
        big = 0xFEDCBA9876543210
        self.assertEqual(self.call("SetQWORDValue", sValueName="q", uValue=big)["ReturnValue"], 0)
        self.assertEqual(self.call("GetQWORDValue", sValueName="q")["uValue"], big)
        self.assertEqual(self.call("SetDWORDValue", sValueName="d", uValue=0xFFFFFFF0)["ReturnValue"], 0)
        self.assertEqual(self.call("GetDWORDValue", sValueName="d")["uValue"], 0xFFFFFFF0)

    def test_signature(self):
        p = self.reg.in_params("StdRegProv", "SetBinaryValue")
        self.assertEqual(p["uValue"], w.CIM_FLAG_ARRAY | w.CIM_UINT8)
        self.assertEqual(p["hDefKey"], w.CIM_UINT32)
        self.assertFalse(self.reg.has_method("StdRegProv", "YokBoyleBirYontem"))
        with self.assertRaises(w.WmiError):
            self.reg.call("StdRegProv", "StdRegProv", "YokBoyleBirYontem", {})

    def test_query_and_class(self):
        rows = self.cim.query("SELECT * FROM Win32_ComputerSystem", ["Manufacturer", "__PATH"])
        self.assertEqual(len(rows), 1)
        self.assertIn("Win32_ComputerSystem", rows[0]["__PATH"])
        self.assertTrue(self.cim.class_exists("Win32_ComputerSystem"))
        self.assertFalse(self.cim.class_exists("AcerGamingFunctionYok"))


if __name__ == "__main__":
    unittest.main()
