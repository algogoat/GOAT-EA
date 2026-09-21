# Secure agent-driven onboarding

Status: agreed product requirement, September 21, 2026; implementation pending.
Owner: GOAT EA, portal and desktop/controller integration.
Tracking ID: SETUP-001.

## Required customer experience

The user signs into GOAT once, reviews the accounts, target machine and requested
setup permissions, and authorizes the experiment. Their agent then discovers or
installs terminals, links the selected accounts within the existing entitlement,
completes pairing, loads the selected portfolios and verifies readiness. The user
sees the same progress and settings in the UI that the agent sees through the API.

Do not require customers to shuttle between six terminals, copy tokens, interpret
HTTP errors, repeatedly approve the same scope, or understand EA build admission.
Do not equate simpler setup with weaker authentication. Passwords, MFA and genuine
new authorization boundaries may require the user; routine orchestration should not.
Trading launch is a distinct, explicit authorization, not a side effect of setup.

## Observed gaps motivating this work

- Broker login, GOAT portal login, account entitlement, device pairing and trading
  readiness are separate states that currently look like one generic failure.
- Startup through a custom MT5 configuration did not provide the required durable
  profile workflow. Native persistent-profile startup has since been demonstrated.
- Native WebRequest permission failed before server admission could be checked.
  Once permission worked, the experimental build correctly received HTTP 409.
- The six demo accounts were not linked in the portal. An authenticated agent has
  now linked them within existing capacity; linking is not proof of EA pairing.
- The published EA can pair, but the setup controller cannot yet expose a complete
  pairing/deployment workflow. Existing RPC only supports status and inert shutdown.
- Switching to a genuine published EA for onboarding is a current workaround,
  not the intended customer flow or admission of an experimental build.

## Security contract

1. Use the real user's authenticated session or an explicitly issued delegated
   capability. Never substitute administrator impersonation, a shared privileged
   token, scraped browser credentials or a fabricated admitted build identity.
2. Bind a setup authorization to the user, registered host, exact selected account
   set, approved artifact identity, allowed operations and expiry. Changes to that
   scope require new authorization; ordinary retries inside it do not.
3. Enforce entitlement, account membership and capacity on the server. The client
   cannot grant itself slots or approve an unknown build. Revocation must be checked
   on subsequent protected operations. Shared user credentials are not account grants.
4. The user-facing review must identify the actual requester, machine and accounts.
   Prevent account substitution, pairing-session swapping and confused-deputy use.
   Use short-lived, one-use pairing challenges and server-validated confirmation.
5. Keep passwords and bearer tokens out of model context, URLs, process arguments,
   logs, receipts and repository files. Store secrets in the OS-protected vault;
   expose opaque handles and redacted status through agent tools. Never request a
   password in chat. Persist only the minimum credential material needed.
6. Prefer local authenticated IPC or outbound authenticated host connections.
   Do not expose an unauthenticated public controller. Define host enrollment,
   credential rotation, expiration and revocation before remote deployment.
7. Retain native permission boundaries. Where MT5 requires a manual permission,
   explain the exact terminal and reason once, then verify a real request. Do not
   bypass the allowlist with an alternate transport merely to suppress the prompt.
8. Setup commands must not enable trading, place orders or close positions.
   Portfolio attachment requires verified disabled trading and appropriate account
   state. Live-account maintenance needs a separate contract preserving management.
9. An internal build needs an explicit reviewed admission route tied to its artifact
   and intended scope. Never silently open experimental activation to every customer
   or replace a public release just to unblock an experiment.

## Implementation sequence and deliverables

### SETUP-001A — One state model and actionable preflight

Expose host, broker connection, loaded artifact, GOAT session, entitlement/capacity,
native network access, pairing, portfolio attachment, policy acknowledgements and
trading state separately. Each observation includes identity, time and freshness.
Distinguish missing, failed, blocked and unknown; do not present stale success as ready.
UI and agent consume the same versioned status contract and recovery instructions.

### SETUP-001B — Secure delegated pairing

Implement a reviewed setup session API connecting the signed-in portal and enrolled
host. The agent can obtain the host's public pairing challenge, inspect the exact
request and complete authorized steps without reading the private credential.
Complete any required user confirmation in one review of the intended scope.
The host receives and stores credentials through the authenticated protocol.
Document threat model, trust boundaries and negative tests before shipping.
No permanent browser-session extraction or global service credential is acceptable.

### SETUP-001C — Complete shared control surface

Refactor existing dashboard handlers into shared commands for portfolio import,
AI mode/protocol/threshold, exposure policy, bounded child attachment and status.
Return structured failures instead of modal-only errors. Keep one authoritative
state writer; UI and agent must not maintain competing copies of the queue/settings.
Bind deployment to immutable source/effective SET hashes and account assignments.
Persist intent before side effects and verify actual child identity, fresh heartbeat
and policy acknowledgement afterward. A dispatch receipt is not completion.

### SETUP-001D — Recovery and customer packaging

Use idempotent request IDs, retained receipts, bounded retries and a single owner
per operation. On restart, reconcile actual state before resuming; never recreate
charts, repeat activation or reissue a trade-affecting action blindly. Preserve
user changes and report scope conflicts. Provide a resumable installer/controller,
documented API, least-privilege agent skill and a visible progress page.

### SETUP-001E — Readiness and explicit launch

Verify every account's access, all expected portfolio members, effective policies,
AI feed freshness where required, resource capacity and restart restoration.
Present a final manifest of accounts, portfolios, sizing and policy variants for
launch. Setup completion must leave trading OFF. Monitoring must distinguish
operational health from strategy performance and must not imply profitability.

## Acceptance checks

- A fresh user and agent can complete the documented setup after one sign-in and
  scoped authorization, with only unavoidable native/MFA interactions explained.
- All six demo accounts can be prepared without repeated manual pairing or token
  handling; an existing unrelated account remains unchanged.
- Wrong user, host, account, artifact, expired challenge, replay, revoked access,
  insufficient capacity and unapproved scope expansion are rejected and explained.
- Interrupted sign-in, network loss, rate limiting, process crash and partial
  deployment recover without duplicate requests, charts or overwritten evidence.
- Logs, API responses, error paths and agent transcripts contain no credentials.
- UI and API report identical effective configuration and fresh per-child evidence.
- Restart preserves authorized settings and portfolio identities. Installed-file
  hashes alone are never reported as proof of the loaded or connected EA.
- Tests prove setup cannot enable trading; launch requires its separate authorization.
- Required source review, native integration tests and protected release checks pass
  before customer availability. Historical workarounds are not acceptance evidence.

## Current implementation boundary

See [AGENT-SETUP.md](AGENT-SETUP.md) for implemented capabilities. This plan grants
no new runtime permissions and does not claim the experiment is activated or deployed.
The current setup skill must remain honest about its limited command surface until
the implementation, tests and native evidence above exist.
