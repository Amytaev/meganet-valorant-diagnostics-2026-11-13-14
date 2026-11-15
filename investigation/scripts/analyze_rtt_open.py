"""Independent offline temporal analysis; no game/network/control APIs are called.

Reuses reviewed numerical inputs; prepare reads frozen game text and existing
monitor files only. Original logs remain outside Git. No missing game RTT is filled.
"""
import argparse
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import random
import re
import statistics

from analyze_rtt_90_180 import (dt, epoch, read_json, write_json, write_csv, TARGETS,
    EARLY_RETN, PROBE_FIELDS, normalized_snapshot, connection_for, TimedIndex,
    control_summary, classify_controls)
from analyze_rrt_logs import times

SEED = 20261115


def quant(values):
    a = sorted(values)
    return dict(n=len(a), min=min(a), median=statistics.median(a), p95=a[math.ceil(.95*len(a))-1], max=max(a)) if a else dict(n=0)


def merged(intervals):
    result = []
    for start, end in sorted(intervals):
        if result and start <= result[-1][1]:
            result[-1][1] = max(result[-1][1], end)
        else:
            result.append([start, end])
    return result


def in_intervals(t, intervals):
    return any(a <= t <= b for a, b in intervals)


def clusters(points, gap):
    out = []
    for p in sorted(points, key=lambda p:p['time_utc']):
        t = epoch(p['time_utc'])
        if not out or t-epoch(out[-1][-1]['time_utc']) > gap:
            out.append([p])
        else:
            out[-1].append(p)
    return out


def rotate(mask, offset, length):
    offset %= length
    return ((mask << offset) | (mask >> (length-offset))) & ((1 << length)-1)


def shift_reference(blocks, iterations=5000, seed=SEED):
    """Rotate the whole event-near mask within each observed block; preserve clusters."""
    rng = random.Random(seed)
    selected = [b for b in blocks if b['n'] >= 30 and b['event_mask'] and b['event_mask'].bit_count() < b['n']]
    observed = sum((b['event_mask'] & b['bad_mask']).bit_count() for b in selected)
    simulated = []
    for _ in range(iterations):
        simulated.append(sum((rotate(b['event_mask'], rng.randrange(10, b['n']-9), b['n']) & b['bad_mask']).bit_count() for b in selected))
    return dict(blocks=len(selected), selected_cycles=sum(b['n'] for b in selected),
                event_window_cycles=sum(b['event_mask'].bit_count() for b in selected), observed_bad_cycles=observed,
                iterations=iterations, seed=seed, shifted_counts=quant(simulated),
                shifted_histogram=dict(sorted(Counter(simulated).items())),
                shifted_mean=round(statistics.mean(simulated),4) if simulated else None,
                reference_tail_fraction=(1+sum(x>=observed for x in simulated))/(iterations+1),
                limits='Exploratory alignment reference, not causal probability. Within-block stationarity and circular boundaries are assumptions.')


def prepare(project, frozen_game_dir, out):
    out.mkdir(parents=True, exist_ok=True)
    old = project/'reports/evidence/rtt-90-180-2026-11-15/inputs'
    source = read_json(old/'game-sources.json')
    events, perf = [], []
    for info in source['sources']:
        f = frozen_game_dir/info['file']; payload = f.read_bytes()
        if hashlib.sha256(payload).hexdigest() != info['sha256']:
            raise ValueError('Frozen original game source mismatch')
        last_stamp = None
        for n, line in enumerate(payload.decode('utf-8-sig').splitlines(), 1):
            m = re.match(r'^\[([^]]+)\]\[[^]]+\](\w+):\s*(.*)', line)
            if m:
                last_stamp = m[1]
                base = dict(file=f.name, line=n, **times(m[1]))
                body = m[3]
                match = re.search(r'Gameplay started at local time ([-\d.]+) \(server time ([-\d.]+)\)', body)
                if m[2] == 'LogShooterGameState' and match:
                    local, server = map(float, match.groups())
                    events.append(dict(base, kind='gameplay_zero' if server == 0 else 'gameplay_nonzero',
                                       local_game_time=local, server_game_time=server,
                                       server_minus_local_seconds=round(server-local,6)))
                match = re.search(r"OnRoundEnded for round '(\d+)'", body)
                if m[2] == 'LogShooterGameState' and match:
                    events.append(dict(base, kind='round_end', round_index=int(match[1])))
                if m[2] == 'LogAres' and 'Soft Reference has not been preloaded' in body:
                    events.append(dict(base, kind='asset_preload_warning'))
                if m[2] == 'LogShooterGameState' and 'Replicated NetServerMaxTickRate' in body:
                    match = re.search(r"NetServerMaxTickRate: '(\d+)'", body)
                    if match:events.append(dict(base, kind='configured_server_tickrate', value=int(match[1])))
            metric = re.fullmatch(r'\s*(Avg\.Frametime \(ms\)|Avg\. Engine Latency \(ms\)|Avg\. Work \(ms\)|Avg\. Slop \(ms\)|Avg\. Slack \(ms\)|Total Frames):\s*([\d.]+)\s*',line)
            if metric and last_stamp:
                perf.append(dict(file=f.name,line=n,nearby_log_time_utc=times(last_stamp)['time_utc'],metric=metric[1],value=float(metric[2]),
                                 timing_limit='Round summary aggregate, not instantaneous or a precisely delimited interval'))
    write_json(out/'phase-events.json', events)
    write_json(out/'performance-summaries.json', perf)
    previous = {a['source']:a for a in read_json(old/'monitor-audit.json') if a['kind']=='continuous'}
    delta_probes, delta_snapshots, native_audits, boundaries = [], [], [], []
    for folder in sorted((project/'raw/continuous').iterdir()):
        if folder.name not in previous or not previous[folder.name]['eligible']:continue
        meta = read_json(folder/'metadata.json');status = read_json(folder/'status.json')
        cap = status.get('committed_seq') if status['state']=='running' else previous[folder.name]['frozen_last_seq']
        old_cap = previous[folder.name]['frozen_last_seq'];count=0;last=0;prefix_hash=hashlib.sha256();probe=[];ref=None;aps={}
        for path in sorted(folder.glob('telemetry-*.jsonl')):
            with path.open('rb') as h:
                for line in h:
                    r=json.loads(line.decode('utf-8-sig'))
                    if r['seq']>cap:break
                    if r['seq'] != last+1:raise ValueError('Gap or duplicate in committed prefix')
                    prefix_hash.update(line);count+=1;last=r['seq']
                    if r['kind']=='system_snapshot':
                        snap=normalized_snapshot(r,folder.name,aps)
                        if r['seq']>old_cap:delta_snapshots.append(snap)
                    if r['kind']=='probe':
                        if ref is None:ref=(epoch(r['sent_utc']),r['elapsed_ms'])
                        clock_delta=(epoch(r['sent_utc'])-ref[0])*1000-(r['elapsed_ms']-ref[1])
                        probe.append(dict(time_utc=r['sent_utc'],clock_residual_ms=clock_delta,status=r['status'],rtt_ms=r.get('rtt_ms'),wait_ms=r.get('observed_wait_ms'),
                                          write_delay_ms=(epoch(r['time_utc'])-epoch(r['completed_utc']))*1000))
                        if r['seq']>old_cap:
                            row={k:r.get(k) for k in PROBE_FIELDS if k not in ('source','eligible')}
                            row.update(source=folder.name,eligible=int(r.get('quality')=='normal'));delta_probes.append(row)
                    if last==cap:break
            if last==cap:break
        if last!=cap or count!=cap:raise ValueError('Non-contiguous frozen monitor prefix')
        native_audits.append(dict(source=folder.name,records=count,probes=len(probe),
            clock_residual_ms=quant([p['clock_residual_ms'] for p in probe]),
            write_delay_ms=quant([p['write_delay_ms'] for p in probe]),
            successful_wait_minus_native_rtt_ms=quant([p['wait_ms']-p['rtt_ms'] for p in probe if p['status']=='Success' and p['rtt_ms'] is not None]),
            success_without_rtt=sum(p['status']=='Success' and p['rtt_ms'] is None for p in probe),
            status_counts=dict(Counter(p['status'] for p in probe))))
        boundaries.append(dict(source=folder.name,previous_frozen_seq=old_cap,current_frozen_seq=cap,consumed_prefix_sha256=prefix_hash.hexdigest(),
                               state=status['state'],heartbeat_at_freeze=status.get('heartbeat_utc')))
    write_csv(out/'additional-control-probes.csv',PROBE_FIELDS,delta_probes)
    write_json(out/'additional-snapshots.json',delta_snapshots)
    write_json(out/'native-clock-audit.json',native_audits)
    write_json(out/'monitor-boundaries.json',boundaries)
    write_json(out/'source-lineage.json',dict(previous_private_commit='ad131138d5d14acb9a2673ca04b2aba75a7abd9a',
               reused_inputs='reports/evidence/rtt-90-180-2026-11-15/inputs',frozen_game_sources=source['sources'],
               raw_sources_published=False, new_network_tests=False, monitor_stopped=False))
    print(json.dumps(dict(phase_events=len(events),performance_metrics=len(perf),additional_probes=len(delta_probes))))


def mask_blocks(cycles):
    groups=defaultdict(list)
    for c in cycles:
        if c['connection_id']:groups[(c['connection_id'],c['source'])].append(c)
    blocks=[]
    for (conn,source),rs in sorted(groups.items()):
        rs.sort(key=lambda c:c['sent_utc']);parts=[]
        for r in rs:
            if not parts or epoch(r['sent_utc'])-epoch(parts[-1][-1]['sent_utc'])>3:parts.append([r])
            else:parts[-1].append(r)
        for part in parts:
            blocks.append(dict(connection_id=conn,source=source,n=len(part),
                 event_mask=sum((1<<i) for i,r in enumerate(part) if r['within_4s_of_band_event']=='True'),
                 bad_mask=sum((1<<i) for i,r in enumerate(part) if r['class_name']!='all_controls_below_threshold'),
                 first_utc=part[0]['sent_utc'],last_utc=part[-1]['sent_utc']))
    return blocks


def rank(values):
    order=sorted(range(len(values)),key=lambda i:values[i]);out=[None]*len(values);i=0
    while i<len(order):
        j=i+1
        while j<len(order) and values[order[j]]==values[order[i]]:j+=1
        for k in range(i,j):out[order[k]]=(i+j-1)/2
        i=j
    return out


def corr(x,y):
    if len(x)<3 or len(set(x))<2 or len(set(y))<2:return None
    return round(statistics.correlation(x,y),6)


def analyze(project, inputs, output):
    output.mkdir(parents=True,exist_ok=True)
    old=project/'reports/evidence/rtt-90-180-2026-11-15/inputs';old_results=project/'reports/rtt-90-180-data'
    all_events=read_json(old/'game-events.json');pings=[e for e in all_events if e['kind']=='ping_threshold']
    conns=read_json(old_results/'connections.json');by_conn=defaultdict(list)
    for e in pings:
        c=connection_for(e,conns)
        if c:by_conn[c['connection_id']].append(e)
    summaries=[];cluster_rows=[];transitions=Counter()
    def band(x):return '120-<130' if x<130 else '130-<150' if x<150 else '150-180' if x<=180 else '>180-<200' if x<200 else '200-<300' if x<300 else '300+'
    for c in conns:
        es=by_conn[c['connection_id']];values=[e['value'] for e in es]
        row=dict(c,n=len(es),tail_rtt_ms=quant(values),first_ping_utc=es[0]['time_utc'] if es else None,
                 first_ping_after_map_ready_seconds=round(epoch(es[0]['time_utc'])-epoch(c['map_ready_utc'] or c['start_utc']),3) if es else None,
                 bands=dict(Counter(band(v) for v in values)),cluster_counts={})
        for gap in (5,10,30,60):
            cl=clusters(es,gap);row['cluster_counts'][str(gap)]=len(cl)
            if gap==10:
                for group in cl:
                    cluster_rows.append(dict(connection_id=c['connection_id'],n=len(group),first_utc=group[0]['time_utc'],last_utc=group[-1]['time_utc'],
                                             observed_span_seconds=round(epoch(group[-1]['time_utc'])-epoch(group[0]['time_utc']),3),
                                             min_ms=min(p['value'] for p in group),max_ms=max(p['value'] for p in group),lines=[p['line'] for p in group],
                                             continuous_duration_seconds=None))
        for a,b in zip(es,es[1:]):
            gap=epoch(b['time_utc'])-epoch(a['time_utc'])
            if gap<=10:transitions[(band(a['value']),band(b['value']))]+=1
        summaries.append(row)
    write_json(output/'connection-tail-process.json',summaries)
    write_json(output/'point-clusters-10s.json',cluster_rows)
    write_json(output/'logged-point-transitions.json',[dict(from_band=a,to_band=b,n=n) for (a,b),n in sorted(transitions.items())])
    with (old_results/'control-cycles.csv').open(encoding='utf-8',newline='') as h:cycles=list(csv.DictReader(h))
    blocks=mask_blocks(cycles);null=shift_reference(blocks)
    null['leave_one_connection_out']={c:shift_reference([b for b in blocks if b['connection_id']!=c],iterations=2000) for c in sorted({b['connection_id'] for b in blocks if b['event_mask']})}
    write_json(output/'control-alignment-shift-reference.json',null)
    write_json(output/'alignment-blocks.json',[{k:v for k,v in b.items() if not k.endswith('_mask')}|dict(event_cycles=b['event_mask'].bit_count(),bad_cycles=b['bad_mask'].bit_count(),observed_overlap=(b['event_mask']&b['bad_mask']).bit_count()) for b in blocks])
    lag_counts=[]
    for lag in [-10,-6,-4,-2,0,2,4,6,10]:
        shifted=[]
        for b in blocks:
            offset=lag//2
            mask=(b['event_mask']<<offset)&((1<<b['n'])-1) if offset>=0 else b['event_mask']>>(-offset)
            shifted.append((mask.bit_count(),(mask&b['bad_mask']).bit_count()))
        lag_counts.append(dict(control_lag_seconds=lag,event_window_cycles=sum(n for n,k in shifted),bad_cycles=sum(k for n,k in shifted),
                               limit='Descriptive 2-second cycle offsets; overlapping windows and adjacent lag bins are dependent. Positive lag means later controls.'))
    write_json(output/'lagged-control-window-overlap.json',lag_counts)
    phase=read_json(inputs/'phase-events.json');phase_by_conn=defaultdict(list)
    for e in phase:
        c=connection_for(e,conns)
        if c:phase_by_conn[c['connection_id']].append(e)
    phase_results=[]
    for kind in ['gameplay_zero','gameplay_nonzero','round_end','asset_preload_warning']:
        for window in [1,5,10]:
            observed=0;exposure=0.;duration=0.;by=[]
            for c in conns:
                if c['end_utc'] is None:continue
                start=epoch(c['map_ready_utc'] or c['start_utc']);end=epoch(c['end_utc'])
                intervals=merged([(max(start,epoch(p['time_utc'])-window),min(end,epoch(p['time_utc'])+window)) for p in phase_by_conn[c['connection_id']] if p['kind']==kind])
                intervals=[p for p in intervals if p[1]>=p[0]];es=by_conn[c['connection_id']]
                n=sum(in_intervals(epoch(e['time_utc']),intervals) for e in es)
                seconds=sum(b-a for a,b in intervals);observed+=n;exposure+=seconds;duration+=end-start
                by.append(dict(connection_id=c['connection_id'],hits=n,game_points=len(es),window_exposure_seconds=round(seconds,3),connection_seconds=round(end-start,3)))
            phase_results.append(dict(kind=kind,window_seconds=window,point_hits=observed,total_points=len(pings),
                                      exposure_seconds=round(exposure,3),total_connection_seconds=round(duration,3),by_connection=by))
    write_json(output/'phase-exposure.json',phase_results)
    point_context=[]
    for e in pings:
        c=connection_for(e,conns);ph=phase_by_conn[c['connection_id']] if c else []
        closest={}
        for kind in ['gameplay_zero','gameplay_nonzero','round_end','asset_preload_warning']:
            rows=[p for p in ph if p['kind']==kind]
            near=min(rows,key=lambda p:abs(epoch(p['time_utc'])-epoch(e['time_utc']))) if rows else None
            closest[kind]=dict(line=near['line'],time_utc=near['time_utc'],delta_seconds=round(epoch(near['time_utc'])-epoch(e['time_utc']),3)) if near else None
        point_context.append(dict(file=e['file'],line=e['line'],time_utc=e['time_utc'],value=e['value'],connection_id=c['connection_id'] if c else None,nearest_phase_events=closest))
    write_json(output/'all-291-points-phase-context.json',point_context)
    # Tail-only rank correlations and leave-one-connection-out: no baseline inference.
    selected=read_json(old_results/'events-90-180.json');features=[]
    for e in selected:
        cs={r['target']:r for r in e['control_windows'][2]['controls']}
        if e['control_windows'][2]['category']=='uncovered_or_incomplete':continue
        vals={t:cs[t]['nearest']['rtt_ms'] for t in cs}
        common=statistics.median([vals[TARGETS[0]]-2,vals[TARGETS[1]]-3,vals[TARGETS[2]]-23])
        far=statistics.median([vals[TARGETS[3]]-93,vals.get(TARGETS[4],vals.get(EARLY_RETN))-(92 if TARGETS[4] in vals else 85)])
        features.append(dict(id=e['id'],connection_id=e['connection']['connection_id'],time_utc=e['time_utc'],game_ms=e['value'],common_local_excess_ms=common,
                             far_excess_ms=far,far_minus_common_ms=far-common,frame_warning=e['local_fps_within_4s'],
                             wifi_rssi_dbm=e['nearest_snapshot']['rssi_dbm'] if e['nearest_snapshot'] else None))
    def correlations(rows):
        return {k:dict(pearson=corr([r['game_ms'] for r in rows],[r[k] for r in rows]),spearman=corr(rank([r['game_ms'] for r in rows]),rank([r[k] for r in rows]))) for k in ['common_local_excess_ms','far_excess_ms','far_minus_common_ms']}
    centered=[]
    for c in sorted({r['connection_id'] for r in features}):
        group=[r for r in features if r['connection_id']==c]
        keys=['game_ms','common_local_excess_ms','far_excess_ms','far_minus_common_ms']
        means={k:statistics.mean(r[k] for r in group) for k in keys}
        centered.extend(dict(r,**{k:r[k]-means[k] for k in keys}) for r in group)
    write_json(output/'point-control-features.json',features)
    write_json(output/'tail-correlations.json',dict(n=len(features),all=correlations(features),
                within_connection_centered=correlations(centered),
                leave_one_connection_out={c:correlations([r for r in features if r['connection_id']!=c]) for c in sorted({r['connection_id'] for r in features})},
                limit='Conditional on threshold-selected points; noisy, dependent and not a causal effect.'))
    # Read complete old numerical history plus newly saved delta, without duplicating prefixes.
    probes=[]
    for path in [old/'control-probes.csv',inputs/'additional-control-probes.csv']:
        with path.open(encoding='utf-8',newline='') as h:
            for r in csv.DictReader(h):
                if r['eligible']=='1':probes.append(dict(r,rtt_ms=float(r['rtt_ms']) if r['rtt_ms'] else None))
    limits=read_json(old/'thresholds.json')
    targets={t:TimedIndex([r for r in probes if r['target']==t],'sent_utc') for t in limits}
    full_context=[]
    for i,e in enumerate(pings,1):
        t=epoch(e['time_utc']);c=connection_for(e,conns)
        controls=[dict(target=target,**control_summary(index.window(t,4),t)) for target,index in targets.items() if index.window(t,4)]
        category,flags=classify_controls(controls,limits,min_samples=2)
        warnings=[dict(kind=w['kind'],line=w['line'],time_utc=w['time_utc'],delta_seconds=round(epoch(w['time_utc'])-t,3),
                       **{k:w[k] for k in ['value','metric','queue','dropped_this_second'] if k in w}) for w in all_events
                  if w['file']==e['file'] and w['kind'] in ['framerate_threshold','queue_overflow','input_replication_stopped','burst_loss','burst_loss_end'] and abs(epoch(w['time_utc'])-t)<=4]
        full_context.append(dict(point_id=f'P{i:03}',**e,connection_id=c['connection_id'] if c else None,
                                 endpoint=f"{c['ip']}:{c['port']}" if c else None,control_class_4s=category,exceeded_targets=flags,
                                 controls_4s=controls,warnings_4s=warnings,baseline_ms=None,continuous_duration_seconds=None))
    write_json(output/'all-game-points-context.json',full_context)
    previous_classes={e['event_id']:e['control_windows'][2]['category'] for e in selected}
    if any(previous_classes[e['event_id']]!=e['control_class_4s'] for e in full_context if e['event_id'] in previous_classes):
        raise ValueError('Old band classifications changed during independent replay')
    write_json(output/'classification-replay.json',dict(replayed_band_points=len(previous_classes),all_match=True,
               full_classes=dict(Counter(e['control_class_4s'] for e in full_context)),
               outside_band_classes=dict(Counter(e['control_class_4s'] for e in full_context if e['value']>180))))
    bins=defaultdict(list)
    for r in probes:bins[(r['target'],int(epoch(r['sent_utc'])//60))].append(r)
    minutes=[]
    for (target,minute),rs in sorted(bins.items()):
        good=[r['rtt_ms'] for r in rs if r['status']=='Success' and r['rtt_ms'] is not None]
        minutes.append(dict(target=target,start_utc=datetime.fromtimestamp(minute*60,timezone.utc).isoformat(),status_counts=dict(Counter(r['status'] for r in rs)),rtt_ms=quant(good)))
    write_json(output/'minute-control-series.json',minutes)
    hourly=defaultdict(list)
    for r in probes:
        if r['status']=='Success' and r['rtt_ms'] is not None:hourly[(r['target'],int(epoch(r['sent_utc'])//3600))].append(r['rtt_ms'])
    write_json(output/'hourly-control-distributions.json',[dict(target=t,start_utc=datetime.fromtimestamp(hour*3600,timezone.utc).isoformat(),rtt_ms=quant(vals)) for (t,hour),vals in sorted(hourly.items())])
    summary=dict(game_points=len(pings),band_points=sum(90<=p['value']<=180 for p in pings),bands=dict(Counter(band(p['value']) for p in pings)),
                 point_clusters={str(g):sum(len(clusters(by_conn[c['connection_id']],g)) for c in conns) for g in [5,10,30,60]},
                 repeated_equal_consecutive_points=sum(a['value']==b['value'] for es in by_conn.values() for a,b in zip(es,es[1:])),
                 short_logged_differences=quant([abs(b['value']-a['value']) for es in by_conn.values() for a,b in zip(es,es[1:]) if epoch(b['time_utc'])-epoch(a['time_utc'])<=10]),
                 phase_event_counts=dict(Counter(p['kind'] for p in phase)),qualified_controls=len(probes),control_end_utc=max(r['sent_utc'] for r in probes),
                 observed_game_min_ms=min(e['value'] for e in pings),observed_game_max_ms=max(e['value'] for e in pings))
    write_json(output/'summary.json',summary)
    print(json.dumps(summary))


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('command',choices=['prepare','analyze']);ap.add_argument('--project',type=Path,default=Path(__file__).resolve().parents[1]);ap.add_argument('--game-dir',type=Path)
    args=ap.parse_args();inputs=args.project/'reports/evidence/rtt-open-2026-11-15';output=args.project/'reports/rtt-open-data'
    if args.command=='prepare':prepare(args.project,args.game_dir,inputs)
    else:analyze(args.project,inputs,output)
