# Fixtures — The Aurora Universe

All test data in this repository lives in **one coherent fictional universe**, aligned
with the delivered design system's example scenario. Real customer data is forbidden
everywhere ([SECURITY.md](../SECURITY.md)); fixtures are synthetic by construction, not
by anonymization.

## The universe

| Entity | Name | Notes |
|---|---|---|
| Operator (the customer) | **Aurora Telekom A.Ş.** ("Aurora Telecom" in English contexts) | Fictional Turkish mobile/fixed operator; sends Turkish BRDs. |
| Vendor (Estimo's user) | **Meridyen Teknoloji** | Fictional BSS software vendor; owns the codebase, wiki and estimate history that ground the estimates. |
| People | A. Demir (Analyst), D. Aksoy (Reviewer/Dev Lead), M. Yılmaz (Delivery Manager) | Matches the design's role examples. Invent additional common-Turkish-name characters freely; never use a real, identifiable person. |

### Meridyen's BSS estate (module taxonomy for impact maps)

`billing-core` · `crm-suite` · `product-catalog` · `campaign-engine` · `dealer-portal` ·
`integration-hub` · `payment-adapter` · `invoice-render` · `selfcare-web`

(`billing-core` appears in the design's Admin screen — keep these names stable; they are
the ontology labels used by decomposition fixtures and golden sets.)

## BRD fixtures (`fixtures/brd/`)

- Naming: `BRD-AUR-<yy>-<nn>-<slug>.docx` (e.g. `BRD-AUR-26-01-taksitlendirme.docx`).
- Language: **Turkish**, realistic telco business register (they simulate real input —
  see [ADR-0004](../docs/adr/0004-turkish-first-pipeline.md)).
- Each BRD deliberately **plants test features** (anchors to quarantine, ambiguities that
  must fail the gate, tables to parse); the plants are recorded in
  [`brd/manifest.json`](brd/manifest.json) so parse/gate evals can assert against them.
- Maturity varies on purpose: clean templated / messy unstructured / micro-CR — the
  pipeline must survive all three.
- Fixtures are **generated, not hand-edited**: `tools/generate_brds.py` is the source of
  truth; edit the content definitions there and regenerate, so the `.docx` files and
  `manifest.json` never drift apart.

## Sanitization checklist (run before committing ANY fixture)

- [ ] No real operator, vendor or employer names (or thinly-veiled variants of them).
- [ ] No real tariff/campaign/product names from any actual telco.
- [ ] Phone numbers only from the reserved fake range `+90 555 000 xx xx`; TCKN-like
      numbers never realistic (use `11111111110`-style).
- [ ] No sentence copied or paraphrased from any real BRD, wiki page or contract.
- [ ] People are fictional; no real names/emails/titles.
- [ ] PR description states: "Fixture sanitization checklist: PASS".
