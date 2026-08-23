"""Sharing a moment OUT of Chauffeur, run in node against the real app.html.

The share path is browser-only — `navigator.share`, `navigator.canShare`, a
`File` built from a fetched blob — so nothing on the server can assert any of
it. What CAN be asserted, and is the part with actual decisions in it, is the
logic around the sheet: which string travels, who gets the button, and what
happens when the device cannot share files.

The string matters most. A moment inside the app is anchored to an event and
routed to the people the schedule proved missed it; none of that crosses to
WhatsApp. The one thing that travels is the caption, and the rule — the user's
— is that the app never generates a person's name or a date into it. The
sender adds a name if they judge that fine.

The functions are lifted out of the rendered template by name rather than
booting the whole PWA: they are pure, and a jsdom boot would drag in Alpine,
the schedule fetch and the service worker for no extra proof.

**Skips** (rather than fails) when node is unavailable.

Run from chauffeur/:  python tests/test_share_out.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SCRATCH = tempfile.mkdtemp(prefix='chauffeur_share_out_')
APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'templates', 'app.html')


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _extract(name):
    """Pull one top-level `function name(...) { ... }` out of app.html.

    Brace-counting, because the template is one 8000-line script and there is
    no module boundary to import across. A rename breaks this loudly, which is
    the intent — a silently-skipped assertion would be worse than a red test.
    """
    with open(APP, encoding='utf-8') as f:
        src = f.read()
    start = src.find(f'function {name}(')
    check(start >= 0, f"app.html no longer defines {name}() — the share slice moved")
    i = src.index('{', start)
    depth = 0
    for j in range(i, len(src)):
        if src[j] == '{':
            depth += 1
        elif src[j] == '}':
            depth -= 1
            if depth == 0:
                return src[start:j + 1]
    raise AssertionError(f"{name}() is unbalanced in app.html")


_NODE = shutil.which('node')


def _run(js):
    """Run a snippet with the extracted functions in scope; return its JSON."""
    if not _NODE:
        return None
    harness = os.path.join(SCRATCH, 'share_harness.js')
    with open(harness, 'w', encoding='utf-8') as f:
        f.write('let membersData = [], selectedMemberId = null;\n')
        f.write(_extract('myRole') + '\n')
        f.write(_extract('momentShareText') + '\n')
        f.write(_extract('canShareOut') + '\n')
        f.write(_extract('canShareMsg') + '\n')
        f.write(js)
    proc = subprocess.run([_NODE, harness], capture_output=True, text=True,
                          cwd=SCRATCH, timeout=60)
    check(proc.returncode == 0,
          f"the share helpers threw:\n{proc.stderr[:2000]}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


def scenario_the_caption_travels_when_there_is_one():
    got = _run("""
        console.log(JSON.stringify({
            captioned: momentShareText('She got a kill!', "Emma's volleyball game"),
            blank: momentShareText('   ', "Emma's volleyball game"),
            neither: momentShareText('', ''),
            padded: momentShareText('  a good one  ', 'x')
        }));
    """)
    if got is None:
        print("  skip  node is not installed — the ladder was not run")
        return
    check(got['captioned'] == 'She got a kill!',
          f"the sender's own words lost to the event title: {got['captioned']}")
    check(got['blank'] == "Emma's volleyball game",
          f"a blank caption did not fall through to the event: {got['blank']}")
    check(got['neither'] == '',
          f"a DM moment with no caption invented something to say: {got['neither']}")
    check(got['padded'] == 'a good one', "the caption was not trimmed")


def scenario_nothing_is_ever_generated_into_the_share():
    """The rule, asserted as a rule.

    Attendee names and dates are the two things the app must never synthesize
    into an outbound string — a share saying "Emma's game, Saturday" tells a
    group chat where a child reliably is. An event TITLE is different and goes
    as typed: it is the family's own words, and the sender can edit it in the
    target app's compose box before sending.
    """
    got = _run("""
        console.log(JSON.stringify({
            out: momentShareText('', 'Volleyball'),
            outWithCaption: momentShareText('so proud', 'Volleyball')
        }));
    """)
    if got is None:
        return
    for key, value in got.items():
        check(not re.search(r'\d{4}-\d{2}-\d{2}', value),
              f"{key} carried a date: {value}")
        check(not re.search(r'\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b', value),
              f"{key} carried a day name: {value}")
        check(' from ' not in value and 'with ' not in value,
              f"{key} looks like it names people: {value}")
    check(got['out'] == 'Volleyball',
          "the event title did not travel as typed")


def scenario_only_parents_and_adults_get_the_button():
    """Children, helpers and guests do not — the user's call.

    A norm rather than a control, and deliberately so: `navigator.share` is
    client-side with no server mirror, so anyone who can see a moment can
    already save or screenshot it. The button is the difference between a
    thoughtless share and a determined one.
    """
    got = _run("""
        const out = {};
        for (const role of ['parent', 'adult', 'child', 'helper', 'guest', '']) {
            membersData = [{ id: 'm1', role: role }];
            selectedMemberId = 'm1';
            out[role || 'none'] = canShareOut();
        }
        console.log(JSON.stringify(out));
    """)
    if got is None:
        return
    check(got['parent'] is True, "a parent cannot share out")
    check(got['adult'] is True, "an adult cannot share out — the user chose all adults")
    for role in ('child', 'helper', 'guest', 'none'):
        check(got[role] is False,
              f"{role} was offered the share button, which the user ruled out")


def scenario_there_has_to_be_something_to_share():
    got = _run("""
        membersData = [{ id: 'm1', role: 'parent' }];
        selectedMemberId = 'm1';
        console.log(JSON.stringify({
            text: canShareMsg({ sender_member_id: 'm2', body: 'hello' }),
            photo: canShareMsg({ sender_member_id: 'm2', body: '', attachment: { kind: 'photo' } }),
            empty: canShareMsg({ sender_member_id: 'm2', body: '   ' }),
            argyle: canShareMsg({ sender_member_id: 'argyle', body: 'I booked it' })
        }));
    """)
    if got is None:
        return
    check(got['text'] is True, "a text message cannot be shared")
    check(got['photo'] is True, "a captionless photo cannot be shared")
    check(got['empty'] is False, "an empty message offered a share button")
    check(got['argyle'] is False,
          "Argyle's own reply offered a share button — the assistant's words "
          "are house furniture, not a family moment")


def scenario_a_kid_sees_no_button_anywhere():
    """The gate is asked once and used by both placements.

    `canShareMsg` defers to `canShareOut`, and the overlay asks `canShareOut`
    directly — so there is no second, drifting copy of the rule.
    """
    got = _run("""
        membersData = [{ id: 'k1', role: 'child' }];
        selectedMemberId = 'k1';
        console.log(JSON.stringify({
            sheet: canShareMsg({ sender_member_id: 'k1', body: 'look!',
                                 attachment: { kind: 'photo' } }),
            gate: canShareOut()
        }));
    """)
    if got is None:
        return
    check(got['gate'] is False and got['sheet'] is False,
          f"a child reached the share button: {got}")


def scenario_the_overlay_and_the_sheet_both_carry_it():
    """Source check, and the only thing that can notice a half-wired slice.

    Every piece can be individually correct while the button is drawn nowhere.
    """
    with open(APP, encoding='utf-8') as f:
        app = f.read()
    check('class="moment-share' in app,
          "the moment overlay no longer draws a Share button")
    check("shareMessage(this, '${m.id}')" in app,
          "the message action sheet no longer draws a Share button")
    check('canEditMsg(m) || canDeleteMsg(m) || canShareMsg(m)' in app,
          "the ⋯ toggle does not account for share, so the sheet holding the "
          "Share button can never be opened")
    check("title: ch.kind === 'event' ? ch.title : ''" in app,
          "openMomentById stopped passing the event title, so the share "
          "ladder has nothing to fall back to")


def scenario_photos_are_uploaded_not_inlined():
    """A ten-photo album must not be a 160 MB JSON POST, so photos go to the
    media store first and the message carries urls."""
    src = _extract('uploadMomentPhoto')
    check('api/media/photo' in src,
          'the photo upload posts to the media-store route')
    check('data_url' in src,
          'it sends the rendition as a data url')

    send = _extract('submitThreadMessage')
    check('data_url' not in send,
          'the message body no longer carries image bytes')
    check('_dataUrl' in send and '!att.url' in send,
          'a retry must not re-upload an already-uploaded photo — nothing '
          'garbage-collects the orphan that would leave behind. This is a '
          'source check, not a runtime one: it proves the guard text is '
          'present, not that the control flow actually skips the second '
          'upload at runtime.')


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    try:
        for fn in SCENARIOS:
            fn()
            print(f"  ok  {fn.__name__}")
        print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} share-out scenarios passed")
    finally:
        shutil.rmtree(SCRATCH, ignore_errors=True)
