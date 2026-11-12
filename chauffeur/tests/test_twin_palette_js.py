"""Shared CSS/canvas palette and mounted texture-cache regression checks (no browser).

Run from chauffeur/: python tests/test_twin_palette_js.py
"""
import sys

from twin_live_node_rig import run

DRIVER = r"""
import {readdirSync} from 'node:fs';
const palette = await import(file('static/twin/palette.js'));
const {markerTexture, markerState, markerTextureCache, markerSprite} = await import(file('static/twin/live/markers.js'));
const checks = [], check = (name, fn) => checks.push([name, fn]);
const draw = (kind, look, color, count = null) => {
  const texture = markerTexture(kind, look, count, color);
  const log = texture.image.__log; texture.dispose(); return log;
};
const disc = log => log.find(row => row[0] === 'fill')[1].fillStyle;
const ring = log => log.find(row => row[0] === 'stroke' && row[2].some(p => p[0] === 'A' && p[3] === 42));
const stateDraw = (kind, state, attributes = {}, entity = '') => {
  const row = markerState(kind, state, attributes, entity);
  return draw(kind, row.look, row.color);
};

check('palette_matches_both_page_roots', () => {
  const tokens = Object.entries(palette).filter(([key, value]) => key.startsWith('twin') && typeof value === 'string');
  assert.equal(tokens.length, 24);
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

check('light_disc_uses_rgb_then_kelvin_then_warm_white_without_brightness_tinting', () => {
  const red = stateDraw('light', 'on', {rgb_color:[255,0,0], color_temp_kelvin:6500});
  assert.equal(disc(red), '#ff0000');
  assert.equal(disc(stateDraw('light', 'on', {rgb_color:[255,0,0], brightness:1})), '#ff0000');
  const warm = disc(stateDraw('light', 'on', {color_temp_kelvin:2700}));
  const cool = disc(stateDraw('light', 'on', {color_temp_kelvin:6500}));
  assert.equal(warm, '#ffa757'); assert.equal(cool, '#fffefa');
  assert.equal(disc(stateDraw('light', 'on', {color_temp:1e6/2700})), warm);
  assert.equal(disc(stateDraw('light', 'on', {color_temp_kelvin:2700, brightness:1})), warm);
  assert.equal(disc(stateDraw('light', 'on')), '#ffd89a');
  assert.equal(disc(stateDraw('light', 'on', {rgb_color:[null,0,0], color_temp:0})), '#ffd89a');
  assert.equal(disc(stateDraw('light', 'off', {rgb_color:[255,0,0]})), palette.twinMarkerOff);
  assert.equal(red.at(-1)[1].strokeStyle, '#111318');
  assert.equal(stateDraw('light', 'on', {rgb_color:[0,0,80]}).at(-1)[1].strokeStyle, '#f4f5f7');
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

check('lock_alarm_and_cover_discs_follow_state_while_retaining_attention', () => {
  assert.equal(markerState('lock', 'locked').look, 'on');
  assert.equal(disc(stateDraw('lock', 'locked')), '#34d399');
  for (const [kind, state] of [['lock','unlocked'], ['lock','locking'], ['lock','unlocking'],
    ['garage','open'], ['garage','opening'], ['alarm','pending'], ['alarm','arming']]) {
    const row = markerState(kind, state), log = draw(kind, row.look, row.color);
    assert.equal(row.look, 'attention');
    assert.equal(disc(log), '#f59e0b');
    assert.equal(ring(log)[1].strokeStyle, '#fde68a');
    assert.equal(log.at(-1)[1].strokeStyle, '#111318');
  }
  for (const [kind, state] of [['lock','jammed'], ['alarm','triggered']]) {
    assert.equal(markerState(kind, state).look, 'attention');
    assert.equal(disc(stateDraw(kind, state)), '#f87171');
  }
  assert.equal(disc(stateDraw('other', 'armed_home', {}, 'alarm_control_panel.home')), '#34d399');
  assert.equal(disc(stateDraw('alarm', 'armed_away')), '#34d399');
  for (const [kind, state] of [['alarm','disarmed'], ['garage','closed'], ['blinds','closed']])
    assert.equal(disc(stateDraw(kind, state)), palette.twinMarkerOff);
  assert.equal(disc(stateDraw('blinds', 'open')), '#e5e7eb');
  assert.equal(disc(stateDraw('sensor', 'on', {device_class:'smoke'})), '#f59e0b');
  assert.equal(disc(stateDraw('lock', 'unavailable')), palette.twinMarkerUnavailable);
  assert.equal(disc(stateDraw('alarm', 'unknown')), palette.twinMarkerUnavailable);
  const count = draw('room', 'on', undefined, 3);
  assert.equal(disc(count), '#f4f5f7');
  assert.equal(count.at(-1)[0], 'fillText');
  assert.equal(count.at(-1)[1].fillStyle, '#111318');
});

check('ordinary_active_states_share_white_and_paused_media_is_off', () => {
  for (const [kind, state, attrs] of [['fan','on'], ['switch','on'], ['outlet','on'], ['other','on'],
    ['media','playing'], ['camera','recording'], ['camera','streaming'], ['vacuum','cleaning'],
    ['sensor','on',{device_class:'motion'}], ['sensor','on',{device_class:'occupancy'}]])
    assert.equal(disc(stateDraw(kind, state, attrs)), '#f4f5f7', kind + ' ' + state);
  for (const state of ['paused','idle']) assert.equal(disc(stateDraw('media', state)), palette.twinMarkerOff);
  assert.equal(palette.markerInk('#000000'), '#f4f5f7');
});

check('climate_colour_follows_mode_even_when_idle_or_action_disagrees', () => {
  for (const [mode, color] of [['heat','#fb923c'], ['cool','#60a5fa'], ['auto','#a78bfa'],
    ['heat_cool','#a78bfa'], ['dry','#2dd4bf'], ['fan_only','#2dd4bf']]) {
    for (const action of ['idle','heating','cooling'])
      assert.equal(disc(stateDraw('climate', mode, {hvac_action:action})), color, mode + ' ' + action);
  }
  assert.equal(disc(stateDraw('climate', 'off', {hvac_action:'heating'})), palette.twinMarkerOff);
});

check('mounted_climate_reuses_maps_material_and_mode_colour_in_thermostat_arc', async () => {
  const t = await rig({devices:[{device_id:'hvac',name:'HVAC',kind:'climate',entity_id:'climate.hvac',state:'heat',
    attributes:{hvac_action:'idle', supported_features:1, temperature:70, min_temp:50, max_temp:90}}]});
  try {
    const sprite = t.sprite('hvac'), material = sprite.material, heat = material.map;
    assert.equal(disc(heat.image.__log), '#fb923c');
    t.states['climate.hvac'].attributes.hvac_action = 'cooling'; await t.live.refresh();
    assert.equal(material.map, heat, 'an action change does not change the mode colour');
    t.states['climate.hvac'].state = 'cool'; await t.live.refresh();
    const cool = material.map;
    assert.notEqual(cool, heat); assert.equal(disc(cool.image.__log), '#60a5fa');
    t.states['climate.hvac'].state = 'auto'; await t.live.refresh();
    const auto = material.map;
    assert.notEqual(auto, cool); assert.equal(disc(auto.image.__log), '#a78bfa');
    await t.hold('hvac');
    const arc = document.querySelector('.twin-thermostat-arc .twin-light-progress');
    assert.ok(arc, 'mounted thermostat ring has its arc');
    for (let i = 0; i < 4; i++) {
      for (const [mode, map] of [['heat',heat], ['cool',cool], ['auto',auto]]) {
        t.states['climate.hvac'].state = mode; await t.live.refresh();
        assert.equal(material.map, map); assert.equal(arc.style.stroke, disc(map.image.__log));
      }
      t.live.draw(); assert.equal(t.sprite('hvac'), sprite); assert.equal(sprite.material, material);
    }
    let disposed = 0;
    for (const texture of [heat,cool,auto]) texture.addEventListener('dispose', () => disposed++);
    t.live.stop(); assert.equal(disposed, 3, 'cache owns disposal');
  } finally {t.cleanup();}
});

check('mounted_light_quantises_nearby_colours_and_keeps_glass_textures_and_material', async () => {
  const t = await rig({devices:[{device_id:'lamp',name:'Lamp',kind:'light',entity_id:'light.lamp',state:'on',
    attributes:{rgb_color:[255,0,0]}}]});
  try {
    const sprite = t.sprite('lamp'), material = sprite.material, red = material.map;
    t.states['light.lamp'].attributes.rgb_color = [254,1,1]; await t.live.refresh();
    assert.equal(material.map, red); assert.equal(disc(red.image.__log), '#ff0000');
    t.states['light.lamp'].attributes.rgb_color = [0,0,255]; await t.live.refresh();
    assert.equal(disc(material.map.image.__log), '#0000ff'); assert.notEqual(material.map, red);
    t.states['light.lamp'].state = 'off'; await t.live.refresh();
    const off = material.map;
    for (const rgb of [[255,0,0], [0,255,0]]) {
      t.states['light.lamp'].attributes.rgb_color = rgb; await t.live.refresh(); assert.equal(material.map, off);
      t.live.draw(); assert.equal(sprite.material, material); assert.equal(t.sprite('lamp'), sprite);
    }
    let disposed = false; off.addEventListener('dispose', () => {disposed = true;});
    t.live.stop(); assert.ok(disposed);
  } finally {t.cleanup();}
});

check('thermostat_range_and_dry_arcs_use_the_same_mode_palette_as_markers', async () => {
  const {climateControls} = await import(file('static/twin/live/controls/climate.js'));
  for (const mode of ['heat', 'cool', 'heat_cool', 'auto', 'dry', 'fan_only']) {
    const range = ['heat_cool', 'auto'].includes(mode);
    const state = {state:mode, attributes:{hvac_action:'idle', min_temp:50, max_temp:90,
      ...(range ? {supported_features:2, target_temp_low:68, target_temp_high:76}
        : {supported_features:1, temperature:70})}};
    const root = climateControls({row:{name:'HVAC', entity_id:'climate.hvac', offered:true},
      state, control:async () => true, surface:'ring'});
    const arc = root.querySelector('.twin-light-progress');
    assert.equal(arc.style.stroke, markerState('climate', mode).color, mode);
    assert.equal(arc.style.visibility, 'visible');
    root.update({...state, state:'off'});
    assert.equal(arc.style.visibility, 'hidden');
    root.stop();
  }
});

check('mounted_colour_churn_evicts_maps_without_replacing_sprite_materials', async () => {
  const t = await rig({devices:[
    {device_id:'pinned',name:'Pinned',kind:'light',entity_id:'light.pinned',state:'on',attributes:{rgb_color:[255,0,0]}},
    {device_id:'moving',name:'Moving',kind:'light',entity_id:'light.moving',state:'on',attributes:{rgb_color:[0,0,0]}},
  ]});
  try {
    const sprites = [t.sprite('pinned'), t.sprite('moving')], materials = sprites.map(s => s.material);
    const made = new Set(), disposed = new Set();
    const watch = () => {
      for (const sprite of sprites) {
        const map = sprite.material.map;
        if (made.has(map)) continue;
        made.add(map); map.addEventListener('dispose', () => {
          assert.ok(sprites.every(s => s.material.map !== map)); disposed.add(map);
        });
      }
    };
    watch();
    for (let n = 1; n < 100; n++) {
      t.states['light.moving'].attributes.rgb_color = [n % 16 * 16, Math.floor(n / 16) * 16, 0];
      await t.live.refresh(); watch(); t.live.draw();
      assert.deepEqual(sprites.map(s => s.material), materials);
      assert.ok(materials.every(m => m.version === 0), 'no material update requests a shader recompile');
    }
    assert.equal(made.size - disposed.size, 48);
    t.live.stop(); assert.equal(disposed.size, made.size);
  } finally {t.cleanup();}
});

check('colour_cache_evicts_lru_beyond_48_without_disposing_any_sprite_map', () => {
  const cache = markerTextureCache(), pinned = markerSprite(null), moving = markerSprite(null);
  const sprites = [pinned, moving], disposed = new Set(), created = new Set();
  const assign = (sprite, color) => {
    const texture = cache.assign(sprite, 'light', 'on', null, color);
    if (!created.has(texture)) {
      created.add(texture);
      texture.addEventListener('dispose', () => {
        assert.ok(sprites.every(s => s.material.map !== texture), 'never dispose any assigned map');
        assert.ok(!disposed.has(texture), 'dispose exactly once'); disposed.add(texture);
      });
    }
    return texture;
  };
  const color = n => '#' + [n % 16 * 16, Math.floor(n / 16) % 16 * 16, Math.floor(n / 256) * 16]
    .map(v => v.toString(16).padStart(2, '0')).join('');
  const red = assign(pinned, '#ff0000'), first = assign(moving, color(0));
  const second = assign(moving, color(1));
  for (let n = 2; n < 47; n++) assign(moving, color(n));
  assert.equal(created.size, 48); assert.equal(disposed.size, 0);
  assert.equal(assign(moving, color(0)), first, 'cache hit refreshes recency');
  assign(moving, color(47));
  assert.ok(disposed.has(second), 'least recently used unpinned map evicted');
  assert.ok(!disposed.has(first)); assert.ok(!disposed.has(red));
  for (let n = 48; n < 200; n++) assign(moving, color(n));
  assert.equal(created.size - disposed.size, 48, 'bounded despite continuous light colour changes');
  assert.equal(pinned.material.map, red); assert.ok(!disposed.has(red), 'hidden/in-use maps stay pinned');
  cache.dispose(); assert.equal(disposed.size, created.size);
  sprites.forEach(s => s.material.dispose());
});

check('more_than_48_in_use_maps_are_retained_until_sprites_are_rekeyed', () => {
  const cache = markerTextureCache(), sprites = Array.from({length:49}, () => markerSprite(null));
  const disposed = new Set();
  const textures = sprites.map((sprite, n) => {
    const texture = cache.assign(sprite, 'light', 'on', null,
      '#' + [n % 16 * 16, Math.floor(n / 16) * 16, 0].map(v => v.toString(16).padStart(2, '0')).join(''));
    texture.addEventListener('dispose', () => {
      assert.ok(sprites.every(s => s.material.map !== texture)); disposed.add(texture);
    });
    return texture;
  });
  assert.equal(new Set(textures).size, 49);
  assert.equal(disposed.size, 0, 'even the oldest of 49 assigned maps is protected');
  // A protected working set may exceed the cap; releasing one key immediately trims it.
  cache.assign(sprites[0], 'light', 'on', null, '#100000');
  assert.deepEqual([...disposed], [textures[0]]);
  cache.dispose(); assert.equal(disposed.size, 49);
  sprites.forEach(s => s.material.dispose());
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
