// Session-only preview. The expensive clock path runs only on release (change).
export function mountTimeScrub(view, slider, {host = document.getElementById('twin-canvas'),
  output = document.getElementById('twin-time-scrub-value')} = {}) {
  if (!slider) return {stop() {}};
  const input = () => view.scrubTime(Number(slider.value));
  const change = () => view.scrubTime(Number(slider.value), {commit:true});
  const sync = () => {
    const hour = Math.round((view.timeHour ?? view.state.previewHour ?? 12)*12)/12;
    slider.value = String(hour);
    const minutes = Math.round(hour*60), text = `${String(Math.floor(minutes/60)).padStart(2,'0')}:${String(minutes%60).padStart(2,'0')}`;
    slider.setAttribute('aria-valuetext', text);
    if (output) output.textContent = text;
  };
  slider.addEventListener('input', input);
  slider.addEventListener('change', change);
  host?.addEventListener('twintimechange', sync);
  sync();
  return {stop() {
    slider.removeEventListener('input', input);
    slider.removeEventListener('change', change);
    host?.removeEventListener('twintimechange', sync);
  }};
}
