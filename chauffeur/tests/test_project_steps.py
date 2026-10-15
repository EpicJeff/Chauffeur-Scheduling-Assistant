"""Steps (Projects core spec §2), Tasks 4–6.

Block A (Task 4) — one write path and dependencies:
  * `projects.add_step(project_id, step, actor)`, `edit_step(project_id, step_id,
    fields, actor)`, `remove_step(project_id, step_id, actor)` and
    `set_step_state(project_id, step_id, state, actor)` are the only writes;
    each returns {'status': 'success'|'error', ...}; `set_step_state` returns
    'advanced': the Argyle step ids `projects.advance(project_id)` found ready;
  * `needs` names existing steps of the same project; a cycle, an unknown id,
    or removing a step another needs is refused;
  * `done` and `skipped` satisfy a dependent; reopening re-blocks a dependent
    that has not started;
  * a child ticks only steps they own; an assignee may not tick a step whose
    needs are open; a parent may; ticking twice changes nothing;
  * an archived owner reads "Unassigned" and the step stays tickable;
  * step titles go through the body-goal rule of the project.

Route handlers (main.py): project_add_step(project_id, body, request),
project_edit_step(project_id, step_id, body, request),
project_remove_step(project_id, step_id, request),
project_step_state(project_id, step_id, body, request).

Run from chauffeur/:  python tests/test_project_steps.py
"""
import threading

from harness import check  # noqa: F401
from services import storage
from test_projects import _fresh, _p, _make
from test_subjects import MOM, DAD, AUNT, KID
from test_subject_audience import _as


def _step(pid, actor, **step):
    res = _p().add_step(pid, step, dict(actor))
    check(res['status'] == 'success', f"step added: {res}")
    return res['step']


def _state(pid, sid):
    return next(s for s in storage.get_project(pid)['steps'] if s['id'] == sid)['state']


def scenario_a1_dependencies_are_checked():
    _fresh()
    p = _make('mom', MOM, audience='household', title='Bathroom')
    s1 = _step(p['id'], MOM, title='Demo the old tile', owner='mom')
    s2 = _step(p['id'], MOM, title='Tile the floor', owner='dad', needs=[s1['id']])
    check(s2['order'] > s1['order'] and s2['state'] == 'todo', f"ordered, to do: {s2}")
    check(_p().add_step(p['id'], {'title': 'x', 'owner': 'mom', 'needs': ['nope']}, dict(MOM))['status'] == 'error',
          "an unknown prerequisite is refused")
    check(_p().edit_step(p['id'], s1['id'], {'needs': [s2['id']]}, dict(MOM))['status'] == 'error', "a cycle is refused")
    check(_p().remove_step(p['id'], s1['id'], dict(MOM))['status'] == 'error', "a step another needs cannot be removed")
    check(_p().edit_step(p['id'], s2['id'], {'needs': []}, dict(MOM))['status'] == 'success'
          and _p().remove_step(p['id'], s1['id'], dict(MOM))['status'] == 'success', "after the edit it can")


def scenario_a2_who_may_tick():
    _fresh()
    p = _make('kid', MOM, title='Learn to ride a bike')
    helmet = _step(p['id'], MOM, title='Get a helmet', owner='mom')
    park = _step(p['id'], MOM, title='Practise in the park', owner='kid', needs=[helmet['id']])
    check(_p().set_step_state(p['id'], park['id'], 'done', dict(KID))['status'] == 'error',
          "Kate may not tick her step while the helmet is still to get")
    check(_p().set_step_state(p['id'], helmet['id'], 'done', dict(KID))['status'] == 'error',
          "a child ticks only steps they own")
    check(_p().set_step_state(p['id'], park['id'], 'done', dict(DAD))['status'] == 'success',
          "a parent may tick out of order (life happens)")
    house = _make('mom', MOM, audience='household', title='Garage')
    a = _step(house['id'], MOM, title='Sort the shelves', owner='dad')
    b = _step(house['id'], MOM, title='Sweep', owner='aunt', needs=[a['id']])
    check(_p().set_step_state(house['id'], b['id'], 'done', dict(AUNT))['status'] == 'error',
          "an adult who is not a parent may not tick early either")
    check(_p().set_step_state(house['id'], a['id'], 'done', dict(AUNT))['status'] == 'success'
          and _p().set_step_state(house['id'], b['id'], 'done', dict(AUNT))['status'] == 'success',
          "an adult who can act ticks in order")


def scenario_a3_one_tick_one_advance():
    _fresh()
    p = _make('mom', MOM, audience='household', title='Bathroom')
    demo = _step(p['id'], MOM, title='Demo the old tile', owner='mom')
    research = _step(p['id'], MOM, title='Find tile', owner='argyle', goal='three tiles under $5 a square',
                     needs=[demo['id']])
    check(_p().advance(p['id']) == [], "nothing is ready before the demo")
    results = []
    barrier = threading.Barrier(2)

    def tick():
        barrier.wait()
        results.append(_p().set_step_state(p['id'], demo['id'], 'done', dict(MOM)))
    threads = [threading.Thread(target=tick) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    check(all(r['status'] == 'success' for r in results), f"both taps answer: {results}")
    advanced = [r.get('advanced') for r in results if r.get('advanced')]
    check(advanced == [[research['id']]], f"one write, one advance: {results}")
    row = storage.get_project(p['id'])
    done = next(s for s in row['steps'] if s['id'] == demo['id'])
    check(done['state'] == 'done' and done['done_by'] == 'mom' and done['done_at'], f"stamped: {done}")
    again = _p().set_step_state(p['id'], demo['id'], 'done', dict(MOM))
    check(again['status'] == 'success' and not again.get('advanced') and storage.get_project(p['id'])['rev'] == row['rev'],
          "ticking a done step changes nothing")


def scenario_a4_skipped_satisfies_and_reopening_reblocks():
    _fresh()
    p = _make('mom', MOM, audience='household', title='Bathroom')
    plumber = _step(p['id'], MOM, title='Hire a plumber', owner='mom')
    rough = _step(p['id'], MOM, title='Rough-in the drain', owner='dad', needs=[plumber['id']])
    check(_p().set_step_state(p['id'], plumber['id'], 'skipped', dict(MOM))['status'] == 'success', "skipped")
    check(_p().set_step_state(p['id'], rough['id'], 'doing', dict(DAD))['status'] == 'success',
          "skipping a prerequisite lets the next step go")
    other = _step(p['id'], MOM, title='Paint', owner='aunt', needs=[plumber['id']])
    check(_p().set_step_state(p['id'], plumber['id'], 'todo', dict(MOM))['status'] == 'success', "reopened")
    check(_p().set_step_state(p['id'], other['id'], 'done', dict(AUNT))['status'] == 'error',
          "a dependent that had not started is blocked again")
    check(_state(p['id'], rough['id']) == 'doing', "one already under way is left alone")


def scenario_a5_an_archived_owner_reads_unassigned():
    _fresh()
    p = _make('mom', MOM, audience='household', title='Garage')
    s = _step(p['id'], MOM, title='Haul the boxes', owner='dad')
    storage.set_member_status('dad', 'archived')
    v = _p().view(storage.get_project(p['id']), dict(MOM))
    step = next(x for x in v['steps'] if x['id'] == s['id'])
    check(step.get('owner_label') == 'Unassigned', f"an archived owner reads Unassigned: {step}")
    check(v['next_step'] and v['next_step']['id'] == s['id'], "and it is still the next step")
    check(_p().set_step_state(p['id'], s['id'], 'done', dict(MOM))['status'] == 'success', "still tickable")
    check(_p().view(storage.get_project(p['id']), dict(MOM))['steps_done'] == 1, "counted up")


def scenario_a6_step_titles_follow_the_body_rule():
    _fresh()
    shared = _make('mom', MOM, audience='household', title='Garage')
    check(_p().add_step(shared['id'], {'title': 'Lose 10 pounds', 'owner': 'mom'}, dict(MOM))['status'] == 'error',
          "a body-goal step in a shared project is refused")
    mine = _p().create({'title': 'Get down to 185 lbs', 'goal': 'hikes', 'done_when': '185', 'owner_member_id': 'mom'},
                       dict(MOM))['project']
    check(_p().add_step(mine['id'], {'title': 'Weigh in on Sundays', 'owner': 'mom'}, dict(MOM))['status'] == 'success',
          "allowed inside an adult's private body goal")


def scenario_a7_routes_act_as_the_signed_in_member():
    _fresh()
    import main
    p = _make('kid', MOM, title='Learn to ride a bike')
    s = main.project_add_step(p['id'], {'title': 'Pump the tyres', 'owner': 'kid'}, request=_as('mom'))
    sid = s['step']['id']
    out = main.project_step_state(p['id'], sid, {'state': 'done', 'member_id': 'mom'}, request=_as('kid'))
    check(out['status'] == 'success' and storage.get_project(p['id'])['steps'][0]['done_by'] == 'kid',
          f"Kate ticks her own step as herself: {out}")
    from fastapi import HTTPException
    try:
        main.project_step_state(p['id'], sid, {'state': 'todo'}, request=_as('aunt'))
        check(False, "an aunt who cannot see it is refused")
    except HTTPException as e:
        check(e.status_code == 404, f"404 for a project she cannot see: {e.status_code}")
    main.project_edit_step(p['id'], sid, {'title': 'Pump both tyres'}, request=_as('dad'))
    check(storage.get_project(p['id'])['steps'][0]['title'] == 'Pump both tyres', "a parent edits")
    main.project_remove_step(p['id'], sid, request=_as('dad'))
    check(storage.get_project(p['id'])['steps'] == [], "and removes")


BLOCK_A = [
    scenario_a1_dependencies_are_checked,
    scenario_a2_who_may_tick,
    scenario_a3_one_tick_one_advance,
    scenario_a4_skipped_satisfies_and_reopening_reblocks,
    scenario_a5_an_archived_owner_reads_unassigned,
    scenario_a6_step_titles_follow_the_body_rule,
    scenario_a7_routes_act_as_the_signed_in_member,
]
BLOCK_B = []      # Task 5: waiting_step and the shared status sets.
BLOCK_C = []      # Task 6: Argyle's steps start, finish with their stage, cancel.
SCENARIOS = BLOCK_A + BLOCK_B + BLOCK_C

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)
