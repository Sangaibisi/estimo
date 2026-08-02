# ADR-0006: Fully containerized — containers are the only supported runtime

- **Status:** accepted
- **Date:** 2026-08-03
- **Deciders:** maintainer

## Context

Estimo must be easy to distribute across a wide deployment ladder (SaaS → single-tenant
VPC → BYOC → air-gapped on-prem, ADR-0002/ARCHITECTURE) to enterprise/telco buyers, and
easy for open-source users to try. Supporting bare-metal installs (system Python, host
Postgres, hand-managed services) multiplies the support matrix and breaks the
stateless-per-tenant design. The stack (FastAPI api, web app, Postgres+pgvector, workers,
optional Langfuse) is container-friendly end to end; the only external dependency by
design is the customer's LiteLLM gateway (ADR-0001), reached over the network.

## Decision

- **Every runnable component ships as an OCI image.** No documented bare-metal install
  path exists; `docker compose up` is the canonical way to run Estimo — for development
  AND for single-node deployments. Kubernetes (Helm, S10-3) consumes the *same* images.
- **Images are published to GHCR** (`ghcr.io/sangaibisi/estimo-<component>`), built in CI,
  **multi-arch (linux/amd64 + linux/arm64)**, tagged with the git SHA on every main build
  and with the semver tag on releases. Air-gapped installs load the same images from a
  tarball.
- **Build discipline:** multi-stage Dockerfiles (slim runtime, non-root user, pinned base
  images), `.dockerignore` mirrors repo hygiene (no fixtures/secrets baked in),
  healthchecks defined in the images, configuration exclusively via environment
  (`.env` / injected secrets — never baked).
- **Compose profiles** separate concerns: core (api, web, postgres), `--profile evals`
  (Langfuse etc.), so a minimal install stays minimal.

## Consequences

- One-command run for contributors and evaluators; distribution = pulling images, which
  directly serves the BYOC/air-gap sales motion.
- CI grows an image-build/publish stage (S1-8) and Dockerfiles become first-class
  reviewed artifacts; base-image updates are scheduled maintenance.
- Local non-container workflows (running uvicorn directly) remain possible for
  development speed but are unsupported as deployments and never documented as such.
- Revisit triggers: a component that cannot reasonably containerize (none foreseen), or a
  customer-mandated alternative registry/signing requirement (then add cosign/signed
  images rather than abandoning the model).
