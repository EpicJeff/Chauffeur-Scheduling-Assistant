"""What the room's speaker says when someone taps the panel's mic (2026-11-10).

The user: '"Yes?" isn't the best. At the very least it should be something like
"How can I help?", but I would make it something a family can configure any way
they want.'

  - settings.panel_talk_greeting, household-wide, default "How can I help?",
    declared in settings_registry (group 'panel', Config › Boards, beside the
    other wall-panel settings) and edited in components/panel_settings.html;
  - POST /api/panel/talk sends it as start_message; blank or missing falls back
    to the default (Home Assistant refuses a start with no message); surrounding
    whitespace is trimmed and it is capped at 200 characters.

Run from chauffeur/ with HA_BASE_URL unset:
    python tests/test_panel_talk_greeting.py
"""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_panel_talk as base          # sets CHAUFFEUR_DATA_DIR before storage loads
from services import storage

DEFAULT = 'How can I help?'


class Greeting(unittest.TestCase):
    def setUp(self):
        base.PanelTalkServer.setUp(self)
        self.extra = {}
        real = storage.get_settings
        p = patch.object(storage, 'get_settings', side_effect=lambda: {**real(), **self.extra})
        p.start(); self.addCleanup(p.stop)

    def said(self, greeting=None, missing=False):
        from services import panel_talk
        panel_talk._last_start.clear()
        self.calls.clear()
        if not missing:
            self.extra['panel_talk_greeting'] = greeting
        r = self.client.post('/api/panel/talk', headers={'X-Device-Token': self.panel})
        self.assertEqual(r.status_code, 200, r.text)
        return self.calls[0][2]['start_message']

    def test_default_is_how_can_i_help(self):
        self.assertEqual(self.said(missing=True), DEFAULT)

    def test_family_greeting_is_said(self):
        self.assertEqual(self.said('What do you need, superstar?'), 'What do you need, superstar?')

    def test_blank_falls_back(self):
        for blank in ('', '   ', None):
            self.assertEqual(self.said(blank), DEFAULT, repr(blank))

    def test_trimmed_and_capped(self):
        self.assertEqual(self.said('  Hi there!  '), 'Hi there!')
        self.assertEqual(len(self.said('x' * 500)), 200)

    def test_declared_in_registry(self):
        from services import settings_registry
        entry = next(e for e in settings_registry.ENTRIES if e['key'] == 'panel_talk_greeting')
        self.assertEqual(entry['group'], 'panel')
        self.assertEqual(entry['anchor'], 'boards')

    def test_settings_model_default(self):
        from models.schemas import Settings
        self.assertEqual(Settings().panel_talk_greeting, DEFAULT)
        self.assertEqual(Settings(panel_talk_greeting='Hey!').panel_talk_greeting, 'Hey!')

    def test_edited_beside_the_other_panel_settings(self):
        tpl = HERE.parent / 'templates' / 'components'
        self.assertIn('x-model="panel.panel_talk_greeting"', (tpl / 'panel_settings.html').read_text(encoding='utf-8'))
        admin = (tpl / 'boards_admin.html').read_text(encoding='utf-8')
        self.assertIn('panel_talk_greeting', admin, 'part of the panel object savePanel posts')


if __name__ == '__main__':
    unittest.main(verbosity=2)
