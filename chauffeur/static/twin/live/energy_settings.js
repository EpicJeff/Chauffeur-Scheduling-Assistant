import { energyLocations, energyAnchors } from './energy_geometry.js';
import { base } from '../twin_library.js';
import { guessEnergy, ROLES } from './energy_mapping.js';
import { energyCheck, renderEnergyCheck } from './energy_check.js';

export function mountEnergySettings(view, {api = (path, init) => fetch(base() + path, init)} = {}) {
  const editor = document.getElementById('twin-energy-fields'), save = document.getElementById('twin-energy-save');
  const search = document.getElementById('twin-energy-search');
  const events = new AbortController(); let stopped = false, draft = null, preferences = null, ready = false;
  const check = document.createElement('section'), title = document.createElement('h3'), checkBody = document.createElement('div');
  check.id = 'twin-energy-check'; check.className = 'twin-energy-check'; title.textContent = 'Energy check'; check.append(title, checkBody);
  save?.parentNode?.append(check);
  let subscribedLive = null, unsubscribe = null;
  function refreshCheck() {
    if (!preferences) return;
    const states = view.live?.peek() || {}, mapping = guessEnergy(states, preferences.mapping, preferences.cars);
    // Saved sources only: these are also the sources used by the ribbons.
    renderEnergyCheck(checkBody, view.live?.energy?.()?.check || energyCheck(view, view.live?.layout?.(), mapping, states, view.live?.stale?.() ?? true));
  }
  if (save) save.disabled = true;
  const listen = (node, event, action) => node?.addEventListener(event, action, {signal: events.signal});
  const caption = key => key.replaceAll('_', ' ').replace(/^./, c => c.toUpperCase());
  function render() {
    if (!editor || !preferences?.can_edit || !draft) return;
    editor.replaceChildren();
    const states = view.live?.peek() || {}, resolved = guessEnergy(states, draft, preferences.cars);
    const name = id => states[id]?.attributes?.friendly_name || id;
    const chosen = [...ROLES.map(k => draft[k]), ...resolved.cars.flatMap(c => [c.charge_power, c.battery_level, c.location])].filter(Boolean);
    const query = (search?.value || '').toLowerCase();
    const ids = [...new Set([...Object.keys(states), ...chosen])].filter(id => chosen.includes(id) || `${name(id)} ${id}`.toLowerCase().includes(query)).sort();
    function select(host, title, options, value, change) {
      const label = document.createElement('label'), field = document.createElement('select'); label.append(document.createTextNode(title));
      for (const [id, text] of options) {const option = document.createElement('option'); option.value = id; option.textContent = text; field.append(option);}
      field.value = value; field.addEventListener('change', () => change(field.value)); label.append(field); host.append(label); return field;
    }
    function entity(host, title, object, key, guessed) {
      const options = [['', `Automatic${guessed ? ': ' + name(guessed) : ': none found'}`], ['-', 'None'], ...ids.map(id => [id, `${name(id)} (${id})`])];
      select(host, title, options, object[key] === null ? '-' : object[key] || '', value => {
        if (!value) delete object[key]; else object[key] = value === '-' ? null : value;
      });
    }
    const locations=energyLocations(view,view.live?.layout?.());
    function location(host,title,object,key,power,kind){
      const options=locations.filter(o=>o.ref.type==='device' || o.kind===kind);
      const match=options.find(o=>o.ref.type==='device' && power && o.entities.includes(power));
      const saved=object[key],value=saved===null?'-':saved===undefined?'':JSON.stringify(saved);
      const choices=[['','Automatic: '+(match?.label || 'not placed')],['-','Not placed'],...options.map(o=>[JSON.stringify(o.ref),o.label])];
      if(saved && !choices.some(([id])=>id===value))choices.push([value,'Not placed (previous location was removed)']);
      select(host,title,choices,value,value=>{if(!value)delete object[key];else object[key]=value==='-'?null:JSON.parse(value);});
    }
    draft.locations ||= {};
    for (const key of ROLES){
      entity(editor,caption(key),draft,key,resolved[key]);
      const role={battery_power:'battery',grid_power:'grid',house_power:'house'}[key];
      if(role)location(editor,caption(role==='grid'?'meter':role==='house'?'electric_panel':role)+' location',draft.locations,role,resolved[key],role==='grid'?'meter':role==='house'?'electric_panel':null);
      if(key==='solar_power'){const note=document.createElement('p'),a=energyAnchors(view,view.live?.layout?.(),resolved);note.textContent=a.solar?'Solar location: source roof '+a.source:'Solar location: not placed. Add zones and choose Solar ribbon starts here in the house editor.';editor.append(note);}
    }
    select(editor, 'Positive battery power means', [['discharge', 'Discharging'], ['charge', 'Charging']], resolved.battery_positive, value => {draft.battery_positive = value;});
    select(editor, 'Positive grid power means', [['import', 'Importing from the grid'], ['export', 'Exporting to the grid']], resolved.grid_positive, value => {draft.grid_positive = value;});
    const chargerLabel = document.createElement('label'), included = document.createElement('input');
    included.type = 'checkbox'; included.checked = resolved.home_includes_chargers !== false;
    included.addEventListener('change', () => {draft.home_includes_chargers = included.checked;});
    chargerLabel.append(included, document.createTextNode(' Home power includes car chargers')); editor.append(chargerLabel);
    const label = document.createElement('label'), panels = document.createElement('input'); panels.type = 'checkbox'; panels.checked = resolved.panels.visible;
    panels.addEventListener('change', () => {draft.panels = {...resolved.panels, visible: panels.checked};}); label.append(panels, document.createTextNode(' Show solar panels on the roof')); editor.append(label);
    const cars = structuredClone(resolved.cars), useCars = () => {draft.cars = cars;};
    for (const [i, car] of cars.entries()) {
      const group = document.createElement('fieldset'), legend = document.createElement('legend'); legend.textContent = car.name; group.append(legend);
      const nameLabel = document.createElement('label'), input = document.createElement('input'); input.value = car.name; input.maxLength = 100;
      input.addEventListener('input', () => {car.name = input.value; useCars();}); nameLabel.append(document.createTextNode('Car name'), input); group.append(nameLabel);
      for (const key of ['charge_power', 'battery_level', 'location']) {
        const opts = [['', key === 'location' ? 'No tracker (rests at home)' : 'None'], ...ids.map(id => [id, `${name(id)} (${id})`])];
        select(group, caption(key), opts, car[key] || '', value => {car[key] = value || null; useCars();});
      }
      location(group,'Charger location',car,'anchor',car.charge_power,null);
      for(const field of group.querySelectorAll('select'))field.addEventListener('change',useCars);
      const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = 'Remove ' + car.name;
      remove.addEventListener('click', () => {cars.splice(i, 1); useCars(); render();}); group.append(remove); editor.append(group);
    }
    const add = document.createElement('button'); add.type = 'button'; add.textContent = 'Add car'; add.disabled = cars.length >= 12;
    add.addEventListener('click', () => {cars.push({id: 'car-' + Date.now(), name: 'Car ' + (cars.length + 1)}); useCars(); render();}); editor.append(add);
    const reset = document.createElement('button'); reset.type = 'button'; reset.textContent = 'Guess sources again';
    reset.addEventListener('click', () => {draft = {}; render();}); editor.append(reset);
    if (!cars.length) {const empty = document.createElement('p'); empty.textContent = 'No cars found. Add a car to choose its charging and location sensors.'; editor.append(empty);}
  }
  function apply(p) {
    preferences = p; view.energySources = p;
    view.live?.configureEnergy(p);
    view.glance?.energy(guessEnergy(view.live?.peek(), p.mapping, p.cars));
    if (subscribedLive !== view.live) {
      unsubscribe?.(); subscribedLive = view.live; unsubscribe = view.live?.subscribe?.(refreshCheck);
    }
    refreshCheck();
  }
  async function reload() {
    try {
      const response = await api('api/house/twin/energy'); if (!response.ok) return;
      const p = await response.json(); if (stopped || !p.mapping || !Array.isArray(p.cars)) return;
      apply(p);
      if (!ready && editor && p.can_edit) {draft = structuredClone(p.mapping); ready = true; save.disabled = false; render();}
    } catch { /* Keep the last mapping through HA or network outages. */ }
  }
  listen(window, 'chf-settings-opened', event => {if (event.detail?.tab === 'twin' && ready) {draft = structuredClone(preferences.mapping); render();}});
  listen(search, 'input', render);
  listen(save, 'click', async () => {
    if (!ready || stopped) return;
    window.chfSettingsSaving?.(); save.disabled = true;
    try {
      const r = await api('api/house/twin/energy', {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(draft)});
      if (!r.ok) throw new Error();
      await reload(); window.chfSettingsSaved?.(true);
    } catch {window.chfSettingsSaved?.(false, 'Could not save energy sources.');}
    finally {if (!stopped) save.disabled = false;}
  });
  const timer = setInterval(reload, 30000); reload();
  return {reload, refreshChoices() {if (preferences) {apply(preferences); if (ready) render();}}, stop() {stopped = true; clearInterval(timer); events.abort(); unsubscribe?.(); check.remove();}};
}
