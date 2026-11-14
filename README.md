# FCUK Control Center

Windows dizüstü ve masaüstü bilgisayarlar için açık kaynak, hafif, tam donanımlı kontrol paneli.
Monster / Clevo tabanlı dizüstülerde üreticinin Control Center'ının yerini tamamen alır; diğer
bilgisayarlarda da donanım tespiti, canlı izleme, NVIDIA ve işlemci ayarları çalışır.

> Bu projenin kaynak kodu Anthropic'in **Claude Opus 5.5** yapay zeka modeliyle yazılmıştır.
> *The source code of this project was written with Anthropic's Claude Opus 5.5 AI model.*

## Özellikler

| Bölüm | Ne yapar | Gereken |
|---|---|---|
| **Donanım** | İşlemci (model, mimari, nesil, P/E çekirdek yapısı, önbellek), ekran kartları ve sürücü sürümleri, bellek modülleri (yuva, kapasite, hız, tür, üretici), diskler (model, NVMe/SATA, sıcaklık, kalan ömür, yazılan TB, çalışma saati), anakart, BIOS, pil sağlığı, ağ kartları, ekran | Her bilgisayar |
| **Canlı izleme** | İşlemci sıcaklığı/gücü/yükü, çekirdek başına MHz, ekran kartı sıcaklığı/gücü/saati/VRAM/PCIe/kısıtlama nedeni, tümleşik grafik yükü, disk başına okuma/yazma hızı, bellek, ağ, pil | Her bilgisayar |
| **NVIDIA** | Güç yönetimi modu, düşük gecikme, V-Sync, en yüksek kare hızı, doku filtreleme, iş parçacıklı optimizasyon, tercih edilen grafik işlemcisi (Optimus), elle saat sınırı. Ayarlar NVIDIA Denetim Masası'nın kullandığı aynı sürücü profiline yazılır | NVIDIA kart; yazmak için yönetici modu |
| **İşlemci** | İşlemci modeline göre yalnızca etkili olan ayarlar: turbo modu, EPP (Speed Shift), P ve E çekirdek frekans tavanları (melez Intel), işlemci durumu sınırları, çekirdek zamanlayıcı politikası, çekirdek park etme | Her bilgisayar (Windows güç planı) |
| **Performans profilleri** | Beş profil: Tam Sessiz → Ultra Performans; her biri gömülü denetleyici güç modu, fan eğrisi, işlemci, ekran kartı ve ekran yenileme hızını birlikte ayarlar | Clevo / Monster |
| **Fanlar, klavye RGB, Fn tuşları** | Özel fan eğrisi, 8 klavye ışık modu, Fn tuşu ekran bildirimleri | Clevo / Monster |
| **Ses ve ekran** | Hoparlör / mikrofon seviyesi, yenileme hızı | Her bilgisayar |
| **Dil** | 14 dil, Windows bölge ayarına göre otomatik | |

Güç sınırı (PL1/PL2) ve voltaj düşürme bilerek yoktur: bunlar işlemci yazmaçlarına (MSR) çekirdek sürücüsüyle
yazmayı gerektirir. Uygulama hiçbir çekirdek sürücüsü kurmaz.

## Kurulum

### setup.exe (önerilen)

`setup.exe` uygulamayı `C:\Program Files\FCUK Control Center` klasörüne kurar ve Monster / Clevo Control Center'ın
yerine geçer:

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

setup.exe'yi kendiniz derleyin (Python 3.10+ gerekir):

```powershell
git clone https://github.com/kuheylanstudio/fcuk-control-center.git
cd fcuk-control-center
pip install -r requirements.txt pyinstaller
powershell -ExecutionPolicy Bypass -File lib\dll_topla.ps1   # üretici DLL'ini bu bilgisayardan lib\'e alır
powershell -ExecutionPolicy Bypass -File setup_olustur.ps1   # çıktı: dist\setup.exe
```

`setup_olustur.ps1` DLL eksikse `lib\dll_topla.ps1`'i kendisi de çalıştırır. Ayrıntı: aşağıdaki
[Üretici DLL'i](#üretici-dlli-insydedchudll) bölümü.

setup.exe üreticiye ait DLL'i içerir. Bu yüzden kendi bilgisayarınız için derleyin, herkese açık dağıtmayın.

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
donanim.py         gömülü denetleyici (DCHU), PDH sayaçları, NVML, ekran, ses, sensör döngüsü
envanter.py        donanım envanteri (CIM), P/E çekirdek tespiti, NVMe SMART ve disk sıcaklığı (IOCTL)
nvidia.py          NVIDIA sürücü ayarları (NVAPI DRS), kart bilgisi (NVML)
islemci.py         modele göre işlemci ayarları (Windows güç planı)
profiller.py       beş performans profili, ısı koruması, fiş/pil kuralları
klavye_rgb.py      klavye ışık motoru
engelle.py         eski Monster Fn programlarını tam yollarıyla engeller (IFEO yol filtresi)
fntus.py, tepsi.py Fn tuşları, ekran bildirimi ve tepsi simgesi (ayrı, normal yetkili süreç)
ceviri.py, ui/lang dil dosyaları
ui/index.html      arayüz (Edge --app penceresi)
```

Geliştirme sırasında kurulu motoru atlayıp kodu doğrudan çalıştırmak için: `python control_center.py --dev`

## Lisans

[MIT](LICENSE). Kodu istediğiniz gibi kullanabilir, değiştirebilir ve dağıtabilirsiniz. Üçüncü taraf DLL'ler bu
lisansın parçası değildir ve depoda bulunmaz. NVIDIA, Intel, Monster ve Clevo kendi sahiplerinin ticari
markalarıdır; bu proje onlarla bağlantılı değildir. Gömülü denetleyici komutları birlikte çalışabilirlik amacıyla
belgelenmiştir; üretici kodu içermez.

---

**English:** FCUK Control Center is an open-source, lightweight hardware control panel for Windows. It detects
CPU, GPUs, memory modules and disks, monitors temperatures, clocks, load and disk health live, exposes NVIDIA
driver settings and model-aware Intel/AMD CPU power settings, and fully replaces the vendor Control Center on
Clevo-based laptops (fan curves, power modes, keyboard RGB, Fn keys). Written with Claude Opus 5.5. MIT licensed.
