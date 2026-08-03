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
