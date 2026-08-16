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

import tpl_source  # noqa: E402

TPL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'templates')
THEME = open(os.path.join(TPL, 'ha_theme.html'), encoding='utf-8').read()
CC = open(os.path.join(TPL, 'components', 'control_center.html'), encoding='utf-8').read()
NAV = open(os.path.join(TPL, 'nav.html'), encoding='utf-8').read()


HIDDEN = "classList.add(" + chr(39) + "hidden" + chr(39) + ")"


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
              'moment.html', 'trip_kiosk.html',
              # Never drawn on a panel: the invite/reset landing page (auth
              # arc S3) is a standalone page opened from a mail client, with
              # no shell, no nav and no session. A panel skin on it would be
              # styling for a context it can never appear in.
              'set_password.html')]
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
    """One level down: a shelf visible from the first paint must not show all
    twelve destinations and snap to six when the profile lands — nor render in
    one order and shuffle into another, which is what shipped in v2.119.0 and
    was reported from the kitchen as the buttons jumping around.

    This was a head-time CSS guess off a cached list. It is the SERVER's answer
    now: nav.html asks `shelf_order()` (the same `resolve_tabs` the profile
    endpoint returns) and renders the buttons filtered and ordered. That is
    both earlier than any script and correct on the first load, where a cache
    has nothing to say — and a stale cache can no longer hide a button the
    server rightly drew.

    `?tabs=none` stays in the head: it hides the whole nav, which is this
    file's chrome rather than the shelf's contents."""
    check("st.id = 'panel-early-tabs'" in THEME,
          "?tabs=none no longer hides the nav before paint")
    check('chauffeurPanelTabs' not in THEME and 'chauffeurPanelTabs' not in NAV,
          "the cached-tabs guess is back — the server renders the shelf now, "
          "and a cache can only contradict it")
    check('{% set _order = shelf_order(request) %}' in NAV,
          "the shelf no longer takes its order from the server, so it is back "
          "to being rearranged after the paint")
    # One loop over one order, holding both kinds of destination. It used to
    # be a SHELF_ITEMS list built from NAV_ITEMS; the household's own boards
    # joined the shelf in v2.189.0 and were rendered as a second loop, which
    # made the shelf two lists that had to agree about order — and did not.
    check('{% for slug in _order %}' in NAV,
          "the shelf does not render the server's ordered list")
    check(NAV.count('{% for slug in _order %}') == 1,
          "the shelf is built from more than one pass over the order again")


def scenario_the_skin_maps_the_greys_the_pages_are_written_in():
    """Eleven templates were not going to be rewritten. The greys they already
    use are mapped onto the tokens instead — surfaces, ink and edges."""
    for needle in ('html[data-panel] .bg-gray-800', 'html[data-panel] .text-gray-300',
                   'html[data-panel] .border-gray-700', 'html[data-panel] input'):
        check(needle in SKIN, f"the skin no longer maps {needle}")
    check('--panel-card' in SKIN and '--panel-fg' in SKIN,
          "the tokens moved out of the shared skin")


def scenario_the_grey_mapping_never_applies_a_filter():
    """This one broke the whole panel twice, for two different reasons.

    CORRECTNESS: a filter — `backdrop-filter` included — makes an element a
    CONTAINING BLOCK for every fixed-position descendant and opens a new
    stacking context. `config` and `map` carry `bg-gray-900` on <body>, so a
    filter on that tier lands on the body, captures the shelf, the orb and the
    two `z-index: -2` background layers, and puts the photograph behind the
    element it was meant to sit behind.

    PERFORMANCE: these selectors match every card on every page — 154
    `bg-gray-*` sites in the driver app alone, more once a list renders. Each
    blurred element is a compositing layer that re-blurs a full-screen
    photograph per frame. That is what made the Raspberry Pi panel take
    seconds to answer a tap. The blur budget is two things: `.panel-card` and
    `#panel-fade`."""
    # The three mapped tiers must carry no filter of their own. Slice each rule
    # at its closing brace so a `backdrop-filter` further down the file (the
    # budget rule, `.panel-card`) cannot make this pass by accident.
    for tier in ('html[data-panel] .bg-gray-950,',
                 'html[data-panel] .bg-gray-800,',
                 'html[data-panel] .bg-gray-700,'):
        rule = SKIN[SKIN.index(tier):]
        rule = rule[:rule.index('}')]
        check('backdrop-filter' not in rule,
              f"the mapped tier starting '{tier}' is blurred again — that is "
              f"one compositing layer per card on a Raspberry Pi, and it is "
              f"what the panel's several-second tap latency was")
    # The blur that IS allowed, so this guard cannot be satisfied by deleting
    # the look entirely.
    check('backdrop-filter: blur(16px) saturate(140%)' in SKIN,
          ".panel-card lost its glass — the budget is two blurs, not zero")

    # <body> is the safety net for the whole scheme. A filter makes an element
    # a containing block for fixed descendants, and `config` and `map` put
    # `bg-gray-900` on their body. Without this override the shelf, the orb and
    # both background layers get trapped inside the body and the panel goes
    # flat, which is exactly what v2.115 shipped.
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


def scenario_the_trip_page_kept_everything_its_hero_carried():
    """The trip page's hero banner became a normal page header, so it matches
    every other page. A banner is also where things accumulate — the way back
    to the Trips grid especially, which `?tabs=none` can hide from the nav — so
    each control it carried is named here rather than trusted to a reread.

    BOTH templates are checked. `/trip` serves `trip_kiosk.html` whenever
    `kiosk=true`, and panel mode sets `kiosk=true` — so the panel renders the
    kiosk one, and a whole release of edits to `trip.html` was invisible there.
    Checking a single template is exactly how that went unnoticed."""
    for tpl in ('trip.html', 'trip_kiosk.html'):
        trip = open(os.path.join(TPL, tpl), encoding='utf-8').read()
        for needle, what in (
                ('href="trips"', 'the way back to the trips grid'),
                ('id="trip-title"', 'the trip name'),
                ('id="trip-location"', 'the location'),
                ('id="trip-dates"', 'the dates'),
                ('id="trip-countdown"', 'the countdown')):
            check(needle in trip, f"{tpl}: {what} was lost with the hero banner")
        check('panel-page-title' in trip,
              f"{tpl}: the trip name is not the page title")
        check('panel-page' in trip.replace('panel-page-title', ''),
              f"{tpl}: the trip page is not in a full-width frame")
        check("getElementById('panel-bg-image')" in trip,
              f"{tpl}: the trip's photograph is not the page background")
    check('html[data-panel] #bg-img' in SKIN,
          "the trip page's own background layer is not stood down on a panel, "
          "so it stacks with the shared one and washes the picture out")


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
              'config.html', 'settings.html',
              # Not a destination: the invite/reset landing page (auth arc S3)
              # is opened from a mail client by somebody with no session, and
              # carries no shelf, no nav and no identity on purpose. It cannot
              # line its title up with pages it is never seen beside.
              'set_password.html')]
    for path in pages:
        body = open(path, encoding='utf-8').read()
        name = os.path.basename(path)
        check('panel-page-title' in body, f"{name} has no page title")
        check('panel-page' in body.replace('panel-page-title', ''),
              f"{name}'s title is not in a .panel-page frame, so it will not "
              f"line up with the others")


def scenario_a_page_never_hides_its_own_name_on_a_panel():
    """Reported from the wall: the schedule's title and controls appeared for a
    split second and then vanished.

    Two faults in one line. The page hid `#page-header` — which carries the
    TITLE — whenever it was read-only, and panel mode sets kiosk=true. That
    predates the one-title-per-page convention (v2.117.0) and had been quietly
    deleting the page's name on every panel since. On a panel the heading is
    the only thing on screen saying which room you are in: the wordmark is gone
    and the shelf is icons.

    And it did it from a DOMContentLoaded handler, so the controls painted
    first and disappeared a frame later. A display surface is known in the
    HEAD — `html[data-display]` — for exactly the reason the theme is.
    """
    import glob
    for path in glob.glob(os.path.join(TPL, '*.html')):
        body = open(path, encoding='utf-8').read()
        name = os.path.basename(path)
        for needle in ("getElementById('page-header')",
                       'getElementById("page-header")'):
            at = body.find(needle)
            if at == -1:
                continue
            check(HIDDEN not in body[at:at + 140],
                  f"{name} hides its own page header, and the page title lives "
                  f"inside it — a panel page with no name is a room with no "
                  f"door sign")

    check('data-display' in THEME,
          "the head no longer marks a display surface, so pages are back to "
          "hiding their controls after the first paint")
    check('html[data-display] #header-buttons' in THEME,
          "the controls are not hidden before paint, which is the flash that "
          "was reported")
    # All three, or an HA card (?kiosk=true) and a read-only embed keep the
    # flash the panel just lost.
    head = THEME[THEME.index('data-display') - 400:THEME.index('data-display') + 200]
    for param in ('panel', 'kiosk', 'readonly'):
        check(param in head,
              f"?{param} does not mark a display surface, so it still flashes")


def scenario_ink_on_a_photograph_is_not_page_ink():
    """Reported from the wall in light mode, twice.

    First: the trip captions were hard to read. The skin maps Tailwind greys to
    the panel's ink, which is right for text on a SURFACE and wrong for text on
    a PICTURE — the scrim stayed dark while the ink followed the theme and went
    dark with it.

    Then, having fixed that by forcing the caption white: the blocks felt like
    they had not been themed at all. A dark scrim is a dark surface however
    light the room is, so the meals and trips blocks read as holes in a light
    page. Light mode LIGHTENS the picture now — white band, dark ink — and the
    block becomes paper laid on the photograph like every other card.

    One token pair drives all three places that put text on a picture (the
    trips grid, the meals week strip, the board's mosaics). They arrived with
    three separate gradients and three separate whites, which is why the first
    fix only reached one of them.
    """
    for token in ('--photo-scrim', '--photo-ink', '--photo-shadow'):
        check(SKIN.count(token) >= 3,
              f"{token} is not defined for dark, light AND auto — a theme "
              f"without it falls back to the other one's scrim")
    light = SKIN[SKIN.index('html[data-panel-theme="light"] {'):]
    light = light[:light.index('}')]
    check('rgb(255 255 255 / .96)' in light,
          "the light scrim is not near-opaque at the text, so dark ink lands "
          "on whatever the photograph happens to be doing")
    check('--photo-ink: #0f172a' in light,
          "light mode still writes white on its own white band")

    check('html[data-panel] .photo-scrim { background: var(--photo-scrim)' in SKIN,
          "the shared scrim class is gone, so each page is back to its own")
    check('.trip-card::before { background: var(--photo-scrim)' in SKIN,
          "the trip cards no longer follow the shared scrim")
    for cls in ('.board-ink', '.board-ink-dim', '.board-shadow'):
        check(f'html[data-panel] {cls}' in SKIN,
              f"{cls} (the meals week strip) is not themed, so it keeps its "
              f"hardcoded white on a white band")

    # Every place that paints a caption over a picture has to carry the class,
    # or it is themed in one place and not the others — which is exactly the
    # state this replaced.
    import glob
    for name in ('home.html', 'shopping.html'):
        body = tpl_source.read(name)
        check('photo-scrim' in body,
              f"{name} paints a caption over a photograph without the shared "
              f"scrim class")

    # Include-inlined: the chip moved into components/shopping_lists.html so
    # the `shopping_staples` card draws the same one the page does.
    shopping = tpl_source.read('components/shopping_lists.html')
    chip = shopping[shopping.index('outOf(s.name)'):]
    chip = chip[:chip.index('</button>')]
    check('bg-gray-800' in chip,
          "the cart chips have no surface, so on a panel they are an outline "
          "and a word on a photograph")


def scenario_no_page_title_carries_an_emoji():
    """Three of eleven had one, which is worse than all or none: the icon
    shifts the first letter right, so those titles did not line up with the
    rest down the left edge — the exact thing the shared title class exists to
    guarantee. The shelf already carries an icon for every destination."""
    import glob, re
    emoji = re.compile('[🀀-🫿←-⇿☀-➿]')
    for path in glob.glob(os.path.join(TPL, '*.html')):
        body = open(path, encoding='utf-8').read()
        for title in re.findall(r'class="panel-page-title"[^>]*>([^<]*)<', body):
            check(not emoji.search(title),
                  f"{os.path.basename(path)}: page title {title.strip()!r} "
                  f"carries an emoji, so it does not line up with the others")


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
    # A surface, not a wrapper — but a surface made of OPACITY, not of blur.
    # The blur came off every mapped tier for the Raspberry Pi's sake (see
    # scenario_the_grey_mapping_never_applies_a_filter), so the token is the
    # only thing keeping these readable over a photograph.
    check('--panel-surface-1' in card and 'transparent' not in card,
          "bare bg-gray-900 is no longer a surface — the schedule's driver "
          "columns and the dashboard's sidebar are cards, not page wrappers")


def scenario_the_panel_brings_its_own_emoji():
    """Reported from the Raspberry Pi on the wall: the emoji in the tiles do
    not render. Nothing in the app was wrong — Raspberry Pi OS ships no colour
    emoji font, so every 🚗 🍽️ ⭐ in the board, the shelf and the kid digests
    came out as a tofu box. A phone and a laptop have one built in, which is
    why it only ever showed up on the panel.

    Two things have to be true. The font has to be REQUESTED, and the family
    has to be in the stack — and the shared Tailwind config overrides
    `fontFamily.sans` with a stack starting at Inter, which is what dropped
    the three emoji families Tailwind's own default ends with. That override is
    the trap a new page will fall into again, so the fix lives here, centrally,
    and this guards it.

    The font is vendored now (static/vendor/fonts/emoji) rather than fetched
    from Google, and renamed to "Chauffeur Emoji" on the way in — see
    tests/test_tailwind_build.py for why the name matters."""
    check('vendor/fonts/emoji/emoji.css' in SKIN,
          "the panel no longer asks for an emoji font — on a device with none "
          "installed, every emoji on the board is a tofu box")
    # Only on a display surface: a phone with a perfectly good emoji font of
    # its own should not download two megabytes of this one.
    gate = SKIN[:SKIN.index('vendor/fonts/emoji/emoji.css')]
    check("query_params.get('panel')" in gate and "query_params.get('kiosk')" in gate,
          "the emoji font is fetched for every browser, not just the panel")

    for rule in ('html[data-display] body', 'html[data-display] .font-mono'):
        block = SKIN[SKIN.index(rule):]
        block = block[:block.index('}')]
        check('"Noto Color Emoji"' in block and '"Chauffeur Emoji"' in block,
              f"`{rule}` no longer names both the system emoji family and the "
              "vendored one, so the font is either never used or downloaded "
              "by devices that already have their own")


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
    """A board's picture is a field ON THE BOARD, and this map is built from
    the boards.

    It used to be built from a separate `panel_page_backgrounds` setting with
    its own editor field, which is how a household ended up with two settings
    for one thing — and the one on the board, the one that looked
    authoritative, was the dead one. A custom board was not even in this map
    (the old build filtered to nav slugs), so on a wall it silently fell back
    to the household default.
    """
    from services import home_board
    got = home_board.backgrounds({
        'panel_background': 'mountains at dusk',
        'panel_pages': [
            {'slug': 'home', 'name': 'Home', 'v': 5, 'widgets': []},
            {'slug': 'garage', 'name': 'Garage', 'v': 5, 'widgets': [],
             'background': 'empty highway at dawn'},
            {'slug': 'hallway', 'name': 'Hallway', 'v': 5, 'widgets': [],
             'background': 'the sea'},
            {'slug': 'landing', 'name': 'Landing', 'v': 5, 'widgets': [],
             'background': '   '},
        ]})
    check(got['default'].startswith('api/unsplash/background?query=mountains'),
          "the default picture is gone")
    # Boards the household OWNS. A stored page under a shipped slug is ignored
    # entirely since v2.229.0 — a shipped board's picture is authored with the
    # board — so the boards here are their own, not `schedule` and `map`.
    check('highway' in got['garage'], "a page's own picture is not resolved")
    check('sea' in got.get('hallway', ''),
          "a board the household made is not in the map, so a wall showing it "
          "falls back to the household default")
    check('landing' not in got, "a blank entry is treated as a picture")
    check('home' not in got, "a board with no picture is claiming one")


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


def scenario_the_server_can_tap_the_panel_on_the_shoulder():
    """A wall panel used to run last week's frontend until somebody touched
    it: nothing reloaded on an add-on rebuild, layout edits from another
    device landed on the next manual reload, and data changes waited out the
    60s poll. The panel now subscribes to the same SSE stream as the
    dashboard/PWA, with three contracts pinned here:
      hello:<boot_id> on connect (a changed id after reconnect = restart ->
      reload), `profile` on panel_* settings saves (-> reload), and `update`
      re-announced as a chf-server-update DOM event each page consumes."""
    check("EventSource(apiBase + 'api/stream')" in NAV
          and "hello:" in NAV and "chf-server-update" in NAV,
          "nav.html no longer subscribes the panel to the server stream")
    check("window.location.reload()" in NAV,
          "a restart or profile change must reload the panel outright")
    src = open(os.path.join(os.path.dirname(TPL), 'main.py'), encoding='utf-8').read()
    check('BOOT_ID' in src and 'data: hello:{BOOT_ID}' in src,
          "the stream must say hello with the process boot id")
    check('LAST_PROFILE_TIME' in src and "data: profile" in src
          and "k.startswith('panel_')" in src,
          "panel_* settings saves must emit the profile event")
    home = tpl_source.read('home.html')
    check("chf-server-update" in home,
          "the board must repaint on the push, not only on the 60s poll")
    check("HeroCard.html(ssNext, { compact: true })" in NAV
          and NAV.count('chf-server-update') >= 2,
          "the screensaver hero must also listen for the push")

def scenario_a_vendored_grid_is_themed_for_the_panel_too():
    """Reported off a light wall: "can you tell what month the calendar is
    showing? Me neither." FullCalendar's chrome is styled by the component in
    hardcoded near-white — right for the dark page it was written on — and the
    component carried a `body.ha-theme` block that remapped it for Home
    Assistant and NOTHING for the panel skin. Panel mode deliberately runs no
    HA theming, so on a board in light mode the month title, the weekday
    headers and the day numbers were white on paper.

    The lesson generalises past this grid: a VENDORED widget's chrome has to be
    restated for every theme this app has, because it cannot be written in the
    tokens it has never heard of.
    """
    comp = tpl_source.read('components/family_calendar.html')
    for sel in ('.fc .fc-toolbar-title', '.fc-daygrid-day-number',
                '.fc-col-header-cell-cushion'):
        check(f'html[data-panel] {sel}' in comp,
              f"{sel} has no panel-skin colour, so it keeps the near-white it "
              f"was written in and vanishes on a light wall")
    # Written in the SKIN's tokens, so one block serves both panel themes —
    # a hardcoded dark-mode colour here would just move the bug to light.
    block = comp[comp.index('html[data-panel] .fc .fc-toolbar-title'):]
    block = block[:block.index('.cal-host')]
    check('var(--panel-fg)' in block and 'var(--panel-line)' in block,
          "the panel calendar rules are hardcoded rather than written in the "
          "skin's variables, so they cannot follow a theme flip")
    for hard in ('#f8fafc', '#cbd5e1', 'rgba(255, 255, 255'):
        check(hard not in block,
              f"a panel calendar rule hardcodes {hard} instead of a token")
    # And the buttons, which are how you change month at all.
    check('html[data-panel] .fc .fc-button-primary' in comp,
          "the calendar's own toolbar buttons are unthemed on a panel")


def scenario_nobody_falls_between_the_two_lists_on_the_identity_screen():
    """Reported from the household: three people missing from Select Family
    Member, with no relation to who had an email or an account.

    The screen draws the DRIVERS, then the members who are not one of them.
    `driversData` drops `is_disabled` rows, and the second list said
    `!m.driver_id` — so a member linked to a disabled driver had no driver card
    AND was excluded from the member list for having a `driver_id`. They were
    on neither list and could not sign in as themselves at all.

    `is_disabled` is a SCHEDULING fact — out of the solver, off the rota — and
    it had quietly become an identity one. The test is therefore "is this
    person already drawn above?", never "do they have a driver_id".

    The same mistake sat in the restore path, so even a member who could find
    themselves was bounced back to this screen on the next load.
    """
    app = tpl_source.read('app.html')
    check('drawnDriverIds' in app,
          "the identity screen still splits on driver_id, so a member whose "
          "driver is disabled appears on neither list")
    fn = app[app.index('function showDriverSelection()'):]
    fn = fn[:fn.index('let isNotifOpen')]
    check('!drawnDriverIds.has(m.driver_id)' in fn,
          "the passenger list does not pick up members whose driver row is "
          "gone or disabled")
    restore = app[app.index('const restoredPassenger'):]
    restore = restore[:restore.index(';')]
    check('driversData.some' in restore,
          "the restore path still calls a disabled driver's member a driver, "
          "so they are sent back to the picker on every load")


def scenario_the_agent_button_is_not_offered_before_anybody_has_said_who_they_are():
    """Argyle answers AS somebody. A chat button floating over the identity
    picker is a button that cannot work, and it was there because the rule
    lived inline in `applyViewVisibility` — which that screen never calls.

    One rule, one function, asked of the SCREEN rather than of
    `selectedMemberId`: that id survives in localStorage and can still name
    somebody the app just failed to restore, which is precisely the state that
    lands on the picker.
    """
    app = tpl_source.read('app.html')
    check('function updateAgentFab()' in app,
          "the FAB's visibility is decided inline, so any screen that does "
          "not run that code keeps whatever the last one left")
    fn = app[app.index('function updateAgentFab()'):]
    fn = fn[:fn.index('function updateTabBar')]
    check("classList.contains('hidden')" in fn,
          "the FAB rule trusts selectedMemberId, which outlives a failed "
          "restore — the exact case that shows the picker")
    picker = app[app.index('function showDriverSelection()'):]
    picker = picker[:picker.index('driver-name')]
    check('updateAgentFab()' in picker,
          "the identity screen never asks for a FAB decision, so the chat "
          "button floats over Select Family Member")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} panel-chrome scenarios passed")
