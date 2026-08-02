# ADR-0002: Core runs adjacent to Atlassian; thin Forge/Rovo surface on top

- **Status:** accepted
- **Date:** 2026-08-03
- **Deciders:** maintainer

## Context

The primary knowledge sources live in Atlassian Cloud (Confluence, Jira). Research
(RESEARCH.md §5.1, §2.2) established: Confluence has no bulk/space-export API (page-by-page
v2 crawl, points-based rate limits from 2026-03); Atlassian's MCP surface is limited to
~1,000 req/h interactive use; Forge FaaS cannot host a heavy multi-agent pipeline, and
shipping data out forfeits "Runs on Atlassian" anyway; Atlassian's own Code Intelligence
(EAP) will likely commoditize code+wiki Q&A — the platform is both a distribution channel
and an erosion clock.

## Decision

Eforge's core (ingest, knowledge layer, pipeline, calibration, review UI) runs on its own
infrastructure. Atlassian integration is split by purpose: **bulk sync via first-party REST
connectors** (checkpointed, incremental, ACL- and version-aware); **interactive enrichment
via Atlassian/Teamwork-Graph MCP** (no hard dependency while in beta); **distribution via a
thin Forge Rovo Agent** front-door calling our API; and Eforge ships **its own MCP server**
so estimates are queryable from Rovo/Copilot/Claude.

## Consequences

- Full control over indexing, retrieval quality, and multi-source grounding; deployable
  to VPC/BYOC/air-gap where Forge cannot go.
- We own connector maintenance and pay the initial-sync latency (days for large wikis —
  budgeted in onboarding).
- The moat must live in workflow + ledger + calibration, not retrieval (which the
  platform will commoditize).
- Revisit triggers: Atlassian ships bulk-export APIs or GA's Teamwork Graph access with
  terms that materially change connector economics.
