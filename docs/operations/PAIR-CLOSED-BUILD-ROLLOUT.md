# Closed demo-pair build rollout

`goat_demo_pair_build_rollout.py` qualifies the inspected September 24 R1-to-R2
transition only. Both pair processes must be absent and Algo must remain OFF.
Terminal 07 must have the completed second partial recovery, all 26 saved children
and its original deployment journal. Terminal 08 must have only its known inert
dashboard. This tool does not issue RPC, import the SDK, start/close a process or
enable trading. Root remains the operator of separately reviewed native actions.

`goat_demo_pair_builds.py` contains two exact reviewed binary/source/compile tuples.
They are not admission. Rollout and connection also require the pinned, currently
valid protected backend release receipt for that exact build and pair accounts.
Missing, queued or unsuccessful admission cannot be replaced by a catalog entry.

## Private plan preparation

Use the host's current files, not a local stale copy. The following Python example
only constructs a new private plan; it does not apply it. Supply the actual fresh
R2 admission path after protected release and readback. Pin the independently
verified candidate binary. `R` is the existing evidence directory; `C` comes from
the original installation manifest's `commonFiles`. Do not put the private plan,
account metadata or snapshots in Git. Preserve all original artifacts.

```python
import hashlib, json
from pathlib import Path
R = Path('C:/GOAT Experiment/Installation Evidence/Balanced35-V148-20260924')
def pin(path):
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
def optional(path):
    return pin(path) if path.exists() else None
targets = []
for n in (7, 8):
    installation = R / f'installation/terminal-{n:02d}.json'
    i = json.loads(installation.read_bytes())
    D, C = Path(i['directory']), Path(i['commonFiles'])
    setup = C / 'GOAT/AgentSetup' / D.name
    portfolio = C / 'GOAT/AgentPortfolio' / D.name
    t = dict(terminal=n, installation=pin(installation),
        draft=pin(R / f'installation/portfolio-{n:02d}.json'),
        setupRegistration=pin(setup / 'registration.json'),
        portfolioRegistration=optional(portfolio / 'registration.json'),
        owner=optional(portfolio / 'orchestration-owner.json'),
        state=pin(C / 'GOAT' / f'dashboard_state_{D.name}.tsv'),
        globals=pin(D / 'bases/gvariables.dat'))
    for kind, folder in [('setup', setup), ('portfolio', portfolio)]:
        request = folder / 'request.json'
        t[kind + 'Request'] = optional(request)
        t[kind + 'Receipt'] = (pin(folder / (json.loads(request.read_bytes())['id'] + '.json'))
            if request.exists() else None)
    targets.append(t)
plan = dict(schema='goat-pair-closed-build-rollout-v1',
    manifest=pin(R / 'partial-child-recovery-v2/reconnect-manifest.json'),
    candidate=pin(Path('C:/Windows/Temp/GOAT-V148-R2-1995f434.ex5')),
    admission=pin(R / 'admission-proof-r2.json'), # actual reviewed release readback
    pins=pin(R / 'controller-pins.json'), controlDirectory=str(R / 'tools'),
    outputDirectory=str(R / 'closed-build-rollout-r2'),
    recovery=pin(R / 'partial-child-recovery-v2/recovery-proof.json'),
    journal=pin(R / 'deployment-07/journal.jsonl'),
    dashboardReference=pin(R / 'activation-recapture/8/profile/chart01.chr'),
    dashboardShutdown=pin(R / 'dashboard08-r2-close/shutdown.json'), targets=targets)
with (R / 'closed-build-rollout-r2-plan.json').open('x', encoding='utf8') as out:
    json.dump(plan, out, indent=2)
```

Review every pinned path, receipt and process inventory. Terminal 08's native
shutdown is historical evidence, not a fresh observation: no age-only restart is
required. Current process absence, fresh protected-six witness, current exact
config/global/state bytes and full dashboard input equality against the retained
native chart are required independently. Its UI objects may have changed the
profile hash; the helper retains the complete current profile and records that
hash without changing its inputs. For 07 the repaired profile hash must be exact.

```powershell
& $PairPython -B "$PairScripts/goat_demo_pair_build_rollout.py" --plan "$PairStage/closed-build-rollout-r2-plan.json" --protected-witness "$PairStage/protected-six-witness.json"
# Only after reviewing dry_run_passed and the pinned plan:
& $PairPython -B "$PairScripts/goat_demo_pair_build_rollout.py" --plan "$PairStage/closed-build-rollout-r2-plan.json" --protected-witness "$PairStage/protected-six-witness.json" --apply
```

Apply takes the shared lifecycle, setup/portfolio producer and original journal
locks, then repeats validation. It saves complete old binaries, configurations,
profiles, globals, state and metadata under private ACLs. Only completed request
files are retired; UUID receipts remain in their native folders. New immutable
`terminal-07.json`, `portfolio-07.json`, `terminal-08.json`, `portfolio-08.json`
and combined `reconnect-manifest.json` describe R2. Original installation files,
SET files, child identities, globals, inputs and common.ini stay unchanged.
Registrations change only build identity and expiry; 08's first portfolio
registration is created from the original reviewed draft. One `build_transition`
record binds the old and new metadata into **the existing 07 journal**. A partially
applied output remains for inspection; do not delete it or rerun into a new folder.

## Inert restart, original 07 resume and first 08 attachment

Let `$Rollout` be the completed output directory. Use its new combined manifest
for both separately retained connection attempts, with the exact R2 admission
proof/hash and `--allow-closed`. Omit `--initial-login`; the accounts already have
qualified credentials. Run each through the reviewed persistent InteractiveToken
runner, never as an SSH child. Confirm both exact new processes, Algo OFF and
fresh native status. A startup or completed rollout is not attachment success.

For 07, request and retain a fresh native portfolio `status` using the **new**
`$Rollout/terminal-07.json`. Check the unchanged 26-member prefix and empty row 26.
Create a new inspection JSON with exact schema below, hashing the current original
journal after the build-transition record and the actual native UUID receipt:

```json
{"schema":1,"decision":"resume_from_observed_state","journalSha256":"<current-original-journal-sha>","receiptPath":"<native-UUID-status-path>","receiptSha256":"<exact-status-sha>"}
```

The status must be at most 120 seconds old at resume. The resumed command belongs
inside its own one-shot interactive task with retained output; do not rerun the
old issued attachment wrapper:

```powershell
& $PairPython -B "$PairScripts/goat_demo_pair_orchestrate.py" --control-dir "$PairStage/tools" --pins "$PairStage/controller-pins.json" --manifest "$Rollout/terminal-07.json" --draft "$Rollout/portfolio-07.json" --terminal 7 --run-dir "$PairStage/deployment-07" --protected-witness "$PairStage/protected-six-witness.json" --reconnect-manifest "$Rollout/reconnect-manifest.json" --inspection "$PairStage/r2-resume07-inspection.json" --recovery-proof "$PairStage/partial-child-recovery-v2/recovery-proof.json" --recovery-proof-sha256 $RecoveryProofSHA --build-rollout-proof "$Rollout/rollout-proof.json" --build-rollout-proof-sha256 $RolloutProofSHA
```

Both proof hashes come from retained completion records and must match actual
bytes. The transition validates both historical recoveries against their original
R1 registration and journal prefix; it does not rewrite old build identities.
Only the one unused `recovery:deploy:26:<failure-sha>` may be attempted. All prior
ordinary/recovery intents still block repeats. A new timeout requires inspection.

After 07 completes successfully, verify 08 is authorized, connected, flat and
Algo OFF with its single dashboard. Its fresh portfolio registration is already
staged; do not register it a second time. Use its original unused `deployment-08`
directory with the new manifest/draft and combined manifest, without inspection,
recovery or rollout flags:

```powershell
& $PairPython -B "$PairScripts/goat_demo_pair_orchestrate.py" --control-dir "$PairStage/tools" --pins "$PairStage/controller-pins.json" --manifest "$Rollout/terminal-08.json" --draft "$Rollout/portfolio-08.json" --terminal 8 --run-dir "$PairStage/deployment-08" --protected-witness "$PairStage/protected-six-witness.json" --reconnect-manifest "$Rollout/reconnect-manifest.json"
```

Then complete each 35-member full input/policy audit, paired native readiness,
restart rehearsal, same-members/only-AI comparison and current capacity checks.
Any later trading-enabled launch remains a separate reviewed operation requiring
the closed persistence proof. Admission remains required at every launch.

## Immutable tool packaging and tests

Freeze these 14 source files together from the reviewed commit under one directory:
`goat_demo_pair_builds.py`, `goat_demo_pair_build_rollout.py`,
`goat_demo_pair_connection.py`, `goat_demo_pair_guard.py`,
`goat_demo_pair_orchestrate.py`, `goat_demo_pair_profile.py`,
`goat_demo_pair_readiness.py`, `goat_demo_pair_recover_child.py`,
`goat_demo_pair_recover_child_v2.py`, `goat_demo_pair_dashboard_recapture.py`,
`goat_demo_pair_trust.py`, `goat_demo_pair_lifecycle.py`,
`goat_demo_pair_restart.py`, `goat_demo_pair_prepare.py`.
Also include the 15th file, `goat_demo_pair_connect.ps1`, beside the updated
`goat_demo_pair_connection.py`: the credential wrapper resolves its Python client
through `$PSScriptRoot`. Invoking an old wrapper directory would load old tooling.
Keep the two separately pinned native controller sources in their reviewed
`--control-dir`. Package by explicit tracked paths, excluding `__pycache__`,
credentials, scratch artifacts and unrelated files. Verify a SHA-256 inventory
after transfer. Do not change earlier immutable tool packages.

Run `python -B scripts/test_goat_pair_build_rollout.py`, the existing
`goat_demo_pair_tests.py`, `test_goat_pair_recovery_v2.py` and
`test_goat_deployment_liveness.py`. These use local fixtures; they do not establish
native liveness or R2 runtime success.
