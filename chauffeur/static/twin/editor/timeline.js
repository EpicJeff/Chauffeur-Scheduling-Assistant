import { request, report } from './api.js';

export function createTimeline({ getState, render, onPreview, signal }) {
  const el = id => document.getElementById(id), slider = el('editor-scrub');
  let preview = null, index = null, version = 0, busy = false, currentBuild = null;
  const rounds = () => (getState().rounds || []).filter(row => row.kind !== 'start_over');
  function sync(build) {
    if (build !== undefined) currentBuild = build;
    const marks = el('editor-time-labels'), rows = rounds();
    const signature = JSON.stringify(rows);
    if (marks.dataset.rounds !== signature) {
      marks.dataset.rounds = signature; marks.replaceChildren();
      rows.forEach((round, i) => {
        const button = document.createElement('button'); button.type = 'button'; button.dataset.kind = round.kind;
        button.textContent = round.step?.label || round.note || `${round.kind === 'draft' ? 'Build' : round.kind} ${i + 1}`;
        button.title = `Step ${i + 1} · ${round.kind}`;
        button.addEventListener('click', () => scrubTo(i).catch(report)); marks.append(button);
      });
    }
    slider.max = Math.max(0, rows.length - 1); slider.disabled = !rows.length || busy;
    if (index === null) slider.value = slider.max;
    const steps = currentBuild?.steps || [], done = steps.filter(s => s.status === 'done').length;
    el('editor-progress').max = steps.length || 1; el('editor-progress').value = done;
    const count = plan => (plan?.buildings || []).flatMap(b => [...(b.walls || []), ...(b.openings || []), ...(b.rooms || []), ...(b.roof?.sections || [])]);
    const pieces = count(preview || getState().plan), settled = pieces.filter(p => p.state !== 'ghost').length;
    el('editor-step-count').textContent = `${settled} of ${pieces.length} pieces · $${Number(getState().cost?.total || 0).toFixed(2)}`;
    el('editor-time-note').textContent = preview ? 'This earlier house is read-only. Return here adds a new step.'
      : rows.length ? 'Drag back to see an earlier house.' : 'Your build will appear here, one step at a time.';
    el('time-chip').hidden = !preview;
    el('time-actions').hidden = !preview;
    el('time-return').disabled = busy || !preview;
    if (preview) el('time-chip').textContent = `Looking at step ${index + 1}`;
  }
  async function scrubTo(i) {
    const rows = rounds(); i = Math.max(0, Math.min(rows.length - 1, Math.round(i)));
    if (!rows[i]) return;
    const ticket = ++version;
    // Freeze editing before the historical request can race an edit.
    onPreview(true);
    try {
      const result = await request(`rounds/${rows[i].id}`, 'GET', undefined, 'twin');
      if (ticket !== version) return;
      preview = result.plan; index = i; slider.value = i;
      await render(); sync();
    } catch (error) { if (ticket === version) onPreview(!!preview); throw error; }
  }
  async function now() {
    ++version; preview = null; index = null; onPreview(false); await render(); sync();
  }
  slider.addEventListener('input', () => scrubTo(Number(slider.value)).catch(report), { signal });
  el('time-now').addEventListener('click', () => now().catch(report), { signal });
  el('time-return').addEventListener('click', async () => {
    if (busy || index === null) return;
    const round = rounds()[index]; if (!round) return;
    busy = true; sync();
    try {
      await request('revert', 'POST', { round: round.id }, 'twin');
      // Keep the preview until Back to now; the appended round is read fresh.
      const state = await request('state'); Object.assign(getState(), state); await render(); sync();
    } catch (error) { report(error); }
    finally { busy = false; sync(); }
  }, { signal });
  return { sync, scrubTo, now, preview: () => preview, roundCount: () => getState().rounds?.length || 0 };
}
