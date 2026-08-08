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


SKIN = open(os.path.join(TPL, 'panel_skin.html'), encoding='utf-8').read()


def scenario_the_skin_reaches_every_page():
    """A look that stops at the home board is worse than no look — tapping
    DRIVES on the shelf dropped you out of a photographic display and into a
    flat dark web page, which makes the other ten look broken rather than
    plain. The skin is included from ha_theme, which is in every page's head,
    and maps the Tailwind greys the pages are already written in."""
    check("{% include 'panel_skin.html' %}" in THEME,
          "the skin is no longer included from ha_theme, so only /home has it")
    import glob
    pages = [p for p in glob.glob(os.path.join(TPL, '*.html'))
             if os.path.basename(p) not in
             ('nav.html', 'ha_theme.html', 'panel_skin.html', 'app.html',
              'moment.html', 'trip_kiosk.html')]
    for path in pages:
        body = open(path, encoding='utf-8').read()
        check("{% include 'ha_theme.html' %}" in body,
              f"{os.path.basename(path)} does not include ha_theme, so it "
              f"gets no panel skin")


def scenario_the_panel_never_flashes_the_browser_chrome():
    """Every page load showed the desktop nav bar for a frame or two before JS
    swapped it for the shelf, which reads as a hack rather than a product. The
    switch has to be CSS in the head — `data-panel` is set synchronously before
    the body exists, so these rules hold at the first paint. If this reverts to
    a DOMContentLoaded hide, the flash comes straight back."""
    check('html[data-panel] #top-nav-bar' in SKIN,
          "the top bar is no longer hidden by CSS — the flash is back")
    block = SKIN[SKIN.index('html[data-panel] #top-nav-bar'):]
    check('display: none !important' in block[:block.index('}')],
          "the top bar rule no longer hides it")
    for el in ('#panel-shelf', '#panel-fade'):
        check(f'html[data-panel] {el}.hidden' in SKIN,
              f"{el} still waits for JS to reveal it")


def scenario_the_shelf_does_not_flash_the_wrong_buttons():
    """One level down: a shelf visible from the first paint would show all
    twelve destinations and snap to six when the profile lands. The URL wins
    when it says anything; otherwise the last known list decides before
    anything renders, and the guess is retired once the real answer arrives."""
    check("id = 'panel-early-tabs'" in THEME or "st.id = 'panel-early-tabs'" in THEME,
          "there is no head-time tab filter")
    check('chauffeurPanelTabs' in THEME, "the head never reads the cached tabs")
    check('chauffeurPanelTabs' in NAV, "the resolved tabs are never cached")
    check("getElementById('panel-early-tabs')" in NAV and 'early.remove()' in NAV,
          "the head-time guess is never retired, so it outranks the real answer")


def scenario_the_skin_maps_the_greys_the_pages_are_written_in():
    """Eleven templates were not going to be rewritten. The greys they already
    use are mapped onto the tokens instead — surfaces, ink and edges."""
    for needle in ('html[data-panel] .bg-gray-800', 'html[data-panel] .text-gray-300',
                   'html[data-panel] .border-gray-700', 'html[data-panel] input'):
        check(needle in SKIN, f"the skin no longer maps {needle}")
    check('--panel-card' in SKIN and '--panel-fg' in SKIN,
          "the tokens moved out of the shared skin")


def scenario_the_grey_mapping_never_applies_a_filter():
    """This one broke the whole panel once and the reason is not obvious.

    A filter — `backdrop-filter` included — makes an element a CONTAINING BLOCK
    for every fixed-position descendant and opens a new stacking context. The
    mapped greys ARE blurred (that is the glass everyone wanted), and `config`
    and `map` carry `bg-gray-900` on <body>. So the whole scheme rests on one
    override: the body must force `filter: none`. Without it the shelf, the orb
    and the two `z-index: -2` background layers are captured by the body and
    the photograph ends up behind the element it was meant to sit behind."""
    # <body> is the safety net for the whole scheme. A filter makes an element
    # a containing block for fixed descendants, and `config` and `map` put
    # `bg-gray-900` on their body — the tier that is now blurred. Without this
    # override the shelf, the orb and both background layers get trapped
    # inside the body and the panel goes flat, which is exactly what v2.115
    # shipped.
    body_rule = SKIN[SKIN.index('html[data-panel] body,'):]
    body_rule = body_rule[:body_rule.index('}')]
    # `background:` not `background-color:` — Calendar and Trips give the body
    # a gradient, and clearing only the colour leaves its background-IMAGE to
    # cover the photograph.
    for prop in ('backdrop-filter: none', 'filter: none',
                 'background: transparent', 'background-image: none'):
        check(prop in body_rule, f"the body no longer forces {prop}")
    for tier in ('bg-gray-950', 'bg-gray-900', 'bg-gray-800'):
        check(f'body.{tier}' in body_rule,
              f"body.{tier} is no longer neutralised, so a page using it on "
              f"<body> would trap the panel's fixed chrome")


def scenario_panel_mode_turns_the_ha_theme_off():
    """Two complete themes cannot both be on, and this one was winning silently.

    Panel mode writes `kiosk=true` into the address so the app's existing kiosk
    gating lights up — which also switched on HA theming, whose mapping paints
    every `bg-gray-900` a flat `#111111 !important`. A standalone panel has no
    parent frame to sync colours from, so `--ha-bg` never resolves and that
    fallback IS the theme: opaque slabs over the photograph. It beat the panel
    skin because both are `!important` at equal specificity and ha_theme's
    styles came later in the file.

    Fixed by suppressing HA theming in panel mode outright, rather than by
    out-specifying it — and by making the skin the later stylesheet, so a
    future HA rule cannot outrank the panel just by being added below."""
    check("const isPanelTheme = urlParamsTheme.get('panel') === 'true'" in THEME,
          "panel mode is no longer detected in the theme switch")
    check('!isPanelTheme' in THEME,
          "HA theming is no longer suppressed on a panel — its #111111 "
          "fallback will paint over the photograph again")
    check(THEME.index("{% include 'panel_skin.html' %}") > THEME.index('<style>'),
          "the panel skin is included before the HA styles, so on an "
          "equal-specificity !important tie the HA rule wins")


def scenario_a_field_that_is_its_own_container_stays_transparent():
    """The Argyle bar is one textarea inside a rounded shell. Giving every
    field a surface drew a second, differently-coloured box inside the first —
    visible as a pale slab in light mode and a dark one in dark. `.bg-transparent`
    is the app saying "this field IS its container", so the mapping leaves it
    alone and only sets the ink."""
    check('input:not(.bg-transparent)' in SKIN,
          "the input mapping paints over deliberately transparent fields again")
    check('html[data-panel] textarea.bg-transparent' in SKIN,
          "transparent fields are not explicitly kept transparent")
    check('bg-transparent' in CC,
          "the Argyle input no longer declares itself transparent, so the "
          "mapping will give it a box of its own")


def scenario_the_panel_canvas_is_never_browser_white():
    """The body is transparent in panel mode so the photograph shows through —
    which means the ROOT has to carry the base colour. Without it the canvas is
    browser white, and every page showed either a white band or (on the board,
    where a dark scrim sits over it) a flat mid-grey."""
    check('html[data-panel] {' in SKIN, "the root rule is gone")
    block = SKIN[SKIN.index('html[data-panel] {'):]
    block = block[:block.index('}')]
    check('background-color: var(--panel-bg)' in block,
          "the root no longer carries the base colour — the canvas goes white")


def scenario_the_orb_opens_from_the_middle():
    """It shares the chat bar's centring transform, so tapping it reads as one
    thing growing rather than a swap between two corners. If the collapse ever
    drops `translateX(-50%)`, the orb jumps to the left edge on its way out."""
    block = THEME[THEME.index('#panel-chat-orb {'):]
    block = block[:block.index('}')]
    check('left: 50%' in block and 'translateX(-50%)' in block,
          "the orb is no longer centred on the chat bar's axis")
    hidden = THEME[THEME.index('#panel-chat-orb.panel-chat-hidden {'):]
    hidden = hidden[:hidden.index('}')]
    check('translateX(-50%)' in hidden,
          "the collapsed orb loses its centring and jumps to the left edge")


def scenario_every_page_says_its_name_in_the_same_place():
    """Some pages had no title, some a 2xl, one a 4xl gradient, and each sat in
    a container of its own width — so walking the shelf moved the title around
    the screen on every tap. One class for the name, one for the frame."""
    import glob
    pages = [p for p in glob.glob(os.path.join(TPL, '*.html'))
             if os.path.basename(p) not in
             ('nav.html', 'ha_theme.html', 'panel_skin.html', 'app.html',
              'moment.html', 'trip_kiosk.html', 'home.html',
              'config.html', 'settings.html')]
    for path in pages:
        body = open(path, encoding='utf-8').read()
        name = os.path.basename(path)
        check('panel-page-title' in body, f"{name} has no page title")
        check('panel-page' in body.replace('panel-page-title', ''),
              f"{name}'s title is not in a .panel-page frame, so it will not "
              f"line up with the others")


def scenario_the_page_background_never_covers_the_photograph():
    """You could see the picture behind the shelf and nowhere else: `bg-gray-900`
    is Tailwind's PAGE background and pages put it on the wrapper that fills the
    content area, so mapping it to a surface laid a slab over the photo. Only
    800/700/600 — actual cards — are surfaces."""
    """The split is by USAGE, not shade: bare `bg-gray-900` is a card (the
    schedule's driver column), while the opacity variants are the page-level
    scroll wrappers that fill the content area. Getting it backwards put a slab
    over the picture one way, and deleted the schedule's panes the other."""
    block = SKIN[SKIN.index('html[data-panel] .bg-gray-900\/30,'):]
    block = block[:block.index('}')]
    check('transparent' in block,
          "the page-level wrappers are painting a surface over the background")
    check('.panel-page' in block,
          "the page frame is not among the transparent wrappers")
    card = SKIN[SKIN.index('html[data-panel] .bg-gray-950,'):]
    card = card[:card.index('}')]
    check('--panel-surface-1' in card and 'backdrop-filter' in card,
          "bare bg-gray-900 is no longer glass — the schedule's driver columns "
          "and the dashboard's sidebar are cards, not page wrappers")


def scenario_the_skin_stays_out_of_the_browser():
    """Silently restyling every page of a working app for people at a laptop is
    a much bigger promise than the one being made. Every mapping rule is scoped
    to panel mode."""
    import re
    body = SKIN[SKIN.index('html[data-panel] body'):]
    rules = re.findall(r'^\s{4}([^\s@}][^{]*)\{', body, re.M)
    for sel in rules:
        check('html[data-panel]' in sel,
              f"a skin rule escapes panel mode and hits the browser: {sel.strip()[:60]}")


def scenario_a_page_can_have_its_own_picture():
    from services import home_board
    got = home_board.backgrounds({
        'panel_background': 'mountains at dusk',
        'panel_page_backgrounds': {'schedule': 'empty highway at dawn',
                                   'nonsense': 'x', 'map': '   '}})
    check(got['default'].startswith('api/unsplash/background?query=mountains'),
          "the default picture is gone")
    check('highway' in got['schedule'], "a page's own picture is not resolved")
    check('nonsense' not in got, "an unknown page slug is stored anyway")
    check('map' not in got, "a blank entry is treated as a picture")


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
