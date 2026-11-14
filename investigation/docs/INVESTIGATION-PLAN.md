# Experiment plan and acceptance criteria

## Phase 0 — execution check
Confirm whether Codex has local Windows terminal access. Cloud container access is **not** enough to inspect Windows Resource Monitor or live Valorant traffic. Ask for the smallest necessary approval only if a proposed method requires it. Do not assume user is at keyboard during gameplay.

## Phase 1 — read-only snapshot
Record `Get-Date` with timezone; `Get-NetAdapter`, `Get-NetIPInterface`, `Get-NetRoute` / `route print`, `Get-NetIPConfiguration`, `netsh wlan show interfaces` if using Wi-Fi, and process/interface counters with low overhead. Capture useful technical detail. The repository is private: curated detailed logs and relevant IPs may be committed, but exclude secrets and unrelated personal data. Note any split tunneling or unexpected routes from Radmin VPN; don't disable it.

## Phase 2 — silent simultaneous sampling
Use the continuous ordinary-user monitor, with PowerShell launch/stop wrappers and a dependency-free Python core. Probe router, near-hop, public destination and two RETN targets every two seconds; no default time limit. Rotate append-only JSONL without restarting; keep a global sequence, UTC/local millisecond timestamps and explicit quality/gap events. Read a fixed committed watermark for interim analysis while collection continues. Manual RegisterHotKey markers are authorized; no input hooks, screen capture or elevation. ICMP to routers may be rate limited: compare with downstream observations, not intermediate values in isolation. See COLLECTOR-RUNBOOK.md for retention, startup verification and explicit finalization.

## Phase 3 — in-game correlation
User stays in Range for an initial sample. Ask user to note timestamps of game-reported RTT changes/loss; optional screenshots. Under consent, perform one unrated match on Stockholm and record same metrics. Compare destination and conditions, not just mean values. If the user volunteers ranked, use observation only.

## Phase 4 — discriminate causes
- Router spikes correlated with game spikes -> investigate local interface/Wi-Fi under controlled conditions.
- Router stable but near-hop spikes -> investigate ISP access/aggregation.
- Near-hop stable but several downstream destinations degrade together -> consider ISP egress or transit.
- Only a verified Riot game destination degrades -> consider destination-specific peering/route/Riot; corroborate with evidence.
- Heavy uploads/downloads correlated with spikes -> check bufferbloat; only run load tests outside live matches with consent.
- All diagnostic pings normal but game packet loss persists -> investigate game UDP-specific routing, rate limiting, server/anti-cheat logging artifacts and alternative path measurement.

## Artifact structure
`scripts/` for conservative, reviewable PowerShell collectors; `docs/` for methodology; `reports/` for fact-vs-hypothesis conclusions. Keep `.gitignore` for high-volume raw logs and captures by default; intentionally curated, reviewed diagnostic samples and reports may be committed. Prefer no third-party utilities or packet capture unless discussed and approved.

## Exit criteria
- At least two reproducible sessions with synchronized observations.
- Clear explanation of confidence and unresolved uncertainty.
- A support-ready Meganet report naming dates, symptoms, nodes, protocols, comparative measurements, and a request to investigate destination-specific routing/packet loss (without premature accusations).
