export const DRAG_THRESHOLD_PX = 3, HANDLE_HIT_PX = 16, CYCLE_SLOP_PX = 4;

const key = ({ kind, building = null, id }) => JSON.stringify([kind, building, id]);

export function createPicker({ sources, isPickable = () => true }) {
  let previous = null;
  function at(x, y) {
    const seen = new Set();
    return sources.flatMap(source => source(x, y)).filter(isPickable)
      .sort((a, b) => a.distance - b.distance).filter(candidate => {
        const id = key(candidate); if (seen.has(id)) return false;
        seen.add(id); return true;
      });
  }
  function next(x, y) {
    const candidates = at(x, y), keys = candidates.map(key);
    const cycle = previous && Math.hypot(x - previous.x, y - previous.y) <= CYCLE_SLOP_PX
      && keys.length === previous.keys.length && keys.every((id, i) => id === previous.keys[i]);
    const index = cycle && keys.length ? (previous.index + 1) % keys.length : 0;
    return { x, y, keys, index, candidate: candidates[index] || null };
  }
  return {
    at,
    click(x, y) { const result = next(x, y); previous = result; return result.candidate; },
    peek(x, y) { return next(x, y).candidate; },
    reset() { previous = null; },
  };
}
