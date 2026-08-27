"""tick(): one entry, all gating inside. Disabled = inert. Cadences honored.
A promoted flag causes an early think."""
import datetime
from harness import check
from services import storage, mind

LOG = []

def _stub(name, result):
    def f(*a, **kw):
        LOG.append(name)
        return result
    return f

def _reset(enabled=True):
    LOG.clear()
    storage.set_app_state('mind_sentinel_last', 0)
    storage.set_app_state('mind_last_think_ts', 0)
    storage.set_app_state('mind_think_attempt_ts', 0)
    storage.set_app_state('mind_think_requested', False)
    storage.get_settings = lambda: {'mind_enabled': enabled,
                                    'llm_gemini_api_key': 'k'}
    mind.sentinel_sweep = _stub('sentinel', {'status': 'swept'})
    mind.maybe_promote = _stub('promote', {'status': 'nothing'})
    mind.deep_think = _stub('think', {'status': 'thought'})

NOON = datetime.datetime(2026, 8, 27, 12, 0)

def scenario_disabled_is_inert():
    _reset(enabled=False)
    res = mind.tick(NOON)
    check(res['status'] == 'disabled' and not LOG, "off means OFF")

def scenario_first_tick_runs_all():
    _reset()
    mind.tick(NOON)
    check('sentinel' in LOG and 'think' in LOG, f"cold start runs rungs, got {LOG}")

def scenario_cadence_holds():
    LOG.clear()
    storage.set_app_state('mind_sentinel_last', NOON.timestamp())
    storage.set_app_state('mind_last_think_ts', NOON.timestamp())
    mind.tick(NOON + datetime.timedelta(seconds=45))
    check(LOG == [], f"45s later nothing is due, got {LOG}")

def scenario_promoted_flag_forces_think():
    LOG.clear()
    storage.set_app_state('mind_think_requested', True)
    mind.tick(NOON + datetime.timedelta(seconds=45))
    check('think' in LOG, "promoted flag beats the hourly cadence")

def scenario_error_think_does_not_retry_within_floor():
    # A think that errors leaves mind_last_think_ts alone, so it stays "due"
    # every 30s tick — the attempt marker must hold it to the 300s floor
    # instead of a heavy LLM call per tick.
    _reset()
    mind.deep_think = _stub('think', {'status': 'error'})
    mind.tick(NOON)
    check(LOG.count('think') == 1, f"first attempt goes out, got {LOG}")
    mind.tick(NOON + datetime.timedelta(seconds=30))
    check(LOG.count('think') == 1,
          f"an errored think does not retry on the next 30s tick, got {LOG}")
    mind.tick(NOON + datetime.timedelta(seconds=330))
    check(LOG.count('think') == 2, f"the floor lifts after 300s, got {LOG}")

if __name__ == '__main__':
    scenario_disabled_is_inert()
    scenario_first_tick_runs_all()
    scenario_cadence_holds()
    scenario_promoted_flag_forces_think()
    scenario_error_think_does_not_retry_within_floor()
    print("test_mind_tick OK")
