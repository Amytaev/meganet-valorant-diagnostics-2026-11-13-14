import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from analyze_session import summarize, counter_rates, paired_spikes, normalize_wlan_text


def row(cycle, status='Success', rtt='1', target='192.168.123.1', wait=1500):
    return dict(cycle=str(cycle),target=target,status=status,rtt_ms=rtt,
                sent_local='2026-11-13T23:00:00+05:00',sent_utc='2026-11-13T18:00:00Z',
                completed_utc='2026-11-13T18:00:01.500Z',observed_wait_ms=str(wait))


class AnalysisTests(unittest.TestCase):
    def test_localized_native_output_recovery_preserves_raw(self):
        original='Канал: 36\nRssi : -58'
        corrupted=original.encode('utf-8').decode('cp866')
        self.assertEqual(normalize_wlan_text(corrupted)[0],original)
        self.assertEqual(normalize_wlan_text(original)[0],original)

    def test_timeout_is_not_zero_rtt_and_local_error_not_network_loss(self):
        result=summarize([row(1,rtt='10'),row(2,'TimedOut',''),row(3,'ProbeError',''),row(4,rtt='30')],1500)[0]
        self.assertEqual(result['avg_ms'],20)
        self.assertAlmostEqual(result['nonresponse_pct'],33.333)
        self.assertEqual(result['requests_without_local_error'],3)
        self.assertIsNone(result['mean_abs_consecutive_rtt_delta_ms'])

    def test_early_timeout_invalidates_loss_inference(self):
        result=summarize([row(1),row(2,'TimedOut','',wait=30)],800)[0]
        self.assertEqual(result['early_timeout_count'],1)
        self.assertIsNone(result['nonresponse_pct'])
        self.assertEqual(result['recorded_nonresponse_pct'],50)

    def test_all_timeouts_have_no_latency(self):
        result=summarize([row(1,'TimedOut','')],1500)[0]
        self.assertIsNone(result['p95_ms'])
        self.assertEqual(result['nonresponse_pct'],100)

    def test_spikes_are_paired_by_cycle_not_row_position(self):
        rows=[row(1,rtt='20'),row(1,rtt='80',target='1.1.1.1'),row(2,rtt='2')]
        spikes=paired_spikes(rows)
        self.assertEqual(len(spikes),1)
        self.assertEqual(spikes[0]['rtt_ms_or_status']['1.1.1.1'],80)

    def test_counter_resets_are_not_negative_bandwidth(self):
        def counter(ms,rx,tx):
            return dict(name='WiFi',time='test',elapsed_ms=ms,rx_bytes=rx,tx_bytes=tx)
        rates=counter_rates([counter(0,100,100),counter(10000,1250100,2500100),counter(20000,0,0)])
        self.assertEqual(len(rates),1)
        self.assertEqual(rates[0]['rx_mbps'],1)
        self.assertEqual(rates[0]['tx_mbps'],2)


if __name__=='__main__':
    unittest.main()
