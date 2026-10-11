/* The transcript's helpers, shared by every page that includes
   components/mission_transcript.html (/missions and the thread card's
   details). One implementation: an Alpine component exposes these under the
   names the template uses (stepKindClass, stepResultText, stepArgsText,
   isLastAsk, isReleasePending) by delegating here. */
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
    isReleasePending(mission) {
      const asks = (mission.steps || []).filter(s => s.kind === 'ask');
      return asks.length > 0 && asks[asks.length - 1].name === 'release';
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
    // POST the release decision; the caller refreshes its own view.
    async release(apiBase, missionId, decision) {
      const r = await fetch(apiBase + `api/missions/${missionId}/release`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ decision })
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || "That didn't work.");
      return d;
    }
  };
})();
