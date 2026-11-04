/* Conversation summaries use the channel payload and the caller's display builders. */
function pwaTimeLabel(ts, now, opts = {}) {
    if (!Number.isFinite(ts)) return '';
    const date = new Date(ts * 1000);
    if (!Number.isFinite(date.getTime())) return '';
    const today = new Date(now);
    // Compare local calendar days without daylight-saving time changing the gap.
    const day = value => Date.UTC(value.getFullYear(), value.getMonth(), value.getDate()) / 86400000;
    const daysAgo = day(today) - day(date);
    if (daysAgo <= 0) return pwaClock(date, opts);
    if (daysAgo === 1) return 'Yesterday';
    if (daysAgo >= 2 && daysAgo <= 6) return date.toLocaleDateString('en-US', {weekday: 'short'});
    return date.toLocaleDateString('en-US', date.getFullYear() === today.getFullYear()
        ? {month: 'short', day: 'numeric'} : {month: 'short', day: 'numeric', year: 'numeric'});
}

function pwaPreviewLine(last, ctx) {
    if (!last) return 'No messages yet';
    const sender = (ctx.members || []).find(member => member.id === last.sender_member_id);
    const name = last.sender_member_id === ctx.meId ? 'You'
        : last.sender_member_id === 'argyle' ? 'Argyle' : (sender?.name || 'Someone').split(' ')[0];
    const text = last.attachment ? ctx.previewLabel(last) : last.body || '';
    return `${name}: ${text}`;
}

function pwaConversationRows(channels, ctx) {
    const family = channels.find(channel => channel.kind === 'family');
    const argyle = channels.find(channel => channel.kind === 'dm' && (channel.member_ids || []).includes('argyle'));
    const row = channel => {
        const display = ctx.display(channel);
        const unread = Math.max(0, Math.trunc(Number(channel.unread) || 0));
        return {id: channel.id, kind: channel.kind, name: display.name, color: display.color,
            avatar: display.avatar, image: display.image || null,
            time: channel.last_message ? pwaTimeLabel(channel.last_message.ts, ctx.now, {use24h:ctx.use24h}) : '',
            preview: pwaPreviewLine(channel.last_message, ctx), unread,
            unreadStyle: unread > 1 ? 'count' : unread === 1 ? 'dot' : 'none'};
    };
    const pinned = [];
    if (family) pinned.push(row(family));
    if (argyle) pinned.push(row(argyle));
    else if (ctx.argyleAllowed) {
        const display = ctx.display({kind: 'dm', member_ids: [ctx.meId, 'argyle']});
        pinned.push({id: null, kind: 'argyle', name: 'Argyle',
            color: display.color, avatar: display.avatar, image: display.image || null,
            time: '', preview: 'Ask me anything.', unread: 0, unreadStyle: 'none'});
    }
    return {pinned, chats: channels.filter(channel => channel !== family && channel !== argyle).map(row)};
}

function pwaConversationAvatar(display, className) {
    const avatar = document.createElement('div');
    avatar.className = className;
    avatar.style.background = display.color;
    avatar.innerHTML = avatarInner(display, display.avatar || (display.name || '?').charAt(0));
    avatar.setAttribute('aria-hidden', 'true');
    return avatar;
}

function pwaRenderConversations() {
    const list = document.getElementById('channel-list');
    if (!list) return;
    const groups = pwaConversationRows(channelsData, {meId: selectedMemberId, members: membersData,
        now: Date.now(), use24h: typeof use24h !== 'undefined' && use24h,
        argyleAllowed: pwaOrbAllowed(), display: channelDisplay, previewLabel: momentPreviewLabel});
    const focusedChannel = document.activeElement?.closest('#channel-list > [data-channel]')?.dataset.channel;
    list.replaceChildren();
    for (const [label, rows] of [['Pinned', groups.pinned], ['Chats', groups.chats]]) {
        if (!rows.length) continue;
        const heading = document.createElement('div');
        heading.className = 'pwa-conv-label';
        heading.textContent = label;
        list.append(heading);
        for (const row of rows) {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'pwa-conv';
            button.dataset.channel = row.id === null ? 'argyle' : row.id;
            button.addEventListener('click', () => row.kind === 'argyle' ? pwaOpenArgyle() : openChannel(row.id));
            button.append(pwaConversationAvatar(row, 'pwa-conv-av'));
            const text = document.createElement('div');
            text.className = 'pwa-conv-tx';
            text.innerHTML = `<div class="pwa-conv-name">${mfEscape(row.name)} <small class="pwa-conv-time">${mfEscape(row.time)}</small></div>
                <div class="pwa-conv-preview${row.unread ? ' u' : ''}">${mfEscape(row.preview)}</div>`;
            button.append(text);
            if (row.unreadStyle !== 'none') {
                const badge = document.createElement('span');
                badge.className = 'pwa-conv-unread';
                const mark = document.createElement('span');
                mark.className = row.unreadStyle === 'dot' ? 'pwa-conv-dot' : 'pwa-conv-count';
                if (row.unreadStyle === 'count') mark.textContent = row.unread > 99 ? '99+' : String(row.unread);
                mark.setAttribute('aria-hidden', 'true');
                const unread = document.createElement('span');
                unread.className = 'sr-only';
                unread.textContent = `, ${row.unread} unread`;
                badge.append(mark, unread);
                button.append(badge);
            }
            list.append(button);
        }
    }
    if (!list.childElementCount) list.innerHTML = '<p class="pwa-empty">No conversations yet.</p>';
    pwaFilterConversations(document.querySelector('.pwa-conversation-search input').value);
    if (focusedChannel) Array.from(list.querySelectorAll('[data-channel]'))
        .find(button => button.dataset.channel === focusedChannel)?.focus({preventScroll: true});
}

function pwaAddMomentRing() {
    if (!pwaIsAdult() || currentMemberRole() === 'guest' || !channelsData.some(c => c.kind === 'event')) return '';
    return '<button type="button" class="pwa-mo add" onclick="pwaAddMoment()" aria-label="Add a moment"><span class="ring"><i aria-hidden="true"></i></span><span>Add</span></button>';
}

async function pwaAddMoment() {
    const events = channelsData.filter(c => c.kind === 'event');
    if (!events.length) {
        showGlobalAlert('Start from an event: open it from your day and tap Add a moment.');
        return;
    }
    const id = events.length === 1 ? events[0].id : await promptChoice('Add a moment to…', '',
        events.map(c => ({value: c.id, label: channelDisplay(c).name})));
    if (id === null) return;
    await openChannel(id);
    if (activeChannelId === id) armMomentCapture();
}

function pwaSyncCompose() {
    document.getElementById('thread-form').classList.toggle('has-text',
        !!document.getElementById('thread-input').value.trim());
}

function pwaThreadHead(c) {
    const head = document.createElement('div');
    head.className = 'pwa-thread-head';
    head.append(pwaConversationAvatar(channelDisplay(c), 'pwa-thread-av'));
    const sub = document.createElement('div');
    sub.className = 'pwa-thread-sub';
    if ((c.member_ids || []).includes('argyle') && c.kind === 'dm') {
        sub.textContent = 'Ask anything · every exchange lands here';
    } else if (c.kind === 'family' || c.kind === 'group') {
        const members = c.kind === 'family'
            ? membersData.filter(m => ['parent', 'adult', 'child'].includes(m.role) && (!m.status || m.status === 'active'))
            : (c.member_ids || []).map(id => id === 'argyle' ? {id, name: 'Argyle'}
                : membersData.find(m => m.id === id)).filter(Boolean);
        sub.textContent = members.filter(m => m.id !== selectedMemberId)
            .map(m => (m.name || '').split(' ')[0]).filter(Boolean).join(', ');
    } else if (c.kind === 'event') {
        const date = c.event_end ? new Date(c.event_end) : null;
        if (date && Number.isFinite(date.getTime())) {
            const now = new Date();
            const startOf = d => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
            const daysAgo = Math.round((startOf(now) - startOf(date)) / 86400000);
            sub.textContent = daysAgo === 0 ? 'Today' : daysAgo === 1 ? 'Yesterday'
                : daysAgo > 1 && daysAgo < 7 ? date.toLocaleDateString([], {weekday: 'long'})
                : date.toLocaleDateString([], date.getFullYear() === now.getFullYear()
                    ? {weekday: 'short', month: 'short', day: 'numeric'} : {month: 'short', day: 'numeric', year: 'numeric'});
        } else {
            const day = String(c.title || '').match(/\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)(?:day|sday|nesday|rsday|urday)?\b/i);
            sub.textContent = day ? day[0] : 'Event thread';
        }
    }
    head.append(sub);
    return head;
}
