B51 (`V1.49-BETA17-51`) is B50-alpha plus B50-beta-1 (goatai#2750). **Research only, the D1 hunt build:** tester
use only, no admission row, no live arm, no demo chart. Each item had its own reviewed PR into `claude-mac/b50-alpha`:
#286 (beta-1a, the random-direction benchmark), #287 (beta-1b, the single's break-even and trailing), #289 (the
single partial close and the demo gate) and #291 (controller only: one-trade `RiskperSeq` singles).

**Why its own identity.** Until this commit the tree still named B50-alpha's build (`V1.49-BETA17-50`), which
`PINNED_BUILDS` gives to B50-alpha's binary `8364a371`. Hunt evidence made by this binary under that name could not be
told apart from B50-alpha's (goatai#2750 6702767671; Claude-Mac approved this change in 6702775712).

**Build**
- `GOAT_BUILD_ID` is `V1.49-BETA17-51`, marker `B51`. Against `41e1fb9f` (GOAT-EA#289) the compile closure differs in those
  two defines only; `studio_equivalence` normalizes exactly those two, so the trading source is #289's.
- **Compiled once** with the pinned portable MetaEditor (sha256 `cf2750bd…`), Idle, outside every terminal folder, B47's
  include root copied hash-equal: `Result: 0 errors, 0 warnings, 32134 ms elapsed, cpu='X64 Regular'`, 42-file closure.
- `GOAT V1.49.ex5`: sha256 **`58623845018e37c917c32bc5599c1ff16ae14575777a49b337ed8ba44be3d95a`**, 2,568,360 bytes. MetaEditor output is not
  byte-reproducible, so this is the one binary to use.
- Entrypoint `GOAT V1.49.mq5` sha256 `2694222c…` (pinned in `controller/contracts/v149/dependencies.json`),
  input header `8431ae6c…` (B50-alpha's 127 inputs plus B51's 9).
- `controller/studio_installed_build.py` pins this binary as `V1.49-BETA17-51`.

**Not done.** No native qualification (one tester partial-close check only), no externals manifest, no admission row.
The root `GOAT V1.49.ex5` is unchanged.
