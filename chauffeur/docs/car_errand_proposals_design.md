# Car Stop Proposals (C3) — propose → approve fuel stops & charge buffers

Status: **IMPLEMENTED** (v2.50.0 — `services/cars.py`, `services/chat_actions.py`,
tests in `tests/test_car_stops.py`)
Depends on: C1 entity/solver (`car_entity_design.md`), C2 telemetry (`car_telemetry_design.md`).

## 1. What changes from C2

C2 pushed "fuel is low" and (behind a default-off toggle) silently created an errand at
a fixed station. C3 turns that into a **proposal the family approves**, with the
station chosen **along the driver's actual route**, and the errand placed by the
existing min-detour errand pass. Nothing lands on the schedule without a tap.

Key recon facts this design leans on:
- The app is **pure Mapbox** (no Google Places anywhere). Route polylines are already
  cached as GeoJSON (`route_geometry`, 1-week TTL); Mapbox Search Box **category
  search** is available and already metered (`category` cap in
  `check_usage_limits_and_spikes`).
- `insert_errands_globally` already evaluates before-first-event / between-events /
  drop-off-and-run / after-last-event slots and picks **minimum detour** — so "stop on
  the way home" and "during an event instead of waiting" are existing behavior once the
  errand exists with a good station location. No new solver concept needed.
- The propose→approve chassis exists end-to-end: `chat_actions.create_action_proposal`
  → card on an Argyle chat message → approve buttons in app chat →
  `POST /api/action-proposals/{id}/act` → `_execute` → `schedule_dirty`.

## 2. New action type: `add_car_stop`

Added to `ADMIN_ACTIONS` / `ACTION_LABELS` in `chat_actions.py`. Payload:

```json
{ "car_id", "kind": "fuel" | "charge_buffer", "title", "location",
  "station_name", "duration_mins", "target_date", "allowed_drivers": [] }
```

`_execute('add_car_stop', payload)` builds an `Errand` (priority 1, `starts_on` =
target_date, `window_days` = 1, tags `['auto_car_fuel', car_id]` — same tags C2 used,
so the existing "active errand already exists" dedupe keeps working) and
`storage.add_errand`s it. The errand pass then places it min-detour on the next
refresh. Approval requires parent/adult (`requires_admin`), same as every other card.

## 3. Along-route station selection (fuel only)

`maps.search_category(category, ...)` — new wrapper over Mapbox Search Box
`/category/{name}` with the existing key resolution and
`check_usage_limits_and_spikes('category', 1)` metering. It supports **true
search-along-route** (spotted by the user in the Search Box docs): pass GeoJSON route
coords and it sends `sar_type=isochrone` + a polyline-encoded `route` +
`time_deviation` (max detour minutes) — Mapbox constrains and ranks results by actual
detour, returns full features with coordinates, and needs no session token.

`cars.pick_station(origin, dest)`:
1. `maps.get_route_geometry(origin, dest)` → cached GeoJSON LineString (1-week TTL).
2. **Primary**: category SAR (`gas_station`, `time_deviation=8`, limit 10) over that
   polyline; take the top result.
3. Fallback when SAR returns nothing: one proximity category search at the polyline
   midpoint, ranked by minimum haversine distance to the polyline vertices.
4. Then: `car_fuel_station` setting → category search near the origin → None
   (proposal still goes out, worded "find a station on the way").

Corridor choice: **same-day** proposals use last-remaining-event → home; **tomorrow**
proposals use home → first event. One category call per proposal, and proposals are
capped at one per car per target day — quota impact is negligible.

## 4. Charge buffers (EV) — reserve time, don't pick chargers

The car's nav knows its plug, charge curve, and preconditioning; we don't compete.
A `charge_buffer` proposal reserves **time**, not a place: the errand's location is the
car's first upcoming event location (detour ≈ 0, so the pass slots it adjacent to
where the driver already is), duration `car_charge_buffer_mins` (default 25), titled
"🔌 Charging time for {car} — car picks the charger". If ChargeFinder (or similar)
lands later, `pick_station` grows an EV branch and the location gets real; the
proposal/approve flow doesn't change.

## 5. Triggers & delivery

The C2 30-minute sweep (`cars.run_sweep`) now **proposes instead of auto-adding**:

- Low fuel/battery + drives in the next 24h → create `add_car_stop` proposal, post ONE
  card to the **family channel** (K3-mirror precedent: family-visible, parents
  approve; `_post_chat_message` fan-out pushes it to phones). The C2 push text is
  replaced by the card message.
- **Dedupe key change**: `car_ready:{car}:{date}` → `car_ready:{car}:{date of the
  car's first upcoming drive}`. This is what makes the evening run propose *for
  tomorrow* ("still low after today's drives") as a separate event from the morning's
  same-day proposal, with no new scheduler hook needed.
- `car_auto_errand` (existing setting, default off) now means **auto-approve**: skip
  the card, create the errand directly (C2 behavior preserved for those who opted in).
- Away warnings unchanged (plain push).
- The evening **tomorrow digest** gains an informational fuel line per affected driver
  ("⛽ Minivan at 15% — fuel stop proposed") in `build_drive_digests`, so the digest
  and the `get_drive_digest` agent tool stay consistent; the actionable card comes
  from the sweep.

## 6. Admin dashboard

New `GET /api/action-proposals?status=proposed` (storage gains
`get_action_proposals(status)`) and a dismissible banner atop the dashboard listing
pending car-stop proposals with Approve/Dismiss buttons hitting the same
`/act` endpoint. First pending-approvals UI in the dashboard — deliberately minimal.

## 7. Out of scope

EV station picking (revisit with ChargeFinder), mileage-based fuel projection ("will
be low after today's drives" is threshold-now, not predicted), multi-stop planning,
proposal TTL/expiry (matches existing proposals; rows keep terminal status).

## 8. Tests (`tests/test_car_stops.py`)

Stubbed `ha_api` + `maps`: proposal created once per car per target day (dedupe key
uses first-drive date); approve executes → errand exists with tags/window/drivers;
dismiss executes nothing; auto-approve setting bypasses the card; station ranking
prefers on-polyline candidates; charge buffer uses first-event location and never
calls station search; digest fuel line renders; C2 away-push behavior unchanged.
