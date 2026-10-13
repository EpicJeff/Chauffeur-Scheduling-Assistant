# Voice Enrollment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A family member sets up their voice by talking to Argyle on a satellite or by tapping through five questions on their phone, a phone-made voice is checked on each speaker with one spoken sentence, and a parent turns recognition on with one spoken word.

**Architecture:** One enrollment state machine in `services/voice_fingerprint.py` (questions, a one-use admission token per step, speaker binding to the credential utterance, provenance and per-satellite check state), fronted by a new `services/voice_setup.py` that holds the spoken dialog for satellites and the phone endpoints' logic. `services/voice_identity.py` gains an enrollment-scoped parent consent verifier and a per-satellite recognition switch. The satellite door rides `/api/v2/converse` and HA's `continue_conversation`; the phone door rides new `/api/app-voice/enroll` routes that reuse the shipped recorder, `app_voice_audio.pcm` and `app_voice_audio.speak`.

**Tech Stack:** Python 3.11 FastAPI add-on, sherpa-onnx WeSpeaker embeddings (`voice_fingerprint.extract`), Home Assistant custom component (`chauffeur_conversation`), vanilla JS PWA (`static/app_voice.js`, `static/pwa_shell.js`), Alpine on `config.html`. Tests are plain `unittest` scripts run from `chauffeur/` with `HA_BASE_URL` unset.

**Spec:** `docs/superpowers/specs/2026-10-13-voice-enrollment-design.md`

## Global Constraints

- Recognition names, never verifies: a template sets a session to `named`; PIN sets `verified`; release, submit and payment keep their PIN-backed rules (spec, Boundary).
- Recognition on a satellite is turned on by a parent after that satellite's check, never by finishing an enrollment (spec, Activation; fingerprint spec builds F2).
- Thresholds stay `THRESHOLD, MARGIN, CONTINUITY = .70, .12, .65` and are never lowered to finish a setup.
- A sample needs at least 4 s of voiced audio (`extract`'s rule); three unusable attempts at one step end the enrollment.
- Enrollment expiry stays 600 s; at most one pending enrollment per satellite and per member, sixteen household-wide.
- Speech during an active enrollment never reaches the chat model: sample, guidance, or cancellation only.
- Archiving or disabling a member keeps templates and stops matching; only explicit voice deletion or permanent member deletion removes them.
- `templates.json` keeps its shape; new fields only; old rows read as `provenance: satellite`, checked on their own key.
- Credential fingerprints and step tokens live only in the in-memory enrollment.
- The paid-key pin test and the settings-registry audit must stay green; tests run from `chauffeur/` as `python tests/<file>.py`; never the full sweep.
- No `alert`/`confirm`/`prompt`; the PWA uses `promptConfirm`/`showGlobalAlert`; Tailwind is rebuilt with `python tools/build_tailwind.py` after template class changes.
- Nobody bumps `config.yaml` or commits except Claude Code at the end of each task (standing coordination rule).

## Review Focus

1. **A second enrollment started on the same satellite while one is pending** (a sibling says "set up my voice" mid-flow): the pending one must keep its anchor and the newcomer must be told to wait, never merged. Test in Task 1 (`test_second_enrollment_on_a_busy_satellite_is_refused`).
2. **The credential utterance yields no fingerprint** (bridge down, short PIN phrase): enrollment must still run on mutual consistency and the finish message must say matching was unavailable. Test in Task 1 (`test_no_credential_fingerprint_falls_back_to_consistency`).
3. **HA delivers the continued answer as a new conversation id** (some HA versions rotate ids): the admission rule must accept when the pending enrollment recorded no id, and reject only a *different* known id. Test in Task 3 (`test_continued_turn_with_unknown_conversation_id_is_still_admitted`).
4. **A parent's PIN spoken for a child is wrong three times**: the parent's own lock counters must trip, the child's must not, and the enrollment must end. Test in Task 2 (`test_wrong_parent_pin_locks_the_parent_not_the_child`).
5. **A phone upload arrives for a step whose token was already used** (double tap, retry after a timeout): the second upload must be refused as a stale token, not counted as a sample. Test in Task 5 (`test_a_reused_step_token_is_refused`).

---

### Task 1: The enrollment core — questions, admission, speaker binding, provenance

**Files:**
- Modify: `chauffeur/services/voice_fingerprint.py` (PROMPTS at :30-36, `begin` :284-298, `enrollment_turn` :301-353, `consume` :247-271, `status` :406-416, `delete` :393-404)
- Create: `chauffeur/tests/test_voice_enrollment.py`

**Interfaces:**
- Consumes: `voice_identity._active`, `voice_identity.configuration`, `storage.get_member`, existing `extract`, `score`, `normalized`, `profiles`, `_load/_save`.
- Produces (all in `voice_fingerprint`):
  - `QUESTIONS: tuple[str, ...]` (five), `CHECK_QUESTION: str`.
  - `begin(ctx, member_id, consent_actor, *, door='satellite', anchor=None, exclude=None) -> dict` — same positional signature as today (the Config endpoint keeps calling it); keyword extras bind the speaker. Raises `ValueError` as today, plus `'Voice setup is already in progress here.'` when the key is busy and `'That person is already setting up a voice.'` when the member is busy on another key.
  - `ask(key) -> dict` → `{'enrollment_id', 'step', 'question', 'token'}`; records `awaiting`.
  - `answer(key, evidence, token=None, conversation_id=None) -> dict` → `{'status': 'accepted'|'retry'|'ended'|'confirm'|'done', 'message', 'step'}`.
  - `confirm(key, yes: bool) -> dict` → `{'status': 'done'|'ended', 'message'}` (child flow).
  - `cancel(key) -> dict` → `{'status': 'ended', 'message': 'Voice setup cancelled.'}`.
  - `check(key, member_id, evidence, anchor) -> dict` → `{'status': 'checked'|'does_not_transfer'|'retry', 'message'}`; `anchor` may be None.
  - `checked_on(row, key) -> bool`.
  - Row fields: `provenance`, `device_id`, `checks` (dict keyed `"ha:assist_satellite.kitchen"` → `'checked'|'does_not_transfer'`).
  - `enrollment_turn(text, ctx, evidence, conversation_id=None)` keeps its name and return shape (`None` or `{'message'}`), now: `cancel voice setup` → cancel; otherwise `answer(...)` when awaiting, else guidance.
  - `status()` gains `'question'` in place of `'prompt'` on enrollments, plus `'door'`, `'phase'`; profiles gain `'provenance'`, `'checks'`.

- [ ] **Step 1: Write the failing tests**

Create `chauffeur/tests/test_voice_enrollment.py`:

```python
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

    def evidence(self, v, seconds=8):
        pending = fp._enrollments.get(KEY) or {}
        return {'vector': v, 'seconds': seconds, 'enrollment_id': pending.get('id')}

    def run_five(self, voices, token_for_step=None):
        """Ask and answer five steps; returns the last answer."""
        out = None
        for step in range(5):
            asked = fp.ask(KEY)
            token = token_for_step(step, asked['token']) if token_for_step else asked['token']
            out = fp.answer(KEY, self.evidence(voices[step]), token=token)
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
        self.run_five([vector(0)] * 5)
        row = fp.profiles()[0]
        self.assertEqual(row['provenance'], 'phone')
        self.assertFalse(fp.checked_on(row, KEY))
        out = fp.check(KEY, 'jeff', {'vector': vector(0, lean=1, weight=0.95), 'seconds': 8}, anchor=vector(0, lean=1, weight=0.95))
        self.assertEqual(out['status'], 'checked', out)
        self.assertTrue(fp.checked_on(fp.profiles()[0], KEY))

    def test_a_check_that_misses_marks_does_not_transfer(self):
        fp.begin(self.ctx(), 'jeff', 'jeff', door='phone', anchor=None)
        self.run_five([vector(0)] * 5)
        out = fp.check(KEY, 'jeff', {'vector': vector(5), 'seconds': 8}, anchor=vector(5))
        self.assertEqual(out['status'], 'does_not_transfer')
        self.assertEqual(fp.profiles()[0]['checks'][f'{KEY[0]}:{KEY[1]}'], 'does_not_transfer')
        self.assertFalse(fp.checked_on(fp.profiles()[0], KEY))

    def test_a_check_answer_must_match_its_own_credential(self):
        fp.begin(self.ctx(), 'jeff', 'jeff', door='phone', anchor=None)
        self.run_five([vector(0)] * 5)
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
        fp.begin(self.ctx(), 'jeff', 'jeff', anchor=vector(0))
        fp.ask(KEY)
        out = fp.enrollment_turn("what's on the calendar", self.ctx(), None)
        self.assertIn('Voice setup is in progress', out['message'])
        self.assertEqual(fp._enrollments[KEY]['samples'], [])
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


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run it to verify it fails**

Run from `chauffeur/`: `python tests/test_voice_enrollment.py`
Expected: errors on `fp.QUESTIONS`, `fp.ask`, `fp.answer`, `fp.confirm`, `fp.cancel`, `fp.check`, `fp.checked_on`, `fp.on_member_status` (AttributeError), and `begin()` rejecting the keyword arguments (TypeError).

- [ ] **Step 3: Implement the core**

In `chauffeur/services/voice_fingerprint.py`, replace `PROMPTS` (:30-36) with:

```python
# Answers, not phrases: the speaker model is text-independent, and every
# sample is bound to its run and admitted by a one-use token (spec, core).
QUESTIONS = (
    'Tell me about your day so far, for about ten seconds.',
    'What is coming up for the family this week?',
    'Describe the room you are in.',
    'What would you like help with most mornings?',
    'Tell me something you are looking forward to.',
)
CHECK_QUESTION = 'Tell me what you did this morning, for about ten seconds.'
PROMPTS = QUESTIONS   # the Config page and old tests read this name
MIN_SAMPLE_SECONDS = 4
MAX_RETRIES = 3
```

Replace `begin` (:284-298) with:

```python
def _key_str(key):
    return f'{key[0]}:{key[1]}'


def _busy(member_id):
    return any(p['member_id'] == member_id for p in _enrollments.values())


def begin(ctx, member_id, consent_actor, *, door='satellite', anchor=None, exclude=None):
    """Open an enrollment. `anchor` is the enrollee's own credential fingerprint
    (self-enrollment binds every sample to it); `exclude` is the consenting
    parent's (a child's samples must not match it). Both live only here."""
    member = storage.get_member(member_id)
    if door == 'satellite' and (not ctx.paired or not identity._active(member)):
        raise ValueError('Choose an enabled satellite and active family member.')
    if door == 'phone' and not identity._active(member):
        raise ValueError('That family member is not active.')
    if not model_ready():
        raise ValueError('Prepare the voice model first.')
    key = ('phone', member_id) if door == 'phone' else (ctx.ha_instance_id, ctx.satellite_id)
    with _lock:
        _prune()
        if key in _enrollments:
            raise ValueError('Voice setup is already in progress here.')
        if _busy(member_id):
            raise ValueError('That person is already setting up a voice.')
        if len(_enrollments) >= 16:
            raise ValueError('Too many pending enrollments.')
        _enrollments[key] = {
            'id': uuid.uuid4().hex, 'member_id': member_id, 'consent_actor': consent_actor, 'door': door,
            'device_id': satellite(ctx).get('device_id') if door == 'satellite' else 'phone',
            'service_revision': ctx.service_revision if door == 'satellite' else identity._revision(),
            'samples': [], 'step': 0, 'retries': 0, 'awaiting': None, 'phase': 'questions',
            'anchor': anchor, 'exclude': exclude, 'bound': anchor is not None or exclude is not None,
            'reference': None, 'expires_at': time.time() + 600}
    if door == 'satellite':
        identity.recover(ctx.ha_instance_id, ctx.satellite_id)
    return status()


def ask(key):
    """The current step's question with a fresh one-use token."""
    with _lock:
        _prune()
        pending = _enrollments.get(key)
        if not pending or pending['phase'] != 'questions':
            raise ValueError('No voice setup is waiting for an answer here.')
        token = uuid.uuid4().hex
        pending['awaiting'] = {'step': pending['step'], 'token': token, 'conversation_id': None, 'asked_at': time.time()}
        return {'enrollment_id': pending['id'], 'step': pending['step'] + 1,
                'question': QUESTIONS[pending['step']], 'token': token}


def expect_conversation(key, conversation_id):
    """The satellite door records the question's conversation id once it is known."""
    with _lock:
        pending = _enrollments.get(key)
        if pending and pending.get('awaiting') and conversation_id:
            pending['awaiting']['conversation_id'] = conversation_id


def cancel(key):
    with _lock:
        _enrollments.pop(key, None)
    return {'status': 'ended', 'message': 'Voice setup cancelled.'}


def _end(key, message):
    _enrollments.pop(key, None)
    return {'status': 'ended', 'message': message, 'step': 0}


def answer(key, evidence, token=None, conversation_id=None):
    """Admit one answer: the token must be the current one (one use), the
    conversation id must match when both are known, the sample must be long
    enough, and the speaker must be the credential's (or not the parent's)."""
    with _lock:
        _prune()
        pending = _enrollments.get(key)
        if not pending or pending['phase'] != 'questions':
            return {'status': 'retry', 'message': 'No voice setup is waiting for an answer here.', 'step': 0}
        awaiting = pending.get('awaiting')
        step = pending['step']
        if not awaiting or awaiting['token'] != token or awaiting['step'] != step \
                or (conversation_id and awaiting['conversation_id'] and awaiting['conversation_id'] != conversation_id):
            return {'status': 'retry', 'step': step + 1,
                    'message': 'Voice setup is in progress. Answer the question, or say cancel voice setup.'}
        pending['awaiting'] = None   # one use, spent whatever happens next
        if not evidence or evidence.get('enrollment_id') not in (None, pending['id']) \
                or evidence.get('seconds', 0) < MIN_SAMPLE_SECONDS or not evidence.get('vector'):
            pending['retries'] += 1
            if pending['retries'] >= MAX_RETRIES:
                return _end(key, 'I could not get a clear sample three times. Voice setup stopped; try again somewhere quieter.')
            return {'status': 'retry', 'step': step + 1, 'message': 'A little longer, please.'}
        vector = evidence['vector']
        if pending['anchor'] is not None and score(vector, pending['anchor']) < CONTINUITY:
            return _end(key, 'That did not sound like the voice that said the PIN. Voice setup stopped.')
        if pending['exclude'] is not None and score(vector, pending['exclude']) >= CONTINUITY:
            return _end(key, 'That sounded like the parent who gave consent, not the person being set up. Voice setup stopped.')
        samples = pending['samples']
        if samples and any(score(vector, other) < CONTINUITY for other in samples):
            return _end(key, 'The samples did not sound consistent. Voice setup stopped.')
        pending['retries'] = 0
        if step < 3:
            samples.append(vector)
        reference = normalized([sum(v[i] for v in samples) for i in range(256)])
        pending['reference'] = reference
        if step >= 3:
            rivals = [r for r in profiles() if r['member_id'] != pending['member_id']]
            competing = max((score(vector, r['vector']) for r in rivals), default=-1)
            if score(vector, reference) < THRESHOLD or score(vector, reference) - competing < MARGIN:
                return _end(key, 'I could not tell this voice apart reliably. Voice setup stopped; recognition stays off.')
        pending['step'] += 1
        if pending['step'] < len(QUESTIONS):
            return {'status': 'accepted', 'step': pending['step'] + 1, 'message': 'Got it.'}
        if pending['exclude'] is not None:
            pending['phase'] = 'confirm'
            name = (storage.get_member(pending['member_id']) or {}).get('name', 'them')
            return {'status': 'confirm', 'step': 5, 'message': f'Was that {name}? Say yes.'}
        return _finish(key, pending)


def confirm(key, yes):
    with _lock:
        pending = _enrollments.get(key)
        if not pending or pending['phase'] != 'confirm':
            return {'status': 'retry', 'message': 'Nothing is waiting for a yes.', 'step': 0}
        if not yes:
            return _end(key, 'Not saved. Say set up my voice to start again.')
        return _finish(key, pending)


def _finish(key, pending):
    member = storage.get_member(pending['member_id'])
    if not identity._active(member):
        return _end(key, 'That member is no longer active.')
    reference = pending['reference']
    rows = [r for r in _load() if not (r['member_id'] == member['id'] and r.get('provenance', 'satellite') == pending['door']
                                      and (pending['door'] == 'phone' or r['key'] == list(key)))]
    checks = {_key_str(key): 'checked'} if pending['door'] == 'satellite' else {}
    rows.append({'member_id': member['id'], 'key': list(key) if pending['door'] == 'satellite' else ['phone', member['id']],
                 'vector': reference, 'revision': REVISION, 'consent_actor': pending['consent_actor'],
                 'created_at': time.time(), 'checks': checks, 'calibrated': pending['door'] == 'satellite',
                 'provenance': pending['door'], 'device_id': pending['device_id']})
    active = [r for r in rows if r.get('revision') == REVISION and identity._active(storage.get_member(r['member_id']))]
    for row in active:
        if any(r['member_id'] != row['member_id'] and score(r['vector'], row['vector']) >= THRESHOLD - MARGIN for r in active):
            row['calibrated'] = False
            if isinstance(row.get('checks'), dict):
                row['checks'] = {k: 'does_not_transfer' if v == 'checked' else v for k, v in row['checks'].items()}
    _save(rows)
    _enrollments.pop(key, None)
    note = '' if pending['bound'] else ' Voice matching was unavailable during setup, so this relied on the samples matching each other.'
    if pending['door'] == 'phone':
        return {'status': 'done', 'step': 5, 'message': 'Saved. Your speakers will each check it the first time: say "Hey Argyle, check my voice" in the room.' + note}
    return {'status': 'done', 'step': 5, 'message': 'Your voice is saved here.' + note}


def checked_on(row, key):
    """A template names people on a satellite only once checked there. A
    legacy row (no provenance) was made on its own key and counts as checked."""
    checks = row.get('checks')
    if isinstance(checks, dict):
        return checks.get(_key_str(key)) == 'checked'
    return row.get('provenance', 'satellite') == 'satellite' and row.get('key') == list(key) and bool(row.get('calibrated'))


def check(key, member_id, evidence, anchor):
    """One explicit spoken check of a phone template on a satellite: the answer
    must be the credential's voice, then it is scored like a held-out check."""
    if not evidence or evidence.get('seconds', 0) < MIN_SAMPLE_SECONDS or not evidence.get('vector'):
        return {'status': 'retry', 'message': 'A little longer, please.'}
    vector = evidence['vector']
    if anchor is not None and score(vector, anchor) < CONTINUITY:
        return {'status': 'retry', 'message': 'That did not sound like the voice that said the PIN. Try once more.'}
    with _lock:
        rows = _load()
        mine = [r for r in rows if r['member_id'] == member_id and r.get('provenance') == 'phone' and r.get('revision') == REVISION]
        if not mine:
            return {'status': 'retry', 'message': 'There is no phone voice to check. Set up your voice on your phone first.'}
        row = mine[-1]
        rivals = [r for r in rows if r['member_id'] != member_id and r.get('revision') == REVISION
                  and identity._active(storage.get_member(r['member_id'])) and checked_on(r, key)]
        competing = max((score(vector, r['vector']) for r in rivals), default=-1)
        own = score(vector, row['vector'])
        ok = own >= THRESHOLD and own - competing >= MARGIN
        row.setdefault('checks', {})[_key_str(key)] = 'checked' if ok else 'does_not_transfer'
        _save(rows)
    if ok:
        return {'status': 'checked', 'message': 'Your phone voice works here.'}
    return {'status': 'does_not_transfer', 'message': 'Your phone voice does not match this microphone.'}


def on_member_status(member_id):
    """Archiving or disabling stops matching (profiles() already filters) and
    cancels a pending enrollment; it never deletes a template."""
    with _lock:
        for key in list(_enrollments):
            if _enrollments[key]['member_id'] == member_id and not identity._active(storage.get_member(member_id)):
                _enrollments.pop(key, None)
```

Replace `enrollment_turn` (:301-353) with:

```python
def enrollment_turn(text, ctx, evidence, conversation_id=None):
    """The satellite door's per-turn gate: during an enrollment every utterance
    is a cancellation, an answer, or guidance; it never reaches the model."""
    key = (ctx.ha_instance_id, ctx.satellite_id)
    with _lock:
        _prune()
        pending = _enrollments.get(key)
        if not pending:
            return None
        if not ctx.paired or pending['service_revision'] != ctx.service_revision \
                or pending['device_id'] != satellite(ctx).get('device_id'):
            _enrollments.pop(key, None)
            return None
        awaiting = pending.get('awaiting')
        phase = pending['phase']
    low = text.strip().lower().rstrip('.!?')
    if low == 'cancel voice setup':
        return cancel(key)
    if phase == 'confirm':
        if low in ('yes', 'yes it was', 'yep', 'correct'):
            return confirm(key, True)
        if low in ('no', 'nope', 'no it was not', "no it wasn't"):
            return confirm(key, False)
        return {'message': 'Say yes or no.', 'status': 'retry'}
    if awaiting:
        return answer(key, evidence, token=awaiting['token'], conversation_id=conversation_id)
    return {'message': 'Voice setup is in progress. Answer the question, or say cancel voice setup.', 'status': 'retry'}
```

In `consume` (:259) replace `setup_phrase = pending and _matches_prompt(text, PROMPTS[pending['step']])` with `setup_phrase = bool(pending and pending.get('awaiting'))` and delete `_clean_phrase`/`_matches_prompt` if nothing else uses them (grep first; the Config page does not).

In `status()` (:406-416) change the enrollments entry to `'question': QUESTIONS[p['step']] if p['step'] < len(QUESTIONS) else '', 'door': p['door'], 'phase': p['phase']` (drop `'prompt'`), and the profiles entry to include `'provenance': r.get('provenance', 'satellite'), 'checks': r.get('checks') if isinstance(r.get('checks'), dict) else {}`.

In `delete` (:393) keep behaviour; it already cancels that member's pending enrollments.

Wherever `apply()` picks `rows` for naming on a satellite (the `rows` used for `candidates`, around :351), filter with `checked_on(r, key)` so an unchecked phone template never names anyone there.

- [ ] **Step 4: Run the tests**

Run: `python tests/test_voice_enrollment.py` — Expected: all pass.
Run: `python tests/test_voice_fingerprint.py` and `python tests/test_voice_identity.py` — Expected: pass. If a fingerprint test asserts the old phrase messages ("Read the next phrase shown on your phone"), update that assertion to the new guidance text; do not weaken anything about binding or thresholds.

- [ ] **Step 5: Commit**

```bash
git add chauffeur/services/voice_fingerprint.py chauffeur/tests/test_voice_enrollment.py chauffeur/tests/test_voice_fingerprint.py
git commit -m "feat(voice): enrollment core - answers not phrases, one-use step tokens, speaker binding to the credential utterance, provenance and per-satellite checks (vX.Y.Z)"
```
(Claude Code bumps `config.yaml` and adds the version to the subject.)

---

### Task 2: The enrollment-scoped parent consent verifier and the recognition switch

**Files:**
- Modify: `chauffeur/services/voice_identity.py` (after `_audit` :276-282; `configure` :44-69)
- Test: `chauffeur/tests/test_voice_enrollment.py` (append a class)

**Interfaces:**
- Consumes: `normalize_pin`, `_lock_keys`, `_locked`, `_record`, `storage.verify_member_pin`, `storage.rate_record/rate_locked/rate_clear`.
- Produces:
  - `voice_identity.verify_parent_consent(ctx, parent_id, text, language='en') -> dict` → `{'ok': bool, 'message': str}`; never touches `_sessions`; applies the parent's lock keys and the satellite's format rate key.
  - `voice_identity.parents_named(name_or_empty) -> list[dict]` → active parents matching the spoken name (all parents when empty).
  - `voice_identity.set_recognition(installation, satellite, on: bool) -> dict` → the configuration row; raises `ValueError('Enroll and check a voice before enabling recognition.')` when turning on with no checked template on that key.

- [ ] **Step 1: Write the failing tests** (append to `test_voice_enrollment.py`)

```python
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
        self.assertNotIn(KEY, voice._sessions, 'consent created a voice session')
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
```

- [ ] **Step 2: Run to verify failure** — `python tests/test_voice_enrollment.py` — Expected: AttributeError on `verify_parent_consent`, `parents_named`, `set_recognition`.

- [ ] **Step 3: Implement** (append after `_audit` in `voice_identity.py`)

```python
def parents_named(name):
    want = ' '.join((name or '').split()).casefold()
    parents = [m for m in storage.get_all_members() if _active(m) and m.get('role') == 'parent']
    if not want:
        return parents
    return [m for m in parents if want in voice_names(m)]


def verify_parent_consent(ctx, parent_id, text, language='en'):
    """A parent's PIN spoken (or typed) to consent to a child's enrollment.
    Verifies THAT parent's record with that parent's limits; creates no
    session, anchor or readback. The credential turn is consumed here."""
    parent = storage.get_member(parent_id)
    if not _active(parent) or parent.get('role') != 'parent':
        return {'ok': False, 'message': 'Only a parent can give consent for voice setup.'}
    if not parent.get('pin_hash'):
        return {'ok': False, 'message': f"{parent.get('name')} has no PIN yet. Set one on your phone first."}
    if _locked(ctx, parent['id']) or storage.rate_locked(f"member:{parent['id']}"):
        return {'ok': False, 'message': 'Voice verification is locked for that parent. Clear the voice lock on your phone.'}
    request_key = f'voice:format:{ctx.ha_instance_id}:{ctx.satellite_id}'
    if storage.rate_locked(request_key):
        return {'ok': False, 'message': 'Too many attempts. Try again in a moment.'}
    storage.rate_record(request_key, False)
    match = re.search(r'(?i)\b(?:my\s+)?pin\s+is\b\s*(.*)$', text or '')
    pin = normalize_pin(match.group(1) if match else (text or '')) if language.startswith('en') else None
    if pin is None or not 4 <= len(pin) <= 8 or parent.get('pin_length') and len(pin) != parent['pin_length']:
        return {'ok': False, 'message': 'Say the PIN one digit at a time.'}
    ok = storage.verify_member_pin(parent['id'], pin)
    _record(ctx, parent['id'], ok)
    storage.rate_record(f"member:{parent['id']}", ok)
    if ok:
        storage.rate_clear(request_key)
        _audit(ctx.ha_instance_id, ctx.satellite_id, parent['id'], 'consent')
        return {'ok': True, 'message': 'Thanks.'}
    return {'ok': False, 'message': 'That PIN did not match.' if not _locked(ctx, parent['id'])
            else 'Voice verification is locked for that parent.'}


def set_recognition(installation, satellite, on):
    """The per-satellite recognition switch, a parent's act (spec, Activation)."""
    config = configuration()
    rows = list(config.get('satellites', []))
    row = next((r for r in rows if r['ha_instance_id'] == installation and r['satellite_id'] == satellite), None)
    if not row:
        raise ValueError('That satellite is not set up for voice identity.')
    if on:
        from services import voice_fingerprint
        if not any(voice_fingerprint.checked_on(p, (installation, satellite)) for p in voice_fingerprint.profiles()):
            raise ValueError('Enroll and check a voice before enabling recognition.')
    row['recognition_enabled'] = bool(on)
    with _lock:
        storage.set_app_state('voice_identity_config', {**config, 'satellites': rows})
    return row
```

Also in `configure` (:59) change the calibrated check to `voice_fingerprint.checked_on(p, (installation, satellite))` over `voice_fingerprint._load()` rows that are active, so Config's toggle and the spoken switch agree.

- [ ] **Step 4: Run** — `python tests/test_voice_enrollment.py`, `python tests/test_voice_identity.py` — Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add chauffeur/services/voice_identity.py chauffeur/tests/test_voice_enrollment.py
git commit -m "feat(voice): enrollment-scoped parent consent verifier and the per-satellite recognition switch (vX.Y.Z)"
```

---

### Task 3: The satellite dialog — set up, check, activate, by voice

**Files:**
- Create: `chauffeur/services/voice_setup.py`
- Modify: `chauffeur/main.py` (`converse_ha_assist` perform(), the block at :3851-3855 that calls `enrollment_turn`)
- Create: `chauffeur/tests/test_voice_setup.py`

**Interfaces:**
- Consumes: Task 1 (`begin`, `ask`, `expect_conversation`, `answer`, `confirm`, `cancel`, `check`, `enrollment_turn`), Task 2 (`verify_parent_consent`, `parents_named`, `set_recognition`), `voice_identity.intercept` (the enrollee's own PIN), `voice_identity.voice_names`, `storage.get_member`.
- Produces: `voice_setup.intercept(text, ctx, evidence, conversation_id) -> dict | None` with keys `message` and `continue` (bool). `None` means "not a setup turn". A per-satellite dialog state `_dialogs[(installation, satellite)]` with `phase` in `who | pin | consent_parent | consent_pin | questions | confirm | activate | check_pin | check_answer | check_offer`.

The dialog phases, each one turn:

```
"set up my voice"                      → who   : "Who is this for?"              (continue)
who: name (via identity.intercept)     → pin   : "Say your PIN." (adult)           (continue)
                                       → consent_parent: "Which parent?" (child, >1 parent) / consent_pin: "A parent's PIN, please."
pin: the adult's PIN (identity.intercept; verified session) → begin(anchor=evidence vector) → ask → question 1 (continue)
consent_pin: parent PIN (verify_parent_consent) → begin(exclude=evidence vector) → ask → question 1 (continue)
questions: enrollment_turn → accepted → ask next (continue) | retry (continue) | confirm (continue) | done → activate? | ended
confirm: yes/no → done → activate? | ended
activate: "Turn on voice recognition for <you|Lily> here? Say yes." → yes → set_recognition(on) ; no → "Left off."
"check my voice"                       → check_pin: "Say your PIN." → verified → check_answer: CHECK_QUESTION (continue)
check_answer: check(key, member, evidence, anchor) → checked → activate? | does_not_transfer → check_offer: "Shall I set up your voice here now? Say yes." → yes → begin(anchor) with the check answer admitted as sample 1
"turn on voice recognition for <name> here" → parent PIN via identity.intercept if not verified → set_recognition(on)
"cancel voice setup"                   → cancel + clear dialog
```

- [ ] **Step 1: Write the failing tests**

Create `chauffeur/tests/test_voice_setup.py`:

```python
"""The spoken enrollment dialog on a satellite, driven through the real converse
endpoint with a scripted fingerprint. Spec: 2026-10-13-voice-enrollment-design.md."""
import os, sys, tempfile, time, unittest, uuid
from pathlib import Path
from unittest.mock import patch

os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_setup_')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import storage, voice_identity as voice, voice_fingerprint as fp, voice_setup
from starlette.requests import Request
import main

KEY = ('ha', 'assist_satellite.kitchen')


def vector(index=0):
    return fp.normalized([float(i == index) for i in range(256)])


class SatelliteDialogTests(unittest.TestCase):
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
        self.voices = []          # the fingerprint each next utterance carries
        self.conversation = 'conv-1'

        def consume(ctx, metadata, text=''):
            v = self.voices.pop(0) if self.voices else None
            pending = fp._enrollments.get(KEY) or {}
            return None if v is None else {'vector': v, 'seconds': 8, 'enrollment_id': pending.get('id')}
        patch.object(fp, 'consume', consume).start()

    def say(self, text, voice_vector=vector(0), conversation=None):
        self.voices.append(voice_vector)
        req = main.ConverseRequest(text=text, language='en', conversation_id=conversation or self.conversation,
                                   voice={'ha_instance_id': 'ha', 'satellite_id': KEY[1], 'device_id': 'device',
                                          'request_id': uuid.uuid4().hex, 'observed_at': time.time()})
        request = Request({'type': 'http', 'method': 'POST', 'path': '/', 'query_string': b'',
                           'headers': [(b'x-service-token', b'service')]})
        out = main.converse_ha_assist(req, request)
        return out['response']['speech']['plain']['speech'], out['continue_conversation']

    def test_an_adult_enrolls_in_one_conversation_and_turns_recognition_on(self):
        speech, cont = self.say('set up my voice')
        self.assertIn('Who is this for', speech); self.assertTrue(cont)
        speech, cont = self.say("it's Jeff")
        self.assertIn('PIN', speech); self.assertTrue(cont)
        speech, cont = self.say('my PIN is one two three four')
        self.assertIn(fp.QUESTIONS[0], speech); self.assertTrue(cont)
        for q in fp.QUESTIONS[1:]:
            speech, cont = self.say('well today I did some things and then some more things')
            self.assertIn(q, speech); self.assertTrue(cont)
        speech, cont = self.say('and finally I am looking forward to the weekend')
        self.assertIn('saved here', speech.lower()); self.assertIn('Turn on voice recognition', speech); self.assertTrue(cont)
        speech, cont = self.say('yes')
        self.assertIn('on', speech.lower()); self.assertFalse(cont)
        self.assertTrue(next(r for r in voice.configuration()['satellites'] if r['satellite_id'] == KEY[1])['recognition_enabled'])
        self.assertEqual([r['member_id'] for r in fp.profiles()], ['jeff'])
        self.assertFalse(voice_setup._dialogs)

    def test_a_child_is_enrolled_with_a_parents_pin_and_yes(self):
        self.say('set up my voice')
        speech, _ = self.say('for Lily')
        self.assertIn("parent's PIN", speech)
        speech, cont = self.say('my PIN is one two three four', vector(0))     # Jeff speaks
        self.assertIn(fp.QUESTIONS[0], speech); self.assertTrue(cont)
        for _ in range(5):
            speech, cont = self.say('I had cereal and then I went to school and played', vector(3))  # Lily speaks
        self.assertIn('Was that Lily', speech); self.assertTrue(cont)
        speech, cont = self.say('yes', vector(0))
        self.assertIn('Turn on voice recognition for Lily', speech)
        self.say('yes', vector(0))
        row = fp.profiles()[0]
        self.assertEqual((row['member_id'], row['consent_actor']), ('lily', 'jeff'))
        self.assertIsNone(voice._sessions.get(KEY, {}).get('member_id') if voice._sessions.get(KEY, {}).get('level') == 'verified' else None,
                          'the parent consent left a verified parent session')

    def test_the_parent_answering_for_the_child_ends_it(self):
        self.say('set up my voice'); self.say('for Lily'); self.say('my PIN is one two three four', vector(0))
        speech, cont = self.say('I will answer for her', vector(0))
        self.assertIn('parent', speech.lower()); self.assertFalse(cont)
        self.assertNotIn(KEY, fp._enrollments)

    def test_unrelated_speech_during_setup_never_reaches_the_agent(self):
        self.say('set up my voice'); self.say("it's Jeff"); self.say('my PIN is one two three four')
        with patch.object(main, 'process_agent_request', side_effect=AssertionError('the agent ran')) as agent:
            speech, cont = self.say('cancel voice setup')
        self.assertEqual(speech, 'Voice setup cancelled.'); self.assertFalse(cont)
        self.assertFalse(agent.called)

    def test_continued_turn_with_unknown_conversation_id_is_still_admitted(self):
        self.say('set up my voice'); self.say("it's Jeff")
        speech, _ = self.say('my PIN is one two three four')
        self.assertIn(fp.QUESTIONS[0], speech)
        speech, cont = self.say('today I walked the dog and made breakfast for everyone', conversation=None)
        self.assertIn(fp.QUESTIONS[1], speech, 'an answer with no conversation id was refused')
        speech, cont = self.say('today I walked the dog and made breakfast for everyone', conversation='another-room')
        self.assertNotIn(fp.QUESTIONS[2], speech, 'an answer from a different known conversation was admitted')

    def test_check_my_voice_accepts_a_phone_template_here(self):
        fp._save([{'member_id': 'jeff', 'key': ['phone', 'jeff'], 'vector': vector(0), 'revision': fp.REVISION,
                   'consent_actor': 'jeff', 'created_at': time.time(), 'checks': {}, 'calibrated': False,
                   'provenance': 'phone', 'device_id': 'phone'}])
        speech, cont = self.say('check my voice')
        self.assertIn('PIN', speech); self.assertTrue(cont)
        speech, cont = self.say('my PIN is one two three four')
        self.assertIn(fp.CHECK_QUESTION, speech); self.assertTrue(cont)
        speech, cont = self.say('this morning I made coffee and read the news for a while')
        self.assertIn('works here', speech.lower()); self.assertIn('Turn on voice recognition', speech)
        self.assertTrue(fp.checked_on(fp.profiles()[0], KEY))

    def test_check_my_voice_that_misses_offers_setup_here_keeping_the_answer(self):
        fp._save([{'member_id': 'jeff', 'key': ['phone', 'jeff'], 'vector': vector(9), 'revision': fp.REVISION,
                   'consent_actor': 'jeff', 'created_at': time.time(), 'checks': {}, 'calibrated': False,
                   'provenance': 'phone', 'device_id': 'phone'}])
        self.say('check my voice'); self.say('my PIN is one two three four')
        speech, cont = self.say('this morning I made coffee and read the news for a while')
        self.assertIn('does not match', speech.lower()); self.assertIn('set up your voice here', speech.lower()); self.assertTrue(cont)
        speech, cont = self.say('yes')
        self.assertIn(fp.QUESTIONS[1], speech, 'the check answer was not kept as sample 1')
        self.assertEqual(len(fp._enrollments[KEY]['samples']), 1)

    def test_turn_on_recognition_by_name_is_a_parent_act(self):
        fp.begin(voice.context({'ha_instance_id': 'ha', 'satellite_id': KEY[1], 'device_id': 'device',
                                'request_id': 'r', 'observed_at': time.time()}, True), 'lily', 'jeff', exclude=vector(0))
        for _ in range(5):
            a = fp.ask(KEY); fp.answer(KEY, {'vector': vector(3), 'seconds': 8, 'enrollment_id': fp._enrollments[KEY]['id']}, token=a['token'])
        fp.confirm(KEY, True)
        speech, cont = self.say('turn on voice recognition for Lily here')
        self.assertIn('PIN', speech)
        speech, cont = self.say('my PIN is one two three four')
        self.assertIn('on', speech.lower())
        self.assertTrue(next(r for r in voice.configuration()['satellites'] if r['satellite_id'] == KEY[1])['recognition_enabled'])


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run to verify failure** — `python tests/test_voice_setup.py` — Expected: ImportError on `voice_setup`.

- [ ] **Step 3: Implement `services/voice_setup.py`**

```python
"""The spoken voice-setup dialog on a satellite (spec 2026-10-13, Satellite
flow, Checking a phone voice, Activation). One small state per satellite;
every turn is intercepted before the chat model while a dialog is open."""
import logging, re, threading, time
from services import storage, voice_identity as identity, voice_fingerprint as fp

logger = logging.getLogger(__name__)
_dialogs = {}
_lock = threading.RLock()
EXPIRY = 600
YES = ('yes', 'yes please', 'yep', 'yeah', 'sure', 'ok', 'okay', 'do it')
NO = ('no', 'nope', 'no thanks', 'not now', 'leave it')


def _key(ctx):
    return (ctx.ha_instance_id, ctx.satellite_id)


def _reply(message, cont=False):
    return {'message': message, 'continue': bool(cont)}


def _activation_question(d):
    member = storage.get_member(d['member_id']) or {}
    who = 'you' if d.get('parent_id') == d['member_id'] else member.get('name', 'them')
    return f'Turn on voice recognition for {who} here? Say yes.'


def _finish_or_activate(key, d, lead):
    """After a save or a successful check: a parent present may switch it on."""
    if d.get('parent_id'):
        d['phase'] = 'activate'
        return _reply(f'{lead} {_activation_question(d)}', True)
    _dialogs.pop(key, None)
    return _reply(f'{lead} A parent can turn on recognition for you here.')


def intercept(text, ctx, evidence, conversation_id=None):
    """None when this is not a setup turn; otherwise the spoken reply."""
    if not ctx.paired:
        return None
    key = _key(ctx)
    low = ' '.join((text or '').lower().split()).rstrip('.!?')
    with _lock:
        for k, d in list(_dialogs.items()):
            if d['expires_at'] <= time.time():
                _dialogs.pop(k, None)
        d = _dialogs.get(key)
        if low == 'cancel voice setup':
            _dialogs.pop(key, None)
            return _reply(fp.cancel(key)['message'])
        if d is None:
            if low in ('set up my voice', 'setup my voice', 'set my voice up'):
                _dialogs[key] = {'phase': 'who', 'expires_at': time.time() + EXPIRY}
                return _reply('Who is this for?', True)
            if low == 'check my voice':
                _dialogs[key] = {'phase': 'check_pin', 'expires_at': time.time() + EXPIRY}
                return _reply('Say your PIN.', True)
            m = re.fullmatch(r'turn (on|off) voice recognition(?: for (.+?))?(?: here)?', low)
            if m:
                return _switch(key, ctx, m.group(1) == 'on', m.group(2) or '')
            return None
        d['expires_at'] = time.time() + EXPIRY
        vector = (evidence or {}).get('vector')
        phase = d['phase']

        if phase == 'who':
            name = re.sub(r"^(for|it's|it is|this is|i am|i'm)\s+", '', low)
            matches = [m for m in storage.get_all_members() if identity._active(m) and name in identity.voice_names(m)]
            if len(matches) != 1:
                return _reply('Which family member? Say the full name.', True)
            d['member_id'] = matches[0]['id']
            if matches[0].get('role') == 'child':
                parents = identity.parents_named('')
                if len(parents) == 1:
                    d['parent_id'] = parents[0]['id']; d['phase'] = 'consent_pin'
                    return _reply(f"{parents[0]['name']}, a parent's PIN, please.", True)
                d['phase'] = 'consent_parent'
                return _reply("Which parent is giving consent? Say your name, then I'll ask for your PIN.", True)
            d['phase'] = 'pin'
            if matches[0].get('role') == 'parent':
                d['parent_id'] = matches[0]['id']
            identity_reply = identity.intercept(f"it's {matches[0]['name']}", ctx)   # names the session
            return _reply('Say your PIN.', True)

        if phase == 'consent_parent':
            parents = identity.parents_named(re.sub(r"^(it's|it is|this is|i am|i'm)\s+", '', low))
            if len(parents) != 1:
                return _reply('Which parent? Say the full name.', True)
            d['parent_id'] = parents[0]['id']; d['phase'] = 'consent_pin'
            return _reply("A parent's PIN, please.", True)

        if phase == 'consent_pin':
            out = identity.verify_parent_consent(ctx, d['parent_id'], text)
            if not out['ok']:
                if 'locked' in out['message'].lower() or 'Too many' in out['message']:
                    _dialogs.pop(key, None)
                    return _reply(out['message'])
                return _reply(out['message'] + ' Try once more, or say cancel voice setup.', True)
            return _begin(key, ctx, d, anchor=None, exclude=vector)

        if phase == 'pin':
            out = identity.intercept(text, ctx)
            refreshed = identity.context({'ha_instance_id': ctx.ha_instance_id, 'satellite_id': ctx.satellite_id,
                                          'device_id': identity._observed.get(key, {}).get('device_id'),
                                          'request_id': ctx.request_id, 'observed_at': time.time()}, True)
            if out is None or refreshed.level != 'verified' or refreshed.member_id != d['member_id']:
                if out and ('locked' in out['message'].lower() or 'Too many' in out['message']):
                    _dialogs.pop(key, None)
                    return _reply(out['message'])
                return _reply((out or {}).get('message', 'Say your PIN.') + ' Try once more, or say cancel voice setup.', True)
            return _begin(key, ctx, d, anchor=vector, exclude=None)

        if phase == 'questions':
            out = fp.enrollment_turn(text, ctx, evidence, conversation_id=conversation_id)
            if out is None:
                _dialogs.pop(key, None)
                return _reply('Voice setup stopped.')
            status = out.get('status')
            if status == 'accepted' or status == 'retry' and key in fp._enrollments:
                asked = fp.ask(key); fp.expect_conversation(key, conversation_id)
                return _reply(f"{out['message']} {asked['question']}", True)
            if status == 'confirm':
                d['phase'] = 'confirm'
                return _reply(out['message'], True)
            if status == 'done':
                return _finish_or_activate(key, d, out['message'])
            _dialogs.pop(key, None)
            return _reply(out['message'])

        if phase == 'confirm':
            if low in YES:
                out = fp.confirm(key, True)
                return _finish_or_activate(key, d, out['message']) if out['status'] == 'done' else _reply(out['message'])
            if low in NO:
                _dialogs.pop(key, None)
                return _reply(fp.confirm(key, False)['message'])
            return _reply('Say yes or no.', True)

        if phase == 'activate':
            _dialogs.pop(key, None)
            if low in YES:
                try:
                    identity.set_recognition(key[0], key[1], True)
                    return _reply('Voice recognition is on here.')
                except ValueError as error:
                    return _reply(str(error))
            return _reply('Left off. A parent can turn it on later.')

        if phase == 'check_pin':
            out = identity.intercept(text, ctx)
            refreshed = identity.context({'ha_instance_id': ctx.ha_instance_id, 'satellite_id': ctx.satellite_id,
                                          'device_id': identity._observed.get(key, {}).get('device_id'),
                                          'request_id': ctx.request_id, 'observed_at': time.time()}, True)
            if out is None or refreshed.level != 'verified':
                return _reply((out or {}).get('message', 'Say your PIN.') + ' Or say cancel voice setup.', True)
            d.update(member_id=refreshed.member_id, anchor=vector, phase='check_answer')
            member = storage.get_member(refreshed.member_id) or {}
            if member.get('role') == 'parent':
                d['parent_id'] = member['id']
            return _reply(fp.CHECK_QUESTION, True)

        if phase == 'check_answer':
            out = fp.check(key, d['member_id'], evidence, d.get('anchor'))
            if out['status'] == 'retry':
                return _reply(out['message'] + ' ' + fp.CHECK_QUESTION, True)
            if out['status'] == 'checked':
                return _finish_or_activate(key, d, out['message'])
            d.update(phase='check_offer', last_evidence=evidence)
            return _reply(out['message'] + ' Shall I set up your voice here now? Say yes.', True)

        if phase == 'check_offer':
            if low not in YES:
                _dialogs.pop(key, None)
                return _reply('Alright. Your phone voice stays off here.')
            reply = _begin(key, ctx, d, anchor=d.get('anchor'), exclude=None)
            asked_token = (fp._enrollments.get(key) or {}).get('awaiting', {}).get('token')
            first = fp.answer(key, d.get('last_evidence'), token=asked_token, conversation_id=None)
            if first['status'] == 'accepted':
                asked = fp.ask(key); fp.expect_conversation(key, conversation_id)
                return _reply(f"Keeping that answer as the first sample. {asked['question']}", True)
            return reply
    return None


def _begin(key, ctx, d, anchor, exclude):
    try:
        fp.begin(ctx, d['member_id'], d.get('parent_id') or d['member_id'], anchor=anchor, exclude=exclude)
    except ValueError as error:
        _dialogs.pop(key, None)
        return _reply(str(error))
    d['phase'] = 'questions'
    asked = fp.ask(key)
    return _reply(f"Thanks. {asked['question']}", True)


def _switch(key, ctx, on, name):
    """'turn on voice recognition for Lily here': a parent's act, PIN-verified."""
    if ctx.level != 'verified' or (storage.get_member(ctx.member_id) or {}).get('role') != 'parent':
        _dialogs[key] = {'phase': 'switch_pin', 'on': on, 'name': name, 'expires_at': time.time() + EXPIRY}
        return _reply("A parent's PIN, please. " + identity.challenge(ctx), True)
    return _apply_switch(key, on)


def _apply_switch(key, on):
    _dialogs.pop(key, None)
    try:
        identity.set_recognition(key[0], key[1], on)
        return _reply('Voice recognition is on here.' if on else 'Voice recognition is off here.')
    except ValueError as error:
        return _reply(str(error))
```

Add the `switch_pin` phase inside `intercept` (next to `check_pin`): run `identity.intercept(text, ctx)`, refresh the context, and when `refreshed.level == 'verified'` and the member's role is `parent`, return `_apply_switch(key, d['on'])`; otherwise reply with the intercept's message and `continue` true.

In `main.py` `converse_ha_assist.perform()` replace the three lines at :3852-3855:

```python
        enrollment = voice_fingerprint.enrollment_turn(req.text, ctx, evidence)
        if enrollment:
            return _voice_response(enrollment['message'], req.language)
```

with:

```python
        from services import voice_setup
        setup = voice_setup.intercept(req.text, ctx, evidence, req.conversation_id)
        if setup is not None:
            return _voice_response(setup['message'], req.language, setup['continue'])
```

(`voice_setup.intercept` calls `enrollment_turn` itself during the `questions` phase, so nothing during an enrollment reaches `voice_identity.intercept`, `voice_approval.intercept` or the agent.)

- [ ] **Step 4: Run** — `python tests/test_voice_setup.py`, `python tests/test_voice_enrollment.py`, `python tests/test_voice_identity.py`, `python tests/test_voice_fingerprint.py` — Expected: pass. Also `python tests/test_auth.py` (route table unchanged) — pass.

- [ ] **Step 5: Commit**

```bash
git add chauffeur/services/voice_setup.py chauffeur/main.py chauffeur/tests/test_voice_setup.py
git commit -m "feat(voice): set up, check and switch on your voice by talking to Argyle on a satellite, one conversation via continue_conversation (vX.Y.Z)"
```

---

### Task 4: The HA continuation proof

**Files:**
- Modify: `chauffeur/tests/test_voice_recognition_live.py` (append one scenario) or, if that file needs a live HA, create `chauffeur/tests/test_voice_setup_component.py` that imports the component module directly.
- Read only: `homeassistant/custom_components/chauffeur_conversation/conversation.py:60-112`, `pipeline_bridge.py`.

**Interfaces:**
- Consumes: the component's `async_process` and `pipeline_bridge.observation`.
- Produces: nothing new; a pinned assertion that each continued turn posts its own `request_id`/`run_id` and carries the same `conversation_id`.

- [ ] **Step 1: Write the test**

```python
def test_each_continued_turn_posts_its_own_run_and_the_same_conversation(self):
    """Two utterances in one continued conversation must reach /api/v2/converse as two
    requests with distinct run/utterance ids and the same conversation_id, and the
    second must carry continue_conversation from the first reply."""
    posted = []

    class FakeResp:
        status = 200
        def raise_for_status(self): pass
        async def json(self): return {'continue_conversation': True, 'response': {'speech': {'plain': {'speech': 'q'}}}}

    class FakeSession:
        async def post(self, url, json=None, headers=None, timeout=None):
            posted.append(json); return FakeResp()

    agent = self.agent(session=FakeSession())          # the component's conversation entity, built as the existing live test builds it
    first = self.run(agent, text='set up my voice', conversation_id='c1', run_id='r1', utterance_id='u1')
    second = self.run(agent, text='today I walked', conversation_id='c1', run_id='r2', utterance_id='u2')
    self.assertTrue(first.continue_conversation)
    self.assertEqual([p['conversation_id'] for p in posted], ['c1', 'c1'])
    self.assertEqual([p['voice']['request_id'] for p in posted], ['u1', 'u2'])
    self.assertNotEqual(posted[0]['voice']['run_id'], posted[1]['voice']['run_id'])
```

Use the helper the existing recognition live test already has for building the entity and running it with a fake HA (`self.agent`, `self.run` or their equivalents in that file; read it before writing). If the existing file only runs against a real HA, put the test in the new file and construct `ChauffeurConversationEntity` with a stub `hass` the way `test_voice_recognition_live.py` does for its unit half.

- [ ] **Step 2: Run** — Expected: pass as-is if the component already does this (the spec expects so). If it fails because the bridge reuses an observation across turns, fix `pipeline_bridge.observation` to key on `(run_id, utterance_id)` and re-run.

- [ ] **Step 3: Commit**

```bash
git add chauffeur/tests/test_voice_setup_component.py
git commit -m "test(voice): each continued satellite turn is its own run with the same conversation id (vX.Y.Z)"
```

---

### Task 5: Phone enrollment endpoints

**Files:**
- Modify: `chauffeur/services/voice_setup.py` (phone half), `chauffeur/main.py` (after `/api/app-voice/{request_id}/speech` :4126), `chauffeur/services/auth.py` (rules next to `/api/app-voice/*`)
- Create: `chauffeur/tests/test_voice_enrollment_phone.py`

**Interfaces:**
- Consumes: Task 1 (`begin(door='phone')`, `ask`, `answer`, `cancel`, `status`), Task 2 (`verify_parent_consent`), `app_voice.personal(headers)`, `app_voice_audio.pcm(audio, content_type)`, `fp.extract(audio, metadata, enrollment=True)` → `(vector, seconds)`, `app_voice_audio.speak(text)`.
- Produces (`voice_setup`):
  - `phone_begin(member, parent_pin=None) -> dict` → `{'enrollment_id', 'step', 'question', 'token', 'total': 5}`; raises `PermissionError` (child without parent consent / wrong parent PIN) or `ValueError` (busy, model not ready).
  - `phone_answer(member, enrollment_id, token, audio, content_type) -> dict` → `{'status', 'message', 'step', 'question', 'token'}` (next question and token on `accepted`/`retry`; no question on `done`/`ended`).
  - `phone_cancel(member) -> dict`.
  - `phone_state(member) -> dict` → `{'enrolling': bool, 'step', 'question', 'profiles': [{'provenance', 'checks'}...]}`.
  - Routes (SIGNED_IN tier, personal session checked in the handler): `POST /api/app-voice/enroll`, `POST /api/app-voice/enroll/{enrollment_id}/audio`, `GET /api/app-voice/enroll/{enrollment_id}/speech` (the current question as audio), `DELETE /api/app-voice/enroll`, `GET /api/app-voice/enroll`.
  - Phone key for the core is `('phone', member_id)`; a phone "ctx" is `voice_identity.VoiceContext('phone', member_id, '', '', service_revision=voice_identity._revision(), paired=True)` built inside `voice_setup`.

- [ ] **Step 1: Write the failing tests**

Create `chauffeur/tests/test_voice_enrollment_phone.py`:

```python
"""Phone enrollment: five taps through the shipped recorder, no transcript, no agent."""
import io, os, sys, tempfile, time, unittest, uuid, wave
from pathlib import Path
from unittest.mock import patch

os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_phone_enroll_')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import storage, voice_identity as voice, voice_fingerprint as fp, voice_setup, app_voice_audio
from starlette.requests import Request
from fastapi import HTTPException
import main


def vector(index=0):
    return fp.normalized([float(i == index) for i in range(256)])


def wav(seconds=8):
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(b'\x10\x00' * 16000 * seconds)
    return buf.getvalue()


class PhoneEnrollmentTests(unittest.TestCase):
    def setUp(self):
        for table in (storage.members_table, storage.member_tokens_table, storage.app_state_table,
                      storage.rate_limits_table, storage.chat_channels_table, storage.chat_messages_table):
            table.truncate()
        fp._enrollments.clear(); fp._save([]); voice_setup._dialogs.clear()
        storage.get_settings = lambda: {'auth_enforce': False, 'calendar_ids': [], 'service_token': 'service'}
        storage.add_member({'id': 'jeff', 'name': 'Jeff', 'role': 'parent'}); storage.set_member_pin('jeff', '1234')
        storage.add_member({'id': 'lily', 'name': 'Lily', 'role': 'child'})
        self.jeff = storage.create_member_token('jeff'); self.lily = storage.create_member_token('lily')
        patch.object(fp, 'model_ready', return_value=True).start()
        self.voices = [vector(0)] * 10
        patch.object(fp, 'extract', lambda audio, metadata, enrollment=False: (self.voices.pop(0), 8.0)).start()
        patch.object(app_voice_audio, 'speak', lambda text: (b'ID3fake', 'audio/mpeg')).start()
        self.addCleanup(patch.stopall)

    def request(self, token, body=b'', content_type='audio/wav'):
        return Request({'type': 'http', 'method': 'POST', 'path': '/', 'query_string': b'',
                        'headers': [(b'x-member-token', token.encode()), (b'content-type', content_type.encode())]})

    def test_an_adult_enrolls_in_five_uploads_with_no_transcript_and_no_agent(self):
        start = main.phone_enroll_start({}, self.request(self.jeff))
        self.assertEqual((start['step'], start['total']), (1, 5)); self.assertEqual(start['question'], fp.QUESTIONS[0])
        token = start['token']
        with patch.object(main, 'process_agent_request', side_effect=AssertionError('agent ran')), \
                patch.object(app_voice_audio, 'transcribe', side_effect=AssertionError('transcribed')):
            for step in range(5):
                out = voice_setup.phone_answer(storage.get_member('jeff'), start['enrollment_id'], token, wav(), 'audio/wav')
                if step < 4:
                    self.assertEqual(out['status'], 'accepted', out); self.assertEqual(out['step'], step + 2); token = out['token']
        self.assertEqual(out['status'], 'done'); self.assertIn('check my voice', out['message'])
        row = fp.profiles()[0]
        self.assertEqual((row['member_id'], row['provenance']), ('jeff', 'phone'))
        self.assertEqual(storage.chat_messages_table.all(), [], 'an enrollment answer landed in chat')

    def test_a_reused_step_token_is_refused(self):
        start = main.phone_enroll_start({}, self.request(self.jeff))
        first = voice_setup.phone_answer(storage.get_member('jeff'), start['enrollment_id'], start['token'], wav(), 'audio/wav')
        self.assertEqual(first['status'], 'accepted')
        again = voice_setup.phone_answer(storage.get_member('jeff'), start['enrollment_id'], start['token'], wav(), 'audio/wav')
        self.assertEqual(again['status'], 'retry'); self.assertEqual(again['token'], first['token'])
        self.assertEqual(fp._enrollments[('phone', 'jeff')]['step'], 1)

    def test_a_child_needs_a_parents_pin_entered_on_their_screen(self):
        with self.assertRaises(HTTPException) as caught:
            main.phone_enroll_start({}, self.request(self.lily))
        self.assertEqual(caught.exception.status_code, 403)
        with self.assertRaises(HTTPException):
            main.phone_enroll_start({'parent_id': 'jeff', 'parent_pin': '0000'}, self.request(self.lily))
        start = main.phone_enroll_start({'parent_id': 'jeff', 'parent_pin': '1234'}, self.request(self.lily))
        self.assertEqual(start['step'], 1)
        self.assertEqual(fp._enrollments[('phone', 'lily')]['consent_actor'], 'jeff')
        self.assertEqual(voice._sessions, {}, 'a parent session was created by phone consent')

    def test_a_short_answer_asks_again_and_a_different_voice_ends_it(self):
        start = main.phone_enroll_start({}, self.request(self.jeff))
        with patch.object(fp, 'extract', lambda *a, **k: (vector(0), 2.0)):
            out = voice_setup.phone_answer(storage.get_member('jeff'), start['enrollment_id'], start['token'], wav(2), 'audio/wav')
        self.assertEqual(out['status'], 'retry'); self.assertIn('longer', out['message'].lower()); self.assertEqual(out['step'], 1)
        out = voice_setup.phone_answer(storage.get_member('jeff'), start['enrollment_id'], out['token'], wav(), 'audio/wav')
        self.assertEqual(out['status'], 'accepted')
        self.voices[0] = vector(7)
        out = voice_setup.phone_answer(storage.get_member('jeff'), start['enrollment_id'], out['token'], wav(), 'audio/wav')
        self.assertEqual(out['status'], 'ended')

    def test_the_question_can_be_heard_and_the_flow_cancelled(self):
        start = main.phone_enroll_start({}, self.request(self.jeff))
        res = main.phone_enroll_speech(start['enrollment_id'], self.request(self.jeff))
        self.assertEqual(res.media_type, 'audio/mpeg')
        self.assertEqual(main.phone_enroll_cancel(self.request(self.jeff))['status'], 'ended')
        self.assertNotIn(('phone', 'jeff'), fp._enrollments)

    def test_only_a_personal_session_may_enroll(self):
        house = storage.create_member_token('jeff', house_session=True)
        with self.assertRaises(HTTPException):
            main.phone_enroll_start({}, self.request(house))

    def test_the_routes_are_classified(self):
        from services import auth
        for m, p in (('POST', '/api/app-voice/enroll'), ('GET', '/api/app-voice/enroll'), ('DELETE', '/api/app-voice/enroll'),
                     ('POST', '/api/app-voice/enroll/{enrollment_id}/audio'), ('GET', '/api/app-voice/enroll/{enrollment_id}/speech')):
            self.assertEqual(auth.resolve(m, p), auth.SIGNED_IN, f'{m} {p}')


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run to verify failure** — `python tests/test_voice_enrollment_phone.py` — Expected: AttributeError on `main.phone_enroll_start` / `voice_setup.phone_answer`.

- [ ] **Step 3: Implement**

Append to `services/voice_setup.py`:

```python
def _phone_ctx(member_id):
    return identity.VoiceContext('phone', member_id, '', '', service_revision=identity._revision(), paired=True)


def phone_begin(member, parent_id=None, parent_pin=None):
    consent_actor = member['id']
    if member.get('role') == 'child':
        if not parent_id or not parent_pin:
            raise PermissionError("A parent's PIN is needed to set up a child's voice.")
        out = identity.verify_parent_consent(_phone_ctx(member['id']), parent_id, f'my pin is {parent_pin}')
        if not out['ok']:
            raise PermissionError(out['message'])
        consent_actor = parent_id
    fp.begin(_phone_ctx(member['id']), member['id'], consent_actor, door='phone')
    asked = fp.ask(('phone', member['id']))
    return {**asked, 'total': len(fp.QUESTIONS)}


def phone_answer(member, enrollment_id, token, audio, content_type):
    from services import app_voice_audio
    key = ('phone', member['id'])
    pending = fp._enrollments.get(key)
    if not pending or pending['id'] != enrollment_id:
        raise ValueError('That voice setup has ended. Start again.')
    try:
        pcm = app_voice_audio.pcm(audio, content_type)
        vec, seconds = fp.extract(pcm, {'sample_rate': 16000}, enrollment=True)
        evidence = {'vector': vec, 'seconds': seconds, 'enrollment_id': enrollment_id}
    except ValueError:
        evidence = {'vector': None, 'seconds': 0, 'enrollment_id': enrollment_id}
    out = fp.answer(key, evidence, token=token)
    if out['status'] in ('accepted', 'retry') and key in fp._enrollments:
        if fp._enrollments[key].get('awaiting') is None:
            asked = fp.ask(key)
        else:   # a stale token: the current question and its live token stand
            cur = fp._enrollments[key]['awaiting']
            asked = {'question': fp.QUESTIONS[cur['step']], 'token': cur['token'], 'step': cur['step'] + 1}
        return {**out, 'question': asked['question'], 'token': asked['token'], 'step': asked['step']}
    return out


def phone_cancel(member):
    return fp.cancel(('phone', member['id']))


def phone_state(member):
    pending = fp._enrollments.get(('phone', member['id']))
    rows = [r for r in fp.profiles() if r['member_id'] == member['id']]
    return {'enrolling': bool(pending), 'step': (pending['step'] + 1) if pending else 0,
            'question': fp.QUESTIONS[pending['step']] if pending and pending['step'] < len(fp.QUESTIONS) else '',
            'profiles': [{'provenance': r.get('provenance', 'satellite'), 'checks': r.get('checks') if isinstance(r.get('checks'), dict) else {}} for r in rows]}
```

Add to `main.py` after `phone_voice_speech`:

```python
def _phone_enroll_member(request):
    from services import app_voice, auth
    if auth.arrived_via_ingress(request.headers):
        raise HTTPException(status_code=403, detail='Open the secure Chauffeur app outside Home Assistant ingress for voice.')
    try:
        member, _token = app_voice.personal(request.headers)
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from None
    return member


@app.post('/api/app-voice/enroll')
def phone_enroll_start(payload: Dict[str, Any], request: Request):
    """Set up my voice on the phone: five answers through the shipped recorder.
    A child's screen sends a parent's PIN, verified by the consent verifier."""
    from services import voice_setup
    member = _phone_enroll_member(request)
    try:
        return voice_setup.phone_begin(member, payload.get('parent_id'), payload.get('parent_pin'))
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from None
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None


@app.get('/api/app-voice/enroll')
def phone_enroll_state(request: Request):
    from services import voice_setup
    return voice_setup.phone_state(_phone_enroll_member(request))


@app.delete('/api/app-voice/enroll')
def phone_enroll_cancel(request: Request):
    from services import voice_setup
    return voice_setup.phone_cancel(_phone_enroll_member(request))


@app.post('/api/app-voice/enroll/{enrollment_id}/audio')
async def phone_enroll_audio(enrollment_id: str, request: Request):
    from services import voice_setup, app_voice_audio
    from starlette.concurrency import run_in_threadpool
    member = _phone_enroll_member(request)
    token = request.headers.get('x-voice-step-token', '') or request.query_params.get('token', '')
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > app_voice_audio.MAX_UPLOAD:
            raise HTTPException(status_code=413, detail='The recording exceeded its size limit.')
        chunks.append(chunk)
    try:
        return await run_in_threadpool(voice_setup.phone_answer, member, enrollment_id, token,
                                       b''.join(chunks), request.headers.get('content-type', ''))
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None


@app.get('/api/app-voice/enroll/{enrollment_id}/speech')
def phone_enroll_speech(enrollment_id: str, request: Request):
    """The current question, spoken by the household's Argyle voice."""
    from services import voice_fingerprint, app_voice_audio
    member = _phone_enroll_member(request)
    pending = voice_fingerprint._enrollments.get(('phone', member['id']))
    if not pending or pending['id'] != enrollment_id:
        raise HTTPException(status_code=409, detail='That voice setup has ended.')
    try:
        audio, kind = app_voice_audio.speak(voice_fingerprint.QUESTIONS[pending['step']])
        return Response(content=audio, media_type=kind, headers={'Cache-Control': 'no-store'})
    except ValueError as error:
        raise HTTPException(status_code=503, detail=str(error)) from None
```

In `services/auth.py`, next to the existing `/api/app-voice/*` rule, add before it (specific before prefix):

```python
    ('POST', '/api/app-voice/enroll', SIGNED_IN, None),
    ('GET', '/api/app-voice/enroll', SIGNED_IN, None),
    ('DELETE', '/api/app-voice/enroll', SIGNED_IN, None),
    ('POST', '/api/app-voice/enroll/{enrollment_id}/audio', SIGNED_IN, None),
    ('GET', '/api/app-voice/enroll/{enrollment_id}/speech', SIGNED_IN, None),
```

(Check how the existing `/api/app-voice/*` rule is tiered; mirror it exactly if it is not `SIGNED_IN`, and adjust the test's expected tier to match. The handler's `app_voice.personal` check is what refuses wall and house sessions either way.)

- [ ] **Step 4: Run** — `python tests/test_voice_enrollment_phone.py`, `python tests/test_app_voice.py`, `python tests/test_auth.py` — Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add chauffeur/services/voice_setup.py chauffeur/main.py chauffeur/services/auth.py chauffeur/tests/test_voice_enrollment_phone.py
git commit -m "feat(voice): phone enrollment endpoints - five uploads through the recorder, parent PIN consent on a child's screen, never transcribed, never the agent (vX.Y.Z)"
```

---

### Task 6: The phone screen

**Files:**
- Modify: `chauffeur/static/pwa_shell.js` (`pwaOpenProfile` :167-190), `chauffeur/static/app_voice.js` (add `ChauffeurVoiceSetup`), `chauffeur/templates/app.html` (a `<dialog id="pwa-voice-setup">` next to `#pwa-profile`)
- Test: `chauffeur/tests/test_voice_setup_pwa.py` (node run of `app_voice.js` with a fake DOM, the way `test_house_return.py` runs `house_return.js`)

**Interfaces:**
- Consumes: Task 5 routes; `memberToken()`, `showGlobalAlert`, `promptConfirm`, `promptForPin` from `app.html`; the recorder pattern in `ChauffeurPhoneVoice.capture`.
- Produces: `window.ChauffeurVoiceSetup = { open(), start(parentId, parentPin), record(), done(), cancel(), state }`, a dialog with: intro text, Start/Cancel, "1 of 5", the question, Record/Done, status line, final buttons (Try talking to Argyle, Done); on the profile sheet: `Set up my voice`, `Set up again`, `Turn recognition off for me`, `Delete my voice` (the last two call the existing `/api/voice/recognition` routes where they exist for a member's own profile; if only the parent-gated delete exists, hide Delete for non-parents and say so in the plan's notes).

- [ ] **Step 1: Write the failing test** (`test_voice_setup_pwa.py`): load `static/app_voice.js` under node with a fake `document`, `navigator.mediaDevices`, `MediaRecorder`, `fetch`; assert that `ChauffeurVoiceSetup.start()` posts to `api/app-voice/enroll`, that a recorded blob posts to `api/app-voice/enroll/<id>/audio` with the `X-Voice-Step-Token` header equal to the token the start returned, that an `accepted` reply advances the shown step text to `2 of 5` and uses the new token, that a `retry` keeps `1 of 5`, and that `done` shows the finish buttons and stops the recorder. Follow `tests/test_house_return.py` for the harness shape.

- [ ] **Step 2: Run to verify failure** — Expected: `ChauffeurVoiceSetup` undefined.

- [ ] **Step 3: Implement** — in `app_voice.js` add a second object `ChauffeurVoiceSetup` that reuses the format detection and the `MediaRecorder` setup from `capture()` (extract a shared `recordOnce(onBlob)` helper used by both), keeps `state = {enrollmentId, token, step, total, question, phase}`, reads the question aloud by fetching `api/app-voice/enroll/<id>/speech` into an `Audio` object and only enabling Record after `onended`, and sends `X-Voice-Step-Token`. In `pwa_shell.js` add the profile actions. In `app.html` add the dialog markup with `promptConfirm` on Delete. Run `python tools/build_tailwind.py`.

- [ ] **Step 4: Run** — the node test, `python tests/test_app_voice.py`, and `python tests/test_settings_registry.py` (no new settings, must stay green) — Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add chauffeur/static/app_voice.js chauffeur/static/pwa_shell.js chauffeur/templates/app.html chauffeur/static/tailwind-app.css chauffeur/tests/test_voice_setup_pwa.py
git commit -m "feat(voice): Set up my voice on the phone - five taps, the question read aloud, parent PIN for a child (vX.Y.Z)"
```

---

### Task 7: Config status words and the capabilities record

**Files:**
- Modify: `chauffeur/templates/config.html` (the voice identity section :1124-1240: the enrollment rows read `question` instead of `prompt`; per profile show `provenance` and each check state in words), `chauffeur/system_capabilities.md`
- Test: `chauffeur/tests/test_voice_enrollment.py` (append one source assertion that `config.html` no longer references `pending.prompt` and does reference `profile.checks`)

- [ ] **Step 1: Write the test**

```python
class ConfigWordsTests(unittest.TestCase):
    def test_config_reads_questions_and_check_states(self):
        src = open(Path(__file__).resolve().parents[1] / 'templates' / 'config.html', encoding='utf-8').read()
        self.assertNotIn('pending.prompt', src)
        self.assertIn('pending.question', src)
        self.assertIn('profile.checks', src)
        self.assertIn('does not match', src.lower())
```

- [ ] **Step 2: Run** — Expected: fails on `pending.prompt`.

- [ ] **Step 3: Implement** — in the pending-enrollment row replace the "read this phrase, then refresh" copy with the question and "Answer out loud; Argyle keeps listening between questions." In the profiles list add, per satellite key in `profile.checks`, "checked here" or "your phone voice does not match this microphone; set up your voice there" and the provenance word. Add the capabilities entry describing the two doors, the admission rule, consent, check, activation and the hand paths, marked NOT device-verified. Run `python tools/build_tailwind.py`.

- [ ] **Step 4: Run** — `python tests/test_voice_enrollment.py`, `python tests/test_settings_registry.py` — Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add chauffeur/templates/config.html chauffeur/static/tailwind.css chauffeur/system_capabilities.md chauffeur/tests/test_voice_enrollment.py
git commit -m "docs(voice): Config shows questions and per-satellite check states; capabilities record the enrollment doors (vX.Y.Z)"
```

---

## Self-review notes

- Spec coverage: core (Task 1), consent and switch (Task 2), satellite flow and continuation (Tasks 3 and 4), phone flow (Tasks 5 and 6), check and activation (Task 3), storage fields and archival (Task 1), surfaces (Tasks 6 and 7), identity and safety (Tasks 1, 2, 3, 5). Device acceptance is the user's act after Task 7.
- Type consistency: `begin(ctx, member_id, consent_actor, *, door, anchor, exclude)`, `ask(key)`, `answer(key, evidence, token, conversation_id)`, `confirm(key, yes)`, `cancel(key)`, `check(key, member_id, evidence, anchor)`, `checked_on(row, key)`, `on_member_status(member_id)`, `verify_parent_consent(ctx, parent_id, text, language)`, `parents_named(name)`, `set_recognition(installation, satellite, on)`, `voice_setup.intercept(text, ctx, evidence, conversation_id)`, `phone_begin(member, parent_id, parent_pin)`, `phone_answer(member, enrollment_id, token, audio, content_type)`, `phone_cancel(member)`, `phone_state(member)` are used with these shapes throughout.
- Review Focus items 1 to 5 each have a named test in Tasks 1, 1, 3, 2 and 5.
- Known judgment calls for the implementer: the `who` phase names the session through `identity.intercept("it's <name>")` so the following PIN turn verifies that member; the `check_offer` phase re-admits the check's evidence as sample 1 by reading the fresh token straight from the enrollment, which is the one place the dialog reaches into `fp._enrollments`.
