/* Shared Argyle glyph and button factory. No DOM work until create(). */
(function () {
    if (window.ArgyleOrb) return;

    function glyph() {
        return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"'
            + ' stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
            + '<path d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>';
    }

    function create({ id, label } = {}) {
        const el = document.createElement('button');
        el.type = 'button';
        el.id = id;
        el.className = 'argyle-orb';
        el.setAttribute('aria-label', label);
        el.innerHTML = glyph();
        return el;
    }

    window.ArgyleOrb = { glyph, create };
})();
