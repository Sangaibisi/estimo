# ADR-0001: All model access through an OpenAI-compatible gateway (LiteLLM)

- **Status:** accepted
- **Date:** 2026-08-03
- **Deciders:** maintainer

## Context

Target deployments (starting with the founding dogfood environment) expose LLMs only
through a corporate **LiteLLM** proxy — an OpenAI-compatible gateway in front of many
providers, carrying budgets, virtual keys, routing and audit. Enterprise/telco buyers
demand model flexibility (managed cloud or self-hosted open-weight models) and forbid
direct provider egress. Research findings (RESEARCH.md §5.4, §5.6): LiteLLM is MIT-core
and ubiquitous; provider-coupled agent SDKs conflict with this constraint; a 2026
supply-chain incident on the LiteLLM PyPI package makes version pinning mandatory.

## Decision

Every LLM, embedding and rerank call in Estimo goes through a single internal module
(`packages/gateway/`) that speaks only the OpenAI-compatible API to a configurable base
URL. Provider SDKs are banned repo-wide; model names live in configuration (routing
profiles per pipeline stage), never in code. Gateway 429/budget responses are first-class
handled states (retry/backoff/degrade).

**Clarification (2026-08-03, S1 implementation):** the `openai` PyPI package is permitted
*inside `packages/gateway/` only*, strictly as the de-facto OpenAI-compatible **protocol
client** with an explicit `base_url` — the standard way to talk to LiteLLM/vLLM-class
endpoints, avoiding a hand-rolled reimplementation of retries, SSE streaming and typed
responses. It is still a banned import everywhere else (enforced by
`tests/test_repo_guards.py` and CI). Retry layering is fixed at two layers: the client's
built-in Retry-After-aware `max_retries` at the transport, and step-level retries in the
pipeline — never both around one call site.

## Consequences

- Runs unchanged against LiteLLM, or any OpenAI-compatible endpoint (vLLM, managed clouds
  behind proxies) — SaaS-to-air-gap portability for free.
- We forgo provider-specific features (native tool-calling variants, provider caching);
  the pipeline must rely on portable primitives (JSON/structured outputs, plain chat).
- CI enforces the ban (grep for provider SDK imports outside `packages/gateway/`).
- Revisit triggers: a portable feature we need becomes gateway-inaccessible, or MCP-style
  model-side tool execution becomes a hard requirement.
