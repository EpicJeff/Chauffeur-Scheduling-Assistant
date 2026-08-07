"""Argyle is not a person, and must not appear anywhere people appear.

Argyle exists as a `system: True` member so agent replies have a sender
identity. The original note said the flag "lets the UI exclude it from the
human family roster" — leaving that to each caller, of which there are 57.
Exactly one ever did it (`app.html`), so the assistant turned up in the People
config, in occasion attendance, in presence, in digests: anywhere people are
listed.

A default that has to be remembered at 57 call sites is not a default, so
exclusion lives at the storage boundary now and `include_system=True` is the
deliberate exception for resolving a message SENDER.

Run from chauffeur/:  python tests/test_system_member.py
"""
import atexit
import os
import shutil
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="chauffeur_sysmember_test_")
os.environ["CHAUFFEUR_DATA_DIR"] = _TMP
atexit.register(lambda: shutil.rmtree(_TMP, ignore_errors=True))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import storage, occasions  # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def reset_db():
    with storage.db_lock:
        for name, val in list(vars(storage).items()):
            if name.endswith("_table"):
                val.truncate()


def _seed():
    from models.schemas import FamilyMember
    for name, role in (('Dad', 'parent'), ('Ellie', 'child')):
        storage.add_member(FamilyMember(name=name, role=role).model_dump())
    storage.ensure_argyle_member()


def scenario_the_roster_excludes_argyle_by_default():
    reset_db(); _seed()
    names = {m['name'] for m in storage.get_all_members()}
    check(names == {'Dad', 'Ellie'}, f"the family is the humans, got {names}")
    check(storage.get_member(storage.ARGYLE_MEMBER_ID),
          "while a direct lookup by id still finds it")


def scenario_a_sender_lookup_can_still_resolve_argyle():
    """The one deliberate exception. Without it Argyle's own messages render
    as "Unknown", which is worse than the leak this fixes."""
    reset_db(); _seed()
    withsys = {m['name'] for m in storage.get_all_members(include_system=True)}
    check('Argyle' in withsys, f"opt-in still returns it, got {withsys}")


def scenario_argyle_is_not_offered_as_an_attendee():
    """The report that started this: Argyle appeared in an occasion's
    "Who's coming" roster with no way to remove it."""
    reset_db(); _seed()
    o = occasions.create('Thanksgiving 2026', '2026-11-26', 'thanksgiving')
    rows = occasions.attendance(o['id'])
    check('Argyle' not in {r['name'] for r in rows},
          f"the assistant is not a guest, got {[r['name'] for r in rows]}")
    check(occasions.headcount(o['id']) == 2,
          f"and is not eating, got {occasions.headcount(o['id'])}")


def scenario_argyle_is_not_in_the_people_config_payload():
    reset_db(); _seed()
    import main
    out = main.get_members()
    check('Argyle' not in {m.get('name') for m in out},
          f"/api/members is the human roster, got {[m.get('name') for m in out]}")


def scenario_every_surface_that_lists_people_gets_the_filtered_roster():
    """The failure mode was never one screen — it was every screen that asks
    the roster who the family is. Spot-check the ones that render names."""
    reset_db(); _seed()
    from services import presence
    from models.schemas import FamilyMember
    storage.add_member(FamilyMember(name='Marta', role='helper').model_dump())

    rosters = {
        'storage.get_all_members': [m['name'] for m in storage.get_all_members()],
        'presence.tracked': [m.get('name') for m in
                             storage.get_all_members() if m.get('role') != 'helper'],
    }
    for where, names in rosters.items():
        check('Argyle' not in names, f"{where} still lists Argyle: {names}")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} system-member scenarios passed")
