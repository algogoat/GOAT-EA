B41 is B40 plus the recorded-bias live gate agreed on goatai#1885 with Claude-Mac: in the Strategy
Tester and optimization, AI bias from `GOAT_AI_Bias_<SYM>.csv` reaches the bias logic exactly as live
V1.49 would hand it over, at every `Bias_threshold`. Compiled once from `278ec109` (the #147 merge); see
**Build**.

**Why.** Live V1.49 hands the bias block a score only when the wire state is actionable
(`GOATFinalizeWireV2Actionability`: a direction, and a probability at or above `Bias_threshold`).
Otherwise it hands over -999. The recorded reader handed over every score, so sign-only modes
(`Bias_Close_low`, and `Close_med`/`Close_high` at threshold 0) acted below the threshold in the tester
where live would not, and a neutral 0 counted as a valid bias. Baking a threshold into the export would
fix one N and make the threshold impossible to optimise, so the reader applies the gate with the run's
own input instead.

**What changes from B40**

| Where | What it does |
|---|---|
| `GOATAIWireV2.mqh` | `GOATRecordedBiasLiveScore(score)` rebuilds the wire state a recorded score stands for (+ BULLISH, - BEARISH, 0 NEUTRAL, probability \|score\|/100) and runs the live `GOATFinalizeWireV2Actionability` with the same clamped cutoff `GetState` uses. It returns the score when actionable, otherwise -999. A value outside [-100,100] (the export's -999) stays -999. |
| `NewsBiasFilter.mqh` | `GetCurentBiasScore`: in the tester, optimization and forward only, the selected point goes through that gate after the existing future check. It holds until the export's own -999 row at the wire's `validUntil` (65 minutes), as live holds a record until it expires: the ~2×-row-spacing staleness heuristic, and its per-call average over the whole file, no longer apply to the gated tester path. The live legacy reader is unchanged, staleness rule included. |
| `GOAT V1.49.mq5` | Enables the gate (`GOAT_RECORDED_BIAS_LIVE_GATE_V149`). When the tester's recorded point is unavailable, additions pause under `Bias_SeqTrade`, as live v2 already does for an unavailable wire. Without this, the gate would make `Bias_Opens` + `Bias_SeqTrade` diverge more, not less. Build ID `V1.49-BETA17-41`, marker `B41`. |

Tester and optimization consumption only. No live path, input, input header (`1408e1ee…`, SM32's),
Astra input, trade-event policy, bias wire or model route changes. V1.47 and V1.48 do not define the
flag, so they compile exactly as before.

**Release notes**

- Strategy Tester and optimization now read recorded AI bias exactly as the live EA acts on it, at the
  run's own `Bias_threshold`: below-threshold and neutral points count as unavailable, and a point lasts
  until the export's expiry row.
- **Re-run any sign-only bias-mode optimisation done on recorded data** (`Bias_Close_low`, and
  `Close_med`/`Close_high` at threshold 0, or any mode with `Bias_SeqTrade`): those results did not match
  live. This includes runs on older legacy-sentiment CSVs, which are gated too.
- Recorded files need the export's explicit -999 expiry rows (goatai#2224). A file without them holds
  each point until the next row.

**Build**

- `GOAT_BUILD_ID` is `V1.49-BETA17-41`, marker `B41`, on top of B40 (GOAT-EA#142, compiled in #149).
- Compiled once from `278ec109` with MetaEditor 5.0.0.6230 (sha256 `cf2750bd…`, the same compiler as B39 and
  B40): 0 errors, 0 warnings. The stage was a scratch copy outside every terminal folder; its 307 standard
  includes and the `MACD - GOAT 2.ex5` resource are hash-equal to the B40 compile's (and so to B39's and
  Terminal 2's).
- `GOAT V1.49.ex5`: sha256 `d5cbcbfd182f7ff18afce79c4245c2ac8ff1044ca3b7ec6e7cbfa663deee8913`, 2,428,472 bytes.
- Entrypoint `GOAT V1.49.mq5`: sha256 `16af9bb9…2269f4c9a`, pinned in `controller/contracts/v149/dependencies.json`.
- Pin check at `278ec109`: all 41 sources in `identity.json` match the tree and the staged copy; only
  `GOAT V1.49.mq5`, `GOATAIWireV2.mqh` and `NewsBiasFilter.mqh` differ from B40. The input header is still
  `1408e1ee…`. The sanitized `compile-receipt.json` is in this folder.
- MetaEditor output is not byte-reproducible across stages: the pre-merge review compiles on
  `claude-pc/bias-reader-parity` are superseded and must not be admitted. V1.48 and V1.47, which share the
  changed headers but do not define the flag, compiled with 0 errors, 0 warnings in those reviews.

**Not done.** Native qualification has not been performed, and nothing was installed. The root
`GOAT V1.49.ex5` is unchanged.

**Still owed:** Claude-Mac's server admission of `V1.49-BETA17-41`, the registry publish, and a native tester
run on a recorded file that shows below-threshold rows reaching the bias block as unavailable. Claude-Mac
approved the design (goatai#1885, 5980940867).

**Export truncation (goatai#2230, merged).** The CSV now holds floor(100p), so the tester acts exactly
when live does at every `Bias_threshold` from 1 up, for every probability the wire carries as a decimal;
the parity test expects zero disagreements there. Two edges remain, both pinned exactly in the test:
at `Bias_threshold` <= 0, a directional probability below 1% truncates to 0 (the CSV's neutral); and
#2230's 1e-9 epsilon lifts a double a float hair below a whole percent (0.7*0.1 = 0.06999999999999999)
to that percent, which live does not act on. Stepping the truncation back when percent/100 > p closes
the second.
