"""Guided checks keep skipped pauses waiting, with stable check identities.

Run from chauffeur/: python tests/test_twin_build_checks.py (no model calls).
"""
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_twin_build as T


def scenario_skip_keeps_the_pause_and_paid_result():
    T._fresh()
    _, _, photo = T._sources()
    reader = T.Reader()
    bid = T.tb.start(T._inputs(photo), reader=reader, inline=True)
    before = copy.deepcopy(T.tb.status(bid))
    calls = copy.deepcopy(reader.calls)
    rounds = copy.deepcopy(T.ts.rounds())
    after = T.tb.answer(bid, before['pause']['step'], {'skip': True})
    T.check(after == before, 'Skip changes no build state, check id, event or cost.')
    T.check(reader.calls == calls and T.ts.rounds() == rounds, 'Skip does not read or settle anything.')
    T.check(after['pause']['id'], 'Every new pause carries a check id.')
    T.tb.answer(bid, before['pause']['step'], {'accept': True})
    T.check(T.tb.status(bid)['pause'] != before['pause'], 'The same check remains answerable after Skip.')


def scenario_reread_creates_a_new_check_id():
    T._fresh()
    _, _, photo = T._sources()
    reader = T.Reader()
    bid = T.tb.start(T._inputs(photo), reader=reader, inline=True)
    before = copy.deepcopy(T.tb.status(bid))
    T.tb.reread(bid, before['pause']['step'], reader=reader, inline=True)
    after = T.tb.status(bid)
    T.check(after['state'] == 'paused', after)
    T.check(after['pause']['id'] != before['pause']['id'], 'A reread is a new check, even at the same step.')


def scenario_empty_house_can_start_with_a_floor_and_two_corners():
    T._fresh()
    part = T.ts.add_building('My house', 'main_house')
    T.ts.save_hand_edit({'schema': 'chauffeur.twin.plan/2', 'units': 'ft', 'site': {}, 'materials': {},
                        'buildings': [{'id': part['id'], 'name': part['name'], 'position': [0, 0],
                                       'levels': [{'id': 'L1', 'name': 'Main floor', 'elevation': 0, 'ceiling': 9}],
                                       'walls': [], 'openings': [], 'rooms': [], 'roof': {'sections': []}}]},
                       'Start drawing my house.')
    from services import twin_model_ops
    model, words = twin_model_ops.apply(T.ts.current_model(), {'op': 'add_wall', 'building': part['id'],
                                                        'level': 'L1', 'from': [0, 0], 'to': [20, 0]})
    T.check(len(model['buildings'][0]['walls']) == 1, 'Two corners create the first wall.')


if __name__ == '__main__':
    for fn in (scenario_skip_keeps_the_pause_and_paid_result, scenario_reread_creates_a_new_check_id,
               scenario_empty_house_can_start_with_a_floor_and_two_corners):
        fn()
        print('  ok ', fn.__name__)
    print('3/3 passed')
