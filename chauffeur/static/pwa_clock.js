// Shared local clock for the PWA's pure summaries.
function pwaClock(value, opts = {}) {
    if (!(value instanceof Date) && typeof value !== 'number' && typeof value !== 'string') return '';
    const date = new Date(value);
    if (!Number.isFinite(date.getTime())) return '';
    const hour = opts?.use24h ? String(date.getHours()).padStart(2, '0') : date.getHours() % 12 || 12;
    return `${hour}:${String(date.getMinutes()).padStart(2, '0')}`;
}

function pwaClockSuffix(value, opts = {}) {
    const time = pwaClock(value, opts);
    if (!time || opts?.use24h) return time;
    return `${time} ${new Date(value).getHours() < 12 ? 'AM' : 'PM'}`;
}

function pwaNumberWord(n) {
    return ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine'][n] || String(n);
}

function pwaLocalDay(value) {
    if (value == null || value === '') return '';
    const date = new Date(value);
    if (!Number.isFinite(date.getTime())) return '';
    const pad = n => String(n).padStart(2, '0');
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

function pwaWeekday(date) {
    return new Date(date + 'T12:00:00').toLocaleDateString('en-US', {weekday:'long'});
}

