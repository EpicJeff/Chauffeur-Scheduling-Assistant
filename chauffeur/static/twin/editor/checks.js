import { createFlags } from './flags.js';
import { report } from './api.js';
import { gutterCheckItems, gutterAcknowledgement, gutterOwner } from './gutter_controls.js';
import { cachedGutterPlacement } from '../gutters.js';

const key = item => !item ? '' : item.kind === 'pause' ? `pause:${item.build}:${item.id || item.step}`
  : item.kind === 'flag' ? `flag:${item.building}:${item.index}:${item.flag.text}` : `proposal:${item.building}:${item.id}`;

export function createChecks(view, { api, getBuild, getModel, getPlan, tools, panel, canEdit,
  signal, op = api.op, flags, pauses, onClose, dock }) {
  const card = document.createElement('aside'); card.id = 'check-card';
  card.setAttribute('data-step-panel', 'Check it'); card.setAttribute('aria-label', 'Check it');
  document.getElementById('piece-card').after(card);
  const adjustment = pauses && document.getElementById('pause-card');
  const adjustmentHome = adjustment?.parentElement;
  const acceptButton = pauses && document.getElementById('pause-accept');
  const rereadButton = pauses && document.getElementById('pause-reread');
  // The adopted accept and re-read buttons go back to the pause card's row before the check card
  // is cleared: pauses.js finds them by id, and a detached button reads as missing.
  const buttonHome = acceptButton?.parentElement;
  const sendHome = () => {
    if (acceptButton && buttonHome) buttonHome.prepend(acceptButton);
    if (rereadButton && buttonHome) buttonHome.append(rereadButton);
  };
  const rereadEstimate = () => Number(pauses?.rereadEstimate?.()
    ?? selected?.stepInfo?.estimate ?? selected?.stepInfo?.last_cost ?? selected?.stepInfo?.cost ?? 0);
  const review = flags || createFlags({ view, getModel, getPlan, tools, panel, op, canEdit, signal, managed: true });
  // The queue opens from Check it (or when a build pauses), never by itself on load: opening it
  // moves the camera and the floor, which must not happen before the person asks.
  let rows = [], selected = null, signature = '', busy = false, dismissed = true, framing = false, emptyOpen = false, frame;
  let seenModel, seenBuild, seenPlan, waiting = false, gutterRows = [];
  const sceneHost = view.renderer3?.domElement?.parentElement;
  const isHidden = () => dismissed || !selected && !emptyOpen || !canEdit();
  // While a flag or proposal check is open its card takes the piece card's slot, so the piece card
  // steps aside (a pause's card sits on the left and leaves the piece card where it is).
  const reviewing = () => card.closest?.('.editor-shell')
    ?.toggleAttribute('data-reviewing', !card.hidden && selected?.kind !== 'pause');
  const items = () => {
    const build = getBuild(), buildings = getModel()?.buildings || [];
    // Closed Check only consumes an existing renderer result. Opening Check
    // can compute a missing result through the same shared placement cache.
    const cached = cachedGutterPlacement(getPlan());
    if (cached || !dismissed || build?.state === 'paused') gutterRows = cached
      ? gutterCheckItems(getPlan(), cached) : gutterCheckItems(getPlan());
    return [
      ...(build?.state === 'paused' && build.pause ? [{ ...build.pause, kind: 'pause', build: build.id,
        stepInfo: build.steps?.find(s => s.id === build.pause.step) }] : []),
      ...buildings.flatMap(b => (b.flags || []).map((flag, index) => ({ kind: 'flag', building: b.id, index, flag }))),
      ...buildings.flatMap(b => (b.proposals || []).map(p => ({ ...p, kind: 'proposal', building: b.id, id: p.id || p.piece.id }))),
      ...gutterRows.filter(item => {
        const record = gutterOwner(getPlan(), item.building, item)?.record;
        return record?.gutter && item.flags.some(flag => !record.gutter_ack?.includes(flag));
      }),
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
    // A check chosen while the house is still drawing waits for the drawn house when the floor it
    // names is not in the scene being replaced (choosing it there would do nothing).
    const level = selected.kind === 'flag' ? selected.flag.level : selected.kind === 'proposal' ? selected.piece?.level : null;
    if (view.ready === false && sceneHost && level && !view.groups?.levels?.[`${selected.building}:${level}`]) {
      if (!waiting) {
        waiting = true;
        sceneHost.addEventListener('twinrebuilt', () => { waiting = false; focus(); }, { once: true, signal });
      }
      return;
    }
    framing = true;
    try {
      if (selected.kind === 'pause') { review.dismiss(); pauses?.show(); }
      else if (selected.kind === 'gutter') {
        pauses?.dismiss(); review.dismiss();
        tools.select({ id: selected.roof || selected.porch, building: selected.building });
        tools.focusDownspout?.(selected);
      }
      else { pauses?.dismiss(); review.review(selected); }
    } finally { framing = false; }
  }
  function draw() {
    if (adjustment) adjustmentHome.append(adjustment);
    sendHome();
    card.replaceChildren(); card.hidden = isHidden();
    card.setAttribute('data-check-kind', selected?.kind || 'empty');
    pauseControls(); reviewing();
    if (card.hidden) { dock?.properties.clear(card); return; }
    dock?.properties.render(card, { crumbs: ['Check it', selected?.stepInfo?.label || (selected?.kind === 'proposal' ? 'Proposal' : selected?.kind === 'flag' ? 'Flagged piece' : 'Review')], back: dismiss });
    const title = document.createElement('h3'); title.textContent = selected?.stepInfo?.label || 'Check this piece';
    const close = button('Close', dismiss, true); close.setAttribute('aria-label', 'Close check');
    if (!selected) {
      const text = document.createElement('p'); text.textContent = 'Nothing needs checking.';
      card.append(title, close, text); return;
    }
    const item = selected;
    if (item.kind === 'pause' && adjustment) {
      // The pause card says what was read and holds its adjustments (drag, pins, turn): it sits under
      // the title, before the answers, and its own title and reason are not repeated above it.
      card.append(title, close, adjustment); adjustment.hidden = false;
    } else if (item.kind === 'gutter') {
      // Keep Close in normal flow, above the issue rows, so long reasons have
      // the full card width and each reason appears only in its row.
      const header = document.createElement('header'); header.append(title, close); card.append(header);
    } else {
      const text = document.createElement('p');
      text.textContent = item.kind === 'pause' ? item.why || 'Check this part of your house.'
        : item.kind === 'flag' ? item.flag.text : 'A new reading suggests a change. Your version stays until you choose Use this.';
      card.append(title, close, text);
    }
    if (item.kind === 'gutter') {
      // Use the Check card's existing button builder, with one plain reason per
      // run/downspout issue. Geometry-derived issues disappear when corrected.
      for (const entry of rows.filter(r => r.kind === 'gutter')) {
        const row = button(`${entry.label}: ${entry.reason}`, () => { selected = entry; focus(); draw(); });
        row.dataset.gutterCheck = entry.id; row.setAttribute('aria-pressed', String(key(entry) === key(item))); card.append(row);
      }
      card.append(button('Looks fine', () => save(() => op(gutterAcknowledgement(getPlan(), item)))),
        button('Fix it', () => { focus(); dismiss(); }));
    } else if (item.kind === 'proposal') {
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
      card.hidden = isHidden();
      if (card.hidden) dock?.properties.clear(card);
      pauseControls(); reviewing();
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
    dismissed = false; sync(); const index = rows.findIndex(r => key(r) === key(selected));
    selected = rows[(index + 1) % rows.length] || null; dismissed = false; focus(); draw();
    return selected;
  }
  function show(item) {
    dismissed = false; sync();
    if (item) selected = rows.find(r => r.kind === item.kind && r.building === item.building && r.id === item.id) || selected;
    dismissed = false; emptyOpen = true; focus(); draw();
  }
  function dismiss(notify = true) {
    if (framing) return;
    dismissed = true; pauses?.dismiss(); review.dismiss(); draw();
    if (notify !== false) onClose?.();
  }
  // Each frame only notices a new model or build (the editor replaces them, never edits them in
  // place) or a change in whether the card may show; the queue is rebuilt only then.
  function tick() {
    const model = getModel(), build = getBuild(), plan = getPlan();
    if (model !== seenModel || build !== seenBuild || plan !== seenPlan) { seenModel = model; seenBuild = build; seenPlan = plan; sync(); }
    else if (card.hidden !== isHidden()) draw();
    frame = requestAnimationFrame(tick);
  }
  signal.addEventListener('abort', () => {
    cancelAnimationFrame(frame);
    if (adjustment) adjustmentHome.append(adjustment);
    sendHome();
    card.hidden = true; reviewing();
    card.remove();
  }, { once: true });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !card.hidden) dismiss();
  }, { signal });
  sceneHost?.addEventListener('twinrebuilt', sync, { signal });
  sync(); frame = requestAnimationFrame(tick);
  return { queue: () => { sync(); return rows; }, current: () => { sync(); return selected; }, next, show, dismiss, sync };
}
