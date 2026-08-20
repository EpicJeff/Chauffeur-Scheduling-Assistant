"""Drive context on messages (family-network arc S12, §6A).

The rule the household stated: *the container is the durable thing; the
transient thing is a label on messages.* A drive is never a channel — the
helper↔parent DM persists, the drive lasts forty minutes — so the drive
rides each message as `context` and the thread draws a "re: …" chip over
that run. The moment-gate property survives untouched: a DM is not an event
channel, so a drive conversation can never produce family memory.

Run from chauffeur/:  python tests/test_drive_context.py
"""
from harness import check  # noqa: F401  (isolates CHAUFFEUR_DATA_DIR)

from services import drive_sheet, storage


def _seed():
    storage.members_table.truncate()
    storage.chat_channels_table.truncate()
    storage.chat_messages_table.truncate()
    storage.add_member({"id": "mom", "name": "Mom", "role": "parent"})
    storage.add_member({"id": "nan", "name": "Nanny", "role": "helper",
                        "driver_id": "d_nan"})
    storage.set_cached_schedule({
        'events': [{'id': 'ev1', 'title': "Emma's game",
                    'start': '2026-08-21T16:00:00',
                    'end': '2026-08-21T17:30:00'}],
        'assignments': {'ev1': 'd_nan'}, 'matched_rules': {}})


def scenario_a_canned_line_arrives_labelled():
    _seed()
    mom = storage.get_member('mom')
    real = drive_sheet._message_audience
    drive_sheet._message_audience = lambda leg_id, sched: [mom]
    try:
        out = drive_sheet.send_quick_message(
            'init_ev1', drive_sheet.MESSAGES[0]['key'], storage.get_member('nan'))
    finally:
        drive_sheet._message_audience = real
    check(out.get('status') == 'ok', f"the send worked: {out}")
    dm = storage.get_or_create_dm('nan', 'mom')
    msgs = storage.get_channel_messages(dm['id'])
    ctx = msgs[-1].get('context')
    check(ctx and ctx['kind'] == 'drive' and ctx['leg_id'] == 'init_ev1',
          f"the message carries its drive as context: {ctx}")
    check("Emma's game" in (ctx.get('label') or '') and '4:00' in ctx['label'],
          f"…with the chip's label denormalised at send time: {ctx.get('label')}")
    check(dm.get('kind') == 'dm',
          "and the container is the DM — a drive is never a channel, so a "
          "drive conversation can never produce family memory")


def scenario_client_context_is_whitelisted_never_stored_verbatim():
    import main
    from fastapi import BackgroundTasks

    class Req:
        def __init__(self, token=None):
            self.headers = {'x-member-token': token} if token else {}
            self.query_params = {}

    _seed()
    tok = storage.create_member_token('mom')
    dm = storage.get_or_create_dm('nan', 'mom')
    msg = main.send_message(dm['id'], main.SendMessageRequest(
        sender_member_id='mom', body='On my way',
        context={'kind': 'drive', 'event_id': 'ev1', 'leg_id': 'init_ev1',
                 'label': 'Emma\'s game · 4:00', 'evil': '<script>'}),
        BackgroundTasks(), request=Req(tok))
    ctx = msg.get('context')
    check(ctx == {'kind': 'drive', 'event_id': 'ev1', 'leg_id': 'init_ev1',
                  'label': "Emma's game · 4:00"},
          f"known keys survive, invented ones do not: {ctx}")
    msg2 = main.send_message(dm['id'], main.SendMessageRequest(
        sender_member_id='mom', body='hi', context={'kind': 'surveillance'}),
        BackgroundTasks(), request=Req(tok))
    check(msg2.get('context') is None,
          "a kind this arc never defined is dropped, not stored")


SCENARIOS = [
    scenario_a_canned_line_arrives_labelled,
    scenario_client_context_is_whitelisted_never_stored_verbatim,
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
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)
