"""The settings registry (2026-08-07).

Config had reached 5,631 lines and 83 fields saved as one object. The fix is
to move settings onto the surfaces that own them and replace the big page with
a searchable index — so the load-bearing property is that the index stays
COMPLETE. A registry that quietly falls behind the model is worse than none,
because the index would then claim to list everything while hiding whatever
was added last.

Run from chauffeur/:  python tests/test_settings_registry.py
"""
import atexit
import os
import shutil
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="chauffeur_settings_test_")
os.environ["CHAUFFEUR_DATA_DIR"] = _TMP
atexit.register(lambda: shutil.rmtree(_TMP, ignore_errors=True))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import settings_registry as reg   # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def scenario_every_setting_is_listed_and_nothing_is_stale():
    """THE test. Add a field to `Settings` without registering it and this
    fails — which is the only thing keeping the index honest."""
    a = reg.audit()
    check(not a['missing'],
          f"settings missing from the registry: {a['missing']}")
    check(not a['stale'],
          f"registry entries with no matching setting: {a['stale']}")


def scenario_no_setting_is_unreachable():
    """The "none get lost" guarantee, mechanically enforced.

    The registry says where each setting lives; this checks the claim against
    the template. A registry entry pointing at a page that does not carry the
    control is the silent failure the index would otherwise hide — and it
    would be worse than the old 5,631-line config page, where at least
    everything really was on it.

    Run at the start of the migration this found TEN settings with no hand
    path anywhere (days-to-solve, sides, dessert, the three prep-reminder
    keys, and the four Walmart keys). None were introduced by the move; they
    had simply never had one.
    """
    u = reg.audit_ui()['unreachable']
    check(not u,
          "settings with no way to change them by hand: "
          + ', '.join(f"{e['key']} ({e['why']})" for e in u))


def scenario_every_entry_carries_an_owner_and_words_to_search_on():
    for e in reg.ENTRIES:
        check(e['page'] and e['anchor'],
              f"{e['key']} has nowhere to send you")
        check(e['group'] in dict((g, t) for g, _i, t in reg.GROUPS),
              f"{e['key']} is in an unknown group {e['group']}")
        check(len(e['help'] or '') > 15,
              f"{e['key']} has no help text worth searching")
        # Only the real failure: a raw key pasted in as a label. "Trip
        # hashtags" for `trip_hashtags` is not a miss — some keys are already
        # the words a person would say, and forcing a synonym makes it worse.
        check(e['label'] and '_' not in e['label'],
              f"{e['key']} has a raw key for a label, got {e['label']!r}")


def scenario_search_finds_things_by_the_word_you_would_say():
    """Somebody looking for the oven types "oven", not `kitchen_ovens`."""
    for term, want in (('oven', 'kitchen_ovens'),
                       ('quiet', 'kid_quiet_start'),
                       ('shop day', 'grocery_weekday'),
                       ('thaw', 'prep_reminders_enabled')):
        hits = {s['key'] for g in reg.search(term) for s in g['settings']}
        check(want in hits, f"searching {term!r} did not find {want}: {sorted(hits)}")


def scenario_the_index_never_reveals_a_secret():
    """An index is a findability tool and has no business being a second place
    a token can leak from."""
    vals = {'ha_token': 'super-secret', 'llm_gemini_api_key': 'AIza-secret',
            'ingest_email_password': 'hunter2', 'home_location': '1 Home St'}
    rows = {s['key']: s for g in reg.index(vals) for s in g['settings']}
    for k in ('ha_token', 'llm_gemini_api_key', 'ingest_email_password'):
        check(rows[k]['is_secret'], f"{k} is not marked secret")
        check(rows[k]['value'] == 'set',
              f"{k} leaked its value as {rows[k]['value']!r}")
    check(rows['home_location']['value'] == '1 Home St',
          "an ordinary value is still shown, or the index is useless")


def scenario_the_kitchen_points_at_the_page_that_owns_it():
    """The first setting deliberately moved off the config page. If this ever
    reverts, the decentralisation stopped."""
    for k in ('kitchen_ovens', 'kitchen_burners', 'kitchen_cooks'):
        own = reg.owner(k)
        check(own['page'] == 'shopping' and own['anchor'] == 'kitchen',
              f"{k} should live with the meals, got {own}")


def scenario_an_empty_search_is_the_whole_index():
    check(len(reg.search('')) == len(reg.index()),
          "a blank box lists everything rather than nothing")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} settings-registry scenarios passed")
