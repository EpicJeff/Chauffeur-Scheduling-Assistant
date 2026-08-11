/* The driver app's stylesheet (templates/app.html only).
 *
 * A verbatim port of the config app.html used to build at runtime and hand to
 * the Play CDN. Every palette entry points at a channel triple from theme.css,
 * so one `[data-theme]` flip restyles the app without touching a utility class.
 * `<alpha-value>` is what keeps `bg-amber-500/10` and friends working.
 *
 * white and black are deliberately NOT tokenized: `text-white` on a solid
 * accent fill must stay white in both themes. Surface-level primary text uses
 * text-gray-100 instead.
 */
const SHADES = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950];
const HUES = ['slate', 'blue', 'indigo', 'violet', 'purple', 'pink', 'rose',
    'red', 'orange', 'amber', 'yellow', 'lime', 'green', 'emerald',
    'teal', 'cyan', 'sky'];
const ramp = (name) => Object.fromEntries(
    SHADES.map(s => [s, `rgb(var(--c-${name}-${s}) / <alpha-value>)`]));
const colors = { gray: ramp('gray') };
HUES.forEach(h => { colors[h] = ramp(h); });

module.exports = {
    darkMode: 'class',
    // Every template, same as the base build — app.html includes three shared
    // components and they must be scanned with THIS theme, not the other one.
    content: [
        './templates/**/*.html',
    ],
    theme: {
        extend: {
            colors,
            // 13px is the app's type floor: every arbitrary 9-13px size was
            // collapsed into text-xs, so this one token IS the floor. Don't
            // reintroduce text-[NNpx] below it.
            fontSize: { xs: ['13px', '18px'] },
            // Softer radii app-wide (Skylight/Hearth direction): same markup,
            // friendlier geometry.
            borderRadius: {
                lg: '12px', xl: '16px', '2xl': '20px', '3xl': '28px',
            },
        },
    },
};
