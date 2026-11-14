"""Opt-in loopback integration. No game inputs or system shutdown commands."""
import ctypes
import base64
import json
import os
import queue
import subprocess
import sys
import threading
import time
import unittest
import uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from continuous_monitor import active_run, marker, read_json, windows_directory
from analyze_continuous import analyze
PROJECT=Path(__file__).resolve().parents[1]
ENGINE=PROJECT/'scripts/continuous_monitor.py'


@unittest.skipUnless(os.environ.get('VALORANT_DIAG_WINDOWS_TESTS')=='1','Opt-in local Windows loopback test')
class WindowsTests(unittest.TestCase):
    def test_powershell_numeric_marker_uses_atomic_queue(self):
        root=PROJECT/'raw'/('mark-'+uuid.uuid4().hex[:8]); (root/'commands').mkdir(parents=True)
        (root/'metadata.json').write_text('{"schema":3}',encoding='utf-8')
        script=PROJECT/'scripts/Add-GameMarker.ps1'
        command="& '"+str(script).replace("'","''")+"' -SessionPath '"+str(root).replace("'","''")+"' -Event spike -RttAverageMs 180 -LossInPercent 1"
        encoded=base64.b64encode(command.encode('utf-16le')).decode('ascii')
        result=subprocess.run([str(windows_directory()/'System32/WindowsPowerShell/v1.0/powershell.exe'),'-NoProfile','-NonInteractive','-EncodedCommand',encoded],capture_output=True,creationflags=0x08000000,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        files=list((root/'commands').glob('*.json')); self.assertEqual(len(files),1)
        data=read_json(files[0]); self.assertEqual(data['rtt_avg_ms'],180); self.assertEqual(data['loss_in_pct'],1)
        self.assertRegex(data['observed_local'],r'\.\d{3}[+-]\d{2}:\d{2}$')

    def test_native_loopback_has_actual_echo_reply(self):
        from monitor_windows import Native
        native=Native()
        try:
            row=native.probe('127.0.0.1',1500,1,time.monotonic())
            self.assertEqual(row['status'],'Success',row)
            self.assertIsNotNone(row['rtt_ms'])
            self.assertEqual(row['native_status'],0)
        finally:
            native.close()

    def test_independent_parent_rotation_parallel_analysis_and_stop(self):
        root=PROJECT/'raw'/('it-'+uuid.uuid4().hex[:8])
        started=subprocess.run([sys.executable,str(ENGINE),'start','--root',str(root),'--targets','127.0.0.1',
                                '--no-hotkeys','--rotate-seconds','1','--test-instance',uuid.uuid4().hex],capture_output=True,text=True,timeout=25)
        self.assertEqual(started.returncode,0,started.stderr)
        launch=json.loads(started.stdout); run=active_run(root)
        try:
            self.assertEqual(launch['independent_creator']['parent_name'],'WmiPrvSE.exe')
            meta=read_json(run/'metadata.json')
            self.assertTrue(meta['continuous']); self.assertEqual(meta['duration_requested_seconds'],0)
            before=read_json(run/'status.json')['cycles']
            marker(run,'spike',rtt_max_ms=180)
            first=analyze(run); self.assertFalse(first['complete'])
            again=subprocess.run([sys.executable,str(ENGINE),'start','--root',str(root)],capture_output=True,text=True,timeout=15)
            self.assertTrue(json.loads(again.stdout)['already_running'])
            deadline=time.monotonic()+12
            while time.monotonic()<deadline and read_json(run/'status.json')['cycles']<before+3:
                time.sleep(.1)
            after=analyze(run)
            self.assertGreater(after['snapshot_watermark'],first['snapshot_watermark'])
            self.assertGreaterEqual(len(list(run.glob('telemetry*.jsonl'))),3)
            self.assertTrue(any(r['kind']=='game_marker' for r in after['recent_events']))
            self.assertFalse(after['missing_sequence_ranges'])
            self.assertEqual(set(after['metrics'][0]['statuses']),{'Success'})
            self.assertLess(after['metrics'][0]['maximum_probe_interval_ms'],6000)
            snapshots=[json.loads(line) for f in run.glob('telemetry*.jsonl') for line in f.read_text().splitlines() if 'system_snapshot' in line]
            self.assertTrue(snapshots,'Background system helper did not return data.')
        finally:
            stopped=subprocess.run([sys.executable,str(ENGINE),'stop','--root',str(run)],capture_output=True,text=True,timeout=15)
            self.assertEqual(stopped.returncode,0,stopped.stderr)
        self.assertTrue(analyze(run)['complete']); self.assertTrue(read_json(run/'DONE')['durable'])
        self.assertEqual(read_json(run/'metadata.json')['stop_reason'],'stop_file')

    def test_only_our_hidden_window_receives_synthetic_control_message(self):
        from monitor_windows import Controls
        events=queue.Queue(); stop=threading.Event(); finished=threading.Event(); finished.set()
        controls=Controls(events,stop,finished,hotkeys=False)
        try:
            user=ctypes.WinDLL('user32'); user.PostMessageW.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_size_t,ctypes.c_ssize_t]
            user.PostMessageW(controls.hwnd,0x312,1,0)
            self.assertEqual(events.get(timeout=2)['event'],'spike')
            # Only our private window: this does not request Windows shutdown.
            user.PostMessageW(controls.hwnd,0x16,1,0)
            self.assertTrue(stop.wait(2)); self.assertEqual(events.get(timeout=2)['event'],'windows_session_end')
        finally:
            controls.close()


if __name__=='__main__':
    unittest.main()
