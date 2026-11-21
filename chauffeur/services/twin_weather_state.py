"""Plausible, not exact: one bounded ground record outside the house model.

Sensor values in the public source report are normalized: rain 0..1, wind
m/s, bearing degrees clockwise from north, temperature Celsius. Raw state
and unit remain alongside them for the drawer and browser weather mapper.
"""
import math
import threading
import time
from datetime import datetime, timezone

from services import ha_api, storage, twin_site

KEY = 'house_twin_weather_state'
MAX_RECORD_AGE = 24 * 3600
SENSOR_SETTINGS = {'rain': 'weather_rain_sensor', 'wind_speed': 'weather_wind_speed_sensor',
                   'wind_direction': 'weather_wind_direction_sensor', 'temperature': 'weather_temperature_sensor'}
QUANTITIES = ('condition', 'precipitation', 'temperature', 'humidity', 'cloud_coverage',
              'wind_speed', 'wind_bearing', 'visibility')
RATES = {'rainy': .45, 'pouring': 1, 'lightning-rainy': .8, 'snowy': .5, 'snowy-rainy': .5, 'hail': .7}
CLOUDS = {'partlycloudy': .4, 'cloudy': .85, 'fog': 1, 'lightning': 1,
          **{condition: 1 for condition in RATES}}
FALLBACKS = {'condition': 'clear and calm', 'precipitation': 'condition intensity',
             'temperature': 'no snow accumulation or melting; 180-minute drying',
             'humidity': 'no humidity drying adjustment', 'cloud_coverage': 'condition cloud amount',
             'wind_speed': 'calm; gentle grass breeze', 'wind_bearing': 'no measured direction',
             'visibility': 'fog condition only'}
_lock = threading.RLock()
_forecast_cache = {}  # one entity, at most one hourly response; never a history


def number(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def sun_altitude(now, lat, lon):
    """Python port of slice 1 sky/ephemeris.js sunPosition (radians)."""
    d = now / 86400 + 2440587.5 - 2451545
    rad = math.pi / 180
    mean = rad * (357.5291 + .98560028 * d)
    center = rad * (1.9148 * math.sin(mean) + .0200 * math.sin(2 * mean) + .0003 * math.sin(3 * mean))
    longitude = mean + center + rad * (102.9372 + 180)
    obliquity = 23.4397 * rad
    ra = math.atan2(math.sin(longitude) * math.cos(obliquity), math.cos(longitude))
    dec = math.asin(math.sin(obliquity) * math.sin(longitude))
    hour = rad * (280.16 + 360.9856235 * d + lon) - ra
    phi = lat * rad
    return math.asin(max(-1, min(1, math.sin(phi) * math.sin(dec) + math.cos(phi) * math.cos(dec) * math.cos(hour))))


def valid_record(record, now):
    if not isinstance(record, dict):
        return False
    for key in ('snow_cm', 'wetness', 'updated'):
        if type(record.get(key)) not in (int, float) or number(record[key]) is None:
            return False
    return (0 <= record['snow_cm'] <= 10000 and 0 <= record['wetness'] <= 1
            and (record.get('puddle_amount') is None or type(record['puddle_amount']) in (int, float)
                 and number(record['puddle_amount']) is not None and 0 <= record['puddle_amount'] <= 1)
            and 0 <= now - record['updated'] <= MAX_RECORD_AGE
            and (record.get('last_rain') is None or type(record['last_rain']) in (int, float)
                 and number(record['last_rain']) is not None and record['last_rain'] <= now))


def _valid_forcing(value):
    if not isinstance(value, dict) or not isinstance(value.get('condition'), (str, type(None))):
        return False
    for key in ('rate', 'cloud_cover', 'sun_altitude'):
        if type(value.get(key)) not in (int, float) or number(value[key]) is None:
            return False
    return (0 <= value['rate'] <= 1 and 0 <= value['cloud_cover'] <= 1
            and all(value.get(key) is None or type(value[key]) in (int, float) and number(value[key]) is not None
                    for key in ('temperature', 'humidity')))


def advance(record, forcing, now):
    """Integrate a constant observation over simulated hours; pure test seam."""
    if not valid_record(record, now):
        record = {'snow_cm': 0., 'wetness': 0., 'updated': now, 'last_rain': None}
    hours = (now - record['updated']) / 3600
    snow, wet = record['snow_cm'], record['wetness']
    # Existing persisted records predate the duration accumulator. Retain their
    # known puddles once; every newly integrated record writes the new field.
    puddle = record.get('puddle_amount')
    if puddle is None:
        puddle = max(0., (wet - .6) / .4)
    if record.get('last_rain') is None or now - record['last_rain'] > 10800:
        puddle = 0.
    condition, rate = forcing.get('condition'), forcing.get('rate', 0)
    temperature = forcing.get('temperature')
    cover = forcing.get('cloud_cover', 0)
    sun = forcing.get('sun_altitude', -1) > 0
    growing = condition in ('snowy', 'snowy-rainy') and temperature is not None and temperature <= 1 and rate > 0
    if growing:
        snow += rate * (1 if condition == 'snowy-rainy' else 2.5) * hours
    melt = 0
    melt_hours = 0
    if temperature is not None and temperature > 0:
        melt_rate = temperature * .4 + (.8 * (1 - cover) if sun else 0)
        melt = min(snow, melt_rate * hours)
        melt_hours = melt / max(melt_rate, 1e-9)
        snow -= melt
    # Keep sub-threshold snowfall between ticks, otherwise light mix can never
    # reach .2 cm. The final melting remnant is cleared, as specified.
    if snow < .2 and not growing:
        snow = 0
    raining = condition in ('rainy', 'pouring', 'lightning-rainy', 'snowy-rainy') and rate > 0
    rain_rate = rate * (.5 if condition == 'snowy-rainy' else 1) if raining else 0.
    if raining or melt > 0:
        # Forty minutes of full rain, or eighty minutes of continuous melt.
        rise = rain_rate * 1.5 + (.75 if melt > 0 else 0.)
        if raining:
            # Only the interval above .45 counts: 18 + 42 = 60 pouring minutes.
            eligible = max(0., hours - max(0., .45 - wet) / max(rise, 1e-9))
            puddle += rain_rate * eligible / .7
        wet += rain_rate * 1.5 * hours + .75 * melt_hours
    else:
        tau = 180 - 6 * max(0, min(20, temperature if temperature is not None else 0))
        if sun:
            tau /= 2
        if (forcing.get('humidity') or 0) > 90:
            tau *= 2
        drying = math.exp(-hours * 60 / tau)
        wet *= drying
        puddle *= drying
    return {'snow_cm': min(10000, max(0, snow)), 'wetness': max(0, min(1, wet)), 'updated': now,
            'puddle_amount': max(0, min(1, puddle)),
            'last_rain': now if raining else record.get('last_rain')}


def puddles(record, now):
    recent = record.get('last_rain')
    amount = record.get('puddle_amount')
    if amount is None:
        amount = max(0., (record['wetness'] - .6) / .4)
    return min(amount, max(0., (record['wetness'] - .45) / .55)) if recent is not None and 0 <= now - recent <= 10800 else 0.


def frost_cycle(now, latitude):
    """An autumn-to-autumn year, distinct across hemispheres."""
    date = datetime.fromtimestamp(now, timezone.utc)
    south = latitude < 0
    return (date.year - (date.month < (2 if south else 8))) * 2 + int(south)


def calendar_target(now, latitude, grass_type):
    """Coarse average-frost calendar, mirrored six months in the south.

    Tropical <23.5 degrees: frost free; <35: Nov-Feb; <50: Oct-Apr;
    >=50: Sep-May. January is the northern coldest month.
    """
    month = datetime.fromtimestamp(now, timezone.utc).month
    if latitude < 0:
        month = (month + 5) % 12 + 1
    lat = abs(latitude)
    if lat < 23.5:
        return 0.
    if grass_type == 'cool':
        return .3 if month == 1 else 0.
    first, last = (11, 2) if lat < 35 else (10, 4) if lat < 50 else (9, 5)
    return float(month >= first or month <= last)


def _valid_season(record, now):
    if not isinstance(record, dict):
        return False
    updated = record.get('season_updated')
    if type(updated) not in (int, float):
        return False
    updated = number(updated)
    if updated is None or not 0 <= now - updated <= MAX_RECORD_AGE:
        return False
    for key in ('lawn_target', 'lawn_dormancy'):
        value = number(record.get(key))
        if type(record.get(key)) not in (int, float) or value is None or not 0 <= value <= 1:
            return False
    if record.get('frost_cycle') is not None and type(record['frost_cycle']) is not int:
        return False
    current = int(now // 3600)
    for key in ('temperature_hours', 'rain_hours'):
        rows = record.get(key)
        if not isinstance(rows, list) or len(rows) > 240:
            return False
        hours = []
        for row in rows:
            if key == 'temperature_hours':
                if (not isinstance(row, (list, tuple)) or len(row) != 2
                        or type(row[1]) not in (int, float) or number(row[1]) is None):
                    return False
                hour = row[0]
            else:
                hour = row
            if type(hour) is not int or hour > current:
                return False
            hours.append(hour)
        if hours != sorted(set(hours)):
            return False
    return True


def season_payload(record, grass_type, usable):
    rows = record['temperature_hours']
    history = usable and len(rows) >= 72
    return ({'dormancy': record['lawn_dormancy'], 'grass_type': grass_type,
             'source': 'history' if history else 'calendar'},
            {'avg_temp_c': sum(row[1] for row in rows) / len(rows) if history else None,
             'history_days': len(rows) / 24})


def advance_season(record, forcing, now, grass_type, latitude, usable):
    """Bounded hourly observations and a rate-limited lawn, in the ground row.

    One last observation per UTC hour (rain is any rain in that hour). Do not
    invent overnight history or fill outages. Missing/corrupt/old extensions
    start with the calendar even when the slice 3 ground fields are valid.
    """
    valid = _valid_season(record, now)
    hour = int(now // 3600)
    temps = {h: t for h, t in record['temperature_hours'] if hour - 239 <= h <= hour} if valid else {}
    rain = {h for h in record['rain_hours'] if hour - 239 <= h <= hour} if valid else set()
    temp = number(forcing.get('temperature')) if usable else None
    if temp is not None:
        temps[hour] = temp
    if usable and forcing.get('condition') in ('rainy', 'pouring', 'lightning-rainy', 'snowy-rainy') and forcing.get('rate', 0) > 0:
        rain.add(hour)
    cycle = frost_cycle(now, latitude)
    frost = record.get('frost_cycle') if valid and record.get('frost_cycle') == cycle else None
    if temp is not None and temp <= 0:
        frost = cycle
    target = calendar_target(now, latitude, grass_type)
    if usable and len(temps) >= 72:
        avg = sum(temps.values()) / len(temps)
        if grass_type == 'warm':
            # Warm grass has a green/dormant latch. A newly selected warm
            # lawn must not inherit cool grass's .3/.6 stress target.
            target = 1. if valid and record['lawn_target'] == 1 else 0.
            if avg > 18.3:
                target = 0.
            elif avg < 12.8 and frost == cycle:
                target = 1.
        else:
            target = .6 if avg >= 29.4 and len(rain) < 6 else .3 if avg < 0 else 0.
    dormancy = record['lawn_dormancy'] if valid else target
    step = (now - record['season_updated']) / (14 * 86400) if valid else 0.
    dormancy += max(-step, min(step, target - dormancy))
    return {'temperature_hours': sorted([h, t] for h, t in temps.items()), 'rain_hours': sorted(rain),
            'frost_cycle': frost, 'lawn_target': target, 'lawn_dormancy': dormancy, 'season_updated': now}


def _temperature(value, unit):
    value = number(value)
    if value is None:
        return None
    if unit in ('°F', 'F', 'fahrenheit'):
        return (value - 32) * 5 / 9
    if unit in ('K', 'kelvin'):
        return value - 273.15
    return value if unit in ('', '°C', 'C', 'celsius') else None


def _wind(value, unit):
    value = number(value)
    scale = {'': 1 / 3.6, 'km/h': 1 / 3.6, 'kph': 1 / 3.6, 'mph': .44704,
             'm/s': 1, 'kn': .514444, 'knots': .514444, 'kt': .514444, 'kts': .514444}.get(unit)
    return value * scale if value is not None and value >= 0 and scale is not None else None


def _rain(value, unit):
    if value in ('on', 'off'):
        return .5 if value == 'on' else 0.
    value = number(value)
    if value is None or value < 0 or unit not in ('', 'mm/h', 'mm/hr', 'in/h', 'in/hr'):
        return None
    if unit in ('in/h', 'in/hr'):
        value *= 25.4
    return min(1, max(.1, value / 8)) if value > 0 else 0.


def _forecast_rate(rows, now, unit):
    for row in rows if isinstance(rows, list) else []:
        try:
            start = datetime.fromisoformat(row['datetime'].replace('Z', '+00:00'))
            if start.tzinfo is None or not 0 <= now - start.timestamp() < 3600:
                continue
            mm = number(row.get('precipitation'))
            if mm is not None and mm >= 0 and unit in ('mm', 'in'):
                return max(.1, min(1, mm * (25.4 if unit == 'in' else 1) / 8))
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
            continue
    return None


def _hourly_forecast(entity, now):
    if (_forecast_cache.get('entity') != entity or not 0 <= now - _forecast_cache.get('updated', -math.inf) < 300):
        rows = ha_api.get_weather_forecast(entity, kind='hourly')
        _forecast_cache.clear()
        _forecast_cache.update(entity=entity, updated=now, rows=rows)
    return _forecast_cache.get('rows', [])


def observation(rows, settings, now, stale=False):
    by_id = {row['entity_id']: row for row in rows if isinstance(row, dict) and isinstance(row.get('entity_id'), str)}
    candidates = sorted((row for eid, row in by_id.items() if eid.startswith('weather.')),
                        key=lambda row: ((row.get('attributes') or {}).get('friendly_name') or row['entity_id']).lower())
    entity = settings.get('weather_entity') or (candidates[0]['entity_id'] if candidates else None)
    weather = by_id.get(entity) or {}
    attrs = weather.get('attributes') or {}
    condition = weather.get('state')
    usable = bool(weather) and condition not in (None, 'unknown', 'unavailable') and not stale
    values = dict.fromkeys(QUANTITIES)
    values.update(rate=0., cloud_cover=0., sun_altitude=-1.)
    sensors = {}
    missing = []
    if usable:
        values.update(condition=condition, temperature=_temperature(attrs.get('temperature'), attrs.get('temperature_unit', '')),
                      humidity=number(attrs.get('humidity')), cloud_coverage=number(attrs.get('cloud_coverage')),
                      wind_speed=_wind(attrs.get('wind_speed'), attrs.get('wind_speed_unit', '')),
                      wind_bearing=number(attrs.get('wind_bearing')), visibility=number(attrs.get('visibility')))
        # Older integrations carry forecast on the entity; modern Met.no uses
        # weather.get_forecasts. No historical/daily forecast is treated as now.
        forecast = attrs.get('forecast')
        if not isinstance(forecast, list):
            forecast = _hourly_forecast(entity, now)
        values['precipitation'] = _forecast_rate(forecast, now, attrs.get('precipitation_unit', 'mm'))
        values['rate'] = values['precipitation'] if values['precipitation'] is not None else RATES.get(condition, 0.)
    for role, key in SENSOR_SETTINGS.items():
        eid = settings.get(key) or None
        row = by_id.get(eid) or {}
        unit = (row.get('attributes') or {}).get('unit_of_measurement', '')
        raw = row.get('state')
        value = None
        if usable and row:
            value = (_rain(raw, unit) if role == 'rain' else _temperature(raw, unit) if role == 'temperature'
                     else _wind(raw, unit) if role == 'wind_speed' else number(raw))
            if role == 'wind_direction' and value is not None:
                value %= 360
        sensors[role] = {'entity': eid, 'state': raw, 'unit': unit, 'value': value}
        if eid and value is None:
            missing.append(key)
        if value is not None:
            target = {'rain': 'precipitation', 'wind_direction': 'wind_bearing'}.get(role, role)
            values[target] = value
            if role == 'rain':
                values['rate'] = value
                if value == 0:
                    values['condition'] = 'sunny' if condition in RATES else condition
                elif condition not in RATES:
                    values['condition'] = 'rainy'
    missing = [q for q in QUANTITIES if values[q] is None] + missing
    values['cloud_cover'] = (max(0, min(100, values['cloud_coverage'])) / 100
                             if values['cloud_coverage'] is not None else CLOUDS.get(condition, 0.))
    if usable:
        site = twin_site.site()
        lat, lon = number(site.get('lat')), number(site.get('lon'))
        if lat is not None and lon is not None:
            values['sun_altitude'] = sun_altitude(now, lat, lon)
    source = {'entity': entity if weather else None, 'configured_entity': settings.get('weather_entity') or '',
              'missing': missing, 'sensors': sensors,
              'stale': bool(stale or weather and not usable), 'values': values,
              'fallbacks': {q: FALLBACKS.get(q, 'weather entity quantity; local sensor unavailable') for q in missing}}
    return values, source, usable


def update(now=None):
    """Called by the add-on's event/timer job and the small read route."""
    now = time.time() if now is None else now
    with _lock:
        settings = storage.get_settings() or {}
        try:
            rows = ha_api.get_states()
            stale = ha_api.states_unreachable()
        except Exception:
            rows, stale = [], True
        forcing, source, usable = observation(rows, settings, now, stale)
        record = storage.get_app_state(KEY)
        grass_type = 'warm' if settings.get('lawn_grass_type') == 'warm' else 'cool'
        site = twin_site.site()
        latitude = number(site.get('lat'))
        unknown_latitude = site.get('source') == 'default' or latitude is None or not -90 <= latitude <= 90
        latitude = 40. if unknown_latitude else latitude
        season = advance_season(record, forcing, now, grass_type, latitude, usable)
        lawn, season_report = season_payload(season, grass_type, usable)
        source['season'] = {'latitude': latitude, 'latitude_source': 'fallback: 40 N' if unknown_latitude else 'site',
                            'lawn': 'temperature history' if lawn['source'] == 'history' else 'growing-season calendar by latitude'}
        # Integrate the observation that actually occupied the elapsed interval,
        # then latch the new one. A snow->sun event must not retroactively melt
        # the preceding hour. A new rain observation starts building next tick.
        previous = record.get('forcing') if isinstance(record, dict) else None
        if not usable or not _valid_forcing(previous):
            record = None
            previous = None
        result = advance(record, previous or forcing, now)
        if usable:
            result = advance(result, forcing, now)
        else:
            result = advance(None, forcing, now)
        stored = dict(result, forcing=forcing, **season)
        storage.set_app_state(KEY, stored)
        return {key: result[key] for key in ('snow_cm', 'wetness', 'updated')} | {
            'snow_cm': result['snow_cm'] if result['snow_cm'] >= .2 else 0.,
            'puddles': puddles(result, now), 'source': source, 'lawn': lawn, 'season': season_report}


def relevant(entity_id):
    settings = storage.get_settings() or {}
    return (entity_id.startswith('weather.') or entity_id in
            [settings.get(key) for key in SENSOR_SETTINGS.values()])


def save_sources(body):
    """Weather preferences cannot affect schedules or write the house model."""
    keys = {'weather_entity', 'lawn_grass_type', *SENSOR_SETTINGS.values()}
    if not isinstance(body, dict) or not body or not set(body) <= keys:
        raise ValueError('Choose only weather sources.')
    cleaned = {}
    for key, value in body.items():
        if key == 'lawn_grass_type':
            if value not in ('cool', 'warm'):
                raise ValueError('Choose cool-season or warm-season grass.')
            cleaned[key] = value
            continue
        if not isinstance(value, str):
            raise ValueError('Choose an entity or use the weather default.')
        value = value.strip()
        prefixes = ('weather.',) if key == 'weather_entity' else ('sensor.', 'binary_sensor.') if key == 'weather_rain_sensor' else ('sensor.',)
        if value and (len(value) > 255 or not value.startswith(prefixes) or
                      not value.partition('.')[2] or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789_.' for c in value)):
            raise ValueError('Choose a weather entity or a matching local sensor.')
        cleaned[key] = value
    storage.patch_settings(cleaned)
    return update()
