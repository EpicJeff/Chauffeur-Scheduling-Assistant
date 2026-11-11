import { createFlags } from './flags.js';
import { report } from './api.js';

const key = item => !item ? '' : item.kind === 'pause' ? `pause:${item.build}:${item.id || item.step}`
  : item.kind === 'flag' ? `flag:${item.building}:${item.index}:${item.flag.text}` : `proposal:${item.building}:${item.id}`;

export function createChecks(view, { api, getBuild, getModel, getPlan, tools, panel, canEdit,
  signal, op = api.op, flags, pauses, onClose }) {
  const card = document.createElement('aside'); card.id = 'check-card';
  card.setAttribute('data-step-panel', 'Check it'); card.setAttribute('aria-label', 'Check it');
  document.getElementById('piece-card').after(card);
  const adjustment = pauses && document.getElementById('pause-card');
  const adjustmentHome = adjustment?.parentElement;
  const acceptButton = pauses && document.getElementById('pause-accept');
  const rereadButton = pauses && document.getElementById('pause-reread');
  const rereadEstimate = () => Number(pauses?.rereadEstimate?.()
    ?? selected?.stepInfo?.estimate ?? selected?.stepInfo?.last_cost ?? selected?.stepInfo?.cost ?? 0);
  const review = flags || createFlags({ view, getModel, getPlan, tools, panel, op, canEdit, signal, managed: true });
  let rows = [], selected = null, signature = '', busy = false, dismissed = false, framing = false, emptyOpen = false, frame;
  const items = () => {
    const build = getBuild(), buildings = getModel()?.buildings || [];
    return [
      ...(build?.state === 'paused' && build.pause ? [{ ...build.pause, kind: 'pause', build: build.id,
        stepInfo: build.steps?.find(s => s.id === build.pause.step) }] : []),
      ...buildings.flatMap(b => (b.flags || []).map((flag, index) => ({ kind: 'flag', building: b.id, index, flag }))),
      ...buildings.flatMap(b => (b.proposals || []).map(p => ({ ...p, kind: 'proposal', building: b.id, id: p.id || p.piece.id }))),
    ];
  };
  function button(text, action, always = false) {
    const node = document.createElement('button'); node.type = 'button'; node.textContent = text;
    node.disabled = !always && (busy || !canEdit());
    node.addEventListener('click', () => Promise.resolve().then(action).catch(api.report || report), { signal });
    return node;
  }
  function focus() {
    if (!selected || dismissed) return;
    framing = true;
    try {
      if (selected.kind === 'pause') { review.dismiss(); pauses?.show(); }
      else { pauses?.dismiss(); review.review(selected); }
    } finally { framing = false; }
  }
  function draw() {
    if (adjustment) adjustmentHome.append(adjustment);
    card.replaceChildren(); card.hidden = dismissed || !selected && !emptyOpen || !canEdit();
    card.setAttribute('data-check-kind', selected?.kind || 'empty');
    pauseControls();
    if (card.hidden) return;
    const title = document.createElement('h3'); title.textContent = selected?.stepInfo?.label || 'Check this piece';
    const close = button('Close', dismiss, true); close.setAttribute('aria-label', 'Close check');
    if (!selected) {
      const text = document.createElement('p'); text.textContent = 'Nothing needs checking.';
      card.append(title, close, text); return;
    }
    const text = document.createElement('p');
    text.textContent = selected.kind === 'pause' ? selected.why || 'Check this part of your house.'
      : selected.kind === 'flag' ? selected.flag.text : 'A new reading suggests a change. Your version stays until you choose Use this.';
    card.append(title, close, text);
    const item = selected;
    if (item.kind === 'proposal') {
      card.append(button('Use this', () => save(() => op({ op: 'accept_proposal', building: item.building, id: item.id }))),
        button('Dismiss', () => save(() => op({ op: 'dismiss_proposal', building: item.building, id: item.id }))));
    } else {
      // A failed draft has no result to accept; it still offers editing, skip and re-read.
      if (item.kind !== 'pause' || getBuild()?.pause?.kind !== 'draft')
        card.append(item.kind === 'pause' && acceptButton ? acceptButton : button('Looks right', () => save(() => item.kind === 'pause'
          ? answer(item, { accept: true })
          : op({ op: 'set', building: item.building, field: 'flag_ok', value: { index: item.index, text: item.flag.text, flag: item.flag } }))));
      card.append(button('Fix it', () => {
        if (item.kind === 'pause') {
          const b = getPlan()?.buildings?.find(b => b.id === getBuild()?.part)
            || getPlan()?.buildings?.find(b => !b.id.startsWith('editor-preview:'));
          if (b) tools.select({ id: item.stepInfo?.level || b.id, building: b.id });
          pauses?.show(); panel.message('Adjust this part in the house, then check it again.');
        }
        else { focus(); dismiss(); }
      }));
    }
    card.append(button('Skip for now', async () => {
      if (item.kind === 'pause') await save(() => answer(item, { skip: true }), false);
      next();
    }));
    if (item.kind === 'pause') {
      const estimate = rereadEstimate();
      const label = `Read it again · about $${estimate.toFixed(2)}`;
      if (rereadButton) { rereadButton.textContent = label; card.append(rereadButton); }
      else card.append(button(label, () => save(async () => {
        if (await window.promptConfirm('Read it again?', 'Reading again adds to the running cost.', 'Read it again', 'Cancel'))
          await api.request(`build/${encodeURIComponent(item.build)}/reread`, 'POST', { step: item.step });
      }, false)));
      if (adjustment) { card.append(adjustment); adjustment.hidden = false; }
    }
  }
  function pauseControls() {
    const hidden = card.hidden || selected?.kind !== 'pause';
    if (adjustment) adjustment.hidden = hidden;
    if (acceptButton) {
      acceptButton.hidden = hidden || getBuild()?.pause?.kind === 'draft';
      acceptButton.textContent = 'Looks right';
    }
    if (rereadButton) {
      rereadButton.hidden = hidden;
      const estimate = rereadEstimate();
      rereadButton.textContent = `Read it again · about $${estimate.toFixed(2)}`;
    }
  }
  const answer = (item, decision) => api.request(`build/${encodeURIComponent(item.build)}/answer`, 'POST', { step: item.step, decision });
  async function save(action, advance = true) {
    if (busy || !canEdit()) return;
    const before = key(selected);
    busy = true; draw();
    try { await action(); }
    finally { busy = false; sync(); draw(); }
    if (advance && key(selected) === before && selected?.kind !== 'pause') next();
  }
  function sync() {
    const fresh = items(), nextSignature = JSON.stringify(fresh);
    if (signature === nextSignature) {
      card.hidden = dismissed || !selected && !emptyOpen || !canEdit();
      pauseControls();
      return;
    }
    const index = Math.max(0, rows.findIndex(r => key(r) === key(selected)));
    const previous = key(selected), oldPause = rows.find(r => r.kind === 'pause');
    rows = fresh; signature = nextSignature;
    const newPause = rows.find(r => r.kind === 'pause');
    if (newPause && key(newPause) !== key(oldPause)) { selected = newPause; dismissed = false; }
    else selected = rows.find(r => key(r) === previous) || rows[Math.min(index, rows.length - 1)] || null;
    if (key(selected) !== previous) focus();
    panel.checks(rows.length, show); draw();
  }
  function next() {
    sync(); const index = rows.findIndex(r => key(r) === key(selected));
    selected = rows[(index + 1) % rows.length] || null; dismissed = false; focus(); draw();
    return selected;
  }
  function show(item) {
    sync();
    if (item) selected = rows.find(r => r.kind === item.kind && r.building === item.building && r.id === item.id) || selected;
    dismissed = false; emptyOpen = true; focus(); draw();
  }
  function dismiss(notify = true) {
    if (framing) return;
    dismissed = true; pauses?.dismiss(); review.dismiss(); draw();
    if (notify !== false) onClose?.();
  }
  function tick() { sync(); frame = requestAnimationFrame(tick); }
  signal.addEventListener('abort', () => {
    cancelAnimationFrame(frame);
    if (adjustment) adjustmentHome.append(adjustment);
    if (acceptButton) adjustment.append(acceptButton, rereadButton);
    card.remove();
  }, { once: true });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !card.hidden) dismiss();
  }, { signal });
  sync(); frame = requestAnimationFrame(tick);
  return { queue: () => { sync(); return rows; }, current: () => { sync(); return selected; }, next, show, dismiss, sync };
}
