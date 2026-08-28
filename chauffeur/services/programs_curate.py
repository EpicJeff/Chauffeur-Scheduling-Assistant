"""Finding the plan, rather than writing one.

For nearly every goal a family has, a good program already exists, built by
somebody who actually knows the domain — Justin Guitar, Couch to 5K, a state's
driving-test curriculum, a library's reading ladder. Enthusiasts know these
exist; nobody else does. That gap is the whole value of this module.

So the rule is CURATE OVER GENERATE, and it is enforced rather than requested:
a phase that cites no page the app actually read is dropped, and if dropping
empties the plan, the program is marked hand-written and says so. A made-up
curriculum is confident, tidy, and worse than the free one an expert spent a
decade refining -- and it is indistinguishable from the real thing at a glance,
which is exactly why the check cannot be left to a reader's judgement.

This module knows nothing about a program's lifecycle -- it hands back phases
and a source dict; services/programs.py never imports it.
"""
import math

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
BODY_TERMS = (
    'lose weight', 'lose 5', 'lose 10', 'lose 15', 'lose 20', 'lose 25',
    'lose 30', 'pounds', 'lbs', 'kilos', 'kg off', 'goal weight',
    'target weight', 'body fat', 'bodyfat', 'bmi', 'calorie', 'calories',
    'deficit', 'slim down', 'get lean', 'drop a size', 'six pack', 'abs',
    'weigh ', 'skinny', 'thin', 'diet',
)

BEHAVIOUR_ALTERNATIVES = (
    "move four times a week",
    "cook at home five nights a week",
    "train for a real 5K with a date and a bib",
)

# How many pages a curation run reads. One run per program, cached on the
# object for its life -- a background sweep must never spend research calls.
PAGES = 4

# Structuring at most four already-extracted, one-line claims into 2-4 phases
# is not the "rare quality-critical generation" services/model_pools.py
# reserves 'heavy' for -- the part that actually has to be right (citation
# matching, below) is deterministic code that does not care how good the
# model is. A person is waiting on this to come back, which is what
# 'interactive' is for: lite first, gemma as fallback, and the scarce
# flash-quota 'heavy' pool stays free for the genuinely hard generation
# services/web.py's own extraction step uses it for.
TIER = 'interactive'

# A phase's WEEK COUNT is computed, never asked for -- a week count out of
# the model would be curriculum with no page behind it, exactly the thing
# `url` is checked for but a bare number can't be. SESSIONS_PER_PHASE is the
# house standard: at the default three sessions a week it reproduces the
# design's own worked example (12 sessions -> a four-week phase); a family
# that can only manage two a week gets six-week phases for the same
# material instead of quietly falling behind a plan that assumed three.
SESSIONS_PER_PHASE = 12

PHASE_SYSTEM = (
    "You are organising material for a household's program, not writing one. "
    "You are given exactly what was read from real pages for this aim -- "
    "organise ONLY that material into 2-4 phases. Do not add a step that is "
    "not supported by the material below. Every phase's url MUST be copied "
    "EXACTLY from one of the urls provided. If the material does not support "
    "a real phased plan, reply with an empty phases list.\n\n"
    'Return STRICT JSON: {"phases": [{"name": "", "what": "", '
    '"milestone": "", "url": ""}]}'
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
    if any(term in low for term in BODY_TERMS):
        return {'ok': False,
                'message': ("I don't do target weights or calorie numbers — "
                            "not for anyone, and never for a kid. I can do the "
                            "behaviour version, which is the part that "
                            "actually moves anyway."),
                'alternatives': list(BEHAVIOUR_ALTERNATIVES)}
    return {'ok': True}


def _pool_call(tier, api_key, system, prompt, **kw):
    """Indirection so tests stub one attribute."""
    from services import model_pools
    return model_pools.call_pool_json(tier, api_key, system, prompt, **kw)


def _hand_written(reason: str = '') -> dict:
    """No plan was found. Say so; do not fill the gap."""
    return {'plan_name': '', 'url': '', 'why_this_one': reason,
            'facts': [], 'runners_up': [], 'hand_written': True}


def curate(title: str, shape: dict, member_name: str = '') -> dict:
    """One research run, turned into cited phases.

    Returns {'phases': [...], 'source': {...}}. Phase CONTENT comes from pages
    that were read; phase PACING is arithmetic over `shape`, because pacing is
    exactly where a model would otherwise start writing curriculum.
    """
    per_week = int((shape or {}).get('sessions_per_week') or 3)
    minutes = int((shape or {}).get('minutes') or 25)
    question = (f"What is the best established, existing, step-by-step program "
                f"a beginner should follow to {title}? Name the real program "
                f"and its phases. Do not invent one.")
    try:
        res = web.research(question, read_pages=PAGES) or {}
    except Exception as e:
        print(f"[programs] research failed: {e}")
        return {'phases': [], 'source': _hand_written('research was unavailable')}

    if res.get('status') != 'ok':
        return {'phases': [],
                'source': _hand_written(f"research is {res.get('status')}")}

    # Facts are claims tied to a page the app actually FETCHED. `sources` is
    # merely everything the search returned and is never a citation here --
    # the same line threads drew, for the same reason.
    facts = [f for f in (res.get('facts') or [])
             if f.get('url') and f.get('claim')]
    if not facts:
        return {'phases': [], 'source': _hand_written('nothing solid was found')}

    api_key = (storage.get_settings() or {}).get('llm_gemini_api_key', '')
    phases = _phases_from(title, facts, per_week, minutes, api_key, member_name)
    if not phases:
        return {'phases': [], 'source': _hand_written('no phase could be cited')}

    return {'phases': phases,
            'source': {'plan_name': _plan_name(res.get('answer') or '', facts),
                       'url': facts[0]['url'],
                       'why_this_one': (res.get('answer') or '').strip()[:400],
                       'facts': facts,
                       'runners_up': _runners_up(facts),
                       'hand_written': False}}


def _plan_name(answer: str, facts: list) -> str:
    """The named program, if the answer names one. Never invented: an empty
    name is better than a plausible one."""
    first = (answer or '').strip().split('.')[0]
    return first[:80] if first else ''


def _runners_up(facts: list) -> list:
    """The other candidates, so the choice reads as a choice rather than an
    oracle. Takes the already-filtered `facts` list -- not the raw research
    result -- so this and the citation set `curate()` actually used can never
    describe two different things."""
    seen, out = set(), []
    for f in facts[1:]:
        url = f.get('url')
        if not url or url in seen:
            continue
        seen.add(url)
        out.append({'name': (f.get('claim') or '')[:60], 'url': url,
                    'why_not': 'second choice for this aim'})
    return out[:3]


def _phase_weeks(per_week: int) -> int:
    """How many weeks a phase takes. Computed, not asked for -- see the
    SESSIONS_PER_PHASE comment above."""
    safe = per_week if isinstance(per_week, int) and per_week > 0 else 1
    return max(1, math.ceil(SESSIONS_PER_PHASE / safe))


def _phases_from(title: str, facts: list, per_week: int, minutes: int,
                 api_key: str, member_name: str = '') -> list:
    """Turn what was read into phases, then drop any that cite nothing.

    The model is asked to organise material it was given, not to produce
    material. Anything it returns whose citation is not one of the URLs we
    actually fetched is discarded -- the same discipline `web.research`'s own
    `dropped` counter applies one level down.
    """
    allowed = {f['url'] for f in facts}
    corpus = "\n".join(f"- {f['claim']} [{f['url']}]" for f in facts)
    who = f" for {member_name}" if member_name else ''
    prompt = (f"Aim{who}: {title}.\n"
              f"They can practise {per_week} times a week for {minutes} minutes.\n\n"
              f"What was actually read from real pages:\n{corpus}")
    try:
        data = _pool_call(TIER, api_key, PHASE_SYSTEM, prompt,
                          timeout_s=60, gemma_timeout_s=180)
    except Exception as e:
        print(f"[programs] phase shaping failed: {e}")
        return []
    if not isinstance(data, dict) or data.get('error'):
        return []

    weeks = _phase_weeks(per_week)
    out = []
    for ph in (data.get('phases') or [])[:4]:
        if not isinstance(ph, dict):
            continue
        url = (ph.get('url') or '').strip()
        if url not in allowed:
            # A plausible phase with no page behind it does not get to be a
            # phase. This is the whole rule.
            continue
        # Note: any 'weeks' the model sent is ignored. Pacing is arithmetic
        # over `shape`, computed once above -- never a number out of the model.
        out.append({'name': (ph.get('name') or f"Phase {len(out) + 1}")[:60],
                    'weeks': weeks,
                    'what': (ph.get('what') or '').strip()[:400],
                    'milestone': (ph.get('milestone') or '').strip()[:120],
                    'milestone_hit_at': None})
    return out
