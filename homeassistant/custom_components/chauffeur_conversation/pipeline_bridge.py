"""Explicit per-run context for HA 2026.10.x; never correlate by time/text.

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
import re
import uuid

_current = ContextVar('chauffeur_pipeline_run', default=None)
_owners = {}
_original = None
_wrapper = None
_pipeline_class = None
_status = {}


def status(hass):
    return _status.get(id(hass), {'available': False, 'reason': 'Choose an STT delegate to enable the voice bridge.'})


def _unavailable(hass, reason, version=''):
    _status[id(hass)] = {'available': False, 'reason': reason, 'version': version}
    return False


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
        result = await asyncio.wait_for(asyncio.shield(run.observation), 1)
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
    global _original, _wrapper, _pipeline_class
    try:
        from homeassistant.const import __version__
    except ImportError:
        return _unavailable(hass, 'Home Assistant version is unavailable.')
    if not re.fullmatch(r'2026\.10\.\d+', __version__):
        return _unavailable(hass, 'Voice bridge supports HA 2026.10.x.', __version__)
    try:
        from homeassistant.components.assist_pipeline.run import PipelineRun
    except (ImportError, AttributeError):
        return _unavailable(hass, 'Assist pipeline controller is unavailable.', __version__)
    method = getattr(PipelineRun, 'async_execute', None)
    if method is None:
        return _unavailable(hass, 'Assist pipeline entry point is unavailable.', __version__)
    if _wrapper and method is not _wrapper:
        return _unavailable(hass, 'Another component replaced the Assist pipeline controller.', __version__)
    if not _wrapper:
        original = method
        try:
            compatible = tuple(inspect.signature(original).parameters) == ('self', 'pipeline_input', 'validate')
        except (TypeError, ValueError):
            compatible = False
        if not compatible:
            return _unavailable(hass, 'Assist pipeline signature is incompatible.', __version__)

        @wraps(original)
        async def execute(controller, pipeline_input, *, validate=False):
            if id(getattr(controller, 'hass', None)) not in _owners:
                return await original(controller, pipeline_input, validate=validate)
            context_id = getattr(getattr(controller, 'context', None), 'id', None)
            if not context_id or not getattr(controller, 'id', None):
                _unavailable(controller.hass, 'Assist pipeline context is incompatible.', __version__)
                return await original(controller, pipeline_input, validate=validate)
            run = Run(controller.hass, controller.id, context_id,
                      getattr(pipeline_input, 'device_id', None), getattr(pipeline_input, 'satellite_id', None))
            token = _current.set(run)
            try:
                return await original(controller, pipeline_input, validate=validate)
            finally:
                run.active = False
                if run.observation and not run.observation.done():
                    run.observation.cancel()
                _current.reset(token)

        _original, _wrapper, _pipeline_class = original, execute, PipelineRun
        PipelineRun.async_execute = execute
    _owners[id(hass)] = _owners.get(id(hass), 0) + 1
    _status[id(hass)] = {'available': True, 'reason': '', 'version': __version__}
    return True


def uninstall(hass):
    global _original, _wrapper, _pipeline_class
    if _owners.get(id(hass), 0) > 1:
        _owners[id(hass)] -= 1
    else:
        _owners.pop(id(hass), None)
        _status.pop(id(hass), None)
    if not _owners and _wrapper:
        if _pipeline_class.async_execute is _wrapper:
            _pipeline_class.async_execute = _original
        _original = _wrapper = _pipeline_class = None
