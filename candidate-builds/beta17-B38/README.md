B38 is the one consolidated beta.17 V1.49 candidate: EX33 plus FU35 (with Claude-Mac's two fold-ins), PS37
and LC36's activation-code file. It is compiled once, so it needs one server admission and one pairing approval
per terminal. FU35, PS37 and LC36 are not admitted on their own; their PRs stay open for code review only.

**What it contains**

| Part | Source | What it does |
|---|---|---|
| FU35 | GOAT-EA#122 @ `689808c2` (approved) | A controller cancel answers `CANCELLED_RECONCILE` only after a bounded idle confirmation. The `EvidenceEnd` export setting ends every export at that day + 1. |
| FU35 fold-in 1 | this branch | The Stop toggle (`0x31`, the same message as Start) is sent directly, and only when a fresh passive caption read still says "running". It never goes through `ClickStop`/`IsIdle`. The loop disarms only after a Stop was actually sent. |
| FU35 fold-in 2 | this branch | The Studio writer carries `EvidenceEnd` through save, rename, `.goatbatch` load and human Start. An absent setting is journaled (`GOAT_EVIDENCE_END_ABSENT`). At finish, each kept export's real end (its `.set` FOOS range end) is checked against the staged date (`GOAT_EVIDENCE_END_CHECK`). |
| PS37 | GOAT-EA#124 @ `7388c01f` (approved, merged) | Steady Studio panel: each control property is written once per refresh. |
| PS37 follow-up | this branch | The forward date picker is enabled exactly when the forward mode is Custom (Codex P2 on #124). |
| LC36 | GOAT-EA#125 source commit `49e7f359` (head `0d9ddd21`), EA part only | Shares the pending connection code (never the credential) in Common Files `GOAT\activation-code-<data folder>.json`, on demo accounts only, and withdraws it as soon as it is no longer shown. MH34 (#112) is **not** included; LC36 does not need it. |
| LC36 follow-up | this branch | The file is reconciled on every activation tick: a failed first write, or a record another chart withdrew, is shared again. A newer record from another chart is never overwritten (Codex P2s on #125). |

There are no trading, risk, sizing, order, wire or input-header changes. The input header is still SM32's
(`1408e1ee…`), so SM32 batch packages stay valid.

**Build**

- `GOAT_BUILD_ID` is `V1.49-BETA17-38`, marker `B38`.
- Compiled once from `e4e9ccfc` with MetaEditor 5.0.0.6230 (Terminal 2): 0 errors, 0 warnings.
- `GOAT V1.49.ex5`: sha256 `7f03c9bae1e6367f0cff731f5ad1fa95599ca6e54ea5d8fb592efb85067e07df`, 2,415,510 bytes.
- Entrypoint `GOAT V1.49.mq5`: sha256 `74fd0c32…bc2f8`, pinned in `controller/contracts/v149/dependencies.json`.
- The sanitized `compile-receipt.json` is in this folder. Every source hash is in `identity.json`.

**Not done.** Native qualification has not been performed, and nothing was installed. The new build ID needs
server admission before activation. EX33, SM32, SM31 and SP30 stay in `candidate-builds/` unchanged, and the root
`GOAT V1.49.ex5` is unchanged.

**Native proofs still owed** (from Claude-Mac's #122 review, plus the panel and code-file checks):
- cancel a running batch: expect `CANCELLED_RECONCILE` and the `GOAT_CANCEL_STOP_CONFIRM` journal line;
- cancel an idle tester: expect 3 polls and 0 clicks;
- cancel during an export run;
- run a staged EvidenceEnd across a member restart: deals, equity and `.goatseq` all end on the date, and
  `GOAT_EVIDENCE_END_CHECK` reads `matched=<all>`;
- set a refused EvidenceEnd: expect Error and no exports;
- the Studio panel no longer flashes; the forward date picker follows Custom;
- `studio pairing-code` reads the code while MT5 shows it, and finds nothing once it is approved or expires.
