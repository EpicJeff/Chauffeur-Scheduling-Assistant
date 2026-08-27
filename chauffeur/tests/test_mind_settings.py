"""Every Mind setting is registered, on the Mind page — never config."""
from harness import check
from services import settings_registry

def scenario_mind_settings_registered():
    entries = {e['key']: e for e in settings_registry.ENTRIES}
    for key in ('mind_enabled', 'mind_sentinel_cadence_s', 'mind_think_cadence_min',
                'mind_wake_start', 'mind_wake_end', 'mind_max_insights',
                'mind_cap_think', 'mind_cap_sentinel', 'mind_cap_promote',
                'mind_direct_categories'):
        check(key in entries, f"{key} registered")
        check(entries[key]['page'] == 'mind', f"{key} lives on the Mind page")

if __name__ == '__main__':
    scenario_mind_settings_registered()
    print("test_mind_settings OK")
