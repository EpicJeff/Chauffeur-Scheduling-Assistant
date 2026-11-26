import { visibilityKind } from '../twin_visibility.js';
import { porchPosts, findPost } from '../porch_posts.js';

export const existingPostIds = plan => (plan?.buildings || []).flatMap(b => porchPosts(b).map(p => p.id));
export const postParentId = (building, id) => (building && findPost(building, id)?.porchId) || null;

const fields = ['hidden', 'locked', 'hiddenKinds', 'lockedKinds'];
export function createVisibility({ houseId = 'current', storage } = {}) {
  if (storage === undefined) { try { storage = globalThis.localStorage; } catch { storage = null; } }
  let house = houseId || 'current', state;
  const listeners = new Set(), key = () => `chauffeur.editor.visibility.${house}`;
  function read() {
    try { const value = JSON.parse(storage?.getItem(key()) || 'null'); return value && typeof value === 'object' ? value : null; }
    catch { return null; }
  }
  const load = value => Object.fromEntries(fields.map(field => [field,
    new Set(Array.isArray(value?.[field]) ? value[field].filter(id => typeof id === 'string') : [])]));
  state = load(read());
  const snapshot = () => Object.fromEntries(fields.map(field => [field, [...state[field]]]));
  function changed() {
    try { storage?.setItem(key(), JSON.stringify(snapshot())); } catch { /* Private mode/quota: keep working in memory. */ }
    for (const fn of listeners) fn(snapshot());
  }
  function toggle(field, id, on) {
    if (!id) return;
    if (field.endsWith('Kinds')) id = visibilityKind(id);
    if (state[field].has(id) === on) return;
    if (on) state[field].add(id); else state[field].delete(id);
    changed();
  }
  const isHidden = (id, kind) => state.hidden.has(id) || state.hiddenKinds.has(visibilityKind(kind));
  const isLocked = (id, kind) => state.locked.has(id) || state.lockedKinds.has(visibilityKind(kind));
  return {
    hide: id => toggle('hidden', id, true), show: id => toggle('hidden', id, false),
    lock: id => toggle('locked', id, true), unlock: id => toggle('locked', id, false),
    hideKind: kind => toggle('hiddenKinds', kind, true), showKind: kind => toggle('hiddenKinds', kind, false),
    lockKind: kind => toggle('lockedKinds', kind, true), unlockKind: kind => toggle('lockedKinds', kind, false),
    setMembers(refs, values) {
      let dirty = false;
      for (const field of ['hidden', 'locked']) if (typeof values[field] === 'boolean') for (const ref of refs) {
        const id = ref.pieceId ?? ref.id;
        if (!values[field] && state[field + 'Kinds'].delete(visibilityKind(ref.visibilityKind || ref.kind))) dirty = true;
        if (!id || state[field].has(id) === values[field]) continue;
        if (values[field]) state[field].add(id); else state[field].delete(id);
        dirty = true;
      }
      if (dirty) changed();
    },
    showAll() { state.hidden.clear(); state.hiddenKinds.clear(); changed(); },
    isHidden, isLocked,
    isPickable(candidate) {
      const id = candidate?.id ?? candidate?.pieceId, kind = candidate?.visibilityKind ?? candidate?.kind;
      const building = candidate?.building ?? candidate?.buildingId;
      const parent = candidate?.parentPieceId ?? candidate?.porchId;
      return !!candidate && !isHidden(id, kind) && !isLocked(id, kind)
        && (!parent || !isHidden(parent) && !isLocked(parent))
        && !isHidden(building) && !isLocked(building) && !isHidden(candidate.level) && !isLocked(candidate.level);
    },
    forHouse(nextHouse, existingIds) {
      const previous = snapshot();
      const switched = house !== (nextHouse || 'current'); house = nextHouse || 'current';
      // A never-opened save inherits matching ids; a previously opened save
      // restores its own state. Prune only on load, never during a local edit.
      state = load(switched ? read() || previous : previous);
      const existing = new Set(existingIds);
      for (const field of ['hidden', 'locked']) for (const id of state[field]) if (!existing.has(id)) state[field].delete(id);
      changed();
    },
    subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); }, snapshot,
  };
}
