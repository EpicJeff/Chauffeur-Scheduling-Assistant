// Pure clock, colour and compass math shared by the view and its node checks.
const RAD = Math.PI / 180;
const clamp = x => Math.max(0, Math.min(1, x));
const smooth = x => { x = clamp(x); return x * x * (3 - 2 * x); };
const mix = (a, b, t) => Array.isArray(a) ? a.map((v, i) => mix(v, b[i], t)) : a + (b - a) * t;

export function resolveSite(site = {}, date = new Date()) {
  const located = site.source !== 'default' && Number.isFinite(site.lat) && Number.isFinite(site.lon);
  return { ...site, lat: located ? site.lat : 40,
    lon: located ? site.lon : -date.getTimezoneOffset() / 60 * 15,
    front_bearing_deg: Number.isFinite(site.front_bearing_deg) ? site.front_bearing_deg : 180,
    source: located ? site.source : 'default' };
}

export function previewDate(now, mode, site) {
  if (mode === 'now') return new Date(now);
  const hour = mode === 'day' ? 12 : 23;
  // Household IANA zone gives civil noon/23:00, including DST. When no zone is
  // configured use the site's longitude (mean solar clock), not the viewer's zone.
  try {
    if (site.timezone) {
      const format = new Intl.DateTimeFormat('en-CA', { timeZone: site.timezone,
        year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit',
        minute: '2-digit', second: '2-digit', hourCycle: 'h23' });
      const parts = date => Object.fromEntries(format.formatToParts(date).map(p => [p.type, p.value]));
      const p = parts(now), desired = Date.UTC(+p.year, +p.month - 1, +p.day, hour);
      let stamp = desired;
      for (let i = 0; i < 3; i++) {
        const q = parts(new Date(stamp));
        stamp += desired - Date.UTC(+q.year, +q.month - 1, +q.day, +q.hour, +q.minute, +q.second);
      }
      return new Date(stamp);
    }
  } catch { /* An old/invalid household zone still gets a useful preview. */ }
  const offset = site.lon / 15 * 3600000, local = new Date(+now + offset);
  return new Date(Date.UTC(local.getUTCFullYear(), local.getUTCMonth(), local.getUTCDate(), hour) - offset);
}

export function modelDirection(azimuth, altitude, frontBearing = 180) {
  // The street is plan -y / three +z; compass bearings turn clockwise.
  const angle = azimuth - frontBearing * RAD + Math.PI;
  const horizontal = Math.cos(altitude);
  return [horizontal * Math.sin(angle), Math.sin(altitude), -horizontal * Math.cos(angle)];
}

const bands = [
  [-12, { background: [.035, .055, .10], ambient: .09, environment: .015, exposure: 1.2, sunColor: [1, .46, .22] }],
  [-6, { background: [.18, .22, .34], ambient: .26, environment: .06, exposure: 1.15, sunColor: [1, .46, .22] }],
  [0, { background: [.60, .49, .52], ambient: .8, environment: .3, exposure: 1.07, sunColor: [1, .55, .28] }],
  [6, { background: [.725, .796, .843], ambient: 1.8, environment: .65, exposure: 1, sunColor: [1, .94, .83] }],
];
// Where the sun casts shadows the sky fill steps back and the sun carries the
// day, so shade reads about a stop under sunlit ground. Without sun shadows
// that balance would only flatten the picture, so those views keep the fill.
const shadowedBands = new Map([[0, { ambient: .5 }], [6, { ambient: .5, environment: .4 }]]);
export function lookAt(altitudeDeg, moon = { altitude: 0, fraction: 0 }, { shadows = false, overcast = 0, zenith = null, ground = null } = {}) {
  const band = ([edge, look]) => [edge, shadows ? { ...look, ...shadowedBands.get(edge) } : look];
  let lower = band(bands[0]), upper = band(bands.at(-1));
  for (let i = 1; i < bands.length; i++) if (altitudeDeg <= bands[i][0]) { lower = band(bands[i - 1]); upper = band(bands[i]); break; }
  const t = smooth((altitudeDeg - lower[0]) / (upper[0] - lower[0]));
  const look = Object.fromEntries(Object.keys(lower[1]).map(key => [key, mix(lower[1][key], upper[1][key], t)]));
  const c = clamp(overcast), colour = rgb => { const peak = Math.max(...rgb, 1e-6); return rgb.map(v => v / peak); };
  return { ...look, ambient: look.ambient * (1 + .35 * c), environment: look.environment * (1 + .35 * c),
    skyColor: zenith ? colour(zenith) : null, groundColor: ground ? colour(ground) : null,
    sun: (shadows ? 7 : 3) * smooth(altitudeDeg / 6) * (1 - .75 * c),
    moon: .16 * Math.max(0, Math.sin(moon.altitude)) * clamp(moon.fraction) * (1 - smooth((altitudeDeg + 6) / 6)),
    moonColor: [.60, .72, 1], lamps: altitudeDeg < -3 };
}
