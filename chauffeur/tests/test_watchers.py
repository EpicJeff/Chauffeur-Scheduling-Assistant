"""Tests for the proactive parent watchers (services/watchers.py).

Load-bearing properties: findings fire once and only once (persisted dedup
markers), delivery is ONE consolidated Argyle DM per parent, quiet hours defer
without consuming findings, grace periods gate the stale-state nudges, and the
master toggle silences everything.

Run from chauffeur/:  python tests/test_watchers.py
"""
import datetime
import time
from unittest import mock

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import storage, watchers

NOON = datetime.datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
LATE = NOON.replace(hour=23)


def _reset():
    for t in (storage.members_table, storage.cache_table, storage.chores_table,
              storage.redemptions_table, storage.errands_table,
              storage.event_proposals_table, storage.app_state_table,
              storage.chat_channels_table, storage.chat_messages_table,
              storage.findings_table, storage.coverage_asks_table,
              storage.agent_action_proposals_table, storage.drivers_table,
              storage.assist_contacts_table, storage.assist_assignments_table,
              storage.assist_history_table, storage.household_tasks_table):
        t.truncate()
    storage.get_settings = lambda: {"calendar_ids": ["primary"]}
    storage.add_member({"id": "mom", "name": "Mom", "role": "parent"})
    storage.add_member({"id": "dad", "name": "Dad", "role": "parent"})
    storage.add_member({"id": "kid", "name": "Addison", "role": "child", "is_child": True})


def _run(now=NOON):
    """run_watchers with the LLM prep-kit check neutralized and the DM post
    captured; returns (count, [posted bodies])."""
    posts = []
    with mock.patch.object(watchers, '_prep_kit_findings', return_value=[]), \
         mock.patch('services.agent_tools_v2._post_chat_message',
                    side_effect=lambda ch, sender, body, card=None:
                        posts.append((ch, sender, body)) or {}):
        n = watchers.run_watchers(now=now)
    return n, posts


def _bodies(posts):
    """The consolidated heads-up, without the per-finding action cards that
    follow it."""
    return [b for _, _, b in posts if b.startswith("👋")]


def scenario_unassigned_event_fires_once():
    _reset()
    soon = (NOON + datetime.timedelta(days=1)).replace(hour=16)
    storage.set_cached_schedule({
        "events": [
            {"id": "ev1", "title": "Soccer Practice", "start": soon.isoformat(),
             "end": (soon + datetime.timedelta(hours=1)).isoformat()},
            {"id": "far", "title": "Recital", "start": (NOON + datetime.timedelta(days=10)).isoformat(),
             "end": (NOON + datetime.timedelta(days=10, hours=1)).isoformat()},
            {"id": "gone", "title": "Away Game", "start": soon.isoformat(),
             "end": soon.isoformat(), "trip_suppressed": True},
        ],
        "assignments": {},
        "unassigned": ["ev1", "far", "gone"],
    })
    n, posts = _run()
    check(n == 1, f"exactly the in-window event is a finding, got {n}")
    bodies = _bodies(posts)
    check(len(bodies) == 2, f"one DM per parent (2 parents), got {len(bodies)}")
    body = bodies[0]
    check("Soccer Practice" in body, f"body names the event: {body}")
    check("Recital" not in body, "events beyond the 3-day window stay quiet")
    check("Away Game" not in body, "trip-suppressed events are not triage")
    check(posts[0][1].get("id") == "argyle", "sent as the Argyle system member")
    # second sweep: nothing new -> no post at all
    n2, posts2 = _run()
    check(n2 == 0 and _bodies(posts2) == [], "same finding never notifies twice")


def scenario_stale_grace_periods():
    _reset()
    now_ts = NOON.timestamp()
    storage.set_cached_schedule({"events": [], "assignments": {}, "unassigned": []})
    # proposals: 4 days old fires, 1 day old waits
    storage.add_proposal({"id": "p_old", "title": "Book Fair", "status": "proposed",
                          "created_at": now_ts - 4 * 86400})
    storage.add_proposal({"id": "p_new", "title": "Bake Sale", "status": "proposed",
                          "created_at": now_ts - 1 * 86400})
    # chores: done 3 days ago fires; done 1h ago waits; open 8 days unclaimed fires
    storage.add_chore({"id": "c1", "title": "Mow lawn", "state": "done",
                       "done_at": now_ts - 3 * 86400, "created_at": now_ts - 9 * 86400,
                       "points": 20, "recurrence": "once", "eligible_member_ids": []})
    storage.add_chore({"id": "c2", "title": "Dishes", "state": "done",
                       "done_at": now_ts - 3600, "created_at": now_ts - 3600,
                       "points": 5, "recurrence": "once", "eligible_member_ids": []})
    storage.add_chore({"id": "c3", "title": "Garage sweep", "state": "open",
                       "created_at": now_ts - 8 * 86400,
                       "points": 5, "recurrence": "once", "eligible_member_ids": []})
    # redemption pending 3 days fires
    with storage.db_lock:
        storage.redemptions_table.insert({"id": "r1", "member_id": "kid",
                                          "reward_title": "Movie night", "state": "pending",
                                          "requested_at": now_ts - 3 * 86400})
    # past-due errand fires
    with storage.db_lock:
        storage.errands_table.insert({"id": "er1", "title": "Return library books",
                                      "status": "past_due", "is_completed": False})
        storage.errands_table.insert({"id": "er2", "title": "Groceries",
                                      "status": "pending", "is_completed": False})
    n, posts = _run()
    body = _bodies(posts)[0]
    check("Book Fair" in body and "Bake Sale" not in body, "proposal grace period is 3 days")
    check("Mow lawn" in body and "Dishes" not in body, "verify nudge waits 48h")
    check("Movie night" in body and "Addison" in body, "stale reward request names the kid")
    check("library books" in body and "Groceries" not in body, "only past_due errands nudge")
    n2, posts2 = _run()
    check(n2 == 0 and _bodies(posts2) == [], "all stale-state findings dedup on the second sweep")


def scenario_the_noise_cuts_are_watched_but_silent():
    """The family's own report: unclaimed chores and a far-off optional skip
    are not worth a prompt. They are still WATCHED — a record exists, the
    counts are real — they simply never interrupt anybody."""
    _reset()
    now_ts = NOON.timestamp()
    soon = (NOON + datetime.timedelta(days=2)).replace(hour=16)
    storage.set_cached_schedule({
        "events": [{"id": "opt1", "title": "Art Club", "start": soon.isoformat(),
                    "end": (soon + datetime.timedelta(hours=1)).isoformat(),
                    "app_config": {"is_optional": True}}],
        "assignments": {}, "unassigned": ["opt1"],
    })
    storage.add_chore({"id": "c9", "title": "Garage sweep", "state": "open",
                       "created_at": now_ts - 8 * 86400,
                       "points": 5, "recurrence": "once", "eligible_member_ids": []})
    n, posts = _run()
    check(n == 0 and _bodies(posts) == [],
          f"neither cut finding earns an interruption, got {n}")
    kinds = {f['kind'] for f in storage.get_findings(state='open')}
    check('optional_skip' in kinds, "the skipped optional is still a record")
    check('chore_unclaimed' in kinds, "the unclaimed batch is still a record")
    lines = [f['line'] for f in storage.get_findings(state='open')]
    check(any("Art Club" in l for l in lines), f"and it still says what it is: {lines}")


def scenario_quiet_hours_defer_not_drop():
    _reset()
    soon = (NOON + datetime.timedelta(days=1)).replace(hour=9)
    storage.set_cached_schedule({
        "events": [{"id": "ev1", "title": "Dentist", "start": soon.isoformat(),
                    "end": (soon + datetime.timedelta(hours=1)).isoformat()}],
        "assignments": {}, "unassigned": ["ev1"],
    })
    n, posts = _run(now=LATE)
    check(n == 0 and _bodies(posts) == [], "23:00 sweep posts nothing")
    check(len(storage.get_findings(state='open')) == 1,
          "records are still reconciled inside quiet hours — silence is about "
          "speaking, not about knowing")
    n2, posts2 = _run(now=NOON)
    check(n2 == 1 and len(_bodies(posts2)) == 2,
          "the finding survives to the morning sweep")


def scenario_master_toggle():
    _reset()
    storage.get_settings = lambda: {"calendar_ids": ["primary"],
                                    "proactive_watchers_enabled": False}
    soon = (NOON + datetime.timedelta(days=1)).replace(hour=9)
    storage.set_cached_schedule({
        "events": [{"id": "ev1", "title": "Dentist", "start": soon.isoformat(),
                    "end": (soon + datetime.timedelta(hours=1)).isoformat()}],
        "assignments": {}, "unassigned": ["ev1"],
    })
    n, posts = _run()
    check(n == 0 and _bodies(posts) == [], "toggle off silences the sweep entirely")
    check(storage.get_findings() == [], "and writes no records either")


def scenario_prep_kit_weekly_fingerprint():
    _reset()
    storage.set_cached_schedule({
        "events": [{"id": "e1", "title": "Swim Practice", "start": NOON.isoformat(),
                    "end": NOON.isoformat()}],
        "assignments": {}, "unassigned": [],
    })
    fake_kits = [{"name": "Swim Kit", "keywords": ["swim"], "items": ["Goggles"]}]
    with mock.patch('services.prep_kits.suggest_kits', return_value=fake_kits) as sk:
        f1 = watchers._prep_kit_findings(NOON.timestamp())
        check(len(f1) == 1 and "Swim Kit" in f1[0][1], "fresh suggestion becomes a finding")
        check(sk.call_args.kwargs.get('tier') == 'background', "watcher uses the background tier")
        f2 = watchers._prep_kit_findings(NOON.timestamp() + 60)
        check(f2 == [], "interval gate: no second LLM call inside a week")
        f3 = watchers._prep_kit_findings(NOON.timestamp() + 8 * 86400)
        check(f3 == [], "already-announced kit names are fingerprinted, not repeated")


def scenario_absence_is_resolution():
    """The lifecycle claim that makes the whole surface work: a finding whose
    condition stops appearing has been handled SOMEWHERE — on the chores page,
    by the other parent — and closes itself without anybody dismissing it."""
    _reset()
    now_ts = NOON.timestamp()
    storage.set_cached_schedule({"events": [], "assignments": {}, "unassigned": []})
    storage.add_chore({"id": "c1", "title": "Mow lawn", "state": "done",
                       "done_at": now_ts - 3 * 86400, "created_at": now_ts - 9 * 86400,
                       "points": 20, "recurrence": "once", "eligible_member_ids": []})
    _run()
    rows = storage.get_findings(state='open')
    check(len(rows) == 1 and rows[0]['kind'] == 'chore_verify',
          f"the verify nudge opened a record, got {rows}")

    # A parent verifies it on the chores page. Nobody tells the watcher.
    storage.update_chore("c1", {"state": "verified"})
    _run()
    check(storage.get_findings(state='open') == [], "the record closed itself")
    done = storage.get_findings(state='done')
    check(len(done) == 1 and done[0].get('resolved_by') == 'auto',
          f"and knows nobody tapped anything, got {done}")


def scenario_dismissed_stays_dismissed_until_the_subject_changes():
    """Dismissed is dismissed. The sentence changing (a count, a countdown, a
    severity bump) never reopens it; only the subject itself changing does."""
    _reset()
    from services import findings as _f
    now_ts = NOON.timestamp()
    storage.set_cached_schedule({"events": [], "assignments": {}, "unassigned": []})
    storage.add_chore({"id": "c1", "title": "Mow lawn", "state": "done",
                       "done_at": now_ts - 3 * 86400, "created_at": now_ts - 9 * 86400,
                       "points": 20, "recurrence": "once", "eligible_member_ids": []})
    _run()
    fid = storage.get_findings(state='open')[0]['id']
    _f.resolve(fid, 'dismiss', member_id='mom')
    _run()
    check(storage.get_findings(state='open') == [],
          "a settled answer is not asked again")

    # Two more days pass: the line now says a different number of days. Words
    # changed, the chore did not — it stays dismissed.
    later = NOON + datetime.timedelta(days=2)
    _run(now=later)
    check(storage.get_findings(state='open') == [],
          "a changed count is still the same dismissed finding")

    # The chore is done AGAIN (a fresh completion waiting for an OK): that is
    # a new situation and may open.
    storage.chores_table.update({'done_at': later.timestamp() - 3 * 86400},
                                storage.Query().id == 'c1')
    _run(now=later)
    check(len(storage.get_findings(state='open')) == 1,
          "a new completion is a new finding")


def scenario_dismissed_ride_ignores_countdown_and_escalation():
    _reset()
    from services import findings as _f
    start = (NOON + datetime.timedelta(days=2)).replace(hour=16)
    def sched(when):
        storage.set_cached_schedule({
            "events": [{"id": "ev1", "title": "Soccer", "start": when.isoformat(),
                        "end": (when + datetime.timedelta(hours=1)).isoformat()}],
            "assignments": {}, "unassigned": ["ev1"]})
    sched(start)
    _run()
    rows = storage.get_findings(state='open')
    check(len(rows) == 1 and rows[0]['kind'] == 'unassigned', "the ride is a finding")
    _f.resolve(rows[0]['id'], 'dismiss', member_id='dad')
    for hours in (24, 40, 46):
        _run(now=NOON + datetime.timedelta(hours=hours))
    check(storage.get_findings(state='open') == [],
          "the countdown and the time-critical escalation never bring it back")
    sched(start + datetime.timedelta(hours=2))
    _run(now=NOON + datetime.timedelta(hours=46))
    check(len(storage.get_findings(state='open')) == 1,
          "the ride MOVING is a new situation")


def scenario_task_due_date_edit_reopens():
    _reset()
    from services import findings as _f
    from models.schemas import HouseholdTask
    storage.set_cached_schedule({"events": [], "assignments": {}, "unassigned": []})
    tomorrow = (NOON + datetime.timedelta(days=1)).date().isoformat()
    row = HouseholdTask(title="Sign the slip", due_date=tomorrow).model_dump()
    storage.add_household_task(row)
    _run()
    fid = storage.get_findings(state='open')[0]['id']
    _f.resolve(fid, 'dismiss', member_id='mom')
    _run()
    check(storage.get_findings(state='open') == [], "dismissed unclaimed task stays quiet")
    later = (NOON + datetime.timedelta(days=2)).date().isoformat()
    storage.update_household_task(row['id'], {'due_date': later})
    _run()
    check(len(storage.get_findings(state='open')) == 1,
          "a moved due date is a new situation")


def scenario_legacy_dismissal_adopts_its_fingerprint_silently():
    """Rows dismissed before fingerprints existed take theirs on first sight
    without reopening — the migration itself never nags."""
    _reset()
    now_ts = NOON.timestamp()
    storage.set_cached_schedule({"events": [], "assignments": {}, "unassigned": []})
    storage.add_chore({"id": "c1", "title": "Mow lawn", "state": "done",
                       "done_at": now_ts - 3 * 86400, "created_at": now_ts - 9 * 86400,
                       "points": 20, "recurrence": "once", "eligible_member_ids": []})
    storage.add_finding({'identity': 'chore_verify:c1', 'kind': 'chore_verify',
                         'severity': 'approve', 'line': 'an older sentence',
                         'state': 'dismissed', 'resolved_by': 'dismiss'})
    _run()
    check(storage.get_findings(state='open') == [], "no reopen from the migration")
    row = storage.get_finding_by_identity('chore_verify:c1')
    check(row.get('fingerprint'), "the dismissed row now carries a fingerprint")


def scenario_dismissed_record_silences_a_dated_notify_key():
    """Some kinds carry the day in their notify key (one nudge a day while a
    gap stands). Once the record is dismissed, the daily key must not keep
    earning a DM — the dismissal covers the subject, not one day's sentence."""
    _reset()
    from services import findings as _f
    storage.set_cached_schedule({"events": [], "assignments": {}, "unassigned": []})
    def daily(day):
        return [_f.Finding(key=f"occasion_gap:o1:{day}",
                           line="🎉 Party is soon — still to sort: cake",
                           kind='occasion_gap', severity='decide',
                           subject_type='occasion', subject_id='o1',
                           due_at=NOON.timestamp() + 5 * 86400, fp='o1|cake')]
    with mock.patch.object(watchers, 'collect_findings',
                           side_effect=lambda now: (daily(now.date()), [])):
        n, posts = _run()
        check(n == 1 and _bodies(posts), "day one: the gap is announced")
        fid = storage.get_findings(state='open')[0]['id']
        _f.resolve(fid, 'dismiss', member_id='mom')
        n2, posts2 = _run(now=NOON + datetime.timedelta(days=1))
    check(n2 == 0 and _bodies(posts2) == [],
          "day two: a new dated key, same dismissed subject — no DM")


def scenario_undo_puts_it_back():
    _reset()
    from services import findings as _f
    fid = storage.add_finding({'identity': 'chore_verify:c1', 'kind': 'chore_verify',
                               'severity': 'approve', 'line': 'x', 'state': 'open'})
    _f.resolve(fid, 'tap', member_id='mom')
    check(storage.get_finding(fid)['state'] == 'done', "tap resolves it")
    _f.resolve(fid, 'undo')
    check(storage.get_finding(fid)['state'] == 'open',
          "undo is first-class — a lock-screen mis-tap must be takeable back")


SCENARIOS = [
    scenario_unassigned_event_fires_once,
    scenario_stale_grace_periods,
    scenario_the_noise_cuts_are_watched_but_silent,
    scenario_quiet_hours_defer_not_drop,
    scenario_master_toggle,
    scenario_prep_kit_weekly_fingerprint,
    scenario_absence_is_resolution,
    scenario_dismissed_stays_dismissed_until_the_subject_changes,
    scenario_dismissed_ride_ignores_countdown_and_escalation,
    scenario_task_due_date_edit_reopens,
    scenario_legacy_dismissal_adopts_its_fingerprint_silently,
    scenario_dismissed_record_silences_a_dated_notify_key,
    scenario_undo_puts_it_back,
]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    raise SystemExit(1 if failed else 0)
