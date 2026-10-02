SM32 is an inert forward V1.49 candidate. It is SM31 plus terminal isolation, so every
MT5 terminal and account on one PC runs its batch state and its GOAT sign-in independently:

- Common batch state lives in `GOAT\<EA>-<server>-<login>-<terminal hash>` (INV-BATCH-01),
  with a one-time move of the shared pre-isolation files and a refusal when both folders hold state.
- The GOAT user credential is stored per MT5 login, `GOAT\Credentials\api-bearer-v149-<login>.token`
  (INV-CRED-01), with a copy-only migration of the shared file when this login provably wrote it.
- The tester's running fitness file is per optimization run instead of one shared `GOAT\Tester.txt`.
- The Studio observation reports `state_base`, which the controller must match before native work.

Its `GOAT_BUILD_ID` is `V1.49-TERMINAL-ISOLATION-32`, with marker `SM32`. `identity.json` binds the
exact forward source. **The compile is pending:** there is no `GOAT V1.49.ex5` or `compile-receipt.json`
here yet. After the reviewed head is compiled, add the binary and the sanitized receipt, set
`identity.json` `binary` and `compile`, and keep the candidate test in step.

SM31 stays retained unchanged in `candidate-builds/ndx-symbol-map-SM31`. The root `GOAT V1.49.ex5`
and all installed artifacts remain unchanged. Compilation does not qualify native use: exact-head
review, isolated native DEMO/owner/STOP/Algo-off qualification and a separately reviewed customer
delivery remain required.
