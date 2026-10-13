"""Explicit per-run context, pinned to HA 2026.10.0; never correlate by time/text.

HA does not pass the run identity to STT. Wrap its run controller, not the
delegate or global latest audio. Context survives awaits and inherited tasks;
conversation additionally checks the original HA context/device/satellite.
"""
from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
import inspect
import uuid

_current = ContextVar('chauffeur_pipeline_run', default=None)
_owners = {}
_original = None
_wrapper = None


@dataclass
class Run:
    hass: object
    run_id: str
    context_id: str
    device_id: str | None
    satellite_id: str | None
    utterance_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    observation: asyncio.Task | None = None
    captured: bool = False
    consumed: bool = False
    active: bool = True


def current(hass):
    run = _current.get()
    return run if run and run.hass is hass and run.active else None


async def observation(hass, user_input):
    run = current(hass)
    if not run or run.consumed or run.context_id != getattr(user_input.context, 'id', None) \
            or run.device_id != getattr(user_input, 'device_id', None) \
            or run.satellite_id != getattr(user_input, 'satellite_id', None):
        return None
    run.consumed = True
    if not run.observation:
        return None
    try:
        result = await asyncio.wait_for(asyncio.shield(run.observation), .1)
        if result:
            return {'run_id': run.run_id, 'utterance_id': run.utterance_id,
                    'observation_id': result['observation_id']}
    except (TimeoutError, asyncio.CancelledError):
        if asyncio.current_task().cancelling():
            raise
    except Exception:
        pass  # unavailable recognition must not break ordinary STT
    return None


def install(hass):
    from homeassistant.const import __version__
    from homeassistant.components.assist_pipeline.run import PipelineRun
    global _original, _wrapper
    if __version__ != '2026.10.0':
        return False
    if _wrapper and PipelineRun.async_execute is not _wrapper:
        return False  # another component replaced the controller
    if not _wrapper:
        original = PipelineRun.async_execute
        if tuple(inspect.signature(original).parameters) != ('self', 'pipeline_input', 'validate'):
            return False

        @wraps(original)
        async def execute(controller, pipeline_input, *, validate=False):
            if id(controller.hass) not in _owners:
                return await original(controller, pipeline_input, validate=validate)
            run = Run(controller.hass, controller.id, controller.context.id,
                      pipeline_input.device_id, pipeline_input.satellite_id)
            token = _current.set(run)
            try:
                return await original(controller, pipeline_input, validate=validate)
            finally:
                run.active = False
                if run.observation and not run.observation.done():
                    run.observation.cancel()
                _current.reset(token)

        _original, _wrapper = original, execute
        PipelineRun.async_execute = execute
    _owners[id(hass)] = _owners.get(id(hass), 0) + 1
    return True


def uninstall(hass):
    from homeassistant.components.assist_pipeline.run import PipelineRun
    global _original, _wrapper
    if _owners.get(id(hass), 0) > 1:
        _owners[id(hass)] -= 1
    else:
        _owners.pop(id(hass), None)
    if not _owners and _wrapper and PipelineRun.async_execute is _wrapper:
        PipelineRun.async_execute = _original
        _original = _wrapper = None
