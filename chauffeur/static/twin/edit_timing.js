// Explicit records travel with an edit; background rebuilds never share a clock.
const finished = new WeakSet();
export function span(record, name) {
  if (!record || finished.has(record)) return () => {};
  const start = performance.now();
  return () => { if (!finished.has(record)) record[name] = (record[name] || 0) + performance.now() - start; };
}

export function serverTiming(header = '') {
  return Object.fromEntries(header.split(',').flatMap(part => {
    const match = part.trim().match(/^([\w-]+)\s*;\s*dur=([\d.]+)/);
    return match ? [[match[1], Number(match[2])]] : [];
  }));
}

export function beginEdit(operation, start = performance.now()) {
  return { op: operation?.op || '', at: new Date().toISOString(), start,
    request: 0, parse: 0, rebuild: 0, first_frame: 0, refresh_state: 0,
    detail: { generate: 0, batch: 0, yard: 0, materials: 0, dispose: 0, bake_stop: 0 },
    counts: { meshes: 0, draw_calls: 0, triangles: 0, buildings: 0, levels: 0 }, buildings: [] };
}

export function observeEditFrame(view, record) {
  const end = performance.now();
  const frame = view?.afterNextRender ? view.afterNextRender()
    : new Promise(resolve => requestAnimationFrame(() => resolve({})));
  return frame.then(stats => {
    record.first_frame = performance.now() - end;
    record.total = performance.now() - record.start;
    // A fallback model can load later. Its work belongs after this first frame.
    finished.add(record.detail);
    Object.assign(record.counts, stats);
  });
}

export function keepEdit(record) {
  delete record.start;
  const records = window.__twinEditTiming ||= [];
  records.push(record);
  if (records.length > 30) records.splice(0, records.length - 30);
  window.dispatchEvent(new Event('twin-edit-timing'));
}

// Same device preference and aria-pressed pattern as the Lighting controls.
export function mountEditTiming({ toggle, overlay, send, signal, post, report }) {
  window.__twinEditTiming ||= [];
  const key = 'chf.editor.editTiming';
  let shown = false, sending = false;
  try { shown = localStorage.getItem(key) === 'true'; } catch { /* Private storage. */ }
  function draw() {
    toggle?.setAttribute('aria-pressed', String(shown));
    if (!overlay) return;
    overlay.hidden = !shown;
    if (!shown) return;
    const last = window.__twinEditTiming.at(-1);
    overlay.replaceChildren();
    const heading = document.createElement('h2');
    heading.textContent = last ? `Edit ${last.total.toFixed(1)} ms` : 'Edit timing';
    overlay.append(heading);
    const text = document.createElement('pre');
    text.textContent = last ? [
      ...Object.entries({ request: last.request, parse: last.parse, rebuild: last.rebuild, first_frame: last.first_frame,
        ...Object.fromEntries(Object.entries(last.detail).map(([k, v]) => [`  ${k}`, v])),
        ...Object.fromEntries(Object.entries(last.server || {}).map(([k, v]) => [`  server ${k}`, v])) })
        .sort((a, b) => b[1] - a[1]).map(([name, ms]) => `${name}: ${ms.toFixed(1)} ms`),
      `refresh_state: ${last.refresh_state.toFixed(1)} ms (overlaps frame)`,
      `${last.counts.meshes} meshes · ${last.counts.draw_calls} calls · ${last.counts.triangles} triangles`,
      `${last.counts.buildings} buildings · ${last.counts.levels} levels`,
    ].join('\n') : 'Make an edit to measure it.';
    overlay.append(text);
  }
  toggle?.addEventListener('click', () => {
    shown = !shown;
    try { localStorage.setItem(key, String(shown)); } catch { /* Still usable. */ }
    draw();
  }, { signal });
  send?.addEventListener('click', async () => {
    if (sending) return;
    if (!window.__twinEditTiming.length) { report(new Error('Make an edit before sending a timing report.')); return; }
    sending = true; send.disabled = true;
    try {
      await post({ kind: 'edit_timing', records: window.__twinEditTiming.slice(-30) });
      window.showGlobalAlert('Edit timing report sent.');
    } catch (error) { report(error); }
    finally { sending = false; send.disabled = false; }
  }, { signal });
  window.addEventListener('twin-edit-timing', draw, { signal });
  draw();
}
