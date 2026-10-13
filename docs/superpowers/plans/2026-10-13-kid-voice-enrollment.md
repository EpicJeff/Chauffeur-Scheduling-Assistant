# Kid Voice Enrollment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A parent says "Hey Argyle, set up Lily's voice", gives their PIN, Lily answers quick questions until five pooled samples exist, the parent names the voice after the first pool and gives their PIN again at the end, and recognition names Lily afterwards.

**Architecture:** The enrollment core in `services/voice_fingerprint.py` gains a *pooled* mode on the same `_enrollments` state: several short answers are admitted one by one and averaged into one sample per step, pool 1 is hard and becomes the anchor once the parent names it, later answers are dropped when they do not match the anchor, and the two held-out check steps score each short answer alone. The spoken dialog in `services/voice_setup.py` chooses pooling for a child (or for "the short questions"), hands off to the child, asks the parent "Is that Lily talking?", falls back to a consent line when the PIN turn carried no fingerprint, and closes someone else's enrollment with the parent's PIN instead of a yes. Thresholds, admission tokens, provenance and activation are untouched.

**Tech Stack:** Python 3.11 FastAPI add-on, sherpa-onnx WeSpeaker embeddings (`voice_fingerprint.extract`), Home Assistant `continue_conversation`, Alpine on `config.html`. Tests are plain `unittest` scripts run from `chauffeur/` with `HA_BASE_URL` unset.

**Spec:** `docs/superpowers/specs/2026-10-13-kid-voice-enrollment-design.md` (revised after the Codex adversarial review; the final confirmation is the parent's PIN again, the user's decision on 2026-10-13).

## Global Constraints

- Thresholds stay `THRESHOLD, MARGIN, CONTINUITY = .70, .12, .65`; nothing in this plan lowers one to finish a setup.
- A pooled step holds **4 s** of voiced speech (`POOL_SECONDS = 4`); a pooled answer needs **1 s** (`POOLED_ANSWER_SECONDS = 1`); three consecutive sub-floor answers end the setup (`MAX_RETRIES = 3`, reused); three consecutive drops end it (`MAX_DROPS = 3`); a second pool-1 restart ends it (`MAX_POOL_RESTARTS = 2`); forty admitted turns end it (`MAX_POOLED_TURNS = 40`).
- The parent-exclusion rule is hard on every answer in every pool: an answer with `score ≥ CONTINUITY` against the consenting parent's fingerprint ends the setup.
- A held-out check step (steps 4 and 5) scores **each short answer alone** against the centroid and rivals; one failure ends the setup.
- A satellite enrollment of someone else (`consent_actor != member_id`) always ends with the consenting parent's PIN through `voice_identity.verify_parent_consent`, voice-matched to the exclusion fingerprint when one exists; a bare "yes" is answered with "Say your PIN."; a correct PIN from the wrong voice or a wrong PIN gets one more try; the verifier's lockout ends the setup. No parent session is created.
- A child enrollment never starts with `exclude=None` from the dialog: a PIN turn with no fingerprint asks for a consent line, three tries.
- The confirmation PIN and the activation yes are answered in the conversation that asked; a turn from another conversation re-asks (and re-binds to the new conversation).
- The phone door does not pool and has no closing confirmation (a present parent types the PIN on the child's screen at the start; unchanged).
- Enrollment expiry stays 600 s; one pending enrollment per satellite and per member.
- Speech during an enrollment never reaches the chat model.
- `templates.json` keeps its shape; rows gain only `pooled: true|false`.
- The question list and follow-ups live beside `QUESTIONS` in `voice_fingerprint.py` because `ask()` and `status()` read them (the spec's split put the list in `voice_setup.py`; the dialog still owns every spoken line that is not a question).
- Tests run from `chauffeur/` as `python tests/<file>.py` with `HA_BASE_URL` unset; never the full sweep. Gate for this arc: `test_voice_enrollment_pooled.py`, `test_voice_enrollment.py`, `test_voice_setup.py`, `test_voice_setup_kids.py`, `test_voice_enrollment_phone.py`, `test_voice_setup_component.py`.
- Nobody bumps `config.yaml` or commits except Claude Code at the end of each task (standing coordination rule). Task 1's implementation goes to Codex against the tests Claude writes; Tasks 2 and 3 are Claude's.

## Review Focus

1. **The child keeps talking when the parent is asked "Is that Lily talking?"**: the chatter must not be scored, pooled or counted as a turn; the question is re-asked, and only after two non-answers is it read as no. Test in Task 2 (`test_chatter_at_is_that_lily_is_re_asked_and_never_pooled`).
2. **Pool 1 restarts after a sibling answers**: the question index returns to the first question, the pool empties, the turn counter keeps counting (exhaustion stays bounded). Test in Task 1 (`test_an_inconsistent_answer_in_pool_one_restarts_it_and_a_second_restart_ends_it`).
3. **A dropped or short answer must not leak into the pool**: `pool_seconds` unchanged on a drop, `drops` and `short` reset on an admitted answer. Test in Task 1 (`test_a_drop_does_not_advance_the_pool_and_an_admitted_answer_resets_the_counters`).
4. **Re-enrolling a child who already has a template and running out of turns**: the old template must survive untouched. Test in Task 1 (`test_forty_turns_end_the_setup_and_keep_an_existing_template`).
5. **"stop" inside a sentence ("I like to stop at the park")** is an answer, not a cancel; only the bare word cancels. Test in Task 2 (`test_stop_inside_a_sentence_is_an_answer`).

---

### Task 1: The pooled enrollment core

**Files:**
- Modify: `chauffeur/services/voice_fingerprint.py` (constants after `CHECK_QUESTION` :38; `begin` :307-336; `ask` :339-349; `answer` :371-419; `confirm` :421-428; `_finish` :431-454; `enrollment_turn` :512-539; `status` :592-603)
- Create: `chauffeur/tests/test_voice_enrollment_pooled.py`

**Interfaces:**
- Consumes: existing `normalized`, `score`, `profiles`, `_load/_save`, `_end`, `_finish`, `storage.get_member`, `identity._active`.
- Produces (all in `voice_fingerprint`):
  - `KID_QUESTIONS: tuple[tuple[str, str], ...]` fifteen `(question, topic)` pairs; `FOLLOW_UPS`, `SHORT_FOLLOW_UPS`, `INTERJECTIONS`; `POOL_SECONDS = 4`, `POOLED_ANSWER_SECONDS = 1`, `MAX_POOLED_TURNS = 40`, `MAX_DROPS = 3`, `MAX_POOL_RESTARTS = 2`.
  - `kid_question(index: int) -> str` (the list, then follow-ups cycling the topics).
  - `current_question(pending: dict) -> str` (what `ask()` will ask next; the dialog and `status()` use it).
  - `begin(ctx, member_id, consent_actor, *, door='satellite', anchor=None, exclude=None, pooled=False)`; a pooled pending row carries `pooled, pool, pool_seconds, question_index, turns, short, drops, restarts`.
  - `answer(...)` returns, for a pooled enrollment, `status` in `'accepted'|'retry'|'restart'|'dropped'|'name_voice'|'confirm'|'done'|'ended'`; `retry` carries an empty message (the follow-up question comes from `ask()`).
  - `name_voice(key, yes: bool) -> dict` → `{'status': 'accepted', 'message': 'Great.'}` (anchor set to pool 1's mean) or `ended`.
  - `confirm(key, ok: bool)` unchanged in shape; now reached for every satellite enrollment where `consent_actor != member_id`, with the message `All done! If that was {name}, say your PIN.` (non-pooled: `If that was {name}, say your PIN.`).
  - `enrollment_turn` in the `confirm` phase returns guidance `Say the parent's PIN.` and never accepts a yes.
  - Saved rows and `status()['profiles']` carry `pooled: bool`; `status()['enrollments'][*]['question']` uses `current_question`.

- [ ] **Step 1: Write the failing tests**

Create `chauffeur/tests/test_voice_enrollment_pooled.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run from `chauffeur/` (PowerShell: `Remove-Item Env:HA_BASE_URL -ErrorAction SilentlyContinue; python tests/test_voice_enrollment_pooled.py`):

Expected: errors on `fp.KID_QUESTIONS`, `fp.kid_question`, `begin() got an unexpected keyword argument 'pooled'`, `fp.name_voice`.

- [ ] **Step 3: Hand the implementation to Codex**

Dispatch (Claude runs this; the test file is the contract):

```
/codex:rescue --background Make chauffeur/tests/test_voice_enrollment_pooled.py green without weakening it, keeping chauffeur/tests/test_voice_enrollment.py green too. Touch only chauffeur/services/voice_fingerprint.py. Read AGENTS.md, then docs/superpowers/specs/2026-10-13-kid-voice-enrollment-design.md (sections "The one mechanism change", "Establishing the child's voice", "The dialog, for a child" items 3-6) and Task 1 of docs/superpowers/plans/2026-10-13-kid-voice-enrollment.md, which carries a reference implementation. Run the tests from chauffeur/ with HA_BASE_URL unset: python tests/test_voice_enrollment_pooled.py; python tests/test_voice_enrollment.py. Do not bump config.yaml, do not commit. If a test is wrong, say so with the reason instead of changing it.
```

Reference implementation (what the tests encode). Constants after `CHECK_QUESTION`:

```python
# A child's enrollment pools many short answers into each sample (kid spec,
# 2026-10-13): the fixed list first, then follow-ups that cycle the topics so
# the questions never run out before the five pools fill.
KID_QUESTIONS = (
    ("What's your favorite color, and why?", 'your favorite color'),
    ("What's your favorite food?", 'your favorite food'),
    ('What do you like to do at the park?', 'the park'),
    ("What's your favorite animal?", 'your favorite animal'),
    ('What did you have for breakfast today?', 'breakfast'),
    ('Who is your best friend, and what do you play together?', 'your best friend'),
    ('What do you want to be when you grow up?', 'growing up'),
    ("What's the best part of school?", 'school'),
    ("What's a game you like to play?", 'that game'),
    ("Do you have a pet or a stuffed animal? What's its name?", 'your pet or stuffed animal'),
    ("What's your favorite thing to do on the weekend?", 'the weekend'),
    ('If you could go anywhere, where would you go?', 'where you would go'),
    ('What makes you laugh?', 'what makes you laugh'),
    ("What's your favorite song or show?", 'your favorite song or show'),
    ('What do you like to eat for dinner?', 'dinner'),
)
FOLLOW_UPS = ('Tell me more about {topic}.', 'What else about {topic}?')
SHORT_FOLLOW_UPS = ('Tell me more about that.', 'Why is that?')
INTERJECTIONS = ('Nice.', 'Cool.', 'Good one.')
POOL_SECONDS = 4             # voiced seconds per pooled sample
POOLED_ANSWER_SECONDS = 1    # a shorter answer is kept out of the pool, never refused
MAX_POOLED_TURNS = 40        # answers, follow-ups and drops together
MAX_DROPS = 3                # consecutive anchor mismatches after pool 1
MAX_POOL_RESTARTS = 2        # pool 1 discards


def kid_question(index):
    n = len(KID_QUESTIONS)
    if index < n:
        return KID_QUESTIONS[index][0]
    lap, topic = divmod(index - n, n)
    return FOLLOW_UPS[lap % len(FOLLOW_UPS)].format(topic=KID_QUESTIONS[topic][1])


def current_question(pending):
    """What ask() will ask next: the adult list by step, or for a pooled
    enrollment the kid list by question index, or a follow-up after a short answer."""
    if not pending.get('pooled'):
        return QUESTIONS[pending['step']] if pending['step'] < len(QUESTIONS) else ''
    if pending.get('short'):
        return SHORT_FOLLOW_UPS[(pending['short'] - 1) % len(SHORT_FOLLOW_UPS)]
    return kid_question(pending['question_index'])
```

`begin` gains `pooled=False` and the pending row gains:

```python
            'pooled': bool(pooled), 'pool': [], 'pool_seconds': 0.0, 'question_index': 0,
            'turns': 0, 'short': 0, 'drops': 0, 'restarts': 0,
```

`ask` returns `'question': current_question(pending)`. `status()` enrollments use `current_question(p)`; profiles add `'pooled': bool(r.get('pooled'))`. `_finish` writes `'pooled': bool(pending.get('pooled'))` on the row.

In `answer`, right after `pending['awaiting'] = None`:

```python
        if pending.get('pooled'):
            return _pooled_answer(key, pending, evidence, step)
```

and replace the tail of `answer` (from `if pending['exclude'] is not None:` to the end) with `return _closing(key, pending)`.

```python
def _closing(key, pending):
    """The fifth sample is in. Someone else's satellite enrollment is gated by
    the consenting parent's PIN (the dialog verifies it); a self-enrollment saves."""
    if pending['door'] == 'satellite' and pending['consent_actor'] != pending['member_id']:
        pending['phase'] = 'confirm'
        name = (storage.get_member(pending['member_id']) or {}).get('name', 'them')
        lead = 'All done! ' if pending.get('pooled') else ''
        return {'status': 'confirm', 'step': 5, 'message': f'{lead}If that was {name}, say your PIN.'}
    return _finish(key, pending)


def _pooled_answer(key, pending, evidence, step):
    """One short answer of a pooled enrollment (kid spec): admitted into the
    open pool, dropped, or a restart of pool 1; a full pool becomes the step's
    sample, and a check step scores every answer alone."""
    name = (storage.get_member(pending['member_id']) or {}).get('name', 'them')
    pending['turns'] += 1
    if pending['turns'] > MAX_POOLED_TURNS:
        return _end(key, f"That's enough for today. I couldn't get all of {name}'s voice; try again another time.")
    usable = bool(evidence) and evidence.get('enrollment_id') in (None, pending['id']) \
        and bool(evidence.get('vector')) and evidence.get('seconds', 0) >= POOLED_ANSWER_SECONDS
    if not usable:
        pending['short'] += 1
        if pending['short'] >= MAX_RETRIES:
            return _end(key, f"I couldn't get enough of {name}'s voice. Try again another time.")
        return {'status': 'retry', 'step': step + 1, 'message': ''}
    vector, seconds = evidence['vector'], float(evidence['seconds'])
    pending['short'] = 0
    if pending['exclude'] is not None and score(vector, pending['exclude']) >= CONTINUITY:
        return _end(key, 'That sounded like the parent who gave consent, not the person being set up. Voice setup stopped.')
    if pending['anchor'] is None:
        if any(score(vector, other) < CONTINUITY for other in pending['pool']):
            pending['restarts'] += 1
            if pending['restarts'] >= MAX_POOL_RESTARTS:
                return _end(key, 'The voices kept changing. Voice setup stopped.')
            pending['pool'], pending['pool_seconds'], pending['question_index'] = [], 0.0, 0
            return {'status': 'restart', 'step': step + 1, 'message': "Let's start over."}
    elif score(vector, pending['anchor']) < CONTINUITY:
        pending['drops'] += 1
        pending['question_index'] += 1
        if pending['drops'] >= MAX_DROPS:
            return _end(key, 'The voices kept changing. Voice setup stopped.')
        return {'status': 'dropped', 'step': step + 1, 'message': "Let's try another one."}
    pending['drops'] = 0
    pending['question_index'] += 1
    pending['pool'].append(vector)
    pending['pool_seconds'] += seconds
    interjection = INTERJECTIONS[(pending['turns'] - 1) % len(INTERJECTIONS)]
    if pending['pool_seconds'] < POOL_SECONDS:
        return {'status': 'accepted', 'step': step + 1, 'message': interjection}
    pool = pending['pool']
    mean = normalized([sum(v[i] for v in pool) for i in range(256)])
    if step < 3:
        pending['samples'].append(mean)
        pending['reference'] = normalized([sum(v[i] for v in pending['samples']) for i in range(256)])
    else:
        # Held-out checks score each short answer ALONE: the shape of a live
        # query. A pooled mean sits closer to the centroid than any one answer
        # (Codex review, finding 1) and would pass where recognition fails.
        rivals = [r for r in profiles() if r['member_id'] != pending['member_id']]
        for v in pool:
            competing = max((score(v, r['vector']) for r in rivals), default=-1)
            own = score(v, pending['reference'])
            if own < THRESHOLD or own - competing < MARGIN:
                return _end(key, 'I could not tell this voice apart reliably. Voice setup stopped; recognition stays off.')
    pending['pool'], pending['pool_seconds'] = [], 0.0
    pending['step'] += 1
    if pending['step'] == 1 and pending['anchor'] is None:
        pending['phase'] = 'name_voice'
        return {'status': 'name_voice', 'step': 2, 'message': f'Is that {name} talking? Say yes.'}
    if pending['step'] == 4:
        return {'status': 'accepted', 'step': 5, 'message': 'Almost done!'}
    if pending['step'] < 5:
        return {'status': 'accepted', 'step': pending['step'] + 1, 'message': interjection}
    return _closing(key, pending)


def name_voice(key, yes):
    """The parent's answer to "Is that Lily talking?" after pool 1: yes makes
    pool 1's mean the anchor every later answer must match; no saves nothing."""
    with _lock:
        pending = _enrollments.get(key)
        if not pending or pending['phase'] != 'name_voice':
            return {'status': 'retry', 'message': 'Nothing is waiting for a yes.', 'step': 0}
        if not yes:
            name = (storage.get_member(pending['member_id']) or {}).get('name', 'them')
            return _end(key, f"Not saved. Try again when it's just {name}.")
        pending['anchor'] = pending['samples'][0]
        pending['phase'] = 'questions'
        return {'status': 'accepted', 'step': 2, 'message': 'Great.'}
```

In `enrollment_turn`, replace the `confirm` branch body with:

```python
    if phase == 'confirm':
        return {'message': "Say the parent's PIN.", 'status': 'retry'}
```

Note for the implementer: `ask()` must still raise `No voice setup is waiting for an answer here.` while `phase == 'name_voice'` (it checks `phase != 'questions'`; keep that).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python tests/test_voice_enrollment_pooled.py; python tests/test_voice_enrollment.py; python tests/test_voice_enrollment_phone.py`
Expected: all OK. (`test_voice_enrollment.py::test_child_enrollment_needs_the_parents_yes_before_saving` still passes: it asserts `confirm` status and `Lily` in the message, and calls `fp.confirm(KEY, True)` directly.)

- [ ] **Step 5: Claude reviews Codex's diff, then commits**

`/codex:review` is not used here (Codex wrote it); Claude reads the diff against the reference implementation and the spec, then:

```bash
git add chauffeur/services/voice_fingerprint.py chauffeur/tests/test_voice_enrollment_pooled.py
git commit -m "feat(voice): pooled enrollment core - short answers pooled to four voiced seconds per sample, pool 1 hard then anchored by the parent's yes, drops after the anchor, held-out checks score each answer alone, forty-turn ceiling, the closing gate is the parent's PIN for every enrollment of someone else (vX.Y.Z)"
```

---

### Task 2: The child dialog on the satellite

**Files:**
- Modify: `chauffeur/services/voice_setup.py` (`START` :39; `_finish_or_activate` :70-79; `_begin` :82-89; `intercept` :178-330: start phrases, `who` phase, `consent_pin`, new `consent_voice`, `questions` statuses, new `name_voice`, `confirm` (PIN), `activate` binding)
- Modify: `chauffeur/main.py:4035` (Config-started enrollment passes `pooled=` for a child)
- Create: `chauffeur/tests/test_voice_setup_kids.py`
- Modify: `chauffeur/tests/test_voice_setup.py:71-87` (the child test becomes the pooled flow with the closing PIN)

**Interfaces:**
- Consumes: Task 1's `begin(..., pooled=)`, `current_question`, `name_voice`, `confirm`, statuses `restart|dropped|name_voice|confirm`, `fp.score`, `fp.CONTINUITY`; `identity.verify_parent_consent(ctx, parent_id, text)`.
- Produces: `voice_setup._start(low) -> tuple[str, bool] | None`; dialog phases `consent_voice`, `name_voice`; dialog keys `pooled`, `confirm_conversation`, `confirm_tries`, `activate_conversation`, `consent_tries`, `name_reasks`; `_finish_or_activate(key, d, lead, conversation_id=None)`.

- [ ] **Step 1: Write the failing dialog tests**

Create `chauffeur/tests/test_voice_setup_kids.py`:

```python
"""A child's voice set up by talking: the parent's PIN, quick questions pooled
into samples, "Is that Lily talking?", the parent's PIN again at the end.
Driven through the real converse endpoint with scripted fingerprints and
per-utterance voiced seconds. Spec: 2026-10-13-kid-voice-enrollment-design.md."""
import os, sys, tempfile, time, unittest, uuid
from pathlib import Path
from unittest.mock import patch

os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_kids_')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import storage, voice_identity as voice, voice_fingerprint as fp, voice_setup
from starlette.requests import Request
import main

KEY = ('ha', 'assist_satellite.kitchen')


def vector(index=0):
    return fp.normalized([float(i == index) for i in range(256)])


JEFF, LILY, SAM = vector(0), vector(3), vector(5)
PIN = 'my PIN is one two three four'


class KidDialogTests(unittest.TestCase):
    def setUp(self):
        for table in (storage.members_table, storage.member_tokens_table, storage.app_state_table,
                      storage.rate_limits_table, storage.conversations_table):
            table.truncate()
        voice._sessions.clear(); voice._observed.clear(); voice._requests.clear()
        fp._observations.clear(); fp._enrollments.clear(); fp._last.clear(); voice_setup._dialogs.clear()
        fp._save([])
        storage.get_settings = lambda: {'service_token': 'service', 'auth_enforce': False, 'calendar_ids': []}
        storage.add_member({'id': 'jeff', 'name': 'Jeff', 'role': 'parent'}); storage.set_member_pin('jeff', '1234')
        storage.add_member({'id': 'lily', 'name': 'Lily', 'role': 'child'})
        voice.configure(True, [{'ha_instance_id': 'ha', 'satellite_id': KEY[1], 'device_id': 'device', 'enabled': True}])
        patch.object(fp, 'model_ready', return_value=True).start()
        self.addCleanup(patch.stopall)
        self.evidence = []        # (vector or None, voiced seconds) for each next utterance
        self.conversation = 'conv-1'

        def consume(ctx, metadata, text=''):
            v, seconds = self.evidence.pop(0) if self.evidence else (None, 0)
            pending = fp._enrollments.get(KEY) or {}
            return None if v is None else {'vector': v, 'seconds': seconds, 'enrollment_id': pending.get('id')}
        patch.object(fp, 'consume', consume).start()

    def say(self, text, v=JEFF, seconds=3, conversation=None):
        self.evidence.append((v, seconds))
        req = main.ConverseRequest(text=text, language='en', conversation_id=conversation or self.conversation,
                                   voice={'ha_instance_id': 'ha', 'satellite_id': KEY[1], 'device_id': 'device',
                                          'request_id': uuid.uuid4().hex, 'observed_at': time.time()})
        request = Request({'type': 'http', 'method': 'POST', 'path': '/', 'query_string': b'',
                           'headers': [(b'x-service-token', b'service')]})
        out = main.converse_ha_assist(req, request)
        return out['response']['speech']['plain']['speech'], out['continue_conversation']

    def start_lily(self):
        speech, cont = self.say("set up Lily's voice")
        self.assertIn("parent's PIN", speech); self.assertTrue(cont)
        speech, cont = self.say(PIN, JEFF, 3)
        self.assertIn("Hi Lily. I'm going to ask you some questions. Just answer out loud.", speech)
        self.assertIn(fp.kid_question(0), speech); self.assertTrue(cont)
        return speech

    def pool(self, v=LILY, seconds=1.5, count=3):
        speech = cont = None
        for _ in range(count):
            speech, cont = self.say('blue because it is the sky', v, seconds)
        return speech, cont

    def test_a_child_is_set_up_with_quick_questions_and_the_parents_pin_twice(self):
        self.start_lily()
        speech, cont = self.say('blue because it is the sky', LILY, 1.5)
        self.assertTrue(speech.startswith('Nice. ')); self.assertIn(fp.kid_question(1), speech); self.assertTrue(cont)
        speech, cont = self.say('pizza', LILY, 1.5)
        self.assertIn(fp.kid_question(2), speech)
        speech, cont = self.say('the swings', LILY, 1.5)
        self.assertEqual(speech, 'Is that Lily talking? Say yes.'); self.assertTrue(cont)
        speech, cont = self.say('yes', JEFF, .5)
        self.assertTrue(speech.startswith('Great. ')); self.assertIn(fp.kid_question(3), speech); self.assertTrue(cont)
        for pool in range(3):                  # pools 2, 3, 4
            speech, cont = self.pool()
            self.assertTrue(cont)
        self.assertTrue(speech.startswith('Almost done! '), speech)
        speech, cont = self.pool()             # pool 5
        self.assertEqual(speech, 'All done! If that was Lily, say your PIN.'); self.assertTrue(cont)
        self.assertEqual(fp.profiles(), [])
        speech, cont = self.say('yes', JEFF, .5)
        self.assertEqual(speech, 'Say your PIN.'); self.assertTrue(cont)
        speech, cont = self.say(PIN, JEFF, 3)
        self.assertIn('saved', speech.lower()); self.assertIn('Turn on voice recognition for Lily', speech); self.assertTrue(cont)
        speech, cont = self.say('yes', JEFF, .5)
        self.assertEqual(speech, 'Voice recognition is on.'); self.assertFalse(cont)
        row = fp.profiles()[0]
        self.assertEqual((row['member_id'], row['consent_actor'], row['pooled']), ('lily', 'jeff', True))
        self.assertFalse(voice_setup._dialogs)
        session = voice._sessions.get(KEY, {})
        self.assertFalse(session.get('level') == 'verified' and session.get('member_id') == 'jeff', 'the closing PIN left a parent session')

    def test_follow_ups_are_asked_once_the_list_is_spent(self):
        self.start_lily()
        self.pool(seconds=1.0, count=4)
        self.say('yes', JEFF, .5)
        for _ in range(2):
            self.pool(seconds=1.0, count=4)
        speech, _ = self.pool(seconds=1.0, count=3)   # the 15th admitted answer
        self.assertIn(fp.kid_question(15), speech)
        self.assertIn('Tell me more about your favorite color.', speech)

    def test_the_closing_pin_must_be_the_consenting_parents_voice(self):
        self.start_lily(); self.pool(); self.say('yes', JEFF, .5)
        for _ in range(4):
            self.pool()
        speech, cont = self.say(PIN, LILY, 3)
        self.assertEqual(speech, 'That did not sound like the parent who gave consent. If that was Lily, say your PIN.'); self.assertTrue(cont)
        self.assertEqual(fp.profiles(), [])
        speech, cont = self.say(PIN, JEFF, 3)
        self.assertIn('saved', speech.lower())

    def test_a_wrong_closing_pin_gets_one_more_try_then_nothing_is_saved(self):
        self.start_lily(); self.pool(); self.say('yes', JEFF, .5)
        for _ in range(4):
            self.pool()
        speech, cont = self.say('my PIN is nine nine nine nine', JEFF, 3)
        self.assertIn('did not match', speech); self.assertIn('say your PIN', speech); self.assertTrue(cont)
        speech, cont = self.say('my PIN is nine nine nine nine', JEFF, 3)
        self.assertIn('Not saved', speech); self.assertFalse(cont)
        self.assertEqual(fp.profiles(), []); self.assertNotIn(KEY, fp._enrollments); self.assertFalse(voice_setup._dialogs)

    def test_the_closing_pin_and_the_activation_yes_answer_the_conversation_that_asked(self):
        self.start_lily(); self.pool(); self.say('yes', JEFF, .5)
        for _ in range(4):
            self.pool()
        speech, cont = self.say(PIN, JEFF, 3, conversation='another-room')
        self.assertEqual(speech, 'If that was Lily, say your PIN.'); self.assertTrue(cont)
        self.assertEqual(fp.profiles(), [])
        speech, cont = self.say(PIN, JEFF, 3, conversation='another-room')   # the re-ask bound it here
        self.assertIn('Turn on voice recognition for Lily', speech)
        speech, cont = self.say('yes', JEFF, .5, conversation='conv-1')
        self.assertIn('Turn on voice recognition for Lily', speech); self.assertTrue(cont)
        speech, cont = self.say('yes', JEFF, .5, conversation='conv-1')
        self.assertEqual(speech, 'Voice recognition is on.')

    def test_a_pin_turn_without_a_fingerprint_asks_for_a_consent_line_first(self):
        self.say("set up Lily's voice")
        speech, cont = self.say(PIN, None)
        self.assertEqual(speech, "I need to hear your voice first. Say: I'm giving consent for Lily to set up a voice."); self.assertTrue(cont)
        self.assertNotIn(KEY, fp._enrollments, 'the enrollment started with no exclusion fingerprint')
        speech, cont = self.say("I'm giving consent for Lily to set up a voice", JEFF, 3)
        self.assertIn('Hi Lily', speech)
        self.assertEqual(fp.score(fp._enrollments[KEY]['exclude'], JEFF), 1.0)

    def test_three_consent_lines_without_a_fingerprint_end_it(self):
        self.say("set up Lily's voice"); self.say(PIN, None)
        self.say('consent', None); self.say('consent', None)
        speech, cont = self.say('consent', None)
        self.assertIn("couldn't hear you well enough", speech); self.assertFalse(cont)
        self.assertFalse(voice_setup._dialogs); self.assertNotIn(KEY, fp._enrollments)

    def test_a_sibling_answering_first_is_caught_by_the_parents_no(self):
        self.start_lily()
        speech, _ = self.pool(SAM)
        self.assertEqual(speech, 'Is that Lily talking? Say yes.')
        speech, cont = self.say('no', JEFF, .5)
        self.assertEqual(speech, "Not saved. Try again when it's just Lily."); self.assertFalse(cont)
        self.assertEqual(fp.profiles(), []); self.assertFalse(voice_setup._dialogs)

    def test_a_sibling_chiming_in_after_the_anchor_is_dropped(self):
        self.start_lily(); self.pool(); self.say('yes', JEFF, .5)
        speech, cont = self.say('I want to answer too', SAM, 1.5)
        self.assertTrue(speech.startswith("Let's try another one. ")); self.assertIn(fp.kid_question(4), speech); self.assertTrue(cont)

    def test_chatter_at_is_that_lily_is_re_asked_and_never_pooled(self):
        self.start_lily(); self.pool()
        speech, cont = self.say('and I like purple too', LILY, 1.5)
        self.assertEqual(speech, 'Is that Lily talking? Yes or no?'); self.assertTrue(cont)
        pending = fp._enrollments[KEY]
        self.assertEqual((pending['pool'], pending['turns'], pending['step']), ([], 3, 1))
        speech, cont = self.say('and green', LILY, 1.5)
        self.assertEqual(speech, 'Is that Lily talking? Yes or no?')
        speech, cont = self.say('and yellow', LILY, 1.5)
        self.assertIn('Not saved', speech); self.assertFalse(cont)

    def test_stop_inside_a_sentence_is_an_answer(self):
        self.start_lily()
        speech, cont = self.say('I like to stop at the park', LILY, 1.5)
        self.assertIn(fp.kid_question(1), speech); self.assertTrue(cont)
        speech, cont = self.say("we're done", JEFF, .5)
        self.assertEqual(speech, 'Voice setup cancelled.'); self.assertFalse(cont)
        self.assertNotIn(KEY, fp._enrollments)

    def test_an_adult_can_ask_for_the_short_questions(self):
        speech, cont = self.say('set up my voice with the short questions')
        self.assertIn('Who is this for', speech)
        self.say("it's Jeff")
        speech, cont = self.say(PIN, JEFF, 3)
        self.assertEqual(speech, f'Thanks. {fp.kid_question(0)}'); self.assertTrue(cont)
        speech, cont = self.pool(JEFF)
        self.assertTrue(speech.startswith('Good one. '), 'the PIN voice is the anchor; nobody is asked to name it')
        speech, cont = self.say('me too', SAM, 1.5)
        self.assertTrue(speech.startswith("Let's try another one. "))

    def test_a_config_started_child_enrollment_is_pooled_and_closes_with_the_pin(self):
        ctx = voice.VoiceContext('ha', KEY[1], '', '', service_revision=voice._revision(), paired=True)
        with patch.object(main, '_voice_parent', return_value=storage.get_member('jeff')):
            main.voice_recognition_enroll({'consent': True, 'ha_instance_id': 'ha', 'satellite_id': KEY[1], 'member_id': 'lily'},
                                          Request({'type': 'http', 'method': 'POST', 'path': '/', 'query_string': b'', 'headers': []}))
        self.assertTrue(fp._enrollments[KEY]['pooled'])
        speech, cont = self.say('hello', LILY, 1.5)
        self.assertIn(fp.kid_question(0), speech)
        self.pool(); self.say('yes', JEFF, .5)
        for _ in range(4):
            self.pool()
        speech, cont = self.say(PIN, JEFF, 3)    # no exclusion fingerprint: the PIN alone verifies the parent
        self.assertIn('saved', speech.lower())
        self.assertEqual(fp.profiles()[0]['member_id'], 'lily')


if __name__ == '__main__':
    unittest.main()
```

Replace `test_a_child_is_enrolled_with_a_parents_pin_and_yes` in `chauffeur/tests/test_voice_setup.py:71-87` with (that harness always reports 8 voiced seconds, so each answer fills a pool):

```python
    def test_a_child_is_enrolled_with_a_parents_pin_twice(self):
        self.say('set up my voice')
        speech, _ = self.say('for Lily')
        self.assertIn("parent's PIN", speech)
        speech, cont = self.say('my PIN is one two three four', vector(0))     # Jeff speaks
        self.assertIn('Hi Lily', speech); self.assertIn(fp.kid_question(0), speech); self.assertTrue(cont)
        speech, cont = self.say('I had cereal and then I went to school and played', vector(3))  # Lily, 8 s fills pool 1
        self.assertEqual(speech, 'Is that Lily talking? Say yes.')
        self.say('yes', vector(0))
        for _ in range(4):
            speech, cont = self.say('I had cereal and then I went to school and played', vector(3))
        self.assertEqual(speech, 'All done! If that was Lily, say your PIN.'); self.assertTrue(cont)
        speech, cont = self.say('my PIN is one two three four', vector(0))
        self.assertIn('Turn on voice recognition for Lily', speech)
        self.say('yes', vector(0))
        row = fp.profiles()[0]
        self.assertEqual((row['member_id'], row['consent_actor'], row['pooled']), ('lily', 'jeff', True))
        self.assertIsNone(voice._sessions.get(KEY, {}).get('member_id') if voice._sessions.get(KEY, {}).get('level') == 'verified' else None,
                          'the parent consent left a verified parent session')
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python tests/test_voice_setup_kids.py; python tests/test_voice_setup.py`
Expected: failures on `set up Lily's voice` (no dialog opens: the agent runs or "Who is this for" is missing), `Hi Lily`, the closing PIN.

- [ ] **Step 3: Implement the dialog**

In `chauffeur/services/voice_setup.py`:

Add after `NAME_LEAD`:

```python
SHORT_QUESTIONS = r"(?:,?\s*(?:with |using )?the (?:short|kid) questions)?"


def _start(low):
    """A start phrase: 'set up my voice', 'set up Lily's voice', either with
    'with the short questions' → (spoken name or '', pooled) or None."""
    pooled = bool(re.search(r"\bthe (?:short|kid) questions$", low))
    base = re.sub(r",?\s*(?:with |using )?the (?:short|kid) questions$", '', low).strip()
    if base in START:
        return '', pooled
    m = re.fullmatch(r"(?:set ?up|enroll|enrol) (.+?)'s voice", base)
    return (m.group(1), pooled) if m else None
```

Change `_finish_or_activate` to take and record the conversation:

```python
def _finish_or_activate(key, d, lead, conversation_id=None):
    if identity.recognition_on_everywhere():
        _dialogs.pop(key, None)
        return _reply(f'{lead} Recognition is already on.')
    if d.get('parent_id'):
        d['phase'] = 'activate'
        d['activate_conversation'] = conversation_id
        return _reply(f'{lead} {_activation_question(d)}', True)
    _dialogs.pop(key, None)
    return _reply(f'{lead} A parent can turn on recognition for you.')
```

and pass `conversation_id` at its three call sites (`questions` done, `confirm`, `check_answer`).

Change `_begin`:

```python
def _begin(key, ctx, d, anchor, exclude):
    try:
        fp.begin(ctx, d['member_id'], d.get('parent_id') or d['member_id'], anchor=anchor, exclude=exclude,
                 pooled=bool(d.get('pooled')))
    except ValueError as error:
        _dialogs.pop(key, None)
        return _reply(str(error))
    d['phase'] = 'questions'
    asked = fp.ask(key)
    if d.get('pooled') and (d.get('parent_id') or d['member_id']) != d['member_id']:
        name = (storage.get_member(d['member_id']) or {}).get('name', 'there')
        return _reply(f"Thanks. Hi {name}. I'm going to ask you some questions. Just answer out loud. {asked['question']}", True)
    return _reply(f"Thanks. {asked['question']}", True)
```

Pull the `who` phase body into a helper and call it from both the start phrase and the phase:

```python
def _who(key, ctx, d, text):
    matches = _members_named(text)
    if len(matches) != 1:
        return _reply('Which family member? Say the full name.', True)
    member = matches[0]
    d['member_id'] = member['id']
    if member.get('role') == 'child':
        d['pooled'] = True
        parents = identity.parents_named('')
        if len(parents) == 1:
            d['parent_id'] = parents[0]['id']
            d['phase'] = 'consent_pin'
            return _reply(f"{parents[0]['name']}, a parent's PIN, please.", True)
        d['phase'] = 'consent_parent'
        return _reply("Which parent is giving consent? Say your name, then I'll ask for your PIN.", True)
    d['phase'] = 'pin'
    if member.get('role') == 'parent':
        d['parent_id'] = member['id']
    identity.intercept(f"it's {member['name']}", ctx)
    identity.expect_pin(*key)
    return _reply('Say your PIN.', True)
```

In `intercept`, the `d is None` branch:

```python
        if d is None:
            started = _start(low)
            if started is not None:
                who, pooled = started
                d = _dialogs[key] = {'phase': 'who', 'pooled': pooled, 'expires_at': time.time() + EXPIRY}
                return _who(key, ctx, d, who) if who else _reply('Who is this for?', True)
            ...
        if phase == 'who':
            return _who(key, ctx, d, text)
```

`consent_pin` success and the new `consent_voice` phase:

```python
        if phase == 'consent_pin':
            out = identity.verify_parent_consent(ctx, d['parent_id'], text)
            if not out['ok']:
                if _locked_out(out['message']):
                    _dialogs.pop(key, None)
                    return _reply(out['message'])
                return _reply(out['message'] + ' Try once more, or say cancel voice setup.', True)
            if vector is None:
                # No fingerprint from the PIN turn: a child's enrollment must not
                # start without the parent's voice to exclude (Codex review, finding 3).
                d['phase'] = 'consent_voice'; d['consent_tries'] = 0
                return _reply(f"I need to hear your voice first. Say: I'm giving consent for {_name(d)} to set up a voice.", True)
            return _begin(key, ctx, d, anchor=None, exclude=vector)

        if phase == 'consent_voice':
            if vector is not None:
                return _begin(key, ctx, d, anchor=None, exclude=vector)
            d['consent_tries'] = d.get('consent_tries', 0) + 1
            if d['consent_tries'] >= 3:
                _dialogs.pop(key, None)
                return _reply("I couldn't hear you well enough to go on. Voice setup stopped.")
            return _reply(f"A little longer, please. Say: I'm giving consent for {_name(d)} to set up a voice.", True)
```

with a tiny helper near `_activation_question`:

```python
def _name(d):
    return (storage.get_member(d.get('member_id') or '') or {}).get('name', 'them')
```

`questions` phase: widen the continuing statuses and handle the new ones:

```python
        if phase == 'questions':
            out = fp.enrollment_turn(text, ctx, evidence, conversation_id=conversation_id)
            if out is None:
                _dialogs.pop(key, None)
                return _reply('Voice setup stopped.')
            status = out.get('status')
            if status in ('accepted', 'retry', 'restart', 'dropped') and key in fp._enrollments:
                pending = fp._enrollments[key]
                if pending.get('awaiting'):
                    return _reply(f"{out['message']} {fp.current_question(pending)}".strip(), True)
                return _next_question(key, conversation_id, out['message'])
            if status == 'name_voice':
                d['phase'] = 'name_voice'; d['name_reasks'] = 0
                return _reply(out['message'], True)
            if status == 'confirm':
                d['phase'] = 'confirm'; d['confirm_conversation'] = conversation_id; d['confirm_tries'] = 0
                return _reply(out['message'], True)
            if status == 'done':
                return _finish_or_activate(key, d, out['message'], conversation_id)
            _dialogs.pop(key, None)
            return _reply(out['message'])

        if phase == 'name_voice':
            kind = _answer_kind(low)
            if kind is None:
                d['name_reasks'] = d.get('name_reasks', 0) + 1
                if d['name_reasks'] <= 2:
                    return _reply(f'Is that {_name(d)} talking? Yes or no?', True)
                kind = 'no'
            out = fp.name_voice(key, kind == 'yes')
            if out['status'] == 'accepted':
                d['phase'] = 'questions'
                return _next_question(key, conversation_id, out['message'])
            _dialogs.pop(key, None)
            return _reply(out['message'])

        if phase == 'confirm':
            # Someone else's voice is saved on the consenting parent's PIN, said
            # again, in the conversation that asked, in the parent's own voice.
            again = f'If that was {_name(d)}, say your PIN.'
            if conversation_id and d.get('confirm_conversation') and conversation_id != d['confirm_conversation']:
                d['confirm_conversation'] = conversation_id
                return _reply(again, True)
            if not d.get('parent_id'):
                _dialogs.pop(key, None); fp.cancel(key)
                return _reply('Not saved. A parent has to give consent.')
            if _answer_kind(low) == 'yes' and 'pin' not in low:
                return _reply('Say your PIN.', True)
            out = identity.verify_parent_consent(ctx, d['parent_id'], text)
            if not out['ok']:
                if _locked_out(out['message']):
                    _dialogs.pop(key, None); fp.cancel(key)
                    return _reply(out['message'] + ' Not saved.')
                if 'did not match' not in out['message']:
                    return _reply(out['message'] + ' ' + again, True)   # not a PIN at all: the question stands
                return _confirm_strike(key, d, out['message'] + ' ' + again)
            pending = fp._enrollments.get(key) or {}
            exclude = pending.get('exclude')
            if exclude is not None and (vector is None or fp.score(vector, exclude) < fp.CONTINUITY):
                return _confirm_strike(key, d, 'That did not sound like the parent who gave consent. ' + again)
            out = fp.confirm(key, True)
            if out['status'] == 'done':
                return _finish_or_activate(key, d, out['message'], conversation_id)
            _dialogs.pop(key, None)
            return _reply(out['message'])

        if phase == 'activate':
            if conversation_id and d.get('activate_conversation') and conversation_id != d['activate_conversation']:
                d['activate_conversation'] = conversation_id
                return _reply(_activation_question(d), True)
            ... (the existing body)
```

with the helper:

```python
def _confirm_strike(key, d, message):
    """A wrong PIN or the wrong voice at the closing PIN: one more try."""
    d['confirm_tries'] = d.get('confirm_tries', 0) + 1
    if d['confirm_tries'] >= 2:
        _dialogs.pop(key, None); fp.cancel(key)
        return _reply('Not saved. Say set up my voice to start again.')
    return _reply(message, True)
```

Also in the `check_answer` phase pass `conversation_id` to `_finish_or_activate`, and add `"we're done"` to the bare cancel words at `intercept` (`'cancel', 'stop', 'never mind', 'nevermind', 'quit', "we're done", ...`); a sentence that merely contains one of them stays an answer, as today.

In `chauffeur/main.py:4035`:

```python
        member_id = str(payload.get('member_id') or '')
        return voice_fingerprint.begin(ctx, member_id, parent['id'],
                                       pooled=(storage.get_member(member_id) or {}).get('role') == 'child')
```

(`storage` is already imported in `main.py`; if that line's scope lacks it, add `from services import storage` beside the existing local import.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python tests/test_voice_setup_kids.py; python tests/test_voice_setup.py; python tests/test_voice_setup_component.py; python tests/test_voice_enrollment.py; python tests/test_voice_enrollment_pooled.py`
Expected: all OK.

- [ ] **Step 5: Codex reviews the diff, Claude applies verified findings, then commits**

`/codex:review --base HEAD` with the spec path in the focus; apply with receiving-code-review discipline (verify each finding against the code first). Then:

```bash
git add chauffeur/services/voice_setup.py chauffeur/main.py chauffeur/tests/test_voice_setup_kids.py chauffeur/tests/test_voice_setup.py
git commit -m "feat(voice): a child's voice by talking - 'set up Lily's voice', the parent's PIN (or a consent line when the PIN carried no fingerprint), quick questions pooled into samples, 'Is that Lily talking?' after the first pool, drops after it, the parent's PIN again at the end in the parent's voice and conversation, the activation yes bound to its conversation (vX.Y.Z)"
```

---

### Task 3: Config word, the capabilities record, the spec correction, memory

**Files:**
- Modify: `chauffeur/templates/config.html:1234` (the profile line)
- Modify: `chauffeur/tests/test_voice_enrollment.py:305-310` (`ConfigWordsTests`)
- Modify: `chauffeur/system_capabilities.md` (new entry at the top; version line)
- Modify: `docs/superpowers/specs/2026-10-13-kid-voice-enrollment-design.md` ("What does not change", the phone line)
- Modify: `C:\Users\ffejn\.claude\projects\e--repositories-Chauffeur\memory\voice-enrollment-arc.md`, `MEMORY.md`

**Interfaces:**
- Consumes: `status()['profiles'][*]['pooled']` from Task 1.

- [ ] **Step 1: Write the failing test**

Add to `ConfigWordsTests` in `chauffeur/tests/test_voice_enrollment.py`:

```python
    def test_config_says_short_answers_for_a_pooled_voice(self):
        src = open(Path(__file__).resolve().parents[1] / 'templates' / 'config.html', encoding='utf-8').read()
        self.assertIn('profile.pooled', src)
        self.assertIn('short answers', src)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python tests/test_voice_enrollment.py`
Expected: `AssertionError: 'profile.pooled' not found`.

- [ ] **Step 3: The Config word**

In `chauffeur/templates/config.html:1234` extend the `x-text`:

```html
<span class="text-xs" x-text="(members.find(m => m.id === profile.member_id)?.name || 'Family member') + ' · ' + (profile.provenance === 'phone' ? 'made on a phone' : 'made on this speaker') + (profile.pooled ? ' · short answers' : '') + ' · ' + (profile.calibrated ? 'five samples checked' : 'voices too similar — recognition unavailable')"></span>
```

No class changes, so no Tailwind rebuild. Run: `python tests/test_voice_enrollment.py` → OK.

- [ ] **Step 4: The spec correction**

In the spec's "What does not change", replace the phone line with:

```markdown
- The phone door is unchanged: it does not pool, and it has no closing confirmation (a present parent types the PIN on the child's screen at the start, which is the parent's own authenticated act). The adult satellite flow gains the consent fixes above (no child enrollment without an exclusion fingerprint; the parent's PIN instead of a yes before saving someone else's voice; the activation yes bound to its conversation), which it should have had.
```

- [ ] **Step 5: The capabilities entry**

At the top of `chauffeur/system_capabilities.md`, after the "Current through" line (update that line's version and date), add one paragraph in the house style, covering: pooled enrollment (`begin(..., pooled=)`, `KID_QUESTIONS`/`kid_question`/`current_question`, `POOL_SECONDS`/`POOLED_ANSWER_SECONDS`/`MAX_POOLED_TURNS`/`MAX_DROPS`/`MAX_POOL_RESTARTS`, `_pooled_answer`, `name_voice`, `_closing`), how a sample is assembled, pool 1 hard then anchored by the parent's "Is that Lily talking?", drops after the anchor, held-out checks scoring each short answer alone and why (the Codex finding), the forty-turn ceiling and follow-ups, the dialog (`voice_setup._start`, "set up Lily's voice", "with the short questions", `consent_voice`, `name_voice`, the closing PIN voice-matched and conversation-bound, `_confirm_strike`, the activation yes bound to its conversation), the Config-started child enrollment pooled from `main.py`, the two shipped-flow fixes (no `exclude=None` start; the yes replaced by the PIN for someone else's enrollment), `pooled` on rows and in Config ("short answers"), the test files, the device step with negatives, and NOT device-verified.

- [ ] **Step 6: Gate, bump, commit**

Run: `python tests/test_voice_enrollment.py; python tests/test_voice_enrollment_pooled.py; python tests/test_voice_setup.py; python tests/test_voice_setup_kids.py; python tests/test_voice_enrollment_phone.py; python tests/test_voice_setup_component.py`
Expected: all OK. Bump `chauffeur/config.yaml`, then:

```bash
git add chauffeur/templates/config.html chauffeur/tests/test_voice_enrollment.py chauffeur/system_capabilities.md chauffeur/config.yaml docs/superpowers/specs/2026-10-13-kid-voice-enrollment-design.md
git commit -m "docs(voice): kid voice enrollment shipped - Config says short answers for a pooled voice, capabilities entry, spec phone line corrected (vX.Y.Z)"
```

Then update the memory arc file (shipped versions, NOT device-verified, the device step with negatives as the next user act) and the `MEMORY.md` line.

---

## Self-review notes

- **Spec coverage:** pooled step and per-answer floor (Task 1); per-answer held-out checks (Task 1); pool 1 hard, parent names it, drops after (Task 1 core, Task 2 dialog); start phrases and the short-questions choice (Task 2); consent-line fallback (Task 2); hand-off line, interjections, "Almost done!", follow-ups, exhaustion (Tasks 1 and 2); closing PIN voice-matched and conversation-bound, one more try, lockout (Task 2); activation yes conversation-bound (Task 2); cancel words bare only (test in Task 2, no code change); silence/expiry (unchanged, 600 s); `pooled` on rows, Config word (Tasks 1 and 3); device step with negatives (memory, Task 3). The phone door is untouched and the spec line about it is corrected (Task 3).
- **Placeholders:** none; every step carries code or an exact command.
- **Type consistency:** `begin(..., pooled=)`, `current_question(pending)`, `kid_question(index)`, `name_voice(key, yes)`, `_closing(key, pending)`, `_finish_or_activate(key, d, lead, conversation_id=None)`, `_start(low)`, `_who(key, ctx, d, text)`, `_name(d)`, `_confirm_strike(key, d, message)` are used with the same shapes in every task.
- **Review Focus:** each of the five lines names its test and task.
- **Known judgment calls for the executor:** a non-PIN utterance at the closing PIN ("Say the PIN one digit at a time.") does not count as a strike, so a chattering child cannot burn the parent's two tries; the `name_voice` re-ask is twice, then no; a Config-started child enrollment has no exclusion fingerprint, so its closing PIN is verified but not voice-matched (documented in the capabilities entry).
