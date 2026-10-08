# Settings Drawer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every admin page shows its work first; each page's settings move into one shared right-hand drawer, opened by a single **⚙ Settings** gear at the right end of a page bar that every admin page now has.

**Architecture:** A Jinja macro (`templates/components/settings_drawer.html`) draws the drawer shell around a page's existing settings markup, inside the page's own Alpine island, so bindings and save functions keep working. A small static script (`static/settings_drawer.js`, loaded by `nav.html` on every page) owns the gear, the open/close events, deep links (`#anchor`, `?settings=open`) and the shared save mark. `nav.html`'s PAGE_GROUPS strip becomes a page bar on ungrouped pages too. The settings registry's `audit_ui()` gains a check that a drawer page's anchors sit inside its drawer.

**Tech Stack:** FastAPI + Jinja2 templates, Alpine.js 3.16.1 (vendored), precompiled Tailwind (`tools/build_tailwind.py`), Playwright live tests through `tests/live_app.py`, standalone scenario test scripts run by `tools/test.py`.

**Spec:** `docs/superpowers/specs/2026-10-07-settings-drawer-design.md` — read it first; this plan argues from it.

All paths below are relative to `chauffeur/` unless they start with `docs/`. Line numbers were measured on 2026-10-08 (v2.499.274) and drift as earlier tasks land; find blocks by the quoted markup, not by number alone.

## Global Constraints

- **Scope:** browser admin pages only. Kiosk (`?kiosk=true`), filtered embeds (`?tabs=`) and wall panels (`?panel=true`) render no page bar, no gear, no drawer. The macro enforces this server-side; never add a second client-side guard.
- **Drawer shape (copy exactly from Task 1, never restyle per page):** right slide-over `md:w-[40rem]` over `bg-black/40`; on phones an `h-[88vh]` bottom sheet; `z-[85]`; header "<Title> settings", the save mark, ✕; jump chips only when the drawer has 3 or more sections.
- **Close:** ✕, Escape (unless a global prompt from `control_center.html` is open), or a tap on the backdrop. Closing clears a hash that points into the drawer (`replaceState`).
- **Keys, endpoints, anchors are kept.** Every moved setting keeps its `Settings` key and its endpoint. A moved block's root keeps its registry anchor as its `id`. When a block is wrapped in `settings_section(anchor, …)`, the old element that carried that `id` loses it — **never two elements with one id.**
- **A drawer root is never inside a `<template x-if>` / `<template x-for>`.** The gear looks for `[data-settings-for]` in the DOM at Alpine init; a drawer inside a template is invisible to it. Put the drawer inside the page's island but outside any template.
- **No `transform`, `filter`, `backdrop-filter` or `will-change` on any ancestor of a drawer** (it traps `position: fixed`). Known traps: `dashboard.html` `#page-header` (`backdrop-blur-sm`), `trips.html` `.glass-panel`, `calendar.html` `.glass-panel`. Place the drawer outside them.
- **THE SAVE REPORT PATTERN.** Every save function a drawer control calls reports through the shared helpers, and falls back to the page's old alert only when no drawer is open:

  ```js
  window.chfSettingsSaving();
  try {
      const r = await fetch(/* unchanged URL and body */);
      if (!r.ok) {
          const err = await r.json().catch(() => ({}));
          const msg = err.detail || 'Could not save that just now.';
          if (!window.chfSettingsSaved(false, msg)) showGlobalAlert(msg);
          return;
      }
      window.chfSettingsSaved(true);
      /* the function's existing success work (reloads etc.) stays here */
  } catch (e) {
      if (!window.chfSettingsSaved(false, 'Could not save that just now.')) showGlobalAlert('Could not save that just now.');
  }
  ```

  `chfSettingsSaved`/`chfSettingsSaving` return `true` only when an open drawer showed the mark. On `/map` (no `control_center.html`, so no `showGlobalAlert`) drop the fallback call. Per-section "Saved ✓" chips inside moved blocks are deleted in favour of the header mark.
- **Imports are template-local** (Jinja). Every template or component that calls the macros carries its own line: `{% from 'components/settings_drawer.html' import settings_drawer, settings_section, settings_off with context %}`.
- **No pointers** ("settings are now in ⚙") where a setting used to be. Invisible hash/URL forwards for old bookmarks are fine.
- **No functionality dropped.** Every control a person could operate stays operable. If a task seems to require removing one, stop and ask.
- **Tailwind is precompiled:** after any template class change run `python tools/build_tailwind.py` and commit `static/tailwind.css`.
- **Tests:** run only the task's own tests plus the related tests the task names: `env -u HA_BASE_URL python tools/test.py <keywords>` from `chauffeur/` (Git Bash). **Never** run the full sweep, **never** `--focus` (it selects 200+ files when `nav.html`/`main.py` change), never pipe the gating run. Known baseline reds unrelated to this arc: `test_messaging`, `test_status_protocols`, `test_leave_times_live` ("the wall says the same two departures"), `test_myday_timeline_live`, `test_house_window_groups`, `test_house_facade_live`, House live load failures. Compare against those.
- **Screenshots:** every task that changes a page carries proof — drawer closed and open, dark theme, 1300px desktop and 390px phone. The live tests save them when `CHF_SHOTS=<dir>` is set; look at every image before claiming the task done.
- **Release per task:** at the end of each task: update `system_capabilities.md` (the section for the surface touched, plus the version line at the top), `python tools/bump_version.py` (never hand-edit the version), `git add` only the files the task changed, commit with a subject ending `(vX.Y.Z)` (no double quotes in the message), `git push`. Commit trailer: `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- **UI rules:** read `docs/ui_design_guide.md` first (inside `chauffeur/`). No `alert()/confirm()/prompt()`; use `showGlobalAlert`/`promptConfirm`/`promptInput`. Inside the drawer, inner cards use the dish editor's tiles (`bg-gray-900 rounded-xl`, `templates/shopping.html` editor sheet) rather than the page's `bg-gray-800` cards, because the drawer panel is itself `bg-gray-800`.

## Review Focus

1. **A save fails while the drawer is open** — the header shows the server's message in red and keeps it until the next save; no silent "Saved ✓". Pinned in Task 1's live test (routed 500).
2. **A deep link into a drawer whose tab is not the active one** (`rhythms?tab=routines#lessons`, `work?tab=mind#threads-settings`) — the bar switches tab, then the drawer opens at the section. Pinned in Tasks 1 and 2.
3. **Phone width with a crowded bar** (Work has four tabs) — the gear stays on screen, the sheet is 88vh and scrolls. Pinned in Task 1 (390px).
4. **Escape while a global prompt is open over the drawer** (Programs' "Write lessons now" asks `promptConfirm`) — Escape answers the prompt and leaves the drawer open. Pinned in Task 2.
5. **Typing in an Intake text field** — no request per keystroke; one save on blur. Pinned in Task 6.

---

## Slice 1 — Shell plus pilots

### Task 1: The shell, the page bar, and the Threads pilot

**Files:**
- Create: `templates/components/settings_drawer.html`
- Create: `static/settings_drawer.js`
- Modify: `templates/nav.html` (bar computation after the `_show_tabs` line ~153; strip markup ~262-330; script include after the strip)
- Modify: `templates/rhythms.html:48-71` (delete the `openAnchor` script)
- Modify: `templates/school.html:422-440` (delete the second script, the opener; keep the forwarder at 406-420)
- Modify: `templates/components/threads_page.html:16-30` (stall days into a drawer) and `saveStallDays` (~715)
- Modify: `docs/ui_design_guide.md` (inside `chauffeur/`) — add the placement rules section
- Test: `tests/test_settings_drawer.py` (new, render pins)
- Test: `tests/test_settings_drawer_live.py` (new, Playwright)

**Interfaces:**
- Produces (Jinja, `components/settings_drawer.html`):
  - `settings_drawer(tabs, title, sections=none)` — call-block macro. `tabs` is a space-separated list of page-bar keys (`'threads'`, `'errands tasks'`). `sections` is a list of `(anchor, label)` pairs for the jump chips. Renders nothing on walls.
  - `settings_section(anchor, heading)` — call-block macro; `<section id="{{anchor}}" data-settings-section class="scroll-mt-28">` with a small uppercase heading.
  - `settings_off(message, tab, anchor, show)` — one-line switched-off state; `show` is an Alpine expression; the **Turn on…** button calls `chfOpenSettings(tab, anchor)` and is omitted on walls.
- Produces (JS globals, `static/settings_drawer.js`): `chfOpenSettings(tab?, anchor?)`, `chfCloseSettings()`, `chfSettingsSaving() -> bool`, `chfSettingsSaved(ok, message?) -> bool`, `chfSettingsDrawer()` (Alpine component).
- Produces (window events): `chf-settings-open` `{tab, anchor}`, `chf-settings-close`, `chf-settings-status` `{state, message}`, `chf-settings-opened` `{tab}` (after the drawer is visible), `chf-settings-closed` `{tab}`.
- Produces (DOM): `#page-tabs[data-bar-key]` on every browser admin page; `#page-settings-gear`; drawer root `[data-settings-for]` with `[data-open]` while open; header mark `[data-settings-status]`; panel `[role=dialog]`; chips `[data-settings-chip]`; close button `[aria-label="Close settings"]`.
- Produces (nav JS): `window.chfPageTab()` now returns the bar key on ungrouped pages too.
- Bar keys: grouped pages use the PAGE_GROUPS tab `key`; `/board/<slug>` → `board`; `/config` → `config`; `/settings` → `settings`; otherwise the first `NAV_ITEMS` entry whose `match` is in the path (`home`, `trips`, `map`, `music`, `school` once Task 14 ungroups it).

- [ ] **Step 1: Write the failing render pins**

Create `tests/test_settings_drawer.py`:

```python
"""The settings drawer, rendered (settings-drawer arc, slice 1).

Pages are rendered by calling their route function with a hand-built
Starlette Request — TestClient needs httpx, which is not installed here
(the test_house_facade idiom). A rendered page is what a browser gets, so
these pins see the macro's wall guard and the nav's page bar for real.

Run from chauffeur/:  python tests/test_settings_drawer.py
"""
import asyncio
import inspect
import os
import re
import sys
import tempfile

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='settings_drawer_'))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _render(path, query=''):
    from starlette.requests import Request
    import main
    route = next(r for r in main.app.routes
                 if getattr(r, 'path', None) == path and 'GET' in (getattr(r, 'methods', None) or ()))
    req = Request({'type': 'http', 'method': 'GET', 'path': path,
                   'query_string': query.encode('utf-8'), 'headers': [],
                   'app': main.app, 'router': main.app.router})
    out = route.endpoint(req)
    if inspect.isawaitable(out):
        out = asyncio.run(out)
    return out.body.decode('utf-8')


def scenario_every_admin_page_draws_the_bar():
    """Grouped pages show their tabs; ungrouped ones show their name."""
    for path, key in (('/work', 'mind'), ('/trips', 'trips'), ('/map', 'map'),
                      ('/config', 'config'), ('/settings', 'settings')):
        html = _render(path)
        check('id="page-tabs"' in html, f'{path} draws no page bar')
        check(f'data-bar-key="{key}"' in html, f'{path} bar key is not {key}')
        check('id="page-settings-gear"' in html, f'{path} has no gear button to show')
    check('page-bar-name' in _render('/trips') and '>Trips<' in _render('/trips'),
          'an ungrouped page does not name itself on the bar')


def scenario_walls_get_no_bar_no_gear_no_drawer():
    for path in ('/work', '/trips'):
        for q in ('kiosk=true', 'panel=true', 'tabs=threads'):
            html = _render(path, q)
            check('id="page-tabs"' not in html, f'{path}?{q} draws the page bar')
            check('id="page-settings-gear"' not in html, f'{path}?{q} draws the gear')
            check('data-settings-for' not in html, f'{path}?{q} draws a settings drawer')


def scenario_threads_settings_live_in_a_drawer():
    html = _render('/work', 'tab=threads')
    m = re.search(r'data-settings-for="threads"', html)
    check(m, 'the Threads drawer is missing')
    i = html.index('id="threadStallDays"')
    check(i > m.start(), 'the stall-days input sits outside the Threads drawer')
    check('saveStallDays()' in html, 'the stall-days input lost its save')


def scenario_the_drawer_script_loads_everywhere():
    """The save helpers are called by page code on walls too (they return
    false and the page falls back to its alert), so the script loads even
    where no drawer is drawn."""
    for path, q in (('/work', ''), ('/work', 'kiosk=true'), ('/map', '')):
        check('static/settings_drawer.js' in _render(path, q),
              f'{path}?{q} does not load settings_drawer.js')


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith('scenario_')]

if __name__ == '__main__':
    for fn in SCENARIOS:
        fn()
        print(f'  ok  {fn.__name__}')
    print(f'\n{len(SCENARIOS)}/{len(SCENARIOS)} settings drawer scenarios passed')
```

- [ ] **Step 2: Run it and watch it fail**

Run: `env -u HA_BASE_URL python tests/test_settings_drawer.py`
Expected: FAIL — `/trips draws no page bar` (or `data-bar-key` missing).

- [ ] **Step 3: Create the macro file**

Create `templates/components/settings_drawer.html`:

```jinja
{#
  THE SETTINGS DRAWER (settings-drawer arc).

  A page's settings are reached one way, from one place: the ⚙ Settings gear
  at the right end of the page bar (nav.html) opens the drawer whose
  `data-settings-for` names the active tab. The page wraps its EXISTING
  settings markup in `settings_drawer`, inside its own Alpine island, so every
  binding and save function keeps working; fixed positioning lifts the drawer
  out visually. The shell is the dish editor sheet's (shopping.html), at its
  tier: z-[85], above the Control Center (z-[70]) and the Ask Argyle bar
  (z-[80]), below page dialogs (z-[90]) and global prompts (z-[400]).

  Walls never show settings: a kiosk, a filtered embed and a panel render
  nothing here, and nothing the caller wrapped.

  Import with context (Jinja imports are template-local, and the wall guard
  reads `request`):
    {% from 'components/settings_drawer.html' import settings_drawer, settings_section, settings_off with context %}

  The behaviour lives in static/settings_drawer.js (chfSettingsDrawer).
#}
{% macro settings_drawer(tabs, title, sections=none) -%}
{%- set _q = request.query_params if request is defined else {} -%}
{%- if _q.get('kiosk') != 'true' and _q.get('tabs') is none and _q.get('panel') != 'true' -%}
<div data-settings-for="{{ tabs }}" x-data="chfSettingsDrawer()" x-show="drawerOpen" x-cloak
    :data-open="drawerOpen ? 'true' : null"
    @chf-settings-open.window="drawerOpenFor($event.detail)"
    @chf-settings-close.window="drawerClose()"
    @chf-settings-status.window="drawerStatus($event.detail)"
    @keydown.escape.window="drawerEscape()"
    @click.self="drawerClose()"
    class="fixed inset-0 z-[85] bg-black/40 flex justify-end items-end md:items-stretch">
    <div x-ref="drawerPanel" tabindex="-1" role="dialog" aria-modal="true" aria-label="{{ title }} settings"
        class="bg-gray-800 w-full md:w-[40rem] h-[88vh] md:h-full overflow-y-auto border-t md:border-t-0 md:border-l border-gray-700 rounded-t-2xl md:rounded-none flex flex-col outline-none">
        <div class="sticky top-0 z-10 bg-gray-800 border-b border-gray-700 px-4 py-3">
            <div class="flex items-center gap-3">
                <h2 class="flex-1 min-w-0 text-lg font-extrabold text-white truncate">{{ title }} settings</h2>
                <span data-settings-status x-show="drawerState" x-text="drawerStatusText()"
                    :class="drawerState === 'error' ? 'text-red-300' : (drawerState === 'saved' ? 'text-teal-300' : 'text-gray-400')"
                    class="text-[11px] font-semibold text-right"></span>
                <button type="button" @click="drawerClose()" title="Close" aria-label="Close settings"
                    class="w-8 h-8 shrink-0 rounded-full bg-gray-900 text-white hover:bg-gray-700 font-bold">✕</button>
            </div>
            {%- if sections and sections|length >= 3 %}
            <div class="flex gap-1.5 mt-2.5 overflow-x-auto" style="scrollbar-width: none">
                {%- for anchor, label in sections %}
                <button type="button" data-settings-chip="{{ anchor }}" @click="drawerJump('{{ anchor }}')"
                    class="whitespace-nowrap text-xs font-bold px-2.5 py-1.5 rounded-lg border border-gray-700 text-gray-300 hover:bg-gray-700 hover:text-white transition-colors">{{ label }}</button>
                {%- endfor %}
            </div>
            {%- endif %}
        </div>
        <div class="px-4 pt-4 pb-8 flex flex-col gap-6">
            {{ caller() }}
        </div>
    </div>
</div>
{%- endif -%}
{%- endmacro %}

{% macro settings_section(anchor, heading) -%}
<section id="{{ anchor }}" data-settings-section class="scroll-mt-28">
    <div class="text-xs font-semibold text-gray-500 uppercase tracking-widest mb-2">{{ heading }}</div>
    {{ caller() }}
</section>
{%- endmacro %}

{#
  A feature switched off says so in the work area, honestly and in one line,
  with a way to turn it on. Never a blank or silently empty work area
  (placement rule 4).
#}
{% macro settings_off(message, tab, anchor, show) -%}
{%- set _q = request.query_params if request is defined else {} -%}
<div data-settings-off x-show="{{ show }}" x-cloak
    class="bg-gray-800 rounded-2xl border border-gray-700 px-4 py-3 mb-5 flex items-center justify-between gap-3">
    <p class="text-sm text-gray-300">{{ message }}</p>
    {%- if _q.get('kiosk') != 'true' and _q.get('tabs') is none and _q.get('panel') != 'true' %}
    <button type="button" @click="chfOpenSettings('{{ tab }}', '{{ anchor }}')"
        class="shrink-0 text-xs font-bold px-3 py-1.5 rounded-lg bg-blue-600 text-white hover:bg-blue-500">Turn on…</button>
    {%- endif %}
</div>
{%- endmacro %}
```

- [ ] **Step 4: Create the script**

Create `static/settings_drawer.js`:

```js
/* The settings drawer's behaviour (settings-drawer arc).

   Loaded by nav.html on every page, before Alpine starts (Alpine is
   deferred), so `chfSettingsDrawer` exists when Alpine walks the tree and
   the save helpers exist for page code everywhere — on a wall they simply
   report that no drawer showed the mark, and the page falls back to its
   own alert. */
(function () {
    'use strict';

    function keysOf(el) {
        return ((el && el.getAttribute('data-settings-for')) || '').split(/\s+/).filter(Boolean);
    }
    function drawerFor(tab) {
        if (!tab) return null;
        return document.querySelector('[data-settings-for~="' + CSS.escape(tab) + '"]');
    }
    function activeTab() {
        return typeof window.chfPageTab === 'function' ? window.chfPageTab() : null;
    }
    function anyOpen() {
        return !!document.querySelector('[data-settings-for][data-open]');
    }
    // A global prompt (control_center.html, z-[400]) open above the drawer
    // owns Escape; the drawer under it stays put.
    function promptOpen() {
        return !!document.querySelector(
            '#cc-confirm-modal:not(.hidden), #cc-alert-modal:not(.hidden),' +
            ' #cc-input-modal:not(.hidden), #cc-choice-modal:not(.hidden)');
    }

    window.chfOpenSettings = function (tab, anchor) {
        window.dispatchEvent(new CustomEvent('chf-settings-open',
            { detail: { tab: tab || activeTab(), anchor: anchor || null } }));
    };
    window.chfCloseSettings = function () {
        window.dispatchEvent(new CustomEvent('chf-settings-close'));
    };
    window.chfSettingsSaving = function () {
        window.dispatchEvent(new CustomEvent('chf-settings-status', { detail: { state: 'saving' } }));
        return anyOpen();
    };
    window.chfSettingsSaved = function (ok, message) {
        window.dispatchEvent(new CustomEvent('chf-settings-status',
            { detail: { state: ok ? 'saved' : 'error', message: message || '' } }));
        return anyOpen();
    };

    window.chfSettingsDrawer = function () {
        return {
            drawerOpen: false,
            drawerTab: null,
            drawerState: '',
            drawerMsg: '',
            _drawerTimer: null,

            drawerOpenFor(detail) {
                const d = detail || {};
                if (!keysOf(this.$root).includes(d.tab)) {
                    // One drawer at a time.
                    if (this.drawerOpen) this.drawerClose();
                    return;
                }
                this.drawerOpen = true;
                this.drawerTab = d.tab;
                this.drawerState = '';
                this.drawerMsg = '';
                this.$nextTick(() => {
                    const panel = this.$refs.drawerPanel;
                    const target = d.anchor ? document.getElementById(d.anchor) : null;
                    if (target && this.$root.contains(target)) target.scrollIntoView({ block: 'start' });
                    else if (panel) panel.scrollTop = 0;
                    if (panel) panel.focus({ preventScroll: true });
                    window.dispatchEvent(new CustomEvent('chf-settings-opened', { detail: { tab: d.tab } }));
                });
            },
            drawerClose() {
                if (!this.drawerOpen) return;
                this.drawerOpen = false;
                const tab = this.drawerTab;
                // A hash that pointed in here would reopen it on reload.
                try {
                    const id = decodeURIComponent((location.hash || '').slice(1));
                    const el = id ? document.getElementById(id) : null;
                    if (el && this.$root.contains(el))
                        history.replaceState(history.state, '', location.pathname + location.search);
                } catch (e) { }
                window.dispatchEvent(new CustomEvent('chf-settings-closed', { detail: { tab } }));
                const gear = document.getElementById('page-settings-gear');
                if (gear && !gear.classList.contains('hidden')) gear.focus({ preventScroll: true });
            },
            drawerEscape() {
                if (this.drawerOpen && !promptOpen()) this.drawerClose();
            },
            drawerJump(id) {
                const el = document.getElementById(id);
                if (el) el.scrollIntoView({ block: 'start', behavior: 'smooth' });
            },
            drawerStatus(detail) {
                if (!this.drawerOpen) return;
                const d = detail || {};
                clearTimeout(this._drawerTimer);
                this.drawerState = d.state || '';
                this.drawerMsg = d.message || '';
                if (d.state === 'saved')
                    this._drawerTimer = setTimeout(() => { this.drawerState = ''; }, 2500);
                if (d.state === 'saving')
                    this._drawerTimer = setTimeout(() => {
                        if (this.drawerState === 'saving') this.drawerState = '';
                    }, 15000);
            },
            drawerStatusText() {
                if (this.drawerState === 'saving') return 'Saving…';
                if (this.drawerState === 'saved') return 'Saved ✓';
                if (this.drawerState === 'error') return this.drawerMsg || 'Could not save that just now.';
                return '';
            },
        };
    };

    // The page bar's in-page tab links (nav.html). A hidden tab block hides
    // everything in it, a drawer included, so the tab opens first.
    function switchTab(tab) {
        const link = document.querySelector('#page-tabs a[data-inpage-tab="' + tab + '"]');
        if (link && !link.classList.contains('bg-blue-600')) link.click();
    }
    function syncGear() {
        const gear = document.getElementById('page-settings-gear');
        if (gear) gear.classList.toggle('hidden', !drawerFor(activeTab()));
    }
    // One path for every deep link (it replaces the per-page openers that
    // rhythms.html and school.html carried): an anchor in a tab opens the
    // tab; an anchor in a drawer opens the drawer at it; `?settings=open`
    // opens the active tab's drawer at the top (the forwards from retired
    // settings tabs land here).
    function openFromAddress() {
        let handled = false;
        let id = '';
        try { id = decodeURIComponent((location.hash || '').slice(1)); } catch (e) { }
        const el = id ? document.getElementById(id) : null;
        if (el) {
            const block = el.closest('[data-page-tab]');
            if (block) switchTab(block.getAttribute('data-page-tab'));
            const drawer = el.closest('[data-settings-for]');
            if (drawer) {
                const keys = keysOf(drawer);
                const act = activeTab();
                window.chfOpenSettings(keys.includes(act) ? act : keys[0], id);
                handled = true;
            } else if (block) {
                setTimeout(() => el.scrollIntoView({ block: 'start' }), 50);
            }
        }
        const q = new URLSearchParams(location.search);
        if (q.get('settings') === 'open') {
            q.delete('settings');
            const qs = q.toString();
            try { history.replaceState(history.state, '', location.pathname + (qs ? '?' + qs : '') + location.hash); } catch (e) { }
            if (!handled && drawerFor(activeTab())) window.chfOpenSettings(activeTab());
        }
    }

    let booted = false;
    function boot() {
        if (booted) return;
        booted = true;
        syncGear();
        openFromAddress();
    }
    document.addEventListener('alpine:initialized', boot);
    window.addEventListener('load', boot);
    window.addEventListener('hashchange', openFromAddress);
    window.addEventListener('chf-page-tab', syncGear);
    document.addEventListener('click', ev => {
        if (ev.target.closest && ev.target.closest('#page-settings-gear')) {
            ev.preventDefault();
            window.chfOpenSettings(activeTab());
        }
    });
})();
```

- [ ] **Step 5: Turn the strip into the page bar (`templates/nav.html`)**

5a. Replace the line `{% set _show_tabs = _pg.group and not _full_nav and _qp.get('panel') != 'true' %}` with:

```jinja
{#
  THE PAGE BAR (settings-drawer arc). Every browser admin page gets one:
  a grouped page shows its tabs, an ungrouped page its name, and the right
  end carries ⚙ Settings, which settings_drawer.js shows only when the
  active tab has a drawer. `_bar.key` is the key a drawer names in
  `data-settings-for`. Config and Find a setting get the bar without a
  gear: they ARE settings pages.
#}
{% set _bar = namespace(key=none, label=none) %}
{% if _pg.group %}
  {% set _bar.key = _active_tab.key %}
{% elif '/board/' in _path %}
  {% set _bar.key = 'board' %}{% set _bar.label = 'Board' %}
{% elif _path.endswith('/config') %}
  {% set _bar.key = 'config' %}{% set _bar.label = 'Settings' %}
{% elif _path.endswith('/settings') %}
  {% set _bar.key = 'settings' %}{% set _bar.label = 'Find a setting' %}
{% else %}
  {% for item in NAV_ITEMS if item.match in _path and _bar.key is none %}
    {% set _bar.key = item.slug %}{% set _bar.label = item.label %}
  {% endfor %}
{% endif %}
{% set _show_bar = _bar.key and not _full_nav and _qp.get('panel') != 'true' %}
```

5b. In the strip block (`{% if _show_tabs %}` … `{% endif %}`, ~262-330): change `{% if _show_tabs %}` to `{% if _show_bar %}`, update the comment above it to say it is the page bar, and replace the `<div id="page-tabs" …>` element with:

```html
    <div id="page-tabs" class="border-t border-gray-800" data-group="{{ _pg.group or '' }}" data-bar-key="{{ _bar.key }}">
        <div class="px-4 sm:px-6 lg:px-8 flex items-center gap-2 h-11">
            <div class="flex items-center gap-1 min-w-0 flex-1 overflow-x-auto" style="scrollbar-width: none">
                {% if _pg.group %}
                {% for t in PAGE_GROUPS[_pg.group] %}
                {% set _here = t.key == _active_tab.key %}
                <a href="{{ _up }}{{ t.href }}" data-tab-key="{{ t.key }}"
                    {% if t.tab and t.path in _path %}data-inpage-tab="{{ t.tab }}"{% endif %}
                    class="page-tab {% if _here %}bg-blue-600 text-white{% else %}text-gray-400 hover:bg-gray-700 hover:text-white{% endif %} whitespace-nowrap px-3 py-1.5 rounded-lg text-sm font-bold transition-colors flex items-center gap-1.5">
                    {{ t.label }}
                    <span class="page-tab-count hidden text-[10px] font-bold px-1.5 py-0.5 rounded bg-gray-700 text-gray-300"></span>
                </a>
                {% endfor %}
                {% else %}
                <span class="page-bar-name whitespace-nowrap px-3 py-1.5 text-sm font-bold text-white">{{ _bar.label }}</span>
                {% endif %}
            </div>
            <button type="button" id="page-settings-gear" aria-label="Settings for this page"
                class="hidden shrink-0 whitespace-nowrap px-3 py-1.5 rounded-lg text-sm font-bold text-gray-300 hover:bg-gray-700 hover:text-white transition-colors flex items-center gap-1.5">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                        d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"></path>
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path>
                </svg>
                Settings
            </button>
        </div>
    </div>
```

The `<style id="page-tab-style">` line stays guarded by `{% if _active_tab.tab and _active_tab.path in _path %}` — but `_active_tab` is undefined-ish on ungrouped pages, so change that guard to `{% if _pg.group and _active_tab.tab and _active_tab.path in _path %}`.

5c. In the strip `<script>`: `mark(key)` gains `strip.dataset.barKey = key;` as its first line, and `window.chfPageTab` becomes:

```js
        window.chfPageTab = function () {
            return strip.dataset.barKey || null;
        };
```

5d. Directly after the strip's `{% endif %}`, outside every condition, add:

```html
    <script src="{{ 'static/settings_drawer.js'|ver }}"></script>
```

5e. `grep -n "_show_tabs" templates/` must return nothing afterwards (rename any other use to `_show_bar`).

- [ ] **Step 6: Delete the two per-page openers**

- `templates/rhythms.html`: delete the whole `<script>` block whose comment starts `// An anchor (rhythms#growing-up, rhythms#kid-evenings from the` (lines ~48-71). `settings_drawer.js` `openFromAddress` does the same for non-drawer anchors.
- `templates/school.html`: delete the second inline script (the `openAnchor` IIFE, ~422-440). Keep the first one (the old-link forwarder, ~406-420) untouched.

- [ ] **Step 7: Threads pilot (`templates/components/threads_page.html`)**

7a. Add as the file's first line after the header comment: `{% from 'components/settings_drawer.html' import settings_drawer, settings_section, settings_off with context %}`

7b. Replace the block from `<!-- Settings: thread_stall_days lives here, not on /config. -->` through the closing `</div>` of that card (lines ~16-30) with:

```html
            {% call settings_drawer('threads', 'Threads') %}
            {% call settings_section('threads-settings', 'Stalls') %}
            <div class="bg-gray-900 rounded-xl px-4 py-3 flex items-center justify-between gap-3">
                <div>
                    <label for="threadStallDays" class="text-xs font-semibold text-gray-200">Stalls after (days)</label>
                    <p class="text-[11px] text-gray-500 mt-0.5">
                        No movement for this long on an open thread counts as
                        quiet. A past next-action date stalls it immediately
                        either way.
                    </p>
                </div>
                <input type="number" min="1" id="threadStallDays" x-model.number="s.thread_stall_days" @change="saveStallDays()"
                    class="w-20 bg-gray-800 border border-gray-700 rounded-lg px-2 py-1.5 text-white text-center shrink-0">
            </div>
            {% endcall %}
            {% endcall %}
```

7c. Rewrite `saveStallDays()` with THE SAVE REPORT PATTERN:

```js
                async saveStallDays() {
                    const days = Math.max(1, parseInt(this.s.thread_stall_days, 10) || 7);
                    this.s.thread_stall_days = days;
                    window.chfSettingsSaving();
                    try {
                        const r = await fetch(this.apiBase + 'api/settings', {
                            method: 'POST', headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ thread_stall_days: days })
                        });
                        if (!r.ok) {
                            const err = await r.json().catch(() => ({}));
                            const msg = err.detail || 'Could not save that just now.';
                            if (!window.chfSettingsSaved(false, msg)) showGlobalAlert(msg);
                            return;
                        }
                        window.chfSettingsSaved(true);
                    } catch (e) {
                        if (!window.chfSettingsSaved(false, 'Could not save that just now.')) showGlobalAlert('Could not save that just now.');
                    }
                },
```

- [ ] **Step 8: Placement rules in the design guide**

In `chauffeur/docs/ui_design_guide.md`, insert after the `## The vocabulary (with the canonical source)` section (before `## Spatial house surfaces`):

```markdown
## Where settings go

Every browser admin page carries a page bar (`nav.html`): its tabs, or its
name, and **⚙ Settings** at the right end. The gear opens the active tab's
drawer — `templates/components/settings_drawer.html`, behaviour in
`static/settings_drawer.js` — and nothing else.

1. **Settings for the whole page** live in the page's drawer, never in the
   work flow.
2. **Settings for one item** live in that item's editor (a reward's active
   switch, a child's school hours, a dish's details), not in the drawer.
3. **Work actions that write a setting** stay in the work area: Block sender
   in Intake, Graduate in Mind.
4. **A feature switched off** shows an honest one-line state in the work area
   with a **Turn on…** button that opens the drawer at the switch
   (`settings_off`). Never a blank or silently empty work area.
5. **No pointers** ("settings are now in ⚙") where a setting used to be.
6. **Walls never show settings.** Kiosk, `?tabs=` and panel views render no
   drawer; the macro enforces it.

Mechanics: wrap the existing markup in `{% call settings_drawer(tab, title,
sections) %}` inside the page's own Alpine island and outside any
`<template>`; no `transform`/`filter`/`backdrop-filter` ancestor; each
section root keeps its registry anchor as its `id`; saves report through
`chfSettingsSaving()` / `chfSettingsSaved(ok, message)`. Config and Find a
setting are settings pages and have no drawer.
```

- [ ] **Step 9: Build Tailwind, run the render pins**

Run: `python tools/build_tailwind.py` then `env -u HA_BASE_URL python tests/test_settings_drawer.py`
Expected: `4/4 settings drawer scenarios passed`.

- [ ] **Step 10: Write the live test**

Create `tests/test_settings_drawer_live.py`:

```python
"""The settings drawer, actually clicked (settings-drawer arc).

A drawer is a fixed overlay inside a page's Alpine island; whether it covers
the viewport, opens from the gear, saves, reports and closes is only true in
a layout engine. One file for the shell and the slice-1 pilots; later
slices add their own files.

Set CHF_SHOTS=<dir> to save the screenshots the arc requires.
Run from chauffeur/:  python tests/test_settings_drawer_live.py
"""
import os
import sys
import tempfile

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='settings_drawer_live_'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from live_app import live_app
from services import storage

SHOTS = os.environ.get('CHF_SHOTS')
DRAWER = '[data-settings-for~="threads"]'


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _visible(page, sel):
    return page.evaluate(
        "(s) => { const el = document.querySelector(s);"
        " return !!el && getComputedStyle(el).display !== 'none'; }", sel)


def _changed(before, after):
    return {k for k in set(before) | set(after) if before.get(k) != after.get(k)}


def _shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        page.screenshot(path=os.path.join(SHOTS, name + '.png'))


def seed():
    storage.update_settings({'llm_gemini_api_key': 'test-key', 'thread_stall_days': 7})
    storage.add_member({'id': 'mum', 'name': 'Mum', 'role': 'parent', 'color_code': '#6366f1'})


def main():
    served = live_app(seed)
    if served is None:
        return
    try:
        handle = served.browser(color_scheme='dark')
        with handle as page:
            page.set_viewport_size({'width': 1300, 'height': 900})
            page.goto(served.url('work?tab=threads'), wait_until='networkidle')
            check(_visible(page, '#page-settings-gear'), 'Threads shows no gear')
            check(not _visible(page, DRAWER), 'the drawer starts open')
            _shot(page, 'threads-closed-desktop')

            page.click('#page-settings-gear')
            page.wait_for_selector(DRAWER + '[data-open]')
            box = page.evaluate(
                "(s) => { const r = document.querySelector(s).getBoundingClientRect();"
                " return [r.left, r.top, r.width, r.height, innerWidth, innerHeight]; }", DRAWER)
            check(box[0] == 0 and box[1] == 0 and box[2] == box[4] and box[3] == box[5],
                  f'the drawer does not cover the viewport: {box}')
            _shot(page, 'threads-open-desktop')

            before = storage.get_settings()
            with page.expect_request(lambda r: r.url.endswith('/api/settings') and r.method == 'POST'):
                page.fill('#threadStallDays', '11')
                page.dispatch_event('#threadStallDays', 'change')
            page.wait_for_selector(DRAWER + ' [data-settings-status]:has-text("Saved")')
            check(_changed(before, storage.get_settings()) == {'thread_stall_days'},
                  'saving stall days changed other settings')

            page.keyboard.press('Escape')
            page.wait_for_timeout(150)
            check(not _visible(page, DRAWER), 'Escape did not close the drawer')
            page.reload(wait_until='networkidle')
            page.click('#page-settings-gear')
            page.wait_for_selector(DRAWER + '[data-open]')
            check(page.input_value('#threadStallDays') == '11', 'the stall days did not stick')

            # A failed save says so, in the header, in the server's words.
            page.route('**/api/settings', lambda route: route.fulfill(
                status=500, content_type='application/json', body='{"detail": "The house said no"}')
                if route.request.method == 'POST' else route.continue_())
            page.fill('#threadStallDays', '12')
            page.dispatch_event('#threadStallDays', 'change')
            page.wait_for_selector(DRAWER + ' [data-settings-status]:has-text("The house said no")')
            page.unroute('**/api/settings')
            page.click(DRAWER + ' [aria-label="Close settings"]')

            # Deep link from another tab: the bar switches, the drawer opens.
            page.goto(served.url('work?tab=mind#threads-settings'), wait_until='networkidle')
            page.wait_for_selector(DRAWER + '[data-open]')
            check(_visible(page, '[data-page-tab="threads"]'), 'the deep link did not switch to Threads')
            check('tab=threads' in page.url, f'the bar forgot the tab: {page.url}')
            page.click(DRAWER + ' [aria-label="Close settings"]')
            check('#' not in page.url, f'closing left the hash: {page.url}')
            page.reload(wait_until='networkidle')
            check(not _visible(page, DRAWER), 'a reload after closing reopened the drawer')

            # Settings pages carry the bar, never a gear.
            for path in ('config', 'settings'):
                page.goto(served.url(path), wait_until='domcontentloaded')
                page.wait_for_timeout(300)
                check(_visible(page, '#page-tabs'), f'/{path} has no page bar')
                check(not _visible(page, '#page-settings-gear'), f'/{path} shows a gear')

            # Phone: the gear stays on screen beside four tabs; the sheet is 88vh.
            page.set_viewport_size({'width': 390, 'height': 844})
            page.goto(served.url('work?tab=threads'), wait_until='networkidle')
            gear = page.evaluate("() => document.getElementById('page-settings-gear').getBoundingClientRect().right")
            check(gear <= 390, f'the gear is off screen on a phone: right={gear}')
            _shot(page, 'threads-closed-phone')
            page.click('#page-settings-gear')
            page.wait_for_selector(DRAWER + '[data-open]')
            sheet = page.evaluate("(s) => { const r = document.querySelector(s + ' [role=dialog]').getBoundingClientRect(); return [r.top, r.bottom, innerHeight]; }", DRAWER)
            check(abs(sheet[1] - sheet[2]) < 2 and abs((sheet[1] - sheet[0]) - 0.88 * sheet[2]) < 4,
                  f'the phone sheet is not an 88vh bottom sheet: {sheet}')
            _shot(page, 'threads-open-phone')

            # Walls: no bar, no gear, no drawer.
            for q in ('work?kiosk=true', 'work?panel=true', 'work?tabs=threads'):
                page.goto(served.url(q), wait_until='domcontentloaded')
                check(page.query_selector('[data-settings-for]') is None, f'{q} drew a drawer')
                check(page.query_selector('#page-settings-gear') is None, f'{q} drew the gear')

            errors = [e for e in handle.errors if 'Failed to load resource' not in e]
            check(not errors, f'page errors: {errors[:3]}')
    finally:
        served.stop()
    print('test_settings_drawer_live OK')


if __name__ == '__main__':
    main()
```

- [ ] **Step 11: Run the task's tests and the related ones**

Run: `env -u HA_BASE_URL CHF_SHOTS="$TEMP/chf_shots_t1" python tools/test.py settings_drawer nav page_tabs school_page rhythms_settings threads`
Expected: all pass (or match the baseline reds listed in Global Constraints). `test_rhythms_settings_live` and `test_school_page_live` exercise the deleted openers through the new shared path — if either fails on a deep link, fix `settings_drawer.js`, not the test. Open every screenshot in `$TEMP/chf_shots_t1` and check it.

- [ ] **Step 12: Capabilities, release**

Add a "The settings drawer" paragraph to `system_capabilities.md` (top of the shipped list): the page bar on every browser admin page, the gear rule, the macro and script, the events and helpers, deep links (`#anchor`, `?settings=open`), the wall guard, Threads as the first drawer. Then bump, commit `feat(settings): a page bar on every admin page, the settings drawer, Threads first (vX.Y.Z)`, push.

---

### Task 2: The registry audit's drawer check, and the Programs pilot

**Files:**
- Modify: `services/settings_registry.py` (`audit_ui` `_read` and the anchor check, ~742-826; threads entry ~645; programs entries ~670-698)
- Modify: `templates/components/programs_page.html` (accordion 27-171; `settingsOpen` ~848; `saveProgramSettings` ~1021)
- Test: `tests/test_settings_registry.py` (new scenario)
- Test: `tests/test_settings_drawer_live.py` (Programs scenarios appended)

**Interfaces:**
- Consumes: Task 1's macros and JS helpers.
- Produces: `settings_registry._drawer_spans(body) -> list[tuple[int, int]]`; `audit_ui()` flags `"#<anchor> sits outside the settings drawer on '<page>'"` and `"a drawer page needs a real anchor"`. Registry `page` may carry a query (`work?tab=threads`); the audit reads the template named by the part before `?`.

- [ ] **Step 1: Write the failing audit scenario**

Append to `tests/test_settings_registry.py` before the `SCENARIOS` line (match the file's existing `check` helper and imports):

```python
def scenario_a_drawer_page_keeps_its_settings_in_the_drawer():
    """Placement rule 1, enforced: on a page that has a settings drawer,
    every registry anchor of that page sits inside the drawer. Config is a
    settings page and is exempt."""
    import tempfile
    from services import settings_registry as reg
    tpl = tempfile.mkdtemp(prefix='reg_drawer_')
    with open(os.path.join(tpl, 'demo.html'), 'w', encoding='utf-8') as fh:
        fh.write("{% call settings_drawer('demo', 'Demo') %}"
                 "{% call settings_section('inside', 'In') %}<input x-model=\"s.thread_stall_days\">{% endcall %}"
                 "{% endcall %}"
                 "<div id=\"outside\"><input x-model=\"s.gift_lead_days\"></div>")
    spans = reg._drawer_spans(open(os.path.join(tpl, 'demo.html'), encoding='utf-8').read())
    check(len(spans) == 1, f'one drawer, nested section call included: {spans}')
    saved = reg.ENTRIES[:]
    try:
        reg.ENTRIES[:] = [
            reg._e('thread_stall_days', 'threads', 'a', 'b', page='demo', anchor='inside'),
            reg._e('gift_lead_days', 'meals', 'a', 'b', page='demo', anchor='outside'),
            reg._e('days_to_show', 'daily', 'a', 'b', page='demo'),
        ]
        why = {e['key']: e['why'] for e in reg.audit_ui(tpl)['unreachable']}
    finally:
        reg.ENTRIES[:] = saved
    check('thread_stall_days' not in why, 'an anchor inside the drawer was flagged')
    check('outside the settings drawer' in why.get('gift_lead_days', ''),
          'an anchor outside the drawer was not flagged')
    check('needs a real anchor' in why.get('days_to_show', ''),
          'a general anchor on a drawer page was not flagged')
```

(`days_to_show` has no control in the demo either; the scenario only asserts the anchor message appears, so make the anchor check run before giving up — see Step 3 ordering.)

- [ ] **Step 2: Run it and watch it fail**

Run: `env -u HA_BASE_URL python tests/test_settings_registry.py`
Expected: FAIL — `AttributeError: module 'services.settings_registry' has no attribute '_drawer_spans'`.

- [ ] **Step 3: Implement the check**

In `services/settings_registry.py`:

3a. Add above `audit_ui`:

```python
_CALL_TOKEN = None


def _drawer_spans(body: str):
    """Where each `{% call settings_drawer(...) %}` … `{% endcall %}` sits.

    Call blocks nest (a drawer holds `settings_section` calls), so the
    matching endcall is found by depth rather than by the first one."""
    import re
    global _CALL_TOKEN
    if _CALL_TOKEN is None:
        _CALL_TOKEN = re.compile(r'{%-?\s*(call\b[^%]*?|endcall)\s*-?%}')
    spans, stack = [], []
    for m in _CALL_TOKEN.finditer(body):
        tok = m.group(1).strip()
        if tok == 'endcall':
            if stack:
                start, is_drawer = stack.pop()
                if is_drawer:
                    spans.append((start, m.end()))
        else:
            stack.append((m.start(), 'settings_drawer(' in tok))
    return spans
```

3b. In `audit_ui._read`, inline includes **in place** instead of appending them (a drawer that wraps an `{% include %}` must keep its contents inside its span). Replace the body of `_read` after the `open` with:

```python
        body = _markup_only(body)
        return re.sub(r"{%-?\s*include\s+'([^']+)'[^%]*%}",
                      lambda m: _read(m.group(1), seen), body)
```

(delete the old `includes = re.findall(...)` / append loop).

3c. In `_text(page)`, read the template for the route part only:

```python
    def _text(page):
        base = page.split('?')[0]
        if base not in cache:
            cache[base] = _read(PAGE_TEMPLATES.get(base, f'{base}.html'), set())
        return cache[base]
```

3d. In the `for e in ENTRIES:` loop, add the drawer checks immediately after `body = _text(e['page'])` and the empty-body `continue`, **before** the key search, so a misplaced anchor is reported even when the key is also missing:

```python
        spans = _drawer_spans(body)
        if spans and e['page'].split('?')[0] != 'config':
            if e['anchor'] == 'general':
                missing.append({**e, 'why': f"a drawer page needs a real anchor (on '{e['page']}')"})
                continue
            at = re.search(r'id="%s"' % re.escape(e['anchor']), body)
            if at and not any(a <= at.start() < b for a, b in spans):
                missing.append({**e, 'why': f"#{e['anchor']} sits outside the settings drawer on '{e['page']}'"})
                continue
```

3e. Registry entries:
- `thread_stall_days`: `page='work?tab=threads', anchor='threads-settings'`.
- Every `programs` entry: `page='rhythms?tab=programs'`; `program_lessons_enabled` and `lesson_help_daily_cap` keep `anchor='lessons'`; `programs_enabled` and `programs_generate_enabled` get `anchor='programs-settings'`; `programs_ask_grace_hours`, `programs_rebaseline_days`, `programs_rebaseline_cooldown_days`, `programs_research_pages` get `anchor='programs-pacing'`.

- [ ] **Step 4: Programs into its drawer (`templates/components/programs_page.html`)**

4a. Add the import line at the top of the file (after any header comment).

4b. Replace the whole accordion card (the comment at ~27 and `<div class="bg-gray-800 rounded-2xl border border-gray-700 p-4 mb-6">` through its closing `</div>` at ~171, including the `@click="settingsOpen = !settingsOpen"` toggle and the `x-show="settingsOpen"` wrapper) with a drawer holding the same controls, regrouped and otherwise unchanged:

```html
            {% call settings_drawer('programs', 'Programs', sections=[('programs-settings', 'Programs'), ('lessons', 'Lessons'), ('programs-pacing', 'Pacing')]) %}
            {% call settings_section('programs-settings', 'Programs') %}
            <div class="bg-gray-900 rounded-xl p-4 space-y-3">
                {# MOVE HERE, unchanged: the Programs on/off label (old 35-45)
                   and the make-a-plan-when-none-found label (old 46-56). #}
            </div>
            {% endcall %}
            <section data-settings-section class="scroll-mt-28">
                <div class="text-xs font-semibold text-gray-500 uppercase tracking-widest mb-2">Lessons</div>
                <div class="bg-gray-900 rounded-xl p-4 space-y-3">
                    {# MOVE HERE, unchanged: <label id="lessons"> lesson scripts
                       (old 57-68), questions a day (old 69-83), and the
                       "Write lessons now" block with sweepReport and ▶ Play
                       (old 84-125). The label keeps id="lessons"; that is
                       this section's anchor. #}
                </div>
            </section>
            {% call settings_section('programs-pacing', 'Pacing') %}
            <div class="bg-gray-900 rounded-xl p-4 space-y-3">
                {# MOVE HERE, unchanged: Ask after (old 126-136), Look back
                   (old 137-147), Re-baseline at most every (old 148-158),
                   Pages to read (old 159-169). #}
            </div>
            {% endcall %}
            {% endcall %}
            {{ settings_off('Programs are off — nothing is asked, re-planned or found.', 'programs', 'programs-settings', 'settingsLoaded && !s.programs_enabled') }}
```

The `{# MOVE HERE #}` comments are instructions to you: cut each named block from the old accordion and paste it in that spot verbatim, then delete the comment. The same convention holds in every later task. Moved inputs keep their own classes; only the surrounding card becomes the `bg-gray-900` tile shown.

4c. Script: delete `settingsOpen: false`. Add `settingsLoaded: false` to the state and set `this.settingsLoaded = true;` in `load()` right after the `api/settings` values are copied into `this.s` (~919-926), so the off state never flashes before the values arrive.

4d. `saveProgramSettings()` adopts THE SAVE REPORT PATTERN (body stays `JSON.stringify(this.s)`).

4e. `playSweepSlot` opens the lesson player at `z-[90]`, above the drawer — leave it. `runLessonSweep` keeps its `promptConfirm`.

- [ ] **Step 5: Append Programs live scenarios**

In `tests/test_settings_drawer_live.py`, add before the walls loop:

```python
            # Programs: a deep link from another tab lands on the section.
            page.set_viewport_size({'width': 1300, 'height': 900})
            P = '[data-settings-for~="programs"]'
            page.goto(served.url('rhythms?tab=routines#lessons'), wait_until='networkidle')
            page.wait_for_selector(P + '[data-open]')
            check(_visible(page, '[data-page-tab="programs"]'), 'rhythms#lessons did not open Programs')
            top = page.evaluate("() => document.getElementById('lessons').getBoundingClientRect().top")
            check(0 <= top < 260, f'#lessons is not in view in the drawer: top={top}')
            check(page.locator(P + ' [data-settings-chip]').count() == 3, 'Programs has no jump chips')
            _shot(page, 'programs-open-desktop')

            # Escape belongs to a global prompt open above the drawer.
            page.evaluate("() => { window.promptConfirm('Write lessons now?', 'Test'); }")
            page.wait_for_selector('#cc-confirm-modal:not(.hidden)')
            page.keyboard.press('Escape')
            page.wait_for_timeout(200)
            check(_visible(page, P), 'Escape on a prompt closed the drawer under it')
            if _visible(page, '#cc-confirm-modal'):
                page.click('#cc-confirm-modal button:has-text("Cancel")')

            # A switch saves, reports, sticks.
            before = storage.get_settings()
            page.click('#programs-settings input[type=checkbox] >> nth=0')
            page.wait_for_selector(P + ' [data-settings-status]:has-text("Saved")')
            check('programs_enabled' in _changed(before, storage.get_settings()) or
                  'programs_generate_enabled' in _changed(before, storage.get_settings()),
                  'the Programs switch did not save')
            page.click(P + ' [aria-label="Close settings"]')
```

If `#cc-confirm-modal` closes itself on Escape, the `if` is skipped; if it does not, the Cancel click closes it (match the button text in `control_center.html` ~42-53 if it differs).

- [ ] **Step 6: Run the task's tests and the related ones**

Run: `python tools/build_tailwind.py` then `env -u HA_BASE_URL CHF_SHOTS="$TEMP/chf_shots_t2" python tools/test.py settings_registry settings_drawer programs lesson_player routine_lanes page_tabs`
Expected: all pass. `audit_ui()` must report nothing for the real registry. Look at the Programs screenshot.

- [ ] **Step 7: Capabilities, release**

`system_capabilities.md`: the audit's drawer rule, Programs' drawer (three sections, chips, the off state). Bump; commit `feat(settings): Programs settings in the drawer; the registry audit keeps drawer anchors inside it (vX.Y.Z)`; push.

---

## Slice 2 — Work

### Task 3: Mind

**Files:**
- Modify: `templates/components/mind_page.html` (settings 15-183; `save()` ~592; `saveWatchers()` ~407; `load()` ~391)
- Modify: `services/settings_registry.py` (mind_*, negotiation_*, proactive_watchers_enabled)
- Modify: `tests/test_mind_settings.py` (page assertions)
- Test: `tests/test_settings_drawer_work_live.py` (new)

**Interfaces:**
- Consumes: Task 1 macros/helpers; Task 2 audit.
- Produces: drawer `data-settings-for="mind"`, sections `mind-general`, `negotiation`, `heads-ups`.

- [ ] **Step 1: Write the failing live test**

Create `tests/test_settings_drawer_work_live.py` with the same header, helpers (`check`, `_visible`, `_changed`, `_shot`), `SHOTS` and `seed()` as `tests/test_settings_drawer_live.py` (copy them verbatim; seed adds `'mind_enabled': False, 'missions_enabled': False`), and this `main()` body inside the `with handle as page:` block:

```python
            page.set_viewport_size({'width': 1300, 'height': 900})
            M = '[data-settings-for~="mind"]'
            page.goto(served.url('work?tab=mind'), wait_until='networkidle')
            # Rule 4: off says so in the work area, with a way back on.
            page.wait_for_selector('[data-page-tab="mind"] [data-settings-off]', state='visible')
            check(not _visible(page, M), 'the Mind drawer starts open')
            _shot(page, 'mind-closed-desktop')
            page.click('[data-page-tab="mind"] [data-settings-off] button')
            page.wait_for_selector(M + '[data-open]')
            _shot(page, 'mind-open-desktop')
            before = storage.get_settings()
            page.check(M + ' input[x-model="s.mind_enabled"]')
            page.wait_for_selector(M + ' [data-settings-status]:has-text("Saved")')
            check('mind_enabled' in _changed(before, storage.get_settings()), 'turning the Mind on did not save')
            page.click(M + ' [aria-label="Close settings"]')
            page.wait_for_timeout(150)
            check(not _visible(page, '[data-page-tab="mind"] [data-settings-off]'), 'the off line outlived the switch')
            # heads-ups deep link (was test_config_small_moves_live's path)
            page.goto(served.url('work?tab=threads#heads-ups'), wait_until='networkidle')
            page.wait_for_selector(M + '[data-open]')
            check(_visible(page, '#proactiveWatchersEnabled'), 'heads-ups is not reachable in the drawer')
```

…followed by the same `errors` check and `print('test_settings_drawer_work_live OK')`.

- [ ] **Step 2: Run it and watch it fail**

Run: `env -u HA_BASE_URL python tests/test_settings_drawer_work_live.py`
Expected: FAIL — timeout waiting for `[data-settings-off]`.

- [ ] **Step 3: Move the settings**

In `templates/components/mind_page.html`:
- Add the import line.
- Cut the `<div class="space-y-4">` settings block (15-183) and replace it, in place, with:

```html
            {{ settings_off('The Mind is off — nothing is being noticed.', 'mind', 'mind-general', 'loaded && !s.mind_enabled') }}
            {% call settings_drawer('mind', 'Mind', sections=[('mind-general', 'The Mind'), ('negotiation', 'Negotiation'), ('heads-ups', 'Heads-ups')]) %}
            {% call settings_section('mind-general', 'The Mind') %}
            <div class="bg-gray-900 rounded-xl p-4 space-y-4">
                {# MOVE HERE, unchanged: on/off (16-23), wake/sleep (25-39),
                   cadences (41-56), insights kept (58-65), caps (67-92),
                   graduated categories chips (94-105). #}
            </div>
            {% endcall %}
            {% call settings_section('negotiation', 'Negotiation') %}
            <div class="bg-gray-900 rounded-xl p-4 space-y-4">
                {# MOVE HERE, unchanged: 113-155 (drop the old <h3> at 107;
                   the section heading replaces it). #}
            </div>
            {% endcall %}
            {% call settings_section('heads-ups', 'Heads-ups') %}
            <div class="bg-gray-900 rounded-xl p-4 space-y-3">
                {# MOVE HERE: the heads-ups label and explainer (167-181).
                   Drop the Jinja wall guard around it (the drawer guards)
                   and drop id="heads-ups" from the old <h3> — the section
                   carries it now. #}
            </div>
            {% endcall %}
            {% endcall %}
```

- Graduate (345-358) stays in the work area (rule 3). The drawer is outside the `<template x-if="adminChecked && adminAllowed">`.
- Script: add `loaded: false` to the data and `this.loaded = true;` at the end of `load()`'s success path. `save()` and `saveWatchers()` adopt THE SAVE REPORT PATTERN; delete `watchersSaved` and its "Saved ✓" chip.

- [ ] **Step 4: Registry**

All `mind_*` and `negotiation_*` entries: `page='work?tab=mind'`. Anchors: `mind_*` (including `mind_direct_categories`) → `'mind-general'`; `negotiation_*` → `'negotiation'`; `proactive_watchers_enabled` → `page='work?tab=mind'`, anchor stays `'heads-ups'`. In `tests/test_mind_settings.py` change every `page == 'mind'` expectation to `'work?tab=mind'`.

- [ ] **Step 5: Run the task's tests and the related ones**

Run: `python tools/build_tailwind.py`; `env -u HA_BASE_URL CHF_SHOTS="$TEMP/chf_shots_t3" python tools/test.py settings_drawer mind config_small_moves settings_registry missions_endpoints page_tabs`
Expected: pass. `test_config_small_moves_live` 92-110 loads `work?tab=mind#heads-ups` and unchecks `#proactiveWatchersEnabled`; it should pass through the deep link. If it scrolls a hidden element, update it to wait for `[data-settings-for~="mind"][data-open]` first. Check screenshots (desktop + 390px phone: add a phone shot pair the same way Task 1 does).

- [ ] **Step 6: Capabilities, release**

Bump; commit `feat(settings): Mind settings in the drawer, an honest off line on the work (vX.Y.Z)`; push.

---

### Task 4: Missions

**Files:**
- Modify: `templates/components/missions_page.html` (settings 25-79; off note 109-111; `save()` 230-247; `load()` ~218)
- Modify: `services/settings_registry.py` (missions entries)
- Test: `tests/test_settings_drawer_work_live.py` (append)

**Interfaces:**
- Produces: drawer `data-settings-for="missions"`, one section `missions-settings`; `#llmGeminiPaidApiKey` (empty draft field), `[data-paid-key-state]` ("Set"/"Not set"), `savePaidKey()`, `removePaidKey()`.

- [ ] **Step 1: Append the failing scenario**

```python
            X = '[data-settings-for~="missions"]'
            page.goto(served.url('work?tab=missions'), wait_until='networkidle')
            page.wait_for_selector('[data-page-tab="missions"] [data-settings-off]', state='visible')
            page.click('#page-settings-gear')
            page.wait_for_selector(X + '[data-open]')
            check(page.inner_text(X + ' [data-paid-key-state]').strip() == 'Not set', 'key state is not Not set')
            page.fill('#llmGeminiPaidApiKey', 'paid-123')
            page.dispatch_event('#llmGeminiPaidApiKey', 'change')
            page.wait_for_selector(X + ' [data-settings-status]:has-text("Saved")')
            check(storage.get_settings().get('llm_gemini_paid_api_key') == 'paid-123', 'the paid key did not save')
            page.reload(wait_until='networkidle')
            page.click('#page-settings-gear')
            page.wait_for_selector(X + '[data-open]')
            check(page.input_value('#llmGeminiPaidApiKey') == '', 'the stored key is shown in the field')
            check(page.inner_text(X + ' [data-paid-key-state]').strip() == 'Set', 'key state is not Set')
            before = storage.get_settings()
            page.fill(X + ' input[x-model.number="s.mission_cap_launch"]', '4')
            page.dispatch_event(X + ' input[x-model.number="s.mission_cap_launch"]', 'change')
            page.wait_for_selector(X + ' [data-settings-status]:has-text("Saved")')
            check(storage.get_settings().get('llm_gemini_paid_api_key') == 'paid-123',
                  'saving another control wiped the paid key')
            _shot(page, 'missions-open-desktop')
            page.click(X + ' [aria-label="Close settings"]')
```

(Use the real `x-model` of the launch-cap input from lines 58-78 if it differs.)

- [ ] **Step 2: Run it and watch it fail**

Run: `env -u HA_BASE_URL python tests/test_settings_drawer_work_live.py`
Expected: FAIL at the Missions off line.

- [ ] **Step 3: Move the settings and change how the key shows**

- Import line; replace the `<div class="space-y-4">` (25-79) with `{{ settings_off('Missions are off — Argyle runs none.', 'missions', 'missions-settings', 'loaded && !s.missions_enabled') }}` followed by `{% call settings_drawer('missions', 'Missions') %}{% call settings_section('missions-settings', 'Missions') %}<div class="bg-gray-900 rounded-xl p-4 space-y-4">` + the moved controls + `</div>{% endcall %}{% endcall %}`.
- Replace the paid-key control (35-45) with:

```html
                <div>
                    <div class="flex items-center justify-between gap-2">
                        <label for="llmGeminiPaidApiKey" class="text-xs font-semibold text-gray-200">Paid Gemini API key</label>
                        <span data-paid-key-state class="text-[10px] font-bold px-1.5 py-0.5 rounded"
                            :class="paidKeySet ? 'bg-teal-500/20 text-teal-300' : 'bg-gray-700 text-gray-300'"
                            x-text="paidKeySet ? 'Set' : 'Not set'"></span>
                    </div>
                    <p class="text-[11px] text-gray-500 mt-0.5">Billed key used only by missions. Regular traffic stays on the free key.</p>
                    <div class="flex gap-2 mt-2">
                        <input type="password" id="llmGeminiPaidApiKey" x-model="paidKeyDraft" @change="savePaidKey()" autocomplete="off"
                            :placeholder="paidKeySet ? 'Paste a new key to replace it' : 'Paste the key'"
                            class="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm">
                        <button type="button" x-show="paidKeySet" @click="removePaidKey()"
                            class="shrink-0 text-xs font-bold px-3 py-1.5 rounded-lg border border-gray-700 text-gray-300 hover:bg-gray-700">Remove</button>
                    </div>
                </div>
```

(Copy the old block's help sentence if it reads differently.)
- Delete the amber "Missions are off — turn them on in Settings above first." note (109-111); the off line replaces it. The Launch button stays disabled while off.
- Script: data gains `loaded: false, paidKeySet: false, paidKeyDraft: ''`. In `load()`: `this.paidKeySet = !!sd.llm_gemini_paid_api_key;` and **do not** copy the key into `this.s` (delete it from `s` and from its defaults); `this.loaded = true;` at the end. `save()` posts `{missions_enabled, model_pool_pro, mission_cap_launch, mission_step_cap, mission_cap_pro_calls}` only — **never the key** (posting `''` would wipe it) — with THE SAVE REPORT PATTERN. Add:

```js
                async savePaidKey() {
                    const v = (this.paidKeyDraft || '').trim();
                    if (!v) return;
                    if (await this._postKey(v)) { this.paidKeySet = true; this.paidKeyDraft = ''; }
                },
                async removePaidKey() {
                    if (!await promptConfirm('Remove the paid key?', 'Missions stop until a new key is pasted.', 'Remove', 'Keep it')) return;
                    if (await this._postKey('')) this.paidKeySet = false;
                },
                async _postKey(value) {
                    window.chfSettingsSaving();
                    try {
                        const r = await fetch(this.apiBase + 'api/settings', {
                            method: 'POST', headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ llm_gemini_paid_api_key: value })
                        });
                        if (!r.ok) {
                            const err = await r.json().catch(() => ({}));
                            const msg = err.detail || 'Could not save that just now.';
                            if (!window.chfSettingsSaved(false, msg)) showGlobalAlert(msg);
                            return false;
                        }
                        window.chfSettingsSaved(true);
                        return true;
                    } catch (e) {
                        if (!window.chfSettingsSaved(false, 'Could not save that just now.')) showGlobalAlert('Could not save that just now.');
                        return false;
                    }
                },
```

(Use the component's real `apiBase` name.)

- [ ] **Step 4: Registry** — every missions entry: `page='work?tab=missions', anchor='missions-settings'`. The audit finds `llm_gemini_paid_api_key` through `llmGeminiPaidApiKey`.

- [ ] **Step 5: Run the task's tests and the related ones**

Run: `python tools/build_tailwind.py`; `env -u HA_BASE_URL CHF_SHOTS="$TEMP/chf_shots_t4" python tools/test.py settings_drawer missions settings_registry`
Expected: pass.

- [ ] **Step 6: Capabilities, release** — Missions' drawer, key set/not-set with replace and remove. Bump; commit `feat(settings): Missions settings in the drawer; the paid key shows set or not set (vX.Y.Z)`; push.

---

### Task 5: Intake

**Files:**
- Modify: `templates/intake.html` (settings section 449-567; `saveConfig()` 1163-1187; `blockPattern` 987-1028; `unblockSender` 1029-1042)
- Modify: `services/settings_registry.py` (sender defaults and blocklist anchors)
- Modify: `tests/test_intake_wait_live.py:60-68`
- Test: `tests/test_settings_drawer_work_live.py` (append)

**Interfaces:**
- Produces: drawer `data-settings-for="intake"`, sections `settings` (Mailbox), `ingest-daily-limit`, `intake-senders`, `intake-blocked`; `saveConfig()` saves on change with a single-flight queue.

- [ ] **Step 1: Append the failing scenario**

```python
            I = '[data-settings-for~="intake"]'
            page.goto(served.url('intake'), wait_until='networkidle')
            page.click('#page-settings-gear')
            page.wait_for_selector(I + '[data-open]')
            check(page.locator(I + ' button:has-text("Save Settings")').count() == 0, 'Intake still has a Save button')
            posts = []
            page.on('request', lambda r: posts.append(r.url) if r.method == 'POST' and r.url.endswith('/api/ingest/config') else None)
            host = I + ' input[x-model="config.ingest_email_host"]'
            page.click(host)
            page.keyboard.type('imap.example.com', delay=20)
            page.wait_for_timeout(300)
            check(not posts, f'typing saved per keystroke: {len(posts)} posts')
            page.click('#ingestDailyLimit')          # blur commits the host
            page.wait_for_selector(I + ' [data-settings-status]:has-text("Saved")')
            check(len(posts) == 1, f'one blur, {len(posts)} saves')
            check(storage.get_settings().get('ingest_email_host') == 'imap.example.com', 'the host did not save')
            _shot(page, 'intake-open-desktop')
            page.click(I + ' [aria-label="Close settings"]')
```

- [ ] **Step 2: Run it and watch it fail**

Run: `env -u HA_BASE_URL python tests/test_settings_drawer_work_live.py`
Expected: FAIL — no `[data-settings-for~="intake"]`.

- [ ] **Step 3: Move the mailbox settings and save on change**

- Import line at the top of `intake.html`.
- Replace `<section class="mb-16">` … `</section>` (450-567) with a drawer, still inside the `intakePage()` island (it closes at 569):

```html
            {% call settings_drawer('intake', 'Intake', sections=[('settings', 'Mailbox'), ('ingest-daily-limit', 'Daily limit'), ('intake-senders', 'Senders'), ('intake-blocked', 'Blocked')]) %}
            {% call settings_section('settings', 'Family mailbox') %}
            <div class="bg-gray-900 rounded-xl p-4 space-y-4">
                {# MOVE HERE: poll toggle (453-461) and the three fields
                   (462-479). Add @change="saveConfig()" to the toggle, the
                   host and the user inputs, and to the password input. #}
            </div>
            {% endcall %}
            {# MOVE HERE: <div id="ingest-daily-limit"> (481-490) unchanged,
               plus class="scroll-mt-28"; add @change="saveConfig()" to
               #ingestDailyLimit. #}
            {% call settings_section('intake-senders', 'Which calendar a sender goes to') %}
            <div class="bg-gray-900 rounded-xl p-4 space-y-3">
                {# MOVE HERE: sender defaults (492-514). Each row's pattern
                   input and calendar select get @change="saveConfig()"; the
                   row's remove button saves after removing
                   (`...splice(i, 1); saveConfig()`); the add button does NOT
                   save (an empty row is not a setting yet). #}
            </div>
            {% endcall %}
            {% call settings_section('intake-blocked', 'Blocked senders') %}
            <div class="bg-gray-900 rounded-xl p-4 space-y-3">
                {# MOVE HERE: skip rules / blocked senders (516-559)
                   unchanged — they already save on their own. #}
            </div>
            {% endcall %}
            {% endcall %}
```

- Delete the old `<div id="settings">` wrapper (its id now lives on the section), the "Family mailbox" `<h3>`, and the Save Settings button (561-565). Text inputs use `@change`, which fires on commit/blur, never per keystroke — do not use `@input`.
- `saveConfig()` becomes single-flight and quiet on success:

```js
            async saveConfig() {
                if (this.savingConfig) { this._saveAgain = true; return; }
                this.savingConfig = true;
                window.chfSettingsSaving();
                try {
                    const payload = {
                        ingest_email_enabled: this.config.ingest_email_enabled,
                        ingest_email_host: this.config.ingest_email_host,
                        ingest_email_user: this.config.ingest_email_user,
                        ingest_sender_defaults: this.config.ingest_sender_defaults,
                        ingest_daily_limit: Math.max(0, parseInt(this.config.ingest_daily_limit, 10) || 0),
                    };
                    if (this.passwordInput.trim()) payload.ingest_email_password = this.passwordInput.trim();
                    const r = await fetch(`${this.apiBase}api/ingest/config`, {
                        method: 'POST', headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload)
                    });
                    if (!r.ok) {
                        const err = await r.json().catch(() => ({}));
                        const msg = err.detail || 'Could not save the mailbox settings.';
                        if (!window.chfSettingsSaved(false, msg)) showGlobalAlert(msg);
                        return;
                    }
                    if (payload.ingest_email_password) this.passwordInput = '';
                    window.chfSettingsSaved(true);
                    this.loadStatus();
                } catch (e) {
                    if (!window.chfSettingsSaved(false, 'Could not save the mailbox settings.')) showGlobalAlert('Could not save the mailbox settings.');
                } finally {
                    this.savingConfig = false;
                    if (this._saveAgain) { this._saveAgain = false; this.saveConfig(); }
                }
            },
```

  Match the field names and payload of the existing function exactly (read it first; the above mirrors lines 1163-1187). Do **not** call `loadConfig()` after a save: it would overwrite the field the person has just moved into. Add `_saveAgain: false` to the data.
- `blockPattern` and `unblockSender` keep their behaviour; their error/success alerts adopt the report fallback (`if (!window.chfSettingsSaved(...)) showGlobalAlert(...)`), so the Block buttons in the work area (rule 3) still alert when no drawer is open.

- [ ] **Step 4: Registry** — `ingest_sender_defaults` → `anchor='intake-senders'`; `ingest_sender_blocklist` → `anchor='intake-blocked'`. Others unchanged (`settings`, `ingest-daily-limit`).

- [ ] **Step 5: Update `tests/test_intake_wait_live.py`**

Replace the fill-and-click-Save lines (60-61) with: click `#page-settings-gear`, wait for `[data-settings-for~="intake"][data-open]`, `page.fill('#ingestDailyLimit', '120')`, `page.dispatch_event('#ingestDailyLimit', 'change')`, wait for the "Saved" mark. Keep the storage assertion; the `#ingest-daily-limit` screenshot (68) is taken with the drawer open.

- [ ] **Step 6: Run the task's tests and the related ones**

Run: `python tools/build_tailwind.py`; `env -u HA_BASE_URL CHF_SHOTS="$TEMP/chf_shots_t5" python tools/test.py settings_drawer intake email_ingest settings_registry supply`
Expected: pass. Check desktop and phone shots.

- [ ] **Step 7: Capabilities, release** — Intake's drawer and the one behaviour change (save on change, no Save button). Bump; commit `feat(settings): Intake's mailbox in the drawer, saved as you go (vX.Y.Z)`; push.

---

## Slice 3 — Meals

### Task 6: Meals' "How this works" becomes the Meals drawer

**Files:**
- Modify: `templates/shopping.html` (header button 124-126; block `#how` 389-959; `showMealSettings` 1879; `$watch` 1914-1916; `openFromHash` call ~1936 and definition 2980-2988; `openMealSettings` 2970-2974; `saveMealCfg` 3041; `saveKitchen` 3077; `saveCategory` 2336; rule saves 2139-2210)
- Test: `tests/test_settings_drawer_meals_live.py` (new)

**Interfaces:**
- Produces: drawer `data-settings-for="meals"`, sections (existing roots, ids kept) `rules`, `dining`, `plate`, `planning`, `prep`, `walmart`, `pictures`, `kitchen`; an empty `<span id="how">` as its first child (old `meals#how` bookmarks open the drawer at the top).

- [ ] **Step 1: Write the failing live test**

Create `tests/test_settings_drawer_meals_live.py` with the shared header/helpers (copy from `tests/test_settings_drawer_live.py`; seed a parent member and `kitchen_ovens: 1`). Body:

```python
            page.set_viewport_size({'width': 1300, 'height': 900})
            D = '[data-settings-for~="meals"]'
            page.goto(served.url('meals'), wait_until='networkidle')
            check(page.locator('button:has-text("How this works")').count() == 0, 'the How this works buttons survived')
            check(_visible(page, '#page-settings-gear'), 'Meals shows no gear')
            _shot(page, 'meals-closed-desktop')
            page.click('#page-settings-gear')
            page.wait_for_selector(D + '[data-open]')
            check(page.locator(D + ' [data-settings-chip]').count() == 8, 'Meals drawer chips are not the eight sections')
            _shot(page, 'meals-open-desktop')
            before = storage.get_settings()
            ovens = D + ' input[x-model.number="kitchen.ovens"]'
            page.fill(ovens, '2')
            page.dispatch_event(ovens, 'change')
            page.wait_for_selector(D + ' [data-settings-status]:has-text("Saved")')
            check(_changed(before, storage.get_settings()) <= {'kitchen_ovens', 'kitchen_burners', 'kitchen_cooks'},
                  'saving the kitchen changed other settings')
            check(storage.get_settings().get('kitchen_ovens') == 2, 'ovens did not save')
            page.reload(wait_until='networkidle')
            page.goto(served.url('meals#planning'), wait_until='networkidle')
            page.wait_for_selector(D + '[data-open]')
            top = page.evaluate("() => document.getElementById('planning').getBoundingClientRect().top")
            check(0 <= top < 260, f'meals#planning is not in view: {top}')
            page.click(D + ' [aria-label="Close settings"]')
            page.click('#page-tabs [data-tab-key="groceries"]')
            page.wait_for_timeout(200)
            check(not _visible(page, '#page-settings-gear'), 'Groceries shows a gear')
            page.goto(served.url('lists'), wait_until='networkidle')
            check(not _visible(page, '#page-settings-gear'), 'Lists shows a gear')
            page.goto(served.url('meals?kiosk=true'), wait_until='domcontentloaded')
            check(page.query_selector('[data-settings-for]') is None, 'the meals kiosk drew a drawer')
```

(Use the real kitchen ovens binding from lines 926-957; registry `ui_marker='kitchen.ovens'` says it is `kitchen.ovens`.) Add the phone shot pair.

- [ ] **Step 2: Run it and watch it fail**

Run: `env -u HA_BASE_URL python tests/test_settings_drawer_meals_live.py`
Expected: FAIL — the "How this works" button count.

- [ ] **Step 3: Move the block**

- Import line at the top of `shopping.html`.
- Delete the header "How this works" button (124-126).
- Replace the `#how` block (comment 389-399, `<div id="how" …>` 400 through its close at 959) with:

```html
            {% if page_mode == 'meals' %}
            {% call settings_drawer('meals', 'Meals', sections=[('rules', 'How we eat'), ('dining', 'Dining'), ('plate', 'Plate'), ('planning', 'Planning'), ('prep', 'Prep'), ('walmart', 'Walmart'), ('pictures', 'Pictures'), ('kitchen', 'Kitchen')]) %}
            <span id="how" class="block"></span>
            {# MOVE HERE, in this order and otherwise unchanged, the eight
               section roots that sat inside the old x-show="showMealSettings"
               wrapper: #rules (419-589), #dining (594-626), #plate (631-717),
               #planning (723-808), #prep (812-839), #walmart (843-905),
               #pictures (913-925), #kitchen (926-957). Add class
               "scroll-mt-28" to each root. They keep their own headings. #}
            {% endcall %}
            {% endif %}
```

  Use the template's real mode variable (grep `page_mode` near the top of `shopping.html`). The drawer stays inside the `[data-page-tab="meals"]` section (113-960) and the `shoppingPage()` island, so the Groceries tab hides it and the gear with it. Delete the toggle button (405-412) and the `x-show="showMealSettings"` wrapper (413).
- Script: delete `showMealSettings`, the `$watch('showMealSettings', …)`, `openMealSettings()` and `openFromHash()` plus its call in `init()` (keep the `if (!this.isLists) {` structure `tests/test_meals_lists_split.py` pins). In `init()`, inside that same `if (!this.isLists) {` block, add:

```js
                window.addEventListener('chf-settings-opened', e => {
                    if (e.detail && e.detail.tab === 'meals' && !this.rulesLoaded) this.loadRules();
                });
```

- Any remaining `openMealSettings()` call (grep the whole `templates/` and `static/`) becomes `chfOpenSettings('meals', '<anchor>')`.
- `saveMealCfg`, `saveKitchen`, `saveCategory`, the category delete, and the rule save/toggle/delete adopt THE SAVE REPORT PATTERN (their existing reload calls stay in the success branch).
- Our meals (983-1089) is untouched; check the screenshot that it now sits directly under the week planner. If the two-column grid leaves a hole where the block was, report it rather than restyling the grid.

- [ ] **Step 4: Run the task's tests and the related ones**

Run: `python tools/build_tailwind.py`; `env -u HA_BASE_URL CHF_SHOTS="$TEMP/chf_shots_t6" python tools/test.py settings_drawer shopping meals walmart settings_registry dish_grid page_tabs nav`
Expected: pass (`test_shopping`'s orphan check passes because the drawer root is its own `x-data`).

- [ ] **Step 5: Capabilities, release** — Meals drawer; "How this works" and `showMealSettings` gone. Bump; commit `feat(settings): Meals' how-this-works becomes the Meals drawer (vX.Y.Z)`; push.

---

## Slice 4 — Rhythms

### Task 7: Chores

**Files:**
- Modify: `templates/chores.html` (`#petxp` 419-508; `#rewards` 511-620; tiers include 622-623; the `!isKiosk` template 188-627; saves `saveFeature` 683, `savePetXp` 709, `setRewardActive` 674, `saveReward` 1165, `deleteReward` 1183)
- Modify: `templates/components/status_tiers_editor.html` (`save()` ~74, `resetDefaults()` ~104)
- Modify: `tests/test_household_features_live.py`
- Test: `tests/test_settings_drawer_rhythms_live.py` (new)

**Interfaces:**
- Produces: drawer `data-settings-for="chores"`, sections `petxp`, `rewards`, `tiers`; rewards-off line in the work area.

- [ ] **Step 1: Write the failing live test**

Create `tests/test_settings_drawer_rhythms_live.py` (shared header/helpers; seed a parent and a child member). Body:

```python
            page.set_viewport_size({'width': 1300, 'height': 900})
            C = '[data-settings-for~="chores"]'
            page.goto(served.url('chores'), wait_until='networkidle')
            check(not _visible(page, '#petxp'), 'pet XP still sits in the work flow')
            _shot(page, 'chores-closed-desktop')
            page.click('#page-settings-gear')
            page.wait_for_selector(C + '[data-open]')
            check(page.locator(C + ' [data-settings-chip]').count() == 3, 'Chores drawer has no three chips')
            _shot(page, 'chores-open-desktop')
            before = storage.get_settings()
            page.uncheck(C + ' input[x-model="features.rewards_enabled"]')
            page.wait_for_selector(C + ' [data-settings-status]:has-text("Saved")')
            check(_changed(before, storage.get_settings()) == {'rewards_enabled'}, 'the rewards switch changed more')
            page.click(C + ' [aria-label="Close settings"]')
            page.wait_for_selector('[data-settings-off]', state='visible')
            page.click('[data-settings-off] button')
            page.wait_for_selector(C + '[data-open]')
            top = page.evaluate("() => document.getElementById('rewards').getBoundingClientRect().top")
            check(0 <= top < 260, f'Turn on did not land on #rewards: {top}')
            page.check(C + ' input[x-model="features.rewards_enabled"]')
            page.click(C + ' [aria-label="Close settings"]')
            page.goto(served.url('chores?kiosk=true'), wait_until='domcontentloaded')
            check(page.query_selector('[data-settings-for]') is None, 'the chores kiosk drew a drawer')
```

Add the phone shot pair.

- [ ] **Step 2: Run it and watch it fail** — `env -u HA_BASE_URL python tests/test_settings_drawer_rhythms_live.py` → FAIL (`pet XP still sits in the work flow`).

- [ ] **Step 3: Move the three sections**

- Import line in `chores.html`.
- Cut `<section id="petxp">` (419-508), `<section id="rewards">` (511-620) and the two tier lines (622-623: `{% set tier_kind='chore' %}` + the include). Paste them, unchanged except `scroll-mt-28` added to the two section roots, into:

```html
        {% call settings_drawer('chores', 'Chores', sections=[('petxp', 'Critters & pet XP'), ('rewards', 'Reward store'), ('tiers', 'Status tiers')]) %}
        {# the three moved blocks, in that order #}
        {% endcall %}
```

  placed inside the `choresPage()` root **after** the `<template x-if="!isKiosk">` closes (~627), never inside it. The reward catalog (per-reward active switch, edit, delete, the add/edit form with its `season_editor`) moves with `#rewards`: the catalog is the store's definition, and the spec puts it in the drawer. Per-child point and XP tools on the leaderboard stay.
- In the work area, directly above "Pending reward requests" (190), add:

```html
            {{ settings_off('The reward store is off — nobody can ask for a reward.', 'chores', 'rewards', 'features.rewards_enabled === false') }}
```

- `saveFeature`, `savePetXp`, `setRewardActive`, `saveReward`, `deleteReward` adopt THE SAVE REPORT PATTERN; delete the "Saved." text lines (~506 and the store card's). In `status_tiers_editor.html`, `save()` and `resetDefaults()` adopt it too (this also serves Routines).

- [ ] **Step 4: Update `tests/test_household_features_live.py`** — before clicking the critters/rewards inputs or waiting on `#rewards h4:has-text("Ice cream")` / `input[aria-label="Offer Ice cream"]`, click `#page-settings-gear` and wait for `[data-settings-for~="chores"][data-open]`. The chore-form steps ("Add Chore", "Summer" preset) stay in the work area — close the drawer before them.

- [ ] **Step 5: Run the task's tests and the related ones**

Run: `python tools/build_tailwind.py`; `env -u HA_BASE_URL CHF_SHOTS="$TEMP/chf_shots_t7" python tools/test.py settings_drawer household_features seasons chores pets avatars settings_registry status_tiers`
Expected: pass (`test_seasons` still counts exactly 2 `season_editor(` calls in `chores.html`).

- [ ] **Step 6: Capabilities, release** — Bump; commit `feat(settings): Chores' pet XP, reward store and tiers in the drawer (vX.Y.Z)`; push.

---

### Task 8: Routines

**Files:**
- Modify: `templates/components/routines_page.html` (`#runway` label 21-26; tiers include 545-546; kid-evenings include 551-562; `saveRunwayCues` 626)
- Modify: `templates/components/kid_evenings_settings.html` (`save()` ~88)
- Modify: `tests/test_rhythms_settings_live.py`
- Test: `tests/test_settings_drawer_rhythms_live.py` (append)

**Interfaces:**
- Produces: drawer `data-settings-for="routines"`, sections `runway`, `tiers`, `kid-evenings`.

- [ ] **Step 1: Append the failing scenario**

```python
            R = '[data-settings-for~="routines"]'
            page.goto(served.url('rhythms?tab=routines'), wait_until='networkidle')
            check(not _visible(page, '#kid-evenings'), 'kid evenings still sit in the work flow')
            page.click('#page-settings-gear')
            page.wait_for_selector(R + '[data-open]')
            before = storage.get_settings()
            page.fill('#kidDigestTime', '19:15')
            page.dispatch_event('#kidDigestTime', 'change')
            page.wait_for_selector(R + ' [data-settings-status]:has-text("Saved")')
            check(_changed(before, storage.get_settings()) <= {'kid_digest_enabled', 'kid_digest_time', 'kid_digest_cutover_time', 'kid_quiet_start', 'kid_quiet_end'},
                  'kid evenings saved outside its keys')
            _shot(page, 'routines-open-desktop')
            page.click(R + ' [aria-label="Close settings"]')
            page.goto(served.url('routines'), wait_until='networkidle')
            check(_visible(page, '#page-settings-gear'), 'standalone /routines shows no gear')
```

- [ ] **Step 2: Run it and watch it fail** → FAIL (`kid evenings still sit in the work flow`).

- [ ] **Step 3: Move the three settings**

- Import line in `routines_page.html`.
- Cut the `<label id="runway" x-show="!isKiosk">` (21-26) from the header row. Cut the tier lines (545-546). Cut the kid-evenings block (551-562) **without** its Jinja wall guard (the drawer guards). Paste into:

```html
    {% call settings_drawer('routines', 'Routines', sections=[('runway', 'Runway'), ('tiers', 'Status tiers'), ('kid-evenings', 'Kid evenings')]) %}
    {% call settings_section('runway', 'Runway voice cues') %}
    <div class="bg-gray-900 rounded-xl p-4">
        {# the old runway <label>, minus its id and its x-show #}
        <p class="text-[11px] text-gray-500 mt-2">Each child also needs a cue room, picked on their routine.</p>
    </div>
    {% endcall %}
    {% set tier_kind='routine' %}
    {% include 'components/status_tiers_editor.html' %}
    {% include 'components/kid_evenings_settings.html' %}
    {% endcall %}
```

  placed inside the `routinesPage()` root after the `<template x-if="!isKiosk">` closes (~549), never inside it. Add `scroll-mt-28` to the `#kid-evenings` section root in `kid_evenings_settings.html` and the `#tiers` root in `status_tiers_editor.html`. Each child's cue-room select (~123-135) stays on their block (rule 2).
- `saveRunwayCues` and `kid_evenings_settings.html` `save()` adopt THE SAVE REPORT PATTERN.

- [ ] **Step 4: Update `tests/test_rhythms_settings_live.py`** — the kid-evenings checks (`rhythms?tab=routines`, `/routines`) open the gear first; the wall checks (count 0 on `routines?kiosk=true`, `rhythms?kiosk=true`, `rhythms?panel=true`, `rhythms?tabs=routines`) stay as they are. Leave the Growing up assertions for Task 9.

- [ ] **Step 5: Run the task's tests and the related ones**

Run: `python tools/build_tailwind.py`; `env -u HA_BASE_URL CHF_SHOTS="$TEMP/chf_shots_t8" python tools/test.py settings_drawer rhythms_settings runway routine_steps routine_lanes settings_registry school_page`
Expected: pass.

- [ ] **Step 6: Capabilities, release** — Bump; commit `feat(settings): Routines' runway, tiers and kid evenings in the drawer (vX.Y.Z)`; push.

---

### Task 9: Growing up moves to Config › People

**Files:**
- Modify: `templates/config.html` (People panel: after the member list `</div>` ~1623, before "Add a Person" ~1624)
- Modify: `templates/rhythms.html` (delete the `#growing-up` section 36-47; add a hash forwarder)
- Modify: `templates/nav.html` (PAGE_GROUPS: delete the `growing-up` tab)
- Modify: `templates/school.html` (forwarder ~406-420: growing-up target)
- Modify: `main.py` (`/rhythms` route ~1739: forward `?tab=growing-up`)
- Modify: `services/watchers.py:759-760`
- Modify: `services/settings_registry.py` (`stage_cutoffs`)
- Modify: `tests/test_stages.py:316-335`, `tests/test_rhythms_settings_live.py`, `tests/test_school_page_live.py:190-208`

**Interfaces:**
- Produces: `config#growing-up` (Config's own `openHashTab` opens the People panel, whose tab key is `family`). **Deviation from the spec, on purpose:** the spec names `config?tab=people#growing-up`, but Config has no `?tab=` handling and its People tab key is `family`; `config#growing-up` lands on the same place through code that already exists. Findings carry no link field (`services/findings.py` `Finding`), so the watcher change is text only.

- [ ] **Step 1: Write the failing pins**

Append to `tests/test_settings_drawer.py`:

```python
def scenario_growing_up_lives_on_config_people():
    import tpl_source
    cfg = tpl_source.read('config.html')
    check("include 'components/growing_up.html'" in open(os.path.join(tpl_source.TPL, 'config.html'), encoding='utf-8').read(),
          'Config does not include Growing up')
    check('id="growing-up"' in cfg, 'Config has no #growing-up anchor')
    check('growing_up.html' not in open(os.path.join(tpl_source.TPL, 'rhythms.html'), encoding='utf-8').read(),
          'Rhythms still carries Growing up')
    from services import settings_registry as reg
    e = reg.BY_KEY['stage_cutoffs']
    check((e['page'], e['anchor']) == ('config', 'growing-up'), f'stage_cutoffs points at {e}')
    # A redirect has no page body, so assert on the response itself.
    import main
    from starlette.requests import Request
    route = next(r for r in main.app.routes if getattr(r, 'path', None) == '/rhythms')
    req = Request({'type': 'http', 'method': 'GET', 'path': '/rhythms',
                   'query_string': b'tab=growing-up', 'headers': [],
                   'app': main.app, 'router': main.app.router})
    resp = route.endpoint(req)
    check(resp.status_code in (302, 303, 307) and resp.headers['location'].endswith('config#growing-up'),
          f'rhythms?tab=growing-up does not forward to Config: {resp.status_code} {resp.headers.get("location")}')
```

- [ ] **Step 2: Run it and watch it fail** — `env -u HA_BASE_URL python tests/test_settings_drawer.py` → FAIL (`Config does not include Growing up`).

- [ ] **Step 3: Move it**

- `config.html`, People panel, right after the member list's closing `</div>` (~1623) and before `<div class="mt-6">` (Add a Person):

```html
                    <section id="growing-up" class="mt-8">
                        {% include 'components/growing_up.html' %}
                    </section>
```

  `growing_up.html` is included unchanged. Config's `openHashTab()` (~2157) resolves `#growing-up` to the People panel through `closest('[x-show^="activeTab === "]')`; confirm by test, do not add a new opener.
- `rhythms.html`: delete the Growing up block (the `{# Growing up … #}` comment, `{% set _rq %}`, the `{% if %}`, the `<section id="growing-up">` and `{% endif %}`). Update the page comment's last sentence to say Growing up moved to Config › People. Add before `{% include 'components/control_center.html' %}`:

```html
    <script>
        // Growing up lives on Config › People now; old links follow it.
        if ((window.location.hash || '') === '#growing-up') window.location.replace('config#growing-up');
    </script>
```

- `nav.html` PAGE_GROUPS: delete the `{'key': 'growing-up', …}` entry.
- `main.py` `/rhythms` route: at the top of the function,

```python
    if request.query_params.get('tab') == 'growing-up':
        return RedirectResponse('config#growing-up')
```

  (a relative Location, like `/dashboard`'s, so it works under ingress).
- `school.html` forwarder: `window.location.replace('rhythms?tab=growing-up#growing-up')` → `window.location.replace('config#growing-up')`.
- `services/watchers.py:759-760`: `Confirm it in Rhythms → Growing up.` → `Confirm it in Config → People.`
- Registry `stage_cutoffs`: `page='config', anchor='growing-up'`.

- [ ] **Step 4: Update the tests**

- `tests/test_stages.py:316-335`: the include and `data-page-tab="growing-up"` assertions move from `rhythms.html` to `config.html` (`include 'components/growing_up.html'` and `id="growing-up"`); the `growing_up.html` content assertions stay.
- `tests/test_rhythms_settings_live.py`: the expected tab list becomes `['chores', 'routines', 'programs']`; the Growing up part (click tab, `#growing-up` visible, `[x-ref="stageTrack"]`, the `[data-cutoff-handle]` drag saving `stage_cutoffs [4,12,15]`) moves to `config#growing-up` (wait for `#growing-up [x-ref="stageTrack"]` visible); `rhythms#growing-up` and `rhythms?tab=growing-up` both end on `config` with `#growing-up` visible; the wall checks for Growing up are dropped from Rhythms (Config is not a wall page).
- `tests/test_school_page_live.py:190-208`: the `school#growing-up` / `school?tab=growing` forwards now land on `config` with `#growing-up` visible.

- [ ] **Step 5: Run the task's tests and the related ones**

Run: `env -u HA_BASE_URL CHF_SHOTS="$TEMP/chf_shots_t9" python tools/test.py settings_drawer stages rhythms_settings school_page nav page_tabs settings_registry watchers config`
Expected: pass. Screenshot Config › People scrolled to Growing up (desktop and phone).

- [ ] **Step 6: Capabilities, release** — Growing up's fourth home, and why (the spec's "Why here" paragraph, one line). Bump; commit `feat(settings): Growing up moves to Config People; Rhythms forwards (vX.Y.Z)`; push.

---

## Slice 5 — Schedule

### Task 10: Drives takes in Drive setup

**Files:**
- Create: `templates/components/drive_setup_panel.html` (from `templates/drive_setup.html`)
- Delete: `templates/drive_setup.html`
- Modify: `templates/dashboard.html` (leave margin 63-73; includes; `saveLeaveMargin` 522-536)
- Modify: `main.py` (`/dashboard_v2` 1472-1474; `/drive_setup` 1764-1783)
- Modify: `templates/nav.html` (PAGE_GROUPS: delete the `setup` tab)
- Modify: `templates/components/errand_rules.html:14-15` (the `drive_setup#rules` link)
- Modify: `services/settings_registry.py` (`_DRIVE`)
- Modify: `tests/test_drive_setup_live.py`, `tests/test_leave_times_live.py:149-155`, and the source-reading tests that open `drive_setup.html`: `tests/test_assist.py:389`, `tests/test_assist_work.py:165`, `tests/test_outlets.py:277`, `tests/test_house_state.py:217`, `tests/test_arrive_by.py:239`

**Interfaces:**
- Produces: drawer `data-settings-for="drives"` on `/dashboard_v2`, sections `leave-margin`, `rules` (with `routing-rules`/`priority-rules` inside), `cars` (with `car-alerts`), `protected-time`, `outside-hands`, `solver` (with `horizons`, `solver-behavior`, `traffic`, `tomorrow-digest`); `/drive_setup` → 302 `dashboard_v2?settings=open` (the browser keeps the original `#hash` across the redirect); `main._drive_setup_context() -> dict`.

- [ ] **Step 1: Rewrite the live test first**

Rewrite `tests/test_drive_setup_live.py` so every scenario starts from `dashboard_v2`, opens `#page-settings-gear`, waits for `[data-settings-for~="drives"][data-open]`, and then asserts exactly what it asserted before on the same ids (`#rules`, `#routing-rules input[x-model="enableAiRules"]`, `#daysToShow`, `#daysToBuild`, `#loadBalancingEnabled`, `#tomorrowDigestTime`, `#cars`, `#car-alerts [x-model.number="carFuelWarnPct"]`, `#car-alerts [data-save-alerts]`, `#protected-time`, `#outside-hands`, `#assistReadyBuffer`). Delete the `#drive-sections [data-section-tab]` clicks (the sections are stacked now; chips replace them) and assert instead `page.locator('[data-settings-for~="drives"] [data-settings-chip]').count() == 6`. Add:

```python
            # Old addresses still land, hash and all.
            for old, anchor in (('drive_setup', None), ('drive_setup#traffic', 'traffic'),
                                ('drive_setup#priority-rules', 'priority-rules'), ('drive_setup#car-alerts', 'car-alerts'),
                                ('config#outside-hands', 'outside-hands')):
                page.goto(served.url(old), wait_until='networkidle')
                page.wait_for_selector('[data-settings-for~="drives"][data-open]')
                check('dashboard_v2' in page.url, f'{old} did not forward to Drives: {page.url}')
                if anchor:
                    top = page.evaluate("(a) => document.getElementById(a).getBoundingClientRect().top", anchor)
                    check(0 <= top < 300, f'{old} did not land on #{anchor}: {top}')
                page.click('[data-settings-for~="drives"] [aria-label="Close settings"]')
            # Leave margin moved out of the toolbar.
            page.goto(served.url('dashboard_v2'), wait_until='networkidle')
            check(not _visible(page, '#leave-margin-mins'), 'leave margin still sits in the toolbar')
            box = page.evaluate("() => { const r = document.querySelector('[data-settings-for~=\"drives\"]').getBoundingClientRect(); return [r.width, innerWidth]; }")
            check(box[0] == box[1], 'the Drives drawer is trapped by an ancestor')
```

Keep the errand-rules part (286-311) as it is for now; Task 12 rewrites it. Replace the "no `a[href*="drive_setup#"]` outside nav" assertion (317) with the same assertion for `drive_setup` anywhere outside nav.

- [ ] **Step 2: Run it and watch it fail** — `env -u HA_BASE_URL python tests/test_drive_setup_live.py` → FAIL (no drawer on `dashboard_v2`).

- [ ] **Step 3: Make the panel component**

Create `templates/components/drive_setup_panel.html` from `drive_setup.html`:
- Header comment: what it is, who includes it (the Drives drawer), that it is one island (`driveSetup()`).
- Root: `<div x-data="driveSetup()" x-init="init()" class="flex flex-col gap-6">` replacing `<body x-data=…>` and the page wrappers (42-43); no `x-cloak` (the drawer shell has it).
- Copy the sections 66-840 in order. Delete the section switcher `#drive-sections` (56-62) and every `x-show="section === '…'"`; keep `data-drive-section` attributes (harmless) and add `scroll-mt-28` to each top-level section root (`#rules`, `#cars`, `#protected-time`, `#outside-hands`, `#solver`). Keep the routing/priority sub-tabs (`rulesSubTab`) and the debug-log panel (100-116, the "Logs" button stays in `#rules`).
- Copy `{% include 'components/drive_rules.html' %}` and the `driveSetup()` script (853-1940). In the script: delete `sections`, `section`, `setSection`, the `hashchange` listener and `openAnchor()` in `init()` (943-979). Replace them with one listener that keeps the priority sub-tab reachable by link:

```js
                const subFromHash = () => {
                    let id = '';
                    try { id = decodeURIComponent((location.hash || '').slice(1)); } catch (e) { }
                    const el = id ? document.getElementById(id) : null;
                    const sub = el && el.closest('[data-rules-sub]');
                    if (sub) this.rulesSubTab = sub.getAttribute('data-rules-sub');
                };
                window.addEventListener('hashchange', subFromHash);
                window.addEventListener('chf-settings-opened', subFromHash);
                subFromHash();
```

- `postSettings(payload, which)` (1008-1027) adopts THE SAVE REPORT PATTERN; delete every per-section `saved === '…'` "Saved ✓" badge in the copied markup and the `saved` state they read.
- Delete `templates/drive_setup.html`.

- [ ] **Step 4: Put it in the Drives drawer (`dashboard.html`)**

- Import line at the top.
- Cut the leave-margin `<label id="leave-margin" class="hidden …">` (63-73, with its comment) out of `#header-buttons`.
- Directly before `{% include 'components/control_center.html' %}` (a body-level child, outside `#page-header`, whose `backdrop-blur-sm` would trap a fixed drawer), add:

```html
    {% call settings_drawer('drives', 'Drives', sections=[('leave-margin', 'Leave margin'), ('rules', 'Rules'), ('cars', 'Cars'), ('protected-time', 'Protected time'), ('outside-hands', 'Outside hands'), ('solver', 'Solver')]) %}
    <section id="leave-margin" data-settings-section class="scroll-mt-28 hidden">
        <div class="text-xs font-semibold text-gray-500 uppercase tracking-widest mb-2">Leave margin</div>
        <div class="bg-gray-900 rounded-xl px-4 py-3 flex items-center justify-between gap-3">
            {# the old label's text and its #leave-margin-mins input,
               unchanged (data-setting, min/max, onchange) #}
        </div>
    </section>
    {% include 'components/drive_setup_panel.html' %}
    {% endcall %}
    {% include 'components/emoji_picker.html' %}
```

  `loadLeaveMargin()` already removes `hidden` from `#leave-margin`; it now unhides the section. `saveLeaveMargin` adopts THE SAVE REPORT PATTERN (it is vanilla JS; same calls). If `emoji_picker.html` is already included by `dashboard.html`, do not include it twice. If its overlay's z-index is below `z-[85]`, raise it to `z-[90]` so it opens above the drawer.
- `main.py`: extract the context from `drive_setup_page` into

```python
def _drive_setup_context() -> dict:
    import datetime as _dt
    current_month = _dt.datetime.now().strftime("%Y-%m")
    allow_map_loads = (maps.get_map_option('enable_mapbox_map_loads', True)
                       and storage.get_mapbox_usage(current_month, 'map_loads')
                       < maps.get_map_option('mapbox_map_loads_limit', 45000))
    return {"mapbox_key": maps.get_mapbox_api_key() or "",
            "allow_map_loads": allow_map_loads}
```

  `/dashboard_v2` becomes `_page_or_board(request, "schedule", "dashboard.html", context=_drive_setup_context())`. `/drive_setup` becomes a docstring explaining the fold plus `return RedirectResponse("dashboard_v2?settings=open")` (a relative Location; the browser carries the original fragment over a redirect whose Location has none).
- `nav.html` PAGE_GROUPS: delete the `{'key': 'setup', …}` entry.
- `errand_rules.html:14-15`: the `drive_setup#rules` link → `dashboard_v2#rules`.
- Registry: `_DRIVE = 'dashboard_v2'` (the comment above it says the Drives drawer); anchors unchanged. `leave_margin_mins` is already `dashboard_v2#leave-margin`.

- [ ] **Step 5: Update the source-reading tests**

In `tests/test_assist.py:389`, `tests/test_assist_work.py:165`, `tests/test_outlets.py:277`, `tests/test_house_state.py:217`, `tests/test_arrive_by.py:239`: read `components/drive_setup_panel.html` where they opened `drive_setup.html` (the `include 'components/drive_rules.html'` string now lives there). `tests/test_leave_times_live.py:149-155`: open the gear and wait for the drawer before filling `#leave-margin-mins`.

- [ ] **Step 6: Run the task's tests and the related ones**

Run: `python tools/build_tailwind.py`; `env -u HA_BASE_URL CHF_SHOTS="$TEMP/chf_shots_t10" python tools/test.py drive_setup leave_times leave_margin assist outlets house_state arrive_by settings_registry settings_drawer nav page_tabs triage ride_groups house_personal_vehicles house_vehicle_artwork`
Expected: pass, except `test_leave_times_live`'s known baseline red ("the wall says the same two departures"). Screenshots: Drives closed, drawer open at the top, drawer open at `#car-alerts`, phone.

- [ ] **Step 7: Capabilities, release** — Drive setup folded into the Drives drawer; `/drive_setup` forwards; `_drive_setup_context`. Bump; commit `feat(settings): Drive setup folds into the Drives drawer, leave margin with it (vX.Y.Z)`; push.

---

### Task 11: Calendar's status day types, and Occasions' gift lead time

**Files:**
- Modify: `templates/calendar.html` (header link 79-82)
- Modify: `templates/components/status_days.html` (types card 13-186; work block 187-225)
- Modify: `templates/occasions.html` (`#gifts` 36-46; `saveGiftLead` 781-789)
- Modify: `tests/test_config_small_moves_live.py:111-150, 202-212`
- Test: `tests/test_settings_drawer_schedule_live.py` (new)

**Interfaces:**
- Produces: Calendar drawer `data-settings-for="calendar"`, section `status-day-types` (inside the `statusDaysPanel()` island); the Upcoming list and the set/clear row stay in `#status-days`; an empty state with **Add a type…** when no types exist. Occasions drawer `data-settings-for="occasions"`, section `gifts`.

- [ ] **Step 1: Write the failing live test**

Create `tests/test_settings_drawer_schedule_live.py` (shared header/helpers; seed a parent and a kid). Body:

```python
            page.set_viewport_size({'width': 1300, 'height': 900})
            K = '[data-settings-for~="calendar"]'
            page.goto(served.url('calendar'), wait_until='networkidle')
            check(page.locator('[data-status-days-link]').count() == 0, 'the Status days header link survived')
            page.wait_for_selector('[data-status-types-empty]', state='visible')
            page.click('[data-status-types-empty] button')
            page.wait_for_selector(K + '[data-open]')
            page.click(K + ' [data-status-add]')
            page.fill(K + ' [data-status-name]', 'Snow day')
            page.click(K + ' [data-status-submit]')
            page.wait_for_selector(K + ' [data-status-row]:has-text("Snow day")')
            page.click(K + ' [aria-label="Close settings"]')
            page.wait_for_selector('#status-days [data-status-set]', state='visible')
            _shot(page, 'calendar-closed-desktop')
            O = '[data-settings-for~="occasions"]'
            page.goto(served.url('occasions'), wait_until='networkidle')
            check(not _visible(page, '#gifts'), 'gift lead time still sits in the work flow')
            page.click('#page-settings-gear')
            page.wait_for_selector(O + '[data-open]')
            before = storage.get_settings()
            page.fill(O + ' input[x-model.number="giftLeadDays"]', '5')
            page.dispatch_event(O + ' input[x-model.number="giftLeadDays"]', 'change')
            page.wait_for_selector(O + ' [data-settings-status]:has-text("Saved")')
            check(_changed(before, storage.get_settings()) == {'gift_lead_days'}, 'gift lead saved more than itself')
            _shot(page, 'occasions-open-desktop')
```

Add phone shot pairs for both.

- [ ] **Step 2: Run it and watch it fail** → FAIL (`the Status days header link survived`).

- [ ] **Step 3: Calendar**

- `calendar.html`: delete the `{% if %}<a href="#status-days" data-status-days-link>…</a>{% endif %}` (79-82).
- `status_days.html`: import line at top. Keep `<section id="status-days" x-data="statusDaysPanel()" …>` as the island root in the work area. Cut the types card content (title/blurb 14-20, protocol list 21-49, add button and form 50-186) and paste it into a drawer placed inside the island, before the work block:

```html
    {% call settings_drawer('calendar', 'Calendar') %}
    {% call settings_section('status-day-types', 'Status day types') %}
    <div class="bg-gray-900 rounded-xl p-4">
        {# the moved types content, unchanged: rows, edit, delete, the add
           form with its beats #}
    </div>
    {% endcall %}
    {% endcall %}
```

  The work block (187-225, Upcoming + set row) stays; above it add the empty state:

```html
    <div data-status-types-empty x-show="loaded && !statusProtocols.length" x-cloak
        class="bg-gray-800 rounded-2xl border border-gray-700 px-4 py-3 flex items-center justify-between gap-3">
        <p class="text-sm text-gray-300">No status day types yet — a type is what a day can be (snow day, sick day).</p>
        <button type="button" @click="chfOpenSettings('calendar', 'status-day-types')"
            class="shrink-0 text-xs font-bold px-3 py-1.5 rounded-lg bg-blue-600 text-white hover:bg-blue-500">Add a type…</button>
    </div>
```

  Add `loaded: false` to `statusDaysPanel()`'s data, set true after the protocols load. The day/type CRUD calls keep their endpoints; their error alerts adopt the report fallback.

- [ ] **Step 4: Occasions**

- Import line in `occasions.html`. Cut `<div id="gifts" …>` (40-46, with its comment 36-39) and paste it inside the `occasionsPage()` island as:

```html
        {% call settings_drawer('occasions', 'Occasions') %}
        {% call settings_section('gifts', 'Presents') %}
        <div class="bg-gray-900 rounded-xl px-4 py-3 flex flex-wrap items-center gap-2 text-sm text-gray-400">
            {# the old #gifts content: the sentence and the giftLeadDays input #}
        </div>
        {% endcall %}
        {% endcall %}
```

  (drop `id="gifts"` from the old div — the section carries it). `saveGiftLead()` adopts THE SAVE REPORT PATTERN.

- [ ] **Step 5: Update `tests/test_config_small_moves_live.py`** — the status-days walk (111-150) clicks `[data-status-add]`/`[data-status-name]`/`[data-status-kid]`/`[data-status-submit]`/`[data-status-row]`/`[data-status-edit]`/`[data-status-delete]` inside `[data-settings-for~="calendar"]` after opening it, and `[data-status-set]`/`[data-status-clear]` in `#status-days`; the `[data-status-days-link]` count becomes 0; `calendar#status-days` (202-205) still scrolls to the work block; the walls check (211-212) asserts `[data-settings-for]` is absent too.

- [ ] **Step 6: Run the task's tests and the related ones**

Run: `python tools/build_tailwind.py`; `env -u HA_BASE_URL CHF_SHOTS="$TEMP/chf_shots_t11" python tools/test.py settings_drawer config_small_moves gift_leadtime calendar_render invited_occasions settings_registry`
Expected: pass.

- [ ] **Step 7: Capabilities, release** — Bump; commit `feat(settings): status day types and gift lead time in their drawers (vX.Y.Z)`; push.

---

## Slice 6 — The rest

### Task 12: Errands › Rules becomes the Errands drawer

**Files:**
- Modify: `templates/errands.html` (rules block 133-137)
- Modify: `templates/components/errand_rules.html` (`init()` lazy-load 253-260)
- Modify: `templates/nav.html` (PAGE_GROUPS: delete the `rules` tab)
- Modify: `main.py` (`/errands` 1723-1725)
- Modify: `tests/test_drive_setup_live.py:286-311`
- Test: `tests/test_settings_drawer_schedule_live.py` (append)

**Interfaces:**
- Produces: drawer `data-settings-for="errands tasks"` (the gear opens it from either tab), section `errand-rules`; `/errands?tab=rules` → 302 `errands?settings=open`.

- [ ] **Step 1: Append the failing scenario**

```python
            E = '[data-settings-for~="errands"]'
            for start in ('errands', 'errands?tab=tasks'):
                page.goto(served.url(start), wait_until='networkidle')
                page.click('#page-settings-gear')
                page.wait_for_selector(E + '[data-open]')
                check(_visible(page, '#errand-rules'), f'{start}: the rules are not in the drawer')
                page.click(E + ' [aria-label="Close settings"]')
            page.goto(served.url('errands?tab=rules'), wait_until='networkidle')
            page.wait_for_selector(E + '[data-open]')
            check('tab=rules' not in page.url, f'the retired tab survived: {page.url}')
            check(page.locator('#page-tabs [data-tab-key="rules"]').count() == 0, 'the Rules tab is still on the bar')
```

- [ ] **Step 2: Run it and watch it fail** → FAIL.

- [ ] **Step 3: Move it**

- `errands.html`: import line. Replace the guarded `[data-page-tab="rules"]` block (133-137) with, inside the `errandsPage()` wrapper but outside every `[data-page-tab]` block:

```html
            {% call settings_drawer('errands tasks', 'Errands') %}
            {% include 'components/errand_rules.html' %}
            {% endcall %}
```

  Add `scroll-mt-28` to `#errand-rules`'s root and drop its own page-sized padding/heading only if it duplicates the drawer header (keep "Errand Rules" as the section heading).
- `errand_rules.html` `init()`: replace the `?tab=rules` / missing-strip / `chf-page-tab` lazy-load conditions with:

```js
            window.addEventListener('chf-settings-opened', e => {
                const t = e.detail && e.detail.tab;
                if ((t === 'errands' || t === 'tasks') && !this.loaded) this.load();
            });
```

  (use the component's real loaded flag and loader names). Rule CRUD alerts adopt the report fallback.
- `nav.html` PAGE_GROUPS: delete `{'key': 'rules', …}`.
- `main.py` `/errands`: at the top,

```python
    if request.query_params.get('tab') == 'rules':
        return RedirectResponse('errands?settings=open')
```

- [ ] **Step 4: Update `tests/test_drive_setup_live.py:286-311`** — the errand-rules link now points at the Errands drawer: assert the Drives drawer's `#rules` carries no `errands?tab=rules` link only if that link was removed; otherwise assert it ends with `errands?settings=open` (change the link in `drive_setup_panel.html` `#rules` to `errands?settings=open`). Load `errands`, open the gear, create the rule through the drawer, assert `api/errand_rules` and 'Grocery runs' as before.

- [ ] **Step 5: Run the task's tests and the related ones**

Run: `python tools/build_tailwind.py`; `env -u HA_BASE_URL CHF_SHOTS="$TEMP/chf_shots_t12" python tools/test.py settings_drawer drive_setup errand page_tabs nav assist_work`
Expected: pass (`test_page_tabs_live` still sees Errands and Tasks).

- [ ] **Step 6: Capabilities, release** — Bump; commit `feat(settings): errand rules move from a tab into the Errands drawer (vX.Y.Z)`; push.

---

### Task 13: School › Calendar becomes the School drawer

**Files:**
- Modify: `templates/school.html` (`#children` 52-325; `#calendar` 328-403; `saveCalendar`/`postSettings` 524-570)
- Modify: `templates/nav.html` (PAGE_GROUPS: delete the `school` group)
- Modify: `main.py` (`/school` 1746-1761)
- Modify: `tests/test_school_page_live.py:97-100, 168-187`

**Interfaces:**
- Produces: School is ungrouped: bar label "School", key `school`; drawer `data-settings-for="school"`, section `calendar` (both cards); `/school?tab=calendar` → 302 `school?settings=open`.

- [ ] **Step 1: Update the live test first** (`tests/test_school_page_live.py`)

- 97-100: the Children content is visible by default; `[data-page-tab]` assertions go; assert `#page-tabs .page-bar-name` reads `School` and `#page-tabs [data-tab-key]` count is 0.
- 168-173: open `#page-settings-gear`, wait for `[data-settings-for~="school"][data-open]`, then the `#kw-schoolHalfDayKeywords` fill/change and the "Saved" mark in the drawer header.
- 185-187: `school#calendar` opens the drawer at `#calendar`; add `school?tab=calendar` → drawer open, URL without `tab=`.

- [ ] **Step 2: Run it and watch it fail** — `env -u HA_BASE_URL python tests/test_school_page_live.py` → FAIL.

- [ ] **Step 3: Move it**

- `school.html`: import line. `<section id="children" data-page-tab="children">` loses `data-page-tab` (the page has no tabs now). Cut `<section id="calendar" data-page-tab="calendar">` (328-403) and paste its two cards, unchanged except the "Saved ✓" badge `saved==='calendar'` deleted, into:

```html
        {% call settings_drawer('school', 'School') %}
        {% call settings_section('calendar', 'School calendar') %}
        <div class="flex flex-col gap-4">
            {# card 1 (calendar, year dates, status line) and card 2 (the
               district's words), fills bg-gray-800 → bg-gray-900 #}
        </div>
        {% endcall %}
        {% endcall %}
```

  inside the `schoolPage()` island. `postSettings` adopts THE SAVE REPORT PATTERN (its success work — emptying default word boxes, `loadSchoolStatus()` — stays).
- `nav.html` PAGE_GROUPS: delete the `'school': [...]` group. School's admin-bar link now uses `item.href` (`school`).
- `main.py` `/school`: at the top, `if request.query_params.get('tab') == 'calendar': return RedirectResponse('school?settings=open')`.

- [ ] **Step 4: Run the task's tests and the related ones**

Run: `python tools/build_tailwind.py`; `env -u HA_BASE_URL CHF_SHOTS="$TEMP/chf_shots_t13" python tools/test.py school_page settings_drawer nav page_tabs bus settings_registry`
Expected: pass (`test_nav`'s parsed-tab floor of 12 still holds: 15 tabs remain).

- [ ] **Step 5: Capabilities, release** — Bump; commit `feat(settings): School's calendar settings in the drawer; School is one page again (vX.Y.Z)`; push.

---

### Task 14: Trips and Map

**Files:**
- Modify: `templates/trips.html` (`#trip-hashtags` 113-198)
- Modify: `templates/map.html` (announce strip 22-63; `Announce` 83-182)
- Modify: `services/settings_registry.py` (`announce_targets` ui_marker stays `announce-pin-select`)
- Modify: `tests/test_config_small_moves_live.py:76-89` (only if it fails)
- Test: `tests/test_settings_drawer_rest_live.py` (new)

**Interfaces:**
- Produces: Trips drawer `data-settings-for="trips"`, section `trip-hashtags` (the island root itself). Map drawer `data-settings-for="map"`, section `announce` (voice select + one pin row per room cloned from `<template id="announce-pin-row">`, each select carrying class `announce-pin-select` and `data-room`); the strip is renamed `#announce-strip`; `#announce-pin-toggle` is gone.

- [ ] **Step 1: Write the failing live test**

Create `tests/test_settings_drawer_rest_live.py` (shared header/helpers; seed a parent). Body:

```python
            page.set_viewport_size({'width': 1300, 'height': 900})
            T = '[data-settings-for~="trips"]'
            page.goto(served.url('trips'), wait_until='networkidle')
            check(not _visible(page, '#trip-hashtags'), 'trip hashtags still sit under the gallery')
            page.click('#page-settings-gear')
            page.wait_for_selector(T + '[data-open]')
            box = page.evaluate("(s) => { const r = document.querySelector(s).getBoundingClientRect(); return [r.width, innerWidth]; }", T)
            check(box[0] == box[1], 'the Trips drawer is trapped by .glass-panel')
            before = storage.get_settings()
            page.fill('#newTripHashtagInput', '#holiday')
            page.click(T + ' [data-add-trip-hashtag]')
            page.wait_for_selector(T + ' [data-settings-status]:has-text("Saved")')
            check(_changed(before, storage.get_settings()) == {'trip_hashtags'}, 'hashtags saved more than themselves')
            _shot(page, 'trips-open-desktop')
            page.click(T + ' [aria-label="Close settings"]')
            P = '[data-settings-for~="map"]'
            page.goto(served.url('map'), wait_until='networkidle')
            check(page.query_selector('#announce-pin-toggle') is None, "the strip's gear reveal survived")
            page.click('#page-settings-gear')
            page.wait_for_selector(P + '[data-open]')
            check(_visible(page, P + ' #announce-voice-select'), "Argyle's voice is not in the Map drawer")
            _shot(page, 'map-open-desktop')
```

If the test environment has announce rooms (check `api/announce/rooms` fixture use in `tests/test_announce.py`), also pick a pin in the first row and assert `announce_targets` changed; otherwise assert the drawer's empty line ("No rooms with a speaker yet.") is visible. Phone shot pairs for both.

- [ ] **Step 2: Run it and watch it fail** → FAIL.

- [ ] **Step 3: Trips**

- Import line. The guarded block (113-198) becomes:

```html
    {% call settings_drawer('trips', 'Trips') %}
    <section id="trip-hashtags" data-settings-section x-data="tripHashtagsPanel()" x-init="init()" class="scroll-mt-28">
        <div class="text-xs font-semibold text-gray-500 uppercase tracking-widest mb-2">Trip hashtags</div>
        <div class="bg-gray-900 rounded-xl p-4">
            {# the old section's content, unchanged, minus its "Saved ✓" chip #}
        </div>
    </section>
    {% endcall %}
```

  placed after `</main>` (outside the `.panel-page` main and never inside a `.glass-panel`); keep the `<script>` that defines `tripHashtagsPanel()` where it is. Drop the old Jinja wall guard (the drawer guards). `save()` adopts THE SAVE REPORT PATTERN.

- [ ] **Step 4: Map**

- Import line in `map.html`. Rename the strip `<div id="announce" …>` to `id="announce-strip"` and update `Announce`'s references (`#announce-toggle.onclick` toggles `#announce-strip`). Delete `#announce-pin-toggle` (46-48), `#announce-pin` (49-52) and `#announce-voice-row` (57-60) from the strip.
- Before the page's scripts, add:

```html
    {% call settings_drawer('map', 'Map') %}
    {% call settings_section('announce', 'Announcements') %}
    <div class="bg-gray-900 rounded-xl p-4 space-y-4">
        <label class="block">
            <span class="text-xs font-semibold text-gray-200">Argyle's voice</span>
            <select id="announce-voice-select" class="mt-1 w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm"></select>
        </label>
        <div>
            <div class="text-xs font-semibold text-gray-200">Speaker for each room</div>
            <p class="text-[11px] text-gray-500 mt-0.5">Unpinned rooms use the voice satellite, then whichever player is already on.</p>
            <div id="announce-pins" class="mt-2 space-y-2"></div>
            <p id="announce-pins-empty" class="hidden text-xs text-gray-500 italic">No rooms with a speaker yet.</p>
        </div>
        <template id="announce-pin-row">
            <label class="flex items-center justify-between gap-3">
                <span class="announce-pin-room text-sm text-gray-300"></span>
                <select class="announce-pin-select bg-gray-800 border border-gray-700 rounded-lg px-2 py-1.5 text-white text-sm"></select>
            </label>
        </template>
    </div>
    {% endcall %}
    {% endcall %}
```

  (copy the old voice select's options/attributes and the old pin help text if they differ).
- `Announce`: build one row per room from `#announce-pin-row` into `#announce-pins` after rooms load (the room name into `.announce-pin-room`, the room's players into the select with the same option list the old `#announce-pin-select` got, `select.dataset.room = room.id`, `select.value = room.pinned || ''`); show `#announce-pins-empty` when there are none. Each select's change sets that room's `pinned` and calls `savePin()`, which still POSTs the whole `announce_targets` map. Load voices on `chf-settings-opened` with `tab === 'map'` (replacing the old lazy load on the ⚙ reveal), once. The voice select's change keeps POSTing `api/announce/voice`. Both saves use THE SAVE REPORT PATTERN without the `showGlobalAlert` fallback (`/map` has no `control_center.html`).

- [ ] **Step 5: Run the task's tests and the related ones**

Run: `python tools/build_tailwind.py`; `env -u HA_BASE_URL CHF_SHOTS="$TEMP/chf_shots_t14" python tools/test.py settings_drawer config_small_moves announce family_map settings_registry trip`
Expected: pass. If `test_config_small_moves_live` 76-89 (`trips#trip-hashtags`) fails, make it wait for `[data-settings-for~="trips"][data-open]` before asserting.

- [ ] **Step 6: Capabilities, release** — Bump; commit `feat(settings): trip hashtags and announcements in their drawers (vX.Y.Z)`; push.

---

### Task 15: Home and Music

**Files:**
- Modify: `templates/home.html` (toolbar ⚙ 805-814; `#board-settings` 1177-1324; `openBoardSettings` 5210-5219; `closeBoardSettings` 5221-5229; `newPage()` ~4647)
- Test: `tests/test_settings_drawer_rest_live.py` (append)

**Interfaces:**
- Produces: drawer `data-settings-for="<home|music|board>"` (Jinja: `'music'` when the path contains `/music`, `'board'` when it contains `/board/`, else `'home'`), section `board-settings`; opening runs `openBoardSettings()`, closing runs `closeBoardSettings()` (which saves).

- [ ] **Step 1: Append the failing scenario**

```python
            H = '[data-settings-for~="home"]'
            page.goto(served.url('home'), wait_until='networkidle')
            check(page.locator('[x-data="homeBoard()"] button:has-text("Settings")').count() == 0,
                  "the board toolbar's ⚙ Settings survived")
            check(_visible(page, 'button:has-text("✎ Edit")'), 'Edit left the toolbar')
            page.click('#page-settings-gear')
            page.wait_for_selector(H + '[data-open]')
            page.fill('#boardSettingsName', 'Our home')
            page.dispatch_event('#boardSettingsName', 'change')
            page.keyboard.press('Escape')
            page.wait_for_timeout(600)
            pages = storage.get_settings().get('panel_pages') or []
            check(any((p.get('name') == 'Our home') for p in pages), 'closing the drawer did not save the board name')
            _shot(page, 'home-open-desktop')
            page.goto(served.url('music'), wait_until='networkidle')
            page.click('#page-settings-gear')
            page.wait_for_selector('[data-settings-for~="music"][data-open]')
            page.goto(served.url('home?panel=true'), wait_until='domcontentloaded')
            check(page.query_selector('[data-settings-for]') is None, 'a panel drew the board drawer')
```

(The name input is the one bound through `setPageField('name'` at 1197-1206; Step 3 gives it `id="boardSettingsName"`. If it commits on `input` rather than `change`, dispatch that event instead. The drawer itself lives inside `homeBoard()`, so the toolbar check excludes the drawer's own header by looking for the old button's label only in the toolbar row if the first check proves too broad.)

- [ ] **Step 2: Run it and watch it fail** → FAIL.

- [ ] **Step 3: Move the modal into the drawer**

- Import line near the top of `home.html`'s body content.
- Delete the toolbar `⚙ Settings` button (811-814) and its comment (805-810). `✎ Edit` stays.
- Keep the literal comment `<!-- ── The BOARD's settings, over the board.` (tests slice from it to `<!-- The card picker`) directly above the replacement, and the card-picker comment directly after it. Replace the `#board-settings` modal root and its inner card (1183-1324) with:

```html
        {% set _bk = 'music' if '/music' in request.url.path else ('board' if '/board/' in request.url.path else 'home') %}
        {% call settings_drawer(_bk, 'Board') %}
        <section id="board-settings" data-settings-section class="scroll-mt-28 flex flex-col gap-5"
            @chf-settings-opened.window="$event.detail.tab === '{{ _bk }}' && openBoardSettings()"
            @chf-settings-closed.window="$event.detail.tab === '{{ _bk }}' && closeBoardSettings()">
            {# the old card's contents, unchanged: icon + name (give the
               name input id="boardSettingsName"), the icon picker panel,
               the address, the picture, the grid and its gutter hint.
               The ✕ goes (the drawer header has one). The footer's "Done"
               calls chfCloseSettings(); Reset/Delete calls
               `removePage(); chfCloseSettings()`. #}
        </section>
        {% endcall %}
```

  placed inside the `homeBoard()` root. If the icon picker's EmojiPicker overlay sits below `z-[85]`, raise it to `z-[90]`.
- Script: `openBoardSettings()` keeps pointing `pageIndex` at the viewed board and setting `iconPicking = false; boardSettings = true` — it is now run by the opened event. `closeBoardSettings()` keeps `boardSettings = false; iconPicking = false; await this.save()` — run by the closed event. `newPage()`: replace `this.boardSettings = true` with `this.$nextTick(() => window.chfOpenSettings('{{ _bk }}'))` — or, since the script is not templated, read the key from the DOM: `const d = document.querySelector('[data-settings-for]'); if (d) window.chfOpenSettings(d.getAttribute('data-settings-for'));`. `save()` errors adopt the report fallback.
- Keep `test_home_board.py`'s and `test_board_instances.py`'s pinned strings inside the slice (`setPageField('name'`, `('icon'`, `setPageSlug(`, `('background'`, `('columns'`, `('row_height'`, `('gap'`, `removePage()`), `setPageField('background'` exactly once in the file, and `'max-h-56'` within 200 characters after the first `x-show="iconPicking"`.

- [ ] **Step 4: Run the task's tests and the related ones**

Run: `python tools/build_tailwind.py`; `env -u HA_BASE_URL CHF_SHOTS="$TEMP/chf_shots_t15" python tools/test.py settings_drawer home_board board_instances board_pages board_arrange settings_registry music`
Expected: pass. Screenshots: Home closed/open, Music open, a custom board open, phone.

- [ ] **Step 5: Capabilities, release** — Home, Music and boards: the board settings modal becomes the drawer; toolbar ⚙ gone. Close the arc's `system_capabilities.md` paragraph with the full list of drawers. Bump; commit `feat(settings): board settings in the drawer on Home, Music and custom boards (vX.Y.Z)`; push.

---

## Self-review (done while writing)

- **Spec coverage:** page bar (T1), drawer shell/z/close/chips/sections (T1), saving + shared mark (T1, every task), Alpine scope + transform trap (Global Constraints, T1/T10/T14 rect checks), open event + deep links + hash clearing + one shared opener (T1), registry anchors + `audit()` drawer check (T2; spec says `audit()`, the anchor check lives in `audit_ui()` where anchors are already checked), placement rules in the guide (T1), Threads + Programs pilots (T1, T2), Mind/Missions/Intake (T3-T5), Meals (T6), Chores/Routines/Growing up (T7-T9), Drives/Calendar/Occasions (T10-T11), Errands/School/Trips/Map/Home/Music (T12-T15), forwarded URLs (T9, T10, T12, T13), wall pins (T1 + each live test), screenshots (each task).
- **Deviations, flagged for the reader:** Growing up forwards to `config#growing-up`, not `config?tab=people#growing-up` (T9, reason given); the stage finding has no link field, so only its text changes (T9); a second helper `chfSettingsSaving()` joins `chfSettingsSaved()` so "Saving…" is shown by the page that knows a save started rather than guessed from every `change` event; Missions gains a Remove button so clearing the paid key stays possible once the field no longer shows it.
- **Not in the spec, added because the move needs it:** `?settings=open` as the landing for forwards from retired tabs; `chf-settings-opened/closed` events (lazy loads, Home's save-on-close); the registry audit's in-place include flattening.
