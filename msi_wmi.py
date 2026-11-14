# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""MSI_ACPI (root\\WMI) tasima katmani: MSI'in ACPI-WMI koprusu, ek surucu kurmadan.

Yontemlerin hepsi 32 baytlik Package_32 alir ve verir (Linux msi-wmi-platform belgesi):
  giris : [alt ozellik / EC adresi, 31 bayt veri]
  cikis : [durum (0 = basarisiz), 31 bayt veri]
  Get_EC   -> cikis[1] bayrak, cikis[2:30] EC firmware metni (alt ozellik onemsiz)
  Get_Data -> giris[0] = EC adresi; cikis[1] = o adresteki bayt
  Set_Data -> giris[0] = EC adresi, giris[1] = deger
  Get_Fan  -> giris[0] = 0; cikis[1:9] dort adet 16 bit (buyuk uclu) fan okumasi, devir = 480000 / okuma
Set_EC hic kullanilmaz (yerlesimi belgelenmemis).

Get_Data/Set_Data'nin ham EC adresi aldigi bilgisi tek kaynakli ve DONANIMDA DOGRULANMAMISTIR; bu yuzden
msi.MsiEC once firmware alanini Get_Data ile okuyup Get_EC'nin metniyle karsilastirir, tutmazsa EC'yi hic
kullanmaz. ACPI tarafi is parcacigi guvenli degildir: tum cagrilar tek kilit ve tek isci surecten gecer.

Isci: tek bir kalici Windows PowerShell sureci (her cagri icin yeni surec acilmaz). Satir protokolu:
  istek  "C <yontem> <64 hex>"   yanit "OK <64 hex>" ya da "ERR <ileti>"
Isci yalnizca METHODS listesindeki yontemleri cagirir (iki tarafta da denetlenir).
"""
import base64
import os
import queue
import subprocess
import threading

METHODS = ("Get_EC", "Get_Data", "Set_Data", "Get_Fan", "Get_WMI")
NO_WINDOW = 0x08000000
TIMEOUT = 4.0

_PS = r"""
$ErrorActionPreference = 'Stop'
try {
  $inst = Get-WmiObject -Namespace root\wmi -Class MSI_ACPI | Select-Object -First 1
  $cls = [wmiclass]'root\wmi:Package_32'
} catch { $inst = $null }
if ($null -eq $inst) { [Console]::Out.WriteLine('NOINST'); [Console]::Out.Flush(); exit 0 }
[Console]::Out.WriteLine('READY'); [Console]::Out.Flush()
$allowed = @('Get_EC','Get_Data','Set_Data','Get_Fan','Get_WMI')
while ($true) {
  $line = [Console]::In.ReadLine()
  if ($null -eq $line -or $line -eq 'Q') { break }
  try {
    $p = $line.Split(' ')
    if ($p.Length -ne 3 -or $p[0] -ne 'C' -or $allowed -notcontains $p[1] -or $p[2].Length -ne 64) { throw 'bad request' }
    $b = New-Object byte[] 32
    for ($i = 0; $i -lt 32; $i++) { $b[$i] = [Convert]::ToByte($p[2].Substring($i * 2, 2), 16) }
    $pkg = $cls.CreateInstance(); $pkg.Bytes = $b
    $r = $inst.($p[1])($pkg)
    $o = $r.Data.Bytes
    $hex = -join ($o | ForEach-Object { $_.ToString('x2') })
    [Console]::Out.WriteLine('OK ' + $hex)
  } catch {
    [Console]::Out.WriteLine('ERR ' + ($_.Exception.Message -replace '[\r\n]', ' '))
  }
  [Console]::Out.Flush()
}
"""


class WmiError(OSError):
    pass


class PowerShellWorker:
    """Kalici PowerShell sureci. call(yontem, 32 bayt) -> 32 bayt."""

    def __init__(self, exe=None):
        if exe is None:
            import donanim
            exe = donanim.tool_path("powershell")
        if not exe:
            raise WmiError("powershell.exe bulunamadı")
        enc = base64.b64encode(_PS.encode("utf-16-le")).decode("ascii")
        self.p = subprocess.Popen([exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                                   "-EncodedCommand", enc],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  creationflags=NO_WINDOW, cwd=os.path.dirname(exe))
        self.q = queue.Queue()
        threading.Thread(target=self._reader, daemon=True).start()
        self.present = self._line(20.0) == "READY"  # ilk WMI baglantisi yavas olabilir
        if not self.present:
            self.close()

    def _reader(self):
        try:
            for raw in self.p.stdout:
                self.q.put(raw.decode("ascii", "replace").strip())
        except (OSError, ValueError):
            pass
        finally:
            self.q.put(None)

    def _line(self, timeout):
        try:
            return self.q.get(timeout=timeout)
        except queue.Empty:
            return None

    def call(self, method, data):
        if method not in METHODS:
            raise WmiError("izinsiz yöntem")
        if self.p.poll() is not None:
            raise WmiError("WMI işçisi kapandı")
        try:
            self.p.stdin.write(("C %s %s\n" % (method, bytes(data).hex())).encode("ascii"))
            self.p.stdin.flush()
        except OSError as exc:
            raise WmiError(str(exc))
        line = self._line(TIMEOUT)
        if line is None:
            self.close()
            raise WmiError("MSI_ACPI yanıt vermedi")
        if line.startswith("ERR "):
            raise WmiError(line[4:])
        if not line.startswith("OK "):
            raise WmiError("beklenmeyen yanıt")
        return bytes.fromhex(line[3:])

    def close(self):
        try:
            if self.p.poll() is None:
                try:
                    self.p.stdin.write(b"Q\n")
                    self.p.stdin.flush()
                    self.p.wait(1.0)
                except (OSError, subprocess.TimeoutExpired):
                    self.p.kill()
        except OSError:
            pass


class MsiWmi:
    """msi.MsiEC'nin bekledigi tasima: fw(), read(), write(), fan_rpm(). `caller` sahte (test) olabilir:
    call(yontem, 32 bayt) -> 32 bayt."""

    def __init__(self, caller):
        self.caller = caller
        self.lock = threading.Lock()

    def _call(self, method, data):
        if method not in METHODS:
            raise WmiError("izinsiz yöntem")
        buf = (bytes(data) + bytes(32))[:32]
        with self.lock:
            out = bytes(self.caller.call(method, buf))
        if len(out) < 2 or out[0] == 0:
            raise WmiError("%s başarısız" % method)
        return out

    def fw(self):
        return self._call("Get_EC", [0])[2:30]

    def read(self, addr):
        if not 0 <= addr <= 0xFF:
            raise ValueError("adres")
        return self._call("Get_Data", [addr])[1]

    def write(self, addr, value):
        if not 0 <= addr <= 0xFF or not 0 <= value <= 0xFF:
            raise ValueError("adres/değer")
        self._call("Set_Data", [addr, value])

    def fan_rpm(self):
        """[islemci, ekran karti] devir (0 = duruyor)."""
        out = self._call("Get_Fan", [0])
        vals = []
        for i in range(2):
            raw = (out[1 + 2 * i] << 8) | out[2 + 2 * i]
            rpm = round(480000 / raw) if raw else 0
            vals.append(rpm if rpm < 12000 else 0)
        return vals

    def close(self):
        close = getattr(self.caller, "close", None)
        if close:
            close()


def open_wmi():
    """MSI_ACPI varsa MsiWmi, yoksa None."""
    w = PowerShellWorker()
    return MsiWmi(w) if w.present else None
