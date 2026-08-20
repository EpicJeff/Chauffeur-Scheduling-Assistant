"""Tests for trip creation plumbing. Trip creation was broken for a month by
a route rename (POST /api/trips -> /api/trip) that never reached the client:
the POST hit the GET-only gallery route, 405'd, and the client navigated to
trip?event_id=undefined. And the trips snapshot write (set_cached_trips) was
killed by a missing `import time`. Both get pinned here.

Run from chauffeur/:  python tests/test_trip_create.py
"""
import os
import re

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR and mocks maps)

from services import storage, maps

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_template_posts_to_a_real_route():
    """The URL saveNewTrip POSTs must exist on the app WITH the POST method —
    a rename that only touches main.py fails here instead of in production."""
    import main
    src = open(os.path.join(HERE, 'templates', 'trips.html'), encoding='utf-8').read()
    m = re.search(r"fetch\(`\$\{apiBase\}(api/[a-z_/]+)`,\s*\{\s*method:\s*'POST'", src)
    check(m, "trips.html no longer has a recognizable create POST — update this test")
    posted = "/" + m.group(1)
    post_routes = {r.path for r in main.app.routes if 'POST' in (getattr(r, 'methods', None) or set())}
    check(posted in post_routes,
          f"trips.html posts to {posted}, which is not a POST route on the app")


def test_snapshot_write_roundtrips():
    """set_cached_trips crashed on `time` for want of an import — the home
    board's trips gallery read a stale snapshot forever."""
    rows = [{'id': 'cal::x', 'title': 'Beach Week', 'start': '2026-09-01', 'end': ''}]
    storage.set_cached_trips(rows)
    snap = storage.get_cached_trips()
    check(snap.get('trips') == rows, f"snapshot did not round-trip: {snap}")
    check(snap.get('at'), "snapshot carries its write timestamp")


def test_flexible_date_create_lands_a_draft():
    """The flexible-dates path (no start/end, day-of-week + nights) must end
    in stored draft metadata whose id the client can navigate to."""
    import main
    maps.get_home_location = lambda: None  # skip travel/flight lookups
    res = main.create_trip_api(main.CreateTripRequest(
        title="Lake Weekend", location="Lakeville",
        start_day_of_week=4, duration_nights=2))
    check(res.get('success') and res.get('event_id'), f"create failed: {res}")
    meta = storage.get_trip_metadata(res['event_id'])
    check(meta and meta.get('is_draft'), f"draft metadata missing: {meta}")
    check(meta.get('mock_start_date') and meta.get('mock_end_date'),
          "flexible draft carries mock dates for the solver/UI")
    check(meta.get('draft_duration_nights') == 2, "nights preserved")


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
