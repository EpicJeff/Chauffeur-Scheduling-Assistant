# PWA reimagined, slice 0: the shell (vocabulary, the orb in the tab bar, pushed screens) — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the adult PWA the new shell every later slice builds on: the shared Argyle orb (one look for wall and phone) docked at the far right of the tab bar, the time-of-day wash and card tokens, and a pushed-screen stack on the History API. No screen converts yet; every existing surface keeps working on top of it.

**Architecture:** The orb's look moves out of `ha_theme.html` into one static stylesheet plus a tiny factory script that both the wall (`control_center.html`) and the phone (`app.html` tab bar) use; the wall keeps its own positioning rules so `test_panel_chrome` stays green. The phone tab bar becomes an evenly spaced row of equal slots with the orb as the last slot, shown only to members whose scope has `chat.agent`; in this slice tapping it opens the Argyle DM in Messages (the overlay is slice 2). Tokens for the wash and cards live in `pwa_shell.css`, fed by a pure `pwaSky(hour, dark)` function. `static/pwa_nav.js` owns a screen stack with `pushState`/`popstate`.

**Tech Stack:** FastAPI + Jinja templates, vanilla JS, precompiled Tailwind (`python tools/build_tailwind.py` after any template class change), Playwright live tests via `tests/live_app.py`, node + jsdom for pure-JS tests. Tests run from `chauffeur/` as `python tests/test_x.py` with `HA_BASE_URL` unset.

**Spec:** `docs/superpowers/specs/2026-11-03-pwa-reimagined-design.md` (sections "The vocabulary", "Argyle from anywhere", "Dispositions", "Suggested slices" item 0). Inventory: `docs/design/pwa-reimagined/current-state-inventory.md`.

## Global Constraints

- Adult overrides stay scoped to `html[data-audience="adult"]`; child shells (`pwa_child_shell.*`) untouched; kid live checks (`tests/pwa_child_checks.py` via `test_pwa_adult_shell_live.py`) stay green.
- The orb look is exactly the wall's: `radial-gradient(120% 120% at 30% 25%, #a78bfa 0%, #6366f1 45%, #2563eb 100%)`, `border: 1px solid rgb(255 255 255 / 0.22)`, `box-shadow: 0 6px 22px rgb(79 70 229 / .45), 0 0 0 6px rgb(99 102 241 / .12)`, the `M13 10V3L4 14h7v7l9-11h-7z` glyph, a 4.5 s breathe under `prefers-reduced-motion: no-preference`.
- Every slot in the adult tab bar is 44 px wide (labels may spill symmetrically past the slot, `white-space: nowrap`); the orb is a 44 px round in the last slot; the first slot's left edge and the orb's right edge sit 18 px from the bar's edges; the slots between are evenly spaced.
- The orb shows only when `scopeOf('chat.agent') !== 'none'` and the member is an adult (kid bars: a later pass).
- No browser dialogs; nothing a person can do today is removed (More's "Ask Argyle" and `#kiosk-chat-popup` stay in this slice; they leave in slice 2).
- Every new route needs a rule in `services/auth.py` (none expected in this slice).
- The person's hue stays the accent (`--pwa-accent`); the wash never carries the person's colour.
- `tools/build_tailwind.py` must run before the live test if any template class changes.
- Bump `chauffeur/config.yaml` and update `chauffeur/system_capabilities.md` in the last task.

## Review Focus

1. A member with a custom scope map that sets `chat.agent` to `none` must get no orb even though they are an adult parent (Task 2 test `helper_and_scoped_out_adult_get_no_orb`).
2. A bar with only two tabs (helper) must still anchor the first tab left and leave no orphan gap where the orb would be (Task 2 live check on the `helper` profile).
3. The orb must hide while the Argyle thread is open and come back when the thread closes, including after `setView('messages')` from elsewhere (Task 2 live check `orb_hides_in_the_argyle_thread`).
4. At 23:30 and at 04:00 the sky must still contrast with the ink at 4.5:1 or better in light mode (Task 3 node test iterates all 24 hours).
5. Hardware Back with an empty stack must leave the app on its tab, not pop the tab bar or exit mid-flow (Task 4 jsdom test `back_with_empty_stack_is_inert`).

---

### Task 1: One orb for the wall and the phone

**Files:**
- Create: `chauffeur/static/argyle_orb.css`
- Create: `chauffeur/static/argyle_orb.js`
- Modify: `chauffeur/templates/ha_theme.html:462-504` (keep position rules, drop look rules, link the stylesheet)
- Modify: `chauffeur/templates/components/control_center.html:1149-1156` (build the button through the factory)
- Test: `chauffeur/tests/test_argyle_orb.py`

**Interfaces:**
- Produces: `window.ArgyleOrb.glyph() -> string` (the SVG markup) and `window.ArgyleOrb.create({ id, label }) -> HTMLButtonElement` (a `<button type="button" class="argyle-orb" aria-label=label>` holding the glyph). CSS class `.argyle-orb` (look only: size via `--argyle-orb-size`, default `3.25rem`; gradient, border, radius, shadow, colour, backdrop blur, breathe) and `.argyle-orb-hidden` (opacity 0, visibility hidden, `scale(0.72)` composed with any `--argyle-orb-base-transform`, default `none`).
- The wall keeps `#panel-chat-orb { position: fixed; left: 50%; transform: translateX(-50%); transform-origin; bottom; z-index; transition }` and `#panel-chat-orb.panel-chat-hidden { ...translateX(-50%) scale(0.72) }` in `ha_theme.html` so `tests/test_panel_chrome.py` `scenario_the_orb_opens_from_the_middle` still finds `left: 50%` and `translateX(-50%)` in both blocks.

- [ ] **Step 1: Write the failing source test**

`tests/test_argyle_orb.py`, harness style (`from harness import check`, `scenario_*` functions, `__main__` runner printing `  ok  <name>`):

```python
def scenario_the_orb_look_lives_in_one_stylesheet():
    css = read('static/argyle_orb.css')
    block = css[css.index('.argyle-orb {'):]; block = block[:block.index('}')]
    check('radial-gradient(120% 120% at 30% 25%, #a78bfa 0%, #6366f1 45%, #2563eb 100%)' in block)
    check('rgb(255 255 255 / 0.22)' in block and '0 6px 22px rgb(79 70 229 / .45)' in block)
    check('var(--argyle-orb-size, 3.25rem)' in block)
    check('@keyframes argyle-orb-breathe' in css and 'prefers-reduced-motion: no-preference' in css)
    theme = read('templates/ha_theme.html')
    orb = theme[theme.index('#panel-chat-orb {'):]; orb = orb[:orb.index('}')]
    check('radial-gradient' not in orb and 'box-shadow' not in orb, 'the wall still paints its own orb')
    check('left: 50%' in orb and 'translateX(-50%)' in orb, 'the wall lost its centring')
    check("'static/argyle_orb.css'|ver" in read('templates/nav.html'), 'the wall does not load the shared look')

def scenario_the_factory_builds_the_button():
    js = read('static/argyle_orb.js')
    check('window.ArgyleOrb' in js and 'M13 10V3L4 14h7v7l9-11h-7z' in js)
    cc = read('templates/components/control_center.html')
    check('ArgyleOrb.create(' in cc and "id: 'panel-chat-orb'" in cc)
    check("orb.innerHTML = '<svg" not in cc, 'the wall still hand-draws the glyph')
    check("'static/argyle_orb.js'|ver" in cc or "'static/argyle_orb.js'|ver" in read('templates/nav.html'))
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd chauffeur && python tests/test_argyle_orb.py`
Expected: FAIL (`static/argyle_orb.css` does not exist).

- [ ] **Step 3: Create `static/argyle_orb.css` and `static/argyle_orb.js`**

CSS: `.argyle-orb` with the look only (width/height `var(--argyle-orb-size, 3.25rem)`, `display:flex; align-items:center; justify-content:center; border-radius:999px; color:#fff; cursor:pointer; backdrop-filter: blur(8px)`, the gradient, border and shadow from Global Constraints, `transition: opacity .18s ease, transform .18s ease, visibility .18s`), `.argyle-orb svg { width: 1.4rem; height: 1.4rem; }`, `.argyle-orb-hidden { opacity:0; visibility:hidden; transform: var(--argyle-orb-base-transform, none) scale(0.72); }`, the breathe keyframes (same two shadow stops as `ha_theme.html:501-504`) under the reduced-motion media query. JS: a classic script defining `window.ArgyleOrb = { glyph(), create({id, label}) }`; `create` sets `type='button'`, `id`, `className='argyle-orb'`, `aria-label`, `innerHTML = glyph()`.

- [ ] **Step 4: Move the wall onto it**

In `ha_theme.html` 462-483 keep only position, transform, transform-origin, bottom, z-index and transition in `#panel-chat-orb`; delete the look lines and the breathe rules 485, 497-504; `ha_theme.html` holds only `<script>` and `<style>` blocks, so the stylesheet is loaded from `nav.html` next to its script tags at 375-377 as `<link rel="stylesheet" href="{{ _up }}{{ 'static/argyle_orb.css'|ver }}">` (every wall page includes nav.html). Set `--argyle-orb-base-transform: translateX(-50%)` on `#panel-chat-orb` so the hidden state keeps centring. In `control_center.html:1149-1156` replace the five lines that build `orb` with `const orb = ArgyleOrb.create({ id: 'panel-chat-orb', label: 'Ask Argyle' });` and load `static/argyle_orb.js` from `nav.html` next to line 375-377.

- [ ] **Step 5: Run the tests**

Run: `cd chauffeur && python tests/test_argyle_orb.py && python tests/test_panel_chrome.py && python tests/test_template_js.py`
Expected: all `ok`.

- [ ] **Step 6: Commit**

```bash
git add chauffeur/static/argyle_orb.css chauffeur/static/argyle_orb.js chauffeur/templates/ha_theme.html chauffeur/templates/components/control_center.html chauffeur/templates/nav.html chauffeur/tests/test_argyle_orb.py
git commit -m "refactor(orb): the Argyle orb's look is one stylesheet and one factory, the wall uses them"
```

---

### Task 2: The orb in the phone's tab bar

**Files:**
- Modify: `chauffeur/templates/app.html:112-113` (load `argyle_orb.css` and `argyle_orb.js`), `:525-530` (add `#tab-argyle` after `#tab-more`), `:951-972` (`updateAgentFab` also toggles the orb)
- Modify: `chauffeur/static/pwa_shell.js:7-11` (`pwaOrderTabs` keeps `argyle` last), `:54-91` (`pwaSyncShell` sets orb visibility), new `pwaOpenArgyle()`
- Modify: `chauffeur/static/pwa_shell.css:134-139` (slot layout)
- Test: `chauffeur/tests/test_pwa_adult_shell_live.py` (extend the adult branch), `chauffeur/tests/test_argyle_orb.py` (one source scenario)

**Interfaces:**
- Consumes: `ArgyleOrb` from Task 1; `scopeOf(facet)` (`app.html:993`); `setView`, `openChannel`, `selectedMemberId`, `apiBase`.
- Produces: `<button id="tab-argyle" class="argyle-orb" aria-label="Ask Argyle" onclick="pwaOpenArgyle()">` as the last child of `#pwa-tab-bar`; `pwaOpenArgyle(): Promise<void>` posts `api/channels/dm` with `{ member_id: selectedMemberId, other_member_id: 'argyle' }` (the same call `app.html:6522` makes), then `setView('messages')` and `openChannel(ch.id, ch)`; on failure `showGlobalAlert('Could not open Argyle')`. `pwaOrbAllowed(): boolean` = `pwaIsAdult() && scopeOf('chat.agent') !== 'none'`.

- [ ] **Step 1: Write the failing live checks**

In `test_pwa_adult_shell_live.py` add a helper and call it from the adult branch (after the `#tab-more` assertion at `:217`):

```python
def check_orb(page, key, role):
    orb = page.locator('#tab-argyle')
    allowed = page.evaluate("pwaOrbAllowed()")
    expected = role in ('parent', 'adult') and key != 'scoped_out'
    assert allowed == expected and orb.is_visible() == expected, (key, allowed)
    slots = page.locator('#pwa-tab-bar > button:visible')
    boxes = [b.bounding_box() for b in slots.all()]
    bar = page.locator('#pwa-tab-bar').bounding_box()
    assert abs(boxes[0]['x'] - (bar['x'] + 18)) <= 1, boxes[0]
    assert abs((boxes[-1]['x'] + boxes[-1]['width']) - (bar['x'] + bar['width'] - 18)) <= 1, boxes[-1]
    widths = {round(b['width']) for b in boxes}; assert len(widths) == 1, widths
    gaps = [round(boxes[i+1]['x'] - (boxes[i]['x'] + boxes[i]['width'])) for i in range(len(boxes)-1)]
    assert max(gaps) - min(gaps) <= 1, gaps
    if not expected: return
    assert orb.evaluate('e=>e===e.parentElement.lastElementChild')
    assert round(orb.evaluate('e=>e.getBoundingClientRect().width')) == 44
    assert 'radial-gradient' in orb.evaluate('e=>getComputedStyle(e).backgroundImage')
    orb.click()
    page.wait_for_function("activeChannelId && threadChannel && threadChannel.member_ids.includes('argyle')")
    assert not orb.is_visible(), 'the orb covers the composer'
    page.evaluate('closeThread()')   # app.html:6420
    page.wait_for_function("document.getElementById('tab-argyle').checkVisibility()")
```

Add one profile to `PROFILES`: `('scoped_out', 'parent', 'd5')` seeded with `member['scope'] = {'preset': 'household_adult', 'overrides': {'chat.agent': 'none'}}` (`services/scope.py:255` reads `scope.overrides[facet]`). Route `**/api/channels/dm` to fulfil `{'id': 'dm_argyle', 'kind': 'dm', 'member_ids': [key, 'argyle']}` and `**/api/channels/dm_argyle/messages*` to `[]`.

In `test_argyle_orb.py` add:

```python
def scenario_the_phone_bar_ends_with_the_orb():
    app = read('templates/app.html')
    check(app.index('id="tab-more"') < app.index('id="tab-argyle"'))
    check("'static/argyle_orb.css'|ver" in app and "'static/argyle_orb.js'|ver" in app)
    css = read('static/pwa_shell.css')
    check('justify-content: space-between' in css and '#tab-argyle' in css)
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd chauffeur && python tests/test_argyle_orb.py; python tests/test_pwa_adult_shell_live.py`
Expected: the source scenario FAILS on `tab-argyle`; the live test FAILS on `pwaOrbAllowed is not defined`.

- [ ] **Step 3: Add the button, the layout and the functions**

`app.html`: load the two assets after line 113; after `#tab-more` (line 529) add the button (markup from Interfaces, keep `style="display:none"` off: visibility is CSS-driven by `pwaSyncShell`). `pwa_shell.js`: in `pwaSyncShell`, after the labels loop, `document.getElementById('tab-argyle').hidden = !pwaOrbAllowed();` and in `pwaOrderTabs` append `tab-argyle` last after the ordered tabs. `updateAgentFab` (`app.html:951`): after computing `inThread`, `document.getElementById('tab-argyle')?.classList.toggle('argyle-orb-hidden', inThread && threadChannel?.member_ids?.includes('argyle'))`. `pwa_shell.css`: replace lines 134-139 with the slot layout: `[data-audience="adult"] #pwa-tab-bar { display:flex; justify-content:space-between; align-items:flex-start; padding: 0 18px; box-shadow:none }`, `[data-audience="adult"] #pwa-tab-bar > button { flex: 0 0 44px; width:44px; min-width:0; min-height:62px; padding:10px 0 8px; overflow:visible }`, `[data-audience="adult"] #pwa-tab-bar > button > span:first-of-type { white-space:nowrap }` (keep the existing span/svg/aria-current rules), `[data-audience="adult"] #tab-argyle { --argyle-orb-size: 44px; min-height:44px; padding:0; align-self:center; margin-top:0 }`. `[data-audience="child"] #tab-argyle { display:none }`. The `hidden` attribute set by `pwaSyncShell` must win over the flex display: add `#tab-argyle[hidden] { display:none }`.

- [ ] **Step 4: Rebuild Tailwind, run the tests**

Run: `cd chauffeur && python tools/build_tailwind.py && python tests/test_argyle_orb.py && python tests/test_pwa_adult_shell_live.py && python tests/test_template_js.py`
Expected: all pass, every profile.

- [ ] **Step 5: Commit**

```bash
git add chauffeur/templates/app.html chauffeur/static/pwa_shell.js chauffeur/static/pwa_shell.css chauffeur/static/tailwind-app.css chauffeur/tests/test_argyle_orb.py chauffeur/tests/test_pwa_adult_shell_live.py
git commit -m "feat(pwa): the Argyle orb sits at the far right of the tab bar, one slot wide, and opens the Argyle thread"
```

---

### Task 3: The sky and the card tokens

**Files:**
- Modify: `chauffeur/static/pwa_shell.js` (new `pwaSky(hour, dark)`, applied in `pwaSyncShell`)
- Modify: `chauffeur/static/pwa_shell.css:1-32` (tokens), new body rule
- Test: `chauffeur/tests/test_pwa_sky.py` (node), `chauffeur/tests/test_pwa_adult_shell_live.py` (one computed-style assertion)

**Interfaces:**
- Produces: `pwaSky(hour: number, dark: boolean) -> { top: string, mid: string, bottom: string }` hex colours; `pwaSyncSky(): void` sets the three vars on `:root` from the current hour and `data-theme`; `pwaSky.contrast(hexA, hexB) -> number` (WCAG ratio, reuse the luminance maths in `pwaProfilePalette`). CSS vars on `:root`: `--pwa-sky-top`, `--pwa-sky-mid`, `--pwa-sky-bottom`; tokens `--pwa-ink` (`#1f1d2b` light, `#f3f2f7` dark), `--pwa-card` (`rgba(255,255,255,.62)` light, `rgba(255,255,255,.06)` dark), `--pwa-card-raised` (`#ffffff` light, `#262a36` dark), `--pwa-radius: 22px`. Rule: `[data-audience="adult"] body { background: linear-gradient(180deg, var(--pwa-sky-top) 0%, var(--pwa-sky-mid) 42%, var(--pwa-sky-bottom) 100%) fixed; }`.
- Pinned values (spec mockup A): light morning (05:00-11:59) = `#fff0e6`, `#f6eef7`, `#eef0fb`. The other bands are the builder's within the rule below.

- [ ] **Step 1: Write the failing node test**

`tests/test_pwa_sky.py`: extract `pwaSky` and `pwaProfilePalette` from `static/pwa_shell.js` with `_function_text` (`tests/test_moment_media_token.py:57`) and run with `_run_node`:

```python
def scenario_morning_is_the_mockup():
    assert out['morning'] == {'top': '#fff0e6', 'mid': '#f6eef7', 'bottom': '#eef0fb'}
def scenario_every_hour_reads_against_the_ink():
    for hour in range(24):
        for stop in ('top', 'mid', 'bottom'):
            assert out['light'][hour]['contrast'][stop] >= 4.5, (hour, stop)
            assert out['dark'][hour]['contrast'][stop] >= 4.5, (hour, stop)
def scenario_dark_is_the_deep_version():
    for hour in range(24):
        assert out['dark'][hour]['luminance_top'] < 0.08
def scenario_four_bands_only():
    assert len({json.dumps(out['light'][h]['sky']) for h in range(24)}) == 4
```

The node script calls `pwaSky(h, false)` and `pwaSky(h, true)` for every hour, computes `pwaSky.contrast(stop, ink)` with ink `#1f1d2b` (light) / `#f3f2f7` (dark), and prints one JSON line.

- [ ] **Step 2: Run it to see it fail**

Run: `cd chauffeur && python tests/test_pwa_sky.py`
Expected: FAIL (`pwaSky` not found).

- [ ] **Step 3: Implement `pwaSky` and the tokens**

Bands: morning 05-11, afternoon 12-16, evening 17-20, night 21-04. Each band is three hexes; top warmer than bottom; the dark version is the same hue family at relative luminance under 0.08. In `pwaSyncShell` set the three vars from `pwaSky(new Date().getHours(), document.documentElement.dataset.theme === 'dark')` and re-run it when the theme changes: `window.applyTheme` (`app.html:35-39`) writes `data-theme`; after that write call `window.pwaSyncSky?.()` (a small exported function that only sets the three vars, so it is safe before the shell has a member). Add the tokens and the body rule to `pwa_shell.css`; `[data-theme="light"]` and `[data-theme="dark"]` variants for ink and card.

- [ ] **Step 4: Live assertion**

In `test_pwa_adult_shell_live.py` adult branch: `assert 'linear-gradient' in page.evaluate("getComputedStyle(document.body).backgroundImage")` and, after `page.evaluate("applyTheme('dark')")`, the same check plus `page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--pwa-sky-top').trim()") != ''`. Then `applyTheme('light')` again. The fixed clock is 12:00, so also assert the vars equal `pwaSky(12,false)`.

- [ ] **Step 5: Run the tests**

Run: `cd chauffeur && python tests/test_pwa_sky.py && python tests/test_pwa_adult_shell_live.py`
Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add chauffeur/static/pwa_shell.js chauffeur/static/pwa_shell.css chauffeur/tests/test_pwa_sky.py chauffeur/tests/test_pwa_adult_shell_live.py
git commit -m "feat(pwa): the adult shell wears a time-of-day sky and the card tokens"
```

---

### Task 4: Pushed screens on the History API

**Files:**
- Create: `chauffeur/static/pwa_nav.js`
- Modify: `chauffeur/templates/components/pwa_shell.html:1` (add `<div id="pwa-stack" hidden></div>` before `#pwa-more-container`), `chauffeur/templates/app.html:113` (load `pwa_nav.js` deferred), `:858-900` (`setView` calls `PwaNav.clear()` first)
- Modify: `chauffeur/static/pwa_shell.css` (`.pwa-screen` chrome)
- Test: `chauffeur/tests/test_pwa_nav.py` (jsdom, harness like `tests/test_pwa_assign_other_driver.py:60-150`)

**Interfaces:**
- Produces: `window.PwaNav = { push({ id, title, render, onPop }), pop(), clear(), depth(), current() }`. `push` appends `<section class="pwa-screen" data-screen=id>` to `#pwa-stack` with a header `<button class="pwa-back" aria-label="Back">‹ {parent title}</button>` and `<h1>{title}</h1>` and a `<div class="pwa-screen-body">` that `render(bodyEl)` fills; sets `#pwa-stack` visible and `html[data-pwa-stack="n"]`; calls `history.pushState({ pwaScreen: id }, '')`. `pop` removes the top screen, calls its `onPop`, and when the stack empties hides `#pwa-stack`. A `popstate` whose state lacks `pwaScreen` with a non-empty stack pops one screen; with an empty stack it does nothing. `clear` pops everything without touching history beyond `history.go(-depth)` when depth > 0. The parent title for the first screen is the current tab's label (`document.querySelector('#pwa-tab-bar [aria-current="page"] > span')?.textContent || 'Back'`).

- [ ] **Step 1: Write the failing jsdom test**

`tests/test_pwa_nav.py` runs `static/pwa_nav.js` in jsdom with a minimal DOM (`#pwa-stack`, a tab bar with one `aria-current="page"` button labelled `Household`) and cases:

```python
'push_draws_chrome': push({'id':'chores','title':'Chores'}) → stack visible, one .pwa-screen, back text '‹ Household', h1 'Chores', history.length grew by 1
'pop_calls_onpop':    push then pop → zero screens, stack hidden, onPop count 1
'back_pops_one':      push a, push b → history.back() → depth 1, current().id == 'a'
'back_with_empty_stack_is_inert': history.back() with depth 0 → depth 0, no error, stack hidden
'clear_empties':      push a, push b → clear() → depth 0, stack hidden
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd chauffeur && python tests/test_pwa_nav.py`
Expected: FAIL (`PwaNav` undefined).

- [ ] **Step 3: Implement `static/pwa_nav.js`, the markup, the CSS and the `setView` hook**

CSS: `#pwa-stack { position:fixed; inset:0 0 var(--pwa-tabbar-h, 84px) 0; z-index: 40; overflow:hidden }`, `.pwa-screen { position:absolute; inset:0; overflow-y:auto; padding: 0 20px 24px; background: inherit }`, `.pwa-back { color: var(--pwa-accent); font-weight:600; font-size:15px; min-height:44px; margin-top: 8px }`, `.pwa-screen h1 { font-size:34px; font-weight:700; letter-spacing:-.03em; margin: 8px 0 4px }`. In `setView` (`app.html:858`) call `window.PwaNav?.clear()` before the same-view early return at 872.

- [ ] **Step 4: Run the tests**

Run: `cd chauffeur && python tests/test_pwa_nav.py && python tests/test_template_js.py && python tests/test_pwa_adult_shell_live.py`
Expected: pass (no live consumer yet; the live test proves the script loads without errors).

- [ ] **Step 5: Commit**

```bash
git add chauffeur/static/pwa_nav.js chauffeur/static/pwa_shell.css chauffeur/templates/components/pwa_shell.html chauffeur/templates/app.html chauffeur/tests/test_pwa_nav.py
git commit -m "feat(pwa): a pushed-screen stack on the History API, hardware Back pops one screen"
```

---

### Task 5: Record it, gate it, ship it

**Files:**
- Modify: `chauffeur/docs/ui_design_guide.md` (new section "Adult PWA, reimagined: the vocabulary" after "Adult PWA presentation")
- Modify: `chauffeur/system_capabilities.md` (new top entry), `chauffeur/config.yaml` (version)
- Test: the gate below

- [ ] **Step 1: Design guide**

Add a section stating: the sky tokens and bands, the card tokens and radius, the orb as the shared component (`static/argyle_orb.*`, class `.argyle-orb`), the tab bar slot rule (equal slots, 18 px edges, orb last), the pushed-screen chrome (`PwaNav`), and that these apply under `html[data-audience="adult"]` only.

- [ ] **Step 2: Capabilities entry and version**

Top of `system_capabilities.md`: a `v2.499.751` paragraph in the house style (what shipped, the files, the tests, "NOT device-verified"). Bump `chauffeur/config.yaml` to `2.499.751`.

- [ ] **Step 3: Gate**

Run, with `HA_BASE_URL` unset, from `chauffeur/`:

```bash
python tests/test_argyle_orb.py && python tests/test_pwa_sky.py && python tests/test_pwa_nav.py && python tests/test_panel_chrome.py && python tests/test_template_js.py && python tests/test_auth.py && python tests/test_pwa_adult_shell_live.py && python tests/test_voice_setup_pwa.py && python tests/test_projects_parity.py
```

Expected: every file prints its `ok` lines; `PWA_REVIEW_OUTPUT=tests/probe_shots/pwa_slice0 python tests/test_pwa_adult_shell_live.py` writes the adult screenshots for the review.

- [ ] **Step 4: Commit**

```bash
git add chauffeur/docs/ui_design_guide.md chauffeur/system_capabilities.md chauffeur/config.yaml chauffeur/tests/probe_shots/pwa_slice0
git commit -m "feat(pwa): slice 0 of the reimagined PWA, the shell (v2.499.751)"
```

---

## Follow-on plans (not this one)

Slice 1 My Day (one brief for every adult, the phone HeroCard skin, the member-scoped hero, the sentence builder, Needs you, the collapsed day), slice 2 the orb overlay (and Ask Argyle leaves More), slice 3 Household cards, slice 4 Messages, slice 5 Plan, slice 6 the drive. Each gets its own plan from the same spec once this slice is on the device.
