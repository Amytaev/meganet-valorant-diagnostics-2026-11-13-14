"""Independent raw-line and SQLite verification; offline and read-only to sources."""
import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import tempfile
from analyze_rtt_open import analyze
from analyze_rtt_90_180 import read_json, epoch


def verify(project,game_dir):
    root=project/'reports';inputs=root/'evidence/rtt-open-2026-11-15';data=root/'rtt-open-data'
    events=read_json(data/'all-game-points-context.json');actual=[]
    for s in read_json(inputs/'source-lineage.json')['frozen_game_sources']:
        raw=(game_dir/s['file']).read_bytes()[:s['bytes']]
        if hashlib.sha256(raw).hexdigest()!=s['sha256']:raise ValueError('Original hash mismatch')
        for n,line in enumerate(raw.decode('utf-8-sig').splitlines(),1):
            m=re.search(r'^\[([^]]+)\].*Average Ping Threshold (?:critically )?exceeded! Current: ([\d.]+)',line)
            if m:
                t=datetime.strptime(m[1],'%Y.%m.%d-%H.%M.%S:%f').replace(tzinfo=timezone.utc).isoformat(timespec='milliseconds')
                actual.append((s['file'],n,t,float(m[2])))
    expected=[(e['file'],e['line'],e['time_utc'],e['value']) for e in events]
    if sorted(actual)!=sorted(expected):raise ValueError('Raw game line replay differs')
    db=sqlite3.connect(':memory:');db.execute('create table probes(target text,t real,status text,rtt real)');total=0
    for f in [root/'evidence/rtt-90-180-2026-11-15/inputs/control-probes.csv',inputs/'additional-control-probes.csv']:
        with f.open(encoding='utf-8',newline='') as h:
            for r in csv.DictReader(h):
                if r['eligible']=='1':
                    db.execute('insert into probes values(?,?,?,?)',(r['target'],epoch(r['sent_utc']),r['status'],float(r['rtt_ms']) if r['rtt_ms'] else None));total+=1
    db.execute('create index target_time on probes(target,t)');windows=0;classes=Counter()
    targets=['192.168.123.1','89.38.164.205','1.1.1.1','87.245.238.34','87.245.233.166']
    limits={'192.168.123.1':15,'89.38.164.205':16,'1.1.1.1':38,'87.245.238.34':109,'87.245.233.166':106,'87.245.234.191':100}
    for e in events:
        t=epoch(e['time_utc']);rows={}
        for c in e['controls_4s']:
            found=db.execute('select status,rtt,t from probes where target=? and t between ? and ? order by t',(c['target'],t-4,t+4)).fetchall()
            success=[r[1] for r in found if r[0]=='Success' and r[1] is not None]
            if c['n']!=len(found) or c['max_ms']!=(max(success) if success else None):raise ValueError('SQL window differs')
            if c['statuses']!=dict(Counter(r[0] for r in found)):raise ValueError('SQL statuses differ')
            rows[c['target']]=found;windows+=1
        chosen=[x if x in rows or x!='87.245.233.166' else '87.245.234.191' for x in targets]
        if any(len(rows.get(x,[]))<2 for x in chosen):category='uncovered_or_incomplete'
        else:
            bad=[any(s!='Success' or r is None or r>=limits[x] for s,r,_ in rows[x]) for x in chosen]
            category=(['gateway_control_anomaly','near_without_gateway_anomaly','public_without_near_anomaly','retn_only_control_anomaly','retn_only_control_anomaly'][bad.index(True)] if any(bad) else 'all_controls_below_threshold')
        if category!=e['control_class_4s']:raise ValueError('Independent class differs')
        classes[category]+=1
    db.close()
    with tempfile.TemporaryDirectory(prefix='rtt-open-replay-') as tmp:
        out=Path(tmp);analyze(project,inputs,out);replayed=[]
        for f in sorted(out.glob('*.json')):
            if f.read_bytes()!=(data/f.name).read_bytes():raise ValueError('Numerical replay differs: '+f.name)
            replayed.append(f.name)
    report=(root/'VALORANT-RTT-OPEN-INVESTIGATION.md').read_text(encoding='utf-8')
    table=len(re.findall(r'^\| P\d{3} \|',report,re.M))
    if table!=len(events):raise ValueError('Report table differs')
    result=dict(independently_parsed_game_lines=len(actual),independently_checked_sql_target_windows=windows,
                independently_checked_sql_game_classes=len(events),classes=dict(classes),eligible_probes=total,
                byte_identical_offline_replayed_results=replayed,full_report_table_rows=table,
                no_game_values_below_threshold_invented=all(e['value']>=120 and e['baseline_ms'] is None and e['continuous_duration_seconds'] is None for e in events))
    (inputs/'NUMERICAL-VERIFICATION.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='byte_identical_offline_replayed_results'}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--project',type=Path,default=Path(__file__).resolve().parents[1]);p.add_argument('--game-dir',type=Path,required=True)
    a=p.parse_args();verify(a.project,a.game_dir)
