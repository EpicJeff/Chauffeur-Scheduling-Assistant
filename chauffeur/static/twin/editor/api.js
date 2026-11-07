// The shared nav fetch wrapper owns the parent session and ingress headers.
export const idleInterval = 60000;
export const buildInterval = 1000;
const signedOut = 'Home Assistant signed this tab out. Open any Chauffeur admin page from the Home Assistant sidebar, then come back here.';
export const plain = value => String(value ?? '').replace(/mesh(?:es)?/gi, 'shape')
  .replace(/extrud\w*/gi, 'build').replace(/gizmo/gi, 'tool').replace(/vertex/gi, 'point');
let checkpointPrompt = null;

export function report(error) {
  if (!error.cancelled && !error.shown) window.showGlobalAlert(plain(error.message || 'Could not reach the house. Try again.'));
}

export async function checkpoint(detail) {
  if (checkpointPrompt) return checkpointPrompt;
  checkpointPrompt = (async () => {
    const total = Number(detail.total) || 0;
    if (Number(detail.checkpoint) >= 50 || total >= 50) {
      window.showGlobalAlert(`Spent $${total.toFixed(2)}. The $50 limit has been reached. No more paid requests can run.`);
      return false;
    }
    const go = await window.promptConfirm(`Spent $${total.toFixed(2)} so far`,
      'Continue to the next checkpoint?', 'Continue', 'Stop');
    if (!go) return false;
    await request('cost/ack', 'POST', { checkpoint: detail.checkpoint }, 'twin');
    return true;
  })();
  try { return await checkpointPrompt; }
  finally { checkpointPrompt = null; }
}

export async function request(path, method = 'GET', body, area = 'editor') {
  for (;;) {
    const response = await fetch((window.chfBase ?? '../') + `api/house/${area}/` + path, {
      method, ...(body === undefined ? {} : body instanceof FormData ? { body } : {
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      }),
    });
    let data;
    try { data = JSON.parse(await response.text()); }
    catch {
      const error = new Error(response.status === 401 ? signedOut : 'The house could not answer. Try again.');
      error.status = response.status;
      if (response.status === 401) { window.showGlobalAlert(signedOut); error.shown = true; }
      throw error;
    }
    if (response.ok) return data;
    if (response.status === 409 && data?.detail?.checkpoint) {
      if (await checkpoint(data.detail)) continue;
      throw Object.assign(new Error('Stopped at the spending checkpoint.'), { cancelled: true });
    }
    throw Object.assign(new Error(typeof data?.detail === 'string' ? plain(data.detail) : 'The house request could not finish.'), {
      status: response.status, detail: data?.detail,
    });
  }
}

export const active = build => ['running', 'paused', 'checkpoint'].includes(build?.state);

export function createPolling({ onState, onBuild, onError }) {
  let build = null, seq = 0, timer = null, pending = null, stopped = false;
  const schedule = () => {
    clearTimeout(timer);
    if (!stopped) timer = setTimeout(() => pollNow().catch(onError), active(build) ? buildInterval : idleInterval);
  };
  async function readBuild(id) {
    if (id !== build?.id) { build = null; seq = 0; }
    let next;
    try { next = await request(`build/${encodeURIComponent(id)}?since=${seq}`); }
    catch (error) {
      if (error.status === 404 || (error.status === 409 && error.detail === 'The house was started over.')) {
        build = null; seq = 0;
        await readState();
        return;
      }
      throw error;
    }
    build = next;
    await onBuild(next);
    // Advance only after the scene and log consumed this batch successfully.
    seq = next.seq;
  }
  async function readState() {
    const state = await request('state');
    if (!state.build) { build = null; seq = 0; }
    await onState(state);
    return state;
  }
  function pollNow(forceState = false) {
    if (pending) return pending;
    clearTimeout(timer);
    pending = (async () => {
      if (active(build) && !forceState) {
        await readBuild(build.id);
      } else {
        const state = await readState();
        if (state.build) await readBuild(state.build);
      }
    })().finally(() => { pending = null; schedule(); });
    return pending;
  }
  return {
    start: () => pollNow(true), pollNow,
    async follow(id) { await pending; await readBuild(id); schedule(); },
    refreshState: readState,
    stop() { stopped = true; clearTimeout(timer); },
  };
}
