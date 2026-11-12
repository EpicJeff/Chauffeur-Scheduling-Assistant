const KEY = 'chf.editor.lighting';
const choices = ['day', 'night', 'now', 'unlit'];

// Device-only viewport preference; it never changes the household's settings.
export function mountLighting(view, host, { storage, signal } = {}) {
  let choice = 'day';
  try {
    storage ??= globalThis.localStorage;
    const saved = storage?.getItem(KEY); if (choices.includes(saved)) choice = saved;
  } catch { /* Private storage. */ }
  function select(value) {
    if (!choices.includes(value)) return;
    choice = value;
    view.setUnlit(value === 'unlit');
    view.setTime(value === 'unlit' ? 'day' : value);
    try { storage?.setItem(KEY, choice); } catch { /* Still usable without storage. */ }
    host.querySelectorAll('[data-editor-lighting]').forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.editorLighting === choice));
    });
  }
  host.addEventListener('click', event => {
    const button = event.target.closest('[data-editor-lighting]');
    if (button) select(button.dataset.editorLighting);
  }, { signal });
  select(choice);
  return { select, choice: () => choice };
}
