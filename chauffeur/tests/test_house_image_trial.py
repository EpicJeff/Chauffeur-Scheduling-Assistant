"""Paid trial guardrails; never contacts a provider or reads real credentials."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    'house_image_trial', Path(__file__).resolve().parents[1] / 'tools/evaluate_house_images.py')
trial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trial)


class PaidTrialGuards(unittest.TestCase):
    def test_no_free_key_fallback_and_no_implicit_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            settings = folder / 'settings.json'
            settings.write_text(json.dumps({'llm_gemini_api_key': 'test-free-key'}))
            self.assertFalse(trial.paid_key(settings))
            settings.write_text(json.dumps({'settings': {'1': {
                'llm_gemini_paid_api_key': 'test-paid-key'}}}))
            output = folder / 'run'
            argv = ['trial', '--live', '--settings', str(settings), '--out', str(output)]
            with patch.object(sys, 'argv', argv), patch.object(
                trial, 'request', side_effect=RuntimeError('503 test-paid-key')
            ) as request, contextlib.redirect_stdout(io.StringIO()):
                trial.main()
                self.assertEqual(request.call_count, 2)
                report = (output / 'results.json').read_text()
                self.assertNotIn('test-paid-key', report)
                self.assertTrue(all(r['status'] == 'failed' for r in json.loads(report)['results']))
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    trial.main()
                self.assertEqual(request.call_count, 2)

    def test_key_file_metadata_check_never_generates(self):
        with tempfile.TemporaryDirectory() as directory:
            key_file = Path(directory) / 'key.txt'
            key_file.write_text('test-paid-key\n')
            out = Path(directory) / 'unused'
            argv = ['trial', '--key-file', str(key_file), '--out', str(out)]
            with patch.object(sys, 'argv', argv), patch.object(
                trial, 'request', return_value={'supportedGenerationMethods': ['generateContent']}
            ) as request, contextlib.redirect_stdout(io.StringIO()) as printed:
                trial.main()
            self.assertEqual(request.call_count, 2)
            self.assertTrue(all(len(call.args) == 2 for call in request.call_args_list))
            self.assertNotIn('test-paid-key', printed.getvalue())
            self.assertFalse(out.exists())


if __name__ == '__main__':
    unittest.main()
