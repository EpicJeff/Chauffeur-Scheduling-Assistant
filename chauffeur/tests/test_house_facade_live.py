"""The Home's generated facade in real chromium: the canonical elevation
pinned against the hand-built one it replaced, the worst-case spec the
caps allow, the roof-line audit (nothing a facade gable/dormer builds may
bury itself under the block roof it sits on), and a saved facade that
reproduced a user-reported bug.

Split out of test_house_live.py (Task 7) so tools/test.py's parallel sweep
can spread the file's ~21 Chromium scenarios across workers. This file
holds the canonical facade pin/worst case/roof-line audit/saved-facade
reproduction scenarios; boot/lifecycle/leak scenarios stayed in
test_house_live.py, shell/mask/vault/clipper/convexity/study-box moved to
test_house_shell_live.py, and navigation/orbit/swipe/idle moved to
test_house_nav_live.py. Shared helpers live in house_live_common.py —
imported, never run on its own.

Run from chauffeur/:  python tests/test_house_facade_live.py
Set HOUSE_SHOTS=<dir> to also save a study-gable screenshot.
"""
import os
import copy
import math as _math
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools'))
os.environ.setdefault('CHAUFFEUR_DATA_DIR',
                      tempfile.mkdtemp(prefix='chauffeur_house_facade_live_'))

from live_app import live_app
from house_live_common import (check, _seed, DAY_LOCK_JS, SEED_RNG_JS,
                               INVARIANT_JS, _VAULT_PITCH, FEATURE_JS,
                               VERTEX_AUDIT_JS, ROOF_INSIDE_NEIGHBOUR_JS,
                               roof_piece_names)

# Spec 2026-09-17 blocks section 2, the compatibility pin's window: the
# rectangle of the B0 frame that is the HOUSE and nothing else.
#
# The fixture (tools/house_probe.py --views exterior, Task 1) is a whole
# 1400x1000 VIEWPORT, so it also carries the nav bar, the wall clock (a
# different minute every run and a different date every day), the hero
# card, the Ask-Argyle bar, the sky (whose tint follows the weather stub
# the probe's own --seed installs and this file's live_app does not) and
# the driveway cars (four in the probe's seed). None of those is what
# "the canonical still renders the same house" means, and none of them
# can be held still from here.
#
# MEASURED, not guessed: with house.js at the V1 head the EAST window's
# mean channel difference against the fixture is [0.016, 0.094, 0.125]
# (max pixel 22) -- the same house, to within the sky sliver above the
# ridge -- while the whole frame reads [7.9, 13.6, 16.4].
#
# TWO windows (review fix, v2.499.75), because one was half a house. The
# EAST window is the main roof's south deck, the east gable end, the
# street elevation east of the porch, six windows, the fascia and rake
# trim, the fence and the planting. The WEST window is the other half and
# the half this task could actually break: the garage bay's door, header
# and both PIERS (which now carry the base band), the mudroom's street
# face, the porch's gable, posts, deck and steps, and the front door.
# Measured the same way, same tolerance: [0.347, 0.236, 0.103], max 87.
#
# The west window's bounds are where they are for a reason, all four
# checked against the fixture pixel by pixel: x starts at 340 because the
# SKY (and the tree against it) begins around x 320 and the sky is the
# one big surface the weather stub moves; y starts at 460 to clear the
# Garage and Mudroom badges and the Garage MARKER, whose glyphs count the
# cars the probe seeded and this file does not; y stops at 715 because
# the wall clock's "11:48 AM" runs to x 455 below it; x stops at 660,
# short of the east window, with the Living-room marker inside it (that
# overlay costs about 3 per channel locally and the window absorbs it).
# The garage DOOR LEAF was the data-dependent risk worth checking -- four
# seeded cars versus none -- and it is not: the leaf's own region
# (x 340..440, y 460..560) differs by 0.002 per channel with and without
# them, which is antialiasing and not a door in another state.
B0_HOUSE_CLIP = {'x': 600, 'y': 430, 'width': 660, 'height': 470}
B0_WEST_CLIP = {'x': 340, 'y': 460, 'width': 320, 'height': 255}


# The facade spec §2.2 pins the canonical facade to the elevation it
# replaces. Exterior boot, quality=high, INVARIANT_JS `meshes` (the
# never-merged survivors only), counted where this scenario runs in the
# file -- so the two cars, two backpacks and hero card the earlier
# scenarios seeded into the shared temp data dir are in the scene too,
# identically before and after. Measured on a bare server (nothing
# seeded) the same build counts 1732, against 1724 at HEAD 34dcf7c
# before buildElevation() existed.
#
# The canonical build lands at 1732, +8, and every one of the eight is
# the SAME mesh standing unmerged rather than a new or a lost one.
# mergeStatic merges within one registered piece and needs four items on
# one material; two buckets only ever reached that floor because a
# feature shared its wall's group, and spec §6 puts every generated
# feature in a registered piece of its own:
#   +4  south_wall's baseboard and the front door's three casing boards
#       (all 0xe4ddd1 sharp) were one 4-item bucket; the door is
#       facade_main_door_10 now, so 1 + 3 survivors stand instead.
#   +4  the old wing wall's two corner boards and its two window sill
#       boards (FARMHOUSE.trim sharp) were one 4-item bucket; the
#       windows are facade_wing_window_15/16 now, so 2 + 1 + 1 survive.
#
# MASSING ARC 1 re-records this RED-first: 1873 -> 1840, a net -33 in
# the same in-file position (standalone, with only this scenario's own
# seed, the same build counts 1699 -- the 141-mesh gap is the seeded
# cars/backpacks/hero card the earlier scenarios leave in the shared
# temp data dir, exactly as before).
#
# -33 NET, not -33 pieces: this counts UNMERGED SURVIVORS, and both
# sides of the change merge well. Gone: TWENTY-FOUR registered names,
# recounted name by name against the pre-arc registry pin at 2fb22a4
# (its own expected-name list, 41 hand pieces) minus the 16 this arc
# keeps minus east_wall, which is rebuilt in a new plane but keeps its
# name -- 41 - 17 = 24:
#   massing_east_front_south/east/patio                          3
#   massing_front_roof_north/south/end_east                      3
#   massing_east_back_north/east/patio                           3
#   massing_back_roof_shed/back/front                            3
#   massing_service_north/west/south                             3
#   massing_service_roof_north/south/end_west                    3
#   mudroom_cross_roof_north/south                               2
#   mudroom_roof, mudroom_front_cladding, mudroom_east_finish,
#   living_roof                                                  4
# plus the terrace slab and its furniture. Two of the 24 retire the
# NAME only -- mudroom_roof's street wall/door folds into mudroom_front
# and mudroom_east_finish folds into west_wall, both at identity -- so
# 22 pieces of geometry actually left the scene. But a shell piece is a
# handful of same-material boxes that mergeStatic already collapsed
# inside its own group, and the yard furniture was mostly folded into
# instanceYard's InstancedMeshes, so neither was ever costing survivors
# in proportion to its size. Added: east_wall's three windows, north_wall_east and
# its window, the back door, the garage block's three walls, the block
# roof's two end pieces, two future-room floors, future_room_partition
# and the back patio slab. The pin's job is to catch the NEXT
# unintended change; the direction (fewer) is the arc's own thesis.
#
# CUTAWAY OWNERSHIP (fix 2026-09-16) re-records it RED-first once more:
# 1840 -> 1849, +9, every one of the nine derived from the two splits
# rather than measured and accepted. Standalone (only this scenario's
# own seed) the same build counts 1708 against 1699 before the fix --
# the same +9, and the same 141-mesh seeded gap as before, which is
# what says the delta is the split and nothing else.
#   +6  roof_main becomes roof_main_west + roof_main_east. Each half
#       still builds 2 slope decks + 2 eave trims + 2 ridge caps (6),
#       so the pair costs 12 where one roof cost 6: +6 there. The GABLE
#       ENDS are a wash: the one roof built two (each a gable infill
#       plus two rake boards, 3 meshes), and the two halves build one
#       outer end each -- `ends [-1]` west, `ends [1]` east -- because
#       the split is an interior line and a gable there would be a wall
#       through the middle of the attic. 2 x 3 before, 2 x 3 after.
#   +3  south_wall becomes south_wall + south_wall_east: the same
#       three-box idiom (plaster half, siding half, baseboard) twice.
# Neither split adds a merge survivor beyond its own boxes: mergeStatic
# needs four items on one material inside ONE registered piece, and
# every one of these boxes is a different material or a lone member of
# its bucket on both sides of the change.
#
# STUDY REFIT (2026-09-16) re-records it RED-first again: 1849 -> 1865,
# +16. This pin counts every never-merged mesh in the SCENE, not only
# the elevation, so interior pieces do move it -- and this pass swaps
# two interior doors and rebuilds two of the study's own walls. The
# exterior elevation itself is untouched in COUNT: the study's own east
# pane changed SIZE (1.35 x 2.70 at y 2.80 -> 2.02 x 1.34 at y 1.95, to
# be the same window the room has behind it) and shellWindow builds the
# same eight meshes at any size.
# Standalone (only this scenario's own seed) the same build counts 1724
# against 1708 before the refit -- the same +16, and the same 141-mesh
# seeded gap, which is what says the delta is this pass and nothing else.
#   +13 living_study_door: the plain interiorDoor's 7 meshes (leaf, two
#       panels, head casing, two side casings, knob) become the glazed
#       pair's 20 -- 2 lites, 2 hanging stiles, 4 rails, the meeting
#       stile, 8 handle parts (a plate and a knob per leaf per face)
#       and 3 casing/lining boxes.
#   +17 east_room_door is new: two interiorDoor leaves, one per face of
#       a cut opening (7 each), plus the cut's own head and two jambs.
#       Both doors are house_features fixtures, added to the scene after
#       the build's mergeStatic pass, so every one of them survives.
#    -8 patio_slider is retired. Its twelve frame-coloured boxes were
#       already ONE merged mesh, which this pin does not count; the
#       survivors that leave with it are 2 unique panes (forceUnique
#       glass), 2 trim sills, 2 wood pulls and 2 stoop sills.
#    -3 east_partition crosses the merge threshold. Its C.wall boxes go
#       from three (the three wall segments) to five (plus a header over
#       each door opening), and four on one material inside one
#       registered piece is exactly what mergeStatic folds: three
#       survivors become none.
#    -3 house_study's north wall. The window's four-box opening (left,
#       right, under, over) left it; it is one solid run now, because it
#       is the interior wall the shelves and the board hang on.
#
# FIX ROUND 1 (v2.499.44) re-records it RED-first once more, 1865 -> 1868,
# +3, and the exterior elevation's own count still has not moved: every
# piece in both passes is interior.
#    +3 house_study's EAST wall. The first cut gave the room no east wall
#       of its own -- it let the block's `east_wall` slab stand in for
#       one and left the old `box('east', ...)` dead inside that slab,
#       which is why the room read cream on the north and charcoal on
#       the east. The room has its own again, built the way the north
#       wall is: the four boxes around the window (east-north, -south,
#       -low, -high) where one dead box used to be.
#    +1 VAULTED PARTITIONS (2026-09-16). Four interior wall sections
#       rise from the eave to the roof deck, and only ONE of them shows
#       up here: mergeStatic folds east_partition's section into that
#       group's existing five-box plaster bucket and the garage's into
#       the garage shell's five-box siding bucket (this count skips
#       merged output by design), and the study's two walls grew in
#       HEIGHT rather than in number. future_room_partition's group
#       holds two boxes now, under mergeStatic's four-item floor, so its
#       section stays its own draw. The exterior elevation itself has
#       not moved a millimetre: every piece in this arc is interior.
#
# VIEW-VOLUME MASKING (task 3, v2.499.53 / fix round 1 v2.499.54)
# re-records it RED-first, 1869 -> 2026, +157, and the exterior
# elevation's own count has still not moved: the full shell is merged
# exactly as before (its patterned buckets keep their one full composite;
# the per-room stand-ins are merged output, which this count skips), and
# the exterior draws the same 1432 meshes it did (probe --budget,
# before/after). The +157 are the five room shells' unmerged REMNANTS --
# the cut-off faces of fabric meshes and their caps, merged per mirrored
# ROW (so a composite keeps its row's shellOf ancestry) and therefore
# loose wherever a row's remnants or caps stay under mergeStatic's
# four-item floor: kitchen 57, living 20, study 14, garage 8, mudroom 58.
# Most are west_wall's own props (a picture frame, a shelf, a sconce part
# -- each on its own material, 25 in the kitchen shell and 34 in the
# mudroom's) cut where they stand between the street camera and the
# pantry nook, or between the mudroom camera and the mudroom. Hidden
# shells count all the same: this pin walks the scene, not the frustum.
# (Standalone -- only this scenario's own seed -- the same build counts
# 1885, the same 141-mesh seeded gap as every earlier entry.)
#
# VIEW-VOLUME MASKING task 4 (v2.499.55) re-records it RED-first,
# 2026 -> 2017, -9: the x 6.85 splits are folded back, so the exterior
# elevation's own count MOVES for the first time since the facade arc
# -- fewer pieces, the arc's own thesis. Derived first (-9), then
# measured: 2017 here, and standalone (only this scenario's own seed)
# 1876 against 1885 before -- the same -9 and the same 141-mesh seeded
# gap, which is what says the delta is the un-split and nothing else:
#   -3  south_wall_east's three boxes (plaster half, siding half,
#       baseboard) fold into south_wall's own three: the same three
#       materials, each still a lone member of its bucket (under
#       mergeStatic's four-item floor), so three survivors become none.
#   -6  roof_main_west + roof_main_east become roof_main. Each half
#       built 2 slope decks + 2 eave trims + 2 ridge caps (6), all on
#       different materials inside their own registered groups; one
#       roof builds 6 where the pair built 12. The gable ends are a
#       wash: one outer end per half before, two ends on the one roof
#       after (3 meshes each, either way).
#    0  the room shells' remnants and caps (merged per mirrored row,
#       loose under the four-item floor): the one wall's and the one
#       deck's remnants per room merge into the same number of
#       composites the two halves' did -- measured, not assumed.
#
# ROOF VALLEYS, masking task 5 (v2.499.56) re-records it RED-first,
# 2017 -> 2015, -2: the two facade gables lose what was buried under
# the block roofs (clipBuried, at build), so the pieces the exterior
# draws and the remnants the room shells cut both change. Derived from
# a per-row census (scratch/valley-shellrows-{before,after}.txt), then
# measured: 2015 here.
#   +6  exterior: each gable SIDE group was deck + eave trim + ridge cap,
#       three materials, three survivors. After the clip the porch
#       gable's deck and trim are each two convex pieces (above the
#       main deck; below it in front of the wall) and its ridge cap one
#       (its buried back gone) -- 5 face meshes on the same three
#       materials plus 5 section caps, which reach mergeStatic's floor
#       and fold into one composite: 5 survivors, +2 per side, +4. The
#       bay gable's deck splits the same way, its trim keeps only its
#       front stub and its cap its front: 4 survivors, +1 per side, +2.
#       The two front groups (infill + rakes) stand in front of the
#       wall and are untouched.
#   -8  kitchen shell: the porch gable's two side rows each left 6 loose
#       remnants (three faces, three caps); the buried back that stood
#       in the kitchen's cone is gone, so each row leaves two face
#       remnants and its caps merge (4 -> a composite): 2 + 1 merged.
#   +4  garage shell: the bay gable's two side rows each leave 4
#       remnants where they left 2 (the above-deck piece and the cap
#       are cut separately now).
#   -4  mudroom shell: the bay gable's east deck was grazed (0.09) at
#       its buried back only; nothing of it stands in the mudroom's
#       cone now (fraction 0), so its 4 remnants are gone.
#
# TASK 7 (test file split, v2.499.59) re-records it once more, 2015 ->
# 1874, -141, with NO code change behind it: this scenario itself never
# calls `_seed()` (it never seeded a driver, cars or members of its own),
# so every prior number above was measured IN THE ORIGINAL MONOLITHIC
# FILE, where the two cars, two backpacks and hero card the file's
# EARLIER scenarios (boot, the leak scenarios, the fridge/garage rebuild
# scenarios) seeded into the ONE shared temp data dir were still sitting
# in storage when this scenario's turn came -- exactly what the comment
# at the top of this block already called out ("the two cars, two
# backpacks and hero card the earlier scenarios seeded ... are in the
# scene too"). Split into its own process with its own empty
# CHAUFFEUR_DATA_DIR (Task 7), this scenario now runs against a bare
# server the way the very first measurement in this file's history did
# ("Measured on a bare server (nothing seeded) the same build counts
# 1732" -- before buildElevation() existed, and before every mesh-count
# delta this whole comment block has tracked since). 1874 is that same
# "bare server" lineage carried forward through every intervening change
# this file recorded (facade §6 registration, MASSING ARC 1, cutaway-
# ownership splits, the STUDY REFIT, FIX ROUND 1, view-volume masking
# tasks 3-5) -- re-measured directly rather than back-derived, and
# three-run-stable in this file alone.
CANONICAL_EXTERIOR_MESHES = 1874


def scenario_canonical_facade_pins_the_hand_built_elevation():
    """The canonical facade builds the elevation it replaced.

    Facade spec §2.2: CANONICAL is today's street face, snapped onto the
    slot grid. Pixel positions move (no slot width reproduces the old
    hand-typed x values); the mesh count and the spec the scene was built
    from do not. §2 also makes the slot table single-source: house.js
    computes it in JS, services/house_facade.py in Python, and this pins
    the two against each other slot by slot so they can never drift.
    """
    served = live_app()
    if served is None:
        return
    with served.browser() as page:
        # INVARIANT_JS reads window.__hpScene, which only the probe's
        # THREE_WRAP captures -- same route idiom as the boot scenario.
        from house_probe import THREE_WRAP
        with open('static/vendor/three.min.js', 'rb') as fh:
            _patched = fh.read() + THREE_WRAP
        page.route('**/three.min.js*', lambda route: route.fulfill(
            status=200, content_type='application/javascript', body=_patched))
        page.add_init_script(DAY_LOCK_JS)
        # MASSING ARC 2 task 5: the same seeded Math.random the B0 capture
        # ran under (tools/house_probe.py --seed-rng), so grass, drive and
        # planting paint the same picture the fixture below holds.
        page.add_init_script(SEED_RNG_JS)
        page.goto(served.url('house?quality=high'))
        page.wait_for_selector('#room canvas', timeout=20000)
        page.wait_for_timeout(2200)
        inv = page.evaluate(INVARIANT_JS)
        check(not inv.get('err'), 'mesh probe captured the scene: %r' % inv)
        check(inv['meshes'] == CANONICAL_EXTERIOR_MESHES,
              'canonical facade builds the same exterior mesh count: '
              '%d != %d' % (inv['meshes'], CANONICAL_EXTERIOR_MESHES))
        from services import house_facade as hf
        check(page.evaluate('window.chfFacade()') == hf.CANONICAL,
              'the scene is built from CANONICAL, not a hand literal')
        # MASSING ARC 2 (spec 2026-09-17): CANONICAL_JS (house.js's
        # no-injection fallback) is still the VERSION-1 literal and no
        # longer equals CANONICAL directly -- it only equals it THROUGH
        # normalize()'s V1 upgrade table. So the check above no longer
        # passes either way, which makes these two more load-bearing,
        # not less: they say which object the scene actually used --
        # the server injected a spec, and the scene was built from THAT.
        # Task 5 makes CANONICAL_JS the V2 literal again.
        check(page.evaluate("!!(window.HOUSE_FACADE && window.HOUSE_FACADE.spec)"),
              'the server injected the facade')
        check(page.evaluate("window.chfFacade() === window.HOUSE_FACADE.spec"),
              'the scene built from the injected spec, not the fallback')
        js_slots = page.evaluate('window.chfFacadeSlots()')
        py_slots = hf.slot_table()
        check(len(js_slots) == len(py_slots),
              'same slot count: %d vs %d' % (len(js_slots), len(py_slots)))
        for a, b in zip(js_slots, py_slots):
            for k in ('x0', 'x1', 'cx', 'z', 'eave'):
                check(abs(a[k] - b[k]) < 1e-6,
                      'slot %d %s: %r vs %r' % (b['i'], k, a[k], b[k]))
            for k in ('face', 'room', 'roof'):
                check(a[k] == b[k],
                      'slot %d %s: %r vs %r' % (b['i'], k, a[k], b[k]))
            # masking task 4: the slot table carries no owners any more
            # on either side (the mask decides what a room view removes)
            check('owners' not in a and 'owners' not in b,
                  'slot %d: owners retired, got %r / %r' % (b['i'], sorted(a), sorted(b)))
        # Spec 2026-09-17 blocks section 2 compatibility pin: the canonical
        # V2 model renders the same picture as B0 (Task 1, same seed, same
        # day lock). Mean absolute difference over the house window,
        # 8-bit channels.
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        from PIL import Image, ImageChops, ImageStat
        import io as _io
        fixture = Image.open(os.path.join(os.path.dirname(__file__), 'fixtures',
                                          'house_photo', 'b0-exterior.png')).convert('RGB')
        for half, clip in (('east', B0_HOUSE_CLIP), ('west', B0_WEST_CLIP)):
            png = page.screenshot(clip=clip)
            a = Image.open(_io.BytesIO(png)).convert('RGB')
            b = fixture.crop((clip['x'], clip['y'],
                              clip['x'] + clip['width'], clip['y'] + clip['height']))
            diff = ImageStat.Stat(ImageChops.difference(a, b)).mean
            check(max(diff) < 1.5,
                  'canonical V2 renders B0 within tolerance, %s half: '
                  'mean channel diff %r' % (half, diff))
        check(page.evaluate('window.chfBlocks().main.cladding') == 'batten',
              'the scene built from the block model')
        check(page.evaluate('window.chfBlocks()') == hf.CANONICAL['blocks'],
              'and the block model IS the canonical one, block for block')
        errs = [e for e in served.errors()
                if 'WebGL' not in e and 'GroupMarker' not in e]
        check(not errs, 'no console errors: ' + '; '.join(errs[:3]))


def scenario_claddings_and_base_band():
    """Spec section 3.1: six claddings, world-scaled UVs carried on the
    texture, a base band in its own material and colour. Each variant
    boots clean and the draw count stays within the measured rule.

    The spec rides in on a DRAFT TOKEN, not an init script: house.html
    assigns window.HOUSE_FACADE inline AFTER every init script has run,
    so add_init_script cannot inject a facade (task 10's finding). live_app
    runs uvicorn on a thread of THIS interpreter, so a token minted here
    is a token the served /house resolves.
    """
    from services import house_facade as hf
    served = live_app(_seed)
    if served is None:
        return
    from house_probe import THREE_WRAP, BUDGET_JS
    with open('static/vendor/three.min.js', 'rb') as fh:
        patched = fh.read() + THREE_WRAP

    def boot(page, spec):
        page.route('**/three.min.js*', lambda route: route.fulfill(
            status=200, content_type='application/javascript', body=patched))
        page.add_init_script(DAY_LOCK_JS)
        page.add_init_script(SEED_RNG_JS)
        page.goto(served.url('house?quality=high&draft=' + hf.issue_draft(spec)))
        page.wait_for_selector('#room canvas', timeout=20000)
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        return page.evaluate(BUDGET_JS)

    with served.browser() as page:
        base = boot(page, copy.deepcopy(hf.CANONICAL))
        check(page.evaluate("window.chfBlocks().main.base") is None,
              'the canonical block model carries no base band')
    for clad in ('lap', 'brick', 'stone', 'stucco', 'shingle'):
        spec = copy.deepcopy(hf.CANONICAL)
        spec['blocks']['main']['cladding'] = clad
        spec['blocks']['main']['body'] = 'brick_red' if clad == 'brick' else 'tan'
        spec['blocks']['garage']['base'] = {'material': 'stone', 'height': 1.0,
                                            'body': 'stone_grey'}
        spec, _notes = hf.normalize(spec)
        with served.browser() as page:
            r = boot(page, spec)
            # MEASURED, every one of the six identical (task-5-report.md):
            # +5 meshes -- the garage block's five base-band runs, three
            # from shellWall (garage_block_north/west, mudroom_front) and
            # one on each of the bay's two piers -- and +10 draws: those
            # five, plus the two new material buckets (the main block's own
            # tile, now a different (material, body) pair from the
            # garage's, and the stone base) splitting merges the canonical
            # could make. Nothing else.
            check(r['calls'] <= base['calls'] + 10,
                  '%s: draws %s vs canonical %s (+2 material buckets, '
                  '+ five unmerged band runs)' % (clad, r['calls'], base['calls']))
            check(r['inFrustum'] <= base['inFrustum'] + 5,
                  '%s: meshes %s vs %s (the five base bands and nothing else)'
                  % (clad, r['inFrustum'], base['inFrustum']))
            u = page.evaluate("(() => { const b = window.chfBlocks();"
                              " return b.main.cladding + '|' + b.garage.base.material; })()")
            check(u == clad + '|stone', 'built from the model: %s' % u)
            errs = [e for e in served.errors() if 'WebGL' not in e]
            check(not errs, '%s: console clean: %s' % (clad, errs[:3]))


def scenario_worst_case_facade_builds_clean():
    """Spec §8: the heaviest spec the caps allow builds with no console
    errors, registers every feature, and the generated front door still
    navigates.

    The saved 'worst' record and the active-facade setting are process-wide
    state living in the module's shared CHAUFFEUR_DATA_DIR (every scenario
    in this file serves its own app against the same temp data dir), so a
    `finally` restores canonical and deletes the saved record no matter how
    the browser half of this scenario ends -- later scenarios (the
    canonical pin, in particular) must still see canonical.
    """
    from services import house_facade as hf
    served = live_app(lambda: (_seed(), hf.save_facade('worst', hf.worst_case(), activate=True)))
    if served is None:
        return
    try:
        with served.browser() as page:
            errors = []
            page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
            page.add_init_script(DAY_LOCK_JS)
            page.goto(served.url('house?quality=high'))
            page.wait_for_selector('#room canvas', timeout=20000)
            page.wait_for_timeout(2600)
            check(not errors, f'worst case builds clean: {errors[:3]}')
            spec = page.evaluate('window.chfFacade()')
            check(spec == hf.worst_case(), 'built from the worst case')
            fab = page.evaluate('window.chfShellFabric()')
            names = {f['name'] for f in fab}
            for g in spec['ground']:
                if g['kind'] in ('window', 'door', 'porch'):
                    face = hf.slot_table()[g['slot']]['face']
                    check(f"facade_{face}_{g['kind']}_{g['slot']}" in names, f'registered: {g}')
            for r in spec['roof']:
                face = hf.slot_table()[r['slot']]['face']
                prefix = f"facade_{face}_{r['kind']}_{r['slot']}"
                check(any(n == prefix or n.startswith(prefix + '_') for n in names), f'registered: {r}')
            page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
            p = page.evaluate("window.chfNavProbe({entry:'front_door'})")
            check(p is not None, 'the generated front door is tappable')
            page.mouse.click(p['cx'], p['cy'])
            page.wait_for_function("window.chfNavProbe({settled:true}) && window.chfHouseMode() === 'living'", timeout=20000)
    finally:
        for r in hf.list_facades():
            if r.get('id') != hf.CANONICAL_ID and r.get('name') == 'worst':
                hf.delete_facade(r['id'])
        hf.set_active(hf.CANONICAL_ID)


def _audit_roof_features(page):
    feats = page.evaluate(FEATURE_JS)
    check(feats, 'the facade has roof features')
    seen = {}
    for f in feats:
        if f['kind'] == 'hip_end':
            continue          # a fin standing on the wall line, in front of it
        a = page.evaluate(VERTEX_AUDIT_JS, f)
        check(a['n'] > 0, f"{f['name']}: has vertices")
        check(a['buried'] == 0,
              f"{f['name']}: {a['buried']} of {a['n']} vertices below the "
              f"{f['face']} deck plane behind the face (lowest {a['worst']:.3f})")
        seen[f['name']] = a
    return seen


def scenario_roof_features_stop_at_the_roof_line():
    """Spec 2026-09-16 masking section 6: every vertex of a facade gable or
    dormer behind the street face sits at or above the block deck it sits
    on; a gable's ridge stands proud of that deck at the wall.

    The porch gable (canonical gable_8) keeps the porch's own eave (4.8:
    it IS the porch roof, on the porch posts), so in FRONT of the wall its
    low eaves pass under the main eave as they always have -- the audit
    is 'nothing buried behind the face', not 'nothing below the plane
    anywhere'. Its ridge still stands proud at the wall: 7.505 against
    the deck plane's 5.78 there, 1.725 (its rise 2.525 less the 0.8 the
    porch eave sits under the block eave). The garage bay gable's eave is
    the block eave, so it stands proud by its whole rise (1.92)."""
    served = live_app(_seed)
    if served is None:
        return
    with served.browser() as page:
        page.add_init_script(DAY_LOCK_JS)
        page.goto(served.url('house?quality=high'))
        page.wait_for_selector('#room canvas', timeout=20000)
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        pl = page.evaluate("window.chfRoofPlane('main')")
        check(pl and abs(pl['n'][1] - _math.cos(_VAULT_PITCH)) < 1e-6
              and abs(pl['n'][2] - _math.sin(_VAULT_PITCH)) < 1e-6,
              f'the main street deck plane tilts up and south at pi/8: {pl}')
        # the plane's height at the wall line is the block eave + 0.18
        y_wall = (pl['d'] - pl['n'][2] * 14.55) / pl['n'][1]
        check(abs(y_wall - 5.78) < 1e-3, f'main deck plane at the wall: {y_wall:.3f} != 5.78')
        seen = _audit_roof_features(page)
        for name, proud in (('facade_main_gable_8_west', 1.725),
                            ('facade_main_gable_8_east', 1.725),
                            ('facade_garage_block_gable_0_west', 1.92),
                            ('facade_garage_block_gable_0_east', 1.92)):
            check(name in seen, f'{name} audited')
            # the ridge cap's top adds 0.125 over the ridge line
            got = seen[name]['proudAtWall']
            check(proud - 0.05 < got < proud + 0.2,
                  f'{name}: stands {got:.3f} proud of the deck at the wall, want ~{proud}')
        check(not served.errors(), f'console clean: {served.errors()[:3]}')


def scenario_a_saved_gable_over_the_study_stays_outside():
    """User report (2026-09-16): a SAVED facade with a gable over the study
    put a shingled wedge with white battens beside the study's glass
    doors, inside the house, in the living view. The gable's decks and
    eave trims ran back and down under the main roof; the mask keeps
    everything inside the room, so it drew them. Reproduced at HEAD with
    a span-3 gable at slot 13 (x 5.57..11.02: it straddles the study
    partition at 6.85, so its buried west deck stood in the great room
    beside the study doors -- scratch/valley-before-13/study-gable-
    living.png); a gable wholly over the study (slot 14) buries the same
    way but the partition hides it from the living camera. After the
    valley clip no vertex of that gable is below the main deck behind
    the wall, and the gable takes the height rule (eave = the block
    eave: ridge = plane + its own rise, 1.894 on a span of 3)."""
    from services import house_facade as hf
    spec = copy.deepcopy(hf.CANONICAL)
    spec['roof'].append({'slot': 13, 'span': 3, 'kind': 'gable'})
    served = live_app(lambda: (_seed(), hf.save_facade('study gable', hf.normalize(spec)[0], activate=True)))
    if served is None:
        return
    try:
        with served.browser() as page:
            page.add_init_script(DAY_LOCK_JS)
            page.goto(served.url('house?quality=high'))
            page.wait_for_selector('#room canvas', timeout=20000)
            page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
            built = page.evaluate('window.chfFacade()')
            check(any(r['slot'] == 13 and r['kind'] == 'gable' for r in built['roof']),
                  'the saved facade with the study gable is what built')
            seen = _audit_roof_features(page)
            for side in ('west', 'east'):
                a = seen.get(f'facade_main_gable_13_{side}')
                check(a, f'the study gable {side} deck is registered')
                check(1.894 - 0.05 < a['proudAtWall'] < 1.894 + 0.2,
                      f"study gable {side}: stands {a['proudAtWall']:.3f} proud at the wall, want ~1.894")
            # LOOKED at from the living (HOUSE_SHOTS): nothing of the
            # gable lies in the house (behind the wall, under the deck);
            # the audit above is the same statement vertex by vertex
            page.evaluate("window.chfHouseEnterRoom('living')")
            page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
            shots = os.environ.get('HOUSE_SHOTS')
            if shots:
                os.makedirs(shots, exist_ok=True)
                page.screenshot(path=os.path.join(shots, 'study-gable-living.png'))
            check(not served.errors(), f'console clean: {served.errors()[:3]}')
    finally:
        for r in hf.list_facades():
            if r.get('id') != hf.CANONICAL_ID and r.get('name') == 'study gable':
                hf.delete_facade(r['id'])
        hf.set_active(hf.CANONICAL_ID)



# ?day=1 has to beat a clock that says otherwise, so this locks the page's
# own clock to eleven at night -- the inverse of DAY_LOCK_JS.
NIGHT_LOCK_JS = 'Date.prototype.getHours = function () { return 23; };'


def _mean_luma(data_url):
    """The mean brightness of a chfCapture() frame, and its size."""
    import base64, io as _io
    raw = base64.b64decode(data_url.split(',', 1)[1])
    from PIL import Image
    im = Image.open(_io.BytesIO(raw)).convert('L')
    px = list(im.getdata())
    return sum(px) / float(len(px)), im.size


def scenario_a_draft_token_renders_day_locked_and_captures():
    """MASSING ARC 2 task 10: /house?draft=<token> is the injection path.

    `window.HOUSE_FACADE = ...` is assigned INLINE in house.html, AFTER
    every init script has run, so page.add_init_script cannot inject a
    facade -- house.js reads the inline assignment, not the injected one.
    The token is the seam instead: live_app runs uvicorn on a thread of
    THIS interpreter, so a token minted here is a token the served /house
    resolves, and the spec rides the page without anything being saved or
    activated.

    Three laws in one boot:
      - the DRAFT builds (a mirrored spec, which the active facade is not),
        and the draft's own slot table rides the page with it;
      - ?day=1 beats the scene's own clock, pinned here to 23:00 -- a night
        sweep used to photograph a dark house, and no init script is needed
        to stop it any more;
      - window.chfCapture() hands back one real 1400x1000 frame, rendered
        and read in the same task with no preserveDrawingBuffer.
    """
    from services import house_facade as hf
    served = live_app(_seed)
    if served is None:
        return
    spec, _ = hf.normalize({**copy.deepcopy(hf.CANONICAL), 'mirror': True})
    tok = hf.issue_draft(spec)
    with served.browser() as page:
        page.add_init_script(NIGHT_LOCK_JS)      # deliberately NOT DAY_LOCK_JS
        page.goto(served.url('house?draft=' + tok + '&day=1&quality=medium'))
        page.wait_for_selector('#room canvas', timeout=20000)
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        built = page.evaluate('window.chfFacade()')
        check(built and built['mirror'] is True,
              'the mirrored DRAFT is what built, not the active facade: %r'
              % (built and built.get('mirror')))
        check(hf.active_bundle()['spec']['mirror'] is False,
              'and the active facade was never touched by rendering a draft')
        # the injected bundle itself, not the JS recomputation (house.js
        # derives SLOTS in unrounded floats of its own; the canonical pin
        # above already holds those two against each other). What is new
        # here is that the DRAFT bundle rode the page, slots and all.
        inj = page.evaluate('window.HOUSE_FACADE')
        check(inj['id'] == 'draft' and inj['spec'] == spec,
              "the page carries the draft bundle: %r" % inj.get('id'))
        check(inj['slots'] == hf.slot_table(spec['blocks']),
              "the draft carries its OWN blocks' slot table into the page")
        day_shot = page.evaluate('window.chfCapture()')
        check(isinstance(day_shot, str) and day_shot.startswith('data:image/png;base64,'),
              'chfCapture hands back a png data URL: %r' % (day_shot or '')[:40])
        day_mean, size = _mean_luma(day_shot)
        check(size == (1400, 1000), 'the frame is the whole viewport: %r' % (size,))
        check(day_mean > 40,
              'at 23:00 with ?day=1 the capture is a LIT house: mean %.1f' % day_mean)

        # the same page, same clock, no ?day=1: the scene's own night rig is
        # still in charge, so the flag is a flag and not a new default.
        page.goto(served.url('house?draft=' + tok + '&quality=medium'))
        page.wait_for_selector('#room canvas', timeout=20000)
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        night_mean, _ = _mean_luma(page.evaluate('window.chfCapture()'))
        check(night_mean < day_mean - 5,
              'without ?day=1 the 23:00 clock still wins: night %.1f vs day %.1f'
              % (night_mean, day_mean))
        check(not served.errors(), f'console clean: {served.errors()[:3]}')


def scenario_a_bad_draft_token_is_not_an_error():
    """Never drop functionality: a token that expired while a parent was
    away, or a link someone kept, draws the ACTIVE facade -- the page
    everyone else gets -- and never an error page."""
    from services import house_facade as hf
    served = live_app(_seed)
    if served is None:
        return
    with served.browser() as page:
        page.add_init_script(DAY_LOCK_JS)
        page.goto(served.url('house?draft=deadbeef.nope&quality=medium'))
        page.wait_for_selector('#room canvas', timeout=20000)
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        built = page.evaluate('window.chfFacade()')
        check(built and built['mirror'] is False,
              'a bad token falls back to the active facade, never an error page')
        check(built == hf.active_bundle()['spec'],
              'and it is the active facade exactly, spec for spec')
        check(not served.errors(), f'console clean: {served.errors()[:3]}')


# MASSING ARC 2 task 6: the canonical souths the block model measures its
# depth from -- house.js's own SWZ1 and the garage block's 10.10, which
# services/house_facade.py's FACES table carries verbatim.
MAIN_SOUTH_0, GARAGE_SOUTH_0 = 14.55, 10.10

# The `garage_door` fabric row is the whole bay assembly -- jambs, header
# trim, glazing, coach lamps AND the leaf -- and its box centre sits
# 0.015 behind the face line at depth 0 (MEASURED at the canonical boot,
# not derived: the group spans z 9.76..10.41). Fix round 1 pins it,
# because the LEAF was the one part of the bay still nailed to z 10.02
# while the opening around it moved out with the face.
GARAGE_DOOR_ZC_0 = 10.085


def scenario_depth_moves_the_face_and_the_blocks_meet():
    """Spec section 2 (depth, where blocks meet) and 3.2.

    Five boots; each one comes up clean, the street faces sit where the
    model says, the JS slot table still agrees with Python's, the whole
    garage bay -- leaf included -- rides its own face, the step at the
    shared face x -7.15 is closed by a wall, the deeper block's roof
    stops at the neighbour's BOUNDED volume, and nothing outside that
    volume is lost.

    TWO BRIEF DEVIATIONS, both recorded in task-6-report.md.

    (1) THE RETURN WALL IS NOT SYMMETRIC, because the house is not. The
    main block already stands 4.45 deeper than the garage block at depth
    0/0, and its west face over that step is `west_skirt` -- a piece that
    has carried the main block's cladding and base band there since long
    before the block model existed. So the MAIN's return wall IS
    west_skirt (extended to FULL_HOUSE.south by this task), and only the
    garage's own return, when a depth actually pushes the garage block
    PAST the main's street face, is a new piece (`garage_return`). A
    second wall in the same plane as west_skirt would z-fight it.

    (2) THE NEIGHBOUR-VOLUME CLIP RUNS ONLY WHERE THE TWO BLOCK ROOFS ARE
    GEOMETRICALLY IDENTICAL -- depth, form, ridge, pitch AND eave, all
    five (fix round 1; it was depth alone). Spec section 2 rev2 ends
    "with equal depth and equal stories nothing changes for the
    canonical", and measurably it cannot: with all five equal the two
    blocks stand exactly as they were hand-built -- one shared eave line,
    one pitch, therefore one coplanar north deck -- and the main roof's
    west rakes have always run over the garage's footprint under the
    garage's own roof. Subtracting there would cut geometry the canonical
    mesh and pixel pins hold. Any other combination -- a hip beside a
    gable, two different pitches, a moved face -- genuinely
    interpenetrates and is clipped; the fifth boot below is exactly that
    case at depth 0/0.

    A BLOCK-ROOF PIECE CAN LEGITIMATELY VANISH. Where the clip runs,
    `garage_block_roof_end_east` -- the garage's own gable infill at the
    shared face -- stands wholly inside the main block's volume, because
    the main owns that face plane (equal eaves, tie to main) and closes
    it with its own `roof_main_end_west` in the same 0.14 of x. Two
    infills in one plane is the z-fight the ownership rule exists to
    end, so the garage's is dropped rather than registered with nothing
    in it. Every combination below pins the exact surviving set.
    """
    from services import house_facade as hf
    served = live_app(_seed)
    if served is None:
        return
    from house_probe import BUDGET_JS, THREE_WRAP
    with open('static/vendor/three.min.js', 'rb') as fh:
        patched = fh.read() + THREE_WRAP
    all_roof = (roof_piece_names('roof_main', 'gable', 'x') |
                roof_piece_names('garage_block_roof', 'gable', 'x'))
    # (depths, main roof override, label)
    combos = [({'main': 0, 'garage': 0}, None, 'canonical'),
              ({'main': 2, 'garage': 0}, None, 'main deeper'),
              ({'main': 0, 'garage': 6}, None, 'garage deeper'),
              ({'main': 2, 'garage': 6}, None, 'both, main still deeper'),
              ({'main': 0, 'garage': 0}, 'hip', 'a hip beside a gable')]
    base_main_out = base_garage_out = None
    for depths, main_form, label in combos:
        spec = copy.deepcopy(hf.CANONICAL)
        spec['blocks']['main']['depth'] = depths['main']
        spec['blocks']['garage']['depth'] = depths['garage']
        if main_form:
            spec['blocks']['main']['roof']['form'] = main_form
        spec, _notes = hf.normalize(spec)
        m_south = MAIN_SOUTH_0 + depths['main']
        g_south = GARAGE_SOUTH_0 + depths['garage']
        # the shared face x -7.15: whichever block's street face is
        # further south leaves the OTHER one's side wall exposed over the
        # step. Only the garage's side needs a new piece (see the
        # docstring); the main's is west_skirt.
        want_return = 'garage_return' if g_south > m_south + 1e-6 else None
        # the clip runs unless all five roof inputs match
        want_meet = bool(depths['main'] != depths['garage'] or main_form)
        tok = hf.issue_draft(spec)
        with served.browser() as page:
            page.route('**/three.min.js*', lambda route: route.fulfill(
                status=200, content_type='application/javascript', body=patched))
            page.add_init_script(DAY_LOCK_JS)
            page.add_init_script(SEED_RNG_JS)
            page.goto(served.url('house?quality=high&draft=' + tok))
            page.wait_for_selector('#room canvas', timeout=20000)
            page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
            geo = page.evaluate('window.chfBlockGeometry()')
            check(geo and abs(geo['main']['south'] - m_south) < 1e-3 and
                  abs(geo['garage']['south'] - g_south) < 1e-3,
                  f'{label} {depths}: the street faces moved: {geo}')
            # the JS slot table still IS the Python one, depth and all
            js_slots = page.evaluate('window.chfFacadeSlots()')
            py_slots = hf.slot_table(spec['blocks'])
            check(len(js_slots) == len(py_slots), f'{label}: slot count')
            for a, b in zip(js_slots, py_slots):
                check(abs(a['z'] - b['z']) < 1e-6,
                      f"{label}: slot {b['i']} z {a['z']} vs {b['z']}")
            rows = {r['name']: r for r in page.evaluate('window.chfShellFabric()')}
            # FIX ROUND 1: the whole bay rides its own face -- the LEAF
            # is inside this box and was the one part left behind
            zc = (rows['garage_door']['box'][4] + rows['garage_door']['box'][5]) / 2
            check(abs(zc - (GARAGE_DOOR_ZC_0 + depths['garage'])) < 0.2,
                  f'{label}: the garage door assembly (leaf included) sits on '
                  f'its own face: centre z {zc:.3f}, want '
                  f'~{GARAGE_DOOR_ZC_0 + depths["garage"]:.3f}')
            check('main_return' not in rows,
                  f'{label}: the main block never gets a second west face')
            if want_return:
                check(want_return in rows, f'{label}: {want_return} registered')
                box = rows[want_return]['box']
                check(abs(box[4] - m_south) < 0.2 and abs(box[5] - g_south) < 0.2,
                      f'{label}: {want_return} closes the step: {box}')
            else:
                check('garage_return' not in rows,
                      f'{label}: no garage return wall wanted, got one')
                # the main block IS the deeper one here, and its west face
                # reaches its own street line. + 0.05: the corner board at
                # its end is 0.1 deep and centred on the face line, so the
                # box runs half past it
                check(abs(rows['west_skirt']['box'][5] - (m_south + 0.05)) < 0.02,
                      f"{label}: west_skirt reaches the main face: "
                      f"{rows['west_skirt']['box']}")
            # R-B: a depth opens a floor-less void behind the moved face
            for who, key in (('main', 'main_void_floor'), ('garage', 'garage_void_floor')):
                check((key in rows) == (depths[who] > 0),
                      f'{label}: {key} present iff {who} has depth')
            # the front door and the garage still read from the street,
            # and the Mudroom marker's own roof piece still resolves
            # through roofAlias whatever the clip dropped
            check(page.evaluate("window.chfNavProbe({front:'main'})"),
                  f'{label}: the front door is reachable from the street')
            check(page.evaluate("window.chfNavProbe({front:'garage_block'})"),
                  f'{label}: the garage front is reachable from the street')
            check(page.evaluate("window.chfNavProbe({piece:'garage_block_roof_south'})"),
                  f'{label}: the Mudroom marker still lands on a roof piece')
            meet = page.evaluate('window.chfBlockMeet()')
            check(meet['main']['active'] is want_meet and
                  meet['garage']['active'] is want_meet,
                  f'{label}: the block-meet clip active={want_meet}, got '
                  f"{meet['main']['active']}/{meet['garage']['active']}")
            leak = page.evaluate(ROOF_INSIDE_NEIGHBOUR_JS)
            check(not leak.get('err'), f'{label}: audit ran: {leak}')
            # FIX ROUND 1: the exact surviving block-roof set, so a piece
            # the clip swallows whole can never vanish unnoticed
            check(set(leak['pieces']) == all_roof,
                  f'{label}: block roof pieces {sorted(leak["pieces"])} != '
                  f'{sorted(all_roof)}')
            if want_meet:
                check(leak['main_in_garage'] == 0 and leak['garage_in_main'] == 0,
                      f'{label}: roof left inside the neighbour volume: {leak}')
            if base_main_out is None:
                base_main_out, base_garage_out = leak['main_out'], leak['garage_out']
            check(leak['main_out'] > 0.9 * base_main_out,
                  f'{label}: main roof kept outside the neighbour: {leak}')
            # the garage roof keeps its own volume too, at the same
            # 0.9 floor -- NOTHING is legitimately removed whole in any
            # of these five boots (both blocks' north faces sit on
            # z -6.10 and each roof overhangs 0.32 past it, which is
            # outside the neighbour's footprint, so every one of the
            # eight pieces keeps at least its own north tip). MEASURED
            # counts per boot in task-6-report.md.
            check(leak['garage_out'] > 0.9 * base_garage_out,
                  f'{label}: garage roof kept outside the neighbour: {leak}')
            # nothing outside the neighbour's volume is lost: the main
            # roof still runs its whole east/south footprint plus the
            # 0.32 overhang
            span = leak['main_span']
            check(span[1] > 14.65 + 0.32 - 0.02 and span[3] > m_south + 0.32 - 0.02,
                  f'{label}: the main roof still covers its own block: {span}')
            b = page.evaluate(BUDGET_JS)
            print('  %-24s %r inFrustum=%s calls=%s buildMs=%s main_out=%s garage_out=%s'
                  % (label, depths, b.get('inFrustum'), b.get('calls'),
                     b.get('buildMs'), leak['main_out'], leak['garage_out']))
            errs = [e for e in served.errors() if 'WebGL' not in e]
            check(not errs, f'{label}: console clean: {errs[:3]}')


if __name__ == '__main__':
    scenario_canonical_facade_pins_the_hand_built_elevation()
    scenario_worst_case_facade_builds_clean()
    scenario_roof_features_stop_at_the_roof_line()
    scenario_a_saved_gable_over_the_study_stays_outside()
    scenario_a_draft_token_renders_day_locked_and_captures()
    scenario_a_bad_draft_token_is_not_an_error()
    scenario_depth_moves_the_face_and_the_blocks_meet()
    # Last: it boots six browsers of its own, and every scenario above
    # reads mesh counts out of the shared temp data dir this one seeds.
    scenario_claddings_and_base_band()
    print("test_house_facade_live OK")
