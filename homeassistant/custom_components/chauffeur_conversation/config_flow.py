"""Config flow for Chauffeur Conversation."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback

from .const import CONF_BASE_URL, DEFAULT_BASE_URL, DOMAIN


class ChauffeurConversationConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> ChauffeurOptionsFlow:
        return ChauffeurOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title="Chauffeur",
                data={CONF_BASE_URL: user_input[CONF_BASE_URL].rstrip("/")},
            )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_BASE_URL, default=DEFAULT_BASE_URL): str}
            ),
        )


class ChauffeurOptionsFlow(OptionsFlow):
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                data={CONF_BASE_URL: user_input[CONF_BASE_URL].rstrip("/")}
            )
        current = self.config_entry.options.get(
            CONF_BASE_URL,
            self.config_entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL),
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {vol.Required(CONF_BASE_URL, default=current): str}
            ),
        )
