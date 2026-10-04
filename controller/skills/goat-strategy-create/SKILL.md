---
name: goat-strategy-create
description: Guide a user, expert or not, from a trading idea to their own new GOAT strategy file through a plain-language interview, a catalog check first, then starter-set, build-set and validate-set, registered as an untested fork with zero evidence.
---

Read [template construction](../../TEMPLATE-WORKFLOW.md) and the
[input reference](../../INPUT-REFERENCE.md), and run `discover` for the installed
schema, dependency policy and operation contracts. Talk to the user in plain
English, one question at a time; keep input names, enum numbers and ranges for
yourself unless they ask. Demo accounts only. Building a file never touches MT5.

**1. The idea, not inputs.** Ask what market behaviour they want to trade: a trend,
a pullback inside a trend, a breakout, mean reversion (fading extremes) or a
session/time pattern. Then which symbols (exact broker names later) and which
session (Asia, Europe, US or all day). Say the idea back in one sentence; get a yes.

**2. Single trade or sequence.** Single: one trade per signal, closed by its exit
or stop. Sequence: more trades added as price moves against the first one. If they
lean to a sequence, explain the risk first, before any other sequence question: a
sequence can run a long way against them; `Risk` is the money lost per sequence when
one fails (the sequence starter hard-closes there); a maximum number of trades caps
it; the gaps between trades and the lot growth decide how far and how big it gets.
Use their own demo numbers ("Risk 500 on a 10,000 demo is about 5% per failed
sequence"). Only then ask about max trades, gaps and lot growth.

**3. Entry filters.** Map the idea to the EA's real signal inputs from `discover`
and INPUT-REFERENCE: RSI/RSI2 (overbought/oversold, crosses), EMA and ADX (trend,
range or counter modes), Bollinger Bands (channel, overbought/oversold, trend),
MACD; sessions with `Active_Time_*`; direction with `Mode_Trade`. Enable only what
the idea needs. Every other signal mode stays at its disabled value with its
period/level inputs fixed. Resolve each enum by its own exact numbers. The AI bias
and news filters are separate choices the user makes explicitly.

**4. Exits and sizing.** Agree take profit, stop, trailing and lock-profit in plain
words (negative pip values mean ATR multiples). Single trade: fixed lots; the starter
sets `CloseAtMaxLevels` so the next gap against the trade closes it; add `SL_Pips`
for a hard stop (with RSI on, that gap check also waits for RSI). Never risk-based
sizing with fewer than 2 trades: the EA has no loss path to size from and would use
the broker maximum, so every validate-set and build-set refuses it
(`RISK_PER_SEQUENCE_NEEDS_TWO_TRADES`). Sequence: `RiskperSeq`, and **ask the user
for `Risk`**, the money one failed sequence may lose, as an amount of their demo
currency. The starter's 500 is only a placeholder (half of a 1,000 demo); build-set
from a sequence starter refuses with `RISK_NOT_CHOSEN` until `Risk` is in the changes
with the user's own amount, even when they choose 500.

**5. Catalog check before building.** Read `Desktop 'strategy.matrix'` and compare
the answers with each template's description, support notes and SET (enabled
signals, single or sequence, exits) and the user's own results. If one is close, say
so: "this is about 80% like template X, which has results; start from it or from
blank?" Prefer the existing template when it really is close: it has evidence and a
blank has none (then follow goat-template-create). The percentage is a rough
comparison of filters, shape and exits; say so, never present it as a measurement.

**6. Build.** Write the spec as in TEMPLATE-WORKFLOW: one rationale per change and
honest `entry_logic`, `ladder_exits` and `intended_role` for the actual file. Search
only a few inputs the idea depends on; at least one search axis is required.

```powershell
Studio @('starter-set','--shape','single','--output','<My strategies>\Starter.set')   # or --shape sequence
Studio @('build-set','--source','<My strategies>\Starter.set','--output','<My strategies>\<name>.set','--spec','<changes.json>')
Studio @('validate-set','--set','<My strategies>\<name>.set','--require-optimization')
Desktop 'strategy.forkTemplate' @{starter='single'; name='<name agreed with the user>'
  contentBase64=[Convert]::ToBase64String([IO.File]::ReadAllBytes('<My strategies>\<name>.set'))}
```

`starter-set` writes a blank SET from the installed schema (no entry filter, nothing
searched) and a `.starter.json` receipt listing every input it set away from its
default; it never overwrites. Run `validate-set --require-optimization` on the
result. Check the `.build.json`: `parent` is `starter:single` or `starter:sequence`
and `starter.warnings` must be read to the user. For a starter parent the desktop
takes `{ starter: 'single' | 'sequence', contentBase64, name }` instead of
`{ templateId, contentBase64, name }`; pass exactly one. Keep the `.md` notes and
`.build.json` beside the fork.

**7. Untested, then research.** Mark it UNTESTED and say plainly: "a new idea starts
with zero evidence". Hand off to Explore, then Refine, then Prove. Hand-built ideas
overfit easily, because every filter the user picked is part of the search, so the
13-week held-out lock matters even more: declare it with `heldOut.declare` as the
strategy enters Prove, let those unseen weeks close, and never tune against them.
Never claim or imply performance. Demo only; real money stays the user's own
decision outside this workflow.
