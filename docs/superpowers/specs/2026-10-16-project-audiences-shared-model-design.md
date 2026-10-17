# Project audiences on the shared model

**Status:** rev 3 (2026-10-17: §3 rewritten after the Task 1 tests found that parents wrappers would restrict records open to every adult and the house; user ruling: wrappers are test data, option A). Rev 2 approved 2026-10-17; rev 2.1 added the no-list private default; 2026-10-16, Codex adversarial review folded in (14 findings, §9). Prerequisite of the Projects delete slice.

## Why

Projects carry their own three-value audience (`private` | `parents` | `household`, `services/projects.py:12`) that cannot express what the rest of the household's records can. Trips, occasions, calendar events and lists use the shared model in `services/scope.py` (`audience_allows`, :601): `household`, `parents`, `shared` (parents plus a `shared_with` list) and `private` (exactly the `shared_with` list, which may leave a parent out: the surprise-gift case). A project cannot be hidden from one parent, so a "Mom's 50th surprise party" project cannot exist.

Front door slice 1 papered over the gap for wrapper projects (projects made by `adopt` around an existing record): instead of an audience, a wrapper borrows its record's visibility live (`projects._wrapped_visible`). That makes a project's visibility depend on whether a piece still exists, which breaks the delete slice. The user's ruling (2026-10-16): the project determines who sees it; if project audiences cannot model what their pieces can, the project model is wrong. Projects move onto the shared model, and the wrapper special case goes away.

## Decisions (user, 2026-10-16)

- Projects use the shared audience values and `shared_with`, read through `scope.audience_allows`.
- A wrapper's visibility is copied onto the project **once**, at migration or adoption; afterwards the project's own audience wins. `_wrapped_visible` is deleted.
- What a role may see INSIDE a project (a child never sees mission internals or contacts) stays at the piece level. It decides how much a person sees in a project, never whether they see the project.
- Children's projects follow the occasion rule: a child may leave a parent off a `private` list.

## 1. Meaning of each value for a project

`projects.can_see(project, viewer)` becomes: the viewer is active, and either the viewer is the owner, or `scope.audience_allows(project, 'project', viewer)`.

| audience | who sees it |
|---|---|
| `household` | every active member, and anonymous house readers (wall, panel, speaker, Mind) |
| `parents` | every parent, and the owner |
| `shared` | every parent, the owner, and each member in `shared_with` |
| `private` | exactly `shared_with` (which always contains the owner) |

- The owner always sees their project (a project-level rule on top of `audience_allows`, which has no notion of owner).
- `scope.AUDIENCE_DEFAULTS` gains `'project': 'private'`; an unknown value reads as the default and therefore fails closed.
- House readers (`access.HOUSE`, `HOUSE_PARENT`, `member=None`) see `household` only (`access.project_visible` loses its wrapper branch).
- `access.restricted(project)` becomes `audience != 'household'`, with no wrapper exception.
- **The parent-of-child-keeper bypass** (`access.record_view`, :194) no longer applies when the record's home project is `private` and owned by that child: the child's list decides. In any other home it applies as today. A parent left off a child's private list therefore sees none of that project's records, practice words or holds on any surface.

## 2. Writing an audience

One validator, `projects.normalize_audience(fields, actor, current=None)`, used by `prepare_create`, `update` (PATCH), plan proposal and reshape (`planned.py`), `adopt` and the migration:

- `audience` must be one of the four values; anything else is refused with "Choose household, parents, shared or private".
- `shared_with` keeps only ids of existing, non-archived members, de-duplicated. It is cleared for `household` and `parents`.
- `private` always contains the owner (added if missing). An owner change adds the new owner to a `private` or `shared` list.
- `shared` with an empty list after filtering is stored as `parents`.
- `private` with NO list supplied (the chat card's "Make private", the planner, an API caller) means the owner's default private list: `[owner]` for an adult, `[child] + every active parent` for a child. An explicit list is taken as given (the owner auto-added), which is how a child leaves a parent out.
- Body goals (`body_goal` set): audience must be `private` with `shared_with == [owner]`, owner an adult; anything else is refused (today's pin, restated).

**Edit authority.** Changing `audience`, `shared_with` or `owner_member_id` is allowed only to the project's CURRENT owner, or a parent who can see the project, judged against the row before the change. An adult who is merely listed (or who passes `can_act`) can edit title, goal and steps but cannot widen the audience or take ownership. The card and detail payloads gain `can_edit_audience` (this rule) and `body_goal`; both surfaces use them instead of `can_edit`.

**Defaults** (`prepare_create`, `start_project`): a child owner gets `parents` (as today, `projects.py:139`); anyone else gets `private` with `[owner]`; spoken or house-started projects get `household` (as today). The planner prompt (`missions.py:159`) keeps offering `private|parents|household` only; it never picks people, and its `private` normalizes to the defaults above.

**Plans carry the list.** The plan proposal whitelist (`planned.py:746`), `RESHAPE` (:257), the preview, the approval intent and replay carry `shared_with` alongside `audience`; the final merged shape is normalized once at approval.

## 3. Migration and wrapper derivation (rev 3)

**User, 2026-10-17:** existing wrappers are test data only ("everything with a wrapper is just a test thread or mission"), so the migration does not need a frozen snapshot of legacy visibility. Every wrapper, old or new, gets its audience from one rule, `project_audience.derive_for_record(kind, row, owner_id)`:

- The record is judged by secrecy, not by role (role capability stays at the piece level, Decisions). If the anonymous house reader (`access.HOUSE`) can read the record and every active parent and adult can read it, the wrapper is `household`. Children and helpers then see the project's name but still cannot open a thread or mission (piece-level role rules), and secret records never qualify because the house reader passes only household audiences.
- Otherwise the viewer set is every active member with a non-None `record_view(kind, row, member, skip_project=True)`; every parent in the set: `parents` (nobody else beyond the owner) or `shared` (with the others); else `private` with the set.
- If the owner is not in the set, ownership moves to a member of it (the record's keeper first, then a parent, then an adult). An empty set keeps the owner, `private` `[owner]`, and replaces the copied title and goal with "Untitled project".
- A wrapper whose record is gone: `private` `[owner]`. A body goal: `private` `[owner]` first.

**Binding narrows once.** When a thread, mission or program in a wrapper (`wrapped_from` set) gets a new subject (`subject_kind`/`subject_id`/`subject_history` written by any path), the wrapper is re-derived and its audience replaced only if the derived viewers are a subset of who sees it now. This is the propagation the user asked for ("the visibility should have been propagated to the project"); nothing reads the record live.

**The migration** (one numbered function in `services/migrations.py`, after `migrate_projects_adopt_v2499517`) converts every row without `audience_rev: 2`: plain rows as below, wrappers through `derive_for_record`; each converted row is stamped `audience_rev: 2` and never touched again, so an interrupted run resumes.
- `household`, `parents`: unchanged, `shared_with` empty.
- `private`, adult owner: `[owner]`. `private`, child owner: `[child] + every active parent` (accepted: survives adulthood; a parent added later is not on it).

`wrapped_from` stays on the row as provenance (plan reshape and triage still read it); visibility never reads it.

**House readers:** `access.project_visible` passes `household` for `HOUSE`; `HOUSE_PARENT` (the mission engine acting for the parent of record) passes `household`, `parents` and `shared` (the shared model's parent bypass), never a `private` list.

**Recipients:** a thread in a person's private project notifies the project's list (its owner included) as well as the keeper (§4).

## 4. Readers that change

- `services/projects.py`: `can_see`, `_validate` (replaced by `normalize_audience`), `update` (edit authority), `prepare_create`, `_wrapper_fields`, `adopt`, `AUDIENCE_LABEL` (adds `shared` "Parents and chosen people", `private` with more than the owner "Only {names}"), `card()`/`view()` emit `shared_with` with names, `can_edit_audience`, `body_goal`. `_wrapped_visible` and `_GATE` deleted.
- `services/access.py`: `restricted()`, `project_visible`, the bypass rule in §1, and `private_recipients`: candidates are the keeper, a child keeper's parents (as today), and the home project's audience members (`parents`: parents; `shared`: parents and the list; `private`: the list); every candidate must be active and have a non-None `record_view`; keepers get their keeper projection. `replies._send` (:164) refuses a recipient whose projection is None instead of sending the summary.
- `services/planned.py`: §2 "Plans carry the list".
- `services/home_board.py:5334`: the access digest adds `shared_with`.
- Literal checks that stay correct unchanged (`household` vs not): `projects.calendar_holds`, the subjects adapter's `spoken_safe`, `agent_tools_v2._sensitive` and `_project_in_reach`, `subjects.subject_records` proposed-project rule, `main._project_hold_titles`. Each gets one test under a `shared` and a `private`-list project.
- `services/access_readers.py`: an explicit row for `PATCH /api/projects/{id}` (today it falls through the `NONE` prefix entry, :341).

## 5. UI

- One shared people picker, `templates/components/audience_picker.html`, extracted from the list share popover (`templates/shopping.html:1104-1153`, logic :3541-3596). It renders the audience choice and a member checklist and posts what the person chose; the SERVER owns each kind's rules and the picker re-reads the saved row afterwards. Per-kind config: lists keep `household | private`, the default list hides private, and a household list keeps its additive `shared_with` grants (keeping-up members) untouched; projects get all four values and the checklist only for `shared`/`private`. The shopping page uses the component with no behaviour change, proven by its existing live tests plus one new cell per case above.
- Projects page: the create form's `<select>` becomes the picker; the project detail page gets an Audience row (shown when `can_edit_audience`) that opens the picker in the settings sheet. Body-goal projects show "Only you" and no picker.
- The chat project card's ladder (`app.html:5370-5402`) shows its quick choices plus "Choose people…" only when `can_edit_audience`.
- No browser dialogs; Tailwind rebuild after template changes.

## 6. Tests

Written first. New `tests/test_project_audience_model.py`:
- each value against owner, parent, the other parent, adult, listed child, unlisted child, helper, house reader;
- normalize: filtering, owner auto-add, owner change, empty `shared` -> `parents`, body goal pin;
- edit authority: a listed adult cannot change audience, list or owner; the two-request escalation (take ownership, then widen) is refused;
- plans: a proposal with a list survives preview, approval and replay;
- migration: each legacy value; body goal first; wrappers for a household-visible record, an adults-only thread, Aunt who sees Dad's thread but not its `parents` wrapper (stays hidden), a subject-restricted thread whose owner is hidden (ownership moves), an empty set ("Untitled project"), a child keeper's program, a missing record; an interrupted run resumed; a second run is a no-op;
- deleting a wrapped record changes nobody's view of the project (the bug this spec exists to close).

The access fixture (`tests/access_fixture.py`) gains a `shared` project and a child's `private` project that leaves Dad out, with expected cells in `tests/access_signed_in.py` and the channel, signal and calendar tables: Dad sees none of that project's records, practice words, holds or DMs; `private_recipients` never includes him.

Existing tests to update, not weaken: `test_projects.py` :61-71, `test_front_door_audience.py` :17-36 and `test_project_adopt.py` :147-158 (a wrapper is narrowed by its derived audience, not by later record changes), `tests/access_signed_in.py` :76-89, `test_projects_audience.py`, `test_project_private.py`, `test_body_goal.py`. Live: the picker on the projects page and the chat card (`test_project_card_live.py`), and the shopping share popover unchanged.

Gate: the files above plus `test_access_matrix.py`, `test_access_register.py`, `test_audience.py`, `test_scope.py`, `test_list_sharing.py`, `test_subject_audience.py`.

## 7. Split

Claude writes the tests first, the picker extraction and UI, the gate, docs, bump and commit. Codex builds `normalize_audience`, edit authority, the migration and the reader changes in §4. Claude reviews Codex's work.

## 8. Out of scope

- The delete slice (next spec), which relies on this one: with no wrapper case, deleting a piece never changes who sees its project.
- Changing trips, occasions or events' own audience behaviour.
- Letting the planner choose people.

## 9. Codex review (rev 1 -> rev 2)

1-4: wrapper derivation now starts from today's exact project visibility (record gate AND wrapper audience), keeps house/spoken/hold-title promotion to legacy `household` wrappers only, moves ownership when the owner is outside the set, and gives body goals precedence. 5: the child-keeper parent bypass yields to a child's own private list. 6, 12: edit authority judged against the row before the change; `can_edit_audience` and `body_goal` in the payloads. 7-8: `private_recipients` unions today's candidates with the audience and filters by projection; `replies._send` refuses None. 9: plans carry the list. 10: per-row `audience_rev`, frozen legacy evaluation before any write, ordered after the adopt migration. 11: a child's legacy private becomes a private list of the child and the parents (accepted: survives adulthood); a later parent sees a derived `parents` wrapper (accepted: the project's audience wins). 13: the picker posts choices and the server owns per-kind rules; shopping's additive grants untouched. 14: explicit PATCH register row; fixture and matrix extended.
