---
name: goat-template-create
description: Create and audit GOAT optimization SET variants from installed templates while preserving encoding, active-input semantics, unique identity and provenance.
---

Read [template construction](../../TEMPLATE-WORKFLOW.md) and obtain the current
input schema/dependency policy with `discover`. Use `validate-set` and `build-set`
from the installed controller; examples from another EA version are not its schema.

Clone a real compatible source SET into a new local candidate. Preserve UTF-16 LE
BOM, CRLF, section order, comments and untouched inputs. Use a unique readable
EA_Desc and retain parent/output hashes, exact changes and supporting notes.
Publisher catalog files and previously tested/queued inputs remain immutable.

Review every optimized axis against its controlling mode and actual role. Resolve
each declared enum independently, including fixed values and all ladder endpoints.
Check initialization constraints, conditional branches, derived values and lot-mode
interactions. The dependency validator is partial: list unchecked axes rather than
claiming complete semantic proof.

Descriptions must match every enabled filter and exit in the actual output, including
unchanged fields whose meaning changed. Names alone do not establish execution
diversity. Separate fixed exports from optimization templates with active axes.

Use `build-set` with a per-change rationale. Inspect its SET, support notes and final
provenance receipt, then register an untested local fork through the advertised
desktop matrix API. Test on the declared development data before recording results;
changed inputs do not inherit the parent's performance claims.
