import { active, report, request } from './api.js';

export function createHistory({ getRound, getBuild, canEdit, refresh, signal }) {
  const undo = [], redo = [];
  const el = id => document.getElementById(id);
  let busy = false;
  const enabled = () => canEdit() && !active(getBuild()) && !busy;
  function sync() {
    el('rail-undo').disabled = !enabled() || !undo.length;
    el('rail-redo').disabled = !enabled() || !redo.length;
  }
  // A gesture may write several rounds (for example a split and its name).
  async function perform(work) {
    if (busy) throw new Error('Wait for the house to finish this change.');
    const before = getRound();
    busy = true; sync();
    try { return await work(); }
    finally {
      const after = getRound();
      if (before !== null && after !== null && before !== after) {
        undo.push({ before, after }); redo.length = 0;
      }
      busy = false; sync();
    }
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
  el('rail-undo').addEventListener('click', () => restore(true).catch(report), { signal });
  el('rail-redo').addEventListener('click', () => restore(false).catch(report), { signal });
  document.addEventListener('keydown', event => {
    if (!event.ctrlKey || event.altKey || event.defaultPrevented
      || event.target.closest?.('input, textarea, select, [contenteditable="true"]')
      || document.querySelector('#cc-confirm-modal:not(.hidden), #cc-input-modal:not(.hidden), #cc-choice-modal:not(.hidden), dialog[open]')) return;
    const key = event.key.toLowerCase();
    if (key !== 'z' && key !== 'y') return;
    event.preventDefault();
    restore(key === 'z' && !event.shiftKey).catch(report);
  }, { signal });
  sync();
  return { perform, sync, clear() { undo.length = redo.length = 0; sync(); } };
}
