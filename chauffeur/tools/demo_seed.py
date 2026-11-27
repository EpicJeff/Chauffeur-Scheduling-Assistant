"""Invented demo household and shared synthetic gutter geometry. No import-time I/O."""
import copy
import datetime as dt
from datetime import timedelta
import json
import math
import struct
from zoneinfo import ZoneInfo

from tools.demo_isolation import DEMO_TIMEZONE, fresh_data_folder

NAMES = ('Avery', 'Jordan', 'Pip', 'Milo')
PANEL_NAME = 'Moonkite demo panel'
DEMO_LAMP_ENTITY = 'light.demo_floor_lamp'
DEMO_LAMP_FIXTURE_ID = 'fixture:3c5a6c72-9b4a-4e2d-8f12-71c0a9d4e801'
# Explicit reviewed vocabulary, independent of the data collector below.
INVENTED_TEXT = frozenset((
    'Avery', 'Jordan', 'Pip', 'Milo', 'Avery demo calendar', 'Jordan demo calendar',
    'Pip demo calendar', 'Milo demo calendar', 'Demo home', 'Comet wagon', 'Cloudbug mini',
    'Moonkite team practice', 'Cloud orchestra', 'Paper comet workshop', 'Pretend Meadow',
    'Imaginary music loft', 'Make-believe craft studio', 'Moonbeam lantern', 'Starlight floor lamp',
    'Cloud room temperature', 'Cloud room', 'Demo ground', 'Demo cottage', 'Demo hip wing', 'Garden awning',
    'Demo sofa', 'Demo coffee table', 'Demo armchair', 'Demo floor lamp', 'Demo garden bench', 'Demo teak',
    'Seat', 'Frame', 'Cushion', 'Glass',
    'Ground', 'Living', 'Storage', 'Demo patio', 'Return moonkite books', 'Collect craft paper',
    'Pick up starfruit', 'Pretend market', 'Demo pantry', 'Oat clouds', 'Starfruit',
    'Rainbow pasta', 'Paper napkins', 'Water the moonflowers', 'Sort the craft shelf', 'Moonkite demo panel'))


def visible_strings(value):
    """Collect authored human-facing labels, excluding ids, dates and enums."""
    result = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key in ('name', 'title', 'summary', 'location', 'home_location', 'label', 'friendly_name', 'panel_name'):
                if isinstance(child, str) and child:
                    result.add(child)
            result.update(visible_strings(child))
    elif isinstance(value, (list, tuple)):
        for child in value:
            result.update(visible_strings(child))
    return result


def demo_morning(instant=None):
    instant = instant or dt.datetime.now(ZoneInfo(DEMO_TIMEZONE))
    return instant.astimezone(ZoneInfo(DEMO_TIMEZONE)).replace(hour=8, minute=12, second=0, microsecond=0)


def household(today=None):
    """Pure data, relative to today. No credentials, addresses or security entities."""
    today = today or demo_morning().date()
    colors = ['#287a72', '#cf7c44', '#8b6ac8', '#397fb0']
    members = [dict(id=name.lower(), name=name, role='parent' if i < 2 else 'child',
                    color_code=colors[i], **({'driver_id': 'd' + str(i)} if i < 2 else
                    {'passenger_id': 'p' + str(i), 'stage_override': 'navigator'}))
               for i, name in enumerate(NAMES)]
    drivers = [dict(id='d' + str(i), name=NAMES[i], home_location='Demo home', color_code=colors[i])
               for i in range(2)]
    passengers = [dict(id='p' + str(i), name=NAMES[i], calendar_ids=['demo-' + str(i)])
                  for i in (2, 3)]
    cars = [dict(id='car' + str(i), name=name, seats=5, is_disabled=False)
            for i, name in enumerate(('Comet wagon', 'Cloudbug mini'))]
    calendars = {'demo-' + str(i): dict(summary=name + ' demo calendar', backgroundColor=colors[i])
                 for i, name in enumerate(NAMES)}
    events, assignments, car_assignments = [], {}, {}
    initial, final = {'d0': {}, 'd1': {}}, {'d0': {}, 'd1': {}}
    for offset in range(7):
        day = (today + timedelta(days=offset)).isoformat()
        for i, (title, place, hour) in enumerate([
                ('Moonkite team practice', 'Pretend Meadow', 9),
                ('Cloud orchestra', 'Imaginary music loft', 14),
                ('Paper comet workshop', 'Make-believe craft studio', 17)]):
            eid, did = f'demo-{offset}-{i}', 'd' + str(i % 2)
            events.append(dict(id=eid, title=title, start=f'{day}T{hour:02d}:00:00',
                               end=f'{day}T{hour + 1:02d}:00:00', location=place,
                               calendar_ids=['demo-' + str(2 + i % 2)], event_type='activity',
                               all_day=False, passengers=['p' + str(2 + i % 2)]))
            assignments[eid] = did
            car_assignments[eid] = 'car' + str(i % 2)
            initial[did][eid] = dict(travel_mins=12, buffer_before_mins=5)
            final[did][eid] = dict(travel_mins=12)
    schedule = dict(events=events, assignments=assignments, car_assignments=car_assignments,
                    calendar_metadata=calendars, home_location='Demo home', drivers=drivers,
                    passengers=passengers, cars=cars, initial_edges=initial, final_edges=final,
                    route_edges={}, unassigned=[], true_unassigned=[], conflicts=[],
                    scheduled_errands=[], completed_drives=[], in_progress_drives=[],
                    passenger_calendar_ids=['demo-2', 'demo-3'])
    devices = [
        dict(id='demo-lantern', name='Moonbeam lantern', area_id='demo-living',
             entities=[('light.demo_moonbeam', 'on', dict(brightness=190,
                       supported_color_modes=['brightness'], color_mode='brightness'))]),
        dict(id='demo-floor-lamp', name='Starlight floor lamp', area_id='demo-living',
             entities=[(DEMO_LAMP_ENTITY, 'on', dict(brightness=255, color_temp_kelvin=2700,
                       supported_color_modes=['color_temp'], color_mode='color_temp'))]),
        dict(id='demo-temperature', name='Cloud room temperature', area_id='demo-living',
             entities=[('sensor.demo_cloud_temperature', '21',
                        dict(unit_of_measurement='°C', device_class='temperature'))]),
    ]
    errands = [dict(id=f'demo-errand-{i}', title=title, duration_mins=10, location='Pretend market')
               for i, title in enumerate(('Return moonkite books', 'Collect craft paper', 'Pick up starfruit'))]
    shopping = dict(id='demo-shopping', name='Demo pantry', is_default=True)
    items = [dict(id=f'demo-item-{i}', list_id=shopping['id'], name=title)
             for i, title in enumerate(('Oat clouds', 'Starfruit', 'Rainbow pasta', 'Paper napkins'))]
    chores, routines = [], []
    for i, (title, member) in enumerate((('Water the moonflowers', 'pip'), ('Sort the craft shelf', 'milo'))):
        chores.append(dict(id=f'demo-chore-{i}', title=title, recurrence='daily',
                           state='claimed', claimed_by=member, points=10))
        routines.append(dict(id=f'demo-routine-{i}', member_id=member, title=title, time_of_day='18:00'))
    return dict(members=members, drivers=drivers, passengers=passengers, cars=cars,
                calendars=calendars, schedule=schedule, devices=devices, errands=errands,
                shopping=shopping, items=items, chores=chores, routines=routines,
                areas=[dict(area_id='demo-living', name='Cloud room', floor_id='demo-ground')],
                floors=[dict(floor_id='demo-ground', name='Demo ground', level=0)], panel_name=PANEL_NAME)


def demo_plan(gutters_on=True):
    """Extend the gutter regression fixture with an actual hip-roofed wing."""
    plan = synthetic_plan(gutters_on=gutters_on)
    wing = plan['buildings'][1]
    wing['name'] = 'Demo hip wing'
    # Keep the live fixture's deliberately jammed roofs out of the demo.
    wing['roof']['sections'] = wing['roof']['sections'][:1]
    wing['roofs'] = wing['roofs'][:1]
    section = wing['roof']['sections'][0]
    section['kind'] = 'hip'
    if gutters_on:
        section['gutters'] = dict.fromkeys(('y0', 'x1', 'y1', 'x0'), True)
    else:
        section.pop('gutters', None)
    for edge in wing['roofs'][0]['edges']:
        if gutters_on:
            edge.update(setting='sloped', gutter=True)
        else:
            edge.update(setting='sloped')
            edge.pop('gutter', None)
    main = plan['buildings'][0]
    main['name'] = 'Demo cottage'
    main['rooms'][0]['ha_area'] = 'demo-living'
    return plan


def seed(today=None):
    """Load only invented data into the caller's already-isolated service store."""
    directory = fresh_data_folder()  # MUST precede every service import/write
    import sys
    from pathlib import Path
    existing = sys.modules.get('services.storage')
    if existing is not None and not Path(existing.DB_PATH).resolve().is_relative_to(directory):
        raise RuntimeError('demo storage was imported outside this run')
    harnesses = str(Path(__file__).resolve().parents[1] / 'tests')
    if harnesses not in sys.path:
        sys.path.insert(0, harnesses)
    from models.schemas import Car, Chore, Errand, RoutineItem, ShoppingItem, ShoppingList
    from services import storage, twin_store, twin_library
    from house_ha_fake import FakeHA
    import test_twin_view_live as assets

    from tools.demo_isolation import assert_household
    # A previously imported storage module must not point at another store.
    if not Path(storage.DB_PATH).resolve().is_relative_to(directory):
        raise RuntimeError('demo storage was imported outside this run')
    today = today or demo_morning().date()
    data = household(today)
    data['data_dir'] = str(directory)
    plan = demo_plan()
    if not visible_strings(dict(data, plan=plan)) <= INVENTED_TEXT:
        raise RuntimeError('demo seed text is outside the invented vocabulary')
    storage.patch_settings(dict(auth_enforce=True, timezone=DEMO_TIMEZONE,
        home_location='Demo home', calendar_metadata=data['calendars'],
        panel_house_home=False, panel_screensaver_enabled=False,
        panel_allow_unsafe_controls=False, house_twin_glance=['drives', 'chores', 'lists'],
        panel_widgets=['drives', 'calendar', 'chores', 'routines', 'lists', 'errands']))
    # Member records must precede driver/passenger records (ensure_members).
    for member in data['members']:
        storage.add_member(member)
    for driver in data['drivers']:
        storage.add_driver(driver)
    for passenger in data['passengers']:
        storage.add_passenger(passenger)
    for car in data['cars']:
        storage.add_car(Car(**car).model_dump())
    for errand in data['errands']:
        storage.add_errand(Errand(**errand).model_dump())
    shopping = ShoppingList(**data['shopping'])
    storage.add_shopping_list(shopping.model_dump())
    for item in data['items']:
        storage.add_shopping_item(ShoppingItem(**item).model_dump())
    for chore in data['chores']:
        storage.add_chore(Chore(**chore).model_dump())
    for routine in data['routines']:
        storage.add_routine(RoutineItem(**routine).model_dump())
    # Cache after errands, whose writes invalidate schedules. Every day is
    # available to real endpoint builders without invoking a solver or feed.
    schedule = data['schedule']
    storage.set_cached_schedule(schedule)
    for offset in range(-7, 15):
        day = (today + timedelta(days=offset)).isoformat()
        daily = copy.deepcopy(schedule)
        daily['events'] = [e for e in schedule['events'] if e['start'].startswith(day)]
        storage.save_cached_daily_schedule(day, daily, 'demo')
    twin_library._urlopen = assets._stub_urlopen
    twin_store.push_round(plan, 'build')
    fake = FakeHA(areas=data['areas'], floors=data['floors'],
                  devices=data['devices']).install()
    from services import ha_api, calendar, maps, twin_site
    # Even an unanticipated HA endpoint cannot fall through to a real host.
    ha_api._request = lambda *a, **kw: None
    ha_api.states_unreachable = lambda: False
    ha_api.get_weather_forecast = lambda *a, **kw: []
    # No credential discovery, even if a secondary page asks for calendars.
    calendar.get_calendar_service = lambda: None
    # Board builders may ask for coordinates even without a map tile. Invented
    # labels are deliberately not sent to a geocoder or neighbourhood service.
    maps.geocode_address = lambda *a, **kw: None
    twin_site.start_bearing_job = lambda: None
    # Keep the fictional solar site metadata. Cached shadows come from the
    # US-local page-load morning; that round-4 lighting was visually approved.
    site = twin_site.site
    twin_site.site = lambda: dict(site(), lat=40, lon=0, source='demo', timezone='Etc/UTC')
    assert_household(storage, directory)
    return data, fake


def synthetic_plan(gutters_on=True):
    """A synthetic gable+porch house with a hip wing so corners, mitres and downspouts show clearly."""
    poly = [[0, 0], [36, 0], [36, 22], [0, 22]]
    walls = [
        {'id': f'w{i}', 'from': poly[i], 'to': poly[(i + 1) % 4],
         'exterior': True, 'height': 10, 'thickness': 0.5, 'level': 'L1'}
        for i in range(4)
    ]
    edges = [
        {'setting': 'sloped', 'pitch': 6, **({'gutter': True} if gutters_on else {})},
        {'setting': 'gable', 'pitch': 6},
        {'setting': 'sloped', 'pitch': 6, **({'gutter': True} if gutters_on else {})},
        {'setting': 'gable', 'pitch': 6},
    ]
    section = {
        'id': 'r1', 'roof': 'r1', 'kind': 'gable', 'ridge': 'x', 'pitch': 6,
        'plate': 10, 'overhang': 1.25, 'level': 'L1', 'rect': [0, 0, 36, 22],
        'plane_edges': {'y0': 0, 'x1': 1, 'y1': 2, 'x0': 3},
        **({'gutters': {'y0': True, 'y1': True}} if gutters_on else {}),
    }
    porch_section = {
        'id': 'r2', 'roof': 'r2', 'kind': 'shed', 'low_side': 'y0', 'pitch': 3,
        'plate': 8.5, 'overhang': 1, 'level': 'L1', 'rect': [6, -8, 22, 0],
        'plane_edges': {'y0': 0, 'x1': 1, 'y1': 2, 'x0': 3},
    }
    porch_roof = {
        'id': 'r2', 'area': [[6, -8], [22, -8], [22, 0], [6, 0]], 'overhang': 1,
        'edges': [
            {'setting': 'sloped', 'pitch': 3},
            {'setting': 'gable', 'pitch': 3},
            {'setting': 'gable', 'pitch': 3},
            {'setting': 'gable', 'pitch': 3},
        ],
    }
    awning_section = dict(id='demo-awning', roof='demo-awning', name='Garden awning',
                          kind='shed', low_side='y1', pitch=2, plate=8.5, overhang=.4,
                          level='L1', rect=[8, 22, 24, 27], fascia=False, thickness_ft=.3,
                          support=dict(kind='brace', style='arched', count=3, inset_ft=.6, size_ft=.3),
                          ends={'1':'closed','3':'closed'}, underside=dict(kind='flat',drop_ft=.8),
                          host=dict(wall='w2', edge=0))
    awning_roof = {**awning_section, 'area': [[8,22],[24,22],[24,27],[8,27]],
                   'edges': [dict(setting=s, pitch=2) for s in ('gable','gable','sloped','gable')]}
    awning_roof.pop('rect'); awning_roof.pop('roof')
    building = {
        'id': 'synth-house', 'name': 'Main House', 'position': [0, 0], 'base': 0, 'rotation': 0,
        'levels': [{'id': 'L1', 'name': 'Ground', 'elevation': 0, 'ceiling': 10, 'outline': poly}],
        'rooms': [{'id': 'rm1', 'name': 'Living', 'level': 'L1', 'polygon': poly}],
        'walls': walls,
        'openings': [
            {'id': 'door1', 'wall': 'w0', 'at': 14, 'width': 3.5, 'sill': 0, 'head': 7, 'kind': 'door'},
            {'id': 'win1', 'wall': 'w0', 'at': 27, 'width': 4, 'sill': 3, 'head': 7, 'kind': 'window'},
        ],
        'porches': [{
            'id': 'front-porch', 'name': 'Demo patio', 'level': 'L1', 'polygon': [[6, -8], [22, -8], [22, 0], [6, 0]],
            'floor': 0.5, 'columns': [{'at': [6.5, -7.5], 'size': 0.5}, {'at': [21.5, -7.5], 'size': 0.5}],
            **({'gutter': True} if gutters_on else {}),
        }],
        'roof': {'sections': [section, porch_section, awning_section], 'extensions': []},
        'roofs': [{'id': 'r1', 'area': poly, 'overhang': 1.25, 'edges': edges}, porch_roof, awning_roof],
    }
    shed_poly = [[0, 0], [14, 0], [14, 12], [0, 12]]
    shed_walls = [
        {'id': f'sw{i}', 'from': shed_poly[i], 'to': shed_poly[(i + 1) % 4],
         'exterior': True, 'height': 9, 'thickness': 0.5, 'level': 'L1'}
        for i in range(4)
    ]
    shed_section = {
        'id': 'sr1', 'roof': 'sr1', 'kind': 'gable', 'ridge': 'x', 'pitch': 5,
        'plate': 9, 'overhang': 1, 'level': 'L1', 'rect': [0, 0, 14, 12],
        'plane_edges': {'y0': 0, 'x1': 1, 'y1': 2, 'x0': 3},
        **({'gutters': {'y0': True, 'y1': True}} if gutters_on else {}),
    }
    shed_roof = {
        'id': 'sr1', 'area': shed_poly, 'overhang': 1,
        'edges': [
            {'setting': 'sloped', 'pitch': 5, **({'gutter': True} if gutters_on else {})},
            {'setting': 'gable', 'pitch': 5},
            {'setting': 'sloped', 'pitch': 5, **({'gutter': True} if gutters_on else {})},
            {'setting': 'gable', 'pitch': 5},
        ],
    }
    # Side carport flat roof + jammed upper shed eave right above it (0.96 in gap) so the live fixture includes an outlet-blocked spill.
    carport_section = {
        'id': 'sr_low', 'roof': 'sr_low', 'kind': 'flat', 'ridge': 'x', 'pitch': 0,
        'plate': 8.32, 'overhang': 0, 'level': 'L1', 'rect': [14, 0, 21, 12],
        'plane_edges': {'y0': 0, 'x1': 1, 'y1': 2, 'x0': 3},
    }
    carport_roof = {
        'id': 'sr_low', 'area': [[14, 0], [21, 0], [21, 12], [14, 12]], 'overhang': 0,
        'edges': [{'setting': 'gable', 'pitch': 0} for _ in range(4)],
    }
    jammed_section = {
        'id': 'sr_jam', 'roof': 'sr_jam', 'kind': 'shed', 'low_side': 'x1', 'pitch': 4,
        'plate': 9.15, 'overhang': 1, 'level': 'L1', 'rect': [14, 2, 16, 10],
        'plane_edges': {'y0': 0, 'x1': 1, 'y1': 2, 'x0': 3},
        **({'gutters': {'x1': True}} if gutters_on else {}),
    }
    jammed_roof = {
        'id': 'sr_jam', 'area': [[14, 2], [16, 2], [16, 10], [14, 10]], 'overhang': 1,
        'edges': [
            {'setting': 'gable', 'pitch': 4},
            {'setting': 'sloped', 'pitch': 4, **({'gutter': True} if gutters_on else {})},
            {'setting': 'gable', 'pitch': 4},
            {'setting': 'gable', 'pitch': 4},
        ],
    }
    shed = {
        'id': 'garden-shed', 'name': 'Garden Shed', 'position': [42, 4], 'base': 0, 'rotation': 0,
        'levels': [{'id': 'L1', 'name': 'Ground', 'elevation': 0, 'ceiling': 9, 'outline': shed_poly}],
        'rooms': [{'id': 'srm1', 'name': 'Storage', 'level': 'L1', 'polygon': shed_poly}],
        'walls': shed_walls,
        'openings': [{'id': 'sdoor', 'wall': 'sw0', 'at': 7, 'width': 3, 'sill': 0, 'head': 7, 'kind': 'door'}],
        'porches': [],
        'roof': {'sections': [shed_section, carport_section, jammed_section], 'extensions': []},
        'roofs': [shed_roof, carport_roof, jammed_roof],
    }
    return {
        'units': 'ft',
        'buildings': [building, shed],
        'site': {
            'lot': [[-25, -30], [75, -30], [75, 45], [-25, 45]],
            'hardscape': [
                {'id': 'walk1', 'kind': 'walkway', 'polygon': [[12, -25], [16, -25], [16, -8], [12, -8]]},
            ],
            'beds': [
                {'id': 'bed1', 'polygon': [[-3, -4], [5, -4], [5, 0], [-3, 0]], 'elevation': 0},
                {'id': 'bed2', 'polygon': [[31, -4], [39, -4], [39, 0], [31, 0]], 'elevation': 0},
            ],
        },
    }



# Shared outlet framing from the gutter live acceptance (scene metres).
GUTTER_OUTLET_CAMERA = """async (wide = false) => {
              const v = window.__twin;
              v.levels.go({ level: 'house' }, { immediate: true });
              if (v.precipitation?.group) v.precipitation.group.visible = false;
              v.controls.minDistance = 0.2;
              v.controls.maxPolarAngle = Math.PI * 0.85;
              let spout;
              if (wide) {
                // Rain meshes are allocated lazily and are absent on dry days.
                // Read the renderer's shared static placement; never run a
                // second placement pass just to choose a camera.
                const {cachedGutterPlacement} = await import(new URL(
                  (window.chfBase || '') + 'static/twin/gutters.js', location.href).href);
                const placement = cachedGutterPlacement(v.plan);
                spout = placement?.spouts.find(s => s.run.startsWith('synth-house:')
                  && s.mount === 'wall' && s.top[0] > 9 && s.top[2] > -2);
                if (!spout || !placement.runs.some(r => r.id === spout.run))
                  throw new Error('no rendered synthetic cottage gutter/downspout to frame');
                window.__demoGutterFrame = {spout:spout.id, run:spout.run};
              } else {
                const pours = (v.eaves.data.instances || []).filter(i => i.pour);
                spout = (pours.find(p => p.mount === 'wall' && p.top[0] > 9
                  && p.top[0] < 12 && p.top[2] > -2) || pours[0])?.spout;
              }
              if (!spout) throw new Error('no synthetic downspout to frame');
              const sTop = spout.top; // [x, y, z] at gutter bottom outlet
              const target = wide ? [sTop[0], sTop[1] * 0.52, sTop[2]]
                : [sTop[0] - 0.14, sTop[1] - 0.14, sTop[2] - 0.18];
              const pos = wide ? [target[0] + 3.4, target[1] + 1.0, target[2] + 4.2]
                : [target[0] + 1.15, target[1] - 0.30, target[2] + 1.15];
              v.setCameraState({ position: pos, target });
            }"""


def _norm3(x, y, z):
    length = math.sqrt(x * x + y * y + z * z)
    return (x / length, y / length, z / length) if length > 1e-9 else (0.0, 1.0, 0.0)


def _rotate_xyz(p, rx=0.0, ry=0.0, rz=0.0):
    x, y, z = p
    if rx:
        c, s = math.cos(rx), math.sin(rx)
        y, z = c * y - s * z, s * y + c * z
    if ry:
        c, s = math.cos(ry), math.sin(ry)
        x, z = c * x + s * z, -s * x + c * z
    if rz:
        c, s = math.cos(rz), math.sin(rz)
        x, y = c * x - s * y, s * x + c * y
    return (x, y, z)


class _MeshPart:
    def __init__(self, material_index, uvs=None):
        self.material = material_index
        self.positions = []
        self.normals = []
        self.colors = []
        self.indices = []
        self.uvs = uvs

    def add_beveled_box(self, cx, cy, cz, sx, sy, sz, bevel=0.03, steps=2, rx=0.0, ry=0.0, rz=0.0, color=(1.0, 1.0, 1.0)):
        """Watertight rounded/beveled box with outward CCW winding and smooth bevel normals."""
        hx, hy, hz = sx * 0.5, sy * 0.5, sz * 0.5
        r = max(1e-4, min(bevel, hx * 0.48, hy * 0.48, hz * 0.48))

        def axis_stops(h):
            f = min(0.95, r / h)
            ring = [f * k / steps for k in range(steps)]
            pos_side = [1.0 - f] + [1.0 - d for d in reversed(ring)]
            return [-v for v in reversed(pos_side)] + pos_side

        gx_s, gy_s, gz_s = axis_stops(hx), axis_stops(hy), axis_stops(hz)
        # 6 faces: (fixed_axis, fixed_val, u_axis, v_axis, flip_winding)
        # Ensure cross(du, dv) points outward on every face.
        faces = (
            (2, 1.0, 0, 1, False),   # +Z: u=+X, v=+Y -> +X x +Y = +Z
            (2, -1.0, 0, 1, True),   # -Z
            (0, 1.0, 2, 1, True),    # +X: u=+Z, v=+Y -> +Z x +Y = -X -> flip
            (0, -1.0, 2, 1, False),  # -X
            (1, 1.0, 0, 2, True),    # +Y: u=+X, v=+Z -> +X x +Z = -Y -> flip
            (1, -1.0, 0, 2, False),  # -Y
        )
        stops = (gx_s, gy_s, gz_s)
        extents = (hx, hy, hz)
        for fixed_a, fixed_v, ua, va, flip in faces:
            us, vs = stops[ua], stops[va]
            nu, nv = len(us), len(vs)
            base = len(self.positions)
            for j, v in enumerate(vs):
                for i, u in enumerate(us):
                    g = [0.0, 0.0, 0.0]
                    g[fixed_a] = fixed_v
                    g[ua] = u
                    g[va] = v
                    raw = [g[k] * extents[k] for k in range(3)]
                    inner = [max(-extents[k] + r, min(extents[k] - r, raw[k])) for k in range(3)]
                    delta = [raw[k] - inner[k] for k in range(3)]
                    dlen = math.sqrt(delta[0] ** 2 + delta[1] ** 2 + delta[2] ** 2)
                    if dlen > 1e-7:
                        n = (delta[0] / dlen, delta[1] / dlen, delta[2] / dlen)
                        p = (inner[0] + n[0] * r, inner[1] + n[1] * r, inner[2] + n[2] * r)
                    else:
                        n = [0.0, 0.0, 0.0]
                        n[fixed_a] = fixed_v
                        n = tuple(n)
                        p = tuple(raw)
                    pr = _rotate_xyz(p, rx, ry, rz)
                    nr = _norm3(*_rotate_xyz(n, rx, ry, rz))
                    self.positions.append((pr[0] + cx, pr[1] + cy, pr[2] + cz))
                    self.normals.append(nr)
                    self.colors.append(color)
                    if self.uvs is not None:
                        self.uvs.append(((u + 1) / 2, (v + 1) / 2))
            for j in range(nv - 1):
                for i in range(nu - 1):
                    a = base + j * nu + i
                    b = a + 1
                    c = a + nu
                    d = c + 1
                    if flip:
                        self.indices.extend((a, c, d, a, d, b))
                    else:
                        self.indices.extend((a, b, d, a, d, c))

    def add_frustum(self, x0, y0, z0, r0, x1, y1, z1, r1, segs=16, cap_bottom=True, cap_top=True, color=(1.0, 1.0, 1.0)):
        """Cylinder / tapered frustum (supports splayed legs via distinct bottom/top centres)."""
        dx, dy, dz = x1 - x0, y1 - y0, z1 - z0
        dr = r0 - r1
        slope_h = math.hypot(dy, dr) or 1.0
        ny_side = dr / slope_h
        nr_side = dy / slope_h
        base = len(self.positions)
        for i in range(segs + 1):
            ang = 2.0 * math.pi * i / segs
            ca, sa = math.cos(ang), math.sin(ang)
            n = _norm3(ca * nr_side, ny_side, sa * nr_side)
            self.positions.append((x0 + r0 * ca, y0, z0 + r0 * sa))
            self.normals.append(n)
            self.colors.append(color)
            self.positions.append((x1 + r1 * ca, y1, z1 + r1 * sa))
            self.normals.append(n)
            self.colors.append(color)
        for i in range(segs):
            b0 = base + i * 2
            t0 = b0 + 1
            b1 = b0 + 2
            t1 = b0 + 3
            self.indices.extend((b0, t0, t1, b0, t1, b1))
        if cap_bottom and r0 > 1e-5:
            cb = len(self.positions)
            self.positions.append((x0, y0, z0))
            self.normals.append((0.0, -1.0, 0.0))
            self.colors.append(color)
            for i in range(segs + 1):
                ang = 2.0 * math.pi * i / segs
                self.positions.append((x0 + r0 * math.cos(ang), y0, z0 + r0 * math.sin(ang)))
                self.normals.append((0.0, -1.0, 0.0))
                self.colors.append(color)
            for i in range(segs):
                self.indices.extend((cb, cb + 1 + i, cb + 2 + i))
        if cap_top and r1 > 1e-5:
            ct = len(self.positions)
            self.positions.append((x1, y1, z1))
            self.normals.append((0.0, 1.0, 0.0))
            self.colors.append(color)
            for i in range(segs + 1):
                ang = 2.0 * math.pi * i / segs
                self.positions.append((x1 + r1 * math.cos(ang), y1, z1 + r1 * math.sin(ang)))
                self.normals.append((0.0, 1.0, 0.0))
                self.colors.append(color)
            for i in range(segs):
                self.indices.extend((ct, ct + 2 + i, ct + 1 + i))

    def add_hollow_shade(self, cx, y0, cz, r0, y1, r1, wall=0.012, segs=24, color=(1.0, 1.0, 1.0)):
        """Open-ended tapered drum lamp shade with outer wall, inner wall, and top/bottom rims."""
        self.add_frustum(cx, y0, cz, r0, cx, y1, cz, r1, segs=segs, cap_bottom=False, cap_top=False, color=color)
        ir0, ir1 = max(0.01, r0 - wall), max(0.01, r1 - wall)
        dy = y1 - y0
        dr = ir0 - ir1
        slope_h = math.hypot(dy, dr) or 1.0
        ny_in = -dr / slope_h
        nr_in = -dy / slope_h
        base = len(self.positions)
        for i in range(segs + 1):
            ang = 2.0 * math.pi * i / segs
            ca, sa = math.cos(ang), math.sin(ang)
            n = _norm3(ca * nr_in, ny_in, sa * nr_in)
            self.positions.append((cx + ir0 * ca, y0, cz + ir0 * sa))
            self.normals.append(n)
            self.colors.append(color)
            self.positions.append((cx + ir1 * ca, y1, cz + ir1 * sa))
            self.normals.append(n)
            self.colors.append(color)
        for i in range(segs):
            b0 = base + i * 2
            t0 = b0 + 1
            b1 = b0 + 2
            t1 = b0 + 3
            self.indices.extend((b0, b1, t1, b0, t1, t0))
        for y, ro, ri, ny, flip in ((y0, r0, ir0, -1.0, False), (y1, r1, ir1, 1.0, True)):
            rb = len(self.positions)
            for i in range(segs + 1):
                ang = 2.0 * math.pi * i / segs
                ca, sa = math.cos(ang), math.sin(ang)
                self.positions.append((cx + ro * ca, y, cz + ro * sa))
                self.normals.append((0.0, ny, 0.0))
                self.colors.append(color)
                self.positions.append((cx + ri * ca, y, cz + ri * sa))
                self.normals.append((0.0, ny, 0.0))
                self.colors.append(color)
            for i in range(segs):
                a = rb + i * 2
                if flip:
                    self.indices.extend((a, a + 1, a + 3, a, a + 3, a + 2))
                else:
                    self.indices.extend((a, a + 2, a + 3, a, a + 3, a + 1))


def _pack_glb(materials, parts):
    """Pack multi-material MeshParts into a self-contained binary glTF 2.0 (.glb)."""
    blob = bytearray()
    buffer_views = []
    accessors = []
    primitives = []

    def append_bytes(data, target=None):
        while len(blob) % 4:
            blob.append(0)
        offset = len(blob)
        blob.extend(data)
        bv = {'buffer': 0, 'byteOffset': offset, 'byteLength': len(data)}
        if target is not None:
            bv['target'] = target
        idx = len(buffer_views)
        buffer_views.append(bv)
        return idx

    for part in parts:
        if not part.indices:
            continue
        pos_data = struct.pack(f'<{len(part.positions) * 3}f', *(c for p in part.positions for c in p))
        nrm_data = struct.pack(f'<{len(part.normals) * 3}f', *(c for n in part.normals for c in n))
        col_data = struct.pack(f'<{len(part.colors) * 3}f', *(c for col in part.colors for c in col))
        use_u32 = len(part.positions) > 65535
        idx_fmt = 'I' if use_u32 else 'H'
        idx_type = 5125 if use_u32 else 5123
        idx_data = struct.pack(f'<{len(part.indices)}{idx_fmt}', *part.indices)
        pos_bv = append_bytes(pos_data, 34962)
        nrm_bv = append_bytes(nrm_data, 34962)
        col_bv = append_bytes(col_data, 34962)
        idx_bv = append_bytes(idx_data, 34963)
        mins = [min(p[k] for p in part.positions) for k in range(3)]
        maxs = [max(p[k] for p in part.positions) for k in range(3)]
        pos_acc = len(accessors)
        accessors.append({'bufferView': pos_bv, 'componentType': 5126, 'count': len(part.positions),
                          'type': 'VEC3', 'min': mins, 'max': maxs})
        nrm_acc = len(accessors)
        accessors.append({'bufferView': nrm_bv, 'componentType': 5126, 'count': len(part.normals), 'type': 'VEC3'})
        col_acc = len(accessors)
        accessors.append({'bufferView': col_bv, 'componentType': 5126, 'count': len(part.colors), 'type': 'VEC3'})
        idx_acc = len(accessors)
        accessors.append({'bufferView': idx_bv, 'componentType': idx_type, 'count': len(part.indices), 'type': 'SCALAR'})
        primitives.append({'attributes': {'POSITION': pos_acc, 'NORMAL': nrm_acc, 'COLOR_0': col_acc},
                           'indices': idx_acc, 'material': part.material})
        if part.uvs is not None:
            if len(part.uvs) != len(part.positions):
                raise ValueError('Each UV part needs one UV per vertex')
            uv_data = struct.pack(f'<{len(part.uvs) * 2}f', *(c for uv in part.uvs for c in uv))
            uv_bv = append_bytes(uv_data, 34962)
            primitives[-1]['attributes']['TEXCOORD_0'] = len(accessors)
            accessors.append({'bufferView': uv_bv, 'componentType': 5126, 'count': len(part.uvs), 'type': 'VEC2'})

    while len(blob) % 4:
        blob.append(0)
    doc = {
        'asset': {'version': '2.0', 'generator': 'chauffeur-demo-seed'},
        'scene': 0,
        'scenes': [{'nodes': [0]}],
        'nodes': [{'mesh': 0}],
        'meshes': [{'primitives': primitives}],
        'materials': materials,
        'buffers': [{'byteLength': len(blob)}],
        'bufferViews': buffer_views,
        'accessors': accessors,
    }
    json_bytes = json.dumps(doc, separators=(',', ':')).encode('utf-8')
    while len(json_bytes) % 4:
        json_bytes += b' '
    total = 12 + 8 + len(json_bytes) + 8 + len(blob)
    header = struct.pack('<4sII', b'glTF', 2, total)
    json_chunk = struct.pack('<II', len(json_bytes), 0x4E4F534A) + json_bytes
    bin_chunk = struct.pack('<II', len(blob), 0x004E4942) + bytes(blob)
    return header + json_chunk + bin_chunk


def _pbr(rgb, roughness=0.75, metallic=0.0, emissive=None):
    mat = {'pbrMetallicRoughness': {'baseColorFactor': [*rgb, 1.0],
                                    'metallicFactor': metallic, 'roughnessFactor': roughness}}
    if emissive is not None:
        mat['emissiveFactor'] = list(emissive)
    return mat


def demo_sofa_glb():
    """Invented 3-seat mid-century sofa (~2.22 m wide x 0.90 m deep x 0.86 m tall, faces +Z)."""
    # One vertex-coloured PBR material keeps shader warm-up fast while preserving multi-tone cushions/pillows/legs.
    materials = [_pbr((1.0, 1.0, 1.0), roughness=0.84)]
    mesh = _MeshPart(0)
    body_col = (0.20, 0.34, 0.42)
    cushion_col = (0.27, 0.43, 0.51)
    pillow_col = (0.80, 0.60, 0.38)
    wood_col = (0.19, 0.11, 0.06)
    # 4 splayed tapered wooden legs
    for sx in (-1, 1):
        for sz in (-1, 1):
            mesh.add_frustum(sx * 0.98, 0.0, sz * 0.35, 0.020, sx * 0.93, 0.15, sz * 0.31, 0.032, segs=12, color=wood_col)
    # Lower base deck / plinth
    mesh.add_beveled_box(0.0, 0.215, 0.0, 2.18, 0.15, 0.84, bevel=0.035, steps=2, color=body_col)
    # Slightly reclined outer backrest shell
    mesh.add_beveled_box(0.0, 0.53, -0.34, 2.18, 0.56, 0.17, bevel=0.04, steps=2, rx=-0.10, color=body_col)
    # Left and right rounded track arms
    for sx in (-1, 1):
        mesh.add_beveled_box(sx * 1.00, 0.41, 0.03, 0.20, 0.44, 0.84, bevel=0.055, steps=2, color=body_col)
    # 3 distinct plump beveled seat cushions with visible seams
    for i in (-1, 0, 1):
        mesh.add_beveled_box(i * 0.605, 0.365, 0.085, 0.585, 0.17, 0.72, bevel=0.052, steps=2, color=cushion_col)
    # 3 distinct plump reclined back cushions
    for i in (-1, 0, 1):
        mesh.add_beveled_box(i * 0.605, 0.625, -0.19, 0.58, 0.42, 0.19, bevel=0.06, steps=2, rx=-0.14, color=cushion_col)
    # 2 angled accent throw pillows tucked into the corners
    mesh.add_beveled_box(-0.76, 0.57, 0.02, 0.36, 0.34, 0.13, bevel=0.05, steps=2, rx=-0.18, ry=0.52, color=pillow_col)
    mesh.add_beveled_box(0.76, 0.57, 0.02, 0.36, 0.34, 0.13, bevel=0.05, steps=2, rx=-0.18, ry=-0.52, color=pillow_col)
    return _pack_glb(materials, [mesh])


def demo_coffee_table_glb():
    """Invented beveled walnut coffee table (~1.26 m x 0.68 m x 0.45 m) with books and ceramic bowl."""
    materials = [_pbr((1.0, 1.0, 1.0), roughness=0.45)]
    mesh = _MeshPart(0)
    top_col = (0.38, 0.23, 0.13)
    leg_col = (0.24, 0.14, 0.08)
    bowl_col = (0.88, 0.83, 0.74)
    book1_col = (0.58, 0.23, 0.19)
    book2_col = (0.24, 0.36, 0.46)
    mesh.add_beveled_box(0.0, 0.425, 0.0, 1.26, 0.05, 0.68, bevel=0.018, steps=2, color=top_col)
    mesh.add_beveled_box(0.0, 0.382, 0.0, 1.06, 0.048, 0.50, bevel=0.008, steps=1, color=leg_col)
    mesh.add_beveled_box(0.0, 0.155, 0.0, 1.02, 0.028, 0.46, bevel=0.010, steps=1, color=top_col)
    for sx in (-1, 1):
        for sz in (-1, 1):
            mesh.add_frustum(sx * 0.56, 0.0, sz * 0.28, 0.018, sx * 0.48, 0.40, sz * 0.22, 0.028, segs=12, color=leg_col)
    mesh.add_beveled_box(-0.26, 0.466, 0.04, 0.28, 0.032, 0.21, bevel=0.006, steps=1, ry=0.14, color=book1_col)
    mesh.add_beveled_box(-0.24, 0.494, 0.03, 0.24, 0.026, 0.18, bevel=0.005, steps=1, ry=-0.10, color=book2_col)
    mesh.add_frustum(0.28, 0.450, -0.04, 0.065, 0.28, 0.525, -0.04, 0.115, segs=18, color=bowl_col)
    return _pack_glb(materials, [mesh])


def demo_armchair_glb():
    """Invented mid-century accent armchair (~0.84 m wide x 0.82 m deep x 0.86 m tall, faces +Z)."""
    materials = [_pbr((1.0, 1.0, 1.0), roughness=0.72)]
    mesh = _MeshPart(0)
    body_col = (0.60, 0.33, 0.19)
    cushion_col = (0.68, 0.40, 0.24)
    wood_col = (0.19, 0.11, 0.06)
    for sx in (-1, 1):
        for sz in (-1, 1):
            mesh.add_frustum(sx * 0.34, 0.0, sz * 0.32, 0.018, sx * 0.29, 0.18, sz * 0.27, 0.028, segs=12, color=wood_col)
    mesh.add_beveled_box(0.0, 0.235, 0.0, 0.80, 0.13, 0.76, bevel=0.032, steps=2, color=body_col)
    mesh.add_beveled_box(0.0, 0.54, -0.31, 0.78, 0.56, 0.14, bevel=0.038, steps=2, rx=-0.14, color=body_col)
    for sx in (-1, 1):
        mesh.add_beveled_box(sx * 0.35, 0.42, 0.02, 0.13, 0.40, 0.74, bevel=0.042, steps=2, color=body_col)
    mesh.add_beveled_box(0.0, 0.37, 0.07, 0.57, 0.16, 0.64, bevel=0.048, steps=2, color=cushion_col)
    mesh.add_beveled_box(0.0, 0.62, -0.17, 0.56, 0.40, 0.17, bevel=0.055, steps=2, rx=-0.16, color=cushion_col)
    return _pack_glb(materials, [mesh])


def demo_floor_lamp_glb():
    """Invented floor lamp with stepped brass base, slender pole, and glowing linen drum shade (~1.68 m tall)."""
    materials = [
        _pbr((0.24, 0.19, 0.13), roughness=0.35, metallic=0.65),  # 0: brushed antique bronze/brass
        _pbr((0.96, 0.90, 0.78), roughness=0.85, metallic=0.0,
             emissive=(0.75, 0.58, 0.32)),                        # 1: warm lit linen drum shade
    ]
    metal, shade = _MeshPart(0), _MeshPart(1)
    metal.add_frustum(0.0, 0.0, 0.0, 0.17, 0.0, 0.028, 0.0, 0.155, segs=24)
    metal.add_frustum(0.0, 0.028, 0.0, 0.085, 0.0, 0.052, 0.0, 0.042, segs=20)
    metal.add_frustum(0.0, 0.05, 0.0, 0.017, 0.0, 1.44, 0.0, 0.015, segs=16)
    metal.add_frustum(0.0, 1.38, 0.0, 0.032, 0.0, 1.48, 0.0, 0.026, segs=16)
    shade.add_hollow_shade(0.0, 1.28, 0.0, 0.24, 1.68, 0.18, wall=0.014, segs=28)
    return _pack_glb(materials, [metal, shade])


def demo_furniture_glbs():
    """Return invented GLB bytes for the living room furniture pieces."""
    return {
        'sofa': ('Demo sofa', 'demo_sofa.glb', demo_sofa_glb()),
        'coffee_table': ('Demo coffee table', 'demo_coffee_table.glb', demo_coffee_table_glb()),
        'armchair': ('Demo armchair', 'demo_armchair.glb', demo_armchair_glb()),
        'floor_lamp': ('Demo floor lamp', 'demo_floor_lamp.glb', demo_floor_lamp_glb()),
    }


def _garden_bench_parts():
    """Four original materials, each kept as one glTF primitive (metres, faces +Z)."""
    materials = [
        dict(_pbr((0.78, 0.78, 0.76)), name='Seat'),
        dict(_pbr((0.12, 0.20, 0.19), roughness=0.4, metallic=0.6), name='Frame'),
        dict(_pbr((0.24, 0.46, 0.52), roughness=0.9), name='Cushion'),
        dict(_pbr((0.65, 0.87, 0.91), roughness=0.15), name='Glass', alphaMode='BLEND'),
    ]
    materials[3]['pbrMetallicRoughness']['baseColorFactor'][3] = 0.35
    seat, frame, cushion, glass = parts = [_MeshPart(i, uvs=[] if i != 1 else None) for i in range(4)]
    # Slatted seat and back leave the wood override easy to see around the cushion.
    for z in (-0.22, -0.07, 0.08, 0.23):
        seat.add_beveled_box(-0.15, 0.43, z, 1.12, 0.055, 0.12, bevel=0.012)
    for y in (0.62, 0.75, 0.88):
        seat.add_beveled_box(-0.15, y, -0.28, 1.12, 0.10, 0.05, bevel=0.012)
    for x in (-0.75, 0.45):
        for z in (-0.25, 0.25):
            frame.add_beveled_box(x, 0.21, z, 0.055, 0.42, 0.055, bevel=0.009)
        frame.add_beveled_box(x, 0.64, 0, 0.065, 0.055, 0.62, bevel=0.012)
        frame.add_beveled_box(x, 0.65, -0.28, 0.055, 0.50, 0.055, bevel=0.009)
    # Small side table shares the frame material; the top is its own translucent part.
    frame.add_beveled_box(0.63, 0.27, 0.04, 0.045, 0.54, 0.045, bevel=0.008)
    cushion.add_beveled_box(-0.15, 0.50, 0.06, 0.78, 0.09, 0.39, bevel=0.03)
    glass.add_beveled_box(0.63, 0.56, 0.04, 0.29, 0.018, 0.38, bevel=0.004)
    return materials, parts


def seed_library_model():
    """Import an invented four-part model and set one model-wide material default."""
    from pathlib import Path
    import os

    data_dir = os.environ.get('CHAUFFEUR_DATA_DIR')
    if not data_dir:
        raise RuntimeError('demo model seed requires a chauffeur_demo_ folder')
    root = Path(data_dir).resolve()
    if not root.name.startswith('chauffeur_demo_') or not root.is_dir():
        raise RuntimeError('demo model seed refused non-demo folder')
    from services import storage, twin_imports, twin_materials, twin_model_records, twin_store
    if not Path(storage.DB_PATH).resolve().is_relative_to(root):
        raise RuntimeError('demo model seed refused non-demo storage')
    if not Path(twin_store.DATA_DIR).resolve().is_relative_to(root):
        raise RuntimeError('demo model seed refused non-demo twin store')

    label = 'Demo garden bench'
    materials, parts = _garden_bench_parts()
    if not {label, *(mat['name'] for mat in materials)} <= INVENTED_TEXT:
        raise RuntimeError('demo model text outside invented vocabulary')
    entry = twin_imports.create({'demo_garden_bench.glb': _pack_glb(materials, parts)}, label, 'furniture')
    # Mirrors model_levels.stampParts: one unique named material per primitive,
    # indexed triangles, authored UV presence, and BLEND is non-opaque.
    stamped = twin_model_records.update(entry['id'], {
        'parts': [dict(key=mat['name'], name=mat['name'], triangles=len(part.indices) // 3,
                       has_uv=part.uvs is not None, opaque=mat.get('alphaMode', 'OPAQUE') == 'OPAQUE')
                  for mat, part in zip(materials, parts)],
        'parts_version': 1,
    }, entry['revision'])
    teak = twin_materials.create({'name': 'Demo teak', 'params': {'tint': '#9a5b2e', 'roughness': 0.6}}, 'avery')
    twin_model_records.update(entry['id'], {
        'materials': {'Seat': {'material': teak['id'], 'texture': 'real'}},
    }, stamped['revision'])
    return entry['id']


def furnish_demo_room():
    """Import invented GLB furniture and place them + the floor lamp fixture in Demo cottage Living."""
    from pathlib import Path
    import os

    data_dir = os.environ.get('CHAUFFEUR_DATA_DIR')
    if not data_dir:
        raise RuntimeError('demo furnish requires a chauffeur_demo_ folder')
    root = Path(data_dir).resolve()
    if not root.name.startswith('chauffeur_demo_') or not root.is_dir():
        raise RuntimeError('demo furnish refused non-demo folder')
    from services import storage, twin_imports, twin_store
    if not Path(storage.DB_PATH).resolve().is_relative_to(root):
        raise RuntimeError('demo furnish refused non-demo storage')
    if not Path(twin_store.DATA_DIR).resolve().is_relative_to(root):
        raise RuntimeError('demo furnish refused non-demo twin store')

    glbs = demo_furniture_glbs()
    assets = {}
    for key, (label, filename, payload) in glbs.items():
        if label not in INVENTED_TEXT:
            raise RuntimeError(f'demo furniture label outside invented vocabulary: {label}')
        entry = twin_imports.create({filename: payload}, label, 'furniture')
        assets[key] = entry['id']

    # Demo cottage rm1 is [0..36] x [0..22] ft. Group furniture in the west-north living area:
    # - Floor lamp at (7.0, 17.5) ft with its point light fixture inside the drum shade at z=4.85 ft.
    # - Sofa at (13.0, 18.2) ft facing south (rotation=0) -> casts shadow east and onto north wall.
    # - Coffee table at (13.0, 12.6) ft -> sits in the bright lamp pool and casts a crisp table shadow SE.
    # - Armchair at (6.8, 11.4) ft facing ENE (rotation=115) -> lit on lamp-facing side, casts shadow S/SW.
    items = [
        {'id': 'demo-sofa', 'name': 'Demo sofa', 'asset': assets['sofa'], 'object_kind': 'furniture',
         'host': {'floor': 'rm1', 'u': 13.0 / 36.0, 'v': 18.2 / 22.0}, 'rotation': 0, 'scale': 1.0,
         'casts_shadow': True},
        {'id': 'demo-coffee-table', 'name': 'Demo coffee table', 'asset': assets['coffee_table'], 'object_kind': 'furniture',
         'host': {'floor': 'rm1', 'u': 13.0 / 36.0, 'v': 12.6 / 22.0}, 'rotation': 0, 'scale': 1.0,
         'casts_shadow': True},
        {'id': 'demo-armchair', 'name': 'Demo armchair', 'asset': assets['armchair'], 'object_kind': 'furniture',
         'host': {'floor': 'rm1', 'u': 6.8 / 36.0, 'v': 11.4 / 22.0}, 'rotation': 115, 'scale': 1.0,
         'casts_shadow': True},
        {'id': 'demo-floor-lamp', 'name': 'Demo floor lamp', 'asset': assets['floor_lamp'], 'object_kind': 'furniture',
         'host': {'floor': 'rm1', 'u': 7.0 / 36.0, 'v': 17.5 / 22.0}, 'rotation': 0, 'scale': 1.0,
         'casts_shadow': True},
    ]
    if not visible_strings(items) <= INVENTED_TEXT:
        raise RuntimeError('demo furniture items contain text outside invented vocabulary')

    lamp_fixture = {
        'id': DEMO_LAMP_FIXTURE_ID,
        'shape': 'point',
        'ref': 'floor',
        'building': 'synth-house',
        'level': 'L1',
        'at': [7.0, 17.5, 4.85],
    }

    def place(before):
        model = copy.deepcopy(before)
        main = next(b for b in model['buildings'] if b['id'] == 'synth-house')
        existing_ids = {item['id'] for item in items}
        main['items'] = [i for i in main.get('items', []) if i.get('id') not in existing_ids] + items
        fixtures = dict(model.get('light_fixtures') or {})
        fixtures[DEMO_LAMP_ENTITY] = [lamp_fixture]
        model['light_fixtures'] = fixtures
        meta = dict(model.get('light_fixtures_meta') or {})
        meta[DEMO_LAMP_ENTITY] = {'output_lm': 750}
        model['light_fixtures_meta'] = meta
        return model

    twin_store.update_model(place, 'edit', note='demo living room furniture and floor lamp')
    return assets


