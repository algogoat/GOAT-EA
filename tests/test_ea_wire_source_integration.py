#!/usr/bin/env python3
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
FILTER_SOURCE = (ROOT / "NewsBiasFilter.mqh").read_text(encoding="utf-8-sig")
EA_SOURCE = (ROOT / "GOAT V1.42.mq5").read_text(encoding="utf-8-sig")
WIRE_SOURCE = (ROOT / "EALegacyWireContract.mqh").read_text(encoding="utf-8-sig")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


require(
    '#include "EALegacyWireContract.mqh"' in FILTER_SOURCE,
    "live bias source must include the strict wire evaluator",
)
require(
    "EAEvaluateLegacyBiasResponse(json,asset,request_elapsed_ms,evaluated)" in FILTER_SOURCE,
    "live HTTP 200 body must pass through the strict evaluator",
)
require(
    "LastBiasAuthoritativeNowMs=evaluated.authoritative_now_ms;" in FILTER_SOURCE
    and "LastBiasAuthoritativeTickMs=request_finished_tick;" in FILTER_SOURCE,
    "accepted server time must be anchored to the monotonic response tick",
)
require(
    "wire_valid_until_ms<=authoritative_now_ms" in FILTER_SOURCE,
    "cached live rows must enforce explicit validUntil",
)
require(
    'InvalidateLiveBias("HTTP_STATUS_"+(string)res);' in FILTER_SOURCE,
    "non-200 responses must invalidate live bias",
)
require(
    "return DownloadAndFillBias(startdate - 24*60*60" not in FILTER_SOURCE,
    "live parse failure must not recurse into older windows",
)
require(
    "Injected dummy 0 bias point" not in FILTER_SOURCE,
    "live parse failure must not fabricate neutral",
)
require(
    re.search(
        r"else if\(res!=200\).*?"
        r'InvalidateLiveBias\("HTTP_STATUS_"\+\(string\)res\);.*?return false;',
        FILTER_SOURCE,
        re.DOTALL,
    ),
    "non-200 branch must return before response parsing",
)
require(
    "bool bias_controls_additions = bias_filter_active && Mode_Bias_Trades==Bias_SeqTrade;"
    in EA_SOURCE,
    "unavailable bias must identify when bias controls sequence additions",
)
require(
    "Sequence_Pause_Bias_B = bias_controls_additions;"
    " Sequence_Pause_Bias_S = bias_controls_additions;"
    in EA_SOURCE,
    "unavailable bias must pause both controlled addition lanes",
)
for side, sequence in (("B", "Buy"), ("S", "Sell")):
    downstream_guard = (
        f"else if(Sequence_Pause_Bias_{side} && "
        f"(Bias_Feed_Unavailable || !Seq_{sequence}.BiasRescueActive))"
    )
    require(
        downstream_guard in EA_SOURCE,
        f"unavailable {sequence.lower()} rescue must be stopped at the downstream addition consumer",
    )
    require(
        re.search(
            re.escape(downstream_guard)
            + r".*?else\s*\{.*?"
            + re.escape(f"Seq_{sequence}.Add_Level("),
            EA_SOURCE,
            re.DOTALL,
        ),
        f"{sequence.lower()} addition must remain behind the unavailable-aware pause guard",
    )
    require(
        f"Sequence_Pause_Bias_{side} && !Seq_{sequence}.BiasRescueActive"
        not in EA_SOURCE,
        f"legacy {sequence.lower()} rescue bypass must not survive",
    )
require(
    "bool Bias_Feed_Unavailable = true;" in EA_SOURCE
    and "Bias_Feed_Unavailable=false;" in EA_SOURCE
    and "Bias_Feed_Unavailable=true;" in EA_SOURCE,
    "live bias availability must fail closed and track accepted versus unavailable state",
)


def reaches_add_level(
    sequence_pause: bool,
    feed_unavailable: bool,
    rescue_active: bool,
) -> bool:
    blocked = sequence_pause and (feed_unavailable or not rescue_active)
    return not blocked


for sequence in ("buy", "sell"):
    require(
        not reaches_add_level(True, True, True),
        f"unavailable {sequence} rescue must not add risk",
    )
    require(
        not reaches_add_level(True, True, False),
        f"unavailable non-rescue {sequence} sequence must not add risk",
    )
    require(
        reaches_add_level(True, False, True),
        f"available {sequence} rescue compatibility must remain unchanged",
    )
require(
    '"  Latest Bias: UNAVAILABLE"' in EA_SOURCE
    and '"Previous Bias: UNAVAILABLE"' in EA_SOURCE,
    "feed unavailability must render distinctly from model-authored neutral",
)
for required_reason in (
    "BODY_JSON_INVALID",
    "SERVER_TIME_INVALID",
    "DATA_EMPTY",
    "ROW_ASSET_MISMATCH",
    "ROW_TIMESTAMP_INVALID",
    "ROWS_NOT_STRICTLY_ASCENDING",
    "ROW_SENTIMENT_INVALID",
    "ROW_VALIDITY_WINDOW_INVALID",
    "ROW_FROM_FUTURE",
    "VALID_UNTIL_EXPIRED",
):
    require(
        f'"{required_reason}"' in WIRE_SOURCE,
        f"strict evaluator must expose {required_reason}",
    )

print("EA wire source integration checks passed.")
