"""Shared CSS/canvas palette and mounted texture-cache regression checks (no browser).

Run from chauffeur/: python tests/test_twin_palette_js.py
"""
import sys

from twin_live_node_rig import run

DRIVER = r"""
import {readdirSync} from 'node:fs';
const palette = await import(file('static/twin/palette.js'));
const {markerTexture, markerState} = await import(file('static/twin/live/markers.js'));
const checks = [], check = (name, fn) => checks.push([name, fn]);
const draw = (kind, look, color, count = null) => {
  const texture = markerTexture(kind, look, count, color);
  const log = texture.image.__log; texture.dispose(); return log;
};
const disc = log => log.find(row => row[0] === 'fill')[1].fillStyle;
const ring = log => log.find(row => row[0] === 'stroke' && row[2].some(p => p[0] === 'A' && p[3] === 42));

check('palette_matches_both_page_roots', () => {
  const tokens = Object.entries(palette).filter(([key, value]) => key.startsWith('twin') && typeof value === 'string');
  assert.equal(tokens.length, 21);
  for (const template of ['house_twin.html', 'house_editor.html']) {
    const source = readFileSync(root + '/templates/' + template, 'utf8');
    const css = source.match(/:root\s*\{([^}]+)\}/)[1];
    const properties = Object.fromEntries([...css.matchAll(/--(twin\w+)\s*:\s*([^;]+);/g)].map(m => [m[1], m[2].trim()]));
    assert.deepEqual(properties, Object.fromEntries(tokens), template);
  }
  assert.equal(palette.twinGlass, 'rgba(17,19,24,.62)');
  assert.equal(palette.twinGlassStrong, 'rgba(17,19,24,.82)');
  assert.equal(palette.twinText, '#f4f5f7');
  assert.equal(palette.twinTextDim, '#a3a9b6');
});

check('old_parchment_and_brown_chips_are_gone', () => {
  // Old chrome/marker colours, including every brown chip alpha and sepia ink.
  // Sun/kelvin/material colours and the approved energy hues are domain data.
  const forbidden = ['#e3d3ab', '#f0e6cf', '#1c1710', '#c9bb98', '#2a2117', '#0d0b08',
    '#363b43', '#686e77', '#edaa48', 'rgba(28,23,16,.82)', 'rgba(28,23,16,.9)',
    'rgba(28,23,16,.94)', 'rgba(28,23,16,.98)', 'rgba(54,43,29,.94)',
    'rgba(227,211,171,.45)', 'rgba(227,211,171,.2)', 'rgba(227,211,171,.08)',
    'rgba(227,211,171,.28)', 'rgba(227,211,171,.16)', '#d6bfa5', '#e9c49a',
    '#fcd5a5', '#fde09d', '#f3b183', '#facc62', '#fdba74', '#f7b6a0'];
  const walk = dir => readdirSync(dir, {withFileTypes:true}).flatMap(entry =>
    entry.isDirectory() ? walk(dir + '/' + entry.name) : [dir + '/' + entry.name]);
  for (const path of [...walk(root + '/static/twin'), ...['house_twin.html', 'house_editor.html'].map(p => root + '/templates/' + p)]) {
    const source = readFileSync(path, 'utf8').toLowerCase().replace(/\s+/g, '');
    for (const old of forbidden) assert.ok(!source.includes(old), path + ': ' + old);
  }
});

check('on_light_and_fan_draw_in_their_kind_colours', () => {
  assert.equal(disc(draw('light', 'on')), '#facc15');
  assert.equal(disc(draw('fan', 'on')), '#22d3ee');
  assert.equal(draw('light', 'on').at(-1)[1].strokeStyle, '#111318');
  for (const kind of ['switch', 'outlet']) assert.equal(disc(draw(kind, 'on')), '#22d3ee');
});

check('off_and_unavailable_have_glass_and_distinct_glyphs', () => {
  const off = draw('light', 'off'), unavailable = draw('light', 'unavailable');
  assert.equal(disc(off), 'rgba(17,19,24,.78)');
  assert.equal(ring(off)[1].strokeStyle, 'rgba(255,255,255,.22)');
  assert.equal(off.at(-1)[1].strokeStyle, '#f4f5f7');
  assert.equal(disc(unavailable), 'rgba(17,19,24,.5)');
  assert.equal(ring(unavailable), undefined);
  assert.equal(unavailable.at(-1)[1].strokeStyle, '#6b7280');
});

check('attention_precedes_kind_colour_and_counts_use_contrasting_ink', () => {
  assert.equal(markerState('lock', 'locked').look, 'off');
  for (const [kind, state] of [['lock','unlocked'], ['garage','open']]) {
    const row = markerState(kind, state), log = draw(kind, row.look, row.color);
    assert.equal(row.look, 'attention');
    assert.equal(disc(log), '#f59e0b');
    assert.equal(ring(log)[1].strokeStyle, '#fde68a');
    assert.equal(log.at(-1)[1].strokeStyle, '#111318');
  }
  const count = draw('room', 'on', undefined, 3);
  assert.equal(disc(count), '#e5e7eb');
  assert.equal(count.at(-1)[0], 'fillText');
  assert.equal(count.at(-1)[1].fillStyle, '#111318');
});

check('kind_and_climate_colours_follow_confirmed_state', () => {
  for (const kind of ['media', 'blinds', 'garage', 'cover', 'sensor', 'camera', 'other']) {
    const expected = kind === 'media' ? '#a78bfa' : ['blinds','garage','cover'].includes(kind) ? '#34d399' : '#e5e7eb';
    assert.equal(palette.markerOnColor(kind), expected, kind);
  }
  const color = (state, attributes = {}) => markerState('climate', state, attributes).color;
  assert.equal(color('heat'), '#fb923c');
  assert.equal(color('cool'), '#60a5fa');
  assert.equal(color('heat_cool'), '#a78bfa');
  assert.equal(color('auto'), '#a78bfa');
  assert.equal(color('auto', {hvac_action:'heating'}), '#fb923c');
  assert.equal(color('heat_cool', {hvac_action:'cooling'}), '#60a5fa');
  assert.equal(color('dry'), '#fb923c');
  assert.equal(markerState('light', 'on', {rgb_color:[0,0,255]}).color, '#facc15', 'no new per-light marker tinting');
  assert.equal(palette.markerInk('#000000'), '#f4f5f7');
});

check('mounted_climate_reuses_textures_and_material_across_colour_changes', async () => {
  const t = await rig({devices:[{device_id:'hvac',name:'HVAC',kind:'climate',entity_id:'climate.hvac',state:'auto',
    attributes:{hvac_action:'heating'}}]});
  try {
    const sprite = t.sprite('hvac'), material = sprite.material, heat = material.map;
    assert.equal(disc(heat.image.__log), '#fb923c');
    t.states['climate.hvac'].attributes.hvac_action = 'cooling'; await t.live.refresh();
    const cool = material.map;
    assert.notEqual(cool, heat); assert.equal(disc(cool.image.__log), '#60a5fa');
    t.states['climate.hvac'].attributes.hvac_action = 'idle'; await t.live.refresh();
    const auto = material.map;
    assert.notEqual(auto, cool); assert.equal(disc(auto.image.__log), '#a78bfa');
    for (let i = 0; i < 4; i++) {
      t.states['climate.hvac'].attributes.hvac_action = 'heating'; await t.live.refresh();
      assert.equal(material.map, heat);
      t.states['climate.hvac'].attributes.hvac_action = 'cooling'; await t.live.refresh();
      assert.equal(material.map, cool);
      t.live.draw(); assert.equal(t.sprite('hvac'), sprite); assert.equal(sprite.material, material);
    }
    let disposed = 0;
    for (const texture of [heat,cool,auto]) texture.addEventListener('dispose', () => disposed++);
    t.live.stop(); assert.equal(disposed, 3, 'cache owns disposal');
  } finally {t.cleanup();}
});

let passed = 0;
for (const [name, fn] of checks) {
  try {await fn(); passed++; console.log('  ok   ' + name);}
  catch (error) {console.error('  FAIL ' + name, error);}
}
assert.deepEqual(domErrors, []); assert.deepEqual(escaped, []);
console.log(`${passed}/${checks.length} palette checks passed`);
process.exit(passed === checks.length ? 0 : 1);
"""

if __name__ == '__main__':
    sys.exit(run(DRIVER, prefix='chauffeur_palette_', timeout=180))
