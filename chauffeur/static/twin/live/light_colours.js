const clamp = (value, max = 255) => Math.max(0, Math.min(max, value));
// Colour words an effect name may carry. A vocabulary, not a vendor table: any
// integration that names an effect by its colour resolves with no configuration.
const COLOUR_WORDS = {red: [255, 0, 0], green: [0, 255, 0], blue: [0, 0, 255], white: [255, 255, 255],
  magenta: [255, 0, 255], purple: [160, 32, 240], violet: [143, 0, 255], indigo: [75, 0, 130],
  lavender: [181, 126, 220], pink: [255, 105, 180], cyan: [0, 255, 255], aqua: [0, 255, 255],
  teal: [0, 128, 128], turquoise: [64, 224, 208], yellow: [255, 255, 0], amber: [255, 191, 0],
  orange: [255, 128, 0], gold: [255, 215, 0], lime: [191, 255, 0]};
const triple = (value, n = 3) => Array.isArray(value) && value.length >= n && value.slice(0, n).every(Number.isFinite);

export function hsRgb([h, s]) {
  const sat = clamp(s, 100) / 100, hue = ((h % 360) + 360) % 360 / 60;
  const x = 1 - Math.abs(hue % 2 - 1);
  const base = [[1, x, 0], [x, 1, 0], [0, 1, x], [0, x, 1], [x, 0, 1], [1, 0, x]][Math.floor(hue) % 6];
  return base.map(value => Math.round(255 * (1 - sat + sat * value)));
}

function xyRgb([x, y]) {
  if (!(y > 0)) return null;
  // CIE xy at full luminance through the wide-gamut D65 matrix, scaled to the brightest channel.
  const X = x / y, Z = (1 - x - y) / y;
  const linear = [1.656492 * X - .354851 - .255038 * Z, -.707196 * X + 1.655397 + .036152 * Z,
    .051713 * X - .121364 + 1.01153 * Z].map(value => Math.max(0, value));
  const peak = Math.max(...linear);
  if (!(peak > 0)) return null;
  return linear.map(value => value / peak)
    .map(value => Math.round(255 * (value <= .0031308 ? 12.92 * value : 1.055 * Math.pow(value, 1 / 2.4) - .055)));
}

export function effectRgb(effect) {
  if (typeof effect !== 'string') return null;
  // The last colour word wins, so 'Deep Blue' and 'Blue Green' read as their head noun.
  const word = effect.toLowerCase().split(/[^a-z]+/).filter(part => Object.hasOwn(COLOUR_WORDS, part)).pop();
  return word ? [...COLOUR_WORDS[word]] : null;
}

// The colour a light reports, most specific first: an explicit colour attribute, then an
// effect named by its colour, then a colour temperature, then warm white.
function reportedColour(attributes = {}) {
  const { rgb_color: rgb, hs_color: hs, xy_color: xy, effect, color_temp_kelvin: kelvin, color_temp: mireds } = attributes || {};
  if (triple(rgb)) return rgb.slice(0, 3).map(value => Math.round(clamp(value)));
  if (triple(hs, 2)) return hsRgb(hs);
  const named = (triple(xy, 2) && xyRgb(xy)) || effectRgb(effect);
  if (named) return named;
  const temperature = Number(kelvin) > 0 ? Number(kelvin) : Number(mireds) > 0 ? 1e6 / Number(mireds) : null;
  if (!Number.isFinite(temperature) || temperature === null) return null;
  // Black-body approximation, with HA's temperatures expressed in kelvin.
  const t = Math.max(1000, Math.min(40000, temperature)) / 100;
  return [t <= 66 ? 255 : 329.698727446 * Math.pow(t - 60, -.1332047592),
    t <= 66 ? 99.4708025861 * Math.log(t) - 161.1195681661 : 288.1221695283 * Math.pow(t - 60, -.0755148492),
    t >= 66 ? 255 : t <= 19 ? 0 : 138.5177312231 * Math.log(t - 10) - 305.0447927307]
    .map(value => Math.round(clamp(value)));
}

// Stored looks are untrusted on the client too; ignore a malformed entry in full.
const rgbTriple = value => Array.isArray(value) && value.length === 3 && Array.from(value).every(v => Number.isInteger(v) && v >= 0 && v <= 255);
export const validPalette = value => Array.isArray(value) && value.length >= 1 && value.length <= 4 && Array.from(value).every(rgbTriple);
function validLook(look) {
  if (!look || typeof look !== 'object' || Array.isArray(look) || Object.keys(look).some(k => !['colour', 'effects'].includes(k))) return false;
  if ('colour' in look && !rgbTriple(look.colour)) return false;
  if ('effects' in look && (!look.effects || typeof look.effects !== 'object' || Array.isArray(look.effects)
    || Object.keys(look.effects).length > 64 || Object.entries(look.effects).some(([name, palette]) => !name.trim() || name.length > 80 || !validPalette(palette)))) return false;
  return true;
}
const decode = channel => { const c = channel / 255; return c <= .04045 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4; };
const encode = c => Math.round(255 * (c <= .0031308 ? c * 12.92 : 1.055 * c ** (1 / 2.4) - .055));
export const averageColour = palette => [0, 1, 2].map(i => encode(palette.reduce((sum, rgb) => sum + decode(rgb[i]), 0) / palette.length));
export function paletteColour(palette, position) {
  const stop = Math.max(0, Math.min(1, position)) * (palette.length - 1), i = Math.floor(stop), t = stop - i;
  return palette[i].map((v, k) => encode(decode(v) * (1 - t) + decode(palette[Math.min(i + 1, palette.length - 1)][k]) * t));
}
export function effectPalette(effect, look) {
  if (typeof effect !== 'string' || !validLook(look)) return null;
  const key = effect.trim().toLowerCase();
  const entry = Object.entries(look.effects || {}).find(([name]) => name.trim().toLowerCase() === key);
  return entry ? entry[1].map(rgb => [...rgb]) : null;
}
export function resolveLightColour(attributes = {}, look, domain = 'light') {
  const fixed = validLook(look) && look.colour;
  if (['switch', 'input_boolean', 'fan'].includes(domain)) return {rgb: fixed ? [...fixed] : reportedColour({color_temp_kelvin: 2700})};
  if (domain === 'media_player') return {rgb: reportedColour({color_temp_kelvin: 6500})};
  const palette = effectPalette(attributes?.effect, look);
  if (palette) return {rgb: averageColour(palette), ...(palette.length > 1 ? {palette} : {})};
  return {rgb: reportedColour(attributes) || (fixed ? [...fixed] : [255, 241, 201])};
}
// Keep the original one-argument API (and its exact automatic colours).
export const lightColor = (attributes = {}, look) => resolveLightColour(attributes, look).rgb;
