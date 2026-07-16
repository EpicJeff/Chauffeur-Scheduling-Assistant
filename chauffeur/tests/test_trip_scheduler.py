"""Scenario tests for services/trip_scheduler.py (design doc §12.3). Run: python tests/test_trip_scheduler.py"""
import datetime

from harness import mk_trip, mk_poi, mk_acc, local, check, MONDAY, ET
from models.schemas import TripRule
from services import trip_scheduler
from services.trip_scheduler import solve_assignment, schedule_pois_bulk

# Orlando-ish coordinates
MK = (28.4177, -81.5812)
EPCOT = (28.3747, -81.5494)
NEAR_MK = (28.4110, -81.5870)          # Grand Floridian-ish, ~2 km from MK
DOWNTOWN = (28.5383, -81.3792)         # ~20 km away
# Paris
EIFFEL = (48.8584, 2.2945)
NEAR_EIFFEL = (48.8577, 2.3060)        # ~1 km
MONTMARTRE = (48.8867, 2.3431)         # ~5 km


def all_ids(pois):
    return [p.id for p in pois]


def scenario_disney_containers():
    mk = mk_poi("Magic Kingdom", *MK, is_background=True, days_claimed=2, priority="must")
    epcot = mk_poi("Epcot", *EPCOT, is_background=True, days_claimed=1, priority="must")
    dine_mk = mk_poi("Cinderella's Royal Table", 28.4187, -81.5790, category="food",
                     meal_type="dinner", parent_container=mk.id, duration_mins=90)
    dine_ep = mk_poi("Space 220", 28.3735, -81.5468, category="food",
                     meal_type="lunch", parent_container=epcot.id, duration_mins=75)
    offsite = mk_poi("Victoria & Albert's", *NEAR_MK, category="food",
                     meal_type="dinner", dining_style="fine", duration_mins=120)
    museum = mk_poi("Downtown Museum", *DOWNTOWN, category="sightseeing", duration_mins=120)

    trip = mk_trip(days=6)
    trip.pois = [mk, epcot, dine_mk, dine_ep, offsite, museum]
    res = solve_assignment(trip, all_ids(trip.pois))

    check(res.error is None, f"solve error: {res.error}")
    check(len(res.claims.get(mk.id, [])) == 2, f"MK should claim 2 days, got {res.claims.get(mk.id)}")
    check(len(res.claims.get(epcot.id, [])) == 1, f"Epcot should claim 1 day, got {res.claims.get(epcot.id)}")
    check(not set(res.claims[mk.id]) & set(res.claims[epcot.id]), "MK and Epcot claimed the same day")
    check(res.assigned[dine_mk.id][0] in res.claims[mk.id],
          f"MK child dining on day {res.assigned[dine_mk.id][0]}, MK days {res.claims[mk.id]}")
    check(res.assigned[dine_mk.id][1] == 'dinner', "character dinner should sit in the dinner block")
    check(res.assigned[dine_ep.id][0] in res.claims[epcot.id], "Epcot child not on Epcot day")
    check(res.assigned[dine_ep.id][1] == 'lunch', "Space 220 should sit in the lunch block")
    check(offsite.id in res.assigned and res.assigned[offsite.id][1] == 'dinner',
          "fine dining should schedule into a dinner block")
    park_days = set(res.claims[mk.id]) | set(res.claims[epcot.id])
    check(res.assigned[museum.id][0] not in park_days,
          f"cross-town museum should avoid park days (got day {res.assigned[museum.id][0]}, parks {park_days})")


def scenario_valid_day_claims():
    # Mon-start 7-day trip; 3 days claimed, valid Mon/Wed/Fri → claims land exactly there
    bg = mk_poi("Conference Park", *MK, is_background=True, days_claimed=3,
                valid_days_of_week=[0, 2, 4], priority="must")
    trip = mk_trip(days=7)
    trip.pois = [bg]
    res = solve_assignment(trip, [bg.id])
    check(res.error is None, f"solve error: {res.error}")
    days = res.claims.get(bg.id, [])
    weekdays = sorted((MONDAY + datetime.timedelta(days=d)).weekday() for d in days)
    check(weekdays == [0, 2, 4], f"claims should be Mon/Wed/Fri, got weekdays {weekdays}")

    # same POI without valid days → contiguous run
    bg2 = mk_poi("Free Park", *MK, is_background=True, days_claimed=3, priority="must")
    trip2 = mk_trip(days=7)
    trip2.pois = [bg2]
    res2 = solve_assignment(trip2, [bg2.id])
    days2 = res2.claims.get(bg2.id, [])
    check(len(days2) == 3 and days2[2] - days2[0] == 2, f"unconstrained claims should be contiguous, got {days2}")

    # infeasible: needs 3 valid days but trip only has 2 → clean failure with reason
    bg3 = mk_poi("Weekend Park", *MK, is_background=True, days_claimed=3,
                 valid_days_of_week=[5, 6], priority="must")
    trip3 = mk_trip(days=7)
    trip3.pois = [bg3]
    res3 = solve_assignment(trip3, [bg3.id])
    check(bg3.id in res3.failures and "day" in res3.failures[bg3.id],
          f"expected a day-shortage reason, got {res3.failures}")


def scenario_eiffel_anchor():
    hotel = mk_acc("Hotel Montmartre", *MONTMARTRE, MONDAY, MONDAY + datetime.timedelta(days=3))
    eiffel = mk_poi("Explore Eiffel Tower", *EIFFEL, is_background=True, days_claimed=1, priority="must")
    jules = mk_poi("Jules Verne", 48.8583, 2.2944, category="food", meal_type="dinner",
                   parent_container=eiffel.id, duration_mins=120)
    troc = mk_poi("Trocadero Gardens", 48.8616, 2.2893, category="sightseeing",
                  parent_container=eiffel.id, duration_mins=60)
    cafe = mk_poi("Rue Cler Cafe", *NEAR_EIFFEL, category="food", meal_type="lunch", duration_mins=60)
    sacre = mk_poi("Sacre-Coeur", 48.8867, 2.3431, category="sightseeing", duration_mins=90)
    moulin = mk_poi("Moulin Rouge district walk", 48.8841, 2.3322, category="sightseeing", duration_mins=90)

    trip = mk_trip(days=3, location="Paris", accommodations=[hotel])
    trip.pois = [eiffel, jules, troc, cafe, sacre, moulin]
    res = solve_assignment(trip, all_ids(trip.pois))
    check(res.error is None, f"solve error: {res.error}")
    anchor_day = res.claims[eiffel.id][0]
    check(res.assigned[jules.id][0] == anchor_day, "Jules Verne (child) must land on the Eiffel day")
    check(res.assigned[troc.id][0] == anchor_day, "Trocadero (child) must land on the Eiffel day")
    check(res.assigned[cafe.id][0] == anchor_day,
          f"nearby cafe should cluster on the anchor day (got {res.assigned[cafe.id][0]}, anchor {anchor_day})")
    check(res.assigned[sacre.id][0] != anchor_day, "Montmartre POI should stay off the Eiffel day")
    check(res.assigned[moulin.id][0] != anchor_day, "Montmartre POI should stay off the Eiffel day")


def scenario_meal_fit():
    fine = mk_poi("Le Grand", *NEAR_EIFFEL, category="food", dining_style="fine", duration_mins=120)
    cas1 = mk_poi("Bistro One", *NEAR_EIFFEL, category="food", duration_mins=75)
    cas2 = mk_poi("Bistro Two", *NEAR_EIFFEL, category="food", duration_mins=75)
    brk = mk_poi("Morning Bakery", *NEAR_EIFFEL, category="food", meal_type="breakfast", duration_mins=45)
    des = mk_poi("Gelato Bar", *NEAR_EIFFEL, category="food", meal_type="dessert", duration_mins=30)

    trip = mk_trip(days=3)
    trip.pois = [fine, cas1, cas2, brk, des]
    res = solve_assignment(trip, all_ids(trip.pois))
    check(res.error is None, f"solve error: {res.error}")
    check(res.assigned[fine.id][1] == 'dinner', f"fine dining must be dinner, got {res.assigned[fine.id]}")
    check(res.assigned[brk.id][1] == 'breakfast', f"bakery must be breakfast, got {res.assigned[brk.id]}")
    check(res.assigned[des.id][1] in ('morning', 'afternoon', 'evening'),
          f"dessert goes in activity blocks, got {res.assigned[des.id]}")
    # no meal block double-booked
    seen = {}
    for pid in (fine.id, cas1.id, cas2.id, brk.id):
        d, b = res.assigned[pid]
        check((d, b) not in seen, f"meal block ({d},{b}) double-booked")
        seen[(d, b)] = pid


def scenario_two_lobes():
    lobe_a = [mk_poi(f"Eiffel Spot {i}", EIFFEL[0] + i * 0.001, EIFFEL[1] + i * 0.001,
                     category="sightseeing", duration_mins=90) for i in range(4)]
    lobe_b = [mk_poi(f"Montmartre Spot {i}", MONTMARTRE[0] + i * 0.001, MONTMARTRE[1] + i * 0.001,
                     category="sightseeing", duration_mins=90) for i in range(4)]
    trip = mk_trip(days=2)
    trip.pois = lobe_a + lobe_b
    res = solve_assignment(trip, all_ids(trip.pois))
    check(res.error is None, f"solve error: {res.error}")
    days_a = {res.assigned[p.id][0] for p in lobe_a}
    days_b = {res.assigned[p.id][0] for p in lobe_b}
    check(len(days_a) == 1 and len(days_b) == 1 and days_a != days_b,
          f"lobes should occupy one coherent day each, got A={days_a} B={days_b}")


def scenario_balance():
    pois = [mk_poi(f"Spot {i}", *NEAR_EIFFEL, category="sightseeing", duration_mins=90) for i in range(12)]
    trip = mk_trip(days=4)
    trip.pois = pois
    res = solve_assignment(trip, all_ids(trip.pois))
    check(res.error is None, f"solve error: {res.error}")
    per_day = {}
    for p in pois:
        check(p.id in res.assigned, f"{p.name} unscheduled")
        per_day.setdefault(res.assigned[p.id][0], 0)
        per_day[res.assigned[p.id][0]] += 1
    check(sorted(per_day.values()) == [3, 3, 3, 3], f"12 POIs over 4 days should be 3/day, got {per_day}")


def scenario_rules():
    # template_override: no mornings before 10, breakfast disabled
    no_morning = TripRule(description="Not morning people", rule_type="template_override",
                          blocks=["breakfast"], template_start="10:00", hardness="hard")
    brk = mk_poi("Breakfast Diner", *NEAR_EIFFEL, category="food", meal_type="breakfast", duration_mins=45)
    act = mk_poi("Gallery", *NEAR_EIFFEL, category="sightseeing", duration_mins=90)
    trip = mk_trip(days=2, rules=[no_morning])
    trip.pois = [brk, act]
    res = solve_assignment(trip, all_ids(trip.pois))
    check(brk.id in res.failures, "breakfast POI must fail when breakfast block is disabled")
    check(act.id in res.assigned, "activity should still schedule")

    # keep_clear day 2 (hard)
    clear = TripRule(description="Keep day 2 clear", rule_type="keep_clear", trip_days=[2], hardness="hard")
    pois = [mk_poi(f"P{i}", *NEAR_EIFFEL, category="sightseeing", duration_mins=90) for i in range(6)]
    trip2 = mk_trip(days=3, rules=[clear])
    trip2.pois = pois
    res2 = solve_assignment(trip2, all_ids(pois))
    for p in pois:
        if p.id in res2.assigned:
            check(res2.assigned[p.id][0] != 1, f"{p.name} landed on cleared day 2")

    # budget_cap hard on food
    d1 = mk_poi("Cheap Eats", *NEAR_EIFFEL, category="food", estimated_price_usd=50, duration_mins=60)
    d2 = mk_poi("Mid Eats", *NEAR_EIFFEL, category="food", estimated_price_usd=100, duration_mins=60)
    d3 = mk_poi("Splurge", *NEAR_EIFFEL, category="food", estimated_price_usd=200, duration_mins=60)
    cap = TripRule(description="Dining under $200 total", rule_type="budget_cap",
                   categories=["food"], max_usd=200, hardness="hard")
    trip3 = mk_trip(days=3, rules=[cap])
    trip3.pois = [d1, d2, d3]
    res3 = solve_assignment(trip3, all_ids(trip3.pois))
    total = sum((p.estimated_price_usd or 0) for p in trip3.pois if p.id in res3.assigned)
    check(total <= 200, f"budget cap violated: ${total}")

    # spacing between parks (hard)
    p1 = mk_poi("Park A", *MK, is_background=True, days_claimed=1, priority="must", category="theme_park")
    p2 = mk_poi("Park B", *EPCOT, is_background=True, days_claimed=1, priority="must", category="theme_park")
    gap = TripRule(description="No back-to-back parks", rule_type="spacing",
                   categories=["theme_park"], min_gap_days=1, hardness="hard")
    trip4 = mk_trip(days=5, rules=[gap])
    trip4.pois = [p1, p2]
    res4 = solve_assignment(trip4, all_ids(trip4.pois))
    da, db = res4.claims[p1.id][0], res4.claims[p2.id][0]
    check(abs(da - db) > 1, f"spacing violated: parks on days {da} and {db}")


def scenario_locked_incremental():
    pois = [mk_poi(f"Spot {i}", EIFFEL[0] + i * 0.002, EIFFEL[1], category="sightseeing", duration_mins=90)
            for i in range(6)]
    trip = mk_trip(days=3)
    trip.pois = list(pois)
    results = list(schedule_pois_bulk(trip, all_ids(pois)))
    check(all(r.get("success") for r in results if not r.get("type")), f"initial bulk failed: {results}")
    before = {p.id: local(p.scheduled_start).date() for p in pois}

    extra = [mk_poi("Late Add 1", *NEAR_EIFFEL, category="food", meal_type="dinner", duration_mins=90),
             mk_poi("Late Add 2", *NEAR_EIFFEL, category="sightseeing", duration_mins=60)]
    trip.pois.extend(extra)
    results2 = list(schedule_pois_bulk(trip, all_ids(extra)))
    check(all(r.get("success") for r in results2 if not r.get("type")), f"incremental bulk failed: {results2}")
    for p in pois:
        check(local(p.scheduled_start).date() == before[p.id],
              f"{p.name} moved days during incremental scheduling")
    for p in extra:
        check(p.is_scheduled and p.scheduled_start, f"{p.name} not scheduled")


def scenario_end_to_end_timing():
    fine = mk_poi("Le Grand", *NEAR_EIFFEL, category="food", dining_style="fine", duration_mins=120)
    act = mk_poi("Louvre", 48.8606, 2.3376, category="sightseeing", duration_mins=180)
    trip = mk_trip(days=2)
    trip.pois = [fine, act]
    results = list(schedule_pois_bulk(trip, all_ids(trip.pois)))
    check(all(r.get("success") for r in results if not r.get("type")), f"bulk failed: {results}")
    fine_local = local(fine.scheduled_start)
    check(datetime.time(17, 30) <= fine_local.time() <= datetime.time(20, 30),
          f"fine dining should start in the dinner window, got {fine_local.time()}")
    act_local = local(act.scheduled_start)
    check(act_local.time() >= datetime.time(8, 0), f"activity too early: {act_local.time()}")
    check(fine.event_id and fine.event_id.startswith("draft_poi_"), "draft event id missing")


def scenario_multiday_bg_day_spans():
    """Regression: a days_claimed=3 anchor must yield one day-view span per claimed date."""
    from services.trip_scheduler import claimed_day_spans
    bg = mk_poi("Magic Kingdom", *MK, is_background=True, days_claimed=3, priority="must")
    child = mk_poi("Character Dining", 28.4187, -81.5790, category="food", meal_type="dinner",
                   parent_container=bg.id, duration_mins=90)
    trip = mk_trip(days=5)
    trip.pois = [bg, child]
    results = list(schedule_pois_bulk(trip, all_ids(trip.pois)))
    check(all(r.get("success") for r in results if not r.get("type")), f"bulk failed: {results}")
    check(len(bg.claimed_dates) == 3, f"expected 3 claimed_dates, got {bg.claimed_dates}")

    spans = claimed_day_spans(bg.model_dump(), trip.timeZone)
    check(spans is not None and len(spans) == 3, f"expected 3 day spans, got {spans}")
    span_dates = {local(s).date() for (_, _, s, _) in spans}
    claimed = {datetime.datetime.strptime(d, "%Y-%m-%d").date() for d in bg.claimed_dates}
    check(span_dates == claimed, f"span dates {span_dates} != claimed {claimed}")
    # single-day anchors and regular POIs don't expand
    check(claimed_day_spans(child.model_dump(), trip.timeZone) is None, "child must not expand")


SCENARIOS = [
    scenario_multiday_bg_day_spans,
    scenario_disney_containers,
    scenario_valid_day_claims,
    scenario_eiffel_anchor,
    scenario_meal_fit,
    scenario_two_lobes,
    scenario_balance,
    scenario_rules,
    scenario_locked_incremental,
    scenario_end_to_end_timing,
]

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
