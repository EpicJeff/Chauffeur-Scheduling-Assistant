"""The shared persistence path for server-side trip itinerary scheduling."""
from models.schemas import TripMetadata
from services import storage


def iter_bulk(event_id, poi_ids):
    """Yield scheduler results, saving progress on completion or cancellation."""
    meta = storage.get_trip_metadata(event_id)
    if not meta:
        raise LookupError('Trip not found')
    trip_obj = TripMetadata(**meta)
    from services.trip_scheduler import schedule_pois_bulk

    import time as _time
    last_save = 0.0
    dirty = False

    def _sync_meta():
        meta['pois'] = [p.model_dump() if hasattr(p, 'model_dump') else p.dict() for p in trip_obj.pois]
        if not event_id.startswith("draft_trip_"):
            if "activities" not in meta:
                meta["activities"] = []
            trip_cals = trip_obj.calendar_ids if hasattr(trip_obj, 'calendar_ids') and trip_obj.calendar_ids else []
            if not trip_cals:
                trip_cals = [event_id.split("::", 1)[0] if "::" in event_id else "primary"]
            for poi in trip_obj.pois:
                if poi.event_id and poi.is_scheduled:
                    if not poi.event_id.startswith("draft_poi_") and not poi.event_id.startswith("draft_acc_"):
                        full_id = f"{trip_cals[0]}::{poi.event_id}"
                        if full_id not in meta["activities"]:
                            meta["activities"].append(full_id)

    try:
        for result in schedule_pois_bulk(trip_obj, poi_ids):
            if result.get("success"):
                dirty = True
                # TinyDB rewrites the whole file per save (~hundreds of ms on a
                # big trip) — throttle to 1/s; the finally below saves the rest.
                now = _time.monotonic()
                if now - last_save >= 1.0:
                    _sync_meta()
                    storage.set_trip_metadata(event_id, meta)
                    last_save = now
                    dirty = False
            yield result
    finally:
        # Persist everything on completion AND on client cancel (GeneratorExit)
        if dirty:
            _sync_meta()
            storage.set_trip_metadata(event_id, meta)


def run_bulk(event_id, poi_ids=None):
    """Schedule the selected (or all unscheduled) POIs and collect outcomes."""
    meta = storage.get_trip_metadata(event_id)
    if not meta:
        raise LookupError('Trip not found')
    if poi_ids is None:
        poi_ids = [p['id'] for p in meta.get('pois', []) if not p.get('is_scheduled')]
    else:
        poi_ids = list(poi_ids)

    scheduled = []
    unplaced = []
    completed = set()
    try:
        for result in iter_bulk(event_id, poi_ids):
            poi_id = result.get('poi_id')
            if not poi_id:
                continue
            completed.add(poi_id)
            if result.get('success'):
                scheduled.append(poi_id)
            else:
                unplaced.append({'poi_id': poi_id,
                                 'reason': result.get('reason') or 'could not fit'})
    except Exception as exc:
        for poi_id in poi_ids:
            if poi_id not in completed:
                unplaced.append({'poi_id': poi_id, 'reason': str(exc)})
                completed.add(poi_id)
    return {'scheduled': scheduled, 'unplaced': unplaced}
