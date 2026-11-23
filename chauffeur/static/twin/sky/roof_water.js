// Roof water state: runoff intensity, moving water film strength, and staged
// post-rain drying (sheet thins -> last trickles -> beads shrink -> dry).
// Pure JS, no DOM, no three.js; shared by weather_surface.js and eave streams.

const unit = v => Number.isFinite(v) ? Math.max(0, Math.min(1, v)) : 0;
const smooth = (a, b, v) => {
  const t = unit((v - a) / (b - a));
  return t * t * (3 - 2 * t);
};

// Film strength by rain intensity & roof wetness:
// light rain (<=0.16) none, steady (~0.40) moderate, heavy (>=0.76) full.
function filmCurve(flow, wet) {
  return smooth(0.16, 0.76, flow) * smooth(0.25, 0.75, wet);
}

export function createRoofWater() {
  let lastRate = 0.5;
  let lastWet = 1;
  let wasRaining = false;
  let stopStartS = null;

  return {
    update(weather = {}, seconds = 0) {
      if (!weather || weather.neutral) {
        lastRate = 0.5;
        lastWet = 1;
        wasRaining = false;
        stopStartS = null;
        return { wet: 0, flow: 0, film: 0, stoppedS: null };
      }

      const nowS = Number.isFinite(seconds) ? seconds : 0;
      const isRain = weather.precip === 'rain' || weather.precip === 'mix';
      const rate = isRain ? unit(weather.rate) : 0;
      const hasWet = weather.wetness !== undefined && weather.wetness !== null;
      const groundWet = hasWet ? unit(weather.wetness) : 0;
      const dryingMin = Number.isFinite(weather.drying_min) && weather.drying_min > 0
        ? Math.max(15, Math.min(1440, weather.drying_min))
        : 180;
      const scale = dryingMin / 180;

      if (rate > 0) {
        const wet = groundWet;
        lastRate = rate;
        lastWet = wet;
        wasRaining = true;
        stopStartS = null;
        return { wet, flow: rate, film: filmCurve(rate, wet), stoppedS: 0 };
      }

      const hasStoppedProp = Number.isFinite(weather.rain_stopped_s) && weather.rain_stopped_s >= 0;
      let stoppedS = null;
      if (hasStoppedProp) {
        stoppedS = weather.rain_stopped_s;
        if (wasRaining) {
          wasRaining = false;
          stopStartS = nowS - stoppedS;
        }
      } else if (wasRaining) {
        wasRaining = false;
        stopStartS = nowS;
        stoppedS = 0;
      } else if (stopStartS !== null) {
        stoppedS = Math.max(0, nowS - stopStartS);
      }

      if (stoppedS === null) {
        return { wet: groundWet, flow: 0, film: 0, stoppedS: null };
      }

      // Determine roof wetness at the moment rain stopped.
      // When the page loads mid-drying, invert the ground model's e-folding decay.
      let baseWet;
      if (hasWet && groundWet <= 0) {
        return { wet: 0, flow: 0, film: 0, stoppedS };
      } else if (hasStoppedProp) {
        baseWet = hasWet ? Math.min(1, groundWet * Math.exp((stoppedS / 60) / dryingMin)) : 1;
      } else {
        baseWet = lastWet;
      }

      if (baseWet <= 0) {
        return { wet: 0, flow: 0, film: 0, stoppedS };
      }

      // Scaled time since stop (at drying_min = 180, t === stoppedS):
      // 1. Sheet/film thins & disappears: 0 - 3 min (180 s)
      // 2. Last trickles / flow drains to 0: 0 - 10 min (600 s)
      // 3. Beads shrink & thin out, dry by 40 min (2400 s)
      const t = stoppedS / scale;
      const wetRaw = baseWet * (1 - smooth(0, 2400, t));
      const flowRaw = lastRate * Math.exp(-t / 180) * (1 - smooth(450, 600, t));
      const filmRaw = filmCurve(lastRate, baseWet) * Math.exp(-t / 55) * (1 - smooth(110, 180, t));

      const wet = wetRaw < 1e-4 ? 0 : Math.min(1, wetRaw);
      const flow = flowRaw < 1e-4 ? 0 : Math.min(1, flowRaw);
      const film = filmRaw < 1e-4 ? 0 : Math.min(1, filmRaw);
      return { wet, flow, film, stoppedS };
    },
  };
}
