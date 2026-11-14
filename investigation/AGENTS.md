# Public mirror context

This directory is a public sanitized derivative. Never publish personal network identifiers, credentials, raw private game logs or subscriber WAN addresses here. Keep private originals and active collection in amir-workspace. Preserve numerical samples, dates, target/route IPs and game ports. The historical private-repository permission below applies to the private source only; it is not permission to publish personal data. Re-run a privacy review and checksum validation before publishing new data.

# Codex agent instructions — Valorant network investigation

## Mission
Perform a rigorous, falsifiable, minimally intrusive network diagnosis on a **Windows 11** gaming PC used for Riot Valorant. Current symptoms: reported Stockholm ping rising from ~90–100 ms to 120 and up to 130–160 ms; Valorant-reported packet loss. Refer to `docs/BASELINE-2026-11-13.md`. State evidence versus hypothesis explicitly.

## Non-negotiable safety / quiet-mode constraints
1. No GUI focus stealing, key presses, mouse clicks, overlays, window activation, screen capture or clipboard edits while the user is gaming. Favor low-priority headless PowerShell and built-in OS counters.
2. No settings changes, netsh resets, adapter toggles, DNS/route changes, VPN connection changes, router reboots, game/service restart, firewall/Defender/Vanguard changes, driver changes, installations, scheduled persistent tasks or elevated actions without separate explicit approval.
3. No injecting/hooking Valorant, reading process memory, patching Riot/Vanguard, traffic manipulation, exploit attempts or invasive interception. Passive packet capture ONLY after discussing anti-cheat/privacy risks and receiving specific permission. Do not assume administrator permissions.
4. No saturation or aggressive probing. The user's explicit architecture instruction of 14 November 2026 supersedes the former 10–15 minute session default: run one continuous primary monitor until an explicit stop, with log rotation inside that process. Default probes every two seconds, at most five targets. Bounded runs are only for explicitly requested tests. Do not stop the live monitor merely because a Codex turn ends. Avoid simultaneous pathping storms or speed tests during matches.
5. This is a **private personal repository**. You MAY commit detailed technical telemetry, timestamps, network addresses, traceroutes, and pertinent non-secret logs to this dedicated branch to preserve evidence. Keep large raw captures local/ignored by default, and inspect any log before a commit for credentials, cookies, access tokens, Riot session tokens, secrets and unrelated personal data. Never commit secrets; never transmit logs to third-party services without separate user authorization. Git commits of relevant reviewed diagnostic data to this user-approved branch are permitted, but do not silently upload bulk raw captures.
6. Check whether a local execution channel truly exists. If cloud-only, prepare scripts and instructions rather than pretending to monitor the local live game. Do not run diagnostics against unrelated hosts from a cloud environment and call that the user's route.
7. Never enter ranked matches on behalf of the user. Do not request ranked testing when Range or unrated suffices. User decides gameplay.
8. Record start/end times, timezone, target, type (ICMP/TCP/UDP), packet counts and configuration. Separate observed facts, interpretation and confidence.
9. User-authorized manual hotkeys may use RegisterHotKey and an invisible non-activating window; never install input hooks or record general keystrokes. OS session-end notifications must not veto shutdown. The collector may be created once through the ordinary-user WMI process broker to outlive Codex; do not install a service, scheduled task or autostart entry.

## Investigative sequence
A. Inventory (read-only): OS build, Wi-Fi/Ethernet interface, RSSI/link rate/band/channel when exposed, adapter driver, network route table & interface metrics, default gateway, active VPN/tunnel adapters (including Radmin), proxy and relevant background network activity. Check for competing routes or traffic without altering them.
B. Establish light parallel time-series: router `192.168.123.1`, ISP near-hop `89.38.164.205`, independent public destination `1.1.1.1`, and where responsive one or two RETN interfaces from the baseline. Do not attribute intermediate-node ICMP anomalies to forwarded data unless corroborated downstream.
C. In-game: user enables Network RTT (average/max), total/inbound/outbound packet loss and jitter. Have user record timestamps/screenshots of spikes or derive values only from supported game logs. Do NOT confuse game UDP telemetry with Windows Resource Monitor TCP 'latency'.
D. If possible, isolate real active game UDP destination through OS-supported read-only observability. Process-scoped TCP addresses, Cloudflare endpoints, or `185.40.64.1` are not confirmed game endpoints. Ensure any identification is evidence-based.
E. Compare Range versus one unrated match and, only if user volunteers, ranked. Range server location need not equal Stockholm match location. Repeat at low versus peak evening hours to test diurnal association.
F. Consider: local Wi-Fi retransmissions, interference, background utilization/bufferbloat, VPN or metric misrouting, ISP edge, international transit/peering, route asymmetry, game server and Riot service incidents. Distinguish baseline geography from variable spikes.
G. Assess causal strength with simultaneous correlated telemetry, not just unrelated one-off pings. Explain non-responding ICMP endpoints as filtered/unresponsive unless independently verified.
H. Generate `reports/INVESTIGATION-RESULTS.md` (no fake measurements), and `reports/ISP-SUPPORT-DRAFT.md` once evidence justifies it.

## Reporting standards
Provide a compact metrics table: timestamp, target, protocol, sample size, min/avg/max/p95 latency, loss %, in-game RTT/loss (if observed), context (Range/match), active interface. Call out mismatched target and sample bias. Propose the least disruptive next test. Never claim proof of Meganet/RETN/Riot fault without corroboration.
