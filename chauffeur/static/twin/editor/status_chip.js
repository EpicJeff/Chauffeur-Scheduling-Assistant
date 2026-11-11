export function createStatusChip(host) {
  const state = document.createElement('span'), spend = document.createElement('span'), estimate = document.createElement('span');
  // Ruling B15: the editor never bakes lights; the 3D house on a High desk does.
  const relight = document.createElement('span');
  const stop = document.getElementById('editor-stop');
  state.setAttribute('role', 'status');
  host.replaceChildren(state, spend, estimate, relight);
  if (stop) host.append(stop);
  function update(value) {
    state.textContent = value.state === 'running' ? 'Working'
      : ['paused', 'checkpoint', 'stopped'].includes(value.state) ? 'Waiting on you' : '';
    state.hidden = !state.textContent;
    spend.textContent = `$${Number(value.cost || 0).toFixed(2)} so far`;
    estimate.hidden = value.estimate == null;
    estimate.textContent = value.estimate == null ? '' : `about $${Number(value.estimate).toFixed(2)}`;
    relight.hidden = value.bake?.waiting !== true;
    relight.textContent = relight.hidden ? '' : 'Lights wait to re-bake';
    relight.title = relight.hidden ? '' : 'The 3D house re-bakes them on a High screen.';
    // Stop ends any build still in flight: running, or waiting at a pause or checkpoint.
    if (stop) stop.hidden = !['running', 'paused', 'checkpoint'].includes(value.state);
  }
  update({ state: null, cost: 0, estimate: null });
  return { update };
}
