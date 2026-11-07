// The editor owns requests, spending checkpoints, scene refreshes and the log.
const runId = () => globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;

export async function runDirector(view, {
  run = runId(), cameras = ['front', 'porch', 'rear', 'top'], base = null,
  critique, log = () => {}, onRound, signal,
} = {}) {
  let roundBase = base, spent = 0;
  for (let n = 0; n < 5; n++) {
    if (signal?.aborted) return;
    const captures = await view.capture(cameras, 1280, 800);
    // capture returns PNG data URLs; the server accepts raw base64 PNGs.
    const renders = captures.map(png => png.replace(/^data:image\/png;base64,/, ''));
    if (signal?.aborted) return;
    const response = await critique({ run, renders, cameras, base: roundBase });
    if (signal?.aborted) return;
    const result = response.result || response;
    spent += result.cost || 0;
    const text = result.critique || 'House reviewed.';
    log(`${/^Round \d+:/i.test(text) ? text : `Round ${n + 1}: ${text}`}\nRun cost: $${spent.toFixed(2)}`);
    if (result.notes?.length) log(result.notes.join('\n'));
    if (result.stale) log('This critique is stale: a newer edit or return won. The current house is shown; the director has stopped.');
    roundBase = result.round;
    if (onRound) await onRound(result);
    else await view.rebuild(result.plan);
    if (result.done || result.stale) return;
  }
  log('Round cap reached (5 rounds).');
}
