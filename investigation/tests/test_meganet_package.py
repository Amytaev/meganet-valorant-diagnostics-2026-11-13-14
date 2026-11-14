import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from build_meganet_package import parse_ping, parse_trace


class MeganetOutputTests(unittest.TestCase):
    def test_filtered_icmp_has_no_invented_zero_latency(self):
        result = parse_ping('Packets: Sent = 100, Received = 0, Lost = 100 (100% loss)')
        self.assertEqual(result['native_sent'], 100)
        self.assertEqual(result['echo_reply_lines'], 0)
        self.assertNotIn('native_rtt_min_max_avg_ms', result)

    def test_unreachable_native_received_is_not_an_echo_reply(self):
        result = parse_ping('Reply from 10.0.0.1: Destination host unreachable.\n'
                            'Packets: Sent = 100, Received = 100, Lost = 0 (0% loss)')
        self.assertEqual(result['native_received'], 100)
        self.assertEqual(result['echo_reply_lines'], 0)

    def test_russian_summary_preserves_native_latency_order(self):
        result = parse_ping('Ответ от 1.1.1.1: число байт=32 время=24мс TTL=57\n'
                            'Пакетов: отправлено = 100, получено = 100, потеряно = 0\n'
                            'Минимальное = 22мсек, Максимальное = 30мсек, Среднее = 24мсек')
        self.assertTrue(result['parsed'])
        self.assertEqual(result['native_rtt_min_max_avg_ms'], [22,30,24])

    def test_trace_stars_do_not_invent_a_destination_or_rtt(self):
        result = parse_trace(' 1 <1 ms 1 ms 1 ms 192.168.123.1\n'
                             ' 2 * * * Request timed out.\n'
                             ' 3 70 ms 71 ms 70 ms 87.245.233.166\n'
                             ' 4 * * * Request timed out.', '185.40.64.1')
        self.assertFalse(result['destination_address_printed'])
        self.assertEqual(result['last_responding_hop']['ttl'], 3)
        self.assertEqual(result['hops'][1]['native_rtt_tokens'], [])
        self.assertEqual(result['hops'][1]['asterisks'], 3)


if __name__ == '__main__':
    unittest.main()
