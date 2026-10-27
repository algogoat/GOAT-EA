# Customer agent skill audit — 2026-09-28

The owner requested that useful internal workflows become part of the product's
agent experience. The result is `controller/CUSTOMER-SKILLS.md` and six portable
skills discoverable through the installed controller. Existing suite packaging
recursively includes controller Markdown/Python/JSON files and hashes them in
the bundle manifest; no separate private plugin is needed.

| Internal source reviewed | Product outcome |
| --- | --- |
| mt5-goat-optimize | OHLC-standard planning, measured machine/workload advice, native progress and report verification; no historical machine paths or removed restart-runner API |
| goat-opt-file-create | Typed installed validate-set/build-set workflow; encoding/layout, semantic-axis checks, unique candidate identity and provenance |
| goat-seed-farming | Dedicated bounded seed research; actual matrix count, canonical comparisons, preserved failures and explicit native qualification limits |
| goat-portfolio-build | Installed authenticated desktop capabilities, frozen pools, measured jobs, evidence-aware comparison and verified exports |
| goat-vps-setup | Supported diagnosis/repair concepts only; its internal-only manifests, credential launcher and fixed-host recipes are excluded |
| goat-vps-trade-audit | Read-only evidence/freshness audit narrowed to the customer's authorized accounts; no inherited developer-fleet scope |
| release/upload, compiler, version-cut, folder-diff skills | Remain maintainer-only; customer agents can report or propose a patch but cannot manufacture an admitted release |

Quality corrections: seed example now uses current V1.49 and Model=1, matching the
optimization standard; native-seed qualification remains explicitly limited.
The local optimization reference's removed `studio_restart_runner` invocation is
marked historical. Instructions separate declared capabilities, source tests,
native qualification and delivered customer releases.

Validation: installed-style discovery returns six paths/descriptions/hashes;
portable-skill tests check metadata, local links and absence of private developer
paths/account identities. Existing controller API tests pass. Publication and
native qualification of unrelated capabilities are not implied by these docs.

Telemetry architecture is deferred at the owner's request. This change neither
changes EA telemetry nor restarts/stops publication tasks.
