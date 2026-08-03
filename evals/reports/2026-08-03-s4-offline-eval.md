# S4 offline eval — 2026-08-03

Deterministic pipeline (no LLM refinement) over the Aurora fixture BRDs vs the
human-authored golden references. AI-arm only: the human and hybrid arms of the
F1 blinded protocol require human estimators (evals/README.md).

- Module attribution accuracy: **92%** (12/13)
- Naive baseline (majority module): 31% — delta **+62%**
- Gate failures: 0
- Question gaps: 0
- Prompt versions: {'questions': 'questions-v1', 'decompose': 'decompose-v1'}

## BRD-AUR-26-01-taksitlendirme.docx
- blocked: ['REQ-G-04']
- work_items: 7
- questions: 1
- module_misses: ['REQ-G-02: expected campaign-engine, got billing-core']

## BRD-AUR-26-02-konsolide-fatura.docx
- blocked: []
- work_items: 6
- questions: 0
- module_misses: []

## BRD-AUR-26-03-bayi-siparis-entegrasyonu.docx
- blocked: ['REQ-H31576BB8', 'REQ-H5C48D3C3', 'REQ-H9295D655', 'REQ-HFF02A0BA']
- work_items: 2
- questions: 4
- module_misses: []

## BRD-AUR-26-04-bakiye-tasima.docx
- blocked: ['REQ-H70A32BD2']
- work_items: 0
- questions: 1
- module_misses: []

