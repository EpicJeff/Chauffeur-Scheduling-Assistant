// Resolves every (text color, background color) pair that co-occurs in a
// class list through the generated token table and reports WCAG contrast,
// for BOTH themes. This is the check that replaces "looks fine to me".
const fs = require('fs');

const css = fs.readFileSync(process.argv[2], 'utf8');
const html = fs.readFileSync(process.argv[3], 'utf8');

// --- parse theme.css into two token tables ---
function parseTheme(selectorRe) {
    const start = css.search(selectorRe);
    const body = css.slice(start, css.indexOf('}', start));
    const map = {};
    for (const m of body.matchAll(/--c-([a-z]+)-(\d+):\s*([\d ]+);/g)) {
        map[`${m[1]}-${m[2]}`] = m[3].trim().split(/\s+/).map(Number);
    }
    return map;
}
const THEMES = {
    dark: parseTheme(/:root, :root\[data-theme="dark"\]/),
    light: parseTheme(/:root\[data-theme="light"\]/),
};
// Never tokenized on purpose.
for (const t of Object.values(THEMES)) { t['white'] = [255, 255, 255]; t['black'] = [0, 0, 0]; }

const srgb = (c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
const lum = ([r, g, b]) => 0.2126 * srgb(r) + 0.7152 * srgb(g) + 0.0722 * srgb(b);
const contrast = (a, b) => {
    const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
    return (x + 0.05) / (y + 0.05);
};
// Flatten a translucent layer onto whatever sits behind it.
const over = (fg, alpha, bg) => fg.map((c, i) => Math.round(c * alpha + bg[i] * (1 - alpha)));

const COLOR = '(?:slate|gray|blue|indigo|violet|purple|pink|rose|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|white|black)';
const TEXT_RE = new RegExp(`(?:^|[\\s'"\`])text-(${COLOR})-?(\\d+)?(?:\\/(\\d+))?(?=[\\s'"\`]|$)`, 'g');
const BG_RE = new RegExp(`(?:^|[\\s'"\`])bg-(${COLOR})-?(\\d+)?(?:\\/(\\d+))?(?=[\\s'"\`]|$)`, 'g');

const key = (hue, shade) => (hue === 'white' || hue === 'black') ? hue : `${hue}-${shade || 500}`;

// Only real class lists, so we never pair a text- from one element with a
// bg- from another. Two sources qualify:
//   1. a class="..." / class='...' attribute (one element, by definition)
//   2. a bare quoted string that is ENTIRELY class tokens -- the fragments
//      passed to helpers like btn(label, cls, onclick)
const CLASS_TOKEN = /^(?:[a-z0-9:[\]/_.,%-]+|\$\{[^}]*\}|'[^']*')$/i;
const isClassList = (s) => {
    const toks = s.trim().split(/\s+/);
    return toks.length > 1 && toks.every(t => CLASS_TOKEN.test(t)) && /-/.test(s);
};
// Painted over photos/video, so the app surface behind them is irrelevant.
// Matched by content rather than line number, which drifts on every edit.
const isMediaOverlay = (s) => /bg-white\/|upload-pct/.test(s) || /\bmt-3 px-4\b/.test(s);

// `${cond ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-100'}` describes
// two mutually exclusive states. Pairing across them invents combinations
// that never render, so each branch is audited on its own.
function branches(s) {
    const m = s.match(/\$\{[^}]*?\?([^}]*)\}/);
    if (!m) return [s];
    const outside = s.replace(/\$\{[^}]*\}/g, ' ');
    const parts = m[1].split(':').map(p => (p.match(/'([^']*)'|"([^"]*)"/) || [])[1] || '');
    return parts.filter(Boolean).map(p => outside + ' ' + p);
}

const raw = [];
for (const m of html.matchAll(/class=(["'])((?:(?!\1).)*)\1/g)) {
    raw.push({ s: m[2], idx: m.index });
}
for (const m of html.matchAll(/(["'`])((?:(?!\1)[^\\\n]|\\.)*?)\1/g)) {
    if (isClassList(m[2])) raw.push({ s: m[2], idx: m.index });
}
const strings = [];
for (const { s, idx } of raw) {
    if (isMediaOverlay(s)) continue;
    branches(s).forEach(b => strings.push({ s: b, idx }));
}

const PAGE = 'gray-950';   // app background
const CARD = 'gray-900';   // the surface most text actually sits on

const findings = [];
for (const { s, idx } of strings) {
    const ln = html.slice(0, idx).split('\n').length;

    if (/^\s*(\/\/|\*)/.test(html.split('\n')[ln - 1] || '')) continue;
    const texts = [...s.matchAll(TEXT_RE)];
    const bgs = [...s.matchAll(BG_RE)];
    if (!texts.length) continue;
    // Assume the dominant surface when the element sets no background.
    const bgList = bgs.length ? bgs : [[null, 'gray', '900', null]];
    for (const t of texts) {
        const tKey = key(t[1], t[2]);
        for (const b of bgList) {
            const bKey = key(b[1], b[2]);
            for (const theme of ['light', 'dark']) {
                const T = THEMES[theme];
                if (!T[tKey] || !T[bKey]) continue;
                // Composite a translucent background over the card behind it.
                const bgAlpha = b[3] ? Number(b[3]) / 100 : 1;
                const bg = bgAlpha === 1 ? T[bKey] : over(T[bKey], bgAlpha, T[CARD]);
                const fgAlpha = t[3] ? Number(t[3]) / 100 : 1;
                const fg = fgAlpha === 1 ? T[tKey] : over(T[tKey], fgAlpha, bg);
                const ratio = contrast(fg, bg);
                // Most of this app is bold small text; 3:1 is the honest
                // floor for bold >=14px, 4.5:1 for everything else.
                const bold = /font-(bold|black|semibold)/.test(s);
                const big = /text-(lg|xl|2xl|3xl)|text-\[1[6-9]px\]|text-\[2\d px\]/.test(s);
                const floor = (bold && big) ? 3 : (bold ? 4 : 4.5);
                if (ratio < floor) {
                    findings.push({
                        theme, ratio, floor, tKey, bKey,
                        line: html.slice(0, idx).split('\n').length,
                        s: s.trim().replace(/\s+/g, ' ').slice(0, 100),
                    });
                }
            }
        }
    }
}

const seen = new Set();
const uniq = findings.filter(f => {
    const k = `${f.theme}|${f.tKey}|${f.bKey}|${f.line}`;
    if (seen.has(k)) return false; seen.add(k); return true;
});
uniq.sort((a, b) => a.ratio - b.ratio);

for (const theme of ['light', 'dark']) {
    const rows = uniq.filter(f => f.theme === theme);
    console.log(`\n===== ${theme.toUpperCase()}: ${rows.length} below floor =====`);
    rows.slice(0, 40).forEach(f => console.log(
        `  ${f.ratio.toFixed(2)}:1 (need ${f.floor})  L${f.line}  text-${f.tKey} on bg-${f.bKey}\n      ${f.s}`));
}
