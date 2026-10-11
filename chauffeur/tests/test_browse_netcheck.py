"""The Missions drawer's "Check the network": DNS and connect timings for the
sites a browse uses, IPv4 and IPv6 apart, in the app (no terminal). Built
2026-10-11 when every browse connect on the HA VM timed out on an 8 Gbit
link, which smells of DNS or a half-configured IPv6 inside the container."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import check  # noqa: F401,E402
from services import browse  # noqa: E402
from browse_pages import serve  # noqa: E402

SRV, PORT = serve()


def scenario_a_reachable_host_reports_its_timings():
    rows = browse.network_check([f'http://127.0.0.1:{PORT}/start'])
    check(len(rows) == 1, f"one row per url: {rows}")
    r = rows[0]
    for k in ('url', 'host', 'dns_any_ms', 'dns_v4_ms', 'connect_v4_ms', 'connect_v6_ms', 'get_ms', 'status', 'verdict'):
        check(k in r, f"row carries {k}: {r}")
    check(r['status'] == 200 and r['get_ms'] is not None and r['get_ms'] < 5000 and r['connect_v4_ms'] is not None, f"a fast local GET: {r}")
    check(r['connect_v6_ms'] is None and r['verdict'], f"no AAAA for an IPv4 literal; a verdict is always said: {r}")


def scenario_an_unreachable_host_is_an_honest_row():
    rows = browse.network_check(['https://nope.invalid/'], timeout_s=2)
    r = rows[0]
    check(r['status'] is None and r['get_ms'] is None and 'dns' in r['verdict'].lower(), f"dns failure named: {r}")


def scenario_the_verdict_reads_the_timings():
    v = browse._net_verdict({'dns_any_ms': 5200, 'dns_v4_ms': 40, 'connect_v4_ms': 30, 'connect_v6_ms': None, 'get_ms': 5400, 'status': 200})
    check('ipv6' in v.lower() or 'aaaa' in v.lower(), f"slow any-DNS with fast v4: the AAAA lookup is named: {v}")
    v = browse._net_verdict({'dns_any_ms': 30, 'dns_v4_ms': 25, 'connect_v4_ms': 40, 'connect_v6_ms': 21000, 'get_ms': 21200, 'status': 200})
    check('ipv6' in v.lower(), f"a hanging v6 connect is named: {v}")
    v = browse._net_verdict({'dns_any_ms': 4800, 'dns_v4_ms': 4700, 'connect_v4_ms': 40, 'connect_v6_ms': None, 'get_ms': 4900, 'status': 200})
    check('resolver' in v.lower() or 'dns' in v.lower(), f"slow DNS both ways: the resolver is named: {v}")
    v = browse._net_verdict({'dns_any_ms': 20, 'dns_v4_ms': 18, 'connect_v4_ms': 35, 'connect_v6_ms': 38, 'get_ms': 300, 'status': 200})
    check('fine' in v.lower() or 'ok' in v.lower(), f"all fast: fine: {v}")


def scenario_the_drawer_and_the_route_exist():
    src = open('templates/components/missions_page.html', encoding='utf-8').read()
    check('netcheck' in src and 'Check the network' in src, "the Browser section has the button")
    main_src = open('main.py', encoding='utf-8').read()
    check('/api/browse/netcheck' in main_src and '_mind_actor' in main_src.split('/api/browse/netcheck')[1][:600], "a parent-gated route")


SCENARIOS = [scenario_a_reachable_host_reports_its_timings, scenario_an_unreachable_host_is_an_honest_row,
             scenario_the_verdict_reads_the_timings, scenario_the_drawer_and_the_route_exist]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    SRV.shutdown()
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)
