# FCUK Control Center: dağıtılabilir kurulum programını (dist\setup.exe) derler.
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazılmıştır. MIT lisansı, bkz. LICENSE.
#   powershell -ExecutionPolicy Bypass -File setup_olustur.ps1
# 1) Uygulama PyInstaller ile dist\FCUKControlCenter\ olarak derlenir (kur.ps1 ile aynı ayarlar).
# 2) kurulum\setup.py tek dosyalık, yönetici isteyen setup.exe'ye derlenir; uygulama klasörü ve
#    kurulum\kurulum.ps1 içine gömülür. Hiçbir şey kurulmaz; kurmak için setup.exe'yi çalıştırın.
#
#   -Dagitim  herkese açık indirme için derler: üreticiye ait DLL pakete GİRMEZ. Uygulama InsydeDCHU.dll'i
#             Clevo / Monster dizüstüde Windows sürücü deposundan yükler. Çıktı: dist\FCUK-Control-Center-Setup-<sürüm>.exe;
#             README'deki indirme düğmesi de bu dosyaya (sürüm etiketi v<sürüm>) güncellenir.
param([switch]$Dagitim)
$ErrorActionPreference = 'Stop'
$src   = Split-Path -Parent $MyInvocation.MyCommand.Path
$build = Join-Path $src 'build'
$dist  = Join-Path $src 'dist'
$app   = Join-Path $dist 'FCUKControlCenter'
Set-Location $src

$ver = [regex]::Match((Get-Content (Join-Path $src 'control_center.py') -Raw -Encoding UTF8), '(?m)^VERSION\s*=\s*"([^"]+)"').Groups[1].Value
if (-not $ver) { throw 'control_center.py içinde VERSION bulunamadı' }
$lib = Join-Path $src 'lib'
if ($Dagitim) {
    # Dağıtım paketinde yalnızca lib\README.md bulunur; üretici DLL'leri kopyalanmaz
    $lib = Join-Path $build 'lib_dagitim'
    if (Test-Path $lib) { Remove-Item $lib -Recurse -Force }
    New-Item -ItemType Directory -Force $lib | Out-Null
    Copy-Item (Join-Path $src 'lib\README.md') $lib
    Write-Host '== Dağıtım derlemesi: üretici DLL''i pakete girmeyecek (sürücü deposundan yüklenir)'
} elseif (-not (Test-Path (Join-Path $src 'lib\InsydeDCHU.dll'))) {
    Write-Host '== lib\InsydeDCHU.dll yok: bu bilgisayarda aranıyor (lib\dll_topla.ps1)'
    & (Join-Path $src 'lib\dll_topla.ps1')
    if (-not (Test-Path (Join-Path $src 'lib\InsydeDCHU.dll'))) {
        Write-Warning 'InsydeDCHU.dll bulunamadı: setup.exe, Clevo/Monster dizüstülerde DLL''i Windows sürücü deposundan yükler; orada da yoksa fan / güç modu / klavye ışığı kapalı olur (bkz. lib\README.md)'
    }
}

New-Item -ItemType Directory -Force $build | Out-Null
$ico = Join-Path $build 'uygulama.ico'
python -c "import sys; sys.path.insert(0, r'$src'); import tepsi; tepsi.make_app_icon(r'$ico')"
if ($LASTEXITCODE -ne 0) { throw 'simge üretilemedi' }

Write-Host "== Uygulama derleniyor (sürüm $ver)"
python -m PyInstaller --noconfirm --clean --onedir --windowed --name FCUKControlCenter `
    --icon $ico --add-data "$src\ui;ui" --add-data "$lib;lib" `
    --distpath $dist --workpath (Join-Path $build 'pyi') --specpath $build `
    control_center.py
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller (uygulama) başarısız' }

$surum = Join-Path $build 'surum.txt'
[IO.File]::WriteAllText($surum, $ver)

Write-Host "== setup.exe derleniyor"
python -m PyInstaller --noconfirm --clean --onefile --windowed --uac-admin --name setup `
    --icon $ico --add-data "$app;payload" --add-data "$src\kurulum\kurulum.ps1;." `
    --add-data "$surum;." --add-data "$ico;." `
    --distpath $dist --workpath (Join-Path $build 'pyi_setup') --specpath $build `
    (Join-Path $src 'kurulum\setup.py')
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller (setup) başarısız' }

$out = Join-Path $dist 'setup.exe'
if ($Dagitim) {
    $dll = @(Get-ChildItem $app -Recurse -File | Where-Object { $_.Name -in 'InsydeDCHU.dll', 'GetProductdll.dll' })
    if ($dll.Count) { throw "Dağıtım paketinde üretici DLL'i var: $($dll[0].FullName)" }
    # Dosya adında sürüm var: kullanıcı yeni sürümü indirdiğini adından görür
    Get-ChildItem $dist -Filter 'FCUK-Control-Center-Setup*.exe' | Remove-Item -Force
    $name = "FCUK-Control-Center-Setup-$ver.exe"
    $pub = Join-Path $dist $name
    Move-Item $out $pub -Force
    $out = $pub
    # README'deki indirme bağlantıları ve düğme bu sürümün dosyasına çevrilir (GitHub sürüm etiketi: v<sürüm>)
    $readme = Join-Path $src 'README.md'
    $md = [IO.File]::ReadAllText($readme)
    $md = $md -replace 'releases/(latest/download|download/v[0-9.]+)/FCUK-Control-Center-Setup(-[0-9.]+)?\.exe', "releases/download/v$ver/$name"
    $md = $md -replace 'FCUK-Control-Center-Setup(-[0-9.]+)?\.exe', $name
    $md = $md -replace 'FCUK--Control--Center--Setup(--[0-9.]+)?\.exe', ($name -replace '-', '--')
    [IO.File]::WriteAllText($readme, $md, (New-Object Text.UTF8Encoding($false)))
    Write-Host "== README indirme bağlantısı: releases/download/v$ver/$name"
}
Write-Host ("Hazır: {0} ({1:N1} MB, sürüm {2})" -f $out, ((Get-Item $out).Length / 1MB), $ver)
