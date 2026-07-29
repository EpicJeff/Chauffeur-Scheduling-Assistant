"""Unit tests for the trip data ingest gate (services/trip_validation.py).

The gate is shared infrastructure: plan generation and the agent tools both
depend on these primitives, so they get direct coverage here in addition to
the integration scenarios in test_trip_planner.py / test_agent_trip_tools.py.

Run from chauffeur/:  python tests/test_trip_validation.py
"""
from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services.trip_validation import (anchor_fields, find_stay_overlap,
                                      reconcile_coords, reground_area_anchors)


def base_enrichment(**over):
    e = {"location": "Rue de Bourgogne, Paris", "mapbox_id": "mb", "lat": 48.85, "lng": 2.35,
         "wikidata_id": "Q1", "opening_hours": "9-18", "website": "w", "phone_number": "p",
         "cuisine": "x", "internet_access": "yes", "image_url": "img", "link": "lnk"}
    e.update(over)
    return e


def scenario_reconcile_coords():
    # far disagreement -> the LLM's region wins and identity fields drop
    e = base_enrichment()
    reconcile_coords(e, {"name": "Burgundy Wine Trail", "search_query": "Burgundy wine route",
                         "approx_lat": 47.02, "approx_lng": 4.84})
    check(abs(e["lat"] - 47.02) < 1e-9 and e["opening_hours"] is None and e["mapbox_id"] is None,
          "far geocode vetoed, identity dropped")
    check(e["location"] == "Burgundy wine route", "location falls back to the query")

    # agreement -> the geocode is kept (more precise than the LLM estimate)
    e = base_enrichment()
    reconcile_coords(e, {"name": "Louvre", "approx_lat": 48.86, "approx_lng": 2.34})
    check(e["lat"] == 48.85 and e["opening_hours"] == "9-18", "agreeing geocode kept")

    # no approx coords -> nothing to compare, untouched
    e = base_enrichment()
    reconcile_coords(e, {"name": "X"})
    check(e["lat"] == 48.85 and e["mapbox_id"] == "mb", "no approx -> untouched")

    # geocode found nothing -> rough approx beats nothing, no fields dropped
    e = base_enrichment(lat=None, lng=None)
    reconcile_coords(e, {"name": "X", "approx_lat": 10.0, "approx_lng": 20.0})
    check(e["lat"] == 10.0 and e["mapbox_id"] == "mb",
          "approx fills missing coords without dropping fields")

    # null-island and out-of-range approx values are ignored
    e = base_enrichment()
    reconcile_coords(e, {"name": "X", "approx_lat": 0.0, "approx_lng": 0.0})
    check(e["lat"] == 48.85, "null-island approx ignored")
    e = base_enrichment()
    reconcile_coords(e, {"name": "X", "approx_lat": 123.0, "approx_lng": 4.0})
    check(e["lat"] == 48.85, "out-of-range approx ignored")


def scenario_anchor_fields():
    check(anchor_fields({"name": "a", "is_background": True, "duration_mins": 60}) == (False, 1, 1),
          "short single-day anchor demoted")
    check(anchor_fields({"name": "a", "is_background": True, "duration_mins": 600}) == (True, 1, 1),
          "long anchor kept")
    check(anchor_fields({"name": "a", "is_background": True, "duration_mins": 60,
                         "days_claimed": 2}) == (True, 2, 1),
          "multi-day anchor kept despite bogus duration")
    check(anchor_fields({"name": "a", "is_background": True}) == (True, 1, 1),
          "anchor with unknown duration kept")
    check(anchor_fields({"name": "a", "occurrences": 3}) == (False, 1, 3),
          "regular POI occurrences pass through")
    check(anchor_fields({"name": "a", "is_background": True, "occurrences": 3,
                         "duration_mins": 600}) == (True, 3, 1),
          "legacy occurrences-as-days habit becomes days_claimed")


def scenario_find_stay_overlap():
    stays = [{"id": "1", "name": "A", "check_in_date": "2030-01-01", "check_out_date": "2030-01-05"},
             {"id": "2", "name": "B", "check_in_date": "2030-01-05", "check_out_date": "2030-01-08"}]
    check(find_stay_overlap("2030-01-04", "2030-01-06", stays)["name"] == "A", "overlap found")
    check(find_stay_overlap("2030-01-08", "2030-01-10", stays) is None,
          "contiguous (checkout == next check-in) is not an overlap")
    check(find_stay_overlap("2030-01-04", "2030-01-06", stays, exclude_id="1")["name"] == "B",
          "exclude_id skips the stay being edited")
    check(find_stay_overlap(None, None, stays) is None, "undated range never conflicts")
    check(find_stay_overlap("2030-01-02", "2030-01-03",
                            [{"id": "3", "name": "U"}]) is None,
          "undated existing stays never conflict")

    class Acc:
        id = "9"
        name = "C"
        check_in_date = "2030-01-02"
        check_out_date = "2030-01-03"
    check(find_stay_overlap("2030-01-01", "2030-01-04", [Acc()]) is not None,
          "model-object stays supported")


def scenario_misplaced_accommodation_classifier():
    from services.trip_validation import is_misplaced_accommodation
    check(is_misplaced_accommodation({"name": "Grand Palace Hotel", "category": "other"}),
          "plain lodging name with no attraction signals is lodging")
    check(is_misplaced_accommodation({"name": "Grand Palace Hotel"}),
          "missing category does not protect")
    check(not is_misplaced_accommodation({"name": "Villa Ephrussi de Rothschild",
                                          "category": "sightseeing"}),
          "attraction category protects a lodging-flavored name")
    check(not is_misplaced_accommodation({"name": "Villa Borghese", "category": "other",
                                          "parent_container": "Rome Old Town"}),
          "parent link protects")
    check(not is_misplaced_accommodation({"name": "Old Faithful Inn Area", "category": "other",
                                          "is_background": True}),
          "anchor flag protects")
    check(not is_misplaced_accommodation({"name": "Eiffel Tower", "category": "other"}),
          "no lodging keyword -> never lodging")


def scenario_reground_area_anchors():
    # identity-less anchor moves to its children's centroid (dict mode: agent tools)
    anchor = {"id": "a1", "name": "Paris Classic Exploration", "is_background": True,
              "lat": 44.83, "lng": -0.57}
    kid1 = {"id": "k1", "parent_container": "a1", "lat": 48.8584, "lng": 2.2945}
    kid2 = {"id": "k2", "parent_container": "a1", "lat": 48.8738, "lng": 2.2950}
    moved = reground_area_anchors([anchor, kid1, kid2])
    check(moved == ["a1"], f"anchor should move, got {moved}")
    check(abs(anchor["lat"] - 48.8661) < 1e-4 and abs(anchor["lng"] - 2.29475) < 1e-4,
          f"anchor should sit on the children's centroid, got ({anchor['lat']}, {anchor['lng']})")

    # a confirmed place identity is ground truth — never moved
    venue = {"id": "a2", "name": "Magic Kingdom", "is_background": True,
             "mapbox_id": "mb", "lat": 28.4177, "lng": -81.5812}
    kid = {"id": "k3", "parent_container": "a2", "lat": 28.5, "lng": -81.3}
    check(reground_area_anchors([venue, kid]) == [] and venue["lat"] == 28.4177,
          "venue anchor keeps its own coords")

    # childless anchor untouched here (its regional guess still picks the leg;
    # the scheduler snaps it to the claimed day's accommodation post-claim)
    lone = {"id": "a3", "name": "Old Town Day", "is_background": True, "lat": 1.0, "lng": 2.0}
    check(reground_area_anchors([lone]) == [] and lone["lat"] == 1.0, "no children -> untouched")

    # a child without coords contributes nothing (and alone, changes nothing)
    a = {"id": "a4", "name": "Harbor Day", "is_background": True, "lat": 5.0, "lng": 6.0}
    k = {"id": "k4", "parent_container": "a4", "lat": None, "lng": None}
    check(reground_area_anchors([a, k]) == [] and a["lat"] == 5.0, "unlocated child ignored")


SCENARIOS = [
    scenario_reconcile_coords,
    scenario_anchor_fields,
    scenario_reground_area_anchors,
    scenario_find_stay_overlap,
    scenario_misplaced_accommodation_classifier,
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
