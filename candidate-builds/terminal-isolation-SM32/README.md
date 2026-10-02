SM32 is an inert forward V1.49 candidate. It is SM31 plus terminal isolation, so every
MT5 terminal and account on one PC runs its batch state and its GOAT sign-in independently:

- Common batch state lives in `GOAT\<EA>-<server>-<login>-<terminal hash>` (INV-BATCH-01),
  with a one-time move of the shared pre-isolation files that only the holder of the shared folder's
  create-only claim performs, that resumes after a crash, and that is refused when both folders hold state.
  Load SM32 on the terminal that ran the shared batch first (Banker on this PC).
- The GOAT user credential is stored per MT5 login, `GOAT\Credentials\api-bearer-v149-<login>.token`
  (INV-CRED-01), with a copy-only migration of the shared file only on an `approved` status for this login.
- The tester's running fitness file is per optimization run (a nonce handed to agents through the
  `GOAT_FitnessRunNonce` input) instead of one shared `GOAT\Tester.txt`.
- The Studio observation reports `state_base`, which the controller must match before native work.

Its `GOAT_BUILD_ID` is `V1.49-TERMINAL-ISOLATION-32`, with marker `SM32`. `identity.json` binds the
exact forward source. **The compile is pending:** there is no `GOAT V1.49.ex5` or `compile-receipt.json`
here yet. After the reviewed head is compiled, add the binary and the sanitized receipt, set
`identity.json` `binary` and `compile`, and keep the candidate test in step.

**Rollout conditions (mandatory):**
- **Banker loads SM32 first.** The terminal that ran the shared batch takes the shared folder's claim and
  moves its state. There is no automated recovery yet for a stale or wrong claim. If one needs clearing,
  the operator archives `terminal-isolation-claim.ini` and the claim holder's `terminal-isolation.ini`
  receipt (never deletes), and only after the holder's receipt shows nothing in flight.
- **Every terminal, Banker included, re-pairs once after the upgrade.** The credential copy only
  fires on an `approved` status, and `activation_reload_pending` overwrites that status in the same
  timer call, so in practice each login signs in once for its own token file. Plan the pairings with Vince.
- No batch may be in flight on any terminal of the PC during the upgrade. Re-prepare saved batch
  packages afterwards (the header hash changed).
- If the per-run fitness key cannot be set (`ParameterSetRange` refused), the optimization still runs.
  OnTesterInit falls back to the key the agents actually see (key 0 by default), seeds that file and
  deletes it in OnTesterDeinit. Agents share the key-0 fitness file and keep the de-noise step, so the
  fitness meaning is SM31's. Only two terminals optimizing the same strategy and symbol at once could
  then interfere, which the warning says.

**Prove natively after compile:**
- OnTesterInit and the agents compute the same nonce;
- whether `ParameterSetRange` refuses in any mode the batches use (if it does, the key-0 fallback is
  the main path, not an edge case, and same-strategy + same-symbol concurrency needs another key);
- whether batch restarts relied on MT5's optimization cache (a new nonce per run means a restarted
  item recomputes every pass; measure the cost);
- two concurrent batches (same and different strategy, including one login on both terminals);
- the A/B pairing test;
- the first-load move with a copied terminal present.

SM31 stays retained unchanged in `candidate-builds/ndx-symbol-map-SM31`. The root `GOAT V1.49.ex5`
and all installed artifacts remain unchanged. Compilation does not qualify native use: exact-head
review, isolated native DEMO/owner/STOP/Algo-off qualification and a separately reviewed customer
delivery remain required.
