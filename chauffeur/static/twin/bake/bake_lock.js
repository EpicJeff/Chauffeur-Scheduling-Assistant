// Ruling B17: one desk bakes a key at a time, through a server-side lease (60 s,
// renewed while a step works). It replaces the browser-only lock: two machines, or two
// tabs of one browser, take turns, so a read-modify-write of a two-channel page never
// loses the other light's channel.
const RENEW_MS = 20000, LOST_MS = 40000, WAIT_MS = 1000;
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));

export function bakeHTTPError(message, status) {
  return Object.assign(new Error(`${message} (HTTP ${status}).`), { status });
}

function ask(api, path, owner, action) {
  return api(`${path}/lease`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ owner, action }) });
}

// Whether this person may bake here at all (a parent): a child's view is refused (M4).
export async function mayBake(api, path, owner) {
  try {
    const r = await ask(api, path, owner, 'check');
    if (r.status === 401) throw bakeHTTPError('Could not check the bake lease', r.status);
    return r.ok;
  } catch (error) { if (error.status === 401) throw error; return false; }
}

export async function withBakeLease(api, path, owner, valid, work) {
  let renewedAt;
  for (;;) {
    if (!valid()) return null;
    const sentAt = Date.now();
    const r = await ask(api, path, owner, 'acquire');
    if (r.ok) { renewedAt = sentAt; break; }
    if (r.status !== 409) throw bakeHTTPError('Could not take the bake lease', r.status);
    if (!valid()) return null;
    await wait(WAIT_MS);
    if (!valid()) return null;
  }
  let failure = null, renewing = null, lastError = null;
  const check = () => {
    if (failure) throw failure;
    if (Date.now() - renewedAt >= LOST_MS) throw lastError || new Error('The bake lease expired.');
  };
  const heartbeat = setInterval(() => {
    if (renewing || failure) return;
    const sentAt = Date.now();
    renewing = ask(api, path, owner, 'acquire').then(async r => {
      if (!r.ok) throw bakeHTTPError('Could not renew the bake lease', r.status);
      const held = await r.json();
      if (held.held === false || held.owner && held.owner !== owner) throw bakeHTTPError('Lost the bake lease', 409);
      renewedAt = sentAt; lastError = null;
    }).catch(error => {
      lastError = error;
      if ([401, 409].includes(error.status)) failure = error;
    }).finally(() => { renewing = null; });
  }, RENEW_MS);
  // Await an in-flight renewal at each safe point as well as observing its error.
  const checkpoint = async () => { await renewing; check(); };
  try { await checkpoint(); return await work(checkpoint); } finally {
    clearInterval(heartbeat);
    await renewing;
    const released = await ask(api, path, owner, 'release').catch(() => null);
    if (released?.status === 401) failure = bakeHTTPError('Could not release the bake lease', 401);
    check();
  }
}
