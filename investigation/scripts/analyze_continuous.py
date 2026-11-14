"""Analyze a fixed append watermark while the monitor keeps collecting."""
import argparse
import json
import math
import os
from collections import Counter, defaultdict, deque
from pathlib import Path
from continuous_monitor import resolve_run, read_json
from monitor_storage import atomic_json, now


def snapshot_records(run,cutoff):
    """Read each file only to its initial size; tolerate rotation and incomplete tail."""
    for path in sorted(Path(run).glob('telemetry-*.jsonl')):
        try:
            stream=path.open('rb')
        except FileNotFoundError:
            continue
        with stream:
            remaining=os.fstat(stream.fileno()).st_size
            while remaining:
                line=stream.readline(min(remaining,128*1024+1)); remaining-=len(line)
                if not line.endswith(b'\n'):
                    break
                try:
                    row=json.loads(line)
                except (ValueError,UnicodeError):
                    yield dict(kind='reader_error',path=path.name)
                    continue
                if row.get('seq',0)<=cutoff:
                    yield row


def analyze(run):
    run=resolve_run(run); state=read_json(run/'status.json'); metadata=read_json(run/'metadata.json')
    cutoff=state.get('committed_seq',state.get('final_health',{}).get('committed_seq',0))
    groups=defaultdict(lambda:dict(statuses=Counter(),hist=Counter(),sum=0,early=0,count=0,first=None,last=None))
    kinds=Counter(); recent=deque(maxlen=1000); gaps=[]; previous=0; maximum_interval=defaultdict(float); previous_sent={}
    for row in snapshot_records(run,cutoff):
        kinds[row['kind']]+=1
        seq=row.get('seq')
        if seq is not None:
            if seq!=previous+1:
                gaps.append(dict(after_seq=previous,before_seq=seq))
            previous=seq
        if row['kind'] in ('anomaly','game_marker','sampling_gap','error','reader_error'):
            recent.append(row)
        if row['kind']!='probe':
            continue
        group=groups[row['target']]; group['statuses'][row['status']]+=1; group['count']+=1
        group['first']=group['first'] or row['sent_local']; group['last']=row['sent_local']
        if row.get('quality')=='early_timeout_unverified':
            group['early']+=1
        if row['status']=='Success':
            value=int(row['rtt_ms']); group['hist'][value]+=1; group['sum']+=value
        target=row['target']
        if target in previous_sent:
            maximum_interval[target]=max(maximum_interval[target],row['elapsed_ms']-previous_sent[target])
        previous_sent[target]=row['elapsed_ms']
    metrics=[]
    for target,group in groups.items():
        count=sum(group['hist'].values()); ranked=0; p95=None
        for value,frequency in sorted(group['hist'].items()):
            ranked+=frequency
            if ranked>=math.ceil(count*.95):
                p95=value; break
        valid=group['count']-group['statuses']['ProbeError']
        metrics.append(dict(target=target,protocol='ICMPv4',samples=group['count'],statuses=dict(group['statuses']),
                            min_ms=min(group['hist']) if count else None,avg_ms=round(group['sum']/count,3) if count else None,
                            max_ms=max(group['hist']) if count else None,p95_ms=p95,
                            early_timeout_count=group['early'],nonresponse_pct=round((valid-count)*100/valid,3) if valid and not group['early'] else None,
                            first_local=group['first'],last_local=group['last'],maximum_probe_interval_ms=round(maximum_interval[target],3)))
    manifest=read_json(run/'segments.json')
    return dict(schema=3,generated_utc=now(),run_id=metadata['run_id'],run_path=str(run),
                monitor_state=state['state'],snapshot_watermark=cutoff,last_read_seq=previous,
                complete=(run/'DONE').exists(),metrics=metrics,record_counts=dict(kinds),
                missing_sequence_ranges=gaps,retention_deletions=manifest['deleted'],recent_events=list(recent),
                recent_events_limit=1000,health=state.get('final_health',state),
                limitations=['Snapshot reads only complete lines at or before its initial committed sequence.',
                             'Retention may remove ordinary old segments; this is not full history if deletions are listed.',
                             'ICMP anomalies and nonresponses are not game UDP loss or proof of an ISP fault.',
                             'Millisecond timestamp formatting does not guarantee clock accuracy or subsecond event coverage.'])


def report(result,path):
    lines=['# Непрерывный мониторинг: снимок результатов','',
           f"Состояние: `{result['monitor_state']}`; завершён: `{result['complete']}`; watermark `{result['snapshot_watermark']}`. "
           f"Снимок создан `{result['generated_utc']}`. Анализ не останавливает сбор.",'',
           '| Цель | Проб | min / avg / max, мс | p95 | ICMP неответы % |',
           '|---|---:|---:|---:|---:|']
    for item in result['metrics']:
        lines.append(f"| {item['target']} | {item['samples']} | {item['min_ms']} / {item['avg_ms']} / {item['max_ms']} | {item['p95_ms']} | {item['nonresponse_pct']} |")
    lines+=['',f"Удалённых обычных сегментов: {len(result['retention_deletions'])}; диапазонов отсутствующих sequence: {len(result['missing_sequence_ranges'])}.",
            '', 'Временные окна каждой цели, ошибки, ручные метки и аномалии приведены в соседнем JSON. '
            'Игровой RTT автоматически не получен; ICMP не подменяет игровой UDP.']
    Path(path).write_text('\n'.join(lines)+'\n',encoding='utf-8')


def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('run'); parser.add_argument('--output'); parser.add_argument('--report')
    args=parser.parse_args(); run=resolve_run(args.run); result=analyze(run)
    output=Path(args.output) if args.output else run/'analysis.latest.json'
    atomic_json(output,result)
    if args.report:
        report(result,args.report)
    print(json.dumps(dict(monitor_state=result['monitor_state'],watermark=result['snapshot_watermark'],
                          probes=sum(m['samples'] for m in result['metrics']),output=str(output)),ensure_ascii=False))


if __name__=='__main__':
    main()
