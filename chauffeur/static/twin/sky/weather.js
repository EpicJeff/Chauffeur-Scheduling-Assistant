import { cloudState, windSpeedMps } from './clouds.js';
import { base } from '../twin_library.js';

const finite = v => typeof v === 'number' && Number.isFinite(v);
const number = v => v !== null && v !== '' && v !== undefined && Number.isFinite(Number(v)) ? Number(v) : null;
const clamp = v => finite(v) ? Math.max(0, Math.min(1, v)) : 0;
const rates = {rainy:.45,pouring:1,'lightning-rainy':.8,snowy:.5,'snowy-rainy':.5,hail:.7};
const kinds = {rainy:'rain',pouring:'rain','lightning-rainy':'rain',snowy:'snow','snowy-rainy':'mix',hail:'hail'};
const scaledRate = v => v === 0 ? 0 : Math.max(.1,clamp(v/8));
const temperature = (v,unit) => !finite(v) ? null : ['°F','F'].includes(unit) ? (v-32)*5/9 : unit==='K' ? v-273.15 : v;

function sensorValue(sensor,role) {
  if (finite(sensor?.value)) return sensor.value; // Task 1's normalized report.
  const raw = sensor?.state, unit = sensor?.unit || sensor?.attributes?.unit_of_measurement;
  if (role==='rain' && ['on','off'].includes(raw)) return raw==='on' ? .5 : 0;
  const value=number(raw);
  if (value===null) return null;
  if (role==='wind_speed') return windSpeedMps(value,unit);
  if (role==='temperature') return temperature(value,unit);
  if (role==='rain') {
    if(value<0 || !['','mm/h','mm/hr','in/h','in/hr'].includes(unit || ''))return null;
    return scaledRate(value*(['in/h','in/hr'].includes(unit)?25.4:1));
  }
  return value;
}

// Reconstruct a standard weather entity from Task 1's normalized observation.
// updated is Unix SECONDS. Freshness remains the source/live stale flag, never
// last_changed (an unchanged HA observation may retain that timestamp for days).
export function sourceEntity(ground) {
  const source=ground?.source, v=source?.values;
  if (!source?.entity || !v?.condition) return null;
  return {state:v.condition,stale:!!source.stale,normalizedRate:v.rate,attributes:{
    cloud_coverage:v.cloud_coverage,wind_speed:v.wind_speed,wind_speed_unit:'m/s',
    wind_bearing:v.wind_bearing,visibility:v.visibility,temperature:v.temperature,temperature_unit:'°C'}};
}

export function weatherState(entity, ground={}, sensors={}, now=Date.now()/1000) {
  const valid=entity && !entity.stale && typeof entity.state==='string' && !['','unknown','unavailable'].includes(entity.state);
  const a=valid ? entity.attributes || {} : {};
  let condition=valid ? entity.state : 'sunny';
  let precip=valid ? kinds[condition] || 'none' : 'none', rate=valid ? rates[condition] || 0 : 0;
  if (valid && finite(entity.normalizedRate)) rate=clamp(entity.normalizedRate);
  else if (valid && Array.isArray(a.forecast)) {
    const hour=a.forecast.filter(row=>{
      const start=Date.parse(row.datetime)/1000;
      return finite(start) && start<=now && now<start+3600 && finite(row.precipitation) && row.precipitation>=0;
    }).sort((x,y)=>Date.parse(y.datetime)-Date.parse(x.datetime))[0];
    if (hour && precip!=='none' && ['mm','in',undefined].includes(a.precipitation_unit)) rate=Math.max(.1,clamp(hour.precipitation*(a.precipitation_unit==='in'?25.4:1)/8));
  }
  let wind=windSpeedMps(a.wind_speed,a.wind_speed_unit), bearing=finite(a.wind_bearing) ? a.wind_bearing : 270;
  let temperatureC=temperature(a.temperature,a.temperature_unit);
  if (valid) {
    const rain=sensorValue(sensors.rain,'rain'), speed=sensorValue(sensors.wind_speed,'wind_speed');
    const direction=sensorValue(sensors.wind_direction,'wind_direction'), temp=sensorValue(sensors.temperature,'temperature');
    if (rain!==null) {
      rate=clamp(rain);
      if(rate===0){precip='none';if(kinds[condition])condition='sunny';}
      else if(precip==='none'){precip='rain';condition='rainy';}
    }
    if (speed!==null && speed>=0) wind=speed;
    if (direction!==null) bearing=direction;
    if (temp!==null) temperatureC=temp;
  }
  // Reuse slice 2's condition table and bearing conversion; override only its
  // old missing-wind fallback so every consumer shares the calm global wind.
  const clouds=cloudState(valid ? {...entity,state:condition,attributes:{...a,wind_speed:wind ?? 0,wind_speed_unit:'m/s',wind_bearing:bearing}} : null);
  clouds.windMps=valid ? wind ?? 0 : 0;
  // Retained diagnostic severity; rendering uses visibilityM/extinction below.
  const fog=valid ? Math.max(condition==='fog'?1:0,finite(a.visibility)?clamp((5-a.visibility)/4):0) : 0;
  const visibilityM=valid&&finite(a.visibility)&&a.visibility>0?a.visibility*1000:condition==='fog'?300:null;
  const elapsed=finite(ground.updated)?Math.max(0,now-ground.updated):0;
  rate=precip==='none'?0:rate;
  return {condition,precip,rate,fog,visibilityM,windMps:clouds.windMps,windToDeg:clouds.windToDeg,
    windMissing:!valid || wind===null,temperatureC:valid?temperatureC:null,
    wetness:valid?clamp(ground.wetness):0,snow_cm:valid&&finite(ground.snow_cm)?Math.max(0,ground.snow_cm):0,
    puddles:valid?clamp(ground.puddles):0,updated:finite(ground.updated)?ground.updated:0,
    rain_stopped_s:!valid?null:rate>0?0:finite(ground.rain_stopped_s)&&ground.rain_stopped_s>=0
      &&ground.rain_stopped_s+elapsed<=21600?ground.rain_stopped_s+elapsed:null,
    drying_min:valid&&finite(ground.drying_min)&&ground.drying_min>0?ground.drying_min:null,
    clouds,preview:null,neutral:false};
}

// One latch per viewer. Stream observations can precede the server read; keep
// that stop time until the server reports a known stop, never restart each frame.
export function createWeatherClock() {
  let wasRaining=false,stoppedAt=null,lastRainAt=null;
  return (entity,ground={},sensors={},now=Date.now()/1000)=>{
    const value=weatherState(entity,ground,sensors,now);
    if(!entity||entity.stale||typeof entity.state!=='string'||['unknown','unavailable',''].includes(entity.state)){
      wasRaining=false;stoppedAt=null;lastRainAt=null;return value;
    }
    if(value.rate>0){wasRaining=true;stoppedAt=null;lastRainAt=now;return value;}
    if(wasRaining){stoppedAt=now;wasRaining=false;}
    // A still-raining server snapshot has stopped_s=0. Prefer the in-session
    // event until its next dry observation arrives.
    if(finite(value.rain_stopped_s)&&ground.source?.values?.rate===0
      &&(lastRainAt===null||now-value.rain_stopped_s>=lastRainAt)){
      stoppedAt=now-value.rain_stopped_s;
    }
    if(stoppedAt!==null)value.rain_stopped_s=now-stoppedAt<=21600?Math.max(0,now-stoppedAt):null;
    return value;
  };
}

export function neutralWeather() { return {...weatherState(null),neutral:true}; }
// Accumulation changes the surface uniforms, not the air or sun. In particular
// a 90-second preview ramp must not repeat sky quadrature on every frame.
export function weatherLightingKey(weather={}) {
  const {wetness,snow_cm,puddles,updated,rain_stopped_s,drying_min,...air}=weather;
  return JSON.stringify(air);
}
// HA visibility is kilometres; extinction is inverse metres. Rain and reported
// visibility describe the same air: take the shorter, never add densities.
export function weatherExtinction(weather={}) {
  if(weather.neutral)return 0;
  const rain=['rain','mix'].includes(weather.precip)?clamp(weather.rate):0;
  const visibility=finite(weather.visibilityM)&&weather.visibilityM>0?weather.visibilityM:weather.condition==='fog'?300:Infinity;
  const shortest=Math.min(visibility,rain>0?20000-17000*rain:Infinity);
  return Number.isFinite(shortest)?3.912/Math.max(shortest,.001):0;
}
export function weatherHaze(weather={},distanceM=10000) {
  return 1-Math.exp(-weatherExtinction(weather)*Math.max(0,finite(distanceM)?distanceM:0));
}
const smooth=(a,b,v)=>{const t=clamp((v-a)/Math.max(b-a,1e-6));return t*t*(3-2*t);};
// Scalar visibility of the unscattered solar/lunar disc through haze and solid
// overcast cloud decks. Clear/partly cloudy keep the disc (clouds modulate it
// spatially); solid overcast, rain and fog scatter it away into the sky dome.
export function sunAirVisibility(weather={}) {
  if(weather?.neutral)return 1;
  const air=1-weatherHaze(weather);
  const cover=clamp(weather?.clouds?.coverage);
  return clamp(air*(1-smooth(.55,.92,cover)));
}
// Combined direct-disc visibility (cloud ray transmittance + air/overcast).
// Shared by lit wet specular attenuation and raindrop splash sun lobes.
export function sunDiscVisibility(weather={},cloudTransmittance=1) {
  if(weather?.neutral)return 1;
  const t=clamp(cloudTransmittance);
  return clamp(t*smooth(.15,.85,t)*sunAirVisibility(weather));
}
const previews={clear:'sunny',rain:'rainy',pouring:'pouring','rain-stopping':'pouring',snow:'snowy',fog:'fog',thunderstorm:'lightning-rainy'};
export function previewWeather(name,elapsed=0) {
  if (!Object.hasOwn(previews,name)) return null;
  if(name==='rain-stopping'){
    const stopped=elapsed>=20;
    const stoppedS=stopped?Math.min(2700,Math.max(0,elapsed-20)<=30?elapsed-20:30+(elapsed-50)*2670/40):0;
    const dry=elapsed>=90;
    return {...weatherState({state:stopped?'sunny':'pouring',attributes:{wind_speed:3,wind_speed_unit:'m/s',wind_bearing:270}},
      {wetness:dry?0:Math.exp(-stoppedS/(180*60))*(1-smooth(80,90,elapsed)),puddles:dry?0:Math.exp(-stoppedS/(180*60))*(1-smooth(80,90,elapsed))}),
      rate:stopped?0:1,rain_stopped_s:stoppedS,drying_min:180,preview:name};
  }
  const wet=['rain','pouring','thunderstorm'].includes(name);
  const ramp=clamp(elapsed/90);
  return {...weatherState({state:previews[name],attributes:{wind_speed:name==='thunderstorm'?12:3,wind_speed_unit:'m/s',wind_bearing:270}},
    {wetness:wet?ramp:0,puddles:wet?ramp:0,snow_cm:name==='snow'?8:0}),preview:name};
}

export function createWeatherPreview(onChange,{setTimer=setTimeout,clearTimer=clearTimeout,now=Date.now}={}) {
  let value=null,timer=null,deadline=null,started=0;
  const clear=()=>{clearTimer(timer);timer=null;deadline=null;};
  const set=name=>{
    if (name!==null && !Object.hasOwn(previews,name)) return;
    clear();value=previewWeather(name);
    if(value){started=now();if(name!=='rain-stopping'){deadline=started+120000;timer=setTimer(()=>set(null),120000);}}
    onChange();
  };
  return {set,get:()=>value?previewWeather(value.preview,Math.max(0,(now()-started)/1000)):null,get deadline(){return deadline;},stop(){clear();value=null;}};
}

// One small request, no stream. Mutations and five-minute ticks coalesce; an
// event arriving during a request gets a trailing read rather than being lost.
export function mountWeatherState({api=(path,options)=>fetch(base()+path,options),onChange=()=>{},
  setTimer=setTimeout,clearTimer=clearTimeout}={}) {
  let stopped=false,timer=null,busy=null,ground=null,again=false;
  const halt=new AbortController();
  function refresh() {
    if(stopped)return Promise.resolve();
    if(busy)return busy;
    clearTimer(timer);
    busy=(async()=>{
      const limit=new AbortController(),abort=()=>limit.abort();
      const deadline=setTimeout(abort,15000);
      halt.signal.addEventListener('abort',abort,{once:true});
      try {
        const response=await api('api/house/twin/weather-state',{signal:limit.signal});
        if(!response.ok)throw new Error('Weather state unavailable');
        const next=await response.json();
        if(!next?.source)throw new Error('Weather state unavailable');
        if(!stopped){ground=next;onChange(next);}
      } catch {
        // The editor has no live-store stale flag. Do not leave an old storm
        // running there after the optional read loses HA/the network.
        if(!stopped && ground && !ground.source.stale){ground={...ground,source:{...ground.source,stale:true}};onChange(ground);}
      }
      finally {
        clearTimeout(deadline);halt.signal.removeEventListener('abort',abort);
        busy=null;
        if(!stopped){if(again){again=false;queueMicrotask(refresh);}else timer=setTimer(refresh,300000);}
      }
    })();
    return busy;
  }
  const changed=id=>{
    const relevant=id?.startsWith('weather.') || Object.values(ground?.source?.sensors || {}).some(s=>s.entity===id);
    if(!relevant || stopped)return Promise.resolve();
    if(busy)again=true;
    return refresh();
  };
  refresh();
  return {refresh,changed,peek:()=>ground,stop(){stopped=true;clearTimer(timer);halt.abort();}};
}
