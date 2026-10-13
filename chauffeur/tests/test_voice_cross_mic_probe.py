"""Probe mechanics only; these fixtures are not voice-accuracy evidence."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
import wave
from unittest.mock import patch

os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_cross_mic_test_')
path = Path(__file__).resolve().parents[1] / 'tools/voice_cross_mic_probe.py'
spec = importlib.util.spec_from_file_location('cross_mic_probe', path)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def vector(index):
    return [float(i == index) for i in range(256)]


class ProbeTests(unittest.TestCase):
    def test_reverse_direction_failure_cannot_be_hidden_by_phone_checks(self):
        result = probe.transfer_report([vector(0)] * 5, [vector(0), vector(2)], vector(0), [vector(1)])
        self.assertTrue(all(r['passes'] for r in result['kitchen_reference_to_phone']))
        self.assertTrue(all(r['passes'] for r in result['phone_reference_to_held_out_phone']))
        self.assertFalse(result['phone_reference_to_fresh_kitchen'][1]['passes'])
        self.assertFalse(result['all_sample_scores_pass'])
        self.assertNotIn('vector', json.dumps(result))

    def test_weak_rival_margin_refuses_even_when_target_score_passes(self):
        rival = probe.fp.normalized([.99, .01] + [0] * 254)
        result = probe.compare(vector(0), vector(0), [rival])
        self.assertGreater(result['score'], probe.fp.THRESHOLD)
        self.assertFalse(result['passes'])

    def test_no_rivals_is_explicitly_not_household_distinction_evidence(self):
        result = probe.transfer_report([vector(0)] * 5, [vector(0)] * 2, vector(0), [])
        self.assertTrue(result['all_sample_scores_pass'])
        self.assertFalse(result['multi_member_margin_measured'])
        self.assertIsNone(result['phone_reference_to_fresh_kitchen'][0]['margin'])

    def test_inconsistent_training_does_not_make_a_phone_reference(self):
        result = probe.transfer_report([vector(0), vector(1), vector(0), vector(0), vector(0)],
                                       [vector(0)] * 2, vector(0), [])
        self.assertFalse(result['training_consistent'])
        self.assertEqual(len(result['phone_reference_to_fresh_kitchen']), 2)
        self.assertTrue(all(not r['passes'] for r in result['phone_reference_to_fresh_kitchen']))
        self.assertFalse(result['all_sample_scores_pass'])

    def test_missing_samples_are_counted_and_cannot_pass(self):
        result = probe.transfer_report([None, vector(0), vector(0), vector(0), None],
                                       [None, vector(0)], vector(0), [])
        self.assertEqual(len(result['kitchen_reference_to_phone']), 5)
        self.assertEqual(len(result['phone_reference_to_held_out_phone']), 2)
        self.assertEqual(len(result['phone_reference_to_fresh_kitchen']), 2)
        self.assertFalse(result['all_sample_scores_pass'])
        self.assertFalse(result['kitchen_reference_to_phone'][0]['usable'])

    def test_failed_decode_reports_unusable_without_printing_private_path(self):
        with patch.object(probe, 'embed', side_effect=ValueError('private input details')):
            vector_result, diagnostic = probe.sample(Path('private-sample.wav'))
        self.assertIsNone(vector_result)
        self.assertFalse(diagnostic['usable'])
        self.assertNotIn('private', json.dumps(diagnostic))

    def test_supported_wav_is_read_only_and_overlong_audio_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            recording = Path(temporary) / 'sample.wav'
            def write(seconds):
                with wave.open(str(recording), 'wb') as output:
                    output.setnchannels(1); output.setsampwidth(2); output.setframerate(16000)
                    output.writeframes(b'\x01\x00' * int(16000 * seconds))
            write(5)
            original = recording.read_bytes()
            with patch.object(probe.subprocess, 'run', side_effect=AssertionError('PCM WAV needs no decoder')):
                audio, rate = probe.decode(recording)
            self.assertEqual((len(audio), rate), (160000, 16000))
            self.assertEqual(recording.read_bytes(), original)
            write(16)
            with self.assertRaises(ValueError): probe.decode(recording)


if __name__ == '__main__':
    unittest.main(verbosity=2)
