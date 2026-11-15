"""Offline tests: synthetic data only; no Native instance, probes or GUI."""
import ctypes
from ctypes import wintypes
import struct
import unittest
from analyze_rtt_open import clusters, merged, rotate, shift_reference, quant
from monitor_windows import Reply


class TemporalMethods(unittest.TestCase):
    def test_rotation_preserves_cluster_and_population(self):
        self.assertEqual(rotate(0b11001,2,5),0b00111)
        for mask in range(32):
            for offset in range(-7,8):
                self.assertEqual(rotate(mask,offset,5).bit_count(),mask.bit_count())
                self.assertEqual(rotate(rotate(mask,offset,5),-offset,5),mask)

    def test_union_does_not_duplicate_overlapping_exposure(self):
        self.assertEqual(merged([(1,4),(3,6),(9,10),(6,7)]),[[1,7],[9,10]])

    def test_cluster_gap_is_support_span_not_continuous_latency(self):
        rows=[dict(time_utc=f'2026-11-14T09:00:{s:02}+00:00',value=v) for s,v in [(0,125),(3,217),(4,155),(20,121)]]
        grouped=clusters(rows,10)
        self.assertEqual([len(g) for g in grouped],[3,1])
        self.assertEqual(max(r['value'] for r in grouped[0]),217)

    def test_shift_reference_preserves_within_block_sample_and_is_reproducible(self):
        b=dict(n=100,event_mask=0b1111<<30,bad_mask=0b1111<<30)
        a=shift_reference([b],iterations=100,seed=2)
        self.assertEqual(a,shift_reference([b],iterations=100,seed=2))
        self.assertEqual(a['observed_bad_cycles'],4)
        self.assertEqual(a['event_window_cycles'],4)
        self.assertEqual(sum(a['shifted_histogram'].values()),100)

    def test_native_reply_consumed_prefix_matches_documented_fixed_width_layout(self):
        self.assertEqual(ctypes.sizeof(wintypes.DWORD),4)
        self.assertEqual([getattr(Reply,n).offset for n in ['address','status','rtt']],[0,4,8])
        for status,rtt in [(0,93),(11010,0),(0,400)]:
            fake=struct.pack('<III',0x01010101,status,rtt)+b'\0'*(ctypes.sizeof(Reply)-12)
            r=Reply.from_buffer_copy(fake)
            self.assertEqual((r.status,r.rtt),(status,rtt))

    def test_quantile_empty_and_nearest_rank(self):
        self.assertEqual(quant([]),dict(n=0))
        self.assertEqual(quant(range(1,21))['p95'],19)


if __name__=='__main__':unittest.main()
