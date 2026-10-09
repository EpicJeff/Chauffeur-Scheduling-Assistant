# Situations, build 2 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** /threads and /missions rewritten around the situation card, the PWA House tab's threads drawn by the same builder, and the watcher DM heads-up carrying each finding's next step and asks.

**Architecture:** The pages stay Alpine islands; each card is `Situations.cardHtml(s, ctx)` inserted with `x-html`, and one delegated listener per lane (`Situations.bind`) runs the card's verbs through `/api/situations/.../act`. A page may **intercept** a verb (`ctx.intercept`) to open its own editable form instead of a prompt — that is how the thread draft/send box, the advance form and the mission answer box keep their exact behaviour. Everything the old pages held (history timeline, note/advance/edit/research/draft forms, Work-this, launch form, transcript, OK acks, settings drawers) lives in a `<details>` under the card or in the page chrome, unchanged in function. `GET /api/situations` gains `owner=` for the PWA's own-threads view. The DM heads-up gains one clause per finding from `situations.view`.

**Tech Stack:** as build 1 (FastAPI, TinyDB-over-SQLite, Alpine + vanilla JS, precompiled Tailwind, standalone test scripts, `live_app` + playwright for live tests).

**Spec:** `docs/superpowers/specs/2026-10-09-situations-design.md` §3 (surfaces), §2 (the DM clause). Build 1 shipped v2.499.303–.313; this is the second half.

## Global Constraints

- Run from `E:\repositories\Chauffeur\chauffeur` with `..\venv\Scripts\python.exe`; tests with `HA_BASE_URL` unset.
- Gate for this build: `tools/test.py situation threads missions watchers mind_endpoints tailwind_build household_features_live` plus the two new live tests. Never the full sweep.
- Markup contracts pinned by `tests/test_missions_endpoints.py` must hold: `threads_page.html` contains `/api/missions/launch`; `missions_page.html` contains `/api/missions/admin`, `/api/missions/launch`, `waiting_user`, `toggleTranscript`, and includes `components/mission_transcript.html` exactly twice; no `alert(`, `confirm(`, `prompt(`; no chrome includes in components.
- Nothing a person can do today is lost: every button on the old pages has a home on the new ones (the table in Task 2 and Task 3 lists them).
- Every model/user string renders through `x-text`, `mfEscape`/`esc`, or JSON into `x-text`; never raw `x-html` of user content (the card builder escapes everything it draws).
- `python tools/build_tailwind.py` after any template class change; `tests/test_tailwind_build.py` must pass.
- Every commit bumps `config.yaml` (`2.499.315` onward, +1 per commit; v2.499.314 is the plan commit), message ends `(vX.Y.Z)`, push.
- Persisted prose is normal English.

## Review Focus

1. A thread whose `owner_member_id` is a **child** viewed on the PWA House tab by that child: cards render, no buttons (the child cannot write), the note form is absent. Pinned in Task 4's endpoint test (`scenario_owner_filter_and_child_view`).
2. The thread draft box: **Send posts exactly what is in the box**, never the draft returned a moment earlier — the two-endpoint rule from v2.429. Pinned in Task 2's live test (`the_send_box_posts_what_is_typed`).
3. A **finished mission with a pending proposal** on /missions: it sits in the "Needs you" group, and approving from the transcript moves it to history. Pinned in Task 3's live test.
4. The DM heads-up for a finding with **no situation record yet** (first sweep opens it in the same pass) → the clause falls back to the line alone, no crash. Pinned in Task 5 (`scenario_heads_up_clause_survives_a_missing_record`).
5. `Situations.bind` on a lane whose cards are re-rendered by Alpine: a second `bind` on the same element must not **double-fire** verbs. Pinned in Task 1 (the JS test through the live harness: one act → one request).

---

### Task 1: `situations.js` — `bind`, `intercept`, `extraHtml`, `details`

**Files:**
- Modify: `static/situations.js`
- Test: `tests/test_situations_builder_live.py` (new; the builder's contract, driven in a real page)

**Interfaces:**
- `Situations.bind(el, ctx)` — attaches the delegated click listener once per element (idempotent; re-binding replaces `el.__sitCtx`). `ctx.lookup(kind, id) -> situation` resolves what was clicked when the page, not `render`, drew the cards.
- `ctx.intercept(s, option, card) -> boolean` — called before `act`/`ask`; `true` means the page handled it.
- `ctx.extraHtml(s) -> string` — HTML appended inside the card after the ask ledger (the page escapes its own content).
- `cardHtml(s, ctx)` no longer draws an empty `<details>`; pages add their own details under the card.
- `Situations.verbLabel(verb)`.

- [ ] **Step 1: Write the failing live test**

```python
# tests/test_situations_builder_live.py
"""The card builder's page contract, in a real browser: bind resolves cards
through the page's lookup, a second bind never double-fires, intercept
wins over the default act, extraHtml lands inside the card."""
import datetime
import os
import sys
import tempfile

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='situations_builder_live_'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from live_app import live_app
from services import storage

NOON = datetime.datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def seed():
    storage.update_settings({'llm_gemini_api_key': ''})
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent', 'color_code': '#6366f1'})
    from services import threads
    threads.create('Deck permit', owner_member_id='mom', next_action='call county', created_by='mom')


PAGE = """
<!doctype html><html><head><meta charset="utf-8"></head><body>
<div id="lane"></div>
<script>
  window.hits = []; window.intercepted = [];
  const origFetch = window.fetch;
  window.fetch = async (url, opts) => { if (String(url).includes('/act')) window.hits.push(String(url)); return origFetch(url, opts); };
</script>
<script src="/static/situations.js"></script>
</body></html>
"""


def main():
    served = live_app(seed)
    if served is None:
        return
    try:
        b = served.browser(color_scheme='dark')
        with b as page:
            page.goto(served.url('threads'), wait_until='networkidle')   # any page that serves static/
            page.set_content(PAGE.replace('/static/', served.url('static/')), wait_until='networkidle')
            sits = page.evaluate("async () => (await (await fetch('%s')).json()).situations" % served.url('api/situations?kinds=thread'))
            check(sits and sits[0]['kind'] == 'thread', "a thread situation to draw")
            n_hits = page.evaluate("""(sits) => {
                const el = document.getElementById('lane');
                const byId = {}; sits.forEach(s => byId[s.id] = s);
                const ctx = { apiBase: '%s', canWrite: true, lookup: (k, id) => byId[id],
                              intercept: (s, o) => { if (o.verb === 'advance') { window.intercepted.push(o.id); return true; } return false; },
                              extraHtml: (s) => '<div class="sit-extra">EXTRA ' + s.title + '</div>' };
                el.innerHTML = sits.map(s => Situations.cardHtml(s, ctx)).join('');
                Situations.bind(el, ctx);
                Situations.bind(el, ctx);     // a second bind must not double-fire
                const adv = el.querySelector('[data-sit-act^="advance"]'); adv.click();
                const own = el.querySelector('[data-sit-act="own"]'); own.click();
                return new Promise(r => setTimeout(() => r({ hits: window.hits.length, intercepted: window.intercepted.length,
                    extra: !!el.querySelector('.situation-card .sit-extra'), details: !!el.querySelector('.situation-card details') }), 1200));
            }""" % served.url(''), sits)
            check(n_hits['intercepted'] == 1, f"intercept handled advance once, got {n_hits}")
            check(n_hits['hits'] == 1, f"own fired exactly one act request through two binds, got {n_hits}")
            check(n_hits['extra'], "extraHtml landed inside the card")
            check(not n_hits['details'], "the card draws no empty details element any more")
            check(not b.errors, f"script errors: {b.errors}")
    finally:
        served.stop()


if __name__ == '__main__':
    main()
    print("test_situations_builder_live OK")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `env -u HA_BASE_URL ../venv/Scripts/python.exe tests/test_situations_builder_live.py`
Expected: FAIL — `Situations.bind is not a function` (page error) or the intercept count is 0.

- [ ] **Step 3: Change `static/situations.js`**

Replace the `render` function and the tail of the module with:

```javascript
  function verbLabel(verb) { return VERB_LABELS[verb] || verb; }

  // One delegated listener per lane element. Pages that draw the cards
  // themselves (Alpine x-html) call bind() with a lookup; render() calls it
  // for its own map. Re-binding only swaps the ctx: never a second listener.
  function bind(el, ctx) {
    el.__sitCtx = ctx || {};
    if (el.__sitBound) return;
    el.__sitBound = true;
    el.addEventListener('click', async (ev) => {
      const ctx2 = el.__sitCtx || {};
      const b = ev.target.closest('button'); if (!b || !el.contains(b)) return;
      if (b.closest('.sit-ask-flow')) return;      // the flow has its own handler
      const card = b.closest('.situation-card'); if (!card) return;
      const s = (ctx2.lookup && ctx2.lookup(card.dataset.kind, card.dataset.id))
             || (el.__situations || {})[`${card.dataset.kind}:${card.dataset.id}`];
      if (!s) return;
      if (b.dataset.sitAct) {
        const option = (s.options || []).find(o => o.id === b.dataset.sitAct); if (!option) return;
        if (ctx2.intercept && ctx2.intercept(s, option, card)) return;
        if (option.verb === 'ask') return ask(s, option, ctx2, card);
        return act(s, option, ctx2);
      }
      if (b.dataset.askAnswer) {
        try { const d = await post(ctx2, `api/asks/${b.dataset.askId}/answer`, { answer: b.dataset.askAnswer, reported: true }); if (d.message) alert_(d.message); }
        catch (e) { alert_(e.message); }
        if (ctx2.onChange) ctx2.onChange();
        return;
      }
      if (b.dataset.askSent) {
        try { await post(ctx2, `api/asks/${b.dataset.askSent}/sent`, {}); } catch (e) { alert_(e.message); }
        if (ctx2.onChange) ctx2.onChange();
      }
    });
  }

  function render(el, list, ctx) {
    ctx = ctx || {};
    el.innerHTML = (list || []).map(s => cardHtml(s, ctx)).join('');
    el.__situations = {}; (list || []).forEach(s => { el.__situations[`${s.kind}:${s.id}`] = s; });
    bind(el, ctx);
  }

  return { VERB_LABELS, verbLabel, cardHtml, render, bind, act, ask };
```

In `cardHtml`, replace the last two lines of the template (the `sit-asks` div and the `<details>`) with:

```javascript
      <div class="sit-asks">${(s.asks || []).filter(a => a.state !== 'withdrawn').map(a => askLine(a, ctx)).join('')}</div>
      ${ctx.extraHtml ? ctx.extraHtml(s) : ''}
    </div>`;
```

- [ ] **Step 4: Run the builder test, then the lane test from build 1**

Run: `env -u HA_BASE_URL ../venv/Scripts/python.exe tests/test_situations_builder_live.py` → OK. Then `env -u HA_BASE_URL ../venv/Scripts/python.exe tests/test_situations_lane_live.py` → OK (render still binds).

- [ ] **Step 5: Commit**

Bump to `2.499.315`.
```bash
git add chauffeur/config.yaml chauffeur/static/situations.js chauffeur/tests/test_situations_builder_live.py
git commit -m "feat(situations): the card builder binds to page-drawn cards, lets a page intercept a verb, and takes extra markup (v2.499.315)" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push origin main
```

---

### Task 2: /threads rewritten on the card

**Files:**
- Modify: `templates/components/threads_page.html` (the whole file; the settings drawer lines 17–32, the create form 34–81 and the Alpine methods from line 311 on are kept verbatim where noted)
- Test: `tests/test_threads_page_live.py` (new); `tests/test_missions_endpoints.py` unchanged (its `scenario_threads_page_has_the_button` must still pass)

**Interfaces:**
- Consumes: `GET /api/situations?kinds=thread&include_done=1`, `GET /api/threads?include_closed=true` (the rows, for the details), `Situations.cardHtml/bind`, the existing `/api/threads/*` endpoints.
- Produces: Alpine `threadsPage()` with `situations: []`, `groups` (computed), `threadById(id)`, `sitById(id)`, `intercept(s, option, card)`, `openDetails(id)`, and every existing method unchanged (`load`, `createThread`, `submitNote`, `openAdvance`, `submitAdvance`, `openEdit`, `submitEdit`, `closeThread`, `workThis`, `requestDraft`, `sendDraft`, `submitResearch`, `researchStatusMessage`, `saveStallDays`, the formatters).

**Where every old control goes:**

| Old control | New home |
|---|---|
| Stalled / Open / Waiting / Done & dropped sections | groups *Needs you now* (`now`) · *Waiting on them* (`waiting`) · *Moving* (`moving`, in hand included) · *Closed* (`done`, folded) |
| title, kind chip, stall chip, goal, counterparty · owner, Next: …, last history line | the card (title, meta, note) + details header (goal, counterparty · owner, kind) |
| Draft email | card option `draft` → intercepted: opens details and runs `requestDraft(t)` (the editable to/subject/body box, Send/Redraft/Cancel, unchanged) |
| Add note | details: the note form, unchanged |
| Advance | card option `advance` → intercepted: opens details with the advance form (unchanged) |
| Research | card option `research` → intercepted: opens details with the research box (unchanged) |
| Work this | details button, unchanged (`/api/missions/launch`) |
| Edit | details button + form, unchanged |
| Done / Drop | card options `close:done` / `close:dropped` (the card confirms nothing; `act` closes) — the details keep the two old buttons with `promptConfirm` for people who want the confirmation |
| archive row (Done · time) | the Closed group's cards show state and since; details show the history |
| history | details: a timeline list (new, every entry; the old page showed only the last line) |

- [ ] **Step 1: Write the failing live test**

```python
# tests/test_threads_page_live.py
"""/threads on the situation card: groups, the next step as the primary
button, details that hold the old forms, the send box posting what is
typed, and nothing lost. Run from chauffeur/."""
import datetime
import os
import sys
import tempfile

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='threads_page_live_'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from live_app import live_app
from services import storage

SHOTS = os.environ.get('CHF_SHOTS')
TODAY = datetime.date.today()


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        page.screenshot(path=os.path.join(SHOTS, name + '.png'))


def seed():
    from services import threads, mailer
    storage.update_settings({'llm_gemini_api_key': '', 'thread_stall_days': 7})
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent', 'color_code': '#6366f1'})
    threads.create('Deck permit with the county', owner_member_id='mom', next_action='call county',
                   next_action_at=(TODAY - datetime.timedelta(days=3)).isoformat(),
                   counterparty_name='County', counterparty_email='permits@county.gov', created_by='mom')
    tid = threads.create('Pool opening', owner_member_id='mom', kind='vendor', next_action='wait for the quote',
                         counterparty_name='Pool guy', created_by='mom')
    storage.update_thread(tid, {'state': 'waiting'})
    done = threads.create('Old fence quote', owner_member_id='mom', created_by='mom')
    threads.close(done, 'done', who='mom')
    # The send box must post what is typed: stub the mailer to record it.
    mailer.configured = lambda settings: True
    sent = []
    mailer.send = lambda to, subject, body, settings=None: (sent.append((to, subject, body)) or {'sent': True, 'reason': None})
    mailer._test_sent = sent


def main():
    served = live_app(seed)
    if served is None:
        return
    try:
        b = served.browser(color_scheme='dark')
        with b as page:
            page.set_viewport_size({'width': 1300, 'height': 900})
            page.goto(served.url('work?tab=threads'), wait_until='networkidle')
            page.wait_for_selector('.situation-card')
            groups = page.locator('[data-sit-group]').all_inner_texts()
            check(any('Needs you now' in g for g in groups) and any('Waiting on them' in g for g in groups),
                  f"groups by situation: {[g[:30] for g in groups]}")
            first = page.locator('[data-sit-group="now"] .situation-card').first
            check('Deck permit' in first.locator('.sit-title').inner_text(), "the overdue thread needs you now")
            check(first.locator('.sit-next button').first.inner_text().startswith('Set the next step'),
                  "the primary button is the next step")
            # Details hold the old forms; Advance from the card opens them.
            first.locator('.sit-next button').first.click()
            page.wait_for_selector('[data-sit-group="now"] details[open] input[placeholder="What has to happen next"]')
            page.fill('[data-sit-group="now"] details[open] input[placeholder="What has to happen next"]', 'email the inspector')
            page.locator('[data-sit-group="now"] details[open] button:has-text("Save")').first.click()
            page.wait_for_timeout(800)
            row = [t for t in storage.get_threads(include_closed=True) if 'Deck permit' in t['title']][0]
            check(row['next_action'] == 'email the inspector', f"advance saved through the old form: {row['next_action']}")
            # The send box posts what is typed, never the draft.
            deck = page.locator('.situation-card:has-text("Deck permit")').first
            deck.locator('.sit-options button:has-text("Draft a message")').click()
            page.wait_for_selector('details[open] textarea[placeholder="Body"]', timeout=15000)
            page.fill('details[open] textarea[placeholder="Body"]', 'TYPED BY A PERSON')
            page.fill('details[open] input[placeholder="Send to"]', 'permits@county.gov')
            page.locator('details[open] button:has-text("Send")').first.click()
            page.wait_for_timeout(300)
            page.locator('button:has-text("Send")').last.click()      # promptConfirm's Send
            page.wait_for_timeout(800)
            from services import mailer
            check(mailer._test_sent and mailer._test_sent[-1][2] == 'TYPED BY A PERSON',
                  f"send posted the box, got {mailer._test_sent}")
            # Nothing lost: Work this, Edit, Add note, Research still reachable.
            deck = page.locator('.situation-card:has-text("Deck permit")').first
            for label in ('Work this', 'Edit', 'Add note', 'Research'):
                check(page.locator(f'details button:has-text("{label}")').count() >= 1, f"{label} still has a home")
            # Closed group folded, with the done thread inside.
            check(page.locator('[data-sit-group="done"] .situation-card').count() == 0, "closed starts folded")
            page.locator('[data-sit-group="done"] button').first.click()
            page.wait_for_timeout(300)
            check('Old fence' in page.locator('[data-sit-group="done"]').inner_text(), "unfolded: the done thread")
            _shot(page, 'threads-page')
            check(not b.errors, f"script errors: {b.errors}")
    finally:
        served.stop()


if __name__ == '__main__':
    main()
    print("test_threads_page_live OK")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `env -u HA_BASE_URL ../venv/Scripts/python.exe tests/test_threads_page_live.py`
Expected: FAIL at `wait_for_selector('.situation-card')` (the old page draws none).

- [ ] **Step 3: Rewrite the markup (lines 1–288)**

Keep lines 1–33 (header, intro, settings drawer) and the create form (34–81) exactly. Replace lines 83–288 (the sections loop through the closing `</div>` of the island) with:

```html
            <!-- The lane: one card per thread, grouped by what it needs. The
                 card is the shared builder's (static/situations.js); the
                 details underneath hold everything the old page held. -->
            <div x-ref="lane">
            <template x-for="g in groups" :key="g.key">
                <div class="mb-6" :data-sit-group="g.key">
                    <button x-show="g.folded" @click="foldOpen[g.key] = !foldOpen[g.key]"
                        class="w-full flex items-center justify-between text-xs font-black uppercase tracking-widest px-1 mb-2"
                        :class="g.titleClass">
                        <span x-text="g.label + ' (' + g.items.length + ')'"></span>
                        <span class="text-gray-600 normal-case font-semibold" x-text="foldOpen[g.key] ? 'Hide' : 'Show'"></span>
                    </button>
                    <div class="text-xs font-black uppercase tracking-widest px-1 mb-2" x-show="!g.folded" :class="g.titleClass">
                        <span x-text="g.label"></span>
                    </div>
                    <template x-if="!g.folded || foldOpen[g.key]">
                    <div>
                    <p class="text-xs text-gray-500 italic px-1" x-show="!g.items.length" x-text="g.empty"></p>
                    <div class="space-y-2">
                        <template x-for="s in g.items" :key="s.id">
                            <div>
                                <div x-html="window.Situations.cardHtml(s, cardCtx())"></div>
                                <template x-if="threadById(s.id)">
                                <details class="sit-details -mt-2 bg-gray-900/60 border border-gray-800 border-t-0 rounded-b-2xl px-3 pb-3"
                                    :open="detailsOpen[s.id] ? true : null" @toggle="detailsOpen[s.id] = $event.target.open">
                                    <summary class="text-[11px] text-gray-500 cursor-pointer py-1.5">details</summary>
                                    <div x-data="{ t: threadById(s.id) }" class="space-y-2">
                                        <div class="text-xs text-gray-500" x-show="t.goal" x-text="t.goal"></div>
                                        <div class="text-[11px] text-gray-500">
                                            <span x-text="counterpartyLabel(t)"></span>
                                            <span class="text-gray-700"> · </span>
                                            <span x-text="memberName(t.owner_member_id)"></span>
                                            <span class="text-gray-700"> · </span>
                                            <span x-text="t.kind"></span>
                                        </div>

                                        <!-- History: every entry, newest last. -->
                                        <div class="space-y-0.5" x-show="(t.history || []).length">
                                            <template x-for="(h, i) in (t.history || [])" :key="i">
                                                <div class="text-[11px] text-gray-500">
                                                    <span class="text-gray-600" x-text="fmtTs(h.ts)"></span>
                                                    <span class="text-gray-400" x-text="' ' + fmtWho(h.who) + ': '"></span>
                                                    <span x-text="h.text"></span>
                                                    <a x-show="h.url" :href="h.url" target="_blank" rel="noopener" class="text-blue-400 underline underline-offset-2"> ↗</a>
                                                </div>
                                            </template>
                                        </div>

                                        <div class="flex flex-wrap gap-2 mt-1" x-show="t.state !== 'done' && t.state !== 'dropped'">
                                            <button @click="requestDraft(t)"
                                                class="text-xs font-bold px-3 py-1.5 rounded-lg bg-purple-700 text-white active:bg-purple-800">Draft email</button>
                                            <button @click="noteOpen[t.id] = !noteOpen[t.id]"
                                                class="text-xs font-bold px-3 py-1.5 rounded-lg bg-gray-800 text-gray-300 border border-gray-700 active:bg-gray-700">Add note</button>
                                            <button @click="openAdvance(t)"
                                                class="text-xs font-bold px-3 py-1.5 rounded-lg bg-gray-800 text-gray-300 border border-gray-700 active:bg-gray-700">Advance</button>
                                            <button @click="researchOpen[t.id] = !researchOpen[t.id]"
                                                class="text-xs font-bold px-3 py-1.5 rounded-lg bg-indigo-700 text-white active:bg-indigo-800">Research</button>
                                            <!-- Work this: opens a MISSION on this thread (POST
                                                 /api/missions/launch, origin_kind 'thread'). -->
                                            <button @click="workThis(t)"
                                                class="text-xs font-bold px-3 py-1.5 rounded-lg bg-violet-700 text-white active:bg-violet-800">Work this</button>
                                            <button @click="openEdit(t)"
                                                class="text-xs font-bold px-3 py-1.5 rounded-lg bg-gray-800 text-gray-300 border border-gray-700 active:bg-gray-700">Edit</button>
                                            <button @click="closeThread(t, 'done')"
                                                class="text-xs font-bold px-3 py-1.5 rounded-lg bg-teal-700 text-white active:bg-teal-800">Done</button>
                                            <button @click="closeThread(t, 'dropped')"
                                                class="text-xs font-bold px-3 py-1.5 rounded-lg bg-gray-800 text-gray-400 border border-gray-700 active:bg-gray-700">Drop</button>
                                        </div>
                                        <div class="text-[11px] text-gray-600" x-show="t.state === 'done' || t.state === 'dropped'">
                                            <span x-text="t.state === 'done' ? 'Done' : 'Dropped'"></span>
                                            <span x-show="t.closed_at" x-text="' · ' + fmtTs(t.closed_at)"></span>
                                        </div>

                                        {# The four inline forms are the old page's, unchanged: paste
                                           lines 154–279 of the pre-rewrite file here (Add note,
                                           Advance, Edit, Research, Draft & send). They bind to the
                                           same noteText/advanceDraft/editDraft/researchQuestion/
                                           draftText dictionaries keyed by t.id. #}
                                        __OLD_FORMS__
                                    </div>
                                </details>
                                </template>
                            </div>
                        </template>
                    </div>
                    </div>
                    </template>
                </div>
            </template>
            </div>

        </div>
```

Replace `__OLD_FORMS__` with the verbatim block from the old file's lines 154–279 (the `<!-- Add note -->` div through the end of the `<!-- Draft & send -->` div). Do it by copy from git (`git show HEAD:chauffeur/templates/components/threads_page.html | sed -n 154,279p`), not by retyping.

- [ ] **Step 4: The Alpine additions** (inside `threadsPage()`; everything existing stays)

Add these fields after `researchOpen…` (line 309):

```javascript
                situations: [],
                foldOpen: {},
                detailsOpen: {},
```

Extend `load()`: after `this.threads = td.threads || [];` add the situations fetch and the lane bind:

```javascript
                        const sRes2 = await fetch(this.apiBase + 'api/situations?kinds=thread&include_done=1');
                        const sd2 = sRes2.ok ? await sRes2.json() : { situations: [] };
                        this.situations = sd2.situations || [];
                        this.$nextTick(() => window.Situations.bind(this.$refs.lane, this.cardCtx()));
```

Add these methods after `get sections()` (keep `sections` for now; nothing references it after the rewrite, remove it):

```javascript
                get groups() {
                    const by = (g) => this.situations.filter(s => s.group === g);
                    return [
                        { key: 'now', label: '⏳ Needs you now', titleClass: 'text-red-400',
                          items: by('now'), empty: 'Nothing needs you right now.', folded: false },
                        { key: 'waiting', label: 'Waiting on them', titleClass: 'text-gray-500',
                          items: by('waiting'), empty: 'Nothing waiting on somebody else.', folded: false },
                        { key: 'moving', label: 'Moving', titleClass: 'text-gray-500',
                          items: by('moving').concat(by('in_hand')), empty: 'Nothing else in motion.', folded: false },
                        { key: 'done', label: 'Closed', titleClass: 'text-gray-600',
                          items: by('done'), empty: 'Nothing closed yet.', folded: true },
                    ];
                },

                threadById(id) { return this.threads.find(t => t.id === id) || null; },
                sitById(id) { return this.situations.find(s => s.id === id) || null; },

                cardCtx() {
                    return {
                        apiBase: this.apiBase, canWrite: true, readOnly: false,
                        lookup: (kind, id) => this.sitById(id),
                        onChange: () => this.load(),
                        intercept: (s, option) => this.intercept(s, option),
                    };
                },

                // The card's draft/advance/research verbs open the page's own
                // editable forms instead of a prompt: a thread's words are
                // written in a box a person can read back, never in a dialog.
                intercept(s, option) {
                    const t = this.threadById(s.id);
                    if (!t) return false;
                    if (option.verb === 'draft') { this.detailsOpen[s.id] = true; this.requestDraft(t); return true; }
                    if (option.verb === 'advance') {
                        this.detailsOpen[s.id] = true;
                        if (option.payload && option.payload.next_action) {
                            this.advanceDraft[t.id] = { next_action: option.payload.next_action,
                                                        next_action_at: option.payload.next_action_at || '', note: '' };
                        } else if (!this.advanceDraft[t.id]) {
                            this.advanceDraft[t.id] = { next_action: t.next_action || '', next_action_at: t.next_action_at || '', note: '' };
                        }
                        this.advanceOpen[t.id] = true;
                        return true;
                    }
                    if (option.verb === 'research') {
                        this.detailsOpen[s.id] = true;
                        if (option.payload && option.payload.text) this.researchQuestion[t.id] = option.payload.text;
                        this.researchOpen[t.id] = true;
                        return true;
                    }
                    return false;
                },
```

Delete the `sections` getter and the `stalledList/openList/waitingList/archiveList` getters only if nothing else references them (the `x-effect` on line 7 uses `stalledList.length` for the tab count: replace that expression with `groups[0].items.length`).

- [ ] **Step 5: Tailwind, then the tests**

Run: `../venv/Scripts/python.exe tools/build_tailwind.py && env -u HA_BASE_URL ../venv/Scripts/python.exe tests/test_tailwind_build.py`, then `env -u HA_BASE_URL ../venv/Scripts/python.exe tests/test_threads_page_live.py` → OK, then `tools/test.py missions_endpoints threads settings_drawer_live` → all pass (the drawer test opens the threads gear).

- [ ] **Step 6: Commit**

Bump to `2.499.316`.
```bash
git add chauffeur/config.yaml chauffeur/templates/components/threads_page.html chauffeur/static/tailwind.css chauffeur/static/tailwind-app.css chauffeur/tests/test_threads_page_live.py
git commit -m "feat(threads): the page is the lane - situation cards grouped by what they need, the old forms in details, the send box unchanged (v2.499.316)" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push origin main
```

---

### Task 3: /missions rewritten on the card

**Files:**
- Modify: `templates/components/missions_page.html` (lines 99–212 replaced; the settings drawer 1–97 and every method kept)
- Test: `tests/test_missions_page_live.py` (new); `tests/test_missions_endpoints.py` contracts unchanged

**Interfaces:**
- Consumes: `GET /api/situations?kinds=mission&include_done=1`, `GET /api/missions/admin` (still, for `active`/`history` rows and their steps), `Situations.cardHtml/bind`.
- Produces: `situations: []`, `groups`, `missionById(id)` (searches `active` then `history`), `cardCtx()`, `intercept(s, option)` (an `answer` verb focuses the mission's answer box instead of a prompt).

**Where every old control goes:**

| Old control | New home |
|---|---|
| Active lane cards (goal, status chip, tier · started) | cards in *Needs you* (`now`: waiting_user or a pending proposal, whatever the engine status) and *Running* (`moving`); meta carries tier · started |
| transcript | details under the card (`mission_transcript.html`, include #1) |
| answer box (waiting_user) | details, unchanged; the card's `answer` verb is intercepted to open details and focus it |
| Drop | card option `close:dropped`; details keep the old Drop button |
| History rows (goal, summary, error, finished, status chip, OK, Transcript toggle) | *History* group (`done`): cards with the summary as the note; details hold OK and the transcript toggle (include #2) |
| Launch form | unchanged, above the lane |

- [ ] **Step 1: Write the failing live test**

```python
# tests/test_missions_page_live.py
"""/missions on the situation card: a waiting mission leads with its question,
a finished mission with a pending proposal stays in Needs you, approving from
the transcript moves it to history, the launch form still launches."""
import datetime
import os
import sys
import tempfile

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='missions_page_live_'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from live_app import live_app
from services import storage

SHOTS = os.environ.get('CHF_SHOTS')


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        page.screenshot(path=os.path.join(SHOTS, name + '.png'))


def seed():
    storage.update_settings({'llm_gemini_api_key': '', 'missions_enabled': True})
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent', 'color_code': '#6366f1'})
    waiting = storage.add_mission({'goal': 'Find a plumber', 'status': 'waiting_user', 'created_by': 'mom',
                                   'tier': 'flash', 'origin_kind': 'manual', 'step_count': 1})
    storage.add_mission_step(waiting, {'kind': 'ask', 'name': 'question', 'result_json': {'question': 'What budget?'}})
    done = storage.add_mission({'goal': 'Compare pool covers', 'status': 'done', 'created_by': 'mom', 'tier': 'flash',
                                'origin_kind': 'manual', 'step_count': 3, 'summary': 'Two options found',
                                'finished_at': datetime.datetime.now().timestamp()})
    storage.add_action_proposal({'id': 'p1', 'action_type': 'add_errand', 'summary': 'Add: call Ace Pools',
                                 'payload': {'title': 'Call Ace Pools'}, 'status': 'proposed', 'requires_admin': True})
    storage.add_mission_step(done, {'kind': 'proposal', 'name': 'add_errand', 'idx': 3,
                                    'result_json': {'proposal_id': 'p1', 'status': 'proposed',
                                                    'card': {'title': 'Add: call Ace Pools'}}})
    from services import chat_actions
    chat_actions._execute = lambda a, p: {'status': 'success', 'message': 'added'}


def main():
    served = live_app(seed)
    if served is None:
        return
    try:
        b = served.browser(color_scheme='dark')
        with b as page:
            page.set_viewport_size({'width': 1300, 'height': 900})
            page.goto(served.url('work?tab=missions'), wait_until='networkidle')
            page.wait_for_selector('.situation-card')
            now = page.locator('[data-sit-group="now"] .situation-card')
            titles = now.locator('.sit-title').all_inner_texts()
            check('Find a plumber' in titles and 'Compare pool covers' in titles,
                  f"a waiting mission AND a done one with a pending proposal need you: {titles}")
            plumber = page.locator('.situation-card:has-text("Find a plumber")').first
            check(plumber.locator('.sit-next button').first.inner_text() == 'What budget?',
                  "the waiting mission leads with its question")
            plumber.locator('.sit-next button').first.click()
            page.wait_for_selector('details[open] input[placeholder="Type your answer"]')
            page.fill('details[open] input[placeholder="Type your answer"]', 'Under 500')
            page.locator('details[open] button:has-text("Send")').first.click()
            page.wait_for_timeout(800)
            steps = storage.get_mission_steps([m for m in storage.get_missions() if m['goal'] == 'Find a plumber'][0]['id'])
            check(any(s.get('name') == 'user_answer' for s in steps), "the answer went through the old box")
            # Approve the pending proposal from the transcript; the mission moves to history.
            pool = page.locator('.situation-card:has-text("Compare pool covers")').first
            pool.locator('.sit-next button').first.click()        # 'Add: call Ace Pools' (do)
            page.wait_for_timeout(1000)
            check(page.locator('[data-sit-group="done"] .situation-card:has-text("Compare pool covers")').count() == 1
                  or page.locator('[data-sit-group="done"]').inner_text().find('Compare pool covers') >= 0,
                  "once its decision is made the finished mission is history")
            # Launch still works.
            page.fill('textarea[placeholder*="What should Argyle work on"]', 'Book the dentist')
            page.locator('button:has-text("Launch")').click()
            page.wait_for_timeout(800)
            check(any(m['goal'] == 'Book the dentist' for m in storage.get_missions()), "the launch form launched")
            _shot(page, 'missions-page')
            check(not b.errors, f"script errors: {b.errors}")
    finally:
        served.stop()


if __name__ == '__main__':
    main()
    print("test_missions_page_live OK")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `env -u HA_BASE_URL ../venv/Scripts/python.exe tests/test_missions_page_live.py`
Expected: FAIL at `wait_for_selector('.situation-card')`.

- [ ] **Step 3: Rewrite lines 99–212 of `missions_page.html`**

Keep the launch card (102–118) verbatim; replace the Active and History sections with:

```html
                    <!-- The lane: one card per mission, grouped by what it
                         needs — a decision left behind counts whatever the
                         engine's status says. Details hold the transcript. -->
                    <div x-ref="lane">
                    <template x-for="g in groups" :key="g.key">
                        <div :data-sit-group="g.key">
                            <div class="text-xs font-black uppercase tracking-widest px-1 mb-2" :class="g.titleClass" x-text="g.label"></div>
                            <p class="text-xs text-gray-500 italic px-1" x-show="!g.items.length" x-text="g.empty"></p>
                            <div class="space-y-2 mb-6">
                                <template x-for="s in g.items" :key="s.id">
                                    <div>
                                        <div x-html="window.Situations.cardHtml(s, cardCtx())"></div>
                                        <template x-if="missionById(s.id)">
                                        <details class="sit-details -mt-2 bg-gray-900/60 border border-gray-800 border-t-0 rounded-b-2xl px-3 pb-3"
                                            :open="detailsOpen[s.id] ? true : null" @toggle="detailsOpen[s.id] = $event.target.open; if ($event.target.open) toggleTranscript(missionById(s.id), true)">
                                            <summary class="text-[11px] text-gray-500 cursor-pointer py-1.5">details</summary>
                                            <div x-data="{ mission: missionById(s.id) }">
                                                <div class="text-[11px] text-gray-600"
                                                    x-text="(mission.tier === 'flash' ? 'Flash' : 'Pro') + ' · started ' + fmtTs(mission.created_at) + (mission.finished_at ? ' · finished ' + fmtTs(mission.finished_at) : '')"></div>
                                                <div class="text-[11px] text-red-400 mt-0.5" x-show="mission.error" x-text="mission.error"></div>

                                                <template x-if="mission.steps">
                                                    <div>
                                                    {% include 'components/mission_transcript.html' %}
                                                    </div>
                                                </template>

                                                <!-- Answer box: only while Argyle is actually waiting on one. -->
                                                <div class="mt-2 bg-gray-800/60 border border-amber-700/40 rounded-xl p-3"
                                                    x-show="mission.status === 'waiting_user'" x-cloak>
                                                    <div class="text-xs font-semibold text-amber-300 mb-1.5"
                                                        x-text="lastAskQuestion(mission) || 'Argyle is waiting on an answer.'"></div>
                                                    <div class="flex gap-2">
                                                        <input type="text" x-model="answerText[mission.id]" :id="'mission-answer-' + mission.id"
                                                            @keydown.enter="sendAnswer(mission.id)" placeholder="Type your answer"
                                                            class="flex-1 bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm">
                                                        <button @click="sendAnswer(mission.id)" :disabled="!!busy[mission.id]"
                                                            class="shrink-0 text-xs font-bold px-3 py-2 rounded-lg bg-blue-600 text-white active:bg-blue-700 disabled:bg-gray-800 disabled:text-gray-500">Send</button>
                                                    </div>
                                                </div>

                                                <div class="flex flex-wrap gap-2 mt-2">
                                                    <button x-show="!['done', 'blocked', 'dropped'].includes(mission.status)" @click="drop(mission.id)" :disabled="!!busy[mission.id]"
                                                        class="text-xs font-bold px-3 py-1.5 rounded-lg bg-gray-800 text-gray-400 border border-gray-700 active:bg-gray-700 disabled:opacity-50">Drop</button>
                                                    <button x-show="['done', 'blocked', 'dropped'].includes(mission.status) && !mission.acknowledged_at" @click="ack(mission.id)"
                                                        class="text-xs font-bold px-2.5 py-1 rounded-lg bg-gray-700 text-gray-200 active:bg-gray-600">OK</button>
                                                </div>
                                            </div>
                                        </details>
                                        </template>
                                    </div>
                                </template>
                            </div>
                        </div>
                    </template>
                    </div>
```

`mission_transcript.html` is now included once in this file; the contract in `test_missions_endpoints` demands exactly two includes. Keep the second by leaving the history transcript include inside a second, history-only template branch: wrap the details body so that for `g.key === 'done'` the transcript renders through a second `{% include 'components/mission_transcript.html' %}` inside `<template x-if="g.key === 'done' && mission.steps">` and the first include is inside `<template x-if="g.key !== 'done' && mission.steps">`. Both branches bind the same `mission`.

- [ ] **Step 4: Alpine additions** (inside `missionsSettings()`)

Fields: `situations: [], detailsOpen: {},`. In `loadAdmin()`, after `this.history = d.history || [];` add:

```javascript
                        const r2 = await fetch(this.apiBase + 'api/situations?kinds=mission&include_done=1');
                        const d2 = r2.ok ? await r2.json() : { situations: [] };
                        this.situations = d2.situations || [];
                        this.$nextTick(() => window.Situations.bind(this.$refs.lane, this.cardCtx()));
```

Methods:

```javascript
                get groups() {
                    const by = (g) => this.situations.filter(s => s.group === g);
                    return [
                        { key: 'now', label: '✋ Needs you', titleClass: 'text-amber-400', items: by('now'), empty: 'No decisions waiting.' },
                        { key: 'moving', label: 'Running', titleClass: 'text-violet-400', items: by('moving').concat(by('in_hand')), empty: 'Nothing running right now.' },
                        { key: 'done', label: 'History', titleClass: 'text-gray-500', items: by('done'), empty: 'Nothing finished yet.' },
                    ];
                },
                missionById(id) { return this.active.find(m => m.id === id) || this.history.find(m => m.id === id) || null; },
                sitById(id) { return this.situations.find(s => s.id === id) || null; },
                cardCtx() {
                    return { apiBase: this.apiBase, canWrite: true, readOnly: false,
                             lookup: (kind, id) => this.sitById(id), onChange: () => this.loadAdmin(),
                             intercept: (s, option) => this.intercept(s, option) };
                },
                // The card's answer verb opens the mission's own box; a prompt
                // would hide the question the box shows beside it.
                intercept(s, option) {
                    if (option.verb !== 'answer') return false;
                    this.detailsOpen[s.id] = true;
                    this.$nextTick(() => { const el = document.getElementById('mission-answer-' + s.id); if (el) el.focus(); });
                    return true;
                },
```

Change `toggleTranscript(m, keepOpen)` so a second argument `true` loads the steps without closing: replace its first line with `if (m._open && !keepOpen) { m._open = false; return; }`. (`history` rows arrive without steps; `active` rows arrive with them.)

- [ ] **Step 5: Tailwind, then the tests**

Run the Tailwind build + test, `tests/test_missions_page_live.py` → OK, then `tools/test.py missions_endpoints missions settings_drawer_live` → all pass (the markup contracts: `/api/missions/admin`, `/api/missions/launch`, `waiting_user`, `toggleTranscript`, two transcript includes, no dialogs).

- [ ] **Step 6: Commit**

Bump to `2.499.317`.
```bash
git add chauffeur/config.yaml chauffeur/templates/components/missions_page.html chauffeur/static/tailwind.css chauffeur/static/tailwind-app.css chauffeur/tests/test_missions_page_live.py
git commit -m "feat(missions): the page is the lane - a decision left behind keeps a finished mission in Needs you; transcript and answer box in details (v2.499.317)" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push origin main
```

---

### Task 4: PWA House threads on the card; `owner=` on the situations list

**Files:**
- Modify: `main.py` `situations_list` (add `owner: str = None`), `services/situations.py` `list_situations(viewer, kinds, include_done, owner=None)`
- Modify: `templates/app.html` `fetchHouseThreads`/`renderHouseThreads` (lines ~6282–6334); `houseAddThreadNote` stays
- Test: `tests/test_situation_endpoints.py` (append), `tests/test_situations_lane_live.py` (append a House section)

**Interfaces:**
- `list_situations(..., owner=None)`: when set, threads are filtered to `row.owner_member_id == owner` (other kinds unaffected).
- `GET /api/situations?kinds=thread&owner=<member_id>`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_situation_endpoints.py`:

```python
def scenario_owner_filter_and_child_view():
    fid, iid = _reset()
    import main
    from services import threads
    storage.add_member({'id': 'teen', 'name': 'Sam', 'role': 'child', 'is_child': True})
    mine = threads.create('Science fair form', owner_member_id='teen', next_action='ask Ms Lee', created_by='mom')
    theirs = threads.create('Deck permit', owner_member_id='mom', next_action='call', created_by='mom')
    _as('teen')
    rows = main.situations_list(kinds='thread', owner='teen', request=_Req('teen'))['situations']
    check([r['id'] for r in rows] == [mine], f"a child sees their own thread, and only theirs: {[r['id'] for r in rows]}")
    _as('mom')
    rows = main.situations_list(kinds='thread', owner='teen', request=_Req('mom'))['situations']
    check([r['id'] for r in rows] == [mine], "owner= narrows a parent's view the same way")
    rows = main.situations_list(kinds='thread', request=_Req('mom'))['situations']
    check({r['id'] for r in rows} == {mine, theirs}, "no owner= means every thread for a parent")


SCENARIOS += [scenario_owner_filter_and_child_view]
```

Append to `tests/test_situations_lane_live.py`'s PWA section (after the `nxt.startswith('Plan:')` check), a House-tab probe using the same stand-in approach:

```python
            page.evaluate("() => { document.body.insertAdjacentHTML('beforeend', '<div id=\\"house-threads\\"></div>'); }")
            page.evaluate("async () => { await fetchHouseThreads(); }")
            page.wait_for_selector('#house-threads .situation-card', timeout=15000)
            check('Deck permit' in page.locator('#house-threads .sit-title').first.inner_text(), "the House tab draws the parent's thread as a card")
            check(page.locator('#house-threads form input[id^="house-thread-note-"]').count() == 1, "the note form rides inside the card")
```

and to its `seed()`: `from services import threads; threads.create('Deck permit', owner_member_id='mom', next_action='call county', created_by='mom')`.

- [ ] **Step 2: Run to verify failure**

`tests/test_situation_endpoints.py` → `TypeError: situations_list() got an unexpected keyword argument 'owner'`; the live test fails at `#house-threads .situation-card`.

- [ ] **Step 3: Implement**

`services/situations.py`:

```python
def list_situations(viewer: Optional[dict], kinds=None, include_done: bool = False,
                    owner: str = None) -> list:
    out = []
    for kind in (kinds or KINDS):
        for k, sid in _rows_of(kind, include_done):
            row = load(k, sid)
            if not row or not can_see(k, row, viewer):
                continue
            if owner and k == 'thread' and row.get('owner_member_id') != owner:
                continue
            s = view(k, sid, viewer)
            if s and (include_done or s['group'] != 'done'):
                out.append(s)
    return rank(out)
```

`main.py`:

```python
@app.get("/api/situations")
def situations_list(kinds: str = None, include_done: int = 0, owner: str = None, request: Request = None):
    from services import situations as _sit
    want = tuple(k for k in (kinds or '').split(',') if k in _sit.KINDS) or None
    return {"situations": _sit.list_situations(_situation_viewer(request), kinds=want,
                                               include_done=bool(include_done), owner=owner or None)}
```

`templates/app.html`: replace `fetchHouseThreads` and `renderHouseThreads` with:

```javascript
        let houseThreadSituations = [];
        async function fetchHouseThreads() {
            if (!selectedMemberId) return;
            try {
                const r = await fetch(`${apiBase}api/situations?kinds=thread&owner=${encodeURIComponent(selectedMemberId)}`);
                const d = r.ok ? await r.json() : { situations: [] };
                houseThreadSituations = d.situations || [];
            } catch (e) { houseThreadSituations = []; }
            houseThreads = houseThreadSituations;      // the anchors count them
            renderHouseAnchors();
            renderHouseThreads();
        }

        function renderHouseThreads() {
            const wrap = document.getElementById('house-threads');
            if (!wrap) return;
            if (!houseThreadSituations.length || !window.Situations) { wrap.innerHTML = ''; return; }
            // POST /api/threads/{id}/note is parent/adult-only server-side
            // (_mind_actor); the form is drawn only for them.
            const canNote = ['parent', 'adult'].includes(currentMemberRole());
            wrap.innerHTML = '<div class="text-xs font-black uppercase tracking-widest text-gray-500 pt-2">🧵 Threads</div><div id="house-threads-lane" class="space-y-2"></div>';
            window.Situations.render(document.getElementById('house-threads-lane'), houseThreadSituations, {
                apiBase, canWrite: canNote, readOnly: false, memberId: selectedMemberId, onChange: fetchHouseThreads,
                extraHtml: (s) => canNote ? `<form onsubmit="houseAddThreadNote(event, '${s.id}')" class="flex gap-2 mt-2.5">
                        <input type="text" id="house-thread-note-${s.id}" placeholder="A call made, a document received…" autocomplete="off"
                            class="flex-1 bg-gray-950 border border-gray-700 rounded-xl px-3 py-2 text-[13px] text-gray-100 placeholder-gray-600">
                        <button type="submit" class="px-3 rounded-xl bg-gray-800 border border-gray-700 text-gray-300 text-xs font-bold active:bg-gray-700 shrink-0">Add note</button>
                    </form>` : '' });
        }
```

`houseThreadDate` can go if nothing else calls it (grep first).

- [ ] **Step 4: Run the tests**

`tests/test_situation_endpoints.py` → all pass; `tests/test_situations_lane_live.py` → OK; `tools/test.py threads household_features_live` → pass.

- [ ] **Step 5: Commit**

Bump to `2.499.318`.
```bash
git add chauffeur/config.yaml chauffeur/main.py chauffeur/services/situations.py chauffeur/templates/app.html chauffeur/tests/test_situation_endpoints.py chauffeur/tests/test_situations_lane_live.py
git commit -m "feat(situations): owner= on the list; the PWA House tab draws its threads with the card (v2.499.318)" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push origin main
```

---

### Task 5: The DM heads-up clause

**Files:**
- Modify: `services/watchers.py` `run_watchers` (the `body = …` lines ~897–898)
- Test: `tests/test_watchers.py` (append)

**Interfaces:**
- New helper `watchers._heads_up_line(f) -> str`: the finding's line, plus ` → {next step label}` when the situation has one that is not `own`/`dismiss`, plus ` (asked {name} by {channel}, {state})` for each open or answered ask. Falls back to the line alone when no record/situation exists.

- [ ] **Step 1: Write the failing tests**

```python
def scenario_heads_up_names_the_next_step_and_the_asks():
    _reset()
    from services import asks
    soon = (NOON + datetime.timedelta(days=1)).replace(hour=16)
    storage.set_cached_schedule({"events": [{"id": "ev1", "title": "Soccer", "start": soon.isoformat(),
                                             "end": (soon + datetime.timedelta(hours=1)).isoformat()}],
                                 "assignments": {}, "unassigned": ["ev1"]})
    storage.add_assist_contact({'id': 'c1', 'name': 'Sarah', 'kinds': ['driving'], 'active': True})
    n, posts = _run()
    body = _bodies(posts)[0]
    check('→ Assign' in body or '→ Ask' in body, f"the heads-up says the next step: {body}")
    fid = storage.get_findings(state='open')[0]['id']
    a = asks.create('finding', fid, {'name': 'Mike'}, 'drive Soccer', 'text', 'mom')['ask']
    asks.mark_sent(a['id'], {'id': 'mom', 'role': 'parent'})
    asks.answer(a['id'], 'no', {'id': 'mom', 'role': 'parent'}, reported=True)
    storage.set_app_state('watcher_notified', {})     # let it notify again
    n, posts = _run(now=NOON + datetime.timedelta(hours=2))
    body = _bodies(posts)[0]
    check('asked Mike by text, said no' in body, f"the heads-up carries the asks so far: {body}")


def scenario_heads_up_clause_survives_a_missing_record():
    _reset()
    from services import watchers as _w, findings as _f
    f = _f.Finding(key='x:1', line='🚨 Something', kind='unassigned', subject_type='event', subject_id='nope')
    check(_w._heads_up_line(f) == '🚨 Something', "no record, no situation: the line alone")


SCENARIOS += [scenario_heads_up_names_the_next_step_and_the_asks, scenario_heads_up_clause_survives_a_missing_record]
```

(Place the `SCENARIOS += […]` after the existing `SCENARIOS = […]` list.)

- [ ] **Step 2: Run to verify failure**

`tests/test_watchers.py` → `AttributeError: module 'services.watchers' has no attribute '_heads_up_line'`.

- [ ] **Step 3: Implement**

In `services/watchers.py`, before `run_watchers`:

```python
def _heads_up_line(f) -> str:
    """The DM's line for one finding: what it is, then what to do about it
    and who has already been asked (spec 2026-10-09-situations-design §3).
    Reads the situation the sweep just reconciled; with no record yet (or
    anything odd) it is the line alone, never a crash in the sweep."""
    try:
        from services import situations as _sit
        row = storage.get_finding_by_identity(_findings.identity(f))
        if not row:
            return f.line
        s = _sit.view('finding', row['id'], {'role': 'parent'})
        if not s:
            return f.line
        out = f.line
        nxt = s.get('next_step') or {}
        if nxt.get('verb') not in (None, 'own', 'dismiss', 'snooze'):
            out += f" → {nxt.get('label')}"
        said = {'sent': 'waiting', 'drafted': 'not sent yet', 'yes': 'said yes', 'no': 'said no'}
        asks = [a for a in (s.get('asks') or []) if a.get('state') in said]
        if asks:
            out += ' (' + '; '.join(f"asked {a.get('to_name')} by {a.get('channel')}, {said[a['state']]}"
                                    for a in asks[-3:]) + ')'
        return out
    except Exception as e:
        print(f"[watchers] heads-up clause failed: {e}")
        return f.line
```

And change the body build to:

```python
    body = "👋 Heads-up — needs a look:\n" + "\n".join(f"• {_heads_up_line(f)}" for f in fresh)
```

- [ ] **Step 4: Run the tests**

`tests/test_watchers.py` → all pass; `tools/test.py watchers negotiation_watcher situations` → pass. The clause's `view` call runs the coverage ladder once more per fresh unassigned finding; the sweep already ran it, and `fresh` is at most a handful, so this stays zero-LLM and cheap.

- [ ] **Step 5: Commit**

Bump to `2.499.319`.
```bash
git add chauffeur/config.yaml chauffeur/services/watchers.py chauffeur/tests/test_watchers.py
git commit -m "feat(watchers): the heads-up says the next step and who was already asked (v2.499.319)" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push origin main
```

---

### Task 6: Clean-up, docs, gate

**Files:**
- Modify: `templates/components/mind_page.html` (delete the dead `dismiss/act/snooze/plan/stepDo/clearIt/snoozedLabel` methods and the `busy/noMove/snoozeOpen` fields left from build 1, after grepping that nothing references them), `services/mind.py` (the revive branch clears `sit_owner_member_id`, `sit_owned_at`, `next_steps`, `status_note` — deferred minor M5)
- Test: `tests/test_mind_think.py` (append one scenario for M5)
- Docs: `chauffeur/system_capabilities.md` (entry + "Current through"), `chauffeur/docs/roadmap.md` (one line), memory `agentic-layer-field-feedback.md` (build 2 shipped)

- [ ] **Step 1: The M5 test**

```python
def scenario_a_revived_insight_is_nobody_s_and_has_no_stale_note():
    _reset()
    mind._pool_call = _fake_pool([{'slug': 'r', 'line': 'back', 'category': 'c', 'refs': ['#x']}])
    mind.deep_think(NOON)
    row = storage.get_mind_insights(state='active')[0]
    storage.update_mind_insight(row['id'], {'state': 'retired', 'outcome': 'expired', 'resolved_ts': time.time(),
                                            'sit_owner_member_id': 'mom', 'sit_owned_at': time.time(),
                                            'next_steps': [{'id': 'advance:argyle:0', 'verb': 'advance', 'label': 'x', 'payload': {}}],
                                            'status_note': 'old words', 'note_source': 'argyle'})
    mind._pool_call = _fake_pool([{'slug': 'r', 'line': 'back again', 'category': 'c', 'refs': ['#x']}])
    mind.deep_think(NOON, force=True)
    row = storage.get_mind_insight(row['id'])
    check(row['state'] == 'active' and not row.get('sit_owner_member_id') and not row.get('next_steps')
          and row.get('note_source') != 'argyle', f"a revived insight starts with nothing attached: {row}")
```

Register it in the `__main__` call list.

- [ ] **Step 2: Run to verify failure, then implement**

In `services/mind.py`'s revive update add `'sit_owner_member_id': None, 'sit_owned_at': None, 'next_steps': [], 'status_note': '', 'note_source': 'fallback', 'note_rev': None,` to the field dict. Run `tests/test_mind_think.py` → all pass.

- [ ] **Step 3: Dead code**

In `mind_page.html`, grep each of `dismiss(`, `act(`, `snooze(`, `plan(`, `stepDo(`, `clearIt(`, `snoozedLabel(`, `busy[`, `noMove[`, `snoozeOpen[` — delete the methods and fields no template expression references (the history section uses `fmtTs`, `outcomeChipClass`; `graduate()` stays). Run `tests/test_mind_endpoints.py` (its `scenario_admin_template_boolean_bindings_are_coerced` reads the template) and `tests/test_situations_lane_live.py`.

- [ ] **Step 4: The gate**

`env -u HA_BASE_URL ../venv/Scripts/python.exe tools/test.py situation threads missions watchers mind_endpoints mind_think tailwind_build household_features_live settings_drawer_live` → all pass; plus `tests/test_threads_page_live.py`, `tests/test_missions_page_live.py`, `tests/test_situations_builder_live.py`, `tests/test_situations_lane_live.py` → OK each.

- [ ] **Step 5: Docs and commit**

`system_capabilities.md`: bump "Current through" and add the build-2 entry in house style (the two pages on the card with the old controls' new homes, `Situations.bind/intercept/extraHtml`, `owner=`, the House tab, the DM clause, the revive clean-up, the removed dead code). `docs/roadmap.md`: one line under the Needs-you entry. Memory: build 2 shipped, NOT device-verified; sub-project 3 next.

Bump to `2.499.320`.
```bash
git add chauffeur/config.yaml chauffeur/templates/components/mind_page.html chauffeur/services/mind.py chauffeur/tests/test_mind_think.py chauffeur/system_capabilities.md chauffeur/docs/roadmap.md
git commit -m "chore(situations): build 2 wrap-up - revived insights start clean, dead Mind-page helpers removed, capabilities and roadmap (v2.499.320)" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push origin main
```
