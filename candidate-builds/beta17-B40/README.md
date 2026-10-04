B40 is B39 plus the no-qualifying-rows research outcome. Seen live on Banker, batch
`banker-desk33-1518-short-year-20260930-g6-r1b` (EX33): 5 of 14 members ended `native_error` with
`SXmlData::WriteUniqueRowsToXml: No Rows!` after 7 of 158 passes were profitable in-sample and the best
combined score was 48.1, below the export score of 60. That is "tested, nothing qualified in this
window", not an error. Compiled once from `daa60928` (the #142 merge); see **Build**.

**What changes from B39**

| Where | What it does |
|---|---|
| `XmlProcessor.mqh` | The forward reader counts kept passes found in the forward report (`forwardMatched`), back-result or input disagreements and repeated passes (`forwardMismatches`), and forward rows whose pass, profit, PF, RF, SR or trades cell does not parse strictly (`forwardMalformed`; the back reader counts unreadable PF, RF and SR cells of profitable passes the same way, and `IsNumberCell` now requires the text to be a decimal number, not just the Number type). Its two inner loops can no longer spin at end of file. `GoatXmlNoQualifierOutcome` returns `no_qualifying_rows` only with the same whole-report proof as `no_profitable_passes`, at least one kept pass, a whole forward report whose rows number 1 to passes, every kept pass matched exactly once with no disagreement or unreadable row, and a best combined score below `GOAT_XML_MIN_COMBINED_SCORE` (60, now one constant shared with `WriteTopToXml`). Such a pair skips the combined writers (no 0-row `CombinedRows` file, no `No Rows!`). Pairs that mix both outcomes keep the old error result. |
| `GOAT V1.49.mq5` | `OnTesterDeinit` writes a `NoQualifyingRows` item_stats row (kept rows, best combined score, details with `back_rows`, `forward_matched`, `forward_discarded`, `best_combined_score`, `score_threshold` and the window), logs the plain sentence and shows "Nothing qualified in this window". The queue status stays `Error` (no wire change). Build ID `V1.49-BETA17-40`, marker `B40`. |
| `Optimizer.mqh` | The end-of-batch summary counts `NoQualifyingRows` items under "No edge", apart from errors, under the same queue-status and de-duplication rules. |

Report processing only: no trading, risk, sizing, order, trade-event, AI-wire, model-route or input-header
change. The input header is still SM32's (`1408e1ee…`), so SM32 batch packages stay valid.

**Build**

- `GOAT_BUILD_ID` is `V1.49-BETA17-40`, marker `B40`.
- Compiled once from `daa60928` with MetaEditor 5.0.0.6230 (sha256 `cf2750bd…`, the same compiler as B39):
  0 errors, 0 warnings. The stage was a scratch copy outside every terminal folder; its standard includes and
  the `MACD - GOAT 2.ex5` resource are hash-equal to the B39 compile's (and so to Terminal 2's).
- `GOAT V1.49.ex5`: sha256 `55d3e393ec80e73612b4305732d4066a925f429c98f80afbe46b41f67088b99b`, 2,427,662 bytes.
- Entrypoint `GOAT V1.49.mq5`: sha256 `36142571…15b597`, pinned in `controller/contracts/v149/dependencies.json`.
- Pin check at `daa60928`: all 41 sources in `identity.json` match the tree and the staged copy; only
  `GOAT V1.49.mq5`, `XmlProcessor.mqh` and `Optimizer.mqh` differ from B39. The input header is still `1408e1ee…`.
  The sanitized `compile-receipt.json` is in this folder.
- MetaEditor output is not byte-reproducible across stages: the pre-merge review compiles (`ffd581e3…`,
  `91350843…`) are superseded and must not be admitted. V1.48 and V1.47, which share `Optimizer.mqh` and
  `XmlProcessor.mqh`, compiled with 0 errors, 0 warnings in those reviews.

**Not done.** Native qualification has not been performed, and nothing was installed. The root
`GOAT V1.49.ex5` is unchanged.

**Still owed:** Claude-Mac's server admission of `V1.49-BETA17-40` for Banker, the registry publish, and native
proof on a member that ends with kept passes and no qualifying row.
