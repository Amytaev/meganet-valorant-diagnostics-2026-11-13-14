"""Continuous Windows monitoring. Default: no deadline; explicit stop only."""
from __future__ import annotations
import argparse
import base64
import ctypes
import hashlib
import ipaddress
import json
import os
import queue
import subprocess
import sys
import threading
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from monitor_storage import Journal, Detector, atomic_json, now

DEFAULT_TARGETS=['192.168.123.1','89.38.164.205','1.1.1.1','87.245.238.34','87.245.233.166']
SCRIPT=Path(__file__).resolve()
DEFAULT_ROOT=SCRIPT.parents[1]/'raw'/'continuous'


def windows_directory():
    buffer=ctypes.create_unicode_buffer(32768)
    if not ctypes.windll.kernel32.GetWindowsDirectoryW(buffer,len(buffer)):
        raise OSError('Windows directory query failed.')
    return Path(buffer.value)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def active_run(root):
    root=Path(root).resolve(); pointer=read_json(root/'active.json')
    run=(root/pointer['run_name']).resolve()
    if run.parent!=root or not (run/'metadata.json').exists():
        raise ValueError('Invalid active run pointer.')
    return run


def resolve_run(value):
    path=Path(value).resolve()
    return path if (path/'metadata.json').exists() else active_run(path)


def marker(run,event,**values):
    path=resolve_run(run)
    if (path/'DONE').exists():
        raise ValueError('Monitor has already stopped.')
    command=dict(event=event,source='manual_command',observed_utc=now(),**values)
    identifier=uuid.uuid4().hex[:12]
    atomic_json(path/'commands'/(identifier+'.json'),command)
    return command


class Snapshot:
    """Bounded helper subprocess. The sampler never waits for CIM or netsh."""
    def __init__(self,targets):
        self.targets=targets; self.process=None; self.started=0; self.number=0
        self.executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='system-helper')
        self.future=None

    def start(self):
        if self.future:
            return
        self.future=self.executor.submit(self._read)

    def _read(self):
        self.number+=1
        script=SCRIPT.with_name('Collect-Snapshot.ps1')
        command="& '"+str(script).replace("'","''")+"' -TargetsJson '"+json.dumps(self.targets)+"'"+(' -Inventory' if self.number==1 or self.number%20==0 else '')
        encoded=base64.b64encode(command.encode('utf-16le')).decode('ascii')
        env=dict(os.environ)
        engine=windows_directory()/'System32/WindowsPowerShell/v1.0/powershell.exe'
        env['PSModulePath']=str(engine.parent/'Modules')
        self.process=subprocess.Popen([str(engine),'-NoLogo','-NoProfile','-NonInteractive','-EncodedCommand',encoded],
                                      stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                                      creationflags=0x08000000|0x4000,env=env)
        try:
            output,_=self.process.communicate(timeout=8)
            code=self.process.returncode
        except subprocess.TimeoutExpired:
            self.process.kill(); self.process.communicate(timeout=2)
            return dict(errors=['system snapshot exceeded 8 seconds; helper terminated, sampler continued'])
        finally:
            self.process=None
        if code or len(output)>128*1024:
            return dict(errors=['snapshot failed or exceeded size bound'])
        try:
            return json.loads(output.decode('utf-8-sig'))
        except (ValueError,UnicodeError):
            return dict(errors=['snapshot output could not be decoded'])

    def poll(self):
        if not self.future or not self.future.done():
            return None
        try:
            return self.future.result()
        except Exception as exc:
            return dict(errors=['snapshot helper:'+type(exc).__name__])
        finally:
            self.future=None

    def close(self):
        if self.process:
            self.process.kill()
        self.executor.shutdown(wait=False,cancel_futures=True)


def collect(args):
    from monitor_windows import Native, Controls
    native=Native()
    name='Local\\ValorantNetDiag-Continuous-v3'
    if args.test_instance:
        name+='-loopback-test-'+args.test_instance
    native.singleton(name)
    try:
        return collect_owned(args,native)
    finally:
        native.close()


def collect_owned(args,native):
    from monitor_windows import Controls
    root=Path(args.root).resolve(); root.mkdir(parents=True,exist_ok=True)
    run_id=uuid.uuid4().hex
    run=root/(datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+run_id[:8])
    run.mkdir(); (run/'commands').mkdir()
    stop=threading.Event(); finished=threading.Event(); events=queue.Queue()
    origin=time.monotonic(); controls=None; journal=None; snapshot=Snapshot(args.targets)
    executor=ThreadPoolExecutor(max_workers=len(args.targets),thread_name_prefix='ICMP')
    pending={}; last_sent={}; probe_status_counts=Counter(); valid_targets=set(); cycle=0; reason='explicit_stop'; failed=False
    reference=Path(args.baseline) if args.baseline else SCRIPT.parents[1]/'config/anomaly-baseline-2026-11-14.json'
    baselines=read_json(reference)['targets'] if reference.exists() else {}
    detector=Detector(baselines)
    metadata=dict(schema=3,run_id=run_id,pid=os.getpid(),start_utc=now(),context=args.context,targets=args.targets,
                  protocol='ICMPv4',payload_bytes=32,interval_seconds=args.interval,timeout_ms=args.timeout,
                  duration_requested_seconds=args.duration,continuous=args.duration==0,
                  process_in_job=native.in_job(),desktop=native.desktop_info(),parent_pid=os.getppid(),launch_method=args.launch_method,admin_token=bool(ctypes.windll.shell32.IsUserAnAdmin()),
                  rotation_seconds=args.rotate_seconds,rotation_bytes=args.rotate_mib*1024**2,soft_budget_mib=args.budget_mib,
                  retention='preserve incidents; soft budget',timezone=time.tzname,
                  game_network_telemetry='unavailable: no verified supported live RTT/loss source; manual markers only',
                  source_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (SCRIPT,SCRIPT.with_name('monitor_storage.py'),SCRIPT.with_name('monitor_windows.py'))})
    atomic_json(run/'metadata.json',metadata)
    atomic_json(root/'active.json',dict(run_name=run.name,run_id=run_id,pid=os.getpid()))
    try:
        journal=Journal(run,run_id,args.rotate_seconds,args.rotate_mib*1024**2,args.budget_mib*1024**2)
        controls=Controls(events,stop,finished,hotkeys=not args.no_hotkeys)
        journal.emit('lifecycle',event='started',metadata=metadata,hotkeys=controls.available)
        next_probe=origin; next_snapshot=origin; next_status=0; last_tick=origin

        def handle_reply(target,future):
            try:
                row=future.result()
            except Exception as exc:
                journal.pin(); journal.emit('error',event='probe_worker_error',target=target,error_type=type(exc).__name__)
                return
            if target in last_sent:
                gap=row['elapsed_ms']-last_sent[target]
                if gap>args.interval*1500:
                    journal.pin(); journal.emit('sampling_gap',target=target,actual_interval_ms=gap,expected_interval_ms=args.interval*1000)
            last_sent[target]=row['elapsed_ms']
            probe_status_counts[row['status']]+=1
            if row['status']!='ProbeError':
                valid_targets.add(target)
            journal.emit('probe',**row)
            alert=detector.check(row)
            if alert:
                journal.pin(); journal.emit('anomaly',**alert)

        while not stop.is_set():
            tick=time.monotonic()
            if (run/'STOP').exists():
                reason='stop_file'; break
            if args.duration and tick-origin>=args.duration:
                reason='explicit_test_duration'; break
            if tick-last_tick>max(5,args.interval*3):
                journal.pin(); journal.emit('sampling_gap',event='main_loop_stall_or_sleep',elapsed_seconds=tick-last_tick)
            last_tick=tick
            for target,future in list(pending.items()):
                if future.done():
                    handle_reply(target,future); del pending[target]
            while not events.empty():
                item=events.get_nowait(); journal.pin(); journal.emit('game_marker',**item)
                if item['event'] in ('stop','windows_session_end'):
                    reason=item['event']; stop.set()
            for command in list((run/'commands').glob('*.json'))[:20]:
                try:
                    if command.stat().st_size>16384:
                        raise ValueError('Oversized marker.')
                    data=read_json(command)
                    allowed=('event','source','observed_utc','observed_local','rtt_avg_ms','rtt_max_ms','loss_in_pct','loss_out_pct','context')
                    data={key:value for key,value in data.items() if key in allowed}
                    if data.get('event') not in ('spike','recovery','note','stop','context','measurement'):
                        raise ValueError('Unknown marker type.')
                    journal.pin(); journal.emit('game_marker',**data)
                    if data['event']=='stop':
                        reason='manual_command'; stop.set()
                except (ValueError,OSError) as exc:
                    journal.emit('error',event='invalid_manual_command',error_type=type(exc).__name__)
                finally:
                    command.unlink(missing_ok=True)
            if tick>=next_probe and not stop.is_set():
                cycle+=1
                for target in args.targets:
                    if target not in pending:
                        pending[target]=executor.submit(native.probe,target,args.timeout,cycle,origin)
                    else:
                        journal.pin(); journal.emit('sampling_gap',event='previous_probe_still_running',target=target,cycle=cycle)
                next_probe+=args.interval
                if next_probe<tick:
                    next_probe=tick+args.interval  # no catch-up traffic burst after resume
            if not args.skip_system and tick>=next_snapshot:
                try:
                    snapshot.start()
                except OSError as exc:
                    journal.emit('error',event='snapshot_start_failed',error_type=type(exc).__name__)
                next_snapshot=tick+30
            result=snapshot.poll()
            if result is not None:
                journal.emit('system_snapshot',**result)
            journal.service()
            if tick>=next_status:
                try:
                    atomic_json(run/'status.json',dict(schema=3,run_id=run_id,pid=os.getpid(),state='running',heartbeat_utc=now(),
                                elapsed_seconds=round(tick-origin,3),cycles=cycle,targets=args.targets,hotkeys=controls.available,
                                baselines=detector.baselines,probe_status_counts=dict(probe_status_counts),valid_probe_targets=sorted(valid_targets),**journal.health()))
                except OSError:
                    pass  # disk failure must not terminate network measurements
                next_status=tick+1
            stop.wait(.05)
    except BaseException as exc:
        failed=True; reason='error:'+type(exc).__name__
        if journal:
            journal.emit('error',event='main_failed',error_type=type(exc).__name__)
        raise
    finally:
        stop.set()
        while not events.empty():
            event=events.get_nowait()
            if event['event'] in ('stop','windows_session_end'):
                reason=event['event']
            if journal:
                journal.pin(); journal.emit('game_marker',**event)
        # Finish bounded in-flight ICMP calls; never launch a replacement monitor.
        deadline=time.monotonic()+args.timeout/1000+1
        while pending and time.monotonic()<deadline:
            for target,future in list(pending.items()):
                if future.done():
                    handle_reply(target,future); del pending[target]
            time.sleep(.02)
        snapshot.close(); executor.shutdown(wait=False,cancel_futures=True)
        if journal:
            try:
                journal.emit('lifecycle',event='stopped',reason=reason,unfinished_probes=list(pending))
                journal.close()
            except OSError:
                pass
        metadata.update(end_utc=now(),stop_reason=reason,failed=failed,cycles=cycle,
                        final_health=journal.health() if journal else None,unfinished_probes=list(pending))
        try:
            atomic_json(run/'metadata.json',metadata)
            atomic_json(run/'status.json',dict(metadata,state='stopped',heartbeat_utc=now()))
            atomic_json(run/'DONE',dict(reason=reason,end_utc=now(),durable=not journal.io_error and not journal.pending if journal else False))
        except OSError:
            pass
        finished.set()
        if controls:
            controls.close()
    return 1 if failed else 0


def start(args):
    if os.name!='nt':
        raise RuntimeError('Local Windows is required.')
    from monitor_windows import Native
    root=Path(args.root).resolve(); root.mkdir(parents=True,exist_ok=True)
    # Check the existing heartbeat before trying to spawn. The kernel mutex is authoritative.
    try:
        old=active_run(root); status=read_json(old/'status.json')
        age=(datetime.now(timezone.utc)-datetime.fromisoformat(status['heartbeat_utc'])).total_seconds()
        if status['state']=='running' and age<10:
            print(json.dumps(dict(already_running=True,run_path=str(old),status=status),ensure_ascii=False)); return 0
    except (OSError,ValueError,KeyError):
        pass
    pythonw=Path(sys.executable).with_name('pythonw.exe')
    if not pythonw.exists():
        raise RuntimeError('pythonw.exe is required for a windowless independent launch.')
    argv=[str(pythonw),str(SCRIPT),'run',*sys.argv[2:]]
    log=root/('launcher-'+uuid.uuid4().hex+'.stderr.txt')
    # Windows job containment may survive BREAKAWAY. Use the OS WMI broker as an
    # independent creator; this is a one-shot process creation, not a scheduled task.
    broker=SCRIPT.with_name('Start-MonitorBroker.ps1')
    argv+=['--launch-method','wmi-broker','--root',str(root)]
    if args.baseline:
        argv+=['--baseline',str(Path(args.baseline).resolve())]
    line=subprocess.list2cmdline(argv)
    command="& '"+str(broker).replace("'","''")+"' -CommandLine '"+line.replace("'","''")+"' -WorkingDirectory '"+str(SCRIPT.parent).replace("'","''")+"'"
    encoded=base64.b64encode(command.encode('utf-16le')).decode('ascii')
    env=dict(os.environ); engine=windows_directory()/'System32/WindowsPowerShell/v1.0/powershell.exe'
    env['PSModulePath']=str(engine.parent/'Modules')
    result=subprocess.run([str(engine),'-NoLogo','-NoProfile','-NonInteractive','-EncodedCommand',encoded],
                          stdin=subprocess.DEVNULL,capture_output=True,creationflags=0x08000000,env=env,timeout=15)
    log.write_bytes(result.stderr)
    if result.returncode:
        raise RuntimeError('WMI broker failed. Inspect '+str(log))
    launch=json.loads(result.stdout.decode('utf-8-sig')); child_pid=int(launch['pid'])
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        try:
            run=active_run(root); meta=read_json(run/'metadata.json'); status=read_json(run/'status.json')
            if meta['pid']==child_pid and status['state']=='running' and set(status.get('valid_probe_targets',[]))==set(args.targets):
                if meta['parent_pid']!=launch['parent_pid'] or meta['admin_token']:
                    (run/'STOP').touch()
                    raise RuntimeError('Independent creator or non-admin token verification failed.')
                print(json.dumps(dict(run_path=str(run),pid=child_pid,independent_creator=launch,
                                      process_in_job=meta['process_in_job'],hotkeys=status['hotkeys'],stderr=str(log)),ensure_ascii=False))
                return 0
        except (FileNotFoundError,KeyError,ValueError):
            pass
        time.sleep(.1)
    try:
        if read_json(active_run(root)/'metadata.json')['pid']==child_pid:
            (active_run(root)/'STOP').touch()
    except OSError:
        pass
    raise RuntimeError('Startup did not produce usable ICMP results for every target; STOP requested. Inspect '+str(log))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['run','start','status','stop','mark'])
    parser.add_argument('--root',default=str(DEFAULT_ROOT))
    parser.add_argument('--targets',nargs='+',default=DEFAULT_TARGETS)
    parser.add_argument('--interval',type=float,default=2)
    parser.add_argument('--timeout',type=int,default=1500)
    parser.add_argument('--rotate-seconds',type=float,default=900)
    parser.add_argument('--rotate-mib',type=float,default=4)
    parser.add_argument('--budget-mib',type=float,default=512)
    parser.add_argument('--duration',type=float,default=0,help='Explicit bounded test only; 0 means continuous.')
    parser.add_argument('--baseline')
    parser.add_argument('--context',choices=['Range','Stockholm-unrated','Unknown'],default='Unknown')
    parser.add_argument('--no-hotkeys',action='store_true')
    parser.add_argument('--launch-method',choices=['direct','wmi-broker'],default='direct')
    parser.add_argument('--test-instance',help=argparse.SUPPRESS)
    parser.add_argument('--skip-system',action='store_true')
    parser.add_argument('--event',choices=['spike','recovery','note','context','measurement'],default='note')
    args=parser.parse_args()
    if not 1<=len(args.targets)<=5 or any(ipaddress.ip_address(t).version!=4 for t in args.targets):
        parser.error('Use one to five literal IPv4 targets.')
    if args.test_instance and (not args.test_instance.isalnum() or len(args.test_instance)>32 or not args.no_hotkeys or not all(ipaddress.ip_address(t).is_loopback for t in args.targets)):
        parser.error('Test isolation is allowed only on loopback without registered hotkeys.')
    if not 1<=args.interval<=30 or not 1000<=args.timeout<=3000 or args.timeout>args.interval*1000:
        parser.error('Use interval 1..30 seconds and timeout 1000..3000 ms fitting the interval.')
    if args.rotate_seconds<1 or args.rotate_mib<=0 or args.budget_mib<=0 or args.duration<0:
        parser.error('Invalid rotation, storage or duration setting.')
    if args.action=='start':
        return start(args)
    if args.action=='run':
        return collect(args)
    run=resolve_run(args.root)
    if args.action=='mark':
        print(json.dumps(marker(run,args.event),ensure_ascii=False)); return 0
    if args.action=='status':
        status=read_json(run/'status.json')
        status['heartbeat_age_seconds']=(datetime.now(timezone.utc)-datetime.fromisoformat(status['heartbeat_utc'])).total_seconds()
        status['health_assessment']='stopped' if status['state']=='stopped' else ('stale_or_interrupted' if status['heartbeat_age_seconds']>10 else 'recent_heartbeat')
        print(json.dumps(status,ensure_ascii=False,indent=2)); return 0
    (run/'STOP').touch()
    deadline=time.monotonic()+10
    while time.monotonic()<deadline and not (run/'DONE').exists():
        time.sleep(.1)
    if not (run/'DONE').exists():
        raise RuntimeError('STOP was requested, but clean finalization is not confirmed. No process was force-killed.')
    print(json.dumps(dict(run_path=str(run),done=read_json(run/'DONE')),ensure_ascii=False)); return 0


if __name__=='__main__':
    try:
        raise SystemExit(main())
    except Exception as failure:
        print(type(failure).__name__+': '+str(failure),file=sys.stderr)
        raise SystemExit(1)
