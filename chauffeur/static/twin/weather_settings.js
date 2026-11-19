import { base } from './twin_library.js';

const roles = {rain: 'weather_rain_sensor', wind_speed: 'weather_wind_speed_sensor',
  wind_direction: 'weather_wind_direction_sensor', temperature: 'weather_temperature_sensor'};

// Uses the same captioned selects, shared drawer and save status as energy.
export function mountWeatherSettings(view, {api = (path, init) => fetch(base() + path, init)} = {}) {
  const section = document.getElementById('twin-weather-settings');
  const report = document.getElementById('twin-weather-report');
  const save = document.getElementById('twin-weather-save');
  const fields = Object.fromEntries(['weather_entity', ...Object.values(roles)].map(key => [key, document.getElementById(key)]));
  const events = new AbortController();
  let stopped = false, ready = false, busy = false, revision = 0;
  const listen = (node, type, fn) => node?.addEventListener(type, fn, {signal: events.signal});
  function controls() {
    for (const field of Object.values(fields)) if (field) field.disabled = !ready || busy;
    if (save) save.disabled = !ready || busy;
  }
  function showReport(body) {
    if (!report) return;
    report.replaceChildren();
    const source = body.source;
    const line = text => { const p = document.createElement('p'); p.textContent = text; report.append(p); };
    line(source.entity ? `Weather: ${source.entity}${source.stale ? ' (unavailable or stale; clear and dry)' : ''}.`
      : 'No weather entity: clear, dry and calm.');
    for (const [role, sensor] of Object.entries(source.sensors || {})) if (sensor.entity) {
      line(`${role.replaceAll('_', ' ')}: ${sensor.entity} — ${sensor.value === null ? 'unavailable; using weather fallback' : `${sensor.state}${sensor.unit ? ' ' + sensor.unit : ''}`}.`);
    }
    for (const quantity of source.missing || []) line(`Missing ${quantity.replaceAll('_', ' ')}: ${source.fallbacks?.[quantity] || 'weather fallback'}.`);
    if (!source.missing?.length) line('All weather quantities are available.');
    line(`Ground: ${body.snow_cm.toFixed(1)} cm snow, ${Math.round(body.wetness * 100)}% wet. Plausible, not exact.`);
  }
  function apply(body, choices) {
    const source = body.source;
    for (const [key, field] of Object.entries(fields)) {
      if (!field) continue;
      const role = Object.keys(roles).find(role => roles[role] === key);
      const value = key === 'weather_entity' ? source.configured_entity || '' : source.sensors?.[role]?.entity || '';
      const rows = choices.filter(row => key === 'weather_entity' ? row.entity_id.startsWith('weather.')
        : row.entity_id.startsWith('sensor.') || key === roles.rain && row.entity_id.startsWith('binary_sensor.'));
      if (value && !rows.some(row => row.entity_id === value)) rows.push({entity_id: value, name: 'Saved source (not currently available)'});
      field.replaceChildren();
      for (const [id, text] of [['', key === 'weather_entity' ? 'Automatic: first weather entity' : 'Use weather entity'],
        ...rows.map(row => [row.entity_id, `${row.name || row.entity_id} (${row.entity_id})`])]) {
        const option = document.createElement('option'); option.value = id; option.textContent = text; field.append(option);
      }
      field.value = value;
    }
    showReport(body);
  }
  async function reload() {
    if (!section || stopped || busy) return;
    const request = ++revision; ready = false; controls();
    try {
      const responses = await Promise.all(['api/house/twin/weather-state', ...['weather', 'sensor', 'binary_sensor'].map(domain => 'api/ha/entities?domain=' + domain)].map(path => api(path)));
      if (responses.some(response => !response.ok)) throw new Error('Could not load weather sources.');
      const [body, ...lists] = await Promise.all(responses.map(response => response.json()));
      if (stopped || request !== revision) return;
      apply(body, lists.flat()); ready = true;
    } catch (error) { if (!stopped && request === revision) window.chfSettingsSaved?.(false, error.message); }
    finally { if (!stopped && request === revision) controls(); }
  }
  listen(save, 'click', async () => {
    if (!ready || busy || stopped) return;
    busy = true; controls(); window.chfSettingsSaving?.();
    try {
      const response = await api('api/house/twin/weather-sources', {method: 'PUT', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(Object.fromEntries(Object.entries(fields).map(([key, field]) => [key, field.value])))});
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || 'Could not save weather sources.');
      if (stopped) return;
      showReport(body); view.setWeatherEntity?.(body.source.configured_entity || '');
      view.refreshWeather?.();
      window.chfSettingsSaved?.(true);
    } catch (error) { if (!stopped) window.chfSettingsSaved?.(false, error.message); }
    finally { busy = false; if (!stopped) controls(); }
  });
  listen(window, 'chf-settings-opened', event => { if (event.detail?.tab === 'twin') reload(); });
  controls();
  return {reload, stop() {stopped = true; ++revision; events.abort();}};
}
