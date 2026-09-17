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


# Textures (grass, drive, wood) paint with Math.random; a pixel pin needs
# the same picture every run. Seeded LCG, installed by init script.
SEED_RNG_JS = ('Math.random = (function () { var s = 20260917; return function () {'
               ' s = (Math.imul(s, 1664525) + 1013904223) >>> 0; return s / 4294967296; }; })();')


# The roof's own vault pitch (pi/8): shared by test_house_shell_live.py's
# vault-height pin (via _deck_underside) and test_house_facade_live.py's
# roof-plane pin. Mirrors house.js's own BLOCK_PITCH constant (hoisted to
# one `var BLOCK_PITCH = Math.PI / 8` in v2.499.60, read by roofVault(),
# both shellGable('roof_main'/'garage_block_roof', ...) calls and
# blockDeckPlanes()/faceDeckPlane() — previously four separate literals).
_VAULT_PITCH = _math.pi / 8


def roof_piece_names(base, form, ridge):
    """shellGable's registered names for one block roof (house.js ~5013/~5095):
    decks _north/_south + ends _end_west/_end_east on a ridge x; decks
    _west/_east + ends _back/_front on a ridge z. Same four for a hip."""
    if ridge == 'x':
        return {base + '_north', base + '_south', base + '_end_west', base + '_end_east'}
    return {base + '_west', base + '_east', base + '_back', base + '_front'}


# ---- ROOF VALLEYS (masking spec section 6) ----------------------------
# A facade gable or dormer is built on a block roof deck. Nothing of it
# may exist UNDER that deck inside the house: the part below the parent
# deck's centre plane and behind the street face is cut at build (the
# valley clip), so the mask, which keeps everything inside a room's own
# volume, has nothing buried left to draw. The plane comes from the
# scene (chfRoofPlane: deckPlane, the one derivation shellGable places
# its own decks by); the face line from the slot table.
# Moved here from test_house_facade_live.py (blocks spec section 0) so
# the shell file's hip / ridge-z pin reads the same audit.
FEATURE_JS = r"""() => {
  const out = [];
  window.chfShellFabric().forEach(f => {
    const m = /^facade_(garage_block|main)_(gable|dormer|hip_end)_(\d+)/.exec(f.name);
    if (m) out.push({ name: f.name, face: m[1], kind: m[2], slot: +m[3] });
  });
  return out;
}"""

# `proudAtWall`: a gable's ridge cap is level, so its top is as high at
# the wall line as anywhere; the piece's highest vertex against the deck
# plane's height at the wall (ridge x: the same across the face) is the
# ridge's stand over the deck there, plus the cap's 0.125 over the ridge
# line.
VERTEX_AUDIT_JS = """(arg) => {
  const pl = window.chfRoofPlane(arg.face), vs = window.chfFabricVertices(arg.name);
  const faceZ = window.chfFacadeSlots().find(s => s.face === arg.face).z;
  const wallY = (pl.d - pl.n[2] * faceZ) / pl.n[1];
  let buried = 0, worst = 1e9, top = -1e9, n = vs.length;
  vs.forEach(p => {
    const s = pl.n[0]*p[0] + pl.n[1]*p[1] + pl.n[2]*p[2] - pl.d;
    if (p[2] < faceZ - 0.05) { if (s < worst) worst = s; if (s < -0.05) buried++; }
    if (p[1] > top) top = p[1];
  });
  return { n, buried, worst, proudAtWall: top - wallY };
}"""

# Blocks spec section 0: the same audit against EVERY deck of the block
# (chfRoofPlanes: the two slopes, plus a hip's two ends) rather than the
# one street deck, because a ridge on z puts a gable end on the street
# and chfRoofPlane is null there. The roof surface over (x, z) is the
# LOWEST of the centre planes, so a vertex is buried only when it lies
# below every one of them -- the same rule clipBuried's own region uses.
VERTEX_AUDIT_ALL_JS = """(arg) => {
  const planes = window.chfRoofPlanes(arg.face), vs = window.chfFabricVertices(arg.name);
  const faceZ = window.chfFacadeSlots().find(s => s.face === arg.face).z;
  let buried = 0, worst = 1e9, n = vs.length;
  vs.forEach(p => {
    let over = -1e9;
    planes.forEach(pl => {
      const s = pl.n[0]*p[0] + pl.n[1]*p[1] + pl.n[2]*p[2] - pl.d;
      if (s > over) over = s;      // the nearest plane ABOVE it: the roof line
    });
    // faceZ - 0.05, like the single-deck audit above: the valley clip's
    // own cut face stands at faceZ - FACE_INSET (0.02), and its vertices
    // run the full height of the cut piece, so a threshold AT the cut
    // plane counts the cut itself as buried geometry.
    if (p[2] < faceZ - 0.05) { if (over < worst) worst = over; if (over < -0.05) buried++; }
  });
  // no proudAtWall: the single-deck audit measures a gable's stand over
  // its one street deck, and this audit's callers ask only whether
  // anything sank under the roof.
  return { n, buried, worst };
}"""


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
