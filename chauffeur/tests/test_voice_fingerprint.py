"""Speaker recognition, exact observation binding and fail-closed continuity."""
import asyncio
from dataclasses import replace
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch

os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_fingerprint_')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import storage, voice_identity as voice, voice_fingerprint as fp


def vector(index=0):
    return [float(i == index) for i in range(256)]


class FingerprintTests(unittest.TestCase):
    def setUp(self):
        for table in (storage.members_table, storage.member_tokens_table, storage.app_state_table,
                      storage.rate_limits_table, storage.conversations_table):
            table.truncate()
        voice._sessions.clear(); voice._observed.clear(); voice._requests.clear()
        fp._observations.clear(); fp._enrollments.clear(); fp._last.clear()
        fp._save([])
        self.settings = {'service_token': 'service'}
        self.settings_patch = patch.object(storage, 'get_settings', return_value=self.settings)
        self.settings_patch.start(); self.addCleanup(self.settings_patch.stop)
        storage.add_member({'id': 'jeff', 'name': 'Jeff', 'role': 'parent'})
        storage.add_member({'id': 'alex', 'name': 'Alex', 'role': 'child'})
        storage.set_member_pin('jeff', '1234')
        self.satellite = {'ha_instance_id': 'ha', 'satellite_id': 'assist_satellite.kitchen',
                          'device_id': 'device', 'enabled': True}
        voice.configure(True, [self.satellite], approvals_enabled=True)

    def ctx(self, **changes):
        import uuid
        metadata = {'ha_instance_id': 'ha', 'satellite_id': 'assist_satellite.kitchen',
                    'device_id': 'device', 'request_id': uuid.uuid4().hex, 'observed_at': time.time(), **changes}
        return voice.context(metadata, True)

    def profile(self, member='jeff', index=0, **changes):
        return {'member_id': member, 'key': ['ha', 'assist_satellite.kitchen'], 'vector': vector(index),
                'revision': fp.REVISION, 'consent_actor': 'jeff', 'created_at': time.time(),
                'checks': 2, 'calibrated': True, **changes}

    def enable(self, profiles=None):
        fp._save(profiles or [self.profile()])
        voice.configure(True, [{**self.satellite, 'recognition_enabled': True}], approvals_enabled=True)

    def evidence(self, index=0, seconds=6):
        pending = fp._enrollments.get(('ha', 'assist_satellite.kitchen')) or {}
        return {'vector': vector(index), 'seconds': seconds, 'enrollment_id': pending.get('id')}

    def test_recognition_requires_checked_enrollment(self):
        with self.assertRaises(ValueError):
            voice.configure(True, [{**self.satellite, 'recognition_enabled': True}])
        fp._save([self.profile(calibrated=False)])
        with self.assertRaises(ValueError):
            voice.configure(True, [{**self.satellite, 'recognition_enabled': True}])

    def test_recognition_names_but_does_not_verify_or_slide(self):
        self.enable()
        ctx = fp.apply(self.ctx(), self.evidence())
        self.assertEqual((ctx.level, ctx.member_id), ('named', 'jeff'))
        self.assertIsNone(ctx.verified_member())
        self.assertEqual(ctx.greeting, 'Hi Jeff.')
        again = fp.apply(self.ctx(), self.evidence())
        self.assertEqual(again.generation, ctx.generation)
        self.assertEqual(again.expires_at, ctx.expires_at)
        self.assertIsNone(again.greeting)

    def test_ambiguous_and_missing_keep_lens_but_clear_on_contradiction(self):
        self.enable([self.profile(), self.profile('alex', 1)])
        first = fp.apply(self.ctx(), self.evidence())
        mixed = fp.normalized([a + b for a, b in zip(vector(), vector(1))])
        self.assertEqual(fp.apply(self.ctx(), {'vector': mixed, 'seconds': 6}).member_id, 'jeff')
        self.assertEqual(fp.apply(self.ctx(), self.evidence(2)).level, 'unknown')
        self.assertNotEqual(fp.apply(self.ctx(), self.evidence(1)).generation, first.generation)
        self.assertEqual(fp.apply(self.ctx(), None).member_id, 'alex')

    def test_pin_anchor_and_new_speaker_clear_readback(self):
        self.enable([self.profile(), self.profile('alex', 1)])
        ctx = fp.apply(self.ctx(), self.evidence())
        self.assertIn('Verified', voice.intercept('My PIN is 1234', ctx)['message'])
        original = self.ctx()
        row = voice._sessions[('ha', 'assist_satellite.kitchen')]
        row['readback'] = {'secret': 'old ask'}
        same = fp.apply(self.ctx(), self.evidence())
        self.assertEqual(same.verified_member()['id'], 'jeff')
        self.assertEqual(same.expires_at, original.expires_at)
        other = fp.apply(self.ctx(), self.evidence(1))
        self.assertEqual((other.level, other.member_id), ('named', 'alex'))
        self.assertIsNone(other.verified_member())
        self.assertNotIn('readback', voice._sessions[('ha', 'assist_satellite.kitchen')])

    def test_missing_evidence_keeps_verified_session_and_readback(self):
        self.enable()
        voice.intercept('My PIN is 1234', fp.apply(self.ctx(), self.evidence()))
        ctx = self.ctx()
        row = voice._sessions[('ha', 'assist_satellite.kitchen')]
        row['readback'] = {'id': 'pending'}
        after = fp.apply(self.ctx(), None)
        self.assertEqual(after.verified_member()['id'], 'jeff')
        self.assertEqual(after.generation, ctx.generation)
        self.assertEqual(after.expires_at, ctx.expires_at)
        self.assertEqual(row['readback']['id'], 'pending')

    def test_short_or_uncertain_followup_keeps_identity_and_original_expiry(self):
        self.enable([self.profile(), self.profile('alex', 1)])
        ctx = fp.apply(self.ctx(), self.evidence())
        voice.intercept('My PIN is 1234', ctx)
        ctx = self.ctx()
        for evidence in (self.evidence(1, seconds=.5), {'vector': fp.normalized([.5 if i < 2 else 0 for i in range(256)]), 'seconds': 6}, None):
            result = fp.apply(self.ctx(), evidence)
            self.assertEqual(result.member_id, 'jeff')
            self.assertEqual(result.level, 'verified')
            self.assertEqual(result.expires_at, ctx.expires_at)
        with patch.object(voice.time, 'time', return_value=ctx.expires_at + 1):
            self.assertEqual(fp.apply(self.ctx(), None).level, 'unknown')

    def test_correct_pin_without_fingerprint_verifies_without_rate_penalty(self):
        self.enable()
        voice.intercept("It's Jeff", self.ctx())
        for _ in range(8):
            result = voice.intercept('My PIN is 1234', self.ctx())
            self.assertIn('Verified', result['message'])
            self.assertEqual(self.ctx().level, 'verified')
        self.assertNotIn('speaker_anchor', voice._sessions[('ha', 'assist_satellite.kitchen')])
        self.assertEqual(storage.get_app_state('voice_auth_history')[-1]['outcome'], 'verified')

    def test_correction_suppresses_automatic_name_in_session(self):
        self.enable()
        voice.intercept("That's not me", fp.apply(self.ctx(), self.evidence()))
        self.assertEqual(fp.apply(self.ctx(), self.evidence()).level, 'unknown')

    def test_disable_restores_pin_only_and_revokes_anchor(self):
        self.enable()
        voice.intercept('My PIN is 1234', fp.apply(self.ctx(), self.evidence()))
        voice.configure(True, [self.satellite])
        self.assertEqual(self.ctx().level, 'unknown')
        voice.intercept("It's Jeff", self.ctx())
        self.assertIn('Verified', voice.intercept('My PIN is 1234', self.ctx())['message'])

    def put_observation(self, ctx, **changes):
        row = {'key': (ctx.ha_instance_id, ctx.satellite_id, 'device', 'run', ctx.request_id),
               'revision': ctx.service_revision, 'vector': vector(), 'seconds': 6,
               'expires': time.time() + 60, **changes}
        fp._observations['opaque'] = row
        return {'observation_id': 'opaque', 'device_id': 'device', 'run_id': 'run', 'utterance_id': ctx.request_id}

    def test_exact_correlation_one_use_and_retry_cache(self):
        ctx = self.ctx(); metadata = self.put_observation(ctx)
        for changed in ({'device_id': 'other'}, {'run_id': 'other'}, {'utterance_id': 'other'}):
            self.assertIsNone(fp.consume(ctx, {**metadata, **changed}))
        self.assertIsNone(fp.consume(replace(ctx, satellite_id='assist_satellite.other'), metadata))
        result = voice.once(ctx, lambda: fp.consume(ctx, metadata))
        self.assertEqual(result['vector'], vector())
        self.assertEqual(voice.once(ctx, lambda: self.fail('retried inference')), result)
        self.assertIsNone(fp.consume(ctx, metadata))

    def test_expiry_and_service_rotation_reject_observations(self):
        ctx = self.ctx(); metadata = self.put_observation(ctx, expires=time.time() - 1)
        self.assertIsNone(fp.consume(ctx, metadata))
        metadata = self.put_observation(ctx, revision='revoked')
        self.assertIsNone(fp.consume(ctx, metadata))
        self.assertIsNone(fp.consume(replace(ctx, paired=False), metadata))

    def test_late_result_never_identifies_another_turn(self):
        from concurrent.futures import Future
        self.enable()
        ctx = self.ctx(); pending = Future()
        metadata = self.put_observation(ctx, future=pending)
        started = time.monotonic()
        self.assertIsNone(fp.consume(ctx, metadata))
        self.assertLess(time.monotonic() - started, .8)
        pending.set_result((vector(), 6))
        self.assertIsNone(fp.consume(ctx, metadata))
        self.assertIsNone(fp.consume(self.ctx(), metadata))

    def test_unsupported_short_silent_and_clipped_audio_refuse_before_model(self):
        import numpy as np
        metadata = {'codec': 'pcm', 'format': 'wav', 'bit_rate': 16, 'channel': 1, 'sample_rate': 16000}
        for audio, changes in ((b'\0\0' * 32000, {}), (b'\0\0' * 100, {}),
                               ((np.ones(32000) * 32767).astype('<i2').tobytes(), {}),
                               (b'\0\0' * 32000, {'codec': 'opus'})):
            with patch.object(fp, '_engine', side_effect=AssertionError('invalid audio reached model')):
                with self.assertRaises(ValueError): fp.extract(audio, {**metadata, **changes})

    def test_short_approval_audio_and_long_question_use_one_model_pass(self):
        import numpy as np
        metadata = {'codec': 'pcm', 'format': 'wav', 'bit_rate': 16, 'channel': 1, 'sample_rate': 16000}
        calls = []
        stream = types.SimpleNamespace(accept_waveform=lambda **kwargs: None, input_finished=lambda: None)
        engine = types.SimpleNamespace(create_stream=lambda: stream, is_ready=lambda s: True,
                                       compute=lambda s: (calls.append(1) or vector()))
        for seconds in (.5, 6):
            t = np.arange(int(seconds * 16000)) / 16000
            audio = (.05 * np.sin(2 * np.pi * 150 * t) * 32768).astype('<i2').tobytes()
            calls.clear()
            with patch.object(fp, '_engine', return_value=engine):
                result, voiced = fp.extract(audio, metadata)
            self.assertEqual(result, vector())
            self.assertEqual(len(calls), 1)
            self.assertGreater(voiced, .3)

        calls.clear()
        with patch.object(fp, '_engine', return_value=engine):
            fp.extract(audio, metadata, enrollment=True)
        self.assertEqual(len(calls), 3)  # split-speaker checks belong to explicit enrollment

    def test_worker_is_bounded_and_audio_is_not_persisted(self):
        self.enable()
        ctx = self.ctx()
        metadata = {'run_id': 'run', 'utterance_id': ctx.request_id, 'device_id': 'device'}
        with patch.object(fp, 'extract', return_value=(vector(), 6)):
            result = asyncio.run(fp.observe(b'private audio', metadata, ctx))
            fp._observations[result['observation_id']]['future'].result(timeout=2)
        self.assertIn(result['observation_id'], fp._observations)
        self.assertNotIn('private audio', repr(fp._observations))
        self.assertFalse((fp.root() / 'audio').exists())
        fp._slot.acquire()
        try:
            with self.assertRaisesRegex(ValueError, 'busy'):
                asyncio.run(fp.observe(b'private audio', metadata, ctx))
        finally:
            fp._slot.release()

    def test_worker_failure_releases_slot(self):
        self.enable()
        ctx = self.ctx()
        with patch.object(fp, 'extract', side_effect=ValueError('short')):
            metadata = {'run_id': 'run', 'utterance_id': ctx.request_id, 'device_id': 'device'}
            result = asyncio.run(fp.observe(b'audio', metadata, ctx))
            self.assertIsNone(fp.consume(ctx, {**metadata, **result}))
        self.assertTrue(fp._slot.acquire(False)); fp._slot.release()

    def test_three_training_two_held_out_samples_and_no_transcript_storage(self):
        with patch.object(fp, 'model_ready', return_value=True):
            fp.begin(self.ctx(), 'jeff', 'jeff')
        self.assertIn('Voice setup', fp.enrollment_turn('ordinary request', self.ctx(), self.evidence())['message'])
        for index, prompt in enumerate(fp.PROMPTS):
            result = fp.enrollment_turn(prompt, self.ctx(), self.evidence())
            if index < 4:
                self.assertEqual(fp.status()['enrollments'][0]['step'], index + 2)
        self.assertIn('saved', result['message'])
        public = fp.status()
        self.assertTrue(public['profiles'][0]['calibrated'])
        self.assertEqual(public['profiles'][0]['checks'], 2)
        self.assertNotIn('vector', json.dumps(public))
        self.assertNotIn('For my voice', (fp.root() / 'templates.json').read_text())
        self.assertEqual(len(fp.profiles()), 1)

    def test_inconsistent_or_uncorrelated_enrollment_fails(self):
        with patch.object(fp, 'model_ready', return_value=True): fp.begin(self.ctx(), 'jeff', 'jeff')
        self.assertIn('not usable', fp.enrollment_turn(fp.PROMPTS[0], self.ctx(),
                      {'vector': vector(), 'seconds': 6, 'enrollment_id': 'previous-setup'})['message'])
        self.assertIn('not usable', fp.enrollment_turn(fp.PROMPTS[0], self.ctx(), None)['message'])
        fp.enrollment_turn(fp.PROMPTS[0], self.ctx(), self.evidence())
        self.assertIn('not sound consistent', fp.enrollment_turn(fp.PROMPTS[1], self.ctx(), self.evidence(1))['message'])
        self.assertFalse(fp.profiles())

    def test_enrollment_accepts_stt_slip_and_unrelated_speech_gets_feedback(self):
        with patch.object(fp, 'model_ready', return_value=True): fp.begin(self.ctx(), 'jeff', 'jeff')
        changed = fp.PROMPTS[0].replace('many things', 'many plans')
        self.assertIn('accepted', fp.enrollment_turn(changed, self.ctx(), self.evidence())['message'])
        result = fp.enrollment_turn('What time is practice?', self.ctx(), self.evidence())
        self.assertIn('voice setup', result['message'].lower())
        self.assertEqual(fp.status()['enrollments'][0]['step'], 2)

    def test_rival_blocks_calibration(self):
        fp._save([self.profile('alex')])
        with patch.object(fp, 'model_ready', return_value=True): fp.begin(self.ctx(), 'jeff', 'jeff')
        for prompt in fp.PROMPTS[:3]: fp.enrollment_turn(prompt, self.ctx(), self.evidence())
        result = fp.enrollment_turn(fp.PROMPTS[3], self.ctx(), self.evidence())
        self.assertIn('could not distinguish', result['message'])
        self.assertEqual(len(fp.profiles()), 1)

    def test_delete_and_disabled_member_remove_templates_and_authority(self):
        self.enable()
        voice.intercept('My PIN is 1234', fp.apply(self.ctx(), self.evidence()))
        fp.delete('jeff')
        self.assertEqual(self.ctx().level, 'unknown')
        self.assertFalse(fp.profiles())
        fp._save([self.profile()])
        storage.set_member_status('jeff', 'disabled')
        self.assertFalse(fp.profiles())
        self.assertEqual(len(fp._load()), 1)
        storage.set_member_status('jeff', 'active')
        self.assertEqual(fp.profiles()[0]['member_id'], 'jeff')

    def test_delete_or_enroll_does_not_erase_other_disabled_templates(self):
        fp._save([self.profile(), self.profile('alex', 1)])
        storage.set_member_status('alex', 'disabled')
        fp.delete('jeff')
        self.assertEqual([r['member_id'] for r in fp._load()], ['alex'])
        with patch.object(fp, 'model_ready', return_value=True): fp.begin(self.ctx(), 'jeff', 'jeff')
        for prompt in fp.PROMPTS: fp.enrollment_turn(prompt, self.ctx(), self.evidence())
        self.assertEqual({r['member_id'] for r in fp._load()}, {'jeff', 'alex'})

    def test_endpoint_recognition_precedes_model_and_uses_named_history(self):
        import main
        from starlette.requests import Request
        self.enable()
        ctx = self.ctx(); metadata = self.put_observation(ctx)
        metadata.update(ha_instance_id='ha', satellite_id='assist_satellite.kitchen',
                        request_id=ctx.request_id, observed_at=time.time())
        request = Request({'type': 'http', 'method': 'POST', 'path': '/', 'query_string': b'',
                           'headers': [(b'x-service-token', b'service')]})
        with patch('services.agent_router.process_agent_request', return_value={'message': 'Two things today.'}) as agent:
            result = main.converse_ha_assist(main.ConverseRequest(text='What is on my schedule?', voice=metadata,
                                                                conversation_id='shared'), request)
        self.assertEqual(agent.call_args.kwargs['voice_context'].member_id, 'jeff')
        self.assertIsNone(agent.call_args.kwargs['voice_context'].verified_member())
        self.assertEqual(result['response']['speech']['plain']['speech'], 'Hi Jeff. Two things today.')
        self.assertNotIn('vector', json.dumps(storage.conversations_table.all()))

    def test_endpoints_require_actual_parent_or_service_credentials(self):
        import main
        from fastapi import HTTPException
        from starlette.requests import Request
        anonymous = Request({'type': 'http', 'method': 'POST', 'path': '/', 'query_string': b'', 'headers': []})
        with self.assertRaises(HTTPException): main.voice_recognition_state(anonymous)
        with self.assertRaises(HTTPException): asyncio.run(main.voice_audio_observation(anonymous))
        token = storage.create_member_token('jeff')
        parent = Request({'type': 'http', 'method': 'POST', 'path': '/', 'query_string': b'',
                          'headers': [(b'x-member-token', token.encode())]})
        with self.assertRaises(HTTPException): main.voice_recognition_enroll({'consent': False}, parent)
        with self.assertRaises(HTTPException): asyncio.run(main.voice_audio_observation(parent))


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.path = Path(__file__).resolve().parents[2] / 'homeassistant/custom_components/chauffeur_conversation'
        class Controller:
            async def async_execute(self, pipeline_input, *, validate=False):
                return await pipeline_input.process()
        self.Controller = Controller
        self.hass = types.SimpleNamespace(async_create_task=asyncio.create_task)
        self.modules = {
            'voice_test_component': types.ModuleType('voice_test_component'),
            'homeassistant.const': types.SimpleNamespace(__version__='2026.10.0'),
            'homeassistant.components.assist_pipeline.run': types.SimpleNamespace(PipelineRun=Controller),
        }
        self.modules['voice_test_component'].__path__ = [str(self.path)]
        self.module_patch = patch.dict(sys.modules, self.modules)
        self.module_patch.start(); self.addCleanup(self.module_patch.stop)
        spec = importlib.util.spec_from_file_location('voice_test_component.pipeline_bridge', self.path / 'pipeline_bridge.py')
        self.bridge = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = self.bridge; self.addCleanup(sys.modules.pop, spec.name, None)
        spec.loader.exec_module(self.bridge)
        self.assertTrue(self.bridge.install(self.hass))
        self.addCleanup(self.bridge.uninstall, self.hass)

    async def run_pipeline(self, name, process):
        controller = self.Controller()
        controller.hass, controller.id = self.hass, name
        controller.context = types.SimpleNamespace(id='context-' + name)
        pipeline_input = types.SimpleNamespace(device_id='device-' + name, satellite_id='assist_satellite.' + name,
                                               process=process)
        return await controller.async_execute(pipeline_input)

    async def test_concurrent_same_text_exact_run_and_one_use(self):
        async def process():
            run = self.bridge.current(self.hass)
            async def infer():
                await asyncio.sleep(.02 if run.run_id == 'kitchen' else .01)
                return {'observation_id': run.run_id}
            run.observation = asyncio.create_task(infer())
            user = types.SimpleNamespace(context=types.SimpleNamespace(id=run.context_id),
                                         device_id=run.device_id, satellite_id=run.satellite_id)
            observed = await self.bridge.observation(self.hass, user)
            self.assertIsNone(await self.bridge.observation(self.hass, user))
            return observed
        a, b = await asyncio.gather(self.run_pipeline('kitchen', process), self.run_pipeline('bedroom', process))
        self.assertEqual(a['observation_id'], 'kitchen')
        self.assertEqual(b['observation_id'], 'bedroom')
        self.assertNotEqual(a['utterance_id'], b['utterance_id'])
        self.assertIsNone(self.bridge.current(self.hass))

    async def test_upload_reference_survives_more_than_one_tenth_second(self):
        async def process():
            run = self.bridge.current(self.hass)
            run.observation = asyncio.create_task(asyncio.sleep(.15, result={'observation_id': 'slow-upload'}))
            user = types.SimpleNamespace(context=types.SimpleNamespace(id=run.context_id),
                                         device_id=run.device_id, satellite_id=run.satellite_id)
            self.assertEqual((await self.bridge.observation(self.hass, user))['observation_id'], 'slow-upload')
        await self.run_pipeline('kitchen', process)

    async def test_local_only_cancellation_and_late_result_discarded(self):
        saved = []
        async def process():
            run = self.bridge.current(self.hass)
            run.observation = asyncio.create_task(asyncio.sleep(60))
            saved.append(run)
        await self.run_pipeline('local', process)
        await asyncio.sleep(0)
        self.assertTrue(saved[0].observation.cancelled())
        self.assertFalse(saved[0].active)
        async def cancel():
            await process()
            raise asyncio.CancelledError
        with self.assertRaises(asyncio.CancelledError): await self.run_pipeline('cancel', cancel)
        await asyncio.sleep(0)
        self.assertTrue(saved[1].observation.cancelled())
        self.assertIsNone(self.bridge.current(self.hass))

    async def test_mismatched_context_or_satellite_never_consumes(self):
        async def process():
            run = self.bridge.current(self.hass)
            run.observation = asyncio.create_task(asyncio.sleep(0, result={'observation_id': 'correct'}))
            user = types.SimpleNamespace(context=types.SimpleNamespace(id='wrong'),
                                         device_id=run.device_id, satellite_id=run.satellite_id)
            self.assertIsNone(await self.bridge.observation(self.hass, user))
            user.context.id = run.context_id
            user.satellite_id = 'assist_satellite.wrong'
            self.assertIsNone(await self.bridge.observation(self.hass, user))
            user.satellite_id = run.satellite_id
            self.assertEqual((await self.bridge.observation(self.hass, user))['observation_id'], 'correct')
        await self.run_pipeline('kitchen', process)

    async def test_unknown_ha_version_refuses_hook(self):
        self.modules['homeassistant.const'].__version__ = '2026.11.0'
        self.assertFalse(self.bridge.install(object()))

    async def test_patch_release_accepted_and_missing_module_is_optional(self):
        self.bridge.uninstall(self.hass)
        self.modules['homeassistant.const'].__version__ = '2026.10.1'
        self.assertTrue(self.bridge.install(self.hass))
        self.bridge.uninstall(self.hass)
        with patch.dict(sys.modules, {'homeassistant.components.assist_pipeline.run': None}):
            self.assertFalse(self.bridge.install(self.hass))
        self.assertFalse(self.bridge.status(self.hass)['available'])

    async def test_uninstall_works_when_module_path_is_gone(self):
        with patch.dict(sys.modules, {'homeassistant.components.assist_pipeline.run': None}):
            self.bridge.uninstall(self.hass)
        self.assertFalse(self.bridge._owners)

    async def test_delegate_removal_unloads_saved_bridge_owner(self):
        import ast
        self.bridge.uninstall(self.hass)
        source = ast.parse((self.path / '__init__.py').read_text(encoding='utf-8'))
        functions = [n for n in source.body if isinstance(n, ast.AsyncFunctionDef)]
        code = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), *functions], type_ignores=[])
        ast.fix_missing_locations(code)
        namespace = {'__package__': 'voice_test_component', 'PLATFORMS': ['conversation', 'stt']}
        exec(compile(code, '__init__.py', 'exec'), namespace)
        from unittest.mock import AsyncMock
        self.hass.config_entries = types.SimpleNamespace(async_forward_entry_setups=AsyncMock(),
                        async_unload_platforms=AsyncMock(return_value=True), async_reload=AsyncMock())
        callbacks = []
        entry = types.SimpleNamespace(options={'stt_delegate': 'stt.cloud'}, entry_id='entry',
                    async_on_unload=callbacks.append, add_update_listener=lambda f: lambda: None)
        self.assertTrue(await namespace['async_setup_entry'](self.hass, entry))
        entry.options = {}  # HA replaces options before unloading the old entry
        self.assertTrue(await namespace['async_unload_entry'](self.hass, entry))
        for callback in callbacks: callback()
        self.assertFalse(self.bridge._owners)

    async def speech_entity(self, delegate):
        class Base: pass
        fake_stt = types.SimpleNamespace(SpeechToTextEntity=Base,
                    async_get_speech_to_text_entity=lambda hass, name: delegate,
                    DEFAULT_AUDIO_PROCESSING=object())
        fake_components = types.ModuleType('homeassistant.components')
        fake_components.stt = fake_stt
        fake_helpers = types.ModuleType('homeassistant.helpers')
        fake_helpers.instance_id = types.SimpleNamespace(async_get=None)
        more = {'homeassistant.components': fake_components, 'homeassistant.components.stt': fake_stt,
                'homeassistant.helpers': fake_helpers,
                'homeassistant.helpers.aiohttp_client': types.SimpleNamespace(async_get_clientsession=None)}
        local_patch = patch.dict(sys.modules, more)
        local_patch.start(); self.addCleanup(local_patch.stop)
        spec = importlib.util.spec_from_file_location('voice_test_component.stt', self.path / 'stt.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module; self.addCleanup(sys.modules.pop, spec.name, None)
        spec.loader.exec_module(module)
        entry = types.SimpleNamespace(entry_id='entry', options={}, data={})
        entity = module.ChauffeurSpeech(entry, 'stt.existing')
        entity.hass = self.hass
        return entity

    async def test_missing_delegate_properties_are_safe(self):
        entity = await self.speech_entity(None)
        self.assertFalse(entity.available)
        for attribute in ('supported_languages', 'supported_formats', 'supported_codecs',
                          'supported_bit_rates', 'supported_sample_rates', 'supported_channels'):
            self.assertEqual(getattr(entity, attribute), [])
        self.assertIsNotNone(entity.audio_processing)

    async def test_stt_audio_and_transcript_unchanged_and_exact_run(self):
        original = types.SimpleNamespace(text='identical transcript')
        parts = [b'\x01\x00' * 16000, b'\x02\x00' * 16000]
        observed = []
        metadata = types.SimpleNamespace(sample_rate=16000, channel=1)
        async def transcribe(actual_metadata, stream):
            self.assertIs(actual_metadata, metadata)
            received = [chunk async for chunk in stream]
            self.assertEqual(received, parts)
            return original
        delegate = types.SimpleNamespace(internal_async_process_audio_stream=transcribe)
        entity = await self.speech_entity(delegate)
        async def submit(run, actual_metadata, audio):
            observed.append((run.run_id, audio))
            return {'observation_id': run.run_id}
        entity._submit = submit
        async def process():
            async def stream():
                for chunk in parts: yield chunk
            self.assertIs(await entity.async_process_audio_stream(metadata, stream()), original)
            run = self.bridge.current(self.hass)
            user = types.SimpleNamespace(context=types.SimpleNamespace(id=run.context_id),
                                         device_id=run.device_id, satellite_id=run.satellite_id)
            return await self.bridge.observation(self.hass, user)
        a, b = await asyncio.gather(self.run_pipeline('kitchen', process), self.run_pipeline('bedroom', process))
        self.assertEqual({a['observation_id'], b['observation_id']}, {'kitchen', 'bedroom'})
        self.assertEqual(sorted(observed), [('bedroom', b''.join(parts)), ('kitchen', b''.join(parts))])

    async def test_oversized_capture_does_not_break_stt_or_persist_audio(self):
        async def transcribe(metadata, stream):
            count = sum([len(chunk) async for chunk in stream])
            self.assertEqual(count, 1_000_002)
            return 'unchanged'
        entity = await self.speech_entity(types.SimpleNamespace(internal_async_process_audio_stream=transcribe))
        async def process():
            async def stream(): yield b'x' * 1_000_002
            self.assertEqual(await entity.async_process_audio_stream(types.SimpleNamespace(sample_rate=16000, channel=1), stream()), 'unchanged')
            self.assertIsNone(self.bridge.current(self.hass).observation)
        await self.run_pipeline('kitchen', process)


if __name__ == '__main__':
    unittest.main(verbosity=2)
