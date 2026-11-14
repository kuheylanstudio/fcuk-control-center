# FCUK Control Center: exe'yi derler ve kurar. Kod degistikten sonra yeniden calistirmak yeterli.
# Claude Opus 5.5 (Anthropic) ile yazildi. MIT lisansi, bkz. LICENSE.
#   powershell -ExecutionPolicy Bypass -File kur.ps1
# 1) (normal kullanici) PyInstaller ile dist\FCUKControlCenter\ derlenir.
# 2) (yonetici, tek UAC) eski motor durdurulur, C:\Program Files\FCUK Control Center'a kopyalanir,
#    yonetici gorevi exe'ye yonlendirilir, Baslat menusu ve masaustu kisayollari olusturulur.
param([switch]$Install)
$ErrorActionPreference = "Stop"
$src  = Split-Path -Parent $MyInvocation.MyCommand.Path
$dist = Join-Path $src "dist\FCUKControlCenter"
$dest = Join-Path $env:ProgramFiles "FCUK Control Center"
$exe  = Join-Path $dest "FCUKControlCenter.exe"
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
    python -m PyInstaller --noconfirm --clean --onedir --windowed --name FCUKControlCenter `
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
        ($_.Name -match '^pythonw?\.exe$' -and $_.CommandLine -match 'control_center\.py') -or $_.Name -in 'FCUKControlCenter.exe', 'KendiControlCenter.exe'
    } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; Log "durduruldu: $($_.ProcessId) $($_.Name)" }
    Start-Sleep 1

    robocopy $dist $dest /MIR /XD $veri /NFL /NDL /NJH /NJS /NP | Out-Null   # veri\ (ayarlar, gunluk) korunur
    if ($LASTEXITCODE -ge 8) { throw "kopyalama basarisiz (robocopy $LASTEXITCODE)" }
    Log "kopyalandi: $dest"
    $eski = Join-Path $env:ProgramFiles "Kendi Control Center"   # onceki surumun klasoru
    if (Test-Path $eski) {
        if ((Test-Path "$eski\veri") -and -not (Test-Path "$veri\config.json")) { robocopy "$eski\veri" $veri /E /NFL /NDL /NJH /NJS /NP | Out-Null }
        Remove-Item $eski -Recurse -Force -ErrorAction SilentlyContinue; Log "onceki surum silindi: $eski"
    }

    # Sonuc cikis kodundan okunur (eskiden kullanicinin yazabildigi task_result.txt'den)
    $p = Start-Process $exe -ArgumentList "--install-task" -Wait -PassThru
    if ($p.ExitCode -ne 0) { throw "gorev kurulamadi (kod $($p.ExitCode)); ayrinti: $(Join-Path $veri 'crash.log')" }
    Log "gorevler: motor (yonetici, oturum acilisinda, cokunce yeniden) + tepsi (normal yetki, oturum acilisinda)"

    # Monster "Fn hotkeys and OSD" paketi (FnKey + eski CC arayuzu) artik gereksiz: Fn tuslarini ve OSD'yi
    # bizim tepsi sureci yapiyor (fntus.py). Ama AcpiBridge1 surucusu paketi Windows'a "donanim destek
    # uygulamasi" olarak bildiriyor (INF AddSoftware) ve Windows onu Store'dan GERI KURABILIR; CCDCHUService de
    # her oturumda FnKey'i baslatmaya calisir. Bu yuzden: 1) Monster programlari IFEO'da TAM YOLLARIYLA
    # engellenir (engelle.py; paket kaldirilmadan ONCE, yollar diskteyken), 2) paket kaldirilir. Ad ile engel
    # kullanilmaz: ayni adi tasiyan baska bir yazilimi da durdururdu. Paket yeni bir surum klasorune geri
    # gelirse yonetici motor yeni yolu acilista ve 30 dakikada bir engeller.
    # Geri almak: IFEO altindaki bu adlarin FCUKCC... alt anahtarlarini silmek; paket yedegi yedek\FnPaketi.
    # Asagidaki bolum YALNIZCA Clevo tabanli bilgisayarlarda (AcpiBridge aygiti ACPI\CLV0001) calisir.
    $clevo = Get-PnpDevice -InstanceId "ACPI\CLV0001*" -ErrorAction SilentlyContinue
    if ($clevo) {
        $p = Start-Process $exe -ArgumentList "--block-fn" -Wait -PassThru
        if ($p.ExitCode -eq 0) { Log "Fn programlari tam yollariyla engellendi (ayrinti: veri\crash.log)" }
        else { Log "UYARI: Fn engelleme basarisiz (kod $($p.ExitCode)); ayrinti: veri\crash.log" }
        # Calisan kopyalar yalnizca Monster klasorlerindeyse durdurulur (ayni adli baska programlara dokunulmaz)
        Get-Process FnKey, LaunchFnkey, AddFn, cc30wk, ControlGPU, CC40, LoadUI, PopUI -ErrorAction SilentlyContinue |
            Where-Object { $_.Path -and ($_.Path -like "*\WindowsApps\CLEVOCO.*" -or $_.Path -like "*\ControlCenter\*" -or
                                         $_.Path -like "*\DriverStore\*") } |
            Stop-Process -Force -ErrorAction SilentlyContinue
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
    schtasks /run /tn "FCUK Control Center" | Out-Null
    schtasks /run /tn "FCUK Control Center Tepsi" | Out-Null
    Log "TAMAM"
} catch {
    Log "HATA: $($_.Exception.Message)"
}
