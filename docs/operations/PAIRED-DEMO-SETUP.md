# Matched demo pair setup

This is the bounded internal Balanced 35 AI experiment workflow, not a
customer-general installer. The source intentionally binds ordinals 7/8 to the
reviewed two accounts, V1.48 build, credential namespace and 35-member policy.
Different accounts/builds require a reviewed contract and new evidence. No
source helper below silently creates an account, changes a password or deploys
to the six existing accounts.

## Contract and source map

| Stage | Implementation | Evidence |
|---|---|---|
| Validate pair, connect or read runtime | [connection](../../scripts/goat_demo_pair_connection.py) | Exact path/hash/process, USD 100,000 demo / leverage 200 / hedging for initial login; receipt with funds, positions, orders and Algo state |
| Protected six, locks, admission | [guards](../../scripts/goat_demo_pair_guard.py) | Fresh six-process witness, shared lifecycle lock, pinned actual protected-release proof |
| Fresh inert installation | [prepare](../../scripts/goat_demo_pair_prepare.py) | Dry-run file claims, fresh bare profile,35 pending rows, installation/draft/reconnect manifests |
| Secret delivery | [PowerShell wrapper](../../scripts/goat_demo_pair_connect.ps1) | CurrentUser or explicit LocalMachine DPAPI; plaintext only in memory/stdin |
| Bare account to dashboard | [bootstrap](../../scripts/goat_demo_pair_bootstrap.py) | Exact inert process graceful close, selected symbols, new dashboard profile and frozen manifest |
| Sequential portfolio setup | [orchestrator](../../scripts/goat_demo_pair_orchestrate.py) | Durable intent chain, exactly-once configure/deploy/policy calls, native receipts |
| Settings plus current policy/AI | [paired readiness](../../scripts/goat_demo_pair_readiness.py) | Original native settings audit plus separate fresh native status; no synthetic merged receipt |
| Restart, snapshot and enable staging | [lifecycle](../../scripts/goat_demo_pair_lifecycle.py), [profile](../../scripts/goat_demo_pair_profile.py), [restart](../../scripts/goat_demo_pair_restart.py) | 36 experts, retained child identities, full profiles/inputs, explicit closed Algo transition |
| Non-native regression tests | [tests](../../scripts/goat_demo_pair_tests.py) |26 tests at initial delivery; native acceptance is separate |

Current terminal directories are `C:\GOAT Experiment\07 - Balanced 35 - AI OFF`
and `C:\GOAT Experiment\08 - Balanced 35 - AI ON`. Account bindings live in
`PAIR_ACCOUNTS` and the reviewed manifest; control is 3000109427, AI is 3000109421.
The expert path is `MQL5/Experts/GOAT Experiment/GOAT V1.48.ex5`; the isolated
Common Files credential is `GOAT/Credentials/api-bearer-balanced35-ai-20260923.token`.
Do not substitute the six-account `api-bearer.token` or reuse their installation
manifest/vault. Both arms have 35 identical members, risk/source settings preserved,
DEMO protocol 2 / threshold 50, exposure filter OFF; intended difference is AI OFF/ON.

The sealed EA source commit is `e96465d590690178176e55c51ff3c1bc8a363fde`, build
`V1.48-DASHBOARD-AI-PAIR-R1`, artifact SHA256
`8fec6e0379be4f2657f3c425ec1cf2e1701d3a65324e39576dcdcb6405833b0d`.
This identity alone is not admission. Root must provide the immutable actual
protected backend release/canary/registry-readback receipt and its SHA256. The
admission guard binds both accounts, build, artifact, compile receipt and source,
requires the seven-day maximum validity window, PASS canary and nonzero published
record, registry, API verification/source-tree/package hashes.

## Before running

Inspect the task's latest continuation, exact six protected processes, all pending
requests/claims, disk/RAM/CPU, final source hashes and source freeze. Keep receipts
outside Git. Use current witnessed timestamps; never extend an expired witness by
editing the old observation. All new operations coordinate through the existing
host lifecycle lock. A lock timeout is not permission to remove a lock.

Select reviewed host-local values for these PowerShell variables before executing
commands: `PairPython`, `PairScripts`, `PairStage`, `PairPlan`, `PairWitness`,
`PairPins`, `PairSdk`, `PairVault`, `PairAdmission`, `PairAdmissionSha`.
`PairPins` holds exact `goat_setup_control.py` and `goat_portfolio_setup.py` hashes.
`PairStage` is a new retained evidence directory, separate from either terminal.
`PairVault` points to the already provisioned pair-only DPAPI vault. No command
below provisions or retransfers that vault.

## Installation and bare broker qualification

Dry-run first, inspect claims, then apply once:

```powershell
& $PairPython -B "$PairScripts/goat_demo_pair_prepare.py" --plan $PairPlan --protected-witness $PairWitness
& $PairPython -B "$PairScripts/goat_demo_pair_prepare.py" --plan $PairPlan --protected-witness $PairWitness --apply
```

Preparation copies only hash-verified vendor terminal/server files, the sealed EA
and frozen SET files. It creates a **bare chart with no EA**, fresh config with
Algo OFF and a separate staged dashboard chart. It does not copy old common.ini,
accounts.dat, profiles, chart IDs or tokens. The initial profile's native
acceptance is a required qualification, not guaranteed by a source fixture.

Set `PairInstall` to the plan's actual outputDirectory and `PairOrdinal` to 7 first.
Set `PairConnection` to its `reconnect-manifest.json`. For this VPS select the
explicit LocalMachine vault scope (restricted Administrator/SYSTEM ACL); there is
no silent CurrentUser fallback. Other reviewed hosts may use CurrentUser scope.

```powershell
& "$PairScripts/goat_demo_pair_connect.ps1" -Python $PairPython -Manifest $PairConnection -Terminal $PairOrdinal -VaultPath $PairVault -VaultScope LocalMachine -SdkPath $PairSdk -AttemptDirectory "$PairStage/initial-07" -ProtectedWitness $PairWitness -InitialLogin -AllowClosed
```

This path may run before EA admission because it refuses a profile containing an
expert. It requires a cold launch and native USD 100,000 balance/equity, hedging demo,
leverage 200, no positions/orders, broker trading permission and terminal Algo OFF.
Any failure retains the startup intent and observed nonsecret state. Repeat for 8
only after 7 is understood; use another new evidence directory, never overwrite 7.

## Dashboard bootstrap and pairing

After the real backend admission exists, set `PairManifest` to
`terminal-07.json`, `PairDraft` to `portfolio-07.json`, and use the actual initial
receipt. Bootstrap selects the registered symbols and gracefully closes only the
verified bare process, with no kill fallback:

```powershell
& $PairPython -B "$PairScripts/goat_demo_pair_bootstrap.py" --manifest $PairConnection --terminal $PairOrdinal --initial-receipt "$PairStage/initial-07/result.json" --draft $PairDraft --protected-witness $PairWitness --sdk-path $PairSdk --output "$PairStage/bootstrap-07" --admission-proof $PairAdmission --admission-sha256 $PairAdmissionSha
```

Select the emitted reconnect manifest, then start the dashboard inert:

```powershell
$PairConnection="$PairStage/bootstrap-07/reconnect-manifest.json"
& "$PairScripts/goat_demo_pair_connect.ps1" -Python $PairPython -Manifest $PairConnection -Terminal $PairOrdinal -VaultPath $PairVault -VaultScope LocalMachine -SdkPath $PairSdk -AttemptDirectory "$PairStage/dashboard-start-07" -ProtectedWitness $PairWitness -AdmissionProof $PairAdmission -AdmissionSha256 $PairAdmissionSha -AllowClosed
& $PairPython -B "$PairScripts/goat_setup_control.py" register --manifest $PairManifest --allow-pairing-read
& $PairPython -B "$PairScripts/goat_setup_control.py" status --manifest $PairManifest
```

If native evidence shows activationOnly, request the explicitly registered public
pairing challenge through the setup client's `pairing` action and finish legitimate
GOAT approval. Do not log challenge data as routine status or copy privileged
tokens. Verify fresh native authorization, account/build identity and WebRequest
behavior. A configured URL does not prove WebRequest permission.

## 35 attachments and inert readiness

```powershell
& $PairPython -B "$PairScripts/goat_portfolio_setup.py" register --manifest $PairManifest --draft $PairDraft
& $PairPython -B "$PairScripts/goat_demo_pair_orchestrate.py" --control-dir $PairScripts --pins $PairPins --manifest $PairManifest --draft $PairDraft --terminal $PairOrdinal --run-dir "$PairStage/deployment-07" --protected-witness $PairWitness --reconnect-manifest $PairConnection
```

The durable journal claims configure and every individual child before issuing
the native request. It requires sequential unique chart/magic identities, fresh
linkage, intended policy acknowledgement, exact input audit and fresh AI status.
The proof is in `deployment-07/paired-readiness/proof.json`. A withheld but verified
AI signal is allowed; unknown/stale AI is not readiness.

Unknown outcomes stop the tool. Only a separately inspected resume document can
continue the existing run; it cannot repeat a previously attempted mutation.
Never change run-dir to evade an old intent/owner claim. Do not register again
while the orchestrator owns the terminal or a native request is unresolved.

## Restart rehearsal and authorized launch

Common lifecycle arguments, rebuilt with the **latest** combined reconnect manifest:

```powershell
$PairLife=@('--control-dir',$PairScripts,'--pins',$PairPins,'--manifest',$PairManifest,'--draft',$PairDraft,'--terminal',"$PairOrdinal",'--reconnect-manifest',$PairConnection,'--protected-witness',$PairWitness)
$PairProof="$PairStage/deployment-07/paired-readiness/proof.json"
& $PairPython -B "$PairScripts/goat_demo_pair_lifecycle.py" close @PairLife --proof $PairProof --sdk-path $PairSdk --output "$PairStage/close-off-07"
& $PairPython -B "$PairScripts/goat_demo_pair_lifecycle.py" freeze-off @PairLife --proof $PairProof --shutdown "$PairStage/close-off-07/shutdown.json" --output "$PairStage/freeze-off-07"
```

Select `freeze-off-07/reconnect-manifest.json`, restart via the same wrapper with a
new attempt directory and admission proof, and run:

```powershell
& $PairPython -B "$PairScripts/goat_demo_pair_lifecycle.py" post-restart @PairLife --proof $PairProof --prior-runtime "$PairStage/close-off-07/runtime-before.json" --restart-receipt "$PairStage/restart-off-07/result.json" --output "$PairStage/rehearsal-07"
```

Rebuild `PairLife` after selecting each new manifest. The rehearsal validates 36
experts/charts, retained 35 child identities, source/effective inputs and policy,
then issues one new policy command and captures a new distinct audit/status proof.

For launch, take the rehearsal's paired proof, close inert once again, and use
`freeze-on` with that new close receipt and `--rehearsal
"$PairStage/rehearsal-07/completion.json"`. This changes the selected **closed**
terminal's saved Algo state, snapshots profile/config/state and emits another
manifest. It does not start trading. Root must compare both arms, fresh protected
six and capacity before explicitly starting the enabled manifests via the wrapper.

Carry the newest combined manifest into the other arm's stages; do not substitute
an earlier manifest that still describes the other arm's pre-rehearsal profile.
Preserve actual startup receipts and times. Establish the comparison baseline only
after both arms are verified, accounting for any staggered-start trades. No test
order or balance reset is necessary. A failed observer after startup may leave a
running terminal: inspect the retained process before retrying anything.

## Monitoring and documentation

The website live adapter separately verifies running status against retained
settings/audit and startup evidence; the inert readiness verifier is not a live
proof. Native command IDs can reset on restart. Check actual fresh 35 child
AI/exposure settings and no pending changes rather than demanding an old ID.

Portfolio registration expiry is four hours. The approved pair monitoring path
may renew **only expiry with unchanged account/build/membership/settings/policy**,
under lifecycle/orchestration exclusion and with old/new digest receipts and no
pending request. It must not invalidate or rewrite the historical settings proof.
That renewal lives in the separately reviewed website adapter, not these helpers.

At delivery, 26 pure tests and syntax checks passed; no native setup was performed
by the tooling author. Record actual host successes/failures in the task handoff,
then update the relevant skill's operating reference. Never promote source tests,
an inert presentation preview, prepared files or a completed process launch into
claims of production attachment, AI readiness or an active trading experiment.
