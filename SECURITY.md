# Security & Data-Handling Policy

## Reporting a vulnerability

Please report security issues privately via **GitHub → Security → Report a vulnerability**
(private vulnerability reporting is enabled for this repository). Do not open public issues
for security problems. You'll get an acknowledgement within a few days.

## The data rule (zero tolerance)

Estimo's subject matter — customer BRDs, internal wikis, codebases, estimate spreadsheets —
is exactly the kind of data that must **never** appear in an open-source repository.

Forbidden in code, fixtures, tests, docs, issues, PRs and commit history:

- Real BRDs or excerpts of them, even "anonymized" by find-and-replace.
- Customer, operator or employer names tied to requirements or estimates.
- Wiki/Confluence exports, Jira issue dumps, internal architecture diagrams.
- Real estimate or actuals data from any organization.
- Credentials, tokens, endpoints of private systems.

Allowed:

- **Synthetic fixtures**: invented Turkish BRDs about fictional companies
  (`fixtures/` — see naming conventions there once created).
- Public benchmark data with permissive licenses (e.g. TAWOS, Apache-2.0).
- Aggregate, source-anonymous numbers already published in the research dossier.

If real data ever lands in history: treat it as an incident — rewrite history
(`git filter-repo`), force-push with maintainer coordination, rotate anything secret,
and note the incident in the PR that fixes it.

## Deployment-security principles (for the product itself)

- Secrets via environment only; `.env` is gitignored, `.env.example` documents every key.
- All model traffic goes through the deployment's OpenAI-compatible gateway (LiteLLM);
  pin gateway/client versions (a 2026 supply-chain incident on a popular gateway package
  is documented in the research dossier §5.4 — version pinning is not optional).
- Retrieval must be permission-aware: source ACLs (e.g. Confluence restrictions) are
  carried in chunk metadata and enforced as a **pre-filter** at query time, never left to
  the prompt.
- Customer deployments range SaaS → VPC → BYOC → air-gapped; the pipeline is designed
  stateless-per-tenant with per-tenant index namespaces and keys.
