"""Single ingest gate for LLM/agent-produced trip data.

Everything the agent or plan-generation LLM produces is UNTRUSTED INPUT:
invented place names, fuzzy geocoder matches, overlapping stay dates,
misclassified anchors. Once persisted, the rest of the app treats trip data as
truth — the scheduler's geography fence trusts accommodation coordinates
outright — so bad data must be caught here, at the boundary, before storage.

Every path that persists trip POIs or accommodations must run through this
module: plan generation (services/trip_planner.py), agent tools
(services/agent_tools.py), and any future importer. The scheduler's hard
fences are the backstop, not the defense; the post-solve audit
(trip_scheduler.audit_solve) is the last-resort detector.

Entry points:
- vet_poi(enrichment, s)            -> (is_background, days_claimed, occurrences)
- vet_accommodation(enrichment, s)  -> None (mutates enrichment)
- repair_accommodation_overlaps(suggestions, existing) -> repaired list
- shift_stays_to_trip_start(suggestions, existing, trip_start) -> days shifted
- uncovered_nights(suggestions, existing, trip_start, trip_end) -> [date, ...]
- find_stay_overlap(check_in, check_out, existing)     -> conflicting stay | None
- reground_area_anchors(pois)       -> ids of anchors whose coordinates moved
"""
import datetime
import re
import urllib.parse
from typing import Any, List, Optional, Tuple

# Below this, an is_background=true suggestion for a single day is an LLM
# misclassification (a 60-min museum visit is not a day anchor) and gets demoted.
ANCHOR_MIN_DURATION_MINS = 180

# Geocode vs LLM-itinerary disagreement beyond this is a bogus fuzzy match.
COORD_MISMATCH_KM = 60


def anchor_fields(s: dict) -> Tuple[bool, int, int]:
    """Resolve (is_background, days_claimed, occurrences) from an LLM POI suggestion.

    Anchors are ONE POI claiming N days; occurrences-cloning is only for repeated
    standalone activities. A short single-day "anchor" is demoted to a regular POI:
    as a background it would claim a whole day exclusively and hijack that day's
    distance base in the scheduler.
    """
    is_bg = bool(s.get('is_background', False))
    days_claimed = max(1, int(s.get('days_claimed') or 1))
    if is_bg and int(s.get('occurrences') or 1) > days_claimed:
        days_claimed = int(s.get('occurrences'))  # legacy LLM habit: "3 days" as occurrences
    dur = s.get('duration_mins')
    if is_bg and days_claimed <= 1 and isinstance(dur, (int, float)) and dur < ANCHOR_MIN_DURATION_MINS:
        print(f"trip validation: demoting '{s.get('name')}' to a regular POI "
              f"(marked is_background but only lasts {int(dur)} mins)")
        is_bg = False
        days_claimed = 1
    occurrences = 1 if is_bg else max(1, int(s.get('occurrences') or 1))
    return is_bg, days_claimed, occurrences


def reground_area_anchors(pois) -> List[str]:
    """Re-center area anchors onto the centroid of their children's coordinates.

    Coordinate trust hierarchy for anchors (is_background POIs): an anchor that
    kept a confirmed place identity through reconcile_coords (mapbox_id or
    wikidata_id) is a real venue — its coordinates are ground truth. Without an
    identity it is an *area* anchor ("Paris Classic Exploration") whose
    coordinates are an LLM regional guess: leg-scale accurate (right region of a
    multi-leg trip) but not day-scale accurate. On a claimed day the anchor's
    coordinates become the scheduler's home base, so a regional guess bends the
    whole day toward a place nobody is going. The centroid of its children —
    real geocoded POIs — is where the day actually happens.

    Takes TripPOI objects or plain dicts (agent tools work pre-schema), mutates
    lat/lng in place, returns the ids of anchors that moved. Anchors with no
    located children are left untouched (the guess still carries its one real
    signal: which leg to claim).
    """
    def g(p, k):
        return p.get(k) if isinstance(p, dict) else getattr(p, k, None)

    moved: List[str] = []
    for b in pois:
        if not g(b, 'is_background'):
            continue
        if g(b, 'mapbox_id') or g(b, 'wikidata_id'):
            continue
        bid = g(b, 'id')
        kids = [p for p in pois
                if g(p, 'parent_container') == bid
                and g(p, 'lat') is not None
                and g(p, 'lng') is not None]
        if not kids:
            continue
        lat = sum(g(p, 'lat') for p in kids) / len(kids)
        lng = sum(g(p, 'lng') for p in kids) / len(kids)
        if (g(b, 'lat'), g(b, 'lng')) != (lat, lng):
            if isinstance(b, dict):
                b['lat'], b['lng'] = lat, lng
            else:
                b.lat, b.lng = lat, lng
            moved.append(bid)
    return moved


def reconcile_coords(enrichment: dict, s: dict) -> None:
    """Give the LLM's rough coordinates veto power over a bad geocode.

    Mapbox fuzzy-matches invented or region-scale names to same-named places
    anywhere ('Burgundy Wine Trail' matched a spot in Paris), silently relocating
    a whole leg for the scheduler. The LLM knows the intended region, so when the
    geocode disagrees with approx_lat/approx_lng by more than COORD_MISMATCH_KM
    the match is treated as bogus: keep the LLM's coordinates and drop the
    matched place's identity fields (hours, website, wikidata), which belong to
    the wrong place. Applies to POIs and accommodations alike. Mutates
    `enrichment` in place.
    """
    try:
        a_lat, a_lng = float(s.get('approx_lat')), float(s.get('approx_lng'))
    except (TypeError, ValueError):
        return
    if not (-90.0 <= a_lat <= 90.0 and -180.0 <= a_lng <= 180.0) or (a_lat == 0.0 and a_lng == 0.0):
        return
    lat, lng = enrichment.get('lat'), enrichment.get('lng')
    if lat is None or lng is None:
        enrichment['lat'], enrichment['lng'] = a_lat, a_lng  # rough beats nothing
        return
    from services.trip_scheduler import _haversine_km
    gap_km = _haversine_km(lat, lng, a_lat, a_lng)
    if gap_km <= COORD_MISMATCH_KM:
        return
    print(f"trip validation: geocode for '{s.get('name')}' is {gap_km:.0f}km from where the "
          f"itinerary places it — keeping the itinerary region, dropping the matched place")
    enrichment['lat'], enrichment['lng'] = a_lat, a_lng
    enrichment['location'] = (s.get('search_query') or s.get('location')
                              or s.get('name') or enrichment['location'])
    for k in ('mapbox_id', 'wikidata_id', 'opening_hours', 'website',
              'phone_number', 'cuisine', 'internet_access'):
        enrichment[k] = None
    clean_name = re.sub(r'\(.*?\)', '', s.get('name') or '').strip()
    enrichment['image_url'] = f"api/unsplash/background?query={urllib.parse.quote(clean_name)}"
    enrichment['link'] = ("https://www.google.com/maps/search/?api=1&query="
                          + urllib.parse.quote(f"{s.get('name')} {enrichment['location']}"))


def vet_poi(enrichment: dict, s: dict) -> Tuple[bool, int, int]:
    """Full POI ingest gate: coordinate reconciliation + anchor demotion.

    Mutates `enrichment`; returns (is_background, days_claimed, occurrences).
    """
    reconcile_coords(enrichment, s)
    return anchor_fields(s)


def vet_accommodation(enrichment: dict, s: dict) -> None:
    """Full accommodation ingest gate. Accommodation coordinates are the keystone:
    the scheduler's day->home-base map and geography fence trust them outright,
    so a hotel geocoded to the wrong city would make every other defense enforce
    the wrong geography. Mutates `enrichment`."""
    reconcile_coords(enrichment, s)


ACCOMMODATION_NAME_KEYWORDS = ('hotel', 'resort', 'motel', 'inn', 'airbnb', 'hyatt',
                               'marriott', 'hilton', 'lodge', 'suites', 'villa', 'bnb')

ATTRACTION_CATEGORIES = ('sightseeing', 'activity', 'shopping', 'food')


def is_misplaced_accommodation(s: dict) -> bool:
    """True when a POI suggestion is really lodging that belongs in accommodations.

    A lodging-flavored name alone is NOT enough: famous attractions carry lodging
    words ('Villa Ephrussi de Rothschild' is a garden estate, not a hotel), and
    moving one strips its dates/duration and silently deletes it from the
    itinerary. Reclassifying needs BOTH a lodging-flavored name AND no attraction
    signals (anchor flag, parent link, or an attraction category). The asymmetry
    is deliberate: wrongly keeping a hotel as a POI is visible and recoverable;
    wrongly moving an attraction is silent data loss.
    """
    name_lower = (s.get('name') or '').lower()
    if not any(k in name_lower.split() or name_lower.startswith(f"{k} ")
               or name_lower.endswith(f" {k}") for k in ACCOMMODATION_NAME_KEYWORDS):
        return False
    if s.get('is_background') or s.get('parent_container'):
        return False
    if (s.get('category') or '').lower() in ATTRACTION_CATEGORIES:
        return False
    return True


def parse_stay_range(ci_s, co_s) -> Optional[Tuple[datetime.date, datetime.date]]:
    """(check_in, check_out) as dates, or None if either is missing/unparseable."""
    try:
        ci = datetime.datetime.strptime(ci_s or '', "%Y-%m-%d").date()
        co = datetime.datetime.strptime(co_s or '', "%Y-%m-%d").date()
        return ci, co
    except (ValueError, TypeError):
        return None


def _stay_field(a: Any, k: str):
    return a.get(k) if isinstance(a, dict) else getattr(a, k, None)


def find_stay_overlap(check_in: Optional[str], check_out: Optional[str],
                      existing, exclude_id: Optional[str] = None):
    """First existing stay whose dated range overlaps [check_in, check_out), or None.

    Accepts dict or model stays; undated stays never conflict. Used by the agent
    tools to reject an overlapping add/edit with guidance instead of silently
    persisting a poisoned day->home-base map.
    """
    rng = parse_stay_range(check_in, check_out)
    if rng is None:
        return None
    ci, co = rng
    for a in existing or []:
        if exclude_id is not None and _stay_field(a, 'id') == exclude_id:
            continue
        arng = parse_stay_range(_stay_field(a, 'check_in_date'), _stay_field(a, 'check_out_date'))
        if arng and arng[0] < co and ci < arng[1]:
            return a
    return None


def repair_accommodation_overlaps(suggestions: List[dict],
                                  existing: Optional[List[Any]] = None) -> List[dict]:
    """Guard against malformed LLM accommodation output (batch form).

    Overlapping stay date ranges poison the scheduler's day->home-base map (the
    first accommodation covering a date wins), which scatters POIs geographically.
    Repairs, in order: drop stays that overlap an already-saved stay, drop
    zero-night stays, drop "umbrella" stays that strictly contain two or more
    other stays (a whole-trip hotel emitted alongside the per-leg ones), then
    clip remaining overlaps forward (the later check_in wins). Undated
    suggestions pass through untouched.

    This function deliberately never invents or extends nights: how many nights
    each leg gets is user intent the gate cannot know (extending the first stay
    to close a gap once gave Paris a 5th night the user had allotted to the
    Riviera). Coverage deficits are detected by uncovered_nights() and sent back
    to the LLM for one corrective pass at the planner layer, which still has the
    user's per-leg wording in context.
    """
    existing_ranges = []
    for a in existing or []:
        rng = parse_stay_range(_stay_field(a, 'check_in_date'), _stay_field(a, 'check_out_date'))
        if rng and rng[1] > rng[0]:
            existing_ranges.append(rng)

    undated = []   # (orig_idx, suggestion)
    dated = []     # [check_in, check_out, orig_idx, suggestion]
    for idx, s in enumerate(suggestions):
        rng = parse_stay_range(s.get('check_in_date'), s.get('check_out_date'))
        if rng is None:
            undated.append((idx, s))
            continue
        ci, co = rng
        if co <= ci:
            print(f"trip validation: dropping zero-night stay '{s.get('name')}' "
                  f"({s.get('check_in_date')} -> {s.get('check_out_date')})")
            continue
        if any(ci < eco and eci < co for eci, eco in existing_ranges):
            print(f"trip validation: dropping '{s.get('name')}' — dates overlap an existing stay")
            continue
        dated.append([ci, co, idx, s])

    kept = []
    for ci, co, idx, s in dated:
        spans = sum(1 for ci2, co2, idx2, _ in dated
                    if idx2 != idx and ci <= ci2 and co2 <= co and (ci2, co2) != (ci, co))
        if spans >= 2:
            print(f"trip validation: dropping umbrella stay '{s.get('name')}' "
                  f"({ci} -> {co}) — it spans {spans} other stays")
        else:
            kept.append([ci, co, idx, s])

    kept.sort(key=lambda t: (t[0], t[1]))
    repaired: List[list] = []
    for entry in kept:
        while repaired and entry[0] < repaired[-1][1]:
            prev = repaired[-1]
            print(f"trip validation: clipping '{prev[3].get('name')}' check-out "
                  f"{prev[1]} -> {entry[0]} (overlapped '{entry[3].get('name')}')")
            prev[1] = entry[0]
            prev[3]['check_out_date'] = entry[0].strftime("%Y-%m-%d")
            if prev[1] <= prev[0]:
                print(f"trip validation: dropping '{prev[3].get('name')}' — "
                      f"nothing left after clipping")
                repaired.pop()
            else:
                break
        repaired.append(entry)

    out = undated + [(idx, s) for _, _, idx, s in repaired]
    out.sort(key=lambda t: t[0])
    return [s for _, s in out]


def shift_stays_to_trip_start(suggestions: List[dict], existing: Optional[List[Any]],
                              trip_start: datetime.date) -> int:
    """Translate a late-starting stay chain back to the trip start (arrival day).

    The generation LLM's one persistent bias is starting the chain a day late
    ("overnight flight, arrive next morning") while keeping every leg length the
    user asked for. Leg lengths are user intent the gate must never touch; the
    anchor point is system truth — mock_start_date IS the arrival day, computed
    from the flight lookup at draft creation. Shifting the whole chain preserves
    every length and fixes only the anchor. Zero LLM requests.

    No-op when nothing is dated or when any existing stay is dated (a shift
    could collide with saved stays). Returns the number of days shifted."""
    for a in existing or []:
        if parse_stay_range(_stay_field(a, 'check_in_date'), _stay_field(a, 'check_out_date')):
            return 0
    dated = []
    for s in suggestions or []:
        rng = parse_stay_range(s.get('check_in_date'), s.get('check_out_date'))
        if rng:
            dated.append((s, rng))
    if not dated:
        return 0
    delta = (min(rng[0] for _, rng in dated) - trip_start).days
    if delta <= 0:
        return 0
    print(f"trip validation: stay chain starts {delta} day(s) after the trip's arrival day — "
          f"shifting all {len(dated)} stay(s) back to {trip_start} (leg lengths preserved)")
    for s, (ci, co) in dated:
        s['check_in_date'] = (ci - datetime.timedelta(days=delta)).strftime("%Y-%m-%d")
        s['check_out_date'] = (co - datetime.timedelta(days=delta)).strftime("%Y-%m-%d")
    return delta


def uncovered_nights(suggestions: List[dict], existing: Optional[List[Any]],
                     trip_start: datetime.date, trip_end: datetime.date) -> List[datetime.date]:
    """Trip nights in [trip_start, trip_end) not covered by any suggested or
    existing stay. Every night of a trip needs a bed: mock_start_date is already
    the arrival day (the flight lookup at draft creation computed it), and the
    last night ends with checkout on the trip's end date. An uncovered FIRST day
    is extra bad — mid-trip gap days inherit the previous night's stay as their
    scheduling home base, but day 1 has nothing to inherit, leaving it baseless
    and unfenced. Pure detector: no mutation, no LLM calls."""
    ranges = []
    for s in suggestions or []:
        rng = parse_stay_range(s.get('check_in_date'), s.get('check_out_date'))
        if rng and rng[1] > rng[0]:
            ranges.append(rng)
    for a in existing or []:
        rng = parse_stay_range(_stay_field(a, 'check_in_date'), _stay_field(a, 'check_out_date'))
        if rng and rng[1] > rng[0]:
            ranges.append(rng)
    out = []
    d = trip_start
    while d < trip_end:
        if not any(ci <= d < co for ci, co in ranges):
            out.append(d)
        d += datetime.timedelta(days=1)
    return out
