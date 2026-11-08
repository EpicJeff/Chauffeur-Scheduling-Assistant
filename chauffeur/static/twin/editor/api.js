// The shared nav fetch wrapper owns the parent session and ingress headers.
export const idleInterval = 60000;
export const buildInterval = 1000;
const signedOut = 'Home Assistant signed this tab out. Open any Chauffeur admin page from the Home Assistant sidebar, then come back here.';
export const plain = value => String(value ?? '');
export const session = { signedOut: false, notices: 0, noticeShown: false };
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
      if (response.status === 401) {
        if (!session.signedOut) {
          session.signedOut = true;
          window.dispatchEvent(new CustomEvent('editor-signed-out'));
          if (!session.noticeShown) {
            session.noticeShown = true; ++session.notices;
            window.showGlobalAlert(signedOut);
          }
        }
        error.shown = true; error.signedOut = true;
      }
      throw error;
    }
    if (response.ok) {
      if (area === 'editor' && path === 'state') session.noticeShown = false;
      return data;
    }
    // Only these routes check spend before doing any work. A conversation
    // can reach a checkpoint AFTER applying edits, so it must never replay.
    if (response.status === 409 && data?.detail?.checkpoint
        && ((area === 'editor' && ['build', 'sheets/suggest', 'place/plot/read', 'place/photos/suggest'].includes(path))
          || (area === 'twin' && path === 'critique'))) {
      if (await checkpoint(data.detail)) continue;
      throw Object.assign(new Error('Stopped at the spending checkpoint.'), { cancelled: true });
    }
    throw Object.assign(new Error(typeof data?.detail === 'string' ? plain(data.detail) : 'The house request could not finish.'), {
      status: response.status, detail: data?.detail,
    });
  }
}

export const active = build => ['running', 'paused', 'checkpoint'].includes(build?.state);

export function createPolling({ onState, onBuild, onTick, onError }) {
  let build = null, seq = 0, timer = null, pending = null, stopped = false, nextBuild = null;
  const interval = () => nextBuild || build?.state === 'running' ? buildInterval : idleInterval;
  const enabled = () => !stopped && !session.signedOut && !document.hidden;
  const schedule = () => {
    clearTimeout(timer);
    timer = null;
    if (enabled()) timer = setTimeout(() => pollNow().catch(onError), interval());
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
    // Queue the handoff for the next poll, after this batch and onTick finish.
    // Calling follow here (or in onBuild) would wait on our own pending poll.
    nextBuild = next.state === 'done' && next.next && next.next !== next.id ? next.next : null;
  }
  async function readState() {
    const state = await request('state');
    if (!state.build) { build = null; seq = 0; }
    await onState(state);
    return state;
  }
  function run(work) {
    if (pending) return pending;
    if (!enabled()) return Promise.resolve();
    clearTimeout(timer);
    timer = null;
    pending = (async () => { await work(); await onTick?.(); })()
      .finally(() => { pending = null; schedule(); });
    return pending;
  }
  function pollNow(forceState = false) {
    return run(async () => {
      if (nextBuild) {
        const id = nextBuild; nextBuild = null;
        await readBuild(id);
      } else if (build?.state === 'running' && !forceState) {
        await readBuild(build.id);
      } else {
        const state = await readState();
        if (state.build) await readBuild(state.build);
      }
    });
  }
  return {
    start: () => pollNow(true), pollNow,
    async follow(id) {
      while (pending) await pending.catch(() => {});
      nextBuild = null;
      return run(() => readBuild(id));
    },
    refreshState: readState,
    stop() { stopped = true; clearTimeout(timer); },
    resume() { stopped = false; session.signedOut = false; return pollNow(true); },
    currentInterval: interval,
    polling: enabled,
  };
}
