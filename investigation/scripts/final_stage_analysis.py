"""Reproducible audit and paired-cycle analysis of the stopped schema-3 monitor."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from continuous_monitor import resolve_run, read_json
from analyze_session import summarize

LOCAL=timezone(timedelta(hours=5))
TARGETS=['192.168.123.1','89.38.164.205','1.1.1.1','87.245.238.34','87.245.233.166']
LABELS=['Домашний шлюз','Meganet near-hop','Cloudflare','RETN 238.34','RETN sto 233.166']
COLORS=['#1768ac','#2e8b57','#d18b00','#b33f62','#7749ae']


def dt(value):
    return datetime.fromisoformat(value.replace('Z','+00:00'))


def percentile(values,p):
    return sorted(values)[max(0,math.ceil(len(values)*p)-1)] if values else None


def metrics(values):
    return dict(n=len(values),min=min(values),median=statistics.median(values),avg=round(statistics.mean(values),3),
                p95=percentile(values,.95),p99=percentile(values,.99),max=max(values)) if values else dict(n=0)


def classify(values,limits):
    if values[TARGETS[0]]>=limits[TARGETS[0]]:
        return 'local_threshold'
    if values[TARGETS[1]]>=limits[TARGETS[1]]:
        return 'near_hop_without_gateway_threshold'
    if values[TARGETS[2]]>=limits[TARGETS[2]]:
        return 'public_without_local_threshold'
    if any(values[t]>=limits[t] for t in TARGETS[3:]):
        return 'transit_only_threshold'
    return 'below_all_thresholds'


def correlation(left,right):
    try:
        return round(statistics.correlation(left,right),4)
    except statistics.StatisticsError:
        return None


def read_complete(run):
    rows=[]; segments=[]; manifest=read_json(run/'segments.json')
    for file in sorted(run.glob('telemetry-*.jsonl')):
        raw=file.read_bytes(); parsed=[]
        for line in raw.splitlines():
            parsed.append(json.loads(line))
        declaration=next((s for s in manifest['segments'] if s['name']==file.name),{})
        actual=dict(name=file.name,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),records=len(parsed),
                    first_seq=parsed[0]['seq'],last_seq=parsed[-1]['seq'],newline_terminated=raw.endswith(b'\n'))
        actual['manifest_first_seq']=declaration.get('first_seq'); actual['manifest_last_seq']=declaration.get('last_seq')
        actual['bounds_match']=actual['first_seq']==declaration.get('first_seq') and actual['last_seq']==declaration.get('last_seq')
        actual['bytes_match']=actual['bytes']==declaration.get('bytes')
        segments.append(actual); rows+=parsed
    return rows,segments,manifest


def wlan_fields(text):
    def match(pattern,cast=str):
        found=re.search(pattern,text,re.I|re.M)
        return cast(found[1]) if found else None
    return dict(rssi_dbm=match(r'^\s*Rssi\s*:\s*(-?\d+)',int),
                channel=match(r'^\s*Channel\s*:\s*(\d+)',int),
                band=match(r'^\s*Band\s*:\s*(.+)'),
                bssid=match(r'^\s*AP BSSID\s*:\s*(\S+)'),
                state=match(r'^\s*State\s*:\s*(\S+)'),
                rx_phy_mbps=match(r'^\s*Receive rate \(Mbps\)\s*:\s*([\d.]+)',float),
                tx_phy_mbps=match(r'^\s*Transmit rate \(Mbps\)\s*:\s*([\d.]+)',float))


def analyze(run,baseline):
    run=resolve_run(run); meta=read_json(run/'metadata.json'); done=read_json(run/'DONE')
    rows,segments,manifest=read_complete(run)
    probes=[r for r in rows if r['kind']=='probe']; snapshots=[r for r in rows if r['kind']=='system_snapshot']
    sequences=[r['seq'] for r in rows]; errors=[]
    for row in rows:
        if row['run_id']!=meta['run_id']:
            errors.append('run_id_mismatch')
        if dt(row['time_utc'])!=dt(row['time_local']) or dt(row['time_local']).utcoffset()!=timedelta(hours=5):
            errors.append('timezone_mismatch')
    complete_cycles=defaultdict(dict); probe_counts=Counter()
    for row in probes:
        complete_cycles[row['cycle']][row['target']]=row; probe_counts[(row['cycle'],row['target'])]+=1
    limits={t:baseline['targets'][t]['threshold_ms'] for t in TARGETS}
    intervals={t:[(b['elapsed_ms']-a['elapsed_ms'])/1000 for a,b in zip([p for p in probes if p['target']==t],[p for p in probes if p['target']==t][1:])] for t in TARGETS}
    drifts=[]
    for target in TARGETS:
        group=[p for p in probes if p['target']==target]; first=group[0]
        for p in group:
            drifts.append(((dt(p['sent_utc'])-dt(first['sent_utc'])).total_seconds()*1000)-(p['elapsed_ms']-first['elapsed_ms']))
            if dt(p['completed_utc'])<dt(p['sent_utc']):
                errors.append('negative_wall_time')
    cycle_rows=[]
    for cycle,group in sorted(complete_cycles.items()):
        if set(group)!=set(TARGETS) or any(r['status']!='Success' for r in group.values()):
            continue
        values={t:group[t]['rtt_ms'] for t in TARGETS}
        stamp=min(dt(r['sent_utc']) for r in group.values())
        cycle_rows.append(dict(cycle=cycle,time_local=stamp.astimezone(LOCAL).isoformat(timespec='milliseconds'),
                               values=values,classification=classify(values,limits),
                               launch_skew_ms=round((max(dt(r['sent_utc']) for r in group.values())-stamp).total_seconds()*1000,3)))
    categories=Counter(c['classification'] for c in cycle_rows)
    all_metrics={t:metrics([p['rtt_ms'] for p in probes if p['target']==t and p['status']=='Success']) for t in TARGETS}
    grouped_metrics={name:{t:metrics([c['values'][t] for c in cycle_rows if c['classification']==name]) for t in TARGETS} for name in categories}
    by_adapter=defaultdict(list); wlans=[]; route_snapshots=[]
    for snapshot in snapshots:
        stamp=snapshot.get('observed_local',snapshot['time_local'])
        for counter in snapshot.get('counters',[]):
            by_adapter[counter['Name']].append(dict(time=stamp,**counter))
        wlans.append(dict(time=stamp,received_local=snapshot['time_local'],**wlan_fields(snapshot.get('wlan',''))))
        if 'selected_routes' in snapshot:
            route_snapshots.append(dict(time=snapshot['time_local'],selected_routes=snapshot['selected_routes'],
                                        ipv4_routes=[r for r in snapshot['routes'] if r['AddressFamily']==2]))
    rates=[]; counter_deltas={}
    for adapter,values in by_adapter.items():
        for a,b in zip(values,values[1:]):
            seconds=(dt(b['time'])-dt(a['time'])).total_seconds()
            rx=b['ReceivedBytes']-a['ReceivedBytes']; tx=b['SentBytes']-a['SentBytes']
            if seconds>0 and rx>=0 and tx>=0:
                rates.append(dict(adapter=adapter,start=a['time'],end=b['time'],seconds=seconds,
                                  time=(dt(a['time'])+(dt(b['time'])-dt(a['time']))/2).isoformat(timespec='milliseconds'),
                                  rx_mbps=rx*8/seconds/1e6,tx_mbps=tx*8/seconds/1e6))
        keys=['ReceivedDiscardedPackets','OutboundDiscardedPackets','ReceivedPacketErrors','OutboundPacketErrors']
        counter_deltas[adapter]={k:values[-1][k]-values[0][k] for k in keys}
    wifi_rates=[r for r in rates if r['adapter']=='Беспроводная сеть']
    peaks=[]
    for cycle in cycle_rows:
        if cycle['classification']=='below_all_thresholds':
            continue
        at=dt(cycle['time_local'])
        rate=next((r for r in wifi_rates if dt(r['start'])<at<=dt(r['end'])),None)
        wlan=min(wlans,key=lambda w:abs((dt(w['time'])-at).total_seconds()))
        peaks.append(dict(cycle,rate_interval=rate,nearest_wlan=wlan))
    selected_signatures=[json.dumps(s['selected_routes'],sort_keys=True) for s in route_snapshots]
    ipv4_signatures=[json.dumps(sorted(s['ipv4_routes'],key=lambda x:(x['InterfaceIndex'],x['DestinationPrefix'],x['NextHop'])),sort_keys=True) for s in route_snapshots]
    corr={t:{u:correlation([c['values'][t] for c in cycle_rows],[c['values'][u] for c in cycle_rows]) for u in TARGETS} for t in TARGETS}
    audit=dict(records=len(rows),expected_records=meta['final_health']['last_seq'],
               sequence_contiguous=sequences==list(range(1,meta['final_health']['last_seq']+1)),
               duplicate_cycle_targets=sum(v-1 for v in probe_counts.values()),
               cycles=len(complete_cycles),complete_five_target_cycles=len(cycle_rows),
               statuses=dict(Counter(p['status'] for p in probes)),quality=dict(Counter(p.get('quality') for p in probes)),
               all_segments_closed=all(s['closed'] for s in manifest['segments']),segments=segments,
               retention_deletions=manifest['deleted'],final_health=meta['final_health'],done=done,
               timestamp_errors=errors,record_log_time_monotonic=all(dt(b['time_utc'])>=dt(a['time_utc']) for a,b in zip(rows,rows[1:])),
               max_clock_vs_monotonic_drift_ms=round(max(abs(v) for v in drifts),3),
               launch_skew_max_ms=max(c['launch_skew_ms'] for c in cycle_rows),
               intervals_seconds={t:metrics(v) for t,v in intervals.items()},
               warnings=['segments.json first_seq is advisory: compare physical rows; original manifest is retained unchanged.'] if any(not s['bounds_match'] for s in segments) else [])
    return dict(schema=1,metadata=meta,audit=audit,metrics=all_metrics,thresholds=limits,
                classification_counts=dict(categories),classification_metrics=grouped_metrics,
                cycles=cycle_rows,peaks=peaks,manual_markers=[r for r in rows if r['kind']=='game_marker'],
                anomaly_count=sum(r['kind']=='anomaly' for r in rows),system_snapshot_count=len(snapshots),
                system_snapshot_errors=[s for s in snapshots if s.get('errors')],
                wlan=wlans,rates=wifi_rates,counter_deltas=counter_deltas,
                game_pid_sets=sorted({tuple(s.get('game_pids',[])) for s in snapshots}),
                udp_binding_variants=len({json.dumps(s.get('udp_bindings',[]),sort_keys=True) for s in snapshots}),
                route_snapshots=route_snapshots,selected_route_variants=len(set(selected_signatures)),
                ipv4_route_variants=len(set(ipv4_signatures)),correlation_all=corr)


def chart_spec(result):
    cycles=result['cycles']
    def series_for(data):
        return [dict(name=label,color=color,points=[dict(x=c['time_local'],y=c['values'][target]) for c in data])
                for target,label,color in zip(TARGETS,LABELS,COLORS)]
    common=dict(x_label='Время, UTC+05:00; 14 ноября 2026',y_label='ICMP RTT, мс',y_min=0)
    zoom=[c for c in cycles if '00:55:20'<=c['time_local'][11:19]<='00:56:05']
    mark=result['manual_markers'][0]['observed_utc'] if result['manual_markers'] else None
    specs=[dict(common,name='rtt-overview.png',title='Непрерывный этап: пять контрольных направлений',series=series_for(cycles),y_max=300,marker=mark,marker_text='F10: тест/другое'),
           dict(common,name='rtt-local-zoom.png',title='Общий всплеск: задержка растёт уже до домашнего шлюза',series=series_for(zoom),y_max=300)]
    specs.append(dict(name='traffic.png',title='Трафик Wi-Fi адаптера ПК: средние за ~30 секунд',x_label=common['x_label'],
                      y_label='Мбит/с; все процессы ПК',y_min=0,series=[dict(name=label,color=color,points=[dict(x=r['time'],y=r[key]) for r in result['rates']]) for label,color,key in [('RX','#1768ac','rx_mbps'),('TX','#d18b00','tx_mbps')]]))
    specs.append(dict(name='wifi.png',title='Wi-Fi: RSSI и согласованная скорость, снимки ~30 секунд',x_label=common['x_label'],
                      y_label='RSSI, dBm',y_min=-80,y_max=-45,y2_label='PHY TX, Мбит/с',
                      series=[dict(name='RSSI',color='#2e8b57',points=[dict(x=w['time'],y=w['rssi_dbm']) for w in result['wlan'] if w['rssi_dbm'] is not None]),
                              dict(name='PHY TX',color='#7749ae',secondary=True,points=[dict(x=w['time'],y=w['tx_phy_mbps']) for w in result['wlan'] if w['tx_phy_mbps'] is not None])]))
    return specs


def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('run'); parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args(); project=Path(__file__).resolve().parents[1]
    result=analyze(Path(args.run),read_json(project/'config/anomaly-baseline-2026-11-14.json'))
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/'final-analysis.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (args.output/'chart-spec.json').write_text(json.dumps(chart_spec(result),ensure_ascii=False)+'\n',encoding='utf-8')
    historical=[]; history_audits=[]; seen=set()
    for parent in [project/'reports/evidence',project/'reports/evidence/final-history']:
        for directory in sorted(parent.glob('*')):
            if not (directory/'metadata.json').exists() or not (directory/'pings.csv').exists():
                continue
            metadata=read_json(directory/'metadata.json')
            if '192.168.123.1' not in metadata.get('targets',[]) or metadata['start_utc'] in seen:
                continue
            seen.add(metadata['start_utc'])
            with (directory/'pings.csv').open(encoding='utf-8-sig',newline='') as stream:
                old_rows=list(csv.DictReader(stream))
            pairs=Counter((int(r['cycle']),r['target']) for r in old_rows)
            cycle_set=sorted({int(r['cycle']) for r in old_rows})
            time_errors=sum(dt(r['sent_utc'])!=dt(r['sent_local']) or dt(r['completed_utc'])<dt(r['sent_utc']) for r in old_rows)
            history_audits.append(dict(name=directory.name,rows=len(old_rows),expected_rows=metadata['cycles']*len(metadata['targets']),
                                       duplicate_pairs=sum(v-1 for v in pairs.values()),
                                       cycles_contiguous=cycle_set==list(range(1,metadata['cycles']+1)),
                                       complete_target_cycles=all({r['target'] for r in old_rows if int(r['cycle'])==c}==set(metadata['targets']) for c in cycle_set),
                                       timestamp_errors=time_errors,statuses=dict(Counter(r['status'] for r in old_rows)),
                                       pings_sha256=hashlib.sha256((directory/'pings.csv').read_bytes()).hexdigest()))
            historical.append(dict(name=directory.name,start=metadata['start_local'],end=metadata['end_local'],
                                   context=metadata['context'],timeout=metadata['timeout_ms'],cycles=metadata['cycles'],
                                   metrics=summarize(old_rows,metadata['timeout_ms'])))
    historical.sort(key=lambda x:x['start'])
    (args.output/'historical-summary.json').write_text(json.dumps(historical,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (args.output/'historical-audit.json').write_text(json.dumps(history_audits,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    with (args.output/'paired-cycles.csv').open('w',encoding='utf-8',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['cycle','time_local','classification',*TARGETS]); writer.writeheader()
        for row in result['cycles']:
            writer.writerow(dict(cycle=row['cycle'],time_local=row['time_local'],classification=row['classification'],**row['values']))
    print(json.dumps({k:result[k] for k in ['classification_counts','selected_route_variants','ipv4_route_variants','counter_deltas']},ensure_ascii=False,indent=2))
    print('Audit:',json.dumps({k:v for k,v in result['audit'].items() if k not in ('segments','intervals_seconds')},ensure_ascii=False))


if __name__=='__main__':
    main()
