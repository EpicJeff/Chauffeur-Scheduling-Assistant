"""Auto-earned recognition tiers for kids — a light touch of gamification, not a
full achievements engine.

Two independent single-metric ladders, so each board's badge reflects THAT
board's performance honestly:
  - chore tiers   -> lifetime points earned (monotonic; redeeming never subtracts)
  - routine tiers -> best routine streak    (monotonic; only rises)

Each tier is {name, emoji, threshold}; the displayed status is the highest tier
whose threshold the value meets. Families can override either ladder from the
Chores / Routines pages (settings['chore_status_tiers'] / ['routine_status_tiers']).
"""
from typing import Optional, Dict, List

DEFAULT_CHORE_TIERS = [
    {"name": "Rising Star",   "emoji": "🌱", "threshold": 25},
    {"name": "Super Helper",  "emoji": "⭐", "threshold": 100},
    {"name": "Everyday Hero", "emoji": "🦸", "threshold": 250},
    {"name": "Legend",        "emoji": "👑", "threshold": 500},
]

DEFAULT_ROUTINE_TIERS = [
    {"name": "Getting There", "emoji": "🌱", "threshold": 3},
    {"name": "Consistent",    "emoji": "⭐", "threshold": 7},
    {"name": "Streak Star",   "emoji": "🔥", "threshold": 14},
    {"name": "Unstoppable",   "emoji": "👑", "threshold": 30},
]

_SETTINGS_KEY = {"chore": "chore_status_tiers", "routine": "routine_status_tiers"}
_DEFAULTS = {"chore": DEFAULT_CHORE_TIERS, "routine": DEFAULT_ROUTINE_TIERS}


def _norm(kind: str) -> str:
    return "routine" if kind == "routine" else "chore"


def get_tiers(kind: str) -> List[Dict]:
    """The effective ladder for 'chore' or 'routine' — configured or default."""
    from services import storage
    k = _norm(kind)
    configured = storage.get_settings().get(_SETTINGS_KEY[k])
    return configured if isinstance(configured, list) and configured else _DEFAULTS[k]


def status_for(value: int, tiers: List[Dict]) -> Optional[Dict]:
    """Highest tier whose threshold `value` meets, or None below the first."""
    reached = None
    for t in sorted(tiers, key=lambda t: t.get("threshold", 0)):
        if (value or 0) >= t.get("threshold", 0):
            reached = t
    return reached


def compute_member_status(member_id: str, kind: str) -> Optional[Dict]:
    """Status on the 'chore' track (lifetime points earned) or the 'routine'
    track (best streak). Both inputs are monotonic, so a status is never lost."""
    from services import storage
    k = _norm(kind)
    if k == "routine":
        value = storage.compute_streak(member_id).get("best", 0)
    else:
        value = storage.get_points_earned(member_id)
    return status_for(value, get_tiers(k))
