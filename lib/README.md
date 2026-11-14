# lib/

Bu klasör üreticiye ait kitaplık içindir. DLL dosyaları depoya **yüklenmez** (`.gitignore`): üreticinin
mülküdür ve bu projenin MIT lisansının parçası değildir.

## Hangi dosya gerekli?

Yalnızca **`InsydeDCHU.dll`**. Clevo / Monster tabanlı dizüstülerde fan, güç modu, klavye ışığı ve Fn tuşları gömülü
denetleyiciyle bu dosya üzerinden konuşur. Dosya statik bağlıdır; `msvcp140.dll`, `vcruntime140*.dll` ya da
`GetProductdll.dll` gerekmez.

Clevo / Monster değilseniz hiçbir şey yapmanız gerekmez: uygulama DLL olmadan da çalışır (donanım tespiti, izleme,
NVIDIA ve işlemci ayarları). Yalnızca gömülü denetleyiciye bağlı özellikler kapanır.

## Nasıl elde edilir?

### 1. Otomatik (önerilen)

```powershell
powershell -ExecutionPolicy Bypass -File lib\dll_topla.ps1
```

Betik yönetici izni istemez, hiçbir şey indirmez. Bilgisayarınızda zaten olan dosyayı şu sırayla arar ve
`lib\InsydeDCHU.dll` olarak kopyalar:

1. **Windows sürücü deposu:** `C:\Windows\System32\DriverStore\FileRepository\acpibridge*\InsydeDCHU.dll`.
   AcpiBridge sürücüsü kurulu her Clevo / Monster dizüstüsünde bulunur; üreticinin Control Center'ı kaldırılmış
   olsa bile durur. Microsoft donanım uyumluluk imzalıdır.
2. Üretici Control Center kurulumu: `C:\Program Files (x86)\ControlCenter\DCHU\` ya da `AppInstall\`
3. Microsoft Store "Fn hotkeys and OSD" paketi (`CLEVOCO.FnhotkeysandOSD`): `FnKey\DCHU\`
4. FCUK Control Center setup.exe'nin aldığı yedekler: `C:\ProgramData\FCUK Control Center\yedek\`

`setup_olustur.ps1` dosya eksikse bu betiği kendisi çalıştırır.

### 2. Elle

- Dosya Gezgini'nde yukarıdaki klasörlerden birini açın, `InsydeDCHU.dll` dosyasını bu `lib\` klasörüne kopyalayın.
- Bilgisayarda hiç yoksa: üreticinin destek sayfasından (Monster, Clevo ya da dizüstünüzü satan marka) modelinize
  ait **Control Center** veya **AcpiBridge / DCHU sürücü** paketini indirin, arşivi açın ve içindeki
  `InsydeDCHU.dll` dosyasını buraya kopyalayın. Sürücü paketini kurmak da yeterlidir: dosya sürücü deposuna
  gelir ve 1. adım onu bulur.

## Çalışma anında

Uygulama `lib\InsydeDCHU.dll` dosyasını bulamazsa sırasıyla üretici Control Center klasörüne ve Windows sürücü
deposuna bakar. Bu yüzden DLL'siz derlenmiş bir setup.exe de, AcpiBridge sürücüsü kurulu bir Clevo / Monster
dizüstüde tüm özellikleriyle çalışır.
