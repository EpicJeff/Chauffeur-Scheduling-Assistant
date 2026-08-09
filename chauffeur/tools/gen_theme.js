// Generates chauffeur/static/theme.css from the authoritative Tailwind
// palette embedded in the Play CDN bundle, so colors never drift from what
// the app renders. Usage:
//   curl -sSL https://cdn.tailwindcss.com -o tools/tw.js
//   node tools/gen_theme.js chauffeur/static/theme.css
// Audit afterwards:
//   node tools/audit_contrast.js chauffeur/static/theme.css chauffeur/templates/app.html
const fs = require('fs');

const bundle = fs.readFileSync(__dirname + '/tw.js', 'utf8');

const HUES = ['slate', 'blue', 'indigo', 'violet', 'purple', 'pink', 'rose',
    'red', 'orange', 'amber', 'yellow', 'lime', 'green', 'emerald',
    'teal', 'cyan', 'sky'];
const SHADES = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950];

// Pull `hue:{50:"#...",...,950:"#..."}` straight out of the bundle.
function extract(hue) {
    const re = new RegExp(hue + ':\\{' + SHADES.map(s => s + ':"(#[a-f0-9]{6})"').join(',') + '\\}');
    const m = bundle.match(re);
    if (!m) throw new Error('palette not found for ' + hue);
    const out = {};
    SHADES.forEach((s, i) => { out[s] = m[i + 1]; });
    return out;
}

const hex2ch = (h) => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16)).join(' ');

// Light mode remaps each shade by the ROLE that shade plays in this app.
// It is deliberately NOT a strict mirror: shade 400 is pale TEXT that must
// darken to 600, while shade 600 is a solid BUTTON FILL that must not move
// at all. Both can hold the same value -- they're separate variables --
// but a strict mirror would have dragged every solid button pale.
//
//   50-400  pale text      -> darken
//   500-700 solid fills    -> invariant (white text stays legible on them)
//   800-950 tinted surface -> lighten
// The surface and fill bands are fixed. The TEXT band is not: amber-600 and
// green-600 are far lighter than blue-600, so a single offset would leave
// warm hues failing on cream. Instead the text anchor is MEASURED per hue --
// the lightest shade that still clears 4.5:1 on the light card.
const MIRROR_FIXED = { 500: 500, 600: 600, 700: 700, 800: 200, 900: 100, 950: 50 };

const srgb = (c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
const lumHex = (h) => {
    const [r, g, b] = [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));
    return 0.2126 * srgb(r) + 0.7152 * srgb(g) + 0.0722 * srgb(b);
};
const contrastHex = (a, b) => {
    const [x, y] = [lumHex(a), lumHex(b)].sort((p, q) => q - p);
    return (x + 0.05) / (y + 0.05);
};

// Text sits on the card, not the page -- the card is the tighter constraint.
const LIGHT_CARD = '#f3eee6';

function textBand(palette) {
    const anchor = [600, 700, 800].find(s => contrastHex(palette[s], LIGHT_CARD) >= 4.5) || 800;
    const step = (s) => Math.min(900, s);
    return {
        400: anchor,
        300: step(anchor + 100),
        200: step(anchor + 200),
        100: 900,
        50: 900,
    };
}

// --- Neutrals -------------------------------------------------------------
// The ramp is split by ROLE at the 500/600 seam, which is how the app
// already uses it: 50-500 are text, 600-950 are surfaces. Each band is
// internally ordered and inverts cleanly; the seam itself is deliberately
// non-monotonic (light-mode gray-500 is darker than gray-600) because a
// muted LABEL and a pressed SURFACE want opposite things from light mode.
const GRAY_DARK = {
    // Text band — unchanged from Tailwind neutral, which is what ships today.
    50: '#fafafa', 100: '#f5f5f5', 200: '#e5e5e5', 300: '#d4d4d4',
    400: '#a3a3a3', 500: '#737373',
    // Surface band — the app's existing custom values, preserved exactly.
    600: '#525252', 700: '#404040', 800: '#262626', 900: '#171717', 950: '#0a0a0a',
};
const GRAY_LIGHT = {
    // Text band, warm near-blacks. The band is tuned against the CARD
    // (#f3eee6), not the page -- cards are darker, so they're the binding
    // constraint, and tuning against the page leaves muted labels at 4.38:1.
    // 500 is the muted label and clears AA at 4.77:1; 300/400 step down
    // evenly from it so the tiers stay tellable apart.
    50: '#1c1917', 100: '#241f1c', 200: '#3d362f', 300: '#4a4238',
    400: '#5c5145', 500: '#6f6558',
    // Surface band, warm creams. 950 is the page; cards sit slightly DARKER
    // than the page rather than whiter — the Skylight/Hearth move, and it
    // keeps every existing elevation relationship pointing the same way.
    600: '#c9bdaa', 700: '#dcd3c5', 800: '#eae3d8', 900: '#f3eee6', 950: '#faf7f2',
};

const lines = [];
lines.push('/* Chauffeur PWA theme tokens — GENERATED, do not hand-edit.');
lines.push(' * Source: scratchpad/gen_theme.js against the Tailwind Play CDN palette.');
lines.push(' *');
lines.push(' * Every color Tailwind resolves in the PWA points at one of these');
lines.push(' * channel triples, so flipping [data-theme] restyles the whole app');
lines.push(' * without touching a single utility class. Values are space-separated');
lines.push(' * RGB channels so `rgb(var(--x) / <alpha-value>)` keeps opacity');
lines.push(' * modifiers (bg-amber-500/10, border-blue-500/50) working.');
lines.push(' */');
lines.push('');

// Elevation shadows. Dark mode leans on near-black at high alpha because it
// has no ambient light to work with; on a cream ground the same values read
// as grime, so light mode uses a warm, much softer cast.
const SHADOWS_DARK = {
    nav: '0 -4px 12px rgb(0 0 0 / 0.40)',
    sheet: '0 -10px 40px rgb(0 0 0 / 0.50)',
};
const SHADOWS_LIGHT = {
    nav: '0 -4px 12px rgb(120 105 85 / 0.10)',
    sheet: '0 -10px 40px rgb(120 105 85 / 0.18)',
};

function block(selector, grayMap, mirrored, comment) {
    const out = [];
    if (comment) out.push(comment);
    out.push(selector + ' {');
    out.push('  color-scheme: ' + (mirrored ? 'light' : 'dark') + ';');
    out.push('');
    out.push('  /* elevation */');
    const sh = mirrored ? SHADOWS_LIGHT : SHADOWS_DARK;
    Object.keys(sh).forEach(k => out.push(`  --shadow-${k}: ${sh[k]};`));
    out.push('');
    out.push('  /* neutrals */');
    SHADES.forEach(s => out.push(`  --c-gray-${s}: ${hex2ch(grayMap[s])};`));
    HUES.forEach(hue => {
        const p = extract(hue);
        const map = mirrored ? Object.assign({}, MIRROR_FIXED, textBand(p)) : null;
        out.push('');
        out.push(mirrored
            ? `  /* ${hue} — text anchor ${map[400]} (${contrastHex(p[map[400]], LIGHT_CARD).toFixed(2)}:1 on card) */`
            : `  /* ${hue} */`);
        SHADES.forEach(s => {
            const src = mirrored ? map[s] : s;
            out.push(`  --c-${hue}-${s}: ${hex2ch(p[src])};`);
        });
    });
    out.push('}');
    return out.join('\n');
}

lines.push(block(':root, :root[data-theme="dark"]', GRAY_DARK, false,
    '/* Dark is the default and is byte-identical to the pre-token app. */'));
lines.push('');
lines.push(block(':root[data-theme="light"]', GRAY_LIGHT, true,
    '/* Light: neutrals get a warm cream ramp, accents mirror across shade 500. */'));
lines.push('');
lines.push([
    '/* Elevation utilities. Tailwind never emits these names, so load order',
    ' * between this file and the Play CDN\'s injected styles does not matter. */',
    '.shadow-nav { box-shadow: var(--shadow-nav); }',
    '.shadow-sheet { box-shadow: var(--shadow-sheet); }',
].join('\n'));
lines.push('');

fs.writeFileSync(process.argv[2], lines.join('\n') + '\n');
console.log('wrote', process.argv[2], lines.join('\n').length, 'bytes');
