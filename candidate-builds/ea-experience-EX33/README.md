EX33 is an inert forward V1.49 candidate. It is SM31 plus the EA experience track:

- **No profitable passes is a research outcome, not an error.** When a whole back report (table
  closed, every row parsed, a whole forward report with no more rows than passes) holds passes, at
  least one of them traded, and none is profitable with at least 50 trades, `XmlProcessor.mqh` classifies the member as
  `no_profitable_passes` (`GOAT_RESEARCH_OUTCOME_V149`) instead of failing the combine with
  `No Rows!`. `OnTesterDeinit` writes one `NoProfitablePasses` row to the run's `item_stats.tsv`
  with the pass count, profitable count, best profit, best score and the back-test window. The
  native queue status stays `Error`, so the controller wire is unchanged; the controller tells
  these members apart (`research-status`, `finish`, `batch-pause`, `batch-resume --include-failed`).
  A report whose EA never traded, that cannot be read or that is partial stays a real error, and
  `--include-failed` retries it; `--include-no-edge` deliberately re-runs no-edge members.
  The back-row log now reports kept/total passes instead of `Rows Saved=0/0`. Whether MT5 writes a
  partial report after a manual tester Stop still needs native verification.
- **Connection code.** The activation card says "Connection code: XXXX-XXXX" and its link carries
  the code in the `#ea-connect=` URL fragment (never a query string). The server contract is unchanged.
- Studio, Dashboard and prompt copy, state and layout fixes from the 2026-10-02 UX audit
  (plain language, 60-character status lines, honest states, safe default buttons).

No trading, risk, sizing, order or controller wire behaviour changes. The pinned input header
(`GOAT_Inputs_Definitions.mqh`) is unchanged, so saved batch packages stay valid.

Its `GOAT_BUILD_ID` is `V1.49-EA-EXPERIENCE-33`, with marker `EX33`. `identity.json` binds the
exact forward source. **The compile is pending:** there is no `GOAT V1.49.ex5` or
`compile-receipt.json` here yet. After Claude-Mac approves the exact head, compile it with
MetaEditor, add the binary and the sanitized receipt, set `identity.json` `binary` and `compile`,
and keep the candidate test in step. The new build ID needs server admission before activation.

`candidate-builds/terminal-isolation-SM32` (PR #113) is a parallel candidate from the same SM31
base; whichever merges second rebuilds its identity on the merged source.

SM31 stays retained unchanged in `candidate-builds/ndx-symbol-map-SM31`. The root
`GOAT V1.49.ex5` and all installed artifacts remain unchanged. Compilation does not qualify
native use: exact-head review, isolated native DEMO/owner/STOP/Algo-off qualification and a
separately reviewed customer delivery remain required.
