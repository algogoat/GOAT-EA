# GOAT V1.47 performance A/B receipt

Date: 2026-08-24

Result: PASS. A control carrying V1.46 trading behavior under the same V1.47
filename and build identity was compared sequentially with the V1.47 candidate.
Both used the audited NZDUSD RangeFade set, M1, 2026-01-26 through 2026-08-21,
USD 100,000, leverage 1:500, execution mode 0, non-visual, local agent only.

| Evidence | OHLC (Model 1) | ETWRT (Model 4) |
|---|---|---|
| Complete MT5 HTML report | byte-identical `545a557de52ca6842f39aa731454a9a0e05566857ac765927cb7a70779bf7f4d` | byte-identical `008d08710afc700a59b683fe2f5ef063e3e3e61d5d4deea7a80cd27c1de1af20` |
| GOAT CSV | byte-identical `fabf2635e6f9a06fdc34f45e62e7003e42f2854ef498717bad78d9ea3999255d` | byte-identical `8c176442878f632dd44459429ea740fa9dce525274b163aae081f6435f3aa38c` |
| GOAT SET | byte-identical `63d2dff36e719d8c5f503252688b6f09185e1b7e145259a4570c0c478d66b45e` | byte-identical `126cdec86984f9dd2558eebc365510d99124bbfeaaf8402a8d8d4283b52cff3c` |
| Ticks / bars | 843,129 / 213,243 | 22,027,127 / 213,243 |
| MLPS exits | 28, exact normalized list | 32, exact normalized list |

The candidate kept every trade, order, deal, statistic, counter, MLPS exit,
and export byte-identical. It removed 6,000 OHLC and 58,304 ETWRT per-skip TSL
lines. Master/agent logs fell 42.58%/45.21% in OHLC and 86.67%/87.82% in
ETWRT. Actual TSL modification failures remain logged.

The profiler emitted exactly one end-of-test summary. ETWRT measured exact MLPS
enforcement at 5,297,792 microseconds across 23,993,766 calls. V1.47 deliberately
does not extend the optimization-only MLPS estimate to ordinary tester/export
runs because its current stale-leg approximation has no proven safe boundary.

Candidate source SHA-256:
`2263ea19b5d2cd0f984588e7ae7c3e85d49f82ab5150817f9ebcedf8a6050ad8`.

Terminal 2 MetaEditor build 6140 compiled with 0 errors and 0 warnings.
