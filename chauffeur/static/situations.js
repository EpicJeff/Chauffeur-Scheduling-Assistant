// static/situations.js — the one card builder for everything that needs a
// person (spec: docs/superpowers/specs/2026-10-09-situations-design.md §3).
// Vanilla, so Alpine pages and the PWA's renderers share it. Markup rule:
// the next step is the ONE primary button; everything else is quiet.
// Read-only renders (a wall, no identity) draw no buttons at all.
window.Situations = (function () {
  const VERB_LABELS = {
    'assign': 'Assign', 'ask': 'Ask', 'plan': 'Plan', 'prepare': 'Line it up', 'do': 'Approve',
    'done': 'Done', 'skip': 'Skip', 'research': 'Look it up', 'draft': 'Draft', 'advance': 'Next step',
    'answer': 'Answer', 'close': 'Close', 'snooze': 'Not now', 'dismiss': 'Dismiss', 'own': 'I\'ll handle it'
  };
  const CHANNEL_LABELS = { chauffeur: 'Chauffeur', email: 'Email', text: 'Text', in_person: 'In person' };

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }
  function when(ts) {
    if (!ts) return '';
    try { return new Date(ts * 1000).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' }); } catch (e) { return ''; }
  }
  function alert_(msg) { if (window.showGlobalAlert) showGlobalAlert(msg); else console.warn(msg); }

  const PRIMARY = 'text-xs font-bold px-3 py-1.5 rounded-lg bg-blue-600 text-white active:bg-blue-700';
  const QUIET = 'text-xs font-bold px-3 py-1.5 rounded-lg bg-gray-800 text-gray-300 border border-gray-700 active:bg-gray-700';

  function askState(a) {
    if (a.state === 'yes') {
      if (a.outcome === 'applied') return 'said yes, covering';
      if (a.outcome === 'superseded') return 'said yes, but someone else already has it';
      if (a.outcome === 'stale') return 'said yes, but the time moved; confirm';
      if (a.outcome === 'failed') return 'said yes; finish by hand';
      if (a.outcome === 'manual') return 'said yes; apply by hand';
      if (a.outcome === 'claimed') return 'said yes; applying';
      return 'said yes';
    }
    if (a.state === 'no') return 'said no';
    if (a.state === 'sent') return 'waiting';
    if (a.state === 'drafted') return 'drafted, not sent';
    return a.state || '';
  }

  function askLine(a, ctx) {
    const report = ctx.canWrite && !ctx.readOnly && (a.state === 'sent' || a.state === 'drafted')
      ? ` <button class="${QUIET}" data-ask-answer="yes" data-ask-id="${a.id}">said yes</button>`
        + ` <button class="${QUIET}" data-ask-answer="no" data-ask-id="${a.id}">said no</button>`
        + (a.state === 'drafted' ? ` <button class="${QUIET}" data-ask-sent="${a.id}">Sent it</button>` : '')
      : '';
    return `<div class="text-xs text-gray-400 mt-1" data-ask-line="${a.id}">Asked ${esc(a.to_name)} by ${esc(CHANNEL_LABELS[a.channel] || a.channel)} ${esc(when(a.sent_at || a.asked_at))}: ${esc(askState(a))}${report}</div>`;
  }

  function dueLabel(due) {
    if (!due) return '';
    // A bare date (a thread's next_action_at) is a calendar day: parse it as
    // LOCAL midnight, or Date.parse's UTC midnight shows the day before
    // anywhere west of Greenwich.
    const ts = typeof due === 'number' ? due
      : /^\d{4}-\d{2}-\d{2}$/.test(due) ? new Date(due + 'T00:00:00').getTime() / 1000
      : Date.parse(due) / 1000;
    return isNaN(ts) ? String(due) : when(ts);
  }

  function cardHtml(s, ctx) {
    ctx = ctx || {};
    const opts = s.options || [];
    const next = s.next_step;
    const rest = opts.filter(o => !next || o.id !== next.id);
    const buttons = (ctx.canWrite && !ctx.readOnly)
      ? `<div class="sit-next mt-2">${next ? `<button class="${PRIMARY}" data-sit-act="${esc(next.id)}">${esc(next.label)}</button>` : ''}</div>
         <div class="sit-options flex flex-wrap gap-2 mt-1.5">${rest.map(o => `<button class="${QUIET}" data-sit-act="${esc(o.id)}">${esc(o.label)}</button>`).join('')}</div>`
      : '';
    const since = when(s.since);
    const meta = [s.state, since ? `since ${since}` : '', s.due ? `due ${dueLabel(s.due)}` : '', (s.people || []).join(', ')].filter(Boolean).join(' · ');
    const note = s.note_source === 'argyle'
      ? `<div class="sit-note text-xs text-gray-400 italic mt-0.5" data-source="argyle">${esc(s.status_note)}</div>`
      : `<div class="sit-note text-xs text-gray-500 mt-0.5" data-source="fallback">${esc(s.status_note)}</div>`;
    return `<div class="situation-card bg-gray-900 border border-gray-800 rounded-2xl p-3" data-kind="${esc(s.kind)}" data-id="${esc(s.id)}">
      <div class="flex items-start justify-between gap-2">
        <div class="sit-title text-sm text-gray-100">${esc(s.title)}</div>
        ${s.sensitivity === 'sensitive' ? '<span class="text-[10px] font-bold px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300 shrink-0">sensitive</span>' : ''}
      </div>
      <div class="text-[11px] text-gray-600 mt-0.5">${esc(meta)}</div>
      ${note}
      ${buttons}
      <div class="sit-ask-flow mt-2" style="display:none"></div>
      <div class="sit-asks">${(s.asks || []).filter(a => a.state !== 'withdrawn').map(a => askLine(a, ctx)).join('')}</div>
      ${ctx.extraHtml ? ctx.extraHtml(s) : ''}
    </div>`;
  }

  async function post(ctx, path, body) {
    const res = await fetch(`${ctx.apiBase || ''}${path}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(Object.assign({}, body || {}, ctx.memberId ? { member_id: ctx.memberId } : {})) });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || 'That did not work.');
    return data;
  }

  async function act(s, option, ctx) {
    const payload = {};
    // Closing is the one verb with no way back (a closed thread cannot be
    // reopened), so it asks first wherever the card is drawn.
    if (option.verb === 'close' && window.promptConfirm) {
      if (!await promptConfirm(`${option.label}?`, s.title, option.label, 'Keep it')) return;
    }
    if (['advance', 'answer', 'draft', 'research'].includes(option.verb)) {
      const ask = { advance: 'What is the next step?', answer: 'Your answer', draft: 'What should the message say?', research: 'What should I look up?' }[option.verb];
      const text = window.promptInput ? await promptInput(ask, '') : null;
      if (!text) return;
      if (option.verb === 'advance') {
        payload.next_action = text;
        const d = window.promptInput ? await promptInput('By when? (YYYY-MM-DD, or blank)', '') : '';
        if (d) payload.next_action_at = d;
      } else payload.text = text;
    }
    try {
      const data = await post(ctx, `api/situations/${s.kind}/${s.id}/act`, { verb: option.verb, option_id: option.id, payload });
      if (data.message && option.verb !== 'own') alert_(data.message);
    } catch (e) { alert_(e.message); }
    if (ctx.onChange) ctx.onChange();
  }

  function askFlowHtml(s, option) {
    const to = (option.payload.to || {}).name;
    const head = to ? `Ask ${esc(to)}: ${esc(option.payload.what)}` : `Ask someone to ${esc(option.payload.what)}`;
    const nameBox = to ? '' : `<input class="sit-ask-name w-full bg-gray-800 border border-gray-700 rounded-lg px-2 py-1 text-sm text-gray-100 mb-2" placeholder="Who?">`;
    return `<div class="text-xs text-gray-300 mb-1">${head}</div>${nameBox}
      <div class="text-[11px] text-gray-500 mb-1">How?</div>
      <div class="sit-ask-channels flex flex-wrap gap-2"><button class="${QUIET}" data-ask-cancel="1">Cancel</button></div>`;
  }

  function channelButtons(channels) {
    return channels.map(c => `<button class="${QUIET}" data-ask-channel="${esc(c.channel)}">${esc(c.label || CHANNEL_LABELS[c.channel] || c.channel)}</button>`).join('')
      + `<button class="${QUIET}" data-ask-cancel="1">Cancel</button>`;
  }

  // The server says how a person can be reached (a member adds Chauffeur;
  // every copy channel is always there), from a known id or a typed name.
  async function lookupChannels(ctx, to) {
    const q = new URLSearchParams();
    if (to.name) q.set('name', to.name);
    if (to.member_id) q.set('member_id', to.member_id);
    if (to.contact_id) q.set('contact_id', to.contact_id);
    try {
      const r = await fetch(`${ctx.apiBase || ''}api/asks/channels?${q.toString()}`);
      if (r.ok) return await r.json();
    } catch (e) { /* fall through to the copy channels */ }
    return { to, channels: ['email', 'text', 'in_person'].map(c => ({ channel: c, label: CHANNEL_LABELS[c], link: null })) };
  }

  function draftHtml(a, ch) {
    const text = (a.draft_subject ? `Subject: ${a.draft_subject}\n\n` : '') + (a.draft_body || '');
    const query = ch.channel === 'email'
      ? `?subject=${encodeURIComponent(a.draft_subject || '')}&body=${encodeURIComponent(a.draft_body || '')}`
      : `?&body=${encodeURIComponent(a.draft_body || '')}`;
    const link = a.link ? `<a class="${QUIET} inline-block" href="${esc(a.link)}${query}">Open in ${esc(CHANNEL_LABELS[ch.channel])}</a>` : '';
    const sent = ch.channel === 'in_person' ? 'Asked them' : 'Sent it';
    return `<div class="text-[11px] text-gray-500 mb-1">${a.draft_source === 'argyle' ? 'Argyle drafted this; change anything' : 'A plain draft; change anything'}</div>
      <textarea class="sit-draft w-full bg-gray-800 border border-gray-700 rounded-lg px-2 py-1 text-sm text-gray-100" rows="5">${esc(text)}</textarea>
      <div class="flex flex-wrap gap-2 mt-1.5">
        <button class="${QUIET}" data-ask-copy="${a.id}">Copy</button>${link}
        <button class="${PRIMARY}" data-ask-sent="${a.id}">${sent}</button>
        <button class="${QUIET}" data-ask-withdraw="${a.id}">Never mind</button></div>`;
  }

  async function ask(s, option, ctx, card) {
    const flow = card.querySelector('.sit-ask-flow');
    let to = Object.assign({}, option.payload.to || {});
    flow.innerHTML = askFlowHtml(s, option);
    flow.style.display = 'block';
    const channelsEl = flow.querySelector('.sit-ask-channels');
    const nameBox = flow.querySelector('.sit-ask-name');
    const refreshChannels = async () => {
      const typed = nameBox ? nameBox.value.trim() : '';
      if (nameBox && !typed) { channelsEl.innerHTML = channelButtons([]); return; }
      const d = await lookupChannels(ctx, typed ? { name: typed } : to);
      to = Object.assign({}, to, d.to || {});
      channelsEl.innerHTML = channelButtons(d.channels || []);
    };
    if (nameBox) nameBox.addEventListener('change', refreshChannels);
    refreshChannels();
    let inFlight = false;
    flow.onclick = async (ev) => {
      const b = ev.target.closest('button'); if (!b) return;
      if (b.dataset.askCancel) { flow.style.display = 'none'; flow.innerHTML = ''; return; }
      if (b.dataset.askChannel) {
        if (inFlight) return;
        const body = { kind: s.kind, id: s.id, option_id: option.id, channel: b.dataset.askChannel, to };
        if (!body.to.name) { alert_('Who are you asking?'); return; }
        inFlight = true;
        try {
          const data = await post(ctx, 'api/asks', body);
          const a = data.ask, ch = (data.channels || []).find(c => c.channel === b.dataset.askChannel) || { channel: b.dataset.askChannel };
          if (b.dataset.askChannel === 'chauffeur') { flow.style.display = 'none'; alert_(`Sent to ${a.to_name} on Chauffeur.`); if (ctx.onChange) ctx.onChange(); return; }
          a.link = ch.link; flow.innerHTML = draftHtml(a, ch);
        } catch (e) { alert_(e.message); }
        finally { inFlight = false; }
        return;
      }
      if (b.dataset.askCopy) {
        const ta = flow.querySelector('.sit-draft');
        try { await navigator.clipboard.writeText(ta.value); alert_('Copied.'); } catch (e) { ta.select(); document.execCommand('copy'); alert_('Copied.'); }
        return;
      }
      if (b.dataset.askSent) { try { await post(ctx, `api/asks/${b.dataset.askSent}/sent`, {}); } catch (e) { alert_(e.message); } flow.style.display = 'none'; if (ctx.onChange) ctx.onChange(); return; }
      if (b.dataset.askWithdraw) { try { await post(ctx, `api/asks/${b.dataset.askWithdraw}/withdraw`, {}); } catch (e) { alert_(e.message); } flow.style.display = 'none'; if (ctx.onChange) ctx.onChange(); }
    };
  }

  function verbLabel(verb) { return VERB_LABELS[verb] || verb; }

  // One delegated listener per lane element. Pages that draw the cards
  // themselves (Alpine x-html) call bind() with a lookup; render() calls it
  // for its own map. Re-binding only swaps the ctx: never a second listener.
  function bind(el, ctx) {
    el.__sitCtx = ctx || {};
    if (el.__sitBound) return;
    el.__sitBound = true;
    el.addEventListener('click', async (ev) => {
      const ctx2 = el.__sitCtx || {};
      const b = ev.target.closest('button'); if (!b || !el.contains(b)) return;
      if (b.closest('.sit-ask-flow')) return;      // the flow has its own handler
      const card = b.closest('.situation-card'); if (!card) return;
      const s = (ctx2.lookup && ctx2.lookup(card.dataset.kind, card.dataset.id))
             || (el.__situations || {})[`${card.dataset.kind}:${card.dataset.id}`];
      if (!s) return;
      if (b.dataset.sitAct) {
        const option = (s.options || []).find(o => o.id === b.dataset.sitAct); if (!option) return;
        if (ctx2.intercept && ctx2.intercept(s, option, card)) return;
        if (option.verb === 'ask') return ask(s, option, ctx2, card);
        return act(s, option, ctx2);
      }
      if (b.dataset.askAnswer) {
        try { const d = await post(ctx2, `api/asks/${b.dataset.askId}/answer`, { answer: b.dataset.askAnswer, reported: true }); if (d.message) alert_(d.message); }
        catch (e) { alert_(e.message); }
        if (ctx2.onChange) ctx2.onChange();
        return;
      }
      if (b.dataset.askSent) {
        try { await post(ctx2, `api/asks/${b.dataset.askSent}/sent`, {}); } catch (e) { alert_(e.message); }
        if (ctx2.onChange) ctx2.onChange();
      }
    });
  }

  function render(el, list, ctx) {
    ctx = ctx || {};
    el.innerHTML = (list || []).map(s => cardHtml(s, ctx)).join('');
    el.__situations = {}; (list || []).forEach(s => { el.__situations[`${s.kind}:${s.id}`] = s; });
    bind(el, ctx);
  }

  return { VERB_LABELS, verbLabel, cardHtml, render, bind, act, ask };
})();
