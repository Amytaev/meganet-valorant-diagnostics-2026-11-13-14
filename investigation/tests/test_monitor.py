import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from monitor_storage import Journal, Detector, threshold, atomic_json
from analyze_continuous import analyze


class MonitorTests(unittest.TestCase):
    def test_manifest_bounds_match_physical_rows_after_rotation(self):
        with tempfile.TemporaryDirectory() as directory:
            journal=Journal(directory,'test',rotate_bytes=1)
            for i in range(5):
                journal.emit('probe',value=i)
            journal.close()
            manifest=json.loads((Path(directory)/'segments.json').read_text())
            for segment in manifest['segments']:
                rows=[json.loads(line) for line in (Path(directory)/segment['name']).read_text().splitlines()]
                self.assertEqual(segment['first_seq'],rows[0]['seq'])
                self.assertEqual(segment['last_seq'],rows[-1]['seq'])

    def test_frozen_threshold_is_not_trained_on_a_spike(self):
        detector=Detector({'router':dict(threshold([2]*60),source='reference')})
        alert=detector.check(dict(target='router',status='Success',rtt_ms=100,elapsed_ms=5000,quality='normal'))
        self.assertEqual(alert['event'],'icmp_rtt_threshold')
        self.assertEqual(detector.baselines['router']['median_ms'],2)

    def test_early_timeouts_do_not_become_network_loss_alerts(self):
        detector=Detector()
        for i in range(6):
            alert=detector.check(dict(target='router',status='TimedOut',rtt_ms=None,elapsed_ms=i*2000,quality='early_timeout_unverified'))
            self.assertEqual(alert['event'],'probe_quality')
            self.assertFalse(alert['network_fault_proven'])
        self.assertNotIn('router',detector.misses)

    def test_three_real_nonresponses_alert_without_assigning_fault(self):
        detector=Detector()
        events=[detector.check(dict(target='router',status='TimedOut',rtt_ms=None,elapsed_ms=i*2000,quality='normal')) for i in range(3)]
        self.assertIsNone(events[0]); self.assertIsNone(events[1])
        self.assertEqual(events[2]['event'],'icmp_nonresponse_run')

    def test_rotation_preserves_sequence_and_pins_incident_neighbours(self):
        with tempfile.TemporaryDirectory() as directory:
            journal=Journal(directory,'test',rotate_bytes=1,budget_bytes=1)
            for i in range(4):
                journal.emit('probe',value=i)
            journal.pin()
            for i in range(4,7):
                journal.emit('probe',value=i)
            journal.prune(); journal.close()
            self.assertTrue(journal.storage_pressure); self.assertTrue(journal.deleted)
            self.assertTrue(all(not s.get('deleted') for s in journal.segments if s['pinned']))
            records=[json.loads(line) for file in sorted(Path(directory).glob('telemetry*.jsonl')) for line in file.read_text().splitlines()]
            self.assertEqual([r['seq'] for r in records],list(range(records[0]['seq'],8)))

    def test_disk_error_buffers_then_recovers_without_losing_records(self):
        with tempfile.TemporaryDirectory() as directory:
            journal=Journal(directory,'test')
            with patch.object(journal,'_append',side_effect=OSError('simulated disk failure')):
                journal.emit('probe',value=1); journal.emit('probe',value=2)
                self.assertEqual(len(journal.pending),2)
            journal.io_error=None; journal.service(); journal.close()
            records=[json.loads(line) for f in Path(directory).glob('telemetry*.jsonl') for line in f.read_text().splitlines()]
            self.assertEqual([r['seq'] for r in records],[1,2])

    def test_reader_uses_watermark_and_ignores_incomplete_tail(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); journal=Journal(root,'test')
            journal.emit('probe',target='router',status='Success',rtt_ms=2,sent_local='time1',elapsed_ms=0,quality='normal')
            journal.emit('probe',target='router',status='Success',rtt_ms=100,sent_local='time2',elapsed_ms=2000,quality='normal')
            atomic_json(root/'metadata.json',dict(schema=3,run_id='test'))
            atomic_json(root/'status.json',dict(state='running',committed_seq=1))
            result=analyze(root)
            self.assertFalse(result['complete']); self.assertEqual(result['metrics'][0]['max_ms'],2)
            journal.close()
            with next(root.glob('telemetry*.jsonl')).open('ab') as f:
                f.write(b'{"partial":')
            self.assertEqual(analyze(root)['metrics'][0]['samples'],1)


if __name__=='__main__':
    unittest.main()
