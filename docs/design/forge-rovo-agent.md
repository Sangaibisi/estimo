# Design note: Atlassian Forge Rovo Agent front-door (S10-4)

**Status:** design note — implementation deferred until a Marketplace distribution
exists (Forge apps are hosted on Atlassian's platform, not in Estimo's containers, so
this is packaged and released separately from the self-hosted product).

## Goal

Let a user inside Jira or Confluence say *"send this BRD to Estimo"* and get a status
card back, without leaving Atlassian — a thin front-door onto the self-hosted Estimo
API, not a second implementation.

## Shape (web-verified against the 2026 Forge model)

- A **`rovo:agent`** module declares the agent (name, prompt, conversation starters) and
  the **actions** it may invoke.
- A Forge **`action`** (function module) calls the external, customer-hosted Estimo API.
  Because Estimo is self-hosted, the manifest must declare **egress**:

  ```yaml
  permissions:
    external:
      fetch:
        backend:
          - "https://estimo.example.com"   # the customer's Estimo API origin
  ```

- Auth from Forge → Estimo reuses S10's OIDC resource-server model: the action attaches
  a bearer token (the customer wires an app credential / API token in the IdP) so the
  call lands as a proper authenticated, tenant-scoped request. No new auth surface.
- Actions map 1:1 onto existing endpoints — e.g. *upload BRD* → `POST /v1/estimates`,
  *status* → `GET /v1/estimates/{id}`, *evidence* → the MCP `get_estimate_lines` tool.
  The agent renders the returned status/coverage as a Rovo card.

## Why deferred, not built now

- Forge apps deploy to Atlassian, are reviewed for Marketplace, and version
  independently of the self-hosted images — mixing them into this repo's release train
  would couple two unrelated cadences (ADR-0005 reliability bar).
- The whole surface is a **client** of already-shipped, already-tested endpoints; there
  is no core logic to build here, only packaging + egress config, which belongs with the
  Marketplace-readiness work (S10-6 assessment).

## Prerequisite already in place

The MCP server (S10-5) gives any agent host — Rovo included — a typed, read-only,
tenant-isolated tool surface over the same endpoints, so the Forge action layer stays
thin.
