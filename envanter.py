# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""Donanim envanteri: bu bilgisayarda hangi islemci, ekran karti, bellek, disk, anakart ve pil var.

Hizli kisim (islemci cekirdek yapisi, ekran kartlari, disk saglik okumasi) dogrudan Windows API'leriyle,
yavas kisim (bellek modulleri, disk modelleri, BIOS, pil) tek bir PowerShell/CIM sorgusuyla, arka planda
bir kez toplanir. Hicbir sey ekran kartini uyandirmaz: NVIDIA ayrintilari nvidia.py'de, istenince okunur.
"""
import ctypes
import json
import re
import struct
import threading
import time
from ctypes import wintypes as wt

import donanim as hw

# ----------------------------------------------------------------------------- islemci modeli
# Intel aile 6 model numarasi -> (mimari adi, nesil). Nesil None ise addan okunur (Core Ultra).
INTEL_MODELS = {
    0x4E: ("Skylake", 6), 0x5E: ("Skylake", 6), 0x55: ("Skylake-X / Cascade Lake", 6),
    0x8E: ("Kaby / Coffee / Whiskey Lake", 8), 0x9E: ("Kaby / Coffee Lake", 8),
    0xA5: ("Comet Lake", 10), 0xA6: ("Comet Lake", 10), 0x7D: ("Ice Lake", 10), 0x7E: ("Ice Lake", 10),
    0x8C: ("Tiger Lake", 11), 0x8D: ("Tiger Lake", 11), 0xA7: ("Rocket Lake", 11),
    0x97: ("Alder Lake", 12), 0x9A: ("Alder Lake", 12), 0xBE: ("Alder Lake-N", 12),
    0xB7: ("Raptor Lake", 13), 0xBA: ("Raptor Lake", 13), 0xBF: ("Raptor Lake", 13),
    0xAA: ("Meteor Lake", None), 0xAC: ("Meteor Lake", None), 0xBD: ("Lunar Lake", None),
    0xC5: ("Arrow Lake", None), 0xC6: ("Arrow Lake", None), 0xB5: ("Arrow Lake", None),
    0xCC: ("Panther Lake", None),
}
MEM_TYPES = {20: "DDR", 21: "DDR2", 24: "DDR3", 26: "DDR4", 27: "LPDDR", 28: "LPDDR2", 29: "LPDDR3",
             30: "LPDDR4", 34: "DDR5", 35: "LPDDR5"}
FORM_FACTORS = {8: "DIMM", 12: "SODIMM", 0: "", 1: "", 2: "SIP", 13: "SRIMM", 23: "LGA"}


def _reg(path, name):
    import winreg
    try:
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path)
        try:
            return winreg.QueryValueEx(k, name)[0]
        finally:
            winreg.CloseKey(k)
    except OSError:
        return None


def cpu_sets():
    """Her mantiksal islemci icin (mantiksal no, fiziksel cekirdek no, verimlilik sinifi).
    Melez Intel islemcide sinif 1 = P (performans) cekirdek, 0 = E (verimlilik) cekirdek."""
    k32 = ctypes.WinDLL("kernel32")
    fn = k32.GetSystemCpuSetInformation
    fn.argtypes = [ctypes.c_void_p, wt.ULONG, ctypes.POINTER(wt.ULONG), wt.HANDLE, wt.ULONG]
    n = wt.ULONG()
    fn(None, 0, ctypes.byref(n), None, 0)
    if not n.value:
        return []
    buf = (ctypes.c_ubyte * n.value)()
    if not fn(buf, n, ctypes.byref(n), None, 0):
        return []
    b, o, out = bytes(buf), 0, []
    while o + 8 + 11 <= n.value:
        size = struct.unpack_from("<I", b, o)[0]
        if not size:
            break
        # CPU_SET: Id(4) Group(2) LogicalProcessorIndex(1) CoreIndex(1) LastLevelCacheIndex(1) NumaNodeIndex(1) EfficiencyClass(1)
        group = struct.unpack_from("<H", b, o + 12)[0]
        out.append((group * 64 + b[o + 14], group * 64 + b[o + 15], b[o + 18]))
        o += size
    return sorted(out)


def cpu_layout():
    """PDH cekirdek sirasiyla ayni sirada her mantiksal islemcinin etiketi: P1, P1, P2 ... E1, E2 ..."""
    sets = cpu_sets()
    classes = sorted({c for _, _, c in sets})
    hybrid = len(classes) > 1
    top = max(classes) if classes else 0
    seen, out = {}, []
    for lp, core, cls in sets:
        kind = ("P" if cls == top else "E") if hybrid else ""
        key = (kind, core)
        if key not in seen:
            seen[key] = sum(1 for k in seen if k[0] == kind) + 1
        thr = sum(1 for x in out if x["key"] == key)
        out.append({"key": key, "t": kind, "n": seen[key], "thr": thr})
    p = len({k for k in seen if k[0] == "P"})
    e = len({k for k in seen if k[0] == "E"})
    return {"hybrid": hybrid, "p_cores": p, "e_cores": e, "cores": len(seen), "threads": len(sets),
            "lps": [{"t": x["t"], "n": x["n"], "thr": x["thr"]} for x in out]}


def cpu_model():
    """Islemcinin adi, ureticisi, mimarisi, nesli ve bu modelde anlamli olan ozellikler."""
    base = r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
    name = re.sub(r"\s+", " ", (_reg(base, "ProcessorNameString") or "").strip())
    vendor_id = _reg(base, "VendorIdentifier") or ""
    ident = _reg(base, "Identifier") or ""  # "Intel64 Family 6 Model 154 Stepping 3"
    m = re.search(r"Family (\d+) Model (\d+) Stepping (\d+)", ident)
    family, model, stepping = (int(x) for x in m.groups()) if m else (0, 0, 0)
    vendor = "Intel" if "Intel" in vendor_id else "AMD" if "AMD" in vendor_id else vendor_id
    arch, gen = None, None
    if vendor == "Intel" and family == 6:
        arch, gen = INTEL_MODELS.get(model, (None, None))
    series = ""
    g = re.search(r"(\d+)(?:th|rd|nd|st) Gen", name)
    if g:
        gen = int(g.group(1))
    else:
        g = re.search(r"i[3579]-(\d{4,5})", name)
        if g:
            digits = g.group(1)
            gen = gen or (int(digits[:2]) if len(digits) == 5 else int(digits[0]))
    u = re.search(r"Ultra \d+ (\d)\d\d", name)
    if u:
        series = "Core Ultra seri %s" % u.group(1)
    suffix = ""
    s = re.search(r"\d{3,5}([A-Z]{1,3})\b", name)
    if s:
        suffix = s.group(1)
    # pazar kesimi (arayuz cevirir: seg.<kod>)
    segment = ("laptop_hp" if suffix.startswith("H") else
               "laptop_lp" if suffix[:1] in ("U", "P", "Y", "V") else
               "desktop" if suffix[:1] in ("K", "F", "S", "T") or (vendor == "Intel" and suffix == "") else "")
    lay = cpu_layout()
    hwp = vendor == "AMD" or (vendor == "Intel" and ((gen or 0) >= 6 or bool(series)))
    return {
        "name": name, "vendor": vendor, "family": family, "model": model, "stepping": stepping,
        "arch": arch or "", "gen": gen, "series": series, "suffix": suffix, "segment": segment,
        "base_mhz": hw.base_mhz(), "hybrid": lay["hybrid"], "p_cores": lay["p_cores"], "e_cores": lay["e_cores"],
        "cores": lay["cores"], "threads": lay["threads"], "lps": lay["lps"],
        # Islemciye gore hangi ayarlar anlamli: EPP yalnizca donanim P-state (Intel Speed Shift / AMD CPPC) ile
        # etkilidir; P/E ayri tavanlar ve zamanlayici politikasi yalnizca melez islemcide vardir.
        "features": {"epp": hwp, "hybrid": lay["hybrid"], "speed_shift": vendor == "Intel" and hwp},
    }


# ----------------------------------------------------------------------------- disk sagligi (IOCTL)
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateFileW.restype = wt.HANDLE
_k32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p, wt.DWORD, wt.DWORD, wt.HANDLE]
_k32.DeviceIoControl.argtypes = [wt.HANDLE, wt.DWORD, ctypes.c_void_p, wt.DWORD, ctypes.c_void_p, wt.DWORD,
                                 ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
_k32.CloseHandle.argtypes = [wt.HANDLE]
IOCTL_STORAGE_QUERY_PROPERTY = 0x2D1400
INVALID = wt.HANDLE(-1).value


def _open_drive(n):
    for access in (0, 0x80000000 | 0x40000000):  # once haksiz (sicaklik yeter), sonra okuma/yazma (NVMe gunlugu)
        h = _k32.CreateFileW(r"\\.\PhysicalDrive%d" % n, access, 3, None, 3, 0, None)
        if h and h != INVALID:
            try:
                yield h
            finally:
                _k32.CloseHandle(h)


def _query(h, inbuf, outsize):
    out = (ctypes.c_ubyte * outsize)()
    ret = wt.DWORD()
    ok = _k32.DeviceIoControl(h, IOCTL_STORAGE_QUERY_PROPERTY, inbuf, len(inbuf), out, outsize, ctypes.byref(ret), None)
    return bytes(out[:ret.value]) if ok else None


def disk_health(n):
    """PhysicalDrive n: sicaklik (her disk turu) ve NVMe ise SMART gunlugu. Okunamazsa bos sozluk."""
    out = {}
    for h in _open_drive(n):
        if "temp" not in out:
            q = bytearray(12)
            struct.pack_into("<II", q, 0, 52, 0)  # StorageDeviceTemperatureProperty
            b = _query(h, (ctypes.c_ubyte * 12).from_buffer(q), 512)
            if b and len(b) >= 28:
                crit, warn = struct.unpack_from("<hh", b, 8)
                t = struct.unpack_from("<h", b, 26)[0]
                if 0 < t < 150:
                    out["temp"] = t
                if 0 < warn < 150:
                    out["temp_warn"] = warn
                if 0 < crit < 150:
                    out["temp_crit"] = crit
        if "used_pct" not in out:
            size = 8 + 40 + 512
            q = bytearray(size)
            # StorageDeviceProtocolSpecificProperty; NVMe, log sayfasi 2 (SMART / Health)
            struct.pack_into("<II", q, 0, 50, 0)
            struct.pack_into("<10I", q, 8, 3, 2, 2, 0, 40, 512, 0, 0, 0, 0)
            b = _query(h, (ctypes.c_ubyte * size).from_buffer(q), size)
            if b and len(b) >= 48 + 176:
                d = b[48:48 + 512]

                def le(a, z):
                    return int.from_bytes(d[a:z], "little")
                kelvin = le(1, 3)
                if kelvin > 200:
                    out.setdefault("temp", kelvin - 273)
                out.update({
                    "critical": d[0], "spare": d[3], "spare_min": d[4], "used_pct": d[5],
                    "read_tb": round(le(32, 48) * 512000 / 1e12, 2), "written_tb": round(le(48, 64) * 512000 / 1e12, 2),
                    "power_cycles": le(112, 128), "hours": le(128, 144), "unsafe": le(144, 160),
                    "media_errors": le(160, 176),
                })
    if "used_pct" in out:
        out["life"] = max(0, 100 - out["used_pct"])
    return out


# ----------------------------------------------------------------------------- yavas envanter (CIM)
_PS = r"""$ErrorActionPreference='SilentlyContinue'
$o=[ordered]@{}
$o.cpu=Get-CimInstance Win32_Processor | select Name,MaxClockSpeed,L2CacheSize,L3CacheSize,SocketDesignation,VirtualizationFirmwareEnabled
$o.ram=@(Get-CimInstance Win32_PhysicalMemory | select DeviceLocator,Capacity,Speed,ConfiguredClockSpeed,Manufacturer,PartNumber,SMBIOSMemoryType,FormFactor,ConfiguredVoltage)
$o.slots=(Get-CimInstance Win32_PhysicalMemoryArray | measure -Property MemoryDevices -Sum).Sum
$o.maxram=(Get-CimInstance Win32_PhysicalMemoryArray | measure -Property MaxCapacityEx -Sum).Sum
$o.gpu=@(Get-CimInstance Win32_VideoController | select Name,DriverVersion,DriverDate,AdapterRAM,CurrentHorizontalResolution,CurrentVerticalResolution,CurrentRefreshRate,PNPDeviceID)
$o.disk=@(Get-PhysicalDisk | select DeviceId,FriendlyName,MediaType,BusType,Size,HealthStatus,OperationalStatus,FirmwareVersion)
$o.vol=@(Get-Volume | ? DriveLetter | select DriveLetter,FileSystemLabel,FileSystem,Size,SizeRemaining)
$o.part=@(Get-Partition | ? DriveLetter | select DiskNumber,DriveLetter)
$o.board=Get-CimInstance Win32_BaseBoard | select Manufacturer,Product
$o.system=Get-CimInstance Win32_ComputerSystem | select Manufacturer,Model
$o.bios=Get-CimInstance Win32_BIOS | select Manufacturer,SMBIOSBIOSVersion,ReleaseDate
$o.os=Get-CimInstance Win32_OperatingSystem | select Caption,Version,BuildNumber,OSArchitecture,LastBootUpTime
$o.bat=@(Get-CimInstance Win32_Battery | select Name,DeviceID)
$o.batdesign=@(Get-CimInstance -Namespace root\wmi BatteryStaticData | select DesignedCapacity,ManufactureName)
$o.batfull=@(Get-CimInstance -Namespace root\wmi BatteryFullChargedCapacity | select FullChargedCapacity)
$o.batcycle=@(Get-CimInstance -Namespace root\wmi BatteryCycleCount | select CycleCount)
$o.net=@(Get-NetAdapter -Physical | select Name,InterfaceDescription,LinkSpeed,Status,MediaType)
$o.monitor=@(Get-CimInstance -Namespace root\wmi WmiMonitorID | % { [pscustomobject]@{ maker=(($_.ManufacturerName|?{$_})|%{[char]$_}) -join ''; name=(($_.UserFriendlyName|?{$_})|%{[char]$_}) -join '' } })
$o | ConvertTo-Json -Depth 4 -Compress"""


def _date(v):
    """CIM tarihi ('/Date(1695254400000)/' ya da ISO) -> 'YYYY-MM-DD'."""
    if not v:
        return ""
    m = re.search(r"/Date\((\d+)", str(v))
    if m:
        return time.strftime("%Y-%m-%d", time.gmtime(int(m.group(1)) / 1000))
    return str(v)[:10]


def _list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _clean(s):
    s = str(s or "").strip()
    return "" if s.lower() in ("", "not applicable", "default string", "to be filled by o.e.m.", "unknown",
                               "system product name", "system manufacturer") else s


def _slow():
    rc, out = hw.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS], timeout=90)
    if "{" not in (out or ""):
        raise RuntimeError("CIM query failed: " + (out or str(rc))[:200])
    return json.loads(out[out.index("{"):])


class Inventory(threading.Thread):
    """Envanteri arka planda bir kez toplar; uygulamanin acilisini bekletmez."""

    def __init__(self):
        super().__init__(daemon=True)
        self.data = {"ready": False}
        self.error = ""
        self.disk_ids = []

    def run(self):
        info = {"ready": False}
        try:
            info["cpu"] = cpu_model()
        except Exception as exc:
            info["cpu"] = {"name": "", "error": str(exc), "lps": [], "features": {}}
        info["gpus"] = [{"name": n, "vendor": {0x10DE: "NVIDIA", 0x8086: "Intel", 0x1002: "AMD"}.get(v, hex(v)),
                         "luid": lu} for n, v, lu in hw.gpu_adapters()]
        self.data = dict(info)  # islemci bilgisi hemen hazir: arayuz cekirdek etiketlerini beklemesin
        try:
            info.update(self._shape(_slow(), info))
        except Exception as exc:
            self.error = str(exc)
        info["ready"] = True
        info["error"] = self.error
        self.data = info

    def _shape(self, r, info):
        cpu = info["cpu"]
        c = (_list(r.get("cpu")) or [{}])[0]
        cpu.update({"l2_kb": c.get("L2CacheSize"), "l3_kb": c.get("L3CacheSize"), "socket": c.get("SocketDesignation"),
                    "virt_fw": c.get("VirtualizationFirmwareEnabled")})

        ram = []
        for m in _list(r.get("ram")):
            ram.append({"slot": m.get("DeviceLocator") or "", "gb": round((m.get("Capacity") or 0) / 2 ** 30),
                        "speed": m.get("ConfiguredClockSpeed") or m.get("Speed"), "rated": m.get("Speed"),
                        "maker": _clean(m.get("Manufacturer")), "part": _clean(m.get("PartNumber")),
                        "type": MEM_TYPES.get(m.get("SMBIOSMemoryType"), ""),
                        "form": FORM_FACTORS.get(m.get("FormFactor"), ""),
                        "volt": (m.get("ConfiguredVoltage") or 0) / 1000.0 or None})
        memory = {"modules": ram, "slots": r.get("slots") or len(ram), "total_gb": sum(x["gb"] for x in ram),
                  "max_gb": round((r.get("maxram") or 0) / 2 ** 20) or None,
                  "channels": len({re.sub(r"-DIMM\d+$", "", x["slot"]) for x in ram}) if ram else 0}

        wmi_gpu = {g.get("Name") or "": g for g in _list(r.get("gpu"))}
        for g in info["gpus"]:
            w = wmi_gpu.get(g["name"]) or {}
            g.update({"driver": w.get("DriverVersion") or "", "driver_date": _date(w.get("DriverDate")),
                      "res": "%s×%s" % (w["CurrentHorizontalResolution"], w["CurrentVerticalResolution"])
                      if w.get("CurrentHorizontalResolution") else "",
                      "hz": w.get("CurrentRefreshRate")})
            if g["vendor"] == "NVIDIA" and g["driver"]:
                # Windows surucu surumunun son bes hanesi NVIDIA surumudur: 32.0.16.1742 -> 617.42
                d = g["driver"].replace(".", "")[-5:]
                g["nv_driver"] = "%s.%s" % (d[:3], d[3:])

        letters = {}
        for p in _list(r.get("part")):
            letters.setdefault(str(p.get("DiskNumber")), []).append(p.get("DriveLetter"))
        vols = {v.get("DriveLetter"): v for v in _list(r.get("vol"))}
        disks = []
        for d in _list(r.get("disk")):
            did = str(d.get("DeviceId"))
            parts = []
            for letter in letters.get(did, []):
                v = vols.get(letter) or {}
                parts.append({"letter": letter, "label": v.get("FileSystemLabel") or "", "fs": v.get("FileSystem") or "",
                              "gb": round((v.get("Size") or 0) / 1e9), "free_gb": round((v.get("SizeRemaining") or 0) / 1e9)})
            disks.append({"id": did, "name": d.get("FriendlyName") or "", "media": d.get("MediaType") or "",
                          "bus": d.get("BusType") or "", "gb": round((d.get("Size") or 0) / 1e9),
                          "health": d.get("HealthStatus") or "", "status": d.get("OperationalStatus") or "",
                          "firmware": d.get("FirmwareVersion") or "", "volumes": parts})
        self.disk_ids = [int(d["id"]) for d in disks if d["id"].isdigit()]

        battery = None
        if _list(r.get("bat")):
            design = sum(b.get("DesignedCapacity") or 0 for b in _list(r.get("batdesign")))
            full = sum(b.get("FullChargedCapacity") or 0 for b in _list(r.get("batfull")))
            cycles = sum(b.get("CycleCount") or 0 for b in _list(r.get("batcycle")))
            maker = next((b.get("ManufactureName") for b in _list(r.get("batdesign")) if b.get("ManufactureName")), "")
            battery = {"name": (_list(r.get("bat"))[0].get("Name") or ""), "maker": _clean(maker),
                       "design_wh": round(design / 1000, 1) if design else None,
                       "full_wh": round(full / 1000, 1) if full else None,
                       "health": round(full * 100.0 / design) if design and full else None,
                       "cycles": cycles or None}

        board = (_list(r.get("board")) or [{}])[0]
        system = (_list(r.get("system")) or [{}])[0]
        bios = (_list(r.get("bios")) or [{}])[0]
        os_ = (_list(r.get("os")) or [{}])[0]
        nets = [{"name": n.get("Name") or "", "desc": n.get("InterfaceDescription") or "",
                 "speed": n.get("LinkSpeed") or "", "up": n.get("Status") == "Up"} for n in _list(r.get("net"))]
        mons = [{"maker": m.get("maker") or "", "name": m.get("name") or ""} for m in _list(r.get("monitor"))]
        return {
            "memory": memory, "disks": disks, "battery": battery, "network": nets, "monitors": mons,
            "system": {"maker": _clean(system.get("Manufacturer")) or _clean(board.get("Manufacturer")),
                       "model": _clean(system.get("Model")) or _clean(board.get("Product")),
                       "board": " ".join(x for x in (_clean(board.get("Manufacturer")), _clean(board.get("Product"))) if x),
                       "bios": " ".join(x for x in (_clean(bios.get("Manufacturer")), bios.get("SMBIOSBIOSVersion") or "") if x),
                       "bios_date": _date(bios.get("ReleaseDate")),
                       "os": os_.get("Caption") or "Windows", "os_build": os_.get("BuildNumber") or "",
                       "boot": _date(os_.get("LastBootUpTime"))},
        }
