"""Routine item steps, descriptions and photos — the item's INSIDE.

"Pack backpack" hiding five real things was the failure mode routines were
built to prevent: the reminder fired and the water bottle still got
forgotten. Load-bearing properties:

  1. **One level, inline.** Steps live ON the item ([{'id','title','emoji'}]),
     never as a reference to another routine or a list — they reset with the
     routine's day, and a kid tablet has no room for a graph.
  2. **The ITEM is the unit.** Steps mint no XP and no points; completing the
     last step completes the item THROUGH set_routine_check, so XP, the day
     bonus and the streak fire exactly once, exactly as a direct tap.
  3. **Wholly done or not done.** A half-stepped item is unchecked; unticking
     any step untucks the item (its siblings keep their ticks). Tapping the
     parent row carries all steps with it, both directions.
  4. **Photos and descriptions ride along** — routine items and shopping
     items take a media id from the generic photo endpoint.

Run from chauffeur/:  python tests/test_routine_steps.py
"""
import datetime

from harness import check  # noqa: F401

from services import storage

TODAY = datetime.date.today().isoformat()


def _seed_member():
    storage.members_table.truncate()
    storage.routines_table.truncate()
    storage.routine_checks_table.truncate()
    storage.routine_step_checks_table.truncate()
    storage.add_member({"id": "emma", "name": "Emma", "role": "child"})


def _mk_routine(steps=None):
    import main
    req = main.RoutineRequest(
        member_id="emma", title="Pack backpack", emoji="🎒",
        steps=steps if steps is not None else [
            {"title": "Work folder"}, {"title": "Snack", "emoji": "🍎"},
            {"title": "Water bottle"}],
        description="Everything for school")
    return main.create_routine(req)


def scenario_steps_round_trip_with_server_ids():
    import main
    _seed_member()
    item = _mk_routine()
    check(len(item['steps']) == 3 and all(s['id'] for s in item['steps']),
          f"steps saved, server assigned ids: {item['steps']}")
    check(item['description'] == "Everything for school", "description rides along")
    ids_before = [s['id'] for s in item['steps']]
    main.edit_routine(item['id'], main.RoutineRequest(
        member_id="emma", title="Pack backpack",
        steps=[{"id": ids_before[0], "title": "Work folder"},
               {"title": "Laptop"}]))
    after = next(r for r in storage.get_routines("emma") if r['id'] == item['id'])
    check(after['steps'][0]['id'] == ids_before[0] and after['steps'][1]['id'],
          "an edit keeps existing step ids and mints new ones")
    try:
        main.create_routine(main.RoutineRequest(
            member_id="emma", title="Too much",
            steps=[{"title": f"s{i}"} for i in range(13)]))
        check(False, "13 steps must be refused")
    except Exception as e:
        check('12' in str(getattr(e, 'detail', e)), "the cap says its number")


def scenario_the_last_step_completes_the_item_once():
    import main
    _seed_member()
    item = _mk_routine()
    sids = [s['id'] for s in item['steps']]
    for sid in sids[:2]:
        res = main.check_routine_step(item['id'], main.RoutineStepCheckRequest(
            member_id="emma", step_id=sid))
        check(res['item_checked'] is False, "half-stepped is NOT done")
    day = storage.routines_for_day("emma", TODAY)
    check(not day[0]['checked'] and set(day[0]['steps_checked']) == set(sids[:2]),
          f"the day view carries the step ticks: {day[0]}")

    res = main.check_routine_step(item['id'], main.RoutineStepCheckRequest(
        member_id="emma", step_id=sids[2]))
    check(res['item_checked'] is True, "the last step finishes the item")
    check(storage.routines_for_day("emma", TODAY)[0]['checked'],
          "and the item check is the real one streaks read")

    # XP fired once, through set_routine_check — steps mint nothing extra.
    xp_rows = [r for r in storage.pets_xp_rows("emma")
               if r.get('kind') == 'routine' and r.get('ref_id') == item['id']] \
        if hasattr(storage, 'pets_xp_rows') else None
    if xp_rows is not None:
        check(len(xp_rows) == 1, f"one XP grant for the item, none per step: {xp_rows}")

    res = main.check_routine_step(item['id'], main.RoutineStepCheckRequest(
        member_id="emma", step_id=sids[0], checked=False))
    check(res['item_checked'] is False, "unticking a step untucks the item")
    day = storage.routines_for_day("emma", TODAY)
    check(not day[0]['checked'] and set(day[0]['steps_checked']) == set(sids[1:]),
          "…while its sibling steps keep their ticks")


def scenario_the_parent_row_carries_its_steps():
    import main
    _seed_member()
    item = _mk_routine()
    main.check_routine(item['id'], main.RoutineCheckRequest(member_id="emma",
                                                           checked=True))
    day = storage.routines_for_day("emma", TODAY)
    check(day[0]['checked'] and len(day[0]['steps_checked']) == 3,
          "ticking the item ticks every step (big-motion forgiveness)")
    main.check_routine(item['id'], main.RoutineCheckRequest(member_id="emma",
                                                           checked=False))
    day = storage.routines_for_day("emma", TODAY)
    check(not day[0]['checked'] and not day[0].get('steps_checked'),
          "unticking clears them for a fresh start")


def scenario_wrong_member_and_wrong_step_are_refused():
    import main
    _seed_member()
    storage.add_member({"id": "jack", "name": "Jack", "role": "child"})
    item = _mk_routine()
    sid = item['steps'][0]['id']
    check(storage.set_routine_step_check(item['id'], "jack", TODAY, sid, True) is None,
          "another kid's tap is refused")
    check(storage.set_routine_step_check(item['id'], "emma", TODAY, "nope", True) is None,
          "an unknown step id is refused")


def scenario_copy_carries_the_inside_but_never_the_ticks():
    import main
    _seed_member()
    storage.add_member({"id": "jack", "name": "Jack", "role": "child"})
    item = _mk_routine()
    main.check_routine_step(item['id'], main.RoutineStepCheckRequest(
        member_id="emma", step_id=item['steps'][0]['id']))
    main.copy_routines(main.RoutineCopyRequest(from_member_id="emma",
                                               to_member_id="jack"))
    jacks = storage.get_routines("jack")
    check(len(jacks) == 1 and len(jacks[0]['steps']) == 3
          and jacks[0]['description'] == "Everything for school",
          "the copy carries steps and description")
    day = storage.routines_for_day("jack", TODAY)
    check(not day[0].get('steps_checked'),
          "…and none of Emma's ticks (histories stay apart)")


def scenario_photos_land_in_the_media_store():
    import main
    _seed_member()
    # A 1x1 PNG, the smallest real image there is.
    png = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
           "AAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
    saved = main.upload_media_photo({"data_url": png})
    check(saved.get('id') and saved.get('url', '').startswith('/api/media/'),
          f"the generic photo endpoint stores and serves: {saved}")
    item = _mk_routine()
    main.edit_routine(item['id'], main.RoutineRequest(
        member_id="emma", title="Pack backpack", image_id=saved['id']))
    after = next(r for r in storage.get_routines("emma") if r['id'] == item['id'])
    check(after['image_id'] == saved['id'], "a routine item wears it")

    storage.shopping_lists_table.truncate()
    storage.shopping_items_table.truncate()
    it = main.create_shopping_item(main.ShoppingItemRequest(
        name="That sauce", image_id=saved['id']))
    check(it['image_id'] == saved['id'], "a shopping item wears it too")
    main.patch_shopping_item(it['id'], main.ShoppingItemPatch(image_id=""))
    check(storage.get_shopping_item(it['id'])['image_id'] is None,
          "and an empty PATCH clears it")
    try:
        main.create_shopping_item(main.ShoppingItemRequest(
            name="Evil", image_id="../../etc/passwd"))
        check(False, "a non-media id must be refused")
    except Exception as e:
        check('image' in str(getattr(e, 'detail', e)).lower(), "with a clear refusal")


def scenario_the_hand_paths_exist():
    import os
    tpl = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'templates')
    routines = open(os.path.join(tpl, 'routines.html'), encoding='utf-8').read()
    check('editItem.steps' in routines and 'Add step' in routines
          and 'uploadItemPhoto' in routines and 'editItem.description' in routines,
          "the routine editor edits steps, description and photo")
    app = open(os.path.join(tpl, 'app.html'), encoding='utf-8').read()
    check('kidStepRows' in app and 'toggleRoutineStep' in app,
          "kid My Day draws and ticks steps")
    check('firstOpen.image_id' in app and 'firstOpen.description' in app,
          "the hero card wears the photo and the description")
    lanes = open(os.path.join(tpl, 'components', 'routine_lanes.html'),
                 encoding='utf-8').read()
    check('toggleRoutineStepCheck' in lanes and 'it.steps_checked' in lanes,
          "the wall panel lanes tick steps too")
    shop = open(os.path.join(tpl, 'components', 'shopping_lists.html'),
                encoding='utf-8').read()
    check('attachItemPhoto' in shop and 'imgPreview' in shop,
          "shopping items attach and preview a photo")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)
