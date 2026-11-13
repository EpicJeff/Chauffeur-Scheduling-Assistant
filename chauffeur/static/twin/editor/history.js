import { active, report, request } from './api.js';

export const CHANGED_SINCE = 'Something else changed the house since; use the timeline to go back.';

// A step remembers the round its change left the house at (`at`). Undo and
// redo act only while the house is still at that round: a build, Argyle or
// another parent's later round is never reverted over (I5).
export function createHistory({ getRound, getBuild, canEdit, refresh, latest, signal, onError }) {
  const undo = [], redo = [];
  const el = id => document.getElementById(id);
  let pending = 0, queue = Promise.resolve();
  const enabled = () => canEdit() && !active(getBuild()) && !pending;
  function sync() {
    el('rail-undo').disabled = !enabled() || !undo.length;
    el('rail-redo').disabled = !enabled() || !redo.length;
  }
  function enqueue(work) {
    ++pending; sync();
    const run = queue.then(work).catch(error => {
      onError?.(error); throw error;
    }).finally(() => { --pending; sync(); });
    // Keep the lane usable after a refusal; the caller still gets its rejection.
    queue = run.catch(() => {});
    return run;
  }
  // A gesture may write several rounds (for example a split and its name).
  // Capture its starting round when it runs, after earlier saves and redraws.
  function perform(work) {
    return enqueue(async () => {
      const before = getRound();
      try { return await work(); }
      finally {
        const after = getRound();
        if (before !== null && after !== null && before !== after) {
          const connected = undo[undo.length - 1]?.at === before;
          undo.push({ before, after, at: after, connected }); redo.length = 0;
        }
      }
    });
  }
  async function restore(back) {
    const source = back ? undo : redo, destination = back ? redo : undo;
    if (!canEdit() || active(getBuild()) || !source.length) return;
    const step = source[source.length - 1];
    await latest?.();
    if (getRound() !== step.at) {
      window.showGlobalAlert(CHANGED_SINCE);
      return;
    }
    const result = await request('revert', 'POST', { round: back ? step.before : step.after }, 'twin');
    step.at = result?.round ?? null;
    source.pop(); destination.push(step);
    // Revert writes a fresh round for the same state the next step expects.
    // Advance only that adjacent step; later outside edits still fail the guard.
    const next = source[source.length - 1];
    if (next && (back ? step.connected : next.connected)) next.at = step.at;
    await refresh();
  }
  // A press made while a change is still being saved or redrawn waits its
  // turn instead of being dropped; a running build still refuses it.
  const later = back => { enqueue(() => restore(back)).catch(report); };
  el('rail-undo').addEventListener('click', () => later(true), { signal });
  el('rail-redo').addEventListener('click', () => later(false), { signal });
  document.addEventListener('keydown', event => {
    if (!event.ctrlKey || event.altKey || event.defaultPrevented
      || event.target.closest?.('input, textarea, select, [contenteditable="true"]')
      || document.querySelector('#cc-confirm-modal:not(.hidden), #cc-input-modal:not(.hidden), #cc-choice-modal:not(.hidden), #houses-panel:not([hidden]), dialog[open]')) return;
    const key = event.key.toLowerCase();
    if (key !== 'z' && key !== 'y') return;
    event.preventDefault();
    later(key === 'z' && !event.shiftKey);
  }, { signal });
  sync();
  return { perform, sync, clear() { undo.length = redo.length = 0; sync(); } };
}
