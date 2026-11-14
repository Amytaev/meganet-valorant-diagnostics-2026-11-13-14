# VALORANT × Meganet — network investigation

**Дополнение 15 ноября:** [RRT-анализ](reports/RIOT-RRT-LOG-ANALYSIS.md), числовые игровые события и контрольные окна, отдельные [Meganet](reports/MEGANET-RRT-BRIEF.md) / [Riot](reports/RIOT-SUPPORT-RRT-BRIEF.md) сводки. Исходники RRT и чувствительные поля не публикуются; конкретная причина не установлена.

**Private-source follow-up (public data is a frozen snapshot):** a new user-started match is being monitored continuously from 16:32:40 (+05:00), 14 November; run `20261114-163240-f28706ce`. The previous daytime run below is finalized. A separate [Meganet engineer package](reports/meganet-package-2026-11-14/README.md) contains completed finite ping/tracert results and Anycast/SDR limitations.

**Status:** first local investigation stage completed on 13–14 November 2026. Quiet collectors, reviewed evidence and reproducible analysis are available. An in-game 185/189 ms RTT episode is confirmed; root cause remains unverified. See [incident](reports/INCIDENT-2026-11-14.md), [collector runbook](docs/COLLECTOR-RUNBOOK.md), [tasks](TASKS.md) and [investigation results](reports/INVESTIGATION-RESULTS.md).

**Continuous architecture (14 November):** the launcher now starts one independent monitor until explicit stop. Logs rotate in place; analysis does not stop measurement. Use [COLLECTOR-RUNBOOK.md](docs/COLLECTOR-RUNBOOK.md) for hotkeys, status, retention and finalization. An active investigation must remain active when Codex finishes a reply.

**Latest stage finalized:** daytime ranked Stockholm observation ended on 14 November at 14:49:44 (+05:00). The continuous monitor is stopped; all 5988 records / 5745 probes were saved without gaps. See the [daytime report with graphs](reports/DAY-MATCH-RESULTS-2026-11-14.md). Game-reported 300–400 ms diverged from control RTT; recovery after a user restart coincided with a changed game-log connection address. Specific cause remains unproven. The [nighttime report](reports/INVESTIGATION-RESULTS.md) preserves the earlier stage.

## Objective
Identify and substantiate the cause(s) of increased or variable Valorant latency (90–160 ms), game-reported packet loss, and the difference between Beeline and Meganet from Almaty, Kazakhstan. Stockholm is the selected competitive server. Do not presume the ISP, Riot, transit provider, router or Wi-Fi is guilty.

## Working mode
The player may be training in the Range or playing an unrated/ranked match. Diagnosis must be **quiet**, low-overhead, read-only by default, and not interrupt input, game, connectivity or anti-cheat. Cloud/sandbox Codex cannot inspect the user's Windows system without a *locally connected, user-approved* execution environment. Do not claim measurements have been taken if local access is unavailable.

## Starting point for Codex
Read [AGENTS.md](AGENTS.md) for strict operating instructions, then [docs/BASELINE-2026-11-13.md](docs/BASELINE-2026-11-13.md) for measured facts, and [docs/INVESTIGATION-PLAN.md](docs/INVESTIGATION-PLAN.md) for experiment design.

## Deliverables
- Reproducible light-weight Windows measurement scripts with explicit start/stop, configurable intervals and CSV/JSONL timestamped logs (local-only storage).
- Comparison across Range / unrated match / ranked match (ranked only if user chooses), preferably same clock window and same Stockholm target where verified.
- Evidence-weighted diagnosis separating LAN/Wi-Fi, access/ISP, transit/peering, Riot endpoint and background load.
- Markdown report with tests, timestamps in Asia/Almaty, uncertainty, and ISP support ticket draft.
- The repository is intentionally **private** and dedicated to the user's own workspace. Detailed technical results, traceroutes, relevant IP addresses, and reviewed diagnostic logs may be committed to this investigation branch. Never commit credentials, cookies, access tokens, secrets, or unrelated personal content.

## Suggested local output
Use a folder outside the repository such as `%LOCALAPPDATA%\ValorantNetDiag\` for high-volume raw logs while capturing. Keep raw capture files ignored by default; commit detailed, intentionally selected datasets and technical reports to this private branch after checking for secrets. Privacy of the repository is not a reason to omit useful routing evidence.


Публичный экспорт находится в investigation/. Коллектор, о котором говорится в исторических заметках, работает только в прежней приватной рабочей папке. Срез текущей серии: reports/evidence/follow-up-2026-11-14-snapshot/snapshot.json; это незавершённый committed prefix без DONE. Сведения об обезличивании и целостности — в PUBLIC-EXPORT-VALIDATION.json и корневом PUBLICATION-NOTES.md.
