"""Offline RRT analysis: explicit field allowlists, no raw log publication.

Python standard library only. No network, game, process-memory or settings access.
Use a PRIVATE scratch directory outside a Git repository for extracted sources.
Output is a technical derivative, still requiring human review before publication.
"""
import argparse
import collections
import datetime as dt
import hashlib
import ipaddress
import json
import math
from pathlib import Path, PurePosixPath
import re
import stat
import statistics
import xml.etree.ElementTree as ET
import zipfile

UTC = dt.timezone.utc
LOCAL = dt.timezone(dt.timedelta(hours=5))
STAMP = re.compile(r'^\[(\d{4}\.\d{2}\.\d{2}-\d{2}\.\d{2}\.\d{2}:\d{3})\]')
GAME_NAME = re.compile(r'^ShooterGame(?:-backup-\d{4}\.\d{2}\.\d{2}-\d{2}\.\d{2}\.\d{2})?\.log$')
UUID = r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}'
IPPORT = re.compile(r'\b((?:\d{1,3}\.){3}\d{1,3}):(\d{1,5})\b')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def safe_member(name):
    normalized = name.replace('\\', '/')
    p = PurePosixPath(normalized)
    if p.is_absolute() or '..' in p.parts or ':' in normalized or '\x00' in normalized:
        raise ValueError('Unsafe archive member')
    return p


def selected(group, basename):
    return ((group == 'system' and basename in ('DxDiag.txt', 'NetworkInfo.txt', 'Process.txt'))
            or (group in ('VALORANT Logs', 'Riot Client Logs') and basename.endswith('.log'))
            or (group == 'VALORANT Config' and basename in ('GameUserSettings.ini', 'RiotUserSettings.ini'))
            or (group == 'VALORANT Crashes' and basename == 'CrashContext.runtime-xml'))


def inventory_extract(source, scratch):
    archives, members, extracted, seen = [], [], [], {}
    total = 0
    for archive in sorted(source.glob('*.zip')):
        data = archive.read_bytes()
        sha = digest(data)
        archive_alias = f'archive-{len(archives)+1:02d}'
        item = dict(archive=archive.name, bytes=len(data), sha256=sha,
                    mtime_utc=dt.datetime.fromtimestamp(archive.stat().st_mtime, UTC).isoformat(),
                    duplicate_of=seen.get(sha))
        archives.append(item)
        if sha in seen:
            continue
        seen[sha] = archive.name
        with zipfile.ZipFile(archive) as z:
            item['members'] = len(z.infolist())
            item['expanded_bytes'] = sum(i.file_size for i in z.infolist())
            for n, info in enumerate(z.infolist(), 1):
                p = safe_member(info.filename)
                mode = info.external_attr >> 16
                if info.flag_bits & 1 or stat.S_ISLNK(mode):
                    raise ValueError('Encrypted or symbolic archive member')
                if info.file_size > 64 * 1024**2 or info.file_size / max(info.compress_size, 1) > 1000:
                    raise ValueError('Archive size/ratio limit')
                total += info.file_size
                if total > 1024**3:
                    raise ValueError('Expanded archive total exceeds 1 GiB')
                group = p.parts[0] if len(p.parts) > 1 else 'system'
                base = p.name
                alias = f'{archive_alias}-member-{n:04d}'
                # Names from account, crash, Vanguard and client configuration trees stay private.
                public_name = base if group in ('system', 'VALORANT Logs', 'Riot Client Logs') else alias + p.suffix
                if group == 'Riot Vanguard Logs' and re.fullmatch(r'vg[ck]_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.log', base):
                    public_name = base
                take = not info.is_dir() and selected(group, base)
                entry = dict(file_id=alias, group=group, name=public_name, bytes=info.file_size,
                             compressed_bytes=info.compress_size, zip_local_time=list(info.date_time),
                             analyzed=take)
                members.append(entry)
                if not take:
                    continue
                # Never reproduce untrusted account/directory names on disk.
                target = scratch / alias / base
                target.parent.mkdir(parents=True, exist_ok=True)
                payload = z.read(info)  # also verifies member CRC
                target.write_bytes(payload)
                entry['sha256'] = digest(payload)
                extracted.append((entry, target))
        # Confirm extraction did not alter the original archive.
        if digest(archive.read_bytes()) != sha:
            raise ValueError('Original archive changed during analysis')
    return archives, members, extracted


def times(raw):
    utc = dt.datetime.strptime(raw, '%Y.%m.%d-%H.%M.%S:%f').replace(tzinfo=UTC)
    return {'time_utc': utc.isoformat(timespec='milliseconds'),
            'time_local': utc.astimezone(LOCAL).isoformat(timespec='milliseconds')}


def parse_game(text, file_id, filename):
    lines = text.splitlines()
    events, stats, stamp_rows = [], [], []
    for n, line in enumerate(lines, 1):
        stamp = STAMP.match(line)
        if not stamp:
            continue
        raw = stamp[1]
        stamp_rows.append((n, raw))
        base = dict(file_id=file_id, file=filename, line=n, **times(raw))
        def emit(kind, **fields):
            events.append(dict(base, kind=kind, **fields))
        # Known engine event formats only. Never forward arbitrary message text.
        m = re.search(r'LogInstabilityTrackingDetails: Error: (Average Ping|Local Framerate|Server Framerate) Threshold (critically )?exceeded! Current: ([\d.]+), Threshold: ([\d.]+)', line)
        if m:
            emit('ping_threshold' if m[1] == 'Average Ping' else 'framerate_threshold',
                 metric={'Average Ping': 'average_ping_ms', 'Local Framerate': 'local_fps', 'Server Framerate': 'server_fps'}[m[1]],
                 critical=bool(m[2]), value=float(m[3]), threshold=float(m[4]))
        m = re.search(r'LogAresNetDriver: Warning: \[NetworkErrorState\] Outgoing (Input|Movement) Queue Overflow - (ACTIVE|inactive)', line)
        if m:
            emit('queue_overflow', queue=m[1].lower(), active=m[2] == 'ACTIVE')
        if 'LogAresInputStateComponent:' in line and 'Stopping input replication to server (MaxUnacknowledgedInputDuration exceeded)' in line:
            emit('input_replication_stopped', reason='MaxUnacknowledgedInputDuration exceeded')
        m = re.search(r'LogAresNetDriver: Warning: \[Client\] Burst Loss Detected!\s+(\d+) packets dropped this second \(>= (\d+)\)', line)
        if m:
            emit('burst_loss', dropped_this_second=int(m[1]), threshold_packets=int(m[2]))
        if 'LogAresNetDriver: Warning: Burst Loss no longer detected.' in line:
            emit('burst_loss_end')
        if 'LogNetPlayerMovement:' in line and 'Hit limit of 96 saved moves' in line:
            emit('saved_moves_limit', limit=96)
        m = re.search(r'LogRemoteClientMovementComponent: Warning: TimeIndexDiff was negative .*TimeIndexDiff: (-?\d+)\)', line)
        if m:
            emit('remote_movement_time_index', difference=int(m[1]))
        if 'XmppTcpSocket' in line and 'Select timed out waiting to read in 0ms' in line:
            emit('chat_zero_ms_select_timeout')
        if 'LogRNetVoiceManager:' in line and 'UpdateReconnectStatus' in line:
            if 'No longer reconnecting' in line:
                emit('voice_reconnect_state', reconnecting=False)
            elif 'Now reconnecting' in line:
                emit('voice_reconnect_state', reconnecting=True)
        if 'LogAresNetDriver: Printing NetDriver Stats' in line:
            values = {}
            for following in lines[n:n+9]:
                m = re.match(r'\s*->\s*(TotalLifetime|InTotalPackets|InTotalPacketsLost|InOutOfOrderPackets|InTotalBytes|OutTotalBytes):\s*([\d.]+)(?:s)?(?:\s*\(([\d.]+)(%|/sec)\))?', following)
                if m:
                    values[m[1]] = float(m[2]) if m[1] == 'TotalLifetime' else int(m[2])
                    if m[3]:
                        values[m[1] + ('_printed_percent' if m[4] == '%' else '_per_second')] = float(m[3])
            stats.append(dict(base, **values))
        endpoints = IPPORT.findall(line)
        if endpoints and any(cat in line for cat in ('LogTravelManager:', 'LogMapLoadModel:', 'LogNet:')):
            for ip, port in endpoints:
                ipaddress.IPv4Address(ip)
                if not 0 < int(port) < 65536:
                    continue
                if 'LogTravelManager: Beginning travel to' in line:
                    emit('endpoint_travel', ip=ip, port=int(port))
                elif 'LogMapLoadModel:' in line and '[URL:' in line:
                    flags = {key: bool(re.search(r'\['+key+r': TRUE', line)) for key in ('Match Setup', 'Map Ready', 'Map Complete')}
                    emit('endpoint_map_state', ip=ip, port=int(port), flags=flags)
                elif 'UNetConnection::ReceivedPacket' in line and 'RemoteAddr:' in line:
                    m = re.search(r'Too many received packets to ack \((\d+)\).*InSeq: (\d+)', line)
                    emit('endpoint_received_packet', ip=ip, port=int(port),
                         received_ack_limit=int(m[1]) if m else None, in_sequence=int(m[2]) if m else None)
        m = re.search(r'LogPingManager: Warning: Failure to ping endpoint (aresriot\.[a-z0-9.-]+), not reporting stats\.', line)
        if m:
            emit('regional_probe_failure', regional_label=m[1])
        if 'QueryName: [Latency_Stats]' in line and 'Platform HTTP Query End' in line:
            m = re.search(r'Response Code: \[(\d{3})\].*Seconds Since Query \[([\d.]+)\]', line)
            if m:
                emit('http_latency_stats_upload', response_code=int(m[1]), elapsed_seconds=float(m[2]))
        if 'LogMatchDetailsManager:' in line and 'HTTPStatus: 404' in line and 'MATCH_NOT_FOUND' in line:
            emit('match_details_http_404')
        # Stable opaque match alias; never an original account/match identifier.
        m = re.search(r'(?:MatchId: |match id: |NewMatchID: )('+UUID+')', line)
        if m and any(cat in line for cat in ('LogLoadTimeMetrics:', 'LogMatchDetailsManager:', 'LogCoreGameManager:')):
            emit('match_alias', alias='match-'+digest(m[1].lower().encode())[:12])
    coverage = dict(file_id=file_id, file=filename, lines=len(lines),
                    first=times(stamp_rows[0][1]) if stamp_rows else None,
                    last=times(stamp_rows[-1][1]) if stamp_rows else None)
    if lines and lines[0].startswith('Log file open,') and stamp_rows:
        opened = dt.datetime.strptime(lines[0].split(', ', 1)[1], '%m/%d/%y %H:%M:%S')
        first = dt.datetime.strptime(stamp_rows[0][1], '%Y.%m.%d-%H.%M.%S:%f')
        coverage['header_minus_first_stamp_seconds'] = round((opened-first).total_seconds(), 3)
    return coverage, events, stats


def read_records(folder, max_seq=None, time_start=None, time_end=None):
    records = []
    last_seq = 0
    for f in sorted(folder.glob('telemetry-*.jsonl')):
        with f.open(encoding='utf-8-sig') as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    raise ValueError('Incomplete/invalid saved telemetry; freeze a committed prefix first')
                if max_seq is not None and row['seq'] > max_seq:
                    return records
                last_seq = row['seq']
                if (time_start is None or row['time_utc'] >= time_start) and (time_end is None or row['time_utc'] <= time_end):
                    records.append(row)
                if max_seq is not None and last_seq == max_seq:
                    return records
    if max_seq is not None and last_seq < max_seq:
        raise ValueError('Committed telemetry watermark not found')
    return records


def summarize_window(records, start, end):
    groups = collections.defaultdict(list)
    for row in records:
        if row.get('kind') == 'probe' and start <= row['time_utc'] <= end:
            groups[row['target']].append(row)
    out = []
    for target, rows in sorted(groups.items()):
        good = [r['rtt_ms'] for r in rows if r['status'] == 'Success' and r.get('rtt_ms') is not None]
        good.sort()
        out.append(dict(target=target, n=len(rows), statuses=dict(collections.Counter(r['status'] for r in rows)),
                        first_utc=min(r['time_utc'] for r in rows), last_utc=max(r['time_utc'] for r in rows),
                        min_ms=min(good) if good else None, median_ms=statistics.median(good) if good else None,
                        avg_ms=round(statistics.mean(good), 3) if good else None,
                        max_ms=max(good) if good else None, p95_ms=good[math.ceil(.95*len(good))-1] if good else None))
    return out


def correlate(events, records):
    probes = [r for r in records if r.get('kind') == 'probe']
    markers = [r for r in records if r.get('kind') == 'game_marker']
    output = []
    for e in events:
        if e['kind'] not in ('ping_threshold', 'burst_loss', 'queue_overflow', 'input_replication_stopped', 'framerate_threshold', 'endpoint_received_packet'):
            continue
        t = dt.datetime.fromisoformat(e['time_utc'])
        near = []
        for m in markers:
            delta = (dt.datetime.fromisoformat(m['time_utc'])-t).total_seconds()
            if abs(delta) <= 5:
                # Only known semantic marker labels, not arbitrary user note text.
                label = m.get('event', m.get('marker', m.get('label')))
                source = m.get('source')
                near.append(dict(time_utc=m['time_utc'], seq=m['seq'], label=label if label in ('spike', 'recovery', 'note') else None,
                                 source=source if source in ('RegisterHotKey', 'user_report_at_message_entry', 'user_retrospective_report') else None,
                                 observed_utc=m.get('observed_utc'),
                                 delta_seconds=round(delta, 3)))
        output.append(dict(file=e['file'], line=e['line'], kind=e['kind'], time_utc=e['time_utc'], time_local=e['time_local'],
                           window_seconds=4, controls=summarize_window(probes, (t-dt.timedelta(seconds=4)).isoformat(timespec='milliseconds'),
                                                                     (t+dt.timedelta(seconds=4)).isoformat(timespec='milliseconds')),
                           markers_within_5_seconds=near))
    return output


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source', type=Path, required=True)
    ap.add_argument('--scratch', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--day-telemetry', type=Path)
    ap.add_argument('--live-telemetry', type=Path,
                    help='Read only the committed prefix from status.json; never stop the live monitor')
    args = ap.parse_args()
    for destination in (args.scratch.resolve(), args.output.resolve()):
        if destination == args.source.resolve() or args.source.resolve() in destination.parents:
            raise ValueError('Scratch and output must be outside the source directory')
    # Prevent accidental tracking of extracted credentials/identifiers, even in a private clone.
    if any((parent/'.git').exists() for parent in (args.scratch.resolve(), *args.scratch.resolve().parents)):
        raise ValueError('Private extraction scratch must be outside Git repositories')
    args.output.mkdir(parents=True, exist_ok=True)
    archives, members, files = inventory_extract(args.source, args.scratch)
    coverage, events, stats, auxiliary = [], [], [], []
    crash_number = 0
    for entry, path in files:
        if entry['group'] == 'VALORANT Logs' and GAME_NAME.fullmatch(path.name):
            c, ev, st = parse_game(path.read_text(encoding='utf-8-sig'), entry['file_id'], path.name)
            coverage.append(c)
            events.extend(ev)
            stats.extend(st)
        elif entry['group'] == 'VALORANT Crashes':
            root = ET.fromstring(path.read_text(encoding='utf-8-sig'))
            ticks = root.findtext('.//TimeOfCrash')
            crash_number += 1
            auxiliary.append(dict(file_id=entry['file_id'], kind='historical_crash',
                                  time_from_ticks=(dt.datetime(1, 1, 1)+dt.timedelta(microseconds=int(ticks)//10)).isoformat() if ticks else None,
                                  clock_basis='TimeOfCrash ticks; not used for November correlation',
                                  crash_type=root.findtext('.//CrashType'),
                                  seconds_since_start=root.findtext('.//SecondsSinceStart')))
        elif entry['group'] in ('Riot Client Logs', 'VALORANT Logs'):
            text = path.read_text(encoding='utf-8-sig', errors='replace')
            hist = []
            for i, line in enumerate(text.splitlines(), 1):
                m = re.match(r'Histogram: (Net\.[A-Za-z0-9_.]+) recorded (\d+) samples(?:, mean = ([\d.]+))?', line)
                if m:
                    hist.append(dict(line=i, metric=m[1], samples=int(m[2]), mean=float(m[3]) if m[3] else None))
            auxiliary.append(dict(file_id=entry['file_id'], kind='client_or_cef', lines=len(text.splitlines()),
                                  bootstrap_already_running='Client already running, exiting.' in text,
                                  cef_network_histograms=hist,
                                  explicit_browser_error_counts={key: text.count(key) for key in ('ERR_CONNECTION_RESET', 'ERR_CONNECTION_TIMED_OUT', 'ERR_NAME_NOT_RESOLVED', 'ERR_INTERNET_DISCONNECTED')},
                                  has_internal_2026_11_14='2026-11-14' in text,
                                  has_internal_2026_11_15='2026-11-15' in text))
        elif entry['group'] == 'VALORANT Config':
            values = {}
            for line in path.read_text(encoding='utf-8-sig').splitlines():
                m = re.fullmatch(r'(EAresIntSettingName::PlayerPerfShow(?:NetworkRtt|PacketLossPercentage|PacketsLostTotal|IncomingPacketLossPercentage|OutgoingPacketLossPercentage))=(\d+)', line)
                if m:
                    values[m[1]] = int(m[2])
            auxiliary.append(dict(file_id=entry['file_id'], kind='ui_stat_configuration_not_measurements', values=values))
    def write(name, value):
        (args.output/name).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    write('inventory.json', dict(archives=archives, members=members,
                               extracted_files=len(files), total_extracted_bytes=sum(e['bytes'] for e, _ in files),
                               note='Only allowlisted technical derivatives are exported; all extracted sources stay in private scratch.'))
    write('game-coverage.json', coverage)
    events.sort(key=lambda e: (e['time_utc'], e['file'], e['line']))
    write('game-events.json', events)
    write('netdriver-lifetime-stats.json', stats)
    write('auxiliary-summary.json', auxiliary)
    if args.day_telemetry:
        records = read_records(args.day_telemetry)
        write('day-correlations.json', correlate(events, records))
        write('day-manual-markers.json', [{k: r.get(k) for k in ('seq', 'time_utc', 'time_local', 'observed_utc', 'event', 'source')}
                                          for r in records if r.get('kind') == 'game_marker' and r.get('event') in ('spike', 'recovery', 'note')])
        critical = [e for e in events if e['kind'] == 'ping_threshold' and e['critical']]
        day = [e for e in critical if e['time_utc'].startswith('2026-11-14T09:')]
        windows = [('critical_log_span', day[0]['time_utc'], day[-1]['time_utc'])] if day else []
        windows.extend([('pre_escalation', '2026-11-14T09:11:26.000+00:00', '2026-11-14T09:27:44.000+00:00'),
                        ('post_restart', '2026-11-14T09:32:00.000+00:00', '2026-11-14T09:49:20.962+00:00')])
        write('day-window-statistics.json', [dict(label=label, start_utc=start, end_utc=end,
                                                  controls=summarize_window(records, start, end)) for label, start, end in windows])
        colors = ['#1768ac', '#198754', '#a6761d', '#7a42a8', '#008b8b']
        targets = ['192.168.123.1', '89.38.164.205', '1.1.1.1', '87.245.238.34', '87.245.233.166']
        charts = []
        for label, start, end in [('day', '2026-11-14T09:10:00.000+00:00', '2026-11-14T09:49:44.000+00:00'),
                                  ('critical', '2026-11-14T09:27:30.000+00:00', '2026-11-14T09:30:10.000+00:00')]:
            series = [dict(name=target, color=color, points=[dict(x=r['time_local'], y=r['rtt_ms']) for r in records
                         if r.get('kind') == 'probe' and r['target'] == target and r['status'] == 'Success' and start <= r['time_utc'] <= end])
                      for target, color in zip(targets, colors)]
            series.append(dict(name='Valorant Average Ping: logged threshold events only', color='#d62728', chart_type='Point',
                               points=[dict(x=e['time_local'], y=e['value']) for e in events
                                       if e['kind'] == 'ping_threshold' and start <= e['time_utc'] <= end]))
            charts.append(dict(name='rrt-'+label+'.png', title='Valorant log events and Windows ICMP / 14 November 2026',
                               x_label='Local time UTC+05:00; red points are sparse events, not a continuous game series',
                               y_label='RTT (ms)', y_min=0, y_max=420, series=series))
        write('chart-specs.json', charts)
    if args.live_telemetry:
        status = json.loads((args.live_telemetry/'status.json').read_text(encoding='utf-8-sig'))
        watermark = status['committed_seq']
        late_start, late_end = '2026-11-14T11:32:00.000+00:00', '2026-11-14T11:39:00.000+00:00'
        rows = read_records(args.live_telemetry, watermark, late_start, late_end)
        write('late-correlations.json', dict(committed_seq=watermark, heartbeat_utc=status['heartbeat_utc'],
                                             selected_start_utc=late_start, selected_end_utc=late_end,
                                             controls=summarize_window(rows, late_start, late_end),
                                             events=correlate([e for e in events if late_start <= e['time_utc'] <= late_end], rows)))
    print(json.dumps(dict(archives=len(archives), unique_archives=sum(a['duplicate_of'] is None for a in archives),
                          extracted=len(files), game_logs=len(coverage), events=len(events), stats=len(stats)), ensure_ascii=False))


if __name__ == '__main__':
    main()
