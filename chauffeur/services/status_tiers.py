"""Auto-earned recognition tiers for kids — a light touch of gamification, not a
full achievements engine.

A tier is reached by hitting EITHER a lifetime points-earned threshold OR a
best-routine-streak threshold, and the displayed status is the highest tier
reached across both tracks. Both inputs are monotonic (lifetime earned never
drops when rewards are redeemed; best streak only rises), so a status is never
taken away — it is recognition, not a scoreboard that can demote you.
"""
from typing import Optional, Dict, List

# Built-in default ladder, low -> high. A member reaches a tier when
# points_earned >= points OR best_streak >= streak. Families can override the
# whole ladder from the Chores/Routines pages (settings['status_tiers']).
DEFAULT_TIERS = [
    {"name": "Rising Star",   "emoji": "🌱", "points": 25,  "streak": 3},
    {"name": "Super Helper",  "emoji": "⭐", "points": 100, "streak": 7},
    {"name": "Everyday Hero", "emoji": "🦸", "points": 250, "streak": 14},
    {"name": "Legend",        "emoji": "👑", "points": 500, "streak": 30},
]


def get_tiers() -> List[Dict]:
    """The effective ladder: the family's configured tiers, or the defaults."""
    from services import storage
    configured = storage.get_settings().get("status_tiers")
    return configured if isinstance(configured, list) and configured else DEFAULT_TIERS


def status_for(points_earned: int, best_streak: int, tiers: Optional[List[Dict]] = None) -> Optional[Dict]:
    """Highest tier reached, or None before the first threshold. Evaluated in
    ascending threshold order so 'highest reached wins' regardless of config order."""
    tiers = tiers if tiers is not None else get_tiers()
    reached = None
    for t in sorted(tiers, key=lambda t: (t.get("points", 0), t.get("streak", 0))):
        if (points_earned or 0) >= t.get("points", 0) or (best_streak or 0) >= t.get("streak", 0):
            reached = t
    return reached


def compute_member_status(member_id: str) -> Optional[Dict]:
    from services import storage
    earned = storage.get_points_earned(member_id)
    best = storage.compute_streak(member_id).get("best", 0)
    return status_for(earned, best)
