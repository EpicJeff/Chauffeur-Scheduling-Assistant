"""Snapshot boundaries: family channel in, DMs structurally absent, gifts
structurally absent; hash ignores clock noise; sensitivity gate is server-side."""
import datetime, time, inspect
from harness import check
from services import storage, mind


def _seed_chat():
    # Family channel + one DM. The snapshot must carry the first, never the second.
    fam = storage.get_family_channel()
    if not fam:
        storage.chat_channels_table.insert({'id': 'fam1', 'kind': 'family',
                                            'member_ids': [], 'dm_key': None,
                                            'title': '', 'created_at': time.time(),
                                            'archived': False})
        fam = storage.get_family_channel()
    storage.chat_messages_table.insert({'id': 'm1', 'channel_id': fam['id'],
                                        'member_id': 'mom', 'ts': time.time(),
                                        'text': 'we are out of sunscreen'})
    dm = storage.get_or_create_dm('mom', 'dad')
    storage.chat_messages_table.insert({'id': 'm2', 'channel_id': dm['id'],
                                        'member_id': 'mom', 'ts': time.time(),
                                        'text': 'SECRET-DM-LINE'})


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


def scenario_wake_window():
    s = {'mind_wake_start': '06:00', 'mind_wake_end': '22:00'}
    check(mind.in_wake_window(datetime.datetime(2026, 8, 27, 12, 0), s), "noon is awake")
    check(not mind.in_wake_window(datetime.datetime(2026, 8, 27, 3, 0), s), "3am sleeps")


if __name__ == '__main__':
    scenario_family_channel_in_dms_out()
    scenario_dms_and_gifts_structurally_absent()
    scenario_hash_stability()
    scenario_visibility_gate()
    scenario_wake_window()
    print("test_mind_snapshot OK")
