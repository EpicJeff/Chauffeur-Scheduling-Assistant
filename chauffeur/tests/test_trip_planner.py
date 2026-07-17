"""Tests for trip plan generation logic (POI top-up loop).

Regression for: asking the LLM for ~40 POIs in one shot returned as few as 9
(complete, valid JSON — the model self-limits on long lists). generate_trip_plan
now tops up with small follow-up calls until the num_pois target is met.

Run from chauffeur/:  python tests/test_trip_planner.py
"""
from harness import mk_trip, check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import llm, trip_planner
from services.trip_planner import generate_trip_plan

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

    def __init__(self, batches):
        self.batches = batches
        self.prompts = []

    def __call__(self, provider, url, api_key, model, system_prompt, user_prompt,
                 temperature=0.1, tools=None):
        self.prompts.append(user_prompt)
        i = len(self.prompts) - 1
        batch = self.batches[min(i, len(self.batches) - 1)]
        resp = {"pois": list(batch), "accommodations": [], "flights": []}
        if i == 0:
            resp["accommodations"] = [{
                "name": "Paris Hotel", "location": "Paris",
                "check_in_date": "2026-09-07", "check_out_date": "2026-09-17"}]
        return resp


def run_plan(batches, prompt="plan a great 10 day trip to France"):
    fake = FakeLLM(batches)
    original = llm._call_llm_json
    llm._call_llm_json = fake
    try:
        trip = mk_trip(days=10)
        warning, pois, accs, flights = generate_trip_plan(trip, prompt, duration_nights=10)
        return fake, pois, accs
    finally:
        llm._call_llm_json = original


def scenario_healthy_single_shot_costs_one_request():
    """The historical healthy case (~27-30 POIs for 10 nights) must cost exactly
    ONE request — the floor is 28 (70% of 40), so 28+ never triggers a top-up."""
    fake, pois, _ = run_plan([poi_batch(0, 28)])
    check(len(fake.prompts) == 1, f"28 POIs is healthy, got {len(fake.prompts)} calls")
    check(len(pois) == 28, f"expected 28 POIs, got {len(pois)}")
    check("at least 28" in fake.prompts[0], "prompt states the POI floor explicitly")


def scenario_topup_only_on_collapse():
    """A collapsed first call (9 POIs) tops up until the floor is met, max 2 rounds."""
    fake, pois, accs = run_plan([poi_batch(0, 9), poi_batch(100, 12), poi_batch(200, 12)])
    check(len(fake.prompts) == 3, f"expected 1 initial + 2 top-up calls, got {len(fake.prompts)}")
    check(len(pois) == 33, f"expected 33 POIs (9+12+12, floor 28 met), got {len(pois)}")
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


SCENARIOS = [
    scenario_healthy_single_shot_costs_one_request,
    scenario_topup_only_on_collapse,
    scenario_topup_dedups_and_stops_when_dry,
    scenario_explicit_count_skips_topup,
    scenario_topup_failure_keeps_partial,
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
