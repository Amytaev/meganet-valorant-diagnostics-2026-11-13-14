# RRT-дополнение для Meganet и Riot, 15 ноября 2026

Это отдельный проверенный производный пакет. Полные исходные RRT ZIP и журналы с авторизацией не включены.

- [Полный отчёт](investigation/reports/RIOT-RRT-LOG-ANALYSIS.md) и [самодостаточный HTML с двумя встроенными графиками](investigation/reports/RIOT-RRT-LOG-ANALYSIS.html).
- [Meganet](investigation/reports/MEGANET-RRT-BRIEF.html) и [Riot Support](investigation/reports/RIOT-SUPPORT-RRT-BRIEF.html): черновики, не отправлены.
- [Исходные числовые производные, инвентаризация и корреляции](investigation/reports/evidence/riot-rrt-2026-11-15/).
- [Проверка публичного состава](RRT-PUBLIC-VALIDATION.json), [SHA-256 состава этого дополнения](RRT-SUPPLEMENT-SHA256SUMS.txt).

1286 типизированных событий, восемь Average Ping 328,12–383,31 мс, 26 input replication stop/overflow при спокойных ICMP-контролях. Конкретная причина пока не доказана. Оба VAL ZIP исходного набора идентичны, а логи поздних матчей 15 ноября отсутствуют в RRT; прежние endpoint-выдержки помечены отдельным источником.

Ссылки на более ранние данные в Markdown предполагают полный репозиторий. HTML использует прямые ссылки GitHub и встроенные графики. [Полный публичный набор с предыдущими ping/tracert, CSV/JSONL и графиками](https://github.com/Amytaev/meganet-valorant-diagnostics-2026-11-13-14). Старые ZIP остаются историческими срезами; это дополнение их не заменяет. Для разбора RRT на другом ПК нужны оригиналы владельца только через приватный канал; повторный анализ исходников не требует новой игры или сетевых тестов.
