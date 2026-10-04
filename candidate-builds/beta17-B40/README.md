B40 is B39 plus the no-qualifying-rows research outcome. Seen live on Banker, batch
`banker-desk33-1518-short-year-20260930-g6-r1b` (EX33): 5 of 14 members ended `native_error` with
`SXmlData::WriteUniqueRowsToXml: No Rows!` after 7 of 158 passes were profitable in-sample and the best
combined score was 48.1, below the export score of 60. That is "tested, nothing qualified in this
window", not an error. Compile pending; see **Build**.

**What changes from B39**

| Where | What it does |
|---|---|
| `XmlProcessor.mqh` | The forward reader counts kept passes found in the forward report (`forwardMatched`), back-result or input disagreements and repeated passes (`forwardMismatches`), and forward rows whose pass, profit or trades cell does not parse (`forwardMalformed`). Its two inner loops can no longer spin at end of file. `GoatXmlNoQualifierOutcome` returns `no_qualifying_rows` only with the same whole-report proof as `no_profitable_passes`, at least one kept pass, a whole forward report whose rows number 1 to passes, every kept pass matched exactly once with no disagreement or unreadable row, and a best combined score below `GOAT_XML_MIN_COMBINED_SCORE` (60, now one constant shared with `WriteTopToXml`). Such a pair skips the combined writers (no 0-row `CombinedRows` file, no `No Rows!`). Pairs that mix both outcomes keep the old error result. |
| `GOAT V1.49.mq5` | `OnTesterDeinit` writes a `NoQualifyingRows` item_stats row (kept rows, best combined score, details with `back_rows`, `forward_matched`, `forward_discarded`, `best_combined_score`, `score_threshold` and the window), logs the plain sentence and shows "Nothing qualified in this window". The queue status stays `Error` (no wire change). Build ID `V1.49-BETA17-40`, marker `B40`. |
| `Optimizer.mqh` | The end-of-batch summary counts `NoQualifyingRows` items under "No edge", apart from errors, under the same queue-status and de-duplication rules. |

Report processing only: no trading, risk, sizing, order, trade-event, AI-wire, model-route or input-header
change. The input header is still SM32's (`1408e1ee…`), so SM32 batch packages stay valid.

**Build**

- `GOAT_BUILD_ID` is `V1.49-BETA17-40`, marker `B40`. `identity.json` binds the 41 sources; only
  `GOAT V1.49.mq5`, `XmlProcessor.mqh` and `Optimizer.mqh` differ from B39.
- Review compile (not committed): MetaEditor 5.0.0.6230 (sha256 `cf2750bd…`, the B39 compiler) on a scratch
  stage outside every terminal folder, with B39's include root (hash-equal to Terminal 2's): V1.49 0 errors,
  0 warnings (`GOAT V1.49.ex5` 2,426,282 bytes, sha256 `ffd581e3…`); V1.48 and V1.47, which share
  `Optimizer.mqh`, 0 errors, 0 warnings each. MetaEditor output is not byte-reproducible across stages, so the
  candidate binary is owed by a separate compile commit with its sanitized receipt.

**Not done.** No candidate binary, no native qualification, nothing installed. The root `GOAT V1.49.ex5` is
unchanged.

**Still owed:** Claude-Mac review, the candidate compile commit, server admission of `V1.49-BETA17-40`, and
native proof on a member that ends with kept passes and no qualifying row.
