"""Paid garage edit guards: supplied base, bounded requests and safe failures."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import generate_garage_bay as garage


class GarageGeneration(unittest.TestCase):
    def test_fixed_base_metadata_single_call_and_no_repeat(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory); key = folder/'key.txt'; key.write_text('fake-secret')
            base = Path(__file__).resolve().parents[1]/'static/house_hybrid/garage-empty.png'
            output = folder/'run'
            argv = ['garage','--live','--base',str(base),'--key-file',str(key),'--out',str(output),
                    '--vehicle','2021 Nissan Murano','--color','blue','--bay','right']
            with patch.object(sys,'argv',argv), patch.object(garage,'generate',return_value=('image/png',base.read_bytes(),{})) as generate, contextlib.redirect_stdout(io.StringIO()):
                garage.main()
                self.assertEqual(generate.call_count,1)
                _, prompt, source = generate.call_args.args
                self.assertIn('2021 Nissan Murano',prompt)
                self.assertIn('RIGHT',prompt)
                self.assertEqual(source[1],base.read_bytes())
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit): garage.main()
                self.assertEqual(generate.call_count,1)
            report = json.loads((output/'results.json').read_text())
            self.assertEqual(report['max_requests'],1)
            self.assertEqual(report['results'][0]['stage'],'occupied')

    def test_no_retry_or_key_in_failed_report(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory); key = folder/'key'; key.write_text('fake-secret')
            base = Path(__file__).resolve().parents[1]/'static/house_hybrid/garage-empty.png'
            argv = ['garage','--live','--base',str(base),'--key-file',str(key),'--out',str(folder/'run'),
                    '--vehicle','User vehicle','--color','white']
            with patch.object(sys,'argv',argv), patch.object(garage,'generate',side_effect=RuntimeError('503 fake-secret')) as generate, contextlib.redirect_stdout(io.StringIO()):
                garage.main(); self.assertEqual(generate.call_count,1)
            report = (folder/'run/results.json').read_text()
            self.assertNotIn('fake-secret',report)
            self.assertEqual(json.loads(report)['results'][0]['status'],'failed')


if __name__ == '__main__': unittest.main()
