import { active, report, request } from './api.js';
import { modelRecord, rememberImport } from '../twin_library.js';

export const CHANGED_SINCE = 'Something else changed the house since; use the timeline to go back.';

// A round step remembers the round its change left the house at (`at`). Undo and
// redo act only while the house is still at that round: a build, Argyle or
// another parent's later round is never reverted over (I5).
export function createHistory({ getRound, getBuild, canEdit, refresh, latest, signal, onError }) {
  const undo = [], redo = [];
  const el = id => document.getElementById(id);
  let pending = 0, queue = Promise.resolve();
  const enabled = () => canEdit() && !active(getBuild());
  const sameAssetStep = (stack, step) => stack.findLast(other => other !== step && other.kind === 'model-record' && other.asset === step.asset);
  function record(step) {
    const at = getRound();
    const previousModel = step.kind === 'model-record' && sameAssetStep(undo, step);
    // Like round connections, a model connection must describe consecutive
    // local states. A newer local edit cannot bridge an intervening tab's edit.
    const modelConnected = !!previousModel && previousModel.revision === (step.previousRevision ?? step.revision - 1);
    undo.push({ ...structuredClone(step), at, modelConnected, connected: undo[undo.length - 1]?.at === at });
    redo.length = 0;
    if (undo.length > 50) undo.shift();
    sync();
  }
  function sync() {
    el('rail-undo').disabled = !enabled() || !(undo.length || pending);
    el('rail-redo').disabled = !enabled() || !(redo.length || pending);
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
  function perform(work, { step } = {}) {
    return enqueue(async () => {
      const before = getRound();
      try { return await work(); }
      finally {
        const own = step?.(), start = step ? own?.before : before;
        const after = step ? own?.after : getRound();
        if (start != null && after != null && start !== after) {
          const connected = undo[undo.length - 1]?.at === start;
          undo.push({ before: start, after, at: after, connected }); redo.length = 0;
          if (undo.length > 50) undo.shift();
        }
      }
    });
  }
  async function restore(back) {
    const source = back ? undo : redo, destination = back ? redo : undo;
    if (!canEdit() || active(getBuild()) || !source.length) return;
    const step = source[source.length - 1];
    await latest?.();
    const model = step.kind === 'model-record';
    if (!model && getRound() !== step.at) {
      window.showGlobalAlert(CHANGED_SINCE);
      return;
    }
    if (model) {
      // The step owns its expected revision. Catalogue/cache refreshes must
      // never grant permission to overwrite another tab's subsequent edit.
      try {
        const result = await request('models/' + encodeURIComponent(step.asset), 'PATCH',
          { ...(back ? step.before : step.after), revision: step.revision }, '');
        step.revision = result.revision;
        rememberImport(result);
      } catch (error) {
        if (error.status !== 409) throw error;
        window.showGlobalAlert(error.message);
        await modelRecord(step.asset, { refresh: true });
        await refresh({ modelRecord: true });
        return;
      }
    } else {
      const result = await request('revert', 'POST', { round: back ? step.before : step.after }, 'twin');
      step.at = result?.round ?? null;
    }
    source.pop(); destination.push(step);
    if (model) {
      // Only the nearest local edit in either direction now expects the fresh
      // revision. Do not update any revisions on a refused PATCH.
      for (const [stack, older] of [[source, back], [destination, !back]]) {
        const adjacent = sameAssetStep(stack, step);
        if (adjacent && (older ? step.modelConnected : adjacent.modelConnected)) adjacent.revision = step.revision;
      }
    }
    // Revert writes a fresh round for the same state the next step expects.
    // Advance only that adjacent step; later outside edits still fail the guard.
    const next = source[source.length - 1];
    if (next && (!model || getRound() === step.at) && (back ? step.connected : next.connected)) next.at = step.at;
    await refresh(model ? { modelRecord: true } : undefined);
  }
  // A press made while a change is still being saved or redrawn waits its
  // turn instead of being dropped; a running build still refuses it.
  const later = back => { enqueue(() => restore(back)).catch(report); };
  el('rail-undo').addEventListener('click', () => later(true), { signal });
  el('rail-redo').addEventListener('click', () => later(false), { signal });
  document.addEventListener('keydown', event => {
    if (!(event.ctrlKey || event.metaKey) || event.altKey || event.defaultPrevented
      || event.target.closest?.('input, textarea, select, [contenteditable="true"]')
      || document.querySelector('#cc-confirm-modal:not(.hidden), #cc-input-modal:not(.hidden), #cc-choice-modal:not(.hidden), #houses-panel:not([hidden]), dialog[open]')) return;
    const key = event.key.toLowerCase();
    if (key !== 'z' && key !== 'y') return;
    event.preventDefault();
    later(key === 'z' && !event.shiftKey);
  }, { signal });
  sync();
  return { perform, record, sync, clear() { undo.length = redo.length = 0; sync(); } };
}
