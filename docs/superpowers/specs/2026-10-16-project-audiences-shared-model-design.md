# Project audiences on the shared model

**Status:** draft for review, 2026-10-16. Prerequisite of the Projects delete slice.

## Why

Projects carry their own three-value audience (`private` | `parents` | `household`, `services/projects.py:12`) that cannot express what the rest of the household's records can. Trips, occasions, calendar events and lists use the shared model in `services/scope.py` (`audience_allows`, :601): `household`, `parents`, `shared` (parents plus a `shared_with` list) and `private` (exactly the `shared_with` list, which may leave a parent out: the surprise-gift case). A project cannot be hidden from one parent, so a "Mom's 50th surprise party" project cannot exist.

Front door slice 1 papered over the gap for wrapper projects (projects made by `adopt` around an existing record): instead of an audience, a wrapper borrows its record's visibility live (`projects._wrapped_visible`). That makes a project's visibility depend on whether a piece still exists, which breaks the delete slice. The user's ruling (2026-10-16): the project determines who sees it; if project audiences cannot model what their pieces can, the project model is wrong. Projects move onto the shared model, and the wrapper special case goes away.

## Decisions (user, 2026-10-16)

- Projects use the shared audience values and `shared_with`, read through `scope.audience_allows`.
- A wrapper copies its record's audience **once**, at migration or adoption; afterwards the project's own audience wins. `_wrapped_visible` is deleted.
- What a role may see INSIDE a project (a child never sees mission internals or contacts) stays at the piece level. It decides how much a person sees in a project, never whether they see the project.
- Children's projects follow the occasion rule: a child may leave a parent off a `private` list. Today a child's project always includes both parents; that guarantee ends for an explicit private list. The default for a child still includes the parents.

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
- House readers (`access.HOUSE`, `HOUSE_PARENT`, `member=None`) see `household` only, as today (`access.project_visible`).
- `access.restricted(project)` becomes `audience != 'household'`, with no wrapper exception.
- `can_act` is unchanged in shape (sees it, and owner or a non-child parent/adult).

## 2. Writing an audience

One validator, `projects.normalize_audience(project_fields, actor)`, used by `prepare_create`, `update` (PATCH), plan reshape (`planned._project_for_plan`), `adopt` and the migration:

- `audience` must be one of the four values; anything else is refused with "Choose household, parents, shared or private".
- `shared_with` keeps only ids of existing, non-archived members, de-duplicated. It is cleared for `household` and `parents`.
- `private` always contains the owner (added if missing). An owner change adds the new owner to a `private` or `shared` list.
- `shared` with an empty list after filtering is stored as `parents`.
- Body goals (`body_goal` set): audience must be `private` with `shared_with == [owner]`, owner an adult; any other audience is refused (today's pin, restated exactly).
- Who may change the audience: the owner, or a parent who can see the project. An adult who is merely on the list cannot widen it.

Defaults (`prepare_create`): a child owner gets `private` with `[child] + every active parent`; anyone else gets `private` with `[owner]`. `start_project` keeps its rules (spoken or house-started: `household`; child owner: the child default above; else the private default). The planner prompt (`missions.py:159`) keeps offering `private|parents|household` only; it never picks people.

## 3. Migration (one numbered migration, idempotent)

Runs once over every project row:

- `household` and `parents`: unchanged, `shared_with` cleared.
- `private`: `shared_with = [owner]`, plus every active parent when the owner is a child (exactly today's visibility).
- Wrappers (`wrapped_from` set): the audience is derived from the wrapped record as it is seen NOW, by `projects.derive_audience(kind, row)`:
  - the viewer set is every active member for whom `access.record_visible(kind, row, member)` holds;
  - every active member sees it AND the anonymous house reader (`access.HOUSE`) sees it: `household`;
  - every parent sees it and the set is exactly the parents (plus the owner): `parents`;
  - every parent sees it plus others: `shared` with the others;
  - otherwise: `private` with the set (the owner added).
  - The mapping never widens for a signed-in person. It may narrow for house readers: a record seen by HOUSE but not by every member (an adults-only thread) becomes `shared`/`private`, so a wall no longer shows that wrapper. Accepted.
  - A wrapped record already gone: `private` with `[owner]`.
- `wrapped_from` stays on the row as provenance only (plan reshape and triage still read it, `planned.py:275/347`, `missions.py:374`); nothing reads it for visibility.
- A marker in app state makes the migration run once; rerunning it is a no-op.

New wrappers made after the migration (`adopt` on a record created without a project) use the same `derive_audience` instead of `_wrapper_fields`' `parents`/`household` rule.

## 4. Readers that change

- `services/projects.py`: `can_see`, `_validate` (replaced by `normalize_audience`), `prepare_create`, `_wrapper_fields`, `adopt`, `AUDIENCE_LABEL` (adds `shared` "Parents and chosen people", `private` "Only {names}" when the list has more than the owner), `card()`/`view()` emit `shared_with` with names; `_wrapped_visible` and `_GATE` deleted.
- `services/access.py`: `restricted()`, `project_visible` (no wrapper branch), `private_recipients` (a `private` or `shared` home: its listed members, plus parents for `shared`; `parents` as today).
- `services/home_board.py:5334`: the access digest adds `shared_with`.
- Literal checks that stay correct unchanged (`household` vs not): `projects.calendar_holds`, the subjects adapter's `spoken_safe`, `agent_tools_v2._sensitive` and `_project_in_reach`, `subjects.subject_records` proposed-project rule, `main._project_hold_titles`. Each gets one test under a `shared`/`private`-list project.
- `access_readers.py`: no new routes; the PATCH row covers `shared_with`.

## 5. UI

- One shared people picker, extracted from the list share popover (`templates/shopping.html:1104-1153`, logic :3541-3596) into `templates/components/audience_picker.html`: the audience choice plus a member checklist, configured with the allowed values per kind. Lists keep `household | private`; projects get all four. The shopping page uses the component, with no behaviour change (same concept, same builder: `docs/ui_design_guide.md`).
- Projects page: the create form's `<select>` becomes the picker; the project detail page gets an Audience row (owner or a seeing parent) that opens the picker in the settings sheet. Body-goal projects show "Only you" and no picker.
- The chat project card's ladder (`app.html:5370-5402`) keeps its three quick choices and adds "Choose people…", which opens the picker in a sheet.
- No browser dialogs; Tailwind rebuild after template changes.

## 6. Tests

Written first. New `tests/test_project_audience_model.py`:
- each value against owner, parent, the other parent, adult, listed child, unlisted child, house reader;
- a child's private project leaving out one parent: that parent cannot see it on any surface the access matrix covers (project list, detail, holds title, Argyle `list_projects`, situations);
- normalize: filtering, owner auto-add, owner change, empty `shared` -> `parents`, body goal pin, who may edit;
- migration: each legacy value; wrapper derivation for a household-visible record, an adults-only thread, a subject-restricted thread (private occasion), a child keeper's program, a missing record; idempotence;
- deleting a wrapped record changes nobody's view of the project (the bug this spec exists to close).

Existing tests to update, not weaken: `test_projects.py` :61-71 (the "never private from parents" cell becomes the default-list cell), `test_front_door_audience.py` :17-36 and `test_project_adopt.py` :147-158 (a wrapper is no longer narrowed by later record changes; it is narrowed by its derived list), `tests/access_signed_in.py` :76-89 house cells for adult-only wrappers, `test_projects_audience.py`, `test_project_private.py`, `test_body_goal.py`. Live: the picker on the projects page and the chat card (`test_project_card_live.py`), and the shopping list share popover unchanged.

Gate: the files above plus `test_access_matrix.py`, `test_access_register.py`, `test_audience.py`, `test_scope.py`, `test_list_sharing.py`, `test_subject_audience.py`.

## Split

Claude writes the tests first, the picker extraction and UI, the gate, docs, bump and commit. Codex builds `normalize_audience`, `derive_audience`, the migration and the reader changes in §4. Claude reviews Codex's work; Codex adversarially reviews this spec before the plan.

## Out of scope

- The delete slice (next spec), which relies on this one: with no wrapper case, deleting a piece never changes who sees its project.
- Changing trips, occasions or events' own audience behaviour.
- Letting the planner choose people.
