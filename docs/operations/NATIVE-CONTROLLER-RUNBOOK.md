# Native terminal and portfolio controller

For broker login before EA initialization, use the separate [demo connection
contract](DEMO-CONNECTION.md). Its tests and Windows process preflight pass;
successful native login qualification remains pending. Do not confuse this new
client with the existing initialized-EA RPCs described below.

## Present capability boundary

The existing clients operate an EA which has already initialized its controller.
They do not install a terminal, log in to a broker, start an uninitialized EA,
import arbitrary folders, or enable trading. Portfolio members must already be
present in the dashboard's saved state. The one-command customer bootstrap is
unfinished. See `scripts/goat_setup_control.py`, `scripts/goat_portfolio_setup.py`
and the current `goat-vps-setup` skill for the implemented contracts.

The local client can be used on this computer or via SSH on a VPS; the manifest
binds the exact host-local paths. Moving a Python client to the local machine
does not make it control a remote Common Files directory.

## Command map

Run `--help` before adapting a command to a different checkout. Use a manifest
created for the selected terminal and candidate build, not these placeholders.

```text
python scripts/goat_setup_status.py --installation <installation.json> --common-files <common-files> --hash-installed-ea
python scripts/goat_setup_control.py register --manifest <terminal.json>
python scripts/goat_setup_control.py status --manifest <terminal.json>
python scripts/goat_portfolio_setup.py register --manifest <terminal.json> --draft <portfolio.json>
python scripts/goat_portfolio_setup.py configure --manifest <terminal.json>
python scripts/goat_portfolio_setup.py deploy_next --manifest <terminal.json>
python scripts/goat_portfolio_setup.py apply_policy --manifest <terminal.json>
python scripts/goat_portfolio_setup.py audit --manifest <terminal.json>
python scripts/goat_portfolio_setup.py status --manifest <terminal.json>
```

`deploy_next` is one attachment, not an invitation to issue a blind loop. Inspect
its retained request and native receipt before advancing. An unresolved `started`
or timeout requires reconciliation. Count unique chart/magic identities and exact
input matches, not rows in the saved file. The current portfolio client binds rows
by ordinal; a sorted/reordered dashboard needs investigation, not a membership
waiver. The older setup inventory helper pins a V1.47 disk path; for V1.48 compare
the manifest-selected EX5 explicitly until that helper accepts a versioned path.

Pairing adds a short-lived permission:

```text
python scripts/goat_setup_control.py register --manifest <terminal.json> --allow-pairing-read
python scripts/goat_setup_control.py pairing --manifest <terminal.json>
```

Match account, build and challenge expiry to the real portal authorization.
Do not overwrite another experiment's credential. Internal release admission,
account entitlement and actual installed binary identity are separate checks.

## Readiness stages

Versioned controller installations can supply both `expertRelativePath` and
`credentialRelativePath` in the setup manifest. They are normalized relative
paths under `MQL5/Experts/` and `GOAT/Credentials/` respectively; both are required
together. Omitting both preserves the original V1.47 installation contract.
The setup/portfolio clients hash the selected EX5 before registration or commands.
The read-only status tool takes matching `--expert-relative-path` and
`--credential-relative-path` options. It must not inspect the incumbent credential
when reporting an isolated new build. Never infer a version from the window title.

| Stage | Evidence required | Does not prove |
|---|---|---|
| Process started | Exact executable/PID/creation time | Correct login, initialized EA or visible dashboard |
| Broker connected | Fresh native account/server/data path, permissions | EA authorization or portfolio readiness |
| EA initialized | Fresh native status, build, `activationOnly:false` | Every child attached |
| Portfolio loaded | Exact immutable members and source hashes | Child settings applied or trading |
| Portfolio attached, inert | Full settings audit plus fresh status; unique linked members; Algo OFF | Live performance |
| Policies applied | All relevant child acknowledgements, effective AI mode/feed/threshold/scope and exposure policy | AI availability at every future instant |
| Restart verified | New native observation, same frozen profile/identities/settings | Unattended launch is authorized |
| Trading armed | Authorized launch, actual Algo/EA permission, fresh account/policy checks | A trade has occurred |

For a UI-only preview, use a separate marked harness with no trading event
handlers. Frozen real member data is useful for layout QA, but this is neither
production EA activation nor deployment of 35 trading instances. Prefer investor
credentials for a connected preview; verify account permission is read-only and
Algo remains OFF. Never silently fall back to a master credential after failure.

## Bootstrap and recovery

1. Freeze the portfolio and its input hashes, expected account/build and desired
   mode before starting. Preserve original `EA_Desc` identities independently
   from human display names.
2. Prepare the exact EA/preset/profile/startup configuration. MT5 supports
   `/portable`, `/config` and `/profile`; see the official
   [startup reference](https://www.metatrader5.com/en/terminal/help/start_advanced/start).
   A `/config` startup chart is disposable and its config is read-only. Use a
   properly saved normal profile for repeatable production restarts.
3. Use a qualified credential launcher for the explicitly owned new demo. Keep
   passwords out of argv, logs, manifests, Git and temporary plaintext files.
   Attaching to an existing trading terminal is a different operation: no implicit
   credential change or restart.
4. Require a bounded initialization/readiness response. `loaded successfully` in
   the terminal journal means the EX5 was loaded, not that `OnInit` completed.
   An empty disconnected terminal can wait on unavailable symbol context.
5. On timeout inspect the retained attempt and current process before recovery.
   Distinguish process exit, market-data initialization, broker rejection,
   activation-only state, membership mismatch and command timeout. Never retry
   account authentication indiscriminately or repeat a possibly completed deploy.
6. After a verified inert load, save/preserve the profile, conduct one controlled
   restart rehearsal and re-audit. Do not promote a test harness to a live binary.

Screenshots are optional visual evidence after native readiness. A stopped
Computer Use session is not an instruction to replace clicks with shell-based
UI automation. Continue through supported APIs/configuration only, within scope.

## Next controller improvements (not implemented commands)

- A manifest-driven bootstrap covering public broker metadata, encrypted login,
  source/binary hashes, market-watch readiness and native initialization timeout.
- Preview/load modes with explicit requested/achieved state and deterministic
  receipts, without fabricated policy or performance telemetry.
- Import frozen members through a registered operation instead of hand-writing
  per-machine saved state.
- Version-aware installed-binary inspection and stable member identity matching.
- Resume from the last proven stage; preserve unsuccessful attempts and never
  duplicate an unresolved mutation.

The acceptance test is a fresh agent launching the selected local portfolio from
the manifest, receiving verifiable native state and showing the UI without using
the mouse to set it up. Until that passes, describe the bootstrap as incomplete.
