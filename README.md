# Meganet × Valorant / CS2 — диагностика 13–14 ноября 2026

**Новое дополнение — 15 ноября, Riot Repair Tool:** [подробный анализ с двумя новыми графиками](investigation/reports/RIOT-RRT-LOG-ANALYSIS.md), [краткая сводка Meganet](investigation/reports/MEGANET-RRT-BRIEF.md), [вопросы Riot Support](investigation/reports/RIOT-SUPPORT-RRT-BRIEF.md). Восемь числовых игровых Average Ping **328,12–383,31 мс** в **14:27:45.760–14:29:58.816 UTC+05** теперь подтверждены журналом; одновременно контрольные ICMP — по 67/67 Success. Есть 26 input replication stop/queue overflow. Это подтверждает игровой симптом, но пока не устанавливает виновный участок.

Исходные RRT ZIP **не опубликованы**. [Проверенные производные JSON, инвентаризация, временные корреляции и SHA-256](investigation/reports/evidence/riot-rrt-2026-11-15/) сохраняют числовые события, IP:порт и происхождение. Оба VAL ZIP оказались побайтовыми дубликатами; нужные логи поздних матчей 15 ноября отсутствуют в RRT, их [прежняя локальная проверка](investigation/reports/MATCH-ENDPOINTS-2026-11-15.md) обозначена отдельно. [Отдельный ZIP нового RRT-дополнения](downloads/Meganet-Riot-RRT-Reviewed-Evidence-2026-11-15.zip) добавлен к прежним неизменённым архивам.

Полный обезличенный технический набор для сетевых инженеров Meganet. Публичная публикация разрешена владельцем; персональные сетевые идентификаторы и авторизация исключены. **Конкретная причина игрового RTT и потерь UDP пока не доказана.**

## Краткая сводка

В дневном Stockholm-матче игрок сообщил повторные переходы **95 → 120 → 180 → 120 мс**, затем **300–400 мс примерно пять минут**. Это нестабильность с частичными восстановлениями. В близком окне 14:29:10–14:29:58 UTC+05:00 контрольные медианы шлюз / Meganet near-hop / Cloudflare / RETN-1 / RETN-2 — **2 / 3 / 24 / 93 / 92 мс**, по 24 пробы на цель. Это разные измерения, без точной посекундной игровой серии.

После самостоятельного перезахода игровой адрес в логе изменился с **185.40.64.1:7004** на **162.249.72.1:7004**, игрок сообщил ~100, затем 100–110 мс. Есть и отдельные короткие локальные всплески до шлюза, поэтому весь набор симптомов не приписывается только международному транзиту. Позднее в новом матче зарегистрирован **185.40.64.1:7158**, игрок сообщил 96–105 с подъёмом до 110. Физическое размещение серверов и текущий UDP peer не подменяются адресом из лога.

## С чего начать инженеру

- [Полный основной отчёт](investigation/reports/INVESTIGATION-RESULTS.md) · [HTML](investigation/reports/INVESTIGATION-RESULTS.html).
- [Полный дневной отчёт с F8/F9 и сравнением окон](investigation/reports/DAY-MATCH-RESULTS-2026-11-14.md) · [HTML](investigation/reports/DAY-MATCH-RESULTS-2026-11-14.html).
- [Отдельный пакет по методике Meganet: Valorant и Valve SDR / CS2](investigation/reports/meganet-package-2026-11-14/README.md) · [HTML](investigation/reports/meganet-package-2026-11-14/README.html).
- [Черновик технического обращения](investigation/reports/ISP-SUPPORT-DRAFT.md): необходимые проверки forward/reverse route, очередей, дропов и абонентской/NAT-сессии. Обращение автоматически не отправлено.
- [Правила обезличивания, доказательства сохранения данных и ограничения хешей](PUBLICATION-NOTES.md).

## Где исходные измерения и технические метаданные

| Материал | Расположение | Охват |
|---|---|---|
| Непрерывная ночь | [reports/evidence/final-2026-11-14](investigation/reports/evidence/final-2026-11-14/) | 3215 ICMP-проб / 3299 записей; закрытая серия |
| Непрерывный дневной матч | [reports/evidence/day-2026-11-14](investigation/reports/evidence/day-2026-11-14/) | 5745 ICMP-проб / 5988 записей, все ручные метки; закрытая серия |
| Ранние/переходные серии CSV | [reports/evidence](investigation/reports/evidence/) и [final-history](investigation/reports/evidence/final-history/) | Range, переход, Stockholm, ошибочный ранний измеритель сохранён как quality-only |
| Анализ ночи | [final-data](investigation/reports/final-data/) | парные циклы CSV, JSON-аудит, хронология/качество |
| Анализ дня | [day-data](investigation/reports/day-data/) | парные циклы CSV, 107 F8 / 20 F9, группировка без выдуманных точных RTT |
| Текущая незавершённая серия | [follow-up snapshot](investigation/reports/evidence/follow-up-2026-11-14-snapshot/) | 5280 проб / 5389 записей до сохранённого watermark; complete=false, не весь последующий матч |
| Графики ночи и дня | [reports/figures](investigation/reports/figures/) | все 8 исходных PNG: RTT, локальные всплески, Wi-Fi и нагрузка |
| Методика и baseline | [docs](investigation/docs/) | первичные сведения, план, runbook, ограничения сравнения ICMP и игрового UDP |
| Воспроизводимые скрипты и проверки | [scripts](investigation/scripts/) и [tests](investigation/tests/) | PowerShell/Python, низкая нагрузка, без вмешательства в античит |

JSONL содержит не только probe, но и время, ручные метки, lifecycle и очищенные системные снимки. Сохранены RSSI, канал, PHY, счётчики, маршруты и их метрики. Статусы TimedOut/ProbeError и ошибки качества не превращены в нулевой RTT или доказанные сетевые потери. CSV и поля probe не урезаны.

## Ping/tracert по инструкции Meganet

Выполнены **ping -n 100 IP** и **tracert -d -h 32 IP**, без замены тайм-аутов Windows. Полные native `.raw.txt`, читабельные `.utf8.txt`, команды, exit code, UTC/+05 начала/конца и SHA-256 находятся в [measurements](investigation/reports/meganet-package-2026-11-14/measurements/). [Машинная сводка](investigation/reports/meganet-package-2026-11-14/measurement-summary.json).

| Адрес | Роль | ICMP echo | Native min / avg / max |
|---|---|---|---|
| 185.40.64.1 | Связан с игровыми записями Valorant | 0/100 | RTT не получен; не доказательство потерь UDP |
| 162.249.72.1 | Связан с игровыми записями Valorant | 0/100 | RTT не получен; не доказательство потерь UDP |
| 162.254.198.41 | Опубликованный Valve SDR sto / Stockholm Kista | 100/100 | 72 / 72 / 77 мс |
| 155.133.252.37 | Опубликованный Valve SDR sto2 / Stockholm Bromma | 100/100 | 76 / 77 / 81 мс |

Трассы Riot завершили 32 перехода без ответа назначения; последние отвечающие RETN различаются: 87.245.233.166 и 87.245.234.191. Трассы Valve дошли до relay. Эти замеры сделаны отдельно от исторического пика 300–400 и не восстанавливают его маршрут задним числом.

## Адреса Valorant, Anycast и CS2 / SDR

- [Все 14 найденных IP:порт и источники свидетельств](investigation/reports/meganet-package-2026-11-14/valorant-address-inventory.json): связь с записями приложения отличается от проверки текущего UDP peer, успешного handshake и физической географии.
- [План проверок по портам и известный игровой RTT](investigation/reports/meganet-package-2026-11-14/valorant-test-plan.json). ICMP работает по IP и не проверяет игровой UDP-порт.
- [21 опубликованный Stockholm relay Valve с командами](investigation/reports/meganet-package-2026-11-14/cs2-relay-candidates.json) и [публичная конфигурация/время получения](investigation/reports/meganet-package-2026-11-14/sources/). Замерены два представителя, использование relay клиентом CS2 не установлено.
- Anycast-вход Riot не равен физическому серверу матча; адрес SDR relay не равен скрытому серверу CS2. В пакет включены подробные ограничения и ссылки на первичные документы Riot, Valve и Microsoft.

## Скачивание и целостность

- [Полное обезличенное дополнение: код, отчёты, все измерения и графики](downloads/Meganet-Complete-Sanitized-Diagnostics-2026-11-13-14.zip).
- [Компактный пакет только для Meganet, включая Valorant и CS2](downloads/Meganet-Technical-Package-2026-11-14-sanitized.zip).
- [Предыдущий пакет из 80 файлов](downloads/Meganet-Valorant-2026-11-13_14-technical-package.zip) и [его README](technical-package/README.md) сохранены без изменений; это более ранний срез.
- [Аудит публичного экспорта](investigation/PUBLIC-EXPORT-VALIDATION.json) · [общие хеши дополнения](PUBLIC-SHA256SUMS.txt) · [хеши evidence](investigation/reports/evidence/SHA256SUMS.txt).

Время — UTC и UTC+05:00; время нажатия/внесения сообщения не выдаётся за точную секунду игрового RTT. Публичный репозиторий содержит зафиксированные срезы, а не непрерывно обновляемый монитор. Активный монитор и полные необезличенные оригиналы остаются в приватном amir-workspace. Новых игровых сессий ради публикации не запускалось, настройки сети/античит не менялись. Абонентский WAN-IP и договор при необходимости передаются поддержке отдельно через приватный канал.

## Офлайн-воспроизведение

Нужен Python 3.12+; сторонних библиотек для анализа не требуется. Из каталога investigation/: `python -m unittest discover -s tests -v` и `python scripts/analyze_day_match.py reports/evidence/day-2026-11-14 --output reports/day-data --report reports/DAY-MATCH-RESULTS-2026-11-14.md`. Эти команды не запускают игру или сетевые измерения. Windows loopback-тесты требуют отдельного opt-in и по умолчанию не запускаются. Для текущего незавершённого snapshot нет DONE; его нельзя выдавать за закрытый run.
