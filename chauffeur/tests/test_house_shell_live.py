"""The Home's shell in real chromium: fabric registry, view-volume
masking, the room cutaways, the vaulted interior partitions, the mesh
clipper, per-mesh convexity, and the study's own box.

Split out of test_house_live.py (Task 7) so tools/test.py's parallel sweep
can spread the file's ~21 Chromium scenarios across workers. This file
holds the shell/mask/vault/clipper/convexity/study-box scenarios; boot/
lifecycle/leak scenarios stayed in test_house_live.py, navigation/orbit/
swipe/idle moved to test_house_nav_live.py, and the facade pin/worst case/
roof-line audit/saved-facade reproduction moved to
test_house_facade_live.py. Shared helpers live in house_live_common.py
— imported, never run on its own.

Run from chauffeur/:  python tests/test_house_shell_live.py
"""
import json
import os
import math as _math
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools'))
os.environ.setdefault('CHAUFFEUR_DATA_DIR',
                      tempfile.mkdtemp(prefix='chauffeur_house_shell_live_'))

from live_app import live_app
from house_live_common import (check, _seed, DAY_LOCK_JS, _VAULT_PITCH,
                               roof_piece_names)


def scenario_shell_fabric_registry():
    """Two rectangles, two block roofs: the footprint pin and the
    authored mask table.

    MASSING ARC 1 (spec 2026-09-16-regular-house-orbit-design.md,
    sections 2 and 3). The registered set is the spec's kept+new lists
    and nothing else; the deleted massing may not survive under any
    name. The roof slopes still run north/south on both blocks.

    VIEW-VOLUME MASKING (spec 2026-09-16 masking, task 3): the solver's
    per-piece verdicts are gone. A piece's verdict in a room view is
    'masked' exactly when the build-time mask for that room cut some of
    it (maskedFraction > 0) and 'solid' otherwise; the exterior has no
    mask and keeps every piece solid. EXPECTED below names, per view,
    the pieces the mask MUST cut (more than a tenth of their area) and
    the pieces it MUST leave whole, each with its derivation from the
    mask (P: the pyramid from the room camera through the room box's
    silhouette; W: behind the box's front faces; masked = P and not W).
    """
    served = live_app()
    if served is None:
        return
    with served.browser() as page:
        # DAY_LOCK_JS (Task 3): the mudroom door's hero card renders a
        # live leave-in-N-minutes countdown off the real wall clock
        # (house.js's isNight()/countdown maths read `new Date()`
        # directly), which would otherwise drift the mudroom screenshot's
        # pixels test-run to test-run for reasons that have nothing to do
        # with ghost edges. Registered before goto() so it wins the race
        # against house.js's own module-scope closures, same idiom as the
        # other live scenarios in this file that already need it.
        page.add_init_script(DAY_LOCK_JS)
        # quality=high, wait_for_selector + a 2200ms settle: the same
        # boot idiom tools/house_probe.py uses ahead of its own reads,
        # not the has_room-and-skip dance the other scenarios in this
        # file use -- there is nothing tier-dependent to skip here: every
        # regFabric() call site sits outside any DETAIL/quality
        # conditional (read at implementation time), so the registry's
        # shape does not depend on which tier boots.
        page.goto(served.url('house?quality=high'))
        page.wait_for_selector('#room canvas', timeout=20000)
        page.wait_for_timeout(2200)
        fab = page.evaluate("window.chfShellFabric()")
        names = sorted(f['name'] for f in fab)
        # MASSING ARC 1 (spec section 2): the footprint pin. KEPT is the
        # spec's own "kept as-is" list, NEW its "new pieces" list, and
        # DELETED_PREFIXES every name the spec deletes -- so a piece that
        # quietly survives the massing cull fails here by name.
        # VIEW-VOLUME MASKING (task 4, spec section 5): the x 6.85 splits
        # the cutaway-ownership fix made (v2.499.41: roof_main_west /
        # roof_main_east, south_wall / south_wall_east) are folded back.
        # The mask cuts a piece only where it stands between a room
        # camera and that room's box, so one street wall and one roof
        # over the whole main block are exactly what the regular-house
        # spec named: roof_main's four pieces, south_wall in one run
        # x -7.15..14.65.
        # STUDY REFIT (2026-09-16): patio_slider is retired. Its glass
        # moved to the study's own opening (living_study_door, unchanged
        # by name) and the opening it used to fill at z 5.80 wears the
        # plain interior door the study gave up -- east_room_door.
        KEPT = {'north_wall', 'north_cladding', 'west_wall', 'west_skirt',
                'west_cladding', 'south_wall', 'garage_shell', 'garage_door',
                'east_room_door', 'living_back_room_door', 'living_study_door',
                'yard'} | roof_piece_names('roof_main', 'gable', 'x')
        # BLOCKS (spec 2026-09-17 section 0): the four names per block roof
        # come from roof_piece_names(), which encodes shellGable's own
        # naming -- so when form and ridge become settings this pin reads
        # the default (gable, ridge x) rather than four frozen literals.
        NEW = {'east_wall', 'east_partition', 'north_wall_east',
               'garage_block_north', 'garage_block_west', 'mudroom_front',
               'back_door', 'future_room_partition'} | roof_piece_names(
                   'garage_block_roof', 'gable', 'x')
        DELETED_PREFIXES = ('massing_', 'mudroom_cross_roof', 'mudroom_roof',
                            'living_roof', 'mudroom_front_cladding',
                            'mudroom_east_finish')
        hand_names = KEPT | NEW
        hand = {n for n in names if not n.startswith('facade_')}
        check(KEPT <= hand, f'kept pieces missing: {sorted(KEPT - hand)}')
        check(NEW <= hand, f'new pieces missing: {sorted(NEW - hand)}')
        check(not [n for n in hand if n.startswith(DELETED_PREFIXES)],
              'deleted pieces still registered: '
              f'{[n for n in hand if n.startswith(DELETED_PREFIXES)]}')
        check(hand == hand_names,
              f'unexpected hand pieces: {sorted(hand - hand_names)}')
        generated = sorted(n for n in names if n.startswith('facade_'))
        check(set(names) == hand_names | set(generated),
              'nothing registers that is neither hand-authored nor generated: %r'
              % sorted(set(names) - hand_names - set(generated)))
        # Every generated piece traces back to a CANONICAL feature: the
        # name carries its own face, kind and slot, and shellGable's
        # _west/_east/_front suffixes ride on the end.
        import re as _re
        from services import house_facade as _hf
        canon = {(f['slot'], f['kind'])
                 for f in _hf.CANONICAL['ground'] + _hf.CANONICAL['roof']}
        slots = _hf.slot_table()
        check(generated, 'the elevation must register generated pieces')
        # face names can themselves carry an underscore now (garage_block),
        # so the alternation is built from the actual faces rather than a
        # bare [a-z]+ that would stop at the first one.
        faces_pat = '|'.join(sorted({s['face'] for s in slots}, key=len, reverse=True))
        for gen in generated:
            m = _re.match(r'^facade_(' + faces_pat + r')_([a-z_]+?)_(\d+)(_[a-z_]+)?$', gen)
            check(m is not None,
                  'generated name must read facade_<face>_<kind>_<slot>: ' + gen)
            face, kind, slot = m.group(1), m.group(2), int(m.group(3))
            check(slots[slot]['face'] == face,
                  '%s names slot %d, which is on the %s face' % (gen, slot, slots[slot]['face']))
            check((slot, kind) in canon,
                  '%s must come from a CANONICAL feature' % gen)
        # arc 4 prerequisite (spec §6): AO occluders come FROM the registry.
        # south_wall/east_wall's registered box is fabBox() of the WHOLE
        # group, which may run larger than the old hand row once porch/trim
        # decor is folded in (measured: south_wall's registered z-range
        # runs 13.95-19.8 against the hand row's tight 14.2-14.55, and
        # east_wall's x-min sits 0.06 outside the old exact-match
        # tolerance) -- so this asserts CONTAINMENT (the registered box
        # covers the hand row's old footprint within tol), not equality.
        occ = page.evaluate("window.chfAoOccluders()")
        def contains_box(b, tol=0.05):
            return any(o[0] <= b[0] + tol and o[1] >= b[1] - tol and
                       o[2] <= b[2] + tol and o[3] >= b[3] - tol and
                       o[4] <= b[4] + tol and o[5] >= b[5] - tol
                       for o in occ)
        # MASSING ARC 1: the south wall is the whole main front now
        # (x -7.15..14.65) and the piece at x 6.5..6.85 is east_partition,
        # the interior wall the old east_wall became; the main's own east
        # side stands out at x 14.65. All three still occlude.
        # one run again (task 4): the great room's front AND the study's
        # street face are the same registered box.
        check(contains_box([-6.5, 14.5, 0.0, 5.6, 14.2, 14.55]),
              'south_wall must occlude via its registered box')
        # 14.20, not 14.55: the fix wave stopped the partition at SWZ0,
        # the south wall's INNER face, so its end stops being coplanar
        # with the street siding (a coplanar plaster end draws a pale
        # stripe down the front elevation). It still occludes the whole
        # run; only the last 0.35 of it belongs to south_wall now.
        check(contains_box([6.5, 6.85, 0.0, 5.6, -5.725, 14.20]),
              'east_partition must occlude via its registered box')
        check(contains_box([14.30, 14.65, 0.0, 5.6, -5.725, 14.55]),
              'east_wall must occlude via its registered box')
        wallish = [f for f in fab if abs(f['n'][1]) < 0.5]
        check(len(occ) >= len(wallish),
              f'every wall-like piece contributes an occluder: {len(occ)} < {len(wallish)}')
        by_name = {f['name']: f for f in fab}
        # MASSING ARC 1 (spec section 3): two block roofs, both at the
        # same eave (GARAGE_BLOCK.eave IS EXT_TOP4 = 5.6), so their south
        # decks share one eave line -- what makes a roof feature run
        # coplanar across the old garage/mudroom boundary. shellGable's
        # deck box bottom is the eave edge of that deck, so comparing the
        # two boxes' y-min is comparing the two eave lines.
        check(abs(by_name['garage_block_roof_south']['box'][2] -
                  by_name['roof_main_south']['box'][2]) < 0.02,
              'both block roofs must start at the same eave height: %r vs %r'
              % (by_name['garage_block_roof_south']['box'][2],
                 by_name['roof_main_south']['box'][2]))
        # VIEW-VOLUME MASKING (task 4): the main roof is ONE roof again.
        # Each slope deck runs the whole block plus one overhang at each
        # end (x -7.15 - 0.32 .. 14.65 + 0.32; the deck box also holds
        # the eave trim, which is the same length), and nothing of it
        # ends or starts at the old 6.85 split.
        for side in ('north', 'south'):
            d = by_name['roof_main_' + side]['box']
            check(abs(d[0] - (-7.15 - 0.32)) < 0.05 and
                  abs(d[1] - (14.65 + 0.32)) < 0.05,
                  'the main roof deck runs the whole block plus its '
                  'overhangs (%s): %r' % (side, d))
        # roof_main reaches the main block's own east wall: the east
        # gable end sits one overhang past FULL_HOUSE.east (14.65) and
        # its rake board 0.08 further still.
        check(14.65 <= by_name['roof_main_end_east']['box'][1] <= 14.65 + 0.32 + 0.20,
              'roof_main must reach the east wall + one overhang: %r'
              % by_name['roof_main_end_east']['box'][1])
        # The two side decks of one block roof share a ridge and a pitch:
        # mirrored normals, same |y|.
        north = by_name['roof_main_north']['normal']
        south = by_name['roof_main_south']['normal']
        check(abs(north[1] - south[1]) < 0.001 and
              abs(north[2] + south[2]) < 0.001 and north[2] < 0 < south[2],
              'the main roof must be two mirrored slopes: %r %r' % (north, south))
        # MASSING ARC 1 (spec section 3): the canonical row is what the
        # scene reports building from, and window.HOUSE_ROOF_FORMS is
        # absent here, so both blocks must read gable / ridge x.
        check(page.evaluate('window.chfRoofForms()') ==
              {'main': {'form': 'gable', 'ridge': 'x'},
               'garage': {'form': 'gable', 'ridge': 'x'}},
              'the canonical block roofs are gables with an east-west '
              'ridge: %r' % page.evaluate('window.chfRoofForms()'))
        # VIEW-VOLUME MASKING (task 4, spec section 5): the verdict
        # machinery is retired -- no row carries an owners table, a
        # cutaway room, a two-sided flag, a hide/ghost mode, a plane or
        # a pad any more. The yard's hide is a mask fact now (fraction 1
        # in every room view, pinned per view below), not a mode.
        RETIRED = ('owners', 'cutawayRoom', 'twoSided', 'mode', 'plane', 'pad')
        leftovers = sorted('%s.%s' % (f['name'], k) for f in fab for k in RETIRED if k in f)
        check(not leftovers, 'retired verdict fields still reported: %r' % leftovers[:6])
        check(all(f['visible'] for f in fab),
              'exterior boot: every piece visible (solid): %r' % fab)

        # VIEW-VOLUME MASKING (task 3): per view, the pieces the mask must
        # cut (> 0.1 of their surface) and must leave whole (exactly 0).
        # Room boxes (chfRoomMask): kitchen x -10.39..6.5 z -5.8..5.8;
        # living x -6.5..6.5 z 5.1..14.22; study x 6.92..15.25 z
        # 7.12..14.45; garage x -17.96..-12.83 z 2.21..9.76; mudroom x
        # -12.6..-6.8 z 2.36..8.3; every one y 0..5.6 (floor to eave).
        EXPECTED = {
            # the sealed house: no mask at all
            'exterior': {'masked': [], 'whole': []},
            # RULING 3 (fix round 1): the yard (yardG whole) hides in every
            # room view, fraction 1, as the old mode:'hide' verdict did.
            # RULING 1: a facade roof feature drops whole below a fifth
            # kept -- the porch gable's decks in the living view.
            # kitchen -- HOME_POS (4.64, 13.8, 23.0), high in the street.
            # The box's near face (z 5.8) is INSIDE the open great room:
            # the pyramid's floor plane, through the camera and the box's
            # bottom-south edge, crosses the street wall's plane at y 6.9
            # -- above the wall (5.6). So the street wall, its windows,
            # its door and the porch are between the camera and the
            # LIVING room only, and stay. What is in the way is the roof:
            # the south deck comes off from the eave to where the ray to
            # the far-top edge crosses it (z ~7.9); the porch gable's two
            # decks stand in that same cone above the eave; and because
            # the kitchen box runs west to x -10.39 (the pantry nook
            # behind the great room's west wall, tagged kitchen), the
            # main roof's west gable end, the mudroom's east gable end,
            # the west wall's living-room run and its exterior skirt all
            # stand between the street camera and that nook.
            # TASK 4 (un-split): roof_main_south is the whole block's
            # deck now, so the kitchen's cut (0.47 of the old west half,
            # 14.32 of the deck's 22.44 run) reads ~0.30 of the one deck
            # -- still > 0.1; the north deck takes a hairline at its west
            # end (0.006 of the old half), so it is neither list.
            'kitchen': {'masked': ['roof_main_south', 'roof_main_end_west',
                                   'garage_block_roof_end_east', 'west_wall',
                                   'west_skirt', 'facade_main_gable_8_west',
                                   'facade_main_gable_8_east'],
                        'whole': ['south_wall', 'facade_main_window_7',
                                  'facade_main_window_9', 'facade_main_window_12',
                                  'facade_main_door_10', 'facade_main_porch_8',
                                  'east_partition', 'east_wall', 'north_wall',
                                  'north_wall_east', 'future_room_partition',
                                  'facade_main_window_15', 'facade_main_window_16',
                                  'garage_door', 'garage_block_west']},
            # living -- LIV_POS (0, 12.8, 26.5). The box reaches the
            # street wall's inner face (14.22 vs 14.20), so the wall
            # straddles the box's south face and is cut by P alone: the
            # room's silhouette projected onto it, nearly all of it. Its
            # windows 7/9/12 and door 10 are kits in that wall (centre
            # masked, whole). The south deck comes off from the eave to
            # z ~10; the porch gable's decks and front stand in the cone.
            # The porch itself (fix round 1: NOT a kit, clipped per mesh):
            # its slab, steps and rails lie under the pyramid's floor
            # plane (a ray to the room's floor passes 2.9 above the porch
            # at z 17) and stay; its eave beam and post tops stand in the
            # cone and are cut (0.13 of the row). The study's windows
            # are east of the pyramid's x span; its street face and its
            # roof are the EAST PARTS of south_wall and roof_main_south
            # (task 4, one wall and one deck again), which the pyramid
            # cuts only over the great room -- the study's own run of
            # both stands, pinned by remnant vertex in
            # scenario_a_room_cutaway_leaves_other_rooms_enclosed. The
            # kitchen's north wall is behind the box, inside W.
            'living': {'masked': ['south_wall', 'roof_main_south',
                                  'facade_main_window_7', 'facade_main_window_9',
                                  'facade_main_window_12', 'facade_main_door_10',
                                  'facade_main_gable_8_west', 'facade_main_gable_8_east',
                                  'facade_main_gable_8_front', 'facade_main_porch_8'],
                       'whole': ['facade_main_window_15', 'facade_main_window_16',
                                 'east_partition', 'east_wall', 'north_wall',
                                 'north_wall_east', 'future_room_partition',
                                 'roof_main_north',
                                 'garage_door', 'mudroom_front']},
            # garage -- GARAGE_POS (-18.0, 10.5, 21.3), 0.04 west of the
            # box's west face: south, top and (a sliver of) west faces
            # are front. The garage door fills the south face: kit,
            # centre masked, whole. The bay gable's front and decks and
            # the block roof's south deck are cut where the cone passes
            # to the box's top face. The north wall of the block, the
            # mudroom's own front and the main block are outside P or
            # inside W.
            'garage': {'masked': ['garage_door', 'facade_garage_block_gable_0_front',
                                  'facade_garage_block_gable_0_west',
                                  'facade_garage_block_gable_0_east',
                                  'garage_block_roof_south'],
                       'whole': ['garage_block_north', 'garage_block_west',
                                 'mudroom_front', 'west_wall', 'south_wall',
                                 'north_wall', 'roof_main_south']},
            # mudroom -- MUD_POS (-3.4, 6.2, 11.2), in the great room
            # east of the box, just above the eave, south of it. The
            # great room's west wall (slab x -7.15..-6.8) touches the
            # box's east face and is cut where the box projects onto it;
            # its exterior skirt and cladding stand behind it in the
            # same cone; mudroom_front's inner layer (z 7.94..8.3)
            # straddles the south face and is cut where it stands in P.
            # The garage-block roof: a camera 0.6 above the eave sees the
            # top face edge-on, so the deck is grazed at its overhang and
            # no more -- the room is seen THROUGH the wall, not the roof.
            'mudroom': {'masked': ['west_wall', 'west_cladding', 'west_skirt',
                                   'mudroom_front'],
                        'whole': ['garage_door', 'garage_block_north',
                                  'garage_block_west', 'south_wall', 'north_wall',
                                  'roof_main_south', 'east_partition']},
            # study -- STUDY_POS (7.02, 4.75, 18.82), east of the old
            # split line and below the eave: the south face is the only
            # front face. The street face straddles it (the study floor
            # reaches z 14.45, the wall's inner face is 14.20) and is cut
            # by P alone -- TASK 4: that face is the east 7.8 of the one
            # 21.8-wide south_wall, so 0.97 of the old south_wall_east
            # reads ~0.35 of the whole wall (> 0.1; the great room's run
            # of it stands, pinned by remnant vertex in
            # scenario_a_room_cutaway_leaves_other_rooms_enclosed).
            # Windows 15/16 are kits in it, whole. east_partition is
            # beside the camera (x 6.44..6.85 < 6.92), not between it and
            # the room: the study keeps its own west wall as a backdrop.
            # The roof is above a camera that looks level into the room:
            # the top face is not front; the north deck stays whole and
            # the south deck is grazed at its overhang only (0.013 of the
            # old east half, ~0.005 of the one deck -- neither list). The
            # great room's windows are outside the pyramid's x span.
            'study': {'masked': ['south_wall', 'facade_main_window_15',
                                 'facade_main_window_16'],
                      'whole': ['east_partition', 'facade_main_window_7',
                                'facade_main_window_12', 'north_wall', 'north_wall_east',
                                'roof_main_north', 'living_study_door',
                                'east_room_door', 'garage_door']},
        }
        for view in EXPECTED:
            if view != 'exterior':
                EXPECTED[view]['masked'].append('yard')
        for view, expected in EXPECTED.items():
            if view == 'exterior':
                page.evaluate("window.chfHouseExit && window.chfHouseExit()")
            elif view == 'kitchen':
                page.evaluate("window.chfHouseEnter()")
            else:
                page.evaluate("window.chfHouseEnterRoom(%r)" % view)
            page.wait_for_timeout(1400)
            fab = page.evaluate("window.chfShellFabric()")
            by_view = {f['name']: f for f in fab}
            offed = sorted(f['name'] for f in fab if f['verdict'] != 'solid')
            # the verdict IS the fraction: 'masked' exactly where the mask
            # took something, 'solid' everywhere else
            if view == 'exterior':
                check(offed == [], 'exterior must mask NOTHING (the '
                      'sealed house, spec section 4): %r' % offed)
            else:
                cut = sorted(f['name'] for f in fab if f['maskedFraction'][view] > 0)
                check(offed == cut,
                      '%s: verdict masked <=> maskedFraction > 0, got %r vs %r'
                      % (view, offed, cut))
                for name in expected['masked']:
                    check(by_view[name]['maskedFraction'][view] > 0.1,
                          '%s: %s must be cut (> 0.1), got %r'
                          % (view, name, by_view[name]['maskedFraction'][view]))
                for name in expected['whole']:
                    check(by_view[name]['maskedFraction'][view] == 0,
                          '%s: %s must be whole, got %r'
                          % (view, name, by_view[name]['maskedFraction'][view]))
            # Task 4 sanity (spec section 3's own words: "the point of the
            # table is that a human wrote the expectation down") -- a mask
            # bug that cut everything (e.g. an inverted P plane) would
            # still slip past a membership check alone; this catches it
            # directly. Exterior's own emptiness is the sealed-house half
            # of the same guard (spec section 4: "Exterior: every piece
            # SOLID").
            check(len(offed) < len(fab),
                  '%s: the mask must not cut EVERY registered piece: %r'
                  % (view, offed))
            check(not any(f.get('edgesVisible') for f in fab),
                  '%s: cutaway wireframes must stay hidden: %r' % (view, fab))

            if view == 'mudroom':
                # west_wall receives the masked verdict (the great room's
                # wall opens onto the mudroom), but the touch-first
                # cutaway leaves its permanent edges hidden.
                west = [f for f in fab if f['name'] == 'west_wall'][0]
                check(west['verdict'] == 'masked',
                      "west_wall must verdict 'masked' in the mudroom, not "
                      "just non-solid: %r" % west)
                check(west.get('edgesVisible') is False,
                      'west_wall cutaway must not draw permanent wireframes')

        # The calendar's support stays visible just like the adjacent pantry.
        # Decor must not move the partition's visibility plane past its card.
        for zone in ['calendar', 'board']:
            page.evaluate("window.chfKitchenFocus(%r)" % zone)
            page.wait_for_function("window.chfNavProbe({settled:true})")
            wall = next(f for f in page.evaluate('chfShellFabric()')
                        if f['name'] == 'west_wall')
            check(wall['visible'], zone + ' must keep its plaster backing')

        page.evaluate("window.chfHouseEnterRoom('mudroom')")
        page.wait_for_function("window.chfNavProbe({settled:true})")
        door_hit = page.evaluate("window.chfNavProbe({zone:'door'})")
        check(door_hit is not None, 'card-bearing door must be tappable')
        page.mouse.click(door_hit['cx'], door_hit['cy'])
        page.wait_for_function("window.chfNavProbe({settled:true})")
        check(page.evaluate("window.chfNavProbe({settled:true}).focused") == 'door',
              'tapping the visible garage connection must focus the hero')

        for piece in ['south_wall', 'facade_main_gable_8_front']:
            page.evaluate("window.chfHouseExit()")
            page.wait_for_function("window.chfNavProbe({settled:true})")
            hit = page.evaluate("window.chfNavProbe({piece:%r})" % piece)
            check(hit is not None, '%s must be reachable from exterior' % piece)
            page.mouse.click(hit['cx'], hit['cy'])
            page.wait_for_function("window.chfNavProbe({settled:true})")
            check(page.evaluate("window.chfHouseMode()") == 'living',
                  '%s on the front facade must enter living' % piece)

        # MASSING ARC 1: east_wall is the roomless piece now -- the main
        # block's own east elevation fronts the study and two UNBUILT
        # rooms, so no single room owns a tap on it and it stays inert,
        # exactly as the massing it replaced did.
        page.evaluate("window.chfHouseExit()")
        page.wait_for_function("window.chfNavProbe({settled:true})")
        hit = page.evaluate("window.chfNavProbe({piece:'east_wall'})")
        check(hit is not None, 'the east elevation must have a reachable surface')
        page.mouse.click(hit['cx'], hit['cy'])
        check(page.evaluate("window.chfHouseMode()") == 'exterior',
              'the roomless east elevation must stay inert')

        # The opening at z 5.80 is the east room's plain interior door
        # now (STUDY REFIT: the glass went to the study). It keeps the
        # slider's registration semantics exactly -- room 'kitchen', a
        # leaf on each face -- so a camera standing in the east room
        # still taps through to the kitchen.
        page.evaluate("window.chfHouseCam(12,2.6,5.6,6.9,2,5.8)")
        page.wait_for_function("window.chfNavProbe({settled:true})")
        hit = page.evaluate("window.chfNavProbe({piece:'east_room_door'})")
        check(hit is not None,
              "the east room's door must be reachable from that room")
        page.mouse.click(hit['cx'], hit['cy'])
        page.wait_for_function("window.chfNavProbe({settled:true})")
        check(page.evaluate("window.chfHouseMode()") == 'kitchen',
              "the east room's door must enter the kitchen")

        # High quality chamfers the radio face. Its fallback projection must
        # use the radio's world X face after the parent rotates 90 degrees;
        # projecting the Z edge collapses the music card to a few pixels.
        page.evaluate("window.chfHouseEnterRoom('living')")
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        radio_hit = page.evaluate("window.chfNavProbe({zone:'radio'})")
        check(radio_hit is not None, 'high-tier radio must have a reachable face')
        page.mouse.click(radio_hit['cx'], radio_hit['cy'])
        page.wait_for_selector('#overlay-music', state='visible', timeout=20000)
        music_box = page.locator('#focus-overlay').bounding_box()
        check(music_box and music_box['width'] > 200,
              'high-tier music card must use the radio face, got %r'
              % music_box)

        errs = [e for e in served.errors()
                if 'WebGL' not in e and 'GroupMarker' not in e]
        check(not errs, 'no console errors: ' + '; '.join(errs[:3]))


def scenario_a_room_cutaway_leaves_other_rooms_enclosed():
    """A room's cutaway removes only what stands between its camera and
    the room.

    Cutaway-ownership fix (brief .superpowers/sdd/2026-09-16-cutaway-
    ownership/brief.md) first stated the user's rule: "Those rooms
    should remain and their walls and roofs should remain. You should
    only be seeing the thing you are looking at." It enforced it with an
    `owners` table and a solver that refused to ghost a non-owner's
    piece. VIEW-VOLUME MASKING (spec 2026-09-16 masking, task 3) enforces
    the same rule geometrically: per room, a build-time mask cuts a piece
    exactly where it lies between the room camera and the room's
    eave-high box, and nowhere else. So the general law is now: in every
    room view, every piece with maskedFraction 0 is whole and visible,
    every piece with maskedFraction > 0 is 'masked', and no kept vertex
    of the room's shell lies inside the mask (chfRoomShellLeak 0). The
    specific pieces the bug was reported on are then pinned by name from
    the living AND the kitchen, exactly as before. Task 4 retired the
    `owners` rows and folded the x 6.85 splits back (one south_wall, one
    roof_main), so the east rooms' street face and roof are now the EAST
    PARTS of pieces the great room's cameras also cut -- the enclosure
    law is pinned there by remnant vertex, not by a whole-piece 0.
    """
    served = live_app()
    if served is None:
        return
    with served.browser() as page:
        page.add_init_script(DAY_LOCK_JS)
        page.goto(served.url('house?quality=high'))
        page.wait_for_selector('#room canvas', timeout=20000)
        page.wait_for_timeout(2200)
        fab = page.evaluate("window.chfShellFabric()")
        check(all('maskedFraction' in f for f in fab),
              'every fabric row must report its maskedFraction per room')

        # The general law, per room view.
        for view in ('kitchen', 'living', 'study', 'garage', 'mudroom'):
            if view == 'kitchen':
                page.evaluate("window.chfHouseEnter()")
            else:
                page.evaluate("window.chfHouseEnterRoom(%r)" % view)
            page.wait_for_timeout(1400)
            rows = page.evaluate("window.chfShellFabric()")
            wrong = sorted(f['name'] for f in rows
                           if (f['maskedFraction'][view] == 0) != (f['verdict'] == 'solid'))
            check(not wrong,
                  "%s: a piece leaves exactly when the mask cut it: %r" % (view, wrong))
            hidden_whole = sorted(f['name'] for f in rows
                                  if f['maskedFraction'][view] == 0 and not f['visible'])
            check(not hidden_whole,
                  "%s: an untouched piece never hides: %r" % (view, hidden_whole))
            check(page.evaluate("window.chfRoomShellShown()") == view,
                  '%s: its own shell is the visible one' % view)
            leak = page.evaluate("window.chfRoomShellLeak(%r, 2000)" % view)
            check(leak == 0, '%s: no kept vertex inside the mask (got %r)' % (view, leak))

        # The reported pieces, pinned by name. From the living room and
        # from the kitchen the study and the two future rooms keep their
        # own walls: every one is east of the pyramid's x span from both
        # street cameras (the great room's boxes end at x 6.5).
        EAST_ENCLOSURE = ['east_partition', 'east_wall',
                          'future_room_partition', 'north_wall_east']
        # TASK 4: their street face and their roof are the east parts of
        # ONE south_wall (x -7.15..14.65) and ONE roof_main_south, so a
        # whole-piece 0 cannot say they stand any more. Two pins say it
        # instead. (1) The living's cut of south_wall cannot exceed the
        # great room's share of the wall: the wall's three boxes are the
        # same height and thickness the whole run, so area goes with
        # width, and the pyramid's x span at the wall is the box's own
        # (-6.5..6.5, 13 of 21.8 = 0.596); the old 14-wide segment read
        # 0.871, which is 0.559 of the one wall. Pinned 0.5 < f < 0.6.
        # (2) The study's run of the wall (x > 6.85) and of the south
        # deck leave remnant vertices in the living shell -- the piece
        # stands there, cut only over the great room. The north deck
        # is not cut from the living at all (0), and from the kitchen
        # only at a hairline (< 0.01; its old west half read 0.006).
        for view in ('living', 'kitchen'):
            if view == 'kitchen':
                page.evaluate("window.chfHouseEnter()")
            else:
                page.evaluate("window.chfHouseEnterRoom(%r)" % view)
            page.wait_for_timeout(1400)
            by = {f['name']: f for f in page.evaluate("window.chfShellFabric()")}
            for name in EAST_ENCLOSURE:
                check(name in by, '%s must be registered' % name)
                check(by[name]['maskedFraction'][view] == 0 and by[name]['verdict'] == 'solid',
                      "%s: %s must stay whole, got %r / %r"
                      % (view, name, by[name]['maskedFraction'][view], by[name]['verdict']))
            check(by['roof_main_north']['maskedFraction'][view] < 0.01,
                  '%s: the north deck is not between a street camera and '
                  'the great room, got %r' % (view, by['roof_main_north']['maskedFraction'][view]))
            for piece in ('south_wall', 'roof_main_south'):
                verts = page.evaluate("window.chfRoomShellVerts(%r, %r, 4000)" % (view, piece))
                east = [p for p in verts if p[0] > 6.85]
                check(by[piece]['maskedFraction'][view] == 0 or east,
                      "%s: the study's run of %s (x > 6.85) must stand in the "
                      'shell, got fraction %r and %d remnant vertices east of '
                      'the old split' % (view, piece, by[piece]['maskedFraction'][view], len(east)))
            if view == 'living':
                check(0.5 < by['south_wall']['maskedFraction']['living'] < 0.6,
                      "living: south_wall is cut over the great room's run only "
                      '(0.559 derived), got %r' % by['south_wall']['maskedFraction']['living'])

        # The study's OWN cutaway: its street face -- the east 7.8 of the
        # one south_wall -- is cut along the room's silhouette and the
        # great room's run of the same wall stays (remnant vertices west
        # of x 6.5). Its roof is NOT cut: STUDY_POS (y 4.75) stands below
        # the eave looking level into the room, so the box's top face is
        # not a front face and no ray to the walled volume passes through
        # the roof -- the old solver hid the whole east half of the roof
        # by cutawayRoom, which is exactly the kind of whole-piece surgery
        # the mask retires. The one south deck is grazed at its overhang
        # at most (0.013 of the old east half, 8.12 of 22.44 = ~0.005).
        page.evaluate("window.chfHouseEnterRoom('study')")
        page.wait_for_timeout(1400)
        by = {f['name']: f for f in page.evaluate("window.chfShellFabric()")}
        for name in ('roof_main_north', 'roof_main_end_east', 'roof_main_end_west'):
            check(by[name]['maskedFraction']['study'] < 0.01,
                  "study: %s must stay (whole or a hairline), got %r"
                  % (name, by[name]['maskedFraction']['study']))
        check(by['roof_main_south']['maskedFraction']['study'] < 0.05,
              "study: the deck over the study is grazed at most, got %r"
              % by['roof_main_south']['maskedFraction']['study'])
        # 0.97 of the old 7.8-wide segment is 0.347 of the 21.8 wall;
        # the cut cannot exceed the study's share (7.8 / 21.8 = 0.358).
        check(by['south_wall']['verdict'] == 'masked' and
              0.3 < by['south_wall']['maskedFraction']['study'] < 0.36,
              "study: its street face (the east run of south_wall) must be "
              'cut, got %r' % by['south_wall']['maskedFraction']['study'])
        west = [p for p in page.evaluate("window.chfRoomShellVerts('study', 'south_wall', 4000)")
                if p[0] < 6.5]
        check(west, "study: the great room's run of south_wall must stand in the shell")


def scenario_study_sits_inside_the_main_block():
    """Regular house + orbit, task 1: the study lives inside the main
    rectangle (x 6.85..14.65, z 7.65..14.55), not in the old front wing
    that used to project past it. chfStudyBox() unions the study's
    furniture root, its house-scale architecture, and its zone proxies
    into one world Box3, exactly as scenario_shell_fabric_registry
    already reads chfShellFabric() for the shell -- a read-only debug
    hook, not a new gameplay surface.
    """
    served = live_app()
    if served is None:
        return
    with served.browser() as page:
        page.goto(served.url('house?quality=high'))
        page.wait_for_selector('#room canvas', timeout=20000)
        page.wait_for_timeout(2200)
        page.evaluate("window.chfHouseEnterRoom('study')")
        page.wait_for_timeout(1400)

        check(page.evaluate("typeof window.chfStudyBox === 'function'"),
              'chfStudyBox must exist so a test can pin the study to its '
              'own world bounding box without guessing at scene internals')
        box = page.evaluate("window.chfStudyBox()")
        check(box is not None, 'chfStudyBox must report a box once the '
              'study has been entered')
        check(box[5] <= 14.56,
              'the study must not reach past the main block\'s street '
              'face (z 14.55): max z %r' % (box[5],))
        check(box[4] >= 7.5,
              'the study must sit south of the future rooms (z 7.65 is '
              'its new north wall): min z %r' % (box[4],))


def scenario_the_study_faces_east_behind_glass_doors():
    """STUDY REFIT (2026-09-16, .superpowers/sdd/2026-09-16-study-refit).

    Two user requests in one pass.

    (A) DOORS. "The patio door is still there even though the patio
    turned into a regular inside room. That door might actually make a
    good door for the study as those commonly have double glass doors.
    And then use the study's regular interior door on that other room."
    So the glazing moved to the study's own opening at z 9.93 -- which
    keeps the name `living_study_door`, its registration, its room
    stamping and its parent-PIN gate -- and the opening at z 5.80 wears
    the plain interior door, registered `east_room_door` with the
    slider's old semantics (normal [1,0,0], room 'kitchen'; it was
    twoSided and ownerless under the verdict solver, which task 4 of the
    masking arc retired -- a kit now, whole or nothing by its box).
    `patio_slider` is retired by name.

    (B) THE STUDY FACES EAST. "The study layout doesn't make sense now
    that the patio is gone. The window needs to be on the east wall and
    the items on the east wall need to move to the north wall." The
    east wall is the only EXTERIOR wall the room has, and the house
    already carries a pane on it at z 11.10, so the window lines up
    with it; the shelf/library/board wall turns onto the north wall,
    which is the interior one it shares with the east room.

    Both halves are asserted from the scene itself -- the fabric
    registry for the doors, the study's own zone proxies for the window
    and the board -- never from a constant the code also reads.
    """
    served = live_app()
    if served is None:
        return
    with served.browser() as page:
        page.add_init_script(DAY_LOCK_JS)
        page.goto(served.url('house?quality=high'))
        page.wait_for_selector('#room canvas', timeout=20000)
        page.wait_for_timeout(2200)

        # ---- A: the doors swapped -------------------------------------
        fab = {f['name']: f for f in page.evaluate("window.chfShellFabric()")}
        check('patio_slider' not in fab,
              'patio_slider must be retired by name, not left registered '
              'beside its replacement')
        door = fab.get('east_room_door')
        check(door is not None,
              "the east room's opening must register as east_room_door; "
              'registered: %r' % sorted(fab))
        check(door and door['room'] == 'kitchen',
              "east_room_door keeps the slider's room stamping so a tap "
              'on it still enters the kitchen, got %r'
              % (door and door['room'],))
        check(door and door['normal'] == [1, 0, 0],
              "east_room_door keeps the slider's normal (it stands in the "
              'east partition, facing x), got %r' % (door and door['normal'],))
        check(door and 'twoSided' not in door and 'owners' not in door,
              'the verdict fields are retired (masking task 4): an opening '
              'is a kit the mask keeps or drops whole, got %r'
              % (door and sorted(door),))

        glass = fab.get('living_study_door')
        check(glass is not None,
              'the study door keeps its name through the glazing swap')
        check(glass and glass['interiorGlow'] == 0,
              "the study's glass is INTERIOR glazing -- both sides of it "
              'are indoors -- so it never takes the exterior night glow, '
              'got %r' % (glass and glass['interiorGlow'],))
        span = glass['box'][5] - glass['box'][4] if glass else 0
        check(span > 2.6,
              'the double doors must fill the widened 2.65 opening at '
              'z 9.93, got a %.2f span' % span)

        # the entry survived the builder swap: the doors are still the
        # study's own tap, and test_house_life_live walks the PIN behind it.
        page.evaluate("window.chfHouseEnterRoom('living')")
        page.wait_for_function("window.chfNavProbe({settled:true})")
        check(page.evaluate("window.chfNavProbe({action:'study'})") is not None,
              'the glass doors must still carry the study entry')

        # ---- B: the study faces east ----------------------------------
        page.evaluate("window.chfHouseEnterRoom('study')")
        page.wait_for_timeout(1400)
        check(page.evaluate("typeof window.chfStudyZone === 'function'"),
              'chfStudyZone must exist so a test can pin which wall a '
              "study signal hangs on, read off the room's own zone proxy")
        win = page.evaluate("window.chfStudyZone('study_window')")
        check(win is not None, 'the study window zone must report a box')
        wx = (win[0] + win[1]) / 2 if win else 0
        wz = (win[4] + win[5]) / 2 if win else 0
        check(wx > 14.0,
              'the study window must hang on the EAST wall (x 14.52), '
              'got centre x %r' % wx)
        check(abs(wz - 11.10) < .35,
              "the study window must line up with the house's own east "
              'pane at z 11.10, got centre z %r' % wz)
        for key in ('study_board', 'study_binders'):
            zb = page.evaluate("window.chfStudyZone(%r)" % key)
            check(zb is not None, '%s must report a box' % key)
            cz = (zb[4] + zb[5]) / 2 if zb else 0
            check(7.6 < cz < 8.6,
                  '%s must have turned onto the NORTH wall (z 7.71), got '
                  'centre z %r' % (key, cz))
            cx = (zb[0] + zb[1]) / 2 if zb else 0
            # east of the study door's corner (the west partition is at
            # x 6.85): the turned set runs world x 8.57..13.76 of a
            # 6.92..14.18 wall, biased as far east as the wall map --
            # the one other thing hanging on the north wall -- allows.
            check(cx > 8.4,
                  '%s must sit on the north wall east of the study door '
                  'corner, got centre x %r' % (key, cx))

        # the room itself did not grow: a rigid turn moves nothing out.
        box = page.evaluate("window.chfStudyBox()")
        check(box is not None and box[1] <= 14.60 and box[0] >= 6.80,
              'the refit must stay between the partition and the east '
              'wall: x %r' % (box and [box[0], box[1]],))
        check(box is not None and box[5] <= 14.56 and box[4] >= 7.5,
              'the refit must stay inside the study: z %r'
              % (box and [box[4], box[5]],))


# ---- VAULTED PARTITIONS (2026-09-16) ---------------------------------
# The roof's own arithmetic, re-derived HERE from the spec's dimensions
# (docs/superpowers/specs/2026-09-16-regular-house-orbit-design.md section
# 2: the main block x -7.15..14.65, z -6.10..14.55, eave 5.6; the garage
# block z -6.10..10.10, same eave; family pitch pi/8 on both) rather than
# read back out of the scene that also uses it. house.js's roofVault()
# and shellGable() each derive the same numbers a third and a second
# time -- both now reading the single BLOCK_PITCH constant house.js
# hoists above its first use (v2.499.60), rather than four separate
# `Math.PI / 8` literals -- so a change to it fails a pin here.
# (_VAULT_PITCH itself lives in house_live_common.py: test_house_facade_live.py's
# roof-line audit needs the same pitch constant.)
#
#   ridge = eave + 0.18 + half * tan(pitch)        the deck's CENTRE plane
#   under = ridge - d * tan(pitch) - 0.09/cos(pitch)    its LOWER face,
#           measured down the vertical, d from the ridge line
_VAULT_GAP = 0.02          # house.js holds every wall top this far under
_MAIN_BLOCK = (-6.10, 14.55, 5.6)
_GARAGE_BLOCK = (-6.10, 10.10, 5.6)


def _deck_underside(block, at):
    north, south, eave = block
    half = (south - north) / 2.0
    ridge_y = eave + 0.18 + half * _math.tan(_VAULT_PITCH)
    return (ridge_y - abs(at - (north + south) / 2.0) * _math.tan(_VAULT_PITCH)
            - 0.09 / _math.cos(_VAULT_PITCH))


def scenario_interior_walls_rise_to_the_roof():
    """Vaulted partitions, and wall above every interior door.

    User report (2026-09-16, a screenshot of the living view): "Look at
    the left side vs the right side. There isn't any geometry on the
    right side to cover the top part. In a real house there would either
    be dropped ceilings with attic space above or vaulted ceilings where
    the walls go all the way up. Assume vaulted ceilings, so the walls
    should go all the way up. Also, even without that assumption, there
    are sections of the wall above two of the doors that are missing."

    Two pins, because the two halves of that report are two different
    facts. A registered piece's BOX says the group grew to the deck --
    that is the vault. Only a RAY says there is plaster at a particular
    point -- that is the header, and the wall between a door head and
    the roof above it. Both are read at the exterior, where the cutaway
    solver leaves every piece solid.
    """
    served = live_app()
    if served is None:
        return
    with served.browser() as page:
        page.add_init_script(DAY_LOCK_JS)
        page.goto(served.url('house?quality=high'))
        page.wait_for_selector('#room canvas', timeout=20000)
        page.wait_for_timeout(2200)
        fab = {f['name']: f for f in page.evaluate("window.chfShellFabric()")}

        # ---- the vault: every partition tops out at the deck ----------
        ridge_y = _deck_underside(_MAIN_BLOCK, (-6.10 + 14.55) / 2.0)
        tops = [
            # east_partition runs ALONG the main block's slope axis and
            # crosses the ridge at z 4.225, so its own top IS the ridge.
            ('east_partition', ridge_y, 0.05),
            # future_room_partition runs ACROSS it at z 1.50; its top is
            # cut square at the lower of its two faces (z 1.325).
            ('future_room_partition', _deck_underside(_MAIN_BLOCK, 1.325), 0.05),
            # the garage/mudroom wall: the garage block's ridge (z 2.00)
            # crosses its north end, so that end is its tallest point.
            ('garage_shell', _deck_underside(_GARAGE_BLOCK, 2.00), 0.05),
        ]
        for name, want, tol in tops:
            f = fab.get(name)
            check(f is not None, 'missing fabric piece %r' % name)
            got = f['box'][3]
            check(abs(got - (want - _VAULT_GAP)) <= tol,
                  '%s must rise to the roof underside %.3f (less the %.2f '
                  'no-z-fight gap), got a box topping out at %.3f'
                  % (name, want, _VAULT_GAP, got))
        check(fab['east_partition']['box'][3] >= ridge_y - 0.2,
              'the east partition reaches the ridge, not merely higher '
              'than it was: %.3f' % fab['east_partition']['box'][3])

        # ---- the ray: wall where a wall belongs -----------------------
        # Every ray starts in the great room (or in the garage) and is
        # fired at the partition; EAST rays go +x, NORTH rays +z.
        EAST, NORTH = [1, 0, 0], [0, 0, 1]
        rays = [
            # the two door headers (shipped v2.499.44, pinned here so the
            # vault above them cannot be built by deleting them)
            ([0, 4.60, 9.93], EAST, 'east_partition',
             "wall above the study's glass doors (head 3.75)"),
            ([0, 3.60, 5.80], EAST, 'east_partition',
             "wall above the east room's plain door (head 3.05)"),
            # the vault itself: over each door, and over the ridge
            ([0, 7.00, 9.93], EAST, 'east_partition',
             'the vault over the study door, 1.4 above the old wall head'),
            ([0, 9.50, 4.225], EAST, 'east_partition',
             'the vault at the ridge line'),
            ([10.0, 6.50, -1.0], NORTH, 'future_room_partition',
             'the vault over the back-room partition'),
            # fired from the MUDROOM side, westward: the garage's own
            # half of this wall is behind `facade_garage_block_gable_0`,
            # a generated roof feature that reaches back into the bay.
            ([-10.0, 7.00, 6.0], [-1, 0, 0], 'garage_shell',
             'the vault over the garage/mudroom wall'),
        ]
        for origin, direction, want_name, why in rays:
            hit = page.evaluate('([o, d]) => window.chfRayFabric(o, d)',
                                [origin, direction])
            check(hit and hit['name'] == want_name,
                  'a ray from %r toward %r must hit %s -- %s -- got %r'
                  % (origin, direction, want_name, why, hit))

        # No new registered names: the arc GREW four groups, it did not
        # add a piece. (scenario_shell_fabric_registry owns the full
        # KEPT/NEW table; this is the one-line statement of the law.)
        names = sorted(fab)
        check(not [n for n in names if 'vault' in n],
              'the vault registers nothing of its own: %r' % names)

        # ---- the study's own north wall -------------------------------
        # INTERIOR (the east room is on the far side of it) and authored
        # 4.45 tall for a standalone page with its own shell. It is not
        # registered fabric -- house_study.js builds the room's
        # architecture itself -- so it is read from the study's own world
        # box, which chfStudyBox only reports once the room is visible.
        # After this arc that wall is the tallest thing in the room.
        page.evaluate("window.chfHouseEnterRoom('study')")
        page.wait_for_timeout(1600)
        want = _deck_underside(_MAIN_BLOCK, 7.71) - _VAULT_GAP
        got = page.evaluate('window.chfStudyBox()')
        check(got and abs(got[3] - want) <= 0.06,
              "the study's north wall must rise to the deck at z 7.71 "
              '(%.3f), the study box tops out at %r' % (want, got and got[3]))


def scenario_shell_without_room_is_inert():
    """Exercise an unbuilt shell using existing walls as fixture geometry.

    Clear room tags before registration, so the real stamping, merging,
    and pointer paths all run. A fixture zone behind the west wall proves
    that the visible roomless shell blocks an otherwise actionable zone.
    """
    served = live_app()
    if served is None:
        return
    with open('static/house.js', encoding='utf-8') as f:
        source = f.read()
    anchor = '    function regFabric(group, o) {'
    check(source.count(anchor) == 1, 'fixture needs the registration entry')
    source = source.replace(anchor, anchor + """
      if (o.name === 'south_wall' || o.name === 'west_wall') {
        o.room = null;
        group.traverse(function (m) { delete m.userData.room; });
      }
      if (o.name === 'west_wall') {
        var behind = new T.Mesh(new T.BoxGeometry(0.05, 12, 40),
                                new T.MeshBasicMaterial());
        behind.position.set(-7.5, 2.8, 4.4);
        behind.userData.zone = 'radio';
        scene.add(behind);
      }
    """)
    with served.browser() as page:
        page.route('**/house.js*', lambda route: route.fulfill(
            content_type='application/javascript', body=source))
        page.goto(served.url('house?quality=low'))
        page.wait_for_function(
            'window.chfNavProbe && window.chfNavProbe({settled:true})',
            timeout=30000)
        p = page.evaluate("window.chfNavProbe({piece:'south_wall'})")
        check(p is not None, 'roomless south wall must have a street pixel')
        page.mouse.click(p['cx'], p['cy'])
        check(page.evaluate('window.chfHouseMode()') == 'exterior',
              'roomless exterior shell must stay inert')
        page.evaluate('window.chfHouseEnter()')
        page.wait_for_function('window.chfNavProbe({settled:true})')
        p = page.evaluate("window.chfNavProbe({piece:'west_wall'})")
        check(p is not None, 'roomless west wall must have an interior pixel')
        page.mouse.click(p['cx'], p['cy'])
        page.wait_for_function('window.chfNavProbe({settled:true})')
        check(page.evaluate('window.chfNavProbe({settled:true})') ==
              {'mode': 'kitchen', 'focused': None},
              'roomless shell must not open a room or zone behind it')


def scenario_clipper_cuts_convex_meshes():
    """Spec 2026-09-16 masking §3: the clipper is exact on a unit cube."""
    served = live_app(_seed)
    if served is None:
        return
    with served.browser() as page:
        page.goto(served.url('house?quality=low'))
        page.wait_for_selector('#room canvas', timeout=20000)
        r = page.evaluate("""() => {
          const C = window.HouseClip;
          if (!C) return {missing: true};
          const v = (x,y,z,u=0,w=0) => ({p:[x,y,z], uv:[u,w]});
          // unit cube 0..1, twelve triangles, slot 0, outward winding
          const q = (a,b,c,d) => [{a,b,c,slot:0},{a,b:c,c:d,slot:0}];
          const P = [v(0,0,0),v(1,0,0),v(1,1,0),v(0,1,0),v(0,0,1),v(1,0,1),v(1,1,1),v(0,1,1)];
          const tris = [].concat(
            q(P[0],P[3],P[2],P[1]), q(P[4],P[5],P[6],P[7]),   // z=0 (facing -z), z=1
            q(P[0],P[1],P[5],P[4]), q(P[3],P[7],P[6],P[2]),   // y=0, y=1
            q(P[0],P[4],P[7],P[3]), q(P[1],P[2],P[6],P[5]));  // x=0, x=1
          const area0 = C.triArea(tris, 0);
          const half = C.clipTris(tris, {n:[1,0,0], d:0.5}, 1);   // keep x >= 0.5
          const kept0 = C.triArea(half, 0), cap = C.triArea(half, 1);
          const out = C.subtractTris(tris, [{n:[1,0,0], d:0.5}, {n:[0,1,0], d:0.5}], 1);
          const outArea = C.triArea(out, 0);
          const m = C.maskPlanes([0, 10, 10], [-1, 1, 0, 2, -1, 1]);
          return {area0, kept0, cap, outArea, nP: m.P.length, nW: m.W.length,
                  inside: C.pointMasked([0, 5, 5], m), behind: C.pointMasked([0, 1, -3], m),
                  outsideCone: C.pointMasked([8, 5, 5], m)};
        }""")
        check(not r.get('missing'), 'window.HouseClip is loaded on /house')
        check(abs(r['area0'] - 6.0) < 1e-6, f"unit cube area 6, got {r['area0']}")
        check(abs(r['kept0'] - 3.0) < 1e-6, f"half cube keeps 3 of the original faces' area, got {r['kept0']}")
        check(abs(r['cap'] - 1.0) < 1e-6, f"one unit cap, got {r['cap']}")
        check(abs(r['outArea'] - 4.5) < 1e-6, f"cube minus its +x+y quarter keeps 4.5 original area, got {r['outArea']}")
        check(r['nP'] >= 4 and r['nW'] >= 1, f"mask planes built: P {r['nP']} W {r['nW']}")
        check(r['inside'] is True, 'a point between the camera and the box is masked')
        check(r['behind'] is False, 'a point beyond the box is kept')
        check(r['outsideCone'] is False, 'a point outside the silhouette is kept')


def scenario_every_fabric_mesh_is_convex_or_a_kit():
    """Task 2 (view-volume masking spec section 3): solids come from the
    builders. chfFabricConvexity() reads each row's `convexity`, scanned
    at registration time (regFabric(), refreshed by refabConvexity() for
    west_wall/mudroom_front/yard's own late folds) -- not a live
    traversal, and not a single bulk pass over FABRIC either, since
    house_features.js's door fixtures register even later than that
    (through syncWorld()'s first call). Registration always happens
    while a row's own meshes are still individual box()/extrude meshes,
    before any merge pass fuses them -- the same population Task 3's
    buildRoomShells() clips -- so a windowed wall built from ordinary
    box() meshes is expected to be fully convex, never a kit: merging
    those boxes into one composite happens later and neither this check
    nor Task 3's clip ever sees it.

    A non-kit row's unstamped meshes (`nonconvex`, a list of geometry
    type names) must all be a recognized non-box primitive -- a lathe,
    torus, cylinder, sphere, swept tube, or an InstancedMesh (exempt from
    the mask outright: kept whole, never even considered for a per-mesh
    keep/drop) -- never a plain BoxGeometry/tiledBoxGeo mesh (or a
    hand-built convex BufferGeometry, e.g. a chamfered box built directly
    instead of through box()) that simply missed its stamp, which is a
    bug, not an allowed shape. A kit row (a door, window, porch, garage
    door or the coach lamp) is kept or dropped WHOLE regardless of what
    is inside it, and the exact set of kit rows is pinned below -- this
    is the regression v2.499.50 actually shipped (nine ordinary windowed
    walls wrongly marked kit), so "at least one row is a kit" alone is
    not enough.
    """
    # ExtrudeGeometry and ShapeGeometry are deliberately ABSENT from this
    # set, not an oversight: every in-repo ExtrudeGeometry site inside a
    # non-kit row is already stamped directly by this task (shellGable's
    # decks/ends, vaultSection), so the only way either name reaches
    # `nonconvex` at all is a NEW extrude/shape site nobody has stamped
    # yet -- and unlike a lathe or a swept tube, an extrude or a shape is
    # not unconditionally non-convex (a Shape with a hole is not convex,
    # but a plain one is). Allowing them here would let a future missed
    # stamp on a genuinely convex (and clippable) mesh quietly pass as
    # "unknown non-box shape, fine" instead of failing loudly. Only
    # TorusGeometry and TubeGeometry are always non-convex (a revolved or
    # swept curve can never be a flat-sided polytope), so only those two
    # join the primitives already seen in this build.
    ALLOWED_NONCONVEX = {'LatheGeometry', 'TorusGeometry', 'CylinderGeometry',
                         'SphereGeometry', 'TubeGeometry', 'InstancedMesh'}
    served = live_app()
    if served is None:
        return
    with served.browser() as page:
        page.goto(served.url('house?quality=high'))
        page.wait_for_selector('#room canvas', timeout=20000)
        page.wait_for_timeout(2200)
        rows = page.evaluate("window.chfFabricConvexity()")
        check(rows, 'chfFabricConvexity reports at least one fabric row')
        by_name = {r['name']: r for r in rows}
        bad = []
        for r in rows:
            if r['kit']:
                continue
            disallowed = [t for t in r['nonconvex'] if t not in ALLOWED_NONCONVEX]
            if disallowed:
                bad.append((r['name'], r['convex'], r['meshes'], disallowed))
        check(not bad,
              'every non-kit row must be convex or a recognized non-box '
              'primitive: %r' % bad)
        check(any(r['kit'] for r in rows),
              'at least one row is a kit (a door/window/porch/lamp assembly)')
        door = by_name.get('living_study_door')
        check(door is not None and door['kit'],
              f"living_study_door is a kit: {door}")
        wall = by_name.get('south_wall')
        check(wall is not None and not wall['kit'] and
              wall['meshes'] > 0 and wall['convex'] == wall['meshes'],
              f"south_wall is fully convex: {wall}")
        # Corrected (v2.499.51): a windowed wall is NOT a kit -- its
        # boxes clip pre-merge like any other box, exactly what the
        # first version of this scenario got wrong.
        for name in ('east_wall', 'east_partition', 'north_cladding',
                     'north_wall_east', 'garage_block_west', 'west_cladding',
                     'garage_shell', 'yard', 'mudroom_front', 'west_wall'):
            row = by_name.get(name)
            check(row is not None and not row['kit'],
                  f"{name} clips pre-merge, not a kit: {row}")
        # Fix round 1 (v2.499.52): pin the kit SET exactly, not just "at
        # least one exists" -- v2.499.50's regression was nine ordinary
        # windowed walls wrongly marked kit, and a test that only checks
        # "some row is a kit" would never have caught that. Generated
        # kits are named 'facade_<face>_<window|door>_<slot>' (windowAt/
        # doorAt); dormerAt/gableAt/hipEndAt generate facade_ names too
        # but are never kits, so the kind is matched explicitly rather
        # than accepting every facade_ name. The PORCH (porchAt) is not
        # a kit either (task 3 fix round 1 ruling): every piece of it is
        # a box(), so it clips per mesh -- the kit test's box centre sat
        # under the room's floor line and kept the porch roof standing
        # across the living view.
        import re as _re3
        kits = {r['name'] for r in rows if r['kit']}
        expected = {n for n in by_name
                    if _re3.match(r'^facade_.*_(window|door)_\d+$', n)}
        porches = [by_name[n] for n in by_name if _re3.match(r'^facade_.*_porch_\d+$', n)]
        check(porches, 'the canonical elevation has a porch')
        for row in porches:
            check(not row['kit'] and row['meshes'] > 0 and row['convex'] == row['meshes'],
                  f"the porch clips per mesh -- every piece a convex box: {row}")
        expected |= {'garage_door', 'back_door', 'living_study_door',
                     'east_room_door', 'living_back_room_door'}
        check(kits == expected,
              f"kit set is exactly the door/window/porch/lamp list: "
              f"extra={sorted(kits - expected)} missing={sorted(expected - kits)}")


ROOMS = ['kitchen', 'living', 'study', 'garage', 'mudroom']


def scenario_room_masks_cut_only_what_blocks_the_room():
    """Spec 2026-09-16 masking section 2/7: per room, only what stands
    between the camera and the room's eave-high box is cut; everything
    else is whole.

    Every pin below carries its derivation from the mask itself (P: the
    pyramid from the room camera through the box's silhouette; W: behind
    the box's front faces; masked = P and not W), read against the room
    boxes chfRoomMask() reports (kitchen x -10.39..6.5 z -5.8..5.8,
    living x -6.5..6.5 z 5.1..14.22, study x 6.92..15.25 z 7.12..14.45,
    garage x -17.96..-12.83 z 2.21..9.76, mudroom x -12.6..-6.8 z
    2.36..8.3, all y 0..5.6) and the room cameras (HOME_POS 4.64,13.8,23;
    LIV_POS 0,12.8,26.5; STUDY_POS 7.02,4.75,18.82; GARAGE_POS
    -18,10.5,21.3; MUD_POS -3.4,6.2,11.2). Where the task brief's first
    draft of this scenario guessed differently (kitchen: south_wall
    "mostly cut"; study: east_partition "cut"), the geometry says
    otherwise and the pin follows the geometry -- see each comment.

    Names (task 4): the main roof and the street wall are ONE piece
    each again (roof_main_south over the whole block, south_wall x
    -7.15..14.65), so every fraction pinned on them is the old split
    piece's fraction scaled by that piece's share of the whole -- area
    goes with width for the wall (same height and thickness the whole
    run) and for the deck (same span the whole run): the old west half
    of the roof was 14.32 of the deck's 22.44 (0.638), the east 8.12
    (0.362); the old south_wall 14.0 of 21.8 (0.642), south_wall_east
    7.8 (0.358). Each pin below carries its own derivation.
    """
    served = live_app(_seed)
    if served is None:
        return
    with served.browser() as page:
        page.add_init_script(DAY_LOCK_JS)
        page.goto(served.url('house?quality=high'))
        page.wait_for_selector('#room canvas', timeout=20000)
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        fab = page.evaluate('window.chfShellFabric()')
        by = {f['name']: f for f in fab}
        check('maskedFraction' in by['south_wall'], 'rows report maskedFraction per room')
        for f in fab:
            check(set(f['maskedFraction']) == set(ROOMS),
                  f"{f['name']}: a fraction for every room camera, got {sorted(f['maskedFraction'])}")
            check(all(0 <= v <= 1 for v in f['maskedFraction'].values()),
                  f"{f['name']}: fractions are 0..1: {f['maskedFraction']}")
        def frac(name, room):
            return by[name]['maskedFraction'][room]
        # THE GREAT ROOM. Both cameras stand in the street, high (y 12.8 /
        # 13.8), looking down over the front of the house.
        #   living: its box reaches the street wall's inner face (z
        #   14.22 vs 14.20), so the wall straddles the box's south face
        #   and is judged entirely "in front": its cut is P alone, the
        #   room's silhouette projected onto the wall -- nearly the whole
        #   wall between x -6.5 and 6.5 (measured 0.87). The south deck of
        #   the roof over it is cut from the eave up to where the ray to
        #   the box's far-top edge (z 5.1, y 5.6) crosses the deck, z ~10
        #   (measured 0.33). The street windows 7/9/12 and door 10 sit in
        #   the cut wall: kits, box centre masked, dropped whole (1.0).
        # RULING 2 (fix round 1): the street wall straddles the box's
        # south face (inner face 14.20, box 14.22); the straddle rule
        # moves W to the wall's own depth so the cut is P alone -- the
        # silhouette of a 13 x 5.6 box on the wall. TASK 4: the wall is
        # the whole 21.8 run, so the old 0.87 of the 14-wide great-room
        # segment is 0.87 * 0.642 = 0.56 of the one wall; a raw plane
        # would keep the inner sliver and read ~0.3. Pinned > 0.5 (and
        # < 0.6: the pyramid's x span at the wall is the box's 13 of
        # 21.8 = 0.596, the most the living can ever take).
        check(0.5 < frac('south_wall', 'living') < 0.6, f"living: south_wall cut on its silhouette over the great room's run, got {frac('south_wall', 'living')}")
        # the south deck: the old west half's 0.33 is 0.33 * 0.638 = 0.21
        # of the one deck; pinned > 0.1
        check(frac('roof_main_south', 'living') > 0.1, f"living: roof_main_south cut over the room, got {frac('roof_main_south', 'living')}")
        for kit in ('facade_main_window_7', 'facade_main_window_9', 'facade_main_window_12', 'facade_main_door_10'):
            check(frac(kit, 'living') == 1, f'living: {kit} goes whole with the wall it sits in')
        # PORCH (fix round 1 ruling): not a kit -- its boxes clip per
        # mesh. The porch ROW is the slab, step, posts, rails and the
        # eave beam; its roof decks are the facade_main_gable_8_* rows
        # (dropped whole above). What stands in the pyramid is the beam
        # and the tops of the posts -- 13% of the row's surface (the
        # slab, step and rails under the pyramid's floor plane are most
        # of it) -- so the row reads 0.13, not the > 0.4 a roof deck in
        # the row would have given. Pinned > 0.1 with remnants present.
        check(frac('facade_main_porch_8', 'living') > 0.1,
              f"living: the porch beam and post tops are cut, got {frac('facade_main_porch_8', 'living')}")
        # RULING 1 (fix round 1): a facade roof feature (gable/dormer/hip
        # end piece) is dropped WHOLE when the mask would keep less than
        # a fifth of it -- the porch gable's two decks kept 14% and stood
        # as floating shards outside the pyramid -- and clipped normally
        # otherwise (its front kept 30%, the kitchen keeps a quarter of
        # each deck).
        # ROOF VALLEYS (task 5): the decks no longer carry their buried
        # back under the main roof; what stood in the kitchen's cone was
        # mostly that back (the cone's floor crosses z 12 at y 4.97, the
        # buried deck reached 6.84 there), so the kitchen's cut of what
        # remains reads 0.20 where it read 0.25 -- measured, the pin
        # widened to hold it.
        for deck in ('facade_main_gable_8_west', 'facade_main_gable_8_east'):
            check(frac(deck, 'living') == 1, f'living: {deck} drops whole below a fifth kept, got {frac(deck, "living")}')
            check(0.15 < frac(deck, 'kitchen') < 0.3, f'kitchen: {deck} keeps its clipped part, got {frac(deck, "kitchen")}')
        check(0.5 < frac('facade_main_gable_8_front', 'living') < 0.8,
              f"living: the porch gable front is clipped, not dropped, got {frac('facade_main_gable_8_front', 'living')}")
        #   kitchen: the box's near face is z 5.8, INSIDE the open great
        #   room. The pyramid's floor plane runs from HOME_POS through
        #   the box's bottom-south edge (y 0, z 5.8) and crosses the
        #   street wall's plane (z 14.4) at y 6.9 -- above the wall's top
        #   (5.6). Every ray from the kitchen camera to the kitchen box
        #   clears the street wall; it stands between the camera and the
        #   LIVING room, not the kitchen, so it stays (0), and so do the
        #   street windows, the door and the porch. What does block the
        #   kitchen is the roof: the ray to the far-top edge (z -5.8, y
        #   5.6) crosses the south deck at z ~7.9, so the deck comes off
        #   from the eave to there (measured 0.47).
        check(frac('south_wall', 'kitchen') == 0, f"kitchen: south_wall clears every ray to the kitchen box, got {frac('south_wall', 'kitchen')}")
        # the old west half's 0.47 is 0.47 * 0.638 = 0.30 of the one
        # deck; pinned > 0.1
        check(frac('roof_main_south', 'kitchen') > 0.1, f"kitchen: roof_main_south cut over the room, got {frac('roof_main_south', 'kitchen')}")
        for kit in ('facade_main_window_7', 'facade_main_window_9', 'facade_main_window_12', 'facade_main_door_10'):
            check(frac(kit, 'kitchen') == 0, f'kitchen: {kit} is not between the street camera and the kitchen')
        # Nothing east of the great room is between either camera and
        # either room: the study's own walls and windows, the east wall,
        # the future rooms' partitions and the kitchen's own north wall
        # (behind the box, inside W) all stay whole. (The study's street
        # face and roof are the east parts of south_wall / roof_main_south
        # now -- pinned standing by remnant vertex in
        # scenario_a_room_cutaway_leaves_other_rooms_enclosed.)
        for room in ('kitchen', 'living'):
            for whole in ('east_partition', 'east_wall', 'north_wall_east', 'future_room_partition',
                          'facade_main_window_15', 'facade_main_window_16', 'north_wall'):
                check(frac(whole, room) == 0, f'{room}: {whole} untouched, got {frac(whole, room)}')
        # RULING 3 (fix round 1): the yard (yardG, the registered row) is
        # hidden whole in every room view and shown at the exterior --
        # its exempt instanced planting doubled every room's triangles
        # when it drew. Fraction 1 everywhere, like a dropped kit.
        for room in ROOMS:
            check(frac('yard', room) == 1, f'{room}: the yard hides whole, got {frac("yard", room)}')
        # THE STUDY. STUDY_POS stands east of the old split line (x 7.02
        # > 6.92, the box's west face) and low (y 4.75 < the eave), so
        # the only front face is the south one: masked = inside the
        # pyramid through the south face's four edges, south of the box.
        # Its street face -- TASK 4: the east 7.8 of the one south_wall
        # -- straddles that face (the study floor reaches z 14.45, the
        # wall's inner face is 14.20) and is cut by P alone: 0.97 of the
        # old segment, 0.97 * 0.358 = 0.35 of the whole wall; its two
        # windows 15/16 are kits in that wall, dropped whole.
        # east_partition (x 6.44..6.85) is beside the camera, west of the
        # box's west face: NOT between camera and room, whole -- the
        # brief's draft pinned it "cut", which was the pre-refit camera
        # at x 5.85. Window 7 and the kitchen's north wall are outside
        # the pyramid's x span. The roof is above a camera that looks
        # level into the room: the top face is not front; the north deck
        # stays and the south deck is grazed at its overhang only (0.013
        # of the old east half, 0.013 * 0.362 = 0.005 of the one deck).
        # RULING 2: the study floor reaches 0.25 into the street wall;
        # the straddle rule cuts the wall by P alone; a raw plane would
        # keep the inner 0.25 and read ~0.1 of the whole wall. Pinned
        # > 0.3, and < 0.36 (the study's share, 7.8 / 21.8 = 0.358, is
        # the most the study can ever take).
        check(0.3 < frac('south_wall', 'study') < 0.36, f"study: its street face is cut on its silhouette, got {frac('south_wall', 'study')}")
        for kit in ('facade_main_window_15', 'facade_main_window_16'):
            check(frac(kit, 'study') == 1, f'study: {kit} goes whole with the street face')
        for whole in ('east_partition', 'facade_main_window_7', 'north_wall',
                      'roof_main_north', 'living_study_door'):
            check(frac(whole, 'study') == 0, f'study: {whole} whole, got {frac(whole, "study")}')
        check(frac('roof_main_south', 'study') < 0.05, f"study: the south deck is grazed at most, got {frac('roof_main_south', 'study')}")
        # THE MUDROOM. MUD_POS stands in the great room, east of the
        # mudroom's east face (x -3.4 > -6.8), just above the eave (y 6.2)
        # and south of the box (z 11.2 > 8.3): three front faces. The
        # great room's west wall (west_wall, slab x -7.15..-6.8) touches
        # the box's east face and is cut where the box projects onto it
        # (measured 0.37), with its exterior skirt and cladding behind
        # it; mudroom_front (the street wall's inner layer at z 7.94..8.3
        # straddles the south face) is cut where it stands in P (0.52).
        # The garage-block roof over the room: a camera 0.6 above the
        # eave sees the top face almost edge-on, so the pyramid's top
        # plane grazes the deck only at its overhang -- a sliver (0.003),
        # not the deck; the walled volume is seen THROUGH the wall, not
        # through the roof. The garage's own walls are not in the way.
        check(frac('west_wall', 'mudroom') > 0.2, f"mudroom: the great room's west wall opens, got {frac('west_wall', 'mudroom')}")
        check(frac('mudroom_front', 'mudroom') > 0.3, f"mudroom: the street wall's inner layer opens, got {frac('mudroom_front', 'mudroom')}")
        check(0 <= frac('garage_block_roof_south', 'mudroom') < 0.1,
              f"mudroom: the garage-block south deck is grazed at most, got {frac('garage_block_roof_south', 'mudroom')}")
        check(frac('garage_shell', 'mudroom') < 0.1, 'mudroom: the garage walls stay whole')
        # THE GARAGE. GARAGE_POS stands in the driveway, high (y 10.5),
        # 0.04 west of the box's west face: south, top and (barely) west
        # faces are front. The garage door fills the box's south face --
        # a kit, box centre masked, dropped whole; the bay's own gable
        # front over it and the south deck of the block roof are cut
        # where the pyramid passes through them to the box's top face.
        check(frac('garage_door', 'garage') == 1, 'garage: the garage door goes whole')
        check(frac('facade_garage_block_gable_0_front', 'garage') > 0.5, 'garage: the bay gable front is cut')
        check(frac('garage_block_roof_south', 'garage') > 0.1, 'garage: the south deck over the bay is cut')
        for whole in ('mudroom_front', 'west_wall', 'south_wall', 'north_wall', 'garage_block_west'):
            check(frac(whole, 'garage') == 0, f'garage: {whole} whole, got {frac(whole, "garage")}')
        # exterior: nothing masked
        page.evaluate('window.chfHouseExit()')
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        fab = page.evaluate('window.chfShellFabric()')
        check(all(f['verdict'] == 'solid' for f in fab), 'exterior: every piece solid')
        check(page.evaluate('window.chfRoomShellShown()') is None, 'exterior: no room shell shown')
        check(page.evaluate('window.chfMaskLeak(null)') == 0, 'exterior: every source shown, every stand-in hidden')
        check(all(f['visible'] for f in fab), 'exterior: every row visible')
        # RULING 2, the direct pin: in the living and study shells no kept
        # vertex of the near wall lies inside P behind the box's near
        # face (z > near face - WALL_T4): the inner sliver a raw W plane
        # would leave is gone. Sampled the way chfRoomShellLeak samples.
        # RULING 1, the direct pin: the living shell holds no remnant of
        # the dropped porch decks; the kitchen shell holds their quarter.
        WALL_T4 = 0.35
        def inside_P(mask, p, eps=1e-3):
            return all(pl['n'][0]*p[0] + pl['n'][1]*p[1] + pl['n'][2]*p[2] - pl['d'] > eps
                       for pl in mask['P'])
        for room, wall in (('living', 'south_wall'), ('study', 'south_wall')):
            mask = page.evaluate(f"window.chfRoomMask('{room}')")
            verts = page.evaluate(f"window.chfRoomShellVerts('{room}', '{wall}', 4000)")
            check(verts, f'{room}: the near wall leaves remnants in the shell')
            near = mask['box'][5] - WALL_T4
            sliver = [p for p in verts if inside_P(mask, p) and p[2] > near]
            check(not sliver, f'{room}: {len(sliver)} kept {wall} vertices inside P behind the near face (inner sliver survived): {sliver[:3]}')
        check(page.evaluate("window.chfRoomShellVerts('living', 'facade_main_porch_8', 100)"),
              'living shell: the porch leaves remnants (its posts and cut deck)')
        for deck in ('facade_main_gable_8_west', 'facade_main_gable_8_east'):
            check(page.evaluate(f"window.chfRoomShellVerts('living', '{deck}', 100)") == [],
                  f'living shell: no {deck} remnant')
            check(page.evaluate(f"window.chfRoomShellVerts('kitchen', '{deck}', 100)"),
                  f'kitchen shell: {deck} clipped quarter present')
        # each room view shows its shell; the swap happened
        for room in ROOMS:
            page.evaluate(f"window.chfHouseEnterRoom('{room}')")
            page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
            shown = page.evaluate('window.chfRoomShellShown()')
            check(shown == room, f'{room}: its room shell is the visible one (got {shown})')
            # sampled kept vertices lie outside the mask
            bad = page.evaluate(f"window.chfRoomShellLeak('{room}', 2000)")
            check(bad == 0, f'{room}: no kept vertex inside the mask (got {bad})')
            # fix round 1: every toggled object is in the state this view
            # wants -- a source mesh whose pattern names the room is hidden
            # even when its ROW group is toggled too (a roof feature
            # dropped whole in one view and clipped in another: the early
            # return that skipped such a row's members left the porch
            # deck's source standing in the kitchen cone)
            check(page.evaluate(f"window.chfMaskLeak('{room}')") == 0,
                  f'{room}: no toggled object in the wrong state')
            rows = page.evaluate('window.chfShellFabric()')
            for f in rows:
                want = 'masked' if f['maskedFraction'][room] > 0 else 'solid'
                check(f['verdict'] == want, f"{room}: {f['name']} verdict {f['verdict']} vs fraction {f['maskedFraction'][room]}")
                if f['maskedFraction'][room] == 1:
                    check(not f['visible'], f"{room}: {f['name']} masked whole is hidden")
        check(not served.errors(), f'console clean: {served.errors()[:3]}')


def scenario_block_roof_forms_register_and_audit():
    """Spec 2026-09-17 blocks section 0: hip and ridge-z block roofs become
    settings in this arc, so they get live pins first. Each variant boots
    clean, the registry holds the four pieces roof_piece_names() predicts,
    the Mudroom marker's alias resolves to the STREET-facing garage roof
    piece, and no facade roof feature is buried under any block deck."""
    from house_live_common import FEATURE_JS, VERTEX_AUDIT_ALL_JS
    variants = [
        ({'main': {'form': 'hip', 'ridge': 'x'}, 'garage': {'form': 'gable', 'ridge': 'x'}}, 'main hip/x'),
        ({'main': {'form': 'gable', 'ridge': 'z'}, 'garage': {'form': 'gable', 'ridge': 'x'}}, 'main gable/z'),
        ({'main': {'form': 'gable', 'ridge': 'x'}, 'garage': {'form': 'hip', 'ridge': 'z'}}, 'garage hip/z'),
    ]
    served = live_app(_seed)
    if served is None:
        return
    for forms, label in variants:
        with served.browser() as page:
            page.add_init_script(DAY_LOCK_JS)
            page.add_init_script('window.HOUSE_ROOF_FORMS = %s;' % json.dumps(forms))
            page.goto(served.url('house?quality=high'))
            page.wait_for_selector('#room canvas', timeout=20000)
            page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
            fabric = page.evaluate('window.chfShellFabric()')
            names = {r['name'] for r in fabric}
            want = (roof_piece_names('roof_main', forms['main']['form'], forms['main']['ridge']) |
                    roof_piece_names('garage_block_roof', forms['garage']['form'], forms['garage']['ridge']))
            check(want <= names, f'{label}: roof pieces registered; missing {sorted(want - names)}')
            alias = page.evaluate('window.chfRoofAlias()')
            street = alias.get('garage_block_roof_south')
            check(street in names, f'{label}: Mudroom alias {street!r} is a registered piece')
            nrm = next(r['n'] for r in fabric if r['name'] == street)
            check(nrm[2] > 0.3, f'{label}: the alias faces the street: n={nrm}')
            for f in page.evaluate(FEATURE_JS):
                if f['kind'] == 'hip_end':
                    continue
                a = page.evaluate(VERTEX_AUDIT_ALL_JS, f)
                check(a['buried'] == 0, f"{label}: {f['name']} has {a['buried']} vertices under the block roof")
            errs = [e for e in served.errors() if 'WebGL' not in e]
            check(not errs, f'{label}: console clean: {errs[:3]}')


if __name__ == '__main__':
    scenario_shell_fabric_registry()
    scenario_a_room_cutaway_leaves_other_rooms_enclosed()
    scenario_study_sits_inside_the_main_block()
    scenario_the_study_faces_east_behind_glass_doors()
    scenario_interior_walls_rise_to_the_roof()
    scenario_shell_without_room_is_inert()
    scenario_clipper_cuts_convex_meshes()
    scenario_every_fabric_mesh_is_convex_or_a_kit()
    scenario_room_masks_cut_only_what_blocks_the_room()
    scenario_block_roof_forms_register_and_audit()
    print("test_house_shell_live OK")
