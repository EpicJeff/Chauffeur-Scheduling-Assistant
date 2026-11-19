import { request, report, active } from './api.js';

export function createTimeline({ getState, render, onPreview, log, signal, canScrub = () => true, dock }) {
  const el = id => document.getElementById(id);
  let preview = null, version = 0, busy = false, loading = false, justReturned = false, currentBuild = null, selected = null;
  const rounds = () => (getState().rounds || []).slice(-50).filter(row => row.kind !== 'start_over');
  function sync(build) {
    if (build !== undefined) currentBuild = build;
    const marks = el('editor-history-list'), rows = rounds();
    const current = getState().current_round ?? [...(getState().rounds || [])].reverse().find(r => !r.stale)?.id;
    const signature = JSON.stringify([rows, current, selected, busy, canScrub()]);
    if (marks.dataset.rounds !== signature) {
      marks.dataset.rounds = signature; marks.replaceChildren();
      [...rows].reverse().forEach(round => {
        const button = document.createElement('button'); button.type = 'button'; button.dataset.kind = round.kind;
        button.dataset.round = round.id;
        const label = round.step?.label || round.note || ({ draft: 'Build', build: 'Build', edit: 'Change', hand: 'Change', revert: 'Returned to an earlier house', director: 'Art director' })[round.kind] || 'House saved';
        button.textContent = `${label}${round.id === current ? ' · Current' : ''}`;
        button.setAttribute('aria-pressed', String(round.id === selected));
        if (round.id === current) button.setAttribute('aria-current', 'step');
        button.disabled = busy || !canScrub();
        button.addEventListener('click', () => previewRound(round).catch(report));
        const item = document.createElement('li'); item.append(button); marks.append(item);
      });
    }
    const steps = currentBuild?.steps || [], done = steps.filter(s => s.status === 'done').length;
    el('editor-progress').max = steps.length || 1; el('editor-progress').value = done;
    const count = plan => (plan?.buildings || []).flatMap(b => [...(b.walls || []), ...(b.openings || []), ...(b.rooms || []), ...(b.roof?.sections || [])]);
    const pieces = count(preview || getState().plan), settled = pieces.filter(p => p.state !== 'ghost').length;
    el('editor-step-count').textContent = `${settled} of ${pieces.length} pieces · $${Number(getState().cost?.total || 0).toFixed(2)}`;
    el('editor-history-note').textContent = preview ? 'This earlier house is read-only. Return to this house adds a new step.'
      : rows.length ? 'Choose a step to see an earlier house.' : 'Your build will appear here, one step at a time.';
    el('time-chip').hidden = !preview;
    el('time-actions').hidden = !preview && !justReturned;
    el('time-return').disabled = busy || loading || active(currentBuild) || !preview || selected === current;
    if (preview) el('time-chip').textContent = `Looking at step ${selected}`;
  }
  async function scrubTo(i) {
    const rows = rounds(); i = Math.max(0, Math.min(rows.length - 1, Math.round(i)));
    if (!rows[i]) return;
    return previewRound(rows[i]);
  }
  async function previewRound(round) {
    if (!canScrub() || busy) return;
    const ticket = ++version;
    el('editor-history').open = true;
    el('editor-history').scrollIntoView({ block: 'nearest' });
    // Freeze editing before the historical request can race an edit.
    loading = true; justReturned = false; onPreview(true); sync();
    try {
      const result = await request(`rounds/${round.id}`, 'GET', undefined, 'twin');
      if (ticket !== version) return;
      loading = false; preview = result.plan; selected = round.id;
      await render(); sync();
    } catch (error) {
      if (ticket !== version) return;
      loading = false;
      if (error.status === 404) { await missing(); return; }
      onPreview(!!preview); sync(); throw error;
    }
  }
  async function now() {
    ++version; preview = null; selected = null; loading = false; justReturned = false; onPreview(false); await render(); sync();
  }
  async function missing() {
    const state = await request('state'); Object.assign(getState(), state);
    await now(); window.showGlobalAlert('That step is no longer kept.');
  }
  signal.addEventListener('abort', () => { ++version; }, { once: true });
  el('time-now').addEventListener('click', () => now().catch(report), { signal });
  el('time-return').addEventListener('click', async () => {
    if (busy || loading || active(currentBuild) || selected === null || selected === (getState().current_round ?? rounds().findLast(r => !r.stale)?.id)) return;
    const round = selected;
    busy = true; sync();
    try {
      await request('revert', 'POST', { round }, 'twin');
      const state = await request('state'); Object.assign(getState(), state);
      log?.(`Returned to the house at step ${round}.`);
      await now(); justReturned = true;
    } catch (error) { if (error.status === 404) await missing(); else report(error); }
    finally { busy = false; sync(); }
  }, { signal });
  return { sync, scrubTo, now, preview: () => preview, roundCount: () => rounds().length };
}
