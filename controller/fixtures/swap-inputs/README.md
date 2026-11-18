# Swap-inputs fixtures (INV-SWAP-01)

Rows cut from three real tester captures for `controller/test_studio_swap_inputs.py`. Each file is the capture's
`deals.csv` header plus every row of its first 40 positions (by first appearance in file order). The kept lines are
byte for byte as the EA wrote them (CRLF), so `.gitattributes` marks this folder `-text`. Cutting kept each case's
verdict, and the verdict of the full capture is the same (checked against the research sweep `swap_free_sweep.py` on
2026-11-18).

| File | Source (catch-up id, member alias) | Rows kept / full | Verdict (fixture; full capture) |
|---|---|---|---|
| `swap-free-inputs.deals.csv` | `fri1009-live3`, `C98887f9bc0e04015_00009` (re-test capture) | 82 / 772 | `swap_free_inputs`: 15 of 15 held positions with zero swap; full: 135 of 135 |
| `swap-charged.deals.csv` | `w12q-t3-d-1113`, `C493ec3fac261495d_00031` (re-test capture) | 82 / 382 | `swap_charged`: 8 of 8 held positions charged, -7.59 in all; full: 51 of 51, -64.12 |
| `not-exercised.deals.csv` | `exp02-mig-banker-1113-v2`, `C71c285e0d2c94c81_00016` (build-migration re-test capture) | 80 / 380 | `not_exercised`: no position held over a rollover; full: none of 186 |

The first is a GBPJPY re-test (evidence end 2026-10-09) that the tester charged no swap at all, though it held 135
positions over a rollover. The second is a USDJPY re-test that was charged swap. The third is a WS30 run that closes
every position the day it opens.
