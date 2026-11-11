import { base } from '../twin_library.js';

export function mountGlanceSettings(view, glance, idle, {api = (path, init) => fetch(base() + path, init)} = {}) {
  const editor = document.getElementById('twin-glance-settings');
  const picker = document.getElementById('twin-glance-panel');
  const source = document.getElementById('twin-glance-source');
  const search = document.getElementById('twin-glance-search');
  const selected = document.getElementById('twin-glance-selected');
  const choices = document.getElementById('twin-glance-choices');
  const enabled = document.getElementById('house_twin_idle_enabled');
  const panelsEnabled = document.getElementById('twin-panels-idle');
  const saveButton = document.getElementById('twin-glance-save');
  let preferences = null, ids = null, stopped = false, editorRevision = 0, editorReady = false;
  if (saveButton) saveButton.disabled = true;
  const events = new AbortController();
  const listen = (node, name, fn) => node?.addEventListener(name, fn, {signal: events.signal});
  const name = id => view.live?.state(id)?.attributes?.friendly_name || id;
  function render() {
    if (!editor) return;
    const linked = [...new Set((view.live?.layout().devices || []).flatMap(d => d.entities || [d.entity_id]))];
    selected.replaceChildren(); choices.replaceChildren();
    const button = (label, action, accessible = label) => {
      const b = document.createElement('button'); b.type = 'button'; b.textContent = label;
      b.setAttribute('aria-label', accessible); b.addEventListener('click', action); return b;
    };
    const automatic = ids === null;
    for (const [i, id] of (ids || []).entries()) {
      const row = document.createElement('li'), caption = document.createElement('span'); caption.textContent = name(id);
      const move = delta => { if (i + delta >= 0 && i + delta < ids.length) { [ids[i], ids[i + delta]] = [ids[i + delta], ids[i]]; render(); } };
      const up = button('↑', () => move(-1), `Move ${name(id)} up`); up.disabled = i === 0;
      const down = button('↓', () => move(1), `Move ${name(id)} down`); down.disabled = i === ids.length - 1;
      row.append(caption, up, down, button('Remove', () => { ids.splice(i, 1); render(); }, `Remove ${name(id)}`)); selected.append(row);
    }
    const query = search.value.toLowerCase();
    for (const id of linked.filter(id => !ids?.includes(id) && `${name(id)} ${id}`.toLowerCase().includes(query)).slice(0, 60)) {
      const b = button(`Add ${name(id)}`, () => { ids ||= []; if (ids.length < 12) ids.push(id); source.value = 'custom'; render(); });
      b.disabled = !!ids && ids.length >= 12; choices.append(b);
    }
    selected.hidden = automatic;
  }
  async function loadEditor() {
    if (!editor || !preferences?.can_edit || stopped) return;
    const revision = ++editorRevision, panelId = picker.value;
    editorReady = false; saveButton.disabled = true;
    try {
      const r = await api('api/house/twin/glance' + (panelId ? '?panel_id=' + encodeURIComponent(panelId) : ''));
      if (!r.ok) throw new Error();
      const p = await r.json(); if (stopped || revision !== editorRevision) return;
      ids = panelId ? p.panel_entities : p.household_entities;
      source.options[0].textContent = panelId ? 'Use household list' : 'Automatic readings';
      source.options[1].textContent = panelId ? "This panel's list" : 'Chosen household list';
      source.value = ids === null ? 'inherit' : 'custom'; enabled.checked = p.idle_enabled;
      panelsEnabled.checked = p.panel_idle_enabled; panelsEnabled.parentElement.hidden = !!panelId;
      editorReady = true; saveButton.disabled = false; render();
    } catch { if (revision === editorRevision) window.chfSettingsSaved?.(false, 'Could not load house settings.'); }
  }
  async function reload() {
    try {
      const r = await api('api/house/twin/glance'); if (!r.ok) return;
      const p = await r.json(); if (stopped) return;
      const first = !preferences; preferences = p;
      glance.configure(p.entities); idle.configure(p.idle_enabled);
      const gear = document.getElementById('twin-settings-gear');
      if (gear) gear.hidden = !p.can_edit;
      if (first && editor && p.can_edit) {
        for (const panel of p.panels || []) {
          const option = document.createElement('option'); option.value = panel.device_id; option.textContent = panel.label; picker.append(option);
        }
        await loadEditor();
      }
    } catch { /* Keep preferences through temporary network loss. */ }
  }
  listen(document.getElementById('twin-settings-gear'), 'click', () => window.chfOpenSettings('twin', 'twin-glance-settings'));
  listen(picker, 'change', loadEditor); listen(search, 'input', render);
  listen(source, 'change', () => { ids = source.value === 'inherit' ? null : ids || []; render(); });
  listen(window, 'chf-settings-opened', event => { if (event.detail?.tab === 'twin' && preferences?.can_edit) loadEditor(); });
  listen(saveButton, 'click', async () => {
    if (!editorReady || stopped) return;
    window.chfSettingsSaving?.();
    try {
      const r = await api('api/house/twin/glance', {method: 'PUT', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({entities: ids, idle_enabled: enabled.checked, panel_idle_enabled: panelsEnabled.checked, panel_id: picker.value || null})});
      if (!r.ok) throw new Error();
      await reload(); window.chfSettingsSaved?.(true);
    } catch { window.chfSettingsSaved?.(false, 'Could not save house settings.'); }
  });
  const timer = setInterval(reload, 30000); reload();
  return {reload, refreshChoices: render, stop() { stopped = true; clearInterval(timer); events.abort(); }};
}
