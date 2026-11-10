"""A glow around the wall panel while its room's satellite is in a conversation (2026-11-10).

The user: "When the voice satellite associated with a wall panel is actively in a
conversation, can we have an effect show on the panel like the dynamic Siri
rainbow border?" Approved design ("Sounds great"):
  - shows for ANY conversation on the panel's room satellite (a tap or a wake word
    from across the room), fades when the satellite is idle again;
  - a soft flowing rainbow glow on all four edges; listening bright and flowing,
    processing a slower shimmer, responding a gentle pulse; static under
    prefers-reduced-motion; above everything including the screensaver, never
    blocking a tap (pointer-events none), never waking the screensaver;
  - the panel polls GET /api/panel/talk once a second while the page is visible;
    the server shares one fresh HA read per satellite per ~0.8 s across panels
    (a tap's busy check in POST still reads HA itself);
  - household switch settings.panel_talk_glow (default on), Config › Boards › The
    wall panel; GET /api/panel/talk now also returns {'glow': bool}.

Page contract, templates/components/control_center.html, ?panel=true only:
  window.chfPanelGlow.tick() -> Promise<bool>: one GET chfBase + 'api/panel/talk'
  (X-Device-Token); element #panel-talk-glow gets class 'glow-listening' /
  'glow-processing' / 'glow-responding' for those states and loses 'hidden';
  idle, unavailable, an error or glow false -> 'hidden' and no glow-* class.
  Returns whether polling should go on (false when the panel is not available).
  window.chfPanelGlow.start() begins the once-a-second loop.

Run from chauffeur/ with HA_BASE_URL unset:
    python tests/test_panel_glow.py
"""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_panel_talk as base          # sets CHAUFFEUR_DATA_DIR first
import test_control_grant_js as js
from services import storage, ha_api

SAT = base.KITCHEN_SAT


class GlowServer(unittest.TestCase):
    def setUp(self):
        base.PanelTalkServer.setUp(self)
        self.extra = {}
        real = storage.get_settings
        p = patch.object(storage, 'get_settings', side_effect=lambda: {**real(), **self.extra})
        p.start(); self.addCleanup(p.stop)
        from services import panel_talk
        getattr(panel_talk, '_fresh_cache', {}).clear()

    get = base.PanelTalkServer.get

    def counting(self, reads):
        real = ha_api.get_state_fresh

        def read(eid):
            reads.append(eid)
            return real(eid)
        return patch.object(ha_api, 'get_state_fresh', side_effect=read)

    def test_glow_on_by_default(self):
        self.assertIs(self.get().json()['glow'], True)

    def test_glow_off_switch(self):
        self.extra['panel_talk_glow'] = False
        self.assertIs(self.get().json()['glow'], False)

    def test_panels_share_one_fresh_read(self):
        reads = []
        with self.counting(reads):
            self.get()
            self.get()
        self.assertEqual(reads, [SAT], 'two polls inside the window cost one HA read')

    def test_shared_read_expires(self):
        from services import panel_talk
        reads = []
        with self.counting(reads):
            self.get()
            for key in list(panel_talk._fresh_cache):
                state, at = panel_talk._fresh_cache[key]
                panel_talk._fresh_cache[key] = (state, at - 5)
            self.get()
        self.assertEqual(len(reads), 2)

    def test_start_never_uses_the_shared_read(self):
        """A tap's busy check reads HA itself: a cached idle must not let a tap
        restart a live conversation."""
        self.get()                                   # caches idle
        self.fresh[SAT] = 'listening'
        r = self.client.post('/api/panel/talk', headers={'X-Device-Token': self.panel})
        self.assertEqual(r.status_code, 409)

    def test_declared_and_edited(self):
        from services import settings_registry
        from models.schemas import Settings
        entry = next(e for e in settings_registry.ENTRIES if e['key'] == 'panel_talk_glow')
        self.assertEqual((entry['group'], entry['anchor']), ('panel', 'boards'))
        self.assertIs(Settings().panel_talk_glow, True)
        tpl = HERE.parent / 'templates' / 'components'
        self.assertIn('x-model="panel.panel_talk_glow"', (tpl / 'panel_settings.html').read_text(encoding='utf-8'))
        self.assertIn('panel_talk_glow', (tpl / 'boards_admin.html').read_text(encoding='utf-8'))


def ok(state, glow=True, available=True):
    return js.ok({'available': available, 'state': state, 'glow': glow})


STEP = """{
    out.steps = out.steps || [];
    out.go = await window.chfPanelGlow.tick();
    const el = byId['panel-talk-glow'];
    out.steps.push([el.classList.contains('hidden'),
                    ['glow-listening', 'glow-processing', 'glow-responding'].filter(c => el.classList.contains(c))]);
}
"""   # a block of its own: STEP * 5 must not redeclare `el`


class GlowPage(unittest.TestCase):
    def run_page(self, scenario, responses):
        out = js.run_node(js.CC_HARNESS, {'base': js.BASE, 'blocks': js._cc_blocks(), 'scenario': scenario,
                                          'routes': [['api/panel/talk', responses]], 'choices': [], 'pins': []})
        self.assertNotIn('error', out, out.get('error'))
        self.assertEqual(out['forbidden'], [])
        return out

    def test_glow_follows_the_satellite(self):
        out = self.run_page(STEP * 5, [ok('idle'), ok('listening'), ok('processing'), ok('responding'), ok('idle')])
        self.assertEqual(out['steps'], [[True, []], [False, ['glow-listening']], [False, ['glow-processing']],
                                        [False, ['glow-responding']], [True, []]])
        call = [c for c in out['calls'] if 'api/panel/talk' in c['url']][0]
        self.assertEqual(call['url'], js.BASE + 'api/panel/talk')
        self.assertEqual(call['headers'].get('x-device-token'), 'dev-tok')

    def test_switched_off_never_glows(self):
        out = self.run_page(STEP, [ok('listening', glow=False)])
        self.assertEqual(out['steps'], [[True, []]])

    def test_unavailable_stops_the_loop(self):
        out = self.run_page(STEP, [ok(None, available=False)])
        self.assertEqual(out['steps'], [[True, []]])
        self.assertIs(out['go'], False)

    def test_network_error_hides_quietly(self):
        out = self.run_page(STEP, [{'throw': True}])
        self.assertEqual(out['steps'], [[True, []]])
        self.assertEqual(out['alerts'], [], 'a dropped poll is never an alert')

    def test_the_glow_never_blocks_a_tap_and_respects_reduced_motion(self):
        src = (HERE.parent / 'templates' / 'components' / 'control_center.html').read_text(encoding='utf-8')
        start = src.index('#panel-talk-glow')
        css = src[start:start + 4000]
        self.assertIn('pointer-events: none', css)
        self.assertIn('prefers-reduced-motion', src)


if __name__ == '__main__':
    unittest.main(verbosity=2)
