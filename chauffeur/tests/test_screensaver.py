"""The panel screensaver (home_board.screensaver_* + the nav.html overlay).

Three properties are load-bearing:

  1. The playlist NEVER escapes the media share. The subpath comes from
     settings and the serve URL from the network, so containment is checked
     with realpath at both ends, not trusted from either.
  2. Absent settings mean the defaults; an explicit 0 means off. Every stored
     settings dict predates this feature, so "absent = disabled" would ship a
     silently-off screensaver to every existing install.
  3. An empty source falls back (photos/media -> wallpaper -> nothing) rather
     than erroring: a wall panel that hits a 500 at 2am shows a browser error
     page until somebody notices.

Run from chauffeur/:  python tests/test_screensaver.py
"""
import os
import tempfile

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import home_board, storage


# --- config resolution ------------------------------------------------------

def scenario_absent_settings_mean_defaults_not_off():
    cfg = home_board.screensaver_config({})
    check(cfg['idle_seconds'] == 600,
          "an install that predates the screensaver should get the 600s default")
    check(cfg['dwell_seconds'] == 20, "default dwell is 20s")
    check(cfg['source'] == 'photos', "default source is the family's own Moments")


def scenario_explicit_zero_stays_off():
    cfg = home_board.screensaver_config({'panel_screensaver_idle_seconds': 0})
    check(cfg['idle_seconds'] == 0, "an explicit 0 is a real choice and stays off")


def scenario_garbage_settings_resolve_not_crash():
    cfg = home_board.screensaver_config({
        'panel_screensaver_idle_seconds': 'soon',
        'panel_screensaver_dwell_seconds': -5,
        'panel_screensaver_source': 'google_photos',
    })
    check(cfg['idle_seconds'] == 600, "unparseable idle falls back to default")
    check(cfg['dwell_seconds'] == 5, "dwell clamps to the 5s floor")
    check(cfg['source'] == 'photos', "unknown source resolves to photos")


def scenario_profile_carries_the_knobs_but_not_the_playlist():
    p = home_board.profile()
    check('screensaver' in p, "the panel profile carries the screensaver knobs")
    check('urls' not in p['screensaver'],
          "the playlist must NOT ride the profile — it is fetched at "
          "activation so a panel up for weeks shows this week's photos")


# --- media share listing ----------------------------------------------------

def _with_media_root(fn):
    old = home_board.MEDIA_SHARE_ROOT
    with tempfile.TemporaryDirectory() as root:
        home_board.MEDIA_SHARE_ROOT = root
        try:
            fn(root)
        finally:
            home_board.MEDIA_SHARE_ROOT = old


def scenario_media_listing_finds_images_and_only_images():
    def run(root):
        os.makedirs(os.path.join(root, 'shots'))
        for name in ('a.jpg', 'b.PNG', 'c.webp', 'notes.txt', 'clip.mp4', '.hidden.jpg'):
            open(os.path.join(root, 'shots', name), 'w').write('x')
        rels = home_board._media_share_images('shots')
        check(sorted(rels) == ['shots/a.jpg', 'shots/b.PNG', 'shots/c.webp'],
              f"images only, dotfiles skipped, case-insensitive ext: {rels}")
    _with_media_root(run)


def scenario_media_listing_never_escapes_the_share():
    def run(root):
        outside = os.path.join(os.path.dirname(root), 'outside_secret')
        os.makedirs(outside, exist_ok=True)
        open(os.path.join(outside, 'leak.jpg'), 'w').write('x')
        check(home_board._media_share_images('../' + os.path.basename(outside)) == [],
              "a subpath that resolves outside the share lists nothing")
        check(home_board._media_share_images('..') == [],
              "a bare .. lists nothing")
        check(home_board._media_share_images('nope/missing') == [],
              "a missing folder lists nothing rather than erroring")
    _with_media_root(run)


def scenario_serve_endpoint_rechecks_containment():
    """The URL is typeable by anyone on the LAN, so the serve path cannot
    trust that the playlist produced it."""
    import main
    from fastapi import HTTPException
    def run(root):
        open(os.path.join(root, 'ok.jpg'), 'w').write('x')
        resp = main.panel_media_image('ok.jpg')
        check(getattr(resp, 'path', '').endswith('ok.jpg'), "a real image serves")
        for evil in ('../ok.jpg', '..\\..\\etc\\passwd', 'ok.jpg/../../x.jpg'):
            try:
                main.panel_media_image(evil)
                check(False, f"traversal path {evil!r} was served")
            except HTTPException as e:
                check(e.status_code == 404, "traversal answers 404, not 500")
        try:
            main.panel_media_image('notes.txt')
            check(False, "a non-image extension was served")
        except HTTPException:
            check(True, "")
    _with_media_root(run)


# --- playlist sources -------------------------------------------------------

def scenario_empty_source_falls_back_to_wallpaper_then_nothing():
    def run(root):
        # media source, empty share, no wallpaper -> nothing (client shows
        # its gradient + clock)
        pl = home_board.screensaver_playlist({
            'panel_screensaver_source': 'media'})
        check(pl == {'source': 'none', 'urls': []},
              f"empty media + no wallpaper -> none: {pl}")
        # same, but a wallpaper exists -> the wallpaper IS the slideshow
        pl = home_board.screensaver_playlist({
            'panel_screensaver_source': 'media',
            'panel_background': 'mountains at dusk'})
        check(pl['source'] == 'background' and len(pl['urls']) == 1
              and 'unsplash' in pl['urls'][0],
              f"empty media + wallpaper -> the wallpaper slow-pans: {pl}")
    _with_media_root(run)


def scenario_media_playlist_urls_route_through_the_guarded_endpoint():
    def run(root):
        open(os.path.join(root, 'pic.jpg'), 'w').write('x')
        pl = home_board.screensaver_playlist({'panel_screensaver_source': 'media'})
        check(pl['urls'] == ['api/panel/media-image/pic.jpg'],
              f"media urls go through the serving endpoint: {pl['urls']}")
    _with_media_root(run)


def scenario_photos_playlist_is_moments_photos():
    ch = storage.get_or_create_event_channel('ev1', 'Game')
    storage.add_chat_message({'id': 'ssm1', 'channel_id': ch['id'],
                              'sender_member_id': 'm1', 'body': 'look!', 'ts': 1000.0,
                              'attachment': {'kind': 'photo', 'url': '/api/media/abc123'}})
    storage.add_chat_message({'id': 'ssm2', 'channel_id': ch['id'],
                              'sender_member_id': 'm1', 'body': 'plain text', 'ts': 1001.0})
    pl = home_board.screensaver_playlist({'panel_screensaver_source': 'photos'})
    check(pl['source'] == 'photos', "photos source resolves as photos")
    check(pl['urls'] == ['api/media/abc123'],
          f"the playlist is the moment photos, relative for ingress: {pl['urls']}")


# --- template contracts -----------------------------------------------------

TPL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'templates')
NAV = open(os.path.join(TPL, 'nav.html'), encoding='utf-8').read()
SKIN = open(os.path.join(TPL, 'panel_skin.html'), encoding='utf-8').read()
HOME = open(os.path.join(TPL, 'home.html'), encoding='utf-8').read()


def scenario_playlist_is_fetched_at_activation_not_page_load():
    check("fetch(apiBase + 'api/panel/screensaver')" in NAV,
          "the overlay no longer fetches a fresh playlist when it starts")
    start = NAV.index('const ssStart')
    check(NAV.index("fetch(apiBase + 'api/panel/screensaver')") > start,
          "the playlist fetch left ssStart — if it moved to page load, a "
          "panel up for weeks shows stale photos")


def scenario_idle_return_defers_to_the_screensaver():
    check('window._chfSsActive' in NAV and '_chfSsPendingHome' in NAV,
          "goHome no longer checks the screensaver — a mid-slideshow "
          "redirect tears the photos down for a page nobody is looking at")


def scenario_wake_tap_is_swallowed():
    check("addEventListener('pointerdown', (e) => {" in NAV
          and 'e.preventDefault(); e.stopPropagation(); ssStop();' in NAV,
          "the waking tap must dismiss, not press whatever was underneath")


def scenario_screensaver_covers_the_overlays():
    idx = SKIN.index('#panel-screensaver')
    block = SKIN[idx:idx + 400]
    check('z-index: 300' in block,
          "the screensaver sits under the hearth/moment overlays (z 200-220) "
          "— an idle popup would poke through the photos")


def scenario_settings_have_a_hand_path():
    for key in ('panel_screensaver_idle_seconds', 'panel_screensaver_source',
                'panel_screensaver_media_path', 'panel_screensaver_dwell_seconds'):
        check(key in HOME, f"{key} has no field in the panel-setup drawer")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} screensaver scenarios passed")
