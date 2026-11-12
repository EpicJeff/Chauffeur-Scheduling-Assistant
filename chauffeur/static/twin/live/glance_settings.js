import { base } from '../twin_library.js';
import { migrateGlanceTiles } from './glance.js';
import { GLANCE_ICONS, defaultGlanceIcon, glanceIcon } from './glance_icons.js';

export function mountGlanceSettings(view, glance, idle, {api = (path, init) => fetch(base() + path, init)} = {}) {
  const editor = document.getElementById('twin-glance-settings');
  const picker = document.getElementById('twin-glance-panel'), source = document.getElementById('twin-glance-source');
  const search = document.getElementById('twin-glance-search'), selected = document.getElementById('twin-glance-selected');
  const choices = document.getElementById('twin-glance-choices'), iconGrid = document.getElementById('twin-glance-icons');
  const entityPicker = document.getElementById('twin-glance-entity-picker'), add = document.getElementById('twin-glance-add');
  const cancel = document.getElementById('twin-glance-cancel'), empty = document.getElementById('twin-glance-empty');
  const enabled = document.getElementById('house_twin_idle_enabled'), panelsEnabled = document.getElementById('twin-panels-idle');
  const saveButton = document.getElementById('twin-glance-save');
  let preferences = null, tiles = [], household = [], stopped = false, editorRevision = 0, editorReady = false;
  let stage = null, editing = null, draft = null, returnFocus = null;
  if (saveButton) saveButton.disabled = true;
  const events = new AbortController();
  const listen = (node, name, fn) => node?.addEventListener(name, fn, {signal: events.signal});
  const name = id => view.live?.state(id)?.attributes?.friendly_name || id;
  const button = (label, action, accessible = label) => {
    const b = document.createElement('button'); b.type = 'button'; b.textContent = label;
    b.setAttribute('aria-label', accessible); b.addEventListener('click', action); return b;
  };
  const custom = () => { if (tiles === null) tiles = household.map(tile => ({...tile})); source.value = 'custom'; };
  function closePicker() {
    const target = returnFocus;
    stage = null; draft = null; render();
    (target === 'add' ? add : selected.children[target?.index]?.querySelector(`[data-action="${target?.action}"]`))?.focus();
  }
  function openPicker(mode, index = null) {
    stage = mode; editing = index; draft = null;
    returnFocus = index === null ? 'add' : {index, action: mode}; search.value = '';
    render();
    (mode === 'entity' ? search : iconGrid.querySelector('button'))?.focus();
  }
  function render() {
    if (!editor) return;
    const inherited = tiles === null, list = inherited ? household : tiles;
    const linked = [...new Set([...(view.live?.layout().devices || []).flatMap(d => d.entities || [d.entity_id]),
      ...Object.keys(view.live?.peek() || {})])].filter(Boolean);
    selected.replaceChildren(); choices.replaceChildren(); iconGrid.replaceChildren();
    for (const [i, tile] of list.entries()) {
      const row = document.createElement('li'), caption = document.createElement('span');
      const title = document.createElement('span'); title.textContent = name(tile.entity);
      const entity = document.createElement('small'); entity.textContent = tile.entity; caption.append(title, entity);
      const icon = button('', () => openPicker('icon', i), `Change icon for ${name(tile.entity)}`);
      icon.dataset.action = 'icon'; icon.append(glanceIcon(tile.icon));
      const change = button('Entity', () => openPicker('entity', i), `Change entity for ${name(tile.entity)}`); change.dataset.action = 'entity';
      const label = document.createElement('input'); label.type = 'text'; label.maxLength = 32; label.value = tile.label || '';
      label.placeholder = 'Optional label'; label.setAttribute('aria-label', `Label for ${name(tile.entity)}`);
      label.addEventListener('input', () => { tile.label = label.value; });
      const move = delta => {
        const target = i + delta;
        if (target < 0 || target >= tiles.length) return;
        [tiles[i], tiles[target]] = [tiles[target], tiles[i]]; render();
        const moved = selected.children[target], preferred = moved.querySelector(`[data-action="${delta < 0 ? 'up' : 'down'}"]`);
        (preferred.disabled ? moved.querySelector('[data-action="icon"]') : preferred).focus();
      };
      const up = button('↑', () => move(-1), `Move ${name(tile.entity)} up`); up.dataset.action = 'up'; up.disabled = i === 0;
      const down = button('↓', () => move(1), `Move ${name(tile.entity)} down`); down.dataset.action = 'down'; down.disabled = i === list.length - 1;
      const remove = button('Remove', () => { tiles.splice(i, 1); render(); (selected.children[Math.min(i, tiles.length - 1)]?.querySelector('button') || add).focus(); }, `Remove ${name(tile.entity)}`);
      row.append(icon, caption, change, label, up, down, remove);
      for (const control of [icon, change, label, up, down, remove]) control.disabled ||= inherited || !editorReady || !!stage;
      selected.append(row);
    }
    if (empty) { empty.hidden = !!list.length; empty.textContent = 'No tiles chosen.'; }
    add.disabled = !editorReady || list.length >= 12 || !!stage;
    source.disabled = !editorReady || !!stage; picker.disabled = !editorReady || !!stage;
    entityPicker.hidden = stage !== 'entity'; iconGrid.hidden = stage !== 'icon'; cancel.hidden = !stage;
    saveButton.disabled = !editorReady || !!stage;
    const query = search.value.toLowerCase();
    if (stage === 'entity') for (const id of linked.filter(id => !list.some((tile, i) => tile.entity === id && i !== editing) && `${name(id)} ${id}`.toLowerCase().includes(query)).slice(0, 60)) {
      choices.append(button(name(id) + ' · ' + id, () => {
        if (editing !== null) { tiles[editing].entity = id; closePicker(); }
        else {
          draft = {entity: id, icon: defaultGlanceIcon(id, view.live?.state(id)), label: ''};
          stage = 'icon'; render(); iconGrid.querySelector('button')?.focus();
        }
      }, `Choose ${name(id)}`));
    }
    if (stage === 'entity' && !choices.children.length) { const p = document.createElement('p'); p.textContent = 'No matching entities.'; choices.append(p); }
    if (stage === 'icon') for (const [id, item] of Object.entries(GLANCE_ICONS)) {
      const tile = draft || tiles[editing], b = button(item.name, () => {
        if (draft) { custom(); tiles.push({...draft, icon: id}); }
        else tiles[editing].icon = id;
        closePicker();
      }, `Use ${item.name} icon`);
      b.setAttribute('aria-pressed', String(id === tile.icon)); b.append(glanceIcon(id)); iconGrid.append(b);
    }
  }
  async function loadEditor() {
    if (!editor || !preferences?.can_edit || stopped) return;
    const revision = ++editorRevision, panelId = picker.value;
    stage = null; editorReady = false; render();
    try {
      const r = await api('api/house/twin/glance' + (panelId ? '?panel_id=' + encodeURIComponent(panelId) : ''));
      if (!r.ok) throw new Error();
      const p = await r.json(); if (stopped || revision !== editorRevision) return;
      household = migrateGlanceTiles(p.household_entities, view.live?.peek());
      tiles = panelId && p.panel_entities === null ? null : migrateGlanceTiles(panelId ? p.panel_entities : p.household_entities, view.live?.peek());
      source.options[0].textContent = panelId ? 'Use household tiles' : 'No tiles';
      source.options[1].textContent = panelId ? "This panel's tiles" : 'Chosen household tiles';
      source.value = tiles === null || !panelId && !tiles.length ? 'inherit' : 'custom';
      enabled.checked = p.idle_enabled; panelsEnabled.checked = p.panel_idle_enabled; panelsEnabled.parentElement.hidden = !!panelId;
      editorReady = true; render();
    } catch { if (revision === editorRevision) window.chfSettingsSaved?.(false, 'Could not load house settings.'); }
  }
  async function reload() {
    try {
      const r = await api('api/house/twin/glance'); if (!r.ok) return;
      const p = await r.json(); if (stopped) return;
      const first = !preferences; preferences = p;
      glance.configure(p.entities); idle.configure(p.idle_enabled, p.weather_entity);
      const gear = document.getElementById('twin-settings-gear'); if (gear) gear.hidden = !p.can_edit;
      if (first && editor && p.can_edit) {
        for (const panel of p.panels || []) { const option = document.createElement('option'); option.value = panel.device_id; option.textContent = panel.label; picker.append(option); }
        await loadEditor();
      }
    } catch { /* Keep preferences through temporary network loss. */ }
  }
  listen(document.getElementById('twin-settings-gear'), 'click', () => window.chfOpenSettings('twin', 'twin-glance-settings'));
  listen(add, 'click', () => openPicker('entity'));
  listen(cancel, 'click', closePicker);
  listen(editor, 'keydown', event => { if (stage && event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); closePicker(); } });
  listen(picker, 'change', loadEditor); listen(search, 'input', render);
  listen(source, 'change', () => { tiles = source.value === 'inherit' ? (picker.value ? null : []) : tiles || household.map(tile => ({...tile})); render(); });
  listen(window, 'chf-settings-opened', event => { if (event.detail?.tab === 'twin' && preferences?.can_edit) loadEditor(); });
  listen(saveButton, 'click', async () => {
    if (!editorReady || stage || stopped) return;
    window.chfSettingsSaving?.(); saveButton.disabled = true;
    try {
      const r = await api('api/house/twin/glance', {method: 'PUT', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({entities: tiles, idle_enabled: enabled.checked, panel_idle_enabled: panelsEnabled.checked, panel_id: picker.value || null})});
      if (!r.ok) throw new Error();
      await reload(); window.chfSettingsSaved?.(true);
    } catch { window.chfSettingsSaved?.(false, 'Could not save house settings.'); }
    finally { if (!stopped) saveButton.disabled = !editorReady || !!stage; }
  });
  const timer = setInterval(reload, 30000); reload();
  return {reload, refreshChoices: render, stop() { stopped = true; clearInterval(timer); events.abort(); }};
}
