// Workers cannot see the page's import map. Both module URLs are explicitly
// versioned by the page, as in lod_worker.js.
export async function handleConduitMessage({id, coreUrl, groundUrl, input}, send) {
  try {
    const [{routeConduits}, {groundAt}] = await Promise.all([import(coreUrl), import(groundUrl)]);
    const messages = [], routes = routeConduits(input, {groundAt, debug: text => messages.push(text)});
    send({id, routes, messages});
  } catch (error) { send({id, error: error.message || String(error)}); }
}
if (typeof WorkerGlobalScope !== 'undefined' && globalThis instanceof WorkerGlobalScope) {
  globalThis.onmessage = event => handleConduitMessage(event.data, message => globalThis.postMessage(message));
}
