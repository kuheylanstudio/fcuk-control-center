# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""Gigabyte / AORUS / AERO dizustuleri: ACPI-WMI (GB_WMIACPI_Get / GB_WMIACPI_Set) ve ITE 829x klavye isigi.

donanim.DCHU ile ayni arayuzu sunar (status, temps, power_mode, set_power_mode, fan_mode, set_fan_mode,
set_fan_curve, set_color); uygulamanin geri kalani hangi ureticide oldugunu bilmeden calisir.

Protokol bilgisi acik kaynak projelerden dogrulandi (kod alinmadi, yalnizca yontem adlari ve degerler):
  - Linux tangalbert919/gigabyte-laptop-wmi (aorus-laptop.c, USAGE.md): yontem kimlikleri, kip bitleri,
    0-229 fan olcegi, 60-100 sarj siniri, devir baytlarinin ters sirasi
  - cabal95/aeroctl (AeroWmi.cs, P75FanController.cs, Ite829XRgbController.cs): Windows sinif/parametre
    adlari, fan kiplerinin bilesimi, klavye ozellik raporu
  - yurii-sio2/alfc MOF dokumu: yontem ve parametre adlari (GetFanIndexValue'daki "Temperture" yazimi dahil)
  - OpenRGB GigabyteAorusLaptopController: klavye VID/PID'leri ve dogrudan renk komutu

Fan kipleri (Gigabyte Control Center'in yaptigi gibi; "normal" hepsinin temizlenmesidir):
  sessiz  : SetNvThermalTarget=1 (eski modellerde SetSmartCool=1)
  normal  : tum kip bitleri 0
  oyun    : SetAutoFanStatus=1
  sabit   : SetStepFanStatus=1, SetFixedFanStatus=1, SetFixedFanSpeed=hiz (0-229), SetGPUFanDuty=hiz
  egri    : SetStepFanStatus=1, 15 nokta SetFanIndexValue(Index, Temperture, Value); egriyi EC calistirir

GUVENLIK: bir yontem MOF'ta yoksa hic cagrilmaz (yalnizca imzasi okunur). Desteklenmeyen ozellik
donanim.Unsupported verir ve hicbir yazma yapmaz. Her yazmadan sonra okunabilen durum geri okunur.
"""
import threading
import time

import ceviri
import donanim as hw

GET_CLASS, SET_CLASS = "GB_WMIACPI_Get", "GB_WMIACPI_Set"
FAN_SCALE = 229          # fan gorevi bayti: 229 = %100
CURVE_POINTS = 15        # SetFanIndexValue: 0..14
CHARGE_MIN, CHARGE_MAX = 60, 100
POLICY_FULL, POLICY_CUSTOM = 0, 4
FIXED_MIN = 30           # sabit hizda en az %30: isi korumasi yalnizca bu uygulamada

# Uygulamanin guc modlari (donanim.POWER_MODES, Clevo sirasi) -> Gigabyte fan kipi
GB_QUIET, GB_NORMAL, GB_GAMING = "quiet", "normal", "gaming"
POWER_TO_GB = {0: GB_QUIET, 1: GB_QUIET, 2: GB_GAMING, 3: GB_NORMAL}

# Devir baytlari bu ailelerde duz sirada, digerlerinde ters (Linux surucusunun DMI listesi)
RPM_NATIVE_FAMILIES = ("GIGABYTE GAMING", "GIGABYTE AERO")
MAKERS = ("GIGABYTE", "AORUS")

# ITE 829x klavye denetleyicisi: (VID, PID). Ozel kullanim sayfasi 0xFF01, kullanim 1, 9 baytlik ozellik raporu.
KB_IDS = frozenset([(0x1044, pid) for pid in range(0x7A38, 0x7A40)] +
                   [(0x0414, pid) for pid in (0x7A3F, 0x7A42, 0x7A43, 0x7A44)])
KB_USAGE_PAGE, KB_USAGE, KB_REPORT_LEN = 0xFF01, 0x0001, 9
KB_BRIGHT_MAX = 0x32


# ============================================================================= tespit
def _bios_values():
    """SMBIOS uretici/aile/model (Win32_ComputerSystem ile ayni kaynak, kayit defterinden hizli)."""
    out = {}
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\BIOS")
        try:
            for name in ("SystemManufacturer", "BaseBoardManufacturer", "SystemFamily", "SystemProductName"):
                try:
                    out[name] = str(winreg.QueryValueEx(k, name)[0] or "").strip()
                except OSError:
                    out[name] = ""
        finally:
            winreg.CloseKey(k)
    except (OSError, ImportError):
        pass
    return out


def is_gigabyte(bios):
    """Uretici GIGABYTE ya da AORUS mu (sistem veya anakart)?"""
    for key in ("SystemManufacturer", "BaseBoardManufacturer"):
        v = (bios.get(key) or "").upper()
        if any(m in v for m in MAKERS):
            return True
    return False


def wmi_path(cls, instance):
    """WMI nesne yolu; anahtar degerindeki ters bolu ve tirnak kacirilir."""
    return '%s.InstanceName="%s"' % (cls, instance.replace("\\", "\\\\").replace('"', '\\"'))


# ============================================================================= klavye
def kb_report(cmd, p2=0, p3=0, p4=0, p5=0, p6=0, p7=0):
    """9 baytlik ozellik raporu: [0]=rapor kimligi 0, [1]=komut, [2..7]=parametre, [8]=0xFF-toplam."""
    b = bytearray([0, cmd & 0xFF, p2 & 0xFF, p3 & 0xFF, p4 & 0xFF, p5 & 0xFF, p6 & 0xFF, p7 & 0xFF, 0])
    b[8] = (0xFF - sum(b[:8])) & 0xFF
    return bytes(b)


def kb_color_report(r, g, b, brightness=KB_BRIGHT_MAX):
    """Tek renk (tum tuslar): komut 0x08, alt komut 0x01, R, G, B, parlaklik 0..0x32."""
    return kb_report(0x08, 0x01, r, g, b, max(0, min(KB_BRIGHT_MAX, brightness)), 0)


def kb_match(vid, pid, usage_page, usage, feature_len):
    return (vid, pid) in KB_IDS and usage_page == KB_USAGE_PAGE and usage == KB_USAGE \
        and feature_len >= KB_REPORT_LEN


class AorusKeyboard:
    """ITE 829x klavye isigi. Motor saniyede ~30 kare yollar; HID'e en fazla 20 kare/sn gider."""
    MIN_INTERVAL = 0.05

    def __init__(self, dev):
        self.dev = dev
        self.lock = threading.Lock()
        self._last = None
        self._at = -10.0
        self.vid, self.pid = dev.vid, dev.pid

    def set_color(self, r, g, b):
        rgb = (int(r) & 255, int(g) & 255, int(b) & 255)
        now = time.monotonic()
        with self.lock:
            if rgb == self._last and now - self._at < 1.0:
                return 0
            if now - self._at < self.MIN_INTERVAL:
                return 0  # cok sik: motor en gec 1 sn icinde son rengi yeniden yollar
            self.dev.set_feature(kb_color_report(*rgb))  # OSError: motor hatayi arayuzde gosterir
            self._last, self._at = rgb, now
        return 0


def find_keyboard(hid_find=None):
    """Bilinen bir Aorus/Aero klavye denetleyicisi takili mi? (yazmaya acik HidDevice ya da None)"""
    if hid_find is None:
        import hid_rapor
        hid_find = hid_rapor.find
    dev = hid_find(kb_match)
    if dev is None:
        return None
    try:
        dev.open_rw()
    except OSError:
        dev.close()
        return None
    return dev


# ============================================================================= arka uc
class GigabyteError(RuntimeError):
    pass


class Gigabyte:
    """GB_WMIACPI uzerinden fan/kip/sicaklik/sarj, varsa ITE klavye. donanim.DCHU yerine gecer."""
    vendor = "gigabyte"
    path = "WMI root\\WMI GB_WMIACPI"
    clevo = False
    reason = ""

    def __init__(self, wmi, get_inst, set_inst, methods, family="", keyboard=None):
        """wmi: call(path, method, inargs, outnames) sunan istemci. methods: MOF'ta bulunan yontem adlari."""
        self.wmi = wmi
        self.get_path = wmi_path(GET_CLASS, get_inst)
        self.set_path = wmi_path(SET_CLASS, set_inst)
        self.methods = frozenset(methods)
        self.rpm_swap = (family or "").upper() not in RPM_NATIVE_FAMILIES
        self.kb = keyboard
        self.lock = threading.RLock()
        self._power = None   # son uygulanan guc modu (Clevo sirasi); kip bitlerinin hepsi okunamiyor
        self._fan = None     # FAN_AUTO / FAN_MAX / FAN_CUSTOM / FAN_FIXED
        self._fixed = None   # sabit yuzde
        m = self.methods
        caps = set()
        if "getCpuTemp" in m:
            caps.add("temps")
        quiet = "SetNvThermalTarget" in m or "SetSmartCool" in m
        if quiet and "SetAutoFanStatus" in m:
            caps.update(("power", "fan_auto"))
        if {"SetStepFanStatus", "SetFixedFanStatus", "SetFixedFanSpeed"} <= m:
            caps.update(("fan_fixed", "fan_max"))
        if {"SetStepFanStatus", "SetFanIndexValue"} <= m:
            caps.add("fan_curve")
        if {"SetChargePolicy", "SetChargeStop", "GetChargePolicy"} <= m:
            caps.add("charge")
        if keyboard is not None:
            caps.add("kb")
        self.caps = frozenset(caps)
        self.available = "fan_auto" in caps   # fan sayfasi ve guc modu
        self.kb_available = keyboard is not None

    # ------------------------------------------------------------------ ham cagrilar
    def _get(self, method):
        if method not in self.methods:
            raise hw.Unsupported(ceviri.t("err.gbNoMethod", m=method))
        with self.lock:
            out = self.wmi.call(self.get_path, method, None, ("Data",))
        v = (out or {}).get("Data")
        if isinstance(v, bool) or not isinstance(v, int):
            raise GigabyteError(ceviri.t("err.gbBadReply", m=method))
        return v

    def _set(self, method, value=None, **kw):
        if method not in self.methods:
            raise hw.Unsupported(ceviri.t("err.gbNoMethod", m=method))
        args = dict(kw)
        if value is not None:
            args["Data"] = int(value)
        for k, v in args.items():
            if not 0 <= int(v) <= 0xFF:  # tum giris parametreleri uint8
                raise ValueError("%s=%r" % (k, v))
        with self.lock:
            out = self.wmi.call(self.set_path, method, args, ("DataOut",))
        if out is None:
            raise GigabyteError(ceviri.t("err.gbBadReply", m=method))
        return out

    def _set_checked(self, method, value, getter=None):
        """Yazar; ayni ayarin Get yontemi varsa geri okuyup karsilastirir."""
        self._set(method, value)
        if getter and getter in self.methods:
            got = self._get(getter)
            if got != value:
                raise GigabyteError(ceviri.t("err.gbVerify", m=method, want=value, got=got))

    def _opt(self, method, value):
        """Modelde varsa yazar (kip bitlerini temizlerken: eski/yeni modellerin farkli yontemleri)."""
        if method in self.methods:
            self._set(method, value)

    # ------------------------------------------------------------------ olcumler
    def _rpm(self, method):
        v = self._get(method) & 0xFFFF
        swapped = ((v & 0xFF) << 8) | (v >> 8)
        rpm, alt = (swapped, v) if self.rpm_swap else (v, swapped)
        if rpm > 12000 >= alt:  # aile listesi eksikse: akla yatkin olani sec
            rpm = alt
        return rpm

    def status(self):
        s = {}
        if "getCpuTemp" in self.methods:
            s["cpu_temp"] = self._get("getCpuTemp") & 0xFF
        if "getGpuTemp1" in self.methods:
            s["gpu_temp"] = self._get("getGpuTemp1") & 0xFF
        for key, m in (("cpu_rpm", "getRpm1"), ("gpu_rpm", "getRpm2")):
            if m in self.methods:
                s[key] = self._rpm(m)
        for key, m in (("cpu_duty", "GetCPUFanDuty"), ("gpu_duty", "GetGPUFanDuty")):
            if m in self.methods:
                s[key] = round(min(self._get(m), FAN_SCALE) * 100.0 / FAN_SCALE)
        return s

    def temps(self):
        s = self.status()
        return s.get("cpu_temp", 0), s.get("gpu_temp", 0)

    # ------------------------------------------------------------------ kip
    def power_mode(self):
        return self._power

    @staticmethod
    def power_key(mode):
        """Arayuz metni: Gigabyte'ta guc modu fan kipidir (sessiz / normal / oyun)."""
        return "gbmode." + POWER_TO_GB.get(mode, GB_NORMAL)

    def _clear_manual(self):
        """Elle fan denetimini (sabit / egri / ayarli) kapatir: fanlar yeniden secili kipin tablosunda."""
        self._opt("SetFixedFanStatus", 0)
        self._opt("SetFanAdjustStatus", 0)
        self._opt("SetStepFanStatus", 0)

    def _apply_gb_mode(self, gb):
        quiet = 1 if gb == GB_QUIET else 0
        self._clear_manual()
        if "SetNvThermalTarget" in self.methods:
            self._set("SetNvThermalTarget", quiet)
        elif "SetSmartCool" in self.methods:
            self._set("SetSmartCool", quiet)
        self._set_checked("SetAutoFanStatus", 1 if gb == GB_GAMING else 0, "GetAutoFanStatus")
        for getter in ("GetFixedFanStatus", "GetStepFanStatus"):
            if getter in self.methods:
                got = self._get(getter)
                if got != 0:
                    raise GigabyteError(ceviri.t("err.gbVerify", m=getter, want=0, got=got))

    def set_power_mode(self, mode):
        if "power" not in self.caps:
            raise hw.Unsupported(ceviri.t("err.gbNoFeature"))
        if mode not in hw.POWER_MODES:
            raise ValueError(ceviri.t("err.unknownPower"))
        with self.lock:
            self._apply_gb_mode(POWER_TO_GB[mode])
            self._power = mode
            self._fan, self._fixed = hw.FAN_AUTO, None

    # ------------------------------------------------------------------ fan
    def fan_mode(self):
        return self._fan

    def fan_fixed(self):
        return self._fixed

    def fan_default(self):
        return None  # fabrika egrisi WMI'den okunamiyor: arayuz egri grafigini gizler

    def set_fan_mode(self, mode):
        with self.lock:
            if mode == hw.FAN_AUTO:
                if "fan_auto" not in self.caps:
                    raise hw.Unsupported(ceviri.t("err.gbNoFeature"))
                self._apply_gb_mode(POWER_TO_GB.get(self._power, GB_NORMAL))
                self._fan, self._fixed = hw.FAN_AUTO, None
            elif mode == hw.FAN_MAX:
                self.set_fan_fixed(100)
                self._fan = hw.FAN_MAX
            else:
                raise hw.Unsupported(ceviri.t("err.fanMode"))

    def set_fan_fixed(self, percent):
        """Iki fan sabit yuzdede (en az %30)."""
        if "fan_fixed" not in self.caps:
            raise hw.Unsupported(ceviri.t("err.gbNoFeature"))
        pct = max(FIXED_MIN, min(100, int(percent)))
        duty = round(pct * FAN_SCALE / 100.0)
        with self.lock:
            self._opt("SetAutoFanStatus", 0)
            self._opt("SetFanAdjustStatus", 0)
            self._set_checked("SetStepFanStatus", 1, "GetStepFanStatus")
            self._set_checked("SetFixedFanStatus", 1, "GetFixedFanStatus")
            self._set_checked("SetFixedFanSpeed", duty, "GetFixedFanSpeed")
            self._opt("SetGPUFanDuty", duty)
            self._fan, self._fixed = hw.FAN_FIXED, pct

    @staticmethod
    def curve_points(cpu):
        """Uygulamanin 4 noktali egrisinden (T2, D2%, T3, D3%) 15 nokta: [(T C, gorev bayti 0-229)].
        Ilk nokta 40 C / %20, son nokta 100 C / %100 sabit; aradaki noktalar dogrusal, azalmayan."""
        t1, d1 = 40, 20
        t2, d2, t3, d3 = hw.validate_curve(cpu, t1, d1)
        knots = [(t1, d1), (t2, d2), (t3, d3), (100, 100)]
        # Kirilma noktalari her zaman noktalar arasinda (egrinin bicimi ve sicak bolge tabani aynen korunur);
        # kalan noktalar araliga esit dagitilir.
        temps = {t1, t2, t3, 100}
        i = 0
        while len(temps) < CURVE_POINTS:
            for j in range(1, 2 ** i + 1, 2):
                temps.add(round(t1 + (100 - t1) * j / 2.0 ** i))
                if len(temps) >= CURVE_POINTS:
                    break
            i += 1
        out = []
        for t in sorted(temps):
            d = 100
            for (ta, da), (tb, db) in zip(knots, knots[1:]):
                if ta <= t <= tb:
                    d = da + (db - da) * (t - ta) / float(tb - ta) if tb != ta else db
                    break
            out.append((t, round(max(0, min(100, d)) * FAN_SCALE / 100.0)))
        for i in range(1, len(out)):  # azalmayan (surucu kosulu)
            out[i] = (max(out[i][0], out[i - 1][0]), max(out[i][1], out[i - 1][1]))
        return out

    def set_fan_curve(self, cpu, gpu):
        """Gigabyte'ta tek egri iki fana uygulanir (islemci egrisi; ekran karti egrisi kullanilmaz).
        Egriyi EC calistirir; uygulama kapansa da gecerli kalir."""
        if "fan_curve" not in self.caps:
            raise hw.Unsupported(ceviri.t("err.gbNoFeature"))
        pts = self.curve_points(cpu)
        with self.lock:
            self._opt("SetAutoFanStatus", 0)
            self._opt("SetFixedFanStatus", 0)
            self._opt("SetFanAdjustStatus", 0)
            for i, (t, d) in enumerate(pts):
                self._set("SetFanIndexValue", None, Index=i, Temperture=t, Value=d)
            self._set_checked("SetStepFanStatus", 1, "GetStepFanStatus")
            self._fan, self._fixed = hw.FAN_CUSTOM, None

    # ------------------------------------------------------------------ pil
    def charge_limit(self):
        """{"enabled": bool, "stop": yuzde ya da None} ya da desteklenmiyorsa/okunamazsa None."""
        if "charge" not in self.caps:
            return None
        try:
            pol = self._get("GetChargePolicy")
            stop = self._get("GetChargeStop") if "GetChargeStop" in self.methods else None
        except Exception:
            return None
        if stop is not None and not CHARGE_MIN <= stop <= CHARGE_MAX:
            stop = None  # bazi modellerde GetChargeStop yazilan degeri yansitmiyor
        return {"enabled": pol == POLICY_CUSTOM, "stop": stop}

    def set_charge_limit(self, stop):
        """stop: 60-100 yuzde ya da None (sinirsiz, tam sarj)."""
        if "charge" not in self.caps:
            raise hw.Unsupported(ceviri.t("err.gbNoFeature"))
        with self.lock:
            if stop is None:
                self._set_checked("SetChargePolicy", POLICY_FULL, "GetChargePolicy")
                return
            stop = int(stop)
            if not CHARGE_MIN <= stop <= CHARGE_MAX:
                raise ValueError(ceviri.t("err.gbCharge", lo=CHARGE_MIN, hi=CHARGE_MAX))
            self._set_checked("SetChargePolicy", POLICY_CUSTOM, "GetChargePolicy")
            self._set("SetChargeStop", stop)

    # ------------------------------------------------------------------ klavye
    def set_color(self, r, g, b):
        if self.kb is None:
            return 0  # motor her karede cagirir: sessizce yok say, aygita hicbir sey gitmez
        return self.kb.set_color(r, g, b)

    # Clevo'ya ozel ham erisim: Gigabyte'ta asla gonderilmez
    def _no(self, *args, **kwargs):
        raise hw.Unsupported(ceviri.t("err.notClevo"))

    set_wmi = set_data = write_app = _no


# ============================================================================= acilis
WANTED_METHODS = (
    (GET_CLASS, ("getCpuTemp", "getGpuTemp1", "getRpm1", "getRpm2", "GetCPUFanDuty", "GetGPUFanDuty",
                 "GetFixedFanStatus", "GetFixedFanSpeed", "GetStepFanStatus", "GetAutoFanStatus",
                 "GetChargePolicy", "GetChargeStop")),
    (SET_CLASS, ("SetNvThermalTarget", "SetSmartCool", "SetAutoFanStatus", "SetStepFanStatus",
                 "SetFixedFanStatus", "SetFixedFanSpeed", "SetGPUFanDuty", "SetFanAdjustStatus",
                 "SetFanIndexValue", "SetChargePolicy", "SetChargeStop")),
)


def _first_instance(wmi, cls):
    items = [i for i in wmi.instances(cls) if i.get("InstanceName") and i.get("Active", True) is not False]
    return items[0]["InstanceName"] if items else None


def open_backend(bios=None, wmi_factory=None, hid_find=None):
    """Gigabyte/AORUS ise Gigabyte nesnesi, degilse None. Tespit sirasinda hicbir yontem CALISTIRILMAZ;
    yalnizca sinif, ornek ve yontem imzalari okunur."""
    bios = _bios_values() if bios is None else bios
    if not is_gigabyte(bios):
        return None
    if wmi_factory is None:
        import wmi_yontem
        wmi_factory = lambda: wmi_yontem.ComWmi("root\\WMI")  # noqa: E731
    wmi, get_inst, set_inst, methods = None, None, None, set()
    try:
        wmi = wmi_factory()
        if wmi.has_class(GET_CLASS) and wmi.has_class(SET_CLASS):
            get_inst, set_inst = _first_instance(wmi, GET_CLASS), _first_instance(wmi, SET_CLASS)
        if get_inst and set_inst:
            for cls, names in WANTED_METHODS:
                methods.update(n for n in names if wmi.has_method(cls, n))
    except Exception:
        get_inst = set_inst = None
        methods = set()
    kb = None
    try:
        dev = find_keyboard(hid_find)
        kb = AorusKeyboard(dev) if dev is not None else None
    except Exception:
        kb = None
    if not (get_inst and set_inst):
        if wmi is not None and hasattr(wmi, "close"):
            wmi.close()
        if kb is None:
            return None
        wmi, get_inst, set_inst, methods = None, "", "", set()  # yalnizca klavye: WMI'ye hic gidilmez
    return Gigabyte(wmi, get_inst, set_inst, methods, bios.get("SystemFamily", ""), kb)
