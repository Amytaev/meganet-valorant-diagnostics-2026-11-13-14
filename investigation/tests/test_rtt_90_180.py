import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]/'scripts'))
import analyze_rtt_90_180 as a


class RttBandTests(unittest.TestCase):
    def controls(self):
        return [dict(target=t, n=4, statuses={'Success':4}, max_ms=v) for t,v in zip(a.TARGETS,[2,3,24,93,92])]

    def limits(self):
        return {t:{'threshold_ms':v} for t,v in zip(a.TARGETS,[15,16,38,109,106])}|{a.EARLY_RETN:{'threshold_ms':100}}

    def test_missing_or_error_samples_are_not_quiet(self):
        self.assertEqual(a.classify_controls(self.controls(),self.limits())[0],'all_controls_below_threshold')
        self.assertEqual(a.classify_controls(self.controls()[:-1],self.limits())[0],'uncovered_or_incomplete')
        rows=self.controls();rows[0]['statuses']={'ProbeError':4}
        self.assertEqual(a.classify_controls(rows,self.limits())[0],'measurement_error')

    def test_local_and_retn_classes_are_distinct(self):
        rows=self.controls();rows[3]['max_ms']=180
        self.assertEqual(a.classify_controls(rows,self.limits())[0],'retn_only_control_anomaly')
        rows[0]['max_ms']=140
        self.assertEqual(a.classify_controls(rows,self.limits())[0],'gateway_control_anomaly')

    def test_early_control_and_one_second_sampling(self):
        rows=self.controls();rows[-1]['target']=a.EARLY_RETN;rows[-1]['max_ms']=86
        for r in rows:r['n']=1
        self.assertEqual(a.classify_controls(rows,self.limits())[0],'uncovered_or_incomplete')
        self.assertEqual(a.classify_controls(rows,self.limits(),min_samples=1)[0],'all_controls_below_threshold')

    def test_incremental_snapshot_preserves_counters_without_identity(self):
        r=dict(seq=1,time_utc='2026-11-14T20:08:42.000+00:00',wlan='Name : WiFiFixture\nState : connected\nSSID : personal-fixture\nAP BSSID : private-ap-fixture\nRssi : -59\nChannel : 36',
               counters=[dict(Name='WiFiFixture',ReceivedBytes=100,SentBytes=50,ReceivedDiscardedPackets=0,OutboundDiscardedPackets=0,ReceivedPacketErrors=0,OutboundPacketErrors=0)])
        result=a.normalized_snapshot(r,'run-fixture',{})
        self.assertEqual(result['counters']['ReceivedBytes'],100)
        self.assertTrue(result['connected'])
        self.assertNotIn('personal-fixture',json.dumps(result))
        self.assertNotIn('private-ap-fixture',json.dumps(result))
        self.assertNotIn('WiFiFixture',json.dumps(result))

    def test_rate_is_interval_average_and_counter_reset_is_excluded(self):
        def row(time,rx,tx):return dict(source='r',time_utc=time,counters=dict(zip(a.COUNTERS,[rx,tx,0,0,0,0])))
        rows=[row('2026-11-14T20:00:00+00:00',0,0),row('2026-11-14T20:00:30+00:00',3000000,1500000)]
        rates=a.rate_intervals(rows)
        self.assertEqual(rates[0]['rx_mbps'],.8)
        self.assertEqual(rates[0]['tx_mbps'],.4)
        self.assertEqual(a.rate_intervals(rows[::-1]),rates)
        rows.append(row('2026-11-14T20:01:00+00:00',0,0))
        self.assertEqual(len(a.rate_intervals(rows)),1)

    def test_connection_ends_at_stats_not_inherited_into_menu(self):
        events=[dict(file='f',line=1,kind='endpoint_travel',time_utc='2026-11-14T20:00:00+00:00',ip='185.40.64.1',port=7004)]
        stats=[dict(file='f',line=5,time_utc='2026-11-14T20:05:00+00:00')]
        conns=a.connections(events,stats)
        self.assertIsNotNone(a.connection_for(dict(file='f',time_utc='2026-11-14T20:02:00+00:00'),conns))
        self.assertIsNone(a.connection_for(dict(file='f',time_utc='2026-11-14T20:06:00+00:00'),conns))
        self.assertIsNone(a.connection_for(dict(file='g',time_utc='2026-11-14T20:02:00+00:00'),conns))

    def test_hotkeys_are_not_numeric_rtt_or_incident_duration(self):
        def marker(event,time):return dict(source_run='run',seq=1,time_utc=time,observed_utc=time,event=event,source_kind='RegisterHotKey',eligible=True)
        result=a.marker_intervals([marker('recovery','2026-11-14T20:00:00+00:00'),marker('spike','2026-11-14T20:01:00+00:00'),
                                   marker('spike','2026-11-14T20:01:01+00:00'),marker('recovery','2026-11-14T20:01:10+00:00')])
        self.assertEqual(len(result['unpaired_recovery_markers']),1)
        self.assertEqual(result['intervals'][0]['spike_presses'],2)
        self.assertEqual(result['intervals'][0]['button_span_seconds'],10)
        self.assertNotIn('rtt_ms',result['intervals'][0])

    def test_band_boundaries(self):
        self.assertEqual([a.band_label(x) for x in [90,110,120,130,150,180]],['90-<110','110-<120','120-<130','130-<150','150-180','150-180'])


if __name__=='__main__':unittest.main()
