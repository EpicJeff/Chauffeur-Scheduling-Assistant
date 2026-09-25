"""Offline paid-call budget and credential guards for the exterior experiment."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import generate_house_orbit as orbit


class OrbitGuards(unittest.TestCase):
    def test_explicit_subset_has_no_retry_and_cannot_repeat_output(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            key = folder/'key.txt'
            key.write_text('fake-paid-key')
            output = folder/'run'
            argv = ['orbit', '--key-file', str(key), '--out', str(output),
                    '--live', '--angles', '4', '6', '--model-only']
            with patch.object(sys, 'argv', argv), patch.object(
                orbit, 'request', side_effect=RuntimeError('503 fake-paid-key')
            ) as request, contextlib.redirect_stdout(io.StringIO()):
                orbit.main()
                self.assertEqual(request.call_count, 2)
                raw = (output/'results.json').read_text()
                self.assertNotIn('fake-paid-key', raw)
                report = json.loads(raw)
                self.assertEqual(report['max_requests'], 2)
                self.assertEqual([v['angle'] for v in report['views']], [4, 6])
                self.assertTrue(all(v['status'] == 'failed' for v in report['views']))
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    orbit.main()
                self.assertEqual(request.call_count, 2)

    def test_invalid_angles_and_missing_live_never_call_provider(self):
        for flags in ([], ['--live','--angles','4','4'], ['--live','--angles','8']):
            argv = ['orbit', '--key-file', 'unused-key', '--out', 'unused-out'] + flags
            with patch.object(sys, 'argv', argv), patch.object(orbit, 'request') as request:
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    orbit.main()
                request.assert_not_called()


if __name__ == '__main__':
    unittest.main()
