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
    seed_categories()
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


def scenario_a_plate_is_composed_from_the_familys_own_blocks():
    """What used to be "an entree plus two sides plus a dessert" is now
    whatever the family said their plate is. Same shape here, said in their
    words: one protein, one vegetable, one starch, something sweet."""
    reset_db(); _seed_people()
    cats = {c['name']: c for c in storage.get_dish_categories()}
    cats['something sweet']['min_per_plate'] = 1
    storage.save_dish_category(cats['something sweet'])
    p = _pantry()
    storage.set_cached_schedule({"events": [], "assignments": {},
                                 "matched_rules": {}, "scheduled_errands": []})
    dishes = meals.compose_plate(DAY)

    def in_cat(name):
        cid = category_id(name)
        return [d for d in dishes if cid in (d.get('category_ids') or [])]

    check(len(in_cat('protein')) == 1, f"one protein, got {[d['name'] for d in dishes]}")
    check(len(in_cat('vegetables')) == 1, "one vegetable")
    check(len(in_cat('starches/carbs')) == 1, "one starch")
    check(len(in_cat('something sweet')) == 1, "and the fruit this family always has")
    check(dishes[0]['type'] == 'meal'
          or category_id('protein') in (dishes[0].get('category_ids') or []),
          f"led by the first block the family asked for, got {dishes[0]['name']}")


def scenario_the_side_count_is_a_knob_not_a_stored_shape():
    """The old model froze the count at whatever was typed. "Only one veggie
    tonight" and "we want three" both have to be expressible."""
    reset_db(); _seed_people()
    p = _pantry()
    storage.set_cached_schedule({"events": [], "assignments": {},
                                 "matched_rules": {}, "scheduled_errands": []})
    veg = next(c for c in storage.get_dish_categories() if c['name'] == 'vegetables')
    for n in (0, 1, 3):
        veg['min_per_plate'], veg['max_per_plate'] = n, max(n, 1)
        storage.save_dish_category(veg)
        cid = veg['id']
        got = [d for d in meals.compose_plate(DAY)
               if cid in (d.get('category_ids') or [])]
        check(len(got) == n, f"asked for {n} vegetables, got {len(got)}")


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
    sweet = next(c for c in storage.get_dish_categories() if c['name'] == 'something sweet')
    cid = sweet['id']
    sweet['min_per_plate'] = 1
    storage.save_dish_category(sweet)
    check(any(cid in (d.get('category_ids') or []) for d in meals.compose_plate(DAY)),
          "families who always have fruit get it")
    sweet['min_per_plate'] = 0
    storage.save_dish_category(sweet)
    check(not any(cid in (d.get('category_ids') or []) for d in meals.compose_plate(DAY)),
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
    check(storage.get_dish(d['chicken']['id'])['category_ids'] == [category_id('protein')],
          "role=protein lands in the family's protein category")
    veg = storage.get_dish(d['veg'][0]['id'])
    check(veg['type'] == 'dish' and veg['category_ids'] == [category_id('vegetables')],
          f"role=vegetable became a vegetable, got {veg.get('category_ids')}")
    check(storage.get_dish(d['rice']['id'])['category_ids'] == [category_id('starches/carbs')],
          "and role=starch became a starch")
    check(all(dd['id'] for dd in storage.get_dishes()),
          "no dish the family entered is lost — only the grouping goes")


def scenario_extraction_emits_one_dish_per_alternative():
    reset_db(); _seed_people()
    storage.get_settings = lambda: {"llm_gemini_api_key": "test-key",
                                    "home_location": HOME}
    payload = {"dishes": [
        {"name": "roasted chicken thighs", "short_name": "chicken",
         "type": "dish", "categories": ["protein"],
         "finish_mins": 10, "portability": "utensils_ok"},
        # The classifier answers in the FAMILY'S words. Beans as both protein
        # and starch is the case the fixed taxonomy could not express at all.
        {"name": "black beans", "short_name": "beans", "type": "dish",
         "categories": ["protein", "starches/carbs"],
         "finish_mins": 5, "portability": "utensils_ok"},
        {"name": "pinto beans", "short_name": "beans", "type": "dish",
         "categories": ["starches/carbs"],
         "finish_mins": 5, "portability": "utensils_ok"},
        {"name": "steamed carrots", "short_name": "carrots", "type": "dish",
         "categories": ["vegetable"],   # singular: a plural must still match
         "finish_mins": 8, "portability": "utensils_ok"},
        {"name": "fresh fruit", "short_name": "fruit", "type": "dish",
         "categories": ["something sweet"],
         "finish_mins": 5, "portability": "utensils_ok"},
    ]}
    with mock.patch('services.model_pools.call_pool_json', return_value=payload):
        res = meals.add_dishes_from_text(
            "chicken, beans (black or pinto), veggies x 2 (carrots), fruit")
    check(len(res['added']) == 5,
          f"every alternative is its own dish — got {len(res['added'])}")
    check(not storage.get_meals(), "and nothing stores a combination any more")
    by_name = {d['name']: d for d in storage.get_dishes()}
    check({d['type'] for d in storage.get_dishes()} == {'dish'},
          "nothing here is a whole meal on its own")
    check(by_name['black beans']['category_ids']
          == [category_id('protein'), category_id('starches/carbs')],
          "a dish can serve as either, which the old side_type could not say")
    check(by_name['steamed carrots']['category_ids'] == [category_id('vegetables')],
          "a singular answer still matches the family's plural category")
    check(by_name['fresh fruit']['category_ids'] == [category_id('something sweet')],
          "and their own words for pudding are honoured")

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


def scenario_every_skip_says_why_and_a_staple_can_be_overridden():
    """Reported 2026-08-05: "+ List doesn't add everything". It was right to
    skip rice and beans by its own lights — the model called them pantry
    staples — but a silent skip is indistinguishable from a bug, and whether
    beans are a staple is a judgement about THIS household (bulk buyers
    restock them; others assume the cupboard)."""
    reset_db(); _seed_people()
    _settings(sides_per_meal=1, include_dessert=False)
    storage.set_cached_schedule({"events": [], "assignments": {},
                                 "matched_rules": {}, "scheduled_errands": []})
    beans = _dish("black beans", short_name="beans", type='side',
                  side_type='starch', finish_mins=5, portability='utensils_ok',
                  ingredients=[{'name': 'black beans', 'kind': 'staple'}])
    plain = _dish("steamed broccoli", short_name="broccoli", type='side',
                  side_type='vegetable', finish_mins=8, portability='utensils_ok')
    lid = storage.ensure_default_shopping_list()['id']

    res = meals.dishes_to_shopping([beans, plain], lid)
    by_name = {x['name']: x for x in res['skipped']}
    check('black beans' in by_name and by_name['black beans']['reason'] == 'staple',
          f"the skip is reported WITH its reason, got {res['skipped']}")
    check(by_name['black beans']['dish_id'] == beans['id'],
          "and it carries the dish, so the guess can be corrected in one tap")
    check(by_name['broccoli']['reason'] == 'no ingredients recorded',
          f"a dish with nothing recorded says so rather than passing silently, "
          f"got {by_name.get('broccoli')}")

    # The override: flip it permanently.
    import main
    main.set_ingredient_kind(beans['id'],
                             main.IngredientPatch(name='black beans', kind='fresh'))
    again = meals.dishes_to_shopping([beans and storage.get_dish(beans['id'])], lid)
    check('black beans' in again['added'],
          f"once it is not a staple, it gets bought — got {again}")

    # And it stays fixed on the next shop.
    storage.clear_checked_shopping_items(lid)
    for i in storage.get_shopping_items(lid):
        storage.delete_shopping_item(i['id'])
    third = meals.dishes_to_shopping([storage.get_dish(beans['id'])], lid)
    check('black beans' in third['added'], "the correction persists on the dish")


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

# The category set these tests compose against. Named and ranged to mirror the
# old fixed taxonomy exactly — one main plus two sides — so every pre-v2.108
# scenario keeps asserting the same behaviour through the new model instead of
# being rewritten around it.
_TEST_CATEGORIES = [
    ('protein', 1, 1, False),
    ('vegetables', 1, 1, False),
    ('starches/carbs', 1, 1, False),
    ('salad', 0, 1, False),
    ('other', 0, 1, False),
    ('something sweet', 0, 1, True),
]
_LEGACY_TO_CATEGORY = {
    ('entree', None): 'protein',
    ('side', 'vegetable'): 'vegetables',
    ('side', 'starch'): 'starches/carbs',
    ('side', 'salad'): 'salad',
    # The old prompt's own rule was "beans served as a starch", and the legacy
    # 'other' bucket is mostly beans in these scenarios — so it maps to the
    # starch block rather than to a category no plate asks for.
    ('side', 'other'): 'starches/carbs',
    ('side', None): 'starches/carbs',
    ('dessert', None): 'something sweet',
}


def seed_categories():
    """Recreate the family vocabulary after a reset_db truncate."""
    import time as _t
    for i, (name, lo, hi, with_meal) in enumerate(_TEST_CATEGORIES):
        storage.save_dish_category({
            'id': 'cat-' + name.split('/')[0].replace(' ', '-'),
            'name': name, 'description': '', 'min_per_plate': lo,
            'max_per_plate': hi, 'with_complete_meal': with_meal,
            'order': i, 'created_at': _t.time()})
    storage.set_app_state('dish_categories_seeded', True)


def category_id(name):
    return next(c['id'] for c in storage.get_dish_categories() if c['name'] == name)


def _dish(name, **kw):
    """Legacy `type=`/`side_type=` kwargs are translated to the family's
    categories, so the existing scenarios exercise the new composer."""
    from models.schemas import Dish
    if not storage.get_dish_categories():
        seed_categories()
    legacy_type = kw.pop('type', None)
    legacy_side = kw.pop('side_type', None)
    if legacy_type == 'meal':
        kw['type'] = 'meal'
    elif legacy_type is not None or legacy_side is not None:
        kw['type'] = 'dish'
        cat = (_LEGACY_TO_CATEGORY.get((legacy_type, legacy_side))
               or _LEGACY_TO_CATEGORY.get((legacy_type, None)))
        if cat and not kw.get('category_ids'):
            kw['category_ids'] = [category_id(cat)]
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
    check('rice' in res['skipped_names'], "the staple is still skipped")
    check(any('chicken' in a for a in res['added']), "and the protein is bought")
    # Every skip carries WHY — a silent one is indistinguishable from a bug.
    rice_skip = next(x for x in res['skipped'] if x['name'] == 'rice')
    check(rice_skip['reason'] == 'staple' and rice_skip['dish'],
          f"reasons are reported per item, got {rice_skip}")


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


# --- M6: the week ahead -----------------------------------------------------
# The load in meals is DECIDING and PROVISIONING, and neither can be done on
# the day. Everything below exists to make one "how does this look?" replace
# the family's planning session. See docs/meal_week_design.md.

def _week_repertoire():
    """Seven entrees and six sides — enough that a week has real choices."""
    ent = [_dish(n, type='entree',
                 ingredients=[{'name': n + ' base', 'kind': 'fresh'}])
           for n in ('chicken thighs', 'tacos', 'salmon', 'spaghetti',
                     'chili', 'stir fry', 'pork chops')]
    sides = [_dish(n, type='side', side_type=st,
                   ingredients=[{'name': n, 'kind': 'fresh'}])
             for n, st in (('rice', 'starch'), ('broccoli', 'vegetable'),
                           ('salad', 'salad'), ('potatoes', 'starch'),
                           ('green beans', 'vegetable'), ('corn', 'vegetable'))]
    return ent, sides


def scenario_a_week_does_not_repeat_the_same_dinner():
    """THE load-bearing property. Ranking used to measure recency from
    wall-clock now regardless of which day was being composed, so every day in
    a horizon scored identically and proposed the same entree. Planning ahead
    was impossible for that one reason."""
    reset_db(); _seed_people()
    _settings(sides_per_meal=2, include_dessert=False)
    _week_repertoire()

    week = meals.compose_week('2026-08-08', 7)
    check(len(week) == 7, f"seven nights, got {len(week)}")
    prot = category_id('protein')
    entrees = [next(x['name'] for x in d['dishes']
                    if prot in (x.get('category_ids') or []))
               for d in week]
    check(len(set(entrees)) == 7,
          f"seven DIFFERENT proteins across the week, got {entrees}")

    # And prove the old behaviour really was the failure: composing each day
    # independently (no forward simulation) collapses to one dinner.
    solo = [next(x['name'] for x in meals.compose_plate(d['date'])
                 if prot in (x.get('category_ids') or [])) for d in week]
    check(len(set(solo)) == 1,
          f"without the overlay every night is the same — got {set(solo)}")


def scenario_the_window_is_the_shop_it_has_to_cover():
    """Families plan up to the next grocery run, a day or two before it — the
    horizon is that shop's coverage period, not "7 days from whenever"."""
    reset_db(); _seed_people()
    _settings(grocery_weekday=5, grocery_plan_lead_days=2)   # Saturday, 2 days

    thursday = datetime.date(2026, 8, 6)
    win = meals.plan_window(storage.get_settings(), thursday)
    check(win['mode'] == 'planning' and win['start'] == '2026-08-08',
          f"inside the lead window we plan the coming shop, got {win}")
    check(win['days'] == 7 and win['days_until_shop'] == 2, f"got {win}")

    monday = datetime.date(2026, 8, 10)
    win2 = meals.plan_window(storage.get_settings(), monday)
    check(win2['mode'] == 'current' and win2['start'] == '2026-08-10',
          f"outside it, show what's LEFT of the span already bought for, got {win2}")
    check(win2['days'] == 5, f"Monday through Friday before Saturday, got {win2['days']}")

    saturday = datetime.date(2026, 8, 8)
    win3 = meals.plan_window(storage.get_settings(), saturday)
    check(win3['mode'] == 'planning' and win3['days_until_shop'] == 0,
          f"shop day itself still plans, got {win3}")


def scenario_approving_the_week_pins_it_and_buys_for_it():
    reset_db(); _seed_people()
    _settings(sides_per_meal=2, include_dessert=False)
    _week_repertoire()

    before = meals.compose_week('2026-08-08', 3)
    res = meals.approve_week('2026-08-08', 3)
    check(res['day_count'] == 3 and len(res['pinned_dates']) == 3,
          f"every night in the window is pinned, got {res['pinned_dates']}")
    check(res['added'], "and the span's fresh ingredients went on the list")

    after = meals.compose_week('2026-08-08', 3)
    check(all(d['pinned'] for d in after), "the week now reports itself pinned")
    check([[x['id'] for x in d['dishes']] for d in after]
          == [[x['id'] for x in d['dishes']] for d in before],
          "and holds exactly what was approved — money has been spent on it")

    # Second press buys nothing new; the skips say why, and which night.
    again = meals.approve_week('2026-08-08', 3)
    check(not again['added'], f"nothing bought twice, got {again['added']}")
    dupes = [s for s in again['skipped'] if s['reason'] == 'already on the list']
    check(dupes and all(s.get('weekday') for s in dupes),
          "every skip names the night it came from")


def scenario_a_pinned_night_still_feeds_the_rotation():
    """A pinned day that did not count would let the plan repeat around it."""
    reset_db(); _seed_people()
    _settings(sides_per_meal=1, include_dessert=False)
    ent, _ = _week_repertoire()

    meals.add_to_plate('2026-08-08', ent[3]['id'])          # pin spaghetti Sat
    week = meals.compose_week('2026-08-08', 7)
    check(week[0]['pinned'], "Saturday is pinned")
    later = [x['name'] for d in week[1:] for x in d['dishes']]
    check(ent[3]['name'] not in later,
          f"the pinned dish is not re-proposed later in the week, got {later}")


def scenario_editing_one_night_leaves_the_others_alone():
    """prune_plates used to delete every plate BEFORE the one being written —
    harmless when only tonight existed, fatal with a week in the table."""
    reset_db(); _seed_people()
    _settings(sides_per_meal=1, include_dessert=False)
    ent, _ = _week_repertoire()

    meals.approve_week('2026-08-08', 3)
    check(len(storage.get_plates_between('2026-08-08', '2026-08-10')) == 3,
          "three nights pinned")
    meals.add_to_plate('2026-08-10', ent[5]['id'])          # edit the LAST one
    kept = storage.get_plates_between('2026-08-08', '2026-08-10')
    check(len(kept) == 3,
          f"editing a later night must not prune the earlier ones, got {len(kept)}")


def scenario_the_week_is_proposed_once_per_shopping_cycle():
    reset_db(); _seed_people()
    _settings(sides_per_meal=1, include_dessert=False,
              grocery_weekday=5, grocery_plan_lead_days=2)
    _week_repertoire()
    sent = []

    thursday = datetime.datetime(2026, 8, 6, 9, 0)
    res = meals.propose_week_plan(thursday, deliver=lambda s, p, b: sent.append((s, p, b)))
    check(res['status'] == 'proposed' and len(sent) == 1, f"proposed once, got {res}")
    check('Sat' in sent[0][2] and 'Shopping Saturday' in sent[0][2],
          f"the nights ARE the message, got {sent[0][2][:120]}")

    again = meals.propose_week_plan(thursday + datetime.timedelta(hours=1),
                                    deliver=lambda s, p, b: sent.append((s, p, b)))
    check(again['status'] == 'already_proposed' and len(sent) == 1,
          "the 30-minute sweep must not re-propose the same cycle")

    monday = datetime.datetime(2026, 8, 10, 9, 0)
    check(meals.propose_week_plan(monday, deliver=lambda *a: sent.append(a)
                                  )['status'] == 'not_yet',
          "and outside the lead window it stays quiet")


def scenario_an_empty_repertoire_proposes_nothing():
    """A card saying "I have no dinners for you" is not a plan."""
    reset_db(); _seed_people()
    _settings(grocery_weekday=5, grocery_plan_lead_days=2)
    sent = []
    res = meals.propose_week_plan(datetime.datetime(2026, 8, 6, 9, 0),
                                  deliver=lambda *a: sent.append(a))
    check(res['status'] == 'empty_repertoire' and not sent, f"silent, got {res}")


def scenario_one_line_per_ingredient_naming_every_dish():
    """Rice used by four dishes produced four identical "assumed on hand"
    lines, which reads as a broken list rather than one judgement about rice."""
    reset_db(); _seed_people()
    _settings(sides_per_meal=0, include_dessert=False)
    shared = [{'name': 'rice', 'kind': 'staple'},
              {'name': 'olive oil', 'kind': 'staple'}]
    a = _dish('chicken bowl', type='entree',
              ingredients=shared + [{'name': 'chicken', 'kind': 'fresh'}])
    b = _dish('bean bowl', type='entree',
              ingredients=shared + [{'name': 'beans', 'kind': 'fresh'}])
    c = _dish('veg bowl', type='entree',
              ingredients=shared + [{'name': 'peppers', 'kind': 'fresh'}])

    res = meals.dishes_to_shopping([a, b, c])
    rice = [s for s in res['skipped'] if s['name'] == 'rice']
    check(len(rice) == 1, f"ONE line for rice, got {len(rice)}")
    check(rice[0]['dish_count'] == 3, f"naming all three dishes, got {rice[0]}")
    check(all(n in rice[0]['dish'] for n in ('chicken bowl', 'bean bowl', 'veg bowl')),
          f"the label lists them, got {rice[0]['dish']}")
    check(len(rice[0]['dish_ids']) == 3,
          "and carries every dish id — the override has to fix ALL of them, or "
          "the other dishes skip it again next week")
    check(len(res['skipped_names']) == len(set(res['skipped_names'])),
          f"no repeats in the names either, got {res['skipped_names']}")


def scenario_a_week_says_which_nights_wanted_it():
    reset_db(); _seed_people()
    _settings(sides_per_meal=0, include_dessert=False)
    for n in ('monday dish', 'tuesday dish'):
        _dish(n, type='entree', ingredients=[{'name': 'rice', 'kind': 'staple'},
                                             {'name': n + ' meat', 'kind': 'fresh'}])
    res = meals.approve_week('2026-08-10', 2)
    rice = [s for s in res['skipped'] if s['name'] == 'rice']
    check(len(rice) == 1, f"one rice line across the whole week, got {len(rice)}")
    check('Mon' in rice[0]['dish'] and 'Tue' in rice[0]['dish'],
          f"naming the nights that wanted it, got {rice[0]['dish']}")


def scenario_the_shop_day_is_derived_not_guessed():
    """The first cut hardcoded Saturday — precisely the day a family with
    weekend activities has least room for a 90-minute trip. An unset shop day
    is now worked out from real free blocks."""
    reset_db(); _seed_people()
    _settings(grocery_weekday=None)
    storage.app_state_table.truncate()

    # Saturdays are eaten by activities; Tuesdays are clear.
    evs, assigns = [], {}
    base = datetime.date(2026, 8, 8)          # a Saturday
    for wk in range(3):
        sat = base + datetime.timedelta(days=7 * wk)
        evs.append({"id": f"sat{wk}", "title": "Tournament", "event_type": "standard",
                    "start": f"{sat.isoformat()}T08:00:00",
                    "end": f"{sat.isoformat()}T19:30:00",
                    "location": "Fields", "calendar_ids": ["add@cal"]})
        assigns[f"sat{wk}"] = "d-mom"
    storage.set_cached_schedule({"events": evs, "assignments": assigns})

    cands = meals.grocery_day_candidates(storage.get_settings(),
                                         datetime.date(2026, 8, 6))
    by_day = {c['weekday']: c for c in cands}
    check(by_day[5]['worst_mins'] < by_day[1]['worst_mins'],
          f"Saturday has less room than Tuesday, got "
          f"{by_day[5]['worst_mins']} vs {by_day[1]['worst_mins']}")
    check(cands[0]['weekday'] != 5,
          f"so Saturday is not the recommendation, got {cands[0]['weekday_name']}")

    sug = meals.suggest_grocery_weekday(storage.get_settings(),
                                        datetime.date(2026, 8, 6))
    check(sug['weekday'] == cands[0]['weekday'] and sug['reason'],
          f"the suggestion says WHY, got {sug}")
    gw, _ = meals.grocery_settings(storage.get_settings())
    check(gw == sug['weekday'],
          f"and an unset setting follows it rather than defaulting, got {gw}")

    # An explicit choice always wins — this is advice, not automation.
    check(meals.grocery_settings({'grocery_weekday': 5})[0] == 5,
          "an explicitly chosen day is honoured")


# --- M11: how this household eats --------------------------------------------
# From the family, and it is the case M9's this-with-this could not carry:
# "we eat 3 kinds of beans, make each in a large quantity and eat it 2-3 days
# then make the next; we only eat meat once a week or so; takeout now and
# then". None of those are properties of a dish — they are rhythms.

def _rules_repertoire():
    beans = [_dish(n, type='side', side_type='other', tags=['beans'])
             for n in ('black beans', 'pinto beans', 'red beans')]
    for n in ('beef tacos', 'roast chicken', 'pork chops'):
        _dish(n, type='entree', tags=['meat'])
    for n in ('pizza delivery', 'thai takeout'):
        _dish(n, type='meal', source='ordered')
    for n in ('veggie chili', 'bean burritos', 'lentil curry', 'shakshuka'):
        _dish(n, type='entree', tags=['vegetarian'])
    for n, st in (('rice', 'starch'), ('salad', 'salad'),
                  ('broccoli', 'vegetable'), ('corn', 'vegetable')):
        _dish(n, type='side', side_type=st)
    return beans


def _served_days(week, names):
    return [i for i, d in enumerate(week)
            if {x['name'] for x in d['dishes']} & set(names)]


def scenario_a_frequency_cap_holds_across_a_composed_fortnight():
    reset_db(); _seed_people()
    _settings(sides_per_meal=2, include_dessert=False)
    _rules_repertoire()

    loose = _served_days(meals.compose_week('2026-09-07', 14),
                         ('beef tacos', 'roast chicken', 'pork chops'))
    check(len(loose) > 2, f"unruled, meat comes up often — {len(loose)} days")

    meals.add_meal_rule('meat about once a week', 'frequency_cap',
                        tags=['meat'], max_servings=1, window_days=7)
    days = _served_days(meals.compose_week('2026-09-07', 14),
                        ('beef tacos', 'roast chicken', 'pork chops'))
    check(all(b - a >= 7 for a, b in zip(days, days[1:])),
          f"never twice inside a week, got days {days}")
    check(days, "but it is not banned outright either")


def scenario_takeout_is_capped_by_source_not_by_tagging_every_dish():
    """source='ordered' is structural, so this rule needs no tags at all —
    which matters because "meat" is not a field but takeout effectively is."""
    reset_db(); _seed_people()
    _settings(sides_per_meal=1, include_dessert=False)
    _rules_repertoire()
    meals.add_meal_rule('takeout now and then', 'frequency_cap',
                        sources=['ordered'], max_servings=1, window_days=10)
    days = _served_days(meals.compose_week('2026-09-07', 14),
                        ('pizza delivery', 'thai takeout'))
    check(all(b - a >= 10 for a, b in zip(days, days[1:])),
          f"takeout stays occasional, got days {days}")


def scenario_a_batch_cycle_dwells_then_rotates():
    """THE one that needed measuring. The first cut compared "time since last
    served" against the dwell — but a batch is eaten EVERY day, so that gap is
    permanently one day and the window slid forever: a 14-day plan sat on black
    beans for all 14 days. The dwell has to count SERVINGS."""
    reset_db(); _seed_people()
    _settings(sides_per_meal=2, include_dessert=False)
    beans = _rules_repertoire()
    meals.add_meal_rule('one pot of beans at a time', 'batch_cycle',
                        tags=['beans'], dwell_days=3)

    week = meals.compose_week('2026-09-07', 14)
    per_day = []
    for d in week:
        got = [x['name'] for x in d['dishes'] if x['name'].endswith('beans')]
        per_day.append(got[0] if got else None)
        check(len(got) <= 1, f"only ever ONE pot open at a time, got {got}")

    runs = []
    for b in per_day:
        if b and (not runs or runs[-1][0] != b):
            runs.append([b, 1])
        elif b:
            runs[-1][1] += 1
    check(len({r[0] for r in runs}) == 3,
          f"all three beans get their turn, got {runs}")
    check(any(r[1] > 1 for r in runs),
          f"and each is eaten for more than one day, got {runs}")
    check(all(r[1] <= 3 for r in runs),
          f"without any batch overstaying the dwell, got {runs}")


def scenario_a_rule_matching_nothing_says_so():
    """"meat" is not a field. A tag the family never used governs nobody, and
    silently doing nothing is the failure mode worth surfacing."""
    reset_db(); _seed_people(); _settings()
    _dish('lentil curry', type='entree', tags=['vegetarian'])
    res = meals.add_meal_rule('no venison', 'frequency_cap', tags=['venison'])
    check(res['match_count'] == 0, "matches nothing")
    from services import agent_tools
    said = agent_tools.execute_tool("set_meal_rule", {
        "description": "we hardly ever eat venison", "tags": "venison"})
    check('not match any dish' in said['message'],
          f"and the agent says so rather than claiming success, got {said}")


def scenario_an_empty_selector_governs_nobody():
    reset_db(); _seed_people(); _settings()
    _dish('lentil curry', type='entree')
    res = meals.add_meal_rule('half a rule', 'frequency_cap')
    check(res['match_count'] == 0,
          "a rule with no clauses matches NOTHING rather than everything — a "
          "half-written rule must not become a household-wide ban")


def scenario_a_cap_is_not_bypassed_by_a_pairing():
    """M9 pairings pull dishes in outside the normal candidate filter, so the
    cap has to be enforced there too or brisket smuggles the meat in."""
    reset_db(); _seed_people()
    _settings(sides_per_meal=1, include_dessert=False)
    steak = _dish('steak', type='entree', tags=['meat'])
    bacon = _dish('bacon greens', type='side', side_type='vegetable', tags=['meat'])
    _dish('plain greens', type='side', side_type='vegetable')
    meals.set_pairing(steak['id'], [bacon['id']])
    meals.add_meal_rule('meat once a week', 'frequency_cap',
                        tags=['meat'], max_servings=1, window_days=7)

    week = meals.compose_week('2026-09-07', 7)
    days = _served_days(week, ('steak', 'bacon greens'))
    check(len(days) <= 1,
          f"the cap survives the pairing that would otherwise bust it, "
          f"got days {days}")


def scenario_rules_can_be_disabled_without_deleting_them():
    reset_db(); _seed_people()
    _settings(sides_per_meal=1, include_dessert=False)
    _rules_repertoire()
    res = meals.add_meal_rule('meat once a week', 'frequency_cap',
                              tags=['meat'], max_servings=1, window_days=7)
    rid = res['rule']['id']
    capped = _served_days(meals.compose_week('2026-09-07', 14),
                          ('beef tacos', 'roast chicken', 'pork chops'))
    storage.update_meal_rule(rid, {'is_enabled': False})
    loose = _served_days(meals.compose_week('2026-09-07', 14),
                         ('beef tacos', 'roast chicken', 'pork chops'))
    check(len(loose) > len(capped),
          f"disabling releases it, got {len(loose)} vs {len(capped)}")
    check(storage.get_meal_rule(rid), "and the rule is still there to re-enable")


def scenario_the_rules_panel_gets_what_it_renders():
    """The rules shipped with an API and agent tools and NO UI, so there was
    nowhere to see or add them. The panel renders description, matches and
    match_count off the list endpoint — if those stop coming back it silently
    renders blank rows, which is how the feature looked absent in the first
    place."""
    reset_db(); _seed_people(); _settings()
    import main
    _rules_repertoire()
    main.create_meal_rule(main.MealRuleReq(
        name='meat about once a week', kind='frequency_cap', tags=['meat'],
        max_servings=1, window_days=7))
    main.create_meal_rule(main.MealRuleReq(
        name='takeout now and then', kind='frequency_cap', sources=['ordered'],
        max_servings=1, window_days=10))
    main.create_meal_rule(main.MealRuleReq(
        name='nothing matches me', kind='frequency_cap', tags=['venison']))

    rows = main.list_meal_rules()['rules']
    check(len(rows) == 3, f"disabled ones are listed too, got {len(rows)}")
    for r in rows:
        for key in ('id', 'name', 'description', 'matches', 'match_count',
                    'is_enabled'):
            check(key in r, f"the panel needs {key}, got {sorted(r)}")
    by_name = {r['name']: r for r in rows}
    check(by_name['meat about once a week']['match_count'] == 3,
          f"tags resolve, got {by_name['meat about once a week']['matches']}")
    check(by_name['takeout now and then']['match_count'] == 2,
          "takeout resolves with no tagging at all")
    check(by_name['nothing matches me']['match_count'] == 0,
          "and the empty one is visibly empty so the panel can warn")
    check('at most 1 in a week' in by_name['meat about once a week']['description'],
          f"description reads as English, got "
          f"{by_name['meat about once a week']['description']!r}")

    rid = by_name['meat about once a week']['id']
    main.patch_meal_rule(rid, main.MealRulePatch(is_enabled=False))
    check(storage.get_meal_rule(rid)['is_enabled'] is False, "pause works")
    check(rid not in [r['id'] for r in storage.get_meal_rules()],
          "a paused rule stops governing")
    check(rid in [r['id'] for r in storage.get_meal_rules(include_disabled=True)],
          "but is still there to resume")
    main.remove_meal_rule(rid)
    check(not storage.get_meal_rule(rid), "and delete removes it")


def scenario_a_tag_can_be_almost_right():
    """Reported: the bean rotation is black, red and pinto — but the "beans"
    tag drags baked beans in too. A tag is nearly always ALMOST right, and
    without subtraction the only way out is enumerating every dish by hand."""
    reset_db(); _seed_people()
    _settings(sides_per_meal=2, include_dessert=False)
    _rules_repertoire()
    baked = _dish('baked beans', type='side', side_type='other', tags=['beans'])

    wide = meals.add_meal_rule('beans', 'batch_cycle', tags=['beans'], dwell_days=3)
    check('baked beans' in wide['matches'],
          f"the plain tag drags it in, got {wide['matches']}")

    narrowed = meals.add_meal_rule('bean rotation', 'batch_cycle', tags=['beans'],
                                   exclude_dish_ids=[baked['id']], dwell_days=3)
    check('baked beans' not in narrowed['matches'],
          f"excluded, got {narrowed['matches']}")
    check(narrowed['match_count'] == 3,
          f"leaving exactly the three that rotate, got {narrowed['matches']}")

    # And it really stays out of the cycle over a composed fortnight.
    storage.delete_meal_rule(wide['rule']['id'])
    week = meals.compose_week('2026-09-07', 14)
    for day in week:
        names = {x['name'] for x in day['dishes']}
        check('baked beans' not in names,
              f"the excluded dish never joins the rotation, got {names}")


def scenario_an_exclusion_beats_every_other_clause():
    """"Not this one" is never conditional — it has to win even over an
    explicit dish list, or an edit that adds an exclusion appears to do
    nothing."""
    reset_db(); _seed_people(); _settings()
    a = _dish('black beans', type='side', side_type='other', tags=['beans'])
    b = _dish('baked beans', type='side', side_type='other', tags=['beans'])
    rule = {'dish_ids': [a['id'], b['id']], 'exclude_dish_ids': [b['id']],
            'tags': [], 'types': [], 'side_types': [], 'sources': []}
    check(meals.rule_matches(rule, a), "the kept one still matches")
    check(not meals.rule_matches(rule, b),
          "and the excluded one does not, despite being listed explicitly")


def scenario_a_rule_can_be_edited_in_place():
    """Without this, changing "once a week" to "twice" meant deleting the rule
    and rebuilding it from memory — and the same PATCH has to carry a one-field
    pause and a whole-rule edit, or the panel needs two endpoints for one
    verb."""
    reset_db(); _seed_people(); _settings()
    import main
    _rules_repertoire()
    made = main.create_meal_rule(main.MealRuleReq(
        name='meat about once a week', kind='frequency_cap', tags=['meat'],
        max_servings=1, window_days=7))
    rid = made['rule']['id']

    edited = main.patch_meal_rule(rid, main.MealRulePatch(
        name='meat twice a week', max_servings=2))
    check(edited['rule']['name'] == 'meat twice a week'
          and edited['rule']['max_servings'] == 2,
          f"the supplied fields change, got {edited['rule']}")
    check(edited['rule']['tags'] == ['meat'] and edited['rule']['window_days'] == 7,
          f"and untouched ones are left alone, got {edited['rule']}")
    check(edited['match_count'] == 3,
          f"the edit reports what it now covers, got {edited['match_count']}")

    # Normalised the same way creation is, or an edited rule quietly behaves
    # differently from an identical created one.
    upper = main.patch_meal_rule(rid, main.MealRulePatch(tags=['  MEAT  ']))
    check(upper['rule']['tags'] == ['meat'],
          f"tags are lowercased and trimmed on edit too, got {upper['rule']['tags']}")
    floored = main.patch_meal_rule(rid, main.MealRulePatch(max_servings=0,
                                                          window_days=0))
    check(floored['rule']['max_servings'] == 1 and floored['rule']['window_days'] == 1,
          f"floors apply on edit, got {floored['rule']}")

    # Switching kind must carry its own number across.
    swapped = main.patch_meal_rule(rid, main.MealRulePatch(
        kind='batch_cycle', dwell_days=2))
    check(swapped['rule']['kind'] == 'batch_cycle'
          and swapped['rule']['dwell_days'] == 2,
          f"kind can change and takes its own number with it, got {swapped['rule']}")
    check('one at a time' in meals.describe_meal_rule(swapped['rule']),
          f"and it now describes itself as a batch, got "
          f"{meals.describe_meal_rule(swapped['rule'])!r}")

    check(meals.edit_meal_rule('nope', {'name': 'x'})['status'] == 'error',
          "editing a rule that does not exist is an error, not a new rule")


def scenario_editing_keeps_what_the_rule_applies_to():
    """The panel rebuilds "applies to" from tags + dish names. If dish_ids are
    not returned by the list endpoint the field comes back empty, and saving
    then turns a working rule into one that governs nobody."""
    reset_db(); _seed_people(); _settings()
    import main
    _rules_repertoire()
    tacos = storage.find_dish_by_name('beef tacos')
    made = main.create_meal_rule(main.MealRuleReq(
        name='tacos rarely', kind='frequency_cap', dish_ids=[tacos['id']],
        max_servings=1, window_days=14))
    row = next(r for r in main.list_meal_rules()['rules']
               if r['id'] == made['rule']['id'])
    check(row.get('dish_ids') == [tacos['id']],
          f"the list endpoint returns dish_ids so the form can repopulate, "
          f"got {row.get('dish_ids')}")
    check(row.get('tags') == [] and row.get('sources') == [],
          "and the other selector fields, so nothing is lost on a round trip")

    # Exclusions have to survive the trip too, or editing a narrowed rule
    # silently re-admits the dish it was narrowed to keep out.
    chicken = storage.find_dish_by_name('roast chicken')
    narrowed = main.create_meal_rule(main.MealRuleReq(
        name='meat but not chicken', kind='frequency_cap', tags=['meat'],
        exclude_dish_ids=[chicken['id']], max_servings=1, window_days=7))
    row2 = next(r for r in main.list_meal_rules()['rules']
                if r['id'] == narrowed['rule']['id'])
    check(row2.get('exclude_dish_ids') == [chicken['id']],
          f"exclusions round-trip, got {row2.get('exclude_dish_ids')}")
    check('roast chicken' not in row2['matches'],
          f"and are honoured in what it reports covering, got {row2['matches']}")


def scenario_rule_tools_in_both_stacks():
    reset_db(); _seed_people(); _settings()
    _rules_repertoire()
    from services import agent_tools, agent_tools_v2
    want = {"set_meal_rule", "get_meal_rules"}
    v2 = {t['name'] for t in agent_tools_v2.get_available_tools()}
    check(want <= v2, f"v2 missing {want - v2}")
    check(want <= set(agent_tools.TOOL_SCHEMAS)
          and want <= set(agent_tools.TOOL_HANDLERS), "v1 stack incomplete")
    import inspect
    from services import agent_router
    src = inspect.getsource(agent_router)
    for name in want:
        check(src.count(f'"{name}"') >= 2,
              f"{name} is not both dispatched and listed terminal in the router")

    made = agent_tools.execute_tool("set_meal_rule", {
        "description": "we only eat meat about once a week", "tags": "meat",
        "max_servings": 1, "window_days": 7})
    check(made['status'] == 'success' and 'covers' in made['message'],
          f"set by voice and names what it covers, got {made}")
    listed = agent_tools.execute_tool("get_meal_rules", {})
    check('meat' in listed['message'] and 'week' in listed['message'],
          f"and reads back in plain words, got {listed}")


# --- M10: a night that is spoken for -----------------------------------------

def scenario_a_locked_night_survives_a_bulk_repropose():
    """The hold-still rule already pinned an edited plate — but a bulk
    repropose is entitled to sweep an edit away, and sweeping away Mom's
    birthday dinner set three weeks out is not the same act at all."""
    reset_db(); _seed_people()
    _settings(sides_per_meal=1, include_dessert=False)
    steak = _dish('steak', type='entree')
    _dish('tacos', type='entree')
    _dish('salad', type='side', side_type='salad')

    meals.set_plate_lock('2026-09-14', True, "Mom's birthday", [steak['id']])
    day = next(d for d in meals.compose_week('2026-09-14', 1))
    check(day['locked'] and day['note'] == "Mom's birthday",
          f"locked and says why, got {day.get('locked')}/{day.get('note')}")
    check([x['name'] for x in day['dishes']] == ['steak'], "with the chosen dish")

    res = meals.reset_plate('2026-09-14')          # the bulk path
    check(res.get('refused') and storage.get_plate('2026-09-14'),
          f"an unforced reset refuses, got {res.get('refused')}")
    meals.reset_plate('2026-09-14', force=True)    # the per-day path
    check(not storage.get_plate('2026-09-14'),
          "but a deliberate per-day reset releases it")


def _repropose_bed(entrees=('tacos', 'brisket', 'chicken', 'pasta', 'chili')):
    reset_db(); _seed_people()
    _settings(sides_per_meal=1, include_dessert=False)
    for n in entrees:
        _dish(n, type='entree')
    for n in ('salad', 'rice', 'broccoli'):
        _dish(n, type='side', side_type='other')


def _entrees_of(week):
    """What leads each night — the first block the family asks a plate to have,
    which is the protein here (a whole-meal dish leads on its own)."""
    prot = category_id('protein')
    return {d['date']: next((x['name'] for x in d['dishes']
                             if x.get('type') == 'meal'
                             or prot in (x.get('category_ids') or [])), None)
            for d in week}


def scenario_repropose_moves_a_week_nobody_has_touched():
    """The button spent three versions doing nothing and it took a bug report
    to notice. It reset every PINNED night and reloaded — but the composer is
    deterministic, so an untouched night recomposes to exactly what was already
    on it, and untouched is the normal case. Only an edit ever moved."""
    _repropose_bed()
    before = meals.compose_week('2026-09-14', 5)
    check(all(not d['pinned'] for d in before), "nothing is pinned to begin with")

    after = meals.repropose_week('2026-09-14', 5)
    b, a = _entrees_of(before), _entrees_of(after)
    check(all(b[d] != a[d] for d in b),
          f"every night is offered something else, got {b} then {a}")
    check(all(x['dishes'] for x in after), "and no night was left with no dinner")


def scenario_repropose_leaves_a_locked_night_exactly_alone():
    """A lock is "this is Mom's birthday dinner". Repropose is entitled to
    sweep an edit away and must not touch this."""
    _repropose_bed()
    steak = _dish('steak', type='entree')
    meals.set_plate_lock('2026-09-16', True, "Mom's birthday", [steak['id']])

    before = meals.compose_week('2026-09-14', 5)
    after = meals.repropose_week('2026-09-14', 5)
    wed = next(d for d in after if d['date'] == '2026-09-16')
    check([x['name'] for x in wed['dishes']] == ['steak'], "the dish is still there")
    check(wed['locked'] and wed['note'] == "Mom's birthday", "and so is the reason")
    check(not (storage.get_plate('2026-09-16') or {}).get('rejected'),
          "a night that was never proposed has nothing to refuse")
    b, a = _entrees_of(before), _entrees_of(after)
    check(all(b[d] != a[d] for d in b if d != '2026-09-16'),
          f"while every other night moved, got {b} then {a}")


def scenario_repropose_rotates_rather_than_dead_ending():
    """With two entrees, a fourth press has nothing un-refused left. Refusals
    are therefore ORDERED and weighted, not a filter with a fallback: the dish
    turned down longest ago comes back first, so it alternates forever instead
    of sticking on the top-ranked one."""
    _repropose_bed(entrees=('tacos', 'brisket'))
    seen = []
    for i in range(6):
        week = (meals.compose_week('2026-09-14', 1) if i == 0
                else meals.repropose_week('2026-09-14', 1))
        got = _entrees_of(week)['2026-09-14']
        check(got is not None, f"press {i} still proposes a dinner")
        seen.append(got)
    check(all(seen[i] != seen[i + 1] for i in range(len(seen) - 1)),
          f"and never repeats itself twice running, got {seen}")


def scenario_a_refusal_expires_with_the_night_it_was_about():
    """Refusals ride on the plate row, so they are pruned with everything else
    rather than following a dish around forever."""
    _repropose_bed()
    meals.repropose_week('2026-09-14', 2)
    check((storage.get_plate('2026-09-14') or {}).get('rejected'),
          "the refusal was recorded")
    check(not storage.get_plate('2026-09-14').get('edited'),
          "without pinning the night — it must stay fluid")

    meals.reset_plate('2026-09-14', force=True)
    check(not storage.get_plate('2026-09-14'),
          "and a deliberate per-day reset clears it, so the night starts over")


def scenario_an_edit_does_not_silently_unlock_the_night():
    """_persist_plate rebuilds the record from scratch, so without carrying the
    lock forward an ordinary edit — or the week approval, which re-persists
    every night — would quietly unlock a birthday and drop its reason."""
    reset_db(); _seed_people()
    _settings(sides_per_meal=1, include_dessert=False)
    steak = _dish('steak', type='entree')
    salad = _dish('salad', type='side', side_type='salad')
    meals.set_plate_lock('2026-09-14', True, "Mom's birthday", [steak['id']])

    meals.add_to_plate('2026-09-14', salad['id'])
    rec = storage.get_plate('2026-09-14')
    check(rec['locked'] and rec['note'] == "Mom's birthday",
          f"still locked after an edit, got {rec.get('locked')}/{rec.get('note')}")

    meals.approve_week('2026-09-14', 1)
    rec2 = storage.get_plate('2026-09-14')
    check(rec2['locked'] and rec2['note'] == "Mom's birthday",
          f"and after the week approval re-persists it, got {rec2.get('locked')}")


def scenario_a_locked_night_with_no_dishes_is_someone_else_cooking():
    """"Grandma is bringing dinner" — nothing to cook, nothing to shop for,
    and it must not read as a night nobody has planned."""
    reset_db(); _seed_people()
    _settings(sides_per_meal=2, include_dessert=False)
    _dish('tacos', type='entree', ingredients=[{'name': 'beef', 'kind': 'fresh'}])
    _dish('salad', type='side', side_type='salad',
          ingredients=[{'name': 'lettuce', 'kind': 'fresh'}])

    meals.set_plate_lock('2026-09-15', True, "Grandma is bringing dinner", [])
    day = meals.compose_week('2026-09-15', 1)[0]
    check(not day['dishes'] and day['note'] == "Grandma is bringing dinner",
          f"an empty night that says why, got {day}")

    res = meals.approve_week('2026-09-15', 1)
    check(not res['added'],
          f"and it buys nothing — somebody else is feeding us, got {res['added']}")


def scenario_a_far_future_night_is_not_pruned():
    reset_db(); _seed_people(); _settings()
    steak = _dish('steak', type='entree')
    far = (datetime.date.today() + datetime.timedelta(days=25)).isoformat()
    meals.set_plate_lock(far, True, "Mom's birthday", [steak['id']])
    # Any later plate write prunes; the future one must survive it.
    meals.add_to_plate(datetime.date.today().isoformat(), steak['id'])
    check(storage.get_plate(far),
          "a night set weeks out survives the prune that runs on every write")


def scenario_lock_tools_in_both_stacks():
    reset_db(); _seed_people(); _settings()
    _dish('steak', type='entree')
    from services import agent_tools, agent_tools_v2
    want = {"plan_specific_dinner", "unlock_dinner"}
    v2 = {t['name'] for t in agent_tools_v2.get_available_tools()}
    check(want <= v2, f"v2 missing {want - v2}")
    check(want <= set(agent_tools.TOOL_SCHEMAS)
          and want <= set(agent_tools.TOOL_HANDLERS), "v1 stack incomplete")
    import inspect
    from services import agent_router
    src = inspect.getsource(agent_router)
    for name in want:
        check(src.count(f'"{name}"') >= 2,
              f"{name} is not both dispatched and listed terminal in the router")

    tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    res = agent_tools.execute_tool("plan_specific_dinner", {
        "target_date": tomorrow, "dish_names": "steak", "note": "Mom's birthday"})
    check(res['status'] == 'success' and "Mom's birthday" in res['message'],
          f"set by voice, got {res}")
    rec = storage.get_plate(tomorrow)
    check(rec and rec['locked'], f"and it really locked, got {rec}")

    # "Grandma is bringing dinner" — no dishes named at all.
    day_after = (datetime.date.today() + datetime.timedelta(days=2)).isoformat()
    res2 = agent_tools.execute_tool("plan_specific_dinner", {
        "target_date": day_after, "note": "Grandma is bringing dinner"})
    check(res2['status'] == 'success', f"a night with nobody here cooking, got {res2}")

    agent_tools.execute_tool("unlock_dinner", {"target_date": tomorrow})
    check(not storage.get_plate(tomorrow), "and released by voice")


# --- M9: dishes that come as a set ------------------------------------------
# Reported from real use: brisket (takeout) with beans and fries (home) arrived
# together once and the family asked whether that would HOLD. Measured: it did
# not — over a fortnight the trio survived 0 of 3 brisket nights. M5 handles
# coherence as a soft tag affinity, which is a preference, not a relationship.

def scenario_pairing_is_a_relationship_not_a_coincidence():
    reset_db(); _seed_people()
    _settings(sides_per_meal=2, include_dessert=False)
    brisket = _dish('brisket', type='entree', source='ordered')
    beans = _dish('beans', type='side', side_type='other')
    fries = _dish('fries', type='side', side_type='starch')
    for n, st in (('broccoli', 'vegetable'), ('rice', 'starch'),
                  ('salad', 'salad'), ('corn', 'vegetable')):
        _dish(n, type='side', side_type=st)
    for n in ('tacos', 'salmon', 'spaghetti'):
        _dish(n, type='entree')

    def brisket_nights(week):
        return [d for d in week
                if any(x['name'] == 'brisket' for x in d['dishes'])]

    loose = brisket_nights(meals.compose_week('2026-09-10', 14))
    intact_before = [d for d in loose
                     if {'beans', 'fries'} <= {x['name'] for x in d['dishes']}]
    check(loose, "brisket does come up")
    check(not intact_before,
          f"and without a declared pairing the trio does NOT hold, got "
          f"{len(intact_before)}/{len(loose)}")

    meals.set_pairing(brisket['id'], [beans['id'], fries['id']])
    bound = brisket_nights(meals.compose_week('2026-09-10', 14))
    intact_after = [d for d in bound
                    if {'beans', 'fries'} <= {x['name'] for x in d['dishes']}]
    check(bound and len(intact_after) == len(bound),
          f"declared, it holds every time: {len(intact_after)}/{len(bound)}")


def scenario_pairing_is_directed_so_partners_stay_free():
    """The asymmetry IS the design: brisket brings beans, but beans are not
    thereby confined to brisket. A symmetric matrix is the O(n^2) upkeep M5
    refused to inflict."""
    reset_db(); _seed_people()
    _settings(sides_per_meal=1, include_dessert=False)
    brisket = _dish('brisket', type='entree')
    beans = _dish('beans', type='side', side_type='other')
    _dish('tacos', type='entree')
    meals.set_pairing(brisket['id'], [beans['id']])

    week = meals.compose_week('2026-09-10', 10)
    with_tacos = [d for d in week if any(x['name'] == 'tacos' for x in d['dishes'])]
    check(any('beans' in {x['name'] for x in d['dishes']} for d in with_tacos),
          "beans still turn up beside other entrees")


def scenario_only_with_confines_a_dish_to_its_partner():
    reset_db(); _seed_people()
    _settings(sides_per_meal=1, include_dessert=False)
    curry = _dish('curry', type='entree')
    _dish('tacos', type='entree')
    naan = _dish('naan', type='side', side_type='starch')
    _dish('rice', type='side', side_type='starch')
    meals.set_pairing(naan['id'], [curry['id']], 'only_with')

    week = meals.compose_week('2026-09-10', 12)
    for day in week:
        names = {x['name'] for x in day['dishes']}
        if 'naan' in names:
            check('curry' in names,
                  f"naan never appears without curry, got {names}")


def scenario_a_pairing_never_overrides_an_allergy():
    """A pairing is the family saying these go together — not a licence to put
    an allergen on the plate. The hard filter still wins."""
    reset_db(); _seed_people()
    _settings(sides_per_meal=1, include_dessert=False)
    brisket = _dish('brisket', type='entree')
    peanuts = _dish('peanut slaw', type='side', side_type='salad', tags=['peanut'])
    _dish('plain slaw', type='side', side_type='salad')
    meals.set_pairing(brisket['id'], [peanuts['id']])
    for m in storage.get_all_members():
        storage.update_member(m['id'], {'dietary_avoid': ['peanut']})

    week = meals.compose_week('2026-09-10', 6)
    for day in week:
        names = {x['name'] for x in day['dishes']}
        check('peanut slaw' not in names,
              f"the allergen stays off the plate even when paired, got {names}")


def scenario_a_pairing_cycle_terminates():
    reset_db(); _seed_people()
    _settings(sides_per_meal=1, include_dessert=False)
    a = _dish('brisket', type='entree')
    b = _dish('beans', type='side', side_type='other')
    meals.set_pairing(a['id'], [b['id']])
    meals.set_pairing(b['id'], [a['id']])      # the family can easily say both
    week = meals.compose_week('2026-09-10', 2)
    check(week and all(len(d['dishes']) <= 4 for d in week),
          f"mutual pairing does not loop, got {[len(d['dishes']) for d in week]}")


def scenario_paired_sides_fill_the_blocks_they_occupy():
    """A pairing counts AGAINST the block it belongs to rather than piling on
    top of it — brisket bringing beans and fries fills the starch block, so no
    third starch is proposed. It does NOT excuse the other blocks: the family
    asked for a vegetable and beans are not one. That is the gain over the old
    flat side count, where two sides of anything satisfied the plate and the
    vegetable a family said they wanted quietly never arrived."""
    reset_db(); _seed_people()
    brisket = _dish('brisket', type='entree')
    beans = _dish('beans', type='side', side_type='other')     # -> starch
    fries = _dish('fries', type='side', side_type='starch')
    for n, st in (('broccoli', 'vegetable'), ('rice', 'starch')):
        _dish(n, type='side', side_type=st)
    meals.set_pairing(brisket['id'], [beans['id'], fries['id']])

    day = next(d for d in meals.compose_week('2026-09-10', 6)
               if any(x['name'] == 'brisket' for x in d['dishes']))
    names = [x['name'] for x in day['dishes']]
    starch = category_id('starches/carbs')
    starches = sorted(x['name'] for x in day['dishes']
                      if starch in (x.get('category_ids') or []))
    check(starches == ['beans', 'fries'],
          f"the pairing fills the starch block, no third starch, got {starches}")
    check('rice' not in names, f"rice is not piled on top, got {names}")
    check('broccoli' in names,
          f"and the vegetable the family asked for still arrives, got {names}")


def scenario_pairing_tools_in_both_stacks():
    reset_db(); _seed_people(); _settings()
    _dish('brisket', type='entree')
    _dish('beans', type='side', side_type='other')
    _dish('fries', type='side', side_type='starch')
    from services import agent_tools, agent_tools_v2
    want = {"pair_dishes", "unpair_dishes"}
    v2 = {t['name'] for t in agent_tools_v2.get_available_tools()}
    check(want <= v2, f"v2 missing {want - v2}")
    check(want <= set(agent_tools.TOOL_SCHEMAS)
          and want <= set(agent_tools.TOOL_HANDLERS), "v1 stack incomplete")
    import inspect
    from services import agent_router
    src = inspect.getsource(agent_router)
    for name in want:
        check(src.count(f'"{name}"') >= 2,
              f"{name} is not both dispatched and listed terminal in the router")

    res = agent_tools.execute_tool("pair_dishes", {
        "dish_name": "brisket", "partner_names": "beans and fries"})
    check(res['status'] == 'success', f"set by voice, got {res}")
    b = storage.find_dish_by_name('brisket')
    check(len(b['always_with']) == 2,
          f"'beans and fries' parsed as two partners, got {b['always_with']}")

    gone = agent_tools.execute_tool("unpair_dishes", {"dish_name": "brisket"})
    check(gone['status'] == 'success'
          and not storage.find_dish_by_name('brisket')['always_with'],
          f"and undone by voice, got {gone}")


def scenario_variants_of_one_dish_stay_distinguishable():
    """Reported: "pizza made from frozen or ordered out all just show as
    pizza". M4 built `_chip_label` for exactly this and M5 retired slots, which
    quietly took the plate back to bare short_name — so every variant read as
    the family's generic word at the one moment you are choosing between
    them."""
    reset_db(); _seed_people(); _settings()
    frozen = _dish('frozen pizza', short_name='pizza', type='meal')
    takeout = _dish('takeout pizza', short_name='pizza', type='meal',
                    source='ordered')
    homemade = _dish('homemade pizza', short_name='pizza', type='meal')
    solo = _dish('lasagna', short_name='lasagna', type='meal')

    labelled = {d['name']: d['chip'] for d in
                meals.with_chip_labels([frozen, takeout, homemade, solo])}
    check(len(set([labelled['frozen pizza'], labelled['takeout pizza'],
                   labelled['homemade pizza']])) == 3,
          f"three pizzas, three different labels, got {labelled}")
    for name in ('frozen pizza', 'takeout pizza', 'homemade pizza'):
        check('pizza' in labelled[name].lower(),
              f"each still says what it IS, got {labelled[name]!r}")
    check(labelled['lasagna'] == 'lasagna',
          f"a dish with no siblings keeps the family's own short word, "
          f"got {labelled['lasagna']!r}")


def scenario_the_week_payload_carries_the_chip_label():
    reset_db(); _seed_people()
    _settings(sides_per_meal=0, include_dessert=False)
    _dish('frozen pizza', short_name='pizza', type='meal')
    _dish('takeout pizza', short_name='pizza', type='meal')
    week = meals.compose_week('2026-09-10', 2)
    for day in week:
        for d in day['dishes']:
            check(d.get('chip'), f"every dish on the board is labelled, got {d}")


# --- M8: prep that happens outside the cook window ---------------------------
# Reported from real use: some foods need work on a DIFFERENT DAY. Soaking rice
# the night before is cognitive load precisely because nothing about cooking
# dinner prompts it. The dish already carried `needs_ahead`, a label with no
# time and no reminder — the useless half.

def scenario_the_night_before_is_a_moment_not_an_offset():
    """THE load-bearing decision. Soaking rice for a 6pm dinner is something
    you do at ~9pm the evening BEFORE. Dinner-minus-12h is arithmetically
    correct and behaviourally useless — it fires at 6am on the day, hours after
    the water needed to be on."""
    reset_db(); _seed_people()
    _settings(prep_reminder_time="20:30")
    rice = _dish('white rice', type='side', side_type='starch')
    meals.add_prep_step(rice['id'], 'soak', 'night_before')
    step = storage.get_dish(rice['id'])['prep_steps'][0]

    due = meals.prep_step_due_at(step, '2026-09-10', storage.get_settings())
    check(due.date() == datetime.date(2026, 9, 9),
          f"it fires the PREVIOUS day, got {due.date()}")
    check((due.hour, due.minute) == (20, 30),
          f"at the household's evening prep time, got {due.hour}:{due.minute:02d}")

    # An offset would have landed in the small hours of the cooking day.
    naive = meals._dinner_time('2026-09-10') - datetime.timedelta(hours=12)
    check(naive.date() == datetime.date(2026, 9, 10) and naive != due,
          f"the arithmetic answer is a different, useless time ({naive})")


def scenario_hours_before_counts_back_from_when_food_is_needed():
    reset_db(); _seed_people()
    _settings()
    chicken = _dish('chicken', type='entree')
    meals.add_prep_step(chicken['id'], 'marinate', 'hours_before', hours=2)
    step = storage.get_dish(chicken['id'])['prep_steps'][0]

    dinner = meals._dinner_time(DAY)
    due = meals.prep_step_due_at(step, DAY, storage.get_settings())
    check((dinner - due) == datetime.timedelta(hours=2),
          f"two hours before the first sitting, got {dinner - due}")
    check(due.date() == dinner.date(), "on the same day, unlike a soak")


def scenario_prep_is_per_dish_and_opt_in():
    """Not everyone soaks their rice — that is a fact about the household, not
    about rice, so it is never inferred."""
    reset_db(); _seed_people(); _settings()
    a = _dish('white rice', type='side', side_type='starch')
    b = _dish('brown rice', type='side', side_type='starch')
    meals.add_prep_step(a['id'], 'soak', 'night_before')
    check(len(meals.dish_prep_steps(storage.get_dish(a['id']))) == 1, "set on the one")
    check(not meals.dish_prep_steps(storage.get_dish(b['id'])),
          "and nothing was inferred onto the other")

    # Re-stating a step edits it rather than stacking a duplicate.
    meals.add_prep_step(a['id'], 'Soak', 'hours_before', hours=4)
    steps = storage.get_dish(a['id'])['prep_steps']
    check(len(steps) == 1 and steps[0]['when'] == 'hours_before',
          f"same action = an edit, not a second reminder, got {steps}")

    meals.remove_prep_step(a['id'], 'soak')
    check(not meals.dish_prep_steps(storage.get_dish(a['id'])), "and it can be dropped")


def scenario_the_reminder_fires_once_and_not_when_stale():
    reset_db(); _seed_people()
    _settings(prep_reminder_time="20:30")
    rice = _dish('white rice', type='side', side_type='starch')
    meals.add_prep_step(rice['id'], 'soak', 'night_before')
    tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    meals.add_to_plate(tomorrow, rice['id'])          # pin it onto tomorrow

    evening = datetime.datetime.combine(datetime.date.today(),
                                        datetime.time(20, 31))
    sent = []
    fired = meals.run_prep_reminders(lambda m, t, b: sent.append(b), now=evening)
    check(len(fired) == 1 and sent, f"the nudge goes out, got {fired}")
    check('soak' in sent[0].lower() and 'tomorrow' in sent[0].lower(),
          f"and says what and when, got {sent[0]!r}")

    again = meals.run_prep_reminders(lambda m, t, b: sent.append(b),
                                     now=evening + datetime.timedelta(minutes=30))
    check(not again and len(sent) == len(set(sent)),
          "the every-cycle sweep must not re-nudge")

    # Hours later it is no longer useful, so a fresh install stays quiet.
    storage.app_state_table.truncate()
    late = datetime.datetime.combine(datetime.date.today(), datetime.time(23, 59))
    check(not meals.run_prep_reminders(lambda m, t, b: sent.append(b), now=late),
          "a stale nudge is worse than none")


def scenario_an_already_made_dish_needs_no_prep():
    reset_db(); _seed_people()
    _settings(prep_reminder_time="20:30")
    rice = _dish('white rice', type='side', side_type='starch')
    meals.add_prep_step(rice['id'], 'soak', 'night_before')
    tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    meals.add_to_plate(tomorrow, rice['id'])
    meals.toggle_leftover_dish(tomorrow, rice['id'])   # already cooked

    evening = datetime.datetime.combine(datetime.date.today(), datetime.time(20, 31))
    check(not meals.run_prep_reminders(lambda m, t, b: None, now=evening),
          "nothing to soak for a dish that is already made")


def scenario_prep_tools_in_both_stacks():
    reset_db(); _seed_people(); _settings()
    _dish('white rice', type='side', side_type='starch')
    from services import agent_tools, agent_tools_v2
    want = {"set_dish_prep", "clear_dish_prep", "get_prep_ahead"}
    v2 = {t['name'] for t in agent_tools_v2.get_available_tools()}
    check(want <= v2, f"v2 missing {want - v2}")
    check(want <= set(agent_tools.TOOL_SCHEMAS)
          and want <= set(agent_tools.TOOL_HANDLERS), "v1 stack incomplete")
    import inspect
    from services import agent_router
    src = inspect.getsource(agent_router)
    for name in want:
        check(src.count(f'"{name}"') >= 2,
              f"{name} is not both dispatched and listed terminal in the router")

    res = agent_tools.execute_tool("set_dish_prep", {
        "dish_name": "white rice", "action": "soak", "when": "night_before"})
    check(res['status'] == 'success' and 'night before' in res['message'],
          f"set by voice, got {res}")
    d = storage.find_dish_by_name('white rice')
    check(meals.dish_prep_steps(d)[0]['when'] == 'night_before', "and it stuck")

    gone = agent_tools.execute_tool("clear_dish_prep", {"dish_name": "white rice"})
    check(gone['status'] == 'success'
          and not meals.dish_prep_steps(storage.find_dish_by_name('white rice')),
          f"and can be undone by voice, got {gone}")


# --- K1: the kiosk board ----------------------------------------------------

import contextlib


@contextlib.contextmanager
def _stock_image(fn):
    """Swap the network lookup out and PUT IT BACK. A leaked monkeypatch here
    would silently decide the outcome of whatever scenario sorted after it."""
    original = meals.fetch_stock_image
    meals.fetch_stock_image = fn
    try:
        yield
    finally:
        meals.fetch_stock_image = original

def scenario_staples_are_the_we_are_out_of_grid():
    """Staples never reach a list on their own — that IS the classification —
    so running out of one had no gesture except the "+ List" dialog's Add,
    which permanently reclassifies it. The grid is the missing verb."""
    reset_db(); _seed_people(); _settings()
    _dish('rice bowl', type='entree', ingredients=[
        {'name': 'rice', 'kind': 'staple'}, {'name': 'olive oil', 'kind': 'staple'},
        {'name': 'chicken', 'kind': 'fresh'}])
    _dish('stir fry', type='entree', ingredients=[
        {'name': 'Rice', 'kind': 'staple'}, {'name': 'soy sauce', 'kind': 'staple'},
        {'name': 'peppers', 'kind': 'fresh'}])

    st = meals.household_staples()
    names = [s['name'].lower() for s in st]
    check('chicken' not in names and 'peppers' not in names,
          f"fresh things are not staples — they get bought by the plan, got {names}")
    check(names[0] == 'rice' and st[0]['dish_count'] == 2,
          f"ranked by how many dishes depend on it, got {st[:2]}")
    check(len([n for n in names if n == 'rice']) == 1,
          f"'rice' and 'Rice' are one entry, got {names}")


def scenario_the_cart_shortcut_learns_what_the_family_actually_buys():
    """Reported: the grid should reflect real habits, not recipe trivia.
    Ranking by how many dishes mention an ingredient is a fact about the
    RECIPES; how often the family buys it is a fact about the household."""
    reset_db(); _seed_people(); _settings()
    # black pepper is in everything and bought almost never; milk is in no
    # recipe at all and bought every week.
    for n in ('a', 'b', 'c', 'd'):
        _dish(n, type='entree', ingredients=[
            {'name': 'black pepper', 'kind': 'staple'},
            {'name': n + ' meat', 'kind': 'fresh'}])

    first = meals.household_staples()
    check(first[0]['name'] == 'black pepper',
          f"with no history, recipe staples seed the grid, got {first[0]}")
    check('milk' not in [s['name'] for s in first], "milk is in no recipe")

    lst = storage.ensure_default_shopping_list()
    from models.schemas import ShoppingItem
    for _ in range(3):
        it = ShoppingItem(list_id=lst['id'], name='Milk').model_dump()
        storage.add_shopping_item(it)
        storage.check_shopping_item(it['id'], True)

    after = meals.household_staples()
    check(after[0]['name'].lower() == 'milk' and after[0]['buys'] == 3,
          f"what is really bought outranks what recipes mention, got {after[:2]}")
    check(after[0]['known'] is True and
          next(s for s in after if s['name'] == 'black pepper')['known'] is False,
          "and the grid can tell a learned item from a seeded guess")


def scenario_the_purchase_tally_outlives_the_shop():
    """clear_checked_shopping_items DELETES the rows, so a tally kept only in
    the items table would be wiped every single shop."""
    reset_db(); _seed_people(); _settings()
    lst = storage.ensure_default_shopping_list()
    from models.schemas import ShoppingItem
    it = ShoppingItem(list_id=lst['id'], name='eggs').model_dump()
    storage.add_shopping_item(it)
    storage.check_shopping_item(it['id'], True)

    storage.clear_checked_shopping_items(lst['id'])
    check(not storage.get_shopping_items(lst['id']), "the row is gone after the sweep")
    check(storage.get_purchase_tally().get('eggs', {}).get('count') == 1,
          f"but the tally survives it, got {storage.get_purchase_tally()}")

    # Two phones tapping the same row must not inflate the count.
    it2 = ShoppingItem(list_id=lst['id'], name='eggs').model_dump()
    storage.add_shopping_item(it2)
    storage.check_shopping_item(it2['id'], True)
    storage.check_shopping_item(it2['id'], True)
    check(storage.get_purchase_tally()['eggs']['count'] == 2,
          f"counted on the false->true edge only, got {storage.get_purchase_tally()}")

    # Unchecking is a correction, not a purchase.
    storage.check_shopping_item(it2['id'], False)
    check(storage.get_purchase_tally()['eggs']['count'] == 2,
          "putting something back does not count as buying it")


def scenario_being_out_of_a_staple_does_not_reclassify_it():
    """The load-bearing distinction. "We're out of rice this week" says nothing
    about whether rice is a staple — that is a standing fact about the
    household, and only the family can change it."""
    reset_db(); _seed_people(); _settings()
    d = _dish('rice bowl', type='entree', ingredients=[
        {'name': 'rice', 'kind': 'staple'}, {'name': 'chicken', 'kind': 'fresh'}])
    lst = storage.ensure_default_shopping_list()

    from models.schemas import ShoppingItem
    storage.add_shopping_item(ShoppingItem(list_id=lst['id'], name='rice',
                                           added_via='kiosk').model_dump())

    fresh = storage.get_dish(d['id'])
    kinds = {i['name']: i['kind'] for i in fresh['ingredients']}
    check(kinds['rice'] == 'staple',
          f"rice is still a staple after being bought once, got {kinds}")
    check('rice' in [s['name'] for s in meals.household_staples()],
          "and still appears in the grid next week")


def scenario_the_board_reports_work_not_the_prep_horizon():
    """Reported: every kiosk block said "180 min". The block was showing
    cook_window_mins — free time available, clamped to PREP_HORIZON_MINS — so
    every unconstrained evening printed the identical ceiling and the board
    looked broken. The week payload has to carry what the board actually
    needs: how much WORK the night is, and whether the window truly pinches."""
    reset_db(); _seed_people()
    _settings(sides_per_meal=0, include_dessert=False)
    _dish('roast chicken', type='entree', prep_ahead_mins=5, finish_mins=25,
          unattended_mins=40, ingredients=[{'name': 'chicken', 'kind': 'fresh'}])

    week = meals.compose_week('2026-08-10', 3)
    for day in week:
        check(day['cook_window_mins'] == meals.PREP_HORIZON_MINS,
              f"an open evening reports the horizon, which is why every block "
              f"read the same number, got {day['cook_window_mins']}")
        check(day['prep_ahead_mins'] == 5 and day['finish_mins'] == 25
              and day['unattended_mins'] == 40,
              f"and the real work is available to show instead, got {day}")
        check(day['has_cook'] is True, f"a cooking adult was considered, got {day}")


def scenario_a_zero_cook_window_means_two_different_things():
    """0 is what an UNSOLVED day reports and also what a genuinely impossible
    evening reports. Conflating them either suppresses a real M2 finding or
    puts a scary number on every block of an empty install."""
    reset_db(); _seed_people()
    _settings(sides_per_meal=0, include_dessert=False)
    _dish('spaghetti', type='entree', prep_ahead_mins=5, finish_mins=20,
          ingredients=[{'name': 'pasta', 'kind': 'fresh'}])

    storage.set_cached_schedule(_tight_evening())
    day = meals.compose_week(DAY, 1)[0]
    check(day['has_cook'] is True,
          f"somebody who COULD cook was considered, so a 0 window here would "
          f"be a real finding rather than missing data, got {day['has_cook']}")

    # Nobody who can cook at all: the same 0 now means "we don't know".
    for m in storage.get_all_members():
        if m.get('role') == 'parent':
            storage.update_member(m['id'], {'role': 'child', 'is_child': True})
    day2 = meals.compose_week(DAY, 1)[0]
    check(day2['has_cook'] is False,
          f"so the board can stay silent instead of warning, got {day2['has_cook']}")


def scenario_a_dish_image_prefers_the_familys_own_photo():
    reset_db(); _seed_people(); _settings()
    d = _dish('tacos', type='meal')
    check(not storage.get_dish(d['id']).get('image_url'), "no picture to begin with")

    meals.set_dish_image(d['id'], 'https://example.com/our-tacos.jpg', 'family')
    got = storage.get_dish(d['id'])
    check(got['image_url'].endswith('our-tacos.jpg') and got['image_source'] == 'family',
          f"the family's photo is stored, got {got.get('image_source')}")

    # A backfill must never paint over it.
    with _stock_image(lambda dish: 'https://stock.example/generic.jpg'):
        res = meals.backfill_dish_images()
    check(storage.get_dish(d['id'])['image_url'].endswith('our-tacos.jpg'),
          "backfill never overwrites the family's own picture")
    check(res['skipped'] >= 1, f"and says it skipped it, got {res}")


def scenario_the_unsplash_key_is_read_the_same_way_the_rest_of_the_app_reads_it():
    """The backfill had its OWN key lookup rather than using
    maps.get_map_option, which every other caller goes through and which checks
    SETTINGS before /data/options.json.

    Not the cause of "the board has no pictures" — that was simply that nothing
    ever ran the backfill — but a duplicate resolver that silently disagrees
    with the shared one is how this codebase keeps producing bugs where both
    halves are individually fine.
    """
    reset_db(); _seed_people()
    from services import maps

    _settings(unsplash_api_key='key-from-the-config-ui')
    check(meals.unsplash_key() == 'key-from-the-config-ui',
          f"a key in settings is found, got {meals.unsplash_key()!r}")
    check(maps.get_map_option('unsplash_api_key', None) == meals.unsplash_key(),
          "and by exactly the resolver the rest of the app uses")

    _settings()   # no key anywhere
    check(meals.unsplash_key() is None,
          f"absent stays absent, got {meals.unsplash_key()!r}")


def scenario_stock_images_search_for_a_cooked_dish_not_an_ingredient():
    """Searching the bare name finds raw meat and anatomical diagrams — worse
    than no picture for the child who needed it."""
    reset_db(); _seed_people(); _settings()
    q = meals.dish_image_query({'name': 'chicken thighs'})
    check('chicken thighs' in q and 'cooked' in q and 'dish' in q,
          f"the query is biased toward a plated meal, got {q!r}")


def scenario_backfill_fills_only_what_is_missing_and_is_capped():
    reset_db(); _seed_people(); _settings()
    for n in ('a', 'b', 'c', 'd'):
        _dish(n, type='entree')
    calls = []
    with _stock_image(lambda dish: (calls.append(dish['name'])
                                    or f"https://stock/{dish['name']}.jpg")):
        res = meals.backfill_dish_images(limit=2)
        check(len(res['filled']) == 2 and len(calls) == 2,
              f"capped — a board that stalls fetching pictures is worse than "
              f"one with none, got {res}")
        res2 = meals.backfill_dish_images(limit=10)
    check(len(res2['filled']) == 2 and res2['skipped'] == 2,
          f"the two already done are skipped, got {res2}")


def scenario_no_image_is_a_normal_state_not_a_failure():
    reset_db(); _seed_people(); _settings()
    _dish('mystery casserole', type='meal')
    with _stock_image(lambda dish: None):           # no key configured
        res = meals.backfill_dish_images()
    check(res['status'] == 'success' and not res['filled'] and res['failed'] == 1,
          f"reported, not raised — the board renders fine without pictures, got {res}")


def scenario_m6_tools_in_both_stacks():
    reset_db(); _seed_people()
    _settings(sides_per_meal=1, include_dessert=False)
    _week_repertoire()
    from services import agent_tools, agent_tools_v2
    want = {"get_week_dinners", "approve_week_dinners"}
    v2 = {t['name'] for t in agent_tools_v2.get_available_tools()}
    check(want <= v2, f"v2 missing {want - v2}")
    check(want <= set(agent_tools.TOOL_SCHEMAS)
          and want <= set(agent_tools.TOOL_HANDLERS), "v1 stack incomplete")
    # The router must both DISPATCH them and treat them as terminal, or the
    # week answer costs a needless 40-80s concluding Gemma round.
    import inspect
    from services import agent_router
    src = inspect.getsource(agent_router)
    for name in want:
        check(src.count(f'"{name}"') >= 2,
              f"{name} is not both dispatched and listed terminal in the router")

    read = agent_tools.execute_tool("get_week_dinners", {})
    check(read['status'] == 'success' and 'Shopping' in read['message'],
          f"the v1 bridge reads the week, got {read}")
    done = agent_tools.execute_tool("approve_week_dinners", {})
    check(done['status'] == 'success' and 'nights are set' in done['message'],
          f"and approves it, got {done}")
    check(all(d['pinned'] for d in meals.compose_week(
        meals.plan_window()['start'], meals.plan_window()['days'])),
        "approving by voice pins the same nights the button does")


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


# --- O0: holiday food is not Tuesday food ------------------------------------

def scenario_occasion_dishes_stay_out_of_the_everyday_pool():
    """The family's complaint exactly: keeping turkey in the standing pool so
    it exists twice a year pollutes every proposal for the other fifty weeks."""
    reset_db(); _seed_people()
    _settings(sides_per_meal=1, include_dessert=False)
    _dish('roast turkey', type='entree', scope='occasion')
    _dish('cornbread stuffing', type='side', side_type='starch', scope='occasion')
    _dish('tacos', type='entree')
    _dish('steamed broccoli', type='side', side_type='vegetable')

    week = meals.compose_week('2026-09-07', 14)
    served = {x['name'] for d in week for x in d['dishes']}
    check(served, "a fortnight still composes")
    check('roast turkey' not in served and 'cornbread stuffing' not in served,
          f"and never proposes occasion food, got {sorted(served)}")
    check('tacos' in served, "while the everyday pool carries the plan")


def scenario_an_occasion_dish_is_still_eaten_as_a_leftover():
    """THE trap. Scope gates PROPOSAL, never PRESENCE: the days right after
    Thanksgiving are precisely when the turkey has to land on an ordinary
    plate, and a naive filter blocks it from the days it exists to cover."""
    reset_db(); _seed_people()
    _settings(sides_per_meal=1, include_dessert=False)
    turkey = _dish('roast turkey', type='entree', scope='occasion',
                   holds_well=True, portability='utensils_ok')
    _dish('tacos', type='entree')
    _dish('steamed broccoli', type='side', side_type='vegetable')

    _leftover(date=DAY, label='turkey', dish_ids=[turkey['id']])
    names = {d['name'] for d in meals.compose_plate(DAY)}
    check('roast turkey' in names,
          f"the bird that already exists gets eaten, got {sorted(names)}")


def scenario_a_hand_picked_occasion_dish_is_never_filtered():
    """Eligibility is not selection. Nothing stops a family from putting the
    turkey on a night deliberately — the pool filter governs what is OFFERED."""
    reset_db(); _seed_people()
    _settings(sides_per_meal=1, include_dessert=False)
    turkey = _dish('roast turkey', type='entree', scope='occasion')
    _dish('tacos', type='entree')

    meals.set_plate_lock('2026-11-26', True, 'Thanksgiving', [turkey['id']])
    day = next(d for d in meals.compose_week('2026-11-26', 1))
    check([x['name'] for x in day['dishes']] == ['roast turkey'],
          f"the night the family named keeps its dish, got {day['dishes']}")


def scenario_occasion_food_is_invisible_to_ordinary_rule_accounting():
    """A turkey carries a `meat` tag like anything else. If it counted toward
    "meat about once a week" the family would get a baffling vegetarian
    weekend after every holiday — and the cap must not block the bird either."""
    reset_db(); _seed_people()
    _settings(sides_per_meal=1, include_dessert=False)
    turkey = _dish('roast turkey', type='entree', scope='occasion', tags=['meat'])
    _dish('beef tacos', type='entree', tags=['meat'])
    _dish('lentil soup', type='entree')
    _dish('steamed broccoli', type='side', side_type='vegetable')
    meals.add_meal_rule('meat about once a week', 'frequency_cap',
                        tags=['meat'], max_servings=1, window_days=7)

    ctx = meals.rule_context(meals._as_of_ts(DAY), {}, storage.get_settings(), {})
    check(turkey['id'] not in ctx['blocked'],
          "the cap never blocks a dish it should not be counting")

    # Serving it yesterday must not spend this week's allowance.
    storage.update_dish(turkey['id'],
                        {'last_served_at': meals._as_of_ts(DAY) - 86400.0})
    after = meals.rule_context(meals._as_of_ts(DAY), {}, storage.get_settings(), {})
    tacos = storage.find_dish_by_name('beef tacos')
    check(tacos['id'] not in after['blocked'],
          "and eating it yesterday leaves the ordinary week untouched")


def scenario_the_model_fills_the_kitchen_metadata_it_can_guess():
    """Same bargain as every other dish field: the human supplies a name or the
    repertoire never reaches fifteen entries."""
    reset_db()
    d = meals._clean_dish({
        'name': 'roasted russet potatoes', 'type': 'side', 'side_type': 'starch',
        'equipment': 'oven', 'oven_temp_f': 425, 'serves': 6, 'scope': 'everyday',
    })
    check(d['equipment'] == 'oven' and d['oven_temp_f'] == 425,
          f"oven and its sharing key survive, got {d.get('oven_temp_f')}")
    check(d['serves'] == 6, f"as does the serving count, got {d.get('serves')}")

    stove = meals._clean_dish({'name': 'white rice', 'equipment': 'burner',
                                  'oven_temp_f': 350})
    check(stove['oven_temp_f'] is None,
          "a burner dish carries no phantom oven temperature")
    plain = meals._clean_dish({'name': 'green salad'})
    check(plain['equipment'] == 'none' and plain['scope'] == 'everyday'
          and plain['serves'] == 4,
          f"and the defaults are the everyday ones, got {plain.get('scope')}")


# --- O0: the kitchen as a resource model -------------------------------------

def scenario_the_kitchen_reduces_to_the_old_arithmetic():
    """THE contract. One cook, one oven, no temperature clash — every number
    must be byte-identical to the sum/max this app shipped with, or the
    replacement is a behaviour change wearing a refactor's clothes."""
    from services import kitchen
    plate = [
        {'prep_ahead_mins': 5, 'finish_mins': 5, 'unattended_mins': 40,
         'equipment': 'oven', 'oven_temp_f': 400},
        {'prep_ahead_mins': 2, 'finish_mins': 0, 'unattended_mins': 20,
         'equipment': 'burner'},
        {'prep_ahead_mins': 0, 'finish_mins': 8, 'unattended_mins': 0,
         'equipment': 'none'},
    ]
    got = kitchen.totals(plate, {})
    want_prep = sum(d['prep_ahead_mins'] for d in plate)
    want_finish = sum(d['finish_mins'] for d in plate)
    want_unatt = max(d['unattended_mins'] for d in plate)
    check(got['prep_ahead_mins'] == want_prep,
          f"prep still sums for one cook, got {got['prep_ahead_mins']}")
    check(got['finish_mins'] == want_finish,
          f"and so does the finish, got {got['finish_mins']}")
    check(got['unattended_mins'] == want_unatt,
          f"the oven still overlaps the rice, got {got['unattended_mins']}")
    check(not got['oven_conflicts'], "and nothing is reported as colliding")


def scenario_dishes_with_no_kitchen_metadata_behave_exactly_as_before():
    """Every dish saved before this shipped has no equipment and no
    temperature. They must not start colliding retroactively."""
    from services import kitchen
    legacy = [{'prep_ahead_mins': 10, 'finish_mins': 15, 'unattended_mins': 45},
              {'prep_ahead_mins': 5, 'finish_mins': 10, 'unattended_mins': 30}]
    got = kitchen.totals(legacy, {})
    check(got['prep_ahead_mins'] == 15 and got['finish_mins'] == 25,
          f"hands-on sums, got {got['prep_ahead_mins']}/{got['finish_mins']}")
    check(got['unattended_mins'] == 45,
          f"and unattended takes the max, got {got['unattended_mins']}")


def scenario_two_temperatures_cannot_share_one_oven():
    """The error that hid on weeknights. Space is the constraint people
    picture; temperature is the one that actually blocks."""
    from services import kitchen
    clash = [{'unattended_mins': 40, 'equipment': 'oven', 'oven_temp_f': 350},
             {'unattended_mins': 20, 'equipment': 'oven', 'oven_temp_f': 425}]
    got = kitchen.totals(clash, {})
    check(got['unattended_mins'] == 60,
          f"they queue rather than overlapping, got {got['unattended_mins']}")
    check([c['temp_f'] for c in got['oven_conflicts']] == [350, 425],
          f"and the collision is NAMED, longest first, got {got['oven_conflicts']}")

    same = [{'unattended_mins': 40, 'equipment': 'oven', 'oven_temp_f': 350},
            {'unattended_mins': 20, 'equipment': 'oven', 'oven_temp_f': 350}]
    check(kitchen.totals(same, {})['unattended_mins'] == 40,
          "while one temperature shares the oven freely")
    check(kitchen.totals(clash, {'kitchen_ovens': 2})['unattended_mins'] == 40,
          "and a second oven dissolves the clash entirely")


def scenario_a_second_pair_of_hands_shortens_the_evening():
    """`hands_on = sum` assumed one cook, which is the assumption that breaks
    the moment anybody offers to help."""
    from services import kitchen
    plate = [{'finish_mins': 20}, {'finish_mins': 20}, {'finish_mins': 10}]
    solo = kitchen.totals(plate, {'kitchen_cooks': 1})['finish_mins']
    pair = kitchen.totals(plate, {'kitchen_cooks': 2})['finish_mins']
    check(solo == 50, f"one cook works through them in turn, got {solo}")
    check(pair == 25, f"two share the load, got {pair}")
    check(kitchen.totals([{'finish_mins': 40}], {'kitchen_cooks': 3})['finish_mins'] == 40,
          "but three cooks cannot make one dish cook faster")
    check(kitchen.totals(plate, {'kitchen_cooks': 1}, cooks=2)['finish_mins'] == 25,
          "and a hosting plate can raise the count without touching the setting")


def scenario_a_burner_dish_holds_its_ring_while_someone_stands_there():
    """A stir-fry is 25 minutes of hands-on AND 25 minutes of occupied burner.
    Counting only the unattended part means burners are never contended for
    exactly the dishes that contend for them."""
    from services import kitchen
    stove = [{'finish_mins': 25, 'unattended_mins': 0, 'equipment': 'burner'},
             {'finish_mins': 20, 'unattended_mins': 0, 'equipment': 'burner'}]
    one = kitchen.totals(stove, {'kitchen_burners': 1})
    check(one['unattended_mins'] == 45,
          f"one ring means they queue, got {one['unattended_mins']}")
    check(kitchen.totals(stove, {'kitchen_burners': 4})['unattended_mins'] == 25,
          "four rings and they run side by side")


def scenario_an_already_made_dish_occupies_no_oven_at_all():
    """Leftovers leave the kitchen model entirely rather than contributing a
    zero — otherwise a reheated casserole still books the oven it does not
    need."""
    reset_db(); _seed_people()
    _settings(sides_per_meal=1, include_dessert=False)
    roast = _dish('roast beef', type='entree', prep_ahead_mins=10, finish_mins=10,
                  unattended_mins=90, equipment='oven', oven_temp_f=325)
    pie = _dish('apple pie', type='dessert', finish_mins=5,
                unattended_mins=45, equipment='oven', oven_temp_f=425)
    both = meals.plate_totals([roast, pie], DAY)
    check(both['unattended_mins'] == 135,
          f"fresh, the two temperatures queue, got {both['unattended_mins']}")

    _leftover(date=DAY, label='beef', dish_ids=[roast['id']])
    left = meals.plate_totals([roast, pie], DAY)
    check(left['unattended_mins'] == 45,
          f"with the beef already made only the pie books the oven, got {left}")
    check(left['prep_ahead_mins'] == 0 and left['finish_mins'] == 5,
          "and it costs none of the hands either")


def _thanksgiving():
    return [
        {'name': 'roast turkey', 'short_name': 'turkey', 'prep_ahead_mins': 20,
         'finish_mins': 20, 'unattended_mins': 240, 'equipment': 'oven',
         'oven_temp_f': 325, 'serves': 12},
        {'name': 'roasted potatoes', 'short_name': 'potatoes', 'prep_ahead_mins': 20,
         'finish_mins': 5, 'unattended_mins': 45, 'equipment': 'oven',
         'oven_temp_f': 425, 'serves': 4},
        {'name': 'gravy', 'short_name': 'gravy', 'prep_ahead_mins': 0,
         'finish_mins': 15, 'unattended_mins': 0, 'equipment': 'burner', 'serves': 12},
    ]


def scenario_the_run_sheet_counts_back_from_when_people_eat():
    from services import kitchen
    r = kitchen.run_sheet(_thanksgiving(), '16:00',
                          {'kitchen_ovens': 1, 'kitchen_burners': 4}, cooks=2)
    check(r['exact'], "the solver answered")
    check(r['start_at'] == '11:00' or r['span_mins'] >= 300,
          f"and starting time reflects a four-hour bird, got {r['start_at']}")
    at = {s['dish'] + ':' + s['kind']: s['at'] for s in r['steps']}
    mins = {k: int(v[:2]) * 60 + int(v[3:]) for k, v in at.items()}
    check(at['turkey:cook'] < at['potatoes:cook'],
          f"the oven runs the long dish first, got {at}")
    # 325 then 425 in ONE oven. The oven frees when the bird comes OUT — which
    # is `cook + unattended`, not when carving finishes: the whole point of the
    # move is that the turkey rests on the counter while the potatoes go in.
    check(mins['potatoes:cook'] >= mins['turkey:cook'] + 240,
          f"the second temperature waits for the oven, got {at}")
    check(mins['turkey:finish'] >= mins['turkey:cook'] + 240,
          f"and nothing is carved before it is cooked, got {at}")


def scenario_finishing_work_lands_against_the_serve_time():
    """The first cut maximised only the earliest start, which cheerfully
    finished the gravy five hours before dinner — technically before serving
    and completely useless."""
    from services import kitchen
    r = kitchen.run_sheet(_thanksgiving(), '16:00',
                          {'kitchen_ovens': 1, 'kitchen_burners': 4}, cooks=2)
    gravy = next(s for s in r['steps'] if s['dish'] == 'gravy')
    check(gravy['at'] >= '15:00',
          f"the gravy is made near the meal, not at dawn, got {gravy['at']}")


def scenario_the_run_sheet_falls_back_rather_than_vanishing():
    """A sheet that fails open with a safe, pessimistic answer beats one that
    disappears on the day somebody needed it."""
    from services import kitchen
    seq = kitchen._sequential_sheet(_thanksgiving(), 1)
    check(seq['span_mins'] == 365 and not seq['exact'],
          f"one dish after another, and it says so, got {seq['span_mins']}")


def scenario_the_run_sheet_is_pull_not_push_in_both_stacks():
    reset_db(); _seed_people()
    _settings(sides_per_meal=1, include_dessert=False)
    _dish('roast beef', type='entree', prep_ahead_mins=15, finish_mins=15,
          unattended_mins=90, equipment='oven', oven_temp_f=325)
    _dish('green salad', type='side', side_type='salad', finish_mins=10)
    from services import agent_tools, agent_tools_v2
    check('get_run_sheet' in {t['name'] for t in agent_tools_v2.get_available_tools()},
          "v2 offers it")
    check('get_run_sheet' in agent_tools.TOOL_SCHEMAS
          and 'get_run_sheet' in agent_tools.TOOL_HANDLERS, "and so does v1")
    res = agent_tools.execute_tool('get_run_sheet',
                                   {'target_date': DAY, 'serve_at': '18:00'})
    check('Start at' in res['message'] and '18:00' in res['message'],
          f"and it answers with clock times, got {res['message'][:120]}")


def scenario_an_empty_night_says_so_instead_of_inventing_a_schedule():
    reset_db(); _seed_people()
    _settings(sides_per_meal=1, include_dessert=False)
    from services import agent_tools_v2
    res = agent_tools_v2.get_run_sheet(DAY)
    check('nothing to cook' in res['message'],
          f"an empty plate is a plain answer, got {res['message']}")


def scenario_scaling_multiplies_the_hands_not_the_oven():
    """Four times the potatoes is four times the peeling and NOT four times
    the roasting. A tray that genuinely needs longer is a bigger thing, which
    M4 already settled: that is its own dish, not a multiplier."""
    from services import kitchen
    plate = [{'prep_ahead_mins': 20, 'finish_mins': 10, 'unattended_mins': 45,
              'equipment': 'oven', 'oven_temp_f': 400, 'serves': 4}]
    base = kitchen.totals(plate, {})
    big = kitchen.totals(plate, {}, serving_for=16)
    check(base['prep_ahead_mins'] == 20 and big['prep_ahead_mins'] == 80,
          f"prep scales with the headcount, got {big['prep_ahead_mins']}")
    check(big['finish_mins'] == 40, f"and so does the finish, got {big['finish_mins']}")
    check(big['unattended_mins'] == 45,
          f"the oven does NOT, got {big['unattended_mins']}")
    check(kitchen.totals(plate, {}, serving_for=2)['prep_ahead_mins'] == 20,
          "and cooking for fewer never makes it faster")


def scenario_each_dish_scales_from_what_it_serves():
    """A main that serves four and a salad that serves eight are not stretched
    by the same amount — which is why `serves` is per dish."""
    from services import kitchen
    plate = [{'prep_ahead_mins': 10, 'serves': 4},
             {'prep_ahead_mins': 10, 'serves': 8}]
    got = kitchen.totals(plate, {}, serving_for=16)
    check(got['prep_ahead_mins'] == 60,
          f"40 for the four-serving dish plus 20 for the eight, got {got['prep_ahead_mins']}")


def scenario_hosting_survives_an_edit_and_a_lock():
    """The same failure the lock had once: `_persist_plate` rebuilds the record
    from scratch, so swapping a side on the night twelve people are coming
    must not quietly reset it to a family of four."""
    reset_db(); _seed_people()
    _settings(sides_per_meal=1, include_dessert=False)
    _dish('roast beef', type='entree', prep_ahead_mins=20, finish_mins=10)
    salad = _dish('green salad', type='side', side_type='salad', finish_mins=10)

    meals.set_plate_hosting(DAY, serving_for=12, cooks=2)
    check(storage.get_plate(DAY)['serving_for'] == 12, "the headcount is recorded")
    check(not storage.get_plate(DAY)['edited'],
          "and saying it does NOT pin the night — it is a fact, not a decision")

    meals.add_to_plate(DAY, [salad['id']]) if hasattr(meals, 'add_to_plate') \
        else meals._persist_plate(DAY, storage.get_dishes_by_ids([salad['id']]))
    rec = storage.get_plate(DAY)
    check(rec['serving_for'] == 12 and rec['cooks'] == 2,
          f"an edit carries it forward, got {rec.get('serving_for')}/{rec.get('cooks')}")

    meals.set_plate_lock(DAY, True, 'Thanksgiving')
    rec = storage.get_plate(DAY)
    check(rec['serving_for'] == 12 and rec['cooks'] == 2,
          f"and so does a lock, got {rec.get('serving_for')}")


def scenario_hosting_reaches_every_surface_that_renders_the_night():
    """Typed on Tonight, true on the week strip: the totals read the stored
    plate rather than only the argument they were handed."""
    reset_db(); _seed_people()
    _settings(sides_per_meal=1, include_dessert=False)
    _dish('roast beef', type='entree', prep_ahead_mins=20, finish_mins=10)
    _dish('green salad', type='side', side_type='salad', finish_mins=10)
    meals.set_plate_hosting(DAY, serving_for=12, cooks=1)

    day = next(d for d in meals.compose_week(DAY, 1))
    check(day['serving_for'] == 12,
          f"the week strip knows, got {day.get('serving_for')}")
    hands = (day['prep_ahead_mins'] or 0) + (day['finish_mins'] or 0)
    check(hands >= 90, f"and reports the real evening, got {hands} min")

    meals.set_plate_hosting(DAY, serving_for=0)
    back = next(d for d in meals.compose_week(DAY, 1))
    check(not back['serving_for'], "clearing it returns an ordinary night")


def scenario_hosting_is_sayable_and_answers_with_the_consequence():
    """"Saved" is not what anyone wants back from this — how long the evening
    now takes is the reason they said it out loud."""
    reset_db(); _seed_people()
    _settings(sides_per_meal=1, include_dessert=False)
    _dish('roast beef', type='entree', prep_ahead_mins=20, finish_mins=10,
          unattended_mins=90, equipment='oven', oven_temp_f=325)
    _dish('apple pie', type='dessert', finish_mins=10, unattended_mins=45,
          equipment='oven', oven_temp_f=425)
    from services import agent_tools, agent_tools_v2
    check('set_hosting' in {t['name'] for t in agent_tools_v2.get_available_tools()},
          "v2 offers it")
    check('set_hosting' in agent_tools.TOOL_SCHEMAS
          and 'set_hosting' in agent_tools.TOOL_HANDLERS, "and so does v1")

    res = agent_tools.execute_tool('set_hosting',
                                   {'target_date': DAY, 'serving_for': 12, 'cooks': 2})
    check(storage.get_plate(DAY)['serving_for'] == 12,
          f"the v1 bridge writes through, got {res}")
    check('hands-on' in res['message'], f"and reports the cost, got {res['message']}")
    check('2 of you cooking' in res['message'], "naming who is doing it")


def scenario_dish_scope_is_sayable_in_both_stacks():
    """Anything the family can tap they must be able to say, and the reply has
    to promise PROPOSAL rather than availability — "I've removed the turkey"
    is not what happened and not what anybody wants to hear."""
    reset_db(); _seed_people()
    _settings()
    _dish('roast turkey', type='entree')
    from services import agent_tools, agent_tools_v2
    check('set_dish_scope' in {t['name'] for t in agent_tools_v2.get_available_tools()},
          "v2 offers the tool")
    check('set_dish_scope' in agent_tools.TOOL_SCHEMAS
          and 'set_dish_scope' in agent_tools.TOOL_HANDLERS, "and so does v1")

    res = agent_tools.execute_tool('set_dish_scope', {'dish_name': 'turkey'})
    check(storage.find_dish_by_name('roast turkey')['scope'] == 'occasion',
          f"the v1 bridge writes through, got {res}")
    check('pick' in res['message'] and 'leftover' in res['message'],
          f"and says it is still pickable, got {res['message']}")

    agent_tools_v2.set_dish_scope('turkey', occasion_only=False)
    check(storage.find_dish_by_name('roast turkey')['scope'] == 'everyday',
          "and it comes back the same way")


def scenario_a_dish_fills_at_most_one_slot():
    """The rule that keeps multi-category dishes from making a family do
    arithmetic. Black beans are the protein next to rice and the starch next to
    a steak — which the old fixed side_type could not say at all — but they can
    never satisfy both blocks at once."""
    reset_db(); _seed_people()
    beans = _dish('black beans', category_ids=[category_id('protein'),
                                               category_id('starches/carbs')])
    _dish('broccoli', type='side', side_type='vegetable')
    storage.set_cached_schedule({"events": [], "assignments": {},
                                 "matched_rules": {}, "scheduled_errands": []})
    dishes = meals.compose_plate(DAY)
    check([d['name'] for d in dishes].count('black beans') == 1,
          f"beans appear once, not once per category, got {[d['name'] for d in dishes]}")
    # With nothing else able to be a starch, the starch block simply goes
    # unfilled — minimums bend rather than duplicating a dish.
    starches = [d for d in dishes
                if category_id('starches/carbs') in (d.get('category_ids') or [])]
    check(len(starches) <= 1, f"no double-counting, got {starches}")

    # Give it a dedicated starch and beans free up to be the protein.
    _dish('rice', type='side', side_type='starch')
    names = [d['name'] for d in meals.compose_plate(DAY)]
    check('black beans' in names and 'rice' in names,
          f"beans answer the protein, rice the starch, got {names}")


def scenario_a_whole_meal_satisfies_the_composition():
    """Marking spaghetti a meal is one word and means "nothing beside it" —
    the alternative was tagging it protein+starch and deleting the vegetables
    off every spaghetti night forever."""
    reset_db(); _seed_people()
    _dish('spaghetti & meat sauce', type='meal')
    _dish('broccoli', type='side', side_type='vegetable')
    _dish('rice', type='side', side_type='starch')
    fruit = _dish('fresh fruit', category_ids=[category_id('something sweet')])
    storage.set_cached_schedule({"events": [], "assignments": {},
                                 "matched_rules": {}, "scheduled_errands": []})

    sweet = next(c for c in storage.get_dish_categories() if c['name'] == 'something sweet')
    sweet['min_per_plate'] = 1        # ...but something sweet opted in
    storage.save_dish_category(sweet)
    names = [d['name'] for d in meals.compose_plate(DAY)]
    check('spaghetti & meat sauce' in names, "the meal leads")
    check('broccoli' not in names and 'rice' not in names,
          f"and nothing is served beside it, got {names}")
    check(fruit['name'] in names,
          f"except the block that opted in with with_complete_meal, got {names}")


def scenario_categories_are_seeded_from_what_the_family_already_has():
    """Nobody re-enters 25 dishes. The old taxonomy migrates into the family's
    own list, which they then rename and re-range."""
    reset_db()
    with storage.db_lock:
        storage.dish_categories_table.truncate()
        storage.app_state_table.truncate()
    # A genuine pre-v2.108 repertoire: the old vocabulary, no categories.
    for name, t, st in (('roast chicken', 'entree', None),
                        ('broccoli', 'side', 'vegetable'),
                        ('tacos', 'meal', None),
                        ('fresh fruit', 'dessert', None)):
        storage.add_dish({'id': name.replace(' ', '-'), 'name': name,
                          'type': t, 'side_type': st, 'category_ids': [],
                          'is_active': True})

    storage.ensure_dish_categories()
    names = [c['name'] for c in storage.get_dish_categories()]
    check('protein' in names and 'vegetables' in names and 'something sweet' in names,
          f"categories seeded from the repertoire, got {names}")
    check('salad' not in names, f"and none nobody owns a dish for, got {names}")
    by_name = {d['name']: d for d in storage.get_dishes()}
    check(by_name['roast chicken']['category_ids'] == [category_id('protein')],
          "the entree became a protein")
    check(by_name['tacos']['type'] == 'meal', "a whole meal stays a whole meal")
    check(by_name['broccoli']['type'] == 'dish', "and everything else is just a dish")

    # One-shot: a family that deletes a category must not find it resurrected.
    storage.delete_dish_category(category_id('vegetables'))
    storage.ensure_dish_categories()
    check('vegetables' not in [c['name'] for c in storage.get_dish_categories()],
          "seeding never runs twice")


def scenario_setting_what_a_dish_is_by_hand_and_by_voice():
    """Every one of these existed in the model and on no screen — the only way
    to fix a misfiled dish was to ask the agent and hope it re-extracted
    differently. Both stacks, because the chat widget uses the other one."""
    reset_db()
    beans = _dish('black beans', type='side', side_type='starch')
    from services import agent_tools, agent_tools_v2
    check('set_dish_categories' in {t['name'] for t in agent_tools_v2.get_available_tools()},
          "v2 offers the tool")
    check('set_dish_categories' in agent_tools.TOOL_SCHEMAS
          and 'set_dish_categories' in agent_tools.TOOL_HANDLERS, "and so does v1")

    res = agent_tools.execute_tool('set_dish_categories',
                                   {'dish_name': 'black beans',
                                    'categories': 'protein, starches/carbs'})
    got = storage.get_dish(beans['id'])
    check(got['category_ids'] == [category_id('protein'), category_id('starches/carbs')],
          f"the v1 bridge writes through, got {res}")

    agent_tools_v2.set_dish_categories('black beans', whole_meal=True, serves=8)
    got = storage.get_dish(beans['id'])
    check(got['type'] == 'meal' and got['serves'] == 8,
          f"whole-meal and serves are settable too, got {got['type']}/{got['serves']}")

    # A category nobody created is reported, never invented.
    bad = agent_tools_v2.set_dish_categories('black beans', categories='amuse-bouche')
    check(bad['status'] == 'error' and 'protein' in bad['message'],
          f"unknown category names the ones they do have, got {bad}")
    check(len(storage.get_dish_categories()) == len(_TEST_CATEGORIES),
          "and nothing was created behind their back")


def scenario_a_renamed_category_propagates_nowhere():
    reset_db()
    veg = next(c for c in storage.get_dish_categories() if c['name'] == 'vegetables')
    d = _dish('broccoli', type='side', side_type='vegetable')
    veg['name'] = 'greens'
    storage.save_dish_category(veg)
    check(storage.get_dish(d['id'])['category_ids'] == [veg['id']],
          "the dish still points at the same category — ids are stable")
    check(any(c['name'] == 'greens' for c in storage.get_dish_categories()),
          "and the family's word for it is what shows")


def scenario_the_classifier_is_given_the_familys_words():
    reset_db()
    block = meals.category_prompt_block()
    check('protein' in block and 'starches/carbs' in block,
          f"their categories are in the prompt, got {block!r}")
    check('entree' not in block, "and ours are not")
    check(meals.resolve_category_names(['Protein', 'vegetable']) ==
          [category_id('protein'), category_id('vegetables')],
          "case and a stray plural still resolve")
    check(meals.resolve_category_names(['appetiser']) == [],
          "a category they never created is discarded, not invented")


def scenario_nights_stay_on_the_record():
    """Plates used to be pruned to TODAY on every write, so the family's own
    history was destroyed daily. It is the only copy that will ever exist."""
    import datetime as _dt
    from models.schemas import Plate, PlateItem
    reset_db()
    today = _dt.date.today()
    iso = lambda n: (today + _dt.timedelta(days=n)).isoformat()

    chili = _dish('chili', type='meal')
    tacos = _dish('tacos', type='meal')
    storage.save_plate(Plate(date=iso(-3), edited=True,
                             items=[PlateItem(dish_id=chili['id'])]).model_dump())
    storage.save_plate(Plate(date=iso(-1), edited=True,
                             items=[PlateItem(dish_id=tacos['id'])]).model_dump())
    # Any write triggers the prune; the past must survive it.
    meals._persist_plate(iso(0), [chili])
    check(storage.get_plate(iso(-3)), "a night from three days ago still exists")
    check(storage.get_plate(iso(-1)), "and so does last night")

    hist = meals.served_history(21)
    check([h['date'] for h in hist] == [iso(-1), iso(-3)],
          f"history is newest-first and excludes today, got {[h['date'] for h in hist]}")
    check(hist[0]['headline'] == 'tacos', "headline names the dish")

    # A refusal record carries no items and is not a dinner.
    storage.save_plate(Plate(date=iso(-2), edited=False,
                             rejected=[chili['id']], items=[]).model_dump())
    check(len(meals.served_history(21)) == 2, "a refusal record is not history")

    # Beyond the retention window it does go.
    storage.save_plate(Plate(date=iso(-(meals.PLATE_RETENTION_DAYS + 5)), edited=True,
                             items=[PlateItem(dish_id=chili['id'])]).model_dump())
    meals._persist_plate(iso(0), [chili])
    check(not storage.get_plate(iso(-(meals.PLATE_RETENTION_DAYS + 5))),
          "past the retention window a night is pruned")


def scenario_arrange_week_is_one_write_for_both_gestures():
    import datetime as _dt
    from models.schemas import Plate, PlateItem
    reset_db()
    today = _dt.date.today()
    iso = lambda n: (today + _dt.timedelta(days=n)).isoformat()
    chili = _dish('chili', type='meal')
    tacos = _dish('tacos', type='meal')

    # A swap (the drag) — both nights written in one call.
    res = meals.arrange_week([{'date': iso(1), 'dish_ids': [tacos['id']]},
                              {'date': iso(2), 'dish_ids': [chili['id']]}])
    check(res['written'] == [iso(1), iso(2)], f"both nights written, got {res}")
    check([i['dish_id'] for i in storage.get_plate(iso(1))['items']] == [tacos['id']],
          "the dishes moved to the new date")
    check(storage.get_plate(iso(1))['edited'],
          "an arranged night is pinned — the family stated an intent about it")

    # A locked night refuses, by name, rather than moving quietly.
    storage.save_plate(Plate(date=iso(3), edited=True, locked=True,
                             items=[PlateItem(dish_id=tacos['id'])]).model_dump())
    res = meals.arrange_week([{'date': iso(3), 'dish_ids': [chili['id']]}])
    check(res['written'] == [] and res['refused'] == [{'date': iso(3), 'reason': 'locked'}],
          f"locked night refused by name, got {res}")
    check([i['dish_id'] for i in storage.get_plate(iso(3))['items']] == [tacos['id']],
          "and it is genuinely untouched")

    # The record of what was eaten is not editable by a drag.
    res = meals.arrange_week([{'date': iso(-1), 'dish_ids': [chili['id']]}])
    check(res['refused'] == [{'date': iso(-1), 'reason': 'past'}],
          f"a past night is refused, got {res}")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} meal-plan scenarios passed")
