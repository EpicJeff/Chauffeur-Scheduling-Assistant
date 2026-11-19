const names = ['Your files', 'Your lot', 'Build', 'Check it', 'Link to Home Assistant'];

export function createSteps(host, { state, onOpen = () => {}, tabs = false }) {
  let opened = null, shown = null;
  if (tabs) host.setAttribute('role', 'tablist');
  const buttons = names.map(name => {
    const button = document.createElement('button'); button.type = 'button';
    button.setAttribute('data-step', name);
    if (tabs) { button.id = `place-step-${names.indexOf(name)}`; button.setAttribute('role', 'tab'); button.setAttribute('aria-controls', 'place-step-content'); }
    button.addEventListener('click', () => open(name));
    return button;
  });
  host.replaceChildren(...buttons);
  function render(next = state) {
    state = next;
    const { model, sheets = {}, build } = state;
    const buildings = model?.buildings || [], sources = sheets.sources || [];
    const drawings = sources.filter(s => s.kind === 'drawing');
    const filed = drawings.length ? drawings.every(s => Array.from({ length: s.pages }, (_, i) => i + 1)
      .every(page => sheets.page_roles?.some(r => r.source === s.id && r.page === page && r.role)))
      : sources.length > 0 || buildings.length > 0 || !!sheets.place?.buildings?.some(b => b.footprint);
    // A build stopped half way (Stop, a spending checkpoint, a failure) may have published a partial
    // round, so pieces exist; it still waits for Continue, so Build is now and not done.
    const unfinished = ['running', 'stopped', 'checkpoint', 'failed'].includes(build?.state);
    const built = buildings.some(b => b.walls?.length || b.rooms?.length || b.roofs?.length);
    const count = buildings.reduce((n, b) => n + (b.flags?.length || 0) + (b.proposals?.length || 0), 0);
    const rooms = buildings.flatMap(b => b.rooms || []);
    const done = [filed, !!sheets.place?.lot?.placement, built && !unfinished, built && !unfinished && !count,
      !unfinished && rooms.length > 0 && rooms.every(r => r.ha_area)];
    const now = unfinished ? 2 : build?.state === 'paused' ? 3
      : built ? count ? 3 : done[4] ? -1 : 4 : done.findIndex(value => !value);
    buttons.forEach((button, i) => {
      const status = i === now ? 'now' : done[i] ? 'done' : 'not-yet';
      button.setAttribute('data-state', status);
      button.setAttribute('aria-expanded', String(opened === names[i]));
      if (tabs) { button.setAttribute('aria-selected', String(opened === names[i])); button.tabIndex = opened === names[i] ? 0 : -1; }
      button.textContent = `${names[i]}${i === 3 && count ? ` (${count})` : ''} · ${status === 'not-yet' ? 'not yet' : status}`;
    });
    if (tabs && opened) document.getElementById('place-step-content')?.setAttribute('aria-labelledby', buttons[names.indexOf(opened)].id);
    // On a narrow screen the strip scrolls: keep the open step, else the one that is now, in view.
    const lead = buttons[opened ? names.indexOf(opened) : now];
    if (lead && lead !== shown && lead.getBoundingClientRect && host.getBoundingClientRect) {
      shown = lead;
      const at = lead.getBoundingClientRect(), box = host.getBoundingClientRect();
      if (at.left < box.left || at.right > box.right) host.scrollLeft += at.left - box.left - 8;
    }
  }
  function open(name) {
    if (!names.includes(name)) return;
    opened = name; render(); onOpen(name);
  }
  function close() { opened = null; render(); }
  if (tabs) host.addEventListener('keydown', event => {
    if (!['ArrowRight', 'ArrowLeft', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const at = buttons.indexOf(document.activeElement), index = event.key === 'Home' ? 0 : event.key === 'End' ? names.length - 1
      : (at + (event.key === 'ArrowRight' ? 1 : -1) + names.length) % names.length;
    buttons[index].focus(); open(names[index]);
  });
  render();
  return { render, open, close, activate(name) { opened = name; render(); } };
}
