// Entity interpretation and clock-based easing, shared by every effect visual.
export const EFFECT_TYPES = Object.freeze({
  waterfall: { label: 'Waterfall', shapes: ['line'], size_min: .3, size_max: 1.5 },
  fountain: { label: 'Fountain jet', shapes: ['point'], size_min: 1, size_max: 6 },
  bubbler: { label: 'Bubbler', shapes: ['point'], size_min: .3, size_max: 1.5 },
  fire: { label: 'Fire', shapes: ['point', 'line'], size_min: .5, size_max: 2 },
  spa_jet: { label: 'Spa jet', shapes: ['point'], size_min: .5, size_max: 2.5 },
  steam: { label: 'Steam', shapes: ['point'], size_min: 1, size_max: 4 },
  sheer: { label: 'Sheer descent', shapes: ['line'], size_min: .5, size_max: 3 },
  deck_jet: { label: 'Deck jet', shapes: ['point'], size_min: 2, size_max: 8 },
  mist: { label: 'Mist', shapes: ['point', 'line'], size_min: 1, size_max: 6 },
});

const clamp = value => Math.max(0, Math.min(1, value));
const finite = value => typeof value === 'number' && Number.isFinite(value);
const numeric = value => {
  if (typeof value !== 'string' && typeof value !== 'number') return null;
  if (typeof value === 'string' && !value.trim()) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
};
const available = (row, stale) => !!row && !stale && !row.stale && row.reachable !== false && !['unavailable', 'unknown'].includes(row.state);
function switchedOn(entity, row, stale) {
  if (!available(row, stale) || ['unavailable', 'unknown', null, undefined].includes(row.state)) return false;
  const domain = entity.split('.')[0], attrs = row.attributes || {};
  const current = numeric(attrs.current_temperature), target = numeric(attrs.temperature);
  if (domain === 'climate') {
    if (attrs.hvac_action != null) return ['heating', 'preheating'].includes(attrs.hvac_action);
    const setpoint = target ?? numeric(attrs.target_temp_low);
    return ['heat', 'heat_cool', 'auto'].includes(row.state) && current !== null && setpoint !== null && current < setpoint;
  }
  if (domain === 'water_heater') return row.state !== 'off' && (current === null || target === null || current < target);
  return row.state === 'on';
}
const sizeAt = (fixture, t) => {
  const defaults = EFFECT_TYPES[fixture.type] || EFFECT_TYPES.fountain;
  const min = finite(fixture.size_min) ? fixture.size_min : defaults.size_min;
  const max = finite(fixture.size_max) ? fixture.size_max : defaults.size_max;
  return min + t * (max - min);
};

export function effectTarget(fixture, states = {}, stale = false) {
  const strength = finite(fixture.strength) ? clamp(fixture.strength) : 1;
  const row = states?.[fixture.sensor];
  const value = available(row, stale) ? numeric(fixture.sensor_attribute ? row.attributes?.[fixture.sensor_attribute] : row.state) : null;
  const range = fixture.sensor_max - fixture.sensor_min;
  const hasValue = !!fixture.sensor && value !== null && finite(fixture.sensor_min)
    && finite(fixture.sensor_max) && range !== 0;
  const t = hasValue ? clamp((value - fixture.sensor_min) / range) : strength;
  const switchRow = states?.[fixture.entity];
  const active = fixture.entity ? switchedOn(fixture.entity, switchRow, stale)
    : fixture.sensor ? hasValue && t > 0 : true;
  return { active: !!active, t, size: sizeAt(fixture, t) };
}

export function createEffectDriver(fixture, { low = false } = {}) {
  let target = null, fromT = 0, fromOpacity = 0, start = 0, lastClock = 0;
  const pose = now => {
    const progress = clamp(now - start), ease = progress * progress * (3 - 2 * progress);
    const t = fromT + (target.t - fromT) * ease;
    const opacity = fromOpacity + (Number(target.active) - fromOpacity) * ease;
    return { active: target.active, t, size: sizeAt(fixture, t), opacity };
  };
  return {
    update(states, stale, nowSeconds) {
      // A backwards clock must not reverse a running transition.
      const now = finite(nowSeconds) ? Math.max(lastClock, nowSeconds) : lastClock;
      lastClock = now;
      const next = effectTarget(fixture, states, stale);
      if (!target || low) {
        target = next; fromT = next.t; fromOpacity = Number(next.active); start = now;
      } else if (next.t !== target.t || next.active !== target.active) {
        const current = pose(now);
        fromT = current.t; fromOpacity = current.opacity; start = now; target = next;
      }
      return pose(now);
    },
  };
}
