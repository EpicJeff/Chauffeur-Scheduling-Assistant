"""Conversation entity that proxies Assist text to Chauffeur's /api/v2/converse."""
from __future__ import annotations

import logging

import aiohttp

from homeassistant.components import conversation
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import MATCH_ALL
from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_BASE_URL, CONF_SERVICE_TOKEN
from .voice import metadata

_LOGGER = logging.getLogger(__name__)

# The Chauffeur agent may call an LLM plus scheduling tools; give it room.
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=120)
MEDIA_INTENTS = frozenset({
    'HassMediaSearchAndPlay', 'HassMediaPause', 'HassMediaUnpause',
    'HassMediaNext', 'HassMediaPrevious', 'HassSetVolume',
})


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([ChauffeurConversationEntity(entry)])


class ChauffeurConversationEntity(conversation.ConversationEntity):
    # No `_attr_supported_features`, and specifically no
    # ConversationEntityFeature.CONTROL — that is load bearing, not an
    # oversight. assist_pipeline narrows "prefer handling commands locally" to
    # a two-intent allowlist (get-state and media-search-and-play) as soon as
    # the agent advertises CONTROL, because such an agent is assumed to control
    # Home Assistant itself through its own LLM tools. Ours does not: it
    # schedules drivers, and it cannot open the garage. Declaring CONTROL would
    # route every light, lock and cover sentence here instead of to the
    # built-in intents that can actually serve them.
    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._base_url: str = entry.options.get(
            CONF_BASE_URL, entry.data[CONF_BASE_URL]
        )
        # Auth arc S7. Empty is a normal state during migration: the household
        # still has the local-origin grace on, and Chauffeur answers anyway.
        self._service_token: str = entry.options.get(
            CONF_SERVICE_TOKEN, entry.data.get(CONF_SERVICE_TOKEN, "")
        )
        self._attr_unique_id = entry.entry_id

    @property
    def supported_languages(self) -> list[str] | str:
        return MATCH_ALL

    async def _house_answer(
        self, user_input: conversation.ConversationInput
    ) -> conversation.ConversationResult | None:
        """Ask the house again when no_valid_targets falls through the pipeline.

        Music intents stay with Argyle's music tool.
        Names HA never heard of stay with Argyle, so overlapping vocabulary
        like "open the schedule" is not stolen.
        """
        try:
            get_agent = getattr(conversation, "async_get_agent", None)
            agent_id = getattr(conversation, "HOME_ASSISTANT_AGENT", None)
            if get_agent is None or agent_id is None:
                _LOGGER.debug("Default agent API unavailable; continuing to Chauffeur")
                return None
            agent = get_agent(self.hass, agent_id)
            if agent is None:
                _LOGGER.debug("Default agent unavailable; continuing to Chauffeur")
                return None
            recognized = await agent.async_recognize_intent(
                user_input, strict_intents_only=True
            )
            name = getattr(getattr(recognized, 'intent', None), 'name', '')
            if name in MEDIA_INTENTS:
                _LOGGER.debug("Media intent %s belongs to Chauffeur; skipping relay", name)
                return None
            if recognized and not recognized.unmatched_entities:
                return await agent.async_process(user_input)
            _LOGGER.debug("No known house target matched; continuing to Chauffeur")
        except Exception:
            # Loud on purpose: a silent failure here looks exactly like the
            # bug this relay exists to fix (Argyle refusing a house command).
            _LOGGER.warning("Default agent relay failed; continuing to Chauffeur", exc_info=True)
        return None

    async def async_process(
        self, user_input: conversation.ConversationInput
    ) -> conversation.ConversationResult:
        house_answer = await self._house_answer(user_input)
        if house_answer is not None:
            return house_answer
        session = async_get_clientsession(self.hass)
        payload = {
            "text": user_input.text,
            "language": user_input.language or "en",
            "conversation_id": user_input.conversation_id,
            "voice": await metadata(self.hass, user_input, self._entry.options.get('device_satellites', '{}')),
        }
        from . import pipeline_bridge
        observation = await pipeline_bridge.observation(self.hass, user_input)
        if observation and payload['voice'].get('satellite_id'):
            payload['voice'].update(observation)
            payload['voice']['request_id'] = observation['utterance_id']
        continue_conversation = False
        try:
            resp = await session.post(
                f"{self._base_url}/api/v2/converse",
                json=payload,
                headers=(
                    {"X-Service-Token": self._service_token}
                    if self._service_token
                    else {}
                ),
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data = await resp.json()
            continue_conversation = data.get('continue_conversation') is True
            speech = (
                data.get("response", {})
                .get("speech", {})
                .get("plain", {})
                .get("speech")
            )
            if not speech:
                speech = data.get("error") or "Chauffeur did not return a response."
        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.error("Error talking to Chauffeur at %s: %s", self._base_url, err)
            speech = "Sorry, I couldn't reach Chauffeur."

        response = intent.IntentResponse(language=user_input.language)
        response.async_set_speech(speech)
        result = {"response": response, "conversation_id": user_input.conversation_id}
        if 'continue_conversation' in getattr(conversation.ConversationResult, '__dataclass_fields__', {}):
            result['continue_conversation'] = continue_conversation
        return conversation.ConversationResult(**result)
