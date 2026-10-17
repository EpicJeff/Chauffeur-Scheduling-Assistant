# The project access rule — design

**Status:**
- Design approved section by section by the user on 2026-10-16.
- Codex adversarial review (13 findings, six blockers) folded in, revision 2, together with three user rulings on capabilities (§10).
- Awaiting the user's review of this written spec.

**Follows:** Projects front door slice 2 (v2.499.520), which shipped with the rule backed out.

**Background:**
- Core spec §5 (`2026-10-15-projects-core-design.md`) said a project's audience governs its pieces.
- Slice 2 made it possible to put any thread, mission or program inside a private project.
- Three patch rounds followed: c697645e, 5724de1e, and branch `privacy-round3-wip`. Each fixed the spots a review named and broke others.

This spec decides every case once.

## 1. The promise

A thread, mission or program whose home project is **private** or **parents** is seen only by:
- the project's audience;
- the record's own person;
- when that person is a child, the child's active parents.

That holds everywhere:
- pages and by-id links;
- Argyle on every surface and in every channel;
- voice;
- the wall and other shared screens;
- the calendar and everything derived from it: commitments, the digest, pushes;
- the Mind, findings and every nudge.

Shared screens and the Mind treat the record as not there, and its calendar time reads "Busy".

The user's choice on 2026-10-16 was "Full secrecy". The rejected options were "hidden from people, house keeps it" and "card-only, labelled".

**Today's model, which this layers on and does not replace.** Each record kind has its own rule.
- **Threads and missions** are open to parents and adults (`situations._can_see_base`, `WRITE_ROLES`).
  - They are narrowed by their subjects (`subjects.subject_records`): a private occasion, a parents-only trip, a project named as subject, or a live mission's proposed project.
  - The record's owner is exempt for the row itself (`situations.can_see`).
- **Programs** are open to parents and adults, and otherwise only to their own member (`subjects._program_visible`, `_program_scope_id`).
- **A project's own visibility** is `projects.can_see`:
  - the owner always sees it;
  - `household`: every active member;
  - `parents`: the owner plus active parents;
  - `private`: the owner, plus active parents when the owner is a child;
  - a wrapper project also needs its record to be visible now.

**Why the patch rounds failed.** The rule itself was not the problem. Three gaps sat under it:
1. **Weak readers.** About twenty readers check only the viewer's role, or nothing at all.
2. **No-person readers.** Readers with no person (wall, speaker, Mind, registry, a mission's own reads) passed `viewer=None`, which had no defined meaning against `projects.can_see`.
3. **Two identities confused.** "The record's own person" was confused with "a parent of a child owner".

Codex's review of revision 1 added four more:
1. Membership was ambiguous: a project's `pieces` list could link a record whose home was elsewhere.
2. A channel was authorised per row, not per projection.
3. Nested subjects bypassed the rule.
4. Words copied out of a record (calendar payloads, commitments, findings, conversation history) were not covered.

## 2. Terms

- **Home project (P).**
  - P is `storage.get_project(row['project_id'])`. `project_id` is the only membership for threads, missions and programs. Every such record has one (slice 1 invariant).
  - A wrapper project (`wrapped_from` set) is not restricting. Its visibility already defers to the record (`projects._wrapped_visible`).
  - A missing project means no P.
  - A project's `pieces` list no longer LINKS threads, missions or programs from other projects (§10.1). It still holds the native entries `projects.adopt` writes for its own records (they drive its cards), and links to other kinds (trips, occasions, lists and the rest); none of these entries changes who sees anything - `project_id` alone does. (Corrected during the build, 2026-10-16.)
- **Restricted.** P exists, is not a wrapper, and `P['audience'] in ('private', 'parents')`.
- **Keeper.** The record's own person: thread `owner_member_id`, mission `created_by`, program `member_id`.
  - The id must be non-empty and the member active (`projects._active`).
  - An empty owner never matches an empty viewer id. This closes round 3's M1 (`None == None`).
- **Keeper's parents.** When the keeper is a child (`projects._child`), the keeper's parents are the active parents (`role == 'parent'`, not a child, `_active`). They count **only** in the project layer (§3), never in subject audiences (round 3's I1).
- **HOUSE.** `access.HOUSE = {'id': None, 'role': 'adult', 'house': True}`.
  - It is used by every reader that has no person: the wall and panels, voice satellites, the Mind snapshot, registry reads with no actor, and a mission's generic reads.
  - `access.HOUSE_PARENT` (`role: 'parent'`) is the existing parents-only variant that `missions.read_viewer` returns for a transcript whose subjects are parents-only.
  - Nothing passes `None` as a viewer any more.
- **`access.project_visible(P, viewer)`** wraps `projects.can_see` and gives HOUSE and HOUSE_PARENT a meaning:
  - a non-wrapper project is visible to them only when its audience is `household`;
  - a wrapper is visible when its record is visible to them.
  - For a person it is `projects.can_see`, unchanged.
  - Every check in this spec that asks about a project uses it. This fixes Codex #8: an owned thread whose subject is a household project used to fail for HOUSE before the project layer ever ran.

## 3. The rule

`access.record_view(kind, row, viewer)` returns `'full'`, `'keeper'` or `None`. `access.record_visible` is `record_view(...) is not None`.

**The call graph is acyclic** (Codex #3). The pieces:
1. **Primitive base**, per kind, with no traversal: the role and scope checks only.
   - Thread: `WRITE_ROLES`, or the viewer is the keeper.
   - Mission: `WRITE_ROLES`.
   - Program: `_program_scope_id` is None, or the viewer is the member.
   - These are new functions in `access`. They never call `subjects.visible`, `situations.can_see` or `record_visible`.
2. **Subject traversal**, over `subjects.subject_records(kind, row)` minus the home project if it also appears as a subject:
   - a subject that is a **thread** is checked with `record_visible`, recursively. A `visited` set guards against cycles, and a revisit counts as not visible. A thread whose subject is a private-project thread is therefore hidden from whoever cannot see that thread (Codex #3).
   - a subject that is a **project** or **proposed project** is checked with `project_visible`.
   - every other subject kind is checked with its adapter's own `visible`. Adapters for non-piece kinds never call back into `access`.
3. **Project layer**, true when any of:
   1. there is no restricted P;
   2. the viewer is the keeper;
   3. the viewer is an active parent of a child keeper;
   4. `project_visible(P, viewer)`.

   HOUSE and HOUSE_PARENT pass only through (1).
4. **Wrapper re-entry.** `projects._wrapped_visible` calls `access.record_visible` on its record under the existing `_GATE` re-entry guard, and never the other way round.

**Composition.**
- A viewer passes when the primitive base passes, every subject passes, and the project layer passes.
- **The keeper's exemption:** a keeper whose subject traversal or project layer would fail through anything other than case (2) still gets `'keeper'`. Their own row stays theirs, as `situations.can_see` does today.
- Anyone else who fails any part gets `None`.

**A home project that is also a subject** (a planning mission's subject is its project, `main.py` `POST /api/projects/{id}/plan`) is checked once, by the project layer. The child-keeper exception therefore holds for it. Every other subject still binds.

**What `'keeper'` shows** (Codex #12):
- **Mission:** the existing keeper projection (`planned.keeper_view`, and the keeper branch of `situations.view`). That is metadata plus the keeper's own options: OK, Delete, steer. No transcript, no plan words, no cached status note.
- **Thread:** the existing thread keeper redaction in `situations.view`. No cached notes or suggestions, and mission history reduced to timestamps.
- **Program:** the whole program. It is their own practice, and they need its lessons. They do not see the project card. A program's `'keeper'` therefore renders like `'full'`.

**Callers that depend on this:**
- `planned.is_keeper(mission, viewer)` becomes `record_view == 'keeper'`.
- The thread keeper test in `situations.view` uses the same call.

**Acting.** `access.record_actable(kind, row, viewer, verb)` is true when:
- `record_view` is not None;
- the action's existing role check passes;
- when the view is `'keeper'`, the verb is one of the keeper's options (the existing `situations.view` filter).

**Kinds are registered** with `access.register(kind, keeper_field, primitive_base, keeper_projection)`, so trips, occasions and lists can become homes later without touching the rule. This slice registers thread, mission and program.

## 4. Surfaces

Every reader belongs to exactly one class. "Hidden" means, per class:
- a 404 shaped like a missing record. Never a 403, so existence is never disclosed.
- the row dropped from a list or a search.
- Argyle answering as if nothing matched.
- "Busy" on calendar surfaces.
- no finding and no DM.

**Authentication comes first** (Codex's correction to revision 1).
- SIGNED_IN routes already refuse a caller with no Chauffeur sign-in (401) before the handler runs. A tokenless HA ingress admin is refused at the door, not shown a filtered page.
- HOUSE applies only to routes and readers that admit an identity-free caller: the WALL, DEVICE and SERVICE tiers, and internal readers.
- Inside a SIGNED_IN handler, a code path that still resolves no person (for example `_situation_viewer`'s `parent_of_record` stand-in) uses HOUSE instead.

### 4.1 Signed-in pages and by-id routes (read and act)

- These use `record_view` / `record_actable` with the signed-in person. Lists and search filter their rows.
- This covers every route in Appendix A class 1.
- `GET /api/threads` checks every row, not only rows that have a subject. Today a signed-in child receives every unbound thread; that is pre-existing, and it is fixed here because the primitive base says otherwise.
- The program actions on DM approve cards (`chat_actions` `log_program_session` and `reshape_program`) use `record_actable` for the approver, not `requires_admin` alone.

### 4.2 Conversations belong to their surface (user ruling, §10.2)

Every Argyle conversation is tied to the surface it happens on, and its audience is that surface's audience. A conversation record gains `surface = {'kind': …, 'owner': …}`:

| surface | owner | Argyle reads as | who may list and read its history |
|---|---|---|---|
| `admin`: the admin pages' widget (`control_center.html` on an admin page) | the signed-in person | that person | that person |
| `panel`: the same widget on a wall panel (`?panel=true`) | the enrolled panel device | HOUSE | that panel, and parents |
| `satellite`: a voice satellite session | the satellite | HOUSE (spoken) | parents (today's voice rule) |
| Argyle DM / group channel | the channel | §4.3 | the channel's members (unchanged) |

- **The phone has no conversation of its own.** In the PWA, the only way to talk to Argyle is the person's Argyle DM, which is already per person (the channel row of the table above). `app.html` still carries a floating Argyle button and popup wired to the shared `general` conversation (`loadChatHistory`), but CSS hides the button for every adult (`pwa_shell.css:131`) and every child in the child shell (`pwa_child_shell.css:13`). The plan confirms that no audience reaches it, then removes the popup and its `general` wiring as dead UI. Removing it takes nothing a person can do today.
- **Today, admin pages and panels share code but not a conversation.** Both use `control_center.html`, and each browser invents its own conversation id in localStorage. The server records no owner or surface, so anyone who knows an id can read its history.
- **Choosing a conversation.** A client no longer invents an unowned id. It asks the server for "my conversation on this surface", and the server creates it with the owner set.
- **History.** `GET /api/chat/history` and `GET /api/chat/conversations` return only conversations whose owner matches the caller: the person, or the device token for a panel. Satellite sessions keep their parent-only rule.
- **Prompt history.** Only the conversation's own history ever goes into a prompt. That is already true; it is now also guaranteed by ownership.
- **Legacy conversations** (no `surface`, including the old shared `general` one) become read-only history listed to parents only. Argyle never answers into them again.
- **Messages already said are not rewritten** when access later narrows. A sentence posted before a project became private stays in that conversation's history, and the spec does not scrub it (stated limit).
- **Live cards** in any conversation or channel (approve buttons, situation options) re-check `record_actable` for the person tapping them when they act. When the channel's audience no longer passes, the card renders "No longer available here".

### 4.3 Argyle in a group channel (Codex #2 and #7)

`access.channel_view(kind, row, focus_key)` returns the projection every human in the channel may receive. It has two branches:
- **No restricted P:** today's channel rule, unchanged (`situations.channel_visible`: every human may read its subjects), returning `'full'`. The family channel keeps everything it has today. Nothing is taken away.
- **Restricted P:** every human must get a non-None `record_view`.
  - The projection delivered is the narrowest any of them gets: `'keeper'` when any recipient gets only `'keeper'`, otherwise `'full'`.
  - Tools, FOCUS and ABOUT injection all render at that projection, whichever member is speaking. In a Mom+Aunt channel, Mom asking about Aunt's mission in Mom's private project gets Aunt's keeper projection, not Mom's full view.
- **Title matching** (`_match_thread`, `_match_program`, `launch_mission(thread_title=…)`, and the "already under way" check in `start_mission_for`) searches only records the speaker may see in that channel.
  - When nothing visible matches, the old fallback stands: a plain mission with no thread (round 3's M5).
  - A hidden title is never named.

### 4.4 A mission's own reads (the engine)

`access.mission_reader(mission)` reads:
- what `missions.read_viewer` reads today (HOUSE or HOUSE_PARENT);
- **plus** the pieces whose `project_id` is the mission's own `project_id`;
- **plus** the mission's own origin thread (`origin_ref` of a thread-origin mission, round 3's I6).

It never reads the creator's other private records: those would leak into a transcript that a wider audience can read. `missions._finder` (subject context authorised as the creator) is unchanged for the subject itself and does not widen to other records. Registry calls with no actor (`_REGISTRY_READER`) are HOUSE, and `_registry_parent` writes are HOUSE_PARENT.

### 4.5 Voice

- Voice reads as HOUSE plus `spoken_safe`. A speaker has a room around it, whoever asked.
- A voice approval of an ask on a restricted record is refused aloud and changes nothing: "That one's private — open it on your phone."
- `voice_approval` uses `record_visible(…, HOUSE)` for the spoken check.

### 4.6 Shared screens

These are: the wall and panels, House, the Study board and binders, board tiles, lesson scenes and lesson help, the practice session, celebrations, and the home-board and House attention counts.

- `access.shared_screen_visible(kind, row, viewer)` is `record_visible(kind, row, HOUSE)`, or, when the viewer is a person, `record_visible(kind, row, viewer)`.
- A signed-in child never sees less than the anonymous wall (round 3's I4), and a restricted piece is absent for HOUSE.
- Counts follow the same rule.
- Study is a signed-in admin page: there it is §4.1 with the signed-in person; on a panel it is this class.

### 4.7 Calendar, practice windows and everything emitted from a program (Codex #4, #5, #9)

**Neutral payload.** A restricted program's practice window, as shown to a viewer who fails `record_visible`, contains only these fields:
- event id, start, end, all-day flag;
- `member_id` and the cached colour (who is busy is structural, the same as for project holds);
- `kind: 'practice'`;
- title "Busy".

Every other field is absent: description, `practice.phase_name`, `unit_title`, `unit_url`, `unit_body`, `session_label`, `steps`, `progression`, `milestone`, and `program_id`.

**Redaction at consumption, not at caching.**
- The schedule cache keeps the full words.
- Every reader of a schedule cache goes through `access.schedule_view(blob, viewer)`, which applies the current audience row by row. That covers `/api/schedule`, `/api/practice-windows`, `/api/packing/day` (`family_day`), Argyle's calendar tools (`agent_tools_v2` readers of `get_cached_schedule`), the Mind, and `family_digest`.
- A project's audience change therefore takes effect on the next read, with no invalidation. Caches written before this feature are covered on rollout with no scrub.
- For a viewer who passes, every presentation field comes back, and the cached colour is kept.
- Program and project lookups are batched once per call, not per event (round 3's I5).

**Commitments.**
- Program-emitted protected commitments (`programs.py` emission loop → `storage.add_protected_commitment`) gain `source = {'kind': 'program', 'id': …}`.
- `GET /api/commitments` and every other reader show their title as "Busy" to a viewer who fails `record_visible` on the source.
- The solver reads them raw (INTERNAL).
- A migration backfills `source` from each program's `emissions.commitment_ids`.

**Target dates write no calendar event** (user ruling, §10.3).
- Program approval stops creating a Google Calendar event for `baseline.target_date`. The target date lives on the program only.
- A migration deletes the existing target events the app created, from `baseline.target_event_id` and `emissions.event_ids`, through the same calendar delete path `release_commitments` uses, and clears those ids.
- `programs.footprint` and `maybe_rebaseline` stop mentioning or re-creating a target event.

**Practice pushes.** `programs.due_practice_pushes`, which goes to the owner's driver, carries the program's words only when the recipient passes `record_visible`. Otherwise the push is a neutral "Practice time".

### 4.8 Signals: watchers, findings, the Mind, DMs (Codex #10)

- The Mind snapshot reads as HOUSE.
- **A finding derives its audience from its source.** A finding whose source reference is a thread, mission or program is shown only to a viewer for whom `record_visible(source)` passes now. This applies at read time to open and historical findings alike: `GET /api/findings`, the `list_open_findings` tool, the Mind snapshot's findings section, and `mind._gather_deltas`. Findings that existed before this feature are covered with no rewrite.
- **A record inside a restricted P never makes a new household Finding.**
  - A signal that would have sent a DM under the household path is sent privately instead: to the keeper; for a `parents` P, to the parents who pass `record_visible`; for a child keeper, to the child and to their parents, as the household path would. The `watcher_notified` dedupe is the same.
  - Signals that never send a DM on the household path (a quiet thread stall, mission done, mission blocked) are dropped for restricted records (round 3's M3, the watcher signal policy).
  - An item with no eligible recipient ages out; `at` is not refreshed on every sweep.
- **A record restricted only by its subject** (an occasion, a trip) keeps today's household Finding path unchanged (round 3's I3).
- Program drift and rebaseline findings follow the same rule.
- **Who gets a DM:**
  - `missions._dm_person`: a mission with no creator sends a DM only to the parents who pass `record_visible`.
  - `replies._recipients` and `replies.flush_pending_dms` follow the same rule for a restricted thread.
- The household briefing (`family_digest.build_household_briefing`) reads through `schedule_view(…, HOUSE)`, and it never lists a neutral window or a hold as an uncovered event.
- Aggregate counts that name nothing (`vitals.measure_day`) stay INTERNAL.

**Internal readers stay raw:**
- the solver, migrations and `projects.adopt`;
- storage itself;
- any job that acts for everyone and shows nothing.

They are listed in the register as INTERNAL so the decision is visible.

## 5. Where it lives

**`services/access.py`** (new) holds:
- the kind table and `register`, with the primitive bases;
- `HOUSE` and `HOUSE_PARENT`;
- `project_visible`;
- `home_project(row)`;
- `keeper_of(kind, row)`;
- `record_view`, `record_visible`, `record_actable`;
- `channel_view`;
- `mission_reader`;
- `shared_screen_visible`;
- `schedule_view`;
- `READERS`.

**Caching (Codex #13).** One request-scoped cache (a `contextvars.ContextVar` set by a middleware and cleared after the response; outside a request it reads straight through) serves:
- project lookups, for both `home_project` and the project and proposed-project subjects that `subjects.load` resolves (the project adapter today scans every project per load);
- the member lookups for keepers and parents.

Visibility is decided from row metadata before any mission steps are loaded. `situations.list_situations` stops loading each mission twice. The matrix test asserts the number of storage calls for `GET /api/situations`, `GET /api/projects` and `GET /api/schedule` against the fixture.

**Existing helpers become thin calls into it**, and their callers stay unchanged where possible:
- `situations.can_see` (thread and mission branch);
- `situations.channel_visible` (records);
- `missions.read_viewer` and the engine's thread matching;
- `subjects.visible`'s thread and program branches for person viewers;
- `planned.is_keeper`;
- the thread keeper test in `situations.view`.

The ad-hoc copies the backed-out rounds added do not come back.

**`READERS`** is a table shaped like `auth.RULES` (Codex #11).
- **Every** FastAPI route and **every** Argyle registry tool gets a row: `(id, surface_class, kinds, check)`.
- `id` is one of `('route', METHOD, path_template)`, `('tool', name)` or `('reader', 'module.function')`.
- `surface_class` is one of the classes in §4, `INTERNAL`, or `NONE`. `NONE` means the reader shows no piece's words. Rows may be grouped by prefix, but every route and tool must resolve to one.
- **Function readers** have no enumerable universe. The register test greps `services/` and `main.py` for calls to:
  - the piece getters (`get_thread`, `get_threads`, `get_mission`, `get_missions`, `get_mission_steps`, `get_program`, `get_programs`, `get_protected_commitments`);
  - the findings getters;
  - `get_cached_schedule`;
  - the conversation getters.

  Every enclosing function must be a `('reader', …)` row or be listed INTERNAL. The grep finds where words can come from; the matrix proves what each reader does.
- **Stated limit.** The register proves that every reader is classified. Only the matrix test proves that it behaves. Words copied into stored text (a status note, a finding's sentence, a past chat message) are protected only where their readers are registered and tested.

## 6. Tests

All tests run from `chauffeur/` as plain scripts with `HA_BASE_URL` unset.

### The fixture household

`tests/access_fixture.py` is used by every access test.

**Members:**
- Mom (parent) and Dad (parent);
- Aunt (adult);
- Kate (child of Mom and Dad);
- Hal (helper);
- Pat (disabled parent);
- an archived member with an empty id field on one record.

**Records:**
- **R1:** Aunt's thread in Mom's **private** project.
- **R2:** Aunt's mission in Mom's private project.
- **R3:** Kate's program in Mom's private project, with:
  - emitted commitments;
  - a target date;
  - a practice window today;
  - lesson content.
- **R4:** Mom's thread in Mom's **parents** project.
- **R5:** Dad's thread and Kate's program in a **household** project.
- **R6:** Kate's thread whose subject is a private occasion shared with Kate and Mom, in its wrapper project.
- **R7:** R6's twin inside Mom's private project.
- **R8:** an unowned thread whose subject is a parents-only occasion.
- **R9:** two missions of Mom's:
  - one in Mom's private project, whose origin thread is Mom's thread in the same project;
  - one in the household project that names R1 by title.
- **R10:** Dad's thread in the household project whose subject is R1. This is the nested subject case.
- **R11:** a planning mission whose subject is its own home project (Kate's private project), viewed by Dad. This is the home project as subject.
- **R12:** a thread with `subject_history` naming a parents-only trip.
- **R13:** a wrapper project's legacy thread.

**State:**
- a pre-existing household Finding sourced from R1, written before R1's project became private;
- a populated schedule cache written while R3's project was household, then narrowed to private;
- conversations on each surface (§4.2).

**Viewers:**
- Mom, Dad, Aunt, Kate, Hal, Pat;
- HOUSE and HOUSE_PARENT;
- the family channel and a Mom+Aunt group channel;
- a wall panel device;
- a voice satellite.

### The test files

- **`tests/test_access_matrix.py`.** For every `READERS` row that is not INTERNAL or NONE, and for every viewer, it runs the reader for real: a TestClient request with that person's or device's token, a tool handler with that acting member and focus, or a function call.
  - It asserts the **returned fields**, not only seen or hidden. A hidden record is absent. A `'keeper'` result has no transcript, plan words or cached note. A neutral calendar payload contains no word from the fixture's secret strings.
  - It checks acted versus refused for every write.
  - Cells come from §7 and only from §7.
- **`tests/test_access_register.py`.** It runs the classification and grep guards from §5. A new route, tool or reader with no row fails the suite, the way an unclassified route fails `test_auth`.
- **Regression cells.** The earlier rounds' regressions are cells, each named after its finding: B1, B2, I1–I6, M1–M5, the two minor id-less routes, and Codex #2–#12.
- **Live test.** A private piece through both deep-link forms, on the admin record sheet and on the phone's piece sheet, discloses nothing to Dad and opens for Mom.

## 7. The matrix (expected outcomes)

**Legend:**
- **✓** seen in full
- **K** keeper projection
- **✗** hidden
- **B** "Busy" on calendar surfaces

Columns are viewers on a person's own surface (§4.1, the admin/PWA conversation, a private DM, by-id routes).

| | Mom | Dad | Aunt | Kate | Hal | Pat | HOUSE |
|---|---|---|---|---|---|---|---|
| R1 Aunt's thread, Mom's private P | ✓ | ✗ | K | ✗ | ✗ | ✗ | ✗ |
| R2 Aunt's mission, Mom's private P | ✓ | ✗ | K | ✗ | ✗ | ✗ | ✗ |
| R3 Kate's program, Mom's private P | ✓ | ✓ (parent of child keeper) | ✗ / B | K (renders full) | ✗ / B | ✗ | ✗ / B |
| R4 Mom's thread, Mom's parents P | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| R5 Dad's thread, household P | ✓ | ✓ | ✓ | ✗ (base) | ✗ (base) | ✗ | ✓ |
| R5 Kate's program, household P | ✓ | ✓ | ✓ | ✓ | ✗ (scope) | ✗ | ✓ |
| R6 Kate's thread, Kate+Mom occasion | ✓ | ✗ (subject) | ✗ | ✓ (owner; she may see the occasion) | ✗ | ✗ | ✗ |
| R7 R6 inside Mom's private P | ✓ | ✗ (I1: subject still binds) | ✗ | K | ✗ | ✗ | ✗ |
| R8 unowned, parents-only occasion | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ (M1) |
| R10 Dad's thread about R1 | ✓ | K (his row; R1 hidden) | ✗ | ✗ | ✗ | ✗ | ✗ |
| R11 planning mission, Kate's private P as subject | ✓ | ✓ (checked once, by the project layer) | ✗ | ✗ (base) | ✗ | ✗ | ✗ |
| R12 thread, parents-only trip in history | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| R13 legacy wrapped thread | as today | as today | as today | as today | as today | ✗ | as today |

Note on R6: Kate is the owner and may see the occasion, so she gets `'full'`. Note on R7: Kate cannot see Mom's private project, so she gets `'keeper'` (Codex #12).

**Per class, the differences from that table:**

- **Group channels (§4.3):**
  - Family channel: R5 and every unrestricted row follow today's channel rule (✓ where every human may read its subjects). R1–R4, R7, R10 and R11 are ✗.
  - Mom+Aunt channel: R1 and R2 are K for both speakers. R3 and R4 are ✗.
- **Surface conversations (§4.2):**
  - A wall panel's chat and a voice satellite get the HOUSE column.
  - Mom's admin widget gets the Mom column, and Dad cannot list or read it.
  - The old `general` conversation is read-only and listed to parents only.
- **Mission engine (§4.4):**
  - R9's private-project mission reads its origin thread and the pieces of its own P.
  - The household-project mission's title match for R1 finds nothing, falls back to a plain draft, and never names R1.
- **Voice (§4.5):** only rows that HOUSE sees and that are `spoken_safe`. A voice approval of an ask on R2 is refused aloud.
- **Shared screens (§4.6):**
  - The anonymous wall gets the HOUSE column.
  - A signed-in person gets HOUSE ∪ their own column. Kate on the wall sees R3 and R5's program with titles; Aunt sees R5's program but not R3.
- **Calendar (§4.7):**
  - R3's window is B with the neutral payload (no lesson words, no milestone) for HOUSE, Aunt, Hal, the feed, every speaker, and the digest.
  - For Mom, Dad and Kate in `/api/schedule` it carries every presentation field and the cached colour.
  - This holds with the pre-narrowing cache too.
  - R3's commitments read "Busy" in `/api/commitments` for Aunt and Hal.
  - R3's approval creates no calendar event.
  - R3's push to Hal as driver says "Practice time"; to Dad it carries the title.
- **Signals (§4.8):**
  - The pre-existing R1 Finding is absent for Dad, HOUSE and the Mind, and present for Mom and Aunt.
  - R1 stalled past the paging threshold makes no new household Finding and sends a DM to Aunt only. A quiet R1 stall does nothing.
  - R4 waiting sends a DM to Mom and Dad.
  - R6 and R8 (subject-only) follow today's household path.
  - Pat never receives anything.
- **Acting:**
  - Dad on R2's answer, release, submit, verify, delete, drop or ack gets a 404.
  - Aunt on R2 may use OK, Delete and steer; approve_plan and run_stage are refused.
  - Aunt approving R3 gets a 404. Dad approving R3 is allowed.
  - A live approve card for R2 posted to Dad before the project narrowed now renders "No longer available here" and refuses.
- **Child lists:** Kate on `GET /api/threads` sees only her own threads (R6, R7), never R5's, R8 or R10.

## 8. Build order and split (the standing Codex rule, said at approval)

1. **Claude:** `tests/access_fixture.py`, `test_access_matrix.py` (red), `test_access_register.py` (red), and the core of `services/access.py` (§3, §5) turning the base cells green.
2. **Codex, one task per surface class, each reviewed by Claude.** Each task turns its class's cells green and adds its rows to `READERS`:
   - **a.** routes and pages;
   - **b.** conversations by surface (§4.2), with the client change in `control_center.html` and the removal of `app.html`'s dead popup;
   - **c.** Argyle DM and channel tools;
   - **d.** the mission engine;
   - **e.** voice;
   - **f.** shared screens;
   - **g.** calendar, commitments, practice pushes, and the target-event removal with its migration;
   - **h.** signals and findings;
   - **i.** the removal of add-existing for threads, missions and programs (§10.1), with its migration.
3. **Codex:** a whole-branch adversarial review.
4. **Claude:** docs (`system_capabilities.md`), bump, push.

`privacy-round3-wip` is a reference implementation only, never a base. Its tests may be mined for probes.

## 9. Out of scope

- Trips, occasions and lists as homes; the kind table has the slots.
- How a project's audience is chosen or changed.
- Kids' practice and session cards on Today. They are unchanged: they read as the child, §4.1.
- Media and photo storage access.
- Scrubbing words already posted into a conversation (§4.2, a stated limit).

## 10. Capability changes the user approved (2026-10-16)

The project rule is that nothing a person can do is removed without approval first. These three were approved in conversation.

1. **Add an existing thread, mission or program to a project is removed, entirely.**
   - The user's words: "The only way to add a thread, mission, or program after these updates is to start a project ... I don't see this as being a necessary supported thing you can do."
   - The user then chose "Drop it entirely" over a move limited to wrapped legacy records and over a general move. Old records stay in their wrappers until finished.
   - What goes:
     - those kinds in the Add-a-piece search on the Projects page;
     - in `POST /api/projects/{id}/pieces` and `…/pieces/remove`;
     - in Argyle's `add_to_project`.
   - A migration drops existing `pieces` entries of those kinds. They were links that never changed a record's home.
   - Links to other kinds stay.
2. **Every Argyle conversation belongs to its surface** (§4.2).
   - The user's words: "Every agent conversation should be tied to the surface where it is occurring. The kitchen voice satellite conversation is different from the office conversation which is different from the kitchen wall panel which is different from the admin pages which is different from the chat in the PWA (which is also per person). I see no benefit to these ever having been the same."
   - The shared `general` conversation stops being a live conversation.
3. **A program's target date no longer writes a Google Calendar event** (§4.7).
   - The user's words: "It is a target date, not an event."
   - Existing target events the app created are deleted by migration.

## Appendix A — the reader inventory

This comes from a read-only sweep of the code on 2026-10-16, plus the routes, tools and readers Codex's review added. Line numbers are as of v2.499.520. The initial `READERS` rows come from here; every other route and tool is classified when the register is built (§5). Where today's check is weaker than its class requires, "today" names it.

### Class 4.1: signed-in pages and by-id routes (`main.py`)

- **Threads:**
  - `GET /api/threads`. Today: rows without a subject are unfiltered, a child included, and no viewer gets everything.
  - `POST /api/threads`;
  - `GET /api/threads/{id}/missions`;
  - `PATCH /api/threads/{id}`, `POST …/note`, `…/advance`, `DELETE /api/threads/{id}`, `…/close`;
  - `…/draft` (sends the thread to the LLM), `…/photo`, `…/send` (sends mail), `…/research`.

  All are role-only today except `/missions`.
- **Missions:**
  - `GET /api/missions/admin` and `GET /api/missions/{id}`. Today: no viewer means unfiltered.
  - `POST /api/missions/launch`. Today: `origin_ref` is unchecked.
  - `…/proposals/{pid}/act`, `GET …/shots/{name}`, `…/plan/answers`;
  - `…/release`, `…/submit`, `…/verify`, `…/answer`, `DELETE /api/missions/{id}`, `…/drop`, `…/ack`. These are role-only today.
- **Programs:**
  - `GET /api/programs`, `POST /api/programs`, `…/edit`, `…/unit`;
  - `GET|PUT|DELETE …/lesson`;
  - `POST /api/programs/lessons/sweep`; its report names every program;
  - `GET …/footprint`;
  - `POST …/approve`, role-only today;
  - `…/session`, `…/milestone`, `…/finish`, `…/reshape`, `…/pause`, `…/resume`, `…/drop`.
- **Commitments:** `GET /api/commitments`, which returns program-emitted titles.
- **Situations and asks:**
  - `GET /api/situations`, `GET /api/situations/{kind}/{sid}`, `GET /api/subjects/{kind}/{sid}/situations`;
  - `POST /api/situations/{kind}/{sid}/act`;
  - `POST /api/asks`, with no situation check today;
  - `POST /api/asks/{id}/answer`, whose effect advances a thread.
- **Projects:**
  - `GET /api/projects`, `GET /api/projects/elsewhere`, `GET /api/projects/for/{kind}/{id}`;
  - `GET /api/projects/{id}/pieces`, `GET /api/projects/{id}`;
  - `POST /api/projects/{id}/plan`, `…/steps/{sid}/cancel`, `…/steps/{sid}/hold` (practice times only);
  - `POST …/pieces` and `…/pieces/remove`, reduced to non-piece kinds (§10.1);
  - `GET /api/subjects/search`, `GET /api/subjects/{kind}/{sid}/projects`.
- **Signals read by people:**
  - `GET /api/findings`, open and historical;
  - `GET /api/action-proposals`;
  - `POST /api/action-proposals/{id}/act` and its `chat_actions` program actions.
- **Study:** `GET /api/study/state`. `study._board` returns every open thread with its notes, and `study._binders` every program. Both are role-only today.

### §4.2: conversations

- `POST /api/chat`: its conversation choice, its history injection, and its no-member actor substitution (`parent_of_record` today).
- `GET /api/chat/history`. Today it has no ownership check.
- `GET /api/chat/conversations`. Today the `general` conversation is household-visible.
- `DELETE /api/chat/history`.
- The conversation create route.
- The clients: `control_center.html`, which keeps a localStorage id per browser on both admin pages and panels, and `app.html`'s hidden floating popup, which picks `general` and is dead UI.

### Classes 4.3 and 4.4: Argyle (the `agent_tools_v2.py` registry and the chat router)

- **Situations, asks and projects:** `list_situations`, `next_situation`, `explain_situation`, `act_on_situation`, `start_ask`, `mark_ask_sent`, `answer_ask`, `start_mission_for`, `start_project`, `list_projects`, `get_project`, `add_project_step`, `add_to_project` (reduced, §10.1), `set_project_state`, `set_step_state`, `find_in_chauffeur`, `list_open_findings`.
- **Threads and missions:**
  - `list_threads`. Today it checks subject-bound rows only, with no channel check.
  - `create_thread`, `update_thread_action`, `close_thread`;
  - `add_thread_note` and `draft_thread_message`. Today the title path is unchecked.
  - `launch_mission`. Today `missions._match_thread` is unchecked and seeds the thread into the mission.
- **Programs:** `list_programs`, `program_progress`, `log_program_session`, `propose_program`.
- **Calendar tools:** the calendar tools that read `get_cached_schedule` (`agent_tools_v2.py` near lines 73, 127 and 1212).
- **`agent_router`:**
  - the focus injection (FOCUS and ABOUT);
  - the voice focus injection;
  - the tool-dispatch actor resolution. Today, no member means `parent_of_record`.
- **`triage`:** `triage.next_for`, `triage.get_focus`, `triage.focus_live_asks`.

### §4.4: the mission engine (`missions.py`, `planned.py`)

- The `_apply_planner_action` branches:
  - tool (READ_TOOLS as `read_viewer`);
  - `find_in_chauffeur`;
  - subject;
  - draft (origin thread or `_match_thread`), unchecked today;
  - ask_user.
- `_match_thread`, `_seed_thread_context`, `launch`, `about_block` / `_finder`, `_user_prompt`, `ask_card`.
- `_land_finish`, which sends the thread title to the creator in a DM.
- `planned.is_keeper`, `keeper_view`, `may_approve`, `approve_plan`.

### §4.5: voice

- `POST /api/v2/converse`;
- `voice_tools.dispatch` (`find_in_chauffeur`, `start_project`, `prepare_voice_approval`);
- `voice_approval.valid`, `prepare`, `intercept`.

### §4.6: shared screens

- `GET /api/house/state`: `house_programs.objects` (every program's title and colour) and the `house_attention._programs` count.
- `GET /api/house/programs/{id}/session` (`house_programs.session`).
- `GET /api/programs/{id}/lesson-scenes`.
- `POST /api/programs/{id}/lesson-help`, which sends the title to the LLM.
- `GET /api/programs/celebrations`.
- `home_board._tile_programs`, `home_board._tile_mind`.
- Study on a panel.

### §4.7: calendar and emissions

- `GET /api/practice-windows`: WALL tier, no check today.
- `main._practice_events` → the cached schedule → `GET /api/schedule`.
- `GET /api/packing/day`, with the `family_day` practice payload.
- `main._project_hold_events` and `_project_hold_titles`.
- `programs.practice_windows`.
- The program emission loop (protected commitments).
- `programs.approve`'s target event and `maybe_rebaseline`'s target handling.
- `programs.due_practice_pushes`.
- `GET /api/debug/event_subjects`: PARENTS tier, stays raw, marked INTERNAL-debug.

### §4.8: signals

- `watchers`: `_thread_stalls`, `_mission_states`, `_program_findings`, `run_watchers`, `_post_action_cards`, `_heads_up_line`.
- `findings` readers (`findings.py`, the open and historical reads).
- `replies`: `read`, `_send`, `_notify`, `dm_line`, `_recipients`, `flush_pending_dms`.
- `missions._dm_person`, `planned._ask`.
- `mind.snapshot` (its threads and findings sections), `mind._gather_deltas`.
- `family_digest.build_household_briefing`.

### INTERNAL: raw by design, listed so the decision is visible

- The loaders and checks themselves: `situations.load`, `subjects.load`, the adapters, `subject_records`, `_thread_mission`.
- `situations._facts` / `refresh`: the LLM status note, shown only through `view`.
- `situations.options_for`: built without a viewer, shown only through `view`.
- `projects`: `adopt`, `adopt_existing`, the migrations, `_work_missions`, `advance`, `resume_waiting`, `_work_step`, `on_question`, `on_mission_closed`, `_busy_intervals`, `find_window`.
- The solver's reads of protected commitments.
- `threads.match_inbound`, `email_ingest._match_thread`.
- `threads.is_stalled` / `stalled`: their callers apply the rule.
- `threads.open_by_owner` and `vitals.measure_day`: counts only.
- `missions.tick`, `planned.reconcile`, `_bind_created`.
- `program_lessons.generate_due`, `generate_for`, `_windows_to_scan`.
- `programs.maybe_rebaseline` (apart from its target handling) and `orphaned_emissions`.

`programs.due_session_asks` and `projects.project_for` have no callers; the plan deletes them.
