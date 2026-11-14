"""Append-only rotating journal; incident-preserving soft storage budget."""
import json
import math
import os
import statistics
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def atomic_json(path,value):
    path=Path(path); temporary=path.with_name(path.name+'.tmp')
    with temporary.open('w',encoding='utf-8',newline='\n') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2); stream.write('\n')
        stream.flush()
    os.replace(temporary,path)


def threshold(values):
    median=statistics.median(values); mad=statistics.median(abs(x-median) for x in values)
    p95=sorted(values)[math.ceil(len(values)*.95)-1]
    return dict(samples=len(values),median_ms=median,mad_ms=mad,p95_ms=p95,
                threshold_ms=max(median+max(10,6*mad),p95+10))


class Detector:
    def __init__(self,baselines=None,warmup=60):
        self.baselines=dict(baselines or {}); self.warmup=warmup
        self.training={}; self.misses={}; self.last_alert={}

    def check(self,row):
        target=row['target']; status=row['status']; mono=row['elapsed_ms']/1000
        if status=='ProbeError' or row.get('quality')=='early_timeout_unverified':
            return dict(event='probe_quality',target=target,status=status,quality=row.get('quality'),network_fault_proven=False)
        if status!='Success':
            self.misses[target]=self.misses.get(target,0)+1
            if self.misses[target]>=3 and mono-self.last_alert.get((target,'miss'),-1000)>=30:
                self.last_alert[target,'miss']=mono
                return dict(event='icmp_nonresponse_run',target=target,consecutive=self.misses[target],network_fault_proven=False)
            return None
        self.misses[target]=0
        if target not in self.baselines:
            values=self.training.setdefault(target,[]); values.append(float(row['rtt_ms']))
            if len(values)>=self.warmup:
                self.baselines[target]=dict(threshold(values),source='initial live successful replies; may already be degraded')
            return None
        limit=self.baselines[target]['threshold_ms']
        if float(row['rtt_ms'])>=limit and mono-self.last_alert.get((target,'rtt'),-1000)>=10:
            self.last_alert[target,'rtt']=mono
            return dict(event='icmp_rtt_threshold',target=target,rtt_ms=row['rtt_ms'],threshold_ms=limit,
                        source=self.baselines[target].get('source','reference'),network_fault_proven=False)
        return None


class Journal:
    def __init__(self,directory,run_id,rotate_seconds=900,rotate_bytes=4*1024**2,budget_bytes=512*1024**2):
        self.root=Path(directory).resolve(); self.root.mkdir(parents=True,exist_ok=True)
        self.run_id=run_id; self.rotate_seconds=rotate_seconds; self.rotate_bytes=rotate_bytes; self.budget=budget_bytes
        self.seq=0; self.committed_seq=0; self.segments=[]; self.file=None; self.active=None
        self.pending=deque(); self.memory_limit=10000; self.dropped=0; self.io_error=None
        self.pin_until=0; self.last_sync=time.monotonic(); self.last_retry=0; self.last_retention=0
        self.deleted=[]; self.storage_pressure=False; self.free_disk_bytes=None
        self._open()

    def _open(self):
        ordinal=len(self.segments)+1
        name=f'telemetry-{ordinal:08d}.jsonl'
        self.file=(self.root/name).open('ab',buffering=0)
        self.active=dict(name=name,first_seq=None,last_seq=None,pinned=time.monotonic()<self.pin_until,
                         start_utc=now(),closed=False,bytes=0)
        self.segments.append(self.active); self.opened=time.monotonic()
        self.manifest()

    def manifest(self):
        atomic_json(self.root/'segments.json',dict(schema=3,segments=self.segments,deleted=self.deleted,
                                                 retention='soft budget; pinned incidents and last two segments never automatically removed'))

    def pin(self):
        self.pin_until=time.monotonic()+120
        for segment in self.segments[-2:]:
            segment['pinned']=True
        try:
            self.manifest()
        except OSError as exc:
            self.io_error=type(exc).__name__+': '+str(exc)

    def _append(self,record):
        if self.file is None or self.file.closed:
            self._open()
        if time.monotonic()-self.opened>=self.rotate_seconds or self.active['bytes']>=self.rotate_bytes:
            self.file.flush(); os.fsync(self.file.fileno()); self.file.close()
            self.active.update(last_seq=self.committed_seq,closed=True,end_utc=now())
            self._open()
        data=(json.dumps(record,ensure_ascii=False,separators=(',',':'))+'\n').encode('utf-8')
        if len(data)>128*1024:
            raise ValueError('Journal record exceeds 128 KiB safety limit.')
        offset=self.file.tell()
        try:
            remaining=memoryview(data)
            while remaining:
                written=self.file.write(remaining)
                if not written:
                    raise OSError('Incomplete journal write.')
                remaining=remaining[written:]
        except OSError:
            try:
                self.file.seek(offset); self.file.truncate(offset)
            except OSError:
                pass
            raise
        if self.active['first_seq'] is None:
            self.active['first_seq']=record['seq']
        self.active['bytes']+=len(data); self.committed_seq=record['seq']

    def emit(self,kind,**data):
        self.seq+=1
        stamp=datetime.now(timezone.utc)
        record=dict(schema=3,run_id=self.run_id,seq=self.seq,kind=kind,
                    time_utc=stamp.isoformat(timespec='milliseconds'),time_local=stamp.astimezone().isoformat(timespec='milliseconds'),**data)
        if len(self.pending)>=self.memory_limit:
            self.pending.popleft(); self.dropped+=1
        self.pending.append(record)
        self.service()
        return record

    def service(self):
        current=time.monotonic()
        if self.io_error and current-self.last_retry<1:
            return
        self.last_retry=current
        try:
            while self.pending:
                self._append(self.pending[0]); self.pending.popleft()
            self.io_error=None
            if current-self.last_sync>=5:
                self.file.flush(); os.fsync(self.file.fileno()); self.last_sync=current
            if current-self.last_retention>=30:
                self.prune(); self.last_retention=current
        except (OSError,ValueError) as exc:
            self.io_error=type(exc).__name__+': '+str(exc)

    def prune(self):
        import shutil
        total=sum(s['bytes'] for s in self.segments if not s.get('deleted'))
        self.free_disk_bytes=shutil.disk_usage(self.root).free
        for segment in self.segments[:-2]:
            if total<=self.budget:
                break
            if segment['pinned'] or not segment['closed'] or segment.get('deleted'):
                continue
            original=self.root/segment['name']; path=original.resolve()
            if path.parent!=self.root or original.is_symlink():
                continue
            try:
                path.unlink()
            except OSError:
                continue
            total-=segment['bytes']; segment['deleted']=True
            self.deleted.append(dict(name=segment['name'],first_seq=segment['first_seq'],last_seq=segment['last_seq'],deleted_utc=now(),reason='ordinary unpinned segment exceeded soft budget'))
        self.storage_pressure=total>self.budget or self.free_disk_bytes<1024**3
        self.manifest()

    def health(self):
        return dict(last_seq=self.seq,committed_seq=self.committed_seq,buffered_records=len(self.pending),
                    dropped_memory_records=self.dropped,io_error=self.io_error,storage_pressure=self.storage_pressure,
                    retained_bytes=sum(s['bytes'] for s in self.segments if not s.get('deleted')),
                    soft_budget_bytes=self.budget,free_disk_bytes=self.free_disk_bytes)

    def close(self):
        self.service()
        if self.file and not self.file.closed:
            try:
                self.file.flush(); os.fsync(self.file.fileno()); self.file.close()
            except OSError as exc:
                self.io_error=type(exc).__name__+': '+str(exc)
                raise
            self.active.update(last_seq=self.committed_seq,closed=True,end_utc=now())
            self.manifest()
