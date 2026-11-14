"""Finite Windows ping/tracert package, exact requested CLI, no game/settings changes."""
import argparse
import concurrent.futures
import ctypes
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import subprocess
import threading
from datetime import datetime, timezone, timedelta


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def atomic_json(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--targets', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    targets = json.loads(args.targets.read_text(encoding='utf-8'))['measurement_targets']
    if not 1 <= len(targets) <= 4:
        parser.error('A single finite batch accepts at most four explicitly selected targets.')
    ips = [str(ipaddress.IPv4Address(t['ip'])) for t in targets]
    if len(set(ips)) != len(ips) or any(not ipaddress.ip_address(ip).is_global for ip in ips):
        parser.error('Explicit distinct globally routable IPv4 addresses required.')
    jobs = []
    for ip in ips:
        jobs += [dict(ip=ip, kind='ping', argv=['ping.exe', '-n', '100', ip], timeout_seconds=600),
                 dict(ip=ip, kind='tracert', argv=['tracert.exe', '-d', '-h', '32', ip], timeout_seconds=450)]
    if not args.execute:
        print(json.dumps(dict(plan_only=True, max_concurrent_commands=2, jobs=jobs), ensure_ascii=False))
        return
    if os.name != 'nt':
        parser.error('Measurement requires the actual local Windows host.')
    if ctypes.windll.shell32.IsUserAnAdmin():
        parser.error('Use an ordinary user token, not an administrator token.')
    args.output.mkdir(parents=True, exist_ok=True)
    if (args.output/'batch.json').exists():
        parser.error('Refusing to overwrite an existing measurement batch.')
    windows = ctypes.create_unicode_buffer(32768)
    if not ctypes.windll.kernel32.GetWindowsDirectoryW(windows, len(windows)):
        raise OSError('Cannot locate native Windows directory.')
    system = Path(windows.value)/'System32'
    codepage = ctypes.windll.kernel32.GetOEMCP()
    batch = dict(start_utc=stamp(), complete=False, ordinary_user=True, protocol='ICMPv4',
                 max_concurrent_commands=2, payload_bytes_default=32, native_timeout_ms_default=4000,
                 note='Finite diagnostic batch; no game launch, packet capture, settings changes or admin token.', jobs=[])
    lock = threading.Lock()
    def run(job):
        name = job['ip']+'-'+job['kind']
        result = dict(job, start_utc=stamp(), complete=False, output_encoding='cp'+str(codepage))
        result['start_local'] = datetime.fromisoformat(result['start_utc']).astimezone(timezone(timedelta(hours=5))).isoformat(timespec='milliseconds')
        argv = [str(system/job['argv'][0]), *job['argv'][1:]]
        print(json.dumps(dict(event='started', ip=job['ip'], kind=job['kind'], time=result['start_local'])), flush=True)
        process = None; raw = b''
        try:
            process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       creationflags=0x08000000 | 0x00004000)
            try:
                raw, _ = process.communicate(timeout=job['timeout_seconds'])
                result.update(complete=True, exit_code=process.returncode, watchdog_terminated=False)
            except subprocess.TimeoutExpired:
                process.kill(); raw, _ = process.communicate()
                result.update(exit_code=process.returncode, watchdog_terminated=True)
        except OSError as error:
            result.update(error_type=type(error).__name__, error=str(error))
        finally:
            result['end_utc'] = stamp()
            result['end_local'] = datetime.fromisoformat(result['end_utc']).astimezone(timezone(timedelta(hours=5))).isoformat(timespec='milliseconds')
            raw_file = args.output/(name+'.raw.txt')
            raw_file.write_bytes(raw)
            (args.output/(name+'.utf8.txt')).write_text(raw.decode('cp'+str(codepage), errors='replace').replace('\r\n','\n'), encoding='utf-8', newline='\n')
            result.update(raw_file=raw_file.name, raw_bytes=len(raw), raw_sha256=hashlib.sha256(raw).hexdigest())
            atomic_json(args.output/(name+'.json'), result)
            with lock:
                batch['jobs'].append(result)
                atomic_json(args.output/'batch.json', batch)
            print(json.dumps(dict(event='finished', ip=job['ip'], kind=job['kind'], complete=result['complete'],
                                  exit_code=result.get('exit_code'), bytes=len(raw))), flush=True)
        return result
    atomic_json(args.output/'batch.json', batch)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, jobs))
    batch.update(end_utc=stamp(), complete=all(r['complete'] for r in results),
                 note_exit_code='A nonzero ping exit code can mean no ICMP replies; it does not establish game packet loss.')
    atomic_json(args.output/'batch.json', batch)
    print(json.dumps(dict(event='batch_finished', complete=batch['complete'], jobs=len(results))), flush=True)


if __name__ == '__main__':
    main()
