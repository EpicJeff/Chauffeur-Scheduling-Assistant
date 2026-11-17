// The same lists as material_defaults.json, which services/twin_materials.py reads; a test keeps
// the two equal. Plain constants here: a JSON module import would stop the whole twin from
// loading in a browser without import attributes.
export const GRASS_IDS = ['lawn', 'grass', 'leafy_grass'];
export const GRASS_SOURCES = ['leafy_grass'];

// An explicit household parameter always wins; vegetation never belongs to a bake key.
export function materialGrass(entry, id = entry?.id) {
  return typeof entry?.params?.grass === 'boolean' ? entry.params.grass
    : GRASS_IDS.includes(id) || GRASS_SOURCES.includes(entry?.source_id);
}
