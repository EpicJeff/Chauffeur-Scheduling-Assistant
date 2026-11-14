// Case-insensitive suffix table (including Poly Haven and ambientCG names):
// basecolor|albedo|diff|diffuse|color|col → base_color
// normalgl|nor_gl|normal → normal (gl)
// normaldx|nor_dx → normal (dx)
// rough|roughness → roughness
// metal|metalness|metallic → metalness
// ao|occlusion|ambientocclusion → ao
// arm|orm → orm
// height|disp|displacement → height
const suffixes = [
  ['basecolor|albedo|diff|diffuse|color|col', 'base_color'],
  ['normalgl|nor_gl|normal', 'normal', 'gl'],
  ['normaldx|nor_dx', 'normal', 'dx'],
  ['rough|roughness', 'roughness'],
  ['metal|metalness|metallic', 'metalness'],
  ['ao|occlusion|ambientocclusion', 'ao'],
  ['arm|orm', 'orm'],
  ['height|disp|displacement', 'height'],
].map(([suffix, slot, convention]) => [new RegExp(`(?:^|[_-])(?:${suffix})$`, 'i'),
  convention ? { slot, convention } : { slot }]);

export function slotForFilename(name) {
  // Poly Haven puts its resolution after the suffix: brick_nor_gl_2k.png.
  const stem = name.replace(/\.[^.]+$/, '').replace(/[_-]\d+k$/i, '');
  const match = suffixes.find(([pattern]) => pattern.test(stem));
  return match ? { ...match[1] } : null;
}
