# Измеренные сессии

**Публичная обезличенная копия.** Числовые измерения, времена и целевые/транзитные IP сохранены. Личные сетевые идентификаторы и локальные пользовательские пути заменены стабильными обозначениями. Упоминаемые исходные размеры и хеши относятся к приватному источнику; актуальные публичные хеши — в SHA256SUMS.txt. Полные native ping/tracert сохранены побайтно. Подробнее — корневой PUBLICATION-NOTES.md.

Протокол проб: ICMPv4; 32 байта; тайм-аут 1500 мс; интервал 2 с. RTT в мс, только успешные ответы; p95 — ближайший ранг. Процент неответов ICMP не равнозначен потерям игрового UDP. Местные метки содержат UTC+05:00.

## 20261113-234606-Range-721321

Режим: `Range`. Завершена: `True`. Начало процесса: `2026-11-13T23:46:06.8285037+05:00`; конец: `2026-11-13T23:50:48.6094894+05:00`. Интерфейс начального снимка для 1.1.1.1: Беспроводная сеть / CLIENT_LAN_IP_01.

| Цель | Протокол | Пробы / ответы | min / avg / max | p95 | Неответы % |
|---|---|---:|---:|---:|---:|
| `192.168.123.1` | ICMPv4 | 140 / 140 | 1 / 1.886 / 7 | 3 | 0 |
| `89.38.164.205` | ICMPv4 | 140 / 140 | 2 / 3.093 / 7 | 5 | 0 |
| `1.1.1.1` | ICMPv4 | 140 / 140 | 22 / 23.436 / 29 | 26 | 0 |
| `87.245.238.34` | ICMPv4 | 140 / 140 | 92 / 93.5 / 112 | 97 | 0 |
| `87.245.234.191` | ICMPv4 | 140 / 140 | 84 / 85.479 / 91 | 88 | 0 |

Фактическое окно проб: `2026-11-13T23:46:10.2352884+05:00` — `2026-11-13T23:50:48.2290034+05:00`.

Фактические интервалы проб (с): `{"min": 1.814, "mean": 1.9999208633093526, "max": 2.193}`.

RSSI: `{"snapshots": 9, "rssi_min_dbm": -64, "rssi_max_dbm": -60}`.

Пиковые средние скорости по интервалам счётчиков (не мгновенные, Мбит/с):

- Ethernet: RX 0; TX 0.
- Ethernet 2: RX 0; TX 0.
- Беспроводная сеть: RX 13.916; TX 0.725.

Синхронных циклов с RTT шлюза ≥10 мс: 0. Ошибок чтения/проб: 0.

Показания игрока (не автоматическое чтение графиков):

```json
{
  "recorded_local": "2026-11-13T23:50:48.3482548+05:00",
  "source": "user_chat",
  "context": "Range",
  "reported_rtt_range_ms": [
    100,
    110
  ],
  "rtt_average_ms": null,
  "rtt_max_ms": null,
  "loss_in_pct": null,
  "loss_out_pct": null,
  "observation_time": "Retrospective over Range, exact spike timestamps not supplied",
  "transition": "User plans to enter ordinary match selecting Stockholm; match entry not yet confirmed"
}
```

## 20261113-235320-Stockholm-unrated-af5126

Режим: `Stockholm-unrated`. Завершена: `True`. Начало процесса: `2026-11-13T23:53:20.9947575+05:00`; конец: `2026-11-14T00:03:21.2625544+05:00`. Интерфейс начального снимка для 1.1.1.1: Беспроводная сеть / CLIENT_LAN_IP_01.

| Цель | Протокол | Пробы / ответы | min / avg / max | p95 | Неответы % |
|---|---|---:|---:|---:|---:|
| `192.168.123.1` | ICMPv4 | 299 / 299 | 1 / 2.151 / 7 | 5 | 0 |
| `89.38.164.205` | ICMPv4 | 299 / 299 | 2 / 3.458 / 10 | 6 | 0 |
| `1.1.1.1` | ICMPv4 | 299 / 299 | 22 / 23.997 / 37 | 28 | 0 |
| `87.245.238.34` | ICMPv4 | 299 / 299 | 91 / 94.037 / 128 | 99 | 0 |
| `87.245.234.191` | ICMPv4 | 299 / 299 | 84 / 86.043 / 99 | 90 | 0 |

Фактическое окно проб: `2026-11-13T23:53:24.6167092+05:00` — `2026-11-14T00:03:20.7418197+05:00`.

Фактические интервалы проб (с): `{"min": 1.803, "mean": 2.0004161073825504, "max": 2.206}`.

RSSI: `{"snapshots": 19, "rssi_min_dbm": -64, "rssi_max_dbm": -58}`.

Пиковые средние скорости по интервалам счётчиков (не мгновенные, Мбит/с):

- Ethernet: RX 0; TX 0.
- Ethernet 2: RX 0; TX 0.
- Беспроводная сеть: RX 0.948; TX 0.668.

Синхронных циклов с RTT шлюза ≥10 мс: 0. Ошибок чтения/проб: 0.

Показания игрока (не автоматическое чтение графиков):

```json
{
  "recorded_local": "2026-11-13T23:58:40.7498938+05:00",
  "source": "user_chat",
  "context": "Stockholm-unrated",
  "region_verification": "Stockholm selected and ordinary match confirmed by player",
  "reported_rtt_range_ms": [
    90,
    100
  ],
  "reported_recent_spike_ms": 110,
  "rtt_average_ms": null,
  "rtt_max_ms": null,
  "loss_in_pct": null,
  "loss_out_pct": null,
  "observation_time": "Retrospective over first match minutes; recent spike exact timestamp not supplied"
}
```

## 20261114-000610-Stockholm-unrated-ee0d94

Режим: `Stockholm-unrated`. Завершена: `True`. Начало процесса: `2026-11-14T00:06:10.6984143+05:00`; конец: `2026-11-14T00:10:18.4942795+05:00`. Интерфейс начального снимка для 1.1.1.1: Беспроводная сеть / CLIENT_LAN_IP_01.

| Цель | Протокол | Пробы / ответы | min / avg / max | p95 | Неответы % |
|---|---|---:|---:|---:|---:|
| `192.168.123.1` | ICMPv4 | 123 / 123 | 1 / 2.154 / 6 | 4 | 0 |
| `89.38.164.205` | ICMPv4 | 123 / 123 | 2 / 3.268 / 7 | 5 | 0 |
| `1.1.1.1` | ICMPv4 | 123 / 123 | 22 / 23.504 / 27 | 26 | 0 |
| `87.245.238.34` | ICMPv4 | 123 / 123 | 92 / 95.016 / 134 | 102 | 0 |
| `87.245.234.191` | ICMPv4 | 123 / 123 | 84 / 85.52 / 90 | 88 | 0 |

Фактическое окно проб: `2026-11-14T00:06:13.6965930+05:00` — `2026-11-14T00:10:17.7858644+05:00`.

Фактические интервалы проб (с): `{"min": 1.807, "mean": 2.00072131147541, "max": 2.193}`.

RSSI: `{"snapshots": 8, "rssi_min_dbm": -63, "rssi_max_dbm": -61}`.

Пиковые средние скорости по интервалам счётчиков (не мгновенные, Мбит/с):

- Ethernet: RX 0; TX 0.
- Ethernet 2: RX 0; TX 0.
- Беспроводная сеть: RX 0.52; TX 1.729.

Синхронных циклов с RTT шлюза ≥10 мс: 0. Ошибок чтения/проб: 0.

Показания игрока (не автоматическое чтение графиков):

```json
{
  "recorded_local": "2026-11-14T00:06:43.6096274+05:00",
  "source": "user_supplied_screenshot",
  "attachment_sha256": "5B2F08CDDFAF20B7533FF20A360D4B8501B2DC3AE79F98DFC3ACAB3FE03EB6D9",
  "attachment_file_last_write_local": "2026-11-14T00:04:27.9452348+05:00",
  "screenshot_has_wall_clock": false,
  "average_network_rtt_ms": 185,
  "maximum_network_rtt_ms": 189,
  "scoreboard_ping_ms": 182,
  "current_total_loss_percent": 0,
  "cumulative_lost_packets": 48,
  "current_inbound_loss_percent": 0,
  "current_outbound_loss_percent": 0,
  "timing_precision": "Screenshot file write time is a proxy, not verified capture time",
  "correlation_limit": "Previous session ended 00:03:21. First hidden restart failed before writing metadata; successful probes resumed 00:06:13 approximately. Screenshot peak is not covered by simultaneous probes."
}
```
```json
{
  "recorded_local": "2026-11-14T00:07:57.1812932+05:00",
  "source": "user_chat",
  "context": "Stockholm-unrated",
  "reported_rtt_range_ms": [
    100,
    160
  ],
  "reported_recent_high_ms": [
    160,
    180
  ],
  "reported_about_one_minute_earlier_ms": [
    100,
    120
  ],
  "timing_precision": "User current/recent report, not exact peak timestamp",
  "loss_in_pct": null,
  "loss_out_pct": null
}
```

## 20261114-001022-Stockholm-unrated-c5ba53

Режим: `Stockholm-unrated`. Завершена: `True`. Начало процесса: `2026-11-14T00:10:22.8271592+05:00`; конец: `2026-11-14T00:15:22.9166113+05:00`. Интерфейс начального снимка для 1.1.1.1: Беспроводная сеть / CLIENT_LAN_IP_01.

| Цель | Протокол | Пробы / ответы | min / avg / max | p95 | Неответы % |
|---|---|---:|---:|---:|---:|
| `192.168.123.1` | ICMPv4 | 149 / 149 | 1 / 2.081 / 10 | 4 | 0 |
| `89.38.164.205` | ICMPv4 | 149 / 149 | 2 / 3.262 / 12 | 6 | 0 |
| `1.1.1.1` | ICMPv4 | 149 / 149 | 22 / 23.678 / 32 | 27 | 0 |
| `87.245.238.34` | ICMPv4 | 149 / 149 | 92 / 93.913 / 103 | 99 | 0 |
| `87.245.233.166` | ICMPv4 | 149 / 149 | 91 / 92.322 / 99 | 96 | 0 |

Фактическое окно проб: `2026-11-14T00:10:25.3300008+05:00` — `2026-11-14T00:15:21.3577941+05:00`.

Фактические интервалы проб (с): `{"min": 1.825, "mean": 2.000175675675676, "max": 2.194}`.

RSSI: `{"snapshots": 10, "rssi_min_dbm": -63, "rssi_max_dbm": -60}`.

Пиковые средние скорости по интервалам счётчиков (не мгновенные, Мбит/с):

- Ethernet: RX 0; TX 0.
- Ethernet 2: RX 0; TX 0.
- Беспроводная сеть: RX 1.876; TX 0.665.

Синхронных циклов с RTT шлюза ≥10 мс: 1. Ошибок чтения/проб: 0.

Показания игрока (не автоматическое чтение графиков):

```json
{
  "recorded_local": "2026-11-14T00:14:43.5121439+05:00",
  "source": "user_chat",
  "context": "Stockholm-unrated",
  "reported_rtt_range_ms": [
    91,
    96
  ],
  "event": "Recovery reported",
  "timing_precision": "Current range at chat reply; exact onset of recovery not provided",
  "loss_in_pct": null,
  "loss_out_pct": null
}
```
