# CLAUDE.md

**Start with [AGENTS.md](AGENTS.md) — it is the canonical guide for this repo.** Everything
there (golden rules, branch topology, Definition of Done, language policy) applies to you.

Claude-specific notes:

- The maintainer converses in **Turkish** — reply in Turkish in conversation. Everything
  in the repo — code, commits, PRs, and all documentation — is English per AGENTS.md §2.8.
- Prefer **editing canonical docs** over creating new ones. This repo treats stale or
  duplicate documentation as a bug; do not generate summary/plan/notes files.
- Before claiming an estimation-behavior change works, **run the eval harness** (once it
  exists — see `evals/`) and put the before/after numbers in the PR description.
- When you finish a roadmap item, tick it in [docs/ROADMAP.md](docs/ROADMAP.md) in the
  same PR and add a `CHANGELOG.md` entry if user-visible.
- Never introduce provider SDKs or hardcoded model names — all model I/O goes through
  `packages/gateway/` (OpenAI-compatible, LiteLLM at deployments).
- Fixtures must be synthetic Turkish BRDs; never paste real-world requirement text from
  any employer or customer context.
