"""Config flow for Chauffeur Conversation."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_BASE_URL, CONF_SERVICE_TOKEN, DEFAULT_BASE_URL, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def _async_validate_connection(
    hass: HomeAssistant, base_url: str, service_token: str = ""
) -> str | None:
    """Hit a cheap Chauffeur endpoint; return an error string or None if OK.

    Validating WITH the token is the point: it turns "did you paste the right
    one?" into something the setup form answers, instead of a silent Argyle
    discovered days later by asking it a question and getting nothing back.
    """
    session = async_get_clientsession(hass)
    headers = {"X-Service-Token": service_token} if service_token else {}
    try:
        resp = await session.get(
            f"{base_url}/api/chat/history",
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=10),
        )
        if resp.status in (401, 403):
            return "Chauffeur refused the token — check it was copied in full."
        resp.raise_for_status()
    except (aiohttp.ClientError, TimeoutError, ValueError) as err:
        _LOGGER.error("Cannot reach Chauffeur at %s: %s", base_url, err)
        return str(err) or type(err).__name__
    return None


class ChauffeurConversationConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> ChauffeurOptionsFlow:
        return ChauffeurOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}
        default_url = DEFAULT_BASE_URL
        token = ""
        if user_input is not None:
            base_url = user_input[CONF_BASE_URL].rstrip("/")
            token = user_input.get(CONF_SERVICE_TOKEN, "").strip()
            default_url = base_url
            error = await _async_validate_connection(self.hass, base_url, token)
            if error is None:
                return self.async_create_entry(
                    title="Chauffeur",
                    data={CONF_BASE_URL: base_url, CONF_SERVICE_TOKEN: token},
                )
            errors["base"] = "cannot_connect"
            placeholders["error"] = error
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_BASE_URL, default=default_url): str,
                    vol.Optional(CONF_SERVICE_TOKEN, default=token): str,
                }
            ),
            errors=errors,
            description_placeholders=placeholders,
        )


class ChauffeurOptionsFlow(OptionsFlow):
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}
        current = self.config_entry.options.get(
            CONF_BASE_URL,
            self.config_entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL),
        )
        current_token = self.config_entry.options.get(
            CONF_SERVICE_TOKEN,
            self.config_entry.data.get(CONF_SERVICE_TOKEN, ""),
        )
        if user_input is not None:
            base_url = user_input[CONF_BASE_URL].rstrip("/")
            current = base_url
            current_token = user_input.get(CONF_SERVICE_TOKEN, "").strip()
            error = await _async_validate_connection(self.hass, base_url, current_token)
            if error is None:
                return self.async_create_entry(
                    data={CONF_BASE_URL: base_url, CONF_SERVICE_TOKEN: current_token}
                )
            errors["base"] = "cannot_connect"
            placeholders["error"] = error
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_BASE_URL, default=current): str,
                    vol.Optional(CONF_SERVICE_TOKEN, default=current_token): str,
                }
            ),
            errors=errors,
            description_placeholders=placeholders,
        )
