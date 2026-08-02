# Product Principles / Ürün Yasaları

These are **evidence-derived, non-negotiable product behaviors**. Each cites its basis in
[RESEARCH.md](RESEARCH.md). A feature that violates one is a bug, even if users ask for it —
changing a principle requires new evidence and a PR against this file first.

1. **Ranges, never points. / Nokta değil aralık.**
   Every effort output is a three-point range (optimistic / likely / pessimistic) with a
   confidence level tied to the cone-of-uncertainty stage. (Research §3.2, §4 — expert 90%
   intervals capture reality only 60–70%; McConnell 4x/16x cone.)

2. **No line without evidence. / Kanıtsız satır yok.**
   Every estimate line links its basis: code refs (`file+line`), wiki pages (`pageId+version`),
   analog history items. Basis-of-estimate provenance is what makes the document auditable.
   (Research §4 — professional estimate anatomy.)

3. **Questions before numbers. / Sayıdan önce sorular.**
   Requirements failing the ambiguity gate get clarification questions, not estimates.
   Ambiguity measurably corrupts downstream output. (Research §3.3.)

4. **Independent first. / Önce bağımsız tahmin.**
   Reviewers record their own estimate before the AI draft is revealed; the delta is logged
   as anchoring telemetry. Anchoring effect on experts is huge (Cohen's d ≈ 1.19). (§3.3.)

5. **Anchor quarantine. / Çıpa karantinası.**
   Customer-supplied budgets, deadlines and effort hints in the BRD are stripped from
   estimation prompts (they remain visible to humans, flagged). LLMs absorb anchors at
   near-human rates. (§3.3.)

6. **No verbalized confidence. / Sözel güven yasak.**
   Never surface "I'm 90% sure" from a model. Uncertainty comes from sampling variance +
   conformal prediction + historical error distributions. (§3.3.)

7. **Honesty against the naive baseline. / Naive-baseline dürüstlüğü.**
   Every eval and every pilot reports against the naive analog-median baseline. Sophisticated
   models routinely fail to beat it in the literature; we prove it, not assume it. (§3.1.)

8. **Edits are signal. / Düzeltme birinci-sınıf sinyaldir.**
   Reviewer edits feed retrieval ranking and calibration. The product learns from its own
   review loop, not just from ingestion. (§5, feedback-driven retrieval.)

9. **A human signs every line. / Her satırda insan imzası.**
   No AI-drafted line becomes a conclusion without a named human sign-off; the signature
   trail ships inside the BoE document. (PMI 2026 AI standard; §4.)

10. **Small items have floors. / Küçük işin taban maliyeti var.**
    Below a size threshold, effort is dominated by fixed overhead, not size — micro-items
    get overhead floors instead of scaled estimates. (COSMIC ≤5 CFP correlation collapse, §4.)
