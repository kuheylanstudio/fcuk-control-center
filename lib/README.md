# lib/

Bu klasör üreticiye ait kitaplıklar içindir ve depoya **yüklenmez** (`.gitignore`).

Clevo / Monster tabanlı dizüstülerde fan, güç modu, klavye ışığı ve Fn tuşları için şu dosyaları kendi
bilgisayarınızdaki üretici Control Center kurulumundan buraya kopyalayın:

| Dosya | Nerede bulunur (örnek) |
|---|---|
| `InsydeDCHU.dll` | `C:\Program Files (x86)\ControlCenter\DCHU\` ya da Control Center kurulum paketi |
| `GetProductdll.dll` | aynı klasör |
| `msvcp140.dll`, `vcruntime140.dll`, `vcruntime140_1.dll` | aynı klasör ya da Microsoft Visual C++ Redistributable |

Bu dosyalar yoksa uygulama yine çalışır: donanım tespiti, izleme, NVIDIA ve işlemci ayarları kullanılabilir,
yalnızca gömülü denetleyiciye bağlı özellikler kapanır.
