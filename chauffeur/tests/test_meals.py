"""Tests for the day's eating plan (meals & provisioning arc M2).

Load-bearing properties, each traceable to docs/meal_design.md §M2:

- Slots are PER-PERSON and ALL-DAY, with a modality (at_home / in_car /
  at_venue) — not one household cook window.
- A passenger eats during a leg; the DRIVER does not. That asymmetry is the
  structural reason the driving parent has no slot, and it must fall out of
  the manifest rather than being special-cased.
- `car_dining` / `venue_dining` are family settings with a permissive default;
  'none' removes that modality's slots wholesale.
- "Nobody can eat" is a first-class finding, not an empty result.
- Silence on an ordinary day (principle 6) — the summary returns [] when the
  day isn't actually constrained.

Run from chauffeur/:  python tests/test_meals.py
"""
import atexit
import datetime
from unittest import mock
import os
import shutil
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="chauffeur_meals_test_")
os.environ["CHAUFFEUR_DATA_DIR"] = _TMP
atexit.register(lambda: shutil.rmtree(_TMP, ignore_errors=True))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import storage, maps, meals  # noqa: E402

DAY = "2026-09-08"
HOME = "1 Home St"


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def reset_db():
    with storage.db_lock:
        for name, val in list(vars(storage).items()):
            if name.endswith("_table"):
                val.truncate()
    storage._distance_mem_cache = None
    # Offline, deterministic travel: 15 min between any two different places.
    maps.get_travel_time_minutes = lambda a, b, *args, **kw: (
        0 if (a or "").lower() == (b or "").lower() else 15)


def _seed_people():
    storage.drivers_table.insert({"id": "d-mom", "name": "Mom", "color_code": "#f00"})
    storage.passengers_table.insert({"id": "p-add", "name": "Addison",
                                     "calendar_ids": ["add@cal"], "hashtags": []})
    storage.passengers_table.insert({"id": "p-ben", "name": "Ben",
                                     "calendar_ids": ["ben@cal"], "hashtags": []})
    storage.ensure_members()
    for m in storage.get_all_members():
        if m.get('driver_id') == 'd-mom':
            storage.update_member(m['id'], {'role': 'parent'})
        elif m.get('passenger_id') in ('p-add', 'p-ben'):
            storage.update_member(m['id'], {'role': 'child', 'is_child': True})


def _member(name):
    return next(m for m in storage.get_all_members() if m.get('name') == name)


def _settings(**over):
    base = {"calendar_ids": ["primary"], "home_location": HOME}
    base.update(over)
    storage.get_settings = lambda: base
    return base


def _ev(eid, title, start, end, loc, cals):
    return {"id": eid, "title": title, "event_type": "standard",
            "start": f"{DAY}T{start}:00", "end": f"{DAY}T{end}:00",
            "location": loc, "calendar_ids": cals}


# --- the core asymmetry -----------------------------------------------------

def scenario_passenger_eats_in_car_driver_does_not():
    """Addison is driven from school to practice; Mom drives her there. The
    gap is the same wall-clock span for both — but Mom spends it driving."""
    reset_db(); _seed_people()
    settings = _settings()
    sched = {
        "events": [
            _ev("school", "School", "08:00", "17:00", "School", ["add@cal"]),
            _ev("practice", "Practice", "17:30", "19:00", "Field", ["add@cal"]),
        ],
        # Mom drives the practice leg.
        "assignments": {"practice": "d-mom"},
        "matched_rules": {},
    }
    add = _member("Addison")
    mom = _member("Mom")

    a_slots = [s for s in meals.eating_slots(add, DAY, sched, settings) if s['meal'] == 'dinner']
    m_slots = [s for s in meals.eating_slots(mom, DAY, sched, settings) if s['meal'] == 'dinner']

    check(a_slots, "the kid being driven has a dinner slot")
    check(a_slots[0]['modality'] == 'in_car',
          f"school -> field is a move, so it is an in-car slot, got {a_slots[0]['modality']}")
    check(not a_slots[0]['is_driving'], "the kid is a passenger")

    # Mom's own commitment is the practice she drives to; her window before it
    # is at home, minus the drive.
    driving = [s for s in m_slots if s['is_driving']]
    check(driving, "the driver's pre-leg window is marked as hers-to-drive")
    check(driving[0]['modality'] == 'at_home',
          "she starts from home, so her window is an at-home one")


def scenario_driver_travel_is_subtracted_and_can_erase_the_slot():
    reset_db(); _seed_people()
    settings = _settings()
    # A 20-minute gap between two events in different places. The passenger
    # gets a slot; the driver spends 15 of those 20 minutes driving.
    sched = {
        "events": [
            _ev("a", "Piano", "16:00", "17:00", "Studio", ["add@cal", "ben@cal"]),
            _ev("b", "Practice", "17:20", "18:30", "Field", ["add@cal", "ben@cal"]),
        ],
        "assignments": {"b": "d-mom"},
        "matched_rules": {},
    }
    add_slots = meals.eating_slots(_member("Addison"), DAY, sched, settings)
    gap = [s for s in add_slots if s['modality'] == 'in_car']
    check(gap and gap[0]['mins'] >= meals.MIN_SLOT_MINS,
          "20-minute inter-event gap is a real in-car slot for a passenger")

    mom_slots = meals.eating_slots(_member("Mom"), DAY, sched, settings)
    tiny = [s for s in mom_slots
            if s['modality'] == 'in_car' and s['is_driving']]
    check(not tiny, "20 min minus a 15 min drive is below the floor — no driver slot")


def scenario_nobody_can_eat_is_a_finding():
    reset_db(); _seed_people()
    settings = _settings()
    # Everyone is booked solid straight through the dinner window.
    sched = {
        "events": [
            _ev("all", "Tournament", "15:00", "21:00", "Field",
                ["add@cal", "ben@cal"]),
        ],
        "assignments": {"all": "d-mom"},
        "matched_rules": {},
    }
    plan = meals.eating_plan(DAY, 'dinner', sched, settings)
    check(plan['nobody_can_eat'], "a solid block through dinner is a finding, not silence")
    check({n['name'] for n in plan['no_slot']} >= {"Addison", "Ben"},
          f"the people with no slot are named, got {plan['no_slot']}")
    lines = meals.plan_summary_lines(plan)
    check(lines and "on the way" in lines[0],
          f"the finding is what triggers route food, got {lines}")


# --- household picture -------------------------------------------------------

def scenario_split_service_and_pack_count():
    reset_db(); _seed_people()
    settings = _settings()
    # Addison eats in the car between school and practice; Ben is home all
    # evening. Two different sittings, one of them packed.
    sched = {
        "events": [
            _ev("school", "School", "08:00", "17:00", "School", ["add@cal"]),
            _ev("practice", "Practice", "17:30", "19:30", "Field", ["add@cal"]),
        ],
        "assignments": {"practice": "d-mom"},
        "matched_rules": {},
    }
    plan = meals.eating_plan(DAY, 'dinner', sched, settings)
    check(plan['packed_count'] >= 1, "someone eating out of the house needs packing")
    add = next(p for p in plan['people'] if p['name'] == 'Addison')
    check(add['first']['modality'] == 'in_car', "Addison's dinner is in the car")
    ben = next(p for p in plan['people'] if p['name'] == 'Ben')
    check(ben['first']['modality'] == 'at_home', "Ben eats at home")
    check(plan['split'], "different times = split service")


def scenario_ordinary_day_says_nothing():
    reset_db(); _seed_people()
    settings = _settings()
    # Nobody has anything on. Everyone is home with the whole evening.
    plan = meals.eating_plan(DAY, 'dinner', {"events": [], "assignments": {},
                                             "matched_rules": {}}, settings)
    check(not plan['split'] and not plan['packed_count'],
          "an empty day is not split and needs no packing")
    check(plan['cook_window_mins'] >= 30, "a wide-open evening is a wide cook window")
    check(meals.plan_summary_lines(plan) == [],
          "silence on an ordinary day — the feature must not become a taskmaster")


def scenario_cook_window_is_prep_time_not_meal_time():
    """The window that matters ends when the packed food has to leave — and it
    starts whenever the cook got home, NOT when the dinner window opens. You
    cook at 4:00 for a 4:30 departure; clipping prep to the meal window would
    erase exactly the time that counts."""
    reset_db(); _seed_people()
    settings = _settings()
    sched = {
        "events": [
            _ev("school", "School", "08:00", "17:00", "School", ["add@cal"]),
            _ev("practice", "Practice", "17:30", "19:30", "Field", ["add@cal"]),
        ],
        "assignments": {"practice": "d-mom"},
        "matched_rules": {},
    }
    plan = meals.eating_plan(DAY, 'dinner', sched, settings)
    check(plan['packed_deadline'], "someone eats away from home, so there IS a deadline")
    check(plan['cook_window_who'] == "Mom",
          f"the window belongs to a cooking-capable adult, got {plan['cook_window_who']}")
    check(plan['cook_window_mins'] > 60,
          f"prep time runs from when she was home, not from 4:30 — got "
          f"{plan['cook_window_mins']} min")
    check(plan['cook_window_mins'] <= meals.PREP_HORIZON_MINS,
          "and it is measured back from when food is needed, not from dawn — "
          f"got {plan['cook_window_mins']} min")
    lines = meals.plan_summary_lines(plan)
    check(not any("to cook" in l for l in lines),
          f"a COMFORTABLE window is not the headline — the split is; got {lines}")
    check(any("out the door by" in l for l in lines),
          f"the deadline is what's stated, got {lines}")


def scenario_long_gap_between_places_is_not_in_the_car():
    """A 2.5-hour gap between school and practice is a trip home, not a drive.
    Calling it in-car would tell the family to pack food they could cook."""
    reset_db(); _seed_people()
    settings = _settings()
    sched = {
        "events": [
            _ev("school", "School", "08:00", "15:00", "School", ["add@cal"]),
            _ev("practice", "Practice", "17:30", "19:00", "Field", ["add@cal"]),
        ],
        "assignments": {}, "matched_rules": {},
    }
    slots = meals.eating_slots(_member("Addison"), DAY, sched, settings)
    dinner = [s for s in slots if s['meal'] == 'dinner']
    check(dinner and dinner[0]['modality'] == 'at_home',
          f"long gap = they went home, got {dinner and dinner[0]['modality']}")

    # Same pair of places, but only 30 minutes apart: now it IS the car.
    sched['events'][0]['end'] = f"{DAY}T17:00:00"
    tight = [s for s in meals.eating_slots(_member("Addison"), DAY, sched, settings)
             if s['meal'] == 'dinner']
    check(tight and tight[0]['modality'] == 'in_car',
          f"a 30-min gap against a 15-min drive is in the car, got "
          f"{tight and tight[0]['modality']}")


# --- household norms are settings, never constants ---------------------------

def scenario_car_dining_none_removes_in_car_slots():
    reset_db(); _seed_people()
    sched = {
        "events": [
            _ev("school", "School", "08:00", "17:00", "School", ["add@cal"]),
            _ev("practice", "Practice", "17:30", "19:00", "Field", ["add@cal"]),
        ],
        "assignments": {"practice": "d-mom"},
        "matched_rules": {},
    }
    permissive = _settings()
    add = _member("Addison")
    check(any(s['modality'] == 'in_car'
              for s in meals.eating_slots(add, DAY, sched, permissive)),
          "default is permissive — a family that eats in the car gets the slot")

    strict = _settings(car_dining='none')
    check(not any(s['modality'] == 'in_car'
                  for s in meals.eating_slots(add, DAY, sched, strict)),
          "car_dining=none removes in-car slots wholesale")


def scenario_dining_level_is_carried_for_m3_matching():
    reset_db(); _seed_people()
    sched = {
        "events": [
            _ev("school", "School", "08:00", "17:00", "School", ["add@cal"]),
            _ev("practice", "Practice", "17:30", "19:00", "Field", ["add@cal"]),
        ],
        "assignments": {}, "matched_rules": {},
    }
    settings = _settings(car_dining='handheld')
    slots = meals.eating_slots(_member("Addison"), DAY, sched, settings)
    in_car = [s for s in slots if s['modality'] == 'in_car']
    check(in_car and in_car[0]['dining_level'] == 'handheld',
          "the slot carries the family's level so M3 can match portability")
    check(meals.dining_setting('car', {'car_dining': 'nonsense'}) == 'full',
          "an unknown value falls back to permissive, never to blocking")


def scenario_venue_slot_when_staying_put():
    reset_db(); _seed_people()
    settings = _settings()
    # Two events at the SAME non-home place with a gap — bleachers time.
    sched = {
        "events": [
            _ev("g1", "Game 1", "16:00", "17:00", "Field", ["add@cal"]),
            _ev("g2", "Game 2", "17:40", "19:00", "Field", ["add@cal"]),
        ],
        "assignments": {}, "matched_rules": {},
    }
    slots = meals.eating_slots(_member("Addison"), DAY, sched, settings)
    venue = [s for s in slots if s['modality'] == 'at_venue']
    check(venue, f"same-location gap is at_venue, got {[s['modality'] for s in slots]}")
    check(venue[0]['where'] == "Field", "and it names where")


# --- shape / honesty ---------------------------------------------------------

def scenario_slots_are_spans_not_timestamps():
    reset_db(); _seed_people()
    settings = _settings()
    sched = {
        "events": [
            _ev("school", "School", "08:00", "17:00", "School", ["add@cal"]),
            _ev("practice", "Practice", "17:30", "19:00", "Field", ["add@cal"]),
        ],
        "assignments": {}, "matched_rules": {},
    }
    slot = meals.eating_slots(_member("Addison"), DAY, sched, settings)[0]
    check('start' in slot and 'end' in slot and slot['mins'] > 0,
          "a slot is a span with a duration")
    check("about" in slot['label'],
          f"the wording is deliberately fuzzy, got {slot['label']}")


def scenario_short_gaps_are_not_meals():
    reset_db(); _seed_people()
    settings = _settings()
    sched = {
        "events": [
            _ev("a", "A", "17:00", "18:00", "Field", ["add@cal"]),
            _ev("b", "B", "18:05", "19:00", "Field", ["add@cal"]),
        ],
        "assignments": {}, "matched_rules": {},
    }
    slots = [s for s in meals.eating_slots(_member("Addison"), DAY, sched, settings)
             if s['meal'] == 'dinner' and s['modality'] == 'at_venue']
    check(not slots, "a 5-minute gap is a scramble, not a meal")


def scenario_derivation_never_writes_schedule_state():
    reset_db(); _seed_people()
    settings = _settings()
    sched = {
        "events": [_ev("school", "School", "08:00", "17:00", "School", ["add@cal"])],
        "assignments": {"school": "d-mom"}, "matched_rules": {},
    }
    import copy
    before = copy.deepcopy(sched)
    meals.eating_plan(DAY, 'dinner', sched, settings)
    check(sched == before,
          "M2 is read-only over solver output (principle 8) — it must not mutate sched")


# --- wiring -----------------------------------------------------------------

def scenario_plan_tool_in_both_stacks_and_rest():
    reset_db(); _seed_people()
    settings = _settings()
    storage.set_cached_schedule({
        "events": [
            _ev("school", "School", "08:00", "17:00", "School", ["add@cal"]),
            _ev("practice", "Practice", "17:30", "19:30", "Field", ["add@cal"]),
        ],
        "assignments": {"practice": "d-mom"}, "matched_rules": {},
        "scheduled_errands": [],
    })
    from services import agent_tools, agent_tools_v2
    v2 = {t['name'] for t in agent_tools_v2.get_available_tools()}
    check('get_eating_plan' in v2, "v2 (widget/Gemma) exposes the plan tool")
    check('get_eating_plan' in agent_tools.TOOL_SCHEMAS
          and 'get_eating_plan' in agent_tools.TOOL_HANDLERS,
          "v1 stack exposes it too — capabilities go in BOTH stacks")

    msg = agent_tools.execute_tool('get_eating_plan', {'target_date': DAY})['message']
    check("Pack" in msg, f"the v1 bridge reaches the same derivation, got {msg}")

    import main
    payload = main.meals_plan(date=DAY)
    check(payload['lines'] and payload['packed_count'] == 1,
          "the REST endpoint returns the plan plus its rendered lines")


def scenario_digest_carries_meal_lines_only_when_constrained():
    reset_db(); _seed_people()
    _settings()
    from services import family_digest
    day = datetime.date.fromisoformat(DAY)

    storage.set_cached_schedule({
        "events": [
            _ev("school", "School", "08:00", "17:00", "School", ["add@cal"]),
            _ev("practice", "Practice", "17:30", "19:30", "Field", ["add@cal"]),
        ],
        "assignments": {"practice": "d-mom"}, "matched_rules": {},
        "scheduled_errands": [],
    })
    digest = family_digest.build_drive_digests(day)
    check(digest['meal_lines'], "a constrained evening reaches the tomorrow digest")
    mom = digest['drivers'].get('d-mom')
    check(mom and any("Pack" in l for l in mom['lines']),
          f"and lands on the driving parent's lines, got {mom and mom['lines']}")

    storage.set_cached_schedule({"events": [], "assignments": {},
                                 "matched_rules": {}, "scheduled_errands": []})
    quiet = family_digest.build_drive_digests(day)
    check(quiet['meal_lines'] == [],
          "an ordinary evening adds nothing to the digest — silence is the default")


def scenario_settings_round_trip_through_the_model():
    reset_db()
    from models.schemas import Settings
    s = Settings(calendar_ids=["primary"])
    check(s.car_dining == 'full' and s.venue_dining == 'full',
          "the shipped default is permissive, so nothing is hidden silently")
    check(meals.dining_setting('car', {}) == 'full', "and absent config reads as permissive")
    check(meals.dining_setting('venue', {'venue_dining': 'snack'}) == 'snack',
          "an explicit restriction is honored")


# --- M3: the repertoire ------------------------------------------------------

def _meal(name, **kw):
    from models.schemas import Meal
    m = Meal(name=name, **kw).model_dump()
    storage.add_meal(m)
    return m


def _tight_evening():
    """Addison eats in the car before practice; everyone else is home."""
    return {
        "events": [
            _ev("school", "School", "08:00", "17:00", "School", ["add@cal"]),
            _ev("practice", "Practice", "17:30", "19:30", "Field", ["add@cal"]),
        ],
        "assignments": {"practice": "d-mom"}, "matched_rules": {},
    }


def scenario_one_number_could_not_express_a_weeknight():
    """The roast and the stir-fry have the same total time and opposite
    verdicts — which is exactly why cook_mins was replaced by four numbers."""
    reset_db(); _seed_people()
    settings = _settings()
    roast = _meal("Roast", finish_mins=8, unattended_mins=90,
                  portability='none', holds_well=True)
    stirfry = _meal("Stir-fry", finish_mins=25, portability='none')

    # A 20-minute window at home.
    ok, _ = meals.meal_fits_window(roast, 20, split=False)
    check(ok, "a 90-minute roast with 8 min hands-on FITS a 20-minute window — "
              "unattended time is not hands-on time")
    ok, why = meals.meal_fits_window(stirfry, 20, split=False)
    check(not ok, f"25 minutes at the stove does not fit 20 minutes ({why})")


def scenario_portability_is_matched_against_the_family_setting():
    reset_db(); _seed_people()
    fork_food = _meal("Chili", portability='utensils_ok', holds_well=True)
    handheld = _meal("Wraps", portability='handheld')
    dinner_plate = _meal("Roast", portability='none')

    full_car = {'modality': 'in_car', 'dining_level': 'full'}
    check(meals.meal_fits_slot(fork_food, full_car)[0],
          "this family eats full meals with forks in the car — chili travels")
    check(meals.meal_fits_slot(handheld, full_car)[0], "so do wraps")
    check(not meals.meal_fits_slot(dinner_plate, full_car)[0],
          "a roast still doesn't travel — that IS physics")

    handheld_car = {'modality': 'in_car', 'dining_level': 'handheld'}
    check(not meals.meal_fits_slot(fork_food, handheld_car)[0],
          "a handheld-only family doesn't get the fork food")
    check(meals.meal_fits_slot(handheld, handheld_car)[0], "but wraps are fine")

    home = {'modality': 'at_home', 'dining_level': 'full'}
    check(all(meals.meal_fits_slot(m, home)[0]
              for m in (fork_food, handheld, dinner_plate)),
          "at home, portability is irrelevant")


def scenario_fit_filter_respects_the_binding_slot_and_split():
    reset_db(); _seed_people()
    settings = _settings()
    _meal("Chili", finish_mins=20, portability='utensils_ok', holds_well=True)
    _meal("Roast", finish_mins=10, unattended_mins=90, portability='none',
          holds_well=True)
    plan = meals.eating_plan(DAY, 'dinner', _tight_evening(), settings)
    res = meals.meals_that_fit(plan)
    names = {m['name'] for m in res['fits']}
    blocked = {m['name']: m['why'] for m in res['blocked']}
    check("Chili" in names, f"chili travels and holds — it fits, got {names}")
    check("Roast" in blocked, "the roast is blocked because someone eats in the car")
    check("travel" in blocked["Roast"], f"and it says why: {blocked['Roast']}")


def scenario_allergies_are_hard_dislikes_are_soft():
    reset_db(); _seed_people()
    settings = _settings()
    add = _member("Addison")
    storage.update_member(add['id'], {'dietary_avoid': ['peanut'],
                                      'dietary_dislike': ['mushroom']})
    _meal("Satay", portability='utensils_ok', finish_mins=10, holds_well=True, tags=['peanut'])
    _meal("Mushroom pasta", portability='utensils_ok', finish_mins=10, holds_well=True, tags=['mushroom'])
    _meal("Chili", portability='utensils_ok', finish_mins=10, holds_well=True, tags=['beef'])

    plan = meals.eating_plan(DAY, 'dinner', _tight_evening(), settings)
    res = meals.meals_that_fit(plan)
    names = [m['name'] for m in res['fits']]
    blocked = {m['name'] for m in res['blocked']}
    check("Satay" in blocked, "an allergy REMOVES the meal entirely")
    check("Mushroom pasta" in names,
          f"a dislike must not remove it — soft means demote, got {names}")
    check(names.index("Chili") < names.index("Mushroom pasta"),
          f"but the disliked one ranks lower, got {names}")


def scenario_rotation_prefers_what_was_not_just_eaten():
    reset_db(); _seed_people()
    settings = _settings()
    import time as _t
    a = _meal("Chili", portability='utensils_ok', finish_mins=10, holds_well=True)
    b = _meal("Tacos", portability='utensils_ok', finish_mins=10, holds_well=True)
    storage.mark_meal_served(a['id'], _t.time())          # had it tonight
    storage.mark_meal_served(b['id'], _t.time() - 20 * 86400)

    plan = meals.eating_plan(DAY, 'dinner', _tight_evening(), settings)
    names = [m['name'] for m in meals.meals_that_fit(plan)['fits']]
    check(names and names[0] == "Tacos",
          f"the one not eaten in three weeks comes first, got {names}")


def scenario_ingredients_drain_fresh_only_and_ordered_drains_nothing():
    reset_db(); _seed_people()
    _settings()
    cooked = _meal("Tacos", ingredients=[
        {'name': 'ground beef', 'kind': 'fresh'},
        {'name': 'tortillas', 'kind': 'fresh'},
        {'name': 'cumin', 'kind': 'staple'},
        {'name': 'salt', 'kind': 'staple'}])
    res = meals.ingredients_to_shopping(cooked)
    check(res['added'] == ['ground beef', 'tortillas'],
          f"only FRESH lines reach the list, got {res['added']}")
    check(set(res['skipped']) == {'cumin', 'salt'},
          "staples are skipped — item CLASS, not item state, so nothing rots")

    lid = storage.ensure_default_shopping_list()['id']
    items = storage.get_shopping_items(lid)
    check(all(i['added_via'] == 'meal' and i['source_meal_id'] == cooked['id']
              for i in items),
          "and they carry their provenance back to the meal")

    again = meals.ingredients_to_shopping(cooked)
    check(again['added'] == [], "re-draining does not duplicate what's open")

    pizza = _meal("Pizza night", source='ordered', vendor="Tony's",
                  ingredients=[{'name': 'large pepperoni', 'kind': 'fresh'}])
    res2 = meals.ingredients_to_shopping(pizza)
    check(res2['added'] == [] and res2.get('reason'),
          f"an ORDERED meal contributes nothing to groceries, got {res2}")


def scenario_a_component_plate_is_ONE_meal_with_substitutable_parts():
    """"Chicken, rice, beans (black/red/pinto), veggies, salad" is one meal,
    not six. Its parts substitute, which the first schema could not express —
    separate lines are AND, options within a line are OR."""
    reset_db(); _seed_people()
    _settings()
    plate = _meal("Chicken plate", ingredients=[
        {'name': 'chicken', 'kind': 'fresh', 'role': 'protein'},
        {'name': 'rice', 'kind': 'staple', 'role': 'starch'},
        {'name': 'beans', 'kind': 'fresh', 'role': 'side',
         'options': ['black', 'red', 'pinto']},
        {'name': 'vegetable', 'kind': 'fresh', 'role': 'vegetable',
         'options': ['carrots', 'green beans', 'broccoli', 'cauliflower', 'corn']},
        {'name': 'salad', 'kind': 'fresh', 'role': 'side', 'optional': True},
    ])
    check(len(storage.get_meals()) == 1, "it is ONE repertoire entry")

    res = meals.ingredients_to_shopping(plate)
    check(res['added'] == ['chicken', 'beans', 'vegetable', 'salad'],
          f"one list item per component, not one per option — got {res['added']}")
    check('rice' in res['skipped'], "the staple starch is skipped as always")

    lid = storage.ensure_default_shopping_list()['id']
    items = {i['name']: i for i in storage.get_shopping_items(lid)}
    check(items['beans']['note'] == "black, red, or pinto",
          f"the alternatives ride along so the shopper picks, got {items['beans']['note']}")
    check("optional" in (items['salad']['note'] or ''),
          "a skippable part says so rather than being silently dropped")
    check(items['vegetable']['note'].endswith("or corn"),
          f"five veg options read as one choice, got {items['vegetable']['note']}")


def scenario_an_open_option_satisfies_its_category():
    """Someone already put 'black beans' on the list, so the plate must not
    add a second 'beans' line on top of it."""
    reset_db(); _seed_people()
    _settings()
    from services.agent_tools_v2 import add_shopping_items
    add_shopping_items("black beans")
    plate = _meal("Chicken plate", ingredients=[
        {'name': 'beans', 'kind': 'fresh', 'options': ['black', 'red', 'pinto']},
        {'name': 'chicken', 'kind': 'fresh'},
    ])
    res = meals.ingredients_to_shopping(plate)
    check(res['added'] == ['chicken'],
          f"the beans category is already satisfied, got {res['added']}")
    check('beans' in res['skipped'], "and it says it skipped it")


def scenario_a_background_trip_is_not_a_commitment():
    """Regression (reported 2026-08-05): two kids away on a trip with nothing
    else on the calendar were reported as having NO GAP TO EAT. A background
    trip runs midnight-to-midnight, so counting it as occupation swallowed the
    whole day. All-day presence is not physical occupation — and someone on a
    trip is not eating at this house at all."""
    reset_db(); _seed_people()
    settings = _settings()
    sched = {
        "events": [{
            "id": "trip", "title": "Grandma's", "event_type": "background_trip",
            "start": f"{DAY}T00:00:00", "end": f"{DAY}T23:59:00",
            "all_day": True, "location": "Away",
            "calendar_ids": ["add@cal", "ben@cal"],
        }],
        "assignments": {}, "matched_rules": {},
    }
    plan = meals.eating_plan(DAY, 'dinner', sched, settings)
    check(not plan['no_slot'],
          f"nobody is trapped by a trip — got no_slot={plan['no_slot']}")
    check({a['name'] for a in plan['away']} == {"Addison", "Ben"},
          f"the travellers are recorded as AWAY, not silently dropped — got {plan['away']}")
    check([p['name'] for p in plan['people']] == ["Mom"],
          "only the people actually home are in the household plan")
    check(not plan['nobody_can_eat'], "and this is not a crisis")
    check(meals.plan_summary_lines(plan) == [],
          f"a quiet evening with two kids away says nothing, got "
          f"{meals.plan_summary_lines(plan)}")

    # The real shape: trips span several days, so the event does NOT start on
    # the day being planned. Commitment gathering only looks at events
    # starting today, so away-detection has to scan the whole range.
    span = dict(sched)
    span['events'] = [{**sched['events'][0],
                       "start": "2026-09-06T00:00:00",
                       "end": "2026-09-11T00:00:00"}]
    mid = meals.eating_plan(DAY, 'dinner', span, settings)
    check({a['name'] for a in mid['away']} == {"Addison", "Ben"},
          f"a multi-day trip covering today still reads as away, got {mid['away']}")

    # ...and the day after it ends, they are home again.
    after = meals.eating_plan("2026-09-12", 'dinner', span, settings)
    check(not after['away'], f"the trip does not follow them home, got {after['away']}")


def scenario_an_all_day_event_does_not_block_eating():
    """"Spirit Week" is a presence marker, not a 24-hour occupation."""
    reset_db(); _seed_people()
    settings = _settings()
    sched = {
        "events": [{
            "id": "spirit", "title": "Spirit Week", "event_type": "standard",
            "start": f"{DAY}T00:00:00", "end": f"{DAY}T23:59:00",
            "all_day": True, "location": "School",
            "calendar_ids": ["add@cal"],
        }],
        "assignments": {}, "matched_rules": {},
    }
    slots = [s for s in meals.eating_slots(_member("Addison"), DAY, sched, settings)
             if s['meal'] == 'dinner']
    check(slots and slots[0]['modality'] == 'at_home',
          f"an all-day marker leaves the evening free, got {slots}")
    plan = meals.eating_plan(DAY, 'dinner', sched, settings)
    check(not plan['no_slot'], "and nobody is reported as unable to eat")
    check(not plan['away'], "an ordinary all-day event does NOT mean away")


def _leftover(**kw):
    from models.schemas import Leftover
    rec = Leftover(date=kw.pop('date', DAY), **kw).model_dump()
    storage.add_leftover(rec)
    return rec


def scenario_leftovers_free_the_cook_window():
    """Chili that already exists needs reheating, not cooking — the app must
    stop holding time for work nobody is going to do."""
    reset_db(); _seed_people()
    settings = _settings()
    chili = _meal("Chili", prep_ahead_mins=20, finish_mins=40,
                  portability='utensils_ok', holds_well=True, needs_ahead='thaw',
                  ingredients=[{'name': 'ground beef', 'kind': 'fresh'},
                               {'name': 'beans', 'kind': 'fresh'}])
    # A 25-minute window: cooking it from scratch is impossible.
    ok, why = meals.meal_fits_window(chili, 25, split=False)
    check(not ok, f"60 min hands-on does not fit 25 ({why})")

    _leftover(meal_id=chili['id'], label="Sunday's chili")
    warmed = meals.apply_leftovers(chili, storage.get_leftovers(DAY)[0])
    check(warmed['finish_mins'] == 10 and warmed['prep_ahead_mins'] == 0,
          f"only the reheat is left, got {warmed['finish_mins']}")
    check(warmed['needs_ahead'] == 'none', "nothing left to thaw — it's already made")
    check(meals.meal_fits_window(warmed, 25, split=False)[0],
          "and now it fits the same 25-minute window")

    res = meals.ingredients_to_shopping(warmed)
    check(res['added'] == [] and 'leftovers' in (res.get('reason') or ''),
          f"already-made food is not shopping, got {res}")


def scenario_partial_leftovers_only_free_their_own_share():
    """"The rice is already made" — the rest still has to be cooked. The
    schema has no per-component times on purpose, so the remainder is an
    estimate, but the point is that time stops being held for the rice."""
    reset_db(); _seed_people()
    _settings()
    plate = _meal("Chicken plate", prep_ahead_mins=20, finish_mins=20,
                  portability='utensils_ok', holds_well=True,
                  ingredients=[{'name': 'chicken', 'kind': 'fresh'},
                               {'name': 'rice', 'kind': 'fresh'},
                               {'name': 'vegetable', 'kind': 'fresh',
                                'options': ['broccoli', 'corn']},
                               {'name': 'salad', 'kind': 'fresh'}])
    lo = _leftover(meal_id=plate['id'], parts=['rice'])
    part = meals.apply_leftovers(plate, lo)
    check(part['leftover'] and not part['leftover_exact'],
          "a partial leftover is flagged as an ESTIMATE, not an exact number")
    check(0 < part['prep_ahead_mins'] < 20,
          f"some but not all prep time is freed, got {part['prep_ahead_mins']}")

    res = meals.ingredients_to_shopping(part)
    check('rice' not in res['added'] and 'rice' in res['skipped'],
          f"the made part is not bought again, got {res}")
    check('chicken' in res['added'], "but the rest still gets shopped for")


def scenario_plain_leftovers_need_no_repertoire_entry():
    reset_db(); _seed_people()
    settings = _settings()
    _leftover(label="Leftovers")
    plan = meals.eating_plan(DAY, 'dinner', _tight_evening(), settings)
    res = meals.meals_that_fit(plan)
    check(not res['empty'], "'we just have leftovers' is a complete answer on its own")
    check(res['fits'] and res['fits'][0]['leftover'],
          f"and it outranks everything, got {[f['name'] for f in res['fits']]}")


def scenario_leftovers_replace_cook_pressure_in_the_summary():
    reset_db(); _seed_people()
    settings = _settings()
    # Genuinely squeezed: the only cooking adult is out from before dawn
    # until 6pm, so there is no window at home ahead of dinner at all.
    sched = {
        "events": [_ev("work", "Long day", "06:20", "18:00", "Office", ["add@cal"])],
        "assignments": {"work": "d-mom"}, "matched_rules": {},
    }
    plain = meals.plan_summary_lines(meals.eating_plan(DAY, 'dinner', sched, settings))
    check(any("cook" in l for l in plain),
          f"without leftovers the tight window is the headline, got {plain}")

    _leftover(label="Sunday's chili")
    withl = meals.plan_summary_lines(meals.eating_plan(DAY, 'dinner', sched, settings))
    check(any("Leftovers tonight" in l for l in withl),
          f"leftovers are stated, got {withl}")
    check(not any("to cook" in l for l in withl),
          f"and the cook-window pressure is DROPPED — manufacturing stress about "
          f"work nobody is doing is the failure mode; got {withl}")


def scenario_leftovers_expire_and_can_be_cleared():
    reset_db(); _seed_people()
    _settings()
    from services.agent_tools_v2 import mark_leftovers, clear_leftovers
    yesterday = (datetime.date.fromisoformat(DAY) - datetime.timedelta(days=1)).isoformat()
    _leftover(date=yesterday, label="Old chili")
    mark_leftovers("", target_date=DAY)
    check(not storage.get_leftovers(yesterday),
          "yesterday's leftovers are not tonight's dinner — they get pruned")
    check(storage.get_leftovers(DAY), "today's stand")

    clear_leftovers(DAY)
    check(not storage.get_leftovers(DAY), "and plans change — clearing works")


def scenario_leftovers_tools_in_both_stacks():
    reset_db(); _seed_people()
    _settings()
    from services import agent_tools, agent_tools_v2
    want = {"mark_leftovers", "clear_leftovers"}
    v2 = {t['name'] for t in agent_tools_v2.get_available_tools()}
    check(want <= v2, f"v2 missing {want - v2}")
    check(want <= set(agent_tools.TOOL_SCHEMAS)
          and want <= set(agent_tools.TOOL_HANDLERS), "v1 stack incomplete")
    agent_tools.execute_tool("mark_leftovers", {"what": "chili", "target_date": DAY})
    check(storage.get_leftovers(DAY), "the v1 bridge writes through")


def scenario_a_plate_can_be_typed_the_way_the_family_says_it():
    """Asked 2026-08-05: "how do I enter my full plate — just like I typed it?"
    Before this, the whole sentence became the meal's NAME. Now the model
    derives a short label and the parts become components."""
    reset_db(); _seed_people()
    storage.get_settings = lambda: {"llm_gemini_api_key": "test-key",
                                    "home_location": HOME}
    typed = ("chicken, rice, beans (black, red, or pinto), veggies (carrots, "
             "green beans, broccoli, cauliflower, corn), potatoes, salad")
    payload = {
        "name": "Chicken plate",
        "prep_ahead_mins": 10, "finish_mins": 25, "unattended_mins": 0,
        "needs_ahead": "thaw", "holds_well": True, "portability": "utensils_ok",
        "source": "prep", "effort": "normal", "serves": 4, "tags": ["chicken"],
        "ingredients": [
            {"name": "chicken", "kind": "fresh", "role": "protein"},
            {"name": "rice", "kind": "staple", "role": "starch"},
            {"name": "beans", "kind": "fresh", "role": "side",
             "options": ["black", "red", "pinto"]},
            {"name": "vegetable", "kind": "fresh", "role": "vegetable",
             "options": ["carrots", "green beans", "broccoli", "cauliflower", "corn"]},
            {"name": "potatoes", "kind": "fresh", "role": "starch"},
            {"name": "salad", "kind": "fresh", "role": "side", "optional": True},
        ],
    }
    with mock.patch('services.model_pools.call_pool_json', return_value=payload):
        meal = meals.create_meal(typed)

    check(meal['name'] == "Chicken plate",
          f"the sentence becomes a short label, not the title — got {meal['name']!r}")
    check(meal['description'] == typed,
          "what they actually typed is kept so they can check it was read right")
    check(len(storage.get_meals()) == 1, "ONE meal, not six")
    beans = next(i for i in meal['ingredients'] if i['name'] == 'beans')
    check(beans['options'] == ["black", "red", "pinto"],
          f"the bracketed alternatives become options, got {beans}")

    res = meals.ingredients_to_shopping(meal)
    check('rice' in res['skipped'], "the staple is skipped")
    check(res['added'].count('beans') == 1 and 'black' not in res['added'],
          f"one beans line, not three — got {res['added']}")


def scenario_a_model_that_echoes_the_description_is_ignored():
    reset_db(); _seed_people()
    storage.get_settings = lambda: {"llm_gemini_api_key": "test-key"}
    typed = "chicken, rice, beans, veggies, salad"
    # A model that just parrots the input has not helped; the guard keeps the
    # raw text rather than pretending a "short name" was produced.
    with mock.patch('services.model_pools.call_pool_json',
                    return_value={"name": typed + " and more", "serves": 4}):
        meal = meals.create_meal(typed)
    check(meal['name'] == typed,
          f"an echo longer than the input is rejected, got {meal['name']!r}")
    check(meal['description'] is None,
          "and no description is stored when nothing was shortened")


# --- M5: plates are composed from typed dishes ------------------------------

def _pantry():
    """What this family actually keeps: a handful of dishes, not 15 meals."""
    ent = _dish("roasted chicken thighs", short_name="chicken", type='entree',
                prep_ahead_mins=5, finish_mins=5, unattended_mins=40,
                holds_well=True, portability='utensils_ok', tags=['chicken'],
                ingredients=[{'name': 'chicken thighs', 'kind': 'fresh'}])
    starches = [_dish(n, short_name=s, type='side', side_type='starch',
                      finish_mins=5, holds_well=True, portability='utensils_ok',
                      ingredients=[{'name': n, 'kind': 'fresh'}])
                for n, s in (("white rice", "rice"),
                             ("roasted russet potatoes", "potatoes"))]
    vegs = [_dish(f"steamed {v}", short_name=v, type='side', side_type='vegetable',
                  finish_mins=8, holds_well=True, portability='utensils_ok',
                  ingredients=[{'name': v, 'kind': 'fresh'}])
            for v in ("carrots", "broccoli", "corn")]
    salad = _dish("green salad", short_name="salad", type='side', side_type='salad',
                  finish_mins=10, portability='utensils_ok',
                  ingredients=[{'name': 'lettuce', 'kind': 'fresh'}])
    fruit = _dish("fresh fruit", short_name="fruit", type='dessert',
                  finish_mins=5, portability='utensils_ok', holds_well=True,
                  ingredients=[{'name': 'fruit', 'kind': 'fresh'}])
    tacos = _dish("tacos", short_name="tacos", type='meal',
                  finish_mins=25, holds_well=True, portability='handheld',
                  tags=['mexican'],
                  ingredients=[{'name': 'tortillas', 'kind': 'fresh'}])
    return {'entree': ent, 'starches': starches, 'vegs': vegs, 'salad': salad,
            'fruit': fruit, 'tacos': tacos}


def scenario_a_plate_is_an_entree_plus_sides_plus_dessert():
    reset_db(); _seed_people()
    _settings(sides_per_meal=2, include_dessert=True)
    p = _pantry()
    storage.set_cached_schedule({"events": [], "assignments": {},
                                 "matched_rules": {}, "scheduled_errands": []})
    dishes = meals.compose_plate(DAY)
    types = [d['type'] for d in dishes]
    check(types.count('side') == 2, f"two sides, as configured — got {types}")
    check(types.count('dessert') == 1, "and the fruit this family always has")
    check(types[0] in ('entree', 'meal'), f"led by a main, got {types}")
    kinds = [d.get('side_type') for d in dishes if d['type'] == 'side']
    check(len(set(kinds)) == 2,
          f"sides spread across kinds rather than two of the same — got {kinds}")


def scenario_the_side_count_is_a_knob_not_a_stored_shape():
    """The old model froze the count at whatever was typed. "Only one veggie
    tonight" and "we want three" both have to be expressible."""
    reset_db(); _seed_people()
    p = _pantry()
    storage.set_cached_schedule({"events": [], "assignments": {},
                                 "matched_rules": {}, "scheduled_errands": []})
    for n in (0, 1, 3):
        s = _settings(sides_per_meal=n, include_dessert=False)
        got = [d for d in meals.compose_plate(DAY, settings=s) if d['type'] == 'side']
        check(len(got) == n, f"asked for {n} sides, got {len(got)}")


def scenario_a_meal_dish_stands_alone():
    reset_db(); _seed_people()
    _settings(sides_per_meal=2, include_dessert=False)
    storage.set_cached_schedule({"events": [], "assignments": {},
                                 "matched_rules": {}, "scheduled_errands": []})
    # Only tacos and sides exist — no entree, so the one-dish meal wins and
    # brings nothing with it.
    tacos = _dish("tacos", type='meal', finish_mins=25, holds_well=True,
                  portability='handheld')
    _dish("green salad", type='side', side_type='salad', finish_mins=10,
          portability='utensils_ok')
    dishes = meals.compose_plate(DAY)
    check([d['id'] for d in dishes] == [tacos['id']],
          f"a 'meal' dish IS the plate — no sides bolted on, got "
          f"{[d['name'] for d in dishes]}")


def scenario_dessert_is_a_family_setting():
    reset_db(); _seed_people()
    p = _pantry()
    storage.set_cached_schedule({"events": [], "assignments": {},
                                 "matched_rules": {}, "scheduled_errands": []})
    on = _settings(sides_per_meal=1, include_dessert=True)
    off = _settings(sides_per_meal=1, include_dessert=False)
    check(any(d['type'] == 'dessert' for d in meals.compose_plate(DAY, settings=on)),
          "families who always have fruit get it")
    check(not any(d['type'] == 'dessert' for d in meals.compose_plate(DAY, settings=off)),
          "families who have nothing after dinner are not offered any")


def scenario_tonight_is_editable_and_then_holds_still():
    reset_db(); _seed_people()
    _settings(sides_per_meal=2, include_dessert=False)
    p = _pantry()
    storage.set_cached_schedule({"events": [], "assignments": {},
                                 "matched_rules": {}, "scheduled_errands": []})
    first = meals.get_or_compose_plate(DAY)
    check(not first['edited'], "an untouched plate is a proposal")

    corn = next(v for v in p['vegs'] if v['short_name'] == 'corn')
    after_add = meals.add_to_plate(DAY, corn['id'])
    check(any(d['id'] == corn['id'] for d in after_add['dishes']),
          "'we've got corn too' adds it")

    drop = after_add['dishes'][1]['id']
    after_rm = meals.remove_from_plate(DAY, drop)
    check(not any(d['id'] == drop for d in after_rm['dishes']),
          "'no salad tonight' removes it")

    again = meals.get_or_compose_plate(DAY)
    check(again['edited'] and [d['id'] for d in again['dishes']]
          == [d['id'] for d in after_rm['dishes']],
          "an edited plate is never re-proposed under the family")

    meals.reset_plate(DAY)
    check(not meals.get_or_compose_plate(DAY)['edited'],
          "and it can be handed back to the composer")


def scenario_leftovers_and_allergies_still_govern_the_plate():
    reset_db(); _seed_people()
    _settings(sides_per_meal=1, include_dessert=False)
    p = _pantry()
    storage.set_cached_schedule({"events": [], "assignments": {},
                                 "matched_rules": {}, "scheduled_errands": []})
    add = _member("Addison")
    storage.update_member(add['id'], {'dietary_avoid': ['mexican']})
    _leftover(dish_ids=[p['starches'][1]['id']])          # the potatoes are made

    dishes = meals.compose_plate(DAY)
    ids = [d['id'] for d in dishes]
    check(p['starches'][1]['id'] in ids,
          "an already-made dish is the obvious thing to serve")
    check(p['tacos']['id'] not in ids,
          "and an allergy still removes a dish outright")


def scenario_plate_timing_uses_the_same_aggregation():
    reset_db(); _seed_people()
    _settings(sides_per_meal=1, include_dessert=False)
    p = _pantry()
    storage.set_cached_schedule({"events": [], "assignments": {},
                                 "matched_rules": {}, "scheduled_errands": []})
    dishes = meals.compose_plate(DAY)
    totals = meals.plate_totals(dishes, DAY)
    hands = sum((d.get('prep_ahead_mins') or 0) + (d.get('finish_mins') or 0)
                for d in dishes)
    check(totals['prep_ahead_mins'] + totals['finish_mins'] == hands,
          "hands-on still sums across the plate")
    check(totals['unattended_mins'] == max((d.get('unattended_mins') or 0)
                                           for d in dishes),
          "and the oven still overlaps rather than adding")


def scenario_migration_types_m4_dishes_and_retires_slot_meals():
    reset_db(); _seed_people(); _settings()
    meal, d = _plate_meal()            # an M4 slot-meal with role-tagged dishes
    res = meals.migrate_slot_meals()
    check(res['retired_meals'] == 1, "the stored combination is retired")
    check(storage.get_dish(d['chicken']['id'])['type'] == 'entree',
          "role=protein became type=entree")
    veg = storage.get_dish(d['veg'][0]['id'])
    check(veg['type'] == 'side' and veg['side_type'] == 'vegetable',
          f"role=vegetable became a vegetable side, got {veg.get('side_type')}")
    check(storage.get_dish(d['rice']['id'])['side_type'] == 'starch',
          "and role=starch became a starch side")
    check(all(dd['id'] for dd in storage.get_dishes()),
          "no dish the family entered is lost — only the grouping goes")


def scenario_extraction_emits_one_dish_per_alternative():
    reset_db(); _seed_people()
    storage.get_settings = lambda: {"llm_gemini_api_key": "test-key",
                                    "home_location": HOME}
    payload = {"dishes": [
        {"name": "roasted chicken thighs", "short_name": "chicken",
         "type": "entree", "finish_mins": 10, "portability": "utensils_ok"},
        {"name": "black beans", "short_name": "beans", "type": "side",
         "side_type": "starch", "finish_mins": 5, "portability": "utensils_ok"},
        {"name": "pinto beans", "short_name": "beans", "type": "side",
         "side_type": "starch", "finish_mins": 5, "portability": "utensils_ok"},
        {"name": "steamed carrots", "short_name": "carrots", "type": "side",
         "side_type": "vegetable", "finish_mins": 8, "portability": "utensils_ok"},
        {"name": "fresh fruit", "short_name": "fruit", "type": "dessert",
         "finish_mins": 5, "portability": "utensils_ok"},
    ]}
    with mock.patch('services.model_pools.call_pool_json', return_value=payload):
        res = meals.add_dishes_from_text(
            "chicken, beans (black or pinto), veggies x 2 (carrots), fruit")
    check(len(res['added']) == 5,
          f"every alternative is its own dish — got {len(res['added'])}")
    check(not storage.get_meals(), "and nothing stores a combination any more")
    by_type = {d['type'] for d in storage.get_dishes()}
    check(by_type == {'entree', 'side', 'dessert'}, f"typed on the way in, got {by_type}")

    # Re-entering the same text reuses rather than duplicating.
    with mock.patch('services.model_pools.call_pool_json', return_value=payload):
        again = meals.add_dishes_from_text("same again")
    check(not again['added'] and len(again['existing']) == 5,
          f"re-entry reuses every dish, got added={len(again['added'])}")


def scenario_the_plate_is_adjustable_by_talking():
    """"We've got corn too" / "no salad tonight" — the intended path is
    Argyle, and it must change TONIGHT without touching the repertoire."""
    reset_db(); _seed_people()
    _settings(sides_per_meal=2, include_dessert=False)
    p = _pantry()
    storage.set_cached_schedule({"events": [], "assignments": {},
                                 "matched_rules": {}, "scheduled_errands": []})
    from services.agent_tools_v2 import (get_tonights_plate, change_tonights_plate)

    before = len(storage.get_dishes())
    said = change_tonights_plate("corn", action="add", target_date=DAY)
    check(said['status'] == 'success' and 'corn' in said['message'].lower(),
          f"adding by name works, got {said['message']}")
    plate = meals.get_or_compose_plate(DAY)
    check(any('corn' in (d.get('short_name') or '') for d in plate['dishes']),
          "and it lands on tonight's plate")
    check(len(storage.get_dishes()) == before,
          "the repertoire is untouched — this is one evening, not a new dish")

    drop = change_tonights_plate("salad", action="remove", target_date=DAY)
    check(drop['status'] == 'success', f"dropping works too, got {drop['message']}")
    plate = meals.get_or_compose_plate(DAY)
    check(not any('salad' in (d.get('short_name') or '') for d in plate['dishes']),
          "salad is off tonight")

    read = get_tonights_plate(DAY)
    check("corn" in read['message'], f"and the read reflects it: {read['message']}")

    missing = change_tonights_plate("caviar", target_date=DAY)
    check(missing['status'] == 'error' and 'caviar' in missing['message'],
          "an unknown dish asks rather than inventing one")


def scenario_already_made_is_a_toggle_not_a_one_way_door():
    """Reported 2026-08-05: once a dish was marked already-made there was no
    way back except removing it from the plate and adding it again."""
    reset_db(); _seed_people()
    _settings(sides_per_meal=2, include_dessert=False)
    p = _pantry()
    storage.set_cached_schedule({"events": [], "assignments": {},
                                 "matched_rules": {}, "scheduled_errands": []})
    rice = p['starches'][0]

    check(meals.toggle_leftover_dish(DAY, rice['id']) is True, "marks it")
    check(meals.dish_is_leftover(DAY, rice['id']), "and it reads as made")
    check(meals.toggle_leftover_dish(DAY, rice['id']) is False, "flips back")
    check(not meals.dish_is_leftover(DAY, rice['id']),
          "so undoing costs one tap, not a remove-and-re-add")
    check(not storage.get_leftovers(DAY),
          "and the emptied record is cleaned up rather than left behind")

    # Un-marking ONE dish out of a multi-dish note leaves the others alone.
    veg = p['vegs'][0]
    _leftover(dish_ids=[rice['id'], veg['id']], label="Sunday's")
    check(meals.unmark_leftover_dish(DAY, rice['id']), "strips just the rice")
    check(not meals.dish_is_leftover(DAY, rice['id']), "rice is back to being made")
    check(meals.dish_is_leftover(DAY, veg['id']),
          "the other dish in the same note is untouched")


def scenario_removing_a_dish_forgets_it_was_already_made():
    """Reported alongside the toggle: the mark outlived the plate, so taking a
    dish off and putting it back brought a struck-through chip with it."""
    reset_db(); _seed_people()
    _settings(sides_per_meal=2, include_dessert=False)
    p = _pantry()
    storage.set_cached_schedule({"events": [], "assignments": {},
                                 "matched_rules": {}, "scheduled_errands": []})
    rice = p['starches'][0]
    meals.add_to_plate(DAY, rice['id'])
    meals.toggle_leftover_dish(DAY, rice['id'])
    check(meals.dish_is_leftover(DAY, rice['id']), "marked")

    meals.remove_from_plate(DAY, rice['id'])
    check(not meals.dish_is_leftover(DAY, rice['id']),
          "taking it off the plate clears the mark — it only means something "
          "while the dish is ON the plate")

    meals.add_to_plate(DAY, rice['id'])
    plate = meals.get_or_compose_plate(DAY)
    totals = meals.plate_totals(plate['dishes'], DAY)
    check(rice['id'] not in (totals.get('leftover_dish_ids') or []),
          "so re-adding gives a normal chip, not a struck-through one")
    check(totals['prep_ahead_mins'] + totals['finish_mins'] > 0,
          "and its cook time is charged again, because it does need making")


def scenario_the_undo_works_by_voice_too():
    reset_db(); _seed_people()
    _settings(sides_per_meal=1, include_dessert=False)
    p = _pantry()
    storage.set_cached_schedule({"events": [], "assignments": {},
                                 "matched_rules": {}, "scheduled_errands": []})
    from services.agent_tools_v2 import mark_leftovers, clear_leftovers
    mark_leftovers("", target_date=DAY, parts="rice")
    check(meals.dish_is_leftover(DAY, p['starches'][0]['id']), "rice marked by voice")

    out = clear_leftovers(target_date=DAY, what="rice")
    check(out['status'] == 'success' and 'rice' in out['message'].lower(),
          f"'the rice isn't made after all' undoes just that, got {out['message']}")
    check(not meals.dish_is_leftover(DAY, p['starches'][0]['id']), "and it took")

    again = clear_leftovers(target_date=DAY, what="rice")
    check(again['status'] == 'success' and "wasn't marked" in again['message'],
          f"undoing twice says so rather than erroring, got {again['message']}")


def scenario_m5_tools_in_both_stacks():
    reset_db(); _seed_people(); _settings()
    _pantry()
    storage.set_cached_schedule({"events": [], "assignments": {},
                                 "matched_rules": {}, "scheduled_errands": []})
    from services import agent_tools, agent_tools_v2
    want = {"get_tonights_plate", "change_tonights_plate", "add_dishes"}
    v2 = {t['name'] for t in agent_tools_v2.get_available_tools()}
    check(want <= v2, f"v2 missing {want - v2}")
    check(want <= set(agent_tools.TOOL_SCHEMAS)
          and want <= set(agent_tools.TOOL_HANDLERS), "v1 stack incomplete")
    out = agent_tools.execute_tool("get_tonights_plate", {"target_date": DAY})
    check(out.get('status') == 'success', f"the v1 bridge reaches it, got {out}")


# --- M4: dishes are the unit of work ----------------------------------------

def _dish(name, **kw):
    from models.schemas import Dish
    d = Dish(name=name, **kw).model_dump()
    storage.add_dish(d)
    return d


def _plate_meal():
    """The family's actual plate, as dishes: chicken + rice + one of three
    beans + one of two vegetables + an optional salad."""
    from models.schemas import Meal, MealSlot
    chicken = _dish("roasted chicken thighs", short_name="chicken", role="protein",
                    prep_ahead_mins=5, finish_mins=5, unattended_mins=40,
                    needs_ahead='thaw', holds_well=True, portability='utensils_ok',
                    ingredients=[{'name': 'chicken thighs', 'kind': 'fresh'}])
    rice = _dish("white rice", short_name="rice", role="starch",
                 prep_ahead_mins=2, finish_mins=0, unattended_mins=20,
                 holds_well=True, portability='utensils_ok',
                 ingredients=[{'name': 'rice', 'kind': 'staple'}])
    beans = [_dish(f"{k} beans", short_name="beans", role="side",
                   finish_mins=5, holds_well=True, portability='utensils_ok',
                   ingredients=[{'name': f'{k} beans', 'kind': 'fresh'}])
             for k in ("black", "red", "pinto")]
    veg = [_dish(f"steamed {v}", short_name="vegetable", role="vegetable",
                 finish_mins=8, holds_well=True, portability='utensils_ok',
                 ingredients=[{'name': v, 'kind': 'fresh'}])
           for v in ("broccoli", "carrots")]
    salad = _dish("green salad", short_name="salad", role="side",
                  finish_mins=10, holds_well=False, portability='utensils_ok',
                  ingredients=[{'name': 'lettuce', 'kind': 'fresh'}])
    meal = Meal(name="Chicken plate", slots=[
        MealSlot(label="chicken", dish_ids=[chicken['id']]),
        MealSlot(label="rice", dish_ids=[rice['id']]),
        MealSlot(label="beans", dish_ids=[b['id'] for b in beans]),
        MealSlot(label="vegetable", dish_ids=[v['id'] for v in veg]),
        MealSlot(label="salad", dish_ids=[salad['id']], optional=True),
    ]).model_dump()
    storage.add_meal(meal)
    return meal, {'chicken': chicken, 'rice': rice, 'beans': beans,
                  'veg': veg, 'salad': salad}


def scenario_a_plate_is_one_dish_per_slot_not_every_option():
    reset_db(); _seed_people(); _settings()
    meal, d = _plate_meal()
    plate = meals.compose_meal(meal)
    names = [x['short_name'] for x in plate['dishes']]
    check(names == ["chicken", "rice", "beans", "vegetable", "salad"],
          f"one dish per slot — got {names}")
    check(len(storage.get_meals()) == 1 and len(storage.get_dishes()) == 8,
          "3 beans x 2 veg is 6 dinners but never 6 meal rows — dishes are stored, "
          f"combinations are not (meals={len(storage.get_meals())}, "
          f"dishes={len(storage.get_dishes())})")


def scenario_timing_aggregates_hands_on_but_not_the_oven():
    reset_db(); _seed_people(); _settings()
    meal, d = _plate_meal()
    plate = meals.compose_meal(meal)
    # prep 5+2, finish 5+0+5+8+10 — one cook, one pair of hands.
    check(plate['prep_ahead_mins'] == 7, f"prep sums, got {plate['prep_ahead_mins']}")
    check(plate['finish_mins'] == 28, f"finish sums, got {plate['finish_mins']}")
    # The oven runs while the rice sits: 40 and 20 overlap, they do not add.
    check(plate['unattended_mins'] == 40,
          f"unattended takes the MAX, not the sum — got {plate['unattended_mins']}")
    check(plate['needs_ahead'] == 'thaw',
          "the strongest lead-time requirement among the dishes wins")


def scenario_a_plate_is_only_as_portable_as_its_worst_dish():
    reset_db(); _seed_people(); _settings()
    meal, d = _plate_meal()
    check(meals.compose_meal(meal)['portability'] == 'utensils_ok',
          "all parts travel, so the plate travels")
    storage.update_dish(d['rice']['id'], {'portability': 'none'})
    check(meals.compose_meal(meal)['portability'] == 'none',
          "one dish that cannot travel grounds the whole plate — weakest link")
    check(not meals.compose_meal(meal)['holds_well'],
          "and holds_well is an AND across the dishes (the salad never held)")


def scenario_per_dish_leftovers_are_exact():
    """The payoff. M3 had to guess proportionally by component count; a dish
    carries its own minutes, so "the rice is made" subtracts exactly the
    rice."""
    reset_db(); _seed_people(); _settings()
    meal, d = _plate_meal()
    before = meals.compose_meal(meal)
    _leftover(meal_id=meal['id'], dish_ids=[d['rice']['id']])
    after = meals.compose_meal(meal, leftovers=storage.get_leftovers(DAY))

    check(after['prep_ahead_mins'] == before['prep_ahead_mins'] - 2,
          f"exactly the rice's 2 prep minutes came off, got {after['prep_ahead_mins']}")
    check(after['leftover_dish_ids'] == [d['rice']['id']], "and it says which")
    check(after['unattended_mins'] == 40,
          "the chicken still needs its oven time — only the rice was made")

    res = meals.ingredients_to_shopping(meal)
    check(not any('rice' == a for a in res['added']),
          f"and nothing is bought for the made dish, got {res['added']}")


def scenario_an_already_made_option_is_the_one_chosen():
    reset_db(); _seed_people(); _settings()
    meal, d = _plate_meal()
    # Pinto beans are in the fridge — that is obviously tonight's bean.
    _leftover(meal_id=meal['id'], dish_ids=[d['beans'][2]['id']])
    plate = meals.compose_meal(meal, leftovers=storage.get_leftovers(DAY))
    bean = next(x for x in plate['dishes'] if x['short_name'] == 'beans')
    check(bean['id'] == d['beans'][2]['id'],
          "a leftover inside a pool is the obvious pick for that slot")


def scenario_pools_rotate_on_their_own():
    reset_db(); _seed_people(); _settings()
    meal, d = _plate_meal()
    import time as _t
    storage.update_dish(d['beans'][0]['id'], {'last_served_at': _t.time()})
    storage.update_dish(d['beans'][1]['id'], {'last_served_at': _t.time() - 9 * 86400})
    plate = meals.compose_meal(meal)
    bean = next(x for x in plate['dishes'] if x['short_name'] == 'beans')
    check(bean['id'] == d['beans'][2]['id'],
          "the never-served bean comes up first; pools rotate without maintenance")


def scenario_shopping_buys_one_platesworth_not_every_alternative():
    reset_db(); _seed_people(); _settings()
    meal, d = _plate_meal()
    res = meals.ingredients_to_shopping(meal)
    beans_bought = [a for a in res['added'] if 'beans' in a]
    check(len(beans_bought) == 1,
          f"one bean, not three — got {beans_bought}")
    check('rice' in res['skipped'], "the staple is still skipped")
    check(any('chicken' in a for a in res['added']), "and the protein is bought")


def scenario_vague_dishes_are_guessed_flagged_and_refinable():
    """Entry must never be gated on answering questions — that is how a
    repertoire stays empty. The model guesses, marks the guess, and the
    family sharpens it later."""
    reset_db(); _seed_people()
    storage.get_settings = lambda: {"llm_gemini_api_key": "test-key",
                                    "home_location": HOME}
    split = {"name": "Chicken plate", "slots": [
        {"label": "potatoes", "optional": False, "dishes": [
            {"name": "roasted potatoes", "short_name": "potatoes", "role": "starch",
             "prep_ahead_mins": 10, "finish_mins": 5, "unattended_mins": 35,
             "portability": "utensils_ok", "holds_well": True,
             "ingredients": [{"name": "potatoes", "kind": "fresh"}],
             "needs_detail": True,
             "detail_question": "Which potatoes, and roasted or mashed?"}]}]}
    with mock.patch('services.model_pools.call_pool_json', return_value=split):
        meal = meals.create_meal_from_dishes("chicken plate with potatoes")
    check(meal['slots'], "the meal saved despite the vagueness — never a gate")
    vague = storage.dishes_needing_detail()
    check(len(vague) == 1 and vague[0]['detail_question'],
          f"the guess is flagged with the question that would fix it, got {vague}")

    refined = {"name": "x", "slots": [{"label": "potatoes", "dishes": [
        {"name": "mashed russet potatoes", "short_name": "potatoes",
         "prep_ahead_mins": 5, "finish_mins": 20, "unattended_mins": 0,
         "portability": "utensils_ok", "holds_well": True,
         "ingredients": [{"name": "russet potatoes", "kind": "fresh"},
                         {"name": "butter", "kind": "staple"}]}]}]}
    with mock.patch('services.model_pools.call_pool_json', return_value=refined):
        out = meals.refine_dish(vague[0]['id'], "russet, mashed")
    check(out['name'] == "mashed russet potatoes" and not out['needs_detail'],
          f"refining re-derives the dish and clears the flag, got {out['name']}")
    check(out['finish_mins'] == 20 and out['unattended_mins'] == 0,
          "and the TIMES change with the cooking method — the reason to ask")
    items = [i['name'] for i in out['ingredients']]
    check("russet potatoes" in items, f"as does the shopping line, got {items}")


def scenario_dish_split_falls_back_rather_than_losing_the_meal():
    reset_db(); _seed_people()
    storage.get_settings = lambda: {"llm_gemini_api_key": "test-key"}
    with mock.patch('services.model_pools.call_pool_json',
                    side_effect=RuntimeError("boom")):
        meal = meals.create_meal_from_dishes("chicken, rice, salad")
    check(meal and meal['name'], "a model failure still saves something")
    check(storage.find_meal_by_name("chicken, rice, salad"),
          "falling back to the flat M3 entry beats losing what they typed")


def scenario_dishes_are_reused_across_meals():
    reset_db(); _seed_people()
    storage.get_settings = lambda: {"llm_gemini_api_key": "test-key"}
    rice_slot = {"label": "rice", "optional": False, "dishes": [
        {"name": "white rice", "short_name": "rice", "finish_mins": 2,
         "unattended_mins": 20, "portability": "utensils_ok",
         "ingredients": [{"name": "rice", "kind": "staple"}]}]}
    for desc in ("chicken and rice", "beef and rice"):
        with mock.patch('services.model_pools.call_pool_json',
                        return_value={"name": desc.title(), "slots": [rice_slot]}):
            meals.create_meal_from_dishes(desc)
    rices = [d for d in storage.get_dishes() if d['name'] == 'white rice']
    check(len(rices) == 1,
          f"rice is rice — defined once and shared, got {len(rices)} copies")
    check(len(storage.get_meals()) == 2, "but they are still two meals")


def _two_veg_meal():
    """"veggies x 2 (carrots, green beans, broccoli)" — TWO slots sharing one
    pool, which is where identity-by-label fell apart."""
    from models.schemas import Meal, MealSlot
    veg = [_dish(f"steamed {v}", short_name="vegetable", role="vegetable",
                 finish_mins=8, holds_well=True, portability='utensils_ok',
                 ingredients=[{'name': v, 'kind': 'fresh'}])
           for v in ("carrots", "green beans", "broccoli")]
    ids = [v['id'] for v in veg]
    meal = Meal(name="Two-veg plate", slots=[
        MealSlot(label="vegetable", dish_ids=list(ids)),
        MealSlot(label="vegetable", dish_ids=list(ids)),
    ]).model_dump()
    storage.add_meal(meal)
    return meal, veg


def scenario_chips_name_the_option_not_the_category():
    """Regression (reported 2026-08-05): "roasted potatoes (red, russet,
    yellow)" made three dishes that all shared short_name "potatoes", so every
    chip read "potatoes" and you could not tell which was selected."""
    reset_db(); _seed_people(); _settings()
    from models.schemas import Meal, MealSlot
    spuds = [_dish(f"roasted {k} potatoes", short_name="potatoes", role="starch",
                   prep_ahead_mins=10, finish_mins=5, unattended_mins=35,
                   portability='utensils_ok', holds_well=True,
                   ingredients=[{'name': f'{k} potatoes', 'kind': 'fresh'}])
             for k in ("red", "russet", "yellow")]
    solo = _dish("white rice", short_name="rice", finish_mins=2,
                 portability='utensils_ok', holds_well=True)
    meal = Meal(name="Plate", slots=[
        MealSlot(label="potatoes", dish_ids=[s['id'] for s in spuds]),
        MealSlot(label="rice", dish_ids=[solo['id']]),
    ]).model_dump()
    storage.add_meal(meal)

    plate = meals.compose_meal(meal)
    chips = {d['_slot']: d['_chip'] for d in plate['dishes']}
    spud_chip = next(v for k, v in chips.items() if 'potato' in v)
    check(spud_chip != "potatoes",
          f"the chip must distinguish the option, got {spud_chip!r}")
    check(any(w in spud_chip for w in ("red", "russet", "yellow")),
          f"it names the variety, got {spud_chip!r}")
    check("potatoes" in spud_chip,
          f"and keeps the noun so 'red' alone is not the whole chip, got {spud_chip!r}")
    rice_chip = next(v for k, v in chips.items() if 'rice' in v)
    check(rice_chip == "rice",
          f"a single-option slot still shows the family's own word, got {rice_chip!r}")

    # Every option in the pool gets its own distinct chip.
    labels = {meals._chip_label(s, spuds) for s in spuds}
    check(len(labels) == 3, f"all three read differently, got {labels}")

    # The label has to read like something a person would say across the
    # shapes these pools actually take.
    def _pool(names, short):
        return [{'id': f'x{i}', 'name': n, 'short_name': short}
                for i, n in enumerate(names)]
    cases = [
        # short_name is the food itself -> keep it, drop the shared method
        (["roasted red potatoes", "roasted russet potatoes"], "potatoes",
         ["red potatoes", "russet potatoes"]),
        # short_name is a CATEGORY, not a word in the name -> never glue it on
        (["steamed carrots", "steamed broccoli"], "vegetable",
         ["carrots", "broccoli"]),
        # the noun sits mid-name -> word ORDER must survive
        (["grilled chicken thighs", "baked chicken breast"], "chicken",
         ["grilled chicken thighs", "baked chicken breast"]),
    ]
    for names, short, expect in cases:
        pool = _pool(names, short)
        got = [meals._chip_label(d, pool) for d in pool]
        check(got == expect, f"{short}: expected {expect}, got {got}")


def scenario_enumerated_options_are_not_flagged_as_vague():
    """Same report: one of the three potato options carried a "?" asking which
    type and how cooked — when the description already said roasted AND listed
    the varieties. Options in a slot are variants of one thing, so a lone
    flag among clean siblings is model noise."""
    reset_db(); _seed_people()
    storage.get_settings = lambda: {"llm_gemini_api_key": "test-key",
                                    "home_location": HOME}
    def spud(kind, vague=False):
        d = {"name": f"roasted {kind} potatoes", "short_name": "potatoes",
             "role": "starch", "prep_ahead_mins": 10, "finish_mins": 5,
             "unattended_mins": 35, "portability": "utensils_ok",
             "holds_well": True,
             "ingredients": [{"name": f"{kind} potatoes", "kind": "fresh"}]}
        if vague:
            d.update({"needs_detail": True,
                      "detail_question": "Which potatoes, and how cooked?"})
        return d
    split = {"name": "Chicken plate", "slots": [
        {"label": "potatoes", "optional": False,
         "dishes": [spud("red"), spud("russet", vague=True), spud("yellow")]}]}
    with mock.patch('services.model_pools.call_pool_json', return_value=split):
        meals.create_meal_from_dishes(
            "roasted potatoes (red, russet, yellow)")
    check(not storage.dishes_needing_detail(),
          f"a lone flag among clean siblings is cleared, got "
          f"{[d['name'] for d in storage.dishes_needing_detail()]}")

    # But a genuinely vague single dish still asks.
    reset_db(); _seed_people()
    storage.get_settings = lambda: {"llm_gemini_api_key": "test-key"}
    lone = {"name": "roasted potatoes", "short_name": "potatoes",
            "needs_detail": True, "detail_question": "Which potatoes?",
            "portability": "utensils_ok"}
    with mock.patch('services.model_pools.call_pool_json',
                    return_value={"name": "Plate", "slots": [
                        {"label": "potatoes", "dishes": [lone]}]}):
        meals.create_meal_from_dishes("chicken and potatoes")
    check(len(storage.dishes_needing_detail()) == 1,
          "a single unspecified dish still asks — the guard is about siblings, "
          "not about never asking")


def scenario_a_stale_detail_flag_does_not_survive_dish_reuse():
    """Regression (reported 2026-08-05): russet potatoes ALWAYS showed a "?".
    The sibling rule cleaned freshly-extracted dishes, but dishes are REUSED —
    a row saved with the flag before the rule existed came back flagged on
    every re-entry, and no amount of re-typing the meal would clear it."""
    reset_db(); _seed_people(); _settings()
    from models.schemas import Meal, MealSlot
    # A dish already in storage carrying the old flag.
    russet = _dish("roasted russet potatoes", short_name="potatoes",
                   portability='utensils_ok', holds_well=True, finish_mins=5,
                   needs_detail=True,
                   detail_question="Which potatoes, and how cooked?")
    red = _dish("roasted red potatoes", short_name="potatoes",
                portability='utensils_ok', holds_well=True, finish_mins=5)

    meal = Meal(name="Plate", slots=[
        MealSlot(label="potatoes", dish_ids=[red['id'], russet['id']])]).model_dump()
    storage.add_meal(meal)

    # READ path: the "?" is gone immediately, without re-entering the meal.
    plate = meals.compose_meal(meal, prefer={
        meals.slot_key(meal['slots'][0], 0): russet['id']})
    chip = plate['dishes'][0]
    check(chip['id'] == russet['id'], "russet is the one on the plate")
    check(not chip['needs_detail'],
          "a clean sibling makes the stale flag moot on READ — nobody should "
          "have to re-enter a meal to clear it")

    # And the repair persists once the slot is normalized.
    check(meals.normalize_slot_detail([red['id'], russet['id']]) == 1,
          "the stored row is repaired too")
    check(not storage.get_dish(russet['id'])['needs_detail'],
          "so it stays clean")


def scenario_reuse_matches_exactly_and_never_merges_dishes():
    reset_db(); _seed_people(); _settings()
    _dish("roasted russet potatoes", short_name="potatoes",
          portability='utensils_ok', finish_mins=5)
    check(storage.find_dish_for_reuse("potatoes") is None,
          "a generic 'potatoes' must NOT bind to the russet dish and inherit "
          "its times, ingredients and flags")
    check(storage.find_dish_for_reuse("roasted russet potatoes") is not None,
          "an exact name still reuses — rice is rice")
    # The agent's fuzzy lookup is deliberately still fuzzy.
    check(storage.find_dish_by_name("potatoes") is not None,
          "but 'the potatoes' still resolves when someone says it out loud")


def scenario_two_slots_sharing_a_label_stay_independent():
    """Regression (reported 2026-08-05): "veggies x 2" gave two chips that
    fought — one pick moved both, one wouldn't cycle, and sometimes a chip
    vanished. Slot identity was the LABEL, and both slots were 'vegetable'."""
    reset_db(); _seed_people(); _settings()
    meal, veg = _two_veg_meal()
    import main

    plate = meals.compose_meal(meal)
    check(len(plate['dishes']) == 2,
          f"both helpings render — neither disappears, got {len(plate['dishes'])}")
    slots = [d['_slot'] for d in plate['dishes']]
    check(len(set(slots)) == 2,
          f"the two slots have DISTINCT identities, got {slots}")
    check(plate['dishes'][0]['id'] != plate['dishes'][1]['id'],
          "and they pick two DIFFERENT vegetables, not the same one twice")

    # Cycling the first must not move the second.
    first, second = plate['dishes'][0], plate['dishes'][1]
    after = main.swap_plate_dish(meal['id'], swap=first['_slot'],
                                 after=first['id'], date=DAY)
    a, b = after['dishes'][0], after['dishes'][1]
    check(a['id'] != first['id'], "the tapped chip moved")
    check(b['id'] == second['id'], "the other chip did NOT move")
    check(a['id'] != b['id'], "and they still differ")


def scenario_cycling_skips_what_the_sibling_slot_is_showing():
    reset_db(); _seed_people(); _settings()
    meal, veg = _two_veg_meal()
    import main
    plate = meals.compose_meal(meal)
    first, second = plate['dishes'][0], plate['dishes'][1]

    # Cycle the first slot through every option; it must never land on
    # whatever the second slot is currently showing.
    cur = first['id']
    for _ in range(len(veg) + 1):
        out = main.swap_plate_dish(meal['id'], swap=first['_slot'], after=cur, date=DAY)
        got = next(d for d in out['dishes'] if d['_slot'] == first['_slot'])
        other = next(d for d in out['dishes'] if d['_slot'] != first['_slot'])
        check(got['id'] != other['id'],
              "cycling never lands on the dish the other helping is using")
        check(other['id'] == second['id'], "and the other helping stays put")
        cur = got['id']


def scenario_a_single_option_slot_reports_nothing_to_cycle():
    reset_db(); _seed_people(); _settings()
    meal, d = _plate_meal()
    plate = meals.compose_meal(meal)
    chicken = next(x for x in plate['dishes'] if x['_slot'])
    solo = next(x for x in plate['dishes'] if x['_pool'] == 1)
    check(meals.next_in_pool(meal, solo['_slot'], solo['id']) is None,
          "a slot with one dish has nothing to cycle to")


def scenario_legacy_slots_get_ids_backfilled():
    """Meals saved before slots had ids are exactly the rows most likely to
    hit the collision, so they are migrated on first read."""
    reset_db(); _seed_people(); _settings()
    from models.schemas import Meal
    veg = [_dish(f"steamed {v}", short_name="vegetable", finish_mins=8,
                 portability='utensils_ok', holds_well=True) for v in ("a", "b")]
    meal = Meal(name="Legacy").model_dump()
    # Hand-write slots the old way: no ids, duplicate labels.
    meal['slots'] = [{'label': 'vegetable', 'dish_ids': [v['id'] for v in veg],
                      'optional': False},
                     {'label': 'vegetable', 'dish_ids': [v['id'] for v in veg],
                      'optional': False}]
    storage.add_meal(meal)

    plate = meals.compose_meal(storage.get_meal(meal['id']))
    check(len({d['_slot'] for d in plate['dishes']}) == 2,
          "the legacy rows get distinct slot identities")
    stored = storage.get_meal(meal['id'])
    check(all(s.get('id') for s in stored['slots']),
          "and the backfill is PERSISTED, not recomputed every read")


def scenario_swapping_a_chip_sticks_for_the_day_only():
    reset_db(); _seed_people(); _settings()
    meal, d = _plate_meal()
    import main
    first = meals.compose_meal(meal)
    bean = next(x for x in first['dishes'] if x['short_name'] == 'beans')

    # Swap by SLOT ID, not label — labels repeat ("veggies x 2").
    swapped = main.swap_plate_dish(meal['id'], swap=bean['_slot'],
                                   after=bean['id'], date=DAY)
    new_bean = next(x for x in swapped['dishes'] if x['_slot'] == bean['_slot'])
    check(new_bean['id'] != bean['id'], "tapping the chip moves to the next option")
    check(new_bean['id'] in [b['id'] for b in d['beans']],
          "and stays inside that slot's own pool")

    again = meals.compose_meal(meal, prefer=meals.get_choices(DAY, meal['id']))
    check(next(x for x in again['dishes'] if x['short_name'] == 'beans')['id']
          == new_bean['id'], "the pick sticks for the day")
    check(not meals.get_choices("2099-01-01", meal['id']),
          "but it is a same-day preference, not a permanent edit")

    # Wraps around rather than dead-ending on the last option.
    cur = new_bean['id']
    for _ in range(len(d['beans'])):
        cur = meals.next_in_pool(meal, bean['_slot'], cur)
    check(cur == new_bean['id'], "cycling the pool returns to where it started")


def scenario_deleting_a_dish_does_not_leave_a_dangling_slot():
    reset_db(); _seed_people(); _settings()
    meal, d = _plate_meal()
    import main
    main.remove_dish(d['salad']['id'])
    after = storage.get_meal(meal['id'])
    labels = [s['label'] for s in after['slots']]
    check('salad' not in labels,
          f"the emptied slot goes with the dish, got {labels}")
    check(all(s['dish_ids'] for s in after['slots']),
          "and no slot is left pointing at nothing")
    check(meals.compose_meal(after)['dishes'], "the meal still composes")


def scenario_metadata_comes_from_the_name_alone():
    reset_db(); _seed_people()
    storage.get_settings = lambda: {"llm_gemini_api_key": "test-key",
                                    "home_location": HOME}
    payload = {"prep_ahead_mins": 10, "finish_mins": 15, "unattended_mins": 0,
               "needs_ahead": "thaw", "holds_well": True,
               "portability": "utensils_ok", "source": "prep", "effort": "easy",
               "serves": 4, "tags": ["beef", "mexican"],
               "ingredients": [{"name": "ground beef", "kind": "fresh"},
                               {"name": "Ground Beef", "kind": "fresh"},
                               {"name": "cumin", "kind": "staple"}]}
    with mock.patch('services.model_pools.call_pool_json', return_value=payload):
        meal = meals.create_meal("tacos")
    check(meal['finish_mins'] == 15 and meal['needs_ahead'] == 'thaw',
          "the human supplied only a name; the model supplied the rest")
    check(len(meal['ingredients']) == 2, "duplicate ingredients collapse")
    check('steps' not in meal and 'instructions' not in meal,
          "NO STEPS, EVER — that's the line between this and a recipe box")


def scenario_a_failed_enrichment_still_saves_the_meal():
    reset_db(); _seed_people()
    storage.get_settings = lambda: {"llm_gemini_api_key": "test-key"}
    with mock.patch('services.model_pools.call_pool_json',
                    side_effect=RuntimeError("boom")):
        meal = meals.create_meal("mystery casserole")
    check(meal and meal['name'] == "mystery casserole",
          "failing to save a meal someone just named is worse than a rough one")
    check(storage.find_meal_by_name("mystery casserole"), "and it persisted")

    storage.get_settings = lambda: {}
    meal2 = meals.create_meal("no key meal")
    check(meal2['name'] == "no key meal", "no API key still saves a plain entry")


def scenario_morning_note_only_when_a_head_start_is_needed():
    reset_db(); _seed_people()
    settings = _settings()
    storage.set_cached_schedule(_tight_evening())
    _meal("Chili", portability='utensils_ok', finish_mins=15, needs_ahead='thaw',
          holds_well=True)
    note = meals.morning_prep_note(DAY)
    check(note and "thaw" in note, f"the thaw becomes a MORNING action, got {note}")

    reset_db(); _seed_people(); _settings()
    storage.set_cached_schedule(_tight_evening())
    _meal("Pasta", portability='utensils_ok', finish_mins=15, needs_ahead='none',
          holds_well=True)
    check(meals.morning_prep_note(DAY) is None,
          "nothing needing a head start = nothing said")


def scenario_empty_repertoire_and_nothing_fitting_are_different_answers():
    reset_db(); _seed_people()
    settings = _settings()
    storage.set_cached_schedule(_tight_evening())
    from services.agent_tools_v2 import suggest_dinner
    msg = suggest_dinner(DAY)['message']
    check("repertoire yet" in msg, f"empty repertoire asks to be filled: {msg}")

    _meal("Roast", portability='none', finish_mins=10)
    msg2 = suggest_dinner(DAY)['message']
    check("Nothing in the repertoire fits" in msg2,
          f"a full repertoire with no fit says so, with a reason: {msg2}")
    check(msg2 != msg, "the two answers must not be the same")


def scenario_m3_tools_in_both_stacks():
    reset_db(); _seed_people()
    _settings()
    storage.set_cached_schedule(_tight_evening())
    from services import agent_tools, agent_tools_v2
    want = {"suggest_dinner", "add_meal_to_repertoire",
            "add_meal_ingredients_to_list", "mark_meal_served"}
    v2 = {t['name'] for t in agent_tools_v2.get_available_tools()}
    check(want <= v2, f"v2 missing {want - v2}")
    check(want <= set(agent_tools.TOOL_SCHEMAS)
          and want <= set(agent_tools.TOOL_HANDLERS), "v1 stack incomplete")

    storage.get_settings = lambda: {"home_location": HOME}   # no LLM key
    agent_tools.execute_tool("add_meal_to_repertoire", {"name": "Chili"})
    check(storage.find_meal_by_name("Chili"), "the v1 bridge writes through")
    res = agent_tools.execute_tool("mark_meal_served", {"meal_name": "Chili"})
    check(storage.find_meal_by_name("Chili")['last_served_at'],
          f"and rotation is recorded, got {res}")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} meal-plan scenarios passed")
