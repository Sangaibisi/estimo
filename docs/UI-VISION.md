# Eforge UI Vizyonu

**Bu dosyanın amacı:** Bir tasarım sistemi çalışmasına (Claude Design) girdi olmak. Burada
ürünün *ne hissettireceği*, ekranları, bileşen envanteri, durumları ve mikro-metin dili
tarif edilir; renk/tipografi/spacing kararları tasarım sistemine bırakılır — ama karar
verilmesi gereken her şeyin listesi buradadır. Ürün davranış yasaları
([PRINCIPLES.md](PRINCIPLES.md)) UI'da da bağlayıcıdır; özellikle: nokta değil aralık,
kanıtsız satır yok, önce bağımsız tahmin.

---

## 1. Ürün kişiliği

**Beş sıfat:** Kararlı · Denetlenebilir · Mühendis-ciddi (ama soğuk değil) · Veri-yoğun
sakinlik · Türkçe-birinci.

**Anti-kişilik (asla):** "Sihirli AI" parıltısı, konfeti, tek büyük kesin sayı gösterme,
belirsizliği gizleyen iyimserlik, oyuncaklaşmış maskot dili, İngilizce-Türkçe karışık
arayüz metni.

**Duygusal hedef:** Bu ekrana bakan bir solution architect "bu araç benim yerime karar
vermiyor, benim işimi hazırlamış" demeli. Güven; parlaklıktan değil, **izlenebilirlikten**
doğar: her sayının yanında "neden" duruyor.

**Metafor:** Hukuk bürosunun dava dosyası + mühendislik ölçüm cihazı. "Tahmin" değil
"bilirkişi dosyası" estetiği: sicil, kanıt, imza.

## 2. Personalar

| Persona | Rol | UI'dan beklentisi |
|---|---|---|
| **Analist (Efor Sahibi)** | BRD'yi yükler, soruları müşteriyle yönetir, taslağı yürütür | Hız + net eksik-bilgi listesi; soruları tek tıkla müşteri formatına çevirme |
| **Dev Lead / Solution Architect (Reviewer)** | Kalemleri teknik olarak doğrular, kendi tahminini verir, düzeltir | Kanıta bir bakışta ulaşmak (kod satırı, wiki sayfası); bağımsız-önce akışının hızlı olması |
| **İmza Yetkilisi (Delivery Manager)** | Dokümanı onaylar, müşteriye gider | Varsayım/risk sicilinin eksiksizliği; kimin neyi onayladığının izi; koni aşaması netliği |
| **Admin** | Bağlantılar, model profilleri, tohum seti import'u | Sıkıcı ama şeffaf: senkron durumları, hata kuyrukları, maliyet sayaçları |

## 3. Bilgi mimarisi

```
Çalışma Alanı (workspace)
├── Estimeler (BRD dosyaları listesi — durum rozetli)
│   └── Estime detayı
│       ├── 1. Okuma Odası      (BRD ↔ gereksinim tablosu)
│       ├── 2. Soru Panosu      (netleştirme soruları)
│       ├── 3. Etki Haritası    (modül/servis + kanıt)
│       ├── 4. Efor Masası      (ana ekran: kalemler + bantlar)
│       ├── 5. BoE Önizleme     (doküman + imzalar + export)
│       └── 6. Estime Geçmişi   (versiyonlar, kim ne değiştirdi)
├── Defter (ledger: geçmiş işler, analoji arama, tohum seti import)
├── Kalibrasyon (panolar: kapsama, takım eğrileri, çıpalama)
├── Bilgi (canonical pages kürasyonu, kaynak tazeliği)
└── Yönetim (bağlantılar, modeller, roller)
```

Navigasyon: sol ray (ikon+etiket, daraltılabilir); estime detayında üstte **aşama şeridi**
(Okuma → Sorular → Etki → Efor → BoE) — pipeline durumunu da gösteren gezinme. Klavye ile
aşamalar arası geçiş (`[` `]`), kalemler arası (`j/k` benzeri) — power-user aracı.

## 4. Ekranlar

### 4.1 Çalışma Alanı / Estimeler listesi
- **İş:** Devam eden estimelerin durumu bir bakışta: aşama, bekleyen soru sayısı, SLA yaşı
  ("müşteri 3 gündür soru cevabı bekliyor" tersine "taslak 4 saattir imza bekliyor").
- Kart değil **tablo-öncelikli** (veri-yoğun kültür): dosya adı, müşteri (kurgusal),
  aşama şeridi mini hâli, kalem sayısı, toplam bant (örn. "34–52 a-g"), bekleyen aksiyon sahibi.
- Yeni estime: `.docx` sürükle-bırak; yükleme anında "ilk okuma" ilerleme durumu —
  ilerleme çubuğu *aşama adlarıyla* konuşur ("Tablolar çıkarılıyor… 12 gereksinim bulundu").
- **Boş durum:** ilk kullanımda tohum seti import'una ve örnek fixture BRD'ye yönlendiren,
  ürünü 90 saniyede anlatan sakin bir kılavuz — pazarlama dili yok.

### 4.2 Okuma Odası
- **İş:** Orijinal BRD ile yapılandırılmış hâlini yan yana doğrulamak.
- Sol: sayfa-sadık BRD görünümü (başlık/tablo vurgulanabilir). Sağ: gereksinim tablosu —
  her satır `REQ-014` gibi kararlı kimlik, kaynak paragrafa çift yönlü highlight bağı.
- **Muğlaklık ısısı:** satır kenarında 3 kademe işaret (net / kısmen / muğlak). Muğlak
  satır sayıya değil soruya gider — bunun *neden* böyle olduğu satır içinde bir cümleyle.
- **Çıpa karantina göstergesi:** BRD'de geçen bütçe/tarih ifadeleri özel bir stil ile
  işaretli: "Bu bilgi tahmin motoruna gösterilmiyor (çıpa koruması)" tooltip'i. Bu, ürünün
  omurgasını UI'da görünür kılan an — tasarımda özenle.

### 4.3 Soru Panosu
- **İş:** Eksik bilgiyi müşteriden hızla toplamak.
- Soru kartları: ilgili `REQ` rozetli, gerekçeli ("kabul kriteri yok"), durum akışı
  *Açık → Gönderildi → Cevaplandı → Kaleme işlendi*.
- "Müşteri seti oluştur": seçili soruları tek belge/e-posta metnine derle (TR resmi dil) —
  kopyala veya `.docx` indir.
- Cevap girilince etkilenen kalemlerde "yeniden değerlendirme önerilir" nabzı.

### 4.4 Etki Haritası
- **İş:** "Bu iş kodda nereye dokunuyor"u tartışılabilir kılmak.
- Modül/servis düzeyinde graf veya ısı-listesi (ikisi arasında görünüm anahtarı; graf
  gösterişi için değil, komşuluk sezgisi için). Her düğümde güven düzeyi (yüksek/orta/düşük).
- Düşük güven = ayrı stil + "keşif eforu önerildi" rozeti (belirsizlik gizlenmez, fiyatlanır).
- **Kanıt paneli:** düğüme tıklayınca sağda kod referansları (dosya+satır, kısa önizleme),
  ilgili wiki sayfaları (başlık + tazelik etiketi: "8 ay önce güncellendi"), analoji işleri.

### 4.5 Efor Masası (ana ekran — tasarımın kalbi)
- **İş:** Kalem kalem taslağı insan kararına çevirmek.
- Yoğun tablo: kalem adı, `REQ` bağları, etki özeti, **aralık çubuğu** (üç-nokta görsel:
  O—L—P; L vurgulu ama P asla gizlenmez), varsayım/risk sayacı (aç-kapa satır ekleri),
  kanıt çipleri, durum (taslak / incelendi / imzalı).
- **Bağımsız-önce modu (kritik akış):** Reviewer masaya ilk girişte AI kolonları
  **kapalı** gelir (blur değil — dürüst bir "önce sen" paneli): kendi bandını girer →
  "Taslağı aç" → AI bandı + **delta göstergesi** (senin bandın vs taslak; kesişiyor mu?).
  Bu akışın sürtünmesi düşük olmalı: kalem başına 5–10 saniye.
- **Delphi modu:** birden çok reviewer'ın bantları anonim yatay çizgilerle üst üste;
  uzlaşmazlık genişliği görünür; kimlikler ancak moderatör açınca.
- Toplam şeridi (yapışkan alt bar): kalem toplamı bandı + koni aşaması etiketi
  ("Konsept aşaması: ±4x") + imza ilerlemesi (12/18 kalem).
- Satır düzenleme: bandı sürükle/değer gir; düzenleme anında "gerekçe" mini alanı
  (opsiyonel ama teşvikli — kalibrasyona sinyal).

### 4.6 BoE Önizleme & İmza
- **İş:** Müşteriye gidecek dokümanın son hâli + kurumsal onay.
- Doküman önizleme (şablonlu): kapsam, hariç-tutmalar, kalem tablosu, varsayım sicili,
  risk sicili + contingency, koni aşaması, provenance ekleri, imza sayfası.
- İmza akışı: rol-bazlı sıra (reviewer → imza yetkilisi); her imza satır-seçimli
  ("neyi onaylıyorsun" açık); imza sonrası değişiklik = yeni versiyon (diff görünümü).
- Export: `.docx` (kurumsal şablon parametreli) + arşiv PDF.

### 4.7 Defter (Ledger) & Analoji Arama
- Geçmiş işler tablosu: iş, o günkü bant, gerçekleşme, **sapma rozeti** (altında/bandında/
  üstünde), takım/domain filtreleri.
- Serbest arama: "kampanya bazlı taksitlendirme" → analoji kartları (benzerlik yüzdesi,
  bant vs gerçekleşme mini görseli, tıklayınca o günkü BoE satırı).
- **Tohum seti import sihirbazı:** xlsx/csv sütun eşleme (görsel eşleyici), hata satırları
  kuyruğu, "içeri girmeden önce kişisel/müşteri verisi kontrol listesi" adımı.

### 4.8 Kalibrasyon Panosu
- **İş:** Ürünün dürüstlük vitrini. Buradaki grafikler pazarlama değil, öz-eleştiri.
- Kapsama grafiği: "P10–P90 bandımız gerçeği %78 yakaladı (hedef %80)" — nominal çizgisi
  ile birlikte; takım/domain kırılımı.
- Naif-taban karşılaştırma: pipeline vs analog-medyan; fark yoksa fark yok diye yazar.
- Çıpalama telemetrisi: bağımsız-önce ile sonrası dağılım farkı.
- Soru etkisi: netleştirme sonrası bant revizyon oranı.

### 4.9 Bilgi Kürasyonu (canonical pages)
- Aday sayfa kuyruğu (LLM damıtması) → yan yana kaynak/aday karşılaştırma → onay/redakte →
  versiyonlu yayın. Tazelik uyarı listesi ("bu canonical 6 aydır kaynağından sapmış olabilir").

### 4.10 Yönetim
- Bağlantı kartları (Confluence, Git, gateway): durum, son senkron, hata kuyruğu, ilk-senkron
  ilerlemesi ("büyük wiki'de günler sürebilir" beklenti yönetimi ile).
- Model profilleri: aşama→model eşlemesi (yalnız adlandırılmış profiller; UI'da model adı
  övgüsü yok), maliyet sayaçları.
- Roller & imza yetkileri.

## 5. Bileşen envanteri (tasarım sisteminden beklenen)

Temel kütüphane (tablo, form, dialog, toast, tab, badge…) + Eforge'a özgü olanlar:

1. **AralıkÇubuğu** — üç-nokta bandın kanonik görseli; boyutları: satır-içi mini,
   tablo-standart, karşılaştırma (iki bant üst üste + kesişim vurgusu). Nokta değil bant.
2. **KanıtÇipi** — tür ikonlu (kod / wiki / analoji / soru-cevabı) küçük çip; hover/odak
   önizleme kartı (kod satırı snippet'i, wiki başlığı+tazelik, analoji mini-bandı).
3. **MuğlaklıkİŞareti** — 3 kademe; renk + biçim birlikte (yalnız renk değil).
4. **SoruKartı** — REQ bağı, gerekçe satırı, durum akışı, "sete ekle" aksiyonu.
5. **AnalojiKartı** — benzerlik %, o günkü bant vs gerçekleşme mini görseli, sapma rozeti.
6. **DeltaGöstergesi** — bağımsız tahmin vs taslak bandı; kesişim/kopukluk durumları.
7. **KoniEtiketi** — belirsizlik konisi aşaması (Konsept ±4x → Onaylı ±1.25x); her BoE
   başlığında ve toplam şeridinde.
8. **GüvenDüzeyi** — yüksek/orta/düşük; düşükte "keşif eforu" ikincil aksiyonu.
9. **İmzaBloğu** — kim, ne zaman, hangi satırlar; versiyon bağı.
10. **AşamaŞeridi** — pipeline durumu + gezinme birleşik bileşeni.
11. **SapmaRozeti** — gerçekleşme bandın altında/içinde/üstünde.
12. **ÇıpaUyarısı** — karantinaya alınmış bütçe/tarih ifadesi stili + açıklama tooltip'i.
13. **TazelikEtiketi** — kaynak yaşı ("8 ay önce güncellendi"); eşik üstünde uyarı tonu.
14. **PipelineZamanÇizgisi** — çalışma anındaki aşama ilerlemesi; aşama adlarıyla konuşan
    yükleme durumları.

## 6. Veri-görselleştirme dili

- **Her yerde bant, hiçbir yerde tek sayı.** Tek sayı görünmesi gereken yerde (toplam
  başlığı gibi) her zaman "olası" vurgusu + bandın uçları birlikte.
- Kapsama/kalibrasyon grafikleri: nominal hedef çizgisi her zaman çizili; başarı da
  başarısızlık da aynı sakin dille.
- Renk semantiği ikiye ayrılır: **durum renkleri** (iyi/uyarı/kritik — kalibrasyon,
  tazelik, güven) ve **tür renkleri** (kanıt türleri, aşamalar). İkisi karışmaz; accent
  rengi üçüncü bir roldür.
- Yoğunluk: masaüstü-öncelikli, bilgi-yoğun tablolar; `tabular-nums` hizalı sayılar;
  satır yüksekliği "yoğun" ve "rahat" iki mod.

## 7. Ton & mikro-metin (Türkçe)

- Resmî ama insanca; kısa cümleler; edilgen çatıdan kaçın ("Analiz edildi" değil
  "12 gereksinim çıkardık").
- Belirsizlik dili dürüst: "Bu kalemde kanıt zayıf — banda keşif eforu ekledik."
- Hata metinleri: ne oldu + ne yapmalı ("Confluence'a ulaşamadık (401). Bağlantı
  anahtarını Yönetim → Bağlantılar'dan yenileyin.") Özür yok, suçlama yok.
- Boş durumlar öğretir: Soru Panosu boşsa "Tüm gereksinimler kapıdan geçti — bu iyiye
  işaret" gibi bağlamlı tek cümle.
- Onay anları ağırbaşlı: imzada konfeti yok; "BoE v3 imzalandı — dışa aktarıma hazır."
- Sayı biçimi TR: `1.234,5 a-g`; tarih `12 Ağu 2026`; "adam-gün" kısaltması ürün genelinde
  tek biçim (`a-g`) — sözlükle tutarlı.

## 8. Tema, erişilebilirlik, hareket

- **Açık + koyu tema eşit vatandaş** (uzun okuma oturumları için koyu talep edilecek);
  tokenlar üzerinden, her iki temada da kontrast AA.
- Yalnız-renk ile durum anlatmak yasak (işaret + biçim ikilisi); klavye ile tam akış
  (özellikle Efor Masası'nda satırlar arası dolaşım + bant düzenleme); odak durumları belirgin.
- Hareket ölçülü ve anlamlı: aşama geçişlerinde kısa süreklilik, taslağın "açılma" anında
  (bağımsız-önce reveal) tek özenli geçiş; `prefers-reduced-motion` saygısı. Süs animasyonu yok.
- Türkçe tipografi: `İ/ı` ayrımını doğru işleyen font; uzun bileşik kelimelerin tablo
  hücrelerinde kırılma stratejisi (`hyphens` yerine akıllı truncation + tooltip).

## 9. Tasarım sisteminden istenen çıktılar

1. Token seti: renk rolleri (zemin/nötr/accent + durum + kanıt-türü paleti), tip ölçeği
   (veri-yoğun tablo + doküman-okuma iki bağlam), spacing/density iki mod, radius/elevation dili.
2. Yukarıdaki 14 özgün bileşenin spesifikasyonu (durumlarıyla: default/hover/odak/disabled/
   hata; boş/yükleniyor/hata içerik durumları dahil).
3. Üç örnek ekran kompozisyonu: **Efor Masası** (bağımsız-önce kapalı ve açık iki hâli),
   **Okuma Odası**, **Kalibrasyon Panosu** — açık + koyu.
4. Ses/ton örnek seti: 10 mikro-metin (boş durum, hata, imza onayı…) tasarım diliyle yazılmış.
5. Anti-örnek notu: "sihirli AI" kalıplarından hangilerinin bilinçli dışlandığı.

---

*Bu vizyon [ROADMAP.md](ROADMAP.md) S7'de hayata geçer; tasarım sistemi çıktısı geldiğinde
bu dosya güncellenir, çelişen kısımlar tasarım sistemi lehine düzeltilir ve karar ADR'e bağlanır.*
