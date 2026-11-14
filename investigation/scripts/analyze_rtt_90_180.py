"""Offline event/counter analysis. No network, settings, game or anti-cheat APIs.

prepare reads existing frozen game logs and saved monitor prefixes and exports
allowlisted numerical inputs. analyze reproduces results from those reviewed
inputs alone, including in the public repository. Raw game logs stay outside Git.
"""
from __future__ import annotations
import argparse
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import statistics

from analyze_rrt_logs import parse_game

LOCAL = timezone(timedelta(hours=5))
UTC = timezone.utc
TARGETS = ['192.168.123.1', '89.38.164.205', '1.1.1.1', '87.245.238.34', '87.245.233.166']
EARLY_RETN = '87.245.234.191'
START = '2026-11-12T19:00:00.000+00:00'  # local 13 November
END = '2026-11-15T19:00:00.000+00:00'    # local 16 November, exclusive
PROBE_FIELDS = ['source', 'seq', 'cycle', 'sent_utc', 'completed_utc', 'target', 'status', 'rtt_ms', 'quality', 'eligible']
COUNTERS = ['ReceivedBytes', 'SentBytes', 'ReceivedDiscardedPackets', 'OutboundDiscardedPackets', 'ReceivedPacketErrors', 'OutboundPacketErrors']


def dt(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def epoch(value):
    return dt(value).timestamp()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8', newline='\n')


def write_csv(path, fields, rows):
    with path.open('w', encoding='utf-8', newline='') as h:
        writer = csv.DictWriter(h, fieldnames=fields, lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def compact_event(e):
    return {k: v for k, v in e.items() if k not in ('file_id',)}


def band_label(value):
    for ceiling, name in ((110, '90-<110'), (120, '110-<120'), (130, '120-<130'), (150, '130-<150')):
        if value < ceiling:
            return name
    return '150-180'


def normalized_snapshot(row, source, ap_aliases):
    """Never export wlan text, MACs, SSIDs, source IPs or raw routes."""
    text = row.get('wlan', '')
    # Early PowerShell logs preserved UTF-8 output decoded as OEM CP866.
    # Repair only reversible lines; never assume their Unicode text is a PHY value.
    repaired = []
    for line in text.splitlines():
        if '╨' in line or '╤' in line:
            try:
                line = line.encode('cp866').decode('utf-8')
            except UnicodeError:
                pass
        repaired.append(line)
    text = '\n'.join(repaired)
    def field(pattern, cast=str):
        found = re.search(pattern, text, re.I | re.M)
        return cast(found[1]) if found else None
    bssid = field(r'^\s*AP BSSID\s*:\s*(\S+)')
    if bssid and bssid not in ap_aliases:
        ap_aliases[bssid] = 'ap-'+str(len(ap_aliases)+1).zfill(2)
    adapter = next((a for a in row.get('adapters', []) if '8852BE' in a.get('InterfaceDescription', '')), None)
    # Full adapter inventories are less frequent than counter/WLAN snapshots.
    # Resolve the interface from netsh's Name on incremental snapshots as well.
    wifi_name = adapter.get('Name') if adapter else field(r'^\s*(?:Name|Имя)\s*:\s*(.+)')
    counters = next((c for c in row.get('counters', []) if wifi_name and c.get('Name') == wifi_name), {})
    routes = []
    for item in row.get('selected_routes', []):
        selection = item.get('selection', [])
        if isinstance(selection, dict):
            selection = [selection]
        fields = {}
        for key in ('InterfaceIndex', 'NextHop', 'RouteMetric', 'InterfaceMetric'):
            fields[key] = next((r[key] for r in selection if isinstance(r, dict) and r.get(key) is not None), None)
        routes.append(dict(target=item['target'], **fields))
    state = field(r'^\s*(?:State|Состояние)\s*:\s*(\S+)')
    return dict(source=source, seq=row['seq'], time_utc=dt(row.get('observed_local', row['time_utc'])).astimezone(UTC).isoformat(),
                recorded_utc=row['time_utc'], connected=(state.lower() in ('connected', 'подключено')) if state else None,
                ap_alias=ap_aliases.get(bssid), rssi_dbm=field(r'^\s*Rssi\s*:\s*(-?\d+)', int),
                channel=field(r'^\s*(?:Channel|Канал)\s*:\s*(\d+)', int),
                rx_phy_mbps=field(r'^\s*(?:Receive rate \(Mbps\)|Скорость приема \(Мбит/с\))\s*:\s*([\d.]+)', float),
                tx_phy_mbps=field(r'^\s*(?:Transmit rate \(Mbps\)|Скорость передачи \(Мбит/с\))\s*:\s*([\d.]+)', float),
                counters={k: counters.get(k) for k in COUNTERS}, selected_routes=routes,
                game_pids=[p for p in row.get('game_pids', []) if type(p) is int],
                snapshot_error_count=len(row.get('errors', [])))


def prepare(project, game_dir, manifest_path, output, watermarks=None):
    if any((p/'.git').exists() for p in (game_dir.resolve(), *game_dir.resolve().parents)):
        raise ValueError('Raw frozen game sources must remain outside Git repositories')
    if output.resolve() == game_dir.resolve() or game_dir.resolve() in output.resolve().parents:
        raise ValueError('Derived output must not be inside the raw source directory')
    output.mkdir(parents=True, exist_ok=True)
    declared = read_json(manifest_path)
    rrt_inventory = read_json(project/'reports/evidence/riot-rrt-2026-11-15/inventory.json')
    rrt_by_hash = {m['sha256']: m['file_id'] for m in rrt_inventory['members'] if m.get('sha256')}
    game_sources, events, stats, coverage = [], [], [], []
    seen = set()
    for source in declared:
        f = game_dir/source['file']
        raw = f.read_bytes()
        if len(raw) > 64*1024**2 or sha(raw) != source['sha256']:
            raise ValueError('Frozen game input mismatch')
        if sha(raw) in seen:
            continue
        seen.add(sha(raw))
        item = dict({k:source[k] for k in ('file_id','file','bytes','sha256','mtime_utc','source_stable_during_read')},
                    rrt_duplicate_member=rrt_by_hash.get(sha(raw)),
                    scratch_write_utc=datetime.fromtimestamp(f.stat().st_mtime, UTC).isoformat(),
                    current_file_is_frozen_prefix=f.name == 'ShooterGame.log')
        game_sources.append(item)
        c, ev, st = parse_game(raw.decode('utf-8-sig'), source['file_id'], f.name)
        coverage.append(c)
        events.extend(compact_event(e) for e in ev if START <= e['time_utc'] < END)
        stats.extend(compact_event(e) for e in st if START <= e['time_utc'] < END)
    events.sort(key=lambda e: (e['time_utc'], e['file'], e['line'], e['kind']))
    for i, e in enumerate(events, 1):
        e['event_id'] = 'G'+str(i).zfill(5)
    write_json(output/'game-sources.json', dict(sources=game_sources, coverage=coverage,
                                               rrt_archives=rrt_inventory['archives'],
                                               scope='Frozen local game logs for 13–15 November; identical RRT members deduplicated by SHA-256.'))
    write_json(output/'game-events.json', events)
    write_json(output/'netdriver-stats.json', stats)
    limits = read_json(project/'config/anomaly-baseline-2026-11-14.json')
    # Only technical thresholds; private source paths are not copied.
    write_json(output/'thresholds.json', {target: {k: d[k] for k in ('threshold_ms', 'median_ms', 'p95_ms', 'samples')}
                                        for target, d in limits['targets'].items()})
    probes, snapshots, markers, audits, observations = [], [], [], [], []
    ap_aliases = {}
    frozen = {r['source']: r for r in read_json(watermarks)} if watermarks else {}
    for folder in sorted((project/'raw/continuous').iterdir()):
        if not folder.is_dir() or not (folder/'metadata.json').exists():
            continue
        source = folder.name
        meta = read_json(folder/'metadata.json')
        status = read_json(folder/'status.json')
        watermark = status.get('committed_seq') if status.get('state') == 'running' else meta.get('final_health', {}).get('last_seq')
        if source in frozen and frozen[source].get('frozen_last_seq') is not None:
            watermark = frozen[source]['frozen_last_seq']
        eligible = source != '20261114-004449-2aa43789'
        seqs, stamps, statuses, chunks, last_seq, stop = [], [], Counter(), [], 0, False
        source_probes = []
        for f in sorted(folder.glob('telemetry-*.jsonl')):
            consumed = bytearray()
            with f.open('rb') as h:
                for line in h:
                    if not line.strip():
                        continue
                    row = json.loads(line.decode('utf-8-sig'))
                    if watermark is not None and row['seq'] > watermark:
                        stop = True
                        break
                    consumed.extend(line)
                    last_seq = row['seq']
                    seqs.append(last_seq)
                    stamps.append(row['time_utc'])
                    if row['kind'] == 'probe':
                        r = {k: row.get(k) for k in PROBE_FIELDS if k not in ('source', 'eligible')}
                        r.update(source=source, eligible=int(eligible and row.get('quality', 'normal') == 'normal'))
                        source_probes.append(r)
                        statuses[r['status']] += 1
                    elif row['kind'] == 'system_snapshot' and eligible:
                        snapshots.append(normalized_snapshot(row, source, ap_aliases))
                    elif row['kind'] == 'game_marker':
                        event = row.get('event')
                        if event in ('spike', 'recovery', 'note'):
                            markers.append(dict(source_run=source, seq=row['seq'], time_utc=row['time_utc'],
                                                observed_utc=row.get('observed_utc', row['time_utc']), event=event,
                                                source_kind=row.get('source') if row.get('source') in ('RegisterHotKey', 'user_report_at_message_entry', 'user_retrospective_report') else 'other',
                                                eligible=eligible))
                    if watermark is not None and last_seq == watermark:
                        stop = True
                        break
            if consumed:
                chunks.append(dict(file=f.name, consumed_bytes=len(consumed), sha256=sha(consumed)))
            if stop:
                break
        if watermark is not None and last_seq != watermark:
            raise ValueError('Committed prefix watermark not found')
        if seqs != list(range(1, last_seq+1)):
            raise ValueError('Missing or duplicate sequence in canonical monitor prefix')
        if any(dt(b) < dt(a) for a, b in zip(stamps, stamps[1:])):
            raise ValueError('Record clock moved backward')
        probes.extend(source_probes)
        intervals = {}
        for target in meta['targets']:
            rows = [r for r in source_probes if r['target'] == target]
            gaps = [(dt(b['sent_utc'])-dt(a['sent_utc'])).total_seconds() for a, b in zip(rows, rows[1:])]
            intervals[target] = dict(n=len(rows), max_seconds=max(gaps) if gaps else None,
                                     gaps_over_3_seconds=sum(g > 3 for g in gaps))
        audits.append(dict(source=source, kind='continuous', eligible=eligible,
                           excluded_reason=None if eligible else 'Known failed collector revision: ProbeError artifacts, not packet-loss measurements',
                           start_utc=meta['start_utc'], end_utc=meta.get('end_utc'), state=status['state'],
                           frozen_last_seq=last_seq, heartbeat_at_freeze=frozen.get(source, {}).get('heartbeat_at_freeze', status.get('heartbeat_utc')),
                           records=len(seqs), sequence_contiguous=True, record_clock_monotonic=True,
                           probe_statuses=dict(statuses), intervals=intervals, consumed_prefix_chunks=chunks))
    for folder in sorted((project/'raw').glob('2026*')):
        f = folder/'pings.csv'
        if not f.exists():
            audits.append(dict(source=folder.name, kind='legacy', eligible=False, excluded_reason='No saved probe CSV'))
            continue
        eligible = folder.name != '20261113-234232-Range-1fbb0d'
        raw = f.read_bytes()
        with f.open(encoding='utf-8-sig', newline='') as h:
            rows = list(csv.DictReader(h))
        for i, row in enumerate(rows, 1):
            probes.append(dict(source=folder.name, seq=i, cycle=row['cycle'], sent_utc=row['sent_utc'],
                               completed_utc=row['completed_utc'], target=row['target'], status=row['status'],
                               rtt_ms=float(row['rtt_ms']) if row.get('rtt_ms') else None,
                               quality=row.get('quality', 'unqualified_legacy'),
                               eligible=int(eligible and row.get('quality') == 'normal')))
        audits.append(dict(source=folder.name, kind='legacy', eligible=eligible, bytes=len(raw), sha256=sha(raw),
                           excluded_reason=None if eligible else 'Known early timeout bug; not reliable loss measurements',
                           rows=len(rows), probe_statuses=dict(Counter(r['status'] for r in rows)),
                           first_sent_utc=rows[0]['sent_utc'] if rows else None, last_sent_utc=rows[-1]['sent_utc'] if rows else None))
        if eligible and (folder/'counters.jsonl').exists() and (folder/'wlan.jsonl').exists():
            wlans = [json.loads(s) for s in (folder/'wlan.jsonl').read_text(encoding='utf-8-sig').splitlines() if s.strip()]
            index = TimedIndex(wlans, 'time')
            adapters = read_json(folder/'adapters.json')
            if isinstance(adapters, dict):
                adapters = [adapters]
            wifi = next((a for a in adapters if '8852BE' in a.get('InterfaceDescription', '')), None)
            for i, line in enumerate((folder/'counters.jsonl').read_text(encoding='utf-8-sig').splitlines(), 1):
                r = json.loads(line)
                if not wifi or r.get('name') != wifi.get('Name'):
                    continue
                wlan = index.nearest(epoch(r['time']))
                if not wlan or abs(epoch(wlan['time'])-epoch(r['time'])) > 30:
                    continue
                c = dict(Name=r['name'], **{k: r.get(v) for k, v in zip(COUNTERS, ['rx_bytes','tx_bytes','rx_discards','tx_discards','rx_errors','tx_errors'])})
                stamp = dt(r['time']).astimezone(UTC).isoformat()
                snapshot = normalized_snapshot(dict(seq=i, time_utc=stamp, counters=[c], adapters=adapters, wlan=wlan['text']), folder.name, ap_aliases)
                snapshot['wlan_sample_time_utc'] = dt(wlan['time']).astimezone(UTC).isoformat()
                snapshots.append(snapshot)
        marker_file = folder/'game-markers.jsonl'
        if marker_file.exists():
            numeric_fields = ['reported_rtt_range_ms','reported_recent_spike_ms','rtt_average_ms','rtt_avg_ms','rtt_max_ms',
                              'average_network_rtt_ms','maximum_network_rtt_ms','loss_in_pct','loss_out_pct',
                              'current_total_loss_percent','cumulative_lost_packets']
            for i, line in enumerate(marker_file.read_text(encoding='utf-8-sig').splitlines(), 1):
                r = json.loads(line)
                fields = {}
                for k in numeric_fields:
                    v = r.get(k)
                    if v is None or type(v) in (int, float) or isinstance(v, list) and all(type(x) in (int, float) for x in v):
                        if k in r:
                            fields[k] = v
                observations.append(dict(source=folder.name, line=i, recorded_local=r.get('recorded_local'),
                                         observed_local=r.get('observed_local'), numeric_fields=fields,
                                         timing_limit='Manual/message/screenshot metadata, not a time-sampled game series'))
    write_csv(output/'control-probes.csv', PROBE_FIELDS, probes)
    write_json(output/'system-snapshots.json', snapshots)
    write_json(output/'manual-markers.json', markers)
    write_json(output/'manual-numeric-observations.json', observations)
    write_json(output/'monitor-audit.json', audits)
    return dict(game_sources=len(game_sources), game_events=len(events), control_probes=len(probes), system_snapshots=len(snapshots))


class TimedIndex:
    def __init__(self, rows, time_key):
        self.time_key = time_key
        self.rows = sorted(rows, key=lambda r: epoch(r[time_key]))
        self.times = [epoch(r[time_key]) for r in self.rows]

    def window(self, t, seconds):
        return self.rows[bisect_left(self.times, t-seconds):bisect_right(self.times, t+seconds)]

    def nearest(self, t):
        i = bisect_left(self.times, t)
        options = self.rows[max(0, i-1):min(len(self.rows), i+1)]
        return min(options, key=lambda r: abs(epoch(r[self.time_key])-t)) if options else None


def control_summary(rows, t):
    values = sorted(r['rtt_ms'] for r in rows if r['status'] == 'Success' and r['rtt_ms'] is not None)
    nearest = min(rows, key=lambda r: abs(epoch(r['sent_utc'])-t)) if rows else None
    return dict(n=len(rows), statuses=dict(Counter(r['status'] for r in rows)),
                min_ms=min(values) if values else None, max_ms=max(values) if values else None,
                median_ms=statistics.median(values) if values else None,
                nearest={k: nearest[k] for k in ('source', 'seq', 'sent_utc', 'target', 'rtt_ms', 'status')} if nearest else None,
                nearest_delta_seconds=round(epoch(nearest['sent_utc'])-t, 6) if nearest else None)


def classify_controls(controls, limits, min_samples=2):
    by = {r['target']: r for r in controls}
    required = TARGETS[:4]+([TARGETS[4]] if TARGETS[4] in by else [EARLY_RETN])
    complete = all(target in by and by[target]['n'] >= min_samples for target in required)
    if not complete:
        return 'uncovered_or_incomplete', []
    if any('ProbeError' in c['statuses'] for c in controls):
        return 'measurement_error', []
    flags = [target for target, c in by.items() if c['max_ms'] is not None and c['max_ms'] >= limits[target]['threshold_ms']
             or any(status != 'Success' for status in c['statuses'])]
    if TARGETS[0] in flags:
        return 'gateway_control_anomaly', flags
    if TARGETS[1] in flags:
        return 'near_without_gateway_anomaly', flags
    if TARGETS[2] in flags:
        return 'public_without_near_anomaly', flags
    if any(target in flags for target in (TARGETS[3], TARGETS[4], EARLY_RETN)):
        return 'retn_only_control_anomaly', flags
    return 'all_controls_below_threshold', []


def connections(events, stats):
    result = []
    for file in sorted({e['file'] for e in events}):
        current = None
        timeline = sorted([e for e in events if e['file'] == file and e['kind'].startswith('endpoint_')]
                          +[dict(s, kind='netdriver_end') for s in stats if s['file'] == file], key=lambda e: (e['time_utc'], e['line']))
        for e in timeline:
            if e['kind'] == 'endpoint_travel':
                if current is not None and current['end_utc'] is None:
                    current['end_utc'] = e['time_utc']
                    current['end_basis'] = 'next_travel'
                current = dict(connection_id='C'+str(len(result)+1).zfill(3), file=file, ip=e['ip'], port=e['port'],
                               start_utc=e['time_utc'], end_utc=None, end_basis=None, travel_line=e['line'],
                               map_ready_utc=None, received_packet_utc=None, received_packet_line=None)
                result.append(current)
            elif current is not None and e['kind'] == 'netdriver_end':
                current['end_utc'] = e['time_utc']
                current['end_basis'] = 'netdriver_stats'
                current = None
            elif current is not None and (e.get('ip'), e.get('port')) == (current['ip'], current['port']):
                if e['kind'] == 'endpoint_received_packet':
                    current['received_packet_utc'] = e['time_utc']
                    current['received_packet_line'] = e['line']
                if e['kind'] == 'endpoint_map_state' and e['flags'].get('Map Ready') and current['map_ready_utc'] is None:
                    current['map_ready_utc'] = e['time_utc']
    return result


def connection_for(e, conns):
    return next((c for c in conns if c['file'] == e['file'] and c['start_utc'] <= e['time_utc']
                 and (c['end_utc'] is None or e['time_utc'] <= c['end_utc'])), None)


def rate_intervals(snapshots):
    groups = defaultdict(list)
    result = []
    for s in snapshots:
        groups[s['source']].append(s)
    for source, rows in groups.items():
        rows.sort(key=lambda s: epoch(s['time_utc']))
        for a, b in zip(rows, rows[1:]):
            seconds = epoch(b['time_utc'])-epoch(a['time_utc'])
            if not 0 < seconds <= 120:
                continue
            if any(a['counters'].get(k) is None or b['counters'].get(k) is None for k in COUNTERS):
                continue
            delta = {k: b['counters'][k]-a['counters'][k] for k in COUNTERS}
            if any(v < 0 for v in delta.values()):
                continue
            result.append(dict(source=source, start_utc=a['time_utc'], end_utc=b['time_utc'], seconds=round(seconds, 3),
                               rx_mbps=round(delta['ReceivedBytes']*8/seconds/1e6, 6), tx_mbps=round(delta['SentBytes']*8/seconds/1e6, 6),
                               error_discard_deltas={k: delta[k] for k in COUNTERS[2:]}))
    return result


def marker_intervals(markers):
    result, stray = [], []
    for source in sorted({m['source_run'] for m in markers}):
        opened = None
        for m in sorted((r for r in markers if r['eligible'] and r['source_run'] == source and r['source_kind'] == 'RegisterHotKey'),
                        key=lambda r: epoch(r['observed_utc'])):
            if m['event'] == 'spike':
                if opened is None:
                    opened = dict(id='M'+str(len(result)+1).zfill(3), source=source, start_utc=m['observed_utc'],
                                  end_utc=None, spike_presses=0, button_span_seconds=None)
                    result.append(opened)
                opened['spike_presses'] += 1
            elif m['event'] == 'recovery':
                if opened is None:
                    stray.append(m)
                else:
                    opened['end_utc'] = m['observed_utc']
                    opened['button_span_seconds'] = round(epoch(m['observed_utc'])-epoch(opened['start_utc']), 3)
                    opened = None
    return dict(intervals=result, unpaired_recovery_markers=stray,
                timing_limit='Button-to-button duration is not the duration of a measured game RTT level.')


def compare_cycle_context(probes, conns, selected, limits):
    grouped = defaultdict(list)
    for r in probes:
        grouped[(r['source'], r['cycle'])].append(r)
    cycles = []
    by_conn_events = defaultdict(list)
    for e in selected:
        c = connection_for(e, conns)
        if c:
            by_conn_events[c['connection_id']].append(epoch(e['time_utc']))
    for (source, cycle), group in grouped.items():
        t = min(epoch(r['sent_utc']) for r in group)
        if len({r['target'] for r in group}) != 5:
            continue
        controls = [dict(target=r['target'], **control_summary([r], t)) for r in group]
        category, flags = classify_controls(controls, limits, min_samples=1)
        conn = next((c for c in conns if epoch(c['map_ready_utc'] or c['start_utc']) <= t
                     and c['end_utc'] is not None and t <= epoch(c['end_utc'])), None)
        nearby = bool(conn and any(abs(t-ping) <= 4 for ping in by_conn_events[conn['connection_id']]))
        cycles.append(dict(source=source, cycle=cycle,
                           sent_utc=datetime.fromtimestamp(t, UTC).isoformat(timespec='milliseconds'),
                           connection_id=conn['connection_id'] if conn else None,
                           class_name=category, exceeded_targets=flags, within_4s_of_band_event=nearby,
                           values_ms={r['target']: r['rtt_ms'] for r in group},
                           statuses={r['target']: r['status'] for r in group}))
    active = [c for c in cycles if c['connection_id']]
    adjacent = [c for c in active if c['within_4s_of_band_event']]
    other = [c for c in active if not c['within_4s_of_band_event']]
    return cycles, dict(all_valid_five_target_cycles=len(cycles), cycles_during_logged_connections=len(active),
                        event_adjacent_cycles=len(adjacent), other_connection_cycles=len(other),
                        event_adjacent_classes=dict(Counter(c['class_name'] for c in adjacent)),
                        other_connection_classes=dict(Counter(c['class_name'] for c in other)),
                        not_a_causal_or_independent_statistical_test=True,
                        comparison_limit='Other cycles have unknown game RTT; they are not labelled normal. Adjacent windows are unioned, not counted repeatedly.')


def analyze(inputs, output):
    output.mkdir(parents=True, exist_ok=True)
    events = read_json(inputs/'game-events.json')
    stats = read_json(inputs/'netdriver-stats.json')
    limits = read_json(inputs/'thresholds.json')
    with (inputs/'control-probes.csv').open(encoding='utf-8-sig', newline='') as h:
        rows = list(csv.DictReader(h))
    for r in rows:
        r['rtt_ms'] = float(r['rtt_ms']) if r['rtt_ms'] else None
        r['seq'] = int(r['seq'])
    probes = [r for r in rows if r['eligible'] == '1']
    by_target = {target: TimedIndex([r for r in probes if r['target'] == target], 'sent_utc') for target in limits}
    snapshots = read_json(inputs/'system-snapshots.json')
    snapshot_index = TimedIndex(snapshots, 'time_utc')
    markers = read_json(inputs/'manual-markers.json')
    marker_index = TimedIndex([m for m in markers if m['eligible']], 'observed_utc')
    conns = connections(events, stats)
    rates = rate_intervals(snapshots)
    relevant = [e for e in events if e['kind'] in ('framerate_threshold', 'burst_loss', 'burst_loss_end', 'queue_overflow',
                                                   'input_replication_stopped', 'saved_moves_limit', 'endpoint_received_packet',
                                                   'remote_movement_time_index')]
    warnings_by_file = {f: TimedIndex([e for e in relevant if e['file'] == f], 'time_utc') for f in {e['file'] for e in events}}
    os_data = read_json(inputs/'windows-network-events.json') if (inputs/'windows-network-events.json').exists() else None
    os_rows = [dict(e, log=g['log']) for g in os_data['groups'] for e in g['events']] if os_data else []
    if any(not (epoch(START) <= epoch(e['time_utc']) < epoch(END)) for e in os_rows):
        raise ValueError('System event outside requested UTC bounds')
    os_index = TimedIndex(os_rows, 'time_utc')
    pings = [e for e in events if e['kind'] == 'ping_threshold']
    selected = [e for e in pings if 90 <= e['value'] <= 180]
    result, previous = [], {}
    for e in pings:
        conn = connection_for(e, conns)
        key = conn['connection_id'] if conn else e['file']+'-unbound'
        prev = previous.get(key)
        previous[key] = e
        if e not in selected:
            continue
        t = epoch(e['time_utc'])
        contexts = []
        for window in (1, 2, 4, 10):
            controls = []
            for target, index in by_target.items():
                found = index.window(t, window)
                if found:
                    controls.append(dict(target=target, **control_summary(found, t)))
            # At ±1 s a two-second sampler may yield one result per target.
            category, flags = classify_controls(controls, limits, min_samples=1 if window == 1 else 2)
            contexts.append(dict(window_seconds=window, controls=controls, category=category, exceeded_targets=flags))
        warn = warnings_by_file[e['file']].window(t, 10)
        fps = [w for w in warn if w['kind'] == 'framerate_threshold' and w.get('metric') == 'local_fps']
        recent = [dict(event_id=w['event_id'], kind=w['kind'], time_utc=w['time_utc'], line=w['line'],
                       delta_seconds=round(epoch(w['time_utc'])-t, 6),
                       **{k: w[k] for k in ('value', 'active', 'queue', 'dropped_this_second', 'difference') if k in w}) for w in warn]
        snap = snapshot_index.nearest(t)
        snapshot = dict(snap, delta_seconds=round(epoch(snap['time_utc'])-t, 6)) if snap and abs(epoch(snap['time_utc'])-t) <= 45 else None
        rate = next((r for r in rates if epoch(r['start_utc']) <= t <= epoch(r['end_utc'])), None)
        nearby = marker_index.window(t, 60)
        result.append(dict(id='E'+str(len(result)+1).zfill(3), **e, baseline_rtt_ms=None, duration_seconds=None,
                           previous_logged_ping_ms=prev['value'] if prev else None,
                           previous_logged_ping_utc=prev['time_utc'] if prev else None,
                           seconds_since_previous_logged_ping=round(t-epoch(prev['time_utc']), 3) if prev else None,
                           delta_from_previous_logged_ping_ms=round(e['value']-prev['value'], 3) if prev else None,
                           connection=conn,
                           endpoint_evidence=('application_received_packet_in_connection' if conn and conn['received_packet_utc']
                                              else 'travel_map_ready_association' if conn and conn['map_ready_utc'] else 'travel_only' if conn else 'unknown'),
                           control_windows=contexts, nearby_game_warnings=recent,
                           local_fps_within_1s=any(abs(epoch(w['time_utc'])-t) <= 1 for w in fps),
                           local_fps_within_4s=any(abs(epoch(w['time_utc'])-t) <= 4 for w in fps),
                           local_fps_within_10s=bool(fps), nearest_snapshot=snapshot, containing_rate_interval=rate,
                           windows_network_events_within_30s=[dict(w, delta_seconds=round(epoch(w['time_utc'])-t, 6)) for w in os_index.window(t, 30)],
                           manual_markers_within_60s=[dict(m, delta_seconds=round(epoch(m['observed_utc'])-t, 6)) for m in nearby]))
    cycles, cycle_comparison = compare_cycle_context(probes, conns, selected, limits)
    summary = dict(events=len(result), bands=dict(Counter(band_label(e['value']) for e in result)),
                   by_file={file: dict(n=sum(e['file'] == file for e in result), min_ms=min(e['value'] for e in result if e['file'] == file),
                                       max_ms=max(e['value'] for e in result if e['file'] == file)) for file in sorted({e['file'] for e in result})},
                   control_categories={str(w): dict(Counter(next(c['category'] for c in e['control_windows'] if c['window_seconds'] == w) for e in result)) for w in (1, 2, 4, 10)},
                   local_fps_overlap={str(w): sum(e['local_fps_within_'+str(w)+'s'] for e in result) for w in (1, 4, 10)},
                   all_ping_events_in_scope=len(pings), ping_events_outside_90_180=len(pings)-len(result),
                   game_connections=len(conns), eligible_control_probes=len(probes), all_control_rows=len(rows),
                   marker_counts={source: dict(Counter(m['event'] for m in markers if m['source_run'] == source and m['source_kind'] == 'RegisterHotKey')) for source in sorted({m['source_run'] for m in markers})},
                   max_control_time= max(r['sent_utc'] for r in probes),
                   duration_or_exact_baseline_available_events=0)
    summary['cycle_comparison'] = cycle_comparison
    summary['system_network_events'] = dict(available=os_data is not None, counts={g['log']: len(g['events']) for g in os_data['groups']} if os_data else {},
                                            matched_within_30s=sum(bool(e['windows_network_events_within_30s']) for e in result))
    summary['event_rate_context'] = dict(available=sum(e['containing_rate_interval'] is not None for e in result),
                                         max_rx_mbps=max((e['containing_rate_interval']['rx_mbps'] for e in result if e['containing_rate_interval']), default=None),
                                         max_tx_mbps=max((e['containing_rate_interval']['tx_mbps'] for e in result if e['containing_rate_interval']), default=None))
    summary['by_local_date'] = dict(Counter(e['time_local'][:10] for e in result))
    summary['endpoint_evidence_counts'] = dict(Counter(e['endpoint_evidence'] for e in result))
    summary['covered_events_without_fps_threshold_within_4s'] = sum(e['control_windows'][2]['category'] != 'uncovered_or_incomplete' and not e['local_fps_within_4s'] for e in result)
    full_route_snapshots = [s for s in snapshots if s['selected_routes']]
    route_signatures = {json.dumps(sorted(s['selected_routes'], key=lambda r:r['target']), sort_keys=True) for s in full_route_snapshots}
    summary['route_snapshot_context'] = dict(full_snapshots=len(full_route_snapshots), distinct_selected_route_signatures=len(route_signatures),
                                            limit='Windows routes to control targets, not per-packet Riot routes or BGP.')
    summary['wifi_context'] = dict(snapshots=len(snapshots), disconnected_snapshots=sum(s['connected'] is False for s in snapshots),
                                   ap_aliases=sorted({s['ap_alias'] for s in snapshots if s['ap_alias']}),
                                   channels=sorted({s['channel'] for s in snapshots if s['channel'] is not None}),
                                   event_snapshot_rssi_dbm=[min(e['nearest_snapshot']['rssi_dbm'] for e in result if e['nearest_snapshot'] and e['nearest_snapshot']['rssi_dbm'] is not None),
                                                            max(e['nearest_snapshot']['rssi_dbm'] for e in result if e['nearest_snapshot'] and e['nearest_snapshot']['rssi_dbm'] is not None)],
                                   rate_intervals=len(rates), error_discard_delta_sums={k:sum(r['error_discard_deltas'][k] for r in rates) for k in COUNTERS[2:]})
    write_json(output/'events-90-180.json', result)
    write_json(output/'summary.json', summary)
    write_json(output/'connections.json', conns)
    write_json(output/'wifi-rate-intervals.json', rates)
    write_json(output/'marker-intervals.json', marker_intervals(markers))
    write_json(output/'cycle-context-summary.json', cycle_comparison)
    write_json(output/'consecutive-logged-points.json', [dict(id=e['id'], connection_id=e['connection']['connection_id'] if e['connection'] else None,
                    previous_time_utc=e['previous_logged_ping_utc'], previous_rtt_ms=e['previous_logged_ping_ms'],
                    time_utc=e['time_utc'], rtt_ms=e['value'], difference_ms=e['delta_from_previous_logged_ping_ms'],
                    point_separation_seconds=e['seconds_since_previous_logged_ping'],
                    transition_duration_seconds=None, baseline_rtt_ms=None) for e in result if e['previous_logged_ping_ms'] is not None])
    write_csv(output/'control-cycles.csv', ['source','cycle','sent_utc','connection_id','class_name','within_4s_of_band_event',
                                          'gateway_ms','near_ms','cloudflare_ms','retn1_ms','retn2_ms','retn_early_ms'],
              [dict(**{k:c[k] for k in ('source','cycle','sent_utc','connection_id','class_name','within_4s_of_band_event')},
                    **{k:c['values_ms'].get(target) for k,target in zip(['gateway_ms','near_ms','cloudflare_ms','retn1_ms','retn2_ms','retn_early_ms'],TARGETS+[EARLY_RETN])}) for c in cycles])
    write_csv(output/'events-90-180.csv', ['id', 'time_utc', 'time_local', 'file', 'line', 'rtt_ms', 'previous_logged_ping_ms',
                                         'seconds_since_previous_logged_ping', 'endpoint', 'endpoint_evidence', 'control_class_4s',
                                         'local_fps_within_1s', 'baseline_rtt_ms', 'duration_seconds'],
              [dict(id=e['id'], time_utc=e['time_utc'], time_local=e['time_local'], file=e['file'], line=e['line'], rtt_ms=e['value'],
                    previous_logged_ping_ms=e['previous_logged_ping_ms'], seconds_since_previous_logged_ping=e['seconds_since_previous_logged_ping'],
                    endpoint=f"{e['connection']['ip']}:{e['connection']['port']}" if e['connection'] else None,
                    endpoint_evidence=e['endpoint_evidence'], control_class_4s=e['control_windows'][2]['category'],
                    local_fps_within_1s=int(e['local_fps_within_1s']), baseline_rtt_ms=None, duration_seconds=None) for e in result])
    return result, summary, probes, conns


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare')
    p.add_argument('--project', type=Path, required=True)
    p.add_argument('--game-dir', type=Path, required=True, help='Already frozen private ShooterGame logs, outside Git')
    p.add_argument('--game-manifest', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--watermarks', type=Path, help='Reuse previously recorded canonical prefix boundaries')
    a = sub.add_parser('analyze')
    a.add_argument('--inputs', type=Path, required=True)
    a.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    if args.command == 'prepare':
        print(json.dumps(prepare(args.project, args.game_dir, args.game_manifest, args.output, args.watermarks)))
    else:
        _, summary, _, _ = analyze(args.inputs, args.output)
        print(json.dumps({k:summary[k] for k in ('events','bands','eligible_control_probes','all_control_rows','duration_or_exact_baseline_available_events')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
