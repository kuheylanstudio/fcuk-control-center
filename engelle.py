# -*- coding: utf-8 -*-
"""Monster "Fn hotkeys and OSD" programlarini TAM YOLLARIYLA engeller (IFEO UseFilter + FilterFullPath).

Neden: eskiden IFEO'da ADLA engelleniyordu (ornek: LoadUI.exe -> Debugger=systray.exe). Ad engeli sistem
geneldir: ayni adi tasiyan BASKA bir yazilimin programi da sessizce acilmaz. Tam yol filtresi yalnizca
Monster paketinin, eski ControlCenter klasorunun ve CCDCHUService klasorunun icindeki dosyalari engeller.

Bedeli: yalnizca diskte BULUNAN yollar engellenebilir. Windows paketi yeni bir surum klasorune geri kurarsa
yeni yol, yonetici motor yeniden taradiginda (acilista ve 30 dakikada bir) engellenir. Bir kez bulunan yol
dosya silinse de filtrede kalir (ayni surum geri kurulursa hemen engelli olur).

Geri almak: IFEO altindaki bu adlarin "KendiCC..." alt anahtarlarini silmek.
Yonetici ister (HKLM).
"""
import os
import winreg

import donanim as hw

IFEO = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options"
# AddFn.exe: CCDCHUService'in calistirdigi, paketi yeniden kaydeden yardimci (prefetch'te goruldu)
NAMES = ("FnKey.exe", "LaunchFnkey.exe", "AddFn.exe", "CC40.exe", "LoadUI.exe", "PopUI.exe",
         "cc30wk.exe", "ControlGPU.exe")
PACKAGE = "CLEVOCO.FnhotkeysandOSD"
SERVICE = "CCDCHUService"
PREFIX = "KendiCC"          # bizim alt anahtarlarimiz; baskalarininkine dokunulmaz
MAX_PATHS = 20              # ad basina en fazla bu kadar yol (eski surum klasorleri birikmesin)
ACCESS = winreg.KEY_ALL_ACCESS | winreg.KEY_WOW64_64KEY


def debugger():
    return os.path.join(hw.system_dir(), "systray.exe")


def _program_files_x86():
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(520)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x2A, None, 0, buf) == 0:  # CSIDL_PROGRAM_FILESX86
            return buf.value
    except (OSError, AttributeError):
        pass
    return r"C:\Program Files (x86)"


def _package_dirs():
    rc, out = hw.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                      "Get-AppxPackage -AllUsers -Name '%s' | ForEach-Object { $_.InstallLocation }" % PACKAGE],
                     timeout=60)
    return [line.strip() for line in out.splitlines() if line.strip()] if rc == 0 else []


def _service_dir():
    """CCDCHUService programinin klasoru (AddFn.exe genelde yaninda)."""
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Services\%s" % SERVICE) as k:
            image = winreg.QueryValueEx(k, "ImagePath")[0]
    except OSError:
        return None
    image = os.path.expandvars(image.strip())
    if image.startswith('"'):
        image = image[1:].split('"', 1)[0]
    else:
        image = image.split(" -", 1)[0].split(" /", 1)[0]
    windir = os.path.dirname(hw.system_dir())
    low = image.lower()
    if low.startswith("\\systemroot\\"):
        image = os.path.join(windir, image[12:])
    elif low.startswith("system32\\"):
        image = os.path.join(windir, image)
    elif low.startswith("\\??\\"):
        image = image[4:]
    return os.path.dirname(image) if os.path.isabs(image) else None


def find_paths():
    """{ad (kucuk harf): [tam yol, ...]} - diskte bulunan Monster programlari."""
    wanted = {n.lower(): [] for n in NAMES}

    def add(path):
        name = os.path.basename(path).lower()
        if name in wanted and os.path.isfile(path) and path.lower() not in [p.lower() for p in wanted[name]]:
            wanted[name].append(path)

    # Paket ve eski ControlCenter klasoru: alt klasorler dahil
    for root in _package_dirs() + [os.path.join(_program_files_x86(), "ControlCenter")]:
        if os.path.isdir(root):
            for d, _, files in os.walk(root):
                for f in files:
                    add(os.path.join(d, f))
    # Hizmet klasoru: yalnizca dogrudan icindekiler (System32 olabilir, tamami taranmaz)
    sdir = _service_dir()
    if sdir and os.path.isdir(sdir):
        for n in NAMES:
            add(os.path.join(sdir, n))
    return wanted


def _subkeys(key):
    out, i = [], 0
    while True:
        try:
            out.append(winreg.EnumKey(key, i))
        except OSError:
            return out
        i += 1


def _value(key, name):
    try:
        return winreg.QueryValueEx(key, name)[0]
    except OSError:
        return None


def _is_our_debugger(v):
    if not isinstance(v, str):
        return False
    return os.path.expandvars(v.strip().strip('"')).replace("/", "\\").rsplit("\\", 1)[-1].lower() == "systray.exe"


def apply(found):
    """Filtreleri yazar. Donus: kayit satirlari (gunluk icin)."""
    lines = []
    dbg = debugger()
    for name in NAMES:
        new = found.get(name.lower(), [])
        with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, IFEO + "\\" + name, 0, ACCESS) as k:
            # 1) eski AD engeli (bizim koydugumuz systray.exe) kaldirilir: UseFilter acikken eslesme olmazsa
            #    Windows ust anahtardaki Debugger'i uygular, yani ad engeli surerdi.
            if _is_our_debugger(_value(k, "Debugger")):
                winreg.DeleteValue(k, "Debugger")
                lines.append("ad engeli kaldirildi: %s" % name)
            # 2) bizim onceki filtrelerimiz okunur ve silinir (birlestirilip yeniden yazilacak)
            ours, others = [], []
            for sub in _subkeys(k):
                if sub.startswith(PREFIX):
                    with winreg.OpenKey(k, sub) as s:
                        p = _value(s, "FilterFullPath")
                    if isinstance(p, str) and p:
                        ours.append(p)
                    winreg.DeleteKey(k, sub)
                else:
                    others.append(sub)
            paths = []
            for p in new + ours:  # yeni bulunanlar once; ayni yol bir kez
                if p.lower() not in [x.lower() for x in paths]:
                    paths.append(p)
            paths = paths[:MAX_PATHS]
            # 3) filtreler yazilir
            for i, p in enumerate(paths):
                with winreg.CreateKeyEx(k, "%s%d" % (PREFIX, i), 0, ACCESS) as s:
                    winreg.SetValueEx(s, "FilterFullPath", 0, winreg.REG_SZ, p)
                    winreg.SetValueEx(s, "Debugger", 0, winreg.REG_SZ, dbg)
            if paths:
                winreg.SetValueEx(k, "UseFilter", 0, winreg.REG_DWORD, 1)
                lines += ["engellendi (tam yol): %s" % p for p in paths if p in new]
            elif not others:
                try:
                    winreg.DeleteValue(k, "UseFilter")
                except OSError:
                    pass
            empty = not _subkeys(k) and _first_value(k) is None
        if empty:  # yalnizca bizim olusturdugumuz bos anahtar kalir: silinir
            try:
                winreg.DeleteKeyEx(winreg.HKEY_LOCAL_MACHINE, IFEO + "\\" + name, winreg.KEY_WOW64_64KEY)
            except OSError:
                pass
    return lines


def _first_value(key):
    try:
        return winreg.EnumValue(key, 0)
    except OSError:
        return None


def refresh():
    """Tara ve uygula. Donus: (bulunan yol sayisi, kayit satirlari)."""
    found = find_paths()
    return sum(len(v) for v in found.values()), apply(found)
