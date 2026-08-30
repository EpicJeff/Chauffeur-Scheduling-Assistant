"""Finding the plan, rather than writing one -- and saying which happened.

For nearly every goal a family has, a good program already exists, built by
somebody who actually knows the domain -- Justin Guitar, Couch to 5K, a state's
driving-test curriculum, a library's reading ladder. Enthusiasts know these
exist; nobody else does. That gap is the whole value of this module.

So the rule is still CURATE OVER GENERATE, and it is still enforced rather
than requested: a phase that cites no page the app actually read is dropped.
What changed is what happens NEXT. Dropping every phase used to leave the
family a bare calendar reservation labelled "hand-written", which was a
misnomer -- nothing had written anything -- and which conflated four very
different situations: research switched off, the allowance spent, the web
genuinely having nothing, and the model failing to copy a URL.

There are three outcomes now, and the family is told which one they got:

  cited      a real published program, with the pages behind it
  generated  no published program fit, so the app made one and says so
  none       research could not run at all -- time is claimed, nothing else

The original objection to generating was that an invented curriculum is
"indistinguishable from the real thing at a glance". That objection is about
LABELLING, and it is answered by labelling: a generated plan never carries a
plan name, never carries a source link, and says on its face that the app made
it. What is NOT answered by labelling is a wrong number in a domain where a
wrong number injures somebody, so generation has its own screen on top of the
body-composition one, and any generated phase that prescribes a load or a dose
is dropped the same way an uncited phase is.

An outage is never papered over with a generated plan. "The research call
failed" is a retry, not a gap in the world's curricula.

This module knows nothing about a program's lifecycle -- it hands back phases
and a source dict; services/programs.py never imports it.
"""
import math
import re

from services import storage, web

# The screen runs BEFORE any model sees the aim. Deterministic on purpose: a
# safety line that depends on a model's judgement is a safety line with a bad
# night. The house supports behaviour goals and stays out of body goals -- and
# for a minor a body-composition target should not exist at all.
#
# A keyword list has both directions of miss: an aim phrased around body
# composition without any word here slips through ("shrink down for the
# wedding"), and a legitimate aim containing one of these words gets caught
# ("carry 30 lbs of gear on the hike" reads as a weight target). It errs
# toward the second kind of miss on purpose.

# Phrases long enough that a plain substring match cannot be an accident.
BODY_PHRASES = (
    'lose weight', 'lose 5', 'lose 10', 'lose 15', 'lose 20', 'lose 25',
    'lose 30', 'kg off', 'goal weight', 'target weight', 'body fat',
    'bodyfat', 'slim down', 'get lean', 'drop a size', 'six pack',
)

# Short words that must match as WORDS. Matched as substrings, 'thin' refused
# "learn to build things with wood" and "get everything ready for the science
# fair", and 'abs' refused "learn abseiling" -- with the target-weights
# sentence, which is baffling to read and worst of all to a kid, who has no
# way to tell which of their words the app objected to. False refusals are
# accepted on purpose in this screen; false refusals of ordinary aims are a
# different thing, and they cost the arc the ambitions it exists to serve.
BODY_WORDS = (
    'pounds', 'lbs', 'kilos', 'bmi', 'calorie', 'calories', 'deficit',
    'abs', 'skinny', 'thin', 'diet', 'diets', 'dieting', 'weigh', 'weighs',
)

_BODY_WORD_RE = re.compile(r'\b(?:' + '|'.join(BODY_WORDS) + r')\b')

# The whole screen in one tuple, for anything that wants to read the list.
BODY_TERMS = BODY_PHRASES + BODY_WORDS

BEHAVIOUR_ALTERNATIVES = (
    "move four times a week",
    "cook at home five nights a week",
    "train for a real 5K with a date and a bib",
)

# --- The generation screen ------------------------------------------------
# A SECOND screen, and only for the generated tier. Curating these aims is
# fine and stays fine: if an expert published a swim progression, following it
# is exactly what this module is for. What is refused is the app inventing one,
# because these are the domains where a plausible wrong number is an injury
# rather than a wasted month. This list is deliberately short -- every entry
# should survive the question "would a wrong step here hurt somebody?".
GENERATION_PHRASES = (
    'bench press', 'one rep max', 'one-rep max', 'free solo', 'lead climb',
    'half marathon', 'century ride', 'open water', 'breath hold',
    'intermittent fasting', 'water fast',
)
GENERATION_WORDS = (
    'barbell', 'deadlift', 'deadlifts', 'squat', 'squats', 'powerlifting',
    'powerlift', '1rm', 'swim', 'swimming', 'dive', 'diving', 'freedive',
    'scuba', 'marathon', 'ultramarathon', 'triathlon', 'fasting', 'keto',
    'macros', 'supplement', 'supplements', 'creatine', 'medication', 'dose',
    'dosage', 'insulin',
)
_GENERATION_WORD_RE = re.compile(r'\b(?:' + '|'.join(GENERATION_WORDS) + r')\b')

# A plan is written in the language the family asked in. Nothing said so, and
# a real generated plan came back with its first two phases in English and its
# third in Vietnamese -- an interactive-tier model drifting mid-response, which
# is a thing small models do and no amount of politeness in the prompt fully
# prevents. A phase somebody cannot read is not a phase.
#
# The test is deliberately crude and one-directional: it only fires when the
# AIM is plain ASCII (an English-speaking household, as far as anything here
# can tell) and a phase is full of non-ASCII letters. It cannot catch drift
# between two ASCII languages, and it must never fire on a household that
# writes its aims in Vietnamese, Spanish or Polish -- which is why the aim
# decides, not a language list.
_NON_ASCII_RE = re.compile(r'[^\x00-\x7f]')
# Measured rather than guessed: the Vietnamese phase that prompted this runs
# at 0.255 non-ASCII characters, while English carrying a borrowed word --
# a cafe or a resume spelled properly -- sits at 0.04 and under. Both
# bounds have to be cleared, so one accented word in a long English
# sentence can never trip it.
FOREIGN_RATIO = 0.10
FOREIGN_MIN = 4


def _looks_foreign(text: str, aim: str) -> bool:
    """Is this phase written in a language the aim was not?"""
    text = (text or '').strip()
    if not text or _NON_ASCII_RE.search(aim or ''):
        return False
    hits = len(_NON_ASCII_RE.findall(text))
    return hits >= FOREIGN_MIN and hits / len(text) > FOREIGN_RATIO


def _phase_text(ph: dict) -> str:
    return ' '.join(str(ph.get(k) or '')
                    for k in ('name', 'what', 'milestone')).strip()


# A generated phase may say "practise for twenty minutes". It may not say how
# much to lift, how far to push, or how much to take -- those are the numbers
# an expert earns the right to set. A phase carrying one is dropped, exactly
# like a phase carrying no citation, and if that empties the plan the family
# gets time-only with the reason said out loud.
_LOAD_RE = re.compile(
    r'\b\d+\s*(?:%|lb|lbs|pound|pounds|kg|kgs|kilo|kilos|mg|mcg|ml|'
    r'rep|reps|set|sets|rm)\b', re.I)

# How many pages a curation run reads. One run per program, cached on the
# object for its life -- a background sweep must never spend research calls.
PAGES = 4

# The most citable items one run will carry into shaping. A grounded answer
# can arrive with a dozen sources; past a handful they stop being material and
# start being prompt weight.
MAX_ITEMS = 8

# Structuring at most a handful of already-extracted, one-line claims into 2-4
# phases is not the "rare quality-critical generation" services/model_pools.py
# reserves 'heavy' for -- the part that actually has to be right (citation
# matching, below) is deterministic code that does not care how good the
# model is. A person is waiting on this to come back, which is what
# 'interactive' is for: lite first, gemma as fallback, and the scarce
# flash-quota 'heavy' pool stays free for the genuinely hard generation
# services/web.py's own extraction step uses it for.
TIER = 'interactive'

# A phase's WEEK COUNT is computed, never asked for -- a week count out of
# the model would be curriculum with no page behind it, exactly the thing
# citations are checked for but a bare number can't be. This holds for the
# generated tier too: making the content up is now allowed and labelled;
# making the PACING up would silently overrule what the family said they can
# actually manage. SESSIONS_PER_PHASE is the house standard: at the default
# three sessions a week it reproduces the design's own worked example (12
# sessions -> a four-week phase); a family that can only manage two a week
# gets six-week phases for the same material instead of quietly falling
# behind a plan that assumed three.
SESSIONS_PER_PHASE = 12

# The three tiers, named once so nothing has to spell them as strings.
ORIGIN_CITED = 'cited'
ORIGIN_GENERATED = 'generated'
ORIGIN_NONE = 'none'

# Why there is no cited plan, in the app's own words. The reason used to exist
# only as an argument to an internal helper and never reached a screen, so
# "the research key is missing" and "the web has nothing on this" looked
# identical to the person reading the card.
REASON_TEXT = {
    'disabled': 'web research is switched off for this household',
    'no_key': 'no research key is set up',
    'capped': "this month's research allowance is spent",
    'unavailable': 'research was unavailable just now',
    'no_plan': 'no published program fit this aim',
    'generation_off': 'made-up plans are switched off for this household',
    'generation_refused': ('this aim needs a real coach or a real course, '
                           'not a plan the app made up'),
    'generation_failed': 'nothing usable came back',
    'load_prescribed': ('the plan that came back prescribed loads or doses, '
                        'which the app will not hand out'),
}

# A research status that means the PIPE broke, not that the world is empty.
# Generating here would dress an outage up as a finding, so these never reach
# the generated tier -- the family gets time-only and a reason to retry.
_OUTAGE_REASON = {'disabled': 'disabled', 'no_key': 'no_key',
                  'capped': 'capped'}

PHASE_SYSTEM = (
    "You are organising material for a household's program, not writing one. "
    "You are given exactly what was read from real pages for this aim -- "
    "organise ONLY that material into 2-4 phases. Do not add a step that is "
    "not supported by the material below. Every phase MUST carry a `cite` "
    "holding the number of the material item it came from. Also name the "
    "program you organised, say in one sentence why it suits this family, "
    "and list the other candidates you did NOT pick with a real reason for "
    "each. Write EVERY field in the same language the aim is written in, and "
    "do not change language part-way through. If the material does not "
    "support a real phased plan, reply with an empty phases list.\n\n"
    'Return STRICT JSON: {"plan_name": "", "why_this_one": "", '
    '"phases": [{"name": "", "what": "", "milestone": "", "cite": 1}], '
    '"runners_up": [{"cite": 2, "why_not": ""}]}'
)

GENERATE_SYSTEM = (
    "No published program was found for this aim, so you are making a "
    "practice plan for one household and it will be labelled as made by an "
    "app. Say what to practise, in plain words, in 2-4 phases that build on "
    "each other.\n\n"
    "Rules. Never prescribe weights, loads, reps, sets, distances to push "
    "to, doses or supplements -- describe the practice, not the numbers. "
    "Never name a real published program, and never claim a source: you have "
    "none. Do not give week counts; the app computes pacing. Say plainly "
    "what a person should be able to do at the end of each phase. Write "
    "EVERY field in the same language the aim is written in, and do not "
    "change language part-way through. If you cannot do this responsibly for "
    "this aim, reply with an empty phases list.\n\n"
    'Return STRICT JSON: {"why_this_one": "<one sentence on the approach>", '
    '"phases": [{"name": "", "what": "", "milestone": ""}]}'
)


def screen_aim(title: str) -> dict:
    """Is this an aim the house will take on?

    Returns {'ok': True} or a refusal carrying the behaviour-shaped version, in
    one plain sentence. No moralising: say what it will not do, say what it
    will, move on.
    """
    low = (title or '').strip().lower()
    if not low:
        return {'ok': False, 'message': "What's the aim?", 'alternatives': []}
    if any(term in low for term in BODY_PHRASES) or _BODY_WORD_RE.search(low):
        return {'ok': False,
                'message': ("I don't do target weights or calorie numbers — "
                            "not for anyone, and never for a kid. I can do the "
                            "behaviour version, which is the part that "
                            "actually moves anyway."),
                'alternatives': list(BEHAVIOUR_ALTERNATIVES)}
    return {'ok': True}


def generation_allowed(title: str) -> bool:
    """May the app INVENT a plan for this aim, having found none?

    Curating any of these is untouched -- an expert's swim progression is
    exactly what this module wants to find. This gate is only about the app
    writing one itself, in domains where a confident wrong step is an injury.
    """
    low = (title or '').strip().lower()
    if any(term in low for term in GENERATION_PHRASES):
        return False
    return not _GENERATION_WORD_RE.search(low)


def _pool_call(tier, api_key, system, prompt, **kw):
    """Indirection so tests stub one attribute."""
    from services import model_pools
    return model_pools.call_pool_json(tier, api_key, system, prompt, **kw)


def _source_none(reason: str, answer: str = '') -> dict:
    """No plan of any kind. Say which of the reasons it was; never fill the
    gap. `hand_written` is kept alongside `origin` because rows written before
    the three tiers existed carry only that field, and so do the readers that
    were written against them."""
    return {'plan_name': '', 'url': '',
            'why_this_one': REASON_TEXT.get(reason, reason),
            'facts': [], 'runners_up': [], 'answer': answer,
            'origin': ORIGIN_NONE, 'reason': reason, 'hand_written': True}


def _source_generated(why: str, answer: str = '') -> dict:
    """A plan the app made. No plan name and no url, on purpose: those two
    fields are what the card renders as "Following <a real thing>", and a
    generated plan has nothing to point at."""
    return {'plan_name': '', 'url': '', 'why_this_one': why,
            'facts': [], 'runners_up': [], 'answer': answer,
            'origin': ORIGIN_GENERATED, 'reason': 'no_plan',
            'hand_written': True}


def curate(title: str, shape: dict, member_name: str = '') -> dict:
    """One research run, turned into cited phases -- or an honest fallback.

    Returns {'phases': [...], 'source': {...}}. Phase CONTENT comes from pages
    that were read where there were any; phase PACING is arithmetic over
    `shape` in every tier, because pacing is exactly where a model would
    otherwise start writing curriculum.
    """
    per_week = int((shape or {}).get('sessions_per_week') or 3)
    minutes = int((shape or {}).get('minutes') or 25)
    question = (f"What is the best established, existing, step-by-step program "
                f"a beginner should follow to {title}? Name the real program "
                f"and its phases. Do not invent one.")
    settings = storage.get_settings() or {}
    pages = int(settings.get('programs_research_pages', PAGES) or PAGES)
    api_key = settings.get('llm_gemini_api_key', '')
    try:
        res = web.research(question, read_pages=pages) or {}
    except Exception as e:
        print(f"[programs] research failed: {e}")
        return {'phases': [], 'source': _source_none('unavailable')}

    status = res.get('status')
    if status != 'ok':
        # An outage is a retry, not a gap in the world's curricula -- these
        # never reach the generated tier. `no_results` is the exception: the
        # search really did run and really did come back with nothing, which
        # is precisely the case generating exists for.
        if status in _OUTAGE_REASON:
            return {'phases': [],
                    'source': _source_none(_OUTAGE_REASON[status])}
        if status != 'no_results':
            return {'phases': [], 'source': _source_none('unavailable')}
        return _fallback(title, per_week, member_name, api_key, '')

    answer = (res.get('answer') or '').strip()
    items = _material(res)
    if not items:
        return _fallback(title, per_week, member_name, api_key, answer)

    shaped = _phases_from(title, items, per_week, minutes, api_key, member_name)
    if not shaped['phases']:
        # Reached here the material was real and the shaping still produced
        # nothing citable. That used to end the story; now it falls through to
        # a labelled plan built on the material, which is a far better answer
        # than a naked calendar reservation.
        return _fallback(title, per_week, member_name, api_key, answer)

    return {'phases': shaped['phases'],
            'source': {'plan_name': shaped['plan_name'],
                       'url': shaped['url'] or items[0]['url'],
                       'why_this_one': shaped['why_this_one'] or answer[:400],
                       'facts': [{'claim': i['claim'], 'url': i['url']}
                                 for i in items],
                       'runners_up': shaped['runners_up'],
                       'answer': answer,
                       'origin': ORIGIN_CITED, 'reason': '',
                       'hand_written': False}}


def _fallback(title: str, per_week: int, member_name: str, api_key: str,
              answer: str) -> dict:
    """No cited plan. Make one and label it, or say why not even that."""
    settings = storage.get_settings() or {}
    if not settings.get('programs_generate_enabled', True):
        return {'phases': [], 'source': _source_none('generation_off', answer)}
    if not generation_allowed(title):
        return {'phases': [],
                'source': _source_none('generation_refused', answer)}
    made = _generated_phases(title, per_week, api_key, member_name, answer)
    if made['reason']:
        return {'phases': [], 'source': _source_none(made['reason'], answer)}
    return {'phases': made['phases'],
            'source': _source_generated(made['why_this_one'], answer)}


def _material(res: dict) -> list:
    """What this run is allowed to cite, as numbered items.

    The two research routes hand back materially different things and used to
    be read as if they were the same. On the PAGES route a fact is a claim
    pulled from a page this app fetched itself, and only those are citable --
    `sources` there is merely everything the search returned, and is never a
    citation.

    On the GROUNDING route -- the default provider's route -- the whole answer
    arrives as a single fact pinned to `sources[0]`, and the other sources
    were dropped on the floor. Every one of them is a page the grounded answer
    was actually built from, so all of them are citable here. Reading only the
    first meant a plan had exactly one URL to copy and one shot at copying it
    right, which is most of why cited plans were coming back as no-plans, and
    it meant the runners-up list -- which reads `facts[1:]` -- was structurally
    always empty on the route nearly every household uses.

    A grounding citation is weaker than a pages citation: it says "this is one
    of the pages the answer was built from", not "this page says this phase".
    That is why a plan name still has to be verifiable in the material below
    before it is allowed on the card.
    """
    if (res.get('via') or 'pages') == 'grounding':
        answer = (res.get('answer') or '').strip()
        out, seen = [], set()
        for s in (res.get('sources') or []):
            url = (s.get('url') or '').strip()
            if not url or url in seen:
                continue
            seen.add(url)
            title = (s.get('title') or '').strip()
            out.append({'url': url, 'title': title,
                        'claim': title or answer[:160]})
        return out[:MAX_ITEMS]

    out, seen = [], set()
    for f in (res.get('facts') or []):
        url = (f.get('url') or '').strip()
        claim = (f.get('claim') or '').strip()
        if not url or not claim or (url, claim) in seen:
            continue
        seen.add((url, claim))
        out.append({'url': url, 'title': '', 'claim': claim})
    return out[:MAX_ITEMS]


def _norm(s: str) -> str:
    return re.sub(r'[^a-z0-9]+', ' ', (s or '').lower()).strip()


def _plan_name_ok(name: str, items: list, answer: str) -> bool:
    """A named plan has to be findable in what was read. The model naming the
    program is a real improvement on taking the answer's first sentence, but
    only if the name cannot be invented -- "Following <a plausible thing>" with
    a link to a page that never said it is the exact failure this module
    exists to prevent."""
    needle = _norm(name)
    if not needle or len(needle) < 3:
        return False
    hay = _norm(answer + ' ' + ' '.join(
        (i.get('title') or '') + ' ' + (i.get('claim') or '') + ' ' +
        (i.get('url') or '') for i in items))
    return needle in hay


def phase_weeks(per_week: int) -> int:
    """How many weeks a phase takes. Computed, not asked for -- see the
    SESSIONS_PER_PHASE comment above.

    Public because editing a proposal's shape has to re-pace the phases it
    already has, and re-pacing by copying this arithmetic into main.py is how
    two pacing rules start disagreeing.
    """
    safe = per_week if isinstance(per_week, int) and per_week > 0 else 1
    return max(1, math.ceil(SESSIONS_PER_PHASE / safe))


_phase_weeks = phase_weeks


def _cited_url(ph: dict, by_ref: dict, urls: set) -> str:
    """The page behind a phase, or ''.

    A `cite` INDEX is the primary form and the reason this is not the old
    check: the model used to have to copy a long resolved URL exactly, and a
    single character of drift threw away an entire real plan. An exact URL is
    still accepted, because a model handed material with URLs in it will
    sometimes answer that way and there is no reason to punish a citation that
    is provably right.
    """
    ref = ph.get('cite')
    if isinstance(ref, bool):
        ref = None
    if isinstance(ref, str) and ref.strip().isdigit():
        ref = int(ref.strip())
    if isinstance(ref, int) and ref in by_ref:
        return by_ref[ref]['url']
    url = (ph.get('url') or '').strip()
    return url if url in urls else ''


def _phases_from(title: str, items: list, per_week: int, minutes: int,
                 api_key: str, member_name: str = '') -> dict:
    """Turn what was read into phases, then drop any that cite nothing.

    The model is asked to organise material it was given, not to produce
    material. Anything whose citation is not one of the items we actually put
    in front of it is discarded -- the same discipline `web.research`'s own
    `dropped` counter applies one level down.
    """
    by_ref = {n + 1: it for n, it in enumerate(items)}
    urls = {it['url'] for it in items}
    corpus = "\n".join(
        f"[{n}] {it['claim']}"
        + (f" (page: {it['title']})" if it['title'] else '')
        + f" <{it['url']}>" for n, it in by_ref.items())
    who = f" for {member_name}" if member_name else ''
    prompt = (f"Aim{who}: {title}.\n"
              f"They can practise {per_week} times a week for {minutes} minutes.\n\n"
              f"What was actually read from real pages:\n{corpus}")
    empty = {'phases': [], 'plan_name': '', 'url': '', 'why_this_one': '',
             'runners_up': []}
    try:
        data = _pool_call(TIER, api_key, PHASE_SYSTEM, prompt,
                          timeout_s=60, gemma_timeout_s=180)
    except Exception as e:
        print(f"[programs] phase shaping failed: {e}")
        return empty
    if not isinstance(data, dict) or data.get('error'):
        return empty

    weeks = _phase_weeks(per_week)
    out, used = [], []
    for ph in (data.get('phases') or [])[:4]:
        if not isinstance(ph, dict):
            continue
        url = _cited_url(ph, by_ref, urls)
        if not url:
            # A plausible phase with no page behind it does not get to be a
            # phase. This is the whole rule.
            continue
        if _looks_foreign(_phase_text(ph), title):
            # Same rule, different failure: a phase nobody in this house can
            # read is not a phase either.
            print(f"[programs] dropped a phase written in another language")
            continue
        used.append(url)
        # Note: any 'weeks' the model sent is ignored. Pacing is arithmetic
        # over `shape`, computed once above -- never a number out of the model.
        out.append({'name': (ph.get('name') or f"Phase {len(out) + 1}")[:60],
                    'weeks': weeks,
                    'what': (ph.get('what') or '').strip()[:400],
                    'milestone': (ph.get('milestone') or '').strip()[:120],
                    'milestone_hit_at': None})
    if not out:
        return empty

    name = (data.get('plan_name') or '').strip()[:80]
    answer_ctx = ' '.join(i['claim'] for i in items)
    return {'phases': out,
            'plan_name': name if _plan_name_ok(name, items, answer_ctx) else '',
            'url': used[0],
            'why_this_one': (data.get('why_this_one') or '').strip()[:400],
            'runners_up': _runners_up(data.get('runners_up'), by_ref, used)}


def _runners_up(raw, by_ref: dict, used: list) -> list:
    """The other candidates, so the choice reads as a choice rather than an
    oracle -- and so it can be argued with.

    The model's own reason is preferred, because "second choice for this aim"
    on every row is a placeholder wearing a reason's clothes. When it gives
    none, the unused material is still listed: knowing there WERE other
    options is most of the value even without the argument.
    """
    seen = set(used)
    out = []
    for r in (raw or []):
        if not isinstance(r, dict):
            continue
        ref = r.get('cite')
        if isinstance(ref, str) and ref.strip().isdigit():
            ref = int(ref.strip())
        item = by_ref.get(ref) if isinstance(ref, int) else None
        if not item or item['url'] in seen:
            continue
        seen.add(item['url'])
        out.append({'name': (item['title'] or item['claim'])[:60],
                    'url': item['url'],
                    'why_not': ((r.get('why_not') or '').strip()[:160]
                                or 'another candidate for this aim')})
    for item in by_ref.values():
        if len(out) >= 3:
            break
        if item['url'] in seen:
            continue
        seen.add(item['url'])
        out.append({'name': (item['title'] or item['claim'])[:60],
                    'url': item['url'],
                    'why_not': 'another candidate for this aim'})
    return out[:3]


def _prescribes_load(ph: dict) -> bool:
    """Does this generated phase hand out a number an expert should be
    setting? Checked over everything the family will read, not just `what`."""
    blob = ' '.join(str(ph.get(k) or '') for k in ('name', 'what', 'milestone'))
    return bool(_LOAD_RE.search(blob))


def _generated_phases(title: str, per_week: int, api_key: str,
                      member_name: str, answer: str) -> dict:
    """Make a plan, label it, and hold it to the two rules that survive the
    move from curating to generating: pacing is still arithmetic, and a phase
    that prescribes a load or a dose is still dropped.

    Returns {'phases', 'why_this_one', 'reason'} -- a non-empty `reason` means
    no plan, and names which way it failed.
    """
    who = f" for {member_name}" if member_name else ''
    context = (f"\n\nWhat the web said about this aim, uncited and NOT to be "
               f"quoted as a source:\n{answer}" if answer else '')
    prompt = (f"Aim{who}: {title}.\n"
              f"They can practise {per_week} times a week.{context}")

    def _ask(system):
        try:
            return _pool_call(TIER, api_key, system, prompt,
                              timeout_s=60, gemma_timeout_s=180)
        except Exception as e:
            print(f"[programs] plan generation failed: {e}")
            return None

    data = _ask(GENERATE_SYSTEM)
    if not isinstance(data, dict) or data.get('error'):
        return {'phases': [], 'why_this_one': '', 'reason': 'generation_failed'}

    # A plan half in another language is not one a family can follow, and
    # dropping the drifted phase silently leaves a plan with a hole in the
    # middle of it. One repair pass, naming the aim as the language to match,
    # costs a single interactive call and only ever runs when drift really
    # happened -- and if the second answer drifts too, the bad phases are
    # dropped rather than shown.
    if any(_looks_foreign(_phase_text(ph), title)
           for ph in (data.get('phases') or []) if isinstance(ph, dict)):
        print("[programs] generated plan changed language; asking once more")
        again = _ask(GENERATE_SYSTEM + (
            f"\n\nWrite the whole answer in the same language as this aim, "
            f"and in no other: \"{title}\""))
        if isinstance(again, dict) and not again.get('error') \
                and (again.get('phases') or []):
            data = again

    weeks = _phase_weeks(per_week)
    out, dropped, foreign = [], 0, 0
    for ph in (data.get('phases') or [])[:4]:
        if not isinstance(ph, dict):
            continue
        clean = {'name': (ph.get('name') or f"Phase {len(out) + 1}")[:60],
                 'what': (ph.get('what') or '').strip()[:400],
                 'milestone': (ph.get('milestone') or '').strip()[:120]}
        if not clean['what']:
            continue
        if _prescribes_load(clean):
            dropped += 1
            continue
        if _looks_foreign(_phase_text(clean), title):
            foreign += 1
            continue
        clean['weeks'] = weeks
        clean['milestone_hit_at'] = None
        out.append(clean)
    if not out:
        return {'phases': [], 'why_this_one': '',
                'reason': 'load_prescribed' if dropped else 'generation_failed'}
    why = (data.get('why_this_one') or '').strip()[:400]
    return {'phases': out,
            'why_this_one': why or ('No published program fit this aim, '
                                    'so this plan was made for it.'),
            'reason': ''}
