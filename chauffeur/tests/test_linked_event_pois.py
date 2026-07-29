"""Tests for the POI-centric linked-event model (main.py).

A Google Calendar event linked to a trip via a Schedule-page event config
(trip_id) must surface as a calendar-backed POI: created on link, idempotent,
and removed on unlink. Calendar-backed POIs are fixed anchors the solver won't
move, and their calendar events are never deletable by Chauffeur.

Run from chauffeur/:  python tests/test_linked_event_pois.py
"""
import os
import sys
import tempfile

os.environ.setdefault("CHAUFFEUR_DATA_DIR", tempfile.mkdtemp(prefix="chauffeur_linkedpoi_"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import storage, trip_planner  # noqa: E402
import main  # noqa: E402

# Stub the Mapbox/Wikidata/OSM enrichment so tests stay offline and we can assert
# the enriched fields flow onto a calendar-backed POI.
trip_planner.enrich_poi_data = lambda name, location, trip_location: {
    "location": "Maria & Enzo's Ristorante, Disney Springs",
    "mapbox_id": "mb.maria", "lat": 28.37, "lng": -81.52,
    "wikidata_id": "Q123", "opening_hours": "11:00-22:00",
    "website": "https://example.com", "phone_number": "+1-407-555-0100",
    "cuisine": "italian", "internet_access": "wlan",
    "image_url": "api/unsplash/background?query=Maria&wikidata_id=Q123",
    "link": "https://maps.google.com/?q=Maria",
}


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


TRIP_ID = "cal@group.calendar.google.com::trip123"
CAL = "cal@group.calendar.google.com"


class FakeEvents:
    def __init__(self, store):
        self.store = store

    def get(self, calendarId, eventId):
        key = f"{calendarId}::{eventId}"
        payload = self.store[key]
        return _Exec(payload)


class _Exec:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return self.payload


class FakeService:
    def __init__(self, store):
        self._events = FakeEvents(store)

    def events(self):
        return self._events


def mk_trip():
    # clear any event-config links from a prior scenario (shared store)
    with storage.db_lock:
        storage.event_configs_table.truncate()
    storage.set_trip_metadata(TRIP_ID, {
        "event_id": TRIP_ID, "is_draft": False, "title": "Disney",
        "pois": [], "accommodations": [], "flights": [], "activities": [],
    })


def link_event(raw_id):
    storage.set_event_config(raw_id, {"google_id": raw_id, "trip_id": TRIP_ID})


def unlink_event(raw_id):
    conf = storage.get_event_config(raw_id)
    conf["trip_id"] = None
    storage.set_event_config(raw_id, conf)


def scenario_link_creates_calendar_backed_poi():
    mk_trip()
    link_event("lunch1")
    svc = FakeService({
        f"{CAL}::lunch1": {
            "summary": "Cinderella table-check time",
            "location": "Magic Kingdom",
            "start": {"dateTime": "2026-08-14T11:10:00-04:00"},
            "end": {"dateTime": "2026-08-14T12:40:00-04:00"},
        }
    })
    meta = storage.get_trip_metadata(TRIP_ID)
    changed = main._sync_linked_events_to_pois(meta, TRIP_ID, svc)
    check(changed, "sync should report a change")
    pois = storage.get_trip_metadata(TRIP_ID)["pois"]
    check(len(pois) == 1, f"one calendar-backed POI created, got {len(pois)}")
    p = pois[0]
    check(p["is_external_event"] is True, "flagged external")
    check(p["source_event_id"] == f"{CAL}::lunch1", "source_event_id links to the event")
    check(p["event_id"] == f"{CAL}::lunch1", "event_id is the real cal id (calendar-backed)")
    check(p["is_scheduled"] and p["scheduled_start"], "is_scheduled at the event's time")
    check(p["category"] == "food", f"'table'/'reservation' title -> food, got {p['category']}")
    check(main._is_calendar_backed_poi(p), "recognized as calendar-backed anchor")
    # the event's OWN location is authoritative — enrichment must NOT overwrite it
    check(p["location"] == "Magic Kingdom",
          f"event location preserved, not overwritten by enrichment, got {p['location']!r}")
    # but enrichment (wikidata/OSM/image) extras DO flow onto the linked-event POI
    check(p["wikidata_id"] == "Q123", "wikidata id enriched")
    check(p["image_url"] and "wikidata_id=Q123" in p["image_url"], "image url enriched")
    check(p["website"] and p["opening_hours"] and p["cuisine"] == "italian", "OSM details enriched")
    check(p["lat"] == 28.37 and p["lng"] == -81.52, "coords enriched for the map pin")

    # idempotent: a second sync must not duplicate
    meta2 = storage.get_trip_metadata(TRIP_ID)
    main._sync_linked_events_to_pois(meta2, TRIP_ID, svc)
    check(len(storage.get_trip_metadata(TRIP_ID)["pois"]) == 1, "no duplicate on re-sync")


def scenario_unlink_removes_poi():
    mk_trip()
    link_event("dinner1")
    svc = FakeService({
        f"{CAL}::dinner1": {
            "summary": "Maria and Enzo",
            "location": "EPCOT",
            "start": {"dateTime": "2026-08-14T18:20:00-04:00"},
            "end": {"dateTime": "2026-08-14T20:00:00-04:00"},
        }
    })
    meta = storage.get_trip_metadata(TRIP_ID)
    main._sync_linked_events_to_pois(meta, TRIP_ID, svc)
    check(len(storage.get_trip_metadata(TRIP_ID)["pois"]) == 1, "POI created")

    # unlink on the Schedule page -> next sync removes the POI
    unlink_event("dinner1")
    meta = storage.get_trip_metadata(TRIP_ID)
    changed = main._sync_linked_events_to_pois(meta, TRIP_ID, svc)
    check(changed, "unlink should report a change")
    check(len(storage.get_trip_metadata(TRIP_ID)["pois"]) == 0, "POI removed on unlink")


def scenario_committed_poi_not_duplicated():
    """A committed POI already owns its cal event — sync must not create a second
    external POI for the same id even if a stray config points at it."""
    mk_trip()
    meta = storage.get_trip_metadata(TRIP_ID)
    meta["pois"] = [{
        "id": "poi_committed", "name": "Committed Ride", "location": "MK",
        "event_id": f"{CAL}::committed1", "is_scheduled": True,
        "scheduled_start": 1786000000.0, "is_external_event": False,
    }]
    storage.set_trip_metadata(TRIP_ID, meta)
    link_event("committed1")
    svc = FakeService({f"{CAL}::committed1": {"summary": "X", "start": {"dateTime": "2026-08-14T09:00:00-04:00"}, "end": {"dateTime": "2026-08-14T10:00:00-04:00"}}})
    meta = storage.get_trip_metadata(TRIP_ID)
    main._sync_linked_events_to_pois(meta, TRIP_ID, svc)
    pois = storage.get_trip_metadata(TRIP_ID)["pois"]
    check(len(pois) == 1, f"committed POI not duplicated, got {len(pois)}")
    check(not pois[0].get("is_external_event"), "still the committed POI, not an external clone")


def scenario_meal_inferred_from_time():
    """An opaque restaurant reservation ('Chef Mickey') with no food keyword and
    no enrichment cuisine is still recognized as a meal via its dinner-time start,
    so it reserves its meal block instead of being scheduled around as 'other'."""
    mk_trip()
    link_event("chefmickey")
    svc = FakeService({
        f"{CAL}::chefmickey": {
            "summary": "Chef Mickey", "location": "Contemporary Resort",
            "start": {"dateTime": "2026-08-13T17:25:00-04:00"},   # dinner window
            "end": {"dateTime": "2026-08-13T18:55:00-04:00"},
        }
    })
    meta = storage.get_trip_metadata(TRIP_ID)
    main._sync_linked_events_to_pois(meta, TRIP_ID, svc)
    p = next(x for x in storage.get_trip_metadata(TRIP_ID)["pois"] if x.get("is_external_event"))
    check(p["category"] == "food", f"opaque dinner name should infer food, got {p['category']}")
    check(p["meal_type"] == "dinner", f"meal_type should infer from time, got {p['meal_type']}")


def scenario_batch_link_creates_multiple():
    """The multiselect linker: /link_events sets every event config's trip_id and
    creates all calendar-backed POIs in one sync."""
    import services.calendar as cal
    mk_trip()
    store = {
        f"{CAL}::a": {"summary": "Lunch A", "location": "Magic Kingdom",
                      "start": {"dateTime": "2026-08-14T11:00:00-04:00"},
                      "end": {"dateTime": "2026-08-14T12:00:00-04:00"}},
        f"{CAL}::b": {"summary": "Dinner B", "location": "EPCOT",
                      "start": {"dateTime": "2026-08-14T18:00:00-04:00"},
                      "end": {"dateTime": "2026-08-14T19:30:00-04:00"}},
    }
    prev = cal.get_calendar_service
    cal.get_calendar_service = lambda: FakeService(store)
    try:
        res = main.link_events_api(TRIP_ID, {"source_event_ids": [f"{CAL}::a", f"{CAL}::b"]})
    finally:
        cal.get_calendar_service = prev
    check(res.get("linked") == 2, f"both events linked, got {res}")
    pois = storage.get_trip_metadata(TRIP_ID)["pois"]
    check(len(pois) == 2, f"two calendar-backed POIs created in one call, got {len(pois)}")
    check(all(p["is_external_event"] for p in pois), "both flagged external")
    check(storage.get_event_config("a")["trip_id"] == TRIP_ID, "config a linked")
    check(storage.get_event_config("b")["trip_id"] == TRIP_ID, "config b linked")


SCENARIOS = [
    scenario_link_creates_calendar_backed_poi,
    scenario_unlink_removes_poi,
    scenario_committed_poi_not_duplicated,
    scenario_meal_inferred_from_time,
    scenario_batch_link_creates_multiple,
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
