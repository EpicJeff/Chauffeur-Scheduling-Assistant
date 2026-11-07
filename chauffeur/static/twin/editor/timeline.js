import { request, report } from './api.js';

export function createTimeline({ getState, render, onPreview, log, signal }) {
  const el = id => document.getElementById(id), slider = el('editor-scrub');
  let preview = null, index = null, version = 0, busy = false, loading = false, justReturned = false, currentBuild = null, scrubTimer = null;
  const rounds = () => (getState().rounds || []).filter(row => row.kind !== 'start_over');
  function sync(build) {
    if (build !== undefined) currentBuild = build;
    const marks = el('editor-time-labels'), rows = rounds();
    const signature = JSON.stringify([rows, currentBuild?.steps.map(s => [s.id, s.kind, s.level, s.level_name])]);
    if (marks.dataset.rounds !== signature) {
      marks.dataset.rounds = signature; marks.replaceChildren();
      const stages = new Set();
      rows.forEach((round, i) => {
        const button = document.createElement('button'); button.type = 'button'; button.dataset.kind = round.kind;
        const label = round.step?.label || round.note || ({ draft: 'Build', build: 'Build', edit: 'Change', hand: 'Change', revert: 'Returned to an earlier house', director: 'Art director' })[round.kind] || 'House saved';
        button.title = `Step ${i + 1} · ${label}`; button.setAttribute('aria-label', button.title);
        button.style.left = `${rows.length > 1 ? i / (rows.length - 1) * 100 : 0}%`;
        const step = currentBuild?.steps.find(s => s.id === round.step?.id);
        const stage = step ? `${step.kind}:${step.level || ''}` : round.step?.id?.split(':').slice(0, 2).join(':');
        if (['build', 'draft'].includes(round.kind) && stage && !stages.has(stage)) {
          stages.add(stage);
          const name = document.createElement('span'); name.textContent = step?.kind === 'walls' ? `${step.level_name || 'Floor'} walls` : label;
          button.append(name);
        }
        button.addEventListener('click', () => scrubTo(i).catch(report)); marks.append(button);
      });
    }
    slider.max = Math.max(0, rows.length - 1); slider.disabled = !rows.length || busy;
    if (index === null && !loading) slider.value = slider.max;
    const steps = currentBuild?.steps || [], done = steps.filter(s => s.status === 'done').length;
    el('editor-progress').max = steps.length || 1; el('editor-progress').value = done;
    const count = plan => (plan?.buildings || []).flatMap(b => [...(b.walls || []), ...(b.openings || []), ...(b.rooms || []), ...(b.roof?.sections || [])]);
    const pieces = count(preview || getState().plan), settled = pieces.filter(p => p.state !== 'ghost').length;
    el('editor-step-count').textContent = `${settled} of ${pieces.length} pieces · $${Number(getState().cost?.total || 0).toFixed(2)}`;
    el('editor-time-note').textContent = preview ? 'This earlier house is read-only. Return here adds a new step.'
      : rows.length ? 'Drag back to see an earlier house.' : 'Your build will appear here, one step at a time.';
    el('time-chip').hidden = !preview;
    el('time-actions').hidden = !preview && !justReturned;
    el('time-return').disabled = busy || loading || !preview || index === rows.length - 1;
    if (preview) el('time-chip').textContent = `Looking at step ${index + 1}`;
  }
  async function scrubTo(i) {
    clearTimeout(scrubTimer);
    const rows = rounds(); i = Math.max(0, Math.min(rows.length - 1, Math.round(i)));
    if (!rows[i]) return;
    const ticket = ++version;
    // Freeze editing before the historical request can race an edit.
    loading = true; justReturned = false; onPreview(true); sync();
    try {
      const result = await request(`rounds/${rows[i].id}`, 'GET', undefined, 'twin');
      if (ticket !== version) return;
      loading = false; preview = result.plan; index = i; slider.value = i;
      await render(); sync();
    } catch (error) { if (ticket === version) { loading = false; onPreview(!!preview); sync(); } throw error; }
  }
  async function now() {
    clearTimeout(scrubTimer);
    ++version; preview = null; index = null; loading = false; justReturned = false; onPreview(false); await render(); sync();
  }
  slider.addEventListener('input', () => {
    const i = Number(slider.value);
    clearTimeout(scrubTimer); ++version; loading = true; onPreview(true); sync();
    scrubTimer = setTimeout(() => scrubTo(i).catch(report), 120);
  }, { signal });
  slider.addEventListener('change', () => scrubTo(Number(slider.value)).catch(report), { signal });
  signal.addEventListener('abort', () => { clearTimeout(scrubTimer); ++version; }, { once: true });
  el('time-now').addEventListener('click', () => now().catch(report), { signal });
  el('time-return').addEventListener('click', async () => {
    if (busy || loading || index === null || index === rounds().length - 1) return;
    const round = rounds()[index]; if (!round) return;
    busy = true; sync();
    try {
      await request('revert', 'POST', { round: round.id }, 'twin');
      const state = await request('state'); Object.assign(getState(), state);
      log?.(`Returned to the house at step ${index + 1}.`);
      await now(); justReturned = true;
    } catch (error) { report(error); }
    finally { busy = false; sync(); }
  }, { signal });
  return { sync, scrubTo, now, preview: () => preview, roundCount: () => getState().rounds?.length || 0 };
}
