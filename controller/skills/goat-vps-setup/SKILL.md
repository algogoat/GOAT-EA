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

A VPS ("virtual private server") is a Windows computer rented in a datacentre that
stays on all the time; the user reaches it over the internet with Remote Desktop.
Explain any term you use: a **vCPU** is one processor core of that rented computer;
**dedicated** cores are reserved for the user, while **shared** or **burst** cores are
shared with other customers and slow down when they are busy; **NVMe** is a fast
kind of disk.

## 1. Ask about their situation

Ask, one at a time, and say why you ask:

1. Which computers do they have: a Windows PC (ask for CPU, cores, RAM and free
   disk, or run `Studio @('resource-profile')` there if GOAT is installed), a Mac,
   or only a phone or tablet?
2. Do they want to **research** (optimize strategies) or **only trade** strategies
   they already have?
3. Can that Windows PC stay on, awake and online 24/7? Most cannot.
4. Which broker and demo server do they use? Where that broker's trade servers are
   decides the best VPS location. **Establish it before they buy**, from evidence:
   the location the broker publishes for its MT5 servers, or the access point and
   ping an existing MT5 already shows in its journal. A broker's home country does
   not tell you where its servers are. If the location stays unknown, say so, and
   suggest a plan they can change cheaply if the ping turns out high (hourly
   billing, a free region move or a refund window), so a wrong guess costs little.

## 2. Recommend a tier

| Tier | Size | Who it is for |
| --- | --- | --- |
| **Trade** | 2 vCPU, 4 GB RAM, 80 GB disk | Runs MT5 + GOAT + the agent 24/7 to trade demo portfolios. No research. |
| **Lab** | 4-6 **dedicated** vCPU, 16 GB RAM, 200 GB NVMe | Mac or no PC: the whole lab, moderate research. |
| **Pro Lab** | 8-16 **dedicated** vCPU, 32 GB RAM, 400 GB+ NVMe | Mac or no PC, heavy or continuous research. |

- **Windows PC that can do the research:** keep optimizing on the PC (they already
  own it, so research there costs nothing extra) and put trading on a **Trade** VPS,
  so a reboot, sleep or update on the PC never stops demo trading.
- **Mac, phone only, or a PC too small or not always on:** run the whole lab on a
  **Lab** VPS; **Pro Lab** when they want many batches a week. Research speed comes
  from cores: MT5 tests on every core it has, so shared cores slow every batch.
  Recommend dedicated cores for Lab and Pro Lab.
- **Only trading, and the PC is always on:** a VPS is optional. Say so honestly.

Disk matters: price history and test files grow quickly and GOAT warns below
30 GB free (a start is refused below 5 GiB). Never recommend less than the tier's disk.

## 3. Provider and signup link (with disclosure, every time)

Read the provider list from GOAT's partner configuration: `<GOAT_VPS_REFERRAL_LINKS>`.
It names, per tier, only providers that passed GOAT's own VPS benchmark, with their
signup links. If it is empty or still the placeholder, say: "GOAT has not finished
benchmarking VPS providers yet, so I have no recommended provider or link." Then
give the tier specs only, so the user can compare any provider themselves. Never
invent a provider ranking, price, discount or link, and make no claim about the
price they will pay beyond what the provider's own page shows.

Whenever you show a link from that list, say this word for word, before the link:

> GOAT may earn a commission if you sign up through this link. Our ranking comes from our own benchmark, not commission.

Then the user signs up and pays on the provider's site themselves. Ask them to
choose: Windows Server (2022 or newer) with the licence included, the location from
step 1, the tier's size, and snapshots or backups if offered. They send you only
the VPS IP address and the Windows user name, never the password.

## 4. First login and Windows

1. The user connects with Remote Desktop: Windows **Remote Desktop Connection**
   (`mstsc`), on a Mac **Windows App** (formerly Microsoft Remote Desktop), on a
   phone the Windows App mobile app. They type the password themselves.
2. Remote Desktop is usually reachable from the whole internet, so the Windows
   password must be **long, strong and used nowhere else**. If the provider set the
   first password, the user changes it now (the user, not you), and stores it in
   their password manager.
3. **Windows Update:** the user installs all updates and restarts once now, before
   MT5 runs.
4. **Update restarts:** Windows' "active hours" cover at most 18 hours a day, so
   they cannot protect a 24/7 trading week. Agree a maintenance policy instead and
   apply it with the user's yes: on Windows Server, `sconfig` > Windows Update
   settings > **Download only** (updates download, nothing installs or restarts by
   itself). Then the user installs updates and restarts in a weekly window when
   their markets are closed (for FX, the weekend). Tell them what remains: a
   download-only server still needs that weekly install, a provider's host
   maintenance can restart it, and step 6 brings MT5 and GOAT back after any
   restart. Remind them of the weekly window in each session's handoff.
5. Tell them how to leave the VPS: close the Remote Desktop window (this
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
   start page **from the GOAT on the VPS**; the user turns on Algo Trading themselves.

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
  and the trade-off: anyone who reaches the VPS console gets a signed-in session,
  which is one more reason for the long, unique password from step 4. Without it,
  after every reboot the user must connect once with Remote Desktop before MT5
  starts again.
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
   a warning; below 5 GiB research cannot start. Compare with the plan **with
   tolerance**: Windows shows a little less RAM than the plan (about 15.9 GB on a
   16 GB plan) and a plan's vCPUs appear as **logical** cores (physical cores can
   read lower). Treat it as matching when logical cores are at least the plan's
   vCPUs and RAM is within 10 % of the plan. Only outside that, say: "This looks
   smaller than the plan you chose; please check it with the provider." Never say
   they received less than they paid for.
2. The broker ping: the newest MT5 journal (`<terminal_data_root>\logs\<yyyymmdd>.log`)
   records each sign-in with its access point and ping. Under about 20 ms is good
   for a VPS in the broker's city; above 50 ms, suggest a closer location.
3. `powercfg /query` shows no standby or hibernate timeout, the startup entries
   from step 6 exist, and Windows Update is on the agreed policy from step 4.
4. `Studio @('onboarding-status')` reaches `local_monitor_ready`, and
   `Desktop 'onboarding.status' @{receiptPath=$receipt}` reports `ready`.
5. Lab and Pro Lab: run the first one-template, one-symbol pilot of the start page
   (steps 13-20) with the user's yes, then `Studio @('benchmark-report','--batch-id',...)`.
   Its measured time per member, not the CPU name, sets expectations for bigger batches.

Write the results into the session's `handoff.md`, with the VPS tier, location and
provider (no IP address, no user name, no password).

## 9. When a strategy goes live: connect the account (demo accounts only)

**Demo accounts only.** Never connect, link or advise a real-money account; if
anything shows real money, stop and tell the user.

Connect the account **from the GOAT that runs on the same machine as that MT5**:
for a VPS, the GOAT installed on the VPS (step 5), driven by the agent on the VPS
(step 7). Only there can GOAT confirm with the broker that the account is demo.

1. A demo GOAT deployed with `deploy.demo` (start page step 21) is already in
   **GOAT > Live**, verified demo and linked to its backtest. Nothing more to do.
2. Any other demo terminal on that machine running a GOAT portfolio:
   `cockpit.discoverAccounts`, then `cockpit.connectAccount @{candidateId=...}` for
   that terminal; the user clicks **Connect** in the app; wait for `live.connected`
   with `events.wait`. Then the user presses **Check account type** in Live while MT5
   runs (their click, never yours; you may point at it with
   `Desktop 'ui.highlight' @{target='live.account.checkType'}`). Only after it reads **demo**,
   `cockpit.linkPortfolio @{accountKey=...}` links it to the saved backtest by the
   SET files' hashes. If it reads real money, stop: GOAT never links, reports or
   advises real-money accounts.

Not supported: connecting an account from a **different** computer (for example
from the user's PC to the MT5 on their VPS). GOAT cannot verify from there that
the account is demo, so it is shown as display-only with equity only (no trades),
`cockpit.linkPortfolio` refuses it, and it is not compared with its backtest. Do
not use that route for this step; connect it on the VPS itself.

Explain why it matters: live demo results show whether a strategy holds up against
its backtest, and they count as evidence for it. It is **private by default**;
sharing with the GOAT library is opt-in, per strategy, in **Settings > Account >
Research sharing**, and only the user switches it on.
