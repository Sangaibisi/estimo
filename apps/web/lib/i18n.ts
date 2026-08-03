/** Minimal i18n: `en` default locale, `tr` first localization (ADR-0004). */

export type Locale = "en" | "tr";

const dict = {
  en: {
    appTitle: "Estimo",
    tagline: "Evidence-linked effort estimation",
    estimates: "Estimates",
    upload: "Upload BRD (.docx)",
    uploading: "Parsing…",
    status: "Status",
    requirements: "Requirements",
    blocked: "Blocked",
    openQuestions: "Open questions",
    workItems: "Work items",
    questionsTab: "Questions",
    deskTab: "Estimate Desk",
    boeTab: "BoE",
    requirementsTab: "Requirements",
    answerPlaceholder: "Customer answer…",
    applyAnswers: "Apply answers",
    buildBoe: "Build BoE draft",
    estimatorName: "Your name",
    independentHint:
      "Independent-first: enter your own band before the AI draft is revealed for an item.",
    record: "Record my band",
    yourBand: "Your band",
    aiBand: "AI draft",
    delta: "Δ likely",
    sign: "Sign line",
    signed: "Signed",
    downloadDocx: "Download BoE (.docx)",
    total: "Total",
    confidence: "Confidence",
    evidence: "Evidence",
    critic: "Critic findings",
    noEstimates: "No estimates yet — upload a BRD to start.",
    copyQuestions: "Copy customer question set",
    anchors: "Quarantined anchors (visible to humans, hidden from models)",
    ambiguity: "Ambiguity",
    idHeader: "ID",
    textHeader: "Text",
    signAllFirst: "The export contains every band — sign all lines on the desk to unlock it.",
    actualsTab: "Actuals",
    actualsHint:
      "Recorded actuals feed the ledger: analog ranking and interval calibration learn from them.",
    actualEffort: "Actual (pd)",
    actualSource: "Source",
    scopeChanged: "Scope changed",
    save: "Save",
    revise: "Revise",
    deviationLabel: "actual / likely",
    actualsAfterSignoff: "Actuals are recorded against the fully signed estimate of record.",
    dashboard: "Dashboard",
    coverageChartTitle: "Interval coverage vs nominal",
    coverageChartHint: "Rolling coverage of the last 20 completed items; dashed line = nominal.",
    maeChartTitle: "MAE — product vs naive median",
    maeChartHint: "Mean absolute error on completed items; lower is better.",
    anchoringTile: "Mean |Δ likely| at reveal",
    zeroDeltaTile: "Near-zero delta share",
    zeroDeltaHint: "High values suggest anchoring — independent bands should rarely match the AI.",
    wipTile: "Estimates in progress",
    revisionTile: "Question revision rate",
    rebuildTile: "Rebuild share",
    samplesShort: "n",
    lowSampleNote: "Small sample — coverage within ±5% needs ~100 completed items.",
    noData: "No data yet — record actuals to light this up.",
    tableView: "Data table",
    connectionsTitle: "Connections",
    newConnection: "New connection",
    connectionName: "Name",
    secretEnvHint:
      "Credentials never pass through this UI or the database — enter the NAME of an env var set on the API container.",
    aclKeysPlaceholder: "ACL keys (comma-separated)",
    lastSync: "Last sync",
    syncNow: "Sync now",
    secretMissing: "secret env missing",
    canonicalTitle: "Canonical pages",
    canonicalHint:
      "The LLM drafts candidates from existing knowledge; only human-approved pages enter retrieval (top authority).",
    canonicalTopic: "Topic…",
    generateCandidate: "Generate candidate",
    approve: "Approve",
    staleSource: "stale",
    deleteConnection: "Delete connection",
    confirmDeleteConnection: "Delete connection “{name}” and its sync history?",
  },
  tr: {
    appTitle: "Estimo",
    tagline: "Kanıt bağlantılı efor tahmini",
    estimates: "Estimeler",
    upload: "BRD yükle (.docx)",
    uploading: "Ayrıştırılıyor…",
    status: "Durum",
    requirements: "Gereksinimler",
    blocked: "Bloke",
    openQuestions: "Açık sorular",
    workItems: "İş kalemleri",
    questionsTab: "Sorular",
    deskTab: "Efor Masası",
    boeTab: "BoE",
    requirementsTab: "Gereksinimler",
    answerPlaceholder: "Müşteri cevabı…",
    applyAnswers: "Cevapları uygula",
    buildBoe: "BoE taslağı oluştur",
    estimatorName: "Adınız",
    independentHint:
      "Önce bağımsız: bir kalem için AI taslağı, kendi bandınızı girmeden açılmaz.",
    record: "Bandımı kaydet",
    yourBand: "Sizin bandınız",
    aiBand: "AI taslağı",
    delta: "Δ olası",
    sign: "Satırı imzala",
    signed: "İmzalı",
    downloadDocx: "BoE indir (.docx)",
    total: "Toplam",
    confidence: "Güven",
    evidence: "Kanıt",
    critic: "Critic bulguları",
    noEstimates: "Henüz estime yok — başlamak için bir BRD yükleyin.",
    copyQuestions: "Müşteri soru setini kopyala",
    anchors: "Karantinadaki çıpalar (insana görünür, modele kapalı)",
    ambiguity: "Muğlaklık",
    idHeader: "ID",
    textHeader: "Metin",
    signAllFirst: "Dışa aktarım tüm bantları içerir — açmak için masadaki tüm satırları imzalayın.",
    actualsTab: "Gerçekleşmeler",
    actualsHint:
      "Kaydedilen gerçekleşmeler ledger'ı besler: analog sıralaması ve aralık kalibrasyonu bunlardan öğrenir.",
    actualEffort: "Gerçekleşen (ag)",
    actualSource: "Kaynak",
    scopeChanged: "Kapsam değişti",
    save: "Kaydet",
    revise: "Düzelt",
    deviationLabel: "gerçekleşen / olası",
    actualsAfterSignoff: "Gerçekleşmeler, tamamı imzalanmış nihai estimeye kaydedilir.",
    dashboard: "Pano",
    coverageChartTitle: "Aralık kapsaması vs nominal",
    coverageChartHint: "Son 20 tamamlanan kalemin kayan kapsaması; kesikli çizgi = nominal.",
    maeChartTitle: "MAE — ürün vs naif medyan",
    maeChartHint: "Tamamlanan kalemlerde ortalama mutlak hata; düşük olan iyidir.",
    anchoringTile: "Açılışta ort. |Δ olası|",
    zeroDeltaTile: "Sıfıra yakın delta payı",
    zeroDeltaHint:
      "Yüksek değer çıpalama işaretidir — bağımsız bantlar AI ile nadiren örtüşmelidir.",
    wipTile: "Devam eden estimeler",
    revisionTile: "Soru revizyon oranı",
    rebuildTile: "Yeniden kurulum payı",
    samplesShort: "n",
    lowSampleNote: "Küçük örneklem — ±%5 kapsama için ~100 tamamlanmış kalem gerekir.",
    noData: "Henüz veri yok — gerçekleşme kaydedince burası canlanır.",
    tableView: "Veri tablosu",
    connectionsTitle: "Bağlantılar",
    newConnection: "Yeni bağlantı",
    connectionName: "Ad",
    secretEnvHint:
      "Kimlik bilgileri bu arayüzden veya veritabanından ASLA geçmez — API konteynerinde tanımlı env değişkeninin ADINI girin.",
    aclKeysPlaceholder: "ACL anahtarları (virgülle)",
    lastSync: "Son senkron",
    syncNow: "Şimdi senkronla",
    secretMissing: "secret env eksik",
    canonicalTitle: "Kanonik sayfalar",
    canonicalHint:
      "LLM mevcut bilgiden aday taslak çıkarır; yalnız insan onaylı sayfalar aramaya girer (en yüksek otorite).",
    canonicalTopic: "Konu…",
    generateCandidate: "Aday üret",
    approve: "Onayla",
    staleSource: "bayat",
    deleteConnection: "Bağlantıyı sil",
    confirmDeleteConnection: "“{name}” bağlantısı ve senkron geçmişi silinsin mi?",
  },
} as const;

const statusLabels: Record<Locale, Record<string, string>> = {
  en: {
    awaiting_answers: "Awaiting answers",
    ready_for_estimation: "Ready for estimation",
    boe_draft: "BoE draft",
  },
  tr: {
    awaiting_answers: "Yanıt bekliyor",
    ready_for_estimation: "Tahmine hazır",
    boe_draft: "BoE taslağı",
  },
};

export function statusLabel(locale: Locale, status: string): string {
  return statusLabels[locale][status] ?? status;
}

export type MessageKey = keyof (typeof dict)["en"];

export function t(locale: Locale, key: MessageKey): string {
  return dict[locale][key];
}

export function detectLocale(): Locale {
  if (typeof window !== "undefined") {
    const saved = window.localStorage.getItem("estimo-locale");
    if (saved === "tr" || saved === "en") return saved;
  }
  return "en";
}

export function setLocale(locale: Locale): void {
  window.localStorage.setItem("estimo-locale", locale);
}
