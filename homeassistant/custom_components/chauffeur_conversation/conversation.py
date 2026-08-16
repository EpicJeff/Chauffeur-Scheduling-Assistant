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

_LOGGER = logging.getLogger(__name__)

# The Chauffeur agent may call an LLM plus scheduling tools; give it room.
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=120)


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

    async def async_process(
        self, user_input: conversation.ConversationInput
    ) -> conversation.ConversationResult:
        session = async_get_clientsession(self.hass)
        payload = {
            "text": user_input.text,
            "language": user_input.language or "en",
            "conversation_id": user_input.conversation_id,
        }
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
        return conversation.ConversationResult(
            response=response, conversation_id=user_input.conversation_id
        )
