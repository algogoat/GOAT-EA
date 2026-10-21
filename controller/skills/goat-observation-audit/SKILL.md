---
name: goat-observation-audit
description: Audit current GOAT account, portfolio and run observations using authorized read-only data, with explicit freshness, scope and reconciliation of trades and settings.
---

Discover the installed read-only account/portfolio observation surfaces and use
only the accounts in the user's requested scope. A historical developer fleet or
copied account list is not customer scope. Map each observation to its exact
account, broker, terminal/data path and timestamp before comparing it.

Prefer current native/API observations. If refresh is unavailable, state the age
and limits of the newest retained evidence. Keep current open exposure separate
from realized results and reconstruct sequences from deals/orders and matching
settings when those data are available. Never infer missing history from totals.

Reconcile symbol, strategy, direction, volumes and sequence identity. Opposing
positions with zero net lots still carry exposure. Include forced end-of-test
liquidations in official historical results and describe any separate attribution.

Cross-check the matching installed input schema and documented behavior; control
names alone do not establish hard stops. Separate observed facts, inferences and
unresolved coverage. Do not import old-version semantics as current facts.

The EA dashboard can upload portfolio-tracking buckets directly when configured.
That does not prove every separate public-experiment projection or historical
collector is redundant. Check producer, destination, fields, freshness and consumers
before replacing a feed. Audit work itself changes neither trading nor publication.
