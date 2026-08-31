"""One tap, one answer, whichever surface it was tapped from.

The Family tab gave you a practice session; the Family Day card gave you a
generic event dialog for the same window; the calendar gave you neither and
sent a trip tap to the trip EDITOR. Three surfaces, three answers, and the
inconsistency was invisible from any one of them.

Worse, `_onEventTap` navigated to the trip editor for any host that had turned
`details` on -- which includes a wall panel, where the person tapping is
whoever walked past and the page they land on can rewrite the household's
holiday. `details` means "say what this is"; it was quietly also granting
"and let them change it".

Run from chauffeur/:  python tests/test_event_details_consistency.py
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TPL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'templates')


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _read(*parts):
    with open(os.path.join(TPL, *parts), encoding='utf-8') as f:
        return f.read()


def _fn(src, name):
    """One function's body. The component's functions sit at column 0 and the
    PWA's are indented inside a <script>, so the indent is matched rather
    than assumed away."""
    m = re.search(r'\n(\s*)function ' + re.escape(name) + r'\s*\(', src)
    check(m, f"{name}() must exist")
    rest = src[m.end():]
    nxt = re.search(r'\n' + m.group(1) + r'(?:async )?function ', rest)
    return rest[:nxt.start()] if nxt else rest


def scenario_a_wall_cannot_walk_into_the_trip_editor():
    """The one that matters. A trip tap may leave for the editor only where a
    host explicitly says so, and `details` is not that permission."""
    cal = _read('components', 'family_calendar.html')
    tap = _fn(cal, '_onEventTap')
    check('inst.opts.tripLinks' in tap,
          "the trip link needs its own permission, not `details`")
    check(re.search(r'props\.isTrip && inst\.opts\.tripLinks', tap),
          "and it must be checked before any navigation")
    check(re.search(r'\n\s*tripLinks: false,', cal),
          "which defaults to off, so a surface has to ask for it")

    board = _read('home.html')
    mount = board[board.index('await FamilyCalendar.mount({'):][:900]
    check('tripLinks' not in mount,
          "a board card must never turn it on -- a wall is a hallway")


def scenario_the_calendar_page_keeps_it_and_its_kiosk_does_not():
    """Same page, two surfaces: one a person opened, one hung on a wall."""
    page = _read('calendar.html')
    check("tripLinks: _calUrlParams.get('kiosk') !== 'true'" in page,
          "the calendar page keeps the editor link and its kiosk gives it up, "
          "the same way it already gives up `onConfigure`")


def scenario_every_kind_answers_in_its_own_terms():
    """A practice window is not an event with a funny title, and the body of
    the dialog was the same four fields for all of them."""
    cal = _read('components', 'family_calendar.html')
    typed = _fn(cal, '_typedDetailsHtml')
    for prop, why in (('isPractice', 'a session'),
                      ('isTrip', 'a trip'),
                      ('isErrand', 'an errand')):
        check(prop in typed, f"{prop} must get {why} of its own")
    for bit in ('session_label', 'unit_title', 'unit_url', 'unit_body',
                'steps', 'progression', 'milestone'):
        check(bit in typed, f"the session must carry {bit}")
    check('id="modal-typed-container"' in cal,
          "and the dialog needs somewhere to put it")
    check('_typedDetailsHtml(props)' in cal,
          "which the dialog fills on every open")


def scenario_a_practice_window_does_not_say_its_steps_twice():
    """`description` on a practice event is the steps joined with dots, for
    surfaces that can only draw one line. Having said them properly, saying
    them again as a blob is noise."""
    cal = _read('components', 'family_calendar.html')
    check('if (props.description && !props.isPractice) {' in cal,
          "the flat description is for everything except a practice window")


def scenario_the_phone_answers_a_trip_tap_too():
    """It was the last row in the Family tab that opened nothing -- and a
    background trip is exactly the one whose meaning cannot be inferred from
    its title."""
    app = _read('app.html')
    check('function openTripSheet(' in app, "the phone needs a trip sheet")
    check('openTripSheet(' in app[app.index('if (card.isTrip) {'):][:900],
          "and the trip card must open it")
    sheet = app[app.index('function openTripSheet('):][:1400]
    check('leaves their events alone' in sheet,
          "saying the same thing the wall's dialog says, in the same words")
    check('trip?event_id' not in sheet and 'location.href' not in sheet,
          "and never offering a way into the editor from a phone's read")


def scenario_a_trip_answers_with_what_it_actually_has():
    """A background trip IS an ordinary calendar event: it has attendees, a
    location, a description and a span of days. The event object carried
    three fields, because the tap used to navigate away and nothing else was
    ever read -- so the dialog said "No passengers / Not assigned / No
    location" over a trip that has all of them."""
    cal = _read('components', 'family_calendar.html')
    trip = cal[cal.index('isTrip: true,'):][:900]
    for field in ('passengers:', 'location:', 'description:', 'driverName:'):
        check(field in trip, f"a trip event must carry {field}")
    check('_tripPax(ev, data)' in trip,
          "and its attendees in the same pill shape every event uses")
    merge = _fn(cal, '_mergeTripPax')
    check('passengers' in merge,
          "every day-slice of one trip contributes its own attendees")


def scenario_an_all_day_span_says_both_ends():
    """A week-long trip said one date and "(All Day)" -- the single most
    useful fact about it left unsaid. And an all-day calendar event ends at
    midnight of the day AFTER its last day, so read literally the trip comes
    home on a day nobody is travelling."""
    cal = _read('components', 'family_calendar.html')
    body = cal[cal.index("let timeText = '';"):][:1500]
    check('setUTCDate' in body and 'getUTCHours() === 0' in body,
          "the exclusive end has to be corrected before it is shown")
    check('_spans' in body, "and a multi-day thing prints both ends")

    app = _read('app.html')
    span = _fn(app, 'tripSpanLabel')
    check('setDate(last.getDate() - 1)' in span,
          "the phone corrects it the same way")


def scenario_not_assigned_is_not_said_over_a_holiday():
    """The same false gap the practice line already retired: nothing is
    missing, the schedule simply does not plan this."""
    cal = _read('components', 'family_calendar.html')
    check("} else if (props.isTrip) {" in cal
          and "doesn't plan the travel for a trip" in cal,
          "a trip says why no driver is named, rather than 'Not assigned'")


if __name__ == '__main__':
    scenario_a_wall_cannot_walk_into_the_trip_editor()
    scenario_the_calendar_page_keeps_it_and_its_kiosk_does_not()
    scenario_every_kind_answers_in_its_own_terms()
    scenario_a_practice_window_does_not_say_its_steps_twice()
    scenario_the_phone_answers_a_trip_tap_too()
    scenario_a_trip_answers_with_what_it_actually_has()
    scenario_an_all_day_span_says_both_ends()
    scenario_not_assigned_is_not_said_over_a_holiday()
    print("test_event_details_consistency OK")
