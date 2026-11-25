# FCUK Control Center - kurulum / kaldırma / rapor motoru.
# Bu dosya Anthropic'in Claude Opus 5.5 yapay zeka modeliyle yazılmıştır. MIT lisansı, bkz. LICENSE.
#
# setup.exe bu betiği yönetici olarak çalıştırır ve çıktısını satır satır gösterir. Her satır "TÜR|metin":
#   ADIM, BILGI, OK, UYARI, HATA. Çıkış kodu: 0 tamam, 2 tamam ama uyarı var, 1 hata.
#
#   -Mode Report     hiçbir şeyi değiştirmez; bulunan eski Control Center bileşenlerini listeler
#   -Mode Install    -Payload <derlenmiş uygulama klasörü>: eski Control Center'ı kaldırır, uygulamayı kurar
#                    -RestorePoint ile önce sistem geri yükleme noktası oluşturur
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
    [switch]$NoLaunch,
    [switch]$RestorePoint,  # sistem geri yükleme noktası (isteğe bağlı; kurulum penceresindeki kutu)
    # Eski Control Center'ın geri yüklenmesini engelle (yalnızca Clevo; kurulum penceresindeki kutu).
    # Keep: önceki seçimi korur (uygulama içi güncelleme ve sessiz kurulum bunu kullanır).
    [ValidateSet('On', 'Off', 'Keep')][string]$CCGuard = 'Keep'
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
# setup.exe çıktıyı konsolsuz (boru üzerinden) okur: [Console]::Out o durumda OEM kod sayfasıyla yazar ve
# Türkçe harfler bozulur. Satırlar standart çıktıya doğrudan UTF-8 olarak yazılır.
$script:StdOut = New-Object System.IO.StreamWriter([Console]::OpenStandardOutput(), (New-Object System.Text.UTF8Encoding($false)))
$script:StdOut.AutoFlush = $true

$AppTitle  = 'FCUK Control Center'
$Dest      = Join-Path $env:ProgramFiles 'FCUK Control Center'
$Exe       = Join-Path $Dest 'FCUKControlCenter.exe'
$OldDest   = Join-Path $env:ProgramFiles 'Kendi Control Center'   # onceki surumlerin kurulum klasoru
$Data      = Join-Path $env:ProgramData 'FCUK Control Center'
$Stamp     = Get-Date -Format 'yyyyMMdd-HHmmss'
$Backup    = Join-Path $Data "yedek\$Stamp"
$LogFile   = Join-Path $Data 'kurulum.log'
$Veri      = Join-Path $Dest 'veri'   # yonetici motorun ayar ve gunlugu (standart kullaniciya salt okunur)
$UninstKey = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\FCUKControlCenter'
$Tasks     = @('FCUK Control Center', 'FCUK Control Center Tepsi')
$OldTasks  = @('KendiControlCenter', 'KendiControlCenter Tepsi')   # onceki surumlerin gorev adlari
$ExeNames  = @('FCUKControlCenter', 'KendiControlCenter')
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
$script:ApiError = ''
function Invoke-Api([string]$path, [string]$method = 'GET', [int]$timeout = 2) {
    $script:ApiError = ''
    try {
        if ($method -eq 'POST') { return Invoke-RestMethod -Method Post -Uri ($Api + $path) -Body '{}' -ContentType 'application/json' -TimeoutSec $timeout }
        return Invoke-RestMethod -Uri ($Api + $path) -TimeoutSec $timeout
    } catch { $script:ApiError = "$($_.Exception.Message)"; return $null }
}
function Copy-Tree([string]$src, [string]$dst, [switch]$Mirror, [string[]]$ExcludeDirs = @(), [string[]]$ExcludeFiles = @()) {
    $ra = @($src, $dst, $(if ($Mirror) { '/MIR' } else { '/E' }), '/R:3', '/W:1', '/NFL', '/NDL', '/NJH', '/NJS', '/NP')
    if ($ExcludeDirs.Count) { $ra += '/XD'; $ra += $ExcludeDirs }
    if ($ExcludeFiles.Count) { $ra += '/XF'; $ra += $ExcludeFiles }
    & robocopy.exe @ra | Out-Null
    $rc = $LASTEXITCODE
    $global:LASTEXITCODE = 0
    return ($rc -lt 8)
}
# Windows PowerShell 5.1'de, ErrorActionPreference 'Stop' iken bir yerel programin hata akisini (2>$null) yonlendirmek
# o programin hata metnini KESEN bir hataya cevirir. Ornek: olmayan bir gorev icin schtasks /end, "ERROR: Sistem
# belirtilen dosyayi bulamiyor" yazar ve tum kurulum durur. Sonucu onemsiz (temizlik) cagrilari bununla calisir.
function Invoke-Quiet([string]$exe, [string[]]$argv) {
    $eap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $exe @argv 2>&1 | Out-Null } finally { $ErrorActionPreference = $eap }
    $rc = $LASTEXITCODE
    $global:LASTEXITCODE = 0
    return $rc
}
# Clevo/Monster gömülü denetleyici köprüsü TAKILI mı (yalnızca kayıtlı değil). Değilse bu betik hiçbir üretici
# yazılımına, sürücüsüne, hizmetine ya da IFEO kaydına dokunmaz: Armoury Crate, Lenovo Vantage, MSI Center, Dell/
# Alienware, HP Omen, Acer NitroSense ve diğer Control Center türevleri olduğu gibi çalışmaya devam eder.
function Get-Clevo { return [bool](Get-PnpDevice -PresentOnly -InstanceId 'ACPI\CLV*' -ErrorAction SilentlyContinue) }

# ---------------------------------------------------------------------------- cihaz tespiti
# Tek setup.exe her modele kurulur; kurulum bilgisayarın hangi denetleyici arayüzünü taşıdığını DONANIMDAN tespit
# eder (yalnızca üretici adına güvenilmez: arayüzün WMI sınıfı da bulunmalı) ve YALNIZCA o cihaza ait adımları
# uygular. Clevo adımları (eski Monster CC'yi kaldırma, Fn engelleri, AcpiBridge sürücü yedeği, InsydeDCHU.dll)
# yalnızca 'clevo'da çalışır; başka bir markada bunların hiçbiri yapılmaz ve Clevo DLL'leri diske bile kopyalanmaz.
# Sıra önemli: Clevo köprüsü (ACPI\CLV) takılıysa üretici adı ne olursa olsun Clevo yolu seçilir (Monster, bazı
# Gigabyte/XMG modelleri Clevo tabanlıdır).
#   Sinif    root\wmi altında bulunması gereken denetleyici sınıfı
#   Uretici  Win32_ComputerSystem.Manufacturer için düzenli ifade;  Model: Model + SystemFamily için (isteğe bağlı)
#   Uygulama üreticinin kendi uygulaması/hizmeti (Win32_Service ve Programlar listesinde ad deseni). DOKUNULMAZ;
#            yalnızca aynı anda fan/güç modu ayarlarsa çakışabileceği bildirilir.
#   Kur      markaya özel kurulum adımı (scriptblock, isteğe bağlı; $Dest kurulduktan sonra çağrılır). Marka dalları
#            gerekirse buraya ekler. Clevo dışındaki hiçbir adım üretici yazılımını, sürücüsünü ya da hizmetini
#            kaldırmamalı/değiştirmemeli.
$Markalar = [ordered]@{
    clevo     = @{ Ad = 'Clevo / Monster';        Sinif = $null;                   Uretici = $null;               Model = $null
                   Uygulama = $null; Kur = $null }
    alienware = @{ Ad = 'Alienware / Dell G';     Sinif = 'AWCCWmiMethodFunction'; Uretici = 'Alienware|Dell';    Model = $null
                   Uygulama = 'Alienware Command Center|AWCC|Alienware Update'; Kur = $null }
    asus      = @{ Ad = 'Asus ROG / TUF';         Sinif = 'AsusAtkWmi_WMNB';       Uretici = '^\s*ASUSTeK';       Model = $null
                   Uygulama = 'Armoury Crate|ArmouryCrate|ASUS Optimization|ROG Live'; Kur = $null }
    # IdeaPad: arayüzler (GameZone WMI ya da \\.\EnergyDrv) modele göre değişir ve uygulama bunları kendisi yalnızca
    # okuyarak sınar; kurulum burada yalnızca bilgi verir, IdeaPad için hiçbir kurulum adımı donanıma dokunmaz.
    ideapad   = @{ Ad = 'Lenovo IdeaPad';         Sinif = $null;                   Uretici = '^\s*LENOVO\s*$';   Model = 'IdeaPad'
                   SadeceModel = $true; Arayuz = 'Lenovo GameZone WMI / Energy Management sürücüsü'
                   Uygulama = 'Lenovo Vantage|ImControllerService|Lenovo Hotkeys|Energy Management'; Kur = $null }
    lenovo    = @{ Ad = 'Lenovo Legion';          Sinif = 'LENOVO_GAMEZONE_DATA';  Uretici = '^\s*LENOVO\s*$';   Model = 'Legion'
                   Uygulama = 'Lenovo Vantage|Legion Zone|Lenovo Legion|ImControllerService|Lenovo Hotkeys'; Kur = $null }
    msi       = @{ Ad = 'MSI';                    Sinif = 'MSI_ACPI';              Uretici = 'Micro-Star|^MSI';   Model = $null
                   Uygulama = 'MSI Center|MSI Central|Dragon Center|MSI SDK'; Kur = $null }
    hp        = @{ Ad = 'HP Omen / Victus';       Sinif = 'hpqBIntM';              Uretici = '^HP|Hewlett';       Model = 'OMEN|Victus'
                   Uygulama = 'OMEN Gaming Hub|OMEN Command Center|HP Omen|OmenCommandCenter|HP Gaming'; Kur = $null }
    acer      = @{ Ad = 'Acer Predator / Nitro';  Sinif = 'AcerGamingFunction';    Uretici = 'Acer';              Model = 'Predator|Nitro'
                   Uygulama = 'PredatorSense|NitroSense|Acer Quick Access'; Kur = $null }
    gigabyte  = @{ Ad = 'Gigabyte Aorus / Aero';  Sinif = 'GB_WMIACPI_Get';        Uretici = 'GIGABYTE|AORUS';    Model = $null
                   Uygulama = 'Gigabyte Control Center|GIGABYTE Control Center|AORUS Control Center'; Kur = $null }
    diger     = @{ Ad = 'Diğer';                  Sinif = $null;                   Uretici = $null;               Model = $null
                   Uygulama = $null; Kur = $null }
}
# Sınıfın yalnızca tanımlı olması yetmez, bir ÖRNEĞİ olmalı (uygulamanın çalışma zamanı tespitiyle aynı ölçüt;
# yoksa setup markayı tanıyıp uygulama denetleyicisiz açılabilirdi)
function Test-WmiSinif([string]$name) {
    try { return [bool](Get-CimInstance -Namespace 'root\wmi' -ClassName $name -ErrorAction Stop | Select-Object -First 1) } catch { return $false }
}
function Get-Cihaz {
    if (Get-Clevo) { return 'clevo' }
    $cs = Get-CimInstance Win32_ComputerSystem -ErrorAction SilentlyContinue
    $uretici = "$($cs.Manufacturer)"
    # Lenovo'da Model makine tipidir (82JW); "Legion" SystemFamily ya da ürün sürümünde (SystemVersion) geçer
    $csp = Get-CimInstance Win32_ComputerSystemProduct -ErrorAction SilentlyContinue
    $model = "$($cs.Model) $($cs.SystemFamily) $($csp.Version) $($csp.Name)"
    foreach ($k in $Markalar.Keys) {
        $m = $Markalar[$k]
        if (-not $m.Sinif -and -not $m.SadeceModel) { continue }
        if ($m.Uretici -and $uretici -notmatch $m.Uretici) { continue }
        if ($m.Model -and $model -notmatch $m.Model) { continue }
        if ($m.SadeceModel -and $model -match 'Legion|LOQ') { continue }  # IdeaPad adı geçen Legion/LOQ değil
        if (-not $m.Sinif -or (Test-WmiSinif $m.Sinif)) { return $k }
    }
    return 'diger'
}
# Üreticinin kendi uygulaması kurulu/çalışıyor mu (yalnızca bilgi; hiçbir şey kaldırılmaz, durdurulmaz)
function Get-UreticiUygulamasi([string]$kind) {
    $rx = $Markalar[$kind].Uygulama
    if (-not $rx) { return @() }
    $bulunan = @()
    $bulunan += @(Get-CimInstance Win32_Service -ErrorAction SilentlyContinue |
        Where-Object { "$($_.DisplayName) $($_.Name)" -match $rx } | ForEach-Object { "hizmet: $($_.DisplayName) ($($_.State))" })
    foreach ($root in 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall',
                      'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall') {
        $bulunan += @(Get-ChildItem $root -ErrorAction SilentlyContinue | ForEach-Object {
            $n = "$((Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue).DisplayName)"
            if ($n -and $n -match $rx) { "program: $n" } })
    }
    $arx = $rx -replace ' ', ''   # paket adlarında boşluk yok (ör. B9ECED6F.ArmouryCrate)
    try { $bulunan += @(Get-AppxPackage -AllUsers -ErrorAction Stop | Where-Object { $_.Name -match $arx } | ForEach-Object { "uygulama paketi: $($_.Name)" }) } catch {}
    return @($bulunan | Select-Object -Unique)
}
function Show-Marka([string]$kind) {
    $m = $Markalar[$kind]
    if ($kind -eq 'diger') {
        Info 'Desteklenen bir denetleyici arayüzü bulunamadı (Clevo, Alienware, Asus, Lenovo, MSI, HP, Acer, Gigabyte): bu bilgisayarın kendi uygulamasına, sürücülerine ve hizmetlerine DOKUNULMAYACAK'
        Info 'Çalışacak: canlı izleme, işlemci ve ekran kartı ayarları, performans profilleri (işlemci / ekran kartı / ekran), ses ve ekran'
        Info 'Bu bilgisayarda olmayan (arayüzde "kullanılamaz" görünür, hiçbir komut gönderilmez): fan eğrisi, denetleyici güç modu, klavye RGB, Fn tuşları'
        return
    }
    $arayuz = if ($m.Sinif) { "root\wmi $($m.Sinif)" } else { $m.Arayuz }
    Info "Cihaz: $($m.Ad) (denetleyici arayüzü: $arayuz)"
    Info 'Yalnızca bu cihaza ait adımlar uygulanır: Monster/Clevo bileşenleri kurulmaz, hiçbir üretici yazılımı kaldırılmaz'
    $apps = @(Get-UreticiUygulamasi $kind)
    foreach ($a in $apps) { Info "Üretici yazılımı (DOKUNULMAYACAK): $a" }
    if ($apps.Count) {
        Info 'Üretici yazılımı da fan / güç modu / klavye ışığı ayarlıyorsa son ayarlayanın değeri geçerli olur; çakışma görürseniz o yazılımdaki aynı ayarı kapatın'
    }
}
# Clevo'ya özgü dosyalar (uygulama klasörüne göre): başka bir markada diske kopyalanmaz
$ClevoDosyalari = @('_internal\lib\InsydeDCHU.dll', '_internal\lib\GetProductdll.dll')

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
    foreach ($t in $Tasks + $OldTasks) { [void](Invoke-Quiet 'schtasks.exe' @('/end', '/tn', $t)) }
    $global:LASTEXITCODE = 0
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        ($ExeNames | ForEach-Object { "$_.exe" }) -contains $_.Name -or ($_.Name -match '^pythonw?\.exe$' -and "$($_.CommandLine)" -match 'control_center\.py')
    } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    for ($i = 0; $i -lt 20 -and (Get-Process $ExeNames -ErrorAction SilentlyContinue); $i++) { Start-Sleep -Milliseconds 250 }
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

    if ($clevo) {
        # Paketler kaldırılmadan ÖNCE (yollar diskteyken): Monster programları IFEO'da TAM YOLLARIYLA engellenir.
        # Ad ile engel kullanılmaz; aynı adı taşıyan başka bir yazılımı da durdururdu. Paket geri kurulursa
        # yönetici motor yeni yolu açılışta ve 30 dakikada bir engeller (engelle.py).
        Step 'Eski Fn / Control Center programları tam yollarıyla engelleniyor'
        $bp = Start-Process (Join-Path $Payload 'FCUKControlCenter.exe') -ArgumentList '--block-fn' -Wait -PassThru
        if ($bp.ExitCode -eq 0) { Ok ('Engellendi: ' + ($Blocked -join ', ') + ' (yalnızca Monster klasörlerindeki kopyalar)') }
        else { Warn "Tam yol engeli yazılamadı (kod $($bp.ExitCode)); motor ilk açılışta yeniden dener" }
    }

    Step 'Eski Control Center uygulama paketleri kaldırılıyor'
    foreach ($a in $inv.AppxReplaced) {
        $b = Join-Path $Backup ("paket\" + $a.PackageFullName)
        if ($a.InstallLocation -and (Test-Path $a.InstallLocation)) { [void](Copy-Tree $a.InstallLocation $b) }
        try { Remove-AppxPackage -Package $a.PackageFullName -AllUsers -ErrorAction Stop; Ok "Kaldırıldı: $($a.Name) ($($Replaced[$a.Name]))" }
        catch {
            try { Remove-AppxPackage -Package $a.PackageFullName -ErrorAction Stop; Ok "Kaldırıldı (bu kullanıcı): $($a.Name)" }
            catch { Warn "Paket kaldırılamadı: $($a.Name): $($_.Exception.Message). Tam yoluyla engellendiği için çalışmayacak." }
        }
    }
    foreach ($p in $inv.Provisioned) {
        try { Remove-AppxProvisionedPackage -Online -PackageName $p.PackageName -ErrorAction Stop | Out-Null; Ok "Hazır paket kaydı kaldırıldı: $($p.DisplayName)" }
        catch { Warn "Hazır paket kaydı kaldırılamadı: $($p.DisplayName): $($_.Exception.Message)" }
    }
    if (-not $inv.AppxReplaced.Count -and -not $inv.Provisioned.Count) { Info 'Kaldırılacak uygulama paketi yok' }
    foreach ($a in $inv.AppxKept) { Info "Dokunulmadı: $($a.Name) - $($Kept[$a.Name])" }


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
        [void](Invoke-Quiet 'reg.exe' @('export', $u.Key, (Join-Path $Backup ("kaldirma_kaydi_" + ($u.Key -split '\\')[-1] + '.reg')), '/y'))
        $global:LASTEXITCODE = 0
        Remove-Item $u.Path -Recurse -Force -ErrorAction SilentlyContinue
        Ok "Programlar listesinden çıkarıldı: $($u.Name)"
    }
    if (-not ($inv.OldDir -or $inv.IsInfo -or $inv.Uninstall.Count)) { Info 'Eski Control Center kurulum dosyası yok' }
}

# ---------------------------------------------------------------------------- geri yükleme engeli
# Eski CC'yi geri getirebilen tek otomatik yol: AcpiBridge1.inf "AddSoftware" -> pfn://CLEVOCO.FnhotkeysandOSD_...
# (Store'dan donanım destek uygulaması; sürücü yeniden kurulunca ya da Windows Update güncelleyince). Defender
# yazılım kurmaz; Store yalnızca kurulu paketleri günceller. Katmanlar, yalnızca FCUK'un yerini tuttuğu paketler için:
#   D: Appx Deprovisioned kaydı (Windows'un "yeniden sağlama" engeli; özellik güncellemesi / yeni kullanıcı)
#   I: DeviceSetup\InstalledPfns = 1 (Windows'un "bu donanım uygulaması işlendi" işareti)
#   ve yönetici motorun bekçisi (engelle.py guard_check): paket yine gelirse tam yoluyla engeller ve kaldırır.
# Geri alınabilir: yalnızca BİZİM oluşturduğumuz kayıtlar CCKorumaKayit'ta tutulur ve 'Off' / kaldırma onları siler.
$GuardKey   = 'HKLM:\SOFTWARE\FCUK Control Center'
$Deprov     = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Appx\AppxAllUserStore\Deprovisioned'
$Pfns       = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\DeviceSetup\InstalledPfns'
$ClevoPubId = '6h6z29zh29qx0'   # CLEVOCO paketlerinin yayıncı kimliği (AcpiBridge1.inf SoftwareID'de görülür)

function Get-GuardState {
    $p = Get-ItemProperty $GuardKey -ErrorAction SilentlyContinue
    return [pscustomobject]@{ On = ($p -and [int]$p.CCKoruma -eq 1); Made = @($(if ($p) { $p.CCKorumaKayit }) | Where-Object { $_ }) }
}
function Set-CCGuard([bool]$on, [string[]]$families = @()) {
    $state = Get-GuardState
    $made = [System.Collections.Generic.List[string]]::new()
    foreach ($m in $state.Made) { $made.Add($m) }
    if ($on) {
        $fams = @($families + @($Replaced.Keys | ForEach-Object { "${_}_$ClevoPubId" }) | Select-Object -Unique)
        foreach ($f in $fams) {
            $d = Join-Path $Deprov $f
            if (-not (Test-Path $d)) { New-Item -Path $d -Force | Out-Null; $made.Add("D|$f") }
        }
        # InstalledPfns: yalnızca sürücüsü bu paketi isteyen (AddSoftware) Fn paketi için
        $fn = @($fams | Where-Object { $_ -like 'CLEVOCO.FnhotkeysandOSD_*' })
        if (-not (Test-Path $Pfns)) { New-Item -Path $Pfns -Force | Out-Null }
        foreach ($f in $fn) {
            if ($null -eq (Get-ItemProperty $Pfns -Name $f -ErrorAction SilentlyContinue)) {
                New-ItemProperty -Path $Pfns -Name $f -Value 1 -PropertyType DWord -Force | Out-Null; $made.Add("I|$f")
            }
        }
        New-Item -Path $GuardKey -Force | Out-Null
        New-ItemProperty -Path $GuardKey -Name CCKoruma -Value 1 -PropertyType DWord -Force | Out-Null
        New-ItemProperty -Path $GuardKey -Name CCKorumaKayit -Value ([string[]]@($made | Select-Object -Unique)) -PropertyType MultiString -Force | Out-Null
        Ok 'Açık: Windows Update / Store eski Control Center bileşenlerini geri kursa da motor onları açılışta ve 10 dakikada bir kaldırır'
        Info ('Kapsam: ' + (($Replaced.Keys | ForEach-Object { $_ -replace '^CLEVOCO\.', '' }) -join ', ') + '. Hız aşırtma, Flexikey ve pil yardımcı programına dokunulmaz')
        Info 'Geri almak için kurulumu bu seçenek işaretsiz yeniden çalıştırın (ya da FCUK Control Center''ı kaldırın)'
    } else {
        foreach ($m in $made) {
            $k, $f = $m -split '\|', 2
            if ($k -eq 'D') { Remove-Item (Join-Path $Deprov $f) -Force -ErrorAction SilentlyContinue }
            elseif ($k -eq 'I') { Remove-ItemProperty -Path $Pfns -Name $f -ErrorAction SilentlyContinue }
        }
        if (Test-Path $GuardKey) {
            New-ItemProperty -Path $GuardKey -Name CCKoruma -Value 0 -PropertyType DWord -Force | Out-Null
            Remove-ItemProperty -Path $GuardKey -Name CCKorumaKayit -ErrorAction SilentlyContinue
        }
        if ($state.On -or $made.Count) { Ok "Kapatıldı: FCUK'un eklediği $($made.Count) engel kaydı silindi; Windows eski Control Center bileşenlerini yeniden kurabilir" }
        else { Info 'Kapalı: Windows eski Control Center bileşenlerini yeniden kurabilir' }
    }
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
    $cihaz = Get-Cihaz
    if ($cihaz -ne 'clevo') {
        $script:StdOut.WriteLine("CIHAZ|$cihaz")
        Show-Marka $cihaz
        if (Test-Path $Exe) { Info "FCUK Control Center zaten kurulu: $Dest (güncellenecek)" }
        exit 0
    }
    $script:StdOut.WriteLine('CIHAZ|clevo')
    Info 'Clevo/Monster gömülü denetleyicisi (AcpiBridge) bulundu'
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
    # Tasarruf profili NVIDIA kartı kapattıysa geri aç: uygulama gidince kartı açacak kimse kalmaz
    try {
        $cfgFile = Join-Path $Veri 'config.json'
        $cc = if (Test-Path $cfgFile) { (Get-Content $cfgFile -Raw -Encoding UTF8 | ConvertFrom-Json).cc } else { $null }
        if ($cc -and $cc.gpu_off) {
            Get-PnpDevice -Class Display -ErrorAction SilentlyContinue |
                Where-Object { $_.InstanceId -like 'PCI\VEN_10DE&*' -and "$($_.Problem)" -eq 'CM_PROB_DISABLED' } |
                ForEach-Object { [void](Invoke-Quiet 'pnputil.exe' @('/enable-device', $_.InstanceId)); Ok "Ekran kartı yeniden açıldı: $($_.FriendlyName)" }
        }
    } catch { Warn "Ekran kartı durumu okunamadı: $_" }
    $global:LASTEXITCODE = 0
    foreach ($t in $Tasks + $OldTasks) { [void](Invoke-Quiet 'schtasks.exe' @('/delete', '/tn', $t, '/f')) }
    $global:LASTEXITCODE = 0
    Ok 'Açılış görevleri silindi'
    Step 'Eski Control Center engelleri kaldırılıyor'
    foreach ($name in $Blocked) {
        $k = Join-Path $Ifeo $name
        if (-not (Test-Path $k)) { continue }
        # Bizim tam yol filtrelerimiz (FCUKCC..., önceki sürümlerde KendiCC...) ve eski ad engeli; başkalarınınkine dokunulmaz
        Get-ChildItem $k -ErrorAction SilentlyContinue | Where-Object { $_.PSChildName -like 'FCUKCC*' -or $_.PSChildName -like 'KendiCC*' } |
            Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
        $p = Get-ItemProperty $k -ErrorAction SilentlyContinue
        if ($p -and "$($p.Debugger)" -like '*\systray.exe') { Remove-ItemProperty -Path $k -Name Debugger -ErrorAction SilentlyContinue }
        if (-not (Get-ChildItem $k -ErrorAction SilentlyContinue)) {
            Remove-ItemProperty -Path $k -Name UseFilter -ErrorAction SilentlyContinue
            if (-not (Get-Item $k).Property) { Remove-Item $k -Force -ErrorAction SilentlyContinue }
        }
    }
    try { Set-CCGuard $false } catch {}
    Remove-Item $GuardKey -Recurse -Force -ErrorAction SilentlyContinue
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
    if (-not $Payload -or -not (Test-Path (Join-Path $Payload 'FCUKControlCenter.exe'))) { throw "Kurulum paketi bozuk: $Payload" }
    if (-not [Environment]::Is64BitOperatingSystem) { throw '64 bit Windows gerekli' }
    $cihaz = Get-Cihaz
    $clevo = $cihaz -eq 'clevo'
    $script:StdOut.WriteLine("CIHAZ|$cihaz")
    $cs = Get-CimInstance Win32_ComputerSystem
    Info ("Bilgisayar: $($cs.Manufacturer) $($cs.Model)")
    Info ("Tespit edilen cihaz: " + $Markalar[$cihaz].Ad + " - kurulum buna göre yapılıyor")

    if ($RestorePoint) {
        Step 'Sistem geri yükleme noktası oluşturuluyor'
        try {
            Checkpoint-Computer -Description "$AppTitle kurulumundan once" -RestorePointType MODIFY_SETTINGS -ErrorAction Stop -WarningVariable cw -WarningAction SilentlyContinue
            if ($cw) { Info "Geri yükleme noktası atlandı: $("$cw".Trim()) Kurulum yine de yedek alarak devam ediyor." } else { Ok 'Geri yükleme noktası oluşturuldu' }
        } catch { Info "Geri yükleme noktası oluşturulamadı ($($_.Exception.Message.Trim())). Kurulum yine de yedek alarak devam ediyor." }
    } else { Info 'Geri yükleme noktası istenmedi (sürücüler ve eski bileşenler yine yedeklenir)' }

    New-Item -ItemType Directory -Force $Backup | Out-Null
    $drivers = @()
    if (-not $clevo) {
        Step "$($Markalar[$cihaz].Ad) için kurulum hazırlanıyor"
        Show-Marka $cihaz
    } else {
        Step 'AcpiBridge sürücüleri yedekleniyor'
        $drivers = @(Get-DriverState)
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
    }

    if ($clevo) {
        Step 'Eski Control Center taranıyor'
        $inv = Get-OldInventory
        if ($inv.Found) { Show-Inventory $inv } else { Info 'Eski Control Center bulunamadı (zaten kaldırılmış); yalnızca kalıntı engelleri uygulanacak' }
    }

    Step 'Çalışan FCUK Control Center kapatılıyor'
    Stop-Fcuk
    Ok 'Kapatıldı'

    # Onceki surumler "Kendi Control Center" adiyla kuruluyordu: ayarlar tasinir, eski gorevler ve klasor silinir
    foreach ($t in $OldTasks) { [void](Invoke-Quiet 'schtasks.exe' @('/delete', '/tn', $t, '/f')) }
    $global:LASTEXITCODE = 0
    if (Test-Path $OldDest) {
        $oldVeri = Join-Path $OldDest 'veri'
        if ((Test-Path $oldVeri) -and -not (Test-Path $Veri)) { [void](Copy-Tree $oldVeri $Veri) }
        Remove-Item $OldDest -Recurse -Force -ErrorAction SilentlyContinue
        if (Test-Path $OldDest) { Warn "Eski klasör tamamen silinemedi: $OldDest" } else { Ok "Önceki sürüm taşındı ve silindi: $OldDest" }
    }

    if ($clevo) {
        Remove-OldCC $inv $clevo
        Restore-Drivers $drivers
    }

    Step "Dosyalar kopyalanıyor: $Dest"
    # Clevo değilse Clevo'ya özgü DLL'ler kopyalanmaz; önceki bir kurulumdan kalmışsa silinir
    $xf = @(if (-not $clevo) { $ClevoDosyalari | ForEach-Object { Split-Path $_ -Leaf } })
    if (-not (Copy-Tree $Payload $Dest -Mirror -ExcludeDirs $Veri -ExcludeFiles $xf)) {
        Start-Sleep -Seconds 2; Stop-Fcuk
        if (-not (Copy-Tree $Payload $Dest -Mirror -ExcludeDirs $Veri -ExcludeFiles $xf)) { throw "Dosyalar kopyalanamadı: $Dest" }
    }
    if (-not $clevo) {
        foreach ($f in $ClevoDosyalari) { Remove-Item (Join-Path $Dest $f) -Force -ErrorAction SilentlyContinue }
        Ok 'Clevo/Monster bileşenleri (InsydeDCHU.dll, GetProductdll.dll) bu cihaza kopyalanmadı'
    }
    Copy-Item $PSCommandPath (Join-Path $Dest 'kaldir.ps1') -Force
    $root = $Payload.TrimEnd('\')
    $files = @(Get-ChildItem $root -Recurse -File | Where-Object { $clevo -or $xf -notcontains $_.Name })
    $bad = @($files | Where-Object {
        $t = Join-Path $Dest $_.FullName.Substring($root.Length + 1)
        -not (Test-Path -LiteralPath $t) -or (Get-Item -LiteralPath $t).Length -ne $_.Length })
    if ($bad.Count) { throw "$($bad.Count) dosya doğru kopyalanmadı (ilk: $($bad[0].Name))" }
    Ok ("Kopyalandı ve doğrulandı: {0} dosya" -f $files.Count)
    if ($clevo -and -not (Test-Path (Join-Path $Dest '_internal\lib\InsydeDCHU.dll'))) {
        # Herkese açık setup.exe üretici DLL'ini içermez: uygulama onu Windows sürücü deposundan yükler
        $ds = @(Get-ChildItem (Join-Path $env:SystemRoot 'System32\DriverStore\FileRepository') -Directory -Filter 'acpibridge*' -ErrorAction SilentlyContinue |
            ForEach-Object { Join-Path $_.FullName 'InsydeDCHU.dll' } | Where-Object { Test-Path $_ })
        if ($ds.Count) { Ok "InsydeDCHU.dll sürücü deposundan kullanılacak: $(Split-Path $ds[0] -Parent | Split-Path -Leaf)" }
        else { Warn 'InsydeDCHU.dll bulunamadı (pakette de sürücü deposunda da yok): fan / güç modu / klavye ışığı çalışmaz. AcpiBridge sürücüsünü kurun, bkz. lib\README.md' }
    }
    $kur = $Markalar[$cihaz].Kur
    if ($kur) {
        Step "$($Markalar[$cihaz].Ad) için cihaza özel kurulum adımları"
        & $kur
    }

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
    New-ItemProperty -Path $UninstKey -Name FCUKCihaz -Value $cihaz -PropertyType String -Force | Out-Null  # tanı için: hangi cihaz yoluyla kuruldu
    Ok 'Ayarlar > Uygulamalar listesine eklendi'

    if ($clevo) {
        # Motor başlamadan önce: bekçi seçimi açılışta okur
        Step 'Eski Control Center geri yükleme engeli'
        $fams = @(if ($inv) { $inv.AppxReplaced | ForEach-Object PackageFamilyName })
        try {
            switch ($CCGuard) {
                'On'  { Set-CCGuard $true $fams }
                'Off' { Set-CCGuard $false }
                default {
                    if ((Get-GuardState).On) { Set-CCGuard $true $fams }  # önceki seçim korunur, kayıtlar tazelenir
                    else { Info 'Kapalı (önceki seçim korundu): Windows eski Control Center bileşenlerini yeniden kurabilir' }
                }
            }
        } catch { Warn "Geri yükleme engeli ayarlanamadı: $($_.Exception.Message)" }
    }

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
        # Motor yeni açıldığında ilk durum okuması (açılış profili uygulanırken) başarısız olabilir: birkaç kez denenir.
        $st = $null; $stErr = ''
        for ($i = 0; $i -lt 5 -and -not $st; $i++) {
            if ($i) { Start-Sleep -Seconds 1 }
            $st = Invoke-Api '/api/state' 'GET' 10
            if (-not $st) { $stErr = $script:ApiError }
        }
        if ($clevo) {
            $now = $null
            for ($i = 0; $i -lt 10 -and -not ($now -and $null -ne $now.cpu_rpm); $i++) { Start-Sleep -Milliseconds 700; $now = Invoke-Api '/api/now' }
            $fanOk = [bool]($now -and $null -ne $now.cpu_rpm -and ([int]$now.cpu_rpm -gt 0 -or [int]$now.cpu_temp -gt 0))
            if ($st -and $st.ec) { Ok "Gömülü denetleyici bağlı: $($st.device)" }
            elseif ($st) { Fail ("Gömülü denetleyiciye bağlanılamadı (fan / güç modu / klavye ışığı çalışmaz)" + $(if ($st.ec_reason) { ": $($st.ec_reason)" } else { '' })) }
            elseif ($fanOk) { Warn "Arayüz durumu okunamadı ($stErr); denetleyici fan okumasına yanıt verdiği için bağlı. Ayrıntı: $(Join-Path $Veri 'crash.log')" }
            else { Fail "Gömülü denetleyiciye bağlanılamadı (fan / güç modu / klavye ışığı çalışmaz); motor durumu okunamadı: $stErr" }
            if ($fanOk) { Ok "Fan okuması: işlemci $($now.cpu_rpm) RPM, ekran kartı $($now.gpu_rpm) RPM, işlemci $($now.cpu_temp) °C" }
            else { Warn 'Fan okuması henüz gelmedi' }
        } elseif ($cihaz -ne 'diger' -and $st) {
            # Kurulum cihazı tanıdı; uygulamanın bu sürümünde o markanın denetleyici desteği var mı?
            if ($st.ec -and "$($st.ec_kind)" -eq $cihaz) { Ok "$($Markalar[$cihaz].Ad) denetleyicisi bağlı: $($st.device)" }
            else { Info "$($Markalar[$cihaz].Ad) denetleyici desteği bu sürümde etkin değil: fan / güç modu / klavye ışığı arayüzde 'kullanılamaz' görünür, donanıma komut gönderilmez" }
        } elseif ($st) { Ok "Arayüz durumu okundu: $($st.device)" }
        $tray = $null
        for ($i = 0; $i -lt 20 -and -not $tray; $i++) {
            $tray = Get-CimInstance Win32_Process -Filter "Name='FCUKControlCenter.exe'" | Where-Object { "$($_.CommandLine)" -match '--tray' }
            if (-not $tray) { Start-Sleep -Milliseconds 500 }
        }
        if ($tray) { Ok 'Tepsi simgesi ve Fn tuşu dinleyicisi çalışıyor' } else { Warn 'Tepsi süreci görülmedi' }
        if ($clevo) {
            $left = @(Get-Process -Name $OldProcs -ErrorAction SilentlyContinue)
            if ($left.Count) { Warn ("Hâlâ çalışan eski süreç: " + (($left | ForEach-Object Name) -join ', ')) } else { Ok 'Eski Control Center süreçlerinden hiçbiri çalışmıyor' }
        }
    }
    if ($clevo) {
        $after = Get-OldInventory
        $rest = $after.Uninstall.Count + [int]$after.IsInfo + $after.AppxReplaced.Count + $after.Tasks.Count + $after.Run.Count + $after.Shortcuts.Count
        if ($rest) { Warn "Eski Control Center'dan $rest kalıntı kaldı:"; Show-Inventory $after } else { Ok "Eski Control Center'dan kalıntı yok" }
        Info "Yedekler: $Backup"
        Info "Kayıt: $LogFile"
        Info 'Yeniden başlatma gerekli: sürücü, hizmet ve Fn tuşu değişiklikleri için kurulumdan sonra bilgisayarı yeniden başlatın'
    } else {
        Ok 'Bu bilgisayarın kendi Control Center / üretici uygulamasına dokunulmadı; ikisi birlikte çalışır'
        if ($cihaz -eq 'diger') { Info 'Fan eğrisi, denetleyici güç modu ve klavye RGB bu bilgisayarda yok: arayüzde "kullanılamaz" görünür, donanıma komut gönderilmez' }
        Info "Kayıt: $LogFile"
    }
} catch {
    Fail $_.Exception.Message
}
if ($script:Fail) { exit 1 }
if ($script:Warn) { exit 2 }
exit 0
