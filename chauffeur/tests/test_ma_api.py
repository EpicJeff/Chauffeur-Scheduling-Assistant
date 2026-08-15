"""Tests for services/ma_api.py (Music Assistant's own API), HTTP mocked.

Run from chauffeur/:  python tests/test_ma_api.py
"""
import atexit
import os
import shutil
import sys
import tempfile
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="chauffeur_ma_api_test_")
os.environ["CHAUFFEUR_DATA_DIR"] = _TMP
atexit.register(lambda: shutil.rmtree(_TMP, ignore_errors=True))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import ma_api, storage  # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def set_settings(doc):
    with storage.db_lock:
        storage.settings_table.truncate()
        if doc:
            storage.settings_table.insert(doc)


def reset():
    for var in ("HA_BASE_URL", "HA_TOKEN", "SUPERVISOR_TOKEN"):
        os.environ.pop(var, None)
    set_settings(None)
    ma_api.reset()


def ok_response(payload, status=200):
    resp = mock.Mock()
    resp.status_code = status
    resp.text = "x"
    resp.json.return_value = payload
    return resp


def scenario_no_token_means_no_requests():
    """The whole module is optional. Without a token it must not even probe —
    a house that never heard of the MA API pays nothing for its existence."""
    reset()
    with mock.patch.object(ma_api.requests, 'get') as get, \
            mock.patch.object(ma_api.requests, 'post') as post:
        check(ma_api.command('players/all') is None, "command -> None sans token")
        check(ma_api.available() is False, "available -> False sans token")
        check(get.call_count == 0 and post.call_count == 0,
              "no HTTP at all without a token")
    h = ma_api.health()
    check(h['configured'] is False and h['ok'] is False, "health says unconfigured")
    check('token' in h['detail'].lower(), f"detail explains the token: {h['detail']}")


def scenario_host_setting_is_reused_whatever_its_shape():
    """`ma_server_url` predates this module and was written for the Sendspin
    relay, so it arrives as ws:// with port 8927 as often as not. Only the
    hostname may survive — the API is always on 8095."""
    reset()
    for raw, want in (("ws://192.168.1.50:8927", "192.168.1.50"),
                      ("http://ma.local:8095/", "ma.local"),
                      ("wss://ma.example:9999/sendspin", "ma.example"),
                      ("192.168.1.50", "192.168.1.50"),
                      ("", "")):
        set_settings({"ma_server_url": raw} if raw else None)
        got = ma_api.configured_host()
        check(got == want, f"{raw!r} -> {got!r}, wanted {want!r}")


def scenario_fallbacks_shared_with_the_relay():
    """One list of plausible MA locations, used by the audio relay and the
    API alike. The supervisor host is HA's own proxy and must never appear."""
    reset()
    set_settings({"ha_base_url": "http://192.168.1.7:8123"})
    hosts = ma_api.fallback_hosts()
    check(hosts[0] == ma_api.ADDON_HOST, "official add-on hostname first")
    check("192.168.1.7" in hosts, "HA host derives a candidate")
    check("homeassistant.local" in hosts, "mDNS name last-resort present")

    os.environ["HA_BASE_URL"] = "http://supervisor/core"
    try:
        check("supervisor" not in ma_api.fallback_hosts(),
              "supervisor is HA's proxy, never an MA candidate")
    finally:
        os.environ.pop("HA_BASE_URL", None)

    import main
    ws = main._ma_ws_candidates()
    check(f'ws://{ma_api.ADDON_HOST}:8927/sendspin' in ws,
          "the relay rides the same fallback list")


def scenario_configured_host_probed_first():
    reset()
    set_settings({"ma_server_url": "ws://192.168.1.50:8927", "ma_token": "t"})
    probed = []

    def fake_get(url, timeout=None):
        probed.append(url)
        return ok_response({"server_version": "2.7.0"})

    with mock.patch.object(ma_api.requests, 'get', side_effect=fake_get):
        base = ma_api.resolve_base(force=True)
    check(base == 'http://192.168.1.50:8095', f"resolved {base}")
    check(probed == ['http://192.168.1.50:8095/info'],
          f"configured host first and only: {probed}")


def scenario_command_roundtrip_and_result_unwrap():
    reset()
    set_settings({"ma_token": "tok", "ma_server_url": "10.0.0.5"})
    with mock.patch.object(ma_api.requests, 'get',
                           return_value=ok_response({"server_version": "2.7.0"})):
        with mock.patch.object(ma_api.requests, 'post',
                               return_value=ok_response(
                                   {"message_id": "1", "result": [{"player_id": "x"}]}
                               )) as post:
            out = ma_api.command('players/all')
            check(out == [{"player_id": "x"}], f"result unwrapped: {out}")
            body = post.call_args.kwargs['json']
            check(body['command'] == 'players/all', "command name sent")
            check('args' in body and body['args'] == {}, "empty args object")
            auth = post.call_args.kwargs['headers']['Authorization']
            check(auth == 'Bearer tok', "bearer token sent")

            ma_api.command('music/favorites/add_item', item='library://track/5',
                           nothing=None)
            body = post.call_args.kwargs['json']
            check(body['args'] == {'item': 'library://track/5'},
                  f"None args dropped: {body['args']}")


def scenario_ma_errors_are_http_200():
    """MA answers a failed command with HTTP 200 and an error_code in the
    body. Treating 200 as success is how a 'favourite added' toast lies."""
    reset()
    set_settings({"ma_token": "tok", "ma_server_url": "10.0.0.5"})
    with mock.patch.object(ma_api.requests, 'get',
                           return_value=ok_response({"server_version": "2.7.0"})):
        with mock.patch.object(ma_api.requests, 'post',
                               return_value=ok_response(
                                   {"message_id": "1", "error_code": "media_not_found",
                                    "details": "no such item"})):
            check(ma_api.command('music/favorites/add_item', item='x') is None,
                  "MA error body -> None despite HTTP 200")
        check('no such item' in ma_api.health.__globals__['_status']['detail'],
              "the reason survives for the health endpoint")


def scenario_refused_token_diagnosed():
    """A wrong address and a wrong token look identical from a wall panel.
    The status has to name which one this is."""
    reset()
    set_settings({"ma_token": "bad", "ma_server_url": "10.0.0.5"})
    with mock.patch.object(ma_api.requests, 'get',
                           return_value=ok_response({"server_version": "2.7.0"})):
        with mock.patch.object(ma_api.requests, 'post',
                               return_value=ok_response({}, status=401)):
            check(ma_api.command('players/all') is None, "401 -> None")
    h_detail = ma_api.health.__globals__['_status']['detail']
    check('token' in h_detail.lower(), f"detail blames the token: {h_detail}")


def scenario_failed_resolve_is_cached_briefly():
    """A music card polls every ten seconds; four dead-host probes each time
    would be forty timeouts a minute. The 'nothing answered' verdict holds
    for a minute, and reset() (settings save) clears it immediately."""
    reset()
    set_settings({"ma_token": "tok"})
    with mock.patch.object(ma_api.requests, 'get',
                           side_effect=Exception("nope")) as get:
        check(ma_api.resolve_base(force=True) is None, "nothing found")
        first = get.call_count
        check(ma_api.resolve_base() is None, "still nothing")
        check(get.call_count == first, "second ask re-probed nothing")
        ma_api.reset()
        ma_api.resolve_base()
        check(get.call_count > first, "reset() clears the verdict")


def scenario_health_names_what_it_tried():
    reset()
    set_settings({"ma_token": "tok", "ma_server_url": "10.9.9.9"})
    with mock.patch.object(ma_api.requests, 'get', side_effect=Exception("nope")):
        h = ma_api.health()
    check(h['configured'] and not h['ok'], "configured but not ok")
    check('10.9.9.9' in h['tried'], f"probed hosts listed: {h['tried']}")
    check('10.9.9.9' in h['detail'], f"detail names the hosts: {h['detail']}")


SCENARIOS = [
    scenario_no_token_means_no_requests,
    scenario_host_setting_is_reused_whatever_its_shape,
    scenario_fallbacks_shared_with_the_relay,
    scenario_configured_host_probed_first,
    scenario_command_roundtrip_and_result_unwrap,
    scenario_ma_errors_are_http_200,
    scenario_refused_token_diagnosed,
    scenario_failed_resolve_is_cached_briefly,
    scenario_health_names_what_it_tried,
]


if __name__ == '__main__':
    failed = 0
    for fn in SCENARIOS:
        try:
            reset()
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
    sys.exit(1 if failed else 0)
