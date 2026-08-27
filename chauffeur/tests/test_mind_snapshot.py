"""Snapshot boundaries: family channel in, DMs structurally absent, gifts
structurally absent; hash ignores clock noise; sensitivity gate is server-side."""
import datetime, time, inspect
from harness import check
from models.schemas import ChatMessage
from services import storage, mind


def _seed_chat():
    # Family channel + one DM. The snapshot must carry the first, never the
    # second. Messages go through the REAL ChatMessage schema + storage path
    # so the field names (body / sender_member_id) are pinned against the
    # schema — a mind.py reading 'text'/'member_id' must fail here.
    fam = storage.get_family_channel()
    if not fam:
        storage.chat_channels_table.insert({'id': 'fam1', 'kind': 'family',
                                            'member_ids': [], 'dm_key': None,
                                            'title': '', 'created_at': time.time(),
                                            'archived': False})
        fam = storage.get_family_channel()
    storage.add_chat_message(ChatMessage(
        channel_id=fam['id'], sender_member_id='mom',
        body='we are out of sunscreen').model_dump())
    dm = storage.get_or_create_dm('mom', 'dad')
    storage.add_chat_message(ChatMessage(
        channel_id=dm['id'], sender_member_id='mom',
        body='SECRET-DM-LINE').model_dump())


def scenario_family_channel_in_dms_out():
    _seed_chat()
    text = mind.snapshot(datetime.datetime.now())
    check('sunscreen' in text, "family-channel talk reaches the snapshot")
    check('SECRET-DM-LINE' not in text, "DM content never reaches the snapshot")


def scenario_dms_and_gifts_structurally_absent():
    src = inspect.getsource(mind)
    check('get_or_create_dm' not in src and 'dm_key' not in src,
          "mind.py never touches DM channel APIs — exclusion is structural")
    check('gift' not in src.lower() and 'present_' not in src.lower(),
          "mind.py never touches gift records — exclusion is structural")


def scenario_hash_stability():
    now = datetime.datetime.now()
    a = mind.snapshot_hash(mind.snapshot(now))
    b = mind.snapshot_hash(mind.snapshot(now + datetime.timedelta(seconds=90)))
    check(a == b, "90 seconds of clock drift alone does not change the hash")


def scenario_visibility_gate():
    storage.mind_insights_table.truncate()
    storage.add_mind_insight({'slug': 's1', 'line': 'normal one', 'category': 'c',
                              'sensitivity': 'normal'})
    storage.add_mind_insight({'slug': 's2', 'line': 'kid stress', 'category': 'c',
                              'sensitivity': 'sensitive'})
    check(len(mind.visible_insights(None)) == 1,
          "no viewer identity (wall panel) sees only normal")
    check(len(mind.visible_insights({'id': 'k1', 'role': 'child'})) == 1,
          "a child sees only normal")
    check(len(mind.visible_insights({'id': 'p1', 'role': 'parent'})) == 2,
          "a parent sees the full lane")


def scenario_ghost_coverage_reads_as_covered():
    # An outside hand covering a ride (ghost_assignments, family_digest.py:64)
    # must never render as unassigned.
    orig = storage.get_cached_schedule
    try:
        start = (datetime.datetime.now() + datetime.timedelta(days=1)) \
            .strftime('%Y-%m-%dT10:00:00')
        storage.get_cached_schedule = lambda: {
            'events': [{'id': 'g1', 'title': 'Karate', 'start': start,
                        'end': start}],
            'assignments': {}, 'ghost_assignments': {'g1': 'ghost_grandma'}}
        text = mind.snapshot(datetime.datetime.now())
        karate = [l for l in text.splitlines() if 'Karate' in l]
        check(karate and 'covered (outside hand)' in karate[0],
              f"ghost-covered event reads as covered, got {karate}")
        check('unassigned' not in (karate[0] if karate else ''),
              "a covered ride never reads as unassigned")
    finally:
        storage.get_cached_schedule = orig


def scenario_wake_window():
    s = {'mind_wake_start': '06:00', 'mind_wake_end': '22:00'}
    check(mind.in_wake_window(datetime.datetime(2026, 8, 27, 12, 0), s), "noon is awake")
    check(not mind.in_wake_window(datetime.datetime(2026, 8, 27, 3, 0), s), "3am sleeps")


if __name__ == '__main__':
    scenario_family_channel_in_dms_out()
    scenario_dms_and_gifts_structurally_absent()
    scenario_hash_stability()
    scenario_visibility_gate()
    scenario_ghost_coverage_reads_as_covered()
    scenario_wake_window()
    print("test_mind_snapshot OK")
