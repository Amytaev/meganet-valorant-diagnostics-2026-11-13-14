"""Offline, dependency-free analysis. ICMP nonresponses are not game packet loss."""
from __future__ import annotations
import argparse
import csv
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


def percentile(values, p):
    return sorted(values)[max(0, math.ceil(len(values) * p) - 1)] if values else None


def summarize(rows, timeout_ms=None):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row['target']].append(row)
    result = []
    for target, samples in grouped.items():
        statuses = Counter(s['status'] for s in samples)
        early = 0
        for s in samples:
            if s['status'] != 'TimedOut':
                continue
            wait = float(s['observed_wait_ms']) if s.get('observed_wait_ms') else (
                datetime.fromisoformat(s['completed_utc'].replace('Z','+00:00'))-
                datetime.fromisoformat(s['sent_utc'].replace('Z','+00:00'))).total_seconds()*1000
            if s.get('quality') == 'early_timeout_unverified' or (timeout_ms and wait < timeout_ms-100):
                early += 1
        valid = [s for s in samples if s['status'] != 'ProbeError']
        good = [s for s in samples if s['status'] == 'Success']
        rtt = [float(s['rtt_ms']) for s in good]
        deltas = [abs(float(b['rtt_ms']) - float(a['rtt_ms'])) for a, b in zip(samples, samples[1:])
                  if a['status'] == b['status'] == 'Success' and int(b['cycle']) == int(a['cycle']) + 1]
        result.append(dict(target=target, protocol='ICMPv4', rows=len(samples), requests_without_local_error=len(valid),
                           success=len(good), status_counts=dict(statuses),
                           recorded_nonresponse_pct=round(100 * (len(valid)-len(good))/len(valid), 3) if valid else None,
                           nonresponse_pct=round(100 * (len(valid)-len(good))/len(valid), 3) if valid and not early else None,
                           early_timeout_count=early, loss_measurement_qualified=not early,
                           min_ms=min(rtt) if rtt else None, avg_ms=round(statistics.mean(rtt),3) if rtt else None,
                           max_ms=max(rtt) if rtt else None, p95_ms=percentile(rtt,.95),
                           mean_abs_consecutive_rtt_delta_ms=round(statistics.mean(deltas),3) if deltas else None,
                           first_local=samples[0]['sent_local'], last_local=samples[-1]['sent_local']))
    return result


def load_jsonl(path):
    if not path.exists():
        return []
    lines = path.read_text(encoding='utf-8-sig').splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def counter_rates(rows):
    previous = {}
    result = []
    for row in rows:
        name = row['name']
        if name in previous:
            old = previous[name]
            seconds = (row['elapsed_ms']-old['elapsed_ms'])/1000
            if seconds > 0:
                rx = row['rx_bytes']-old['rx_bytes']
                tx = row['tx_bytes']-old['tx_bytes']
                if rx >= 0 and tx >= 0:
                    result.append(dict(time=row['time'], name=name, interval_seconds=seconds,
                                       rx_mbps=rx*8/seconds/1e6, tx_mbps=tx*8/seconds/1e6,
                                       counter_reset=False))
        previous[name] = row
    return result


def counter_deltas(rows):
    grouped=defaultdict(list)
    for row in rows:
        grouped[row['name']].append(row)
    fields=('rx_discards','tx_discards','rx_errors','tx_errors')
    return [dict(name=name, samples=len(samples),
                 deltas={key:samples[-1][key]-samples[0][key] for key in fields},
                 counter_reset_suspected=any(b[key]<a[key] for a,b in zip(samples,samples[1:]) for key in fields))
            for name,samples in grouped.items()]


def normalize_wlan_text(value):
    if '\u2568' in value or '\u2564' in value:
        try:
            return value.encode('cp866').decode('utf-8'), 'recovered UTF-8 bytes previously decoded as CP866'
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return value, 'unchanged'


def wlan_summary(rows):
    normalized=[]
    readings=[]
    for row in rows:
        text,method=normalize_wlan_text(row['text'])
        normalized.append(dict(time=row['time'], text=text, normalization=method))
        found=re.search(r'(?im)^\s*Rssi\s*:\s*(-?\d+)',text)
        if found:
            readings.append(int(found[1]))
    return normalized, dict(snapshots=len(rows), rssi_min_dbm=min(readings) if readings else None,
                            rssi_max_dbm=max(readings) if readings else None)


def paired_spikes(rows, target='192.168.123.1', threshold=10):
    cycles = defaultdict(dict)
    times = {}
    for row in rows:
        cycle=int(row['cycle']); cycles[cycle][row['target']] = float(row['rtt_ms']) if row['status']=='Success' else row['status']
        times[cycle]=row['sent_local']
    return [dict(cycle=k,time=times[k],rtt_ms_or_status=v) for k,v in cycles.items()
            if isinstance(v.get(target), (int,float)) and v[target]>=threshold]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('session',type=Path)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    session=args.session
    metadata=json.loads((session/'metadata.json').read_text(encoding='utf-8-sig'))
    with (session/'pings.csv').open(encoding='utf-8-sig',newline='') as f:
        rows=list(csv.DictReader(f))
    metrics=summarize(rows,metadata['timeout_ms'])
    counters=load_jsonl(session/'counters.jsonl')
    rates=counter_rates(counters)
    names=sorted({r['name'] for r in rates})
    rate_summary=[dict(name=name, max_interval_rx_mbps=max(r['rx_mbps'] for r in rates if r['name']==name),
                       max_interval_tx_mbps=max(r['tx_mbps'] for r in rates if r['name']==name)) for name in names]
    intervals=[]
    first_per_cycle={}
    for r in rows:
        first_per_cycle.setdefault(r['cycle'],float(r['elapsed_ms']))
    times=list(first_per_cycle.values())
    intervals=[(b-a)/1000 for a,b in zip(times,times[1:])]
    normalized_wlan,wlan_metrics=wlan_summary(load_jsonl(session/'wlan.jsonl'))
    result=dict(metadata=metadata, complete=(session/'DONE').exists(), metrics=metrics,
                actual_probe_interval_seconds=dict(min=min(intervals),mean=statistics.mean(intervals),max=max(intervals)) if intervals else None,
                interface_rate_summary=rate_summary, interface_counter_deltas=counter_deltas(counters), gateway_spikes_ge_10_ms=paired_spikes(rows),
                wlan_summary=wlan_metrics,
                game_markers=load_jsonl(session/'game-markers.jsonl'),
                errors=load_jsonl(session/'errors.jsonl'),
                limitations=['ICMP timeout/non-success is not game UDP loss.', 'RTT statistics use successful replies only; nearest-rank p95.',
                            'NIC rates are interval averages, not process traffic or proof of bufferbloat.',
                            'Matched cycles are observations, not causal proof. No server region is independently verified.'])
    output=args.output or session/'analysis.json'
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if normalized_wlan:
        (output.parent/'wlan-readable.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in normalized_wlan),encoding='utf-8')
    print(json.dumps(dict(complete=result['complete'],metrics=metrics,interface_rate_summary=rate_summary,
                          gateway_spike_count=len(result['gateway_spikes_ge_10_ms']),errors=len(result['errors'])),ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
