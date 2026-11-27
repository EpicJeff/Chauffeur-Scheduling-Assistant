// Shared safe HTML for plain-text chat bubbles and school descriptions.
function linkifyText(text, linkClass = 'underline break-all') {
    if (typeof text !== 'string') return '';
    const escape = value => value.replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    return text.split(/(https?:\/\/[^\s<>"']+)/g).map((piece, index) => {
        if (index % 2 === 0) return escape(piece);
        let url = piece;
        let closes = (url.match(/\)/g) || []).length;
        const opens = (url.match(/\(/g) || []).length;
        while (url && '.,;:!?)]}'.includes(url.slice(-1))) {
            if (url.endsWith(')')) {
                if (closes <= opens) break;
                closes--;
            }
            url = url.slice(0, -1);
        }
        if (url.length <= piece.indexOf('://') + 3) return escape(piece);
        const escapedUrl = escape(url);
        return `<a href="${escapedUrl}" target="_blank" rel="noopener noreferrer" class="${escape(String(linkClass))}">${escapedUrl}</a>`
            + escape(piece.slice(url.length));
    }).join('');
}
