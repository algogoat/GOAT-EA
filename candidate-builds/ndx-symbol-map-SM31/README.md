SM31 is an inert forward V1.49 candidate. It is SP30 plus one symbol-map change:
`ConvertToGOATsymbol` maps a broker symbol that starts with `NDX` (Darwinex lists the
Nasdaq 100 as `NDX`) to GOAT's `NAS100`, so GOAT AI features cover it.

Its `GOAT_BUILD_ID` is `V1.49-NDX-SYMBOL-MAP-31`, with marker `SM31`. `identity.json`
binds the binary to the exact forward source and `compile-receipt.json` records the
isolated compiler result without host paths. The full private receipt is retained
outside this repository.

SP30 stays retained unchanged in `candidate-builds/start-protocol-SP30`. The root
`GOAT V1.49.ex5` and all installed artifacts remain unchanged. Compilation does not
qualify native use: exact-head review, isolated native DEMO/owner/STOP/Algo-off
qualification and a separately reviewed customer delivery remain required.
