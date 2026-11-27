/* Presentation boards sheet renderer and controller (Task 6).
 *
 * Pure render helpers sit at column 0 with zero DOM/window dependency so
 * tests/pwa_pure.py can extract and run them directly under node.
 * The DOM controller below is guarded by `typeof window !== 'undefined'`.
 */

function boardEscape(value) {
    return String(value == null ? '' : value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function boardBase() {
    if (typeof window !== 'undefined' && typeof window.chfBase === 'string') {
        return window.chfBase;
    }
    return '';
}

function boardSafeHttpUrl(url) {
    if (typeof url !== 'string') return '';
    const trimmed = url.trim();
    return /^https?:\/\//i.test(trimmed) ? trimmed : '';
}

const BOARD_IMAGE_PATH_RE = /^api\/projects\/[0-9a-f]+\/boards\/[0-9a-f]+\/image\/lk_[0-9a-f]{10}$/;

function boardImgUrl(path) {
    if (typeof path !== 'string') return '';
    const trimmed = path.trim();
    if (!BOARD_IMAGE_PATH_RE.test(trimmed)) {
        return '';
    }
    const full = boardBase() + trimmed;
    if (typeof window !== 'undefined' && typeof window.chfAuthUrl === 'function') {
        return window.chfAuthUrl(full);
    }
    return full;
}

function boardFormatMoney(money) {
    if (!money || typeof money !== 'object' || typeof money.amount !== 'number' || !Number.isFinite(money.amount)) {
        return '';
    }
    const amt = money.amount;
    const isWhole = Math.abs(amt - Math.round(amt)) < 1e-9;
    const numStr = isWhole ? String(Math.round(amt)) : amt.toFixed(2);
    const cur = String(money.currency || 'USD').toUpperCase();
    return cur === 'USD' ? '$' + numStr : numStr + ' ' + cur;
}

function boardPlaceholderHtml(title, store, compact) {
    const label = title || store || 'No photo';
    const cls = compact
        ? 'chf-board-placeholder chf-board-placeholder-sm'
        : 'chf-board-placeholder';
    return '<div class="' + cls + '" data-board-img-placeholder="1">'
        + '<svg class="chf-board-placeholder-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">'
        + '<rect x="3" y="4" width="18" height="16" rx="3"></rect>'
        + '<circle cx="8.5" cy="9.5" r="1.5"></circle>'
        + '<path d="M21 16l-5-5-4.5 4.5L9 13l-6 6"></path>'
        + '</svg>'
        + (compact ? '' : '<span class="chf-board-placeholder-label">' + boardEscape(label) + '</span>')
        + '</div>';
}

function boardHeroHtml(option, opts) {
    const items = (option && Array.isArray(option.items)) ? option.items.slice(0, 4) : [];
    const lazy = !!(opts && opts.lazy);
    const loadAttr = lazy ? 'lazy' : 'eager';
    if (!items.length) {
        return '<div class="chf-board-hero chf-board-hero-1">'
            + '<div class="chf-board-hero-tile">'
            + boardPlaceholderHtml((option && option.title) || 'No photos', '', false)
            + '</div></div>';
    }
    const tiles = items.map(function (item) {
        const src = boardImgUrl(item && item.image);
        const title = (item && item.title) || '';
        const store = (item && item.store) || '';
        if (!src) {
            return '<div class="chf-board-hero-tile">'
                + boardPlaceholderHtml(title, store, false)
                + '</div>';
        }
        return '<div class="chf-board-hero-tile" data-board-tile-title="' + boardEscape(title) + '">'
            + '<img src="' + boardEscape(src) + '" alt="' + boardEscape(title) + '"'
            + ' loading="' + loadAttr + '" decoding="async" data-board-img="hero"'
            + ' class="chf-board-hero-img">'
            + '</div>';
    }).join('');
    return '<div class="chf-board-hero chf-board-hero-' + items.length + '">' + tiles + '</div>';
}

function boardSlotMap(view) {
    const map = {};
    const slots = (view && Array.isArray(view.slots)) ? view.slots : [];
    for (let i = 0; i < slots.length; i++) {
        const s = slots[i];
        if (s && s.id) map[s.id] = s.role || '';
    }
    return map;
}

function boardItemFactsHtml(item) {
    const facts = (item && Array.isArray(item.facts)) ? item.facts : [];
    if (!facts.length) return '';
    return '<div class="chf-board-facts">' + facts.map(function (f) {
        return '<span class="chf-board-fact">'
            + '<span class="chf-board-fact-k">' + boardEscape(f && f.label) + '</span> '
            + '<span class="chf-board-fact-v">' + boardEscape(f && f.value) + '</span>'
            + '</span>';
    }).join('') + '</div>';
}

function boardStoreLinkHtml(item) {
    const store = (item && item.store) || 'View item';
    const href = boardSafeHttpUrl(item && item.url);
    if (!href) {
        return '<span class="chf-board-store-text">' + boardEscape(store) + '</span>';
    }
    return '<a href="' + boardEscape(href) + '" target="_blank" rel="noopener noreferrer" class="chf-board-store-link">'
        + '<span>' + boardEscape(store) + '</span>'
        + '<span aria-hidden="true" class="chf-board-ext">&#8599;&#xFE0E;</span>'
        + '</a>';
}

function boardOptionScreenHtml(option, index, totalCount, slotMap) {
    const isOffscreen = index > 0;
    const loadAttr = isOffscreen ? 'lazy' : 'eager';
    const totalStr = boardFormatMoney(option && option.total);
    const items = (option && Array.isArray(option.items)) ? option.items : [];
    const showSlot = Object.keys(slotMap).length > 1;

    const rowsHtml = items.map(function (item) {
        const src = boardImgUrl(item && item.image);
        const title = (item && item.title) || '';
        const store = (item && item.store) || '';
        const priceStr = boardFormatMoney(item && item.price);
        const role = showSlot && item && item.slot_id ? (slotMap[item.slot_id] || '') : '';
        const thumb = src
            ? '<div class="chf-board-thumb" data-board-tile-title="' + boardEscape(title) + '">'
              + '<img src="' + boardEscape(src) + '" alt="' + boardEscape(title) + '"'
              + ' loading="' + loadAttr + '" decoding="async" data-board-img="thumb" class="chf-board-thumb-img">'
              + '</div>'
            : '<div class="chf-board-thumb">' + boardPlaceholderHtml(title, store, true) + '</div>';
        return '<div class="chf-board-item" data-board-item-id="' + boardEscape(item && item.id) + '">'
            + thumb
            + '<div class="chf-board-item-body">'
            + (role ? '<div class="chf-board-slot-role">' + boardEscape(role) + '</div>' : '')
            + '<div class="chf-board-item-title">' + boardEscape(title) + '</div>'
            + '<div class="chf-board-item-meta">' + boardStoreLinkHtml(item) + '</div>'
            + boardItemFactsHtml(item)
            + '</div>'
            + (priceStr ? '<div class="chf-board-item-price">' + boardEscape(priceStr) + '</div>' : '')
            + '</div>';
    }).join('');

    return '<section class="chf-board-screen" data-board-screen="' + index + '"'
        + ' data-option-id="' + boardEscape(option && option.id) + '"'
        + ' aria-label="' + boardEscape((option && option.title) || ('Option ' + (index + 1))) + '"'
        + (isOffscreen ? ' hidden' : '') + '>'
        + boardHeroHtml(option, { lazy: isOffscreen })
        + '<div class="chf-board-option-head">'
        + '<div class="chf-board-option-copy">'
        + '<h3 class="chf-board-option-title">' + boardEscape((option && option.title) || ('Option ' + (index + 1))) + '</h3>'
        + (option && option.note ? '<p class="chf-board-option-note">' + boardEscape(option.note) + '</p>' : '')
        + '</div>'
        + (totalStr ? '<div class="chf-board-option-total" data-board-total="1">' + boardEscape(totalStr) + '</div>' : '')
        + '</div>'
        + '<div class="chf-board-items">' + rowsHtml + '</div>'
        + '</section>';
}

function boardOptionsHtml(view) {
    const options = (view && Array.isArray(view.options)) ? view.options : [];
    if (!options.length) {
        return '<div class="chf-board-empty">No options on this board yet.</div>';
    }
    const slotMap = boardSlotMap(view);
    const screens = options.map(function (opt, idx) {
        return boardOptionScreenHtml(opt, idx, options.length, slotMap);
    }).join('');

    let pager = '';
    if (options.length > 1) {
        const dots = options.map(function (opt, idx) {
            const active = idx === 0;
            return '<button type="button" class="chf-board-dot' + (active ? ' is-active' : '') + '"'
                + ' data-board-dot="' + idx + '"'
                + ' aria-label="' + boardEscape((opt && opt.title) || ('Option ' + (idx + 1))) + '"'
                + ' aria-pressed="' + (active ? 'true' : 'false') + '"></button>';
        }).join('');
        pager = '<div class="chf-board-pager" data-board-pager="1">'
            + '<button type="button" class="chf-board-nav-btn" data-board-prev="1" aria-label="Previous option" disabled>&#8249;</button>'
            + '<div class="chf-board-dots" role="group" aria-label="Options">' + dots + '</div>'
            + '<span class="chf-board-counter" data-board-counter="1">1 / ' + options.length + '</span>'
            + '<button type="button" class="chf-board-nav-btn" data-board-next="1" aria-label="Next option">&#8250;</button>'
            + '</div>';
    }
    return '<div class="chf-board-options" data-board-layout="options">' + pager + screens + '</div>';
}

function boardCompareHtml(view) {
    const options = (view && Array.isArray(view.options)) ? view.options : [];
    const cols = [];
    for (let i = 0; i < options.length; i++) {
        const opt = options[i];
        const items = (opt && Array.isArray(opt.items)) ? opt.items : [];
        for (let j = 0; j < items.length; j++) {
            cols.push({ option: opt, item: items[j] });
        }
    }
    if (!cols.length) {
        return '<div class="chf-board-empty">Nothing to compare yet.</div>';
    }

    const factLabels = [];
    const seen = {};
    for (let i = 0; i < cols.length; i++) {
        const facts = (cols[i].item && Array.isArray(cols[i].item.facts)) ? cols[i].item.facts : [];
        for (let k = 0; k < facts.length; k++) {
            const lbl = facts[k] && facts[k].label;
            if (lbl && !seen[lbl]) {
                seen[lbl] = true;
                factLabels.push(lbl);
            }
        }
    }

    const headerCells = cols.map(function (c) {
        const item = c.item || {};
        const title = item.title || (c.option && c.option.title) || '';
        const src = boardImgUrl(item.image);
        const href = boardSafeHttpUrl(item.url);
        const thumb = src
            ? '<div class="chf-board-cmp-thumb" data-board-tile-title="' + boardEscape(title) + '">'
              + '<img src="' + boardEscape(src) + '" alt="' + boardEscape(title) + '"'
              + ' loading="eager" decoding="async" data-board-img="compare" class="chf-board-cmp-img">'
              + '</div>'
            : '<div class="chf-board-cmp-thumb">' + boardPlaceholderHtml(title, item.store || '', true) + '</div>';
        const titleHtml = href
            ? '<a href="' + boardEscape(href) + '" target="_blank" rel="noopener noreferrer" class="chf-board-cmp-link">'
              + '<span>' + boardEscape(title) + '</span>'
              + '<span aria-hidden="true" class="chf-board-ext">&#8599;&#xFE0E;</span>'
              + '</a>'
            : '<span class="chf-board-cmp-title">' + boardEscape(title) + '</span>';
        return '<th scope="col" class="chf-board-cmp-col">' + thumb + titleHtml + '</th>';
    }).join('');

    const priceRow = '<tr><th scope="row" class="chf-board-cmp-rowlbl">Price</th>'
        + cols.map(function (c) {
            const p = boardFormatMoney(c.item && c.item.price);
            return '<td class="chf-board-cmp-cell chf-board-cmp-price">' + (p ? boardEscape(p) : '&mdash;') + '</td>';
        }).join('') + '</tr>';

    const storeRow = '<tr><th scope="row" class="chf-board-cmp-rowlbl">Store</th>'
        + cols.map(function (c) {
            return '<td class="chf-board-cmp-cell">' + boardStoreLinkHtml(c.item) + '</td>';
        }).join('') + '</tr>';

    const factRows = factLabels.map(function (lbl) {
        return '<tr><th scope="row" class="chf-board-cmp-rowlbl">' + boardEscape(lbl) + '</th>'
            + cols.map(function (c) {
                const facts = (c.item && Array.isArray(c.item.facts)) ? c.item.facts : [];
                let val = '';
                for (let k = 0; k < facts.length; k++) {
                    if (facts[k] && facts[k].label === lbl) { val = facts[k].value || ''; break; }
                }
                return '<td class="chf-board-cmp-cell">' + (val ? boardEscape(val) : '&mdash;') + '</td>';
            }).join('') + '</tr>';
    }).join('');

    const hasNotes = cols.some(function (c) { return c.option && c.option.note; });
    const noteRow = hasNotes
        ? '<tr><th scope="row" class="chf-board-cmp-rowlbl">Note</th>'
          + cols.map(function (c) {
              const n = c.option && c.option.note;
              return '<td class="chf-board-cmp-cell">' + (n ? boardEscape(n) : '&mdash;') + '</td>';
          }).join('') + '</tr>'
        : '';

    const scrollHint = cols.length > 1
        ? '<div class="chf-board-scroll-hint" data-board-scroll-hint="1" hidden>Swipe to see all ' + cols.length + '</div>'
        : '';

    return '<div class="chf-board-compare" data-board-layout="compare">'
        + scrollHint
        + '<div class="chf-board-compare-stage" data-board-compare-stage="1">'
        + '<div class="chf-board-table-wrap" data-board-table-wrap="1">'
        + '<table class="chf-board-table">'
        + '<thead><tr><th scope="col" class="chf-board-cmp-corner"></th>' + headerCells + '</tr></thead>'
        + '<tbody>' + priceRow + storeRow + factRows + noteRow + '</tbody>'
        + '</table>'
        + '</div>'
        + '</div>'
        + '</div>';
}

function boardListHtml(view) {
    const options = (view && Array.isArray(view.options)) ? view.options : [];
    const multiGroup = options.length > 1;
    const sections = [];
    for (let i = 0; i < options.length; i++) {
        const opt = options[i];
        const items = (opt && Array.isArray(opt.items)) ? opt.items : [];
        if (!items.length) continue;
        const rows = items.map(function (item) {
            const src = boardImgUrl(item && item.image);
            const title = (item && item.title) || '';
            const store = (item && item.store) || '';
            const priceStr = boardFormatMoney(item && item.price);
            const thumb = src
                ? '<div class="chf-board-list-thumb" data-board-tile-title="' + boardEscape(title) + '">'
                  + '<img src="' + boardEscape(src) + '" alt="' + boardEscape(title) + '"'
                  + ' loading="eager" decoding="async" data-board-img="list" class="chf-board-thumb-img">'
                  + '</div>'
                : '<div class="chf-board-list-thumb">' + boardPlaceholderHtml(title, store, true) + '</div>';
            return '<div class="chf-board-list-item" data-board-list-item="1" data-board-item-id="' + boardEscape(item && item.id) + '">'
                + '<span class="chf-board-check" aria-hidden="true"></span>'
                + thumb
                + '<div class="chf-board-item-body">'
                + '<div class="chf-board-item-title">' + boardEscape(title) + '</div>'
                + '<div class="chf-board-item-meta">' + boardStoreLinkHtml(item) + '</div>'
                + boardItemFactsHtml(item)
                + '</div>'
                + (priceStr ? '<div class="chf-board-item-price">' + boardEscape(priceStr) + '</div>' : '')
                + '</div>';
        }).join('');
        sections.push(
            '<div class="chf-board-list-group">'
            + (multiGroup && opt && opt.title ? '<h3 class="chf-board-list-heading">' + boardEscape(opt.title) + '</h3>' : '')
            + (opt && opt.note ? '<p class="chf-board-option-note">' + boardEscape(opt.note) + '</p>' : '')
            + '<div class="chf-board-list-rows">' + rows + '</div>'
            + '</div>'
        );
    }
    if (!sections.length) {
        return '<div class="chf-board-empty">Nothing on this list yet.</div>';
    }
    return '<div class="chf-board-list" data-board-layout="list">' + sections.join('') + '</div>';
}

function boardSheetHtml(view) {
    if (!view || typeof view !== 'object') {
        return '<div class="chf-board-empty">This board is no longer available.</div>';
    }
    const layout = view.layout;
    let bodyHtml;
    if (layout === 'options') {
        bodyHtml = boardOptionsHtml(view);
    } else if (layout === 'compare') {
        bodyHtml = boardCompareHtml(view);
    } else {
        bodyHtml = boardListHtml(view);
    }
    const title = view.title || 'Board';
    const summary = view.summary_line || '';
    return '<div class="chf-board-chrome" data-board-view-id="' + boardEscape(view.id) + '">'
        + '<div class="chf-board-header">'
        + '<div class="chf-board-header-copy">'
        + '<h2 class="chf-board-title">' + boardEscape(title) + '</h2>'
        + (summary ? '<div class="chf-board-summary">' + boardEscape(summary) + '</div>' : '')
        + '</div>'
        + '<button type="button" class="chf-board-close" data-board-close="1" aria-label="Close board" title="Close">&#10005;</button>'
        + '</div>'
        + '<div class="chf-board-body" data-board-body="1">' + bodyHtml + '</div>'
        + '<div class="chf-board-tray-slot" data-board-tray-slot="1"></div>'
        + '</div>';
}

function parseBoardHash(hash) {
    if (typeof hash !== 'string') return null;
    const m = /^#board-([0-9a-f]+)-([0-9a-f]+)$/.exec(hash.trim());
    if (!m) return null;
    return { projectId: m[1], boardId: m[2] };
}

let _boardSheetReqSeq = 0;
let _boardSheetOpener = null;
let _boardSheetHistory = null; // null | 'pushed' | 'navigated'
let _boardSheetClosing = false;
let _boardSheetToken = null;
let _boardSheetEntrySeq = 0;
let _boardHashChangeActive = false;
const _boardSheetSessionId = Math.random().toString(36).slice(2);

function boardSheetOverlay() {
    if (typeof document === 'undefined') return null;
    return document.querySelector('[data-board-sheet]');
}

function boardSyncCompareScroll(overlay) {
    if (!overlay || overlay.hidden) return;
    const stage = overlay.querySelector('[data-board-compare-stage]');
    const wrap = overlay.querySelector('[data-board-table-wrap]');
    if (!stage || !wrap) return;
    const overflow = wrap.scrollWidth - wrap.clientWidth;
    const hasOverflow = overflow > 2;
    const hasMoreRight = hasOverflow && wrap.scrollLeft < overflow - 2;
    stage.classList.toggle('has-more-right', hasMoreRight);
    const hint = overlay.querySelector('[data-board-scroll-hint]');
    if (hint) hint.hidden = !hasOverflow;
}

function boardSheetSetActive(index) {
    const overlay = boardSheetOverlay();
    if (!overlay) return;
    const screens = overlay.querySelectorAll('[data-board-screen]');
    if (!screens.length) return;
    const clamped = Math.max(0, Math.min(screens.length - 1, index));
    overlay.setAttribute('data-active-index', String(clamped));
    for (let i = 0; i < screens.length; i++) {
        screens[i].hidden = (i !== clamped);
    }
    const dots = overlay.querySelectorAll('[data-board-dot]');
    for (let i = 0; i < dots.length; i++) {
        const on = i === clamped;
        dots[i].classList.toggle('is-active', on);
        dots[i].setAttribute('aria-pressed', on ? 'true' : 'false');
    }
    const counter = overlay.querySelector('[data-board-counter]');
    if (counter) counter.textContent = (clamped + 1) + ' / ' + screens.length;
    const prev = overlay.querySelector('[data-board-prev]');
    const next = overlay.querySelector('[data-board-next]');
    if (prev) prev.disabled = clamped <= 0;
    if (next) next.disabled = clamped >= screens.length - 1;
    const body = overlay.querySelector('[data-board-body]');
    if (body) body.scrollTop = 0;
}

function closeBoardSheet(reason) {
    const overlay = boardSheetOverlay();
    if (!overlay || overlay.hidden) return;
    _boardSheetReqSeq += 1;
    overlay.hidden = true;
    overlay.removeAttribute('data-open');
    overlay.removeAttribute('data-active-index');

    const opener = _boardSheetOpener;
    _boardSheetOpener = null;
    if (opener && opener.isConnected && !opener.closest('[hidden], [inert]') && typeof opener.focus === 'function') {
        try { opener.focus({ preventScroll: true }); } catch (e) { opener.focus(); }
    }

    const histMode = _boardSheetHistory;
    _boardSheetHistory = null;
    _boardSheetToken = null;

    if (typeof window !== 'undefined' && window.history) {
        const hadBoardHash = !!parseBoardHash(window.location.hash);
        if (hadBoardHash && typeof window.history.replaceState === 'function') {
            window.history.replaceState(window.history.state, '', window.location.pathname + window.location.search);
        }
        if (reason !== 'back' && (histMode === 'pushed' || histMode === 'navigated')) {
            _boardSheetClosing = true;
            window.history.back();
        }
    }
}

function boardStateShellHtml(title, message, isLoading) {
    return '<div class="chf-board-chrome">'
        + '<div class="chf-board-header">'
        + '<div class="chf-board-header-copy">'
        + '<h2 class="chf-board-title">' + boardEscape(title) + '</h2>'
        + '</div>'
        + '<button type="button" class="chf-board-close" data-board-close="1" aria-label="Close board" title="Close">&#10005;</button>'
        + '</div>'
        + '<div class="chf-board-body chf-board-state" role="status">'
        + (isLoading ? '<div class="chf-board-spinner" aria-hidden="true"></div>' : '')
        + '<p class="chf-board-state-text">' + boardEscape(message) + '</p>'
        + '</div>'
        + '<div class="chf-board-tray-slot" data-board-tray-slot="1"></div>'
        + '</div>';
}

async function openBoardSheet(projectId, boardId, opts) {
    const overlay = boardSheetOverlay();
    if (!overlay || !projectId || !boardId) return;
    const panel = overlay.querySelector('[data-board-panel]') || overlay;
    const wasClosed = overlay.hidden;
    const seq = ++_boardSheetReqSeq;

    const fromHashChange = !!(opts && opts.fromHashChange) || _boardHashChangeActive;
    _boardHashChangeActive = false;

    if (wasClosed) {
        _boardSheetOpener = (typeof document !== 'undefined' && document.activeElement
            && document.activeElement !== document.body && !overlay.contains(document.activeElement))
            ? document.activeElement : null;
        if (typeof window !== 'undefined' && window.history) {
            const hasDeepHash = !!parseBoardHash(window.location.hash);
            const cleanUrl = window.location.pathname + window.location.search;
            const token = _boardSheetSessionId + ':' + (++_boardSheetEntrySeq);
            if (_boardSheetClosing) {
                if (typeof window.history.replaceState === 'function') {
                    window.history.replaceState({ pwaOverlay: 'board', boardSheetToken: token }, '');
                }
                _boardSheetHistory = 'pushed';
                _boardSheetToken = token;
            } else if (fromHashChange && hasDeepHash) {
                if (typeof window.history.replaceState === 'function') {
                    const baseState = (window.history.state && typeof window.history.state === 'object')
                        ? window.history.state : {};
                    window.history.replaceState(Object.assign({}, baseState, { pwaOverlay: 'board', boardSheetToken: token }), '');
                }
                _boardSheetHistory = 'navigated';
                _boardSheetToken = token;
            } else if (hasDeepHash && typeof window.history.pushState === 'function') {
                const hashUrl = cleanUrl + window.location.hash;
                if (typeof window.history.replaceState === 'function') {
                    window.history.replaceState(window.history.state, '', cleanUrl);
                }
                window.history.pushState({ pwaOverlay: 'board', boardSheetToken: token }, '', hashUrl);
                _boardSheetHistory = 'pushed';
                _boardSheetToken = token;
            } else if (typeof window.history.pushState === 'function') {
                window.history.pushState({ pwaOverlay: 'board', boardSheetToken: token }, '');
                _boardSheetHistory = 'pushed';
                _boardSheetToken = token;
            }
        }
    }

    overlay.hidden = false;
    overlay.setAttribute('data-open', 'true');
    overlay.setAttribute('data-active-index', '0');
    panel.innerHTML = boardStateShellHtml('Board', 'Loading board\u2026', true);
    if (typeof panel.focus === 'function') panel.focus();

    const pid = encodeURIComponent(String(projectId));
    const bid = encodeURIComponent(String(boardId));
    const url = boardBase() + 'api/projects/' + pid + '/boards/' + bid;
    try {
        const res = await fetch(url);
        if (seq !== _boardSheetReqSeq || overlay.hidden) return;
        if (res.status === 404) {
            panel.innerHTML = boardStateShellHtml('Board', 'This board is no longer available.', false);
            return;
        }
        if (!res.ok) {
            let detail = 'Could not load this board.';
            try {
                const err = await res.json();
                if (err && err.detail) detail = String(err.detail);
            } catch (e) { /* non-JSON error */ }
            if (seq !== _boardSheetReqSeq || overlay.hidden) return;
            panel.innerHTML = boardStateShellHtml('Board', detail, false);
            return;
        }
        const view = await res.json();
        if (seq !== _boardSheetReqSeq || overlay.hidden) return;
        panel.innerHTML = boardSheetHtml(view);
        if (view && view.layout === 'options') {
            boardSheetSetActive(0);
        } else if (view && view.layout === 'compare') {
            boardSyncCompareScroll(overlay);
            if (typeof window !== 'undefined' && typeof window.requestAnimationFrame === 'function') {
                window.requestAnimationFrame(function () { boardSyncCompareScroll(overlay); });
            }
        }
        if (typeof panel.focus === 'function') panel.focus();
    } catch (e) {
        if (seq !== _boardSheetReqSeq || overlay.hidden) return;
        panel.innerHTML = boardStateShellHtml('Board', 'Could not load this board.', false);
    }
}

function boardSheetBindEvents() {
    if (typeof window === 'undefined' || typeof document === 'undefined') return;
    if (window.__chfBoardSheetBound) return;
    window.__chfBoardSheetBound = true;

    window.openBoardSheet = openBoardSheet;
    window.closeBoardSheet = closeBoardSheet;
    window.parseBoardHash = parseBoardHash;
    window.boardSheetHtml = boardSheetHtml;
    window.boardCompareHtml = boardCompareHtml;
    window.boardListHtml = boardListHtml;
    window.boardHeroHtml = boardHeroHtml;
    window.boardSheetSetActive = boardSheetSetActive;

    window.addEventListener('hashchange', function () {
        if (!parseBoardHash(window.location.hash)) return;
        _boardHashChangeActive = true;
        setTimeout(function () { _boardHashChangeActive = false; }, 0);
    }, true);

    window.addEventListener('chf-board-open', function (ev) {
        const d = ev && ev.detail;
        if (d && d.projectId && d.boardId) {
            openBoardSheet(d.projectId, d.boardId, { fromHashChange: !!d.fromHashChange });
        }
    });

    document.addEventListener('click', function (ev) {
        const overlay = boardSheetOverlay();
        if (!overlay || overlay.hidden) return;
        if (ev.target === overlay) {
            closeBoardSheet();
            return;
        }
        if (!overlay.contains(ev.target)) return;
        const closeBtn = ev.target.closest('[data-board-close]');
        if (closeBtn) { closeBoardSheet(); return; }
        const prevBtn = ev.target.closest('[data-board-prev]');
        if (prevBtn && !prevBtn.disabled) {
            const cur = parseInt(overlay.getAttribute('data-active-index') || '0', 10) || 0;
            boardSheetSetActive(cur - 1);
            return;
        }
        const nextBtn = ev.target.closest('[data-board-next]');
        if (nextBtn && !nextBtn.disabled) {
            const cur = parseInt(overlay.getAttribute('data-active-index') || '0', 10) || 0;
            boardSheetSetActive(cur + 1);
            return;
        }
        const dot = ev.target.closest('[data-board-dot]');
        if (dot) {
            const idx = parseInt(dot.getAttribute('data-board-dot') || '0', 10);
            if (!Number.isNaN(idx)) boardSheetSetActive(idx);
        }
    });

    window.addEventListener('popstate', function (ev) {
        const overlay = boardSheetOverlay();
        const isCurrentBoard = !!(ev.state && ev.state.pwaOverlay === 'board'
            && (!_boardSheetToken || ev.state.boardSheetToken === _boardSheetToken));
        if (_boardSheetClosing) {
            _boardSheetClosing = false;
            if (overlay && !overlay.hidden && !isCurrentBoard && _boardSheetHistory === 'pushed'
                && typeof window.history.pushState === 'function') {
                window.history.pushState({ pwaOverlay: 'board', boardSheetToken: _boardSheetToken }, '');
            }
            return;
        }
        if (!overlay || overlay.hidden) return;
        if (!isCurrentBoard) {
            closeBoardSheet('back');
        }
    });

    document.addEventListener('scroll', function (ev) {
        if (!ev.target || !ev.target.hasAttribute || !ev.target.hasAttribute('data-board-table-wrap')) return;
        boardSyncCompareScroll(boardSheetOverlay());
    }, true);

    window.addEventListener('resize', function () {
        boardSyncCompareScroll(boardSheetOverlay());
    });

    document.addEventListener('keydown', function (ev) {
        const overlay = boardSheetOverlay();
        if (!overlay || overlay.hidden) return;
        if (ev.key === 'Escape') {
            if (typeof window.chfPromptOpen === 'function' && window.chfPromptOpen()) return;
            if (document.querySelector('.pwa-prompt-overlay')) return;
            ev.preventDefault();
            ev.stopPropagation();
            closeBoardSheet('escape');
            return;
        }
        if (ev.key === 'Tab') {
            const panel = overlay.querySelector('[data-board-panel]') || overlay;
            const list = Array.from(panel.querySelectorAll(
                'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
            )).filter(function (el) { return !el.closest('[hidden]'); });
            if (!list.length) {
                ev.preventDefault();
                if (typeof panel.focus === 'function') panel.focus();
                return;
            }
            const first = list[0];
            const last = list[list.length - 1];
            const active = document.activeElement;
            if (ev.shiftKey) {
                if (active === first || active === panel || !panel.contains(active)) {
                    ev.preventDefault();
                    last.focus();
                }
            } else if (active === last || !panel.contains(active)) {
                ev.preventDefault();
                first.focus();
            }
            return;
        }
        if (ev.key === 'ArrowRight' || ev.key === 'ArrowLeft') {
            const screens = overlay.querySelectorAll('[data-board-screen]');
            if (screens.length < 2) return;
            const cur = parseInt(overlay.getAttribute('data-active-index') || '0', 10) || 0;
            boardSheetSetActive(cur + (ev.key === 'ArrowRight' ? 1 : -1));
        }
    }, true);

    // Touch swipe between options on phone (horizontal-dominant gesture >= 48px).
    let swipeStart = null;
    document.addEventListener('touchstart', function (ev) {
        const overlay = boardSheetOverlay();
        if (!overlay || overlay.hidden || !ev.touches || ev.touches.length !== 1) return;
        if (!overlay.contains(ev.target)) return;
        if (ev.target.closest('.chf-board-table-wrap')) return;
        swipeStart = { x: ev.touches[0].clientX, y: ev.touches[0].clientY };
    }, { passive: true });

    document.addEventListener('touchend', function (ev) {
        if (!swipeStart) return;
        const start = swipeStart;
        swipeStart = null;
        const overlay = boardSheetOverlay();
        if (!overlay || overlay.hidden || !ev.changedTouches || !ev.changedTouches.length) return;
        const t = ev.changedTouches[0];
        const dx = t.clientX - start.x;
        const dy = t.clientY - start.y;
        if (Math.abs(dx) < 48 || Math.abs(dx) < Math.abs(dy) * 1.5) return;
        const screens = overlay.querySelectorAll('[data-board-screen]');
        if (screens.length < 2) return;
        const cur = parseInt(overlay.getAttribute('data-active-index') || '0', 10) || 0;
        boardSheetSetActive(cur + (dx < 0 ? 1 : -1));
    }, { passive: true });

    // Delegated capture-phase image error fallback: swaps any 404 image for a neutral placeholder tile.
    document.addEventListener('error', function (ev) {
        const img = ev.target;
        if (!img || img.tagName !== 'IMG' || !img.hasAttribute('data-board-img')) return;
        const host = img.parentElement;
        if (!host) return;
        const kind = img.getAttribute('data-board-img');
        const title = host.getAttribute('data-board-tile-title') || img.getAttribute('alt') || '';
        const compact = kind !== 'hero';
        host.innerHTML = boardPlaceholderHtml(title, '', compact);
    }, true);
}

if (typeof window !== 'undefined' && typeof document !== 'undefined') {
    boardSheetBindEvents();
}
