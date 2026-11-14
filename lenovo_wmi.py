# -*- coding: utf-8 -*-
# FCUK Control Center
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazilmistir. MIT lisansi, bkz. LICENSE.
"""Lenovo arka ucu icin WMI tasiyicisi: tek, gizli, kalici bir PowerShell sureci.

Neden PowerShell: Lenovo'nun fan tablosu yontemi (LENOVO_FAN_METHOD.Fan_Set_Table) bayt dizisi parametresi
alir; CIM cmdlet'leri parametre turlerini sinif semasindan kendisi cevirir. Her cagri icin yeni bir surec
~0,3 sn surerdi; surec bir kez acilir ve satir satir JSON istek/yanit alisverisi yapar (cagri basina birkac
ms). Surec takilirsa arayan zaman asimiyla doner, surec oldurulur ve bir sonraki cagrida yeniden acilir.

Yalnizca bu dosya PowerShell'le konusur; Lenovo protokolu lenovo_legion.py'de. Birim testleri bu sinifin
yerine ayni arayuzlu sahte bir nesne verir (query / class_methods / call / calls).
"""
import base64
import json
import queue
import subprocess
import threading

NO_WINDOW = 0x08000000

# Istek: {"id", "op": "q"|"m"|"c", "ns", "cls", ...}; yanit: {"id", "ok", "v"} ya da {"id", "ok": false, "e"}.
#   q: sinifin orneklerinden "props" ozellikleri  ->  [{ozellik: deger}]
#   m: sinifin yontem adlari (sinif yoksa hata)    ->  [ad]
#   c: "calls" = [[yontem, {arg: deger}, cikis_adi]] ayni sinifin ilk orneginde sirayla
#      ->  [[true, deger] | [false, hata]] ; biri basarisiz olsa da digerleri calisir
_LOOP = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$cache = @{}
$sess = New-CimSession  # her cmdlet kendi oturumunu acmasin (cagri basina ~0,4 sn)
function Inst($ns, $cls) {
  $k = "$ns|$cls"
  if (-not $cache.ContainsKey($k)) {
    $o = @(Get-CimInstance -CimSession $sess -Namespace $ns -ClassName $cls) | Select-Object -First 1
    if ($null -eq $o) { throw "ornek yok: $cls" }
    $cache[$k] = $o
  }
  return $cache[$k]
}
function CallOne($ns, $cls, $c) {
  $h = @{}
  if ($null -ne $c[1]) {
    foreach ($p in $c[1].PSObject.Properties) {
      $v = $p.Value
      if ($v -is [array]) { $v = [byte[]]$v }
      $h[$p.Name] = $v
    }
  }
  $r = Invoke-CimMethod -CimSession $sess -InputObject (Inst $ns $cls) -MethodName $c[0] -Arguments $h
  if (-not $c[2]) { return $null }
  $x = $null
  if ($r.OutParameters) { $x = $r.OutParameters[$c[2]] }
  if ($null -ne $x) { $v = $x.Value } else { $v = $r.($c[2]) }
  if ($v -is [array]) { return ,([int[]]$v) }
  return $v
}
while ($null -ne ($line = [Console]::In.ReadLine())) {
  $id = $null
  try {
    $q = $line | ConvertFrom-Json
    $id = $q.id
    if ($q.op -eq 'q') {
      $v = @(Get-CimInstance -CimSession $sess -Namespace $q.ns -ClassName $q.cls | ForEach-Object {
        $o = @{}; foreach ($p in $q.props) { $o[$p] = $_.$p }; $o })
    } elseif ($q.op -eq 'm') {
      $v = @((Get-CimClass -CimSession $sess -Namespace $q.ns -ClassName $q.cls).CimClassMethods | ForEach-Object { $_.Name })
    } elseif ($q.op -eq 'c') {
      $v = @()
      foreach ($c in $q.calls) {
        try { $v += ,@($true, (CallOne $q.ns $q.cls $c)) } catch { $v += ,@($false, $_.Exception.Message) }
      }
    } else { throw "bilinmeyen istek" }
    $out = ConvertTo-Json -Compress -Depth 6 @{ id = $id; ok = $true; v = $v }
  } catch {
    $out = ConvertTo-Json -Compress @{ id = $id; ok = $false; e = $_.Exception.Message }
  }
  # Yalnizca ASCII: konsol kod sayfasindan bagimsiz (Turkce hata iletileri \u00XX kacisiyla gider)
  $out = [regex]::Replace($out, '[^\x00-\x7F]', { param($m) '\u{0:x4}' -f [int][char]$m.Value })
  [Console]::Out.WriteLine($out)
  [Console]::Out.Flush()
}
"""


class WmiError(RuntimeError):
    pass


class PsWmi:
    """Is parcacigi guvenli; tum istekler tek kilitten gecer."""

    def __init__(self, timeout=8.0, exe="powershell.exe"):
        self.timeout = timeout
        self.exe = exe
        self._lock = threading.Lock()
        self._proc = None
        self._lines = None
        self._seq = 0

    # ------------------------------------------------------------------ surec
    def _start(self):
        enc = base64.b64encode(_LOOP.encode("utf-16-le")).decode("ascii")
        self._proc = subprocess.Popen(
            [self.exe, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-EncodedCommand", enc],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            creationflags=NO_WINDOW, encoding="utf-8", errors="replace", bufsize=1)
        self._lines = queue.Queue()
        threading.Thread(target=self._reader, args=(self._proc, self._lines), daemon=True,
                         name="lenovo-wmi").start()

    @staticmethod
    def _reader(proc, lines):
        try:
            for line in proc.stdout:
                lines.put(line)
        finally:
            lines.put(None)

    def _kill(self):
        p, self._proc = self._proc, None
        if p:
            try:
                p.kill()
            except OSError:
                pass

    def close(self):
        with self._lock:
            self._kill()

    def _ask(self, req):
        with self._lock:
            if self._proc is None or self._proc.poll() is not None:
                self._start()
            self._seq += 1
            req["id"] = self._seq
            try:
                self._proc.stdin.write(json.dumps(req) + "\n")
                self._proc.stdin.flush()
            except OSError as exc:
                self._kill()
                raise WmiError("PowerShell yazilamadi: %s" % exc)
            while True:
                try:
                    line = self._lines.get(timeout=self.timeout)
                except queue.Empty:
                    self._kill()  # takildi: bir sonraki cagri yeni surec acar
                    raise WmiError("WMI cagrisi zaman asimi (%s)" % req.get("op"))
                if line is None:
                    self._kill()
                    raise WmiError("PowerShell sureci kapandi")
                try:
                    res = json.loads(line)
                except ValueError:
                    continue  # PowerShell'in kendi ciktisi: yok say
                if not isinstance(res, dict) or res.get("id") != req["id"]:
                    continue  # zaman asimina ugramis eski bir istegin gec yaniti
                if not res.get("ok"):
                    raise WmiError(res.get("e") or "WMI hatasi")
                return res.get("v")

    # ------------------------------------------------------------------ arayuz
    def query(self, cls, props, ns=r"root\WMI"):
        return self._ask({"op": "q", "ns": ns, "cls": cls, "props": list(props)}) or []

    def class_methods(self, cls, ns=r"root\WMI"):
        """Sinifin yontem adlari; sinif yoksa WmiError."""
        return self._ask({"op": "m", "ns": ns, "cls": cls}) or []

    def calls(self, cls, items, ns=r"root\WMI"):
        """items: [(yontem, {arg: deger} | None, cikis_adi | None)] -> [(ok, deger | hata metni)]."""
        res = self._ask({"op": "c", "ns": ns, "cls": cls,
                         "calls": [[m, a or None, o] for m, a, o in items]}) or []
        return [(bool(r[0]), r[1]) if isinstance(r, list) and len(r) == 2 else (False, "bozuk yanit")
                for r in res]

    def call(self, cls, method, args=None, out="Data", ns=r"root\WMI"):
        ok, v = self.calls(cls, [(method, args, out)], ns)[0]
        if not ok:
            raise WmiError("%s.%s: %s" % (cls, method, v))
        return v
