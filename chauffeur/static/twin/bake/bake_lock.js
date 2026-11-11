// Ruling B17: one desk bakes a key at a time, through a server-side lease (60 s,
// renewed while a step works). It replaces the browser-only lock: two machines, or two
// tabs of one browser, take turns, so a read-modify-write of a two-channel page never
// loses the other light's channel.
const RENEW_MS = 20000, WAIT_MS = 1000;
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));

function ask(api, path, owner, action) {
  return api(`${path}/lease`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ owner, action }) });
}

// Whether this person may bake here at all (a parent): a child's view is refused (M4).
export async function mayBake(api, path, owner) {
  try { return (await ask(api, path, owner, 'check')).ok; } catch { return false; }
}

export async function withBakeLease(api, path, owner, valid, work) {
  for (;;) {
    const r = await ask(api, path, owner, 'acquire');
    if (r.ok) break;
    if (r.status !== 409) throw new Error(`Could not take the bake lease (HTTP ${r.status}).`);
    if (!valid()) return null;
    await wait(WAIT_MS);
    if (!valid()) return null;
  }
  const heartbeat = setInterval(() => { ask(api, path, owner, 'acquire').catch(() => {}); }, RENEW_MS);
  try { return await work(); } finally {
    clearInterval(heartbeat);
    await ask(api, path, owner, 'release').catch(() => {});
  }
}
