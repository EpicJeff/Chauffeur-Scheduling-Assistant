// Low precision astronomical coordinates. No browser, clock or scene dependencies.
// Sun: the standard J2000 orbital approximation used by SunCalc; Moon: truncated
// lunar longitude/latitude series (Meeus). Angles returned are radians; longitude
// is east-positive degrees; azimuth is compass north=0, east=PI/2, clockwise.
const RAD = Math.PI / 180;
const TAU = Math.PI * 2;
const DAY = 86400000;
const J2000 = 2451545;
const OBLIQUITY = 23.4397 * RAD;
const wrap = value => ((value % TAU) + TAU) % TAU;
const clamp = value => Math.max(-1, Math.min(1, value));
const days = date => new Date(date).getTime() / DAY + 2440587.5 - J2000;

function equatorial(longitude, latitude = 0) {
  return {
    ra: Math.atan2(Math.sin(longitude) * Math.cos(OBLIQUITY) - Math.tan(latitude) * Math.sin(OBLIQUITY), Math.cos(longitude)),
    dec: Math.asin(clamp(Math.sin(latitude) * Math.cos(OBLIQUITY) + Math.cos(latitude) * Math.sin(OBLIQUITY) * Math.sin(longitude))),
  };
}

function solar(d) {
  const meanAnomaly = RAD * (357.5291 + 0.98560028 * d);
  const center = RAD * (1.9148 * Math.sin(meanAnomaly) + 0.0200 * Math.sin(2 * meanAnomaly) + 0.0003 * Math.sin(3 * meanAnomaly));
  return equatorial(meanAnomaly + center + RAD * (102.9372 + 180));
}

function lunar(d) {
  const m = RAD * (134.963 + 13.064993 * d);
  const f = RAD * (93.272 + 13.229350 * d);
  const elongation = RAD * (297.850 + 12.190749 * d);
  const solarAnomaly = RAD * (357.529 + 0.98560028 * d);
  const longitude = RAD * (218.316 + 13.176396 * d +
    6.289 * Math.sin(m) + 1.274 * Math.sin(2 * elongation - m) +
    0.658 * Math.sin(2 * elongation) + 0.214 * Math.sin(2 * m) -
    0.186 * Math.sin(solarAnomaly) - 0.114 * Math.sin(2 * f));
  const latitude = RAD * (5.128 * Math.sin(f) + 0.280 * Math.sin(m + f) +
    0.277 * Math.sin(m - f) + 0.173 * Math.sin(2 * elongation - f) +
    0.055 * Math.sin(2 * elongation + f - m) + 0.046 * Math.sin(2 * elongation - f - m));
  const distance = 385000.56 - 20905 * Math.cos(m) - 3699 * Math.cos(2 * elongation - m) -
    2956 * Math.cos(2 * elongation) - 570 * Math.cos(2 * m);
  return { ...equatorial(longitude, latitude), distance };
}

function horizontal(d, lat, lon, coordinates) {
  const phi = lat * RAD;
  const hourAngle = RAD * (280.16 + 360.9856235 * d + lon) - coordinates.ra;
  return {
    azimuth: wrap(Math.atan2(Math.sin(hourAngle), Math.cos(hourAngle) * Math.sin(phi) - Math.tan(coordinates.dec) * Math.cos(phi)) + Math.PI),
    altitude: Math.asin(clamp(Math.sin(phi) * Math.sin(coordinates.dec) + Math.cos(phi) * Math.cos(coordinates.dec) * Math.cos(hourAngle))),
  };
}

// Geometric solar centre altitude; refraction is included only in sunrise/set's
// conventional -0.833 degree threshold, keeping altitude smooth at the horizon.
export function sunPosition(date, lat, lon) {
  const d = days(date);
  return horizontal(d, lat, lon, solar(d));
}

// Topocentric lunar centre altitude, without atmospheric refraction; distance
// is the geocentric distance in kilometres. Parallax matters by almost a degree
// at the horizon and is retained even though this is a low precision ephemeris.
export function moonPosition(date, lat, lon) {
  const d = days(date);
  const moon = lunar(d);
  const position = horizontal(d, lat, lon, moon);
  const altitude = Math.atan2(Math.sin(position.altitude) - 6378.14 / moon.distance, Math.cos(position.altitude));
  return { ...position, altitude, distance: moon.distance };
}

// fraction 0..1; phase increases new=0, first quarter=.25, full=.5, last=.75.
export function moonIllumination(date) {
  const d = days(date);
  const sun = solar(d);
  const moon = lunar(d);
  const separation = Math.acos(clamp(Math.sin(sun.dec) * Math.sin(moon.dec) + Math.cos(sun.dec) * Math.cos(moon.dec) * Math.cos(sun.ra - moon.ra)));
  const incidence = Math.atan2(149598000 * Math.sin(separation), moon.distance - 149598000 * Math.cos(separation));
  const angle = Math.atan2(Math.cos(sun.dec) * Math.sin(sun.ra - moon.ra), Math.sin(sun.dec) * Math.cos(moon.dec) - Math.cos(sun.dec) * Math.sin(moon.dec) * Math.cos(sun.ra - moon.ra));
  return { fraction: (1 + Math.cos(incidence)) / 2, phase: 0.5 + 0.5 * incidence * (angle < 0 ? -1 : 1) / Math.PI };
}

// Events for the input's UTC calendar date at the site (its mean solar day,
// midnight shifted by longitude). Results are absolute Date values, or null
// when a polar day/night has no crossing. Civil dawn/dusk use -6 degrees.
export function sunTimes(date, lat, lon) {
  const input = new Date(date);
  const start = Date.UTC(input.getUTCFullYear(), input.getUTCMonth(), input.getUTCDate()) - lon / 360 * DAY;
  const result = { sunrise: null, sunset: null, dawn: null, dusk: null };
  if (!Number.isFinite(start) || !Number.isFinite(lat) || !Number.isFinite(lon)) return result;
  for (const [threshold, rising, setting] of [[-0.833, 'sunrise', 'sunset'], [-6, 'dawn', 'dusk']]) {
    const height = time => sunPosition(time, lat, lon).altitude / RAD - threshold;
    let previousTime = start;
    let previous = height(start);
    // Bracket crossings, then bisect to <1 second. Evaluating the changing
    // declination avoids the several-minute drift of a fixed-noon estimate.
    for (let time = start + DAY / 288; time <= start + DAY; time += DAY / 288) {
      const current = height(time);
      if ((previous < 0 && current >= 0) || (previous >= 0 && current < 0)) {
        let low = previousTime, high = time;
        const isRising = current > previous;
        while (high - low > 500) {
          const middle = (low + high) / 2;
          if ((height(middle) >= 0) === isRising) high = middle;
          else low = middle;
        }
        result[isRising ? rising : setting] = new Date((low + high) / 2);
      }
      previousTime = time;
      previous = current;
    }
  }
  return result;
}
