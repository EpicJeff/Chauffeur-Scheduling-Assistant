"""The house answers for its own devices (local relay): when a sentence that
reached the Chauffeur conversation entity names a real exposed device, the
entity asks Home Assistant's default agent and returns ITS answer ("Sorry,
there are multiple devices called Office TV") instead of Argyle's refusal.
A sentence HA does not recognise, or one naming a device HA has never heard
of, still goes to /api/v2/converse. A broken or missing default agent never
blocks Argyle. Stubbed Home Assistant, the real conversation entity.

Run from chauffeur/:  python tests/test_voice_local_relay.py
"""
import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ARGYLE = "I can't control smart home devices."
HOUSE = 'Sorry, there are multiple devices called Office TV'


class LocalRelayTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.path = Path(__file__).resolve().parents[2] / 'homeassistant/custom_components/chauffeur_conversation'
        self.posted = []
        self.default_agent = None
        tests = self

        class FakeResp:
            status = 200

            def raise_for_status(self):
                pass

            async def json(self):
                return {'response': {'speech': {'plain': {'speech': ARGYLE}}}}

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

        from dataclasses import dataclass

        @dataclass
        class ConversationResult:
            response: object
            conversation_id: str | None = None
            continue_conversation: bool = False

        def async_get_agent(hass, agent_id=None):
            tests.assertEqual(agent_id, 'conversation.home_assistant', 'asked for the wrong agent')
            return tests.default_agent

        conv = types.SimpleNamespace(ConversationEntity=ConversationEntity, ConversationResult=ConversationResult,
                                     ConversationInput=types.SimpleNamespace,
                                     HOME_ASSISTANT_AGENT='conversation.home_assistant',
                                     async_get_agent=async_get_agent)
        components = types.ModuleType('homeassistant.components')
        components.conversation = conv
        helpers = types.ModuleType('homeassistant.helpers')
        helpers.intent = types.SimpleNamespace(IntentResponse=IntentResponse)
        helpers.aiohttp_client = types.SimpleNamespace(async_get_clientsession=lambda hass: FakeSession())
        helpers.entity_platform = types.SimpleNamespace(AddEntitiesCallback=object)
        package = types.ModuleType('voice_relay_component')
        package.__path__ = [str(self.path)]
        voice = types.ModuleType('voice_relay_component.voice')

        async def metadata(hass, user_input, mapping=None):
            return {'ha_instance_id': 'ha', 'satellite_id': None, 'device_id': None, 'observed_at': 0}
        voice.metadata = metadata
        bridge = types.ModuleType('voice_relay_component.pipeline_bridge')

        async def observation(hass, user_input):
            return None
        bridge.observation = observation
        const = types.ModuleType('voice_relay_component.const')
        const.CONF_BASE_URL, const.CONF_SERVICE_TOKEN = 'base_url', 'service_token'
        self.modules = {
            'voice_relay_component': package, 'voice_relay_component.voice': voice,
            'voice_relay_component.const': const, 'voice_relay_component.pipeline_bridge': bridge,
            'homeassistant': types.ModuleType('homeassistant'),
            'homeassistant.const': types.SimpleNamespace(__version__='2026.10.1', MATCH_ALL='*'),
            'homeassistant.core': types.SimpleNamespace(HomeAssistant=object),
            'homeassistant.config_entries': types.SimpleNamespace(ConfigEntry=object),
            'homeassistant.components': components, 'homeassistant.components.conversation': conv,
            'homeassistant.helpers': helpers, 'homeassistant.helpers.intent': helpers.intent,
            'homeassistant.helpers.aiohttp_client': helpers.aiohttp_client,
            'homeassistant.helpers.entity_platform': helpers.entity_platform,
        }
        self.module_patch = patch.dict(sys.modules, self.modules)
        self.module_patch.start()
        self.addCleanup(self.module_patch.stop)
        self.ConversationResult, self.IntentResponse = ConversationResult, IntentResponse
        spec = importlib.util.spec_from_file_location('voice_relay_component.conversation', self.path / 'conversation.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        self.addCleanup(sys.modules.pop, spec.name, None)
        spec.loader.exec_module(module)
        entry = types.SimpleNamespace(entry_id='entry', options={}, data={'base_url': 'http://chauffeur', 'service_token': 's'})
        self.entity = module.ChauffeurConversationEntity(entry)
        self.entity.hass = types.SimpleNamespace(async_create_task=asyncio.create_task)

    def house(self, recognized, speech=HOUSE):
        """A default agent whose strict recognition returns `recognized` and whose own
        processing answers `speech` (the real one re-fails the way it did in the pipeline)."""
        tests = self

        class DefaultAgent:
            def __init__(self):
                self.processed = []

            async def async_recognize_intent(self, user_input, strict_intents_only=False):
                tests.assertTrue(strict_intents_only, 'the pipeline matches strictly; so must we')
                if isinstance(recognized, Exception):
                    raise recognized
                return recognized

            async def async_process(self, user_input):
                self.processed.append(user_input.text)
                response = tests.IntentResponse(user_input.language)
                response.async_set_speech(speech)
                return tests.ConversationResult(response=response, conversation_id=user_input.conversation_id)
        self.default_agent = DefaultAgent()
        return self.default_agent

    async def say(self, text, conversation_id='c1'):
        user_input = types.SimpleNamespace(text=text, language='en-US', conversation_id=conversation_id,
                                           context=types.SimpleNamespace(id='ctx'), device_id=None, satellite_id=None)
        return await self.entity.async_process(user_input)

    async def test_a_sentence_naming_a_real_device_gets_the_houses_answer_not_argyles(self):
        house = self.house(types.SimpleNamespace(unmatched_entities={}))
        result = await self.say('turn off the office tv')
        self.assertEqual(result.response.speech, HOUSE)
        self.assertEqual(house.processed, ['turn off the office tv'])
        self.assertEqual(self.posted, [], 'a house sentence still reached Chauffeur')
        self.assertEqual(result.conversation_id, 'c1')

    async def test_a_device_the_house_never_heard_of_still_goes_to_argyle(self):
        house = self.house(types.SimpleNamespace(unmatched_entities={'name': 'schedule'}))
        result = await self.say('open the schedule')
        self.assertEqual([p['text'] for p in self.posted], ['open the schedule'])
        self.assertEqual(result.response.speech, ARGYLE)
        self.assertEqual(house.processed, [], 'the house ran a command it could not target')

    async def test_an_unrecognised_sentence_goes_to_argyle(self):
        house = self.house(None)
        await self.say('take Alice to practice at four')
        self.assertEqual([p['text'] for p in self.posted], ['take Alice to practice at four'])
        self.assertEqual(house.processed, [])

    async def test_a_broken_default_agent_never_blocks_argyle(self):
        self.house(RuntimeError('intents not loaded'))
        result = await self.say('turn off the office tv')
        self.assertEqual([p['text'] for p in self.posted], ['turn off the office tv'])
        self.assertEqual(result.response.speech, ARGYLE)

    async def test_no_default_agent_means_argyle_as_before(self):
        self.default_agent = None
        result = await self.say('turn off the office tv')
        self.assertEqual(len(self.posted), 1)
        self.assertEqual(result.response.speech, ARGYLE)

    async def test_a_default_agent_that_fails_while_answering_falls_through_to_argyle(self):
        house = self.house(types.SimpleNamespace(unmatched_entities={}))

        async def boom(user_input):
            raise RuntimeError('intent handler exploded')
        house.async_process = boom
        result = await self.say('turn off the office tv')
        self.assertEqual([p['text'] for p in self.posted], ['turn off the office tv'])
        self.assertEqual(result.response.speech, ARGYLE)


if __name__ == '__main__':
    unittest.main()
