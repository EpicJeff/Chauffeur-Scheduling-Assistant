"""Tests for generated NPC opponents (pets arena). The ladder's rungs (tier,
level, xp) are fixed; WHO stands on each rung is generated per roster fetch.
The whole identity derives from the key ('gen:<tier>:<seed8hex>'), so any
opponent ever handed to a client resolves at battle time with no server
state.

Run from chauffeur/:  python tests/test_pet_npc_gen.py
"""
from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import storage, pet_catalog, pet_battle


def test_generation_is_deterministic_from_the_key():
    a = pet_catalog.npc('gen:3:00abc123')
    b = pet_catalog.npc('gen:3:00abc123')
    check(a and a == b, "same key must regenerate the identical opponent")
    c = pet_catalog.npc('gen:3:00abc124')
    check(c and c != a, "a different seed is a different critter")
    check(a['level'] == 10 and a['xp'] == 25, f"tier 3 rung is fixed: {a}")
    check(a['key'] == 'gen:3:00abc123', f"key round-trips: {a['key']}")
    check(a['name'] and a['taunt'] and '{name}' not in a['taunt'],
          f"taunt is filled in: {a.get('taunt')}")


def test_bad_gen_keys_resolve_to_nothing():
    for bad in ('gen:', 'gen:99:00abc123', 'gen:3:zzzz', 'gen:3', 'gen:x:y'):
        check(pet_catalog.npc(bad) is None, f"bad key {bad!r} must be None")
    check(pet_catalog.npc('pebble'), "classic keys still resolve")


def test_roster_covers_the_ladder_with_fresh_faces():
    r = pet_catalog.gen_roster()
    check([n['tier'] for n in r] == [1, 2, 3, 4, 5, 6],
          f"one rung per tier, in order: {[n['tier'] for n in r]}")
    names = [n['name'] for n in r]
    check(len(set(names)) == len(names), f"no name twice in one roster: {names}")
    types_seen = {n['type'] for n in r}
    check(len(types_seen) >= 4,
          f"a roster should show most of the elemental ring, got {types_seen}")
    # Variety is the point: two rosters agreeing on all six names would mean
    # the generator is not generating.
    r2 = pet_catalog.gen_roster()
    check([n['name'] for n in r2] != names or
          [n['key'] for n in r2] != [n['key'] for n in r],
          "two rosters must not be identical")


def test_generated_opponent_fights_end_to_end():
    with storage.db_lock:
        for name, val in list(vars(storage).items()):
            if name.endswith("_table"):
                val.truncate()
    storage.add_member({"id": "k1", "name": "Ada", "role": "child",
                        "color_code": "#3b82f6", "is_child": True})
    pet = storage.create_pet("k1", "Rocket", {'body': 'wedge', 'top': 'horns'},
                             {}, 'ember')['pet']
    npc = pet_catalog.gen_npc(2, 0xBEEF)
    combat = pet_battle.npc_combatant(npc['key'])
    check(combat and combat['name'] == npc['name'] and combat['level'] == 6,
          f"npc_combatant resolves a generated key: {combat}")
    res = storage.run_pet_battle(pet['id'], 'npc:%s' % npc['key'], seed=7)
    check(res.get('battle'), f"battle resolves against a generated NPC: {res}")
    check(res['battle']['opponent_name'] == npc['name'],
          "history snapshots the generated name")
    if res['battle']['winner'] == 'a':
        check(res.get('awarded') == 20, f"tier-2 win pays its rung's xp: {res.get('awarded')}")


def test_missing_gen_spec_falls_back_to_the_classic_six():
    spec = pet_catalog._CATALOG.pop('npc_gen', None)
    try:
        r = pet_catalog.gen_roster()
        check([n['name'] for n in r] == ['Pebble', 'Sprout', 'Puddle',
                                         'Fizz', 'Scorch', 'Monolith'],
              f"old catalogue -> classic roster, got {[n['name'] for n in r]}")
    finally:
        if spec is not None:
            pet_catalog._CATALOG['npc_gen'] = spec


if __name__ == "__main__":
    import traceback
    scenarios = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in scenarios:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(scenarios) - failed}/{len(scenarios)} scenarios passed")
    raise SystemExit(1 if failed else 0)
