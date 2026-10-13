"""Chauffeur Conversation — forwards Assist utterances to the Chauffeur add-on agent."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

PLATFORMS = [Platform.CONVERSATION, Platform.STT]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    from . import pipeline_bridge
    installed = False
    if entry.options.get('stt_delegate'):
        installed = pipeline_bridge.install(hass)
        if not installed:
            import logging
            logging.getLogger(__name__).warning('Voice recognition bridge unavailable: %s STT and conversation still work.', pipeline_bridge.status(hass)['reason'])
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        if installed:
            pipeline_bridge.uninstall(hass)
        raise
    if installed:
        # Capture the installation, not options that may already have changed.
        entry.async_on_unload(lambda: pipeline_bridge.uninstall(hass))
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    # Options changed (base URL edited via Configure) — reload so the
    # conversation entity picks up the new URL.
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
