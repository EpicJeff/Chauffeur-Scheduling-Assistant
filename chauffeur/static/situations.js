// static/situations.js — the one card builder for everything that needs a
// person (spec: docs/superpowers/specs/2026-10-09-situations-design.md §3).
// Vanilla, so Alpine pages and the PWA's renderers share it. Markup rule:
// the next step is the ONE primary button; everything else is quiet.
// Read-only renders (a wall, no identity) draw no buttons at all.
window.Situations = (function () {
  const VERB_LABELS = {
    'assign': 'Assign', 'ask': 'Ask', 'plan': 'Plan', 'prepare': 'Line it up', 'do': 'Approve',
    'done': 'Done', 'skip': 'Skip', 'research': 'Look it up', 'draft': 'Draft', 'advance': 'Next step',
    'answer': 'Answer', 'close': 'Close', 'snooze': 'Not now', 'dismiss': 'Dismiss', 'own': 'I\'ll handle it',
    'unread': 'Argyle got it wrong', 'release': 'Share', 'submit': 'Book it', 'verify': 'Did it go through?',
    'subject': 'About', 'approve_plan': 'Approve plan', 'run_stage': 'Do this'
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

  // A reading-answered ask says so: a person can always tell a tap from
  // what Argyle read, and the quiet "Argyle got it wrong" option undoes it.
  function readLine(a) {
    const base = a.state === 'yes' ? 'Argyle read their reply as yes' : 'Argyle read their reply as no';
    return a.read_summary ? `${base} — "${a.read_summary}"` : base;
  }

  function askLine(a, ctx) {
    const report = ctx.canWrite && !ctx.readOnly && (a.state === 'sent' || a.state === 'drafted')
      ? ` <button class="${QUIET}" data-ask-answer="yes" data-ask-id="${a.id}">said yes</button>`
        + ` <button class="${QUIET}" data-ask-answer="no" data-ask-id="${a.id}">said no</button>`
        + (a.state === 'drafted' ? ` <button class="${QUIET}" data-ask-sent="${a.id}">Sent it</button>` : '')
      : '';
    // A reading-answered ask carries its own quiet undo, right under the line.
    const unread = ctx.canWrite && !ctx.readOnly && a.answered_by === 'argyle' && (a.state === 'yes' || a.state === 'no')
      ? ` <button class="${QUIET}" data-sit-act="unread:${esc(a.id)}">${esc(VERB_LABELS.unread)}</button>` : '';
    // A mail that left by the household address reads as what it was.
    const lead = a.sent_via === 'household'
      ? `Emailed ${esc(a.to_name)}`
      : `Asked ${esc(a.to_name)} by ${esc(CHANNEL_LABELS[a.channel] || a.channel)}`;
    return `<div class="text-xs text-gray-400 mt-1" data-ask-line="${a.id}">${lead} ${esc(when(a.sent_at || a.asked_at))}: ${esc(a.answered_by === 'argyle' ? readLine(a) : askState(a))}${report}${unread}</div>`;
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
    // unread lives under its ask's ledger line (askLine), not in the option row.
    const rest = opts.filter(o => (!next || o.id !== next.id) && o.verb !== 'unread');
    // A viewer who cannot act (a child owner, a wall) still reads the
    // question Argyle's mission is waiting on (browse missions §5).
    const askKind = next && next.payload ? next.payload.ask : null;
    const askOnly = (!ctx.canWrite || ctx.readOnly) && next && /^answer:mission:/.test(next.id || '') && askKind === 'question'
      ? `<div class="sit-ask-line text-xs text-amber-200 mt-1">Argyle asks: ${esc(next.label)}</div>`
      : '';
    // A hand-off ("finish it on your phone") carries its link as a real link,
    // for the person who can act and the one who can only read.
    const handUrl = next && /^answer:/.test(next.id || '') && askKind === 'handoff'
      ? (((next.label || '').match(/https?:\/\/[^\s)]+/) || [])[0] || '').replace(/[.,;:]+$/, '') || null : null;
    const handLink = handUrl
      ? `<div class="mt-1"><a class="sit-link text-xs text-blue-400 underline underline-offset-2" href="${esc(handUrl)}" target="_blank" rel="noopener">Open it</a></div>`
      : '';
    const buttons = ((ctx.canWrite && !ctx.readOnly)
      ? `<div class="sit-next mt-2">${next ? `<button class="${PRIMARY}" data-sit-act="${esc(next.id)}">${esc(next.label)}</button>` : ''}</div>
         <div class="sit-options flex flex-wrap gap-2 mt-1.5">${rest.map(o => `<button class="${QUIET}" data-sit-act="${esc(o.id)}">${esc(o.label)}</button>`).join('')}</div>`
      : askOnly) + handLink;
    const since = when(s.since);
    const meta = [s.state, since ? `since ${since}` : '', s.due ? `due ${dueLabel(s.due)}` : '', (s.people || []).join(', ')].filter(Boolean).join(' · ');
    // A host that navigates for itself (the phone: one-list spec §5) gets a
    // button calling ctx.navigate(kind, id), never an anchor to an admin page.
    const subjTarget = !s.subject ? ''
      : typeof ctx.navigate === 'function'
        ? `<button type="button" class="underline underline-offset-2" data-sit-nav="${esc(s.subject.kind)}:${esc(s.subject.id)}">${esc(s.subject.title || s.subject.kind)}</button>`
        : `<a class="underline underline-offset-2" href="${esc((ctx.apiBase || '') + s.subject.link)}">${esc(s.subject.title)}</a>`;
    const subj = s.subject
      ? `<div class="sit-subject text-[11px] text-indigo-300 mt-0.5" data-sit-subject="${esc(s.subject.kind)}:${esc(s.subject.id)}">About: ${subjTarget}</div>`
      : '';
    const note = s.note_source === 'argyle'
      ? `<div class="sit-note text-xs text-gray-400 italic mt-0.5" data-source="argyle">${esc(s.status_note)}</div>`
      : `<div class="sit-note text-xs text-gray-500 mt-0.5" data-source="fallback">${esc(s.status_note)}</div>`;
    return `<div class="situation-card bg-gray-900 border border-gray-800 rounded-2xl p-3" data-kind="${esc(s.kind)}" data-id="${esc(s.id)}">
      <div class="flex items-start justify-between gap-2">
        <div class="sit-title text-sm text-gray-100">${esc(s.title)}</div>
        ${s.sensitivity === 'sensitive' ? '<span class="text-[10px] font-bold px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300 shrink-0">sensitive</span>' : ''}
      </div>
      <div class="text-[11px] text-gray-600 mt-0.5">${esc(meta)}</div>
      ${subj}
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
    if (option.verb === 'subject') {
      let payload;
      if (option.payload && option.payload.clear) {
        if (!window.promptConfirm || !await promptConfirm('Unlink it?', s.title, 'Unlink', 'Keep')) return;
        payload = { clear: true };
      } else {
        const query = window.promptInput ? await promptInput('What is this about?', 'A trip, a party, an event, a person, a list…') : null;
        if (!query) return;
        payload = { query };
      }
      try {
        let data = await post(ctx, `api/situations/${s.kind}/${s.id}/act`, { verb: 'subject', option_id: option.id, payload });
        if (data.status === 'choose' && (data.candidates || []).length) {
          const pick = window.promptChoice ? await promptChoice('Which one?', '', data.candidates.map(c => ({
            value: `${c.kind}:${c.id}`, label: `${c.title} (${c.kind})`
          }))) : null;
          if (!pick) return;
          const colon = pick.indexOf(':');
          data = await post(ctx, `api/situations/${s.kind}/${s.id}/act`, {
            verb: 'subject', option_id: option.id, payload: { kind: pick.slice(0, colon), id: pick.slice(colon + 1) }
          });
        }
        if (data.message) alert_(data.message);
      } catch (e) { alert_(e.message); }
      if (ctx.onChange) ctx.onChange();
      return;
    }
    const payload = {};
    // Closing is the one verb with no way back (a closed thread cannot be
    // reopened), so it asks first wherever the card is drawn.
    if (option.verb === 'close' && window.promptConfirm) {
      if (!await promptConfirm(`${option.label}?`, s.title, option.label, 'Keep it')) return;
    }
    if (option.verb === 'answer' && (option.payload || {}).ask === 'program_choice') {
      // Use / Make new / Not now: the tap is the answer. The option's own
      // payload (its choice id and option) goes as is; no words are asked for.
      Object.assign(payload, option.payload);
    } else if (['advance', 'answer', 'draft', 'research'].includes(option.verb)) {
      const ask = { advance: 'What is the next step?', answer: 'Your answer', draft: 'What should the message say?', research: 'What should I look up?' }[option.verb];
      // A reading-built option (confirm, reply) arrives pre-filled; the
      // person edits or accepts instead of retyping.
      const text = window.promptInput ? await promptInput(ask, '', { value: option.payload.next_action || option.payload.text || '' }) : null;
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

  // The approval preview shares the plan card's existing row treatment.
  function planPreviewHtml(plan) {
    const project = plan.project;
    let html = '';
    if (project) {
      const meta = [project.owner, project.audience_label, project.target_date].filter(Boolean).join(' · ');
      html += `<div class="text-xs text-gray-300 mt-2">${esc(project.id ? 'Project' : 'New project')}: ${esc(project.title)}
        <div class="text-gray-400">${esc(project.goal)}</div>
        <div class="text-gray-400">Done when: ${esc(project.done_when)}</div>
        ${meta ? `<div class="text-gray-400">${esc(meta)}</div>` : ''}</div>`;
    }
    const steps = plan.steps || [];
    const titles = new Map([...(plan.stages || []), ...steps].map(s => [s.id, s.title]));
    if (steps.length) {
      html += `<div class="text-xs text-gray-300 mt-2">Your steps${steps.map(s => {
        const needs = (s.needs || []).map(id => titles.get(id) || id).join(', ');
        return `<div class="mt-1">${esc(s.title)} · ${esc(s.owner || 'Unassigned')}
          ${needs ? `<div class="text-gray-400">After: ${esc(needs)}</div>` : ''}
          ${s.due_date ? `<div class="text-gray-400">Due: ${esc(s.due_date)}</div>` : ''}</div>`;
      }).join('')}</div>`;
    }
    return html;
  }

  function planStepperHtml(plan) {
    const words = { pending: 'waiting', proposed: 'needs your yes', running: 'running',
      done: 'done', skipped: 'skipped', partial: 'partial', uncertain: 'check these' };
    return (plan && plan.state === 'proposed' ? planPreviewHtml(plan) : '') + ((plan || {}).stages || []).map(s =>
      `<div class="text-xs text-gray-400 mt-1" data-stage-state="${esc(s.state)}">${esc(s.title)} · ${esc(words[s.state] || s.state)}</div>`
    ).join('');
  }

  // The DM course card (programs spec §7): what a chat-made program is, with
  // Preview (the course page), Steer (the course page with its Steer box)
  // and Set it up on the run the choice already made. Markup is the project
  // card's (app.html renderProjectCard). `me` is the viewer's member id: your
  // own program reads "Set it up".
  function programCourseHtml(card, me) {
    const phases = (card.phases || []).map(p =>
      `<li>${esc(p.name)} · ${esc(p.lessons)} ${p.lessons === 1 ? 'lesson' : 'lessons'}</li>`).join('');
    const setup = card.run_id
      ? `<button data-course-setup="${esc(card.run_id)}" data-project-id="${esc(card.project_id || '')}" class="px-3 py-1 rounded-lg text-xs font-semibold bg-blue-600 text-white">${
          esc(card.for_member_id && card.for_member_id === me ? 'Set it up' : 'Set it up for ' + (card.for_name || 'them'))}</button>` : '';
    return `<div class="mt-1 px-3 py-2 rounded-xl bg-gray-900 border border-gray-700" data-course-card="${esc(card.library_id)}">
        <span class="text-xs uppercase tracking-wide text-teal-300 font-bold">Program</span>
        <div class="text-sm text-gray-100 font-semibold mt-1">${esc(card.title)}</div>
        <div class="text-xs text-gray-500 mt-0.5">${esc(card.source_line)}</div>
        ${phases ? `<ul class="text-xs text-gray-300 mt-1">${phases}</ul>` : ''}
        <div class="flex flex-wrap gap-2 mt-2">${setup}
          <button data-course-preview="${esc(card.library_id)}" class="px-3 py-1 rounded-lg text-xs font-semibold bg-gray-700 text-gray-200">Preview</button>
          <button data-course-steer="${esc(card.library_id)}" class="px-3 py-1 rounded-lg text-xs font-semibold bg-gray-700 text-gray-200">Steer</button></div></div>`;
  }

  // One listener for every course card, wherever a DM draws it.
  if (typeof document !== 'undefined' && !window.__chfCourseCards) {
    window.__chfCourseCards = true;
    document.addEventListener('click', ev => {
      const b = ev.target.closest && ev.target.closest('button[data-course-preview], button[data-course-steer], button[data-course-setup]');
      if (!b) return;
      if (b.dataset.coursePreview) {
        if (window.chfLibrary) window.chfLibrary.open(b.dataset.coursePreview);
        return;
      }
      if (b.dataset.courseSteer) {
        if (window.chfLibrary) window.chfLibrary.open(b.dataset.courseSteer, {steer: true});
        return;
      }
      if (window.chfProgramSetup) window.chfProgramSetup.open({runId: b.dataset.courseSetup, projectId: b.dataset.projectId || null});
      else alert_('Open the program from its project to set it up.');
    });
  }

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
      if (b.dataset.sitNav) {
        const at = b.dataset.sitNav.indexOf(':');
        if (typeof ctx2.navigate === 'function') ctx2.navigate(b.dataset.sitNav.slice(0, at), b.dataset.sitNav.slice(at + 1));
        return;
      }
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

  // Thread-owned photos carry their serving query; older photos use the
  // shared archive. Keep ingress prefixes and let chfAuthUrl append with &.
  function threadPhotoUrl(h, apiBase) {
    const url = h.url && h.url.includes('thread_id=')
      ? apiBase + h.url.replace(/^\//, '') : apiBase + 'api/media/' + h.media_id;
    return window.chfAuthUrl ? window.chfAuthUrl(url) : url;
  }

  function render(el, list, ctx) {
    ctx = ctx || {};
    el.innerHTML = (list || []).map(s => cardHtml(s, ctx)).join('');
    el.__situations = {}; (list || []).forEach(s => { el.__situations[`${s.kind}:${s.id}`] = s; });
    bind(el, ctx);
  }

  return { VERB_LABELS, verbLabel, cardHtml, planPreviewHtml, planStepperHtml, programCourseHtml, threadPhotoUrl, render, bind, act, ask };
})();
