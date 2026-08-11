/* The stylesheet for every page EXCEPT the driver app.
 *
 * This is the union of the eighteen near-identical `tailwind.config` blocks
 * that used to sit inline in each template's <head> and get handed to the Play
 * CDN's in-browser compiler. They differed in almost nothing: most repeated a
 * `gray` override whose four values are Tailwind's own defaults (a no-op), and
 * one added `pulse-slow`. Those are folded in here.
 *
 * The driver app is the exception and has its own config next door, because its
 * palette is not colour values at all — it is `rgb(var(--c-*) / <alpha-value>)`
 * pointing into theme.css, which is what lets one `[data-theme]` flip restyle
 * the app. A page that does not load theme.css would render every colour as an
 * unresolved variable, so the two builds cannot be merged.
 */
module.exports = {
    darkMode: 'class',
    // Both builds scan EVERY template, not the subset a given page includes.
    // Components are pulled into a dozen pages, nav and the panel skin into all
    // of them, and getting the per-page graph wrong shows up as a class that
    // silently does nothing on one page only. The cost of over-scanning is a
    // few KB of unused utilities; the cost of under-scanning is a visual bug
    // nobody finds until it is on the wall.
    content: [
        './templates/**/*.html',
    ],
    theme: {
        extend: {
            fontFamily: {
                // Fourteen pages declared `['Inter', 'sans-serif']` inline and
                // four (calendar, trips, map, trip_kiosk) declared nothing and
                // kept Tailwind's default stack. One shared stylesheet cannot
                // have it both ways, so the stack is Inter FOLLOWED BY
                // Tailwind's own default — which is what the second group was
                // already getting, and what the first group falls back to
                // anyway on the eight pages that name Inter without ever
                // loading the font.
                //
                // The emoji families are on the end because the bare
                // `['Inter', 'sans-serif']` override is what dropped them in
                // the first place, and a Raspberry Pi with no emoji font draws
                // a tofu box for every glyph on the board. panel_skin.html
                // still appends the vendored "Chauffeur Emoji" after these on
                // display surfaces — that font is only ever downloaded by a
                // device that has none of its own.
                sans: ['Inter', 'ui-sans-serif', 'system-ui', '-apple-system',
                    'Segoe UI', 'Roboto', 'Helvetica Neue', 'Arial',
                    'sans-serif', 'Apple Color Emoji', 'Segoe UI Emoji',
                    'Noto Color Emoji'],
            },
            animation: {
                'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
            },
        },
    },
};
