"""Tests for trip plan generation logic (POI counts, LLM-output repair guards).

Covers: the healthy path costs exactly one LLM request (top-ups fire only on a
genuine count collapse); short "anchors" are demoted to regular POIs; overlapping
accommodation date ranges from the LLM are repaired before they can poison the
scheduler's day->hotel map.

Run from chauffeur/:  python tests/test_trip_planner.py
"""
from harness import mk_trip, check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import llm, storage, trip_planner
from services.trip_planner import generate_trip_plan

# A configured origin, so the "no flights because no home location" user note
# doesn't fire in scenarios that aren't about flights. (The harness stubs
# get_settings, so patch the stub — update_settings writes would be invisible.)
storage.get_settings = lambda: {"calendar_ids": ["primary"],
                                "home_location": "123 Home St, Springfield"}

trip_planner.enrich_poi_data = lambda name, location_query, trip_location: {
    "location": location_query, "mapbox_id": None, "lat": 48.85, "lng": 2.35,
    "wikidata_id": None, "opening_hours": None, "website": None, "phone_number": None,
    "cuisine": None, "internet_access": None, "image_url": "", "link": "",
}


def poi_batch(start, n):
    return [{"name": f"POI {i}", "category": "sightseeing", "description": "d",
             "search_query": f"POI {i}", "duration_mins": 60}
            for i in range(start, start + n)]


class FakeLLM:
    """Returns scripted POI batches, one per call, recording prompts."""

    def __init__(self, batches, accs=None):
        self.batches = batches
        self.accs = accs if accs is not None else [{
            "name": "Paris Hotel", "location": "Paris",
            "check_in_date": "2026-09-07", "check_out_date": "2026-09-17"}]
        self.prompts = []

    def __call__(self, provider, url, api_key, model, system_prompt, user_prompt,
                 temperature=0.1, tools=None):
        self.prompts.append(user_prompt)
        i = len(self.prompts) - 1
        batch = self.batches[min(i, len(self.batches) - 1)]
        resp = {"pois": list(batch), "accommodations": [], "flights": []}
        if i == 0:
            resp["accommodations"] = list(self.accs)
        return resp


def run_plan(batches, prompt="plan a great 10 day trip to France", accs=None):
    fake = FakeLLM(batches, accs=accs)
    original = llm._call_llm_json
    llm._call_llm_json = fake
    try:
        trip = mk_trip(days=10)
        warning, pois, accs_out, flights = generate_trip_plan(trip, prompt, duration_nights=10)
        return fake, pois, accs_out
    finally:
        llm._call_llm_json = original


def scenario_healthy_single_shot_costs_one_request():
    """The healthy case (27-30 POIs for 10 nights) must cost exactly ONE request —
    the ask is 30 (3/night) with a floor of 27 (90%), so 27+ never triggers a top-up."""
    fake, pois, _ = run_plan([poi_batch(0, 27)])
    check(len(fake.prompts) == 1, f"27 POIs is healthy, got {len(fake.prompts)} calls")
    check(len(pois) == 27, f"expected 27 POIs, got {len(pois)}")
    check("at least 27" in fake.prompts[0], "prompt states the POI floor explicitly")
    check("aim for 30" in fake.prompts[0], "prompt states the POI target explicitly")


def scenario_topup_only_on_collapse():
    """A collapsed first call (9 POIs) tops up until the floor is met, max 2 rounds."""
    fake, pois, accs = run_plan([poi_batch(0, 9), poi_batch(100, 12), poi_batch(200, 12)])
    check(len(fake.prompts) == 3, f"expected 1 initial + 2 top-up calls, got {len(fake.prompts)}")
    check(len(pois) == 33, f"expected 33 POIs (9+12+12, floor 27 met), got {len(pois)}")
    check("CONTINUATION" not in fake.prompts[0], "first call is not a continuation")
    check(all("CONTINUATION" in p for p in fake.prompts[1:]), "top-ups marked as continuation")
    check("poi 0" in fake.prompts[1].lower(), "top-up lists already-suggested names")
    check(len(accs) == 1, "accommodations from the first call survive the top-up")


def scenario_topup_dedups_and_stops_when_dry():
    """A top-up returning only already-suggested names ends the loop without dupes."""
    fake, pois, _ = run_plan([poi_batch(0, 9), poi_batch(0, 9)])
    check(len(fake.prompts) == 2, f"dry top-up stops the loop, got {len(fake.prompts)} calls")
    check(len(pois) == 9, f"no duplicates merged, got {len(pois)}")
    names = [p.name for p in pois]
    check(len(names) == len(set(names)), "POI names unique")


def scenario_explicit_count_skips_topup():
    """'give me 5 restaurants' must not be topped up to 40."""
    fake, pois, _ = run_plan([poi_batch(0, 5)], prompt="give me 5 restaurants in Paris")
    check(len(fake.prompts) == 1, f"explicit count skips top-up, got {len(fake.prompts)} calls")
    check(len(pois) == 5, f"expected exactly the 5 requested, got {len(pois)}")


def scenario_topup_failure_keeps_partial():
    """A top-up call blowing up keeps what the first call produced."""
    fake = FakeLLM([poi_batch(0, 9)])
    original_call = fake.__call__

    def flaky(provider, url, api_key, model, system_prompt, user_prompt,
              temperature=0.1, tools=None):
        if len(fake.prompts) >= 1:
            fake.prompts.append(user_prompt)
            raise RuntimeError("Gemini API request failed: HTTP Error 503")
        return original_call(provider, url, api_key, model, system_prompt,
                             user_prompt, temperature, tools)

    original = llm._call_llm_json
    llm._call_llm_json = flaky
    try:
        trip = mk_trip(days=10)
        warning, pois, accs, flights = generate_trip_plan(
            trip, "plan a great 10 day trip", duration_nights=10)
    finally:
        llm._call_llm_json = original
    check(len(pois) == 9, f"partial result survives a failed top-up, got {len(pois)}")


def scenario_short_anchor_demoted():
    """A 60-min POI marked is_background is an LLM misclassification: as an anchor
    it would claim a whole day exclusively and hijack that day's distance base.
    Real anchors (long, multi-day, or unstated duration) keep their flag."""
    batch = [
        {"name": "Quick Museum", "category": "sightseeing", "description": "d",
         "search_query": "q", "duration_mins": 60, "is_background": True},
        {"name": "Magic Kingdom", "category": "activity", "description": "d",
         "search_query": "q", "duration_mins": 600, "is_background": True},
        {"name": "Disney Week", "category": "activity", "description": "d",
         "search_query": "q", "duration_mins": 60, "is_background": True, "days_claimed": 3},
        {"name": "Mystery Anchor", "category": "activity", "description": "d",
         "search_query": "q", "is_background": True},
    ]
    fake, pois, _ = run_plan([batch], prompt="give me 4 places in France")
    by_name = {p.name: p for p in pois}
    check(not by_name["Quick Museum"].is_background, "60-min 'anchor' demoted to regular POI")
    check(by_name["Magic Kingdom"].is_background, "long single-day anchor keeps its flag")
    check(by_name["Disney Week"].is_background and by_name["Disney Week"].days_claimed == 3,
          "multi-day anchor kept despite bogus duration")
    check(by_name["Mystery Anchor"].is_background, "anchor without a stated duration is kept")


def scenario_accommodation_overlaps_repaired():
    """5 accommodations for 4 legs (a whole-trip umbrella + per-leg stays) must be
    repaired to the 4 legs — overlapping ranges poison the scheduler's day->hotel map."""
    accs = [
        {"name": "Grand Umbrella Stay", "location": "Paris",
         "check_in_date": "2026-09-07", "check_out_date": "2026-09-17"},
        {"name": "Paris Left Bank", "location": "Paris",
         "check_in_date": "2026-09-07", "check_out_date": "2026-09-11"},
        {"name": "Beaune Winery Stay", "location": "Beaune",
         "check_in_date": "2026-09-11", "check_out_date": "2026-09-14"},
        {"name": "Nice Beach Stay", "location": "Nice",
         "check_in_date": "2026-09-14", "check_out_date": "2026-09-16"},
        {"name": "Paris Final Night", "location": "Paris",
         "check_in_date": "2026-09-16", "check_out_date": "2026-09-17"},
    ]
    fake, pois, out = run_plan([poi_batch(0, 27)], accs=accs)
    names = [a.name for a in out]
    check("Grand Umbrella Stay" not in names, "umbrella stay dropped")
    check(len(out) == 4, f"expected the 4 legs, got {len(out)}: {names}")
    ranges = sorted((a.check_in_date, a.check_out_date) for a in out)
    for i in range(len(ranges) - 1):
        check(ranges[i][1] <= ranges[i + 1][0], f"stays overlap: {ranges[i]} vs {ranges[i + 1]}")


def scenario_overlap_repair_edge_cases():
    """Clip-forward, duplicate ranges, zero-night, undated passthrough, existing stays."""
    from services.trip_validation import repair_accommodation_overlaps as _repair_accommodation_overlaps

    # partial overlap: the earlier stay is clipped to the later stay's check-in
    a = {"name": "A", "check_in_date": "2030-01-01", "check_out_date": "2030-01-05"}
    b = {"name": "B", "check_in_date": "2030-01-04", "check_out_date": "2030-01-08"}
    out = _repair_accommodation_overlaps([a, b])
    check(len(out) == 2 and out[0]["check_out_date"] == "2030-01-04",
          "partial overlap clipped forward (check-in wins)")

    # identical ranges: exactly one survives
    a = {"name": "A", "check_in_date": "2030-01-01", "check_out_date": "2030-01-05"}
    b = {"name": "B", "check_in_date": "2030-01-01", "check_out_date": "2030-01-05"}
    out = _repair_accommodation_overlaps([a, b])
    check(len(out) == 1, f"duplicate range collapses to one stay, got {len(out)}")

    # zero-night dropped; undated passes through untouched
    z = {"name": "Z", "check_in_date": "2030-01-02", "check_out_date": "2030-01-02"}
    u = {"name": "U"}
    out = _repair_accommodation_overlaps([z, u])
    check([s["name"] for s in out] == ["U"], "zero-night dropped, undated kept")

    # a suggestion overlapping an already-saved stay is dropped, not clipped
    class Acc:
        check_in_date = "2030-01-01"
        check_out_date = "2030-01-05"
    n = {"name": "N", "check_in_date": "2030-01-03", "check_out_date": "2030-01-07"}
    out = _repair_accommodation_overlaps([n], existing=[Acc()])
    check(out == [], "suggestion overlapping an existing stay dropped")


def scenario_uncovered_nights_detector():
    """Pure detector: every trip night [start, end) needs a stay; the repair
    layer never invents nights (per-leg counts are user intent)."""
    import datetime as _dt
    from services.trip_validation import uncovered_nights
    start, end = _dt.date(2030, 1, 5), _dt.date(2030, 1, 15)

    # the real 'Paris Anniversary' failure: chain starts day 2 -> night 1 uncovered
    stays = [{"name": "Paris", "check_in_date": "2030-01-06", "check_out_date": "2030-01-10"},
             {"name": "Bagnols", "check_in_date": "2030-01-10", "check_out_date": "2030-01-13"},
             {"name": "Riviera", "check_in_date": "2030-01-13", "check_out_date": "2030-01-14"},
             {"name": "Meurice", "check_in_date": "2030-01-14", "check_out_date": "2030-01-15"}]
    gaps = uncovered_nights(stays, None, start, end)
    check(gaps == [_dt.date(2030, 1, 5)], f"night 1 uncovered, got {gaps}")

    # full contiguous chain -> no gaps
    stays[0]["check_in_date"] = "2030-01-05"
    stays[0]["check_out_date"] = "2030-01-09"
    stays[1]["check_in_date"] = "2030-01-09"
    stays[1]["check_out_date"] = "2030-01-12"
    stays[2]["check_in_date"] = "2030-01-12"
    check(uncovered_nights(stays, None, start, end) == [], "full chain covers all nights")

    # existing stays count toward coverage
    class Acc:
        check_in_date = "2030-01-05"
        check_out_date = "2030-01-15"
    check(uncovered_nights([], [Acc()], start, end) == [], "existing stay covers the trip")


def scenario_stay_chain_translated_to_arrival_day():
    """Regression (real 'Paris Anniversary' trip, twice): the LLM starts the stay
    chain a day late ('overnight flight, arrive next morning'), and with the old
    end-pinned prompt that compressed the user's 2-night Riviera leg to 1. Leg
    lengths are user intent — the gate never resizes them; it translates the whole
    chain back to the arrival day (system truth) for free, and anything still
    uncovered becomes a visible warning. Never an extra LLM request."""
    def run(accs_in):
        class Fake:
            def __init__(self): self.prompts = []
            def __call__(self, provider, url, api_key, model, system_prompt, user_prompt,
                         temperature=0.1, tools=None):
                self.prompts.append(user_prompt)
                return {"pois": poi_batch(0, 30), "accommodations": [dict(s) for s in accs_in], "flights": []}
        fake = Fake()
        original = llm._call_llm_json
        llm._call_llm_json = fake
        try:
            trip = mk_trip(days=10)  # Sept 7 -> 17
            warning, pois, accs, flights = generate_trip_plan(
                trip, "4 days in Paris, 3 days wine country, 2 days riviera, 1 final day in Paris",
                duration_nights=10)
            return fake, warning, accs
        finally:
            llm._call_llm_json = original

    # chain shifted a day late but with CORRECT leg lengths (overhangs the end):
    # translated back — Riviera keeps its 2 nights, full coverage, no warning
    shifted_correct = [
        {"name": "Dame des Arts", "location": "Paris", "check_in_date": "2026-09-08", "check_out_date": "2026-09-12"},
        {"name": "Bagnols", "location": "Beaujolais", "check_in_date": "2026-09-12", "check_out_date": "2026-09-15"},
        {"name": "Cap-Eden-Roc", "location": "Antibes", "check_in_date": "2026-09-15", "check_out_date": "2026-09-17"},
        {"name": "Meurice", "location": "Paris", "check_in_date": "2026-09-17", "check_out_date": "2026-09-18"}]
    fake, warning, accs = run(shifted_correct)
    check(len(fake.prompts) == 1, f"translation must cost ZERO extra requests, got {len(fake.prompts)} calls")
    check(accs[0].check_in_date == "2026-09-07", "chain anchored to the arrival day")
    riviera = next(a for a in accs if a.name == "Cap-Eden-Roc")
    check(riviera.check_in_date == "2026-09-14" and riviera.check_out_date == "2026-09-16",
          f"Riviera keeps its 2 nights, got {riviera.check_in_date}->{riviera.check_out_date}")
    check(warning is None, f"full coverage -> no warning, got {warning}")

    # chain the LLM itself compressed (old end-pinned failure shape): translated
    # back, lengths untouched (intent unknown), remaining gap surfaced visibly
    compressed = [
        {"name": "Dame des Arts", "location": "Paris", "check_in_date": "2026-09-08", "check_out_date": "2026-09-12"},
        {"name": "Bagnols", "location": "Beaujolais", "check_in_date": "2026-09-12", "check_out_date": "2026-09-15"},
        {"name": "Cap-Eden-Roc", "location": "Antibes", "check_in_date": "2026-09-15", "check_out_date": "2026-09-16"},
        {"name": "Meurice", "location": "Paris", "check_in_date": "2026-09-16", "check_out_date": "2026-09-17"}]
    fake, warning, accs = run(compressed)
    check(len(fake.prompts) == 1, "no retry even when coverage stays short")
    check(accs[0].check_in_date == "2026-09-07", "compressed chain still anchored to arrival day")
    riviera = next(a for a in accs if a.name == "Cap-Eden-Roc")
    check(riviera.check_out_date == "2026-09-15" and riviera.check_in_date == "2026-09-14",
          "no leg is ever resized by the gate")
    check(warning and "9 of the trip's 10 nights" in warning,
          f"remaining deficit surfaced to the user, got {warning}")

    # dated existing stays suppress translation (a shift could collide with them)
    import datetime as _dt
    from services.trip_validation import shift_stays_to_trip_start
    class Acc:
        check_in_date = "2026-09-07"
        check_out_date = "2026-09-08"
    stays = [{"name": "X", "check_in_date": "2026-09-09", "check_out_date": "2026-09-12"}]
    check(shift_stays_to_trip_start(stays, [Acc()], _dt.date(2026, 9, 7)) == 0
          and stays[0]["check_in_date"] == "2026-09-09",
          "existing dated stay -> chain not shifted")


def scenario_llm_coords_veto_bad_geocode():
    """Regression: Mapbox matched 'Burgundy Wine Trail' to a same-named spot in
    PARIS, silently moving the whole wine leg for the scheduler. When the geocode
    lands > 60km from the LLM's approx_lat/approx_lng, the LLM's region wins and
    the matched place's identity fields are dropped. Agreeing geocodes are kept."""
    rich_enrich = lambda name, location_query, trip_location: {
        "location": "Rue de Bourgogne, Paris", "mapbox_id": "mb123", "lat": 48.85, "lng": 2.35,
        "wikidata_id": "Q1", "opening_hours": "9:00-18:00", "website": "http://x",
        "phone_number": "1", "cuisine": None, "internet_access": None,
        "image_url": "img", "link": "lnk"}
    prev = trip_planner.enrich_poi_data
    trip_planner.enrich_poi_data = rich_enrich
    try:
        batch = [
            {"name": "Burgundy Wine Trail", "category": "activity", "description": "d",
             "search_query": "Burgundy wine route", "duration_mins": 480,
             "is_background": True, "approx_lat": 47.02, "approx_lng": 4.84},
            {"name": "Louvre Museum", "category": "sightseeing", "description": "d",
             "search_query": "Louvre", "duration_mins": 240,
             "approx_lat": 48.86, "approx_lng": 2.34},
        ]
        fake, pois, _ = run_plan([batch], prompt="give me 2 places in France")
    finally:
        trip_planner.enrich_poi_data = prev
    by_name = {p.name: p for p in pois}
    wine = by_name["Burgundy Wine Trail"]
    check(abs(wine.lat - 47.02) < 0.01 and abs(wine.lng - 4.84) < 0.01,
          f"far geocode vetoed by LLM region, got ({wine.lat}, {wine.lng})")
    check(wine.opening_hours is None and wine.mapbox_id is None and wine.wikidata_id is None,
          "wrong place's identity fields dropped")
    louvre = by_name["Louvre Museum"]
    check(abs(louvre.lat - 48.85) < 0.01 and louvre.opening_hours == "9:00-18:00",
          "agreeing geocode kept — it is more precise than the LLM estimate")


def scenario_attraction_named_villa_stays_a_poi():
    """Regression: 'Villa Ephrussi de Rothschild' (a garden-estate attraction) was
    hijacked into accommodations by the hotel-keyword filter — deleting it from
    the itinerary and leaving an undated accommodation card. Only lodging with no
    attraction signals is moved now."""
    batch = [
        {"name": "Villa Ephrussi de Rothschild", "category": "sightseeing",
         "description": "gardens", "search_query": "q", "duration_mins": 120},
        {"name": "Grand Palace Hotel", "category": "other", "description": "stay here",
         "search_query": "q"},
    ]
    fake, pois, accs = run_plan([batch], prompt="give me 2 places in France")
    names = [p.name for p in pois]
    check("Villa Ephrussi de Rothschild" in names, f"attraction kept as a POI, got {names}")
    check("Grand Palace Hotel" not in names, "plain lodging moved out of the POI list")
    check(any(a.name == "Grand Palace Hotel" for a in accs),
          "moved lodging lands in accommodations")


def scenario_return_stay_to_same_hotel_kept():
    """Dedup vs existing stays is date-aware: re-suggesting a hotel the trip already
    has is legitimate for a NEW date range (return stay), a duplicate when the dates
    overlap the existing stay, and a duplicate when no dates are given."""
    from models.schemas import TripAccommodation
    suggested = [
        {"name": "Ritz Paris", "location": "Paris",
         "check_in_date": "2026-09-16", "check_out_date": "2026-09-17"},  # return stay: keep
        {"name": "Ritz Paris", "location": "Paris"},                      # undated dupe: drop
        {"name": "Ritz Paris", "location": "Paris",
         "check_in_date": "2026-09-08", "check_out_date": "2026-09-10"},  # overlaps existing: drop
    ]
    fake = FakeLLM([poi_batch(0, 27)], accs=suggested)
    original = llm._call_llm_json
    llm._call_llm_json = fake
    try:
        trip = mk_trip(days=10)
        trip.accommodations = [TripAccommodation(
            name="Ritz Paris", location="Paris",
            check_in_date="2026-09-07", check_out_date="2026-09-11")]
        warning, pois, out, flights = generate_trip_plan(
            trip, "plan a great 10 day trip to France", duration_nights=10)
    finally:
        llm._call_llm_json = original
    check(len(out) == 1, f"expected only the return stay to survive, got {len(out)}")
    check(out[0].check_in_date == "2026-09-16", "the non-overlapping return stay is kept")


def scenario_no_origin_flight_note():
    """An empty flights array is silent when an origin is configured (the LLM
    legitimately decided not to fly), but with NO home_location it surfaces an
    actionable note — silently missing flights read as a bug to the user."""
    # (origin configured + no flights -> silent is already proven by
    # scenario_stay_chain_translated_to_arrival_day's warning-is-None check)
    prev_settings = storage.get_settings
    storage.get_settings = lambda: {"calendar_ids": ["primary"]}
    try:
        fake = FakeLLM([poi_batch(0, 27)])
        original = llm._call_llm_json
        llm._call_llm_json = fake
        try:
            trip = mk_trip(days=10)
            warning, _, _, _ = generate_trip_plan(
                trip, "plan a great 10 day trip to France", duration_nights=10)
        finally:
            llm._call_llm_json = original
        check(warning and "Home Location" in warning,
              f"missing origin must produce an actionable note, got: {warning}")
    finally:
        storage.get_settings = prev_settings


def scenario_generate_trip_flights():
    """The dedicated flight generator: one LLM request, TripFlight objects out,
    origin context in the prompt, and the no-origin note when it has nothing."""
    from services.trip_planner import generate_trip_flights

    class FakeFlightLLM:
        def __init__(self, flights):
            self.flights = flights
            self.prompts = []

        def __call__(self, provider, url, api_key, model, system_prompt, user_prompt,
                     temperature=0.1, tools=None):
            self.prompts.append(user_prompt)
            return {"flights": list(self.flights)}

    fake = FakeFlightLLM([
        {"airline": "Delta", "origin": "JFK", "destination": "CDG",
         "departure_time": "2026-09-06T18:00:00", "arrival_time": "2026-09-07T07:30:00",
         "estimated_price_usd": 900.0},
        {"airline": "Delta", "origin": "CDG", "destination": "JFK",
         "departure_time": "2026-09-17T11:00:00", "arrival_time": "2026-09-17T14:00:00",
         "estimated_price_usd": 900.0},
    ])
    original = llm._call_llm_json
    llm._call_llm_json = fake
    try:
        warning, flights = generate_trip_flights(mk_trip(days=10), "add flights please")
    finally:
        llm._call_llm_json = original
    check(len(fake.prompts) == 1, f"flight generation costs exactly one request, got {len(fake.prompts)}")
    check("Home Location" in fake.prompts[0] and "123 Home St" in fake.prompts[0],
          "the configured origin is in the prompt")
    check(len(flights) == 2 and flights[0].origin == "JFK", f"TripFlight objects built: {flights}")
    check(all(f.id for f in flights), "generated flights get ids")
    check(warning is None, f"healthy generation -> no warning, got {warning}")

    # no origin anywhere -> empty result carries the actionable note
    prev_settings = storage.get_settings
    storage.get_settings = lambda: {"calendar_ids": ["primary"]}
    fake = FakeFlightLLM([])
    llm._call_llm_json = fake
    try:
        warning, flights = generate_trip_flights(mk_trip(days=10), "add flights please")
    finally:
        llm._call_llm_json = original
        storage.get_settings = prev_settings
    check(not flights and warning and "Home Location" in warning,
          f"no origin -> note, got {warning}")


SCENARIOS = [
    scenario_healthy_single_shot_costs_one_request,
    scenario_topup_only_on_collapse,
    scenario_topup_dedups_and_stops_when_dry,
    scenario_explicit_count_skips_topup,
    scenario_topup_failure_keeps_partial,
    scenario_short_anchor_demoted,
    scenario_accommodation_overlaps_repaired,
    scenario_overlap_repair_edge_cases,
    scenario_uncovered_nights_detector,
    scenario_stay_chain_translated_to_arrival_day,
    scenario_return_stay_to_same_hotel_kept,
    scenario_llm_coords_veto_bad_geocode,
    scenario_attraction_named_villa_stays_a_poi,
    scenario_no_origin_flight_note,
    scenario_generate_trip_flights,
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
