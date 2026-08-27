"""Threads: an open loop with someone outside the family."""
import time
from harness import check
from services import storage


def _reset():
    storage.threads_table.truncate()


def scenario_roundtrip_and_defaults():
    _reset()
    tid = storage.add_thread({'title': 'Pool service', 'kind': 'vendor',
                              'owner_member_id': 'm1'})
    row = storage.get_thread(tid)
    check(row['state'] == 'open', "a new thread is open")
    check(row['history'] == [], "and carries an empty history")
    check(row['kind'] == 'vendor', f"got {row}")


def scenario_history_is_append_only():
    _reset()
    tid = storage.add_thread({'title': 'Gutters', 'owner_member_id': 'm1'})
    storage.append_thread_history(tid, {'who': 'm1', 'text': 'called, no answer'})
    storage.append_thread_history(tid, {'who': 'argyle', 'text': 'drafted a follow-up'})
    hist = storage.get_thread(tid)['history']
    check(len(hist) == 2 and hist[0]['text'] == 'called, no answer',
          f"entries keep their order, got {hist}")
    check(hist[0].get('ts'), "and are stamped")


def scenario_listing_filters():
    _reset()
    a = storage.add_thread({'title': 'A', 'owner_member_id': 'm1'})
    b = storage.add_thread({'title': 'B', 'owner_member_id': 'm2'})
    storage.update_thread(b, {'state': 'done'})
    check(len(storage.get_threads()) == 1, "closed threads are out of the way")
    check(len(storage.get_threads(include_closed=True)) == 2, "but not gone")
    check(storage.get_threads(owner='m1')[0]['id'] == a, "filter by who carries it")


if __name__ == '__main__':
    scenario_roundtrip_and_defaults()
    scenario_history_is_append_only()
    scenario_listing_filters()
    print("test_threads_storage OK")
