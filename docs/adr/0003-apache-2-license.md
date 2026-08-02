# ADR-0003: Apache-2.0 license

- **Status:** accepted
- **Date:** 2026-08-03
- **Deciders:** maintainer

## Context

Lodestar is developed in the open while also aiming to become a commercial product operated
by its creator (internal dogfood → productization, RESEARCH.md §10 K1). License options
considered: MIT (simple, no patent grant), Apache-2.0 (patent grant, contribution terms,
enterprise-friendly), AGPL (protects against cloud competitors but suppresses enterprise
adoption — telco buyers routinely ban AGPL), BUSL/ELv2 (source-available, not open source).
The dependency stack chosen in research is entirely MIT/Apache, so no copyleft obligation
is inherited.

## Decision

License the repository under **Apache-2.0**, with inbound=outbound contribution terms
(license §5, stated in CONTRIBUTING.md). No CLA for now.

## Consequences

- Maximum adoption surface for the target buyers (enterprise/telco vendors) and clean
  compatibility with the whole dependency stack.
- A hyperscaler could offer Lodestar as a service; accepted risk at this stage — the moat is
  each customer's private ledger/calibration data, which does not ship with the code.
- Revisit triggers: significant external contribution volume (consider DCO/CLA), or a
  concrete managed-service competitor (consider open-core split for enterprise modules —
  while keeping the estimation core open).
