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
              'steps': ['One scarf, hand to hand, 20 throws',
                        'Two scarves, one throw each, 10 rounds'],
              'milestone': 'Ten clean throws in a row'},
             {'name': 'Join it up', 'what': 'Run the whole sequence',
              'steps': ['Three scarves, cascade, 5 rounds'],
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
    programs_curate._pool_call = _split_pool(
        {'phases': []},
        {'phases': [{'name': 'x', 'what': 'y', 'steps': ['z']}]}, seen)
    try:
        for aim in ('swim a mile', 'scuba diving', 'train for a marathon',
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
         'steps': ['8 bodyweight squats, slowly'],
         'milestone': 'You can move through them with control'},
        {'name': 'Phase Three',
         'what': 'Bạn nên có khả năng thực hiện trọn vẹn các bài tập phức hợp',
         'steps': ['Bạn nên tập luyện đều đặn mỗi tuần một lần'],
         'milestone': 'với nhịp độ ổn định và kiểm soát hoàn toàn'}]}
    clean = {'phases': [
        {'name': 'Phase One', 'what': 'Learn the basic movements slowly',
         'steps': ['8 bodyweight squats, slowly'],
         'milestone': 'You can move through them with control'},
        {'name': 'Phase Two', 'what': 'Put the movements into sequences',
         'steps': ['3 rounds of squat, push-up, row'],
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


def scenario_a_made_plan_that_prescribes_load_or_a_dose_is_dropped():
    """Counting is not prescribing. "Three sets of eight" is what a workout
    IS, and a plan forbidden from saying it comes back as the mush this rule
    was rewritten over -- "move smoothly through all basic bodyweight
    patterns with complete control", which nobody can follow. What stays
    refused is EXTERNAL LOAD and INTAKE: pounds on a bar, a percentage of a
    max, milligrams of anything."""
    real_research = programs_curate.web.research
    real_pool = programs_curate._pool_call
    programs_curate.web.research = _fake_research([], answer='')
    programs_curate._pool_call = _split_pool(
        {'phases': []},
        {'phases': [
            {'name': 'Build up', 'what': 'Three rounds of the circuit',
             'steps': ['3 sets of 8 goblet squats',
                       'Work up to 185 lbs on the bar',
                       '5 rounds of 30 seconds hanging',
                       'Take 500 mg of creatine before each session'],
             'milestone': 'The circuit start to finish'},
            {'name': 'Also this', 'what': 'Add 20 kg to every lift',
             'milestone': 'n/a'}]})
    try:
        out = programs_curate.curate('get stronger at push-ups',
                                     {'sessions_per_week': 3, 'minutes': 20})
        check(len(out['phases']) == 1,
              f"the phase prescribing kilos is dropped whole, got {out['phases']}")
        steps = out['phases'][0]['steps']
        check(steps == ['3 sets of 8 goblet squats',
                        '5 rounds of 30 seconds hanging'],
              f"sets and rounds stay, pounds and milligrams go, got {steps}")
    finally:
        programs_curate.web.research = real_research
        programs_curate._pool_call = real_pool


def scenario_a_plan_with_nothing_but_load_prescriptions_says_so():
    real_research = programs_curate.web.research
    real_pool = programs_curate._pool_call
    programs_curate.web.research = _fake_research([], answer='')
    programs_curate._pool_call = _split_pool(
        {'phases': []},
        {'phases': [{'name': 'Build up', 'what': 'Work up to 185 lbs',
                     'milestone': 'Add 10 lbs a week'}]})
    try:
        out = programs_curate.curate('get stronger at push-ups',
                                     {'sessions_per_week': 3, 'minutes': 20})
        check(out['phases'] == [], f"nothing survives, got {out['phases']}")
        check(out['source']['reason'] == 'load_prescribed',
              f"and the reason says which rule emptied it, got {out['source']}")
    finally:
        programs_curate.web.research = real_research
        programs_curate._pool_call = real_pool


def scenario_a_phase_carries_the_session_itself():
    """The gap that made a generated strength program worthless: `what` is a
    paragraph ABOUT the phase and `milestone` is how you know it ended, and
    neither of them is the workout. A person opening this wants to know what
    to do on Tuesday."""
    real_research = programs_curate.web.research
    real_pool = programs_curate._pool_call
    programs_curate.web.research = _fake_research([
        {'claim': 'Grade 1 covers three open chords',
         'url': 'https://justinguitar.example/grade1'}])
    programs_curate._pool_call = _fake_pool({
        'phases': [{'name': 'Grade 1', 'cite': 1, 'what': 'Open chords',
                    'steps': ['One minute changes: G to C',
                              'Play through Knockin on Heavens Door',
                              '  ', ''],
                    'milestone': 'G-C-D without looking'}]})
    try:
        out = programs_curate.curate('learn guitar',
                                     {'sessions_per_week': 3, 'minutes': 25})
        steps = out['phases'][0]['steps']
        check(steps == ['One minute changes: G to C',
                        'Play through Knockin on Heavens Door'],
              f"a cited phase carries its own content, blanks dropped, got {steps}")
    finally:
        programs_curate.web.research = real_research
        programs_curate._pool_call = real_pool


def scenario_the_generation_screen_refuses_the_activity_not_the_word():
    """The first cut refused every barbell lift, which drew the line around
    the wrong thing: the hazard is a number nobody earned the right to set,
    and that is blocked structurally. Naming the squat is not the hazard --
    squats are what strength training IS, and refusing the word cost the
    family the only thing they wanted from the plan."""
    for aim in ('learn to deadlift', 'strength training', 'get better at squats',
                'bench press with my son'):
        check(programs_curate.generation_allowed(aim) is True,
              f"'{aim}' is ordinary movement and may have a made plan")
    for aim in ('swim a mile', 'train for a marathon', 'start intermittent fasting',
                'free solo a route', 'hit a 300 lb one rep max'):
        check(programs_curate.generation_allowed(aim) is False,
              f"'{aim}' is a hazard no vagueness fixes and must not")


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
    programs_curate._pool_call = _split_pool(
        {'phases': []},
        {'phases': [{'name': 'x', 'what': 'y', 'steps': ['z']}]}, seen)
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


def _capture_pool(payload, sink):
    """Same seam as `_fake_pool`, but the PROMPT is kept. What a plan is told
    about the family is the whole subject of the scenarios below, and it is
    invisible from the answer alone."""
    def f(tier, api_key, system, prompt, **kw):
        sink.append(prompt)
        return payload
    return f


def _birthdate(years_ago):
    import datetime
    d = datetime.date.today()
    return d.replace(year=d.year - years_ago).isoformat()


_MADE = {'why_this_one': 'Nothing published fits, so here is one.',
         'phases': [{'name': 'Base', 'what': 'Learn the shape of it',
                     'steps': ['Three throws, one ball, twenty times'],
                     'progression': 'Add one throw before you add a ball',
                     'milestone': 'Twenty clean throws in a row'}]}


def scenario_a_made_plan_is_written_for_this_person_and_this_hour():
    """The bug that made every generated plan generic.

    `curate` has always known the session length and the cited path has
    always passed it; the generated path was handed the aim and a number of
    evenings and nothing else. A family with twenty-minute evenings got a
    plan built for an hour, and no surface anywhere said the two disagreed.
    Age is the same omission one level up: a plan for a nine-year-old and a
    plan for an adult are different documents in every domain there is.
    """
    real_research = programs_curate.web.research
    real_pool = programs_curate._pool_call
    real_settings = programs_curate.storage.get_settings
    seen = []
    programs_curate.web.research = _fake_research([])
    programs_curate.storage.get_settings = _settings()
    programs_curate._pool_call = _capture_pool(_MADE, seen)
    try:
        out = programs_curate.curate(
            'learn to juggle', {'sessions_per_week': 2, 'minutes': 20},
            member={'name': 'Lily', 'role': 'child',
                    'birthdate': _birthdate(9)})
        check(out['phases'], f"a plan still comes back, got {out}")
        check(seen, "the generation call really happened")
        prompt = seen[-1]
        check('20 minutes' in prompt,
              f"the session length has to reach the plan, got:\n{prompt}")
        check('9 years old' in prompt,
              f"and so does who is following it, got:\n{prompt}")
    finally:
        programs_curate.web.research = real_research
        programs_curate._pool_call = real_pool
        programs_curate.storage.get_settings = real_settings


def scenario_an_age_is_never_guessed():
    """`stages.age_of` returns None rather than a zero for a member with no
    birthdate, and this is why: the one fact that decides the plan must not
    be invented from a role, a stage or a name."""
    check('an adult' in programs_curate._who_line({'name': 'Jeff',
                                                   'role': 'parent'}),
          "an adult with no birthdate is an adult, not an age")
    line = programs_curate._who_line({'name': 'Sam', 'role': 'child'})
    check('a child' in line and 'years old' not in line,
          f"a child with no birthdate gets no number, got {line}")


def scenario_the_starting_point_reaches_the_plan():
    """A plan written for a generic beginner is the commonest way a real plan
    is useless. This is the household's own sentence about where they are."""
    real_research = programs_curate.web.research
    real_pool = programs_curate._pool_call
    real_settings = programs_curate.storage.get_settings
    seen = []
    programs_curate.web.research = _fake_research([])
    programs_curate.storage.get_settings = _settings()
    programs_curate._pool_call = _capture_pool(_MADE, seen)
    try:
        programs_curate.curate(
            'learn guitar', {'sessions_per_week': 3, 'minutes': 30},
            member={'name': 'Lily', 'role': 'parent'},
            starting_point='already plays open chords, owns a guitar')
        check('already plays open chords' in seen[-1],
              f"what they can already do has to reach it, got:\n{seen[-1]}")
    finally:
        programs_curate.web.research = real_research
        programs_curate._pool_call = real_pool
        programs_curate.storage.get_settings = real_settings


def scenario_the_body_screen_covers_the_starting_point_too():
    """`screen_aim` guards the aim and nothing else, so the moment a second
    free-text field reaches a prompt it is a door beside the locked one."""
    for text in ('I weigh 200 lbs and want to be 170', 'currently 30% body fat',
                 'eating about 1800 calories a day'):
        res = programs_curate.screen_starting_point(text)
        check(res['ok'] is False,
              f"'{text}' is the refused aim typed one box lower, got {res}")
        check(res.get('alternatives'),
              f"and it offers the behaviour version, got {res}")
    for text in ('', 'already plays open chords', 'reads chapter books alone'):
        check(programs_curate.screen_starting_point(text)['ok'] is True,
              f"'{text}' is an ordinary starting point and must pass")


def scenario_a_phase_says_how_to_beat_the_last_session():
    """The missing half of pacing. Phases escalate over months and a
    milestone says when one ended; between the two there was nothing telling
    anybody that Tuesday should be a notch past last Tuesday."""
    real_research = programs_curate.web.research
    real_pool = programs_curate._pool_call
    real_settings = programs_curate.storage.get_settings
    programs_curate.web.research = _fake_research([])
    programs_curate.storage.get_settings = _settings()
    programs_curate._pool_call = _fake_pool({
        'why_this_one': 'made',
        'phases': [
            {'name': 'Base', 'what': 'Learn the shape',
             'steps': ['Twenty throws'],
             'progression': 'Add one throw before you add a ball',
             'milestone': 'Twenty clean throws'},
            {'name': 'Load', 'what': 'More of it',
             'steps': ['Thirty throws'],
             'progression': 'Add 10 lbs to the bar each week',
             'milestone': 'Thirty clean throws'},
        ]})
    try:
        out = programs_curate.curate('learn to juggle',
                                     {'sessions_per_week': 3, 'minutes': 20})
        rules = [ph.get('progression') for ph in out['phases']]
        check(rules[0] == 'Add one throw before you add a ball',
              f"a relative rule is exactly what this field is for, got {rules}")
        check(rules[1] == '',
              f"a number on a bar is not, and is stripped, got {rules}")
        check(out['phases'][1]['steps'],
              f"and stripping it costs the phase nothing else, "
              f"got {out['phases'][1]}")
    finally:
        programs_curate.web.research = real_research
        programs_curate._pool_call = real_pool
        programs_curate.storage.get_settings = real_settings


def scenario_a_rotation_of_one_is_not_a_rotation():
    """Half a rotation is worse than none: a Tuesday labelled 'Session B'
    with nothing in it is a dead end, and one labelled session is a list of
    steps wearing a hat."""
    aim = 'learn to juggle'
    check(programs_curate._clean_rotation(
        [{'label': 'A', 'steps': ['Throws']}], aim) == [],
        "one session is not a rotation")
    check(programs_curate._clean_rotation(
        [{'label': 'A', 'steps': ['Throws']}, {'label': 'B', 'steps': []}],
        aim) == [], "and an empty session cannot make it two")
    out = programs_curate._clean_rotation(
        [{'label': 'Technique', 'steps': ['Three-ball cascade']},
         {'label': 'Material', 'steps': ['Run the routine twice']}], aim)
    check(len(out) == 2 and out[0]['label'] == 'Technique',
          f"two real sessions are a rotation, got {out}")
    loaded = programs_curate._clean_rotation(
        [{'label': 'A', 'steps': ['Squat with 185 lbs']},
         {'label': 'B', 'steps': ['Row 40 kg']}], aim)
    check(loaded == [],
          f"and every step goes through the load screen, got {loaded}")


def scenario_a_rotation_fills_the_steps_it_replaces():
    """`steps` stays the phase's material so every surface written before
    rotations existed keeps drawing something true -- and the empty-steps
    gate, which is what makes 'be concrete' real, keeps meaning something."""
    real_research = programs_curate.web.research
    real_pool = programs_curate._pool_call
    real_settings = programs_curate.storage.get_settings
    programs_curate.web.research = _fake_research([])
    programs_curate.storage.get_settings = _settings()
    programs_curate._pool_call = _fake_pool({
        'why_this_one': 'made',
        'phases': [{'name': 'Base', 'what': 'Two kinds of evening',
                    'steps': [],
                    'rotation': [
                        {'label': 'Technique', 'steps': ['Cascade drill']},
                        {'label': 'Material', 'steps': ['Run the routine']}],
                    'milestone': 'Both feel easy'}]})
    try:
        out = programs_curate.curate('learn to juggle',
                                     {'sessions_per_week': 2, 'minutes': 20})
        ph = out['phases'][0]
        check(len(ph['rotation']) == 2, f"the rotation survives, got {ph}")
        check(ph['steps'] == ['Cascade drill'],
              f"and the flat list is the first session, got {ph['steps']}")
    finally:
        programs_curate.web.research = real_research
        programs_curate._pool_call = real_pool
        programs_curate.storage.get_settings = real_settings


def _shaping_pool(rich, plain, seen):
    """Three different calls go through one seam, told apart by which system
    prompt they carry: the rich shaping contract, the plain one it falls back
    to, and generation."""
    def f(tier, api_key, system, prompt, **kw):
        if system is programs_curate.GENERATE_SYSTEM:
            seen.append('generate')
            return {'why_this_one': 'made it',
                    'phases': [{'name': 'Made', 'what': 'Something',
                                'steps': ['A made-up thing']}]}
        if system is programs_curate.PHASE_SYSTEM:
            seen.append('rich')
            return rich
        seen.append('plain')
        return plain
    return f


_ONE_PAGE = [{'claim': 'Grade 1 module 1 covers three open chords',
              'url': 'https://justinguitar.example/grade1'}]

_CITED_PLAIN = {
    'plan_name': 'Justin Guitar', 'why_this_one': 'It is the standard course',
    'phases': [{'name': 'Grade 1', 'what': 'Three open chords',
                'steps': ['One minute changes: G to C'],
                'milestone': 'G-C-D without looking', 'cite': 1}]}


def scenario_a_lost_citation_costs_one_more_call_not_the_whole_plan():
    """The regression this pass exists for.

    Asking one interactive-tier call for phases AND steps AND a progression
    rule AND a rotation AND a citation on every phase pushes both ways at
    once: more instructions for `cite` to compete with, and several times the
    output to truncate. A phase that loses its `cite` is dropped, and every
    phase losing it emptied the plan -- straight past into a made-up one. A
    household that had been getting real curricula got the app's own for
    everything, and nothing anywhere said so.
    """
    real_research = programs_curate.web.research
    real_pool = programs_curate._pool_call
    real_settings = programs_curate.storage.get_settings
    seen = []
    programs_curate.web.research = _fake_research(_ONE_PAGE)
    programs_curate.storage.get_settings = _settings()
    # The rich pass answers, and every phase comes back with no `cite`.
    programs_curate._pool_call = _shaping_pool(
        {'plan_name': 'Justin Guitar',
         'phases': [{'name': 'Grade 1', 'what': 'Three open chords',
                     'steps': ['One minute changes'],
                     'progression': 'One more change each time',
                     'milestone': 'G-C-D without looking'}]},
        _CITED_PLAIN, seen)
    try:
        out = programs_curate.curate('play campfire songs',
                                     {'sessions_per_week': 3, 'minutes': 25})
        check(out['source']['origin'] == programs_curate.ORIGIN_CITED,
              f"the real plan has to survive a lost citation, got {out['source']}")
        check(seen == ['rich', 'plain'],
              f"one retry on the plainer contract, and no generation, got {seen}")
        check(out['phases'][0]['name'] == 'Grade 1',
              f"and it is the cited material, got {out['phases']}")
    finally:
        programs_curate.web.research = real_research
        programs_curate._pool_call = real_pool
        programs_curate.storage.get_settings = real_settings


def scenario_a_truncated_answer_is_also_rescued():
    """The other way the richer contract fails: the longer answer never
    finishes and comes back as an error payload rather than as phases. Same
    landing place, so the same rescue has to cover it."""
    real_research = programs_curate.web.research
    real_pool = programs_curate._pool_call
    real_settings = programs_curate.storage.get_settings
    seen = []
    programs_curate.web.research = _fake_research(_ONE_PAGE)
    programs_curate.storage.get_settings = _settings()
    programs_curate._pool_call = _shaping_pool(
        {'error': 'json parse failed'}, _CITED_PLAIN, seen)
    try:
        out = programs_curate.curate('play campfire songs',
                                     {'sessions_per_week': 3, 'minutes': 25})
        check(out['source']['origin'] == programs_curate.ORIGIN_CITED,
              f"a parse failure is not a finding about the world, got {out['source']}")
        check('generate' not in seen, f"and nothing was made up, got {seen}")
    finally:
        programs_curate.web.research = real_research
        programs_curate._pool_call = real_pool
        programs_curate.storage.get_settings = real_settings


def scenario_the_plainer_contract_is_never_asked_for_when_the_first_pass_worked():
    """The retry is a rescue, not a habit: a second interactive call on every
    proposal is a cost the family did not agree to."""
    real_research = programs_curate.web.research
    real_pool = programs_curate._pool_call
    real_settings = programs_curate.storage.get_settings
    seen = []
    programs_curate.web.research = _fake_research(_ONE_PAGE)
    programs_curate.storage.get_settings = _settings()
    rich = {'plan_name': 'Justin Guitar',
            'phases': [{'name': 'Grade 1', 'what': 'Three open chords',
                        'steps': ['One minute changes'],
                        'progression': 'One more change each time',
                        'rotation': [
                            {'label': 'Changes', 'steps': ['G to C']},
                            {'label': 'Songs', 'steps': ['Play one through']}],
                        'milestone': 'G-C-D without looking', 'cite': 1}]}
    programs_curate._pool_call = _shaping_pool(rich, _CITED_PLAIN, seen)
    try:
        out = programs_curate.curate('play campfire songs',
                                     {'sessions_per_week': 3, 'minutes': 25})
        check(seen == ['rich'], f"one call when one call worked, got {seen}")
        ph = out['phases'][0]
        check(ph['progression'] == 'One more change each time',
              f"and the richer fields are kept, got {ph}")
        check(len(ph['rotation']) == 2, f"rotation included, got {ph}")
    finally:
        programs_curate.web.research = real_research
        programs_curate._pool_call = real_pool
        programs_curate.storage.get_settings = real_settings


def scenario_a_made_plan_says_which_kind_of_nothing_it_followed():
    """'No published program fit this aim' is a false statement when four
    real pages were read and the shaping simply could not cite them. They are
    different facts about the world, and the second is the one you need when
    made-up plans start arriving for aims that used to find real ones."""
    real_research = programs_curate.web.research
    real_pool = programs_curate._pool_call
    real_settings = programs_curate.storage.get_settings
    seen = []
    programs_curate.storage.get_settings = _settings()
    programs_curate.web.research = _fake_research(_ONE_PAGE)
    programs_curate._pool_call = _shaping_pool({'phases': []}, {'phases': []},
                                               seen)
    try:
        out = programs_curate.curate('play campfire songs',
                                     {'sessions_per_week': 3, 'minutes': 25})
        check(out['source']['origin'] == programs_curate.ORIGIN_GENERATED,
              f"it still gets a plan, got {out['source']}")
        check(out['source']['reason'] == 'uncited',
              f"and the record says pages were read, got {out['source']}")
    finally:
        programs_curate.web.research = real_research
        programs_curate._pool_call = real_pool
        programs_curate.storage.get_settings = real_settings
    # The other kind of nothing is unchanged: the web really was empty.
    real_research = programs_curate.web.research
    real_pool = programs_curate._pool_call
    real_settings = programs_curate.storage.get_settings
    programs_curate.storage.get_settings = _settings()
    programs_curate.web.research = _fake_research([])
    programs_curate._pool_call = _shaping_pool({'phases': []}, {'phases': []},
                                               [])
    try:
        out = programs_curate.curate('play campfire songs',
                                     {'sessions_per_week': 3, 'minutes': 25})
        check(out['source']['reason'] == 'no_plan',
              f"nothing was read, so nothing was thrown away, got {out['source']}")
    finally:
        programs_curate.web.research = real_research
        programs_curate._pool_call = real_pool
        programs_curate.storage.get_settings = real_settings


def scenario_a_citation_survives_how_a_model_types_it():
    """What a citation CLAIMS and how a model TYPES it are different things,
    and only the first one is the rule.

    Every shape below was a real answer that resolved to nothing and cost a
    whole cited plan: the corpus marker copied back verbatim, a list because
    the phase might cite several, a float because JSON has one number type.
    The prompt asking for "the number in square brackets" was this app
    inviting the first of them and then discarding it.
    """
    by_ref = {1: {'url': 'https://justinguitar.example/grade1'},
              2: {'url': 'https://justinguitar.example/grade2'}}
    urls = {i['url'] for i in by_ref.values()}
    for cite in (1, '1', '[1]', '1.', ' 1 ', [1], 1.0):
        check(programs_curate._cited_url({'cite': cite}, by_ref, urls)
              == 'https://justinguitar.example/grade1',
              f"cite={cite!r} names material we read and must resolve")
    check(programs_curate._cited_url({'citation': 2}, by_ref, urls)
          == 'https://justinguitar.example/grade2',
          "and the key it arrives under is not the thing being checked")
    check(programs_curate._cited_url(
        {'url': 'https://justinguitar.example/grade1/'}, by_ref, urls)
        == 'https://justinguitar.example/grade1',
        "a trailing slash is not a different page")


def scenario_the_citation_rule_itself_is_unmoved():
    """Reading a citation more generously is not believing one. A phase that
    names material this app never fetched is still nothing at all."""
    by_ref = {1: {'url': 'https://justinguitar.example/grade1'}}
    urls = {'https://justinguitar.example/grade1'}
    for ph in ({}, {'cite': 9}, {'cite': 0}, {'cite': True}, {'cite': None},
               {'cite': 'the Justin Guitar course'},
               {'url': 'https://not-a-page-we-read.example'}):
        check(programs_curate._cited_url(ph, by_ref, urls) == '',
              f"{ph} cites nothing this app read, and must not pass")


def scenario_a_plan_that_survived_the_model_is_not_lost_in_the_plumbing():
    """`llm._call_llm_json` returns the LAST top-level JSON it can find, which
    is right for a model that chatters before its answer and wrong for one
    that chatters after it. A bare array of phases -- what a model returns
    when it reads "phases" as the answer rather than as a field -- arrived
    here as a list and was refused for not being a dict."""
    payload = programs_curate._phase_payload(
        [{'name': 'Grade 1', 'what': 'Open chords', 'steps': ['G to C'],
          'cite': 1}])
    check(payload and payload.get('phases'),
          f"a bare list of phases is a plan, got {payload}")
    check(programs_curate._phase_payload([1, 2]) is None,
          "and a stray array of numbers is still not one")
    check(programs_curate._phase_payload('nope') is None,
          "nor is a string")


def scenario_a_bracketed_citation_still_yields_a_cited_plan():
    """The whole failure end to end: research reads real pages, the model
    answers with its citations in the corpus's own bracket form, and the
    family gets the real curriculum rather than one the app wrote."""
    real_research = programs_curate.web.research
    real_pool = programs_curate._pool_call
    real_settings = programs_curate.storage.get_settings
    seen = []
    programs_curate.storage.get_settings = _settings()
    programs_curate.web.research = _fake_research([
        {'claim': 'Grade 1 module 1 covers three open chords',
         'url': 'https://justinguitar.example/grade1'}])
    programs_curate._pool_call = _shaping_pool(
        {'plan_name': 'Justin Guitar', 'why_this_one': 'The standard course',
         'phases': [{'name': 'Grade 1', 'what': 'Three open chords',
                     'steps': ['One minute changes: G to C'],
                     'milestone': 'G-C-D without looking', 'cite': '[1]'}]},
        {'phases': []}, seen)
    try:
        out = programs_curate.curate('Learn Guitar',
                                     {'sessions_per_week': 3, 'minutes': 25})
        check(out['source']['origin'] == programs_curate.ORIGIN_CITED,
              f"the real plan has to come back, got {out['source']}")
        check(out['phases'][0]['name'] == 'Grade 1',
              f"and it is the material that was read, got {out['phases']}")
        check(seen == ['rich'], f"and on the first pass, got {seen}")
    finally:
        programs_curate.web.research = real_research
        programs_curate._pool_call = real_pool
        programs_curate.storage.get_settings = real_settings


def scenario_the_prompt_never_asks_for_the_bracket_form():
    """The instruction that caused it. Naming the square brackets told the
    model the citation IS "[1]"; the corpus already shows the number, so the
    prompt only has to say what shape to send it back in."""
    for system in (programs_curate.PHASE_SYSTEM,
                   programs_curate.PHASE_SYSTEM_PLAIN):
        check('in square brackets' not in system,
              "the prompt must not ask for the bracket form")
        check('"cite": 1' in system,
              "it shows the shape it wants instead")


def scenario_shaping_is_given_what_the_pages_said_not_only_their_names():
    """The failure that made the cited tier unreachable on the route nearly
    every household uses.

    On the GROUNDING route a "fact" is a page TITLE -- `_material` sets
    `'claim': title or answer[:160]` -- so the material handed to shaping was
    three page names, "Justin Guitar - Free Online Guitar Lessons" and two
    more like it, and nothing at all about what those pages SAY. A model told
    to organise only that material, and told plainly to return an empty
    phases list where the material supports no plan, returned an empty phases
    list; it was right to. Every one of those fell through to generation --
    which had been receiving the grounded answer as its context all along. So
    the tier that INVENTS a plan was the only tier holding the substance to
    build one from, and the app made up a curriculum for an aim whose real
    curriculum it had just read.
    """
    real_research = programs_curate.web.research
    real_pool = programs_curate._pool_call
    real_settings = programs_curate.storage.get_settings
    seen = []
    answer = ('Justin Guitar is the standard free beginner course. Grade 1 '
              'covers the first three open chords and one-minute changes; '
              'Grade 2 adds the F barre chord and strumming patterns.')
    programs_curate.storage.get_settings = _settings()
    programs_curate.web.research = _fake_grounded(
        [{'title': 'Justin Guitar - Free Online Guitar Lessons',
          'url': 'https://justinguitar.example/'},
         {'title': 'Beginner Guitar Course Grade 1',
          'url': 'https://justinguitar.example/grade1'}],
        answer=answer)
    programs_curate._pool_call = _capture_pool(
        {'plan_name': 'Justin Guitar', 'why_this_one': 'The standard course',
         'phases': [{'name': 'Grade 1', 'what': 'Three open chords',
                     'steps': ['One minute changes: G to C'],
                     'milestone': 'G-C-D without looking', 'cite': 1}]}, seen)
    try:
        out = programs_curate.curate('Learn Guitar',
                                     {'sessions_per_week': 3, 'minutes': 25})
        check('Grade 1 covers the first three open chords' in seen[0],
              f"what the pages SAID has to reach shaping, got:\n{seen[0]}")
        check('[1]' in seen[0] and 'justinguitar.example' in seen[0],
              f"and the numbered pages stay, to cite, got:\n{seen[0]}")
        check(out['source']['origin'] == programs_curate.ORIGIN_CITED,
              f"so a real plan comes back cited, got {out['source']}")
    finally:
        programs_curate.web.research = real_research
        programs_curate._pool_call = real_pool
        programs_curate.storage.get_settings = real_settings


def scenario_the_answer_is_material_and_never_a_source():
    """Handing shaping the research answer is not handing it a citation. A
    phase still has to name one of the pages, and a plan whose phases name
    nothing is still not a cited plan."""
    real_research = programs_curate.web.research
    real_pool = programs_curate._pool_call
    real_settings = programs_curate.storage.get_settings
    seen = []
    programs_curate.storage.get_settings = _settings()
    programs_curate.web.research = _fake_grounded(
        [{'title': 'Justin Guitar', 'url': 'https://justinguitar.example/'}],
        answer='Justin Guitar Grade 1 covers three open chords.')
    programs_curate._pool_call = _shaping_pool(
        {'phases': [{'name': 'Grade 1', 'what': 'Three open chords',
                     'steps': ['G to C']}]},
        {'phases': [{'name': 'Grade 1', 'what': 'Three open chords',
                     'steps': ['G to C']}]}, seen)
    try:
        out = programs_curate.curate('Learn Guitar',
                                     {'sessions_per_week': 3, 'minutes': 25})
        check(out['source']['origin'] == programs_curate.ORIGIN_GENERATED,
              f"an uncited phase is still uncited, got {out['source']}")
        check(out['source']['reason'] == 'uncited',
              f"and the record says pages were read, got {out['source']}")
    finally:
        programs_curate.web.research = real_research
        programs_curate._pool_call = real_pool
        programs_curate.storage.get_settings = real_settings


def scenario_a_cited_lesson_links_out_and_never_carries_our_words():
    """The split that makes a ladder honest.

    A cited plan may point at the lesson; it may not reproduce it. Copying a
    published lesson's text into this app would be somebody else's work
    republished AND the exact blurring the three tiers exist to prevent -- so
    `body` is refused outright on this path, and a `url` survives only when it
    is a page the app really read.
    """
    units = programs_curate._clean_units(
        [{'title': 'Module 1: Your first chords', 'sessions': 2,
          'url': 'https://justinguitar.example/grade1',
          'body': 'Place your fingers like this...'},
         {'title': 'Module 2: One minute changes',
          'url': 'https://a-page-we-never-read.example/lesson2'}],
        'Learn Guitar', urls={'https://justinguitar.example/grade1'})
    check(len(units) == 2, f"both rungs are real, got {units}")
    check(units[0]['url'] == 'https://justinguitar.example/grade1',
          f"a page we read is linkable, got {units[0]}")
    check(units[0]['body'] == '',
          f"and a cited rung never carries our prose, got {units[0]}")
    check(units[1]['url'] == '',
          f"a lesson URL nobody fetched is a guess, got {units[1]}")


def scenario_a_made_lesson_carries_words_and_never_a_link():
    """The other half. The app writing the session IS the generated tier; a
    made-up plan appearing to have a source is the one thing it may not do."""
    units = programs_curate._clean_units(
        [{'title': 'Session 1: The cascade', 'body': 'Two balls, twenty throws.',
          'url': 'https://plausible-but-invented.example/1'},
         {'title': 'Session 2: Adding the third',
          'body': 'Three balls, slow.'}],
        'learn to juggle', allow_body=True)
    check([u['url'] for u in units] == ['', ''],
          f"no made plan gets to look sourced, got {units}")
    check(units[0]['body'] == 'Two balls, twenty throws.',
          f"and it says what to do, got {units[0]}")


def scenario_a_ladder_of_one_is_not_a_ladder():
    check(programs_curate._clean_units(
        [{'title': 'The only lesson'}], 'x') == [],
        "one rung is a phase with a second name")
    check(programs_curate._clean_units(
        [{'title': 'One'}, {'body': 'no title'}], 'x') == [],
        "and a rung with no title is not a rung")
    loaded = programs_curate._clean_units(
        [{'title': 'Week 1: squat 185 lbs'}, {'title': 'Week 2'}], 'x')
    check(len(loaded) == 1 or loaded == [],
          f"a title carrying a load goes through the same screen, got {loaded}")


def scenario_pacing_finally_runs_over_something_true():
    """`ceil(12 / per_week)` gave every phase in every domain the same length
    -- at two evenings a week Lesson 1 and Lesson 4 were both "6w", and the
    number said nothing about either. Still arithmetic; now arithmetic over
    the ladder."""
    units = [{'title': 'A', 'sessions': 2}, {'title': 'B', 'sessions': 1},
             {'title': 'C', 'sessions': 1}]
    units = programs_curate._clean_units(units, 'x')
    check(programs_curate.phase_weeks(2, units) == 2,
          f"four sessions at two a week is two weeks, got "
          f"{programs_curate.phase_weeks(2, units)}")
    check(programs_curate.phase_weeks(2) == 6,
          "and a phase with no ladder keeps the old constant")
    check(programs_curate.unit_sessions(units) == 4,
          "the ladder says how many sessions it needs")


def scenario_a_cited_plan_comes_back_with_its_lessons():
    """End to end on the route a household actually uses."""
    real_research = programs_curate.web.research
    real_pool = programs_curate._pool_call
    real_settings = programs_curate.storage.get_settings
    seen = []
    programs_curate.storage.get_settings = _settings()
    programs_curate.web.research = _fake_grounded(
        [{'title': 'Justin Guitar Grade 1',
          'url': 'https://justinguitar.example/grade1'}],
        answer='Grade 1 runs from Module 1 (first chords) to Module 3.')
    programs_curate._pool_call = _shaping_pool(
        {'plan_name': 'Justin Guitar', 'why_this_one': 'The standard course',
         'phases': [{'name': 'Grade 1', 'what': 'Open chords', 'cite': 1,
                     'steps': ['One minute changes'],
                     'units': [
                         {'title': 'Module 1: First chords', 'sessions': 2,
                          'url': 'https://justinguitar.example/grade1'},
                         {'title': 'Module 2: One minute changes'},
                         {'title': 'Module 3: Your first song'}],
                     'milestone': 'G-C-D without looking'}]},
        {'phases': []}, seen)
    try:
        out = programs_curate.curate('Learn Guitar',
                                     {'sessions_per_week': 2, 'minutes': 25})
        ph = out['phases'][0]
        check(len(ph['units']) == 3, f"the ladder survives, got {ph}")
        check(ph['weeks'] == 2,
              f"and paces the phase -- four sessions at two a week, got "
              f"{ph['weeks']}")
        check(ph['units'][0]['url'].endswith('grade1'),
              f"with the page we read, got {ph['units'][0]}")
    finally:
        programs_curate.web.research = real_research
        programs_curate._pool_call = real_pool
        programs_curate.storage.get_settings = real_settings


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
    scenario_a_made_plan_that_prescribes_load_or_a_dose_is_dropped()
    scenario_a_plan_with_nothing_but_load_prescriptions_says_so()
    scenario_a_phase_carries_the_session_itself()
    scenario_the_generation_screen_refuses_the_activity_not_the_word()
    scenario_a_household_can_switch_made_plans_off()
    scenario_shaping_failure_is_not_a_crash()
    scenario_research_being_off_is_not_an_invented_plan()
    scenario_ordinary_aims_are_not_refused_as_body_goals()
    scenario_every_real_body_aim_still_refuses()
    scenario_a_made_plan_is_written_for_this_person_and_this_hour()
    scenario_an_age_is_never_guessed()
    scenario_the_starting_point_reaches_the_plan()
    scenario_the_body_screen_covers_the_starting_point_too()
    scenario_a_phase_says_how_to_beat_the_last_session()
    scenario_a_rotation_of_one_is_not_a_rotation()
    scenario_a_rotation_fills_the_steps_it_replaces()
    scenario_a_lost_citation_costs_one_more_call_not_the_whole_plan()
    scenario_a_truncated_answer_is_also_rescued()
    scenario_the_plainer_contract_is_never_asked_for_when_the_first_pass_worked()
    scenario_a_made_plan_says_which_kind_of_nothing_it_followed()
    scenario_a_citation_survives_how_a_model_types_it()
    scenario_the_citation_rule_itself_is_unmoved()
    scenario_a_plan_that_survived_the_model_is_not_lost_in_the_plumbing()
    scenario_a_bracketed_citation_still_yields_a_cited_plan()
    scenario_the_prompt_never_asks_for_the_bracket_form()
    scenario_shaping_is_given_what_the_pages_said_not_only_their_names()
    scenario_the_answer_is_material_and_never_a_source()
    scenario_a_cited_lesson_links_out_and_never_carries_our_words()
    scenario_a_made_lesson_carries_words_and_never_a_link()
    scenario_a_ladder_of_one_is_not_a_ladder()
    scenario_pacing_finally_runs_over_something_true()
    scenario_a_cited_plan_comes_back_with_its_lessons()
    print("test_programs_curate OK")
