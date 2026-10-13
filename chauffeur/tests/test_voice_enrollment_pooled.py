"""Pooled enrollment: many short answers become one sample per step, pool 1 is
hard and the parent names it, later mismatches are dropped, held-out checks
score each short answer alone, forty turns is the ceiling.
Spec: docs/superpowers/specs/2026-10-13-kid-voice-enrollment-design.md."""
import os, sys, tempfile, time, unittest, uuid
from pathlib import Path
from unittest.mock import patch

os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_pooled_')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import storage, voice_identity as voice, voice_fingerprint as fp

KEY = ('ha', 'assist_satellite.kitchen')


def vector(index=0, lean=None, weight=0.9):
    """A unit vector on axis `index`, optionally leaning toward another axis."""
    v = [float(i == index) for i in range(256)]
    if lean is not None:
        v = [weight * a + (1 - weight) * float(i == lean) for i, a in enumerate(v)]
    return fp.normalized(v)


PARENT, LILY, SIBLING = vector(0), vector(3), vector(5)


class PooledCoreTests(unittest.TestCase):
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
        voice.configure(True, [{'ha_instance_id': 'ha', 'satellite_id': KEY[1], 'device_id': 'device', 'enabled': True}])
        patch.object(fp, 'model_ready', return_value=True).start()

    def ctx(self):
        return voice.context({'ha_instance_id': 'ha', 'satellite_id': KEY[1], 'device_id': 'device',
                              'request_id': uuid.uuid4().hex, 'observed_at': time.time()}, True)

    def begin_child(self):
        fp.begin(self.ctx(), 'lily', 'jeff', exclude=PARENT, pooled=True)

    def say(self, v, seconds=1.5):
        """Ask the current question and answer it with one short sample."""
        asked = fp.ask(KEY)
        pending = fp._enrollments.get(KEY) or {}
        return fp.answer(KEY, {'vector': v, 'seconds': seconds, 'enrollment_id': pending.get('id')}, token=asked['token'])

    def fill_pool(self, v=LILY, seconds=1.5, count=3):
        out = None
        for _ in range(count):
            out = self.say(v, seconds)
        return out

    # --- questions ---------------------------------------------------------

    def test_fifteen_kid_questions_then_follow_ups_that_cycle_the_topics(self):
        self.assertEqual(len(fp.KID_QUESTIONS), 15)
        self.assertEqual(fp.kid_question(0), "What's your favorite color, and why?")
        self.assertEqual(fp.kid_question(14), 'What do you like to eat for dinner?')
        self.assertEqual(fp.kid_question(15), 'Tell me more about your favorite color.')
        self.assertEqual(fp.kid_question(16), 'Tell me more about your favorite food.')
        self.assertEqual(fp.kid_question(30), 'What else about your favorite color?')
        self.assertTrue(all(q.endswith('?') for q, _ in fp.KID_QUESTIONS))

    def test_a_pooled_enrollment_asks_the_kid_questions_in_order(self):
        self.begin_child()
        self.assertEqual(fp.ask(KEY)['question'], fp.kid_question(0))
        self.assertEqual(fp.current_question(fp._enrollments[KEY]), fp.kid_question(0))
        self.assertEqual(fp.status()['enrollments'][0]['question'], fp.kid_question(0))
        fp._enrollments[KEY]['awaiting'] = None
        self.say(LILY)
        self.assertEqual(fp.ask(KEY)['question'], fp.kid_question(1))

    def test_an_unpooled_enrollment_still_asks_the_five_adult_questions(self):
        fp.begin(self.ctx(), 'jeff', 'jeff', anchor=PARENT)
        self.assertEqual(fp.ask(KEY)['question'], fp.QUESTIONS[0])
        self.assertFalse(fp._enrollments[KEY]['pooled'])

    # --- pooling -----------------------------------------------------------

    def test_a_pool_fills_at_four_voiced_seconds_and_is_the_normalized_mean(self):
        self.begin_child()
        a, b, c = vector(3, lean=4, weight=.95), vector(3, lean=6, weight=.95), vector(3)
        self.assertEqual(self.say(a)['status'], 'accepted')
        self.assertEqual(self.say(b)['status'], 'accepted')
        self.assertEqual(fp._enrollments[KEY]['pool_seconds'], 3.0)
        out = self.say(c)
        self.assertEqual(out['status'], 'name_voice', out)
        self.assertIn('Is that Lily talking', out['message'])
        pending = fp._enrollments[KEY]
        self.assertEqual(pending['step'], 1)
        self.assertEqual(pending['pool'], [])
        expected = fp.normalized([a[i] + b[i] + c[i] for i in range(256)])
        self.assertAlmostEqual(fp.score(pending['samples'][0], expected), 1.0, places=6)

    def test_the_interjections_rotate_and_nothing_is_announced_when_a_pool_fills(self):
        self.begin_child()
        self.assertEqual(self.say(LILY)['message'], 'Nice.')      # turn 1
        self.assertEqual(self.say(LILY)['message'], 'Cool.')      # turn 2
        self.assertEqual(self.say(LILY)['status'], 'name_voice')  # turn 3 fills pool 1
        fp.name_voice(KEY, True)
        self.assertEqual(self.say(LILY)['message'], 'Nice.')      # turn 4
        self.assertEqual(self.say(LILY)['message'], 'Cool.')      # turn 5
        out = self.say(LILY)                                       # turn 6 fills pool 2: just the next interjection
        self.assertEqual(out['status'], 'accepted'); self.assertEqual(out['message'], 'Good one.')

    def test_a_short_answer_asks_a_follow_up_and_three_in_a_row_end_it(self):
        self.begin_child()
        out = self.say(LILY, seconds=.8)
        self.assertEqual(out['status'], 'retry'); self.assertEqual(out['message'], '')
        self.assertEqual(fp.ask(KEY)['question'], 'Tell me more about that.')
        fp._enrollments[KEY]['awaiting'] = None
        self.assertEqual(self.say(LILY, seconds=.5)['status'], 'retry')
        self.assertEqual(fp.ask(KEY)['question'], 'Why is that?')
        fp._enrollments[KEY]['awaiting'] = None
        out = self.say(LILY, seconds=.9)
        self.assertEqual(out['status'], 'ended')
        self.assertIn("enough of Lily's voice", out['message'])
        self.assertNotIn(KEY, fp._enrollments)

    def test_a_short_answer_never_enters_the_pool(self):
        self.begin_child()
        self.say(LILY, seconds=.8)
        self.assertEqual(fp._enrollments[KEY]['pool'], [])
        self.assertEqual(fp._enrollments[KEY]['pool_seconds'], 0)
        self.say(LILY, seconds=1.0)   # exactly the floor is admitted
        self.assertEqual(len(fp._enrollments[KEY]['pool']), 1)
        self.assertEqual(fp._enrollments[KEY]['short'], 0)
        self.assertEqual(fp.ask(KEY)['question'], fp.kid_question(1), 'an admitted answer moves on from the follow-up')

    # --- pool 1 is hard, then the parent names it ----------------------------

    def test_an_inconsistent_answer_in_pool_one_restarts_it_and_a_second_restart_ends_it(self):
        self.begin_child()
        self.say(SIBLING); self.say(SIBLING)
        out = self.say(LILY)
        self.assertEqual(out['status'], 'restart'); self.assertIn('start over', out['message'].lower())
        pending = fp._enrollments[KEY]
        self.assertEqual((pending['pool'], pending['pool_seconds'], pending['question_index']), ([], 0, 0))
        self.assertEqual(pending['turns'], 3, 'a restart must keep counting turns')
        self.assertEqual(fp.ask(KEY)['question'], fp.kid_question(0))
        fp._enrollments[KEY]['awaiting'] = None
        self.say(LILY)
        out = self.say(SIBLING)
        self.assertEqual(out['status'], 'ended'); self.assertIn('voices kept changing', out['message'].lower())
        self.assertNotIn(KEY, fp._enrollments)

    def test_the_parents_yes_after_pool_one_makes_it_the_anchor(self):
        self.begin_child()
        self.fill_pool()
        pending = fp._enrollments[KEY]
        self.assertEqual(pending['phase'], 'name_voice'); self.assertIsNone(pending['anchor'])
        with self.assertRaises(ValueError):
            fp.ask(KEY)   # nothing is asked while the parent is being asked
        out = fp.name_voice(KEY, True)
        self.assertEqual(out['status'], 'accepted'); self.assertEqual(out['message'], 'Great.')
        self.assertEqual(pending['phase'], 'questions')
        self.assertAlmostEqual(fp.score(pending['anchor'], pending['samples'][0]), 1.0, places=6)

    def test_the_parents_no_after_pool_one_saves_nothing(self):
        self.begin_child()
        self.fill_pool(SIBLING)   # a sibling answered first, consistently
        out = fp.name_voice(KEY, False)
        self.assertEqual(out['status'], 'ended'); self.assertIn("just Lily", out['message'])
        self.assertNotIn(KEY, fp._enrollments); self.assertEqual(fp.profiles(), [])

    def test_name_voice_outside_its_phase_is_a_retry(self):
        self.begin_child()
        self.assertEqual(fp.name_voice(KEY, True)['status'], 'retry')

    def test_after_the_anchor_a_mismatch_is_dropped_and_three_in_a_row_end_it(self):
        self.begin_child(); self.fill_pool(); fp.name_voice(KEY, True)
        out = self.say(SIBLING)
        self.assertEqual(out['status'], 'dropped'); self.assertEqual(out['message'], "Let's try another one.")
        self.assertEqual(fp._enrollments[KEY]['question_index'], 4, 'a drop moves to the next question')
        self.assertEqual(self.say(SIBLING)['status'], 'dropped')
        out = self.say(SIBLING)
        self.assertEqual(out['status'], 'ended'); self.assertNotIn(KEY, fp._enrollments)

    def test_a_drop_does_not_advance_the_pool_and_an_admitted_answer_resets_the_counters(self):
        self.begin_child(); self.fill_pool(); fp.name_voice(KEY, True)
        self.say(LILY)
        self.say(SIBLING); self.say(SIBLING)
        pending = fp._enrollments[KEY]
        self.assertEqual((len(pending['pool']), pending['pool_seconds'], pending['drops']), (1, 1.5, 2))
        self.say(LILY, seconds=.5)   # short: not a drop, not pooled
        self.assertEqual((len(pending['pool']), pending['drops'], pending['short']), (1, 2, 1))
        self.say(LILY)
        self.assertEqual((len(pending['pool']), pending['drops'], pending['short']), (2, 0, 0))

    def test_an_alternating_speaker_run_never_fills_a_pool_with_two_voices(self):
        self.begin_child()
        self.say(LILY); self.assertEqual(self.say(SIBLING)['status'], 'restart')
        self.say(LILY); self.assertEqual(self.say(SIBLING)['status'], 'ended')
        self.assertEqual(fp.profiles(), [])

    def test_the_parent_answering_ends_it_in_any_pool(self):
        self.begin_child()
        out = self.say(PARENT)
        self.assertEqual(out['status'], 'ended'); self.assertIn('parent', out['message'].lower())
        self.begin_child(); self.fill_pool(); fp.name_voice(KEY, True); self.say(LILY)
        out = self.say(vector(0, lean=3, weight=.8))   # mostly the parent
        self.assertEqual(out['status'], 'ended'); self.assertIn('parent', out['message'].lower())

    def test_an_adult_with_a_pin_anchor_skips_the_naming_and_drops_from_the_start(self):
        fp.begin(self.ctx(), 'jeff', 'jeff', anchor=PARENT, pooled=True)
        out = self.fill_pool(PARENT)
        self.assertEqual(out['status'], 'accepted', 'the PIN voice is the anchor; nobody has to name it')
        self.assertEqual(self.say(SIBLING)['status'], 'dropped')

    # --- held-out checks score each answer alone -------------------------------

    def complete_training(self):
        self.begin_child(); self.fill_pool(); fp.name_voice(KEY, True); self.fill_pool(); self.fill_pool()
        self.assertEqual(fp._enrollments[KEY]['step'], 3)

    def test_a_check_step_scores_each_short_answer_alone(self):
        self.complete_training()
        # Each answer alone scores ~.68 against the centroid (axis 3): above CONTINUITY, below THRESHOLD.
        # Their normalized mean scores ~.85, which would pass. The step must still fail.
        weak = [vector(3, lean=k, weight=.48) for k in (10, 11, 12)]
        reference = fp._enrollments[KEY]['reference']
        for v in weak:
            self.assertTrue(fp.CONTINUITY <= fp.score(v, reference) < fp.THRESHOLD, fp.score(v, reference))
        mean = fp.normalized([sum(v[i] for v in weak) for i in range(256)])
        self.assertGreater(fp.score(mean, reference), fp.THRESHOLD)
        self.say(weak[0]); self.say(weak[1])
        out = self.say(weak[2])
        self.assertEqual(out['status'], 'ended'); self.assertIn('tell this voice apart', out['message'].lower())

    def test_a_check_step_passes_when_every_short_answer_passes(self):
        self.complete_training()
        good = [vector(3, lean=k, weight=.85) for k in (10, 11, 12)]
        self.say(good[0]); self.say(good[1])
        out = self.say(good[2])
        self.assertEqual(out['status'], 'accepted'); self.assertEqual(out['message'], 'Almost done!')
        self.assertEqual(fp._enrollments[KEY]['step'], 4)

    def test_a_rival_too_close_to_one_answer_fails_the_check(self):
        rows = [{'member_id': 'sam', 'key': list(KEY), 'vector': vector(3, lean=10, weight=.6), 'revision': fp.REVISION,
                 'consent_actor': 'sam', 'created_at': time.time(), 'checks': {}, 'calibrated': True,
                 'provenance': 'satellite', 'device_id': 'device'}]
        fp._save(rows)
        self.complete_training()
        self.say(LILY); self.say(LILY)
        out = self.say(vector(3, lean=10, weight=.6))   # one answer sits on the rival
        self.assertEqual(out['status'], 'ended')

    # --- finishing ---------------------------------------------------------

    def complete_checks(self):
        self.complete_training(); self.fill_pool(); return self.fill_pool()

    def test_the_fifth_pool_asks_for_the_parents_pin_and_the_row_is_pooled(self):
        out = self.complete_checks()
        self.assertEqual(out['status'], 'confirm')
        self.assertEqual(out['message'], 'All done! If that was Lily, say your PIN.')
        self.assertEqual(fp.profiles(), [])
        done = fp.confirm(KEY, True)
        self.assertEqual(done['status'], 'done')
        row = fp.profiles()[0]
        self.assertEqual((row['member_id'], row['consent_actor'], row['pooled'], row['provenance']), ('lily', 'jeff', True, 'satellite'))
        self.assertTrue(fp.status()['profiles'][0]['pooled'])

    def test_an_unpooled_row_reads_pooled_false(self):
        fp.begin(self.ctx(), 'jeff', 'jeff', anchor=PARENT)
        for _ in range(5):
            asked = fp.ask(KEY)
            fp.answer(KEY, {'vector': PARENT, 'seconds': 8, 'enrollment_id': fp._enrollments[KEY]['id']}, token=asked['token'])
        self.assertFalse(fp.profiles()[0]['pooled'])

    def test_someone_elses_enrollment_asks_for_the_pin_even_without_an_exclusion_fingerprint(self):
        fp.begin(self.ctx(), 'lily', 'jeff', exclude=None)   # the Config-started shape
        for _ in range(5):
            asked = fp.ask(KEY)
            out = fp.answer(KEY, {'vector': LILY, 'seconds': 8, 'enrollment_id': fp._enrollments[KEY]['id']}, token=asked['token'])
        self.assertEqual(out['status'], 'confirm', out)
        self.assertEqual(out['message'], 'If that was Lily, say your PIN.')
        self.assertEqual(fp.profiles(), [])

    def test_a_self_enrollment_still_finishes_without_a_confirmation(self):
        fp.begin(self.ctx(), 'jeff', 'jeff', anchor=None)
        for _ in range(5):
            asked = fp.ask(KEY)
            out = fp.answer(KEY, {'vector': PARENT, 'seconds': 8, 'enrollment_id': fp._enrollments[KEY]['id']}, token=asked['token'])
        self.assertEqual(out['status'], 'done')

    def test_enrollment_turn_never_accepts_a_yes_at_confirmation(self):
        self.complete_checks()
        out = fp.enrollment_turn('yes', self.ctx(), None)
        self.assertEqual(out['status'], 'retry'); self.assertIn('PIN', out['message'])
        self.assertEqual(fp.profiles(), [])
        self.assertEqual(fp._enrollments[KEY]['phase'], 'confirm')

    def test_forty_turns_end_the_setup_and_keep_an_existing_template(self):
        fp._save([{'member_id': 'lily', 'key': list(KEY), 'vector': LILY, 'revision': fp.REVISION, 'consent_actor': 'jeff',
                   'created_at': 1.0, 'checks': {}, 'calibrated': True, 'provenance': 'satellite', 'device_id': 'device', 'pooled': True}])
        self.begin_child()
        out = None
        for turn in range(40):
            out = self.say(LILY, seconds=.5 if turn % 3 else 1.0)   # two short, one admitted: a pool every twelve turns
            if out['status'] == 'name_voice':
                fp.name_voice(KEY, True)
            self.assertNotEqual(out['status'], 'ended', (turn, out))
        out = self.say(LILY, seconds=1.0)
        self.assertEqual(out['status'], 'ended'); self.assertIn("enough for today", out['message'])
        self.assertNotIn(KEY, fp._enrollments)
        rows = fp.profiles()
        self.assertEqual([(r['member_id'], r['created_at']) for r in rows], [('lily', 1.0)])

    def test_a_cancel_mid_pool_discards_everything(self):
        self.begin_child(); self.say(LILY)
        fp.cancel(KEY)
        self.assertNotIn(KEY, fp._enrollments); self.assertEqual(fp.profiles(), [])


if __name__ == '__main__':
    unittest.main()
