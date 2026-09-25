# Study paper perspective and Household Monitor

Intake and Plans in hand now project their actual DOM content onto the photographed paper/desk-pad planes with a four-corner perspective transform. The same transform applies to text, form fields, buttons and hit areas. The photographs remain full-screen. The portrait phone intake camera leaves the paper below the room navigation.

The Household Monitor displays family constellations on its own photographed monitor. Each person has a glowing cluster; calendar counts control cluster fullness, matching the data used by the existing 3D monitor. Hover, keyboard focus or touch reveals the exact person and count. Orbiting stars and traveling light pulses are atmospheric; the caption explicitly distinguishes these from calendar data. No new relationship or health metric is inferred.

The canvas is decorative; semantic buttons expose every count. The display supports zero and unavailable counts, an empty household, and up to eight members. Pause persists through refreshes, reduced motion produces a static view, background tabs stop animation, and leaving or locking Study disposes of the animation and private content. Existing bounded parent authorization is retained.

Validation passed against isolated fictional storage:

- `python tests/test_house_study_surfaces_live.py --out ../scratch/study-perspective-regression`: actual intake and plan writes, other Study actions, mobile layout, expiry and failed-save behavior.
- `python tests/test_house_connected_live.py --out ../scratch/study-perspective-connected`: connected rooms, all object surfaces in day/night, responsive full-screen photography, PIN, lock and history.
- `python tests/test_house_study_monitor_live.py --out ../scratch/study-constellations`: projected desktop surfaces, real phone intake/plan writes, hover/focus/tap values, animation and pause persistence, reduced motion, visibility pause, eight-member/zero/unknown/empty states, day/night, disposal and lock.
- JavaScript syntax checks and `git diff --check`.

Screenshots were visually reviewed for desktop and portrait phone layouts. No purchased or newly generated image assets or new dependencies were needed.

Preview: http://127.0.0.1:50978/house?compare=exterior&scene=living&light=day

Demo Parent PIN: `1234`.
