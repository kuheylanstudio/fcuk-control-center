# FCUK Control Center - kurulum / kaldırma / rapor motoru.
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazılmıştır. MIT lisansı, bkz. LICENSE.
#
# setup.exe bu betiği yönetici olarak çalıştırır ve çıktısını satır satır gösterir. Her satır "TÜR|metin":
#   ADIM, BILGI, OK, UYARI, HATA. Çıkış kodu: 0 tamam, 2 tamam ama uyarı var, 1 hata.
#
#   -Mode Report     hiçbir şeyi değiştirmez; bulunan eski Control Center bileşenlerini listeler
#   -Mode Install    -Payload <derlenmiş uygulama klasörü>: eski Control Center'ı kaldırır, uygulamayı kurar
#   -Mode Uninstall  FCUK Control Center'ı kaldırır (Uygulamalar listesindeki "Kaldır" bunu çağırır)
#
# ÖNEMLİ: Monster/Clevo Control Center'ın kendi kaldırıcısı (InstallShield + RemoveAPP.exe) ÇALIŞTIRILMAZ.
# O kaldırıcı AcpiBridge sürücü paketlerini de siler; sürücüler gidince fan, güç modu, klavye ışığı ve
# Fn tuşları çalışmaz. Bu betik eski bileşenleri tek tek, yedek alarak kaldırır. AcpiBridge sürücülerine
# ve CCDCHUService hizmetine dokunmaz; sürücüleri önce dışa aktarır, sonunda yerinde olduklarını doğrular,
# eksik çıkarsa yedekten geri kurar.
param(
    [ValidateSet('Install', 'Uninstall', 'Report')][string]$Mode = 'Report',
    [string]$Payload,
    [string]$Version = '',
    [switch]$NoLaunch
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
# setup.exe çıktıyı konsolsuz (boru üzerinden) okur: [Console]::Out o durumda OEM kod sayfasıyla yazar ve
# Türkçe harfler bozulur. Satırlar standart çıktıya doğrudan UTF-8 olarak yazılır.
$script:StdOut = New-Object System.IO.StreamWriter([Console]::OpenStandardOutput(), (New-Object System.Text.UTF8Encoding($false)))
$script:StdOut.AutoFlush = $true

$AppTitle  = 'FCUK Control Center'
$Dest      = Join-Path $env:ProgramFiles 'Kendi Control Center'
$Exe       = Join-Path $Dest 'KendiControlCenter.exe'
$Data      = Join-Path $env:ProgramData 'FCUK Control Center'
$Stamp     = Get-Date -Format 'yyyyMMdd-HHmmss'
$Backup    = Join-Path $Data "yedek\$Stamp"
$LogFile   = Join-Path $Data 'kurulum.log'
$Veri      = Join-Path $Dest 'veri'   # yonetici motorun ayar ve gunlugu (standart kullaniciya salt okunur)
$UninstKey = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\FCUKControlCenter'
$Tasks     = @('KendiControlCenter', 'KendiControlCenter Tepsi')
$Api       = 'http://127.0.0.1:47815'
$OldDir    = Join-Path ${env:ProgramFiles(x86)} 'ControlCenter'
$OldGuid   = '{52CF73F1-9FE1-4917-AE56-55BF319988EC}'
$IsInfo    = Join-Path ${env:ProgramFiles(x86)} "InstallShield Installation Information\$OldGuid"
$Ifeo      = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options'
$SvcCopy   = Join-Path $Data 'DCHUService'

# Monster/Clevo Fn paketi ve eski CC arayüzü: ADLARIYLA engellenir. AcpiBridge1 sürücüsünün INF'i Fn paketini
# Windows'a "donanım destek uygulaması" olarak bildirir; Windows paketi Store'dan geri kurabilir ve
# CCDCHUService her oturumda LaunchFnkey/AddFn çalıştırır. Engel, paket geri gelse de çalışmamasını sağlar.
$Blocked = @('FnKey.exe', 'LaunchFnkey.exe', 'AddFn.exe', 'CC40.exe', 'LoadUI.exe', 'PopUI.exe', 'cc30wk.exe', 'ControlGPU.exe')

# Control Center Package'ın kurduğu uygulama paketleri. Yerini FCUK Control Center'ın tuttukları kaldırılır.
$Replaced = [ordered]@{
    'CLEVOCO.FnhotkeysandOSD'    = 'Fn tuşları ve ekran bildirimi (OSD) + eski Control Center arayüzü'
    'CLEVOCO.ControlCenter3.0'   = 'Control Center 3.0 arayüzü'
    'CLEVOCO.504814C03D814'      = 'Fan hızı ayarı'
    'CLEVOCO.LedKeyboardSetting' = 'Klavye ışığı ayarı'
    'CLEVOCO.EnergySaveUtility'  = 'Enerji tasarrufu modları'
}
# Bunların karşılığı FCUK Control Center'da yok: kuruluysa DOKUNULMAZ.
$Kept = [ordered]@{
    'CLEVOCO.CPUOverclocking'    = 'İşlemci hız aşırtma (güç sınırı/voltaj: FCUK bilerek yapmaz)'
    'CLEVOCO.GPUOverclocking'    = 'Ekran kartı hız aşırtma (FCUK yalnızca saat sınırı koyar)'
    'CLEVOCO.Flexikey'           = 'Flexikey makro tuşları'
    'CLEVOCO.BatteryPackUtility' = 'Pil yardımcı programı'
}
# Eski Control Center sürümlerinin süreçleri (CCDCHUService'in DCHUService.exe'si BİLEREK yok)
$OldProcs = @('CC40', 'LoadUI', 'PopUI', 'FnKey', 'LaunchFnkey', 'AddFn', 'cc30wk', 'ControlGPU', 'CClnk',
              'ControlCenter30', 'ControlCenter3.0', 'FanSpeedSetting', 'LedKeyboardSetting', 'EnergySave',
              'hkysound', 'ComboKey', 'ComboKeyTray', 'hkeytray2', 'hkclipsvc', 'PhoneJack', 'DiskMonitor',
              'FASer', 'powerbiosserver', 'RunAutoInstall', 'PreCC30')
$OldRefRx = '(?i)(' + [regex]::Escape($OldDir) + '|CLEVOCO\.(Fnhotkeys|ControlCenter|504814C03D814|LedKeyboard|EnergySave)|\\CClnk\.exe|\\FnKey\.exe|\\LaunchFnkey\.exe|' + [regex]::Escape($OldGuid) + ')'

$script:Warn = 0
$script:Fail = 0
$script:KeepOldDir = $false
function Out-Line([string]$kind, [string]$msg) {
    $line = "$kind|$msg"
    $script:StdOut.WriteLine($line)
    if ($Mode -ne 'Report') { try { Add-Content -Path $LogFile -Value ("{0} {1}" -f (Get-Date -Format 'HH:mm:ss'), $line) -Encoding UTF8 } catch {} }
}
function Step($m) { Out-Line 'ADIM' $m }
function Info($m) { Out-Line 'BILGI' $m }
function Ok($m)   { Out-Line 'OK' $m }
function Warn($m) { $script:Warn++; Out-Line 'UYARI' $m }
function Fail($m) { $script:Fail++; Out-Line 'HATA' $m }

function Test-Admin {
    $p = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}
function Invoke-Api([string]$path, [string]$method = 'GET', [int]$timeout = 2) {
    try {
        if ($method -eq 'POST') { return Invoke-RestMethod -Method Post -Uri ($Api + $path) -Body '{}' -ContentType 'application/json' -TimeoutSec $timeout }
        return Invoke-RestMethod -Uri ($Api + $path) -TimeoutSec $timeout
    } catch { return $null }
}
function Copy-Tree([string]$src, [string]$dst, [switch]$Mirror, [string[]]$ExcludeDirs = @()) {
    $ra = @($src, $dst, $(if ($Mirror) { '/MIR' } else { '/E' }), '/R:3', '/W:1', '/NFL', '/NDL', '/NJH', '/NJS', '/NP')
    if ($ExcludeDirs.Count) { $ra += '/XD'; $ra += $ExcludeDirs }
    & robocopy.exe @ra | Out-Null
    $rc = $LASTEXITCODE
    $global:LASTEXITCODE = 0
    return ($rc -lt 8)
}
function Get-Clevo { return [bool](Get-PnpDevice -InstanceId 'ACPI\CLV0001*' -ErrorAction SilentlyContinue) }

# ---------------------------------------------------------------------------- envanter
function Get-OldInventory {
    $inv = [ordered]@{}
    $inv.Uninstall = @(foreach ($root in 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall',
                                         'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall') {
        Get-ChildItem $root -ErrorAction SilentlyContinue | ForEach-Object {
            $p = Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue
            if ($_.PSChildName -eq $OldGuid -or "$($p.DisplayName)" -match '^Control Center Package') {
                [pscustomobject]@{ Key = $_.Name; Path = $_.PSPath; Name = "$($p.DisplayName) $($p.DisplayVersion)".Trim() }
            }
        }
    })
    $inv.OldDir = Test-Path $OldDir
    $inv.IsInfo = Test-Path $IsInfo
    try { $all = @(Get-AppxPackage -AllUsers -ErrorAction Stop | Where-Object Name -like 'CLEVOCO.*') }
    catch { $all = @(Get-AppxPackage -ErrorAction SilentlyContinue | Where-Object Name -like 'CLEVOCO.*') }  # yönetici değilse
    $inv.AppxReplaced = @($all | Where-Object { $Replaced.Contains($_.Name) })
    $inv.AppxKept = @($all | Where-Object { $Kept.Contains($_.Name) })
    $inv.AppxOther = @($all | Where-Object { -not $Replaced.Contains($_.Name) -and -not $Kept.Contains($_.Name) })
    try {
        $inv.Provisioned = @(Get-AppxProvisionedPackage -Online -ErrorAction Stop | Where-Object { $Replaced.Contains($_.DisplayName) })
    } catch { $inv.Provisioned = @(); $inv.ProvisionedError = $_.Exception.Message }
    $inv.Services = @(Get-CimInstance Win32_Service -ErrorAction SilentlyContinue | Where-Object { "$($_.PathName)" -like "*$OldDir\*" })
    $inv.Tasks = @(Get-ScheduledTask -ErrorAction SilentlyContinue | Where-Object {
        $_.TaskPath -notlike '\Microsoft\*' -and $Tasks -notcontains $_.TaskName -and
        (@($_.Actions | ForEach-Object { "$($_.Execute) $($_.Arguments)" }) -join ' ') -match $OldRefRx })
    $inv.Run = @(foreach ($k in 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run',
                                'HKLM:\Software\Microsoft\Windows\CurrentVersion\Run',
                                'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run') {
        $p = Get-ItemProperty $k -ErrorAction SilentlyContinue
        if ($p) { foreach ($n in $p.PSObject.Properties) { if ($n.Name -notlike 'PS*' -and "$($n.Value)" -match $OldRefRx) { [pscustomobject]@{ Key = $k; Name = $n.Name; Value = "$($n.Value)" } } } }
    })
    $sh = New-Object -ComObject WScript.Shell
    $dirs = @([Environment]::GetFolderPath('CommonPrograms'), [Environment]::GetFolderPath('Programs'),
              [Environment]::GetFolderPath('CommonDesktopDirectory'), [Environment]::GetFolderPath('Desktop'),
              [Environment]::GetFolderPath('CommonStartup'), [Environment]::GetFolderPath('Startup'))
    $inv.Shortcuts = @(foreach ($d in $dirs | Where-Object { $_ -and (Test-Path $_) } | Select-Object -Unique) {
        Get-ChildItem $d -Recurse -Filter *.lnk -ErrorAction SilentlyContinue | Where-Object {
            try { "$($sh.CreateShortcut($_.FullName).TargetPath)" -match $OldRefRx } catch { $false } }
    })
    $inv.Procs = @(Get-Process -Name $OldProcs -ErrorAction SilentlyContinue)
    $inv.Found = ($inv.Uninstall.Count + [int]$inv.OldDir + [int]$inv.IsInfo + $inv.AppxReplaced.Count + $inv.Provisioned.Count +
                  $inv.Services.Count + $inv.Tasks.Count + $inv.Run.Count + $inv.Shortcuts.Count + $inv.Procs.Count)
    return $inv
}
function Show-Inventory($inv) {
    foreach ($u in $inv.Uninstall) { Info "Kurulu program kaydı: $($u.Name)" }
    if ($inv.OldDir) { Info "Klasör: $OldDir" }
    if ($inv.IsInfo) { Info "InstallShield bilgisi: $IsInfo" }
    foreach ($a in $inv.AppxReplaced) { Info "Uygulama paketi: $($a.Name) $($a.Version) - $($Replaced[$a.Name])" }
    foreach ($a in $inv.Provisioned) { Info "Yeni kullanıcılar için hazır paket: $($a.DisplayName)" }
    foreach ($s in $inv.Services) { Info "Hizmet (eski klasörden çalışıyor): $($s.Name)" }
    foreach ($t in $inv.Tasks) { Info "Zamanlanmış görev: $($t.TaskPath)$($t.TaskName)" }
    foreach ($r in $inv.Run) { Info "Açılış kaydı: $($r.Name)" }
    foreach ($s in $inv.Shortcuts) { Info "Kısayol: $($s.FullName)" }
    foreach ($p in $inv.Procs) { Info "Çalışan süreç: $($p.Name) ($($p.Id))" }
    foreach ($a in $inv.AppxKept) { Info "DOKUNULMAYACAK: $($a.Name) - $($Kept[$a.Name])" }
    foreach ($a in $inv.AppxOther) { Info "DOKUNULMAYACAK (bilinmeyen Clevo paketi): $($a.Name)" }
    if ($inv.ProvisionedError) { Info "Hazır paket listesi okunamadı: $($inv.ProvisionedError)" }
}
function Get-DriverState {
    # AcpiBridge aygıtları ve sürücü paketleri (oemNN.inf). Windows diline bağlı değil (pnputil metni okunmaz).
    return @(Get-CimInstance Win32_PnPSignedDriver -ErrorAction SilentlyContinue | Where-Object { "$($_.DeviceID)" -like 'ACPI\CLV*' } |
        ForEach-Object {
            $dev = Get-PnpDevice -InstanceId $_.DeviceID -ErrorAction SilentlyContinue
            [pscustomobject]@{ Id = $_.DeviceID; Inf = $_.InfName; Ver = $_.DriverVersion; Status = "$($dev.Status)" }
        })
}

# ---------------------------------------------------------------------------- FCUK süreçleri
function Stop-Fcuk {
    if (Invoke-Api '/api/quit' 'POST' 3) { Info 'Çalışan FCUK Control Center motoru kapatıldı'; Start-Sleep -Seconds 3 }
    foreach ($t in $Tasks) { & schtasks.exe /end /tn $t 2>$null | Out-Null }
    $global:LASTEXITCODE = 0
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.Name -eq 'KendiControlCenter.exe' -or ($_.Name -match '^pythonw?\.exe$' -and "$($_.CommandLine)" -match 'control_center\.py')
    } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    for ($i = 0; $i -lt 20 -and (Get-Process KendiControlCenter -ErrorAction SilentlyContinue); $i++) { Start-Sleep -Milliseconds 250 }
}
function Remove-Shortcuts {
    foreach ($d in [Environment]::GetFolderPath('Programs'), [Environment]::GetFolderPath('Desktop'),
                   [Environment]::GetFolderPath('CommonPrograms'), [Environment]::GetFolderPath('CommonDesktopDirectory')) {
        foreach ($n in 'FCUK Control Center.lnk', 'Kendi Control Center.lnk') {
            $f = Join-Path $d $n
            if (Test-Path $f) { Remove-Item $f -Force -ErrorAction SilentlyContinue }
        }
    }
}

# ---------------------------------------------------------------------------- eski Control Center'ı kaldır
function Remove-OldCC($inv, [bool]$clevo) {
    New-Item -ItemType Directory -Force $Backup | Out-Null

    Step 'Eski Control Center süreçleri durduruluyor'
    if ($inv.Procs.Count) {
        $inv.Procs | Stop-Process -Force -ErrorAction SilentlyContinue
        Ok ("Durduruldu: " + (($inv.Procs | ForEach-Object Name | Select-Object -Unique) -join ', '))
    } else { Info 'Çalışan eski süreç yok' }

    Step 'Eski Control Center uygulama paketleri kaldırılıyor'
    foreach ($a in $inv.AppxReplaced) {
        $b = Join-Path $Backup ("paket\" + $a.PackageFullName)
        if ($a.InstallLocation -and (Test-Path $a.InstallLocation)) { [void](Copy-Tree $a.InstallLocation $b) }
        try { Remove-AppxPackage -Package $a.PackageFullName -AllUsers -ErrorAction Stop; Ok "Kaldırıldı: $($a.Name) ($($Replaced[$a.Name]))" }
        catch {
            try { Remove-AppxPackage -Package $a.PackageFullName -ErrorAction Stop; Ok "Kaldırıldı (bu kullanıcı): $($a.Name)" }
            catch { Warn "Paket kaldırılamadı: $($a.Name): $($_.Exception.Message). Adıyla engellendiği için çalışmayacak." }
        }
    }
    foreach ($p in $inv.Provisioned) {
        try { Remove-AppxProvisionedPackage -Online -PackageName $p.PackageName -ErrorAction Stop | Out-Null; Ok "Hazır paket kaydı kaldırıldı: $($p.DisplayName)" }
        catch { Warn "Hazır paket kaydı kaldırılamadı: $($p.DisplayName): $($_.Exception.Message)" }
    }
    if (-not $inv.AppxReplaced.Count -and -not $inv.Provisioned.Count) { Info 'Kaldırılacak uygulama paketi yok' }
    foreach ($a in $inv.AppxKept) { Info "Dokunulmadı: $($a.Name) - $($Kept[$a.Name])" }

    if ($clevo) {
        Step 'Eski Fn / Control Center programları adlarıyla engelleniyor'
        foreach ($name in $Blocked) {
            $k = Join-Path $Ifeo $name
            New-Item -Path $k -Force | Out-Null
            Remove-Item (Join-Path $k 'KendiCC') -Recurse -ErrorAction SilentlyContinue
            Remove-ItemProperty -Path $k -Name UseFilter -ErrorAction SilentlyContinue
            New-ItemProperty -Path $k -Name Debugger -Value "$env:SystemRoot\System32\systray.exe" -PropertyType String -Force | Out-Null
        }
        Ok ("Engellendi: " + ($Blocked -join ', '))
    }

    Step 'Eski Control Center hizmetleri, görevleri ve açılış kayıtları temizleniyor'
    foreach ($s in $inv.Services) {
        # Eski klasörden çalışan bir hizmet (eski sürümlerde CCDCHUService böyleydi) SİLİNMEZ: klasör kaldırılacağı
        # için dosyaları ProgramData'ya kopyalanır ve hizmet oraya yönlendirilir. Donanım hizmeti çalışmaya devam eder.
        try {
            $wasRunning = $s.State -eq 'Running'
            if ($wasRunning) { Stop-Service -Name $s.Name -Force -ErrorAction SilentlyContinue }
            if (-not (Copy-Tree $OldDir $SvcCopy -ExcludeDirs 'AppInstall')) { throw 'dosyalar kopyalanamadı' }
            $newPath = $s.PathName.Replace($OldDir, $SvcCopy)
            Set-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Services\$($s.Name)" -Name ImagePath -Value $newPath
            if ($wasRunning) { Start-Service -Name $s.Name -ErrorAction SilentlyContinue }
            Ok "Hizmet korundu ve taşındı: $($s.Name) -> $newPath"
        } catch { Fail "Hizmet taşınamadı: $($s.Name): $($_.Exception.Message). Eski klasör yerinde bırakılıyor."; $script:KeepOldDir = $true }
    }
    foreach ($t in $inv.Tasks) {
        try { Export-ScheduledTask -TaskName $t.TaskName -TaskPath $t.TaskPath | Set-Content (Join-Path $Backup ("gorev_" + ($t.TaskName -replace '[\\/:*?"<>|]', '_') + '.xml')) -Encoding Unicode } catch {}
        try { Unregister-ScheduledTask -TaskName $t.TaskName -TaskPath $t.TaskPath -Confirm:$false -ErrorAction Stop; Ok "Görev silindi: $($t.TaskName)" }
        catch { Warn "Görev silinemedi: $($t.TaskName): $($_.Exception.Message)" }
    }
    foreach ($r in $inv.Run) {
        "$($r.Key)`t$($r.Name)`t$($r.Value)" | Add-Content (Join-Path $Backup 'acilis_kayitlari.txt') -Encoding UTF8
        Remove-ItemProperty -Path $r.Key -Name $r.Name -ErrorAction SilentlyContinue
        Ok "Açılış kaydı silindi: $($r.Name)"
    }
    foreach ($s in $inv.Shortcuts) {
        Copy-Item $s.FullName $Backup -ErrorAction SilentlyContinue
        Remove-Item $s.FullName -Force -ErrorAction SilentlyContinue
        Ok "Kısayol silindi: $($s.Name)"
    }

    Step 'Eski Control Center dosyaları ve kurulum kaydı kaldırılıyor'
    if ($inv.OldDir -and -not $script:KeepOldDir) {
        if (Copy-Tree $OldDir (Join-Path $Backup 'ControlCenter_x86')) {
            Remove-Item $OldDir -Recurse -Force -ErrorAction SilentlyContinue
            if (Test-Path $OldDir) { Warn "$OldDir tamamen silinemedi (kullanımda dosya olabilir; yeniden başlatınca silinebilir)" }
            else { Ok "Silindi (yedekli): $OldDir" }
        } else { Warn "$OldDir yedeklenemedi; silinmedi" }
    }
    if ($inv.IsInfo) {
        if (Copy-Tree $IsInfo (Join-Path $Backup "InstallShield_$OldGuid")) {
            Remove-Item $IsInfo -Recurse -Force -ErrorAction SilentlyContinue
            Ok 'InstallShield kaldırıcısı silindi (sürücüleri silen RemoveAPP.exe artık çalıştırılamaz)'
        }
    }
    foreach ($u in $inv.Uninstall) {
        & reg.exe export $u.Key (Join-Path $Backup ("kaldirma_kaydi_" + ($u.Key -split '\\')[-1] + '.reg')) /y 2>$null | Out-Null
        $global:LASTEXITCODE = 0
        Remove-Item $u.Path -Recurse -Force -ErrorAction SilentlyContinue
        Ok "Programlar listesinden çıkarıldı: $($u.Name)"
    }
    if (-not ($inv.OldDir -or $inv.IsInfo -or $inv.Uninstall.Count)) { Info 'Eski Control Center kurulum dosyası yok' }
}

function Restore-Drivers($before) {
    Step 'AcpiBridge sürücüleri ve donanım hizmeti doğrulanıyor'
    if (-not $before.Count) { Info 'AcpiBridge aygıtı yok (Clevo/Monster değil): atlandı'; return }
    $after = @(Get-DriverState)
    $missing = @($before | Where-Object {
        $b = $_; $a = $after | Where-Object Id -eq $b.Id | Select-Object -First 1
        -not $a -or -not $a.Inf -or ($a.Status -ne 'OK' -and $b.Status -eq 'OK') })
    if ($missing.Count) {
        Warn ("Sürücü eksik ya da çalışmıyor: " + (($missing | ForEach-Object Id) -join ', ') + ". Yedekten geri kuruluyor.")
        & pnputil.exe /add-driver (Join-Path (Join-Path $Backup 'surucu') '*.inf') /subdirs /install | Out-Null
        & pnputil.exe /scan-devices | Out-Null
        $global:LASTEXITCODE = 0
        Start-Sleep -Seconds 3
        $after = @(Get-DriverState)
    }
    foreach ($b in $before) {
        $a = $after | Where-Object Id -eq $b.Id | Select-Object -First 1
        if ($a -and $a.Inf -and ($a.Status -eq 'OK' -or $b.Status -ne 'OK')) { Ok "$($a.Id): sürücü $($a.Ver) ($($a.Inf)), durum $($a.Status)" }
        else { Fail "$($b.Id): sürücü geri gelmedi. Yedek: $(Join-Path $Backup 'surucu')" }
    }
    $svc = Get-Service CCDCHUService -ErrorAction SilentlyContinue
    if ($svc) { Ok "CCDCHUService yerinde ($($svc.Status))" } else { Info 'CCDCHUService yok (bu modelde olmayabilir)' }
}

# ---------------------------------------------------------------------------- Report
if ($Mode -eq 'Report') {
    $cs = Get-CimInstance Win32_ComputerSystem
    Info ("Bilgisayar: $($cs.Manufacturer) $($cs.Model)")
    if (Get-Clevo) { Info 'Clevo/Monster gömülü denetleyicisi (AcpiBridge) bulundu' }
    else { Info 'Clevo/Monster AcpiBridge aygıtı yok: fan / güç modu / klavye ışığı özellikleri kapalı olur' }
    $inv = Get-OldInventory
    if (-not $inv.Found) { Info 'Eski Control Center bulunamadı (zaten kaldırılmış)' }
    Show-Inventory $inv
    foreach ($d in Get-DriverState) { Info "Korunacak sürücü: $($d.Id) $($d.Ver) ($($d.Inf)), durum $($d.Status)" }
    if (Test-Path $Exe) { Info "FCUK Control Center zaten kurulu: $Dest (güncellenecek)" }
    exit 0
}

if (-not (Test-Admin)) {
    if ($Mode -eq 'Uninstall') {  # Uygulamalar listesinden çağrıldıysa yönetici olarak yeniden başlat
        Start-Process powershell.exe -Verb RunAs -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden', '-File', "`"$PSCommandPath`"", '-Mode', 'Uninstall')
        exit 0
    }
    Fail 'Yönetici yetkisi gerekli'
    exit 1
}
New-Item -ItemType Directory -Force $Data | Out-Null
Add-Content -Path $LogFile -Value "`r`n===== $Mode $(Get-Date -Format s) $AppTitle $Version" -Encoding UTF8

# ---------------------------------------------------------------------------- Uninstall
if ($Mode -eq 'Uninstall') {
    $wsh = New-Object -ComObject WScript.Shell
    if ($wsh.Popup("$AppTitle kaldırılsın mı?`n`nAyarlarınız $Data\ayarlar altına yedeklenir.", 0, $AppTitle, 4 + 32) -ne 6) { exit 0 }
    Step 'FCUK Control Center kapatılıyor'
    Stop-Fcuk
    foreach ($t in $Tasks) { & schtasks.exe /delete /tn $t /f 2>$null | Out-Null }
    $global:LASTEXITCODE = 0
    Ok 'Açılış görevleri silindi'
    Step 'Eski Control Center engelleri kaldırılıyor'
    foreach ($name in $Blocked) {
        $k = Join-Path $Ifeo $name
        $p = Get-ItemProperty $k -ErrorAction SilentlyContinue
        if ($p -and "$($p.Debugger)" -like '*\systray.exe') { Remove-ItemProperty -Path $k -Name Debugger -ErrorAction SilentlyContinue }
    }
    Ok 'Üretici Fn programları yeniden çalışabilir (üretici Control Center yeniden kurulabilir)'
    Remove-Shortcuts
    if (Test-Path $Veri) { [void](Copy-Tree $Veri (Join-Path $Data 'ayarlar')) }
    Remove-Item $Dest -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item $UninstKey -Recurse -Force -ErrorAction SilentlyContinue
    if (Test-Path $Exe) { Warn "$Dest tamamen silinemedi" } else { Ok "Silindi: $Dest" }
    [void]$wsh.Popup("$AppTitle kaldırıldı.`n`nEski Control Center yedekleri: $Data\yedek", 0, $AppTitle, 64)
    exit 0
}

# ---------------------------------------------------------------------------- Install
try {
    if (-not $Payload -or -not (Test-Path (Join-Path $Payload 'KendiControlCenter.exe'))) { throw "Kurulum paketi bozuk: $Payload" }
    if (-not [Environment]::Is64BitOperatingSystem) { throw '64 bit Windows gerekli' }
    $clevo = Get-Clevo
    $cs = Get-CimInstance Win32_ComputerSystem
    Info ("Bilgisayar: $($cs.Manufacturer) $($cs.Model)")

    Step 'Sistem geri yükleme noktası oluşturuluyor'
    try {
        Checkpoint-Computer -Description "$AppTitle kurulumundan once" -RestorePointType MODIFY_SETTINGS -ErrorAction Stop -WarningVariable cw -WarningAction SilentlyContinue
        if ($cw) { Info "Geri yükleme noktası atlandı: $("$cw".Trim()) Kurulum yine de yedek alarak devam ediyor." } else { Ok 'Geri yükleme noktası oluşturuldu' }
    } catch { Info "Geri yükleme noktası oluşturulamadı ($($_.Exception.Message.Trim())). Kurulum yine de yedek alarak devam ediyor." }

    Step 'AcpiBridge sürücüleri yedekleniyor'
    $drivers = @(Get-DriverState)
    New-Item -ItemType Directory -Force $Backup | Out-Null
    if ($drivers.Count) {
        $drv = Join-Path $Backup 'surucu'
        New-Item -ItemType Directory -Force $drv | Out-Null
        foreach ($inf in $drivers | ForEach-Object Inf | Select-Object -Unique) {
            & pnputil.exe /export-driver $inf $drv | Out-Null
            if ($LASTEXITCODE -eq 0) { Ok "Dışa aktarıldı: $inf" } else { Warn "Dışa aktarılamadı: $inf (pnputil $LASTEXITCODE)" }
            $global:LASTEXITCODE = 0
        }
        $drivers | Format-Table -AutoSize | Out-String | Set-Content (Join-Path $Backup 'suruculer.txt') -Encoding UTF8
    } else { Info 'AcpiBridge aygıtı yok: atlandı' }

    Step 'Eski Control Center taranıyor'
    $inv = Get-OldInventory
    if ($inv.Found) { Show-Inventory $inv } else { Info 'Eski Control Center bulunamadı (zaten kaldırılmış); yalnızca kalıntı engelleri uygulanacak' }

    Step 'Çalışan FCUK Control Center kapatılıyor'
    Stop-Fcuk
    Ok 'Kapatıldı'

    Remove-OldCC $inv $clevo
    Restore-Drivers $drivers

    Step "Dosyalar kopyalanıyor: $Dest"
    if (-not (Copy-Tree $Payload $Dest -Mirror -ExcludeDirs $Veri)) {
        Start-Sleep -Seconds 2; Stop-Fcuk
        if (-not (Copy-Tree $Payload $Dest -Mirror -ExcludeDirs $Veri)) { throw "Dosyalar kopyalanamadı: $Dest" }
    }
    Copy-Item $PSCommandPath (Join-Path $Dest 'kaldir.ps1') -Force
    $root = $Payload.TrimEnd('\')
    $files = @(Get-ChildItem $root -Recurse -File)
    $bad = @($files | Where-Object {
        $t = Join-Path $Dest $_.FullName.Substring($root.Length + 1)
        -not (Test-Path -LiteralPath $t) -or (Get-Item -LiteralPath $t).Length -ne $_.Length })
    if ($bad.Count) { throw "$($bad.Count) dosya doğru kopyalanmadı (ilk: $($bad[0].Name))" }
    Ok ("Kopyalandı ve doğrulandı: {0} dosya" -f $files.Count)
    if ($clevo -and -not (Test-Path (Join-Path $Dest '_internal\lib\InsydeDCHU.dll'))) { Warn 'InsydeDCHU.dll pakette yok: fan / güç modu / klavye ışığı çalışmaz' }

    Step 'Windows açılış görevleri kuruluyor (motor yönetici, tepsi normal yetki)'
    # Sonuc, kullanicinin yazabildigi bir dosyadan degil surecin cikis kodundan okunur
    $p = Start-Process $Exe -ArgumentList '--install-task' -WorkingDirectory $Dest -Wait -PassThru
    if ($p.ExitCode -ne 0) { throw "Görevler kurulamadı (çıkış $($p.ExitCode)); ayrıntı: $(Join-Path $Veri 'crash.log')" }
    foreach ($t in $Tasks) { if (-not (Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue)) { throw "Görev yok: $t" } }
    Ok "Görevler: $($Tasks -join ', ')"

    Step 'Kısayollar ve Uygulamalar listesi kaydı'
    Remove-Shortcuts
    $sh = New-Object -ComObject WScript.Shell
    foreach ($lnk in (Join-Path ([Environment]::GetFolderPath('Programs')) "$AppTitle.lnk"),
                     (Join-Path ([Environment]::GetFolderPath('Desktop')) "$AppTitle.lnk")) {
        $s = $sh.CreateShortcut($lnk); $s.TargetPath = $Exe; $s.WorkingDirectory = $Dest
        $s.IconLocation = "$Exe,0"; $s.Description = $AppTitle; $s.Save()
    }
    Ok 'Başlat menüsü ve masaüstü kısayolu'
    New-Item -Path $UninstKey -Force | Out-Null
    $size = [int]((Get-ChildItem $Dest -Recurse -File | Measure-Object Length -Sum).Sum / 1KB)
    $props = @{
        DisplayName = $AppTitle; DisplayVersion = $Version; Publisher = $AppTitle; DisplayIcon = "$Exe,0"
        InstallLocation = $Dest; InstallDate = (Get-Date -Format 'yyyyMMdd')
        UninstallString = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Dest\kaldir.ps1`" -Mode Uninstall"
    }
    foreach ($k in $props.Keys) { New-ItemProperty -Path $UninstKey -Name $k -Value $props[$k] -PropertyType String -Force | Out-Null }
    foreach ($k in 'NoModify', 'NoRepair') { New-ItemProperty -Path $UninstKey -Name $k -Value 1 -PropertyType DWord -Force | Out-Null }
    New-ItemProperty -Path $UninstKey -Name EstimatedSize -Value $size -PropertyType DWord -Force | Out-Null
    Ok 'Ayarlar > Uygulamalar listesine eklendi'

    if ($NoLaunch) { Info 'Başlatma atlandı (-NoLaunch)' }
    else {
        Step 'Başlatılıyor ve doğrulanıyor'
        foreach ($t in $Tasks) { & schtasks.exe /run /tn $t | Out-Null }
        $global:LASTEXITCODE = 0
        $ping = $null
        for ($i = 0; $i -lt 40 -and -not $ping; $i++) { Start-Sleep -Milliseconds 500; $ping = Invoke-Api '/api/ping' }
        if (-not $ping) { throw 'Motor 20 saniyede yanıt vermedi' }
        if ($ping.path -notlike "$Dest*") { Warn "Yanıt veren motor başka klasörden: $($ping.path)" }
        if ($ping.admin) { Ok "Motor çalışıyor: sürüm $($ping.version), yönetici modu" } else { Warn 'Motor çalışıyor ama yönetici değil (ekran kartı saat sınırı ve NVIDIA ayarları yazılamaz)' }
        $st = Invoke-Api '/api/state' 'GET' 10
        if ($clevo) {
            if ($st -and $st.ec) { Ok "Gömülü denetleyici bağlı: $($st.device)" } else { Fail 'Gömülü denetleyiciye bağlanılamadı (fan / güç modu / klavye ışığı çalışmaz)' }
            $now = $null
            for ($i = 0; $i -lt 10 -and -not ($now -and $null -ne $now.cpu_rpm); $i++) { Start-Sleep -Milliseconds 700; $now = Invoke-Api '/api/now' }
            if ($now -and $null -ne $now.cpu_rpm) { Ok "Fan okuması: işlemci $($now.cpu_rpm) RPM, ekran kartı $($now.gpu_rpm) RPM, işlemci $($now.cpu_temp) °C" }
            else { Warn 'Fan okuması henüz gelmedi' }
        } elseif ($st) { Ok "Arayüz durumu okundu: $($st.device)" }
        $tray = $null
        for ($i = 0; $i -lt 20 -and -not $tray; $i++) {
            $tray = Get-CimInstance Win32_Process -Filter "Name='KendiControlCenter.exe'" | Where-Object { "$($_.CommandLine)" -match '--tray' }
            if (-not $tray) { Start-Sleep -Milliseconds 500 }
        }
        if ($tray) { Ok 'Tepsi simgesi ve Fn tuşu dinleyicisi çalışıyor' } else { Warn 'Tepsi süreci görülmedi' }
        $left = @(Get-Process -Name $OldProcs -ErrorAction SilentlyContinue)
        if ($left.Count) { Warn ("Hâlâ çalışan eski süreç: " + (($left | ForEach-Object Name) -join ', ')) } else { Ok 'Eski Control Center süreçlerinden hiçbiri çalışmıyor' }
    }
    $after = Get-OldInventory
    $rest = $after.Uninstall.Count + [int]$after.IsInfo + $after.AppxReplaced.Count + $after.Tasks.Count + $after.Run.Count + $after.Shortcuts.Count
    if ($rest) { Warn "Eski Control Center'dan $rest kalıntı kaldı:"; Show-Inventory $after } else { Ok "Eski Control Center'dan kalıntı yok" }
    Info "Yedekler: $Backup"
    Info "Kayıt: $LogFile"
} catch {
    Fail $_.Exception.Message
}
if ($script:Fail) { exit 1 }
if ($script:Warn) { exit 2 }
exit 0
