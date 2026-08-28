"""Finding a real plan, and refusing to invent one.

An LLM will happily produce a twelve-week curriculum for anything, and it will
look exactly as good as the real one an expert spent a decade refining. These
scenarios are what stops that.
"""
from harness import check
from services import programs_curate


def _fake_research(facts, answer='', dropped=0):
    return lambda q, read_pages=None: {
        'status': 'ok', 'answer': answer, 'facts': facts,
        'sources': [{'title': 'Everything the search returned',
                     'url': 'https://example.invalid/never-read'}],
        'dropped': dropped}


def _fake_pool(payload):
    """Stands in for services/model_pools.py:call_pool_json, which
    programs_curate._pool_call wraps -- same indirection services/mind.py
    and services/web.py already use so a test can stub one attribute
    instead of reaching the network."""
    def f(tier, api_key, system, prompt, **kw):
        return payload
    return f


def scenario_a_body_aim_is_refused_before_any_research():
    """The screen is deterministic and runs FIRST. A safety line that depends
    on a model's judgement is a safety line with a bad night."""
    called = []
    real = programs_curate.web.research
    programs_curate.web.research = lambda *a, **kw: called.append(1)
    try:
        for aim in ('lose 15 pounds', 'get to 12% body fat',
                    'hit my goal weight', 'stay under 1800 calories'):
            res = programs_curate.screen_aim(aim)
            check(res['ok'] is False, f"'{aim}' must be refused, got {res}")
            check(res.get('alternatives'),
                  f"and offered a behaviour-shaped alternative, got {res}")
        check(called == [], "and no research call may fire for a refused aim")
    finally:
        programs_curate.web.research = real


def scenario_a_behaviour_aim_passes_the_screen():
    for aim in ('play campfire songs by summer', 'run a 5K in June',
                'cook at home five nights a week'):
        check(programs_curate.screen_aim(aim)['ok'] is True,
              f"'{aim}' is a behaviour goal and must pass")


def scenario_a_phase_that_cites_nothing_is_dropped():
    """Two candidate phases come back from shaping; only the one citing a
    page the app actually read survives."""
    real_research = programs_curate.web.research
    real_pool = programs_curate._pool_call
    programs_curate.web.research = _fake_research([
        {'claim': 'Grade 1 module 1 covers three open chords',
         'url': 'https://justinguitar.example/grade1'}])
    programs_curate._pool_call = _fake_pool({
        'phases': [
            {'name': 'Grade 1', 'weeks': 4,
             'what': 'Three open chords, switching cleanly',
             'milestone': 'Play G-C-D without looking',
             'url': 'https://justinguitar.example/grade1'},
            {'name': 'Invented Phase', 'weeks': 4,
             'what': 'Something no page actually said',
             'milestone': 'n/a',
             'url': 'https://not-a-real-source.example'},
        ]})
    try:
        out = programs_curate.curate(
            'play campfire songs', {'sessions_per_week': 3, 'minutes': 25},
            member_name='Lily')
        check(len(out['phases']) == 1,
              f"the uncited phase must be dropped, got {out['phases']}")
        for ph in out['phases']:
            check(ph.get('what'), f"a phase says what to do, got {ph}")
        check(any(f['url'] for f in out['source']['facts']),
              "and the plan carries the page it came from")
        check(out['source']['hand_written'] is False,
              "a cited plan is not hand-written")
    finally:
        programs_curate.web.research = real_research
        programs_curate._pool_call = real_pool


def scenario_pacing_is_computed_not_dictated():
    """weeks is arithmetic over what the family can actually do, not a
    number the model gets to pick -- the design's central pacing rule. The
    model's own 'weeks' field, if it sends one, is ignored entirely."""
    real_research = programs_curate.web.research
    real_pool = programs_curate._pool_call
    programs_curate.web.research = _fake_research([
        {'claim': 'Grade 1 module 1 covers three open chords',
         'url': 'https://justinguitar.example/grade1'}])
    programs_curate._pool_call = _fake_pool({
        'phases': [{'name': 'Grade 1', 'weeks': 999,
                    'what': 'Three open chords, switching cleanly',
                    'milestone': 'Play G-C-D without looking',
                    'url': 'https://justinguitar.example/grade1'}]})
    try:
        fast = programs_curate.curate(
            'play campfire songs', {'sessions_per_week': 6, 'minutes': 25})
        slow = programs_curate.curate(
            'play campfire songs', {'sessions_per_week': 2, 'minutes': 25})
        check(fast['phases'][0]['weeks'] != 999,
              f"the model's own weeks field must be ignored, got {fast['phases']}")
        check(fast['phases'][0]['weeks'] < slow['phases'][0]['weeks'],
              f"more sessions a week must mean fewer weeks for the same "
              f"material, got fast={fast['phases'][0]['weeks']} "
              f"slow={slow['phases'][0]['weeks']}")
    finally:
        programs_curate.web.research = real_research
        programs_curate._pool_call = real_pool


def scenario_shaping_failure_is_hand_written_not_a_crash():
    """The fourth path to hand_written: research succeeded and read real
    pages, but the phase-shaping call itself failed -- raised, or came back
    with an error payload. The program still comes back honest, not broken."""
    real_research = programs_curate.web.research
    real_pool = programs_curate._pool_call
    programs_curate.web.research = _fake_research([
        {'claim': 'Grade 1 module 1 covers three open chords',
         'url': 'https://justinguitar.example/grade1'}])

    def _raises(tier, api_key, system, prompt, **kw):
        raise RuntimeError('pool exhausted')

    def _errors(tier, api_key, system, prompt, **kw):
        return {'error': 'no models available', 'transient': False}

    try:
        for broken in (_raises, _errors):
            programs_curate._pool_call = broken
            out = programs_curate.curate(
                'play campfire songs', {'sessions_per_week': 3, 'minutes': 25})
            check(out['phases'] == [],
                  f"no phases when shaping failed ({broken.__name__}), got {out}")
            check(out['source']['hand_written'] is True,
                  f"shaping failure must be hand_written, not a crash, got {out}")
    finally:
        programs_curate.web.research = real_research
        programs_curate._pool_call = real_pool


def scenario_nothing_cited_means_hand_written():
    """Research came back with no facts at all — no page was read. The honest
    answer is to say so, not to fill the gap with fluent guesswork."""
    real = programs_curate.web.research
    programs_curate.web.research = _fake_research([], answer='Just practise a lot!')
    try:
        out = programs_curate.curate(
            'learn to juggle chainsaws', {'sessions_per_week': 2, 'minutes': 20})
        check(out['source']['hand_written'] is True,
              f"with nothing read, the program is hand-written, got {out['source']}")
        check(out['source']['facts'] == [], "and carries no citations")
        check(out['source']['plan_name'] == '',
              "and does not name a plan it did not find")
    finally:
        programs_curate.web.research = real


def scenario_research_being_off_is_not_an_invented_plan():
    real = programs_curate.web.research
    programs_curate.web.research = lambda *a, **kw: {'status': 'disabled'}
    try:
        out = programs_curate.curate('learn guitar', {'sessions_per_week': 3,
                                                      'minutes': 25})
        check(out['source']['hand_written'] is True,
              "no research means hand-written, never a confident guess")
    finally:
        programs_curate.web.research = real


def scenario_ordinary_aims_are_not_refused_as_body_goals():
    """The screen accepts false refusals on purpose -- but not these. Matched
    as bare substrings, 'thin' refused "learn to build things with wood" and
    "get everything ready for the science fair", and 'abs' refused "learn
    abseiling", each with the target-weights sentence. A kid reading that has
    no way to tell which of their words the app objected to."""
    for aim in ('learn to build things with wood',
                'get everything ready for the science fair',
                'learn abseiling',
                'read a book a month',
                'get better at things i find hard'):
        res = programs_curate.screen_aim(aim)
        check(res['ok'] is True,
              f"'{aim}' is an ordinary aim and must pass, got {res}")


def scenario_every_real_body_aim_still_refuses():
    """The other direction, in the same round: word boundaries must not have
    quietly opened the door the screen exists to hold shut."""
    for aim in ('lose 15 pounds', 'hit my goal weight', 'get to 12% body fat',
                'stay under 1800 calories', 'get skinny for summer',
                'start a diet', 'track my bmi', 'get abs by june',
                'drop 10 lbs', 'calorie deficit', 'slim down', 'six pack'):
        res = programs_curate.screen_aim(aim)
        check(res['ok'] is False, f"'{aim}' must still be refused, got {res}")
        check(res.get('alternatives'),
              f"and still offered the behaviour version, got {res}")


if __name__ == '__main__':
    scenario_a_body_aim_is_refused_before_any_research()
    scenario_a_behaviour_aim_passes_the_screen()
    scenario_a_phase_that_cites_nothing_is_dropped()
    scenario_pacing_is_computed_not_dictated()
    scenario_shaping_failure_is_hand_written_not_a_crash()
    scenario_nothing_cited_means_hand_written()
    scenario_research_being_off_is_not_an_invented_plan()
    scenario_ordinary_aims_are_not_refused_as_body_goals()
    scenario_every_real_body_aim_still_refuses()
    print("test_programs_curate OK")
