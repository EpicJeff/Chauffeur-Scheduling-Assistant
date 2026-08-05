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


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} meal-plan scenarios passed")
