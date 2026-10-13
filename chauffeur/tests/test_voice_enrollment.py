"""The enrollment core: answers not phrases, a one-use token per step, speaker
binding to the credential utterance, provenance and per-satellite checks.
Spec: docs/superpowers/specs/2026-10-13-voice-enrollment-design.md."""
import os, sys, tempfile, time, unittest, uuid
from pathlib import Path
from unittest.mock import patch

os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_enroll_')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import storage, voice_identity as voice, voice_fingerprint as fp

KEY = ('ha', 'assist_satellite.kitchen')
PHONE = ('phone', 'jeff')


def vector(index=0, lean=None, weight=0.9):
    """A unit vector on axis `index`, optionally leaning toward another axis."""
    v = [float(i == index) for i in range(256)]
    if lean is not None:
        v = [weight * a + (1 - weight) * float(i == lean) for i, a in enumerate(v)]
    return fp.normalized(v)


class CoreTests(unittest.TestCase):
    def setUp(self):
        for table in (storage.members_table, storage.member_tokens_table, storage.app_state_table,
                      storage.rate_limits_table, storage.conversations_table):
            table.truncate()
        voice._sessions.clear(); voice._observed.clear(); voice._requests.clear()
        fp._observations.clear(); fp._enrollments.clear(); fp._last.clear()
        fp._save([])
        patch.object(storage, 'get_settings', return_value={'service_token': 'service'}).start()
        self.addCleanup(patch.stopall)
        storage.add_member({'id': 'jeff', 'name': 'Jeff', 'role': 'parent'})
        storage.add_member({'id': 'lily', 'name': 'Lily', 'role': 'child'})
        storage.add_member({'id': 'sam', 'name': 'Sam', 'role': 'adult'})
        self.satellite = {'ha_instance_id': 'ha', 'satellite_id': 'assist_satellite.kitchen',
                          'device_id': 'device', 'enabled': True}
        voice.configure(True, [self.satellite])
        patch.object(fp, 'model_ready', return_value=True).start()

    def ctx(self):
        return voice.context({'ha_instance_id': 'ha', 'satellite_id': 'assist_satellite.kitchen',
                              'device_id': 'device', 'request_id': uuid.uuid4().hex,
                              'observed_at': time.time()}, True)

    def evidence(self, v, seconds=8, key=KEY):
        pending = fp._enrollments.get(key) or {}
        return {'vector': v, 'seconds': seconds, 'enrollment_id': pending.get('id')}

    def run_five(self, voices, token_for_step=None, key=KEY):
        """Ask and answer up to five steps; stops when the enrollment ends."""
        out = None
        for step in range(5):
            asked = fp.ask(key)
            token = token_for_step(step, asked['token']) if token_for_step else asked['token']
            out = fp.answer(key, self.evidence(voices[step], key=key), token=token)
            if out['status'] in ('ended', 'done', 'confirm'):
                break
        return out

    # --- questions and admission ------------------------------------------

    def test_five_questions_and_a_check_question_exist(self):
        self.assertEqual(len(fp.QUESTIONS), 5)
        self.assertTrue(all(q.endswith(('.', '?')) for q in fp.QUESTIONS))
        self.assertTrue(fp.CHECK_QUESTION)

    def test_ask_issues_a_one_use_token_and_answer_consumes_it(self):
        fp.begin(self.ctx(), 'jeff', 'jeff', anchor=vector(0))
        asked = fp.ask(KEY)
        self.assertEqual(asked['step'], 1)
        self.assertEqual(asked['question'], fp.QUESTIONS[0])
        first = fp.answer(KEY, self.evidence(vector(0)), token=asked['token'])
        self.assertEqual(first['status'], 'accepted', first)
        again = fp.answer(KEY, self.evidence(vector(0)), token=asked['token'])
        self.assertEqual(again['status'], 'retry')
        self.assertIn('answer the question', again['message'].lower())
        self.assertEqual(fp._enrollments[KEY]['step'], 1, 'a reused token counted as a sample')

    def test_an_answer_without_the_current_token_is_guidance_not_a_sample(self):
        fp.begin(self.ctx(), 'jeff', 'jeff', anchor=vector(0))
        fp.ask(KEY)
        out = fp.answer(KEY, self.evidence(vector(0)), token='stale')
        self.assertEqual(out['status'], 'retry')
        self.assertEqual(fp._enrollments[KEY]['samples'], [])

    def test_a_short_answer_asks_the_same_step_again_and_three_end_it(self):
        fp.begin(self.ctx(), 'jeff', 'jeff', anchor=vector(0))
        for n in range(3):
            asked = fp.ask(KEY)
            out = fp.answer(KEY, self.evidence(vector(0), seconds=2), token=asked['token'])
            self.assertEqual(asked['step'], 1)
            if n < 2:
                self.assertEqual(out['status'], 'retry'); self.assertIn('longer', out['message'].lower())
        self.assertEqual(out['status'], 'ended')
        self.assertNotIn(KEY, fp._enrollments)

    # --- speaker binding ---------------------------------------------------

    def test_self_enrollment_binds_every_sample_to_the_pin_utterance(self):
        fp.begin(self.ctx(), 'jeff', 'jeff', anchor=vector(0))
        asked = fp.ask(KEY)
        fp.answer(KEY, self.evidence(vector(0)), token=asked['token'])
        asked = fp.ask(KEY)
        out = fp.answer(KEY, self.evidence(vector(7)), token=asked['token'])  # a different voice
        self.assertEqual(out['status'], 'ended')
        self.assertIn('did not sound like', out['message'].lower())
        self.assertNotIn(KEY, fp._enrollments)

    def test_child_enrollment_rejects_the_consenting_parents_voice(self):
        fp.begin(self.ctx(), 'lily', 'jeff', exclude=vector(0))
        asked = fp.ask(KEY)
        out = fp.answer(KEY, self.evidence(vector(0)), token=asked['token'])  # the parent answered
        self.assertEqual(out['status'], 'ended')
        self.assertIn('parent', out['message'].lower())

    def test_child_enrollment_needs_the_parents_yes_before_saving(self):
        fp.begin(self.ctx(), 'lily', 'jeff', exclude=vector(0))
        out = self.run_five([vector(3)] * 5)
        self.assertEqual(out['status'], 'confirm')
        self.assertIn('Lily', out['message'])
        self.assertEqual(fp.profiles(), [])
        done = fp.confirm(KEY, True)
        self.assertEqual(done['status'], 'done')
        rows = fp.profiles()
        self.assertEqual([r['member_id'] for r in rows], ['lily'])
        self.assertEqual(rows[0]['consent_actor'], 'jeff')

    def test_a_no_at_confirmation_saves_nothing(self):
        fp.begin(self.ctx(), 'lily', 'jeff', exclude=vector(0))
        self.run_five([vector(3)] * 5)
        self.assertEqual(fp.confirm(KEY, False)['status'], 'ended')
        self.assertEqual(fp.profiles(), [])

    def test_no_credential_fingerprint_falls_back_to_consistency(self):
        fp.begin(self.ctx(), 'jeff', 'jeff', anchor=None)
        out = self.run_five([vector(0)] * 5)
        self.assertEqual(out['status'], 'done')
        self.assertIn('matching was unavailable', out['message'].lower())
        fp.begin(self.ctx(), 'sam', 'sam', anchor=None)
        out = self.run_five([vector(1), vector(1), vector(9), vector(1), vector(1)])
        self.assertEqual(out['status'], 'ended')

    # --- finishing, provenance, checks -------------------------------------

    def test_a_satellite_enrollment_is_checked_on_its_own_key(self):
        fp.begin(self.ctx(), 'jeff', 'jeff', anchor=vector(0))
        out = self.run_five([vector(0)] * 5)
        self.assertEqual(out['status'], 'done')
        self.assertIn('saved here', out['message'].lower())
        row = fp.profiles()[0]
        self.assertEqual(row['provenance'], 'satellite')
        self.assertEqual(row['device_id'], 'device')
        self.assertTrue(fp.checked_on(row, KEY))
        self.assertFalse(fp.checked_on(row, ('ha', 'assist_satellite.den')))

    def test_finishing_does_not_turn_recognition_on(self):
        fp.begin(self.ctx(), 'jeff', 'jeff', anchor=vector(0))
        self.run_five([vector(0)] * 5)
        row = next(r for r in voice.configuration()['satellites'] if r['satellite_id'] == KEY[1])
        self.assertFalse(row.get('recognition_enabled'))

    def test_a_legacy_row_reads_as_satellite_made_and_checked(self):
        fp._save([{'member_id': 'jeff', 'key': list(KEY), 'vector': vector(0), 'revision': fp.REVISION,
                   'consent_actor': 'jeff', 'created_at': time.time(), 'checks': 2, 'calibrated': True}])
        row = fp.profiles()[0]
        self.assertEqual(row.get('provenance', 'satellite'), 'satellite')
        self.assertTrue(fp.checked_on(row, KEY))

    def test_a_phone_template_is_unchecked_until_checked(self):
        fp.begin(self.ctx(), 'jeff', 'jeff', door='phone', anchor=None)
        self.run_five([vector(0)] * 5, key=PHONE)
        row = fp.profiles()[0]
        self.assertEqual(row['provenance'], 'phone')
        self.assertFalse(fp.checked_on(row, KEY))
        out = fp.check(KEY, 'jeff', {'vector': vector(0, lean=1, weight=0.95), 'seconds': 8}, anchor=vector(0, lean=1, weight=0.95))
        self.assertEqual(out['status'], 'checked', out)
        self.assertTrue(fp.checked_on(fp.profiles()[0], KEY))

    def test_a_check_that_misses_marks_does_not_transfer(self):
        fp.begin(self.ctx(), 'jeff', 'jeff', door='phone', anchor=None)
        self.run_five([vector(0)] * 5, key=PHONE)
        out = fp.check(KEY, 'jeff', {'vector': vector(5), 'seconds': 8}, anchor=vector(5))
        self.assertEqual(out['status'], 'does_not_transfer')
        self.assertEqual(fp.profiles()[0]['checks'][f'{KEY[0]}:{KEY[1]}'], 'does_not_transfer')
        self.assertFalse(fp.checked_on(fp.profiles()[0], KEY))

    def test_a_check_answer_must_match_its_own_credential(self):
        fp.begin(self.ctx(), 'jeff', 'jeff', door='phone', anchor=None)
        self.run_five([vector(0)] * 5, key=PHONE)
        out = fp.check(KEY, 'jeff', {'vector': vector(0), 'seconds': 8}, anchor=vector(6))
        self.assertEqual(out['status'], 'retry')
        self.assertFalse(fp.checked_on(fp.profiles()[0], KEY))

    # --- busy, cancel, archival --------------------------------------------

    def test_second_enrollment_on_a_busy_satellite_is_refused(self):
        fp.begin(self.ctx(), 'jeff', 'jeff', anchor=vector(0))
        with self.assertRaises(ValueError) as caught:
            fp.begin(self.ctx(), 'sam', 'sam', anchor=vector(1))
        self.assertIn('already in progress', str(caught.exception))
        self.assertEqual(fp._enrollments[KEY]['member_id'], 'jeff')

    def test_the_same_member_cannot_enroll_on_two_doors_at_once(self):
        fp.begin(self.ctx(), 'jeff', 'jeff', anchor=vector(0))
        with self.assertRaises(ValueError):
            fp.begin(self.ctx(), 'jeff', 'jeff', door='phone')

    def test_cancel_discards_samples_and_anchors(self):
        fp.begin(self.ctx(), 'jeff', 'jeff', anchor=vector(0))
        asked = fp.ask(KEY)
        fp.answer(KEY, self.evidence(vector(0)), token=asked['token'])
        self.assertEqual(fp.cancel(KEY)['status'], 'ended')
        self.assertNotIn(KEY, fp._enrollments)
        self.assertEqual(fp.profiles(), [])

    def test_enrollment_turn_gives_guidance_and_never_a_sample_for_unrelated_speech(self):
        """While a question is open, any speech IS the answer (the admission
        rule binds by run and token, not by words). When nothing is open,
        speech gets guidance and never a sample; a missing fingerprint on an
        open question is a retry, so a dead bridge ends the setup honestly."""
        fp.begin(self.ctx(), 'jeff', 'jeff', anchor=vector(0))
        out = fp.enrollment_turn("what's on the calendar", self.ctx(), self.evidence(vector(0)))
        self.assertIn('Voice setup is in progress', out['message'])
        self.assertEqual(fp._enrollments[KEY]['samples'], [])
        fp.ask(KEY)
        out = fp.enrollment_turn('um', self.ctx(), None)
        self.assertIn('longer', out['message'].lower())
        self.assertEqual(fp._enrollments[KEY]['retries'], 1)
        out = fp.enrollment_turn('cancel voice setup', self.ctx(), None)
        self.assertEqual(out['message'], 'Voice setup cancelled.')

    def test_archiving_keeps_the_template_and_cancels_pending(self):
        fp.begin(self.ctx(), 'jeff', 'jeff', anchor=vector(0))
        self.run_five([vector(0)] * 5)
        fp.begin(self.ctx(), 'sam', 'sam', anchor=vector(1))
        storage.update_member('sam', {'status': 'archived'})
        fp.on_member_status('sam')
        self.assertNotIn(KEY, fp._enrollments)
        storage.update_member('jeff', {'status': 'archived'})
        fp.on_member_status('jeff')
        self.assertEqual(fp.profiles(), [], 'an archived member still matches')
        self.assertEqual([r['member_id'] for r in fp._load()], ['jeff'], 'archival deleted the template')
        storage.update_member('jeff', {'status': 'active'})
        self.assertEqual([r['member_id'] for r in fp.profiles()], ['jeff'])


class ConsentAndSwitchTests(CoreTests):
    def setUp(self):
        super().setUp()
        storage.set_member_pin('jeff', '1234')
        storage.add_member({'id': 'pat', 'name': 'Pat', 'role': 'parent'})
        storage.set_member_pin('pat', '9876')

    def test_the_parents_pin_verifies_the_parent_without_a_session(self):
        ctx = self.ctx()
        out = voice.verify_parent_consent(ctx, 'jeff', 'my pin is one two three four')
        self.assertTrue(out['ok'], out)
        row = voice._sessions.get(KEY) or {}
        self.assertEqual((row.get('level', 'unknown'), row.get('member_id')), ('unknown', None), 'consent changed the room session')
        self.assertIsNone(voice.context({'ha_instance_id': 'ha', 'satellite_id': KEY[1], 'device_id': 'device',
                                         'request_id': 'r', 'observed_at': time.time()}, True).member_id)

    def test_wrong_parent_pin_locks_the_parent_not_the_child(self):
        ctx = self.ctx()
        for _ in range(3):
            out = voice.verify_parent_consent(ctx, 'jeff', 'my pin is 0000')
            self.assertFalse(out['ok'])
        self.assertTrue(voice._locked(ctx, 'jeff'))
        self.assertFalse((storage.get_app_state('voice:member:lily') or {}).get('locked'))
        self.assertIn('locked', voice.verify_parent_consent(ctx, 'jeff', 'my pin is 1234')['message'].lower())

    def test_a_child_or_adult_cannot_be_the_consenting_parent(self):
        self.assertFalse(voice.verify_parent_consent(self.ctx(), 'lily', 'my pin is 1234')['ok'])
        self.assertFalse(voice.verify_parent_consent(self.ctx(), 'sam', 'my pin is 1234')['ok'])

    def test_parents_named_resolves_by_name_or_lists_all(self):
        self.assertEqual([p['id'] for p in voice.parents_named('pat')], ['pat'])
        self.assertEqual(sorted(p['id'] for p in voice.parents_named('')), ['jeff', 'pat'])
        self.assertEqual(voice.parents_named('lily'), [])

    def test_recognition_switch_requires_a_checked_template(self):
        with self.assertRaises(ValueError):
            voice.set_recognition('ha', KEY[1], True)
        fp.begin(self.ctx(), 'jeff', 'jeff', anchor=vector(0))
        self.run_five([vector(0)] * 5)
        row = voice.set_recognition('ha', KEY[1], True)
        self.assertTrue(row['recognition_enabled'])
        self.assertTrue(next(r for r in voice.configuration()['satellites'] if r['satellite_id'] == KEY[1])['recognition_enabled'])
        self.assertFalse(voice.set_recognition('ha', KEY[1], False)['recognition_enabled'])


class ConfigWordsTests(unittest.TestCase):
    def test_config_reads_questions_and_check_states(self):
        src = open(Path(__file__).resolve().parents[1] / 'templates' / 'config.html', encoding='utf-8').read()
        self.assertNotIn('pending.prompt', src)
        self.assertIn('pending.question', src)
        self.assertIn('profile.checks', src)
        self.assertIn('does not match', src.lower())


if __name__ == '__main__':
    unittest.main()
