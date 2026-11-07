// Foreground twin work uses the page's auth wrapper and shared confirm sheet.
const base = () => window.chfBase || '';
const currentRound = snapshot => [...snapshot.rounds].reverse().find(row => !row.stale)?.id ?? null;
const runId = () => globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;

async function request(path, method = 'GET', body) {
  const response = await fetch(base() + 'api/house/twin' + path, {
    method, ...(body === undefined ? {} : body instanceof FormData
      ? { body } : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  });
  const text = await response.text();
  let data;
  try { data = JSON.parse(text); }
  catch {
    const error = new Error(`House request ${response.status}: ${text || response.statusText || 'Empty response'}`);
    error.status = response.status;
    throw error;
  }
  if (!response.ok) {
    const error = new Error(typeof data?.detail === 'string' ? data.detail : 'The house request could not finish.');
    error.status = response.status; error.detail = data?.detail;
    throw error;
  }
  return data;
}

async function meteredPost(path, body) {
  for (;;) {
    try { return await request(path, 'POST', body); }
    catch (error) {
      if (error.status !== 409 || !error.detail?.checkpoint) throw error;
      const go = await window.promptConfirm(`Spent $${Number(error.detail.total).toFixed(2)} so far`,
        'Continue to the next checkpoint?', 'Continue', 'Stop');
      if (!go) return null;
      await request('/cost/ack', 'POST', { checkpoint: error.detail.checkpoint });
    }
  }
}

function log(message) {
  const host = document.getElementById('twin-director-log');
  if (host) host.textContent += (host.textContent ? '\n' : '') + message;
}

export async function runDirector(view, { run = runId(), cameras = ['front', 'porch', 'rear', 'top'], onRound } = {}) {
  const snapshot = await request('');
  let roundBase = currentRound(snapshot), spent = 0;
  for (let n = 0; n < 5; n++) {
    const captures = await view.capture(cameras, 1280, 800);
    // capture returns PNG data URLs; the server accepts raw base64 PNGs.
    const renders = captures.map(png => png.replace(/^data:image\/png;base64,/, ''));
    let response;
    try { response = await meteredPost('/critique', { run, renders, cameras, base: roundBase }); }
    catch (error) {
      if (error.status === 409) { log(error.message); return; }
      throw error;
    }
    if (!response) { log('Stopped at the spend checkpoint.'); return; }
    const result = response.result;
    await view.rebuild(result.plan);
    spent += result.cost || 0;
    log(`${result.critique}\nRun cost: $${spent.toFixed(2)}`);
    if (result.notes?.length) log(result.notes.join('\n'));
    if (result.stale) log('This critique is stale: a newer edit or revert won. The current house is shown; the director has stopped.');
    roundBase = result.round;
    if (onRound) await onRound(result);
    if (result.done || result.stale) return;
  }
  log('Round cap reached (5 rounds).');
}

export function initTwinTools() {
  const toggle = document.getElementById('twin-tools-toggle');
  if (!toggle) return;
  const sheet = document.getElementById('twin-tools-sheet');
  const editor = document.getElementById('twin-plan-editor');
  const reason = document.getElementById('twin-plan-reason');
  let editorBase = null, dirty = false, running = false, drafting = false;
  const tell = error => window.showGlobalAlert(error.message || String(error));
  const view = () => {
    if (!window.__twin?.ready) throw new Error('Wait for the house preview to finish loading.');
    return window.__twin;
  };

  async function refresh(forceEditor = false) {
    const [snapshot, cost] = await Promise.all([request(''), request('/cost')]);
    const rounds = document.getElementById('twin-rounds');
    rounds.replaceChildren();
    for (const round of snapshot.rounds) {
      const row = document.createElement('li'); row.dataset.roundId = round.id;
      const text = document.createElement('span');
      text.textContent = `#${round.id} · ${round.kind}${round.stale ? ' · stale' : ''}${round.note ? ' · ' + round.note : ''}`;
      const revert = document.createElement('button'); revert.type = 'button';
      revert.dataset.revert = round.id; revert.textContent = 'Revert';
      row.append(text, revert); rounds.appendChild(row);
    }
    if (!snapshot.rounds.length) {
      const empty = document.createElement('li'); empty.textContent = 'No saved rounds yet.'; rounds.appendChild(empty);
    }
    document.getElementById('twin-running-cost').textContent = `Total spent: $${Number(cost.total).toFixed(2)}`;
    if (forceEditor || !dirty) {
      editor.value = snapshot.plan ? JSON.stringify(snapshot.plan, null, 2) : '';
      editorBase = currentRound(snapshot); dirty = false;
    }
    return snapshot;
  }

  async function rebuildCurrent() {
    const snapshot = await refresh(true);
    if (window.__twin) await window.__twin.rebuild(snapshot.plan);
    else window.location.reload(); // The first draft establishes the preview.
  }

  async function sources() {
    const data = await request('/sources');
    const host = document.getElementById('twin-sources'); host.replaceChildren();
    for (const source of data.sources) {
      const group = document.createElement('fieldset'); group.dataset.sourceId = source.id;
      group.dataset.kind = source.kind;
      const legend = document.createElement('legend'); legend.textContent = source.filename; group.appendChild(legend);
      if (source.kind === 'photo') {
        const label = document.createElement('label'), check = document.createElement('input');
        check.type = 'checkbox'; check.checked = true; check.dataset.photo = source.id;
        label.append(check, ' Use this photo'); group.appendChild(label);
      } else {
        for (let page = 1; page <= source.pages; page++) {
          const label = document.createElement('label'), check = document.createElement('input');
          check.type = 'checkbox'; check.checked = true; check.dataset.page = page;
          label.append(check, ` Page ${page} `); group.appendChild(label);
        }
        const label = document.createElement('label'), plot = document.createElement('input');
        plot.type = 'radio'; plot.name = 'twin-plot'; plot.value = source.id;
        label.append(plot, ' Use selected pages as the plot plan'); group.appendChild(label);
      }
      host.appendChild(group);
    }
    if (!data.sources.length) host.textContent = 'Upload PDF drawings and JPEG or PNG photos to draft the house.';
  }

  const close = () => { sheet.hidden = true; toggle.setAttribute('aria-expanded', 'false'); toggle.focus(); };
  toggle.addEventListener('click', async () => {
    sheet.hidden = false; toggle.setAttribute('aria-expanded', 'true');
    document.getElementById('twin-tools-close').focus();
    try { await Promise.all([refresh(), sources()]); } catch (error) { tell(error); }
  });
  document.getElementById('twin-tools-close').addEventListener('click', close);
  sheet.addEventListener('click', event => { if (event.target === sheet) close(); });
  sheet.addEventListener('keydown', event => {
    if (event.key === 'Escape') { event.preventDefault(); close(); }
    if (event.key === 'Tab') {
      const items = [...sheet.querySelectorAll('button, input, textarea, select')].filter(el => !el.disabled && !el.hidden);
      const first = items[0], last = items.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  });
  editor.addEventListener('input', () => { dirty = true; });
  document.getElementById('twin-plan-save').addEventListener('click', async event => {
    if (!reason.value.trim()) { tell(new Error('Give a reason for this hand edit before saving.')); return; }
    let plan;
    try { plan = JSON.parse(editor.value); }
    catch { tell(new Error('The plan must be valid JSON.')); return; }
    const button = event.currentTarget; button.disabled = true;
    try {
      await request('/plan', 'PUT', { plan, reason: reason.value.trim(), base: editorBase });
      reason.value = ''; await rebuildCurrent();
    } catch (error) {
      if (error.status === 409) {
        try {
          const reload = await window.promptConfirm('Plan changed elsewhere',
            'Reload it? Your unsaved text will be replaced.', 'Reload', 'Keep editing');
          if (reload) await rebuildCurrent();
        } catch (reloadError) { tell(reloadError); }
      } else tell(error);
    }
    finally { button.disabled = false; }
  });
  document.getElementById('twin-rounds').addEventListener('click', async event => {
    const button = event.target.closest('[data-revert]'); if (!button) return;
    button.disabled = true;
    try { await request('/revert', 'POST', { round: Number(button.dataset.revert) }); await rebuildCurrent(); }
    catch (error) { tell(error); }
    finally { button.disabled = false; }
  });
  document.getElementById('twin-run-director').addEventListener('click', async event => {
    if (running || drafting) return;
    const button = event.currentTarget; running = true; button.disabled = true;
    document.getElementById('twin-director-log').textContent = 'Starting art director…';
    try { await runDirector(view(), { run: runId(), onRound: () => refresh() }); }
    catch (error) { log(error.message); tell(error); }
    finally { running = false; button.disabled = false; }
  });
  document.getElementById('twin-source-upload').addEventListener('submit', async event => {
    event.preventDefault();
    const files = document.getElementById('twin-source-files'), button = document.getElementById('twin-source-send');
    button.disabled = true;
    try {
      if (!files.files.length) throw new Error('Choose a drawing or photo to upload.');
      for (const file of files.files) {
        const body = new FormData(); body.append('kind', document.getElementById('twin-source-kind').value);
        body.append('file', file); await request('/sources', 'POST', body);
      }
      files.value = '';
    } catch (error) { tell(error); }
    finally { button.disabled = false; try { await sources(); } catch (error) { tell(error); } }
  });
  document.getElementById('twin-draft').addEventListener('click', async event => {
    if (drafting || running) return;
    const button = event.currentTarget; drafting = true; button.disabled = true;
    try {
      const drawings = []; let site = null;
      for (const group of document.querySelectorAll('#twin-sources [data-kind="drawing"]')) {
        const pages = [...group.querySelectorAll('[data-page]:checked')].map(check => Number(check.dataset.page));
        if (!pages.length) continue;
        const selected = { id: group.dataset.sourceId, pages };
        if (group.querySelector('[name="twin-plot"]:checked')) site = selected;
        else drawings.push(selected);
      }
      if (!drawings.length) throw new Error('Select at least one building drawing page.');
      const photos = [...document.querySelectorAll('#twin-sources [data-photo]:checked')].map(check => check.dataset.photo);
      log('Drafting the house…');
      const response = await meteredPost('/draft', { drawings, photos, site, run: runId() });
      if (!response) { log('Draft stopped at the spend checkpoint.'); return; }
      log(`Draft saved. Cost: $${Number(response.result.cost).toFixed(2)}\n${(response.notes || []).join('\n')}`);
      await rebuildCurrent();
    } catch (error) { log(error.message); tell(error); }
    finally { drafting = false; button.disabled = false; }
  });
  document.getElementById('twin-no-plot').addEventListener('click', () => {
    sheet.querySelectorAll('[name="twin-plot"]').forEach(input => { input.checked = false; });
  });
  // Parents-only reads start when the tools sheet opens.
}
