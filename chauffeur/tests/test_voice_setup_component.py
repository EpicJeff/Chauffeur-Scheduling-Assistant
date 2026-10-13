"""The HA continuation proof (plan Task 4): two utterances in one continued
conversation reach /api/v2/converse as two requests with distinct run and
utterance ids, the same conversation_id, and the first reply's
continue_conversation flag reaches HA's result. Stubbed Home Assistant, the
real pipeline bridge and the real conversation entity.

Run from chauffeur/:  python tests/test_voice_setup_component.py
"""
import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


class ContinuationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Module loading is slow enough to trip asyncio's debug-mode warning
        # inside asyncSetUp; it has nothing to await, so it runs here.
        self.path = Path(__file__).resolve().parents[2] / 'homeassistant/custom_components/chauffeur_conversation'
        self.posted = []
        tests = self

        class Controller:
            async def async_execute(self, pipeline_input, *, validate=False):
                return await pipeline_input.process()
        self.Controller = Controller
        self.hass = types.SimpleNamespace(async_create_task=asyncio.create_task)

        class FakeResp:
            status = 200

            def raise_for_status(self):
                pass

            async def json(self):
                return {'continue_conversation': True,
                        'response': {'speech': {'plain': {'speech': 'Tell me about your day.'}}}}

        class FakeSession:
            async def post(self, url, json=None, headers=None, timeout=None):
                tests.posted.append(json)
                return FakeResp()

        class ConversationEntity:
            pass

        class IntentResponse:
            def __init__(self, language=None):
                self.language, self.speech = language, None

            def async_set_speech(self, speech):
                self.speech = speech

        from dataclasses import dataclass, field

        @dataclass
        class ConversationResult:
            response: object
            conversation_id: str | None = None
            continue_conversation: bool = False

        conv = types.SimpleNamespace(ConversationEntity=ConversationEntity, ConversationResult=ConversationResult,
                                     ConversationInput=types.SimpleNamespace)
        components = types.ModuleType('homeassistant.components')
        components.conversation = conv
        helpers = types.ModuleType('homeassistant.helpers')
        helpers.intent = types.SimpleNamespace(IntentResponse=IntentResponse)
        helpers.aiohttp_client = types.SimpleNamespace(async_get_clientsession=lambda hass: FakeSession())
        helpers.entity_platform = types.SimpleNamespace(AddEntitiesCallback=object)
        package = types.ModuleType('voice_test_component')
        package.__path__ = [str(self.path)]
        voice = types.ModuleType('voice_test_component.voice')

        async def metadata(hass, user_input, mapping=None):
            return {'ha_instance_id': 'ha', 'satellite_id': user_input.satellite_id,
                    'device_id': user_input.device_id, 'observed_at': 0}
        voice.metadata = metadata
        const = types.ModuleType('voice_test_component.const')
        const.CONF_BASE_URL, const.CONF_SERVICE_TOKEN = 'base_url', 'service_token'
        self.modules = {
            'voice_test_component': package, 'voice_test_component.voice': voice, 'voice_test_component.const': const,
            'homeassistant': types.ModuleType('homeassistant'),
            'homeassistant.const': types.SimpleNamespace(__version__='2026.10.0', MATCH_ALL='*'),
            'homeassistant.core': types.SimpleNamespace(HomeAssistant=object),
            'homeassistant.config_entries': types.SimpleNamespace(ConfigEntry=object),
            'homeassistant.components': components, 'homeassistant.components.conversation': conv,
            'homeassistant.components.assist_pipeline.run': types.SimpleNamespace(PipelineRun=Controller),
            'homeassistant.helpers': helpers, 'homeassistant.helpers.intent': helpers.intent,
            'homeassistant.helpers.aiohttp_client': helpers.aiohttp_client,
            'homeassistant.helpers.entity_platform': helpers.entity_platform,
        }
        self.module_patch = patch.dict(sys.modules, self.modules)
        self.module_patch.start()
        self.addCleanup(self.module_patch.stop)
        self.bridge = self.load('pipeline_bridge')
        self.assertTrue(self.bridge.install(self.hass))
        self.addCleanup(self.bridge.uninstall, self.hass)
        conversation = self.load('conversation')
        entry = types.SimpleNamespace(entry_id='entry', options={}, data={'base_url': 'http://chauffeur', 'service_token': 's'})
        self.entity = conversation.ChauffeurConversationEntity(entry)
        self.entity.hass = self.hass

    def load(self, name):
        spec = importlib.util.spec_from_file_location(f'voice_test_component.{name}', self.path / f'{name}.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        self.addCleanup(sys.modules.pop, spec.name, None)
        spec.loader.exec_module(module)
        return module

    async def utterance(self, number, text, conversation_id='c1'):
        """One HA pipeline run on the kitchen satellite, the way HA runs a continued turn."""
        controller = self.Controller()
        controller.hass, controller.id = self.hass, f'run-{number}'
        controller.context = types.SimpleNamespace(id=f'context-{number}')
        runs = []

        async def process():
            run = self.bridge.current(self.hass)
            runs.append(run)
            run.observation = asyncio.create_task(asyncio.sleep(0, result={'observation_id': f'obs-{number}'}))
            user_input = types.SimpleNamespace(text=text, language='en', conversation_id=conversation_id,
                                               context=types.SimpleNamespace(id=run.context_id),
                                               device_id=run.device_id, satellite_id=run.satellite_id)
            return await self.entity.async_process(user_input)
        pipeline_input = types.SimpleNamespace(device_id='device', satellite_id='assist_satellite.kitchen', process=process)
        result = await controller.async_execute(pipeline_input)
        return result, runs[0]

    async def test_each_continued_turn_posts_its_own_run_and_the_same_conversation(self):
        first, run1 = await self.utterance(1, 'set up my voice')
        second, run2 = await self.utterance(2, 'today I walked the dog and made breakfast for everyone')
        self.assertTrue(first.continue_conversation, 'the continue flag did not reach HA')
        self.assertEqual([p['conversation_id'] for p in self.posted], ['c1', 'c1'])
        self.assertEqual([p['voice']['request_id'] for p in self.posted], [run1.utterance_id, run2.utterance_id])
        self.assertNotEqual(run1.utterance_id, run2.utterance_id)
        self.assertEqual([p['voice']['run_id'] for p in self.posted], ['run-1', 'run-2'])
        self.assertEqual([p['voice']['observation_id'] for p in self.posted], ['obs-1', 'obs-2'])
        self.assertEqual(second.conversation_id, 'c1')

    async def test_an_observation_is_never_reused_by_the_next_turn(self):
        controller = self.Controller()
        controller.hass, controller.id = self.hass, 'run-x'
        controller.context = types.SimpleNamespace(id='context-x')

        async def process():
            run = self.bridge.current(self.hass)
            run.observation = asyncio.create_task(asyncio.sleep(0, result={'observation_id': 'once'}))
            user = types.SimpleNamespace(context=types.SimpleNamespace(id=run.context_id),
                                         device_id=run.device_id, satellite_id=run.satellite_id)
            self.assertEqual((await self.bridge.observation(self.hass, user))['observation_id'], 'once')
            self.assertIsNone(await self.bridge.observation(self.hass, user), 'a consumed observation came back')
        await controller.async_execute(types.SimpleNamespace(device_id='device', satellite_id='assist_satellite.kitchen',
                                                             process=process))
        self.assertIsNone(self.bridge.current(self.hass))


if __name__ == '__main__':
    unittest.main()
