"""The hand path for Argyle's style (Task 5 of docs/superpowers/plans/2026-11-11-argyle-style.md).

Every agent capability needs a hand path. A person changes their own style from
the PWA's Profile & appearance sheet ("How Argyle talks to you"); a parent sets
the household style, sees everyone whose style differs and resets them, in
Config › People beside what Argyle was taught.

CONTRACT (static/pwa_shell.js):
  async function pwaChooseArgyleStyle() -> Promise<string|null>
    GET apiBase + 'api/argyle/style/me'; promptChoice('How Argyle talks to you', '',
    [{value, label}] for household, plain, warm, playful, custom in that order, labels
    from the reply's `labels`); null -> return null with no POST. 'custom' ->
    promptInput('Your own style', 'For example: a cheerful pirate', {value: current custom});
    null or blank -> null with no POST. Then POST apiBase + 'api/argyle/style/me'
    {style, custom} (custom '' unless custom); a refusal -> showGlobalAlert. Returns
    the chosen style. pwaOpenProfile offers it as item id 'style', title
    'How Argyle talks to you'.

Run from chauffeur/ with HA_BASE_URL unset:  python tests/test_argyle_style_ui.py
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LABELS = {'plain': 'Plain and brief', 'warm': 'Warm', 'playful': 'Playful', 'custom': 'Custom',
          'household': 'Same as the household'}


def read(rel):
    with open(os.path.join(HERE, rel), encoding='utf-8') as fh:
        return fh.read()


def function_source(js, name):
    start = js.index(f'async function {name}(')
    nxt = re.search(r'\n(async )?function \w+\(', js[start + 10:])
    return js[start:start + 10 + nxt.start()] if nxt else js[start:]


HARNESS = r"""
const calls = [], alerts = [];
let choice = __CHOICE__, typed = __TYPED__, refuse = __REFUSE__;
const apiBase = '/api/hassio_ingress/tok/';
global.alert = global.confirm = global.prompt = () => { throw new Error('browser dialog'); };
function showGlobalAlert(m) { alerts.push(m); }
async function promptChoice(title, message, options) { calls.push(['choice', title, options]); return choice; }
async function promptInput(title, message, opts) { calls.push(['input', title, message, opts]); return typed; }
async function fetch(url, opts) {
  calls.push(['fetch', url, opts && opts.method || 'GET', opts && opts.body ? JSON.parse(opts.body) : null]);
  if (!opts || !opts.method || opts.method === 'GET')
    return {ok: true, status: 200, json: async () => ({status: 'success', style: 'household', custom: 'old words',
      household: {style: 'warm', custom: ''}, labels: __LABELS__})};
  return {ok: !refuse, status: refuse ? 400 : 200, json: async () => ({})};
}
__FN__
pwaChooseArgyleStyle().then(r => { console.log(JSON.stringify({r, calls, alerts})); })
  .catch(e => { console.log(JSON.stringify({error: String(e), calls, alerts})); });
"""


class PwaStyleSheet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which('node')
        cls.fn = function_source(read('static/pwa_shell.js'), 'pwaChooseArgyleStyle')

    def run_js(self, choice, typed=None, refuse=False):
        if not self.node:
            self.skipTest('node is not installed')
        src = (HARNESS.replace('__CHOICE__', json.dumps(choice)).replace('__TYPED__', json.dumps(typed))
               .replace('__REFUSE__', json.dumps(refuse)).replace('__LABELS__', json.dumps(LABELS))
               .replace('__FN__', self.fn))
        with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as fh:
            fh.write(src)
        try:
            out = subprocess.run([self.node, fh.name], capture_output=True, text=True, timeout=30)
        finally:
            os.unlink(fh.name)
        self.assertEqual(out.returncode, 0, out.stderr)
        result = json.loads(out.stdout.strip().splitlines()[-1])
        self.assertNotIn('error', result, result)
        return result

    def posts(self, result):
        return [c for c in result['calls'] if c[0] == 'fetch' and c[2] == 'POST']

    def test_choices_in_order_with_labels(self):
        result = self.run_js('playful')
        choice = next(c for c in result['calls'] if c[0] == 'choice')
        self.assertEqual(choice[1], 'How Argyle talks to you')
        self.assertEqual([(o['value'], o['label']) for o in choice[2]],
                         [(k, LABELS[k]) for k in ('household', 'plain', 'warm', 'playful', 'custom')])
        self.assertEqual(self.posts(result), [['fetch', '/api/hassio_ingress/tok/api/argyle/style/me', 'POST',
                                               {'style': 'playful', 'custom': ''}]])
        self.assertEqual(result['r'], 'playful')
        gets = [c for c in result['calls'] if c[0] == 'fetch' and c[2] == 'GET']
        self.assertEqual(gets[0][1], '/api/hassio_ingress/tok/api/argyle/style/me', 'apiBase, never root-relative')

    def test_custom_asks_for_words(self):
        result = self.run_js('custom', typed='a cheerful pirate')
        ask = next(c for c in result['calls'] if c[0] == 'input')
        self.assertEqual(ask[1:3], ['Your own style', 'For example: a cheerful pirate'])
        self.assertEqual(ask[3].get('value'), 'old words')
        self.assertEqual(self.posts(result)[0][3], {'style': 'custom', 'custom': 'a cheerful pirate'})

    def test_cancel_saves_nothing(self):
        for choice, typed in ((None, None), ('custom', None), ('custom', '   ')):
            result = self.run_js(choice, typed=typed)
            self.assertEqual(self.posts(result), [], (choice, typed))
            self.assertIsNone(result['r'])

    def test_a_refusal_says_so(self):
        result = self.run_js('plain', refuse=True)
        self.assertTrue(result['alerts'], 'a failed save must tell the person')

    def test_the_profile_sheet_offers_it(self):
        js = read('static/pwa_shell.js')
        body = js[js.index('function pwaOpenProfile('):]
        body = body[:body.index('\n}\n')]
        self.assertIn("action('style', 'How Argyle talks to you'", body)
        self.assertIn('pwaChooseArgyleStyle', body)


class ConfigPeopleBlock(unittest.TestCase):
    def test_the_parent_block(self):
        src = read('templates/config.html')
        self.assertIn('<details id="argyle-style"', src)
        block = src[src.index('<details id="argyle-style"'):]
        block = block[:block.index('</details>')]
        self.assertLess(src.index('<details id="argyle-memory"'), src.index('<details id="argyle-style"'),
                        'beside what Argyle was taught')
        self.assertIn("this.base() + 'api/argyle/style'", block)
        self.assertIn("'api/argyle/style/reset/'", block)
        self.assertNotIn("fetch('/api/", block, 'root-relative URLs leave the add-on under ingress')
        self.assertIn('promptConfirm(', block, 'a reset is confirmed')
        self.assertNotIn('confirm(', block.replace('promptConfirm(', ''), 'browser dialogs are banned')
        self.assertIn('argyle_style', block, 'the registry audit finds the setting on its page')
        for label in ('Plain and brief', 'Warm', 'Playful', 'Custom'):
            self.assertIn(label, block)

    def test_the_registry_finds_the_ui(self):
        from services import settings_registry
        missing = [m['key'] for m in settings_registry.audit_ui(os.path.join(HERE, 'templates'))['unreachable']
                   if m['key'].startswith('argyle_style')]
        self.assertEqual(missing, [])


if __name__ == '__main__':
    unittest.main()
