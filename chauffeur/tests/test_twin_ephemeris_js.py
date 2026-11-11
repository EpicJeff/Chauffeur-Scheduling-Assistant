"""Execute the dependency-free sky ES module under Node, without a browser.

Solar reference constants independently evaluated from NOAA's published equations:
https://gml.noaa.gov/grad/solcalc/solareqns.PDF
(fractional year, equation of time, declination and hour angle; sunrise -0.833,
civil twilight -6 degrees). UTC dates, longitude positive east.

Moon reference: NASA RP 1349, Fred Espenak, 2001 January 10 at 0 DT:
https://eclipse.gsfc.nasa.gov/TYPE/moon3.html
RA 7h35m7.3s, Dec +22d14m18.8s, distance 357300 km. Transforming these
independent tabulated coordinates at lat 40/lon 0 with GMST 109.585557 degrees
gives geometric altitude 71.885179 degrees; sea-level parallax gives 71.561688.
The DT/UTC difference is immaterial at the requested 1.5 degree tolerance.

Known phases from the US Naval Observatory's primary phase table:
https://aa.usno.navy.mil/api/moon/phases/year?year=2026
Full 2026-01-03 10:03 UT; new 2026-01-18 19:52 UT.

Run from chauffeur/: env -u HA_BASE_URL python tests/test_twin_ephemeris_js.py
"""
import json
import math
from pathlib import Path
import subprocess
import unittest


MODULE = Path(__file__).resolve().parents[1] / 'static/twin/sky/ephemeris.js'
DRIVER = r"""
import fs from 'node:fs';
const sky = await import('data:text/javascript;base64,' + fs.readFileSync(process.argv[1]).toString('base64'));
const solarCases = [
  ['2026-06-21T12:00:00Z', 51.4779, 0],
  ['2026-03-20T17:00:00Z', 40, -75],
  ['2026-12-21T02:00:00Z', -33.8688, 151.2093],
];
const original = new Date('2026-06-21T12:00:00Z');
const timestamp = original.getTime();
sky.sunPosition(original, 40, -75);
sky.moonPosition(original, 40, -75);
sky.moonIllumination(original);
sky.sunTimes(original, 40, -75);
const samples = [];
for (let hour = 0; hour < 24; hour++) {
  for (const lat of [-90, -40, 0, 40, 90]) {
    const date = new Date(Date.UTC(2026, 5, 21, hour));
    samples.push(sky.sunPosition(date, lat, -75), sky.moonPosition(date, lat, -75));
  }
}
console.log(JSON.stringify({
  solar: solarCases.map(args => sky.sunPosition(...args)),
  times: sky.sunTimes('2026-06-21T12:00:00Z', 51.4779, 0),
  eastTimes: sky.sunTimes('2026-12-21T02:00:00Z', -33.8688, 151.2093),
  polarSummer: sky.sunTimes('2026-06-21T12:00:00Z', 89, 0),
  polarWinter: sky.sunTimes('2026-12-21T12:00:00Z', 89, 0),
  full: sky.moonIllumination('2026-01-03T10:03:00Z'),
  newMoon: sky.moonIllumination('2026-01-18T19:52:00Z'),
  firstQuarter: sky.moonIllumination('2026-01-26T04:47:00Z'),
  lastQuarter: sky.moonIllumination('2026-01-10T15:48:00Z'),
  moon: sky.moonPosition('2001-01-10T00:00:00Z', 40, 0),
  morning: sky.sunPosition('2026-03-20T11:30:00Z', 40, -75),
  evening: sky.sunPosition('2026-03-20T22:30:00Z', 40, -75),
  unchanged: original.getTime() === timestamp,
  samples,
}));
"""


class EphemerisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = subprocess.run(
            ['node', '--input-type=module', '-e', DRIVER, str(MODULE)],
            check=True, capture_output=True, text=True, encoding='utf-8', timeout=30,
        )
        cls.data = json.loads(result.stdout)

    def angle_close(self, radians, degrees, tolerance):
        self.assertLessEqual(abs(math.degrees(radians) - degrees), tolerance)

    def test_greenwich_solstice(self):
        self.angle_close(self.data['solar'][0]['altitude'], 61.972976, 0.5)
        self.angle_close(self.data['solar'][0]['azimuth'], 179.351689, 0.5)

    def test_equinox_noon(self):
        self.angle_close(self.data['solar'][1]['altitude'], 49.579000, 0.5)
        self.angle_close(self.data['solar'][1]['azimuth'], 176.875857, 0.5)

    def test_southern_summer(self):
        self.angle_close(self.data['solar'][2]['altitude'], 79.428112, 0.5)
        self.angle_close(self.data['solar'][2]['azimuth'], 350.959278, 0.5)

    def test_sunrise_sunset_within_two_minutes(self):
        from datetime import datetime
        for name, reference_seconds in [('sunrise', 13333.008719), ('sunset', 73226.379697)]:
            with self.subTest(event=name):
                event = datetime.fromisoformat(self.data['times'][name].replace('Z', '+00:00'))
                midnight = event.replace(hour=0, minute=0, second=0, microsecond=0)
                self.assertEqual(event.date().isoformat(), '2026-06-21')
                self.assertLessEqual(abs((event - midnight).total_seconds() - reference_seconds), 120)

    def test_civil_twilight_within_two_minutes(self):
        from datetime import datetime
        for name, reference_seconds in [('dawn', 10469.220973), ('dusk', 76090.167443)]:
            with self.subTest(event=name):
                event = datetime.fromisoformat(self.data['times'][name].replace('Z', '+00:00'))
                midnight = event.replace(hour=0, minute=0, second=0, microsecond=0)
                self.assertLessEqual(abs((event - midnight).total_seconds() - reference_seconds), 120)

    def test_east_longitude_events_can_be_on_previous_utc_date(self):
        self.assertTrue(self.data['eastTimes']['sunrise'].startswith('2026-12-20T18:'))
        self.assertTrue(self.data['eastTimes']['sunset'].startswith('2026-12-21T09:'))

    def test_polar_events_are_absent(self):
        for season in ['polarSummer', 'polarWinter']:
            self.assertEqual(self.data[season], dict.fromkeys(['sunrise', 'sunset', 'dawn', 'dusk']))

    def test_full_and_new_moon_illumination(self):
        self.assertGreaterEqual(self.data['full']['fraction'], 0.98)
        self.assertLessEqual(self.data['newMoon']['fraction'], 0.02)

    def test_phase_increases_from_new_through_quarters(self):
        self.assertAlmostEqual(self.data['firstQuarter']['phase'], 0.25, delta=0.04)
        self.assertAlmostEqual(self.data['full']['phase'], 0.5, delta=0.04)
        self.assertAlmostEqual(self.data['lastQuarter']['phase'], 0.75, delta=0.04)

    def test_moon_altitude_and_distance_from_nasa_table(self):
        self.angle_close(self.data['moon']['altitude'], 71.561688, 1.5)
        self.assertAlmostEqual(self.data['moon']['distance'], 357300, delta=2500)

    def test_compass_bearing_and_finite_poles(self):
        self.assertLess(self.data['morning']['azimuth'], math.pi)
        self.assertGreater(self.data['evening']['azimuth'], math.pi)
        for position in self.data['samples']:
            self.assertTrue(math.isfinite(position['azimuth']))
            self.assertTrue(math.isfinite(position['altitude']))
            self.assertGreaterEqual(position['azimuth'], 0)
            self.assertLess(position['azimuth'], 2 * math.pi)
            self.assertLessEqual(abs(position['altitude']), math.pi / 2)

    def test_input_dates_are_not_mutated(self):
        self.assertTrue(self.data['unchanged'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
