import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

SPEC = importlib.util.spec_from_file_location('rrt', Path(__file__).parents[1]/'scripts/analyze_rrt_logs.py')
rrt = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rrt)


class RrtAnalysisTests(unittest.TestCase):
    def test_archive_paths_and_credential_exclusion(self):
        for bad in ('../outside', '/absolute', 'C:/outside', 'a/../../outside', 'a\\..\\outside', 'a:stream'):
            with self.assertRaises(ValueError):
                rrt.safe_member(bad)
        self.assertFalse(rrt.selected('Riot Client Config', 'lockfile'))
        self.assertFalse(rrt.selected('Riot Client Config', 'RiotClientSettings.yaml'))
        self.assertFalse(rrt.selected('VALORANT Crashes', 'memory.dmp'))
        self.assertFalse(rrt.selected('Riot Vanguard Logs', 'vgc.log'))

    def test_duplicate_archive_is_not_second_observation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root/'source'
            src.mkdir()
            with zipfile.ZipFile(src/'a.zip', 'w') as z:
                z.writestr('NetworkInfo.txt', 'sample')
                z.writestr('Riot Client Config/lockfile', 'sensitive fixture omitted')
            (src/'b.zip').write_bytes((src/'a.zip').read_bytes())
            archives, members, files = rrt.inventory_extract(src, root/'private-scratch')
            self.assertEqual(archives[1]['duplicate_of'], 'a.zip')
            self.assertEqual(len(files), 1)
            self.assertEqual(len(members), 2)

    def test_numeric_ping_and_endpoint_never_export_url_credentials(self):
        lines = [
            '[2026.11.14-09.27.46:264][597]LogInstabilityTrackingDetails: Error: Average Ping Threshold critically exceeded! Current: 383.31, Threshold: 200.00',
            '[2026.11.14-09.31.48:987][540]LogNet: Warning: UNetConnection::ReceivedPacket - Too many received packets to ack (256) since last sent packet. InSeq: 5608 RemoteAddr: 162.249.72.1:7004, UniqueId: private-player',
            '[2026.11.14-09.08.49:238][323]LogTravelManager: Beginning travel to 185.40.64.1:7004?AuthValue=private-credential',
            '[2026.11.14-09.28.00:000][001]ArbitraryLog: player=private-name NetworkRtt=999',
        ]
        coverage, events, stats = rrt.parse_game('\n'.join(lines), 'file-1', 'ShooterGame.log')
        self.assertEqual(events[0]['value'], 383.31)
        self.assertEqual(events[0]['time_local'], '2026-11-14T14:27:46.264+05:00')
        self.assertEqual(events[1]['kind'], 'endpoint_received_packet')
        self.assertEqual(events[2]['kind'], 'endpoint_travel')
        self.assertNotIn('private-', json.dumps(events))
        self.assertEqual(len(events), 3)

    def test_settings_and_engine_latency_are_not_game_ping(self):
        text = '\n'.join([
            '[2026.11.14-09.27.46:264][597]LogShooterGameUserSettings: PlayerPerfShowNetworkRtt=3',
            '[2026.11.14-09.27.46:264][597]LogPerformance: Avg.Engine Latency(ms) 8.1',
            '[2026.11.14-09.27.46:264][597]LogPlatformCommon: Platform HTTP Query End. QueryName: [Latency_Stats], URL [POST service] Response Code: [204], Seconds Since Query [0.233000]',
        ])
        _, events, _ = rrt.parse_game(text, 'f', 'ShooterGame.log')
        self.assertEqual([e['kind'] for e in events], ['http_latency_stats_upload'])
        self.assertEqual(events[0]['elapsed_seconds'], .233)

    def test_committed_prefix_and_window_limits(self):
        rows = [dict(seq=1, kind='probe', time_utc='2026-11-14T09:00:00.000+00:00', target='1.1.1.1', status='Success', rtt_ms=24),
                dict(seq=2, kind='probe', time_utc='2026-11-14T09:00:02.000+00:00', target='1.1.1.1', status='TimedOut', rtt_ms=None)]
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p/'telemetry-00000001.jsonl').write_text('\n'.join(map(json.dumps, rows))+'\n{"partial"', encoding='utf-8')
            result = rrt.read_records(p, max_seq=2)
            self.assertEqual(len(result), 2)
            with self.assertRaises(ValueError):
                rrt.read_records(p)
        summary = rrt.summarize_window(rows, rows[0]['time_utc'], rows[1]['time_utc'])
        self.assertEqual(summary[0]['n'], 2)
        self.assertEqual(summary[0]['statuses'], {'Success': 1, 'TimedOut': 1})
        self.assertEqual(summary[0]['median_ms'], 24)


if __name__ == '__main__':
    unittest.main()
