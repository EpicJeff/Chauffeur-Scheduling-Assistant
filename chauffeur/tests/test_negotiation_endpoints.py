"""HTTP endpoints for negotiation (task 8) -- the hand path onto
services/negotiation.py. The sweep runs a shallow search automatically; these
are the same four things a person can do by hand: search deeper on demand,
send the asks, drop a deal, and see (or clear) what the app taught itself.

FastAPI's TestClient needs httpx, which is not installed in this environment
(`starlette.testclient` raises `RuntimeError` on import here), so these
scenarios call the endpoint functions directly -- the same pattern already in
use for threads (`tests/test_threads_endpoints.py`) and packing
(`tests/test_packing_api.py`): a plain Python call with `request=None` and,
where a claim matters, an explicit `member_id` in the body.

Every route here is parent/adult work, same discipline as findings'
`_needs_you_actor` -- these endpoints reuse it directly rather than growing a
second copy of the same rule.

Run from chauffeur/:  python tests/test_negotiation_endpoints.py
"""
from harness import check  # noqa: F401  (isolates CHAUFFEUR_DATA_DIR)

from fastapi import HTTPException

from services import storage


def _denied(fn, *a, **kw):
    try:
        fn(*a, **kw)
        return None
    except HTTPException as e:
        return e.status_code


def _reset_members():
    storage.members_table.truncate()
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    storage.add_member({'id': 'kid', 'name': 'Lily', 'role': 'child'})


def scenario_the_endpoints_exist():
    import main
    paths = {r.path for r in main.app.routes}
    for p in ('/api/negotiation/find', '/api/negotiation/{deal_id}/ask',
              '/api/negotiation/{deal_id}/kill', '/api/negotiation/refusals'):
        check(p in paths, f"{p} must be reachable by hand, have {sorted(paths)[:5]}...")


def scenario_find_with_no_pack_is_honest():
    import main
    res = main.negotiation_find({'event_id': 'nope', 'date': '2026-09-07'},
                                request=None)
    check(res.get('deal') is None,
          f"and does not invent one when there is no pack, got {res}")


def scenario_find_with_no_event_id_is_honest_too():
    import main
    res = main.negotiation_find({'date': '2026-09-07'}, request=None)
    check(res.get('status') == 'error',
          f"an empty event id must not reach the solver, got {res}")


def scenario_killing_a_missing_deal_is_an_error_not_a_crash():
    import main
    res = main.negotiation_kill('nope', {'reason': 'x'}, request=None)
    check(res.get('status') == 'error', f"got {res}")


def scenario_asking_a_missing_deal_is_an_error_not_a_crash():
    import main
    res = main.negotiation_ask('nope', {}, request=None)
    check(res.get('status') == 'error', f"got {res}")


def scenario_a_learned_flag_can_be_untaught():
    import main
    storage.add_shift_refusal('series-7', 'Piano')
    listed = main.negotiation_refusals(request=None)
    check(any(r['series_key'] == 'series-7' for r in listed['refusals']),
          f"a person can see what the app taught itself, got {listed}")
    cleared = main.negotiation_clear_refusal('series-7', request=None)
    check(cleared.get('status') == 'success', f"clearing did not succeed: {cleared}")
    check(not any(r['series_key'] == 'series-7'
                  for r in storage.get_shift_refusals()),
          "and take it back")


def scenario_clearing_a_flag_that_is_not_there_is_an_error_not_a_crash():
    import main
    res = main.negotiation_clear_refusal('no-such-series', request=None)
    check(res.get('status') == 'error', f"got {res}")


def scenario_a_child_actor_is_refused_on_every_route():
    """Parent/adult work, kiosk-hidden, like the rest of the deal surface --
    a child who reaches one of these routes is refused rather than quietly
    ignored, same as the findings routes these reuse the guard from.

    GET/DELETE carry no body, so (like `list_findings`) they trust only a
    real token, not a client-claimed member_id -- there is nothing to claim
    into on those two, so only the three body-carrying routes are exercised
    here."""
    _reset_members()
    import main
    check(_denied(main.negotiation_find, {'event_id': 'x', 'date': '2026-09-07',
                                          'member_id': 'kid'}, request=None) == 403,
          "a child could run the deep search")
    check(_denied(main.negotiation_ask, 'nope', {'member_id': 'kid'},
                 request=None) == 403,
          "a child could send the asks")
    check(_denied(main.negotiation_kill, 'nope', {'reason': 'x', 'member_id': 'kid'},
                 request=None) == 403,
          "a child could drop a deal")


def _dashboard():
    import os
    return open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'templates', 'dashboard.html'), encoding='utf-8').read()


def _div_block(html, marker):
    """(start, end) of the <div> that opens at `marker`, by counting depth.

    Enough of a parser to answer the only structural question here: is this
    element INSIDE that one? The dashboard's dialog is plain nested divs.
    """
    import re
    start = html.index(marker)
    depth, pos = 0, start
    for m in re.finditer(r'<div\b|</div>', html[start:]):
        depth += 1 if m.group() == '<div' else -1
        pos = start + m.end()
        if depth == 0:
            return start, pos
    raise AssertionError(f"unbalanced divs after {marker!r}")


def scenario_find_a_way_is_reachable_on_an_uncovered_event():
    """Not just "the button exists" — WHERE it exists, which is the whole bug.

    It used to sit inside `#conflicts-section`, un-hidden only when
    `conflictsMap[eventId]` is non-empty. That map comes from
    `matcher.compute_conflicts`, which pairs an ASSIGNED event against ghost
    routes and therefore only ever keys by assigned event id — so the
    uncovered event this button exists for never had an entry, and the
    assigned events that did got a deal search for a day that already covers.
    """
    dash = _dashboard()
    check('id="find-a-way-btn"' in dash and 'findAWay()' in dash,
          "the button has to exist at all")
    conflicts_start, conflicts_end = _div_block(dash, '<div id="conflicts-section"')
    btn = dash.index('id="find-a-way-btn"')
    check(not (conflicts_start < btn < conflicts_end),
          "Find a way must NOT live inside the conflicts block — that block is "
          "keyed by assigned event id and never opens for an uncovered event")
    # It lives in the diagnostics tab, beside the block that IS populated for
    # an unassigned event.
    diag_start, diag_end = _div_block(dash, '<div id="tab-content-diagnostics"')
    check(diag_start < btn < diag_end,
          "and it must live in the diagnostics tab with the unassigned reason")
    check(diag_start < dash.index('id="view-unassigned-reason"') < diag_end,
          "which is where the per-event diagnostics are rendered")
    # And the thing that un-hides it is the unassigned condition, not conflicts.
    toggle = dash[dash.index("getElementById('find-a-way-section')"):][:600]
    check('currentData.diagnostics' in toggle and 'assignmentsMap' in toggle,
          f"visibility must key off the uncovered-event condition, got {toggle[:200]}")
    check('conflictsMap' not in toggle,
          "and never off the conflicts map again")
    # The tap really reaches the endpoint this file exercises above.
    body = dash[dash.index('async function findAWay()'):][:900]
    check("'api/negotiation/find'" in body,
          "and the tap posts to the search endpoint")


def scenario_the_deal_line_is_never_injected_as_html():
    """`deal.line` is built from calendar event titles, and a subscribed
    third-party calendar is somebody else's text inside this app's page."""
    dash = _dashboard()
    body = dash[dash.index('async function findAWay()'):][:1800]
    check('${data.deal.line}' not in body,
          "an event title must never be interpolated into innerHTML")
    check('textContent = data.deal.line' in body,
          "it goes in as text")


if __name__ == '__main__':
    scenario_the_endpoints_exist()
    scenario_find_a_way_is_reachable_on_an_uncovered_event()
    scenario_the_deal_line_is_never_injected_as_html()
    scenario_find_with_no_pack_is_honest()
    scenario_find_with_no_event_id_is_honest_too()
    scenario_killing_a_missing_deal_is_an_error_not_a_crash()
    scenario_asking_a_missing_deal_is_an_error_not_a_crash()
    scenario_a_learned_flag_can_be_untaught()
    scenario_clearing_a_flag_that_is_not_there_is_an_error_not_a_crash()
    scenario_a_child_actor_is_refused_on_every_route()
    print("test_negotiation_endpoints OK")
