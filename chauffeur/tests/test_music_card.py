"""Music on the wall.

This card exists because of a change in what the app IS. For a year Chauffeur
was reached THROUGH Home Assistant, so Music Assistant was always one tab away
and a music surface here would have been a second drawing of something already
at hand. It is the other way round now — the family reaches the house through
Chauffeur, on wall panels and in the PWA — and on a panel there was no way to
play anything at all.

What this file defends:

  * the payload carries NO transport state. Board payloads are cached and
    polled a minute apart; a play/pause glyph that is twenty seconds stale is
    a control that lies about what it will do, and it is the first thing
    anybody presses.
  * the room binding is `announce_targets`, not a second one. A house that has
    already said "the kitchen means the kitchen display" should not have to
    say it again because this surface plays instead of talks.
  * no Home Assistant is a sentence, never a blank card or a vanished board.
  * the two music surfaces share their LOGIC. The PWA widget and this card
    look nothing alike on purpose, but "which speakers exist" and the artwork
    proxying underneath are the part nobody should re-derive — that is how the
    mixed-content rule ends up fixed in one of them and not the other.

Run from chauffeur/:  python tests/test_music_card.py
"""
import datetime
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('CHAUFFEUR_DATA_DIR',
                      tempfile.mkdtemp(prefix='chauffeur_music_'))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

import tpl_source  # noqa: E402
from services import home_board  # noqa: E402

NOW = datetime.datetime(2026, 9, 7, 17, 30)


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


class _HA:
    def __init__(self, available=True, states=None, areas=None):
        self._available = available
        self._states = states or []
        self._areas = areas if areas is not None else [
            {'id': 'kitchen', 'name': 'Kitchen',
             'entities': ['media_player.kitchen', 'assist_satellite.kitchen']},
            {'id': 'playroom', 'name': 'Playroom',
             'entities': ['media_player.playroom']},
        ]

    def get_area_map(self):
        return self._areas

    def resolve_area_id(self, spoken):
        return None

    def mode(self):
        return 'supervisor' if self._available else 'unconfigured'

    def is_available(self):
        return self._available

    def get_states(self, ttl=5):
        return self._states

    def get_state(self, entity_id):
        return next((s for s in self._states if s['entity_id'] == entity_id), None)


def _with_ha(stub, fn):
    """`home_board` imports ha_api INSIDE the functions that use it, so the
    stub goes into sys.modules; `announce` imports it at module level, so that
    binding is replaced too. Missing the second one is not a small omission —
    the room resolution lives there, and every room scenario would quietly
    resolve against a real, absent Home Assistant and answer None."""
    import services
    from services import announce
    real = sys.modules.get('services.ha_api')
    real_announce = announce.ha_api
    sys.modules['services.ha_api'] = stub
    setattr(services, 'ha_api', stub)
    announce.ha_api = stub
    try:
        return fn()
    finally:
        if real is not None:
            sys.modules['services.ha_api'] = real
            setattr(services, 'ha_api', real)
        announce.ha_api = real_announce


def _with_settings(settings, fn):
    from services import storage
    real = storage.get_settings
    storage.get_settings = lambda: settings
    try:
        return fn()
    finally:
        storage.get_settings = real


SPEAKERS = [
    {'entity_id': 'media_player.kitchen', 'state': 'idle',
     'attributes': {'friendly_name': 'Kitchen', 'mass_player_type': 'player'}},
    {'entity_id': 'media_player.playroom', 'state': 'playing',
     'attributes': {'friendly_name': 'Playroom', 'mass_player_type': 'player',
                    'media_title': 'Rasputin', 'volume_level': 0.4}},
    {'entity_id': 'assist_satellite.kitchen', 'state': 'idle',
     'attributes': {'friendly_name': 'Kitchen Argyle'}},
]


def _tile(config=None, states=SPEAKERS, available=True, settings=None):
    stub = _HA(available=available, states=states)
    return _with_ha(stub, lambda: _with_settings(
        settings if settings is not None else {},
        lambda: home_board._tile_music(NOW, config=config or {})))


# --- degrading -------------------------------------------------------------

def scenario_no_home_assistant_at_all_means_no_card():
    """Property 1, the same rule that hides the shopping tile from a household
    that never made a list. The household without HA finds out at the PALETTE,
    where the card is offered disabled — not by adding one and wondering."""
    check(_tile(available=False) is None,
          "the music card drew something on an install with no Home Assistant")
    cat = _with_ha(_HA(available=False), home_board.catalog)
    music = next(w for w in cat['widgets'] if w['key'] == 'music')
    check(music.get('available') is False and music.get('requires'),
          f"the palette offers music without saying it needs HA: {music!r}")


def scenario_the_music_board_explains_itself_rather_than_vanishing():
    """A board that disappears is indistinguishable from one that broke. The
    map board already answers this way; this one says what it needs."""
    check('music' in home_board.REQUIRED_EMPTY,
          "the Music board has no sentence for a household with no HA, so it "
          "would read 'Nothing here yet.' — which names nothing to fix")
    said = home_board.REQUIRED_EMPTY['music']
    check('Home Assistant' in said and 'Music Assistant' in said,
          f"the sentence does not name what is missing: {said!r}")
    page = home_board.builtin_page('music', {})
    check(page and [w['type'] for w in page['widgets']] == ['heading', 'music'],
          f"the shipped Music board is not a heading over a music card: {page}")
    span = page['spans']['music']
    check(span.get('fill'), f"the music card does not fill its board: {span}")


def scenario_configured_but_quiet_says_so():
    """Set up and not answering — restarting, rebooted, off the network — is a
    different answer from not set up, and the card must not silently become
    the no-HA case and disappear off a wall that had it a minute ago."""
    out = _tile(available=True, states=[])
    # `ha_available()` is what a down HA fails, so drive it directly.
    stub = _HA(available=True, states=[])
    stub.is_available = lambda: False
    out = _with_ha(stub, lambda: _with_settings(
        {}, lambda: home_board._tile_music(NOW, config={})))
    check(out and out.get('empty') == 'Needs Home Assistant.',
          f"a quiet Home Assistant did not say so: {out}")


def scenario_a_house_with_no_speakers_is_a_real_state():
    """HA is there and answering, and there is simply nothing to play on. The
    card still draws — the browser is the one that says it, because the player
    list is the browser's to fetch — but the payload must not pretend."""
    out = _tile(states=[{'entity_id': 'light.kitchen', 'state': 'on',
                         'attributes': {'friendly_name': 'Kitchen'}}])
    check(out and out.get('player') == '',
          f"a house with no speakers resolved one anyway: {out}")
    body = tpl_source.read('components/board_tile_body.html')
    check('No speakers in Home Assistant.' in body,
          "nothing on the card says why it has no controls")


# --- the room binding ------------------------------------------------------

def scenario_the_room_is_the_one_announcements_already_pinned():
    """`announce_targets` records "when you mean this room, you mean THIS
    speaker". Asking a family to answer that twice — once for talking and
    once for playing — is how the two drift apart."""
    from services import announce
    area = {'id': 'kitchen', 'name': 'Kitchen',
            'entities': ['media_player.kitchen', 'media_player.playroom']}
    got = _with_ha(_HA(states=SPEAKERS), lambda: _with_settings(
        {'announce_targets': {'kitchen': 'media_player.playroom'}},
        lambda: announce.pick_music_player(area)))
    check(got == 'media_player.playroom',
          f"the room's pinned speaker was ignored: {got}")


def scenario_a_pinned_satellite_is_not_a_stereo():
    """The pin is shared with announce, and announce's best answer for a room
    is often a voice satellite — which is the room's Argyle, not something you
    put an album on. Sharing the pin must not mean inheriting that step."""
    from services import announce
    area = {'id': 'kitchen', 'name': 'Kitchen',
            'entities': ['assist_satellite.kitchen', 'media_player.kitchen']}
    got = _with_ha(_HA(states=SPEAKERS), lambda: _with_settings(
        {'announce_targets': {'kitchen': 'assist_satellite.kitchen'}},
        lambda: announce.pick_music_player(area)))
    check(got == 'media_player.kitchen',
          f"music tried to play into a voice satellite: {got}")


def scenario_a_room_nobody_recognises_is_named():
    """A room renamed in Home Assistant would otherwise look like a card that
    forgot its speaker, and nothing on the wall would lead anybody to the
    setting that is now wrong."""
    out = _tile({'room': 'Zzyzx'})
    check(out and 'Zzyzx' in (out.get('empty') or ''),
          f"an unknown room was swallowed instead of named: {out}")


def scenario_an_explicit_speaker_beats_the_room():
    """The pin on the CARD is the most specific thing anybody said."""
    out = _tile({'room': 'Kitchen', 'player': 'media_player.playroom'})
    check(out.get('player') == 'media_player.playroom',
          f"the card's own speaker lost to its room: {out}")


def scenario_with_no_room_the_card_opens_on_what_is_playing():
    """A panel nobody has bound to a room should open on the music that is
    already on, rather than on nothing."""
    out = _tile({})
    check(out.get('player') == 'media_player.playroom',
          f"the card did not follow the music that was already playing: {out}")


# --- the payload -----------------------------------------------------------

def scenario_the_payload_carries_no_transport_state():
    """THE decision in this card. A board payload is cached and polled a
    minute apart; a play/pause glyph that is twenty seconds stale is a control
    that lies about what it will do."""
    out = _tile({})
    leaked = [k for k in ('state', 'playing', 'media_title', 'media_artist',
                          'volume_level', 'entity_picture', 'players')
              if k in out]
    check(not leaked,
          f"transport state rode the cached board payload: {leaked}")
    tpl = tpl_source.read('home.html')
    check('syncMusic(' in tpl and 'haImageTick % 10' in tpl,
          "the card has no ten-second beat of its own, so it is as stale as "
          "the board it sits on")


def scenario_every_section_is_a_toggle_and_they_start_on():
    """The card conversion paradigm: zero-config equals the full surface."""
    out = _tile({})
    check(out['interactive'] is True,
          "a wall music card arrived that nobody can press")
    for key in ('art', 'picker', 'volume', 'search', 'favorites'):
        check(out['show'][key] is True, f"{key} is off by default")
    off = _tile({'interactive': False, 'show_search': False,
                 'show_favorites': False})
    check(off['interactive'] is False and off['show']['search'] is False
          and off['show']['favorites'] is False,
          f"the toggles do not turn anything off: {off}")


def scenario_the_speaker_picker_offers_only_players_music_can_reach():
    """An HA instance accumulates dozens of TVs and cast targets Music
    Assistant cannot play to. Offering them is offering a choice that fails
    later, at the point where somebody has already pressed play."""
    opts = _with_ha(_HA(states=SPEAKERS), home_board.ha_options)
    values = [r['value'] for r in opts['players']]
    check(values == ['media_player.kitchen', 'media_player.playroom'],
          f"the picker offers something other than the MA players: {values}")
    check('assist_satellite.kitchen' not in values,
          "a voice satellite is offered as a speaker to play music on")
    # And the degraded shape carries the key too — a picker reading an absent
    # key draws as nothing rather than as "no Home Assistant".
    down = _with_ha(_HA(available=False), home_board.ha_options)
    check('players' in down, "ha_options() drops 'players' when HA is down")


# --- the two surfaces ------------------------------------------------------

def scenario_the_two_music_surfaces_share_their_logic():
    """They look nothing alike on purpose — one is a phone control in fixed
    dark colours, the other is read across a kitchen in the wall's own theme.
    What they must not duplicate is everything underneath, because that is how
    a fix lands in one of them and not the other."""
    logic = open(os.path.join(ROOT, 'static', 'music_logic.js'),
                 encoding='utf-8').read()
    for name in ('artwork', 'players', 'command', 'search', 'favorites', 'play'):
        check(f'{name}(' in logic, f"music_logic.js has no {name}()")
    widget = tpl_source.read('components/music_widget.html')
    check('MusicLogic.' in widget,
          "the PWA widget still keeps its own copy of the logic")
    for endpoint in ('api/music/search', 'api/music/favorites', 'api/music/play',
                     'api/ha/image64'):
        check(endpoint not in widget,
              f"the widget still calls {endpoint} itself, so the shared layer "
              f"is only half true")
    board = tpl_source.read('home.html')
    check('MusicLogic.artwork' in board and 'MusicLogic.players' in board,
          "the board card does not use the shared logic")


def scenario_the_artwork_rule_survives_in_one_place():
    """Music Assistant serves cover art over plain http:// and Home Assistant's
    entity_picture is often a relative path. On an https page the first is
    mixed content that iOS blocks SILENTLY, and the second resolves against
    the wrong origin. Both go through the add-on's proxy."""
    logic = open(os.path.join(ROOT, 'static', 'music_logic.js'),
                 encoding='utf-8').read()
    fn = logic[logic.index('artwork(url, opts)'):]
    fn = fn[:fn.index('imageOf(')]
    check("startsWith('https://')" in fn,
          "the artwork rule no longer lets a real https URL through directly")
    check('api/ha/image64/' in fn,
          "the proxy is gone from the artwork rule, so iOS gets blank covers")


# --- the hand path ---------------------------------------------------------

def scenario_music_is_a_destination_a_wall_can_reach():
    """The card is only half of it: a panel needs a way TO the music without
    somebody editing a board first."""
    check('music' in home_board.NAV_SLUGS,
          "music is not on the shelf, so a wall panel cannot reach it")
    check('music' in home_board.DEFAULT_TABS,
          "music is not on the default shelf")
    check('music' in home_board.BUILTIN_PAGES,
          "the Music destination has no shipped board")
    nav = tpl_source.read('nav.html')
    check("'slug': 'music'" in nav, "the shelf has no Music button")
    src = open(os.path.join(ROOT, 'main.py'), encoding='utf-8').read()
    check('@app.get("/music")' in src, "there is no /music route")


def scenario_the_card_is_drawn_and_has_no_door():
    """Interactive content cannot ALSO be a link to a page, or every tap
    navigates out from under the thing it just opened — and here there is
    nowhere for a door to lead anyway, because /music IS this board."""
    tpl = tpl_source.read('home.html')
    decl = tpl.index('PAGELESS: [')
    check("'music'" in tpl[decl:decl + 200],
          "the music card is a door to a page that is itself")
    decl = tpl.index('DRAWN_TILES:')
    check("'music'" in tpl[decl:decl + 200],
          "the music card is measured to its content, so the tile jumps when "
          "a search result list appears under somebody's thumb")


def scenario_a_display_only_card_still_says_where():
    """Off, the card is what is playing and nothing responds — but a wall
    showing a song with no room named is a wall that raises a question."""
    body = tpl_source.read('components/board_tile_body.html')
    frag = body[body.index("t.type === 'music'"):]
    frag = frag[:frag.index('ha_image')]
    check('t.data.room' in frag,
          "a display-only music card never names its room")
    check('t.data.interactive' in frag,
          "the card draws its controls whether or not it is interactive")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} music-card scenarios passed")
