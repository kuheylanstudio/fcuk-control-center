# FCUK Control Center

Windows dizüstü ve masaüstü bilgisayarlar için açık kaynak, hafif, tam donanımlı kontrol paneli.
Monster / Clevo tabanlı dizüstülerde üreticinin Control Center'ının yerini tamamen alır. **Alienware / Dell G** ve
**Asus ROG / TUF** dizüstülerde güç modu, fan ve klavye ışığını üreticinin uygulamasıyla birlikte yönetir. Diğer
bilgisayarlarda da donanım tespiti, canlı izleme, NVIDIA ve işlemci ayarları çalışır.

> Bu projenin kaynak kodu Anthropic'in **Claude Opus 5.5** yapay zeka modeliyle yazılmıştır.
> *The source code of this project was written with Anthropic's Claude Opus 5.5 AI model.*

<p align="center">
  <a href="https://github.com/kuheylanstudio/fcuk-control-center/releases/download/v2.6.0/FCUK-Control-Center-Setup-2.6.0.exe"><img alt="İndir: FCUK-Control-Center-Setup-2.6.0.exe" src="https://img.shields.io/badge/%C4%B0ndir-FCUK--Control--Center--Setup--2.6.0.exe-2ea44f?style=for-the-badge&logo=windows&logoColor=white"></a>
  <br>
  <a href="https://www.virustotal.com/gui/file/2be5162cf66c0e0f674c0da78f5dde7589a129d0423fe693e9013b568a720b04"><img alt="VirusTotal tarama sonucu" src="https://img.shields.io/badge/VirusTotal-tarama%20sonucu-394EFF?logo=virustotal&logoColor=white"></a>
  <br>
  <sub>Windows 10/11 (64 bit) · <a href="https://github.com/kuheylanstudio/fcuk-control-center/releases/latest">tüm sürümler ve SHA-256</a> · <a href="#güvenlik-ve-doğrulama">güvenlik ve doğrulama</a></sub>
</p>

## Özellikler

| Bölüm | Ne yapar | Gereken |
|---|---|---|
| **Donanım** | İşlemci (model, mimari, nesil, P/E çekirdek yapısı, önbellek), ekran kartları ve sürücü sürümleri, bellek modülleri (yuva, kapasite, hız, tür, üretici), diskler (model, NVMe/SATA, sıcaklık, kalan ömür, yazılan TB, çalışma saati), anakart, BIOS, pil sağlığı, ağ kartları, ekran | Her bilgisayar |
| **Canlı izleme** | İşlemci sıcaklığı/gücü/yükü, çekirdek başına MHz, ekran kartı sıcaklığı/gücü/saati/VRAM/PCIe/kısıtlama nedeni, tümleşik grafik yükü, disk başına okuma/yazma hızı, bellek, ağ, pil | Her bilgisayar |
| **NVIDIA** | Güç yönetimi modu, düşük gecikme, V-Sync, en yüksek kare hızı, doku filtreleme, iş parçacıklı optimizasyon, tercih edilen grafik işlemcisi (Optimus), elle saat sınırı. Ayarlar NVIDIA Denetim Masası'nın kullandığı aynı sürücü profiline yazılır | NVIDIA kart; yazmak için yönetici modu |
| **İşlemci** | İşlemci modeline göre yalnızca etkili olan ayarlar: turbo modu, EPP (Speed Shift), P ve E çekirdek frekans tavanları (melez Intel), işlemci durumu sınırları, çekirdek zamanlayıcı politikası, çekirdek park etme | Her bilgisayar (Windows güç planı) |
| **Performans profilleri** | Beş profil: Tam Sessiz → Ultra Performans; her biri gömülü denetleyici güç modu, fan eğrisi, işlemci, ekran kartı ve ekran yenileme hızını birlikte ayarlar. Cihazda olmayan adımlar atlanır ve raporda gösterilir | Clevo / Monster, Alienware, Asus, Lenovo Legion, Lenovo IdeaPad, MSI, HP Omen / Victus, Acer Predator / Nitro, Gigabyte (güç modu) |
| **Fanlar** | Özel fan eğrisi, fan devri ve sıcaklık okuması | Clevo / Monster, Alienware, Asus, Lenovo Legion (Özel modda), Gigabyte; MSI, HP ve Acer'da fan modu / tam devir (modele göre) |
| **Klavye RGB** | 9 ışık modu: sabit, nefes alma, renk geçişi, gökkuşağı, nabız, ses/müzik, sistem durumu, ekran rengi ve **oyun tepkisi**; 4 bölgeli klavyelerde ayrıca bölge renkleri | Clevo / Monster, Alienware (AlienFX), Asus (Aura), Lenovo Legion, MSI (USB klavye), HP Omen, Acer Predator / Nitro, Gigabyte (ITE) |
| **Oyun tepkisi** | Klavye cana göre yeşilden kırmızıya döner, can %35'in altındayken kalp atışı gibi yanıp söner; ateş, yetenek, kill ve ölümde parlar. **League of Legends** (Riot'un resmi canlı oyun verisi) ve **Counter-Strike 2** (resmi Game State Integration). Oyun belleğine dokunulmaz | Klavye RGB olan cihaz |
| **Asus'a özel** | Şarj sınırı, ekran kartı modu (Eco / Standart / Ultimate) | Asus ROG / TUF (modele göre) |
| **Fn tuşları** | Fn tuşu ekran bildirimleri | Clevo / Monster |
| **Lenovo Legion'a özel** | Ekran kartı modu (hibrit / tümleşik / yalnızca harici kart), pil koruma ve hızlı şarj, tam devir fan | Lenovo Legion (modele göre) |
| **MSI'a özel** | Shift / fan modu, Cooler Boost, pil şarj sınırı | MSI (EC firmware'i tabloda olan modeller) |
| **Pil şarj sınırı** | Şarjı %60-100 arasında bir değerde durdurur | Gigabyte, MSI (modele göre) |
| **Ses ve ekran** | Hoparlör / mikrofon seviyesi, yenileme hızı | Her bilgisayar |
| **Güncellemeler** | GitHub'dan yeni sürümü denetler, indirir, SHA-256 ile doğrular ve kurar. Otomatik ya da elle seçilebilir; kurmadan önce yenilikler gösterilir | Her bilgisayar (setup.exe ile kurulmuş) |
| **Dil** | 14 dil, Windows bölge ayarına göre otomatik | |

### Desteklenen cihazlar

| Cihaz | Durum |
|---|---|
| **Monster / Clevo** | Tam destek: üreticinin Control Center'ının yerini alır |
| **Alienware / Dell G** (16 Aurora, 16X Aurora ve AWCC'li modeller) | Güç modu (Sessiz, Dengeli, Performans/G-mode), "Özel" profilde fan eğrisi, sıcaklık ve fan devri, AlienFX klavye ışığı (tek renk). Fn tuşu ya da Alienware Command Center profili değiştirirse uygulama bunu algılar ve gerçek modu gösterir |
| **Asus ROG / TUF** | Güç modu (sessiz, dengeli, turbo), 8 noktalı fan eğrisi, fan devri, klavye arka ışığı ve Aura RGB, şarj sınırı, ekran kartı modu. Her özellik önce sınanır; modelde olmayan özelliğe komut gönderilmez |
| **Lenovo Legion** | Güç modu (Sessiz, Dengeli, Performans) profillerle, fan hızı ve sıcaklık, tam devir fan, Özel modda fan eğrisi, ekran kartı modu (hibrit / tümleşik / yalnızca harici kart), pil koruma ve hızlı şarj, 4 bölgeli klavyede tüm ışık modları. Her özellik önce sınanır; desteklenmeyen özellik hiçbir komut göndermez |
| **Lenovo IdeaPad** (Intel ve Ryzen) | Modelin sunduğu Lenovo arayüzüne göre: güç modu (Sessiz, Dengeli, Performans; Fn+Q ile aynı, GameZone WMI), pil modu (normal, koruma modu, hızlı şarj; Energy Management sürücüsü), işlemci/kart sıcaklığı ve fan devri. Fanları her zaman bellenim çalıştırır (özel fan eğrisi yok); klavye ışığı Fn+Boşluk ile kalır. Güç modunu sunmayan modellerde profiller yine Windows güç modunu ayarlar |
| **MSI** | Güç modu (shift modu) profillerle, fan modu ve Cooler Boost, sıcaklık ve fan devri, pil şarj sınırı, USB klavye ışığı (SteelSeries / 3 bölgeli). EC firmware'i tabloda yoksa yalnızca okuma yapılır (ayrıntı aşağıda) |
| **HP Omen / Victus** | Termal mod (serin / dengeli / performans) profillerle, tam devir fan, sıcaklık ve fan devri, 4 bölgeli klavye ışığı. Özellikler BIOS'tan yalnızca okuyarak yoklanır; olmayan özellik gizlenir |
| **Acer Predator / Nitro** | Güç profili, fan modu (otomatik / en yüksek), sıcaklık ve fan devri, 4 bölgeli RGB klavye (bölge renkleri dahil). Özellikler yalnızca okuyarak yoklanır |
| **Gigabyte / AORUS / AERO** | Sessiz / normal / oyun fan kipi (profillerin güç modu adımı), 15 noktalı özel fan eğrisi, sabit fan hızı, sıcaklık ve fan devri, pil şarj sınırı (%60-100), ITE klavyelerde tek renk RGB. Clevo tabanlı modellerde Clevo yolu kullanılır |
| **Diğer bilgisayarlar** | Donanım, canlı izleme, NVIDIA, işlemci, ses ve ekran. Fan ve klavye sayfaları "Bu bilgisayarda kullanılamaz" der |

Alienware, Asus, Lenovo, MSI, HP, Acer ve Gigabyte desteği gerçek cihazda henüz denenmedi; sorun görürseniz lütfen bildirin. Clevo dışındaki
bilgisayarlarda uygulama denetleyiciye, fanlara, klavyeye ve Fn tuşlarına yalnızca desteklenen cihaz gerçekten
varsa dokunur. Armoury Crate, Alienware Command Center, Vantage, MSI Center ve Omen gibi üretici uygulamaları
kaldırılmaz; birlikte çalışır. Aynı ayarı ikisi birden değiştirirse son değiştirenin ayarı geçerli olur.

Güç sınırı (PL1/PL2) ve voltaj düşürme bilerek yoktur: bunlar işlemci yazmaçlarına (MSR) çekirdek sürücüsüyle
yazmayı gerektirir. Uygulama hiçbir çekirdek sürücüsü kurmaz.

## Kurulum

### setup.exe (önerilen)

1. **[FCUK-Control-Center-Setup-2.6.0.exe](https://github.com/kuheylanstudio/fcuk-control-center/releases/download/v2.6.0/FCUK-Control-Center-Setup-2.6.0.exe)** dosyasını indirin.
2. Çift tıklayın ve yönetici iznini onaylayın. Kurulum penceresi her adımı gösterir; bitince uygulama açılır.
3. Windows "Bilgisayarınız korundu" (SmartScreen) derse: **Ek bilgi → Yine de çalıştır**. Ayrıntı:
   [Güvenlik ve doğrulama](#güvenlik-ve-doğrulama).

### Güvenlik ve doğrulama

- **VirusTotal:** [2.5.0 kurulum dosyasının tarama raporu](https://www.virustotal.com/gui/file/2be5162cf66c0e0f674c0da78f5dde7589a129d0423fe693e9013b568a720b04)
  (yukarıdaki rozet de aynı rapora gider). Yeni sürümler yayımlandığında GitHub Actions ile VirusTotal'a
  yüklenir; rapor bağlantısı sürüm notlarının sonuna eklenir. PyInstaller ile paketlenen programları birkaç
  antivirüs motoru bazen yanlışlıkla işaretler (genel "Trojan/Wacatac" vb. adlarla); kaynak kodun tamamı bu depodadır.
- **SHA-256:** indirdiğiniz dosyanın [sürüm sayfasındaki](https://github.com/kuheylanstudio/fcuk-control-center/releases/latest)
  özetle aynı olduğunu denetleyin: `Get-FileHash FCUK-Control-Center-Setup-2.6.0.exe`
- **Kod imzası:** kurulum programı kod imzalı değildir; SmartScreen uyarısı bu yüzdendir.

İndirilen kurulum programı üreticiye ait DLL'i **içermez**. Clevo / Monster dizüstülerde uygulama `InsydeDCHU.dll`'i
Windows sürücü deposundaki AcpiBridge sürücüsünden kullanır; ayrıca bir şey yapmanız gerekmez.

Tek setup.exe her bilgisayara kurulur. Kurulum cihazı donanımdan tespit eder (Clevo, Alienware, Asus, Lenovo, MSI,
HP, Acer, Gigabyte) ve **yalnızca o cihaza ait adımları** uygular. Clevo dışında aşağıdaki Monster / Clevo adımlarının
hiçbiri yapılmaz, hiçbir üretici yazılımı, sürücüsü ya da hizmeti kaldırılmaz ve yeniden başlatma istenmez.

Monster / Clevo dizüstüde `setup.exe` uygulamayı `C:\Program Files\FCUK Control Center` klasörüne kurar ve üreticinin
Control Center'ının yerine geçer:

- **Üreticinin kaldırıcısı çalıştırılmaz.** O kaldırıcı (InstallShield + `RemoveAPP.exe`) AcpiBridge sürücülerini de
  siler; sürücüler giderse fan, güç modu, klavye ışığı ve Fn tuşları çalışmaz. Eski bileşenleri setup.exe kendisi
  kaldırır ve her birinin yedeğini alır:
  - Fn tuşu / OSD paketi, Control Center 3.0, fan, klavye ışığı ve enerji tasarrufu uygulama paketleri
  - `Program Files (x86)\ControlCenter` klasörü, InstallShield kaydı, kısayollar, açılış kayıtları ve görevler
- Eski Fn programları **tam yollarıyla** engellenir (IFEO yol filtresi): yalnızca Monster paketindeki, eski
  Control Center klasöründeki ve CCDCHUService klasöründeki kopyalar. Aynı adı taşıyan başka yazılımlara dokunulmaz.
  Windows paketi geri kurarsa yönetici motor yeni yolu açılışta ve 30 dakikada bir engeller.
- **Korunanlar:** AcpiBridge sürücüleri ve CCDCHUService hizmeti. Kurulum önce bir geri yükleme noktası oluşturur
  ve sürücüleri dışa aktarır. Sonunda sürücülerin yerinde olduğunu doğrular; eksik çıkarsa yedekten geri kurar.
- Karşılığı bu uygulamada olmayan paketlere dokunulmaz: CPU/GPU hız aşırtma, Flexikey ve pil yardımcı programı.
- Kurulumun sonunda motorun yönetici modunda çalıştığı, gömülü denetleyiciye bağlandığı, fan okumasının geldiği ve
  tepsi / Fn dinleyicisinin açık olduğu denetlenir.
- Yedekler `C:\ProgramData\FCUK Control Center\yedek\<tarih>` altına, kayıt dosyası `kurulum.log` olarak aynı
  klasöre yazılır.
- Kaldırmak için: Ayarlar → Uygulamalar → FCUK Control Center → Kaldır.

Sessiz kurulum için `setup.exe /S` kullanın. Çıkış kodu 0 başarılı, 2 uyarılarla başarılı, 1 hata demektir.

### Güncellemeler

2.1.0'dan itibaren uygulama kendini GitHub'dan günceller (Ayarlar → Güncellemeler):

- **Otomatik** (varsayılan): yeni sürüm denetlenir, indirilir ve doğrulanır. Yenilikler penceresi açılır ve 45 sn
  sonra kurulum başlar; "Şimdi kur" ya da "Bu sefer kurma" seçilebilir.
- **Elle:** yeni sürüm yalnızca bildirilir; yenilikleri okuyup "İndir ve kur" ile siz kurarsınız.

Dosya yalnızca bu deponun sürüm sayfasından HTTPS ile indirilir ve GitHub'ın verdiği SHA-256 özetiyle doğrulanır.
Kurulum `setup.exe /S` ile yapılır, ayarlar korunur. Atlanan sürümlerin notları da yenilikler penceresinde görünür.
2.0.x kullanıyorsanız 2.1.0'ı bir kez elle kurmanız gerekir; sonraki sürümler kendiliğinden gelir.

#### Kendiniz derlemek

setup.exe'yi kaynaktan da derleyebilirsiniz (Python 3.10+ gerekir):

```powershell
git clone https://github.com/kuheylanstudio/fcuk-control-center.git
cd fcuk-control-center
pip install -r requirements.txt pyinstaller
powershell -ExecutionPolicy Bypass -File lib\dll_topla.ps1   # üretici DLL'ini bu bilgisayardan lib\'e alır
powershell -ExecutionPolicy Bypass -File setup_olustur.ps1   # çıktı: dist\setup.exe
```

`setup_olustur.ps1` DLL eksikse `lib\dll_topla.ps1`'i kendisi de çalıştırır. Ayrıntı: aşağıdaki
[Üretici DLL'i](#üretici-dlli-insydedchudll) bölümü.

Bu şekilde derlenen setup.exe üreticiye ait DLL'i içerir; kendi bilgisayarınız için kullanın, herkese açık
dağıtmayın. Dağıtılabilir (DLL'siz) paket için: `setup_olustur.ps1 -Dagitim` (çıktı:
`dist\FCUK-Control-Center-Setup-2.6.0.exe`). İndirme düğmesindeki dosya budur.

### Kaynaktan

Gereken: Windows 10/11 (64 bit), Python 3.10+ ve Microsoft Edge (pencere için).

```powershell
git clone https://github.com/kuheylanstudio/fcuk-control-center.git
cd fcuk-control-center
pip install -r requirements.txt
pythonw control_center.py
```

Exe olarak derleyip `C:\Program Files` altına kurmak ve Windows açılışında yönetici motorunu başlatmak için:

```powershell
pip install pyinstaller
powershell -ExecutionPolicy Bypass -File kur.ps1
```

### Üretici DLL'i (InsydeDCHU.dll)

Clevo / Monster dizüstülerde fan, güç modu, klavye ışığı ve Fn tuşları gömülü denetleyiciyle `InsydeDCHU.dll`
üzerinden konuşur. Bu dosya üreticiye aittir, lisansı dağıtıma izin vermediği için bu depoda **yoktur**. Gereken tek
dosya budur (`GetProductdll.dll` ve Visual C++ DLL'leri gerekmez).

**Nereden bulunur?** Clevo / Monster dizüstünüzde zaten vardır:

| Yer | Not |
|---|---|
| `C:\Windows\System32\DriverStore\FileRepository\acpibridge*\InsydeDCHU.dll` | AcpiBridge sürücüsüyle gelir; üretici Control Center kaldırılmış olsa bile durur. Microsoft imzalı. |
| `C:\Program Files (x86)\ControlCenter\DCHU\` | Üretici Control Center kuruluysa |
| Microsoft Store "Fn hotkeys and OSD" paketi, `FnKey\DCHU\` | Kuruluysa |
| `C:\ProgramData\FCUK Control Center\yedek\` | setup.exe'nin eski Control Center'dan aldığı yedek |
| Üreticinin destek sayfası | Modelinizin "Control Center" ya da "AcpiBridge / DCHU" sürücü paketini indirip açın |

**Projeye nasıl eklenir?**

```powershell
powershell -ExecutionPolicy Bypass -File lib\dll_topla.ps1
```

Betik yukarıdaki yerleri sırayla tarar, bulduğu dosyayı `lib\InsydeDCHU.dll` olarak kopyalar ve sürümünü ve
imzasını gösterir. Yönetici izni istemez, hiçbir şey indirmez. Elle yapmak isterseniz dosyayı `lib\` klasörüne
kopyalamanız yeterlidir. Ayrıntı: [lib/README.md](lib/README.md).

Kaynaktan çalıştırırken ya da DLL'siz derlenmiş bir exe'de uygulama `lib\` içinde dosya bulamazsa sürücü deposuna
kendisi bakar. Dosya hiçbir yerde yoksa (Clevo / Monster olmayan bilgisayar) uygulama yine açılır; yalnızca
gömülü denetleyiciye bağlı özellikler kapanır.

`kur.ps1` Clevo Fn tuşu paketini (FnKey / eski Control Center arayüzü) devre dışı bırakır; bu adım yalnızca
AcpiBridge aygıtı (ACPI\CLV0001) olan bilgisayarlarda çalışır.

## Yönetici modu

Ekran kartı saat sınırı ve NVIDIA sürücü ayarlarını yazmak yönetici ister. Ayarlar → *Yönetici modunu kur* bir kez
UAC sorar ve Görev Zamanlayıcı'ya bir görev ekler; sonra motor her açılışta UAC sormadan yönetici olarak başlar.
Pencere ve tepsi simgesi her zaman normal kullanıcı yetkisiyle çalışır.

## Mimari

```
control_center.py  giriş noktası, yerel HTTP sunucusu (yalnızca 127.0.0.1:47815), görevler
donanim.py         gömülü denetleyici (DCHU), cihaz tespiti, PDH sayaçları, NVML, ekran, ses, sensör döngüsü
alienware.py       Alienware / Dell G arka ucu (AWCC WMI, AlienFX HID)
asus_rog.py        Asus ROG / TUF arka ucu (ATK ACPI-WMI, Aura HID)
wmi_com.py, hid_win.py  ek paket gerektirmeyen WMI ve USB HID erişimi
guncelleme.py      GitHub'dan güncelleme denetimi, indirme, doğrulama ve kurulum
lenovo_legion.py   Lenovo Legion arka ucu (GameZone WMI), lenovo_wmi.py (WMI), lenovo_kb.py (klavye HID)
ideapad.py         Lenovo IdeaPad arka ucu (GameZone WMI, Energy Management sürücüsü)
envanter.py        donanım envanteri (CIM), P/E çekirdek tespiti, NVMe SMART ve disk sıcaklığı (IOCTL)
nvidia.py          NVIDIA sürücü ayarları (NVAPI DRS), kart bilgisi (NVML)
islemci.py         modele göre işlemci ayarları (Windows güç planı)
profiller.py       beş performans profili, ısı koruması, fiş/pil kuralları
klavye_rgb.py      klavye ışık motoru
oyun.py            oyun tepkisi kaynakları: tuş basımları, LoL canlı oyun verisi, CS2 Game State Integration
hp_omen.py         HP Omen / Victus arka ucu (HP BIOS WMI: termal mod, fan, sıcaklık, 4 bölgeli klavye)
acer_predator.py   Acer Predator / Nitro arka ucu (AcerGamingFunction WMI: güç profili, fan, 4 bölgeli klavye)
msi.py             MSI: EC firmware tablosu ve güvenlik kuralları (shift/fan modu, Cooler Boost, pil sınırı)
msi_wmi.py         MSI_ACPI (root\WMI) taşıma katmanı, sürücüsüz
msi_klavye.py      MSI USB klavye ışığı (SteelSeries 1038, eski 3 bölgeli 1770)
gigabyte_aorus.py  Gigabyte/AORUS/AERO arka ucu (GB_WMIACPI fan, kip, sıcaklık, şarj sınırı; ITE klavye)
wmi_yontem.py      ek paketsiz WMI yöntem çağrıları (COM, tek iş parçacığı)
hid_rapor.py       ek paketsiz HID özellik raporu (hid.dll)
engelle.py         eski Monster Fn programlarını tam yollarıyla engeller (IFEO yol filtresi)
fntus.py, tepsi.py Fn tuşları, ekran bildirimi ve tepsi simgesi (ayrı, normal yetkili süreç)
ceviri.py, ui/lang dil dosyaları
ui/index.html      arayüz (Edge --app penceresi)
```

Geliştirme sırasında kurulu motoru atlayıp kodu doğrudan çalıştırmak için: `python control_center.py --dev`

## MSI dizüstüler (deneysel, gerçek donanımda doğrulanmadı)

Üretici `Micro-Star International` ise `msi.py` devreye girer. Gömülü denetleyiciye ek sürücü kurmadan MSI'ın
kendi `MSI_ACPI` WMI sınıfıyla ulaşılır (Get_EC, Get_Data/Set_Data, Get_Fan; Set_EC hiç kullanılmaz). Adres ve
değerler Linux msi-ec sürücüsünün firmware tablolarından alındı (yalnızca adres/değer bilgisi). Korumalar:

- EC firmware'i tablodaki bir girdiyle birebir eşleşmezse yalnızca okuma (sıcaklık, fan) yapılır, yazma denetimleri gizlenir.
- Get_Data'nın ham EC adresi okuduğu, firmware alanı (0xA0) Get_EC'nin verdiği metinle karşılaştırılarak doğrulanır; tutmazsa EC hiç kullanılmaz.
- Yalnızca tablodaki adres/değerler yazılır, her yazma geri okunur; tutmazsa o oturumda tüm yazmalar kapanır.
- Profillerin fan eğrisi MSI'da özel eğri yerine en yakın fan moduna (Silent / Auto) çevrilir.

Testler (sahte WMI/HID ile): `python -m unittest discover -s tests`

## Lisans

[MIT](LICENSE). Kodu istediğiniz gibi kullanabilir, değiştirebilir ve dağıtabilirsiniz. Üçüncü taraf DLL'ler bu
lisansın parçası değildir ve depoda bulunmaz. NVIDIA, Intel, Monster, Clevo, Alienware, Dell, Asus, Riot Games ve
Valve kendi sahiplerinin ticari markalarıdır; bu proje onlarla bağlantılı değildir. Gömülü denetleyici komutları birlikte çalışabilirlik amacıyla
belgelenmiştir; üretici kodu içermez.

---

**English:** FCUK Control Center is an open-source, lightweight hardware control panel for Windows. It detects
CPU, GPUs, memory modules and disks, monitors temperatures, clocks, load and disk health live, exposes NVIDIA
driver settings and model-aware Intel/AMD CPU power settings, and fully replaces the vendor Control Center on
Clevo-based laptops (fan curves, power modes, keyboard RGB, Fn keys). Since 2.1.0 it also controls power modes,
fans and keyboard lighting on Alienware / Dell G and Asus ROG / TUF laptops (plus battery charge limit and GPU mode
on Asus) alongside the vendor app, reacts to League of Legends and Counter-Strike 2 game events with keyboard
lighting, and updates itself from GitHub releases (automatic or manual, SHA-256 verified). Written with Claude
Opus 5.5. MIT licensed.
