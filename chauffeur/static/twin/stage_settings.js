import { base } from './twin_library.js';

// Match services/twin_stage.py and the viewer's transformed house framing.
// Distances and centre are feet; three's z is the negative of plan y.
export function defaultStage(plan = {}) {
  const points = (plan?.buildings || []).flatMap(building => {
    const angle = (building.rotation || 0) * Math.PI / 180, c = Math.cos(angle), s = Math.sin(angle);
    const local = building.walls?.length ? building.walls.flatMap(w => [w.from, w.to])
      : [...(building.levels || []).flatMap(l => l.outline || []), ...(building.rooms || []).flatMap(r => r.polygon || [])];
    return local.map(p => [c * p[0] - s * p[1] + (building.position?.[0] || 0),
      s * p[0] + c * p[1] + (building.position?.[1] || 0)]);
  });
  const centre = points.length ? [0, 1].map(i => (Math.min(...points.map(p => p[i])) + Math.max(...points.map(p => p[i]))) / 2) : [19, 11];
  const farthest = Math.max(0, ...(plan?.site?.lot || []).map(p => Math.hypot(p[0] - centre[0], p[1] - centre[1])));
  const radius = Math.min(1000, Math.max(30, farthest + 120));
  return {centre: [centre[0], -centre[1]], radius, default_radius: radius, radius_override: null};
}

export function mountStageSettings(view, {api = (path, init) => fetch(base() + path, init)} = {}) {
  const section = document.getElementById('twin-stage-settings');
  const field = document.getElementById('house_twin_stage_radius_ft');
  const save = document.getElementById('twin-stage-save'), reset = document.getElementById('twin-stage-reset');
  const hint = document.getElementById('twin-stage-default');
  const mirror = document.getElementById('house_twin_mirror_still_hz');
  const mirrorSave = document.getElementById('twin-mirror-save');
  const cloud = document.getElementById('house_twin_probe_cloud_s');
  const cloudSave = document.getElementById('twin-probe-cloud-save');
  const events = new AbortController();
  let stopped = false, ready = false, busy = false, revision = 0;
  const listen = (node, type, fn) => node?.addEventListener(type, fn, {signal: events.signal});
  function controls() { for (const node of [field,save,reset,mirror,mirrorSave,cloud,cloudSave]) if(node)node.disabled = !ready || busy; }
  function apply(stage) {
    if (field) field.value = String(stage.radius);
    if (mirror) mirror.value = String(stage.mirror_still_hz ?? 10);
    if (cloud) cloud.value = String(stage.probe_cloud_s ?? 30);
    if (hint) hint.textContent = `Automatic radius: ${Math.round(stage.default_radius)} ft (120 ft beyond the farthest lot corner).`;
  }
  async function reload() {
    if (!section || stopped || busy) return;
    const request = ++revision;
    ready = false; controls();
    try {
      const response = await api('api/house/twin/stage');
      if (!response.ok) throw new Error('Could not load the stage radius.');
      const stage = await response.json();
      if (stopped || request !== revision) return;
      apply(stage); ready = true;
    } catch (error) { if (!stopped && request === revision) window.chfSettingsSaved?.(false, error.message); }
    finally { if (!stopped && request === revision) controls(); }
  }
  async function store(radius) {
    if (!ready || busy || stopped) return;
    if (radius !== null && (!Number.isFinite(radius) || radius < 30 || radius > 1000)) {
      window.chfSettingsSaved?.(false, 'Stage radius must be between 30 and 1000 feet.'); return;
    }
    busy = true; ++revision; controls(); window.chfSettingsSaving?.();
    try {
      const response = await api('api/house/twin/stage', {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({radius})});
      const stage = await response.json();
      if (!response.ok) throw new Error(stage.detail || 'Could not save the stage radius.');
      if (stopped) return;
      apply(stage); await view.setStage?.(stage); window.chfSettingsSaved?.(true);
    } catch (error) { if (!stopped) window.chfSettingsSaved?.(false, error.message); }
    finally { busy = false; if (!stopped) controls(); }
  }
  controls();
  listen(mirrorSave, 'click', async () => {
    if (!ready || busy || stopped) return;
    busy=true; ++revision; controls(); window.chfSettingsSaving?.();
    try {
      const response=await api('api/house/twin/mirror', {method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({mirror_still_hz:Number(mirror.value)})});
      const stage=await response.json();
      if(!response.ok)throw new Error(stage.detail || 'Could not save the mirror refresh rate.');
      if(stopped)return;
      apply(stage); view.setMirrorStillHz?.(stage.mirror_still_hz); window.chfSettingsSaved?.(true);
    } catch(error) { if(!stopped)window.chfSettingsSaved?.(false,error.message); }
    finally {busy=false;if(!stopped)controls();}
  });
  listen(save, 'click', () => store(field?.value?.trim() ? Number(field.value) : NaN));
  listen(cloudSave, 'click', async () => {
    if (!ready || busy || stopped) return;
    busy=true; ++revision; controls(); window.chfSettingsSaving?.();
    try {
      const response=await api('api/house/twin/probe-cloud', {method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({probe_cloud_s:Number(cloud.value)})});
      const stage=await response.json();
      if(!response.ok)throw new Error(stage.detail || 'Could not save the cloud reflection interval.');
      if(stopped)return;
      apply(stage); view.setProbeCloudSeconds?.(stage.probe_cloud_s); window.chfSettingsSaved?.(true);
    } catch(error) { if(!stopped)window.chfSettingsSaved?.(false,error.message); }
    finally {busy=false;if(!stopped)controls();}
  });
  listen(reset, 'click', () => store(null));
  listen(window, 'chf-settings-opened', event => { if (event.detail?.tab === 'twin') reload(); });
  // The public mount payload owns the rendered radius. Fetch this parent-only
  // preference only when the desk drawer opens, so a child's view stays quiet.
  return {reload, stop() {stopped = true; ++revision; events.abort();}};
}
