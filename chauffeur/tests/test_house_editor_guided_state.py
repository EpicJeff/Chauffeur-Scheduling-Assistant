"""Exercise the guided cost payload through the real authenticated route."""
import test_twin_build_stream as s
import test_house_editor_routes as routes


def test_cost_payload_tracks_household_ledger_and_running_estimate():
    bid = s._pool_house()
    parent, _, _ = routes._people()
    c = routes._client()
    with routes._enforced():
        empty = c.get('/api/house/editor/state', headers=parent)
        s.check(empty.status_code == 200 and empty.json()['cost']['estimate'] is None, empty.text)
        reader = s.StreamReader(gate_at=('draft', s.after_wall(3, half=True)))
        b = s.tb.start({'part': bid}, reader=reader, inline=False)
        try:
            s.check(reader.at_gate.wait(10), 'read is streaming')
            live = c.get('/api/house/editor/state', headers=parent).json()
            s.check(live['cost']['estimate'] > 0, live['cost'])
            s.check(live['cost']['total'] == s.tc.total(), 'household ledger owns spend')
            s.tb.stop(b)
            s._stopped_with(b)
            stopped = c.get('/api/house/editor/state', headers=parent).json()
            # Final review M6: a stopped build carries what Continue would cost (it was None before).
            s.check((stopped['cost']['estimate'] or 0) > 0 and stopped['cost']['total'] == s.tc.total(), stopped['cost'])
        finally:
            s._release(reader)


if __name__ == '__main__':
    test_cost_payload_tracks_household_ledger_and_running_estimate()
    print('1/1 passed')
