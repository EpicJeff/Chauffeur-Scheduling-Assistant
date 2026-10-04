"""Seasons: when a chore or a reward is on offer.

A family's year has shapes -- "mow the lawn" is a summer job, "rake leaves" an
autumn one, a sledding trip a winter reward, hot chocolate a cool-months one,
a holiday cookie bake a December one. Showing those all year is noise at best
and a broken promise at worst ("redeem: pool day" in January).

So a chore or a reward may carry a YEARLY window, `season_start` and
`season_end`, each "MM-DD", inclusive at both ends. It recurs every year with
no year in it, because the seasons do: set Jun 1 – Aug 31 once and it comes
back next June on its own. A window whose start is after its end wraps New
Year (Nov 15 – Jan 5). No window, or half of one, means all year.

On top of that a reward has `active`, the parent's hand switch -- off is off
whatever the season says. Chores have no switch: that was not asked for, and
a chore nobody wants any more is deleted, not paused.

**Out of season hides; it never takes.** Nothing is deleted or reset. The
Chores page still lists every row with its status so a parent can edit it;
only the family's views (PWA, lanes, wall tiles, Argyle, the asks) skip it.
A pending request or pledge on a reward that goes out of season stays where
it is, and a parent can still decide it.
"""
import datetime
import re
from typing import Optional, Tuple

_MMDD = re.compile(r'^(\d{2})-(\d{2})$')
_MONTHS = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep',
           'Oct', 'Nov', 'Dec')


def parse(value) -> Optional[Tuple[int, int]]:
    """(month, day) for a valid "MM-DD", else None. Feb 29 is valid: a window
    may name it, and in a common year Feb 28 simply comes right before Mar 1."""
    m = _MMDD.match(str(value or '').strip())
    if not m:
        return None
    month, day = int(m.group(1)), int(m.group(2))
    if not 1 <= month <= 12:
        return None
    try:
        datetime.date(2000, month, day)      # a leap year, so 02-29 passes
    except ValueError:
        return None
    return month, day


def clean(start, end) -> Tuple[Optional[str], Optional[str]]:
    """Normalise a submitted window. Both blank -> (None, None), all year.
    Raises ValueError with a sentence a parent can act on otherwise."""
    s_blank = not str(start or '').strip()
    e_blank = not str(end or '').strip()
    if s_blank and e_blank:
        return None, None
    if s_blank or e_blank:
        raise ValueError("A season needs both a start and an end date "
                         "(leave both empty for all year)")
    s, e = parse(start), parse(end)
    if not s or not e:
        raise ValueError("Season dates must be real dates, like 06-01")
    if s == e:
        raise ValueError("A season must be longer than one day "
                         "(leave both empty for all year)")
    return '%02d-%02d' % s, '%02d-%02d' % e


def in_season(item: dict, today: Optional[datetime.date] = None) -> bool:
    s = parse((item or {}).get('season_start'))
    e = parse((item or {}).get('season_end'))
    if not s or not e:
        return True
    today = today or datetime.date.today()
    t = (today.month, today.day)
    if s <= e:
        return s <= t <= e
    return t >= s or t <= e                  # wraps New Year


def label(item: dict) -> Optional[str]:
    """'Jun 1 – Aug 31', or None for all year."""
    s = parse((item or {}).get('season_start'))
    e = parse((item or {}).get('season_end'))
    if not s or not e:
        return None
    return '%s %d – %s %d' % (_MONTHS[s[0] - 1], s[1], _MONTHS[e[0] - 1], e[1])


def reward_offered(reward: dict, today: Optional[datetime.date] = None) -> bool:
    """Is this reward in the family's store right now? The household-wide
    switch is checked by the caller (household_features), not here."""
    return (reward or {}).get('active', True) is not False and in_season(reward, today)


def chore_offered(chore: dict, today: Optional[datetime.date] = None) -> bool:
    """Does the family see this chore right now?

    In season: always. Out of season, work already under way is never yanked
    out from under somebody: a chore DONE and waiting for a parent stays (or
    the points could never be verified), and so does one a child CLAIMED out
    of the pot. What goes quiet is the pot itself (open), last period's
    finished row (verified), and an OWNER's standing job -- "Sam mows the
    lawn" must not sit on Sam's list all winter."""
    if in_season(chore, today):
        return True
    state = (chore or {}).get('state')
    if state == 'done':
        return True
    return state == 'claimed' and not (chore or {}).get('owner')


def annotate(item: dict, kind: str, today: Optional[datetime.date] = None) -> dict:
    """Adds `season_label` / `in_season` (and `offered` for a reward) so the
    Chores page can say why a row is quiet without re-deriving the rule."""
    item['season_label'] = label(item)
    item['in_season'] = in_season(item, today)
    if kind == 'reward':
        item['active'] = item.get('active', True) is not False
        item['offered'] = reward_offered(item, today)
    else:
        item['offered'] = chore_offered(item, today)
    return item
