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


def scenario_master_switch_beats_the_seconds():
    cfg = home_board.screensaver_config({'panel_screensaver_enabled': False,
                                         'panel_screensaver_idle_seconds': 600})
    check(cfg['idle_seconds'] == 0,
          "disabled must fold into idle_seconds=0 — clients only know one flag")
    cfg = home_board.screensaver_config({'panel_screensaver_enabled': True})
    check(cfg['idle_seconds'] == 600,
          "re-enabling gets the tuned/default seconds back, not zero")


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
    # Cancelling pointerdown does not cancel the CLICK synthesised at release,
    # and that click is hit-tested when it fires — so the overlay must outlive
    # the gesture as an invisible shield, not vanish on the press (which is
    # how the dismissal tap was navigating the panel).
    check("root.addEventListener('click', (e) => {" in NAV
          and "['pointerup', 'pointercancel'].forEach" in NAV,
          "the overlay must stay as a shield until the gesture's click has "
          "died on it — removing it on pointerdown lets the click fall "
          "through to the page")


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


# --- jsdom: the overlay actually appears, and a tap actually wakes it -------
# Same harness idea as test_board_render: the real rendered page in jsdom with
# a stubbed fetch. Skips (not fails) without node/jsdom. Image loading never
# fires events in jsdom, so the playlist is EMPTY here on purpose — the
# gradient+clock branch paints synchronously and is assertable.

_SS_HARNESS = r"""
const fs = require('fs');
const { JSDOM } = require('jsdom');
process.on('unhandledRejection', () => {});

const html = fs.readFileSync(process.argv[2], 'utf8')
  .replace(/<script src="[^"]*"[^>]*><\/script>/g, '')
  .replace(/<link href="https:[^"]*"[^>]*>/g, '');

const routes = {
  'api/panel/screensaver': { source: 'none', urls: [] },
  'api/panel/profile': { theme: 'dark', tabs: [], widgets: [], backgrounds: {},
    idle_seconds: 180,
    screensaver: { idle_seconds: 0.05, dwell_seconds: 5, source: 'photos' } },
  'api/home_board/catalog': { widgets: [], widget_defaults: [], tabs: [], tab_defaults: [] },
  'api/home_board': { hero: { remaining: 1, later: [], all_done: false, kids: [],
    next: { title: 'Soccer Practice', at: '4:00 PM', leave_label: '3:20 PM',
            driver: 'Mom', travel_mins: 26, color: '#ef4444',
            start: new Date(Date.now() + 45 * 60000).toISOString(),
            end: new Date(Date.now() + 105 * 60000).toISOString(),
            leave_at: new Date(Date.now() + 30 * 60000).toISOString() } },
    tiles: [] },
  'api/settings': {},
};

const dom = new JSDOM(html, {
  runScripts: 'dangerously', pretendToBeVisual: true,
  url: 'http://localhost/home?panel=true',
  beforeParse(w) {
    w.fetch = (u) => {
      const key = Object.keys(routes).find(k => String(u).includes(k));
      return Promise.resolve({ ok: !!key, text: () => Promise.resolve(''),
        json: () => Promise.resolve(key ? routes[key] : {}) });
    };
    w.showGlobalAlert = () => {};
    w.matchMedia = () => ({ matches: false, addEventListener() {} });
    w.EventSource = function () { return { addEventListener() {}, close() {} }; };
  }
});
const w = dom.window;

setTimeout(() => {
  const doc = w.document;
  const before = doc.getElementById('panel-screensaver');
  const out = { appeared: !!before };
  if (before) {
    out.clock = (doc.querySelector('#panel-ss-clock .ss-time') || {}).textContent || '';
    out.gradientPainted = [...before.querySelectorAll('.ss-layer')]
      .some(l => l.style.opacity === '1' && l.style.backgroundImage.includes('gradient'));
    const next = doc.getElementById('panel-ss-next');
    out.next = next && next.style.display !== 'none'
      ? { text: next.textContent.replace(/\s+/g, ' ').trim(),
          leaveBig: (next.querySelector('.text-4xl') || {}).textContent || '' }
      : null;
    before.dispatchEvent(new w.Event('pointerdown', { bubbles: true, cancelable: true }));
    // The press stops the slideshow but must NOT remove the overlay yet:
    // the browser's synthesised click is hit-tested at release, and an
    // already-removed overlay would let it land on the page below.
    const shield = doc.getElementById('panel-screensaver');
    out.slideshowStopped = w._chfSsActive === false;
    out.shieldStays = !!shield;
    out.shieldInvisible = !!shield && shield.style.opacity === '0';
    if (shield) {
      const click = new w.Event('click', { bubbles: true, cancelable: true });
      shield.dispatchEvent(click);
      out.clickSwallowed = click.defaultPrevented;
    }
    out.goneAfterClick = !doc.getElementById('panel-screensaver');
  }
  console.log(JSON.stringify(out));
  w.close();
  process.exit(0);
}, 600);
"""


def scenario_jsdom_overlay_appears_and_a_tap_wakes_it():
    import json
    import shutil
    import subprocess
    import tempfile
    import types
    node = shutil.which('node')
    if not node:
        print("  skip  node unavailable — the overlay was not exercised")
        return
    scratch = tempfile.mkdtemp(prefix='chf_ss_jsdom_')
    have = subprocess.run([node, '-e', "require.resolve('jsdom')"],
                          capture_output=True, text=True, cwd=scratch)
    if have.returncode != 0:
        print("  skip  jsdom not resolvable — the overlay was not exercised")
        return
    import main
    req = types.SimpleNamespace(url=types.SimpleNamespace(path='/home'),
                                query_params={'panel': 'true'})
    page = os.path.join(scratch, 'home.html')
    with open(page, 'w', encoding='utf-8') as f:
        f.write(main.templates.env.get_template('home.html').render(request=req))
    probe = os.path.join(scratch, 'harness.js')
    with open(probe, 'w', encoding='utf-8') as f:
        f.write(_SS_HARNESS)
    proc = subprocess.run([node, probe, page], capture_output=True, text=True,
                          cwd=scratch, timeout=120)
    check(proc.returncode == 0, f"the panel page threw:\n{proc.stderr[:1200]}")
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    check(out.get('appeared'),
          "the screensaver never appeared after the idle timeout")
    check(out.get('clock'),
          "the clock is empty — the idle face has no time on it")
    check(out.get('gradientPainted'),
          "an empty playlist should paint the gradient, not a black slab")
    check(out.get('slideshowStopped'),
          "the press did not stop the slideshow")
    check(out.get('shieldStays') and out.get('shieldInvisible'),
          "after the press the overlay must remain as an INVISIBLE shield — "
          f"removing it now is what let the tap click the page below: {out}")
    check(out.get('clickSwallowed'),
          "the gesture's click must die on the shield, not reach the page")
    check(out.get('goneAfterClick'),
          "once the click has been swallowed the shield must leave")
    nxt = out.get('next') or {}
    txt = nxt.get('text') or ''
    check('Soccer Practice' in txt,
          f"the Next up card is missing the upcoming event: {out.get('next')}")
    check(nxt.get('leaveBig') == '3:20 PM',
          f"the DEPARTURE must be the big number, as on the board: {nxt}")
    check('leave in 30 min' in txt and 'for 4:00 PM' in txt
          and '26 min drive' in txt and 'Mom' in txt,
          f"the card lost its pill/support-line/driver: {txt!r}")


HERO_COMPONENT = open(os.path.join(TPL, 'components', 'hero_card.html'),
                      encoding='utf-8').read()


def scenario_one_hero_renderer_not_a_smaller_copy():
    """v2.126.0's standing lesson, applied to the hero: the board and the
    screensaver corner must call the SAME function, or the copy drifts."""
    check('HeroCard.html' in HOME and 'heroCardHtml()' in HOME,
          "the board no longer renders its hero through the shared card")
    check("HeroCard.html(ssNext, { compact: true })" in NAV,
          "the screensaver no longer renders through the shared card")
    check('hero.next.title' not in HOME,
          "home.html grew its own hero markup back — that is the drift "
          "the shared renderer exists to prevent")
    check("countdown(next, now)" in HERO_COMPONENT
          and 'HeroCard.countdown' in HOME,
          "the pill arithmetic must live in the component, with the board "
          "delegating — two countdowns disagree within a week")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} screensaver scenarios passed")
