"""Roof water drying ladder and state machine: real node runs of roof_water.js and weather_surface.js."""
import sys
from pathlib import Path

from test_twin_weather_surface_js import PREFIX
from twin_editor_dom import run_node

ROOT = Path(__file__).resolve().parents[1]

DRIVER = PREFIX + r"""
const {createRoofWater,eaveRunoff}=await import(file('static/twin/sky/roof_water.js'));
const {installWeatherSurface}=await import(file('static/twin/sky/weather_surface.js'));
const close=(a,b,msg='',eps=1e-6)=>assert.ok(Math.abs(a-b)<=eps,`${msg?msg+': ':''}${a} != ${b}`);

await test('eave runoff waits for the roof to wet through: beads none, rivulets trickle, film full',()=>{
 const rw=createRoofWater();
 const beads=rw.update({precip:'rain',rate:1,wetness:.15},1);
 close(eaveRunoff(beads),0,'heavy rain on a barely wet roof pours nothing yet');
 const rivulets=rw.update({precip:'rain',rate:1,wetness:.45},2);
 const r=eaveRunoff(rivulets);assert.ok(r>.1&&r<.7,`rivulet stage trickles: ${r}`);
 const film=rw.update({precip:'rain',rate:1,wetness:.9},3);
 close(eaveRunoff(film),1,'saturated roof in heavy rain pours fully');
 close(eaveRunoff({flow:.3,wet:1}),.3,'light rain on a wet roof follows the rain rate');
});

await test('raining gives flow = rate, wet = wetness, stoppedS = 0, and film ramps light 0 -> steady moderate -> heavy 1',()=>{
 const rw=createRoofWater();
 const light=rw.update({precip:'rain',rate:.12,wetness:.55},10);
 close(light.flow,.12);close(light.wet,.55);close(light.film,0);assert.equal(light.stoppedS,0);

 const steady=rw.update({precip:'rain',rate:.40,wetness:.90},20);
 close(steady.flow,.40);close(steady.wet,.90);assert.equal(steady.stoppedS,0);
 assert.ok(steady.film>.20&&steady.film<.60,`steady film moderate (${steady.film.toFixed(3)})`);

 const heavy=rw.update({precip:'rain',rate:1.0,wetness:1.0},30);
 close(heavy.flow,1.0);close(heavy.wet,1.0);close(heavy.film,1.0);assert.equal(heavy.stoppedS,0);

 const mixRain=rw.update({precip:'mix',rate:.50,wetness:.85},40);
 close(mixRain.flow,.50);assert.ok(mixRain.film>.40);assert.equal(mixRain.stoppedS,0);

 // Dry roof while rain just starts: film stays 0 at wet=0.
 const justStarted=rw.update({precip:'rain',rate:1.0,wetness:0},50);
 close(justStarted.wet,0);close(justStarted.flow,1.0);close(justStarted.film,0);
});

await test('after stop at drying_min=180: film thins 0-3m, flow drains 0-10m, beads shrink 10-40m, dry at 40-45m',()=>{
 const rw=createRoofWater();
 rw.update({precip:'rain',rate:1.0,wetness:1.0,drying_min:180,rain_stopped_s:0},0);

 const s0=rw.update({precip:'none',rate:0,wetness:1.0,drying_min:180,rain_stopped_s:0},1);
 close(s0.flow,1.0);close(s0.film,1.0);close(s0.wet,1.0);assert.equal(s0.stoppedS,0);

 const s60=rw.update({precip:'none',rate:0,wetness:.99,drying_min:180,rain_stopped_s:60},61);
 assert.ok(s60.film>.15&&s60.film<.65,`1m film thinning (${s60.film.toFixed(3)})`);
 assert.ok(s60.flow>.5&&s60.flow<.9,`1m flow still active (${s60.flow.toFixed(3)})`);

 const s120=rw.update({precip:'none',rate:0,wetness:.98,drying_min:180,rain_stopped_s:120},121);
 assert.ok(s120.film>0&&s120.film<.25,`2m film mostly thinned (${s120.film.toFixed(3)})`);
 assert.ok(s120.flow>.3&&s120.flow<.7,`2m streams still finishing (${s120.flow.toFixed(3)})`);
 assert.ok(s120.wet>.95,`2m roof still wet (${s120.wet.toFixed(3)})`);

 const s180=rw.update({precip:'none',rate:0,wetness:.97,drying_min:180,rain_stopped_s:180},181);
 close(s180.film,0);
 assert.ok(s180.flow>.2,`3m trickles still running (${s180.flow.toFixed(3)})`);

 const s480=rw.update({precip:'none',rate:0,wetness:.95,drying_min:180,rain_stopped_s:480},481);
 close(s480.film,0);
 assert.ok(s480.flow>0&&s480.flow<.15,`8m last trickles (${s480.flow.toFixed(3)})`);
 assert.ok(s480.wet>.80,`8m beads still full (${s480.wet.toFixed(3)})`);

 const s600=rw.update({precip:'none',rate:0,wetness:.94,drying_min:180,rain_stopped_s:600},601);
 close(s600.film,0);close(s600.flow,0);
 assert.ok(s600.wet>.75,`10m runoff finished, beads begin thinning (${s600.wet.toFixed(3)})`);

 const s1200=rw.update({precip:'none',rate:0,wetness:.90,drying_min:180,rain_stopped_s:1200},1201);
 close(s1200.film,0);close(s1200.flow,0);
 assert.ok(s1200.wet>.35&&s1200.wet<.65,`20m beads mid-thinning (${s1200.wet.toFixed(3)})`);

 const s1800=rw.update({precip:'none',rate:0,wetness:.85,drying_min:180,rain_stopped_s:1800},1801);
 assert.ok(s1800.wet>0&&s1800.wet<s1200.wet*.5,`30m sparse small beads (${s1800.wet.toFixed(3)})`);

 const s2400=rw.update({precip:'none',rate:0,wetness:.80,drying_min:180,rain_stopped_s:2400},2401);
 close(s2400.wet,0);close(s2400.flow,0);close(s2400.film,0);

 const s2700=rw.update({precip:'none',rate:0,wetness:.80,drying_min:180,rain_stopped_s:2700},2701);
 close(s2700.wet,0);close(s2700.flow,0);close(s2700.film,0);
});

await test('drying times scale with drying_min: faster at 60 min (sun/heat), slower at 360 min (humid)',()=>{
 const sample=(dryingMin,stoppedS)=>{
  const rw=createRoofWater();
  rw.update({precip:'rain',rate:.8,wetness:1,drying_min:dryingMin,rain_stopped_s:0},0);
  return rw.update({precip:'none',rate:0,wetness:Math.exp(-(stoppedS/60)/dryingMin),drying_min:dryingMin,rain_stopped_s:stoppedS},stoppedS);
 };
 // At 60 min (scale 1/3): film gone by 60 s, flow gone by 200 s, dry by 800 s.
 const fast60=sample(60,60),fast200=sample(60,200),fast400=sample(60,400),fast800=sample(60,800);
 close(fast60.film,0);close(fast200.flow,0);
 assert.ok(fast400.wet>.35&&fast400.wet<.65,`drying_min=60 mid-ladder at 400 s (${fast400.wet.toFixed(3)})`);
 close(fast800.wet,0);

 // At 360 min (scale 2): still has film at 240 s, flow at 900 s, mid-ladder at 2400 s, dry at 4800 s.
 const slow240=sample(360,240),slow900=sample(360,900),slow2400=sample(360,2400),slow4800=sample(360,4800);
 assert.ok(slow240.film>0,`drying_min=360 still has film at 240 s (${slow240.film.toFixed(3)})`);
 assert.ok(slow900.flow>0,`drying_min=360 still has trickles at 900 s (${slow900.flow.toFixed(3)})`);
 assert.ok(slow2400.wet>.35&&slow2400.wet<.65,`drying_min=360 mid-ladder at 2400 s (${slow2400.wet.toFixed(3)})`);
 close(slow4800.wet,0);

 // Strict ordering at the same wall-clock stoppedS=480: fast < mild < slow.
 const f=sample(60,480),m=sample(180,480),s=sample(360,480);
 assert.ok(f.wet<m.wet&&m.wet<s.wet,`drying_min ordering at 8m: ${f.wet.toFixed(3)} < ${m.wet.toFixed(3)} < ${s.wet.toFixed(3)}`);
});

await test('page loaded mid-drying jumps to the right stage at once and assumes lastRate=0.5 after stop',()=>{
 const mid=createRoofWater().update({precip:'none',rate:0,wetness:.90,rain_stopped_s:1200,drying_min:180},5);
 close(mid.film,0);close(mid.flow,0);
 assert.equal(mid.stoppedS,1200);
 assert.ok(mid.wet>.35&&mid.wet<.65,`fresh page at rain_stopped_s=1200 is mid-ladder (${mid.wet.toFixed(3)})`);

 const justStopped=createRoofWater().update({precip:'none',rate:0,wetness:1.0,rain_stopped_s:0,drying_min:180},5);
 close(justStopped.flow,.5,'assumes lastRate=0.5 when loaded right after stop');
 assert.ok(justStopped.film>.3&&justStopped.wet>.99,'has moderate film and full wet at stop');

 const dryPage=createRoofWater().update({precip:'none',rate:0,wetness:.80,rain_stopped_s:2700,drying_min:180},5);
 close(dryPage.wet,0);close(dryPage.flow,0);close(dryPage.film,0);
});

await test('rain restarting resets the drying ladder and records the new raining rate',()=>{
 const rw=createRoofWater();
 rw.update({precip:'rain',rate:1.0,wetness:1.0},0);
 const mid=rw.update({precip:'none',rate:0,wetness:.90,rain_stopped_s:1200},1200);
 close(mid.flow,0);assert.ok(mid.wet<.65);

 // Restart with light rain: resets stoppedS to 0 and records new rate 0.12.
 const back=rw.update({precip:'rain',rate:.12,wetness:.70,rain_stopped_s:0},1210);
 assert.equal(back.stoppedS,0);close(back.flow,.12);close(back.film,0);close(back.wet,.70);

 // Stop again: drains from the new light rate (no phantom heavy-rain film!).
 const stop2=rw.update({precip:'none',rate:0,wetness:.70,rain_stopped_s:10},1220);
 close(stop2.film,0,'restarted light rain has no phantom heavy film after stopping');
 assert.ok(stop2.flow>0&&stop2.flow<=.12,`drains from new rate 0.12 (${stop2.flow.toFixed(3)})`);
});

await test('missing rain_stopped_s and drying_min fall back to in-session tracking with 180 min default',()=>{
 const rw=createRoofWater();
 // Old server: never rained in session, no rain_stopped_s -> static wetness, zero flow/film.
 const unknown=rw.update({precip:'none',rate:0,wetness:.75},10);
 close(unknown.wet,.75);close(unknown.flow,0);close(unknown.film,0);assert.equal(unknown.stoppedS,null);

 // Rain starts, then stops without rain_stopped_s or drying_min.
 rw.update({precip:'rain',rate:.85,wetness:1.0},100);
 const t0=rw.update({precip:'none',rate:0,wetness:1.0},200);
 assert.equal(t0.stoppedS,0);close(t0.flow,.85);assert.ok(t0.film>.95);

 const t120=rw.update({precip:'none',rate:0,wetness:.98},320);
 assert.equal(t120.stoppedS,120);
 assert.ok(t120.film>0&&t120.film<.25&&t120.flow>.3);

 const t600=rw.update({precip:'none',rate:0,wetness:.94},800);
 assert.equal(t600.stoppedS,600);close(t600.film,0);close(t600.flow,0);

 const t1200=rw.update({precip:'none',rate:0,wetness:.90},1400);
 assert.equal(t1200.stoppedS,1200);assert.ok(t1200.wet>.35&&t1200.wet<.65);

 const t2400=rw.update({precip:'none',rate:0,wetness:.80},2600);
 assert.equal(t2400.stoppedS,2400);close(t2400.wet,0);close(t2400.flow,0);close(t2400.film,0);
});

await test('neutral weather and snow/hail handling: neutral is dry and resets session state',()=>{
 const rw=createRoofWater();
 rw.update({precip:'rain',rate:1.0,wetness:1.0},10);
 const neu=rw.update({neutral:true,precip:'rain',rate:1.0,wetness:1.0,rain_stopped_s:0},20);
 close(neu.wet,0);close(neu.flow,0);close(neu.film,0);assert.equal(neu.stoppedS,null);

 // After neutral reset, dry none weather has no ghost drain.
 const after=rw.update({precip:'none',rate:0,wetness:0},30);
 close(after.wet,0);close(after.flow,0);close(after.film,0);assert.equal(after.stoppedS,null);

 // Snow is not liquid rain flow.
 const snow=rw.update({precip:'snow',rate:.9,wetness:.2,snow_cm:4},40);
 close(snow.flow,0);close(snow.film,0);
});

await test('weatherSurface.update feeds weatherRoof uniform cleanly, fades trails before beads, and keeps phase advancing while draining',()=>{
 const layer=installWeatherSurface(new THREE.Scene());
 layer.update({precip:'rain',rate:1.0,wetness:1.0,puddles:1.0,rain_stopped_s:0,drying_min:180},16);
 let r=layer.roofUniforms.weatherRoof.value;
 close(r.x,1);close(r.y,1);close(r.z,1);close(r.w,1);
 close(layer.uniforms.weatherSurface.value.w-Math.floor(layer.uniforms.weatherSurface.value.w),16/64);

 // Draining at t=10 s (rate=0, flow>0): phase advances on weatherSurface.w while flow > 0.
 layer.update({precip:'none',rate:0,wetness:1.0,rain_stopped_s:10,drying_min:180},20);
 const phaseA=layer.uniforms.weatherSurface.value.w-Math.floor(layer.uniforms.weatherSurface.value.w);
 assert.equal(Math.floor(layer.uniforms.weatherSurface.value.w),0);
 assert.ok(r.y>.8,'flow stays positive during early drain');
 layer.update({precip:'none',rate:0,wetness:1.0,rain_stopped_s:14,drying_min:180},24);
 const phaseB=layer.uniforms.weatherSurface.value.w-Math.floor(layer.uniforms.weatherSurface.value.w);
 assert.ok(phaseB>phaseA,'phase clock keeps running while roof drains');

 // Mid-drying (20 min): damp trails (w) are gone while beads (x) remain mid-ladder.
 layer.update({precip:'none',rate:0,wetness:.90,rain_stopped_s:1200,drying_min:180},30);
 close(r.w,0,'damp trails fade before beads finish');
 assert.ok(r.x>.35&&r.x<.65,'beads still present at 20 min');

 // Dry (45 min) and neutral: all four weatherRoof lanes zero.
 layer.update({precip:'none',rate:0,wetness:.80,rain_stopped_s:2700,drying_min:180},40);
 assert.deepEqual(r.toArray(),[0,0,0,0]);
 layer.update({neutral:true,precip:'rain',rate:1,wetness:1},50);
 assert.deepEqual(r.toArray(),[0,0,0,0]);
 layer.dispose();
});

finish();
"""

if __name__ == '__main__':
    code, output = run_node(DRIVER, {'root': ROOT.as_posix()}, timeout=120)
    print(output)
    sys.exit(code)
