"""Finding a real plan, refusing to invent one where inventing would hurt,
and never dressing an outage up as a finding.

An LLM will happily produce a twelve-week curriculum for anything, and it will
look exactly as good as the real one an expert spent a decade refining. The
answer to that is not silence -- a family with no plan at all is not safer,
just emptier -- it is LABELLING plus two hard limits that survive the move
from curating to generating: pacing stays arithmetic, and a made-up plan never
prescribes a load or a dose. These scenarios are what hold that line.
"""
from harness import check
from services import programs_curate


def _fake_research(facts, answer='', dropped=0):
    """The pages route: only what this app fetched itself is citable, and
    `sources` is everything the search returned, which is not."""
    return lambda q, read_pages=None: {
        'status': 'ok', 'answer': answer, 'facts': facts, 'via': 'pages',
        'sources': [{'title': 'Everything the search returned',
                     'url': 'https://example.invalid/never-read'}],
        'dropped': dropped}


def _fake_grounded(sources, answer='Justin Guitar is the standard beginner course.'):
    """The grounding route -- the default provider's -- where the whole answer
    arrives pinned to one source and every source behind it is a page the
    answer was actually built from."""
    return lambda q, read_pages=None: {
        'status': 'ok', 'answer': answer, 'via': 'grounding',
        'facts': [{'claim': answer, 'url': sources[0]['url']}],
        'sources': list(sources), 'dropped': 0}


def _fake_pool(payload):
    """Stands in for services/model_pools.py:call_pool_json, which
    programs_curate._pool_call wraps -- same indirection services/mind.py
    and services/web.py already use so a test can stub one attribute
    instead of reaching the network."""
    def f(tier, api_key, system, prompt, **kw):
        return payload
    return f


def _split_pool(shaping, generating, seen=None):
    """Two different calls go through one seam. Which one this is, is decided
    by the system prompt, so a scenario can assert that GENERATION happened
    rather than merely that something came back."""
    def f(tier, api_key, system, prompt, **kw):
        made = system is programs_curate.GENERATE_SYSTEM
        if seen is not None:
            seen.append('generate' if made else 'shape')
        return generating if made else shaping
    return f


def _settings(**over):
    base = {'programs_research_pages': 4, 'llm_gemini_api_key': 'k'}
    base.update(over)
    return lambda: base


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
        check(out['source']['origin'] == programs_curate.ORIGIN_CITED,
              f"and its tier is 'cited', got {out['source']}")
    finally:
        programs_curate.web.research = real_research
        programs_curate._pool_call = real_pool


def scenario_a_phase_may_cite_by_number():
    """The citation the model is ASKED for is an index, not a copied URL.

    Copying a long resolved URL exactly was the old requirement, and a single
    character of drift threw away an entire real plan -- which is most of why
    plans were arriving with no phases at all. An index cannot drift, and an
    index that names nothing is still dropped."""
    real_research = programs_curate.web.research
    real_pool = programs_curate._pool_call
    programs_curate.web.research = _fake_research([
        {'claim': 'Week 1 alternates 60 seconds running and 90 walking',
         'url': 'https://c25k.example/week1'},
        {'claim': 'Week 5 ends with a 20 minute continuous run',
         'url': 'https://c25k.example/week5'}])
    programs_curate._pool_call = _fake_pool({
        'phases': [
            {'name': 'Weeks 1-4', 'what': 'Run-walk intervals', 'cite': 1,
             'milestone': 'Eight minutes of running in a session'},
            {'name': 'Week 5', 'what': 'First continuous run', 'cite': '2',
             'milestone': 'Twenty unbroken minutes'},
            {'name': 'Nowhere', 'what': 'Cites an item that does not exist',
             'cite': 9, 'milestone': 'n/a'},
        ]})
    try:
        out = programs_curate.curate('run a 5K',
                                     {'sessions_per_week': 3, 'minutes': 30})
        names = [ph['name'] for ph in out['phases']]
        check(names == ['Weeks 1-4', 'Week 5'],
              f"index citations count and a dangling index does not, got {names}")
    finally:
        programs_curate.web.research = real_research
        programs_curate._pool_call = real_pool


def scenario_grounding_route_can_cite_every_page_behind_the_answer():
    """On the default route the whole answer used to be pinned to sources[0]
    and every other source thrown away, which left one URL to cite, one shot
    at citing it, and a runners-up list that was structurally always empty."""
    real_research = programs_curate.web.research
    real_pool = programs_curate._pool_call
    programs_curate.web.research = _fake_grounded([
        {'title': 'Justin Guitar beginner course', 'url': 'https://jg.example/'},
        {'title': 'Andy Guitar starter', 'url': 'https://andy.example/'},
        {'title': 'Fender Play', 'url': 'https://fender.example/'}])
    programs_curate._pool_call = _fake_pool({
        'plan_name': 'Justin Guitar',
        'why_this_one': 'It is free, sequenced, and made for total beginners.',
        'phases': [{'name': 'Grade 1', 'what': 'Open chords', 'cite': 1,
                    'milestone': 'G-C-D without looking'},
                   {'name': 'Grade 2', 'what': 'Barre chords', 'cite': 2,
                    'milestone': 'F for a whole song'}],
        'runners_up': [{'cite': 3, 'why_not': 'Costs a subscription.'}]})
    try:
        out = programs_curate.curate('learn guitar',
                                     {'sessions_per_week': 3, 'minutes': 25})
        src = out['source']
        check(len(out['phases']) == 2,
              f"both cited phases survive, got {out['phases']}")
        check(src['plan_name'] == 'Justin Guitar',
              f"a plan name found in the material is kept, got {src}")
        check(len(src['runners_up']) >= 1,
              f"the other candidates must reach the card, got {src['runners_up']}")
        check(any(r['why_not'] == 'Costs a subscription.'
                  for r in src['runners_up']),
              f"with the model's own reason, not a canned one, got {src['runners_up']}")
        check(src['why_this_one'].startswith('It is free'),
              f"and the argument for the pick is carried, got {src['why_this_one']}")
    finally:
        programs_curate.web.research = real_research
        programs_curate._pool_call = real_pool


def scenario_a_plan_name_not_in_the_material_is_not_shown():
    """The model naming the program it organised beats taking the answer's
    first sentence -- but only while the name cannot be invented. "Following
    <a plausible thing>" over a link that never said it is the exact failure
    this module exists to prevent."""
    real_research = programs_curate.web.research
    real_pool = programs_curate._pool_call
    programs_curate.web.research = _fake_grounded(
        [{'title': 'A county library reading ladder', 'url': 'https://lib.example/'}],
        answer='The county library publishes a graded reading ladder.')
    programs_curate._pool_call = _fake_pool({
        'plan_name': 'The Oxford Reading Programme',
        'phases': [{'name': 'Ladder 1', 'what': 'Short chapter books',
                    'cite': 1, 'milestone': 'One book finished'}]})
    try:
        out = programs_curate.curate('read a book a month',
                                     {'sessions_per_week': 3, 'minutes': 20})
        check(out['source']['plan_name'] == '',
              f"an unverifiable plan name must not reach the card, got "
              f"{out['source']['plan_name']!r}")
        check(out['phases'], "the cited phases still stand")
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


def scenario_nothing_found_becomes_a_labelled_plan_not_a_bare_week():
    """Research ran and the web had nothing to cite. The old answer was an
    empty plan and a calendar reservation labelled "written by hand", which
    named something nobody had done. Now a plan is made and SAYS it was made:
    no plan name, no source link, and a tier a screen can render honestly."""
    real_research = programs_curate.web.research
    real_pool = programs_curate._pool_call
    seen = []
    programs_curate.web.research = _fake_research([], answer='Just practise a lot!')
    programs_curate._pool_call = _split_pool(
        {'phases': []},
        {'why_this_one': 'Nothing published covers this, so it builds up in steps.',
         'phases': [
             {'name': 'Get the motion', 'what': 'Practise the throw slowly',
              'milestone': 'Ten clean throws in a row'},
             {'name': 'Join it up', 'what': 'Run the whole sequence',
              'milestone': 'The sequence, start to finish'}]},
        seen)
    try:
        out = programs_curate.curate(
            'learn to juggle scarves', {'sessions_per_week': 2, 'minutes': 20})
        src = out['source']
        check('generate' in seen, f"generation must actually run, got {seen}")
        check(len(out['phases']) == 2,
              f"the family gets a plan to follow, got {out['phases']}")
        check(src['origin'] == programs_curate.ORIGIN_GENERATED,
              f"labelled as the app's own, got {src}")
        check(src['plan_name'] == '' and src['url'] == '',
              f"a made plan never names a program or links a source, got {src}")
        check(src['hand_written'] is True,
              "and it is still not a cited plan, for readers that only know "
              "the old field")
        check(all(ph['weeks'] == programs_curate.phase_weeks(2)
                  for ph in out['phases']),
              f"pacing stays arithmetic in the generated tier too, got "
              f"{out['phases']}")
    finally:
        programs_curate.web.research = real_research
        programs_curate._pool_call = real_pool


def scenario_an_outage_is_never_papered_over_with_a_made_plan():
    """"The research call did not run" is a retry, not a gap in the world's
    curricula. Generating here would dress an outage up as a finding, and the
    family would never know there was anything to try again."""
    real_research = programs_curate.web.research
    real_pool = programs_curate._pool_call
    seen = []
    programs_curate._pool_call = _split_pool({'phases': []}, {'phases': []}, seen)
    try:
        for status, reason in (('disabled', 'disabled'), ('no_key', 'no_key'),
                               ('capped', 'capped')):
            programs_curate.web.research = (
                lambda *a, _s=status, **kw: {'status': _s})
            out = programs_curate.curate('learn guitar',
                                         {'sessions_per_week': 3, 'minutes': 25})
            src = out['source']
            check(out['phases'] == [], f"no phases for {status}, got {out}")
            check(src['origin'] == programs_curate.ORIGIN_NONE,
                  f"{status} is the 'none' tier, got {src}")
            check(src['reason'] == reason,
                  f"and says which outage it was, got {src}")
            check(src['why_this_one'] == programs_curate.REASON_TEXT[reason],
                  f"in words a person can read, got {src['why_this_one']!r}")
        check(seen == [], f"and no model call may fire at all, got {seen}")
    finally:
        programs_curate.web.research = real_research
        programs_curate._pool_call = real_pool


def scenario_generation_is_refused_where_a_wrong_step_injures():
    """Curating these is untouched -- an expert's swim progression is exactly
    what this module wants to find. What is refused is the app WRITING one,
    in the domains where a plausible wrong number is an injury rather than a
    wasted month."""
    real_research = programs_curate.web.research
    real_pool = programs_curate._pool_call
    seen = []
    programs_curate.web.research = _fake_research([], answer='')
    programs_curate._pool_call = _split_pool({'phases': []},
                                             {'phases': [{'name': 'x',
                                                          'what': 'y'}]}, seen)
    try:
        for aim in ('swim a mile', 'learn to deadlift', 'train for a marathon',
                    'start intermittent fasting'):
            check(programs_curate.generation_allowed(aim) is False,
                  f"'{aim}' must not get a made-up plan")
            out = programs_curate.curate(aim, {'sessions_per_week': 3,
                                               'minutes': 30})
            check(out['source']['reason'] == 'generation_refused',
                  f"'{aim}' says why it has no plan, got {out['source']}")
            check(out['phases'] == [], f"and carries no phases, got {out}")
        check('generate' not in seen,
              f"and no generation call may fire for these, got {seen}")
        for aim in ('learn guitar', 'read a book a month', 'learn to juggle'):
            check(programs_curate.generation_allowed(aim) is True,
                  f"'{aim}' is an ordinary aim and may have a made plan")
    finally:
        programs_curate.web.research = real_research
        programs_curate._pool_call = real_pool


def scenario_a_plan_that_changes_language_is_repaired_then_dropped():
    """A real generated plan came back with its first two phases in English
    and its third in Vietnamese -- an interactive-tier model drifting
    mid-response. A phase nobody in the house can read is not a phase, and
    dropping it silently would leave a plan with a hole in the middle, so one
    repair pass runs first and the drop is the fallback."""
    real_research = programs_curate.web.research
    real_pool = programs_curate._pool_call
    programs_curate.web.research = _fake_research([], answer='')
    drifted = {'phases': [
        {'name': 'Phase One', 'what': 'Learn the basic movements slowly',
         'milestone': 'You can move through them with control'},
        {'name': 'Phase Three',
         'what': 'Bạn nên có khả năng thực hiện trọn vẹn các bài tập phức hợp',
         'milestone': 'với nhịp độ ổn định và kiểm soát hoàn toàn'}]}
    clean = {'phases': [
        {'name': 'Phase One', 'what': 'Learn the basic movements slowly',
         'milestone': 'You can move through them with control'},
        {'name': 'Phase Two', 'what': 'Put the movements into sequences',
         'milestone': 'You can hold a sequence without losing form'}]}

    calls = []

    def _drift_then_clean(tier, api_key, system, prompt, **kw):
        if system is programs_curate.GENERATE_SYSTEM:
            calls.append('generate')
            return drifted
        if 'in no other' in system:          # the repair pass
            calls.append('repair')
            return clean
        return {'phases': []}

    def _always_drift(tier, api_key, system, prompt, **kw):
        return {'phases': []} if system is programs_curate.PHASE_SYSTEM else drifted

    try:
        programs_curate._pool_call = _drift_then_clean
        out = programs_curate.curate('strength training',
                                     {'sessions_per_week': 3, 'minutes': 30})
        check(calls == ['generate', 'repair'],
              f"drift must trigger exactly one repair pass, got {calls}")
        check(len(out['phases']) == 2,
              f"and the repaired plan is whole, got {out['phases']}")

        programs_curate._pool_call = _always_drift
        out = programs_curate.curate('strength training',
                                     {'sessions_per_week': 3, 'minutes': 30})
        names = [ph['name'] for ph in out['phases']]
        check(names == ['Phase One'],
              f"a phase that still cannot be read is dropped, got {names}")
    finally:
        programs_curate.web.research = real_research
        programs_curate._pool_call = real_pool


def scenario_the_language_check_never_fires_on_the_household_own_words():
    """The test is one-directional on purpose: the AIM decides. A family that
    writes its aims in Vietnamese must never have its plan thrown away, and
    one borrowed word in an English sentence must never look like drift."""
    vi = 'Bạn nên có khả năng thực hiện trọn vẹn các bài tập phức hợp'
    check(programs_curate._looks_foreign(vi, 'strength training') is True,
          "an English aim with a Vietnamese phase is drift")
    check(programs_curate._looks_foreign(vi, 'Tập luyện sức mạnh') is False,
          "the same phase under a Vietnamese aim is the household's own language")
    for ok in ('Practise the café routine',
               'A naïve first attempt at the résumé exercise today',
               'You should be able to move smoothly through the patterns'):
        check(programs_curate._looks_foreign(ok, 'strength training') is False,
              f"a borrowed word is not another language: {ok!r}")


def scenario_a_cited_phase_is_held_to_the_same_language_rule():
    real_research = programs_curate.web.research
    real_pool = programs_curate._pool_call
    programs_curate.web.research = _fake_research([
        {'claim': 'Week 1 alternates running and walking',
         'url': 'https://c25k.example/week1'}])
    programs_curate._pool_call = _fake_pool({
        'phases': [
            {'name': 'Weeks 1-4', 'what': 'Run-walk intervals', 'cite': 1,
             'milestone': 'Eight minutes of running'},
            {'name': 'Giai đoạn hai', 'cite': 1,
             'what': 'Bạn nên có khả năng chạy liên tục trong hai mươi phút',
             'milestone': 'với nhịp độ ổn định'},
        ]})
    try:
        out = programs_curate.curate('run a 5K',
                                     {'sessions_per_week': 3, 'minutes': 30})
        names = [ph['name'] for ph in out['phases']]
        check(names == ['Weeks 1-4'],
              f"a cited phase in another language is dropped too, got {names}")
    finally:
        programs_curate.web.research = real_research
        programs_curate._pool_call = real_pool


def scenario_a_made_plan_that_prescribes_a_load_is_dropped():
    """The one rule that survives from curating into generating, alongside
    pacing: a made-up plan describes the practice, never the numbers an
    expert earns the right to set. A phase carrying one is dropped exactly
    like an uncited phase, and if that empties the plan the family is told."""
    real_research = programs_curate.web.research
    real_pool = programs_curate._pool_call
    programs_curate.web.research = _fake_research([], answer='')
    programs_curate._pool_call = _split_pool(
        {'phases': []},
        {'phases': [
            {'name': 'Build up', 'what': 'Work up to 3 sets of 12 reps',
             'milestone': 'Add 10 lbs'},
            {'name': 'Also this', 'what': 'Take 500 mg before each session',
             'milestone': 'n/a'}]})
    try:
        out = programs_curate.curate('get stronger at push-ups',
                                     {'sessions_per_week': 3, 'minutes': 20})
        check(out['phases'] == [],
              f"every load-prescribing phase is dropped, got {out['phases']}")
        check(out['source']['reason'] == 'load_prescribed',
              f"and the reason says so rather than 'nothing came back', got "
              f"{out['source']}")
    finally:
        programs_curate.web.research = real_research
        programs_curate._pool_call = real_pool


def scenario_a_household_can_switch_made_plans_off():
    """Generating is a default, not a mandate. Off means the old behaviour
    exactly: practice time, no plan, and a sentence saying which it is."""
    real_research = programs_curate.web.research
    real_pool = programs_curate._pool_call
    real_settings = programs_curate.storage.get_settings
    seen = []
    programs_curate.web.research = _fake_research([], answer='')
    programs_curate.storage.get_settings = _settings(
        programs_generate_enabled=False)
    programs_curate._pool_call = _split_pool({'phases': []},
                                             {'phases': [{'name': 'x',
                                                          'what': 'y'}]}, seen)
    try:
        out = programs_curate.curate('learn to juggle',
                                     {'sessions_per_week': 2, 'minutes': 20})
        check(out['phases'] == [], f"no plan when it is switched off, got {out}")
        check(out['source']['reason'] == 'generation_off',
              f"and it says that is why, got {out['source']}")
        check('generate' not in seen,
              f"and nothing was generated behind the setting, got {seen}")
    finally:
        programs_curate.web.research = real_research
        programs_curate._pool_call = real_pool
        programs_curate.storage.get_settings = real_settings


def scenario_shaping_failure_is_not_a_crash():
    """Research succeeded and read real pages, but the phase-shaping call
    itself failed -- raised, or came back with an error payload. With the
    generation call failing the same way, the program still comes back
    honest and whole rather than broken."""
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
                  f"no phases when every call failed ({broken.__name__}), got {out}")
            check(out['source']['hand_written'] is True,
                  f"a total failure is not a cited plan, got {out}")
            check(out['source']['reason'] == 'generation_failed',
                  f"and says what failed, got {out['source']}")
    finally:
        programs_curate.web.research = real_research
        programs_curate._pool_call = real_pool


def scenario_research_being_off_is_not_an_invented_plan():
    real = programs_curate.web.research
    programs_curate.web.research = lambda *a, **kw: {'status': 'disabled'}
    try:
        out = programs_curate.curate('learn guitar', {'sessions_per_week': 3,
                                                      'minutes': 25})
        check(out['source']['hand_written'] is True,
              "no research means no cited plan, never a confident guess")
        check(out['source']['origin'] == programs_curate.ORIGIN_NONE,
              f"and no made plan either, got {out['source']}")
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
    scenario_a_phase_may_cite_by_number()
    scenario_grounding_route_can_cite_every_page_behind_the_answer()
    scenario_a_plan_name_not_in_the_material_is_not_shown()
    scenario_pacing_is_computed_not_dictated()
    scenario_nothing_found_becomes_a_labelled_plan_not_a_bare_week()
    scenario_an_outage_is_never_papered_over_with_a_made_plan()
    scenario_generation_is_refused_where_a_wrong_step_injures()
    scenario_a_plan_that_changes_language_is_repaired_then_dropped()
    scenario_the_language_check_never_fires_on_the_household_own_words()
    scenario_a_cited_phase_is_held_to_the_same_language_rule()
    scenario_a_made_plan_that_prescribes_a_load_is_dropped()
    scenario_a_household_can_switch_made_plans_off()
    scenario_shaping_failure_is_not_a_crash()
    scenario_research_being_off_is_not_an_invented_plan()
    scenario_ordinary_aims_are_not_refused_as_body_goals()
    scenario_every_real_body_aim_still_refuses()
    print("test_programs_curate OK")
