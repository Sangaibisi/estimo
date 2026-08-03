# Contributing to Estimo

Thanks for your interest! Estimo is in its **foundation phase** — the research and plan are
done, the code is arriving sprint by sprint. Early contributions are most valuable on the
items marked in [docs/ROADMAP.md](docs/ROADMAP.md).

## Ground rules

Everything in [AGENTS.md](AGENTS.md) applies to human contributors too — it is the
canonical workflow document (branch topology, commit convention, Definition of Done,
language policy, data rules). The short version:

- **Trunk-based:** branch from `main` (`feat/<scope>-<slug>`), squash-merge back, keep PRs
  scoped to one roadmap item.
- **Conventional Commits** in English.
- **No real customer data anywhere** — synthetic/sanitized fixtures only
  (see [SECURITY.md](SECURITY.md)). This is the one rule with zero tolerance.
- **Tests + evals:** code changes need tests; estimation-behavior changes need golden-set
  eval results in the PR description.
- **Docs discipline:** update `docs/ROADMAP.md` checkboxes and `CHANGELOG.md`
  (`[Unreleased]`) in the same PR; never add new planning documents.

## Discussing before building

Open an issue (English or Turkish both welcome) before large changes. Architectural
proposals should reference or add an ADR (`docs/adr/`). The product's non-negotiable
behaviors are in [docs/PRINCIPLES.md](docs/PRINCIPLES.md) — proposals that conflict with
them need to change the principle first (with evidence), not sneak past it.

## Licensing of contributions

Estimo is [Apache-2.0](LICENSE). By submitting a contribution you agree it is provided
under Apache-2.0 (inbound = outbound), per Section 5 of the license. Do not contribute
code you don't have the right to submit — and never code copied from `ee/`/`enterprise/`
directories of open-core projects.

## Setup

Containers are the only supported runtime ([ADR-0006](docs/adr/0006-fully-containerized.md)),
so the fastest way to see the product is the quick start in the [README](README.md#quick-start):

```bash
cp .env.example .env
docker compose --profile mock up --build
```

To work on the Python side you need [uv](https://docs.astral.sh/uv/) (the version CI pins is
in `.github/workflows/ci.yml`):

```bash
uv sync --all-packages --all-groups
uv run ruff format . && uv run ruff check . && uv run mypy apps packages
uv run pytest                      # db-marked tests need ESTIMO_TEST_DATABASE_URL
```

> **`ESTIMO_TEST_DATABASE_URL` must point at a throwaway database.** The db-marked
> suite runs `alembic upgrade head` against it and TRUNCATES the tenant tables
> between tests. Pointing it at the compose stack's own database — the obvious
> shortcut, since that Postgres is already running — silently wipes whatever you
> were looking at in the UI. Create a second database on the same server instead:
>
> ```bash
> docker compose exec db createdb -U estimo estimo_test
> export ESTIMO_TEST_DATABASE_URL=postgresql+asyncpg://estimo:change-me@localhost:5433/estimo_test
> ```

The web app is a separate npm project under `apps/web` (it is excluded from the uv
workspace on purpose):

```bash
cd apps/web && npm ci && npm run build
```

Those three gates — ruff, mypy, pytest, plus the web build — are exactly what CI runs. Run
them before opening a PR; a PR that has not been run locally will simply fail slower.
