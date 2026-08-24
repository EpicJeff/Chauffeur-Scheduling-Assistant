"""A card's OWN visual editor, running here.

Every custom card worth configuring ships one:

    static async getConfigElement()

It is an ordinary Lit element that takes `hass` and `setConfig(config)` and
fires `config-changed`. What stopped it being hosted was never the editor — it
was what editors are BUILT OUT OF: `<ha-form>` driven by Home Assistant
SELECTORS, plus the entity and icon pickers, all of which live in HA's frontend
bundle. `static/ha_form.js` is those.

The bet worth stating: a selector schema is a DECLARATION, the same way a
built-in card's config is. `{selector: {entity: {domain: 'light'}}}` says "an
entity of this domain", not "draw this widget" — so honouring it is a real
implementation rather than an impersonation, and it draws in the panel's own
vocabulary.

The rule this file guards hardest: an UNKNOWN selector renders as an editable
raw value, NEVER as nothing. A form that silently omits the one option somebody
opened it to change is worse than one that shows them JSON.

Proven separately against the real mushroom 5.2.2 bundle, whose
`mushroom-lock-card-editor` draws 11 fields across six selector kinds through
this. The card here is a stand-in so the suite needs no 660 KB vendored.

Run from chauffeur/:  python tests/test_ha_form_runtime.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('CHAUFFEUR_DATA_DIR',
                      tempfile.mkdtemp(prefix='chauffeur_form_'))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from services import ha_card_convert  # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


PROBE = r"""
const { JSDOM } = require('jsdom');
const fs = require('fs');
const dom = new JSDOM('<!doctype html><body><div id="a"></div><div id="b"></div>',
                      { runScripts: 'outside-only', pretendToBeVisual: true });
const { window } = dom;
window.fetch = () => Promise.resolve({ ok: true, json: () => Promise.resolve({ path: 'M1,1' }) });
window.eval(fs.readFileSync(process.argv[2], 'utf8'));      // ha_form.js

// On demand since the borrowed-frontend arc — at page parse the shims would
// collide with HA's own definitions and kill the chunks mid-evaluation. The
// host calls this exactly when the runtime is not there to define the real
// ones; this probe IS that no-runtime wall.
window.ChauffeurHaForm.ensure();

window.ChauffeurHaForm.setEntities([
  { value: 'light.hall', label: 'Hall' },
  { value: 'sensor.power', label: 'Power' },
]);

// --- 1. A NATIVE schema, straight off the server.
const schema = JSON.parse(process.argv[3]);
const form = window.document.createElement('ha-form');
const seen = [];
form.addEventListener('value-changed', (e) => seen.push(e.detail.value));
window.document.getElementById('a').appendChild(form);
form.schema = schema;
form.data = { entity: 'sensor.power', min: 0 };

const sels = [...form.shadowRoot.querySelectorAll('ha-selector')];
const kinds = sels.map(s => Object.keys(s.selector || {})[0]);

// The value a field starts with has to be the one in the config, or the first
// edit silently wipes whatever it did not show.
const entityField = sels.find(s => Object.keys(s.selector)[0] === 'entity');
const startedWith = entityField && entityField.value;

// An edit emits the WHOLE object, which is what a card editor listens for.
const numberField = sels.find(s => Object.keys(s.selector)[0] === 'number');
numberField.dispatchEvent(new window.CustomEvent('value-changed',
  { detail: { value: 42 }, bubbles: true, composed: true }));

// --- 2. An UNKNOWN selector is shown, not dropped.
const odd = window.document.createElement('ha-form');
window.document.getElementById('b').appendChild(odd);
odd.schema = [{ name: 'tap_action', selector: { ui_action: {} } }];
odd.data = { tap_action: { action: 'toggle' } };
const oddSel = odd.shadowRoot.querySelector('ha-selector');
const oddText = oddSel.shadowRoot.querySelector('textarea');

console.log(JSON.stringify({
  kinds: kinds,
  startedWith: startedWith,
  emitted: seen,
  // Layout containers hold a nested schema over the SAME data object; missing
  // that is how a form quietly loses half its fields.
  grids: form.shadowRoot.querySelectorAll('.grid').length,
  unknownShown: !!oddText,
  unknownCarriesValue: oddText ? oddText.value.includes('toggle') : false,
  unknownExplains: oddSel.shadowRoot.textContent.includes('ui_action'),
}));
"""


def _run():
    node = shutil.which('node')
    if not node:
        return None
    # jsdom is a scratch dependency, not a repo one — the suite skips rather
    # than failing on a machine that has never installed it.
    probe = os.path.join(tempfile.mkdtemp(), 'probe.js')
    with open(probe, 'w', encoding='utf-8') as fh:
        fh.write(PROBE)
    schema = json.dumps(ha_card_convert.schema_for('gauge'))
    form_js = os.path.join(ROOT, 'static', 'ha_form.js')
    out = subprocess.run([node, probe, form_js, schema],
                         capture_output=True, text=True, timeout=90,
                         cwd=os.path.dirname(probe))
    if out.returncode != 0:
        if 'Cannot find module' in (out.stderr or ''):
            return None
        raise AssertionError(f"the form would not run:\n{out.stderr[-1500:]}")
    return json.loads(out.stdout.strip().splitlines()[-1])


def _skip():
    print('  skip  node or jsdom is not available')


def scenario_a_native_schema_draws_the_fields_it_declares():
    """The schema comes from the SERVER, declared beside the builder that reads
    those keys — so a form can never offer a field the drawing ignores."""
    got = _run()
    if got is None:
        return _skip()
    check('entity' in got['kinds'], f"the gauge's entity field is missing: {got['kinds']}")
    check(got['kinds'].count('number') >= 2,
          f"min and max did not both draw: {got['kinds']}")
    check(got['grids'] >= 1,
          "a `grid` layout item drew no container, which means its nested "
          "schema was dropped along with it")
    check(got['startedWith'] == 'sensor.power',
          f"a field opened without the value already in the config "
          f"({got['startedWith']!r}), so the first edit would wipe it")


def scenario_an_edit_emits_the_whole_config():
    """What HA's own ha-form does, and what every card editor is written
    against: it listens once and rebuilds its config from the object, rather
    than tracking fields."""
    got = _run()
    if got is None:
        return _skip()
    check(got['emitted'], "editing a field emitted nothing")
    last = got['emitted'][-1]
    # The first `number` field in the gauge schema is `min`.
    check(last.get('min') == 42, f"the edited field did not arrive: {last}")
    check(last.get('entity') == 'sensor.power',
          f"the fields nobody touched were dropped from the emitted config: {last}")


def scenario_an_unknown_selector_is_shown_not_dropped():
    """The rule that keeps this honest. `ui_action`, `target`, a selector
    invented next release — a form that silently omits the one option somebody
    opened it to change is worse than one that shows them the raw value."""
    got = _run()
    if got is None:
        return _skip()
    check(got['unknownShown'],
          "an unknown selector rendered nothing at all, so the option it "
          "carries is unreachable and invisible")
    check(got['unknownCarriesValue'],
          "the raw field opened empty, which would erase the value on save")
    check(got['unknownExplains'],
          "nothing says WHY the field looks like that, so it reads as a bug")


def scenario_every_native_schema_only_names_keys_the_builder_reads():
    """A form offering a field the drawing ignores is a worse lie than no form.

    Checked against the converter's own source: every `name` in a schema has to
    appear in the module that honours it. This is the guard that fails when a
    card gains an option in HA and somebody adds it here without teaching the
    builder about it.
    """
    src = open(os.path.join(ROOT, 'services', 'ha_card_convert.py'),
               encoding='utf-8').read()
    # The declarations live in this file too, so they are cut OUT of the search
    # space rather than searched — otherwise every field would find itself.
    start = src.index('_SCHEMAS = {')
    end = src.index('GRID_SCHEMA = [')
    body = src[:start] + src[end:]
    unread = []
    for kind in ha_card_convert.editable_cards():
        for item in ha_card_convert.schema_for(kind) or []:
            names = ([item['name']] if item.get('name')
                     else [i['name'] for i in item.get('schema') or []
                           if i.get('name')])
            for name in names:
                if f"'{name}'" not in body:
                    unread.append(f'{kind}.{name}')
    check(not unread,
          "these editor fields name config keys no builder reads, so setting "
          "them would change nothing on screen: " + ', '.join(unread))


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} form-runtime scenarios passed")
