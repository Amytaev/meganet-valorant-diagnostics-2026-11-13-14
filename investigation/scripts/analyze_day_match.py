"""Audit a stopped match, group manual markers, and write its reproducible report."""
import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from final_stage_analysis import analyze, read_json, dt, metrics, TARGETS, LABELS, COLORS, LOCAL


def local(stamp):
    return dt(stamp).astimezone(LOCAL).isoformat(timespec='milliseconds')


def group_markers(markers, end):
    groups = []; opened = None; stray = 0
    for marker in sorted(markers, key=lambda m: dt(m.get('observed_utc', m['time_utc']))):
        stamp = marker.get('observed_utc', marker['time_utc'])
        if marker['event'] == 'spike':
            if opened is None:
                opened = dict(start=stamp, spike_presses=0)
            opened['spike_presses'] += 1
        elif marker['event'] == 'recovery':
            if opened is None:
                stray += 1
            else:
                groups.append(dict(opened, end=stamp, closed=True, end_source=marker['source']))
                opened = None
    if opened:
        groups.append(dict(opened, end=end, closed=False, end_source='observation_end'))
    return groups, stray


def select(cycles, start, end):
    return [c for c in cycles if dt(start) <= dt(c['time_local']) <= dt(end)]


def table(headers, rows):
    return '\n'.join(['| '+' | '.join(headers)+' |', '|'+'|'.join(['---']*len(headers))+'|'] +
                     ['| '+' | '.join(str(x) for x in row)+' |' for row in rows])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    a = analyze(args.run, read_json(project/'config/anomaly-baseline-2026-11-14.json'))
    clarification_file = args.run/'chronology-clarification.json'
    if clarification_file.exists():
        a['chronology_clarification'] = read_json(clarification_file)
    audit = a['audit']; cycles = a['cycles']; meta = a['metadata']
    assert audit['sequence_contiguous'] and not audit['timestamp_errors']
    assert audit['duplicate_cycle_targets'] == 0 and not audit['retention_deletions']
    assert audit['all_segments_closed'] and all(s['bounds_match'] and s['bytes_match'] and s['newline_terminated'] for s in audit['segments'])
    assert audit['done']['durable'] and not meta['unfinished_probes']
    assert audit['final_health']['last_seq'] == audit['final_health']['committed_seq'] == audit['records']
    assert audit['final_health']['dropped_memory_records'] == audit['final_health']['buffered_records'] == 0
    assert audit['final_health']['io_error'] is None
    assert len(cycles) == audit['cycles'] and audit['statuses'] == {'Success': len(cycles)*5}
    groups, stray = group_markers(a['manual_markers'], meta['end_utc'])
    for g in groups:
        cs = select(cycles, g['start'], g['end'])
        g['metrics'] = {ip: metrics([c['values'][ip] for c in cs]) for ip in TARGETS}
    windows = [
        ('Плотные F8, ретроспективно 120–180', '2026-11-14T09:19:15.263+00:00', '2026-11-14T09:22:15.150+00:00'),
        ('После сообщения 300–400, до последнего снимка прежнего PID', '2026-11-14T09:29:10.353+00:00', '2026-11-14T09:29:58.079448+00:00'),
        ('После сообщения о восстановлении ~100', '2026-11-14T09:32:53.416+00:00', meta['end_utc']),
        ('Последняя закрытая группа F8→F9, ретроспективно 120–130', '2026-11-14T09:46:53.433+00:00', '2026-11-14T09:48:19.919+00:00'),
        ('Последняя незакрытая группа F8, ретроспективно 120–130', '2026-11-14T09:48:40.169+00:00', meta['end_utc']),
    ]
    a['game_windows'] = []
    for name, start, end in windows:
        cs = select(cycles, start, end)
        a['game_windows'].append(dict(name=name, start=local(start), end=local(end),
                                     metrics={ip: metrics([c['values'][ip] for c in cs]) for ip in TARGETS}))
    a['grouped_markers'] = groups; a['unpaired_recovery'] = stray
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/'analysis.json').write_text(json.dumps(a, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    with (args.output/'paired-cycles.csv').open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['cycle', 'time_local', 'classification', *TARGETS])
        writer.writeheader()
        for c in cycles:
            writer.writerow(dict(cycle=c['cycle'], time_local=c['time_local'], classification=c['classification'], **c['values']))
    def series(cs):
        return [dict(name=label, color=color, points=[dict(x=c['time_local'], y=c['values'][ip]) for c in cs]) for ip,label,color in zip(TARGETS,LABELS,COLORS)]
    common = dict(x_label='14 ноября 2026, UTC+05:00', y_label='Контрольный ICMP RTT, мс', y_min=0, y_max=300)
    specs = [dict(common, name='rtt-overview.png', title='Дневной матч: контрольные направления; игровые RTT не измерены', series=series(cycles)),
             dict(common, name='rtt-local-zoom.png', title='Выход и перезаход: контрольные RTT продолжают измеряться',
                  series=series(select(cycles, '2026-11-14T09:27:30+00:00', '2026-11-14T09:33:30+00:00')),
                  marker='2026-11-14T09:32:53.416+00:00', marker_text='Сообщено восстановление ~100 мс')]
    specs.append(dict(name='traffic.png', title='Трафик адаптера ПК, средние примерно за 30 с', x_label=common['x_label'], y_label='Мбит/с', y_min=0,
                      series=[dict(name=label, color=color, points=[dict(x=r['time'],y=r[key]) for r in a['rates']]) for label,color,key in [('RX','#1768ac','rx_mbps'),('TX','#d18b00','tx_mbps')]]))
    specs.append(dict(name='wifi.png', title='Wi-Fi: RSSI и согласованная PHY-скорость', x_label=common['x_label'], y_label='RSSI, dBm', y_min=-80, y_max=-40, y2_label='PHY TX, Мбит/с',
                      series=[dict(name='RSSI', color='#2e8b57', points=[dict(x=w['time'],y=w['rssi_dbm']) for w in a['wlan'] if w['rssi_dbm'] is not None]),
                              dict(name='PHY TX', color='#7749ae', secondary=True, points=[dict(x=w['time'],y=w['tx_phy_mbps']) for w in a['wlan'] if w['tx_phy_mbps'] is not None])]))
    (args.output/'chart-spec.json').write_text(json.dumps(specs,ensure_ascii=False),encoding='utf-8')
    hotkeys = Counter(m['event'] for m in a['manual_markers'] if m['source']=='RegisterHotKey')
    duration = (dt(meta['end_utc'])-dt(meta['start_utc'])).total_seconds()
    max_interval = max(m['max'] for m in audit['intervals_seconds'].values())
    figure_dir = 'figures/day-2026-11-14'
    report = [
        '# Итог дневного матча Stockholm — 14 ноября 2026', '',
        '**Проблема проявлялась как повторная нестабильность игрового RTT с частичными восстановлениями: по уточнению игрока 95 → 120 → 180 → 120 мс, позднее 300–400 мс. Длительные игровые 300–400 мс не сопровождались аналогичным ростом контрольных RTT. После самостоятельного перезапуска игрок сообщил ~100, затем стабильные 100–110 мс; одновременно изменился адрес подключения в игровом логе. Это существенная зацепка для проверки конкретного игрового пути/соединения, но она не отделяет маршрут от состояния клиента/сервера. Точная причина и источник UDP-потерь пока не установлены.**', '',
        f"Монитор остановлен после окончания игры в **{local(meta['end_utc'])}**. Run `{meta['run_id']}`; PID {meta['pid']} завершён, DONE durable=true. Начало {local(meta['start_utc'])}, длительность {duration:.3f} с. **{len(cycles)} полных циклов, {len(cycles)*5} успешных ICMP-проб, {audit['records']} записей.**", '',
        '## 1. Происхождение и целостность', '',
        f"Непрерывный обычный пользовательский процесс, ICMPv4 32 байта каждые 2 с к пяти целям, timeout 1500 мс. Три сегмента ротировались без перезапуска. Sequence 1–{audit['records']} непрерывен, дубликатов и удалений нет. Все размеры, границы manifest и завершающие newline совпадают. Очередь записи и dropped=0; io_error=null; незавершённых проб нет. Исправленная после ночного этапа ошибка first_seq в этом запуске не повторилась.", '',
        f"UTC/local +05 согласованы; обратных ходов времени нет; максимальный интервал проб {max_interval:.6f} с, разброс запуска целей {audit['launch_skew_max_ms']} мс, относительное wall/monotonic расхождение {audit['max_clock_vs_monotonic_drift_ms']} мс. Это не независимая проверка абсолютных часов и не гарантия регистрации субсекундных событий.", '',
        'Пользователь подтвердил рейтинговый Stockholm; агент не входил в матч и не управлял игрой. Metadata context=Unknown отражает ограниченный перечень launcher, а ручной контекст явно указывает ranked. Network RTT/loss автоматически из игры не читались. Все игровые числа ниже — сообщения игрока с известным временем внесения, но не точные секундные отсчёты.', '',
        '## 2. Пять контрольных направлений', '',
        table(['Адрес','n','min','median','avg','p95','max, мс','ICMP неответы'], [[ip,m['n'],m['min'],m['median'],m['avg'],m['p95'],m['max'],'0'] for ip,m in a['metrics'].items()]), '',
        f'![Контрольные RTT всего матча]({figure_dir}/rtt-overview.png)', '',
        'Пороги из прежних измерений: 15 / 16 / 38 / 109 / 106 мс, в порядке таблицы. Классы относятся к отдельным контрольным циклам, а не длительности плохой игры или проценту потерь.', '',
        table(['Класс','Циклов'], a['classification_counts'].items()), '',
        '## 3. Игровая хронология и ручные метки', '',
        f"Сохранено **{hotkeys['spike']} F8 и {hotkeys['recovery']} F9**, плюс ручные записи по сообщениям. Последовательные F8 до следующего F9/recovery сгруппированы: всего {len(groups)}; закрыто {sum(g['closed'] for g in groups)}, открыто к концу {sum(not g['closed'] for g in groups)}. Один F9 без открытого F8 сохранён отдельно. Нажатия не выдаются за независимые инциденты, числовой RTT или доказанное непрерывное состояние игры.", '',
        '* Начало: 89–95 мс по сообщению игрока.',
        '* В плотных F8 около 14:19–14:22: ретроспективно колебания 120–180 мс, повторные нажатия сопровождали колебания.',
        '* Новая серия F8 с 14:27:50; в 14:29:10 внесено сообщение о стабильных 300–400 мс. Позже игрок оценил продолжительность примерно в пять минут. Точные границы неизвестны.',
        '* В снимке 14:29:58 ещё PID 12840; в 14:30:28 и 14:30:58 игры нет; в 14:31:28 появился PID 23980. Это дискретные снимки, а не точные секунды выхода/входа.',
        '* В 14:32:53 внесено сообщение ~100 мс после перезахода; в 14:42:38 — стабильные 100–110 мс.',
        '* Последние F8 в 14:46:53/54, 14:48:17 и 14:48:40 игрок после матча связал с 120–130 мс. Потери в этом матче численно не сообщены.', '',
        '### Уточнённый порядок колебаний до тяжёлого эпизода', '',
        '**95 → 120 → 180 → 120 мс, затем позднее 300–400 мс** — ретроспективная последовательность со слов игрока, уточнённая после матча. Это неоднократные изменения задержки с периодическим частичным восстановлением, а не один изолированный скачок и не только постоянный высокий RTT. Возврат 180→120 является частичным: 120 всё ещё выше исходных ~95 мс. Точные секунды этих числовых переходов не записаны.', '',
        table(['Сохранённое время, +05:00','Что действительно зафиксировано','Предел сопоставления'], [
            ['14:14:08.511→14:14:15.215; 14:15:38.130→14:15:41.905; 14:15:47.842→14:15:53.398','Отдельные группы F8→F9 до тяжёлого эпизода','Метки повторных ухудшений/восстановлений; чисел RTT внутри нажатий нет'],
            ['14:19:15.263–14:22:15.150','Плотные серии F8 с промежуточными F9; ранее игрок связал их с колебаниями 120–180','Согласуется с повторными изменениями и частичными восстановлениями; нельзя назначить конкретной F8/F9 значение 95, 120 или 180'],
            ['С 14:27:50.587; F8 также в 14:28:12.731','Новая серия отметок ухудшения','Время нажатий известно; точный переход к 300–400 по ним не установлен'],
            ['14:29:10.353','Внесено сообщение о продолжающихся 300–400 мс','Время внесения сообщения, не точная секунда начала 300–400'],
        ]), '',
        'Контроли в плотном окне 14:19:15–14:22:15: по 90 проб на цель, медианы 2 / 4 / 24 / 94 / 93 мс, максимумы 19 / 20 / 41 / 137 / 109 мс. Максимумы могли прийтись на разные циклы. Синхронно 14:19:20.547: 2 / 3 / 24 / 137 / 92; 14:21:18.527: 19 / 20 / 41 / 110 / 109 мс. Эти измерения не дают числовой привязки к каждому игровому переходу 95→120→180→120. Наличие коротких контрольных всплесков не превращает весь период колебаний игры в один сетевой инцидент.', '',
        '## 4. Сопоставление окон', '',
        'Ниже контрольные min/median/max по каждому адресу. Выбранные окна — границы сообщений/меток; они не подменяют отсутствующий игровой временной ряд.', '',
    ]
    for w in a['game_windows']:
        report += [f"### {w['name']}", '', f"{w['start']} — {w['end']}", '',
                   table(['Цель','n','min / median / max, мс'], [[ip,m['n'],f"{m.get('min')} / {m.get('median')} / {m.get('max')}"] for ip,m in w['metrics'].items()]), '']
    report += [
        f'![Непрерывный контроль вокруг выхода и возврата]({figure_dir}/rtt-local-zoom.png)', '',
        'Во время наиболее полезного короткого окна после сообщения 300–400 и до последнего снимка прежнего игрового процесса все пять контролей остаются близки к обычному уровню. Это не поддерживает гипотезу длительной общей задержки на ПК–шлюз–все измеренные направления. Но узлы RETN не являются подтверждённым игровым peer; специфический игровой/обратный путь и UDP могут отличаться.', '',
        'Отдельный сильный локальный эпизод после восстановления: **14:35:00.503 — 118 / 16 / 139 / 254 / 253 мс**; затем 14:35:02 — 25 / 26 / 46 / 163 / 163, 14:35:04 — 41 / 43 / 63 / 180 / 180. Есть задержка уже до шлюза, но величины целей не идентичны. Это краткое локальное/общее явление, а не доказательство причины прежних игровых пяти минут 300–400. Ручной F8 около него нет. Wi-Fi, AP/роутер, планирование и сетевой стек ещё не разделены.', '',
        '## 5. Что изменилось после перезахода', '',
        'В сохранённой allowlist-выборке штатного игрового лога до выхода: **185.40.64.1:7004**, после: **162.249.72.1:7004**. Категории LogTravelManager/LogMapLoadModel, после также LogNet. Raw log times около 09:08:49–09:09:04 и 09:31:45–09:31:50; интерпретация UTC согласуется с системой, но независимо формат часов не проверен.', '',
        'Финальная выборка после матча также содержит 162.249.72.1:7004 (LogMapLoadModel, raw log time 09:49:20.962). Нового отличающегося адреса в ограниченной выборке не найдено; это не заменяет непрерывную проверку реального UDP peer.', '',
        'Это наблюдаемая смена адреса в логах подключения. Она не доказывает смену физического сервера, датацентра, транзита или независимо проверенный активный UDP peer. Перезапуск одновременно меняет клиентское состояние; восстановление после него не доказывает причинность адреса. Старый baseline уже упоминал 162.249.72.1 как не отвечающий на ICMP: это не означает неработоспособность игрового UDP.', '',
        '## 6. Wi-Fi, нагрузка, маршруты', '',
        f"Снимков системы {a['system_snapshot_count']}; вариантов выбранных маршрутов {a['selected_route_variants']}, IPv4-таблицы {a['ipv4_route_variants']}. Выбор маршрута диагностических целей через домашний Wi-Fi не изменялся в редких снимках. Это не исключает изменений международного/обратного пути или кратких изменений между снимками.", '',
        f"Wi-Fi RSSI {min(w['rssi_dbm'] for w in a['wlan'] if w['rssi_dbm'] is not None)}…{max(w['rssi_dbm'] for w in a['wlan'] if w['rssi_dbm'] is not None)} dBm; каналы {sorted({w['channel'] for w in a['wlan']})}; уникальных BSSID {len({w['bssid'] for w in a['wlan']})}. Максимальные средние RX/TX адаптера примерно за 30 с: {max(r['rx_mbps'] for r in a['rates']):.3f}/{max(r['tx_mbps'] for r in a['rates']):.3f} Мбит/с. Эти средние не измеряют airtime/retries и не исключают микровсплески, другие домашние устройства или bufferbloat.", '',
        f'![Средняя нагрузка адаптера]({figure_dir}/traffic.png)', '',
        f'![Снимки Wi-Fi]({figure_dir}/wifi.png)', '',
        '## 7. Выводы и следующий различающий тест', '',
        table(['Гипотеза','Статус'], [
            ['Пять минут общего роста RTT на всех измеренных направлениях','Не поддерживается сохранёнными синхронными пробами; специфические назначения/протоколы остаются открыты'],
            ['Короткие локальные/общие всплески существуют','Поддерживается, в частности 14:35; точный механизм и соответствующий игровой RTT неизвестны'],
            ['Игровой путь/соединение влияет на высокий RTT','Усилена расхождением контролей с игрой и сменой адреса при восстановлении; причинность не доказана'],
            ['Виноваты только Meganet или RETN','Не доказано: не измерен реальный игровой forward/reverse UDP путь'],
            ['Виноваты клиент или сервер Riot','Не доказано: нет точной игровой телеметрии и причинного A/B'],
            ['Игровых потерь не было','Утверждать нельзя: нули ICMP и NIC не измеряют игровые UDP-потери'],
        ]), '',
        'Наиболее полезный следующий шаг — зафиксировать фактический игровой peer/подключение и точные RTT/loss одновременно с контролями в плохом и хорошем состоянии. Начать со штатных логов и пользовательских показаний; если этого недостаточно, отдельно согласовать строго ограниченное наблюдение метаданных только игрового потока. Никакого бесконтрольного UDP-захвата. Для коротких локальных всплесков остаётся отдельно согласованный Ethernet/Wi-Fi A/B. Для Meganet/Riot уже полезно приложить два кандидата подключения и хронологию, запросив проверку обоих направлений и обратного пути без обвинения оператора.', '',
        '## 8. Материалы и воспроизведение', '',
        'Исходные журналы и метаданные: [дневное evidence](evidence/day-2026-11-14/). Полный аудит и группы меток: [analysis.json](day-data/analysis.json), [парные циклы](day-data/paired-cycles.csv). Ночной этап сохранён в прежнем отчёте и не переписывается новыми выводами. Промежуточные отчёты имеют ограниченные watermark и не являются итогом всей серии.', '',
        '```powershell',
        'python scripts/analyze_day_match.py reports/evidence/day-2026-11-14 --output reports/day-data --report reports/DAY-MATCH-RESULTS-2026-11-14.md',
        'powershell -NoProfile -File scripts/Render-InvestigationCharts.ps1 -SpecPath reports/day-data/chart-spec.json -OutputDirectory reports/figures/day-2026-11-14',
        '```', '',
        'Сетевые настройки не менялись; захват пакетов, вмешательство в память/Vanguard и управление окнами не выполнялись. Перезапуск игры выполнял пользователь. Монитор остановлен только после сообщения об окончании игры. Обращение Meganet обновляется как черновик и не отправляется.',
    ]
    args.report.write_text('\n'.join(report)+'\n', encoding='utf-8', newline='\n')
    print(json.dumps(dict(records=audit['records'],probes=len(cycles)*5,groups=len(groups),hotkeys=hotkeys,
                          stop=local(meta['end_utc']),report=str(args.report)),ensure_ascii=False))


if __name__ == '__main__':
    main()
