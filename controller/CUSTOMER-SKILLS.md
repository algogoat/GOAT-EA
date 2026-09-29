# GOAT skills for customer agents

These portable skills are included in the controller bundle. `discover` returns
their installed paths and hashes. Agents can read the matching `SKILL.md` directly;
hosts that support local skills can register these same folders without copying
private developer tooling. Start with one relevant skill, not the whole library.

| Task | Skill | Working surface |
| --- | --- | --- |
| Plan, time and monitor an optimization batch | [goat-optimize](skills/goat-optimize/SKILL.md) | Installed Studio controller |
| Create or audit an optimization template | [goat-template-create](skills/goat-template-create/SKILL.md) | Installed schema, validate-set/build-set and local matrix |
| Run a bounded seed research matrix | [goat-seed-research](skills/goat-seed-research/SKILL.md) | Dedicated seed-* commands, subject to installed native qualification |
| Build, compare and export portfolios | [goat-portfolio-build](skills/goat-portfolio-build/SKILL.md) | Authenticated desktop agent API |
| Diagnose, repair and submit findings | [goat-repair-report](skills/goat-repair-report/SKILL.md) | Installed recovery commands and support preview/submission |
| Audit current account/portfolio observations | [goat-observation-audit](skills/goat-observation-audit/SKILL.md) | Authorized read-only native/API observations |

Use capabilities from the actual installation. A skill describes a workflow; it
does not add a missing executable, grant or permission. Carry out routine recovery
already within the user's authorization without asking again. Report an unavailable
tool precisely and preserve its evidence so the product can improve.

Maintainer release/upload, compiler, version-cut and repository-diff skills remain
maintainer tools. Customer repair reports can include a proposed code patch; they
do not authorize a replacement EA binary or a production release.
