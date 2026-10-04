---
name: goat-vps-setup
description: Help a user choose and set up an always-on Windows VPS for GOAT (trading only, or the whole research lab for Mac and phone users), with disclosed partner links, user-only signup and payment, MT5 demo, pairing, reboot-safe autostart, a remote agent and a quick health check.
---

Read [the start page](../../AGENT-START-HERE.md) and [the rules](../../GOAT-OPERATING-MODEL.md)
first: on the VPS you follow the same golden path as on a PC. This skill adds the
parts before and around it. Talk in plain words, one question at a time. Demo
accounts only. You never spend money, never sign up for anything, never type or
ask for a password, card number or one-time code, and never accept terms for the
user. Signup, payment, every password and every licence acceptance are the user's.

## 1. Ask about their situation

Ask, one at a time, and say why you ask:

1. Which computers do they have: a Windows PC (ask for CPU, cores, RAM and free
   disk, or run `Studio @('resource-profile')` there if GOAT is installed), a Mac,
   or only a phone or tablet?
2. Do they want to **research** (optimize strategies) or **only trade** strategies
   they already have?
3. Can that Windows PC stay on, awake and online 24/7? Most cannot.
4. Which broker and demo server do they use? Its trade servers' location decides the
   best VPS location (London or New York for most FX brokers). Use the location the
   broker publishes; if it publishes none, say it is unknown and choose London for
   European brokers or New York for US ones, then check the ping in step 7.

## 2. Recommend a tier

| Tier | Size | Who it is for |
| --- | --- | --- |
| **Trade** | 2 vCPU, 4 GB RAM, 80 GB disk | Runs MT5 + GOAT + the agent 24/7 to trade demo portfolios. No research. |
| **Lab** | 4-6 **dedicated** vCPU, 16 GB RAM, 200 GB NVMe | Mac or no PC: the whole lab, moderate research. |
| **Pro Lab** | 8-16 **dedicated** vCPU, 32 GB RAM, 400 GB+ NVMe | Mac or no PC, heavy or continuous research. |

- **Windows PC that can do the research:** keep optimizing on the PC (it is usually
  far faster per dollar) and put trading on a **Trade** VPS, so a reboot, sleep or
  update on the PC never stops live demo trading.
- **Mac, phone only, or a PC too small or not always on:** run the whole lab on a
  **Lab** VPS; **Pro Lab** when they want many batches a week. Research speed comes
  from cores: MT5 runs one tester agent per core, so shared ("burst") vCPUs and
  oversold hosts slow every batch. Recommend dedicated cores for Lab and Pro Lab.
- **Only trading, and the PC is always on:** a VPS is optional. Say so honestly.

Disk matters: tick history and tester caches grow quickly and GOAT warns below
30 GB free (a start is refused below 5 GiB). Never recommend less than the tier's disk.

## 3. Provider and signup link (with disclosure, every time)

Read the provider list from GOAT's partner configuration: `<GOAT_VPS_REFERRAL_LINKS>`.
It names, per tier, only providers that passed GOAT's own VPS benchmark, with their
signup links. If it is empty or still the placeholder, say: "GOAT has not finished
benchmarking VPS providers yet, so I have no recommended provider or link." Then
give the tier specs only, so the user can compare any provider themselves. Never
invent a provider ranking, price or link.

Whenever you show a link from that list, say this sentence word for word, before
the link:

> GOAT may earn a commission if you sign up through this link; your price is the same or lower. Our ranking comes from our own benchmark, not commission.

Then the user signs up and pays on the provider's site themselves. Ask them to
choose: Windows Server (2022 or newer) with the licence included, the location from
step 1, the tier's size, and snapshots or backups if offered. They send you only
the VPS IP address and the Windows user name, never the password.

## 4. First login and Windows

1. The user connects with Remote Desktop: Windows **Remote Desktop Connection**
   (`mstsc`), on a Mac **Windows App** (formerly Microsoft Remote Desktop), on a
   phone the Windows App mobile app. They type the password themselves.
2. Change the provider's initial password if the provider set it (the user, not you).
3. **Windows Update:** the user opens Settings > Windows Update, installs updates
   and restarts once now, before MT5 runs, then sets active hours to their trading
   week if their Windows offers it.
4. Tell them how to leave the VPS: close the Remote Desktop window (this
   **disconnects** and keeps MT5 running). Never **Sign out** or **Shut down**:
   signing out closes MT5 and stops trading.

## 5. GOAT, MT5, demo and pairing

1. The user downloads and installs GOAT desktop on the VPS and signs in with their
   own GOAT account.
2. The user installs their broker's MT5, signs in to the **demo** in MT5 (File >
   Login to Trade Account, ticking Save password) and keeps Algo Trading off.
3. From here follow [the start page](../../AGENT-START-HERE.md) steps 0-12 exactly
   as on a PC: install into this terminal, bootstrap, monitor chart, permissions,
   pairing (the user approves the connection code or clicks **Connect ••1234 to my
   agent**) and GIVE TO AGENT. Nothing changes because it is a VPS.
4. Trade tier: no research. Deploy the user's saved portfolio with step 21 of the
   start page; the user turns on Algo Trading themselves.

## 6. Always on: no sleep, restart after reboot

Explain each change and get the user's yes before running it:

- Power: `powercfg /change standby-timeout-ac 0`, `powercfg /change hibernate-timeout-ac 0`
  and `powercfg /change monitor-timeout-ac 0`. Server editions usually never sleep
  already; check with `powercfg /query` and report what you saw.
- Start MT5 and GOAT after a sign-in: add shortcuts to `terminal64.exe` (the exact
  path from `suite.discover`) and to GOAT desktop in the user's Startup folder
  (`shell:startup`), or a Task Scheduler task "At log on of <user>". MT5 needs a
  signed-in desktop session to run.
- Sign in automatically after a reboot: Windows needs automatic sign-in for that
  (for example Microsoft's Sysinternals **Autologon**). It stores the Windows
  password, so **the user sets it up and types the password**; you only explain it
  and the trade-off (anyone with console access to the VPS gets a signed-in session).
  Without it, after every reboot the user must connect once with Remote Desktop
  before MT5 starts again.
- Test it with the user's yes: one restart, then check MT5 reconnects to the demo,
  the GOAT chart is loaded, Algo Trading is in the state the user left it, and GOAT
  desktop is signed in. Report what you observed.

## 7. Run the agent on the VPS

Install the user's agent (for example Claude Code or Codex) on the VPS so it runs
next to GOAT and MT5, signed in to the user's own account by the user. Then show
them how to reach it from their Mac or phone with that agent's own remote-session
feature (for Claude Code: Remote Control started from the session on the VPS), so
they never need Remote Desktop for routine work. Keep using PowerShell only.

## 8. Quick health check

Run these read-only checks and report each with its number and a pass or a plain fix:

1. `Studio @('resource-profile')`: CPU model, physical and logical cores, total and
   available RAM, and free disk on every drive it lists. Free disk below 30 GB is
   a warning; below 5 GiB research cannot start. Cores and RAM below the chosen tier
   mean the user received a smaller plan than they paid for: tell them.
2. The broker ping: the newest MT5 journal (`<terminal_data_root>\logs\<yyyymmdd>.log`)
   records each sign-in with its access point and ping. Under about 20 ms is good
   for a VPS in the broker's city; above 50 ms, suggest a closer location.
3. `powercfg /query` shows no standby or hibernate timeout, and the startup entries
   from step 6 exist.
4. `Studio @('onboarding-status')` reaches `local_monitor_ready`, and
   `Desktop 'onboarding.status' @{receiptPath=$receipt}` reports `ready`.
5. Lab and Pro Lab: run the first one-template, one-symbol pilot of the start page
   (steps 13-20) with the user's yes, then `Studio @('benchmark-report','--batch-id',...)`.
   Its measured time per member, not the CPU name, sets expectations for bigger batches.

Write the results into the session's `handoff.md`, with the VPS tier, location and
provider (no IP address, no user name, no password).

## 9. When a strategy goes live: connect the account

When a portfolio starts trading on a demo account (on the VPS or anywhere), ask the
user to connect that account in **GOAT > Live** if it is not there yet (a demo GOAT
deployed with `deploy.demo` appears there by itself, already linked). Use
`cockpit.discoverAccounts`, then `cockpit.connectAccount` (an EA on another machine:
`{source:"ea-reporting", login, server, host:"vps"}`); the user confirms once in the
app; wait for `live.connected`, then `cockpit.linkPortfolio` so Live compares it
with the backtest it came from. Explain why: live demo results are the strongest
evidence a strategy can earn short of real money, and the agent can then check
whether it is holding up. It is **private by default**; sharing with the GOAT
library is opt-in, per strategy, in **Settings > Account > Research sharing**, and
only the user switches it on. Never connect a real-money account for the user.
