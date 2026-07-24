# GOAT legacy-wire corrective source patch

Status: source patch only. No versioned release entrypoint or binary is attached or
authorized by this change. This deliberately avoids copying the already-exposed
static bearer material into another public source file.

The patch makes the live legacy bias client fail closed against
`ea-legacy-wire-contract-v1`:

- validates the complete HTTP 200 JSON envelope and every row before use;
- derives authoritative time from response `server_time` plus measured request
  duration, then advances it only with a monotonic clock;
- enforces the packed 65-minute `validUntil` value and never falls back to an older
  row;
- rejects every non-200 response before body parsing;
- removes live recursive history fallback and dummy neutral injection;
- pauses both addition lanes when bias controls additions and the feed is unavailable,
  while leaving independent stops and close logic untouched.

Focused source verification:

```text
python3 tests/test_ea_wire_source_integration.py
```

`tests/EA_Legacy_Wire_Contract_Compile.mq5` compiles the strict parser fixture with
MetaEditor and exercises the required success and failure cases when run as an MQL5
script.

Full build closure remains open. The repository does not track the `ControlsPlus`
include tree, `Canvas/png.mqh`, or the source/binary behind the embedded
`Indicators/MACD - GOAT 2.ex5` resource. A release requires those dependencies to be
pinned, creation of a properly versioned release entrypoint without duplicating
public credential material, a clean MetaEditor build, execution of the runtime
fixture, and source-to-binary hash evidence. The existing V1.42 binary remains the
served authority until that separately reviewed release occurs.
