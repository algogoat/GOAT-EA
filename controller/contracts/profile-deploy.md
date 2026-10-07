# Profile-staged deploy: controller ↔ EA contract (beta.25)

Status: **v1, beta.25**.

- goatai#1885 6033450916: Claude-Mac approved the design in `PROPOSAL.md` with rulings D1-D6.
- 6034765935 and 6034810079: Mac's review of the EA half (GOAT-EA#192) added the follow-ups that this
  version includes: the deployment nonce, the typed refusals, and the fail-safe for a chart that disappears. The controller half lives on `claude-pc/profile-staged-controller`.
The EA half (`claude-pc/profile-staged-ea`) builds against this file, and the beta.26 MQL profile
writer must reproduce the golden fixtures in `profile-fixtures/` byte for byte.

This file fixes every interface detail the proposal left open. Where it differs from the proposal,
the difference is marked **Decided here**, with the reason.

## 1. What the controller writes before the launch

All of these are written create-only, then re-checked byte for byte immediately before the launch.

| File | Content |
|---|---|
| `Common\Files\GOAT\Deployments\<deploymentId>\<SET name>` | The frozen SET bytes (unchanged from beta.24). |
| `Common\Files\GOAT\dashboard_state_<data folder>.tsv` | **Unchanged from beta.24.** The `#GOAT_AI_LAUNCH_V147_2` header, then one row per member in plan order. Each row has 9 columns and ends `0 0`, so every row starts with `cid=0 magic=0`. |
| `MQL5\Profiles\Charts\GOAT-Deploy-<deploymentId[:16]>\chart01.chr` | The dashboard (section 2). |
| `...\chart02.chr` … `chart(N+1).chr` | One child per member, in plan order, so member `i` (0-based) is `chart%02d.chr` of `i + 2`. |
| `Common\Files\GOAT\Deployments\namespaces\<data folder>.json` | The namespace claim (unchanged). |

- The profile folder holds **exactly** these chart files, with no `order.wnd` and no objects. If anything else
  is in the folder, the launch is refused.
- `MQL5\Presets\GOAT Dashboard Agent.set` is **no longer staged**. Its six values are chart01's inputs.

**Decided here: no `id=` and no pre-filled `cid`.** No chart file carries `id=`; MT5 assigns the id at load,
as it did for the monitor profile. The TSV `cid` therefore starts at 0. The dashboard writes the real `cid`
and `magic` when it adopts a child, and from then on `cid` equals the chart file's `id=` in the profile MT5
saves (this is what the Balanced35 profile shows: `g3-b35-dashboard-rows.tsv` row 1
`cid=55933097152258` matches `g3-b35-chart02-mt5-saved.chr` `id=55933097152258`). Pre-writing `id=` would rest
on unproven MT5 behaviour (proposal section 6, Q3/P5). The controller does verify this saved invariant
(`studio_deploy_profile.saved_profile_links`), and the version-change flow will build on it.

### Startup configuration (`/config:`), exact bytes

```
[Charts]
ProfileLast=GOAT-Deploy-<id16>
[Experts]
Enabled=0
Account=1
```

These are UTF-16LE bytes with a BOM and CRLF line ends.

- **There is no `[StartUp]` section.** The dashboard comes from chart01.
- `Enabled=0` is always written (D1). No code path writes `Enabled=1`, and a test scans the controller for it.
- `AllowLiveTrading` is never written (D2).

## 2. Chart file format

The file is UTF-16LE with a BOM `FF FE`, and every line, including the last, ends in CRLF.

```
<chart>
symbol=<member symbol>
period_type=<unit>
period_size=<count>
scale=8
mode=1
grid=0
scroll=1
one_click=0
windows_total=1
<expert>
name=<EA file stem, e.g. GOAT V1.49>
path=Experts\<ea_relative_path, e.g. GOAT-EA\GOAT V1.49.ex5>
expertmode=5
<inputs>
<input lines, section 2.2>
</inputs>
</expert>
<window>
height=100.000000
objects=0
<indicator>
name=Main
path=
apply=1
show_data=1
</indicator>
</window>
</chart>
```

The `<expert>` … `</expert>` lines are exactly what `BuildTemplate` produced. Golden G1 proves this byte for byte
against the real BuildTemplate output for the B35-01 Kestrel SET.

### 2.1 Period. **Decided here**

The period is the **whole token** after the first comma of the SET name, up to the first character that is not
`A-Z` or `0-9`. For example, `GOAT V1.49 EURUSD,M15_x.set` gives `M15`. Both sides read it the same way: the
controller's writer and the EA's adoption (`GoatAdoptSetPeriod`, B43).

beta.24's `TF()` read only two characters (`Dashboard.mqh@78f3b30:347-349`), so it opened M15 SETs on M1 charts.
That reader is deleted together with the template path. The accepted tokens are:

| Token | `period_type` | `period_size` | Evidence (MT5's own saves) |
|---|---|---|---|
| M1 | 0 | 1 | B35 `chart02.chr` |
| M5 | 0 | 5 | `ENUM_TIMEFRAMES` minutes |
| H1 | 1 | 1 | T3 monitor-profile backup charts |
| H4 | 1 | 4 | terminal-isolation `British Pound\chart03.chr` |
| D1 | 1 | **24** | terminal-isolation `British Pound\chart01.chr`. A day is 24 hours (`PERIOD_D1 = 0x4018`). **The proposal's "2 for D1" is wrong**: unit 2 is weeks. |

**M15 and M30 are refused in beta.25** (goatai#1885 6034765935).

- Both sides read them whole, never as M1. The encodings are known: M15 is (0,15), and M30 is (0,30), as in
  terminal-isolation `British Pound\chart04.chr`.
- Supporting them is on the B42 list.

Every token outside the table (M15, M30, W1, MN1, M10, a lowercase token, or no comma) is refused before anything
is written. The refusal is a typed refusal (`refusal_code` `SET_PERIOD_UNSUPPORTED`, with fields `fileName` and
`timeframe`) whose message reads:

> This portfolio has a timeframe the app can't deploy yet (M15): <SET name>. The app deploys M1, M5, H1, H4 and D1.

No chart period is ever implicit.

### 2.2 Input lines (the BuildTemplate rules, plus the refusals both writers share)

1. **Decode.** A SET starting with `FF FE` is UTF-16LE. Anything else is UTF-8 (a UTF-8 BOM is dropped).
2. **Split lines** on CRLF or LF. **Decided here:** a CR that does not end a line is refused (`SET_LINE_UNSUPPORTED`).
   MQL `FileReadString` and the Python reader could split it differently.
3. **Trim** each line of spaces, tabs, CR and LF on both ends (`StringTrimLeft` + `StringTrimRight`).
4. **Keep** the trimmed line when it has `=` after position 0 (`StringFind(ln,"=")>0`). The kept line is written as
   is (`var + "=" + val` is the trimmed line itself). Comment lines that contain `=` **are kept**, exactly as
   BuildTemplate keeps them; MT5 drops unknown names when it saves.
5. **Refuse** a kept line that still starts or ends with other Unicode whitespace, or that contains
   `<`, `>`, NUL or a control character other than tab. A SET with no kept line is refused (`SET_NO_INPUTS`).
6. **AI policy.** `GoatApplyAILaunchPolicy(inputs, aiMode, aiThreshold, aiProtocol)` applies verbatim.
   - With `aiMode` 2, every line whose name (the text before its first `=`, untrimmed) is `Mode_Bias`,
     `Bias_threshold`, `Bias_Protocol` or `Mode_Bias_Trades` gets the policy value in place.
   - Missing names are then appended in that order.
   - With `aiMode` 0 the lines are unchanged. The nonce (step 7) comes after this step.
7. **Deployment nonce** (goatai#1885 6034810079). The carrier was chosen by the EA half (B43 `b3e7ced`).
   Every staged child holds the line `Studio_MonitorRunPath=deploy=<deploymentId>`, where `<deploymentId>` is the
   32-hex deploy ID.
   - It is applied **after** the AI policy. A SET line naming `Studio_MonitorRunPath` with its `""` default is
     replaced in place; otherwise the line is appended as the last input. Nothing else changes.
   - A SET that sets `Studio_MonitorRunPath` to anything else, or names it twice, is refused
     (`SET_RUN_PATH_UNSUPPORTED`).
   - The input was chosen because it is WriteSet-omitted and read only behind `Studio_ReadOnlyMonitor`, which every
     child holds `false`, so trading is unchanged.
   - `EA_Desc` is never touched: it becomes each sequence's order comment, and the fill lookup matches positions by it.
   - The dashboard chart01 carries no nonce.
   - **EA side:** adoption requires that input to equal exactly `deploy=<registration deploymentId>`, and
     `settingsMatch` pins it (section 3). So a chart GOAT did not stage for this deployment can never be adopted,
     even with the same SET.

The dashboard chart01 uses the same frame on `M1` with the symbol of member 0. Its inputs, in this order, are
`Mode_Operation=8`, `Dashboard_Resume_Saved=true`, `Mode_Bias=1`, `Bias_Protocol=2`, `Bias_threshold=50` and `EA_Desc=GOAT Dashboard`.

### 2.3 Duplicate members

Two members with the same symbol, the same period and audit-equal effective inputs are refused before anything is
staged. Byte-identical SETs are the common case. The comparison runs before the nonce is added.

- Audit-equal means equal under `GoatChildAuditInputs` and `GoatChildAuditValue`: decimal canonicalisation,
  the `Download_StartDate` midnight rule, and exact text for the five named inputs.
- The refusal is typed: `refusal_code` `DUPLICATE_MEMBER_SETTINGS`, with field `members`, and this message:

> Two members have identical settings on the same symbol and timeframe; remove one (<a> and <b>).

So no started chart can match two rows.

The same check belongs in the house-portfolio publish CLI (`house_portfolio.cjs`), so a duplicate never reaches a
deploy.

## 3. Mailbox: `link_children`

This is the AgentPortfolio mailbox, unchanged: the same envelope, registration, `ROW_FIELDS` and receipt schema 1.

- **Request.** `action = "link_children"`, which the controller adds to its action list.
  - `deploy_next` is no longer sent.
  - A retained beta.24 `deploy_next` request or receipt is still recognised, so it can be settled and archived.
- **Results.** The controller adds (append-only) `children_linked`, `children_pending` and
  `rejected_deploy_next_retired`.
  - The B43 EA gives that last answer to a `deploy_next` and changes nothing.
  - The controller turns it into a typed refusal (`refusal_code` `DEPLOY_NEXT_RETIRED`), and so does any caller
    that still asks for `deploy_next`. The message reads: "This EA build deploys through the app's Next step; the old
    one-by-one deploy was retired. Use deploy-load (Next in the app) instead."
  - A stale caller therefore never sees an unknown-result error.

**EA behaviour.** **Decided here:** `link_children` is a mutation-class action, like `apply_policy`:

- When the terminal is not inert (not connected, Algo Trading on, or any position or order), the EA answers
  `rejected_not_inert`.
- When the dashboard's AI policy differs from the registration, it answers `rejected_ai_policy_mismatch`.
- When the registration does not match the dashboard rows, it answers `rejected_portfolio_mismatch`, as for
  every action today.
- Otherwise:
  1. It writes the `started` intent receipt first.
  2. It runs **one** adoption pass (section 4).
  3. It writes the final snapshot receipt with result `children_linked` when `GoatPortfolioRowLinked(i)` is true for
     every row, else `children_pending`.
- Rows keep today's exact fields. An unlinked row reads `chartId 0, magic 0, linkedFresh false`.
- The EA must never answer `children_linked` while any row is unlinked.

**Registration.** The registration gains one optional field, `deploymentId` (32 lowercase hex), which the
controller always writes.

- The B43 EA binds adoption and `settingsMatch` to it.
- An 11-field (beta.24) registration still validates on both sides, but the B43 EA then adopts nothing
  (`child_deploy_unbound`).
- Any other shape is refused.

**Controller behaviour.**

| Step | Value |
|---|---|
| Per-request wait | 20 s |
| Pause after `children_pending` | 2 s |
| Pause after `receipt_timeout` | 11 s, so the unanswered request (alive for wait + 5 s) is archivable |
| Start-up deadline | 240 s (`CHILD_START_WAIT_SECONDS`) |

- The controller accepts the link only when the result is `children_linked` **and** every row has
  `linkedFresh=true`, `chartId>0` and `magic>0`, with no `chartId` or `magic` used twice.
- Every `children_*` receipt must show `tradingAllowed=false`, `positions=0`, `orders=0` and `connected=true`.
  Otherwise linking stops at once.
- After the link, `apply_policy`, the ack poll, `audit` (`settingsMatch`) and the readiness checks are unchanged.
- **Approved for beta.25:** the 2 s `link_children` poll that the controller drives, with no adoption on the
  dashboard timer (goatai#1885 6034765935).
- **A linked row whose chart disappears fails safe** (6034810079).
  - `GoatPortfolioRowLinked` turns false, the row reads `linkedFresh=false`, and every later `link_children`
    answer is `children_pending` until `deploy-stop`.
  - During deploy-load that row ends `child_not_linked` (or `child_not_started` once its identity is cleared),
    and the deploy unwinds itself (section 5).
  - After ready, `deploy-status` shows `linkedFresh=false` and `trading=false` for it.
  - Nothing re-attaches a chart. The person runs `deploy-stop` and deploys again.
- The journal phase name `attached` is kept, so a beta.24 journal still resumes.

## 4. Adoption (EA side, for reference)

Adoption runs inside `link_children` (and may run on the dashboard timer) only when the terminal is inert and
while any row is unlinked. A row whose TSV `cid` is already set is tried on that chart first; a freshly staged
row (`cid=0`) is matched against every chart from `ChartFirst`/`ChartNext`:

1. Skip the dashboard's own chart and charts already claimed by a row.
2. Require `ChartSymbol`/`ChartPeriod` equal to the row's, and `CHART_EXPERT_NAME` equal to the EA name.
3. Require a magic from `GoatFindMagicByCid` that is greater than 0 and unused by other rows.
4. Require the chart's `Studio_MonitorRunPath` to be `deploy=<registration deploymentId>` (section 2.2, step 7).
5. Require `GoatChildAuditMaps(frozen SET, AI policy, ChartSaveTemplate snapshot, expert path, deploy tag)` to be
   true. That input is pinned to the nonce, and everything else is compared exactly.

A row is adopted only when **exactly one** chart matches. The EA then sets `cid`/`magic`, deletes the pending
`Magic` GV, sets status Linked and runs `SaveDashboardConfig`. Zero or several matches leave the row alone, with
`child_unmatched` / `child_identity_ambiguous` in the diagnostics. The EA never opens, closes or applies anything.

## 5. Per-row outcome at the deadline, and the auto-unwind (D3)

The last receipt with rows sets each unlinked row's reason:

- `child_not_started` when `chartId<=0` or `magic<=0`: no chart with our EA and this member's frozen settings was
  adopted. When no receipt with rows arrived at all, every row gets this reason.
- `child_not_linked` when the row was adopted but is not a fresh, unique link.

The journal records `rows_failed: [{index, fileName, symbol, reason}]` and `failure: {code, message}`.

deploy-load then runs the **unwind**, which is the inert-only deploy-stop path:

1. Broker proof: Algo off, no positions, no orders.
2. Normal close through the EA.
3. Rename the state TSV, the deploy profile, `request.json` and `registration.json` aside.
4. Select the previous profile again (section 6).

The raised error names the first 5 rows plus a count and says what GOAT did. The same unwind runs when the
dashboard never answers `status` after the launch, or when the registration is refused after the launch, because
the children are already loaded at that point. If the unwind is refused (for example, Algo Trading is on), the
error says so and asks for `deploy-stop`. A later `deploy-load` of the same plan starts a fresh attempt
(`attempt` n+1, its own close attempt ID and startup file), and the earlier journal is kept as `<id>.attempt-n.json`.

## 6. Rollback of the chart profile

- **At `closed`, after MT5 exits**, the controller records `previous_profile`: the `[Charts] ProfileLast` name
  from `config\common.ini` and a SHA-256 manifest of that profile folder. GOAT never writes that folder.
- **At stop or unwind, after MT5 exits**, the controller changes only the `ProfileLast` value in `common.ini` back
  to that name. It makes the change only when **all** of these hold:
  - the previous folder still matches its manifest byte for byte;
  - `common.ini` still names this deployment's profile;
  - `common.ini` decodes and re-encodes to its exact bytes.
- The before and after bytes are kept next to the journal (`<id>.common-before-<stamp>.ini` and
  `<id>.common-after-<stamp>.ini`), and the file is replaced atomically.
- Otherwise `common.ini` is left untouched, and `rollback.reason` says why.
- The stop result adds `rollback`, `previous_profile_intact` and `profile_restored`. All of them are additive.

## 7. Preflight and readiness (D2)

- `deploy-preflight` moves to schema 3. The change is additive: `allow_live_trading_default` is `true` only when
  `common.ini` `[Experts] AllowLiveTrading=1`, `false` otherwise, and `null` when the file is unreadable.
  `readiness_blockers` is `[{code: "allow_live_trading_off", message}]` when that value is false.
- The preflight never writes the option.
- If the audit then shows a child with `EA_TRADE_ALLOWED != 1`, readiness fails with that same plain-English
  instruction appended whenever `allow_live_trading_default` is not true.

## 8. Golden fixtures (`profile-fixtures/`, all `-text` in `.gitattributes`)

`manifest.json` pins the SHA-256 and source of every copied evidence file. `g2/cases.json` drives the writer cases.

| Fixture | Use |
|---|---|
| `kestrel-b35-01.set` + `g1-buildtemplate-kestrel.tpl` | **G1.** The writer's `<expert>`…`</expert>` (aiMode 0, `GOAT-EA\GOAT V1.49.ex5`) equals the real BuildTemplate output, line for line. |
| `g2/*.set` → `g2/*.chr`, `g2/dashboard-eurusd.chr`, `g2/profile/*` | **G2.** Frozen writer bytes covering: `;` lines, CRLF/LF mixes, padding, UTF-8 with and without a BOM, aiMode 0 and 2, the M1, M5, H4 and D1 periods, and the deployment nonce. Each case's `deploymentId` is in `cases.json`. `g2/profile` holds the full profile for a two-member plan, including `dashboard_state.tsv`; its nonce equals the deployment folder of the rows' SET paths. The MQL writer must produce the same bytes. |
| `g3-b35-chart02-mt5-saved.chr` + `g3-b35-dashboard-rows.tsv` | **G3.** MT5's own save of a child built from `kestrel-b35-01.set`. The frame matches (except the version and folder) and the inputs are audit-equal apart from the nonce in `Studio_MonitorRunPath`. The TSV row's `cid` equals the chart's `id=`. |
| `g3-t3-saved-native-e1.tpl` | **G3.** T3's save of the G1 template, with `expertmode=4`: the D2 evidence. The inputs are audit-equal; the extra names are WriteSet-omitted or CA41-declared defaults. |
