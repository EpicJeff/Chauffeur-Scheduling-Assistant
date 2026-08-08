"""The wall panel's chrome: what is on screen when nobody is using it.

A panel is looked at far more than it is touched, so its resting state is the
design. These are string-level guards over the templates — cheap, and each one
stands for a thing that actually shipped wrong:

  - panel mode has to write `kiosk=true` into the URL BEFORE anything reads it,
    or ten pages' worth of existing kiosk gating silently does nothing;
  - the shelf, the page padding and the Argyle bar all have to derive from one
    height, because the first version guessed each separately and the chat bar
    landed on top of the shelf and swallowed two buttons;
  - the Argyle bar has to be collapsed at rest. A black slab lying across the
    bottom of a display for the 99% of the day nobody is talking to it is the
    single most intrusive thing that was on the board.

Run from chauffeur/:  python tests/test_panel_chrome.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TPL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'templates')
THEME = open(os.path.join(TPL, 'ha_theme.html'), encoding='utf-8').read()
CC = open(os.path.join(TPL, 'components', 'control_center.html'), encoding='utf-8').read()
NAV = open(os.path.join(TPL, 'nav.html'), encoding='utf-8').read()


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def scenario_panel_mode_turns_on_kiosk_before_anything_reads_the_url():
    """ha_theme is the first thing in every page's <head>. If this moves, or
    stops rewriting the address, every `?kiosk=true` check in the app goes
    quiet on a panel and the admin chrome comes back on the kitchen wall."""
    check("p.get('panel') !== 'true'" in THEME, "panel mode detection is gone")
    check("p.set('kiosk', 'true')" in THEME, "panel mode no longer implies kiosk")
    check('history.replaceState' in THEME,
          "the kiosk flag is no longer written into the address")
    check(THEME.index("p.set('kiosk', 'true')") < THEME.index('urlParamsTheme'),
          "the rewrite must happen before anything reads the URL")


def scenario_one_shelf_height_feeds_everything_that_must_clear_it():
    """The chat bar sat ON the shelf because each guessed its own number."""
    check('--panel-shelf-h' in THEME, "the shared shelf height is gone")
    check('min-height: var(--panel-shelf-h)' in NAV,
          "the shelf no longer pins its own height to the shared value")
    for needle in ('padding-bottom: calc(var(--panel-shelf-h)',
                   'bottom: calc(var(--panel-shelf-h)'):
        check(needle in THEME, f"'{needle}...' no longer derives from the shared height")


def scenario_the_shelf_has_no_background_and_the_content_fades_behind_it():
    """The shelf carries nothing of its own; a separate fixed strip ramps a
    backdrop blur in via a mask so content dissolves on the way down.

    Two traps this guards, both of which make the obvious implementation fail:
    the fade must NOT be a child of the shelf (the shelf has to stay
    background-free), and it must not be done by masking the scrolling content
    (a mask on <body> is sized to the document, so the fade lands at the bottom
    of the page rather than the screen — and it would capture the fixed shelf
    and fade the buttons too)."""
    block = THEME[THEME.index('html[data-panel] #panel-shelf {'):]
    block = block[:block.index('}') + 1]
    for prop in ('background: none', 'backdrop-filter: none', 'border-top: none'):
        check(prop in block, f"the shelf grew a background again: missing {prop}")

    check('#panel-fade' in THEME and 'id="panel-fade"' in NAV,
          "the fade strip is gone")
    fade = THEME[THEME.index('html[data-panel] #panel-fade {'):]
    fade = fade[:fade.index('}') + 1]
    check('backdrop-filter: blur' in fade, "the fade no longer blurs what is behind it")
    check('mask-image' in fade, "the blur is no longer ramped by a mask — hard edge")
    check('pointer-events: none' in fade, "the fade would swallow taps")

    # It must sit under the shelf and over the content, or it either hides the
    # buttons or does nothing at all.
    check('z-index: 65' in fade, "the fade is no longer between content and shelf")
    check(NAV.index('id="panel-fade"') < NAV.index('id="panel-shelf"'),
          "the fade must be a sibling BEFORE the shelf, not inside it")


def scenario_the_argyle_bar_is_collapsed_at_rest_on_a_panel():
    """It opens on a tap and gets out of the way again."""
    open_rule = 'html[data-panel] #chat-overlay-container.panel-chat-open'
    check(open_rule in THEME, "there is no open state for the panel chat bar")
    base = THEME.index('html[data-panel] #chat-overlay-container {')
    block = THEME[base:THEME.index(open_rule)]
    check('visibility: hidden' in block,
          "the chat bar is no longer hidden at rest on a panel")
    check('panel-chat-open' in CC and 'panel-chat-orb' in CC,
          "nothing opens the collapsed chat bar")


def scenario_the_orb_gets_out_of_the_way_and_comes_back():
    for needle in ("orb.addEventListener('click'", 'closeChat', "e.key === 'Escape'",
                   'panel-chat-hidden'):
        check(needle in CC, f"the orb is missing: {needle}")
    check('chat-submit-btn' in CC and 'setTimeout(closeChat' in CC,
          "sending a message no longer closes the bar")


def scenario_chat_none_still_wins_over_the_orb():
    """An embedded card that wants no Argyle at all must get none — not an
    orb instead of a bar."""
    idx = CC.index("['none', 'off', '0', 'false', 'hide']")
    after = CC[idx:idx + 400]
    check('return' in after,
          "?chat=none no longer short-circuits before the panel orb is built")


def scenario_the_orb_does_not_pulse_for_people_who_asked_it_not_to():
    check('prefers-reduced-motion: no-preference' in THEME,
          "the orb animates regardless of the reduced-motion preference")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} panel-chrome scenarios passed")
