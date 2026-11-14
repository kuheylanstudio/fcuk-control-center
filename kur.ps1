# FCUK Control Center: exe'yi derler ve kurar. Kod degistikten sonra yeniden calistirmak yeterli.
# Claude Opus 5.5 (Anthropic) ile yazildi. MIT lisansi, bkz. LICENSE.
#   powershell -ExecutionPolicy Bypass -File kur.ps1
# 1) (normal kullanici) PyInstaller ile dist\KendiControlCenter\ derlenir.
# 2) (yonetici, tek UAC) eski motor durdurulur, C:\Program Files\Kendi Control Center'a kopyalanir,
#    yonetici gorevi exe'ye yonlendirilir, Baslat menusu ve masaustu kisayollari olusturulur.
param([switch]$Install)
$ErrorActionPreference = "Stop"
$src  = Split-Path -Parent $MyInvocation.MyCommand.Path
$dist = Join-Path $src "dist\KendiControlCenter"
$dest = Join-Path $env:ProgramFiles "Kendi Control Center"
$exe  = Join-Path $dest "KendiControlCenter.exe"
# Yonetici bolumu kullanicinin yazabildigi %APPDATA%'ya YAZMAZ (oradaki bir baglanti/junction yonetici yazmasini
# baska bir dosyaya yonlendirebilir). Gunluk ve motor ayarlari kurulum klasorundeki veri\ altinda (salt okunur).
$veri = Join-Path $dest "veri"

if (-not $Install) {
    Set-Location $src
    $build = Join-Path $src "build"
    New-Item -ItemType Directory -Force $build | Out-Null
    $ico = Join-Path $build "uygulama.ico"
    python -c "import sys; sys.path.insert(0, r'$src'); import tepsi; tepsi.make_app_icon(r'$ico')"
    if ($LASTEXITCODE -ne 0) { throw "simge uretilemedi" }
    python -m PyInstaller --noconfirm --clean --onedir --windowed --name KendiControlCenter `
        --icon $ico --add-data "$src\ui;ui" --add-data "$src\lib;lib" `
        --distpath (Join-Path $src "dist") --workpath (Join-Path $build "pyi") --specpath $build `
        control_center.py
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller basarisiz" }
    Write-Host "Derlendi: $dist"
    Start-Process powershell -Verb RunAs -Wait -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$($MyInvocation.MyCommand.Path)`"", "-Install"
    Get-Content (Join-Path $veri "kurulum.txt") -ErrorAction SilentlyContinue
    exit
}

# ------------------------------------------------------------------ yonetici bolumu
$log = Join-Path $veri "kurulum.txt"
New-Item -ItemType Directory -Force $veri | Out-Null
"--- $(Get-Date -Format s)" | Set-Content $log -Encoding utf8
function Log($m) { $m | Add-Content $log -Encoding utf8 }
try {
    # eski motor (betik ya da onceki exe) ve tepsi
    try { Invoke-RestMethod -Method Post -Uri http://127.0.0.1:47815/api/quit -Body '{}' -ContentType application/json -TimeoutSec 3 | Out-Null } catch {}
    Start-Sleep 3
    Get-CimInstance Win32_Process | Where-Object {
        ($_.Name -match '^pythonw?\.exe$' -and $_.CommandLine -match 'control_center\.py') -or $_.Name -eq 'KendiControlCenter.exe'
    } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; Log "durduruldu: $($_.ProcessId) $($_.Name)" }
    Start-Sleep 1

    robocopy $dist $dest /MIR /XD $veri /NFL /NDL /NJH /NJS /NP | Out-Null   # veri\ (ayarlar, gunluk) korunur
    if ($LASTEXITCODE -ge 8) { throw "kopyalama basarisiz (robocopy $LASTEXITCODE)" }
    Log "kopyalandi: $dest"

    # Sonuc cikis kodundan okunur (eskiden kullanicinin yazabildigi task_result.txt'den)
    $p = Start-Process $exe -ArgumentList "--install-task" -Wait -PassThru
    if ($p.ExitCode -ne 0) { throw "gorev kurulamadi (kod $($p.ExitCode)); ayrinti: $(Join-Path $veri 'crash.log')" }
    Log "gorevler: motor (yonetici, oturum acilisinda, cokunce yeniden) + tepsi (normal yetki, oturum acilisinda)"

    # Monster "Fn hotkeys and OSD" paketi (FnKey + eski CC arayuzu) artik gereksiz: Fn tuslarini ve OSD'yi
    # bizim tepsi sureci yapiyor (fntus.py). Ama AcpiBridge1 surucusu paketi Windows'a "donanim destek
    # uygulamasi" olarak bildiriyor (INF AddSoftware) ve Windows onu Store'dan GERI KURABILIR; CCDCHUService de
    # her oturumda FnKey'i baslatmaya calisir. Bu yuzden: 1) Monster'a ozgu programlar ADLARIYLA engellenir
    # (paket geri gelse de calismaz; Windows onlari systray.exe ile "acar", hemen biter), 2) paket kaldirilir.
    # Geri almak: IFEO altindaki bu adlarin Debugger degerini silmek; paket yedegi yedek\FnPaketi.
    # Asagidaki bolum YALNIZCA Clevo tabanli bilgisayarlarda (AcpiBridge aygiti ACPI\CLV0001) calisir.
    $clevo = Get-PnpDevice -InstanceId "ACPI\CLV0001*" -ErrorAction SilentlyContinue
    if ($clevo) {
        $ifeo = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options"
        # AddFn.exe: CCDCHUService'in calistirdigi, paketi yeniden kaydeden yardimci (prefetch'te goruldu)
        foreach ($name in "FnKey.exe", "LaunchFnkey.exe", "AddFn.exe", "CC40.exe", "LoadUI.exe", "PopUI.exe",
                          "cc30wk.exe", "ControlGPU.exe") {
            $k = Join-Path $ifeo $name
            New-Item -Path $k -Force | Out-Null
            Remove-Item (Join-Path $k "KendiCC") -Recurse -ErrorAction SilentlyContinue       # eski tam-yol filtresi
            Remove-ItemProperty -Path $k -Name UseFilter -ErrorAction SilentlyContinue
            New-ItemProperty -Path $k -Name Debugger -Value "$env:SystemRoot\System32\systray.exe" -Force | Out-Null
            Log "engellendi (ad ile): $name"
        }
        Get-Process FnKey, cc30wk, ControlGPU, CC40, LoadUI -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
        $yedek = Join-Path $src "yedek"
        $pkgs = Get-AppxPackage -AllUsers -Name "CLEVOCO.FnhotkeysandOSD" -ErrorAction SilentlyContinue
        foreach ($p in $pkgs) {
            $b = Join-Path $yedek ("FnPaketi\" + $p.PackageFullName)
            if (-not (Test-Path $b)) {
                robocopy $p.InstallLocation $b /E /NFL /NDL /NJH /NJS /NP | Out-Null
                Log "yedeklendi: $b (robocopy $LASTEXITCODE)"
            }
            try { Remove-AppxPackage -Package $p.PackageFullName -AllUsers -ErrorAction Stop; Log "kaldirildi: $($p.PackageFullName)" }
            catch { Log "paket kaldirilamadi: $($_.Exception.Message)" }
        }
        try {  # yeni kullanicilar icin hazir paket kaydi (DISM; bazi ortamlarda "erisim engellendi" verir)
            Get-AppxProvisionedPackage -Online -ErrorAction Stop | Where-Object DisplayName -eq "CLEVOCO.FnhotkeysandOSD" | ForEach-Object {
                Remove-AppxProvisionedPackage -Online -PackageName $_.PackageName -ErrorAction Stop | Out-Null
                Log "hazir paket kaydi kaldirildi: $($_.PackageName)"
            }
        } catch { Log "hazir paket kaydi denetlenemedi: $($_.Exception.Message)" }
        # CCDCHUService'in LaunchFnkey kopyaladigi eski klasor
        $old = "${env:ProgramFiles(x86)}\ControlCenter"
        if (Test-Path $old) {
            robocopy $old (Join-Path $yedek "ControlCenter_x86") /E /NFL /NDL /NJH /NJS /NP | Out-Null
            Remove-Item $old -Recurse -Force -ErrorAction SilentlyContinue
            Log "silindi (yedekli): $old"
        }
        # Teshis: eski paketten hangi programlar calismis (Prefetch, yalnizca yonetici okuyabilir)
        Get-ChildItem "$env:SystemRoot\Prefetch" -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match '^(CC40|LOADUI|POPUI|CC30WK|CC30_BG|FNKEY|CCLNK|LAUNCHFNKEY|ADDFN|BGEXECU|COUWP|PCC|WKEVENT|HYCCD|CONTROLGPU)\.EXE' } |
            Sort-Object LastWriteTime -Descending | ForEach-Object { Log ("prefetch: {0} son {1}" -f $_.Name, $_.LastWriteTime) }
    } else { Log "Clevo AcpiBridge yok: Fn paketi adimi atlandi" }

    $sh = New-Object -ComObject WScript.Shell
    foreach ($dir in [Environment]::GetFolderPath("Programs"), [Environment]::GetFolderPath("Desktop")) {
        Remove-Item (Join-Path $dir "Kendi Control Center.lnk") -ErrorAction SilentlyContinue   # eski ad
    }
    foreach ($lnk in @((Join-Path ([Environment]::GetFolderPath("Programs")) "FCUK Control Center.lnk"),
                       (Join-Path ([Environment]::GetFolderPath("Desktop")) "FCUK Control Center.lnk"))) {
        $s = $sh.CreateShortcut($lnk); $s.TargetPath = $exe; $s.WorkingDirectory = $dest
        $s.IconLocation = "$exe,0"; $s.Description = "FCUK Control Center"; $s.Save()
        Log "kisayol: $lnk"
    }
    # simdi baslat (acilista gorevler kendiliginden baslatir)
    schtasks /run /tn "KendiControlCenter" | Out-Null
    schtasks /run /tn "KendiControlCenter Tepsi" | Out-Null
    Log "TAMAM"
} catch {
    Log "HATA: $($_.Exception.Message)"
}
