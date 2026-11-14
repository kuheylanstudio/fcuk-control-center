# FCUK Control Center: dağıtılabilir kurulum programını (dist\setup.exe) derler.
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazılmıştır. MIT lisansı, bkz. LICENSE.
#   powershell -ExecutionPolicy Bypass -File setup_olustur.ps1
# 1) Uygulama PyInstaller ile dist\FCUKControlCenter\ olarak derlenir (kur.ps1 ile aynı ayarlar).
# 2) kurulum\setup.py tek dosyalık, yönetici isteyen setup.exe'ye derlenir; uygulama klasörü ve
#    kurulum\kurulum.ps1 içine gömülür. Hiçbir şey kurulmaz; kurmak için setup.exe'yi çalıştırın.
$ErrorActionPreference = 'Stop'
$src   = Split-Path -Parent $MyInvocation.MyCommand.Path
$build = Join-Path $src 'build'
$dist  = Join-Path $src 'dist'
$app   = Join-Path $dist 'FCUKControlCenter'
Set-Location $src

$ver = [regex]::Match((Get-Content (Join-Path $src 'control_center.py') -Raw -Encoding UTF8), '(?m)^VERSION\s*=\s*"([^"]+)"').Groups[1].Value
if (-not $ver) { throw 'control_center.py içinde VERSION bulunamadı' }
if (-not (Test-Path (Join-Path $src 'lib\InsydeDCHU.dll'))) {
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
    --icon $ico --add-data "$src\ui;ui" --add-data "$src\lib;lib" `
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
Write-Host ("Hazır: {0} ({1:N1} MB, sürüm {2})" -f $out, ((Get-Item $out).Length / 1MB), $ver)
