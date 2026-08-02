# Changelog

All notable changes to Estimo are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/) once code ships.
Until the first code release, entries track documentation and foundation milestones.

## [Unreleased]

### Added
- ADR-0005: OSS-first composition — adopt proven, license-safe components behind internal
  interfaces; from-scratch code reserved for the differentiation core. Linked from
  AGENTS.md golden rules and ARCHITECTURE.md.

### Changed
- Project renamed from **Eforge** to **Estimo** (briefly Lodestar) — from the Latin
  *aestimo*, "I estimate, I appraise".
- **English is now the repository's single language**: the research dossier, roadmap and
  UI vision were translated; Turkish remains as *data only* (synthetic BRD fixtures,
  retrieval benchmarks, `tr` localization templates). ADR-0004 revised to
  "English-first product, Turkish-first input"; AGENTS.md language policy updated.
- ADR-0005 gained an explicit **credibility bar**: only de-facto-standard,
  major-org-backed, or overwhelmingly adopted OSS projects qualify as dependencies.
- README is now English-only (Turkish summary section removed).

## [0.1.0] - 2026-08-03

### Added
- Founding research dossier ([docs/RESEARCH.md](docs/RESEARCH.md)): market gap analysis,
  evidence review on LLM-based effort estimation, reference architecture, telco domain
  layer, and open-source stack survey — synthesized from a 5-track parallel research run.
- Repository foundation: README, Apache-2.0 license, agent guide ([AGENTS.md](AGENTS.md)),
  contributor guide, security & data-handling policy, code of conduct.
- Product principles ([docs/PRINCIPLES.md](docs/PRINCIPLES.md)) — evidence-derived rules
  every feature must respect (ranges over points, evidence links, anchoring protection).
- Architecture reference ([docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)) and initial ADRs
  (LiteLLM-only gateway, Atlassian-adjacent core, Apache-2.0, Turkish-first pipeline).
- Trackable sprint roadmap ([docs/ROADMAP.md](docs/ROADMAP.md)).
- UI vision brief ([docs/UI-VISION.md](docs/UI-VISION.md)) — input for the design-system pass.
