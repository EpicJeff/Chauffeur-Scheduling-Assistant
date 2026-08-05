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
