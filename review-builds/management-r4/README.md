# Review artifacts — DO NOT INSTALL

These are separately compiled management-only candidates for R5, R6 and R2.
They are **not approved or deployed**. The running demo experiment is unchanged.

`manifest.json` binds original revisions, generated entrypoint hashes, shared
header hashes, clean compile results, production candidate binaries and separate
tester-harness evidence. The `.ex5` files here are production candidates, **not**
the instrumented test binaries. The repository root V1.48 binary matches R2.
`entrypoint.patch` files are reviewer diffs; use the deterministic generator,
not the patch alone, to include the required shared headers.

Reconstruct source using `python scripts/build_management_variants.py --output
<new-directory>`, then compile each entrypoint with the documented isolated MT5
compile workflow. It preserves original credential namespaces and AI sources.
Never compile directly over an installed terminal binary.

Each native assertion extract is from a separate Strategy Tester run with native
order/exit execution, injected auth transport and simulated in-process reinit.
It is not evidence of cold terminal restart, broker fills, or every exit subtype.
Full journals and compile provenance are retained in the operator artifact pack.

See [qualification and rollout](../../docs/operations/MANAGEMENT-ONLY-R4-QUALIFICATION.md)
via the repository's `docs/operations` directory. Native demo cold-restart tests,
healthy live-auth qualification and independent review remain release gates.
Take the week's experiment export first; Vince coordinates any later flat-account
reload and Claude reviews the release. This PR grants no installation authority.
