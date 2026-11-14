# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""MSI oyun dizustuleri: gomulu denetleyici (EC) ayarlari, MSI_ACPI WMI sinifi uzerinden.

Cekirdek surucusu (WinRing0 vb.) KURULMAZ: EC'ye yalnizca MSI'in kendi ACPI-WMI koprusu (root\\WMI,
MSI_ACPI) ile ulasilir. Tasima katmani msi_wmi.py'dedir; bu dosya "hangi adrese ne yazilir" ve guvenlik
kurallaridir. Tasima: fw() -> EC firmware metni (Get_EC), read(adres) -> bayt (Get_Data),
write(adres, deger) (Set_Data), fan_rpm() -> [devir, ...] (Get_Fan).

EC adresleri ve degerleri EC firmware'ine gore degisir. Tablo, Linux msi-ec surucusunun (BeardOverflow/msi-ec)
firmware tablolarindaki ADRES/DEGER bilgisinden derlenmistir; kod alinmamistir.

Guvenlik kurallari (EC'ye yanlis deger yazmak fanlari durdurabilir, pili bozabilir):
  1. Firmware Get_EC ile okunur; ilk 10 karakteri tablodaki bir girdiyle BIREBIR eslesmezse hicbir yazma
     yapilmaz. Yalnizca okuma (sicaklik, fan) calisir; arayuzde yazma denetimleri gizlenir.
  2. Get_Data'nin gercekten ham EC adresi okudugu dogrulanir: EC 0xA0..0xAB (firmware alani) Get_Data ile
     okunur ve Get_EC'nin verdigi metinle ayni olmalidir. Tutmazsa tasima katmanini anlamiyoruz demektir:
     yazma kapali, EC'den okunan degerler de kullanilmaz.
  3. Yazilabilecek adresler ve degerler yalnizca tablodakilerdir; bit alanlarinda (Cooler Boost) yalnizca o bit
     degistirilir, digerleri okunan haliyle geri yazilir.
  4. Her yazmadan sonra adres geri okunur; tutmazsa o oturumda TUM yazmalar kapanir.
  5. Pil esigi msi-ec gibi yalnizca acilista esik biti (bit 7) acik bulunursa yazilir.
"""
import re
import threading

import ceviri

# Clevo kodlariyla ortak arayuz (donanim.DCHU ile ayni adlar): profiller ve tepsi ayni cagrilari yapar.
FAN_AUTO, FAN_MAX, FAN_CUSTOM = 0, 1, 6

FW_ADDR, FW_LEN = 0xA0, 12
FW_RE = re.compile(r"^[0-9A-Z]{4}[A-Z]{3}[0-9A-Z]\.[0-9A-Z]$")  # ilk 10 karakter, ornek: 17F2EMS1.1
CPU_TEMP, CPU_FAN = 0x68, 0x71          # bilinen tum firmware'lerde ayni (okuma)
GPU_TEMP_DEFAULT, GPU_FAN_DEFAULT = 0x80, 0x89

# ----------------------------------------------------------------------------- firmware tablosu
# Iki kusak: adresler kusaga gore, desteklenen modlar firmware grubuna gore degisir.
_G1 = {"charge": 0xEF, "cooler": (0x98, 7), "shift_addr": 0xF2, "fan_addr": 0xF4,
       "gpu_temp": 0x80, "gpu_fan": 0x89}
_G2 = {"charge": 0xD7, "cooler": (0x98, 7), "shift_addr": 0xD2, "fan_addr": 0xD4,
       "gpu_temp": 0x80, "gpu_fan": 0x89}
SH_ALL = {"eco": 0xC2, "comfort": 0xC1, "sport": 0xC0, "turbo": 0xC4}
SH_NOSPORT = {"eco": 0xC2, "comfort": 0xC1, "turbo": 0xC4}
SH_NOTURBO = {"eco": 0xC2, "comfort": 0xC1, "sport": 0xC0}
FM_ALL = {"auto": 0x0D, "silent": 0x1D, "basic": 0x4D, "advanced": 0x8D}
FM_SA = {"auto": 0x0D, "silent": 0x1D, "advanced": 0x8D}
FM_BA = {"auto": 0x0D, "basic": 0x4D, "advanced": 0x8D}


def _conf(name, gen, fws, shift, fan, **over):
    c = dict(gen)
    c.update(name=name, fw=tuple(fws), shift=shift, fan=fan)
    c.update(over)
    return c


CONFS = [
    _conf("G1_0", _G1, ["14C1EMS1.0", "14C1EMS1.1", "16S3EMS1.1"], SH_ALL, FM_ALL),
    _conf("G1_1", _G1, ["16U7EMS1.1", "16U7EMS1.5", "17E7EMS1.1", "17E8EMS1.1", "17F2EMS1.1", "17F3EMS1.1",
                        "17F3EMS2.1", "17F4EMS1.1", "17F4EMS2.1", "17F5EMS1.1", "17F6EMS1.1"], SH_ALL, FM_BA),
    _conf("G1_2", _G1, ["158LEMS1.1", "15CKEMS1.1", "17LLEMS1.1"], SH_NOSPORT, FM_SA),
    _conf("G1_3", _G1, ["1541EMS1.1", "1542EMS1.1", "16Q2EMS1.1", "16Q2EMS1.T", "16Q3EMS1.1", "16Q4EMS1.1",
                        "16V1EMS1.1", "16V3EMS1.1", "17K2EMS1.1"], SH_ALL, FM_SA),
    _conf("G1_4", _G1, ["16JFEMS1.1", "17FKEMS1.1"], SH_ALL, FM_SA),
    _conf("G1_5", _G1, ["14JKEMS1.1", "14JKEMS1.3", "14JKEMS1.5", "14JKEMS1.6", "1551EMS1.1"], SH_NOTURBO, FM_SA,
          gpu_temp=None, gpu_fan=None),
    _conf("G1_6", _G1, ["14D1EMS1.1", "14DKEMS1.1", "14DLEMS1.1", "155LEMS1.1", "15HKEMS1.1", "15HKEMS1.5"],
          SH_NOTURBO, FM_SA, gpu_temp=None, gpu_fan=None),
    _conf("G1_7", _G1, ["16R1EMS1.1", "16R3EMS1.1", "16R4EMS1.1", "16R4EMS2.1", "16R5EMS1.1", "16W1EMS1.1",
                        "16W1EMS2.1", "16W2EMS1.1"], SH_ALL, FM_ALL),
    _conf("G1_8", _G1, ["16S1EMS1.1", "16WKEMS1.1"], SH_NOSPORT, FM_SA),
    _conf("G1_9", _G1, ["17E9EMS1.1", "17G1EMS1.1", "17G1EMS2.1", "17G3EMS1.1", "17H1EMS1.1"], SH_ALL, FM_BA),
    _conf("G1_10", _G1, ["16P5EMS1.1", "1782EMS1.1", "1799EMS1.1"], SH_NOTURBO,
          {"auto": 0x0C, "basic": 0x4C, "advanced": 0x8C}, charge=None),
    _conf("G1_11", _G1, ["158KEMS1.1", "158MEMS1.1"], SH_NOSPORT, FM_SA),
    _conf("G1_13", _G1, ["16V2EMS1.1"], SH_NOTURBO, FM_SA),
    _conf("G2_0", _G2, ["14D2EMS1.1", "14D3EMS1.1", "1552EMS1.1", "159KIMS1.1", "15H1IMS1.2", "15H4IMS1.1",
                        "15H5EMS1.1"], SH_NOSPORT, FM_SA, gpu_temp=None, gpu_fan=None),
    _conf("G2_1", _G2, ["14C4EMS1.1", "14C6EMS1.1", "1581EMS1.1", "1582EMS1.1", "1583EMS1.1", "1584EMS1.1",
                        "1584IMS1.1", "1585EMS1.1", "1585EMS2.1", "158NIMS1.1", "158NIMS1.3", "158PIMS1.1",
                        "158PIMS1.2", "1591EMS1.1", "1592EMS1.1", "1594EMS1.1", "1596EMS1.1", "15H2IMS1.1",
                        "15K1IMS1.1", "16S6EMS1.1", "16S8EMS1.1", "16V6EMS1.1", "17L1EMS1.1", "17L2EMS1.1",
                        "17L3EMS1.1", "17L4EMS1.1", "17LNIMS1.1", "17LNIMS1.5", "17M1EMS2.1"], SH_NOSPORT, FM_SA),
    _conf("G2_2", _G2, ["1543EMS1.1", "1544EMS1.1", "1545IMS1.1", "16V4EMS1.1", "16V4EMS2.1", "16V5EMS1.1",
                        "17K3EMS1.1", "17K4EMS1.1", "17K5IMS1.1", "17KKIMS1.1", "17M1EMS1.1"], SH_NOSPORT, FM_SA),
    _conf("G2_3", _G2, ["13P3EMS1.1", "13P3EMS1.5", "13P5EMS1.1", "13Q2EMS1.1", "13Q3EMS1.1", "14F1EMS1.1",
                        "14F1EMS1.2", "14J1IMS1.1", "14J1IMS1.2", "14L1EMS1.3", "14N1EMS1.1", "14N1EMS1.3",
                        "14Q2EMS1.3", "14QKIMS1.1", "14T2EMS1.1", "15A1EMS1.1", "15A3EMS1.1", "15QKIMS1.5"],
          SH_NOSPORT, FM_SA, gpu_temp=None, gpu_fan=None),
    _conf("G2_4", _G2, ["14N2EMS1.1", "14P1IMS1.1"], SH_NOSPORT, FM_SA),
    _conf("G2_5", _G2, ["14K1EMS1.1", "14K2EMS1.1", "15Q3EMS1.1"], SH_NOSPORT, FM_SA),
    _conf("G2_6", _G2, ["16R6EMS1.1", "16R7IMS1.0", "16R7IMS1.1", "16R8IMS1.1", "16R8IMS2.1", "16RKIMS1.1",
                        "16RKIMS2.1"], SH_NOSPORT, FM_SA),
    _conf("G2_10", _G2, ["1562EMS1.1", "1563EMS1.1", "1571EMS1.1", "1572EMS1.1", "1587EMS1.1", "158NIMS1.5",
                         "15B1EMS1.1", "15F2EMS1.1", "15F3EMS1.1", "15F4EMS1.1", "15F5EMS1.1", "15FKIMS1.1",
                         "15FLIMS1.1", "15FMIBA1.1", "15G2EWS1.1", "15K2EMS1.1", "15M1IMS1.1", "15M1IMS2.1",
                         "15M2IMS1.1", "15M2IMS2.1", "15M3EMS1.1", "15P2EMS1.1", "15P3EMS1.1", "15P4EMS1.1",
                         "17L5EMS1.1", "17L5EMS2.1", "17L7EMS1.1", "17N1EMS1.1", "17P1EMS1.1", "17P2EMS1.1",
                         "17Q1IMS1.1", "17Q2IMS1.1", "17S1IMS1.1", "17S1IMS2.1", "17S2IMS1.1", "17S3EMS1.1",
                         "17T2EMS1.1", "1822EMS1.1", "1824EMS1.1", "182KIMS1.1", "182LIMS1.1"], SH_NOSPORT, FM_SA),
]
BY_FW = {fw: c for c in CONFS for fw in c["fw"]}
SHIFT_IDS = ("eco", "comfort", "sport", "turbo")
FAN_IDS = ("auto", "silent", "basic", "advanced")
CHARGE_STEPS = (50, 60, 70, 80, 90, 100)

# Clevo guc modu kodlari (profiller.PROFILES "ec") -> MSI shift modu tercih sirasi
POWER_TO_SHIFT = {0: ("eco",), 1: ("eco",), 2: ("turbo", "sport", "comfort"), 3: ("comfort",)}
SHIFT_TO_POWER = {"eco": 0, "comfort": 3, "sport": 2, "turbo": 2}


def lookup(fw):
    """Firmware metninin ilk 10 karakteri bilinen bir tabloyla birebir eslesirse o tablo, yoksa None."""
    fw = (fw or "").strip()
    return BY_FW.get(fw[:10]) if len(fw) >= 10 else None


class Unsupported(RuntimeError):
    """Bu bilgisayarda olmayan ozellik. donanim, kendi Unsupported sinifini verir (profil raporunda 'atlandi')."""


class EcWriteError(RuntimeError):
    pass


def _clean(raw):
    return bytes(raw).split(b"\0", 1)[0].decode("ascii", "replace").strip()


# ----------------------------------------------------------------------------- denetleyici
class MsiEC:
    """donanim.DCHU ile ayni arayuz (available, status, power_mode, set_fan_mode...) + MSI'a ozel ayarlar.

    available = EC'ye YAZMA izni var mi (bilinen ve dogrulanmis firmware). Okumalar (sicaklik, fan) bilinmeyen
    firmware'de de calisir. Klavye isigi ayri bir USB aygitidir (msi_klavye): set_color oraya iletilir."""
    kind = "msi"
    clevo = False

    def __init__(self, ec=None, keyboard=None, unsupported=Unsupported):
        self.ec = ec                    # tasima (msi_wmi.MsiWmi) ya da None: MSI_ACPI yok
        self.kb = keyboard              # msi_klavye.open_keyboard() ya da None
        self._unsup = unsupported
        self.lock = threading.RLock()
        self.fw = ""
        self.conf = None
        self.read_ok = False            # Get_Data ham EC okuyor (dogrulandi)
        self.write_ok = False
        self.charge_ok = False
        self.rpm_ok = False
        self.reason = ""
        if ec is not None:
            try:
                self._probe()
            except Exception as exc:
                self.read_ok = self.write_ok = False
                self.reason = ceviri.t("msi.readFail", err=exc)
        else:
            self.reason = ceviri.t("msi.noWmi")
        self.path = "MSI_ACPI" if self.read_ok else ""

    # ------------------------------------------------------------------ tespit
    def _probe(self):
        self.fw = _clean(self.ec.fw() or b"")
        if not FW_RE.match(self.fw[:10]):
            self.reason = ceviri.t("msi.badFw", fw=self.fw[:16] or "?")
            return
        try:  # Get_Data gercekten ham EC adresi mi okuyor? Firmware alani ayni metni vermeli.
            mirror = _clean(self.ec.read(FW_ADDR + i) & 0xFF for i in range(FW_LEN))
        except Exception as exc:
            self.reason = ceviri.t("msi.readFail", err=exc)
            return
        if mirror[:10] != self.fw[:10]:
            self.reason = ceviri.t("msi.mirror", a=self.fw, b=mirror or "?")
            return
        self.read_ok = True
        try:
            self.rpm_ok = bool(self.ec.fan_rpm() is not None)
        except Exception:
            self.rpm_ok = False
        self.conf = lookup(self.fw)
        if self.conf is None:
            self.reason = ceviri.t("msi.unknownFw", fw=self.fw)
            return
        self.write_ok = True
        addr = self.conf.get("charge")
        if addr is not None:
            try:  # msi-ec gibi: esik biti acilista acik degilse pil esigine hic dokunulmaz
                self.charge_ok = bool(self._read(addr) & 0x80)
            except Exception:
                self.charge_ok = False

    @property
    def available(self):
        return self.write_ok

    @property
    def kb_available(self):
        return bool(self.kb is not None and getattr(self.kb, "ok", False))

    def caps(self):
        c = self.conf or {}
        w = self.write_ok
        return {"power": bool(w and c.get("shift")), "fan": w, "fan_curve": False,
                "kb": self.kb_available, "temps": self.read_ok}

    # ------------------------------------------------------------------ ham erisim (yalnizca bu sinif)
    def _read(self, addr):
        with self.lock:
            return self.ec.read(addr) & 0xFF

    def _write(self, addr, value):
        """Tek yazma noktasi: izin, tablo ve geri okuma denetimi."""
        if not self.write_ok:
            raise self._unsup(self.reason or ceviri.t("msi.readOnly"))
        value &= 0xFF
        with self.lock:
            self.ec.write(addr, value)
            back = self.ec.read(addr) & 0xFF
            if back != value:
                self.write_ok = False
                self.reason = ceviri.t("msi.verifyFail", addr="0x%02X" % addr, want="0x%02X" % value,
                                       got="0x%02X" % back)
                raise EcWriteError(self.reason)

    def _need(self, key):
        if not self.write_ok:
            raise self._unsup(self.reason or ceviri.t("msi.readOnly"))
        v = (self.conf or {}).get(key)
        if not v:
            raise self._unsup(ceviri.t("msi.noFeature"))
        return v

    # ------------------------------------------------------------------ MSI ayarlari
    def shift_mode(self):
        if not self.read_ok or not self.conf:
            return None
        raw = self._read(self.conf["shift_addr"])
        return next((k for k, v in self.conf["shift"].items() if v == raw), None)

    def set_shift_mode(self, mode):
        modes = self._need("shift")
        if mode not in modes:
            raise self._unsup(ceviri.t("msi.noMode", mode=mode))
        self._write(self.conf["shift_addr"], modes[mode])

    def msi_fan_mode(self):
        if not self.read_ok or not self.conf:
            return None
        raw = self._read(self.conf["fan_addr"])
        return next((k for k, v in self.conf["fan"].items() if v == raw), None)

    def set_msi_fan_mode(self, mode):
        modes = self._need("fan")
        if mode not in modes:
            raise self._unsup(ceviri.t("msi.noMode", mode=mode))
        self._write(self.conf["fan_addr"], modes[mode])

    def cooler_boost(self):
        if not self.read_ok or not self.conf or not self.conf.get("cooler"):
            return None
        addr, bit = self.conf["cooler"]
        return bool(self._read(addr) >> bit & 1)

    def set_cooler_boost(self, on):
        addr, bit = self._need("cooler")
        with self.lock:
            cur = self._read(addr)
            new = (cur | (1 << bit)) if on else (cur & ~(1 << bit) & 0xFF)
            if new != cur:
                self._write(addr, new)

    def charge_limit(self):
        addr = (self.conf or {}).get("charge")
        if not self.read_ok or addr is None or not self.charge_ok:
            return None
        v = self._read(addr) & 0x7F
        return v if 10 <= v <= 100 else None

    def set_charge_limit(self, pct):
        addr = self._need("charge")
        if not self.charge_ok:
            raise self._unsup(ceviri.t("msi.noCharge"))
        try:
            pct = int(pct)
        except (TypeError, ValueError):
            pct = -1
        if pct not in CHARGE_STEPS:
            raise ValueError(ceviri.t("msi.badCharge"))
        self._write(addr, pct | 0x80)

    def msi_state(self):
        """Arayuz icin: firmware, desteklenen secenekler ve su anki degerler."""
        c = self.conf or {}
        w = self.write_ok
        out = {"fw": self.fw, "known": self.conf is not None, "write": w, "read": self.read_ok,
               "reason": self.reason, "conf": c.get("name", ""),
               "shifts": [k for k in SHIFT_IDS if k in (c.get("shift") or {})] if w else [],
               "fans": [k for k in FAN_IDS if k in (c.get("fan") or {})] if w else [],
               "cooler": bool(w and c.get("cooler")),
               "charge_steps": list(CHARGE_STEPS) if w and self.charge_ok else [],
               "kb": self.kb_available, "kb_name": getattr(self.kb, "name", "") if self.kb_available else ""}
        try:
            out.update(shift=self.shift_mode(), fan=self.msi_fan_mode(), boost=self.cooler_boost(),
                       charge=self.charge_limit())
        except Exception as exc:
            out["error"] = str(exc)
        return out

    def msi_set(self, key, value):
        if key == "shift":
            self.set_shift_mode(str(value))
        elif key == "fan":
            self.set_msi_fan_mode(str(value))
        elif key == "boost":
            self.set_cooler_boost(bool(value))
        elif key == "charge":
            self.set_charge_limit(value)
        else:
            raise ValueError(ceviri.t("err.action"))

    # ------------------------------------------------------------------ DCHU ile ortak arayuz
    def set_color(self, r, g, b):
        if self.kb_available:
            return self.kb.set_color(r, g, b)
        return 0

    def _temp(self, addr):
        if addr is None:
            return None
        v = self._read(addr)
        return v if 1 <= v <= 115 else None  # 0 / 0xFF: sensor yok ya da okunamadi

    def _duty(self, addr):
        if addr is None:
            return None
        v = self._read(addr)
        return v if v <= 100 else None

    def status(self):
        if not self.read_ok:
            return {}
        c = self.conf
        gt = c.get("gpu_temp") if c else GPU_TEMP_DEFAULT
        gf = c.get("gpu_fan") if c else GPU_FAN_DEFAULT
        out = {}
        for key, fn, addr in (("cpu_temp", self._temp, CPU_TEMP), ("gpu_temp", self._temp, gt),
                              ("cpu_duty", self._duty, CPU_FAN), ("gpu_duty", self._duty, gf)):
            v = fn(addr)
            if v is not None:
                out[key] = v
        if self.rpm_ok:
            try:
                rpm = self.ec.fan_rpm() or []
                if len(rpm) > 0:
                    out["cpu_rpm"] = rpm[0]
                if len(rpm) > 1 and gf is not None:
                    out["gpu_rpm"] = rpm[1]
            except Exception:
                pass
        return out

    def temps(self):
        s = self.status()
        return s.get("cpu_temp", 0), s.get("gpu_temp", 0)

    def power_mode(self):
        return SHIFT_TO_POWER.get(self.shift_mode()) if self.write_ok else None

    def set_power_mode(self, mode):
        modes = self._need("shift")
        for name in POWER_TO_SHIFT.get(mode, ()):
            if name in modes:
                self._write(self.conf["shift_addr"], modes[name])
                return name
        raise self._unsup(ceviri.t("msi.noFeature"))

    def fan_mode(self):
        if not self.write_ok:
            return None
        if self.cooler_boost():
            return FAN_MAX
        return FAN_AUTO if self.msi_fan_mode() == "auto" else FAN_CUSTOM

    def set_fan_mode(self, mode):
        if mode == FAN_MAX:
            self.set_cooler_boost(True)
            return
        if mode == FAN_AUTO:
            if self.write_ok and self.conf.get("cooler"):
                self.set_cooler_boost(False)
            self.set_msi_fan_mode("auto")
            return
        raise self._unsup(ceviri.t("msi.noCurve"))

    def fan_default(self):
        return None  # MSI EC'de okunabilir fabrika egrisi yok: arayuz egri cizmez

    def set_fan_curve(self, cpu, gpu):
        """MSI EC ozel egri tablosu YAZILMAZ (msi-ec de yazmaz, adresleri modele gore degisir). Profilin egrisi
        en yakin MSI fan moduna cevrilir: sessiz egri (son noktada en fazla %60) -> Silent, digerleri -> Auto."""
        modes = self._need("fan")
        quiet = int(cpu[3]) <= 60 and int(gpu[3]) <= 60
        name = "silent" if quiet and "silent" in modes else "auto"
        if self.conf.get("cooler"):
            self.set_cooler_boost(False)
        self.set_msi_fan_mode(name)
        return ceviri.t("msi.curveAs", mode=ceviri.t("msi.fan." + name))

    def set_wmi(self, *a, **k):  # Clevo komutlari MSI'a asla gitmez
        raise self._unsup(ceviri.t("err.notClevo"))

    set_data = write_app = set_wmi

    def close(self):
        for x in (self.ec, self.kb):
            try:
                x and x.close()
            except Exception:
                pass


# ----------------------------------------------------------------------------- tespit
def manufacturer():
    """SMBIOS uretici adi: Win32_ComputerSystem.Manufacturer ile ayni kaynak, WMI sorgusu olmadan okunur."""
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\BIOS")
        try:
            return str(winreg.QueryValueEx(k, "SystemManufacturer")[0])
        finally:
            winreg.CloseKey(k)
    except OSError:
        return ""


def is_msi(maker=None):
    m = (manufacturer() if maker is None else maker).strip().lower()
    return m.startswith("micro-star") or m in ("msi", "msi co., ltd")


def open_msi(unsupported=Unsupported, maker=None, wmi_factory=None, kb_factory=None):
    """MSI ise MsiEC, degilse None. MSI_ACPI sinifi yoksa EC'siz (yalnizca klavye olabilir) bir MsiEC doner."""
    if not is_msi(maker):
        return None
    ec = None
    try:
        if wmi_factory is None:
            import msi_wmi
            wmi_factory = msi_wmi.open_wmi
        ec = wmi_factory()  # MSI_ACPI yoksa None
    except Exception:
        ec = None
    kb = None
    try:
        if kb_factory is None:
            import msi_klavye
            kb_factory = msi_klavye.open_keyboard
        kb = kb_factory()
    except Exception:
        kb = None
    return MsiEC(ec, kb, unsupported)
