"""Standalone probe: why is there no arrival chip?

Same idea as `walmart_check.py` — the question "nothing is showing" has
several very different answers that look identical from the UI, and guessing
between them is worse than asking:

  1. There are no buffer rules and no descriptions to parse — nothing to show.
  2. Rules exist but match no upcoming event — the rule is the problem.
  3. Everything derives correctly but the CACHE is stale, so the screens are
     drawing a solve that predates the feature. Fixed by a re-solve, not by
     code.
  4. The derivation itself is broken.

Run from chauffeur/:  python arrive_by_check.py
"""
import datetime
import sys

from services import storage
from services import arrive_by


def main():
    settings = storage.get_settings() or {}
    print(f"time format: {'24h' if settings.get('time_format_24h') else '12h'}\n")

    # --- 1. the rules
    from models.schemas import Rule
    rules, buffers = [], []
    for r in storage.get_all_rules():
        try:
            rule = Rule(**r)
        except Exception as e:
            print(f"  ! unparseable rule skipped: {e}")
            continue
        rules.append(rule)
        if rule.constraint_type == 'buffer':
            buffers.append(rule)
    print(f"BUFFER RULES: {len(buffers)} of {len(rules)} rules")
    for b in buffers:
        state = 'on' if b.is_enabled else 'OFF'
        print(f"  [{state}] before={b.buffer_before_mins}m after={b.buffer_after_mins}m"
              f" reason={b.buffer_reason or '(none)'}"
              f" keywords={b.keywords or '-'} passengers={b.passenger_ids or '-'}"
              f" days={b.days_of_week or '-'} location={b.location or '-'}")
    if not buffers:
        print("  (none — nothing can come from a rule)")

    # --- 2. the cache, as the screens see it
    cache = storage.get_cached_schedule() or {}
    events = cache.get('events') or []
    print(f"\nCACHED EVENTS: {len(events)}")
    if not events:
        print("  (empty — solve the schedule first)")
        return 0
    stamped = [e for e in events if e.get('arrive_by')]
    print(f"  carrying arrive_by ALREADY: {len(stamped)}")
    if not stamped:
        print("  -> the cache predates the feature. Re-solve (force refresh);")
        print("     no amount of screen-poking will add it to a stale solve.")

    # --- 3. what SHOULD derive right now, cache or no cache
    now = datetime.datetime.now()
    upcoming = []
    for e in events:
        try:
            start = datetime.datetime.fromisoformat(str(e.get('start')))
        except (TypeError, ValueError):
            continue
        if start >= now - datetime.timedelta(hours=12):
            upcoming.append((start, e))
    upcoming.sort(key=lambda t: t[0])

    print(f"\nDERIVING over the next {len(upcoming)} events:")
    hits = 0
    for start, e in upcoming[:40]:
        got = arrive_by.derive(e, rules, None)
        trail = arrive_by.depart_after(e, rules, None)
        title = (e.get('title') or '?')[:44]
        when = start.strftime('%a %d %b %H:%M')
        if got or trail:
            hits += 1
            bits = []
            if got:
                bits.append(f"{got['label']}  [{got['source']}]")
            if trail:
                bits.append(trail['label'])
            print(f"  ✓ {when}  {title}")
            for b in bits:
                print(f"      {b}")
        else:
            why = []
            if e.get('all_day'):
                why.append('all-day')
            if not (e.get('location') or '').strip():
                why.append('no location')
            if not arrive_by._buffer_rules(e, rules, None):
                why.append('no buffer rule matches')
            if not arrive_by.from_description(e.get('description'), start):
                why.append('nothing parseable in the description')
            print(f"  · {when}  {title}  ({', '.join(why) or 'no reason found'})")
    print(f"\n{hits} of {len(upcoming[:40])} would show a chip.")

    # --- 4. the description parser, against this family's own text
    with_desc = [e for _, e in upcoming if (e.get('description') or '').strip()]
    print(f"\nEVENTS WITH A DESCRIPTION: {len(with_desc)}")
    for e in with_desc[:10]:
        head = ' '.join((e.get('description') or '').split())[:70]
        try:
            start = datetime.datetime.fromisoformat(str(e.get('start')))
        except (TypeError, ValueError):
            continue
        got = arrive_by.from_description(e.get('description'), start)
        mark = f"-> {got['lead_mins']}m" if got else "-> nothing"
        print(f"  {mark:14} {(e.get('title') or '?')[:28]:30} {head}")
    if not with_desc:
        print("  (none — ICS feeds carry descriptions; hand-typed events often do not)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
