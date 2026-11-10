import { active, report, request } from './api.js';

export function createHistory({ getRound, getBuild, canEdit, refresh, signal }) {
  const undo = [], redo = [];
  const el = id => document.getElementById(id);
  let busy = false, queue = Promise.resolve();
  const enabled = () => canEdit() && !active(getBuild()) && !busy;
  function sync() {
    el('rail-undo').disabled = !enabled() || !undo.length;
    el('rail-redo').disabled = !enabled() || !redo.length;
  }
  // A gesture may write several rounds (for example a split and its name).
  function perform(work) {
    if (busy) return Promise.reject(new Error('Wait for the house to finish this change.'));
    const before = getRound();
    busy = true; sync();
    const run = (async () => {
      try { return await work(); }
      finally {
        const after = getRound();
        if (before !== null && after !== null && before !== after) {
          undo.push({ before, after }); redo.length = 0;
        }
        busy = false; sync();
      }
    })();
    queue = queue.then(() => run).catch(() => {});
    return run;
  }
  async function restore(back) {
    const source = back ? undo : redo, destination = back ? redo : undo;
    if (!enabled() || !source.length) return;
    const step = source[source.length - 1];
    busy = true; sync();
    try {
      await request('revert', 'POST', { round: back ? step.before : step.after }, 'twin');
      source.pop(); destination.push(step);
      await refresh();
    } finally { busy = false; sync(); }
  }
  // A press made while a change is still being saved or redrawn waits its
  // turn instead of being dropped; a running build still refuses it.
  const later = back => { queue = queue.then(() => restore(back)).catch(report); };
  el('rail-undo').addEventListener('click', () => later(true), { signal });
  el('rail-redo').addEventListener('click', () => later(false), { signal });
  document.addEventListener('keydown', event => {
    if (!event.ctrlKey || event.altKey || event.defaultPrevented
      || event.target.closest?.('input, textarea, select, [contenteditable="true"]')
      || document.querySelector('#cc-confirm-modal:not(.hidden), #cc-input-modal:not(.hidden), #cc-choice-modal:not(.hidden), dialog[open]')) return;
    const key = event.key.toLowerCase();
    if (key !== 'z' && key !== 'y') return;
    event.preventDefault();
    later(key === 'z' && !event.shiftKey);
  }, { signal });
  sync();
  return { perform, sync, clear() { undo.length = redo.length = 0; sync(); } };
}
