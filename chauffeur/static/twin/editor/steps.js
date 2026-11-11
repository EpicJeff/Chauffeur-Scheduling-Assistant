const names = ['Your files', 'Your lot', 'Build', 'Check it', 'Link to Home Assistant'];

export function createSteps(host, { state, onOpen = () => {} }) {
  let opened = null, shown = null;
  const buttons = names.map(name => {
    const button = document.createElement('button'); button.type = 'button';
    button.setAttribute('data-step', name);
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
      button.textContent = `${names[i]}${i === 3 && count ? ` (${count})` : ''} · ${status === 'not-yet' ? 'not yet' : status}`;
    });
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
  render();
  return { render, open, close };
}
