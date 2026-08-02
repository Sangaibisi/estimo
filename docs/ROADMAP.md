# Eforge Yol Haritası

Planın ve ilerlemenin **tek kanonik kaynağı** bu dosyadır. Mimari gerekçeler
[ARCHITECTURE.md](ARCHITECTURE.md) ve [RESEARCH.md](RESEARCH.md) içindedir; bu dosya
"ne, hangi sırayla, bitti mi" sorusuna cevap verir.

## Takip kuralları

- Her madde bir kimlik taşır (örn. `S2-3`). PR'lar maddeyi kimliğiyle referans verir ve
  **aynı PR içinde** checkbox'ı işaretler (bkz. [AGENTS.md](../AGENTS.md) §2.6).
- Sprint durumu: 🔵 Planlandı · 🟡 Devam ediyor · 🟢 Tamamlandı · ⏸️ Beklemede.
  Aktif sprint her zaman en fazla bir tanedir (🟡).
- Madde sessizce silinmez/değiştirilmez; kapsam değişikliği PR açıklamasında gerekçelendirilir.
- Sprint çıkış kapısı sağlanmadan sonraki sprint 🟡'ya çekilmez.

## Faz haritası

| Faz | Sprintler | Hedef | Sürüm hedefi |
|---|---|---|---|
| **F0 — Temel** | S0 | Repo + veri temeli: sentetik fixture'lar, ledger şeması, tohum seti envanteri | v0.1 ✅ (dokümantasyon) |
| **F1 — PoC** | S1–S4 | BRD → dekompozisyon + sorular + analoji kanıtlı taslak; golden set üzerinde körleme değerlendirme | v0.4 |
| **F2 — Dogfood Pilot** | S5–S8 | Kod farkındalığı + efor bantları + review UI + kalibrasyon döngüsü; gerçek akışta kullanım | v1.0 |
| **F3 — Ürünleşme** | S9–S10 | Connector'lar, multi-tenant, BYOC, Atlassian yüzeyi, MCP server | v1.x |

**Körleme değerlendirme kapısı (F1→F2):** golden set üzerinde AI-yalnız / insan-yalnız /
hibrit karşılaştırması; hibrit akış, insan-yalnıza karşı süre kazanıp kalibrasyonda
gerilemiyorsa geçilir. Naif taban çizgisine karşı delta her raporda zorunlu
([PRINCIPLES](PRINCIPLES.md) #7).

---

## S0 — Kuruluş & Veri Temeli · `Durum: 🟡 Devam ediyor`

**Amaç:** Kod yazmaya başlamadan önce veri gerçekliğini kurmak: sentetik Türkçe BRD
fixture'ları, ledger şeması ve geçmiş arşivin (BRD + verilen eforlar) tohum setine
dönüşme yolu.

**Mimari dilimi:** Efor defteri (ledger) veri modeli; fixture standartları; sanitization ilkeleri.

- [x] S0-1 Repo kuruluşu: araştırma dosyası, AGENTS/CONTRIBUTING/SECURITY, ilkeler, ADR'ler, yol haritası, UI vizyonu
- [ ] S0-2 `fixtures/` standardı: kurgusal şirket/operatör evreni tanımı (isimler, ürünler) + fixture adlandırma kuralları — gerçek veriyle benzerlik riskini SECURITY.md'ye göre denetleyen kontrol listesi
- [ ] S0-3 3–5 sentetik Türkçe BRD (`.docx`): farklı olgunlukta (temiz şablonlu / dağınık / tablosuz), telco senaryoları (kampanya kuralı, faturalama değişikliği, CRM akışı, entegrasyon)
- [ ] S0-4 Ledger şeması v0 (doküman olarak): `BRD → iş kalemi → verilen efor (üç-nokta?) → gerçekleşme (varsa) → meta (takım, domain, tarih)`; tohum-seti alan eşleme tablosu (xlsx/csv sütunları → şema)
- [ ] S0-5 Tohum seti envanter şablonu: proje sahibinin dahili arşivini (geçmiş BRD'ler + efor tabloları) İÇERİDE derlerken kullanacağı kontrol listesi — repoya yalnız şablon girer, veri girmez
- [ ] S0-6 Golden set tasarım notu: değerlendirme senaryoları, referans dekompozisyonlar ve metrik tanımları (`evals/README.md`)

**Çıkış kapısı:** En az 3 sentetik BRD fixture'ı repoda; ledger şeması ve tohum-seti eşleme
tablosu onaylı; golden set tasarımı yazılı.

---

## S1 — İskelet · `Durum: 🔵 Planlandı`

**Amaç:** Monorepo altyapısı, domain modelleri ve **gateway** modülüyle çalışan (henüz akılsız)
bir uçtan uca omurga.

**Mimari dilimi:** `packages/core`, `packages/gateway`, `apps/api` iskeleti, CI.

- [ ] S1-1 Python tooling: uv workspace, ruff, mypy, pytest, pre-commit; `packages/` + `apps/` yerleşimi (AGENTS.md §5)
- [ ] S1-2 `packages/core`: Pydantic domain modelleri — `Requirement`, `WorkItem`, `EstimateLine` (üç-nokta + kanıt URI listesi zorunlu alan), `AssumptionRisk`, `BoeDocument`, `LedgerEntry`
- [ ] S1-3 `packages/gateway`: OpenAI-uyumlu istemci (configurable base URL), aşama-bazlı model routing profili, 429/budget geri-çekilme, istek/yanıt logging kancası; sürüm pinleme
- [ ] S1-4 CI (GitHub Actions): lint + type + test; **provider-SDK grep guard** (gateway dışında provider importu = build kırılır); `ee/`/`enterprise/` yol koruması
- [ ] S1-5 `apps/api` FastAPI iskeleti: sağlık ucu, run kaydı (Postgres), docker-compose (postgres+pgvector)
- [ ] S1-6 release-please + Conventional Commits doğrulaması
- [ ] S1-7 `.env.example` + config yükleme (pydantic-settings)

**Çıkış kapısı:** CI yeşil; gateway üzerinden örnek bir tamamlama çağrısı compose ortamında
uçtan uca çalışıyor; provider-SDK guard testle kanıtlı.

---

## S2 — BRD Alımı & Yapısal Ayrıştırma · `Durum: 🔵 Planlandı`

**Amaç:** Türkçe `.docx` BRD'yi kararlı kimlikli, yapısal gereksinim tablosuna çevirmek.

**Mimari dilimi:** `packages/parse` (Docling + python-docx).

- [ ] S2-1 Docling entegrasyonu: başlık hiyerarşisi, tablolar, listeler → ara temsil
- [ ] S2-2 Gereksinim segmentasyonu: madde/başlık bazlı bölme, **kararlı requirement ID** üretimi (`REQ-…`), kaynak sayfa/paragraf izi
- [ ] S2-3 **Çıpa karantinası**: bütçe/tarih/efor imalarını tespit et, işaretle, tahmin bağlamından ayır (insan görür, model görmez — PRINCIPLES #5)
- [ ] S2-4 Muğlaklık ön-skoru v0 (kural + LLM karması): eksik aktör/koşul/kabul kriteri sinyalleri
- [ ] S2-5 Parse eval'i: fixture'lar üzerinde segmentasyon doğruluğu golden karşılaştırması; bozuk şablon dayanıklılık testleri
- [ ] S2-6 CLI: `eforge parse <brd.docx>` → JSON gereksinim tablosu

**Çıkış kapısı:** Tüm fixture BRD'ler ID-kararlı ayrışıyor; çıpa tespiti fixture'lardaki
tüm ekilmiş çıpaları yakalıyor; parse eval CI'da.

---

## S3 — Efor Defteri & Türkçe Retrieval · `Durum: 🔵 Planlandı`

**Amaç:** Tohum setini içeri alacak import hattı + Türkçe'de kanıtlanmış hibrit arama.

**Mimari dilimi:** `packages/knowledge` (ledger + arama rafları).

- [ ] S3-1 Ledger şemasının Postgres uygulaması + import CLI (xlsx/csv eşleme, S0-4 tablosuna göre; hatalı satır raporu)
- [ ] S3-2 **Türkçe retrieval spike'ı**: TR analyzer'lı BM25 + 2–3 çokdilli embedder + reranker adayının sentetik TR golden retrieval seti üzerinde karşılaştırması → sonuç ADR-0004 güncellemesiyle sabitlenir
- [ ] S3-3 Hibrit arama servisi: BM25 + dense + reranker + bağlamsal chunk başlıkları; ACL/tazelik metadata alanları şemada hazır
- [ ] S3-4 Analoji sorgusu: iş kalemi → en yakın geçmiş kalemler (benzerlik + o günkü efor + gerçekleşme + sapma); "analoji kartı" API sözleşmesi
- [ ] S3-5 Retrieval eval'i (Ragas tarzı): recall/precision panosu CI'da

**Çıkış kapısı:** Tohum-set import'u örnek dosyayla uçtan uca; TR retrieval seçimi ölçümle
gerekçeli; analoji kartı API'si fixture ledger'ında anlamlı sonuç veriyor.

---

## S4 — Dekompozisyon & Belirsizlik Kapısı · `Durum: 🔵 Planlandı`

**Amaç:** PoC'nin kalbi: BRD → iş kalemleri → netleştirme soruları; golden set üzerinde
ilk körleme değerlendirme.

**Mimari dilimi:** `packages/pipeline` (LangGraph v0), `evals/` harness.

- [ ] S4-1 LangGraph pipeline v0: parse → decompose → gate → questions; checkpoint/resume; Pydantic AI typed düğümler
- [ ] S4-2 Dekompozisyon düğümü: ontoloji-rehberli (S0 evrenindeki modül taksonomisi; telco eTOM/SID etiketleri opsiyonel alan)
- [ ] S4-3 Belirsizlik kapısı: muğlaklık skoru eşiği; geçemeyen kalem "soru üretimi"ne düşer, efora **giremez** (PRINCIPLES #3 mekanik uygulanır)
- [ ] S4-4 Netleştirme sorusu üretici: şirket-tarzı 10+ örnekli few-shot (fixture evreninden), soru kalitesi rubriği
- [ ] S4-5 HITL checkpoint v0 (CLI/JSON seviyesinde): cevaplar pipeline'a geri girer, kapı yeniden değerlendirir
- [ ] S4-6 Eval harness v1 (DeepEval/promptfoo): dekompozisyon kapsama, soru kalitesi (rubrik + insan etiketli mini set), **naif taban çizgisi hesabı** dahil rapor formatı
- [ ] S4-7 Prompt sürümleme düzeni: `packages/pipeline/prompts/` + CI'da prompt-değişikliği→eval tetikleyici

**Çıkış kapısı (F1 körleme değerlendirmesi):** Golden set üzerinde dekompozisyon+soru
çıktıları insan referansıyla körleme karşılaştırıldı; sonuç raporu `evals/reports/`
altında; devam/düzelt kararı verildi.

---

## S5 — Kod Farkındalığı · `Durum: 🔵 Planlandı`

**Amaç:** İş kalemlerini gerçek kod tabanına bağlamak: repo haritası → sembol grafı →
modül wiki'leri → etki haritası.

**Mimari dilimi:** `packages/knowledge` kod rafı; pipeline'a `impact` worker'ı.

- [ ] S5-1 tree-sitter repo haritası: sembol çıkarımı + önem sıralaması + token-bütçeli özet (java/ts/py öncelik)
- [ ] S5-2 SCIP entegrasyonu: scip-java/scip-typescript index → defs/refs/dependents graf deposu; kalemden tohum-sembol → etkilenen komşuluk sorgusu
- [ ] S5-3 Modül wiki üretimi: deepwiki-open fork'u (gateway'e yönlendirilmiş) veya eşdeğer kendi üreticimiz; "amaç + arayüz + bağımlılık" sayfaları retrieval korpusuna
- [ ] S5-4 Impact worker: repo haritası + graf + arama karışımı; modül başına güven düzeyi; düşük güvende **"keşif eforu" kalemi** önerisi (ARCHITECTURE risk #1)
- [ ] S5-5 Kanıt URI standardı uygulaması: `repo://<repo>@<sha>/<path>#L<start>-L<end>` + BoE satırlarında zorunluluk denetimi
- [ ] S5-6 Kod rafı eval'i: fixture repo (sentetik mini BSS projesi) üzerinde etki-haritası doğruluğu

**Çıkış kapısı:** Fixture repo'da bilinen değişiklik senaryoları için etki haritası kabul
eşiğinde; her impact iddiası kanıt URI'li.

---

## S6 — Efor Bandı & Kalibrasyon v1 · `Durum: 🔵 Planlandı`

**Amaç:** Analoji-temelli üç-nokta bantlar + varsayım/risk sicilleri + BoE dokümanı.

**Mimari dilimi:** `packages/calibrate`, `packages/pipeline` efor düğümleri, BoE render.

- [ ] S6-1 Analog few-shot seçici: ledger'dan kalem-benzeri geçmişler (SSBSE-2023 bulgusu: seçim kalitesi model kalitesinden önemli)
- [ ] S6-2 Üç-nokta üretimi: analog dağılımı + LLM muhakemesi; sözel güven yerine örnekleme varyansı (PRINCIPLES #6)
- [ ] S6-3 Conformal/kuantil aralıklar: tohum seti hata dağılımıyla kapsama hedefli genişletme; küçük kalem taban-maliyet kuralı (PRINCIPLES #10)
- [ ] S6-4 Varsayım & risk üreticisi: kalem-bazlı + doküman-geneli sicil; koni aşaması etiketi
- [ ] S6-5 Critic/tutarlılık geçişi: kalemler arası çakışma, toplam-tutarlılık, kanıtsız satır reddi; judge ≠ generator
- [ ] S6-6 BoE `.docx` render: şablon-parametreli (logo/başlık), imza blokları, provenance ekleri; TR sayı biçimi
- [ ] S6-7 Efor eval'i: golden set MAE/MdAE + aralık kapsaması + naif-taban delta raporu

**Çıkış kapısı:** Fixture BRD'den, kanıt linkli, varsayım/riskli, üç-noktalı BoE `.docx`
uçtan uca üretiliyor; eval raporu naif tabanı içeriyor.

---

## S7 — Review UI & Bağımsız-Önce Akışı · `Durum: 🔵 Planlandı`

**Amaç:** İnsan katmanı: taslağı inceleme, düzeltme, imzalama — çıpalanmadan.

**Mimari dilimi:** `apps/web` (Next.js, TR-first; tasarım sistemi [UI-VISION.md](UI-VISION.md) çıktısından).

- [ ] S7-1 Design system entegrasyonu (Claude Design çıktısı token + komponent kütüphanesi)
- [ ] S7-2 Çalışma alanı + BRD yükleme + pipeline durum zaman çizgisi
- [ ] S7-3 Gereksinim/soru panosu: kalem listesi, muğlaklık vurguları, soru kartları (kopyalanabilir müşteri soru seti çıktısı)
- [ ] S7-4 **Bağımsız-önce efor masası**: AI kolonu gizli → kendi tahminini gir → aç → delta gösterimi; anonim çoklu-değerlendirici (Delphi) modu
- [ ] S7-5 Kanıt çipleri: hover/odak önizlemeli kod/wiki/analoji referansları
- [ ] S7-6 Satır imzası + doküman onay akışı; BoE önizleme/`.docx` export
- [ ] S7-7 Edit telemetrisi: bölüm bazında düzeltme mesafesi + çıpalama deltası kaydı (Langfuse'a olay)
- [ ] S7-8 i18n altyapısı (`tr` varsayılan, `en` iskelet)

**Çıkış kapısı:** Bir BRD'nin tam turu (yükle → sorular → cevap → taslak → bağımsız-önce
inceleme → imza → export) UI üzerinden tamamlanıyor.

---

## S8 — Kalibrasyon Döngüsü & Panolar · `Durum: 🔵 Planlandı`

**Amaç:** Ürünü öğrenen sisteme çevirmek: gerçekleşmeler girer, aralıklar ve analoji
seçimi güncellenir, dürüstlük panoları herkese açık.

**Mimari dilimi:** `packages/calibrate` döngüsü, `apps/web` panolar, Langfuse self-host.

- [ ] S8-1 Gerçekleşme girişi: manuel form + toplu import; kalem ↔ gerçekleşme eşleme deneyimi
- [ ] S8-2 Kalibrasyon işleri: hata dağılımı güncelleme → aralık genişlikleri; analoji sıralamasına geri besleme (edit + gerçekleşme sinyalleri — PRINCIPLES #8)
- [ ] S8-3 Panolar: aralık kapsama vs nominal, takım/domain eğrileri, çıpalama telemetrisi, naif-taban karşılaştırması, soru-sonrası revizyon oranı
- [ ] S8-4 Langfuse self-host entegrasyonu: iz + kullanıcı geri bildirimi + değerlendirme kuyruğu
- [ ] S8-5 Dogfood pilot çalıştırması: gerçek akışta N BRD (içeride) — repoya yalnız anonim metrik özetleri girer
- [ ] S8-6 DORA-tarzı ikinci-derece izleme: taslak hızı ↑ iken rework/WIP izleme notları

**Çıkış kapısı (F2→F3):** Pilot metrikleri: çevrim süresi anlamlı ↓, kapsama nominal
bandda, kadro memnuniyeti anketi olumlu; karar raporu yazıldı.

---

## S9 — Bağlayıcılar & Canlı Bilgi · `Durum: 🔵 Planlandı`

**Amaç:** Fixture'lardan gerçek kaynaklara: Confluence/git canlı senkron + kürasyon.

**Mimari dilimi:** `packages/connectors`.

- [ ] S9-1 Confluence v2 crawl: sayfa+kısıt(ACL)+versiyon metadata, checkpoint'li artımlı senkron, puan-limit uyumlu hız planı (günler sürebilen ilk senkron UX'i)
- [ ] S9-2 Git senkron servisi: çoklu repo clone/fetch, index tazeleme tetikleyicileri
- [ ] S9-3 ACL ön-filtresi retrieval'da zorunlu hale gelir (SECURITY.md ilkesi mekanikleşir)
- [ ] S9-4 Canonical pages kürasyon akışı: aday üretimi (LLM damıtma) → insan onayı → versiyonlama → retrieval önceliği
- [ ] S9-5 Tazelik/otorite skorlama + bayat-kaynak uyarıları (kanıt çipinde "bu sayfa 18 aydır güncellenmedi")
- [ ] S9-6 Jira connector (opsiyonel, generic): epic/story çekimi — ledger'ı Jira'yla besleyen kurulumlar için

**Çıkış kapısı:** Gerçek bir Confluence space + çoklu repo kurulumunda pipeline fixture'sız
çalışıyor; ACL testleri yeşil.

---

## S10 — Ürünleşme & Atlassian Yüzeyi · `Durum: 🔵 Planlandı`

**Amaç:** Tek-kiracıdan ürüne: kimlik, izolasyon, paketleme, dağıtım yüzeyleri.

**Mimari dilimi:** multi-tenant temel, `infra/` Helm, Forge app, Eforge MCP server.

- [ ] S10-1 AuthN/Z: SSO (OIDC), rol modeli (tahminci / reviewer / imza yetkilisi / admin)
- [ ] S10-2 Tenant izolasyonu: index namespace + anahtar ayrımı; stateless-per-tenant pipeline doğrulaması
- [ ] S10-3 Helm chart + BYOC kurulum kılavuzu; hava-boşluklu kurulum notları (açık-ağırlık model profili)
- [ ] S10-4 Forge Rovo Agent front-door: Jira/Confluence içinden "Eforge'a gönder" + durum kartı
- [ ] S10-5 Eforge MCP server: estimate/kanıt/dekompozisyon sorgu araçları (OAuth, stateless HTTP)
- [ ] S10-6 Dokümantasyon sitesi + kurulum hızlı-başlangıcı; Marketplace hazırlık değerlendirmesi
- [ ] S10-7 FP/COSMIC opsiyonel katman tasarım notu (Nesma enhancement-FPA) — uygulama sonraki döngüye

**Çıkış kapısı:** İkinci (dış) kurulumun onboarding'i < 2 hafta; güvenlik gözden geçirmesi
(ACL, tenant sızıntı testleri) yeşil.

---

## Sürekli hatlar (her sprintte geçerli)

- **E — Evals:** Estimation davranışını değiştiren her PR golden-set raporu taşır; naif
  taban zorunlu (PRINCIPLES #7); judge ≠ generator; periyodik insan-etiketli yeniden çıpalama.
- **G — Güvenlik & lisans:** Gerçek veri yasağı (SECURITY.md); bağımlılık lisans denetimi
  (AGPL/SSPL/BUSL/ELv2 → ADR şartı); gateway sürüm pinleme.
- **D — Doküman hijyeni:** Kanonik dosyalar dışında plan/durum dokümanı üretilmez; bayatlayan
  içerik aynı PR'da düzeltilir veya silinir (AGENTS.md §2.4).
