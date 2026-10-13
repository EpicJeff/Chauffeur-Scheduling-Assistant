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
            logging.getLogger(__name__).warning('Voice recognition bridge requires HA 2026.10.0; STT still works without recognition.')
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        if installed:
            pipeline_bridge.uninstall(hass)
        raise
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    # Options changed (base URL edited via Configure) — reload so the
    # conversation entity picks up the new URL.
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded and entry.options.get('stt_delegate'):
        from . import pipeline_bridge
        pipeline_bridge.uninstall(hass)
    return unloaded
