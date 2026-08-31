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

from services import stages, storage, web

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
# is exactly what this module is for. What is refused is the app inventing one.
#
# The first cut of this list refused every barbell lift, and that was drawing
# the line around the wrong thing. What makes an invented strength plan
# dangerous is a NUMBER nobody earned the right to set -- load somebody up to
# 185 lbs because an app said so -- and that is blocked structurally below, in
# a regex a model cannot talk its way past. Naming the squat as an exercise is
# not the hazard; squats are what strength training IS. Refusing the word cost
# the family the only thing they wanted from the plan and bought no safety
# that the numbers rule was not already buying.
#
# What survives is the set where the ACTIVITY is the hazard and no amount of
# vagueness helps: water (you drown), a fall (you fall), anything medical or
# ingested, and endurance distances, where a made-up volume ramp is the injury
# itself rather than a number attached to one. Every entry should survive the
# question "would a wrong step here hurt somebody even with no numbers in it?".
GENERATION_PHRASES = (
    'one rep max', 'one-rep max', 'free solo', 'lead climb',
    'half marathon', 'century ride', 'open water', 'breath hold',
    'intermittent fasting', 'water fast',
)
GENERATION_WORDS = (
    '1rm', 'swim', 'swimming', 'dive', 'diving', 'freedive',
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


# How many concrete items one phase may name, and how long each may be. A
# session is startable from these alone -- that is the whole test.
MAX_STEPS = 8
STEP_CHARS = 140

# How a person makes THIS session harder than the last one, inside a phase.
# The missing half of pacing: phases escalate across months and a milestone
# says when one ended, but between those two there was nothing telling anybody
# that Tuesday should be a notch beyond last Tuesday. Every plan a person can
# find elsewhere carries this and ours did not, in any domain -- one more
# page, a faster tempo, one less prompt from a parent, one more rep.
#
# It is a SENTENCE and not a number on purpose, and it goes through the same
# load screen as everything else: "add a rep before you add weight" is a rule
# a person can follow; "add five pounds" is a number nobody here earned the
# right to set.
PROGRESSION_CHARS = 200

# Sessions inside a phase that are not all the same session. Optional, and it
# has to stay optional: plenty of aims really are the same thing repeated
# (twenty minutes of reading, a walk), and a rotation invented for those is
# variety theatre. Where it is real -- technique night against repertoire
# night, new material against review, push against pull -- one flat list of
# steps repeated twelve times was never what the plan said.
#
# Two is the floor because a rotation of one is a list of steps with a hat on.
MIN_ROTATION = 2
MAX_ROTATION = 4
LABEL_CHARS = 40

# How much of the research answer reaches shaping. Long enough to carry a
# real curriculum's phases, short enough that it cannot crowd out the
# instructions around it.
ANSWER_CHARS = 4000

# --- The ladder -----------------------------------------------------------
# The level below a phase, and the one a real curriculum is actually made of.
# Justin Guitar Grade 1 is about ten modules in order; Couch to 5K is nine
# weeks of three named sessions; a state's driving curriculum is units. This
# app modelled all of that as two to four PHASES with a flat list of steps,
# which is why a finished plan read as "here is some stuff, go and figure out
# how to follow it" rather than "this session, that one, then that one".
#
# A unit is one rung: the title the material gives it, how many sessions it
# takes, and -- where it exists -- somewhere to actually READ it. Which of
# those two places depends on the tier, and the split is not a convenience:
#
#   cited      a `url`, and only ever a page the app really read. Copying a
#              published lesson's text into this app would be reproducing
#              somebody's work AND blurring the exact line the three tiers
#              exist to draw.
#   generated  a `body`, because the app writing the session IS the generated
#              tier, and a made-up plan pointing at a source it does not have
#              is the one thing that tier may never do.
#
# Two is the floor for the same reason it is for a rotation: one rung is not a
# ladder, it is a phase with a second name.
MIN_UNITS = 2
MAX_UNITS = 12
UNIT_TITLE_CHARS = 80
UNIT_BODY_CHARS = 600
# How many sessions one rung may claim. Bounded because this number decides
# pacing, and pacing is the one thing a model has never been allowed to set
# outright -- four is a fortnight of evenings on a single lesson, which is
# already generous for anything a household would follow.
MAX_UNIT_SESSIONS = 4


def _phase_text(ph: dict) -> str:
    """Every word of a phase a family will actually read.

    Every field added to a phase has to arrive here too, or the language
    check quietly stops covering the parts of the plan that are newest.
    """
    words = [str(ph.get(k) or '')
             for k in ('name', 'what', 'milestone', 'progression')]
    words += list(ph.get('steps') or [])
    for sess in (ph.get('rotation') or []):
        if isinstance(sess, dict):
            words.append(str(sess.get('label') or ''))
            words += list(sess.get('steps') or [])
    for unit in (ph.get('units') or []):
        if isinstance(unit, dict):
            words.append(str(unit.get('title') or ''))
            words.append(str(unit.get('body') or ''))
    return ' '.join(w for w in words if w).strip()


def _clean_steps(raw, aim: str) -> list:
    """The actual exercises, drills or material of a phase.

    The missing layer, and the reason a generated strength program read as
    three sentences of nothing: `what` is one paragraph about a phase and
    `milestone` is how you know it ended, and NEITHER of them is the workout.
    A person opening this wants to know what to do on Tuesday.

    Held to the same two rules as everything else here: no external load or
    dose, and the household's own language.
    """
    out = []
    for item in (raw or []):
        text = _clean_line(item, aim, STEP_CHARS)
        if not text:
            continue
        out.append(text)
        if len(out) >= MAX_STEPS:
            break
    return out


def _clean_line(raw, aim: str, cap: int) -> str:
    """One line of plan content, held to the two rules that apply to all of
    it: no external load or dose, and the household's own language.

    Extracted so a field added later cannot quietly arrive unscreened. Every
    string a family reads off a plan goes through here or through
    `_clean_steps`, which is this function in a loop.
    """
    text = str(raw or '').strip()[:cap]
    if not text or _LOAD_RE.search(text) or _looks_foreign(text, aim):
        return ''
    return text


def _clean_rotation(raw, aim: str) -> list:
    """Labelled sessions inside a phase, or nothing at all.

    Held to a higher bar than the fields beside it, because a half-built
    rotation is worse than none: a Tuesday that says "Session B" and lists
    nothing is a dead end, and a rotation of one is a lie about the week. So
    an entry with no surviving steps is dropped, and if fewer than
    MIN_ROTATION entries survive the whole rotation is dropped and the phase
    falls back to its flat steps -- which every surface already draws.
    """
    out = []
    for n, item in enumerate(raw or []):
        if not isinstance(item, dict):
            continue
        steps = _clean_steps(item.get('steps'), aim)
        if not steps:
            continue
        label = _clean_line(item.get('label'), aim, LABEL_CHARS) \
            or f"Session {len(out) + 1}"
        out.append({'label': label, 'steps': steps})
        if len(out) >= MAX_ROTATION:
            break
    return out if len(out) >= MIN_ROTATION else []


def _clean_units(raw, aim: str, urls=None, allow_body: bool = False) -> list:
    """The lessons of a phase, in order, or nothing at all.

    `urls` is the set of pages this app actually read. A unit may carry a link
    only when it is one of them -- a plausible lesson URL is exactly the
    "Following <a real thing>" failure this module exists to prevent, one
    level further down and harder to spot. `allow_body` is the generated
    tier's half of the same rule: the app may write what to do, and may never
    point at a source it does not have.

    Held to the same bar as a rotation: a rung with no title is not a rung,
    and fewer than MIN_UNITS surviving means there was no ladder to describe.
    """
    out = []
    for item in (raw or []):
        if not isinstance(item, dict):
            continue
        title = _clean_line(item.get('title') or item.get('name'), aim,
                            UNIT_TITLE_CHARS)
        if not title:
            continue
        url = ''
        for known in (urls or ()):
            if _same_url(str(item.get('url') or '').strip().rstrip('.,)'),
                         known):
                url = known
                break
        body = (_clean_line(item.get('body'), aim, UNIT_BODY_CHARS)
                if allow_body else '')
        try:
            sessions = int(item.get('sessions') or 1)
        except (TypeError, ValueError):
            sessions = 1
        out.append({'n': len(out) + 1, 'title': title, 'url': url,
                    'body': body,
                    'sessions': max(1, min(MAX_UNIT_SESSIONS, sessions))})
        if len(out) >= MAX_UNITS:
            break
    return out if len(out) >= MIN_UNITS else []


# The line between structure and prescription, and the first cut of it was in
# the wrong place. Refusing every number meant refusing "three sets of eight",
# which is not a prescription -- it is what a workout IS -- and a plan forbidden
# from saying it comes back as the mush that prompted this rule's rewrite:
# "move smoothly through all basic bodyweight patterns with complete control".
# Unfollowable, and unfollowable is its own kind of useless.
#
# So counting is allowed: sets, reps, rounds, minutes, times a session. What
# stays refused is EXTERNAL LOAD and INTAKE -- pounds and kilos on a bar,
# milligrams and millilitres of anything, a percentage of a one-rep max. Those
# are the numbers where a confident wrong answer hurts somebody, and no model
# gets to pick them here. A phase or step carrying one is dropped, exactly like
# a phase carrying no citation, and if that empties the plan the family gets
# time-only with the reason said out loud.
_LOAD_RE = re.compile(
    r'\b\d+\s*(?:lb|lbs|pound|pounds|kg|kgs|kilo|kilos|stone|'
    r'mg|mcg|ml|iu)\b'
    r'|\b\d+\s*%\s*(?:of\s*)?(?:1\s*rm|one[- ]rep)'
    r'|\b\d+\s*rm\b', re.I)

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
    'uncited': ('real pages were read, but nothing on them could be tied '
                'to a phase'),
    'disabled': 'web research is switched off for this household',
    'no_key': 'no research key is set up',
    'capped': "this month's research allowance is spent",
    'unavailable': 'research was unavailable just now',
    'no_plan': 'no published program fit this aim',
    'generation_off': 'made-up plans are switched off for this household',
    'generation_refused': ('this aim needs a real coach or a real course, '
                           'not a plan the app made up'),
    'generation_failed': 'nothing usable came back',
    'no_content': ('the plan that came back never said what to actually do, '
                   'so it was dropped'),
    'load_prescribed': ('the plan that came back prescribed loads or doses, '
                        'which the app will not hand out'),
}

# A research status that means the PIPE broke, not that the world is empty.
# Generating here would dress an outage up as a finding, so these never reach
# the generated tier -- the family gets time-only and a reason to retry.
_OUTAGE_REASON = {'disabled': 'disabled', 'no_key': 'no_key',
                  'capped': 'capped'}

# The shaping contract, in two strengths.
#
# PHASE_SYSTEM_PLAIN is the one that shipped before progression and rotation
# existed, kept verbatim rather than rebuilt, because it is the version known
# to come back with usable citations from a flash-lite model. PHASE_SYSTEM
# asks for the same thing plus the two new fields.
#
# Two prompts and not one, because the first cut of the richer contract cost
# the arc its whole reason for existing. Asking one interactive-tier call for
# phases AND steps AND a progression rule AND a 2-4 session rotation AND a
# citation on every phase pushes both ways at once: more instructions for
# `cite` to compete with, and several times the output tokens to truncate. A
# phase that loses its `cite` is dropped, an answer that truncates fails to
# parse, and BOTH land in the same place -- `_fallback`, which writes a
# labelled made-up plan. So a household that had been getting real curricula
# started getting the app's own for everything, silently, because nothing on
# the way down says "we read four real pages and threw them away".
#
# The fix is not to ask for less. It is to ask for the extras FIRST and fall
# back to the plain contract the moment nothing citable survives -- one extra
# interactive call, only on the pass that already failed, exactly the shape of
# the language-drift repair below. A cited plan without a rotation is the
# outcome that was always intended anyway: the cited tier says what the pages
# said, and where they said nothing about how sessions differ, it says nothing.
_PHASE_CORE = (
    "You are organising material for a household's program, not writing one. "
    "You are given exactly what was read from real pages for this aim -- "
    "organise ONLY that material into 2-4 phases. Do not add a step that is "
    "not supported by the material below. Also name the "
    "program you organised, say in one sentence why it suits this family, "
    "and list the other candidates you did NOT pick with a real reason for "
    "each. `steps` is what the material actually says to DO in that phase -- "
    "the named exercises, drills, lessons or chapters, in order, so somebody "
    "could start a session from them alone. Take them from the material; do "
    "not invent them, and keep them inside the session length given below. "
    "Write EVERY field in the same language the aim is "
    "written in, and do not change language part-way through. Where the "
    "material names a real published program and describes its stages, that "
    "IS a phased plan -- organise it. Reply with an empty phases list only "
    "when the material genuinely describes no program at all."
)

# Said last, alone, and in the imperative, because it is the one rule whose
# failure throws the whole plan away. Buried mid-paragraph it was competing
# with everything else the richer contract asks for.
_PHASE_CITE = (
    "\n\nEVERY phase MUST carry `cite`, holding the number of the material "
    "item it came from as a plain integer -- `\"cite\": 1`, never \"[1]\" and "
    "never a list. A phase without `cite` is discarded."
)

PHASE_SYSTEM_PLAIN = (
    _PHASE_CORE + _PHASE_CITE + "\n\n"
    'Return STRICT JSON: {"plan_name": "", "why_this_one": "", '
    '"phases": [{"name": "", "what": "", "steps": ["", ""], '
    '"milestone": "", "cite": 1}], '
    '"runners_up": [{"cite": 2, "why_not": ""}]}'
)

PHASE_SYSTEM = (
    _PHASE_CORE + "\n\n"
    "`progression` is how somebody makes one session harder than the last one "
    "INSIDE this phase, in the activity's own terms -- one more page, a "
    "faster tempo, one more repetition. Take it from the material; leave it "
    "empty rather than inventing a rule.\n\n"
    "`rotation` is ONLY for a phase whose sessions genuinely differ from each "
    "other. If the material lays out sessions that alternate, give 2-4 with a "
    "short label each; otherwise leave it out. Never manufacture variety.\n\n"
    "`units` is the LADDER: the lessons, modules, weeks or chapters this "
    "phase works through, IN ORDER, each with the title the material gives "
    "it -- \"Module 3: The F chord\", \"Week 4\", \"Chapter 2\". This is the "
    "part a person follows one session at a time, so take it from the "
    "material and never invent a lesson that is not in it. `sessions` is how "
    "many practice sessions that unit takes, 1-4. Give a unit's `url` ONLY "
    "when the material shows that unit's own page; leave it empty otherwise "
    "and never guess one. Leave `units` out entirely if the material names no "
    "ordered lessons."
    + _PHASE_CITE + "\n\n"
    'Return STRICT JSON: {"plan_name": "", "why_this_one": "", '
    '"phases": [{"name": "", "what": "", "steps": ["", ""], '
    '"progression": "", "rotation": [{"label": "", "steps": ["", ""]}], '
    '"units": [{"title": "", "sessions": 1, "url": ""}], '
    '"milestone": "", "cite": 1}], '
    '"runners_up": [{"cite": 2, "why_not": ""}]}'
)

GENERATE_SYSTEM = (
    "No published program was found for this aim, so you are making a real, "
    "followable practice plan for one household, and it will be labelled as "
    "made by an app. 2-4 phases that build on each other.\n\n"
    "BE CONCRETE. `steps` is the actual content of a session -- name the "
    "exercises, drills, pieces, or material, in the order they are done, so "
    "somebody could start on Tuesday from the steps alone. A plan that says "
    "'move through basic patterns with control' and names nothing is a "
    "failure, not a safe answer.\n\n"
    "FIT THE PERSON AND THE SESSION. Write it for the person described below "
    "and for the length of session they actually have -- a plan built for an "
    "hour is not a plan for somebody with twenty minutes. If they are a "
    "child, everything in it has to be doable by a child that age, needing no "
    "equipment and no adult help the steps do not name.\n\n"
    "`progression` is how somebody makes one session harder than the last "
    "one INSIDE a phase, in this activity's own terms -- one more page, a "
    "faster tempo, one more repetition, a longer hold, one less reminder. "
    "Every phase needs one; without it a phase is the same session repeated "
    "until a date passes. It is a rule, never a number on a bar or a dose.\n\n"
    "`rotation` is for a phase whose sessions are NOT all the same session. "
    "Where the activity really does alternate -- technique against material, "
    "new against review, one group of movements against another -- give 2-4 "
    "labelled sessions with their own steps and the app will deal them onto "
    "this family's practice days. Where a session is genuinely the same thing "
    "each time, leave `rotation` out. Do not manufacture variety.\n\n"
    "`units` is the LADDER: the lessons this phase works through IN ORDER, "
    "each with a title and a `body` of a few sentences saying what to "
    "actually do in that session -- enough that somebody could sit down and "
    "follow it without looking anything up. `sessions` is how many sessions "
    "that unit takes, 1-4. NEVER give a unit a `url`: you have no source and "
    "a link you invented is worse than no link.\n\n"
    "You MAY say how much to repeat something: sets, reps, rounds, minutes, "
    "times per session. You may NOT put a number on external load or intake "
    "-- no pounds or kilos on a bar, no percentages of a one-rep max, no "
    "milligrams, doses or supplements. Say 'a weight you could lift a few "
    "more times' instead of naming one.\n\n"
    "Never name a real published program, and never claim a source: you have "
    "none. Do not give week counts; the app computes pacing. Say plainly "
    "what a person should be able to do at the end of each phase. Write "
    "EVERY field in the same language the aim is written in, and do not "
    "change language part-way through. If you cannot do this responsibly for "
    "this aim, reply with an empty phases list.\n\n"
    'Return STRICT JSON: {"why_this_one": "<one sentence on the approach>", '
    '"phases": [{"name": "", "what": "", '
    '"steps": ["<one concrete thing to do>", ""], '
    '"progression": "<how this session beats the last one>", '
    '"rotation": [{"label": "", "steps": ["", ""]}], '
    '"units": [{"title": "", "sessions": 1, "body": "<what to do>"}], '
    '"milestone": ""}]}'
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


def screen_starting_point(text: str) -> dict:
    """The same body screen, on the other free-text field a family types.

    `screen_aim` guards the aim and nothing else, so the moment a second free
    field reaches a prompt it is a way around the one rule this arc will not
    bend -- "learn to cook" with a starting point of "I'm 200 lbs and want to
    be 170" is the refused aim, typed one box lower. Same list, same sentence,
    named as the starting point so nobody has to guess which box objected.
    """
    low = (text or '').strip().lower()
    if not low:
        return {'ok': True}
    if any(term in low for term in BODY_PHRASES) or _BODY_WORD_RE.search(low):
        return {'ok': False,
                'message': ("Same rule for the starting point as for the aim: "
                            "no target weights and no calorie numbers. Say "
                            "what they can already DO instead."),
                'alternatives': list(BEHAVIOUR_ALTERNATIVES)}
    return {'ok': True}


# How much of a starting point reaches a prompt. Long enough for "already
# plays open chords, owns a guitar with old strings", short enough that it
# cannot become an essay that crowds out the material.
STARTING_POINT_CHARS = 240


def _who_line(member: dict, member_name: str = '') -> str:
    """Who the plan is for, in the only terms this app actually knows.

    A plan's single biggest variable in EVERY domain is the age of the person
    following it -- a reading ladder, a cooking program and a bike-skills
    progression are three different documents for a nine-year-old and for an
    adult -- and until this line existed the model was handed a first name and
    nothing else, so every plan came back written for a generic adult beginner.

    Age is stated only when a birthdate really is on file. `stages.age_of`
    returns None rather than a zero for exactly this reason, and guessing --
    from a stage, from a role, from a name -- would be inventing the one fact
    that decides the plan.
    """
    name = (member or {}).get('name') or member_name or ''
    who = f"{name}" if name else 'one person'
    if not member:
        return who
    age = stages.age_of(member)
    if (member.get('role') or '') == 'child':
        return f"{who}, {age} years old" if age is not None else f"{who}, a child"
    return f"{who}, an adult" if age is None else f"{who}, {age} years old"


def _context_block(member: dict, member_name: str, per_week: int,
                   minutes: int, starting_point: str) -> str:
    """Everything about this household that changes what the plan should say.

    One builder for both tiers, because the two prompts drifting apart is how
    the generated tier ended up never being told the session length at all --
    the cited path passed `minutes` from the day it was written and the
    generated path simply did not, so a family with twenty-minute evenings got
    a plan built for an hour and no surface ever said the two disagreed.
    """
    lines = [f"Who this is for: {_who_line(member, member_name)}.",
             f"Their week: {per_week} sessions, {minutes} minutes each. "
             f"What a session contains has to FIT {minutes} minutes."]
    start = (starting_point or '').strip()[:STARTING_POINT_CHARS]
    if start:
        lines.append(f"Where they are starting from: {start}")
    return "\n".join(lines)


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
            'origin': ORIGIN_NONE, 'reason': reason, 'hand_written': True,
            'book_spine': ''}


def _source_generated(why: str, answer: str = '', reason: str = 'no_plan') -> dict:
    """A plan the app made. No plan name and no url, on purpose: those two
    fields are what the card renders as "Following <a real thing>", and a
    generated plan has nothing to point at.

    `reason` used to be 'no_plan' whatever had happened, which is a false
    statement in the one case worth telling apart: real pages WERE read and
    the shaping simply could not tie a phase to any of them. That is a
    different fact about the world from "the web has nothing on this aim",
    and it is the fact you need when generated plans start arriving for aims
    that used to find real ones.
    """
    return {'plan_name': '', 'url': '', 'why_this_one': why,
            'facts': [], 'runners_up': [], 'answer': answer,
            'origin': ORIGIN_GENERATED, 'reason': reason,
            'hand_written': True, 'book_spine': ''}


def curate(title: str, shape: dict, member_name: str = '',
           member: dict = None, starting_point: str = '',
           exclude_books: bool = False) -> dict:
    """One research run, turned into cited phases -- or an honest fallback.

    Returns {'phases': [...], 'source': {...}}. Phase CONTENT comes from pages
    that were read where there were any; phase PACING is arithmetic over
    `shape` in every tier, because pacing is exactly where a model would
    otherwise start writing curriculum.

    `member` is the whole member row rather than a name, so the one fact that
    changes a plan more than any other -- how old the person following it is
    -- reaches both tiers. `member_name` stays for callers that only ever had
    one, and for a member who has since been removed.

    `exclude_books` asks the research question itself to steer past anything
    that starts with a purchase, and does not stop there: a plan can still
    come back leaning on a book even when the question asked it not to, so
    the answer is checked too, with the same `book_spine_of` a family's own
    "no books" tap uses, and a plan that still fails it is handed to the
    generated tier instead of back to the family.
    """
    per_week = int((shape or {}).get('sessions_per_week') or 3)
    minutes = int((shape or {}).get('minutes') or 25)
    context = _context_block(member, member_name, per_week, minutes,
                             starting_point)
    question = (f"What is the best established, existing, step-by-step program "
                f"a beginner should follow to {title}? Name the real program "
                f"and its phases. Prefer pages that actually teach the "
                f"material over pages that merely list or review books. "
                f"Do not invent one.")
    if exclude_books:
        question += (" Only consider programs that can be followed without "
                     "buying a book — free online curricula with the "
                     "lessons on the page.")
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
        return _fallback(title, per_week, api_key, context, '')

    answer = (res.get('answer') or '').strip()
    items = _material(res)
    if not items:
        return _fallback(title, per_week, api_key, context, answer)

    shaped = _phases_from(title, items, per_week, api_key, context,
                          answer=answer)
    if not shaped['phases']:
        # Reached here the material was real and the shaping still produced
        # nothing citable -- twice, since `_phases_from` already spent a
        # second call on the plainer contract before giving up. That used to
        # end the story; now it falls through to a labelled plan built on the
        # material, which is a far better answer than a naked calendar
        # reservation. It is also the one route to a generated plan that is
        # worth watching: pages really were read, so a run of these means the
        # shaping is failing rather than the web being empty.
        print(f"[programs] read {len(items)} items for {title!r} and cited "
              f"none of them -- falling back to a made plan")
        return _fallback(title, per_week, api_key, context, answer,
                         uncited=True)

    src = {'plan_name': shaped['plan_name'],
           'url': shaped['url'] or items[0]['url'],
           'why_this_one': shaped['why_this_one'] or answer[:400],
           'facts': [{'claim': i['claim'], 'url': i['url']}
                     for i in items],
           'runners_up': shaped['runners_up'],
           'answer': answer,
           'origin': ORIGIN_CITED, 'reason': '',
           'hand_written': False,
           'book_spine': book_spine_of(shaped['phases'])}
    if exclude_books and src['book_spine']:
        # Asked for booklessness and the web still answered with a shelf:
        # an app-made plan that says so beats a purchase order.
        print(f"[programs] bookless ask for {title!r} still came back "
              f"book-spined -- generating instead")
        return _fallback(title, per_week, api_key, context, answer)
    return {'phases': shaped['phases'], 'source': src}


def _fallback(title: str, per_week: int, api_key: str, context: str,
              answer: str, uncited: bool = False) -> dict:
    """No cited plan. Make one and label it, or say why not even that.

    `uncited` says which of the two ways we got here: the web had nothing, or
    the web had something and none of it survived the citation rule.
    """
    settings = storage.get_settings() or {}
    if not settings.get('programs_generate_enabled', True):
        return {'phases': [], 'source': _source_none('generation_off', answer)}
    if not generation_allowed(title):
        return {'phases': [],
                'source': _source_none('generation_refused', answer)}
    made = _generated_phases(title, per_week, api_key, context, answer)
    if made['reason']:
        return {'phases': [], 'source': _source_none(made['reason'], answer)}
    return {'phases': made['phases'],
            'source': _source_generated(
                made['why_this_one'], answer,
                reason='uncited' if uncited else 'no_plan')}


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


# A step that only points at a purchasable artifact. "Work through X",
# "complete X", "buy X" plus a book-shaped token. Deliberately dumb -- a
# phrase list, not a model -- because this decides whether the family is
# ASKED a question, and a safety-adjacent ask must not depend on a model's
# mood (same reasoning as the body screen above).
_BOOK_TOKENS = re.compile(
    r'\b(book|books|primer|workbook|method book|lesson book|volume|level'
    r'|grade)\b', re.I)
_BOOK_VERBS = re.compile(r'\b(work through|complete|finish|buy|get|order'
                         r'|start)\b', re.I)
# A capitalised run of 2+ words: the series name a step names, once the verb
# in front of it and the level word after it are cut away. Matching the raw
# step was the first draft, and it failed its own tests: a one-word verb
# that opens a sentence -- "Complete Piano Adventures Level 1" -- capitalises
# exactly like a title word, so the verb rode along in the match, and
# "Level"/"Primer"/"Grade" rode along on the far end for the same reason.
# Two phases naming the same series then produced two DIFFERENT strings,
# sharing no common prefix at all.
_SERIES_RE = re.compile(r'\b([A-Z][a-z]+(?: [A-Z][a-z]+)+)')


def _book_step(step: str) -> str:
    """The series name a step names, when the step is ONLY a pointer at a
    purchasable artifact -- else ''.

    Trims the verb phrase off the front and the book/level word (and
    everything from there on) off the back before it goes looking for a
    title, so "Work through X Level 1" and "Complete X Book 2" agree on X
    even though one buries a verb inside what looks like a title-cased run
    and the other doesn't.
    """
    s = str(step or '')
    tok = _BOOK_TOKENS.search(s)
    if not (tok and _BOOK_VERBS.search(s)):
        return ''
    middle = s[:tok.start()]
    verb = _BOOK_VERBS.search(middle)
    if verb:
        middle = middle[verb.end():]
    m = _SERIES_RE.search(middle)
    return m.group(1) if m else ''


def book_spine_of(phases: list) -> str:
    """The book series a plan leans on, when the plan leans on nothing else.

    'Cited' is sometimes hollow: the page read names lesson books and
    teaches nothing -- the real content is a purchase away. That plan is
    still worth having (a good series carries real sequencing knowledge),
    but the family should be asked, not surprised at the till.

    Flagged only when EVERY phase is book-shaped: all steps are purchase
    pointers and no unit carries an instructional url. One taught phase, or
    one cited unit, and the plan can be followed without buying anything --
    a book line inside it is a resource, not a spine.
    """
    names = []
    for ph in (phases or []):
        if not isinstance(ph, dict):
            return ''
        if any((u or {}).get('url') for u in (ph.get('units') or [])):
            return ''
        steps = [s for s in (ph.get('steps') or []) if str(s or '').strip()]
        if not steps:
            return ''
        per_step = [_book_step(s) for s in steps]
        if not all(per_step):
            return ''
        names += per_step
    if not names:
        return ''
    # Every step already agrees once _book_step has trimmed it, but this
    # keeps only the words every name shares, left to right, so a stray
    # difference at the margin shrinks the name instead of blanking it.
    first = names[0].split()
    for n in names[1:]:
        words = n.split()
        keep = 0
        for a, b in zip(first, words):
            if a != b:
                break
            keep += 1
        first = first[:keep]
    return ' '.join(first) if len(first) >= 2 else names[0]


def unit_sessions(units) -> int:
    """How many sessions a phase's ladder actually asks for."""
    return sum(max(1, int(u.get('sessions') or 1))
               for u in (units or []) if isinstance(u, dict))


def phase_weeks(per_week: int, units=None) -> int:
    """How many weeks a phase takes. Computed, not asked for -- see the
    SESSIONS_PER_PHASE comment above.

    With a ladder, the arithmetic finally runs over something true. Without
    one it ran over a CONSTANT: every phase in every domain was
    `ceil(12 / per_week)`, so at two evenings a week Lesson 1 and Lesson 4
    were both "6w" on the card, and the number said nothing about either. It
    was arithmetic, which was the rule, but arithmetic over a placeholder is
    a placeholder.

    Public because editing a proposal's shape has to re-pace the phases it
    already has, and re-pacing by copying this arithmetic into main.py is how
    two pacing rules start disagreeing.
    """
    safe = per_week if isinstance(per_week, int) and per_week > 0 else 1
    sessions = unit_sessions(units) or SESSIONS_PER_PHASE
    return max(1, math.ceil(sessions / safe))


_phase_weeks = phase_weeks


# The keys a model reaches for when it means `cite`. Naming them is not
# loosening the rule: whatever key it arrives under still has to resolve to a
# numbered item this app actually read, or to a URL that is one of theirs.
# What was costing real plans was the SPELLING of the key and the SHAPE of
# the value, neither of which is the thing being checked.
_CITE_KEYS = ('cite', 'citation', 'cite_index', 'ref', 'reference',
              'source_index', 'material', 'item')
_INT_RE = re.compile(r'\d+')


def _cite_index(value):
    """The number a model meant, out of whatever it actually sent.

    Every shape below was a real answer that resolved to nothing and cost a
    whole cited plan: "[1]" (copying the corpus marker back), "1." (copying a
    list label), [1] (a list because the phase might cite several), 1.0 (a
    float, because JSON has one number type and models know it). None of them
    is a different CLAIM from `1`; they are the same claim typed differently,
    and a citation rule that only accepts one typing is checking the typing.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value == int(value) else None
    if isinstance(value, (list, tuple)):
        for item in value:
            n = _cite_index(item)
            if n is not None:
                return n
        return None
    if isinstance(value, str):
        m = _INT_RE.search(value)
        return int(m.group()) if m else None
    return None


def _same_url(a: str, b: str) -> bool:
    """Two URLs that differ only in a trailing slash are one URL."""
    return a.rstrip('/') == b.rstrip('/')


def _cited_url(ph: dict, by_ref: dict, urls: set) -> str:
    """The page behind a phase, or ''.

    A `cite` INDEX is the primary form and the reason this is not the old
    check: the model used to have to copy a long resolved URL exactly, and a
    single character of drift threw away an entire real plan. An exact URL is
    still accepted, because a model handed material with URLs in it will
    sometimes answer that way and there is no reason to punish a citation that
    is provably right.

    What this does NOT do is guess. An index outside the material, a URL that
    is not one of the pages we read, and a phase with no citation at all are
    all still nothing -- the rule is that a phase names material this app
    really fetched, and it survives every repair above intact.
    """
    for key in _CITE_KEYS:
        if key not in ph:
            continue
        ref = _cite_index(ph.get(key))
        if ref is not None and ref in by_ref:
            return by_ref[ref]['url']
    for key in ('url', 'source', 'source_url', 'link'):
        url = str(ph.get(key) or '').strip().rstrip('.,)')
        if not url:
            continue
        for known in urls:
            if _same_url(url, known):
                return known
    return ''


def _phase_payload(data):
    """What came back, as the object this module expects, or None.

    `llm._call_llm_json` scans a response for top-level JSON and returns the
    LAST thing it found, which is right for a model that chatters before its
    answer and wrong for one that chatters after it: an answer followed by so
    much as a bare "[1]" comes back as the list `[1]`, and a plan that arrived
    perfectly intact is discarded here for not being a dict. The same scan
    turns a bare array of phases -- which is what a model returns when it
    reads "phases" as the answer rather than as a field -- into a list this
    code then refuses.

    Neither of those is a plan that failed. They are a plan that survived the
    model and died in the plumbing.
    """
    if isinstance(data, dict):
        return data
    if isinstance(data, list):
        phases = [p for p in data if isinstance(p, dict)
                  and (p.get('name') or p.get('what') or p.get('steps'))]
        if phases:
            return {'phases': phases}
    return None


def _shaping_note(data) -> str:
    """One line saying what actually came back, for the log that has to
    settle this rather than narrow it.

    Written because two rounds of this were spent reasoning about a payload
    nobody had looked at: "nothing citable" covers an error, an empty answer,
    phases with no citation and phases citing something we never read, and
    those four want four different fixes.
    """
    if data is None:
        return 'the call raised'
    if isinstance(data, dict) and data.get('error'):
        return f"error={str(data.get('error'))[:160]!r} model={data.get('_model')}"
    payload = _phase_payload(data)
    if payload is None:
        return f"answer was a {type(data).__name__}, not an object: {str(data)[:160]!r}"
    phases = [p for p in (payload.get('phases') or []) if isinstance(p, dict)]
    if not phases:
        return (f"no phases in the answer; keys={sorted(payload)[:8]} "
                f"model={payload.get('_model')}")
    first = phases[0]
    cites = [p.get('cite') for p in phases]
    return (f"{len(phases)} phases, none citable; keys={sorted(first)[:8]} "
            f"cites={cites!r} model={payload.get('_model')}")


def _phases_from(title: str, items: list, per_week: int,
                 api_key: str, context: str = '', answer: str = '') -> dict:
    """Turn what was read into phases, then drop any that cite nothing.

    The model is asked to organise material it was given, not to produce
    material. Anything whose citation is not one of the items we actually put
    in front of it is discarded -- the same discipline `web.research`'s own
    `dropped` counter applies one level down.

    `answer` is why this function had stopped working at all on the route
    nearly every household uses. On the GROUNDING route a "fact" is a page
    TITLE (`_material`: `'claim': title or answer[:160]`), so the material
    handed to shaping was three page names -- "Justin Guitar - Free Online
    Guitar Lessons" and two more like it -- and nothing whatsoever about what
    those pages SAY. A model told to organise only that material, and told
    plainly to return an empty phases list where the material does not support
    a plan, returned an empty phases list. It was right to. Every one of those
    empty answers then fell through to generation, which HAD been receiving
    the grounded answer all along as its context -- so the tier that invents
    a plan was the only tier holding the substance to build one from.

    The answer is not an extra source and does not weaken the citation rule:
    it is what those pages said, and `cite` still has to name one of them. A
    grounding citation was always the weaker page-level kind, which is exactly
    what `_material` says about it.
    """
    by_ref = {n + 1: it for n, it in enumerate(items)}
    urls = {it['url'] for it in items}
    corpus = "\n".join(
        f"[{n}] {it['claim']}"
        + (f" (page: {it['title']})" if it['title'] else '')
        + f" <{it['url']}>" for n, it in by_ref.items())
    answer = (answer or '').strip()[:ANSWER_CHARS]
    material = (f"What the research found, built from the pages below -- this "
                f"is the material:\n{answer}\n\nThe pages it was built from, "
                f"numbered for `cite`:\n{corpus}"
                if answer else
                f"What was actually read from real pages:\n{corpus}")
    prompt = f"Aim: {title}.\n{context}\n\n{material}"
    empty = {'phases': [], 'plan_name': '', 'url': '', 'why_this_one': '',
             'runners_up': []}

    def _ask(system):
        try:
            return _pool_call(TIER, api_key, system, prompt,
                              timeout_s=60, gemma_timeout_s=180)
        except Exception as e:
            print(f"[programs] phase shaping failed: {e}")
            return None

    def _build(data):
        """Phases that survive the citation rule, or None if none did.

        None and an empty list are the same outcome to a caller and very
        different in here: it is what decides whether the plainer contract is
        worth one more call.
        """
        if isinstance(data, dict) and data.get('error'):
            return None
        payload = _phase_payload(data)
        if payload is None:
            return None
        out, used = [], []
        for ph in (payload.get('phases') or [])[:4]:
            if not isinstance(ph, dict):
                continue
            url = _cited_url(ph, by_ref, urls)
            if not url:
                # A plausible phase with no page behind it does not get to be
                # a phase. This is the whole rule.
                continue
            if _looks_foreign(_phase_text(ph), title):
                # Same rule, different failure: a phase nobody in this house
                # can read is not a phase either.
                print("[programs] dropped a phase written in another language")
                continue
            used.append(url)
            # Note: any 'weeks' the model sent is ignored. Pacing is
            # arithmetic over `shape` -- never a number out of the model.
            # A rotation the material really described replaces nothing:
            # `steps` stays the phase's material so every surface written
            # before rotations existed keeps drawing something true, and the
            # rotation is what a DATED window uses. Deriving `steps` from the
            # first session rather than asking for it twice also keeps the
            # empty-steps gate honest.
            rotation = _clean_rotation(ph.get('rotation'), title)
            # A link only ever points at a page this app really read. The
            # generated tier's `body` is refused here outright: a cited phase
            # carrying the app's own prose would be the one thing the tiers
            # exist to keep apart, wearing a citation.
            units = _clean_units(ph.get('units'), title, urls=urls)
            steps = _clean_steps(ph.get('steps'), title) or (
                list(rotation[0]['steps']) if rotation else [])
            out.append({'name': (ph.get('name') or f"Phase {len(out) + 1}")[:60],
                        'weeks': phase_weeks(per_week, units),
                        'what': (ph.get('what') or '').strip()[:400],
                        'steps': steps,
                        'progression': _clean_line(ph.get('progression'), title,
                                                   PROGRESSION_CHARS),
                        'rotation': rotation,
                        'units': units,
                        'unit_shift': 0,
                        'milestone': (ph.get('milestone') or '').strip()[:120],
                        'milestone_hit_at': None})
        return (out, used, payload) if out else None

    rich = _ask(PHASE_SYSTEM)
    built = _build(rich)
    if built is None:
        # The richer contract asked for more than this model could return with
        # its citations intact -- either it dropped `cite` under the weight of
        # everything else it was being asked for, or the longer answer never
        # finished parsing. Both land exactly here, and the behaviour used to
        # be to walk straight past into a made-up plan: which is how a
        # household that had been getting real curricula started getting the
        # app's own for everything, with nothing anywhere saying so.
        #
        # One more call, on the contract that shipped before progression and
        # rotation existed. A cited plan without those two fields is what the
        # cited tier was always going to be wherever the pages say nothing
        # about them, and it beats a made-up plan every time.
        print(f"[programs] nothing citable in the shaped plan "
              f"({_shaping_note(rich)}) -- asking again for the plan alone")
        plain = _ask(PHASE_SYSTEM_PLAIN)
        built = _build(plain)
        if built is None:
            print(f"[programs] the plain contract came back the same way "
                  f"({_shaping_note(plain)})")
    if built is None:
        return empty
    out, used, data = built

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
                      context: str, answer: str) -> dict:
    """Make a plan, label it, and hold it to the two rules that survive the
    move from curating to generating: pacing is still arithmetic, and a phase
    that prescribes a load or a dose is still dropped.

    Returns {'phases', 'why_this_one', 'reason'} -- a non-empty `reason` means
    no plan, and names which way it failed.
    """
    heard = (f"\n\nWhat the web said about this aim, uncited and NOT to be "
             f"quoted as a source:\n{answer}" if answer else '')
    prompt = f"Aim: {title}.\n{context}{heard}"

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

    out, dropped, foreign, empty = [], 0, 0, 0
    for ph in (data.get('phases') or [])[:4]:
        if not isinstance(ph, dict):
            continue
        rotation = _clean_rotation(ph.get('rotation'), title)
        # No `urls` at all, so any link the model produced is dropped: a made
        # plan has no source and may never appear to have one.
        units = _clean_units(ph.get('units'), title, allow_body=True)
        clean = {'name': (ph.get('name') or f"Phase {len(out) + 1}")[:60],
                 'what': (ph.get('what') or '').strip()[:400],
                 'steps': (_clean_steps(ph.get('steps'), title)
                           or (list(rotation[0]['steps']) if rotation else [])),
                 'progression': _clean_line(ph.get('progression'), title,
                                            PROGRESSION_CHARS),
                 'rotation': rotation,
                 'units': units,
                 'unit_shift': 0,
                 'milestone': (ph.get('milestone') or '').strip()[:120]}
        if not clean['what']:
            continue
        if _prescribes_load(clean):
            dropped += 1
            continue
        if not clean['steps']:
            # The rule that makes "be concrete" real rather than requested. A
            # generated phase with nothing to DO in it is the failure that
            # started this: three sentences about moving smoothly through
            # basic patterns, and no way to begin. Checked AFTER the load rule
            # so a phase that broke both is reported by the one that matters.
            empty += 1
            continue
        if _looks_foreign(_phase_text(clean), title):
            foreign += 1
            continue
        clean['weeks'] = phase_weeks(per_week, units)
        clean['milestone_hit_at'] = None
        out.append(clean)
    if not out:
        reason = ('load_prescribed' if dropped else
                  'no_content' if empty else 'generation_failed')
        return {'phases': [], 'why_this_one': '', 'reason': reason}
    why = (data.get('why_this_one') or '').strip()[:400]
    return {'phases': out,
            'why_this_one': why or ('No published program fit this aim, '
                                    'so this plan was made for it.'),
            'reason': ''}
