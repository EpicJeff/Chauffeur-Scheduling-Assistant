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


def scenario_all_fields_present():
    _reset()
    # Create a thread with minimal data
    tid = storage.add_thread({'title': 'Minimal', 'owner_member_id': 'm1'})
    row = storage.get_thread(tid)
    # Check that all model fields are present with their defaults
    check('id' in row, "id is present")
    check('title' in row and row['title'] == 'Minimal', "title is preserved")
    check('goal' in row and row['goal'] == '', "goal has default")
    check('kind' in row and row['kind'] == 'project', "kind has default")
    check('state' in row and row['state'] == 'open', "state has default")
    check('owner_member_id' in row and row['owner_member_id'] == 'm1', "owner_member_id is preserved")
    check('contact_id' in row and row['contact_id'] is None, "contact_id has default")
    check('counterparty_name' in row and row['counterparty_name'] == '', "counterparty_name has default")
    check('counterparty_email' in row and row['counterparty_email'] == '', "counterparty_email has default")
    check('next_action' in row and row['next_action'] == '', "next_action has default")
    check('next_action_at' in row and row['next_action_at'] is None, "next_action_at has default")
    check('history' in row and row['history'] == [], "history has default")
    check('created_by' in row and row['created_by'] is None, "created_by has default")
    check('created_at' in row and isinstance(row['created_at'], float), "created_at is a float timestamp")
    check('closed_at' in row and row['closed_at'] is None, "closed_at has default")


if __name__ == '__main__':
    scenario_roundtrip_and_defaults()
    scenario_history_is_append_only()
    scenario_listing_filters()
    scenario_all_fields_present()
    print("test_threads_storage OK")
