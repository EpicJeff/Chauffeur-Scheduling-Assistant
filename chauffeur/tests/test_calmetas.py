"""An event with no calendar must not take the schedule render down.

The failure this pins, reported from a real wall panel:

    TypeError: Cannot read properties of undefined (reading 'backgroundColor')
      at ... renderSchedule ...

`schedule_timeline.html` read `calMetas[0].backgroundColor` in four places,
and two of them built `calMetas` by mapping `ev.calendar_ids` straight — so an
event with an EMPTY calendar list produced an empty array and `[0]` was
undefined. Nothing in this app HAD an empty one until practice windows became
events (v2.435.6): a program's window belongs to a person, and a person need
not have a calendar of their own.

The other two sites had already been patched, separately, at some earlier
point — which is exactly how a bug survives: as four copies of one expression
with two of them fixed. There is one `calMetasFor` now, and this test RUNS it
rather than reading it, because a template's JavaScript is invisible to Python
tests and every syntax check in this suite passed while the page threw.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TPL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'templates', 'components', 'schedule_timeline.html')


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _extract_helper():
    """The real function, lifted out of the template by name."""
    src = open(TPL, encoding='utf-8').read()
    start = src.index('function calMetasFor(')
    # Brace-match to the end of the function, so this cannot drift with edits.
    depth, i = 0, src.index('{', start)
    while i < len(src):
        if src[i] == '{':
            depth += 1
        elif src[i] == '}':
            depth -= 1
            if depth == 0:
                return src[start:i + 1]
        i += 1
    raise AssertionError('calMetasFor is not brace-balanced')


def _run(js):
    node = shutil.which('node')
    if not node:
        print("  skip  node not installed — the helper was not executed")
        return None
    with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False,
                                     encoding='utf-8') as f:
        f.write(js)
        path = f.name
    try:
        proc = subprocess.run([node, path], capture_output=True, text=True)
        check(proc.returncode == 0,
              f"the helper threw:\n{proc.stderr.strip()}")
        return json.loads(proc.stdout.strip() or 'null')
    finally:
        os.unlink(path)


def scenario_an_event_with_no_calendar_still_has_a_colour():
    helper = _extract_helper()
    js = helper + """
const cases = {
  none:      calMetasFor({calendar_ids: []}, {}),
  missing:   calMetasFor({}, {}),
  nullish:   calMetasFor(null, null),
  unknown:   calMetasFor({calendar_ids: ['nope']}, {}),
  known:     calMetasFor({calendar_ids: ['c1']}, {c1: {backgroundColor: '#abc', summary: 'Mom'}}),
  practice:  calMetasFor({calendar_ids: [], practice: {color: '#ff0088', member_name: 'Jeff'}}, {}),
  fallback:  calMetasFor({calendar_ids: []}, {}, {backgroundColor: '#F59E0B', summary: 'System'}),
};
const out = {};
for (const k of Object.keys(cases)) {
  // The exact expression every call site uses. THIS is what threw.
  out[k] = { len: cases[k].length, color: cases[k][0].backgroundColor,
             summary: cases[k][0].summary };
}
console.log(JSON.stringify(out));
"""
    res = _run(js)
    if res is None:
        return
    for key in ('none', 'missing', 'nullish', 'unknown', 'fallback', 'practice'):
        check(res[key]['len'] >= 1,
              f"'{key}' must never yield an empty list, got {res[key]}")
        check(res[key]['color'],
              f"'{key}' must always answer with a colour, got {res[key]}")
    check(res['known']['color'] == '#abc',
          f"a real calendar still wins, got {res['known']}")
    check(res['practice']['color'] == '#ff0088'
          and res['practice']['summary'] == 'Jeff',
          f"a practice window says whose hour it is here, because this is the "
          f"last place that knows, got {res['practice']}")
    check(res['fallback']['summary'] == 'System',
          f"and a caller's own fallback is honoured, got {res['fallback']}")


def scenario_no_call_site_reads_calendar_ids_raw_any_more():
    """The guard is worth nothing if the fifth copy gets written tomorrow."""
    src = open(TPL, encoding='utf-8').read()
    raw = re.findall(r'ev\.calendar_ids\.map\(', src)
    check(not raw,
          f"{len(raw)} call site(s) still map ev.calendar_ids directly — "
          f"that is the expression that threw")


if __name__ == '__main__':
    scenario_an_event_with_no_calendar_still_has_a_colour()
    scenario_no_call_site_reads_calendar_ids_raw_any_more()
    print("test_calmetas OK")
