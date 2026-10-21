# MT5 tester settings round-trip fixture

`wanted.ini` is the first member of the owner's frozen V1.49 Banker research
plan. `observed.ini` comes from the retained MT5 clipboard settings captured
after the native `SETTINGS_NOT_VERIFIED` refusal on September 28, 2026, build
6230. This is a captured regression case, not an independent fresh native Copy
qualification. Generated run and strategy identifiers were replaced with
`FixtureRun` and `FixtureStrategy`; line endings are CRLF. No account identity
or credentials are included.

MT5 changes numeric formatting, emits non-optimizable inputs as scalars,
normalizes inactive range geometry and emits datetimes as epoch seconds. The
comparator checks every intended effective value and every active optimization
range against an explicit V1.49 type allowlist. It rejects missing research
inputs, unknown additions, changed optimization flags and malformed values.
Decimal comparison is exact, without a floating-point tolerance.

The clipboard omits startup-only fields and worker selection. The comparator
allows only the named startup exceptions with their expected policy values;
native worker policy and hashed run controls remain separate dispatch checks.
Omission of Visual is accepted only for optimization. A single test must retain
explicit Visual readback; a complete matching single-test configuration remains
supported. Visual mode is unavailable during optimization, as described in the
[MetaTrader visualization guide](https://www.metatrader5.com/en/terminal/help/algotrading/visualization).
See also the [startup configuration reference](https://www.metatrader5.com/en/terminal/help/start_advanced/start).

`node scripts/test_studio_setting_compare.cjs` executes the production comparison
control flow using JavaScript shims for MQL string, array and UTC intrinsics.
These fixture checks and MetaEditor compilation do not establish native MT5
qualification or authorize a batch start.
