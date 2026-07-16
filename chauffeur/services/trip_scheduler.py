"""
Trip Itinerary Scheduler v2 — CP-SAT day/block assignment + deterministic timing.

Design: docs/trip_scheduler_design.md

Level 1: a CP-SAT model assigns every POI to a (day, block) slot globally.
         Distances use haversine on stored lat/lng — zero API calls.
Level 2: plain code lays concrete clock times onto each affected day using
         the block template plus real (cached) travel times between stops.

Public API (contract-compatible with the old services.trip_planner):
    schedule_poi(trip, poi, bounds=None) -> (event_id, reason, {"suggested_fixes": [...]} | None)
    schedule_pois_bulk(trip, poi_ids)    -> generator of {"poi_id", "success", "reason", ...}
"""
import datetime
import math
import re
import uuid
import zoneinfo
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Tuple

from ortools.sat.python import cp_model

from models.schemas import TripMetadata, TripPOI, TripRule

# ---------------------------------------------------------------------------
# Block template (trip-local times). Overridable via template_override rules.
# ---------------------------------------------------------------------------

@dataclass
class BlockDef:
    name: str
    start: datetime.time
    end: datetime.time
    kind: str                 # 'meal' | 'activity'
    capacity_mins: Optional[int]  # activity blocks only

DEFAULT_TEMPLATE = [
    BlockDef('breakfast', datetime.time(7, 30), datetime.time(9, 30), 'meal', None),
    BlockDef('morning', datetime.time(9, 0), datetime.time(12, 0), 'activity', 180),
    BlockDef('lunch', datetime.time(11, 30), datetime.time(13, 30), 'meal', None),
    BlockDef('afternoon', datetime.time(13, 0), datetime.time(17, 30), 'activity', 270),
    BlockDef('dinner', datetime.time(17, 30), datetime.time(20, 30), 'meal', None),
    BlockDef('evening', datetime.time(20, 0), datetime.time(23, 0), 'activity', 150),
]

MEAL_BLOCKS = ('breakfast', 'lunch', 'dinner')
ACTIVITY_BLOCKS = ('morning', 'afternoon', 'evening')
# Preferred anchor start times for meals in Level 2
MEAL_ANCHOR = {'breakfast': datetime.time(8, 0), 'lunch': datetime.time(12, 0), 'dinner': datetime.time(18, 30)}

# Objective weights (tiered — see design §6)
W_MUST, W_WANT, W_STRETCH = 10_000_000, 1_000_000, 100_000
W_CHILD_BONUS = 10_000
W_DESSERT_AFTER_DINNER = 20_000
W_CLAIM_SPAN = 40_000
W_BASE_DIST = 300      # per haversine-minute from the day's base
W_PAIR_DIST = 100      # per haversine-minute between same-day pairs
W_BALANCE = 30         # per minute of day-load deviation beyond the deadband
BALANCE_DEADBAND_MINS = 60  # imbalance this small is free — geography should win over mild unevenness
W_IDEAL_TIME_SOFT = 20_000
HAVERSINE_MINS_PER_KM = 1.4

# Wall-time cap for the solve. CP-SAT finds the best plan in milliseconds at our sizes;
# extra time only goes to *proving* optimality, so a short cap returns the same schedule.
# A relative gap limit is NOT safe here: shaping terms (clustering, balance) are tiny
# next to placement rewards by design, so any percentage gap ignores them entirely.
SOLVER_TIME_LIMIT_S = 2.5


# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------

def _haversine_km(lat1, lng1, lat2, lng2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _dist_mins(a, b) -> Optional[int]:
    """Rough driving minutes between two objects bearing lat/lng. None if either lacks coords."""
    alat, alng = getattr(a, 'lat', None), getattr(a, 'lng', None)
    blat, blng = getattr(b, 'lat', None), getattr(b, 'lng', None)
    if alat is None or alng is None or blat is None or blng is None:
        return None
    return int(round(_haversine_km(alat, alng, blat, blng) * HAVERSINE_MINS_PER_KM))


def _parse_hhmm(s: str) -> Optional[datetime.time]:
    try:
        return datetime.datetime.strptime(s.strip(), "%H:%M").time()
    except (ValueError, AttributeError):
        return None


def _resolve_tz(trip: TripMetadata) -> zoneinfo.ZoneInfo:
    tz = getattr(trip, 'timeZone', None)
    if tz and tz != 'UTC':
        try:
            return zoneinfo.ZoneInfo(tz)
        except Exception:
            pass
    if trip.location:
        try:
            from services import maps
            tz2 = maps.get_timezone(trip.location)
            if tz2 and tz2 != 'UTC':
                return zoneinfo.ZoneInfo(tz2)
        except Exception:
            pass
    return zoneinfo.ZoneInfo('America/New_York')


def _trip_bounds(trip: TripMetadata) -> Tuple[Optional[datetime.datetime], Optional[datetime.datetime], Optional[str]]:
    """Returns (start_utc, end_utc, error)."""
    if trip.is_draft:
        if not trip.mock_start_date or not trip.mock_end_date:
            return None, None, "Draft trip has no dates set."
        return (datetime.datetime.fromtimestamp(trip.mock_start_date, tz=datetime.timezone.utc),
                datetime.datetime.fromtimestamp(trip.mock_end_date, tz=datetime.timezone.utc), None)
    from services import storage, calendar
    cals = storage.get_settings().get('calendar_ids', [])
    if not cals:
        return None, None, "No calendars configured in settings."
    events = calendar.fetch_upcoming_events(cals, days=60)
    trip_event = next((e for e in events if e.id == trip.event_id or trip.event_id in getattr(e, 'source_event_ids', [])), None)
    if not trip_event:
        return None, None, "The main trip event could not be found on your calendar."
    return trip_event.start, trip_event.end, None


OPEN_HOURS_RE = re.compile(r'(\d{1,2}):(\d{2})\s*(am|pm)?\s*-\s*(\d{1,2}):(\d{2})\s*(am|pm)?')

def _parse_opening_hours(oh: Optional[str]) -> Optional[Tuple[datetime.time, datetime.time]]:
    if not oh:
        return None
    oh = oh.lower()
    if '24/7' in oh:
        return datetime.time(0, 0), datetime.time(23, 59)
    m = OPEN_HOURS_RE.search(oh)
    if not m:
        return None
    try:
        h1, m1, ap1, h2, m2, ap2 = m.groups()
        h1, m1, h2, m2 = int(h1), int(m1), int(h2), int(m2)
        if ap1 == 'pm' and h1 < 12: h1 += 12
        if ap1 == 'am' and h1 == 12: h1 = 0
        if ap2 == 'pm' and h2 < 12: h2 += 12
        if ap2 == 'am' and h2 == 12: h2 = 0
        return datetime.time(h1, m1), datetime.time(h2, m2)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Day grid
# ---------------------------------------------------------------------------

@dataclass
class DayGrid:
    index: int                      # 0-based trip day
    date: datetime.date             # local date
    weekday: int                    # 0=Mon
    blocks: List[BlockDef]
    accommodation: Optional[Any] = None  # TripAccommodation covering this date


def _build_template(trip: TripMetadata) -> List[BlockDef]:
    """Apply template_override rules to the default template."""
    blocks = [BlockDef(b.name, b.start, b.end, b.kind, b.capacity_mins) for b in DEFAULT_TEMPLATE]
    for r in getattr(trip, 'rules', []) or []:
        if not r.is_enabled or r.rule_type != 'template_override':
            continue
        if r.blocks:  # disable specific blocks
            blocks = [b for b in blocks if b.name not in r.blocks]
        t_start = _parse_hhmm(r.template_start) if r.template_start else None
        t_end = _parse_hhmm(r.template_end) if r.template_end else None
        if t_start:
            blocks = [b for b in blocks if b.end > t_start]
            for b in blocks:
                if b.start < t_start:
                    b.start = t_start
        if t_end:
            blocks = [b for b in blocks if b.start < t_end]
            for b in blocks:
                if b.end > t_end:
                    b.end = t_end
    return blocks


def _build_day_grid(trip: TripMetadata, start_utc: datetime.datetime, end_utc: datetime.datetime,
                    local_tz: zoneinfo.ZoneInfo) -> List[DayGrid]:
    template = _build_template(trip)
    start_local = start_utc.astimezone(local_tz)
    end_local = end_utc.astimezone(local_tz)

    acc_by_date: Dict[datetime.date, Any] = {}
    for acc in getattr(trip, 'accommodations', []) or []:
        try:
            ci = datetime.datetime.strptime(acc.check_in_date, "%Y-%m-%d").date()
            co = datetime.datetime.strptime(acc.check_out_date, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue
        d = ci
        while d < co:
            acc_by_date.setdefault(d, acc)
            d += datetime.timedelta(days=1)

    days: List[DayGrid] = []
    d = start_local.date()
    idx = 0
    while d <= end_local.date():
        blocks = []
        for b in template:
            b_start = datetime.datetime.combine(d, b.start, tzinfo=local_tz)
            b_end = datetime.datetime.combine(d, b.end, tzinfo=local_tz)
            # keep the block only if its window intersects the trip bounds
            if b_end > start_local and b_start < end_local:
                blocks.append(b)
        if blocks:
            days.append(DayGrid(index=idx, date=d, weekday=d.weekday(), blocks=blocks,
                                accommodation=acc_by_date.get(d)))
            idx += 1
        d += datetime.timedelta(days=1)
    return days


# ---------------------------------------------------------------------------
# POI classification / implicit rules
# ---------------------------------------------------------------------------

def _infer_meal_type(poi: TripPOI) -> Optional[str]:
    """Explicit meal_type wins; else infer from ideal_time_start for legacy POIs."""
    mt = getattr(poi, 'meal_type', None)
    if mt:
        return mt if mt != 'brunch' else 'breakfast'
    if (poi.category or '') != 'food':
        return None
    t = _parse_hhmm(poi.ideal_time_start) if poi.ideal_time_start else None
    if t:
        if t < datetime.time(10, 30):
            return 'breakfast'
        if t < datetime.time(15, 30):
            return 'lunch'
        return 'dinner'
    return None  # food, unknown meal → lunch or dinner


def _allowed_blocks_for(poi: TripPOI) -> List[str]:
    """Built-in meal-typing matrix (design §6.2)."""
    mt = _infer_meal_type(poi)
    is_food = (poi.category or '') == 'food' or mt is not None
    if not is_food:
        return list(ACTIVITY_BLOCKS)
    if mt in ('dessert', 'snack'):
        return list(ACTIVITY_BLOCKS)
    if getattr(poi, 'dining_style', None) == 'fine' and mt != 'lunch':
        return ['dinner']
    if mt in MEAL_BLOCKS:
        return [mt]
    return ['lunch', 'dinner']


def _is_meal(poi: TripPOI) -> bool:
    """Counts against the one-meal-per-block exclusivity."""
    mt = _infer_meal_type(poi)
    is_food = (poi.category or '') == 'food' or mt is not None
    return is_food and mt not in ('dessert', 'snack')


def _matches_rule(poi: TripPOI, rule: TripRule) -> bool:
    if rule.poi_ids and poi.id not in rule.poi_ids:
        return False
    if rule.categories and (poi.category or '') not in rule.categories:
        return False
    if rule.keywords:
        text = f"{poi.name or ''} {poi.description or ''}".lower()
        if not any(k.lower() in text for k in rule.keywords):
            return False
    return True


def _rule_days(rule: TripRule, days: List[DayGrid]) -> List[int]:
    """Day indexes a rule's day selectors match. Empty selectors → all days."""
    out = []
    for d in days:
        if rule.days_of_week and d.weekday not in rule.days_of_week:
            continue
        if rule.trip_days and (d.index + 1) not in rule.trip_days:
            continue
        out.append(d.index)
    return out


# ---------------------------------------------------------------------------
# Level 1 — CP-SAT assignment
# ---------------------------------------------------------------------------

@dataclass
class SolveResult:
    assigned: Dict[str, Tuple[int, str]] = field(default_factory=dict)      # poi_id -> (day_idx, block)
    claims: Dict[str, List[int]] = field(default_factory=dict)              # bg poi_id -> [day_idx]
    failures: Dict[str, str] = field(default_factory=dict)                  # poi_id -> reason
    fixes: Dict[str, List[dict]] = field(default_factory=dict)              # poi_id -> suggested fixes
    days: List[DayGrid] = field(default_factory=list)
    local_tz: Optional[zoneinfo.ZoneInfo] = None
    error: Optional[str] = None


def solve_assignment(trip: TripMetadata, target_ids: List[str],
                     bounds: Optional[Tuple[datetime.datetime, datetime.datetime]] = None) -> SolveResult:
    res = SolveResult()
    start_utc, end_utc, err = _trip_bounds(trip)
    if err:
        res.error = err
        return res
    if bounds:
        start_utc = max(start_utc, bounds[0])
        end_utc = min(end_utc, bounds[1])
    local_tz = _resolve_tz(trip)
    days = _build_day_grid(trip, start_utc, end_utc, local_tz)
    res.days, res.local_tz = days, local_tz
    if not days:
        res.error = "The trip has no schedulable days."
        return res
    D = len(days)
    day_by_idx = {d.index: d for d in days}

    rules = [r for r in (getattr(trip, 'rules', []) or []) if r.is_enabled and r.rule_type != 'template_override']

    pois_by_id = {p.id: p for p in trip.pois}
    target_ids = [pid for pid in target_ids if pid in pois_by_id]
    targets = [pois_by_id[pid] for pid in target_ids]
    locked = [p for p in trip.pois if p.is_scheduled and p.scheduled_start and p.id not in target_ids]

    backgrounds = [p for p in targets if getattr(p, 'is_background', False)]
    regulars = [p for p in targets if not getattr(p, 'is_background', False)]

    # Locked placements → (day_idx, block) by local time; off-grid locked POIs are ignored.
    locked_at: Dict[str, Tuple[int, str]] = {}
    locked_bg_days: Dict[str, List[int]] = {}
    date_to_idx = {d.date: d.index for d in days}
    for p in locked:
        p_local = datetime.datetime.fromtimestamp(p.scheduled_start, tz=datetime.timezone.utc).astimezone(local_tz)
        di = date_to_idx.get(p_local.date())
        if di is None:
            continue
        if getattr(p, 'is_background', False):
            bg_days = []
            for ds in (getattr(p, 'claimed_dates', None) or [p_local.strftime("%Y-%m-%d")]):
                try:
                    d_idx = date_to_idx.get(datetime.datetime.strptime(ds, "%Y-%m-%d").date())
                except ValueError:
                    d_idx = None
                if d_idx is not None:
                    bg_days.append(d_idx)
            locked_bg_days[p.id] = bg_days
            continue
        blk = None
        for b in day_by_idx[di].blocks:
            if b.start <= p_local.time() < b.end:
                if blk is None or (_is_meal(p) == (b.kind == 'meal')):
                    blk = b.name
        locked_at[p.id] = (di, blk or day_by_idx[di].blocks[0].name)

    model = cp_model.CpModel()

    # --- background claim vars -------------------------------------------
    claim: Dict[Tuple[str, int], Any] = {}
    bg_scheduled: Dict[str, Any] = {}
    prune_cause: Dict[str, str] = {}

    hard_clear: Dict[int, set] = {}   # day_idx -> set(block names) hard-cleared
    for r in rules:
        if r.rule_type == 'keep_clear' and r.hardness == 'hard':
            for di in _rule_days(r, days):
                names = set(r.blocks) if r.blocks else {b.name for b in day_by_idx[di].blocks}
                hard_clear.setdefault(di, set()).update(names)

    for b in backgrounds:
        legal_days = []
        for d in days:
            if b.valid_days_of_week and d.weekday not in b.valid_days_of_week:
                continue
            if d.index in hard_clear and hard_clear[d.index] >= {blk.name for blk in d.blocks}:
                continue  # fully cleared day can't be claimed
            if any(d.index in bdays for bdays in locked_bg_days.values()):
                continue  # a locked background already owns this day
            legal_days.append(d.index)
        need = max(1, getattr(b, 'days_claimed', 1) or 1)
        sv = model.NewBoolVar(f"bgsched_{b.id}")
        bg_scheduled[b.id] = sv
        if len(legal_days) < need:
            model.Add(sv == 0)
            if b.valid_days_of_week:
                prune_cause[b.id] = (f"needs {need} day(s) on "
                                     f"{_weekday_names(b.valid_days_of_week)} but the trip only has "
                                     f"{len(legal_days)} such day(s) available")
            else:
                prune_cause[b.id] = f"needs {need} day(s) but only {len(legal_days)} are available"
        for di in legal_days:
            claim[(b.id, di)] = model.NewBoolVar(f"claim_{b.id}_{di}")
        model.Add(sum(claim[(b.id, di)] for di in legal_days) == need * sv)

    # at most one container per day (locked backgrounds already excluded their days)
    for d in days:
        todays = [claim[(b.id, d.index)] for b in backgrounds if (b.id, d.index) in claim]
        if len(todays) > 1:
            model.Add(sum(todays) <= 1)

    # soft consecutive preference: penalize claim span beyond the minimum
    span_pens = []
    for b in backgrounds:
        legal = [di for di in range(D) if (b.id, di) in claim]
        need = max(1, getattr(b, 'days_claimed', 1) or 1)
        if need <= 1 or not legal:
            continue
        lo = model.NewIntVar(0, D - 1, f"lo_{b.id}")
        hi = model.NewIntVar(0, D - 1, f"hi_{b.id}")
        for di in legal:
            model.Add(lo <= di).OnlyEnforceIf(claim[(b.id, di)])
            model.Add(hi >= di).OnlyEnforceIf(claim[(b.id, di)])
        sp = model.NewIntVar(0, D, f"span_{b.id}")
        model.Add(sp >= hi - lo - (need - 1))
        model.Add(lo == 0).OnlyEnforceIf(bg_scheduled[b.id].Not())
        model.Add(hi == 0).OnlyEnforceIf(bg_scheduled[b.id].Not())
        span_pens.append(sp)

    # --- regular POI vars --------------------------------------------------
    x: Dict[Tuple[str, int, str], Any] = {}
    poi_reason: Dict[str, str] = {}
    poi_fixes: Dict[str, List[dict]] = {}

    for p in regulars:
        allowed_blocks = set(_allowed_blocks_for(p))
        # opening hours: hard, but gracefully dropped if they'd prune everything
        oh = _parse_opening_hours(getattr(p, 'opening_hours', None))
        oh_blocks = None
        if oh:
            oh_open, oh_close = oh
            oh_blocks = set()
            for b in DEFAULT_TEMPLATE:
                b_end_est = (datetime.datetime.combine(datetime.date.today(), b.start)
                             + datetime.timedelta(minutes=min(p.duration_mins or 60, 240))).time()
                if b.start >= oh_open and b_end_est <= oh_close:
                    oh_blocks.add(b.name)
            if oh_blocks & allowed_blocks:
                allowed_blocks &= oh_blocks
            # else: unparseable/pathological hours — ignore rather than hard-fail

        allowed_days = set(range(D))
        if p.valid_days_of_week:
            allowed_days = {d.index for d in days if d.weekday in p.valid_days_of_week}

        # hard rules
        blocked_by_rule = None
        for r in rules:
            if r.hardness != 'hard' or not _matches_rule(p, r):
                continue
            if r.rule_type == 'day_restriction':
                rd = set(_rule_days(r, days))
                if allowed_days & rd:
                    allowed_days &= rd
                else:
                    allowed_days = set()
                    blocked_by_rule = r
            elif r.rule_type == 'block_restriction' and r.blocks:
                if allowed_blocks & set(r.blocks):
                    allowed_blocks &= set(r.blocks)
                else:
                    allowed_blocks = set()
                    blocked_by_rule = r

        created = 0
        for di in allowed_days:
            day = day_by_idx[di]
            cleared = hard_clear.get(di, set())
            for b in day.blocks:
                if b.name not in allowed_blocks or b.name in cleared:
                    continue
                if b.kind == 'activity' and (p.duration_mins or 60) > (b.capacity_mins or 0):
                    continue
                x[(p.id, di, b.name)] = model.NewBoolVar(f"x_{p.id}_{di}_{b.name}")
                created += 1

        if created == 0:
            if blocked_by_rule is not None:
                poi_reason[p.id] = f"blocked by rule: {blocked_by_rule.description}"
                poi_fixes[p.id] = [{"type": "disable_rule", "rule_id": blocked_by_rule.id,
                                    "label": f"Disable rule '{blocked_by_rule.description}' and retry"}]
            elif p.valid_days_of_week and not allowed_days:
                poi_reason[p.id] = (f"restricted to {_weekday_names(p.valid_days_of_week)}, "
                                    "but the trip includes none of those days")
                poi_fixes[p.id] = [{"type": "clear_days", "label": "Remove day-of-week restriction and retry"}]
            elif not allowed_blocks:
                poi_reason[p.id] = "no compatible time block (meal type / opening hours conflict)"
            else:
                poi_reason[p.id] = ("too long for any activity block "
                                    f"({p.duration_mins} mins)") if (p.duration_mins or 60) > 270 else \
                                   "no compatible day/block combination"

    scheduled: Dict[str, Any] = {}
    for p in regulars:
        vars_p = [v for (pid, _, _), v in x.items() if pid == p.id]
        if not vars_p:
            continue
        s = model.NewBoolVar(f"sched_{p.id}")
        model.Add(sum(vars_p) == 1).OnlyEnforceIf(s)
        model.Add(sum(vars_p) == 0).OnlyEnforceIf(s.Not())
        scheduled[p.id] = s

    # children may only land on their parent's claimed days
    bg_target_ids = {b.id for b in backgrounds}
    for p in regulars:
        parent = getattr(p, 'parent_container', None)
        if not parent or p.id not in scheduled:
            continue
        if parent in bg_target_ids:
            for (pid, di, bname), v in list(x.items()):
                if pid != p.id:
                    continue
                if (parent, di) in claim:
                    model.AddImplication(v, claim[(parent, di)])
                else:
                    model.Add(v == 0)
            model.AddImplication(scheduled[p.id], bg_scheduled[parent])
        elif parent in locked_bg_days:
            ok_days = set(locked_bg_days[parent])
            for (pid, di, bname), v in list(x.items()):
                if pid == p.id and di not in ok_days:
                    model.Add(v == 0)
        # parent id unknown (stale) → treat as unparented

    # --- meal exclusivity ---------------------------------------------------
    for d in days:
        for b in d.blocks:
            if b.kind != 'meal':
                continue
            occupied = sum(1 for lp_id, (ldi, lblk) in locked_at.items()
                           if ldi == d.index and lblk == b.name and _is_meal(pois_by_id[lp_id]))
            meal_vars = [v for (pid, di, bname), v in x.items()
                         if di == d.index and bname == b.name and _is_meal(pois_by_id[pid])]
            if meal_vars:
                model.Add(sum(meal_vars) <= max(0, 1 - occupied))

    # --- activity block capacity ---------------------------------------------
    for d in days:
        for b in d.blocks:
            if b.kind != 'activity':
                continue
            used = sum((pois_by_id[lp_id].duration_mins or 60)
                       for lp_id, (ldi, lblk) in locked_at.items()
                       if ldi == d.index and lblk == b.name)
            terms = [(pois_by_id[pid].duration_mins or 60) * v
                     for (pid, di, bname), v in x.items() if di == d.index and bname == b.name]
            if terms:
                model.Add(sum(terms) <= max(0, (b.capacity_mins or 0) - used))

    # --- day indicator vars (for clustering / distance / capacity terms) ------
    day_bool: Dict[Tuple[str, int], Any] = {}
    for p in regulars:
        if p.id not in scheduled:
            continue
        for d in days:
            vars_pd = [v for (pid, di, bname), v in x.items() if pid == p.id and di == d.index]
            if vars_pd:
                db = model.NewBoolVar(f"day_{p.id}_{d.index}")
                model.Add(sum(vars_pd) == db)
                day_bool[(p.id, d.index)] = db

    # --- stored rules: remaining kinds ----------------------------------------
    obj_terms: List[Any] = []

    for r in rules:
        matched_free = [p for p in regulars if p.id in scheduled and _matches_rule(p, r)]
        matched_locked = [pois_by_id[i] for i in locked_at if _matches_rule(pois_by_id[i], r)]

        if r.rule_type == 'day_restriction' and r.hardness == 'soft':
            ok = set(_rule_days(r, days))
            for p in matched_free:
                for d in days:
                    if d.index not in ok and (p.id, d.index) in day_bool:
                        obj_terms.append(-r.weight * day_bool[(p.id, d.index)])

        elif r.rule_type == 'block_restriction' and r.hardness == 'soft' and r.blocks:
            for p in matched_free:
                for (pid, di, bname), v in x.items():
                    if pid == p.id and bname not in r.blocks:
                        obj_terms.append(-r.weight * v)

        elif r.rule_type == 'keep_clear' and r.hardness == 'soft':
            zone_days = set(_rule_days(r, days))
            names = set(r.blocks) if r.blocks else None
            for (pid, di, bname), v in x.items():
                if di in zone_days and (names is None or bname in names):
                    obj_terms.append(-r.weight * v)

        elif r.rule_type == 'day_capacity' and r.max_active_mins is not None:
            for di in _rule_days(r, days):
                base = sum((pois_by_id[i].duration_mins or 60) for i, (ldi, _) in locked_at.items() if ldi == di)
                terms = [(pois_by_id[pid].duration_mins or 60) * v
                         for (pid, d2, bname), v in x.items() if d2 == di]
                if not terms and base <= r.max_active_mins:
                    continue
                if r.hardness == 'hard':
                    model.Add(sum(terms) <= max(0, r.max_active_mins - base))
                else:
                    over = model.NewIntVar(0, 24 * 60, f"cap_over_{r.id}_{di}")
                    model.Add(over >= sum(terms) + base - r.max_active_mins)
                    obj_terms.append(-(r.weight // 10) * over)

        elif r.rule_type == 'budget_cap' and r.max_usd is not None:
            cents_locked = sum(int((p.estimated_price_usd or 0) * 100)
                               for p in matched_locked)
            terms = [int((p.estimated_price_usd or 0) * 100) * scheduled[p.id]
                     for p in matched_free if (p.estimated_price_usd or 0) > 0]
            cap = int(r.max_usd * 100)
            if terms:
                if r.hardness == 'hard':
                    model.Add(sum(terms) <= max(0, cap - cents_locked))
                else:
                    over = model.NewIntVar(0, 10 ** 9, f"budget_over_{r.id}")
                    model.Add(over >= sum(terms) + cents_locked - cap)
                    obj_terms.append(-max(1, r.weight // 100) * over)

        elif r.rule_type == 'spacing' and r.min_gap_days:
            gap = r.min_gap_days
            matched_bg = [b for b in backgrounds if _matches_rule(b, r)]
            for i in range(len(matched_bg)):
                for j in range(i + 1, len(matched_bg)):
                    b1, b2 = matched_bg[i], matched_bg[j]
                    for d1 in range(D):
                        for d2 in range(D):
                            if abs(d1 - d2) <= gap and (b1.id, d1) in claim and (b2.id, d2) in claim and d1 != d2:
                                if r.hardness == 'hard':
                                    model.Add(claim[(b1.id, d1)] + claim[(b2.id, d2)] <= 1)
            for i in range(len(matched_free)):
                for j in range(i + 1, len(matched_free)):
                    p1, p2 = matched_free[i], matched_free[j]
                    for d1 in range(D):
                        for d2 in range(D):
                            if abs(d1 - d2) < gap:
                                v1, v2 = day_bool.get((p1.id, d1)), day_bool.get((p2.id, d2))
                                if v1 is not None and v2 is not None:
                                    if r.hardness == 'hard':
                                        model.Add(v1 + v2 <= 1)
                                    else:
                                        both = model.NewBoolVar(f"sp_{r.id}_{p1.id}_{p2.id}_{d1}_{d2}")
                                        model.Add(both >= v1 + v2 - 1)
                                        obj_terms.append(-r.weight * both)

    # --- soft ideal-time override (legacy field → nearest blocks preferred) ----
    for p in regulars:
        if p.id not in scheduled or _is_meal(p):
            continue  # meals already snap to their block
        t = _parse_hhmm(p.ideal_time_start) if p.ideal_time_start else None
        if not t:
            continue
        preferred = {b.name for b in DEFAULT_TEMPLATE if b.kind == 'activity' and b.start <= t < b.end}
        if not preferred:
            continue
        for (pid, di, bname), v in x.items():
            if pid == p.id and bname not in preferred:
                obj_terms.append(-W_IDEAL_TIME_SOFT * v)

    # --- objective: placement rewards ------------------------------------------
    prio_w = {'must': W_MUST, 'want': W_WANT, 'stretch': W_STRETCH}
    for p in regulars:
        if p.id in scheduled:
            w = prio_w.get((p.priority or 'want').lower(), W_WANT)
            if getattr(p, 'parent_container', None):
                w += W_CHILD_BONUS
            obj_terms.append(w * scheduled[p.id])
    for b in backgrounds:
        obj_terms.append(prio_w.get((b.priority or 'want').lower(), W_WANT) * bg_scheduled[b.id])
    for sp in span_pens:
        obj_terms.append(-W_CLAIM_SPAN * sp)

    # --- distance terms (haversine, zero API) -----------------------------------
    def _base_for_day(d: DayGrid):
        return d.accommodation

    parent_of = {p.id: getattr(p, 'parent_container', None) for p in regulars}
    for p in regulars:
        if p.id not in scheduled:
            continue
        for d in days:
            db = day_bool.get((p.id, d.index))
            if db is None:
                continue
            parent = parent_of.get(p.id)
            if parent and (parent in bg_target_ids or parent in locked_bg_days):
                anchor = pois_by_id.get(parent)
                dist = _dist_mins(anchor, p) if anchor else None
                if dist is not None:
                    obj_terms.append(-W_BASE_DIST * dist * db)
                continue
            base = _base_for_day(d)
            dist_acc = _dist_mins(base, p) if base is not None else None
            if dist_acc is not None:
                obj_terms.append(-W_BASE_DIST * dist_acc * db)
            # anchor-day switch: if a background claims this day, base becomes the anchor
            for b in backgrounds:
                cl = claim.get((b.id, d.index))
                if cl is None:
                    continue
                dist_anchor = _dist_mins(b, p)
                if dist_anchor is None:
                    continue
                delta = dist_anchor - (dist_acc or 0)
                if delta == 0:
                    continue
                y = model.NewBoolVar(f"y_{p.id}_{d.index}_{b.id}")
                model.Add(y <= db)
                model.Add(y <= cl)
                model.Add(y >= db + cl - 1)
                obj_terms.append(-W_BASE_DIST * delta * y)
            for bid, bdays in locked_bg_days.items():
                if d.index in bdays:
                    anchor = pois_by_id.get(bid)
                    dist_anchor = _dist_mins(anchor, p) if anchor else None
                    if dist_anchor is not None:
                        delta = dist_anchor - (dist_acc or 0)
                        if delta:
                            obj_terms.append(-W_BASE_DIST * delta * db)

    # same-day pair distance (one aux var per pair)
    free_with_coords = [p for p in regulars if p.id in scheduled and p.lat is not None and p.lng is not None]
    for i in range(len(free_with_coords)):
        for j in range(i + 1, len(free_with_coords)):
            p, q = free_with_coords[i], free_with_coords[j]
            dist = _dist_mins(p, q)
            if dist is None or dist <= 0:
                continue
            sd = model.NewBoolVar(f"sd_{p.id}_{q.id}")
            shared = False
            for d in days:
                vp, vq = day_bool.get((p.id, d.index)), day_bool.get((q.id, d.index))
                if vp is not None and vq is not None:
                    model.Add(sd >= vp + vq - 1)
                    shared = True
            if shared:
                obj_terms.append(-W_PAIR_DIST * dist * sd)
    # pairs against locked POIs (linear, no aux needed)
    for p in free_with_coords:
        for lid, (ldi, _) in locked_at.items():
            lp = pois_by_id[lid]
            dist = _dist_mins(p, lp)
            db = day_bool.get((p.id, ldi))
            if dist and db is not None:
                obj_terms.append(-W_PAIR_DIST * dist * db)

    # dessert-after-dinner bonus
    dinner_free = [p for p in regulars if p.id in scheduled and _infer_meal_type(p) == 'dinner']
    dessert_free = [p for p in regulars if p.id in scheduled and _infer_meal_type(p) in ('dessert', 'snack')]
    locked_dinner_days = {ldi for lid, (ldi, lblk) in locked_at.items()
                          if lblk == 'dinner' and _infer_meal_type(pois_by_id[lid]) == 'dinner'}
    for p in dessert_free:
        for d in days:
            v_eve = x.get((p.id, d.index, 'evening'))
            if v_eve is None:
                continue
            if d.index in locked_dinner_days:
                obj_terms.append(W_DESSERT_AFTER_DINNER * v_eve)
                continue
            dinner_vars = [x[(q.id, d.index, 'dinner')] for q in dinner_free if (q.id, d.index, 'dinner') in x]
            if dinner_vars:
                z = model.NewBoolVar(f"dd_{p.id}_{d.index}")
                model.Add(z <= v_eve)
                model.Add(z <= sum(dinner_vars))
                obj_terms.append(W_DESSERT_AFTER_DINNER * z)

    # day-load balance (target scaled by each day's available capacity)
    total_target_mins = sum((p.duration_mins or 60) for p in regulars if p.id in scheduled)
    cap_per_day = {d.index: sum((b.capacity_mins or 90) for b in d.blocks) for d in days}
    total_cap = sum(cap_per_day.values()) or 1
    if total_target_mins > 0 and D > 1:
        for d in days:
            target_d = total_target_mins * cap_per_day[d.index] // total_cap
            load_terms = [(pois_by_id[pid].duration_mins or 60) * v
                          for (pid, di, bname), v in x.items() if di == d.index]
            base = sum((pois_by_id[i].duration_mins or 60) for i, (ldi, _) in locked_at.items() if ldi == d.index)
            if not load_terms:
                continue
            dev = model.NewIntVar(0, 24 * 60, f"dev_{d.index}")
            model.Add(dev >= sum(load_terms) + base - target_d - BALANCE_DEADBAND_MINS)
            model.Add(dev >= target_d - sum(load_terms) - base - BALANCE_DEADBAND_MINS)
            obj_terms.append(-W_BALANCE * dev)

    model.Maximize(sum(obj_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = SOLVER_TIME_LIMIT_S
    solver.parameters.num_search_workers = 4
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        res.error = "The scheduler could not find a feasible plan (conflicting hard rules)."
        return res

    for b in backgrounds:
        if solver.Value(bg_scheduled[b.id]):
            res.claims[b.id] = sorted(di for di in range(D) if (b.id, di) in claim and solver.Value(claim[(b.id, di)]))
        else:
            res.failures[b.id] = prune_cause.get(b.id, "could not claim the required days (day conflicts with other anchors or rules)")
    for p in regulars:
        if p.id in scheduled and solver.Value(scheduled[p.id]):
            for (pid, di, bname), v in x.items():
                if pid == p.id and solver.Value(v):
                    res.assigned[p.id] = (di, bname)
                    break
        else:
            res.failures[p.id] = poi_reason.get(p.id) or _competition_reason(p, pois_by_id, x, days, res, locked_at)
            if p.id in poi_fixes:
                res.fixes[p.id] = poi_fixes[p.id]
    return res


def _weekday_names(nums: List[int]) -> str:
    names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    return "/".join(names[n] for n in sorted(set(nums)) if 0 <= n <= 6)


def _competition_reason(p, pois_by_id, x, days, res: SolveResult, locked_at) -> str:
    """Post-hoc explanation for a POI the solver left unscheduled despite having legal slots."""
    parent = getattr(p, 'parent_container', None)
    if parent and parent in res.failures:
        parent_poi = pois_by_id.get(parent)
        return f"its parent '{parent_poi.name if parent_poi else parent}' was not scheduled"
    if _is_meal(p):
        blocks = set(_allowed_blocks_for(p))
        slots = sum(1 for (pid, di, bname) in x if pid == p.id)
        competitors = sum(1 for q in pois_by_id.values()
                          if q.id != p.id and _is_meal(q) and set(_allowed_blocks_for(q)) & blocks
                          and (q.id in res.assigned or q.id in locked_at))
        return (f"all eligible {'/'.join(sorted(blocks))} slots were taken "
                f"({slots} eligible slot(s), {competitors} competing restaurant(s))")
    return "did not fit: competing activities filled its eligible days and blocks"


# ---------------------------------------------------------------------------
# Level 2 — deterministic timing
# ---------------------------------------------------------------------------

def _real_travel_mins(loc_a: Optional[str], loc_b: Optional[str], a=None, b=None) -> int:
    """
    Travel estimate for Level 2 spacing. Haversine-first: with stored coords this is
    instant and zero-API. maps.get_travel_time_minutes is only a fallback for
    coordinate-less locations — it can geocode (Nominatim ~1.1s/lookup) and hit the
    Matrix API, which is exactly the latency the old scheduler drowned in.
    """
    if not loc_a or not loc_b:
        return 15
    if loc_a.strip().lower() == loc_b.strip().lower():
        return 0
    hv = _dist_mins(a, b) if a is not None and b is not None else None
    if hv is not None:
        return hv
    try:
        from services import maps
        mins = maps.get_travel_time_minutes(loc_a, loc_b)
    except Exception:
        mins = None
    if mins is None or mins >= 600:  # unroutable sentinel
        return 20
    return int(mins)


def _apply_claims(trip: TripMetadata, res: SolveResult) -> None:
    """Backgrounds: claims → claimed_dates + spanning timestamps."""
    local_tz = res.local_tz
    pois_by_id = {p.id: p for p in trip.pois}
    day_by_idx = {d.index: d for d in res.days}
    for bid, day_idxs in res.claims.items():
        b = pois_by_id[bid]
        dates = [day_by_idx[di].date for di in day_idxs]
        b.claimed_dates = [d.strftime("%Y-%m-%d") for d in dates]
        first, last = min(dates), max(dates)
        start_local = datetime.datetime.combine(first, datetime.time(9, 0), tzinfo=local_tz)
        # non-consecutive claims can't honestly span; timestamps cover the first day, claimed_dates has the rest
        end_date = last if (last - first).days == len(dates) - 1 else first
        end_local = datetime.datetime.combine(end_date, datetime.time(21, 0), tzinfo=local_tz)
        b.is_scheduled = True
        b.scheduled_start = start_local.timestamp()
        b.scheduled_end = end_local.timestamp()
        if not b.event_id:
            b.event_id = f"draft_poi_{uuid.uuid4().hex}"


def _anchor_map(trip: TripMetadata, res: SolveResult) -> Dict[int, TripPOI]:
    """Anchor POI per day index (freshly claimed + locked backgrounds)."""
    pois_by_id = {p.id: p for p in trip.pois}
    date_to_idx = {d.date: d.index for d in res.days}
    anchor_by_day: Dict[int, TripPOI] = {}
    for bid, day_idxs in res.claims.items():
        for di in day_idxs:
            anchor_by_day[di] = pois_by_id[bid]
    for p in trip.pois:
        if getattr(p, 'is_background', False) and p.is_scheduled and p.id not in res.claims:
            for ds in (getattr(p, 'claimed_dates', None) or []):
                try:
                    di = date_to_idx.get(datetime.datetime.strptime(ds, "%Y-%m-%d").date())
                except ValueError:
                    di = None
                if di is not None:
                    anchor_by_day.setdefault(di, p)
    return anchor_by_day


def layout_days(trip: TripMetadata, res: SolveResult, affected_pids: List[str]) -> None:
    """Write concrete scheduled_start/end (UTC ts) onto affected POIs, re-timing each affected day."""
    _apply_claims(trip, res)
    anchor_by_day = _anchor_map(trip, res)
    affected_days = {res.assigned[pid][0] for pid in affected_pids if pid in res.assigned}
    for di in sorted(affected_days):
        _layout_one_day(trip, res, di, anchor_by_day)


def _layout_one_day(trip: TripMetadata, res: SolveResult, di: int, anchor_by_day: Dict[int, TripPOI]) -> None:
    local_tz = res.local_tz
    pois_by_id = {p.id: p for p in trip.pois}
    day = {d.index: d for d in res.days}[di]

    # everything on this day: newly assigned + previously scheduled regulars
    entries: Dict[str, str] = {}  # pid -> block
    for pid in res.assigned:
        if res.assigned[pid][0] == di:
            entries[pid] = res.assigned[pid][1]
    for p in trip.pois:
        if p.id in entries or getattr(p, 'is_background', False):
            continue
        if p.is_scheduled and p.scheduled_start and p.id not in res.assigned:
            p_local = datetime.datetime.fromtimestamp(p.scheduled_start, tz=datetime.timezone.utc).astimezone(local_tz)
            if p_local.date() == day.date:
                blk = next((b.name for b in day.blocks if b.start <= p_local.time() < b.end), None)
                entries[p.id] = blk or day.blocks[0].name

    base = anchor_by_day.get(di) or day.accommodation
    prev = base  # previous stop (carries across blocks so travel chains correctly)
    prev_loc = getattr(base, 'location', None) or trip.location
    prev_end: Optional[datetime.datetime] = None

    for b in day.blocks:
        block_pois = [pois_by_id[pid] for pid, blk in entries.items() if blk == b.name]
        if not block_pois:
            continue
        # nearest-neighbor order within the block, starting from the previous stop
        ordered: List[TripPOI] = []
        cursor = prev
        remaining = list(block_pois)
        while remaining:
            nxt = min(remaining, key=lambda q: (_dist_mins(cursor, q) if _dist_mins(cursor, q) is not None else 30))
            ordered.append(nxt)
            remaining.remove(nxt)
            cursor = nxt

        window_start = datetime.datetime.combine(day.date, b.start, tzinfo=local_tz)
        window_end = datetime.datetime.combine(day.date, b.end, tzinfo=local_tz)
        for p in ordered:
            travel = _real_travel_mins(prev_loc, p.location, a=prev, b=p)
            start = window_start
            if prev_end is not None:
                start = max(start, prev_end + datetime.timedelta(minutes=travel))
            if b.kind == 'meal' and b.name in MEAL_ANCHOR:
                anchor_t = datetime.datetime.combine(day.date, MEAL_ANCHOR[b.name], tzinfo=local_tz)
                latest_ok = window_end - datetime.timedelta(minutes=(p.duration_mins or 60))
                start = min(max(start, anchor_t), max(window_start, latest_ok))
            # snap to 5 minutes
            start -= datetime.timedelta(minutes=start.minute % 5, seconds=start.second,
                                        microseconds=start.microsecond)
            end = start + datetime.timedelta(minutes=p.duration_mins or 60)
            p.is_scheduled = True
            p.scheduled_start = start.timestamp()
            p.scheduled_end = end.timestamp()
            if not p.event_id:
                p.event_id = f"draft_poi_{uuid.uuid4().hex}"
            prev_end = end
            prev_loc = p.location or prev_loc
            prev = p

    # extend the day's background span to cover late children on its final claimed day
    anchor = anchor_by_day.get(di)
    if (anchor is not None and prev_end is not None and anchor.scheduled_end
            and prev_end.timestamp() > anchor.scheduled_end
            and (anchor.claimed_dates or [None])[-1] == day.date.strftime("%Y-%m-%d")):
        anchor.scheduled_end = prev_end.timestamp()


def claimed_day_spans(poi: Dict[str, Any], tz_str: Optional[str]) -> Optional[List[Tuple[int, int, float, float]]]:
    """
    For a multi-day background POI (dict form, as stored), return one (index, total,
    start_ts, end_ts) span per claimed date so the UI can render a card on every claimed
    day — including non-consecutive claims. Returns None for anything else.
    """
    claimed = poi.get("claimed_dates") or []
    if not (poi.get("is_background") and len(claimed) > 1):
        return None
    try:
        tz = zoneinfo.ZoneInfo(tz_str) if tz_str else zoneinfo.ZoneInfo("America/New_York")
    except Exception:
        tz = zoneinfo.ZoneInfo("America/New_York")
    spans = []
    for i, ds in enumerate(claimed):
        try:
            d = datetime.datetime.strptime(ds, "%Y-%m-%d")
        except (ValueError, TypeError):
            continue
        start = d.replace(hour=9, minute=0, tzinfo=tz)
        end = d.replace(hour=21, minute=0, tzinfo=tz)
        spans.append((i, len(claimed), start.timestamp(), end.timestamp()))
    return spans or None


# ---------------------------------------------------------------------------
# Public API (contract-compatible with the old trip_planner scheduler)
# ---------------------------------------------------------------------------

def schedule_pois_bulk(trip: TripMetadata, poi_ids: List[str]) -> Iterator[Dict[str, Any]]:
    from services import storage
    if not storage.get_settings().get('calendar_ids', []):
        for pid in poi_ids:
            yield {"poi_id": pid, "success": False, "reason": "No calendars configured in settings."}
        return

    target_ids = [pid for pid in poi_ids
                  if any(p.id == pid and not p.is_scheduled for p in trip.pois)]
    if not target_ids:
        return

    res = solve_assignment(trip, target_ids)
    if res.error:
        for pid in target_ids:
            yield {"poi_id": pid, "success": False, "reason": res.error}
        return

    # Stream incrementally: failures first, then anchors, then day by day as each is
    # laid out — the UI refreshes on every success line, so results pop in as they land.
    # A client cancel (disconnect) stops the generator at the next yield.
    for pid in target_ids:
        if pid not in res.assigned and pid not in res.claims:
            out = {"poi_id": pid, "success": False,
                   "reason": res.failures.get(pid, "could not be scheduled")}
            if pid in res.fixes:
                out["suggested_fixes"] = res.fixes[pid]
            yield out

    _apply_claims(trip, res)
    for pid in target_ids:
        if pid in res.claims:
            yield {"poi_id": pid, "success": True, "reason": None}

    anchor_by_day = _anchor_map(trip, res)
    affected_days = sorted({res.assigned[pid][0] for pid in target_ids if pid in res.assigned})
    for di in affected_days:
        _layout_one_day(trip, res, di, anchor_by_day)
        for pid in target_ids:
            if pid in res.assigned and res.assigned[pid][0] == di:
                yield {"poi_id": pid, "success": True, "reason": None}


def schedule_poi(trip: TripMetadata, poi: TripPOI,
                 bounds: Optional[Tuple[datetime.datetime, datetime.datetime]] = None
                 ) -> Tuple[Optional[str], Optional[str], Optional[dict]]:
    from services import storage
    if not storage.get_settings().get('calendar_ids', []):
        return None, "No calendars configured in settings.", None

    res = solve_assignment(trip, [poi.id], bounds=bounds)
    if res.error:
        return None, res.error, None
    if poi.id not in res.assigned and poi.id not in res.claims:
        reason = res.failures.get(poi.id, "Could not find an available slot matching constraints.")
        fixes = res.fixes.get(poi.id, [])
        return None, reason, {"suggested_fixes": fixes} if fixes else None

    layout_days(trip, res, [poi.id])
    return poi.event_id, None, None
