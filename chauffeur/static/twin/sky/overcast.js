const conditions = {sunny:0, 'clear-night':0, partlycloudy:.4, cloudy:.85, fog:.9,
  rainy:1, pouring:1, snowy:1, 'snowy-rainy':1, lightning:1, 'lightning-rainy':1,
  hail:1, exceptional:1, windy:.3, 'windy-variant':.3};

export function overcastFactor(state) {
  if (!state || state.stale || ['unknown','unavailable',''].includes(state.state)) return 0;
  const coverage = state.attributes?.cloud_coverage;
  return typeof coverage === 'number' && Number.isFinite(coverage)
    ? Math.max(0, Math.min(1, coverage / 100)) : conditions[state.state] ?? 0;
}

export function weatherState(states, entity = null, stale = false) {
  if (!states || stale) return null;
  const name = id => String(states[id]?.attributes?.friendly_name || id).toLowerCase();
  const id = entity || Object.keys(states).filter(id => id.startsWith('weather.'))
    .sort((a,b) => name(a).localeCompare(name(b)) || a.localeCompare(b))[0];
  return states[id] || null;
}
