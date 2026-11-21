"""Roof attachments follow roof edits, in real Chromium (owner request 2026-11-19).

Run from chauffeur/: env -u HA_BASE_URL python tests/test_twin_roof_attachments_live.py
A solar zone 2 ft in from every edge of the pool roof's x1 slope; a real drag of
the roof's back (y1) edge handle 3 ft outward resizes the zone so it stays 2 ft
from that edge while its other margins hold; Undo restores roof and zone in one
step; deleting the roof from its card removes the zone with it.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import house_editor_model_harness as H
import test_house_editor_model_live_t14 as T

check = H.check


def _face(building, zone):
    from services import twin_solar
    faces = [f for f in twin_solar.faces(building) if f['roof'] == zone['roof']
             and all(abs(a - b) < 1e-6 for a, b in zip(f['plane'], zone['plane']))]
    check(faces, ('the zone still has its roof plane', zone))
    return max(faces, key=lambda f: abs(twin_solar.area(f['polygon'])))


def _margins(building, zone):
    poly = _face(building, zone)['polygon']
    r = zone['rect']
    return [r[0] - min(p[0] for p in poly), r[1] - min(p[1] for p in poly),
            max(p[0] for p in poly) - r[2], max(p[1] for p in poly) - r[3]]


def _zones(model):
    return [z for z in H.building(model, T.POOL).get('solar_zones') or [] if z.get('roof') == T.POOL_ROOF]


def scenario_drag_roof_edge_zone_follows_undo_and_delete():
    s = T._fresh()
    if s is None:
        return
    from services import twin_solar
    T._facts()
    building = H.building(H.model(), T.POOL)
    face = max((f for f in twin_solar.faces(building) if f['roof'] == T.POOL_ROOF),
               key=lambda f: abs(twin_solar.area(f['polygon'])))
    with s.browser(launch_args=H.GPU_ARGS) as page:
        H.open_editor(page, s)
        poly = face['polygon']
        rect = [min(p[0] for p in poly) + 2, min(p[1] for p in poly) + 2,
                max(p[0] for p in poly) - 2, max(p[1] for p in poly) - 2]
        T._op(page, {'op': 'add_solar_zone', 'building': T.POOL, 'roof': T.POOL_ROOF,
                     'plane': list(face['plane']), 'rect': rect})
        model = T._until(lambda m: _zones(m), 'the seeded zone is stored')
        zone = _zones(model)[0]
        before = _margins(H.building(model, T.POOL), zone)
        check(all(abs(d - 2) < 0.05 for d in before), ('seeded 2 ft in from every edge', before))
        original_rect = list(zone['rect'])
        page.reload()
        H.open_editor(page, s)
        T._exterior(page)
        T._select(page, T.POOL, 'roof', T.POOL_ROOF, T.POOL_ROOF_POINT)

        roof = T._roof(H.model(), T.POOL, T.POOL_ROOF)
        start = T._line(roof, 'y1')
        at = T._edge_handle(page, roof, 'y1')
        T._look_at_handle(page, T.POOL, at)
        T._drag(page, T.POOL, at, (at[0], at[1] + 3.0, at[2]))
        model = T._until(lambda m: T._line(T._roof(m, T.POOL, T.POOL_ROOF), 'y1') > start + 2.5,
                         'the back edge moved out with the drag (no refusal)')
        dragged = T._line(T._roof(model, T.POOL, T.POOL_ROOF), 'y1')
        zones = _zones(model)
        check(len(zones) == 1, ('the zone is still there', zones))
        after = _margins(H.building(model, T.POOL), zones[0])
        check(all(abs(d - 2) < 0.1 for d in after), ('every zone edge keeps its 2 ft margin', before, after))
        check(zones[0]['rect'] != original_rect, ('the zone resized with the roof', original_rect, zones[0]['rect']))
        print(f'  roof back edge {start:.2f} -> {dragged:.2f} ft; zone rect {original_rect} -> {zones[0]["rect"]}')

        page.click('#rail-undo')
        model = T._until(lambda m: abs(T._line(T._roof(m, T.POOL, T.POOL_ROOF), 'y1') - start) < 0.01
                         and _zones(m) and _zones(m)[0]['rect'] == original_rect,
                         'one Undo restores the roof and the zone together')

        T._select(page, T.POOL, 'roof', T.POOL_ROOF, T.POOL_ROOF_POINT)
        page.locator('#piece-card').get_by_role('button', name='Delete', exact=True).click()
        dialog = page.locator('#cc-confirm-modal')
        if dialog.is_visible():
            dialog.get_by_role('button', name='Delete', exact=True).click()
        model = T._until(lambda m: T._roof(m, T.POOL, T.POOL_ROOF) is None and not _zones(m),
                         'deleting the roof deletes its solar zone')
        check(not page.locator('#cc-alert-modal').is_visible(), 'Delete raised no error alert')
        T._no_errors(s)


SCENARIOS = [scenario_drag_roof_edge_zone_follows_undo_and_delete]

if __name__ == '__main__':
    H.run(SCENARIOS)
