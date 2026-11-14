# FCUK Control Center: üreticiye ait InsydeDCHU.dll'i bu bilgisayardan bulup lib\ klasörüne kopyalar.
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazılmıştır. MIT lisansı, bkz. LICENSE.
#   powershell -ExecutionPolicy Bypass -File lib\dll_topla.ps1
# Yönetici izni gerekmez. Hiçbir şey indirilmez; yalnızca bilgisayarda zaten olan dosyalar aranır.
# Aranan yerler (öncelik sırasıyla):
#   1) Windows sürücü deposu: AcpiBridge sürücü paketi (üretici Control Center kaldırılmış olsa bile durur)
#   2) Üretici Control Center kurulumu: C:\Program Files (x86)\ControlCenter
#   3) Microsoft Store "Fn hotkeys and OSD" paketi (CLEVOCO.FnhotkeysandOSD)
#   4) FCUK Control Center setup.exe yedekleri: C:\ProgramData\FCUK Control Center\yedek
param([string]$Hedef = $PSScriptRoot)
$ErrorActionPreference = 'Stop'

$aday = @()
$aday += Get-ChildItem (Join-Path $env:SystemRoot 'System32\DriverStore\FileRepository') -Directory -Filter 'acpibridge*' -ErrorAction SilentlyContinue |
    ForEach-Object { Join-Path $_.FullName 'InsydeDCHU.dll' } |
    Where-Object { Test-Path $_ } | Sort-Object { (Get-Item $_).LastWriteTime } -Descending
foreach ($d in 'DCHU', 'AppInstall', '') {
    $aday += Join-Path ${env:ProgramFiles(x86)} "ControlCenter\$d\InsydeDCHU.dll"
}
$fn = Get-AppxPackage -Name '*FnhotkeysandOSD*' -ErrorAction SilentlyContinue | Select-Object -First 1
if ($fn) { $aday += Join-Path $fn.InstallLocation 'FnKey\DCHU\InsydeDCHU.dll' }
$aday += Get-ChildItem (Join-Path $env:ProgramData 'FCUK Control Center\yedek') -Recurse -Filter 'InsydeDCHU.dll' -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty FullName

$kaynak = $aday | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $kaynak) {
    Write-Host 'InsydeDCHU.dll bu bilgisayarda bulunamadı.' -ForegroundColor Yellow
    Write-Host 'Clevo / Monster tabanlı değilse buna gerek yok: uygulama bu dosya olmadan da çalışır.'
    Write-Host 'Clevo / Monster ise üreticinin destek sayfasından modelinize ait "Control Center" ya da'
    Write-Host '"AcpiBridge / DCHU" sürücü paketini indirip açın ve içindeki InsydeDCHU.dll dosyasını'
    Write-Host "şu klasöre kopyalayın: $Hedef"
    exit 1
}

$sig = Get-AuthenticodeSignature $kaynak
$ver = (Get-Item $kaynak).VersionInfo
New-Item -ItemType Directory -Force $Hedef | Out-Null
Copy-Item $kaynak (Join-Path $Hedef 'InsydeDCHU.dll') -Force
Write-Host "Kopyalandı: $kaynak" -ForegroundColor Green
Write-Host ("  sürüm {0}, imza: {1} ({2})" -f $ver.FileVersion, $sig.Status, $sig.SignerCertificate.Subject)
Write-Host "  hedef: $(Join-Path $Hedef 'InsydeDCHU.dll')"
exit 0
