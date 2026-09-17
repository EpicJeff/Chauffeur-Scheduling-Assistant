"""Shared helpers for the four house-live test files: test_house_live.py
(boot/lifecycle/leak), test_house_shell_live.py (shell/mask/vault/clipper/
convexity/study-box), test_house_nav_live.py (navigation/orbit/swipe/idle)
and test_house_facade_live.py (facade pin/worst case/roof-line audit/
saved-facade reproduction). Split out (Task 7) so tools/test.py's parallel
sweep can spread the ~21 Chromium scenarios across workers instead of
serializing them behind one 8-minute file.

Imported only -- this module carries no runner block and is never run on
its own.
"""
import datetime
import math as _math


def check(cond, msg):
    """Raise AssertionError(msg) unless cond is truthy."""
    if not cond:
        raise AssertionError(msg)


# Reads window.__hpScene (captured only where house_probe's THREE_WRAP
# is routed in): the sharing/batching invariant shared by the boot
# scenario and the canonical-facade pin.
INVARIANT_JS = """() => {
  const S = window.__hpScene;
  if (!S) return { err: 'no scene captured' };
  // use classifies EVERY mesh (merged included) into its material's
  // zone-usage set, so a merged mesh that somehow crossed a zone
  // boundary is still caught. mats/geos/meshes stay scoped to the
  // never-merged survivors, because the ratio gates below measure how
  // much of THAT population batched — merged output would flatter the
  // ratio without reflecting new sharing.
  const use = new Map(), geos = new Set(), mats = new Set();
  let meshes = 0;
  S.traverse(o => {
    if (!o.isMesh || !o.material || Array.isArray(o.material)) return;
    let z = '';
    for (let p = o; p; p = p.parent)
      if (p.userData && p.userData.zone) { z = p.userData.zone; break; }
    if (!use.has(o.material.uuid)) use.set(o.material.uuid, new Set());
    use.get(o.material.uuid).add(z);
    if (o.userData && o.userData.merged) return;
    meshes += 1;
    mats.add(o.material.uuid);
    if (o.geometry) geos.add(o.geometry.uuid);
  });
  let crossing = 0;
  use.forEach(s => { if (s.size > 1) crossing += 1; });
  return { meshes, materials: mats.size, geometries: geos.size, crossing };
}"""


# Freezes the wall clock at 14:00 so a day/night repaint (or a live
# hero countdown) cannot perturb a scenario's pixels or counts run to run.
DAY_LOCK_JS = 'Date.prototype.getHours = function () { return 14; };'


# The roof's own vault pitch (pi/8): shared by test_house_shell_live.py's
# vault-height pin (via _deck_underside) and test_house_facade_live.py's
# roof-plane pin.
_VAULT_PITCH = _math.pi / 8


def _seed():
    """An event TODAY whatever the clock says (the overlay-live idiom), so
    the wall calendar's card has something to show on the lean-in."""
    from services import storage
    now = datetime.datetime.now().replace(microsecond=0)
    late = now.replace(hour=23, minute=59, second=0)
    start = now + datetime.timedelta(minutes=45)
    end = start + datetime.timedelta(hours=1)
    if end > late:
        start, end = now - datetime.timedelta(minutes=5), late
    storage.add_driver({'id': 'd1', 'name': 'Alex', 'color_code': '#38bdf8'})
    # Pin the cache FUNCTION, not the row: the server's own boot refresh
    # rebuilds the cache from the (empty) calendars moments after boot and
    # would silently erase a seeded row mid-test (test_kitchen_state idiom).
    sched = {
        'events': [{'id': 'e1', 'title': 'Soccer practice',
                    'start': start.isoformat(), 'end': end.isoformat()}],
        'assignments': {'e1': 'd1'},
    }
    storage.get_cached_schedule = lambda: sched
    # H2: two cars through the real model (no HA entities: both present,
    # no warnings, garage calm) so the garage has someone to park.
    from models.schemas import Car as CarModel
    storage.add_car(CarModel(name='Red Truck', body_type='truck',
                             color_code='#c9473d', seat_capacity=4).model_dump())
    storage.add_car(CarModel(name='Blue Minivan', body_type='minivan',
                             color_code='#3b82f6', seat_capacity=7).model_dump())
    # H3: children hang backpacks in the mudroom
    storage.add_member({'id': 'k1', 'name': 'Maya', 'role': 'child'})
    storage.add_member({'id': 'k2', 'name': 'Finn', 'role': 'child'})
