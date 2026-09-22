# R6 inert-demo startup diagnostics

R5 account 1 stops producing startup evidence after 34 initialization starts,
25 successful license HTTP responses and 24 completed license checks. Five other
accounts passed their OFF restart checks. Neither a cache reset nor a UI-layout
reset resolved account 1. The cause is not yet established.

R6 adds flushed, per-chart last-stage files under the terminal-local
`MQL5/Files/GOAT/StartupTrace` directory. Tracing runs only during initialization,
on demo accounts, with terminal trading disabled. Successful initialization ends
tracing. Files contain UTC time, chart ID, symbol, operation mode and stage only.
They contain no credentials, response bodies or strategy inputs. Missing files
are unknown, not evidence of success. A trace identifies the last completed file
write; it does not prove that the immediately following call caused a stall.

This build uses `api-bearer-r6-diagnostic.token` within the existing protected
Common Files credentials directory. Both reader and atomic writer use that
namespace, including its `.pending` file. There is no fallback to the R5 token.
Other entrypoints retain the original default credential path. Authentication,
entitlements, strategy execution, sizing and exposure policies are unchanged.

Before native testing, retain the R5 admission unchanged and append a separately
reviewed R6 admission for the single diagnostic demo account with the original
expiry. Pair through the existing native/portal flow. Do not copy the R5 token,
overwrite its file, or mislabel the diagnostic binary as R5. Preserve profiles,
registrations, attempts and the original binary before a closed-terminal change.

R6 is diagnostic preparation, not evidence of a fixed startup or a live
experiment. The next gate is an inert native reproduction with all expected
chart stages, followed by a targeted correction and full restart qualification.
