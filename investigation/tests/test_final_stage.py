import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from final_stage_analysis import read_complete


class FinalAuditTests(unittest.TestCase):
    def test_bad_manifest_bound_is_not_reported_as_a_missing_physical_row(self):
        with tempfile.TemporaryDirectory() as directory:
            run=Path(directory)
            content=b'{"seq":1}\n{"seq":2}\n'
            (run/'telemetry-00000001.jsonl').write_bytes(content)
            (run/'segments.json').write_text(json.dumps(dict(segments=[dict(name='telemetry-00000001.jsonl',first_seq=2,last_seq=2,bytes=len(content))],deleted=[])))
            rows,segments,_=read_complete(run)
            self.assertEqual([r['seq'] for r in rows],[1,2])
            self.assertFalse(segments[0]['bounds_match'])
            self.assertTrue(segments[0]['bytes_match'])

    def test_final_audit_rejects_corrupt_json_instead_of_silently_ignoring_it(self):
        with tempfile.TemporaryDirectory() as directory:
            run=Path(directory)
            (run/'telemetry-00000001.jsonl').write_bytes(b'{"seq":1}\n{"partial":')
            (run/'segments.json').write_text('{"segments":[],"deleted":[]}')
            with self.assertRaises(json.JSONDecodeError):
                read_complete(run)


if __name__=='__main__':
    unittest.main()
