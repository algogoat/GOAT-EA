# Ops machine queues: the hold reader

These are the Claude-PC Ops queue scripts that start research batches on the demo machines (T3, Banker), kept here so
they are reviewed and tested. They run from `G:\GOAT-Build-Artifacts\claude-pc-ops\queue\tools\` and from the cadence
packs' `run\` folders on the ops PC; this folder is the reviewed copy.

## The hold rule

A machine queue does not start a batch while a hold is in force on the coordination inbox:

- a hold exists only as a line of a Claude-Mac post that begins `HOLD:` and names the hunt;
- a later Claude-Mac line that begins `HOLD LIFTED:` lifts it;
- posts at or before the queue's own start id (`-InboxAfter`) are the queue's starting knowledge and are not read as holds;
- a read that is not clean (gh fails, returns nothing, or the inbox issue number is unreadable) refuses the start.

## What went wrong on 2026-11-12

Each script carried its own copy of the reader. Every copy asked for `comments?per_page=100&since=<14 h ago>` and read
that one page. GitHub returns the oldest comments first, so once the inbox had more than 100 comments in 14 hours, every
recent post was outside the page. A `HOLD: hunt` posted at 18:00:35Z was not seen at 18:02Z, and Banker's queue started
a Prove batch seven minutes after the hold (goatai#2750 6831947464). The tests of the old reader fed it short fixtures
that matched the rule; none fed it a full day's inbox.

## What is here

| File | What it is |
| --- | --- |
| `hold-reader.ps1` | The one reader. `Get-HoldReason -InboxAfter <id>` returns nothing (no hold) or a reason not to start. Reads every page (`gh api --paginate`), one comment per line. |
| `hold-reader.test.ps1` | 11 cases against a stand-in `gh` that prints what the real one prints. Includes a 300-comment day with the hold in the last ten, the same day through the old one-page read (which must miss it, so the test is known to tell the two apart), and a `HOLD LIFTED:` on a later page than its `HOLD:`. Exit code = failures. |
| `prove-chain.ps1`, `seed-chain.ps1` | The Prove and seed chains. `Held` now calls the reader. |
| `cadence-anchor.banker.ps1`, `cadence-anchor.t3.ps1` | The cadence walk-forward anchor step on Banker and on T3 (`cadence-anchor.ps1` in each pack). `Held` now calls the reader. |
| `safe-push.ps1` | Release's push guard. Its inbox read was also one page (of 6 h); it now reads every page. |

`ops-merge-ea-pr.ps1`, `merge-loop.ps1`, `inbox-watch.ps1` and `before-live-write.ps1` already read every page and are
unchanged. `ops-post.ps1` and `ops-safe-push.ps1` read one page starting at a named comment's time, so they miss only
when more than 100 comments follow that comment; they are not changed here.

## Known limit

A hold posted at or before a queue's `-InboxAfter` is not seen by that queue. So a queue must never be started with an
`-InboxAfter` later than a hold that is still in force. After a hold is lifted, restart with an id after the lift.

## Disk start floor (2026-11-13)

`disk-floor.ps1` refuses every seed, Prove batch and catch-up start while C: has less than 15 GB free, and when the free
space cannot be read. Every queue gets it through `hold-reader.ps1` (`Get-HoldReason` reads the floor first), and
`run-catchup.ps1` reads it before its first verb. `disk-floor-watch.ps1`, run every 10 minutes as a scheduled task, posts
one `[Watch]` line on the inbox when C: falls under 20 GB and re-arms only after it is back above 22 GB. Why: on
2026-11-13 C: reached 6.78 GB while two queues wrote, found by chance (goatai#2750 6845735751, 6845747846).

## Run the tests

```
powershell.exe -NoProfile -ExecutionPolicy Bypass -File docs\operations\queue\hold-reader.test.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File docs\operations\queue\disk-floor.test.ps1
```
