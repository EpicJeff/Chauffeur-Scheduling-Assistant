"""Household feature switches: whole features a family can turn off.

Two today, both on the chores page because that is where their economies are
already tuned:

  critters_enabled  The critter game (pets arc). Off, no critter stands beside
                    anyone, no door to the editor or the arena exists on the
                    wall or in the app, and `/api/pets*` answers 404.
  rewards_enabled   The rewards store and the pooled family goals. Off, nobody
                    can ask for a reward or pledge to a goal, and the lanes,
                    tiles, PWA and Argyle stop offering them.

**Off hides; it never takes.** Pets, xp, rewards, pledges and pending
requests all stay exactly as they were, so turning a feature back on finds
everything where the family left it -- that is what makes "temporarily" true.
XP keeps minting while critters are off (a chore done in the quiet weeks
still counted), and points keep accruing while rewards are off (chores are
not the reward store). A parent can still decide a request that was pending
when rewards went off and still edit the catalog: the switch closes the shop
to the family, not to the people running it.

One reader per switch, and both default ON: a household that never sees
these settings sees exactly what it saw before them.
"""
from typing import Optional


def _settings() -> dict:
    try:
        from services import storage
        return storage.get_settings() or {}
    except Exception:
        return {}


def critters_enabled(settings: Optional[dict] = None) -> bool:
    s = settings if settings is not None else _settings()
    return s.get('critters_enabled', True) is not False


def rewards_enabled(settings: Optional[dict] = None) -> bool:
    s = settings if settings is not None else _settings()
    return s.get('rewards_enabled', True) is not False


def snapshot(settings: Optional[dict] = None) -> dict:
    """What a page needs to shape itself, rendered into every page's head as
    `window.chfFeatures`. Never raises -- a page must still draw."""
    s = settings if settings is not None else _settings()
    return {'critters': critters_enabled(s), 'rewards': rewards_enabled(s)}


# Rewards routes a CHILD acts through. Withdrawing a pledge is deliberately
# absent: it gives points back, and the family must always be able to do that.
_REWARD_ASKS = {
    ('POST', '/api/rewards/{reward_id}/redeem'),
    ('POST', '/api/rewards/{reward_id}/contribute'),
}


def refusal(method: str, path_template: str) -> Optional[tuple]:
    """(status, detail) when a switched-off feature owns this route, else None.

    Matched against the route TEMPLATE (the auth guard's idiom), so an id can
    never be mistaken for part of the decision. Only reads settings for the
    two families of routes it can refuse."""
    path = path_template or ''
    if path == '/api/pets' or path.startswith('/api/pets/'):
        if not critters_enabled():
            return 404, 'Critters are switched off'
        return None
    if (method, path) in _REWARD_ASKS and not rewards_enabled():
        return 409, 'Rewards are switched off'
    return None
