"""Read-only integrity/cadence audit of explicitly frozen local source prefixes."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from analyze_rtt_open import quant
from analyze_rtt_90_180 import epoch, read_json, write_json


def audit(project, game_dir):
    root=project/'reports/evidence/rtt-open-2026-11-15'
    game=read_json(project/'reports/evidence/rtt-90-180-2026-11-15/inputs/game-sources.json')
    checks=[]
    for s in game['sources']:
        payload=(game_dir/s['file']).read_bytes();prefix=payload[:s['bytes']]
        same=hashlib.sha256(prefix).hexdigest()==s['sha256']
        if not same:raise ValueError('Source prefix differs')
        tail=payload[s['bytes']:].decode('utf-8-sig',errors='strict')
        checks.append(dict(file=s['file'],checked_bytes=s['bytes'],prefix_sha256=s['sha256'],prefix_matches=True,
            current_bytes=len(payload),additional_ping_threshold_lines=len(re.findall(r'Average Ping Threshold (?:critically )?exceeded',tail)),
            additional_game_travel_lines=len(re.findall(r'LogNet:.*(?:Browse:|ClientTravel)|LogTravelManager:.*\b(?:\d{1,3}\.){3}\d{1,3}:\d+',tail))))
    monitors=[]
    for b in read_json(root/'monitor-boundaries.json'):
        folder=project/'raw/continuous'/b['source'];seq=0;digest=hashlib.sha256();clocks=[];previous_t=None;previous_cycle=None
        cycle_gaps=[];largest=[];resets=[];ref=None;previous_residual=None;max_write=None;statuses=Counter()
        for path in sorted(folder.glob('telemetry-*.jsonl')):
            with path.open('rb') as h:
                for line in h:
                    r=json.loads(line)
                    if r['seq']>b['current_frozen_seq']:break
                    if r['seq']!=seq+1:raise ValueError('Non-contiguous sequence')
                    seq=r['seq'];digest.update(line)
                    if r['kind']!='probe':continue
                    sent=epoch(r['sent_utc']);write=(epoch(r['time_utc'])-epoch(r['completed_utc']))*1000
                    statuses[r['status']]+=1
                    if max_write is None or write>max_write['delay_ms']:max_write=dict(time_utc=r['sent_utc'],delay_ms=write)
                    if ref is None:ref=(sent,r['elapsed_ms'])
                    residual=(sent-ref[0])*1000-(r['elapsed_ms']-ref[1]);clocks.append((residual,r['sent_utc']))
                    if previous_residual is not None and abs(residual-previous_residual)>5:
                        resets.append(dict(time_utc=r['sent_utc'],delta_ms=round(residual-previous_residual,3)))
                    previous_residual=residual
                    if r['cycle']!=previous_cycle:
                        if previous_t is not None:
                            gap=sent-previous_t;cycle_gaps.append(gap)
                            if gap>2.5:largest.append(dict(time_utc=r['sent_utc'],gap_seconds=round(gap,3)))
                        previous_t=sent;previous_cycle=r['cycle']
            if seq==b['current_frozen_seq']:break
        if seq!=b['current_frozen_seq'] or digest.hexdigest()!=b['consumed_prefix_sha256']:
            raise ValueError('Frozen monitor SHA differs')
        monitors.append(dict(source=b['source'],last_seq=seq,sha_matches=True,sequence_contiguous=True,
            wall_minus_monotonic_extrema=[dict(residual_ms=round(v,3),time_utc=t) for v,t in [min(clocks),max(clocks)]],
            adjacent_clock_steps_over_5ms=resets,largest_write_delay=max_write,
            first_sent_cycle_gap_seconds=quant(cycle_gaps),cycle_gaps_over_2_5s=largest,status_counts=dict(statuses)))
    out=dict(audit_time_utc=datetime.now(timezone.utc).isoformat(),original_sources_modified=False,
             game_original_prefix_checks=checks,monitors=monitors,
             limits='Only frozen committed prefixes are audited. Live append after the cap is not a missing record; game tail counters are not a full new source parse.')
    if any(r['additional_ping_threshold_lines'] or r['additional_game_travel_lines'] for r in checks):
        raise ValueError('New relevant game tail requires extending reviewed inputs')
    write_json(root/'INTEGRITY-AUDIT.json',out)
    print(json.dumps(dict(game_prefixes=len(checks),monitor_prefixes=len(monitors),all_match=True)))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--project',type=Path,default=Path(__file__).resolve().parents[1]);p.add_argument('--game-dir',type=Path,required=True)
    a=p.parse_args();audit(a.project,a.game_dir)
