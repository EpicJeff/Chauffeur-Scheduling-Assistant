"""Pass-through STT with an opt-in, bounded local fingerprint copy."""
from __future__ import annotations

import asyncio
import json
import logging
import time

import aiohttp
from homeassistant.components import stt
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import instance_id

from . import pipeline_bridge
from .const import CONF_BASE_URL, CONF_SERVICE_TOKEN

_LOGGER = logging.getLogger(__name__)
MAX_AUDIO = 1_000_000


async def async_setup_entry(hass, entry, async_add_entities):
    delegate = entry.options.get('stt_delegate')
    if delegate:
        async_add_entities([ChauffeurSpeech(entry, delegate)])


class ChauffeurSpeech(stt.SpeechToTextEntity):
    _attr_has_entity_name = True
    _attr_name = 'Chauffeur Voice recognition'

    def __init__(self, entry, delegate):
        self.entry, self.delegate_id = entry, delegate
        self._attr_unique_id = entry.entry_id + '_stt'

    @property
    def delegate(self):
        entity = stt.async_get_speech_to_text_entity(self.hass, self.delegate_id)
        if entity is None or isinstance(entity, ChauffeurSpeech):
            raise ValueError('Choose an existing non-Chauffeur STT provider.')
        return entity

    @property
    def available(self):
        try:
            return self.delegate.available
        except (ValueError, AttributeError):
            return False

    def _supported(self, attribute, default=None):
        try:
            return getattr(self.delegate, attribute)
        except (ValueError, AttributeError):
            return [] if default is None else default

    @property
    def supported_languages(self): return self._supported('supported_languages')
    @property
    def supported_formats(self): return self._supported('supported_formats')
    @property
    def supported_codecs(self): return self._supported('supported_codecs')
    @property
    def supported_bit_rates(self): return self._supported('supported_bit_rates')
    @property
    def supported_sample_rates(self): return self._supported('supported_sample_rates')
    @property
    def supported_channels(self): return self._supported('supported_channels')
    @property
    def audio_processing(self): return self._supported('audio_processing', stt.DEFAULT_AUDIO_PROCESSING)

    async def async_process_audio_stream(self, metadata, stream):
        run = pipeline_bridge.current(self.hass)
        capture = bool(run and not run.captured and run.satellite_id and run.device_id)
        if capture:
            run.captured = True
        chunks, size, overflow = [], 0, False
        limit = min(MAX_AUDIO, int(metadata.sample_rate) * int(metadata.channel) * 2 * 15)

        async def tee():
            nonlocal size, overflow
            async for chunk in stream:
                if capture and not overflow:
                    size += len(chunk)
                    if size <= limit:
                        chunks.append(chunk)
                    else:
                        overflow = True
                        chunks.clear()
                yield chunk  # delegate gets identical metadata and bytes
            if capture and chunks and not overflow and run.active:
                audio = b''.join(chunks)
                chunks.clear()
                run.observation = self.hass.async_create_task(self._submit(run, metadata, audio))

        try:
            result = await self.delegate.internal_async_process_audio_stream(metadata, tee())
            return result
        finally:
            chunks.clear()

    async def _submit(self, run, metadata, audio):
        options = self.entry.options
        token = options.get(CONF_SERVICE_TOKEN, self.entry.data.get(CONF_SERVICE_TOKEN, ''))
        if not token:
            return None
        voice = {'ha_instance_id': await instance_id.async_get(self.hass),
                 'satellite_id': run.satellite_id, 'device_id': run.device_id,
                 'request_id': run.utterance_id, 'utterance_id': run.utterance_id,
                 'run_id': run.run_id, 'observed_at': time.time(),
                 'sample_rate': int(metadata.sample_rate), 'channel': int(metadata.channel),
                 'bit_rate': int(metadata.bit_rate), 'codec': str(metadata.codec),
                 'format': str(metadata.format)}
        base = options.get(CONF_BASE_URL, self.entry.data[CONF_BASE_URL])
        try:
            async with async_get_clientsession(self.hass).post(base + '/api/voice/audio', data=audio,
                    headers={'X-Service-Token': token, 'X-Voice-Metadata': json.dumps(voice),
                             'Content-Type': 'application/octet-stream'},
                    timeout=aiohttp.ClientTimeout(total=4)) as response:
                if response.status == 200:
                    return await response.json()
        except (aiohttp.ClientError, TimeoutError):
            _LOGGER.debug('Local voice fingerprint unavailable')
        return None
