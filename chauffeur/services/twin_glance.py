"""Twin display preferences, isolated from schedule settings and model rounds."""
from services import storage

KEY = 'house_twin_glance'


def read(panel=None):
    household = storage.get_app_state(KEY) or {}
    override = (panel or {}).get(KEY) or {}
    return {'household_entities': household.get('entities'),
            'panel_entities': override.get('entities'),
            'entities': override.get('entities') if override.get('entities') is not None else household.get('entities'),
            'idle_enabled': override.get('idle_enabled', household.get('panel_idle_enabled', True)) if panel
            else household.get('idle_enabled', False),
            'panel_idle_enabled': household.get('panel_idle_enabled', True),
            'panel_id': panel.get('device_id') if panel else None}


def save(entities, idle_enabled, panel_id=None, panel_idle_enabled=True):
    fields = {'entities': entities, 'idle_enabled': idle_enabled}
    if panel_id:
        return storage.set_device_twin_glance(panel_id, fields)
    fields['panel_idle_enabled'] = panel_idle_enabled
    storage.set_app_state(KEY, fields)
    return fields
