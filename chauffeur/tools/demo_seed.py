"""Invented demo household and shared synthetic gutter geometry. No import-time I/O."""
import copy
import datetime as dt
from datetime import timedelta
from zoneinfo import ZoneInfo

from tools.demo_isolation import DEMO_TIMEZONE, fresh_data_folder

NAMES = ('Avery', 'Jordan', 'Pip', 'Milo')
PANEL_NAME = 'Moonkite demo panel'
# Explicit reviewed vocabulary, independent of the data collector below.
INVENTED_TEXT = frozenset((
    'Avery', 'Jordan', 'Pip', 'Milo', 'Avery demo calendar', 'Jordan demo calendar',
    'Pip demo calendar', 'Milo demo calendar', 'Demo home', 'Comet wagon', 'Cloudbug mini',
    'Moonkite team practice', 'Cloud orchestra', 'Paper comet workshop', 'Pretend Meadow',
    'Imaginary music loft', 'Make-believe craft studio', 'Moonbeam lantern',
    'Cloud room temperature', 'Cloud room', 'Demo ground', 'Demo cottage', 'Demo hip wing', 'Garden awning',
    'Ground', 'Living', 'Storage', 'Return moonkite books', 'Collect craft paper',
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


def demo_plan():
    """Extend the gutter regression fixture with an actual hip-roofed wing."""
    plan = synthetic_plan()
    wing = plan['buildings'][1]
    wing['name'] = 'Demo hip wing'
    # Keep the live fixture's deliberately jammed roofs out of the demo.
    wing['roof']['sections'] = wing['roof']['sections'][:1]
    wing['roofs'] = wing['roofs'][:1]
    section = wing['roof']['sections'][0]
    section['kind'] = 'hip'
    section['gutters'] = dict.fromkeys(('y0', 'x1', 'y1', 'x0'), True)
    for edge in wing['roofs'][0]['edges']:
        edge.update(setting='sloped', gutter=True)
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

