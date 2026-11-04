"""The adult PWA's one clock, checked by RUNNING `pwaClock(value, opts)` and
`pwaClockSuffix(value, opts)` under node with no `document` and no `window`.

PWA reimagined slice 5, Task 1 (task-1-brief.md). Both functions live at the
top level of static/pwa_clock.js; a missing file or function FAILS, never
skips. Missing node prints `  skip`.

SIGNATURES PINNED HERE
  pwaClock(value, opts)       -> 'h:mm' (12-hour, no leading zero, no AM/PM)
                                 or 'HH:mm' (opts.use24h true)
  pwaClockSuffix(value, opts) -> 'h:mm AM' / 'h:mm PM' or 'HH:mm' (use24h)
  value: a Date, ms since the epoch, or an ISO string with no zone
         ('2026-11-04T16:30', read as local time); opts may be omitted,
         null or {}; use24h absent/false means 12-hour.
  invalid (unparseable string, null, undefined, NaN) -> ''

Run from chauffeur/ with HA_BASE_URL unset:
    python tests/test_pwa_clock.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pwa_pure import check, pure_source, run_node  # noqa: E402

WANTED = ['pwaClock', 'pwaClockSuffix']

PROBE = r"""
const out = {document_defined: typeof document !== 'undefined',
             window_defined: typeof window !== 'undefined', cases: {}};
const ISO = '2026-11-04T16:30';
const at = (h, m) => new Date(2026, 10, 4, h, m, 0);   // local time
const CASES = {
  twelve_hour: () => ({
    iso_empty_opts: pwaClock(ISO, {}),
    iso_false: pwaClock(ISO, {use24h: false}),
    iso_no_opts: pwaClock(ISO),
    iso_null_opts: pwaClock(ISO, null),
    date: pwaClock(at(16, 30), {}),
    ms: pwaClock(at(16, 30).getTime(), {}),
    morning: pwaClock('2026-11-04T09:05', {}),
  }),
  twenty_four_hour: () => ({
    iso: pwaClock(ISO, {use24h: true}),
    date: pwaClock(at(16, 30), {use24h: true}),
    ms: pwaClock(at(16, 30).getTime(), {use24h: true}),
    morning: pwaClock('2026-11-04T09:05', {use24h: true}),
  }),
  suffix_forms: () => ({
    pm_12: pwaClockSuffix(ISO, {}),
    pm_12_false: pwaClockSuffix(ISO, {use24h: false}),
    pm_no_opts: pwaClockSuffix(ISO),
    pm_24: pwaClockSuffix(ISO, {use24h: true}),
    am_12: pwaClockSuffix('2026-11-04T09:05', {}),
    am_24: pwaClockSuffix('2026-11-04T09:05', {use24h: true}),
    date_12: pwaClockSuffix(at(16, 30), {}),
    ms_12: pwaClockSuffix(at(16, 30).getTime(), {}),
  }),
  midnight_and_noon: () => ({
    midnight_12: pwaClockSuffix('2026-11-04T00:00', {}),
    midnight_24: pwaClockSuffix('2026-11-04T00:00', {use24h: true}),
    noon_12: pwaClockSuffix('2026-11-04T12:00', {}),
    noon_24: pwaClockSuffix('2026-11-04T12:00', {use24h: true}),
    midnight_bare_12: pwaClock('2026-11-04T00:00', {}),
    midnight_bare_24: pwaClock('2026-11-04T00:00', {use24h: true}),
    noon_bare_12: pwaClock('2026-11-04T12:00', {}),
    just_after_midnight_12: pwaClockSuffix('2026-11-04T00:05', {}),
  }),
  invalid_is_empty: () => ({
    nope: pwaClock('nope', {}),
    nope_24: pwaClock('nope', {use24h: true}),
    null_value: pwaClock(null, {}),
    undefined_value: pwaClock(undefined, {}),
    nan: pwaClock(NaN, {}),
    empty_string: pwaClock('', {}),
    suffix_nope: pwaClockSuffix('nope', {}),
    suffix_null: pwaClockSuffix(null, {use24h: true}),
    suffix_nan: pwaClockSuffix(NaN, {}),
  }),
};
for (const [name, fn] of Object.entries(CASES)) {
  try { out.cases[name] = {value: fn()}; }
  catch (e) { out.cases[name] = {error: String((e && e.stack) || e)}; }
}
console.log(JSON.stringify(out));
"""

_CACHE = {}


def _out():
    if 'out' not in _CACHE:
        _CACHE['out'] = run_node(pure_source('pwa_clock.js', WANTED) + '\n' + PROBE)
    return _CACHE['out']


def _case(name):
    out = _out()
    if out is None:
        print("  skip  node is not installed")
        return None
    got = out['cases'][name]
    check('error' not in got, f"{name} threw under node:\n{got.get('error')}")
    return got['value']


def _expect(name, exp):
    got = _case(name)
    if got is None:
        return
    for key, want in exp.items():
        check(got[key] == want, f"{name}.{key}: got {got[key]!r}, expected {want!r}")


def scenario_is_pure():
    out = _out()
    if out is None:
        print("  skip  node is not installed")
        return
    check(not out['document_defined'] and not out['window_defined'],
          "the probe leaked a document/window global")
    for name, got in out['cases'].items():
        check('error' not in got, f"{name} threw with no document/window:\n{got.get('error')}")


def scenario_twelve_hour():
    _expect('twelve_hour', {
        'iso_empty_opts': '4:30', 'iso_false': '4:30', 'iso_no_opts': '4:30',
        'iso_null_opts': '4:30', 'date': '4:30', 'ms': '4:30', 'morning': '9:05',
    })


def scenario_twenty_four_hour():
    _expect('twenty_four_hour', {
        'iso': '16:30', 'date': '16:30', 'ms': '16:30', 'morning': '09:05',
    })


def scenario_suffix_forms():
    _expect('suffix_forms', {
        'pm_12': '4:30 PM', 'pm_12_false': '4:30 PM', 'pm_no_opts': '4:30 PM',
        'pm_24': '16:30', 'am_12': '9:05 AM', 'am_24': '09:05',
        'date_12': '4:30 PM', 'ms_12': '4:30 PM',
    })


def scenario_midnight_and_noon():
    _expect('midnight_and_noon', {
        'midnight_12': '12:00 AM', 'midnight_24': '00:00',
        'noon_12': '12:00 PM', 'noon_24': '12:00',
        'midnight_bare_12': '12:00', 'midnight_bare_24': '00:00',
        'noon_bare_12': '12:00', 'just_after_midnight_12': '12:05 AM',
    })


def scenario_invalid_is_empty():
    got = _case('invalid_is_empty')
    if got is None:
        return
    for key, val in got.items():
        check(val == '', f"invalid_is_empty.{key}: got {val!r}, expected ''")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"  ok  {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {fn.__name__}: {e}")
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} pwa clock scenarios passed")
    sys.exit(1 if failed else 0)
