"""The shared, deterministic screen for body-composition language."""
import re

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
    'weight loss',
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

_NUMBER = r'\d+(?:,\d{3})*(?:\.\d+)?'
_WEIGHT_RE = re.compile(
    r'\b' + _NUMBER + r'\s*(?:kgs?|kilos?|lbs?|pounds?|stone)\b')
_LOSE_NUMBER_RE = re.compile(r'\blose\s+' + _NUMBER + r'\b')

# These new numeric matches describe body targets, not a load being lifted.
# The original keywords above still take precedence, preserving even their
# deliberate false refusals (including lifting aims phrased with "lbs").
_LIFT_PREFIX_RE = re.compile(
    r'\b(?:deadlift|squat|bench(?:\s+press)?|overhead\s+press|lift|press|row)'
    r'(?:ing|s|ed)?\s+(?:(?:up\s+to|at|with)\s+)?$')

# Inches alone could describe shelves. Require a named body part in the same
# clause, in either order ("waist to 24 inches" or "24 inch waist"). BMI and
# body-fat percentages are already covered by the original words and phrases.
_BODY_PART = r'\b(?:waist|hips|chest|belly|thighs|arms|neck)\b'
_MEASUREMENT = r'\b' + _NUMBER + r'\s*(?:inches|inch|in|cm)\b'
_BODY_MEASUREMENT_RE = re.compile(
    _BODY_PART + r'[^.!?;\n]*?' + _MEASUREMENT + r'|'
    + _MEASUREMENT + r'[^.!?;\n]*?' + _BODY_PART)


def is_body_goal(text: str) -> bool:
    """Does this text contain a body target or the existing screen's terms?"""
    low = (text or '').strip().lower()
    if not low:
        return False
    if any(term in low for term in BODY_PHRASES) or _BODY_WORD_RE.search(low):
        return True
    if _LOSE_NUMBER_RE.search(low) or _BODY_MEASUREMENT_RE.search(low):
        return True
    return any(not _LIFT_PREFIX_RE.search(low[:match.start()])
               for match in _WEIGHT_RE.finditer(low))
