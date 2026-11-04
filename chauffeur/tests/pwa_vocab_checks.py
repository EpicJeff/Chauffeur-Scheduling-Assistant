"""The adult vocabulary, measured (slice 7 of the reimagined PWA).

`check_skin(page, host, ...)` reads the computed styles of a surface that
claims the adult vocabulary and reports what does not hold: the title's type,
the cards' corners / borders / fill, the one raised card, horizontal overflow,
and the contrast of every visible line of text against the background it is
actually drawn on.

Contrast is a measurement, not a list of classes: the effective background of
a text element composites each ancestor's background colour, outermost first,
over the wash (`--pwa-sky-mid`; an ancestor painted with a gradient is the
wash again), and the text colour is weighted by its own alpha and every
ancestor's opacity. Anything under 4.5:1 is a failure with its text and a
selector, so a grey the shared CSS missed is named rather than squinted at.

Skipped, by design: the map canvas (`#family-map`), disabled controls,
`aria-hidden` subtrees, SVG text, options, text with no letter or digit
(emoji, glyphs), and text drawn over an image (`url(...)` backgrounds).

No side effects at import; any live test may share it.
"""

CHECK = r"""({host, title, cards, raised}) => {
    const out = {checked: 0, failures: [], problems: [], skipped: 0};
    const root = document.querySelector(host);
    if (!root || !root.checkVisibility()) { out.problems.push('host not visible: ' + host); return out; }
    const probe = document.createElement('span');
    probe.style.display = 'none';
    document.body.append(probe);
    const parse = value => {
        const s = String(value || '').trim();
        if (!s || s === 'transparent') return [0, 0, 0, 0];
        let m = s.match(/^color\(srgb\s+([\d.e+-]+)\s+([\d.e+-]+)\s+([\d.e+-]+)(?:\s*\/\s*([\d.e+-]+))?\)$/);
        if (m) return [m[1] * 255, m[2] * 255, m[3] * 255, m[4] === undefined ? 1 : +m[4]];
        m = s.match(/^rgba?\(([^)]+)\)$/);
        if (m) {
            const p = m[1].split(/[\s,\/]+/).filter(Boolean).map(Number);
            return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1];
        }
        return null;
    };
    const resolve = value => { probe.style.color = ''; probe.style.color = value; return parse(getComputedStyle(probe).color); };
    const token = name => resolve(getComputedStyle(document.documentElement).getPropertyValue(name).trim());
    const same = (a, b) => !!a && !!b && a.every((v, i) => Math.abs(v - b[i]) <= (i === 3 ? 0.02 : 2));
    const over = (top, base) => {
        const a = top[3];
        return [0, 1, 2].map(i => top[i] * a + base[i] * (1 - a)).concat(1);
    };
    const lum = c => c.slice(0, 3).map(v => v / 255)
        .map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4)
        .reduce((s, v, i) => s + v * [.2126, .7152, .0722][i], 0);
    const ratio = (a, b) => (Math.max(lum(a), lum(b)) + .05) / (Math.min(lum(a), lum(b)) + .05);
    const describe = el => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '')
        + [...el.classList].slice(0, 4).map(c => '.' + c.replace(/[^\w-]/g, '\\$&')).join('');
    const sky = token('--pwa-sky-mid') || [241, 242, 250, 1];

    function backgroundOf(el) {
        const chain = [];
        for (let n = el; n && n.nodeType === 1; n = n.parentElement) chain.unshift(n);
        let base = sky.slice();
        for (const n of chain) {
            const cs = getComputedStyle(n);
            if (/url\(/.test(cs.backgroundImage)) return null;          // text over a picture
            if (/gradient/.test(cs.backgroundImage)) base = sky.slice();
            const bg = parse(cs.backgroundColor);
            if (bg && bg[3] > 0) base = over(bg, base);
        }
        return base;
    }

    function opacityOf(el) {
        let o = 1;
        for (let n = el; n && n.nodeType === 1; n = n.parentElement) o *= parseFloat(getComputedStyle(n).opacity || '1');
        return o;
    }

    const skip = '#family-map, [disabled], [aria-disabled="true"], [aria-hidden="true"], svg, option, script, style, template';
    for (const el of root.querySelectorAll('*')) {
        if (el.closest(skip)) continue;
        const own = [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join(' ').trim();
        if (!own || !/[\p{L}\p{N}]/u.test(own)) continue;
        if (!el.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})) continue;
        const rect = el.getBoundingClientRect();
        if (rect.width < 1 || rect.height < 1) continue;
        const bg = backgroundOf(el);
        if (!bg) { out.skipped++; continue; }
        const fg = parse(getComputedStyle(el).color);
        if (!fg) { out.skipped++; continue; }
        const text = over([fg[0], fg[1], fg[2], fg[3] * opacityOf(el)], bg);
        const r = ratio(text, bg);
        out.checked++;
        if (r < 4.5) out.failures.push({text: own.slice(0, 60), ratio: Math.round(r * 100) / 100, selector: describe(el)});
    }

    if (title) {
        const t = document.querySelector(title);
        if (!t || !t.checkVisibility()) out.problems.push('title not visible: ' + title);
        else {
            const cs = getComputedStyle(t);
            if (cs.fontSize !== '34px') out.problems.push(`title font-size ${cs.fontSize} (want 34px)`);
            if (cs.fontWeight !== '700') out.problems.push(`title font-weight ${cs.fontWeight} (want 700)`);
        }
    }
    if (cards) {
        const card = token('--pwa-card');
        const seen = [...root.querySelectorAll(cards)].filter(e => e.checkVisibility());
        if (!seen.length) out.problems.push('no visible card: ' + cards);
        for (const c of seen) {
            const cs = getComputedStyle(c);
            const borders = ['Top', 'Right', 'Bottom', 'Left'].map(s => parseFloat(cs['border' + s + 'Width']));
            if (borders.some(w => w > 0)) out.problems.push(`${describe(c)} has a border ${borders.join('/')}`);
            if (parseFloat(cs.borderTopLeftRadius) < 18) out.problems.push(`${describe(c)} radius ${cs.borderTopLeftRadius} (want >= 18px)`);
            if (!same(parse(cs.backgroundColor), card)) out.problems.push(`${describe(c)} background ${cs.backgroundColor} (want --pwa-card)`);
        }
    }
    if (raised) {
        const r = document.querySelector(raised);
        if (!r || !r.checkVisibility()) out.problems.push('raised card not visible: ' + raised);
        else {
            const cs = getComputedStyle(r);
            if (!same(parse(cs.backgroundColor), token('--pwa-card-raised')))
                out.problems.push(`${raised} background ${cs.backgroundColor} (want --pwa-card-raised)`);
            if (cs.boxShadow === 'none') out.problems.push(`${raised} has no shadow`);
        }
    }
    if (root.scrollWidth > root.clientWidth + 1) out.problems.push(`${host} overflows: ${root.scrollWidth} > ${root.clientWidth}`);
    if (document.documentElement.scrollWidth > innerWidth + 1) out.problems.push('the page overflows horizontally');
    probe.remove();
    return out;
}"""

TOKEN_IS = r"""([selector, prop, name]) => {
    const el = document.querySelector(selector);
    if (!el) return 'missing ' + selector;
    const probe = document.createElement('span');
    document.body.append(probe);
    const norm = v => { probe.style.color = ''; probe.style.color = v; return getComputedStyle(probe).color; };
    const want = norm(getComputedStyle(document.documentElement).getPropertyValue(name).trim());
    const got = norm(getComputedStyle(el)[prop]);
    probe.remove();
    return got === want ? true : `${selector} ${prop} ${got} (want ${name} = ${want})`;
}"""


def check_skin(page, host, *, title=None, cards=None, raised=None):
    """Measure `host` against the adult vocabulary; returns the report dict
    ({checked, failures, problems, skipped})."""
    return page.evaluate(CHECK, {'host': host, 'title': title, 'cards': cards, 'raised': raised})


def assert_skin(page, host, label, **kw):
    """check_skin, asserting no contrast failure, no problem and that some
    text was actually measured."""
    report = check_skin(page, host, **kw)
    assert not report['problems'], (label, report['problems'])
    assert not report['failures'], (label, 'under 4.5:1', report['failures'][:12])
    assert report['checked'] > 0, (label, 'no text measured in', host)
    return report


def token_is(page, selector, prop, name):
    """True when `selector`'s computed `prop` (a colour property) equals the
    resolved custom property `name`; otherwise a sentence saying what it is."""
    return page.evaluate(TOKEN_IS, [selector, prop, name])
