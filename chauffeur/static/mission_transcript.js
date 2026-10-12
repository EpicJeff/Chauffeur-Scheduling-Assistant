/* The transcript's helpers, shared by every page that includes
   components/mission_transcript.html (/missions and the thread card's
   details). One implementation: an Alpine component exposes these under the
   names the template uses (stepKindClass, stepResultText, stepArgsText,
   isLastAsk, isTapAskPending, verifyOpen, submitNoteText) by delegating here. */
(function () {
  function compact(v) {
    if (v === null || v === undefined) return '';
    if (typeof v === 'object' && !Array.isArray(v) && !Object.keys(v).length) return '';
    let s;
    try { s = JSON.stringify(v); } catch (e) { s = String(v); }
    return s.length > 400 ? s.slice(0, 400) + '…' : s;
  }
  window.MissionTranscript = {
    stepKindClass(kind) {
      if (kind === 'proposal') return 'bg-violet-500/20 text-violet-300';
      if (kind === 'ask') return 'bg-amber-500/20 text-amber-300';
      if (kind === 'draft') return 'bg-teal-500/20 text-teal-300';
      if (kind === 'browse') return 'bg-sky-500/20 text-sky-300';
      return 'bg-gray-700 text-gray-300';   // llm | tool | note
    },
    stepResultText(step) { return compact(step.result_json); },
    // The proposal's exact args_json — same compact idiom as the result, so
    // Approve never asks a parent to trust a summary sentence for what will
    // actually execute.
    stepArgsText(step) { return compact(step.args_json); },
    isLastAsk(mission, step) {
      const asks = (mission.steps || []).filter(s => s.kind === 'ask');
      return asks.length > 0 && asks[asks.length - 1].id === step.id;
    },
    isTapAskPending(mission) {
      const asks = (mission.steps || []).filter(s => s.kind === 'ask');
      return asks.length > 0 && ['release', 'submit', 'verify'].includes(asks[asks.length - 1].name);
    },
    isReleasePending(mission) { return this.isTapAskPending(mission); },
    // A verify card is answerable while it is the newest ask on a waiting
    // mission, or on a mission that ended before a late report raised it
    // (its attempt still unresolved): services/missions.verify_open.
    verifyOpen(mission, step) {
      if (!this.isLastAsk(mission, step)) return false;
      if (mission.status === 'waiting_user') return true;
      if (!['done', 'blocked', 'dropped'].includes(mission.status)) return false;
      const aid = (step.result_json || {}).attempt_step_id;
      const att = (mission.steps || []).find(s => s.id === aid);
      const o = att ? (att.result_json || {}).outcome : 'none';
      return o === null || o === undefined || o === 'unknown';
    },
    submitNoteText(step) {
      const r = step.result_json || {};
      if (step.name === 'submit_approved') return `Approved: press '${r.button || ''}'.`;
      if (step.name === 'submit_attempt') return `Pressed '${r.button || ''}' at ${r.url || ''}: ${r.outcome || 'no answer yet'}` + (r.resolved_by ? ` (${r.resolved_by.name || 'a parent'} said so)` : '') + '.';
      if (step.name === 'submitted') return (r.verb === 'book' ? 'Booked' : 'Submitted') + (r.confirmation ? `, confirmation ${r.confirmation}` : '') + (r.by_hand ? ` (confirmed by ${r.by || 'a parent'})` : '') + '.';
      if (step.name === 'submit_rejected') return `The site rejected it: ${r.error || ''}`;
      if (step.name === 'submit_failed') return `Did not go through${r.detail ? ': ' + r.detail : ''}.`;
      return r.note || '';
    },
    proposalOutcome(mission, step) {
      const pid = (step.result_json || {}).proposal_id;
      if (!pid) return null;
      const note = (mission.steps || []).find(s => s.kind === 'note'
        && (s.name === 'proposal_approve' || s.name === 'proposal_dismiss')
        && (s.result_json || {}).proposal_id === pid);
      if (!note) return null;
      return note.name === 'proposal_approve' ? 'approved' : 'dismissed';
    },
    // POST a proposal's approve/dismiss; the caller refreshes its own view.
    async actProposal(apiBase, missionId, proposalId, act) {
      const r = await fetch(apiBase + `api/missions/${missionId}/proposals/${proposalId}/act`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ act })
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || "Couldn't do that just now.");
      return d;
    },
    async _post(apiBase, path, body) {
      const r = await fetch(apiBase + path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || "That didn't work.");
      return d;
    },
    // Every tap carries the ask's id: a stale card can never answer a newer question.
    release(apiBase, missionId, decision, askId) { return this._post(apiBase, `api/missions/${missionId}/release`, { decision, ask_id: askId }); },
    submit(apiBase, missionId, decision, askId) { return this._post(apiBase, `api/missions/${missionId}/submit`, { decision, ask_id: askId }); },
    verify(apiBase, missionId, askId, outcome, detail) { return this._post(apiBase, `api/missions/${missionId}/verify`, { ask_id: askId, outcome, detail: detail || '' }); }
  };
})();
