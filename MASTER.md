# FCUK Control Center - Tasarım Sistemi (v3)

Bu belge arayüzün tek kaynağıdır. `ui/index.html` içindeki her renk, ölçü ve süre buradaki bir belirteçten gelir.

## Tezler

**Görsel tez:** Soğuk grafit-siyah bir cihaz paneli. Sabit bir marka rengi yok; ekrandaki tek renk klavyenin o anki canlı rengi ve bu renk, pencerenin üst yarısını kaplayan klavye çiziminden tüm pencereye sızıyor. Yazı tipi Bahnschrift: her Windows'ta kurulu, DIN kökenli bir cihaz etiketi yazısı, indirme gerektirmiyor. Rakamlar sabit genişlikte. 4 px ızgara, tek ekran. 6 px keskin köşeler, ince çizgili düz yüzeyler, gölge yok.

**Etkileşim tezi:** Yumuşak ama kısa geçişler, 200-320 ms, girişte ease-out, çıkışta ease-in. Üzerine gelince yalnızca kenar, zemin ve parlaklık değişir; büyüme yok. Kaydırma efekti yok. Mod değişince ayar paneli 200 ms'de söner, 260 ms'de 8 px aşağıdan gelir. Yasak: zıplama, esneme, donanım durumunu göstermeyen döngüler, paralaks.

**Allowed patterns:** klavye çiziminin ışıması ve altındaki ışık sızması (`.kb`, `.kb-glow`, `.mark`), pencereye yayılan renk sızması (`.bleed`), klavye önizlemesinin sürekli güncellenmesi (gerçek donanım durumu, "Önizlemeyi durdur" ile duraklatılır), sabit genişlikli sayısal göstergeler, ince ayırıcı çizgiler.

## Renk

| Belirteç | Değer | Kullanım |
|---|---|---|
| `--bg` | `#0a0c0f` | Pencere zemini |
| `--surface` | `#111419` | Alt paneller, kontrol zemini |
| `--surface-2` | `#181c23` | Üzerine gelme, seçili satır, açılır pencere |
| `--chassis` | `#0d0f13` | Klavye çerçevesi |
| `--cap` / `--cap-edge` | `#14171c` / `#222730` | Tuş yüzü ve üst kenarı |
| `--line` / `--line-strong` | `#252a33` / `#3b4350` | Ayırıcılar, kontrol kenarları |
| `--text` / `--text-hi` | `#eceff4` / `#ffffff` | Ana metin, vurgulu metin |
| `--text-2` | `#a9b1be` | İkincil metin (surface üzerinde 8.54:1) |
| `--text-3` | `#818a99` | Etiketler (surface 5.30:1, surface-2 4.90:1) |
| `--danger` | `#ff6b6b` | Hata, silme onayı (surface-2 üzerinde 6.16:1) |
| `--live` | çalışırken | Klavyenin o anki rengi |
| `--live-ink` | çalışırken | `--live` renginin okunur hali: parlaklığı en az 0.24 olana dek beyaza yaklaştırılır (en kötü durumda 4.72:1) |
| `--spectrum` | renk çemberi | Ton kaydırıcısı ve Gökkuşağı şeridi |

## Yazı

- Başlık ve etiket: `"Bahnschrift","DIN Alternate","Segoe UI Variable Display","Segoe UI",sans-serif`
- Gövde: `"Segoe UI Variable Text","Segoe UI",system-ui,sans-serif`
- Ölçek: 11, 12, 13, 15, 20, 28, 44 px (`--fs-1` ... `--fs-7`)
- Etiketler: 11 px, 600, büyük harf, 0.12em aralık. Başlıklar %85-90 genişlik ekseni.
- Tüm sayısal göstergelerde `tabular-nums`.

## Aralık, köşe, hareket

- Aralık: 4, 8, 12, 16, 24, 32, 48 px (`--s-1` ... `--s-7`)
- Köşe: 3, 6, 10 px (`--r-1` ... `--r-3`)
- Süre: `--t-fast` 200 ms, `--t-med` 260 ms, `--t-slow` 320 ms
- Eğri: `--ease-out` `cubic-bezier(.2,0,0,1)`, `--ease-in` `cubic-bezier(.4,0,1,1)`
- Azaltılmış hareket: geçişler kapanır, `.bleed` ve `.kb-glow` gizlenir.

## Bileşenler

Her etkileşimli bileşenin beş durumu vardır: varsayılan, üzerine gelme, odak (2 px `--live-ink` çerçeve), basılı, devre dışı (%40 opaklık).

- **Düğme** (`.btn`, `.btn.solid`): ince kenarlı; dolu olan yalnızca birincil eylemde.
- **Kaydırıcı**: 4 px iz, 14 px köşeli tutamak; üzerine gelince tutamak çevresinde halka.
- **Anahtar** (`.switch`): açıkken iz `--live-ink` olur.
- **Renk durağı** (`.stop` + `.stop-x`): renk karesi, kodu ve silme düğmesi.
- **Bölmeli seçim** (`.seg`): seçili olanın kenarı `--live-ink`.
- **Gösterge** (`.meter`): ölçülen 0-1 değeri, `transform: scaleX` ile.
- **Kayıtlı mod satırı** (`.preset`): palet şeridi, ad, mod adı; silme iki tıkla.

## Yerleşim ve gezinme (v3)

Özellik sayısı arttıkça tek sütunlu uzun menü yerine iki katmanlı gezinme kullanılır. Yeni sayfa eklerken menüye yeni satır değil, uygun kategoriye yeni sekme eklenir.

- **Ray** (`.rail`, 96 px): beş kategori, ikon + kısa etiket. Seçili kategoride solda 2 px `--live-ink` çizgi, ikon `--live-ink` ve hafif `--live` ışıması. Ayarlar rayın dibinde.
- **Başlık çubuğu** (`.bar`): kategori adı ve o kategorinin sekmeleri (`.nav`). Seçili sekmenin altında 2 px `--live-ink` çizgi. Kategoride tek sayfa varsa sekmeler gizlenir (`.bar.solo`).
- **Durum çubuğu** (`.status`): her sayfada cihaz, sürüm, canlı CPU/GPU sıcaklığı, güç, fan devri ve profil/ısı koruması/yetki çipleri. Sayfalarda bu ölçümler tekrarlanmaz.
- **Kategoriler** (`CATS`, `ui/index.html`):

| Kategori | Sekmeler |
|---|---|
| İzleme | Canlı, Geçmiş, Donanım |
| Performans | Profiller, Otomasyon, Fanlar, İşlemci, NVIDIA, MSI (yalnızca MSI'da) |
| Klavye | (tek sayfa) |
| Ses ve ekran | (tek sayfa) |
| Ayarlar | Genel, Güncellemeler, Destek |

- Ek betikler (`sayfalar.js`, `gecmis.js`) sayfalarını `window.ccNav.add(id, anahtar)` ile ekler; sekme sırası `CATS` sırasıdır.
- Sayfa başlığı (`.page-head h2`) yalnızca ekran okuyucu içindir; görünen başlık sekmedir. Giriş paragrafı en fazla 86ch.

### Ayar satırı

Ayarlar ve Otomasyon gibi denetim ağırlıklı sayfalarda kart ızgarası yerine gruplar kullanılır:

- **Grup** (`.group`): ince kenarlı yüzey; üstte `.group-head` (etiket + isteğe bağlı eylem).
- **Satır** (`.setting`): solda başlık (`.st-t`, 15 px) ve açıklama (`.hint`), sağda tek denetim (anahtar, seçim, düğme). Satırlar arasında 1 px `--line`.
- **Serbest alan** (`.pad`): liste, günlük ya da düğme sırası gibi satıra sığmayan içerik.
- İki sütunlu düzen `.cols` (1.35fr / 1fr), 1100 px altında tek sütun.

