export function createStatusChip(host) {
  const state = document.createElement('span'), spend = document.createElement('span'), estimate = document.createElement('span');
  const stop = document.getElementById('editor-stop');
  state.setAttribute('role', 'status');
  host.replaceChildren(state, spend, estimate);
  if (stop) host.append(stop);
  function update(value) {
    state.textContent = value.state === 'running' ? 'Working'
      : ['paused', 'checkpoint', 'stopped'].includes(value.state) ? 'Waiting on you' : '';
    state.hidden = !state.textContent;
    spend.textContent = `$${Number(value.cost || 0).toFixed(2)} so far`;
    estimate.hidden = value.estimate == null;
    estimate.textContent = value.estimate == null ? '' : `about $${Number(value.estimate).toFixed(2)}`;
    if (stop) stop.hidden = value.state !== 'running';
  }
  update({ state: null, cost: 0, estimate: null });
  return { update };
}
