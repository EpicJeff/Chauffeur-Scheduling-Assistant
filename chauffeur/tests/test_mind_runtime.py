"""One real cycle: chat message -> sentinel notices -> think curates ->
tile shows it (no sensitive) -> dismiss lands the outcome. Fake LLM only.

This is the one test that RUNS the whole wire end to end (source-reading
tests miss runtime breaks). Adjustment from the brief: the family channel
is not guaranteed to exist yet in a fresh test DB, so it is seeded the same
way tests/test_mind_snapshot.py and tests/test_mind_sentinel.py do — calling
storage.get_family_channel() on an empty DB returns None and 'fam['id']'
would crash before the scenario even starts."""
import datetime, time
from harness import check
from models.schemas import ChatMessage
from services import storage, mind, home_board


def _ensure_family_channel():
    fam = storage.get_family_channel()
    if not fam:
        storage.chat_channels_table.insert({'id': 'fam1', 'kind': 'family',
                                            'member_ids': [], 'dm_key': None,
                                            'title': '', 'created_at': time.time(),
                                            'archived': False})
        fam = storage.get_family_channel()
    return fam


def scenario_full_cycle():
    storage.mind_insights_table.truncate()
    storage.mind_noticings_table.truncate()
    for k in ('mind_chat_watermark', 'mind_event_state', 'mind_finding_keys',
              'mind_shop_hash', 'mind_last_snapshot_hash', 'mind_sentinel_last',
              'mind_last_think_ts', 'mind_think_attempt_ts'):
        storage.set_app_state(k, None)
    storage.get_settings = lambda: {'mind_enabled': True,
                                    'llm_gemini_api_key': 'k',
                                    'mind_wake_start': '00:00',
                                    'mind_wake_end': '00:00'}
    fam = _ensure_family_channel()
    # Real ChatMessage schema + storage path: field names (body /
    # sender_member_id) stay pinned against models/schemas.py.
    storage.add_chat_message(ChatMessage(
        channel_id=fam['id'], sender_member_id='mom',
        body='we are out of sunscreen again').model_dump())

    def fake_pool(tier, api_key, system, prompt, **kw):
        if tier == 'background':
            return {'noticings': [{'line': 'sunscreen is out', 'source': 'chat',
                                   'urgency': 'low'}]}
        if tier == 'heavy':
            check('sunscreen is out' in prompt,
                  "the noticing reached the deep think prompt")
            return {'insights': [
                {'slug': 'sunscreen', 'line': 'Sunscreen keeps running out',
                 'category': 'supply-gap', 'sensitivity': 'normal',
                 'domain': 'supply', 'confidence': 0.9},
                {'slug': 'quiet-kid', 'line': 'Rough week for a kid',
                 'category': 'overload', 'sensitivity': 'sensitive',
                 'domain': 'kids', 'confidence': 0.6}]}
        raise AssertionError(f"unexpected tier {tier}")

    mind._pool_call = fake_pool
    res = mind.tick(datetime.datetime.now())
    check(res.get('think', {}).get('status') == 'thought', f"cycle ran: {res}")

    tile = home_board._tile_mind(datetime.datetime.now())
    lines = [i['line'] for i in tile['insights']]
    check('Sunscreen keeps running out' in lines, "insight reaches the board tile")
    check('Rough week for a kid' not in lines, "sensitive never reaches a board")

    # Hand path: the tile/PWA action works without chat.
    row = storage.get_mind_insight_by_slug('sunscreen')
    storage.update_mind_insight(row['id'], {'state': 'retired',
                                            'outcome': 'dismissed',
                                            'resolved_ts': time.time()})
    check(mind.category_counters()['supply-gap']['dismissed'] == 1,
          "the dismissal lands in the graduation counters")


if __name__ == '__main__':
    scenario_full_cycle()
    print("test_mind_runtime OK")
