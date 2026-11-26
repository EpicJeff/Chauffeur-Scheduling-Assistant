// Porch posts as pieces. Contract shared by the generator and the editor
// (docs/superpowers/specs/2026-11-25-porch-posts-design.md). No ids are minted
// here: a post without one is named by its porch and stored order.
import { allPorches } from './gutter_presence.js';

export const POST_SIZE = { min: 0.05, max: 3, fallback: 0.5, limit: 40 };

export function postRef(porch, index) {
  return porch.columns[index].id || `post:${porch.id}:${index}`;
}

/** Every post of a building, in porch and stored order. */
export function porchPosts(building) {
  return allPorches(building).flatMap(porch => (porch.columns || []).map((piece, index) => ({
    kind: 'porch_post', id: postRef(porch, index), porchId: porch.id, buildingId: building.id, index, piece, porch,
  })));
}

export function findPost(building, ref) {
  return porchPosts(building).find(post => post.id === ref) || null;
}

/** The size most of a porch's posts have; the first stored one wins a tie. */
export function commonPostSize(porch) {
  const counts = new Map();
  for (const column of porch?.columns || []) counts.set(column.size, (counts.get(column.size) || 0) + 1);
  let best = POST_SIZE.fallback, most = 0;
  for (const [size, count] of counts) if (Number.isFinite(size) && count > most) { best = size; most = count; }
  return best;
}
