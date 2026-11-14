"""Build a compact Markdown table from already analyzed, selected evidence sessions."""
import argparse
import json
from pathlib import Path


def number(value):
    return 'unknown' if value is None else f'{value:.3f}'.rstrip('0').rstrip('.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sessions', nargs='+', type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    lines=['# Измеренные сессии','', 'Протокол проб: ICMPv4; 32 байта; тайм-аут 1500 мс; интервал 2 с. '
           'RTT в мс, только успешные ответы; p95 — ближайший ранг. '
           'Процент неответов ICMP не равнозначен потерям игрового UDP. Местные метки содержат UTC+05:00.','']
    for session in args.sessions:
        result=json.loads((session/'analysis.json').read_text(encoding='utf-8-sig'))
        meta=result['metadata']
        selected=[]
        route_file=session/'selected-routes.json'
        if route_file.exists():
            routes=json.loads(route_file.read_text(encoding='utf-8-sig'))
            selected=[s for route in routes if route['target']=='1.1.1.1' for s in route['selection'] if s.get('IPAddress')]
        interface='unknown'
        if selected:
            interface=f"{selected[0]['InterfaceAlias']} / {selected[0]['IPAddress']}"
        lines.extend([f'## {session.name}', '',f"Режим: `{meta['context']}`. Завершена: `{result['complete']}`. "
                      f"Начало процесса: `{meta['start_local']}`; конец: `{meta.get('end_local','pending')}`. "
                      f'Интерфейс начального снимка для 1.1.1.1: {interface}.','',
                      '| Цель | Протокол | Пробы / ответы | min / avg / max | p95 | Неответы % |',
                      '|---|---|---:|---:|---:|---:|'])
        for m in result['metrics']:
            lines.append(f"| `{m['target']}` | ICMPv4 | {m['rows']} / {m['success']} | "
                         f"{number(m['min_ms'])} / {number(m['avg_ms'])} / {number(m['max_ms'])} | {number(m['p95_ms'])} | {number(m['nonresponse_pct'])} |")
        if result['metrics']:
            first=result['metrics'][0]
            lines.extend(['',f"Фактическое окно проб: `{first['first_local']}` — `{first['last_local']}`."])
        lines.extend(['', 'Фактические интервалы проб (с): `'+json.dumps(result['actual_probe_interval_seconds'])+'`.',
                      '', 'RSSI: `'+json.dumps(result.get('wlan_summary',{}))+'`.', '',
                      'Пиковые средние скорости по интервалам счётчиков (не мгновенные, Мбит/с):',''])
        for rate in result['interface_rate_summary']:
            lines.append(f"- {rate['name']}: RX {number(rate['max_interval_rx_mbps'])}; TX {number(rate['max_interval_tx_mbps'])}.")
        lines.extend(['',f"Синхронных циклов с RTT шлюза ≥10 мс: {len(result['gateway_spikes_ge_10_ms'])}. "
                      f"Ошибок чтения/проб: {len(result['errors'])}.", '', 'Показания игрока (не автоматическое чтение графиков):',''])
        if not result['game_markers']:
            lines.append('Не получены.')
        for marker in result['game_markers']:
            lines.append('```json\n'+json.dumps(marker,ensure_ascii=False,indent=2)+'\n```')
        lines.append('')
    args.output.write_text('\n'.join(lines).rstrip()+'\n',encoding='utf-8')


if __name__=='__main__':
    main()
