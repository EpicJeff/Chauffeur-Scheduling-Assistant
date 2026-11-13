import * as THREE from 'three';
import { FT } from '../twin_generator.js';
import { isEnergyEntity } from './glance.js';
import { guessEnergy, chargingCar, flowReading, watts, energyBalance } from './energy_mapping.js';
import { energyCheck, renderEnergyCheck } from './energy_check.js';
import { energyTopology, energyPlacementLegend, energyAnchors, worldPoint, flowCurve, flowRoute, flowApex, flowFans } from './energy_geometry.js';

import { createConduitRouter } from './solar_conduit.js';

export const FLOW_COLORS = {solar: '#efbd24', battery: '#31ae62', grid: '#338bd9', house: '#57a8da', car: '#9957d2'};
// Conduit is electric blue (user, 2026-11-13), clear of grid blue and the panels.
export const CONDUIT_COLOR = '#4df0ff';

// Prefer the apex, then the same ribbon and nearby positions. Crowding must
// never discard a reading: the last resort is a visible stack with a gap.
export function flowLabelPositions(entries, rect) {
  const placed = [];
  const overlaps = (a, b) => a.left < b.right + 2 && a.right + 2 > b.left && a.top < b.bottom + 2 && a.bottom + 2 > b.top;
  const choices = entries.map(entry => {
    const boxes = [], offsets = [[0, 0], [0, -14], [0, 14], [0, -24], [0, 24], [-24, 0], [24, 0], [-16, -16], [16, -16], [-16, 16], [16, 16]];
    const candidates = [{...entry,placement:'apex'}, ...(entry.along || []).map(p => ({...p,placement:'ribbon'})),
      ...offsets.slice(1).map(([dx,dy]) => ({x:entry.x+dx,y:entry.y+dy,placement:'near-apex'}))];
    for (const {x,y,placement} of candidates) {
      const height = entry.height || 24;
      const box = {x, y, left: x - entry.width / 2, right: x + entry.width / 2, top: y - height / 2, bottom: y + height / 2, visible: true, placement};
      if (box.left < rect.left || box.right > rect.right || rect.top !== undefined && box.top < rect.top || rect.bottom !== undefined && box.bottom > rect.bottom) continue;
      boxes.push(box);
    }
    return boxes;
  });
  for (const [i, entry] of entries.entries()) {
    let box = choices[i].find(box => !placed.some(p => p.visible && overlaps(box, p)));
    // A pair can often fit on opposite sides of their apexes even when
    // keeping the first label dead-centre would hide the second one.
    for (let j = placed.length - 1; !box && j >= 0; j--) {
      if (!placed[j].visible) continue;
      for (const alternative of choices[j]) {
        if (placed.some((p, k) => k !== j && p.visible && overlaps(alternative, p))) continue;
        box = choices[i].find(candidate => !overlaps(candidate, alternative) &&
          !placed.some((p, k) => k !== j && p.visible && overlaps(candidate, p)));
        if (box) {placed[j] = alternative; break;}
      }
    }
    if (!box) {
      const x = Math.max(rect.left + entry.width / 2, Math.min(rect.right - entry.width / 2, entry.x));
      const height = entry.height || 24;
      const baseY = Math.max((rect.top ?? -Infinity) + height / 2, Math.min((rect.bottom ?? Infinity) - height / 2, entry.y));
      // Try both sides of the apex and keep the stack within the viewport
      // when it fits. If the viewport itself is too small, retain every label.
      for (const bounded of [true, false]) {
        for (let attempt = 0; !box && attempt <= 2 * placed.length + 2; attempt++) {
          const lane = attempt % 2 ? -(attempt + 1) / 2 : attempt / 2;
          const y = baseY + lane * (height + 4);
          const candidate = {x,y,left:x-entry.width/2,right:x+entry.width/2,top:y-height/2,bottom:y+height/2,visible:true,placement:'stack'};
          if (bounded && (rect.top !== undefined && candidate.top < rect.top || rect.bottom !== undefined && candidate.bottom > rect.bottom)) continue;
          if (!placed.some(p => overlaps(candidate,p))) box = candidate;
        }
        if (box) break;
      }
      // Mixed-height labels may cover several regular stack slots.
      if (!box) {
        const top = Math.max(entry.y - height / 2, ...placed.map(p => p.bottom)) + 4;
        box = {x,y:top+height/2,left:x-entry.width/2,right:x+entry.width/2,top,bottom:top+height,visible:true,placement:'stack'};
      }
    }
    placed.push(box);
  }
  return placed;
}

export function mountEnergy({view, live, warm, overlays = view.scene}) {
  const root = new THREE.Group(); root.userData.twinMode = 'energy'; overlays.add(root);
  const labels = document.createElement('div'); labels.className = 'twin-mode-labels twin-energy-labels'; document.body.append(labels);
  let key = '', mapping = {}, ribbons = [], conduits = [], anchors = null, check = null;
  let conduitSolar = null;
  const conduitRouter = createConduitRouter();
  let conduitTask = Promise.resolve(), conduitPending = false, rebuildSerial = 0, stopped = false, currentMode = 'all';
  const checkControls = document.createElement('div'), checkLink = document.createElement('a'), checkPanel = document.createElement('section');
  checkLink.href = '#twin-energy-check'; checkLink.textContent = 'Why no ribbons?';
  checkPanel.className = 'twin-energy-check'; checkPanel.hidden = true; checkPanel.setAttribute('aria-label', 'Energy check');
  checkLink.setAttribute('aria-expanded', 'false');
  checkLink.addEventListener('click', event => {
    event.preventDefault();
    if (document.getElementById('twin-energy-check') && window.chfOpenSettings) {
      window.chfOpenSettings('twin', 'twin-energy-check'); return;
    }
    checkPanel.hidden = !checkPanel.hidden; checkLink.setAttribute('aria-expanded', String(!checkPanel.hidden));
  });
  checkControls.append(checkLink, checkPanel);
  const layout = live.layout();
  const panels = new Map();
  const resources = new Set();
  const own = value => { resources.add(value); return value; };
  const label = () => {const node = document.createElement('span'); node.hidden = true; labels.append(node); return node;};
  function clear() { root.clear(); labels.replaceChildren(); for (const r of resources) r.dispose(); resources.clear(); ribbons = []; conduits = []; }
  const flowMaterial = (color, glow, surface = false) => own(new THREE.ShaderMaterial({transparent: true, depthTest: surface, depthWrite: false, toneMapped: false,
      blending: glow ? THREE.AdditiveBlending : THREE.NormalBlending,
      uniforms: {color: {value: new THREE.Color(color)}, phase: {value: 0}, radius: {value: .1}, glow: {value: glow ? 1 : 0},
        brightness: {value: 1}, pulseGain: {value: 1}, coreGain: {value: .7}, edgeAlpha: {value: .35}},
      vertexShader: `uniform float radius; uniform float glow; varying vec2 tex; varying vec3 viewNormal; varying vec3 viewRay;
        void main(){tex=uv;vec4 p=modelViewMatrix*vec4(position+normal*(radius*.5*glow),1.0);
          viewNormal=normalMatrix*normal;viewRay=-p.xyz;gl_Position=projectionMatrix*p;}`,
      fragmentShader: `uniform vec3 color; uniform float phase; uniform float glow; uniform float coreGain; uniform float edgeAlpha; uniform float brightness; uniform float pulseGain;
        varying vec2 tex; varying vec3 viewNormal; varying vec3 viewRay;
        void main(){float pulse=pow(max(0.0,cos((tex.x*3.0-phase)*6.2831853)),8.0)*pulseGain;
          float edge=pow(abs(dot(normalize(viewNormal),normalize(viewRay))),2.0);
          vec3 core=color*(coreGain+(1.0-coreGain)*pulse);
          gl_FragColor=vec4(mix(core,color*.7,glow)*brightness,mix(1.0,edgeAlpha*(.5+.5*pulse)*edge*brightness,glow));
          #include <colorspace_fragment>
        }`}));
  function ribbon(id, from, to, color, fan, link = null) {
    const route = flowRoute(from, to), curve = link ? new THREE.LineCurve3(worldPoint(from),worldPoint(to)) : flowCurve(route.from, route.to, fan);
    const geometry = own(new THREE.TubeGeometry(curve, 64, flowReading(0).width / 2, 8, false));
    const centres = new Float32Array(geometry.attributes.position.count * 3);
    for (let ring = 0; ring <= 64; ring++) {
      const p = curve.getPointAt(ring / 64);
      for (let side = 0; side <= 8; side++) p.toArray(centres, (ring * 9 + side) * 3);
    }
    geometry.setAttribute('centerline', new THREE.BufferAttribute(centres, 3));
    const halo = new THREE.Mesh(geometry, flowMaterial(color, true)), mesh = new THREE.Mesh(geometry, flowMaterial(color, false));
    // Overlay all WebGL geometry, including roofs and marker sprites. HTML
    // markers and the collision-separated kW labels remain above the canvas.
    halo.renderOrder = 1000; mesh.renderOrder = 1001;
    halo.frustumCulled = mesh.frustumCulled = false; // The halo expands beyond the core's bounds.
    mesh.userData.energyRibbon = id; halo.userData.energyRibbonHalo = id;
    mesh.visible = halo.visible = false; root.add(halo, mesh);
    const node = label(); node.dataset.energyLabel = id;
    ribbons.push({id, link, mesh, halo, curve, route, hue: new THREE.Color(color).convertLinearToSRGB().toArray(), label: node, point: link?curve.getPoint(.5):flowApex(curve), reading: flowReading(0)});
  }
  function conduit(route) {
    const points = route.points.map(worldPoint), edges = points.length - 1;
    if (!edges) return;
    // Rings land exactly on every bend; an arc-length-only TubeGeometry can
    // skip a short wall/soffit segment and cut through the corner of the house.
    class SurfaceCurve extends THREE.Curve {
      getPoint(t, target = new THREE.Vector3()) {
        const f = Math.min(edges - 1, Math.floor(t * edges)), u = t * edges - f;
        return target.copy(points[f]).lerp(points[f + 1], u);
      }
      getPointAt(t, target) { return this.getPoint(t, target); }
      getTangentAt(t) {
        return this.getPoint(Math.min(1, t + 1e-6)).sub(this.getPoint(Math.max(0, t - 1e-6))).normalize();
      }
    }
    const radius = 1.5 / 12 * FT, segments = edges * 4;
    const geometry = own(new THREE.TubeGeometry(new SurfaceCurve(), segments, radius, 8, false));
    const lengths = [0];
    for (let i = 1; i < points.length; i++) lengths.push(lengths[i - 1] + points[i].distanceTo(points[i - 1]));
    for (let ring = 0; ring <= segments; ring++) {
      const edge = Math.min(edges - 1, Math.floor(ring / 4)), fraction = ring / 4 - edge;
      const u = (lengths[edge] + fraction * (lengths[edge + 1] - lengths[edge])) / lengths.at(-1);
      for (let side = 0; side <= 8; side++) geometry.attributes.uv.setX(ring * 9 + side, u);
    }
    const mesh = new THREE.Mesh(geometry, flowMaterial(CONDUIT_COLOR, false, true));
    const halo = new THREE.Mesh(geometry, flowMaterial(CONDUIT_COLOR, true, true));
    mesh.userData.solarConduit = route.id; halo.userData.solarConduitHalo = route.id;
    for (const object of [halo, mesh]) {
      object.material.uniforms.radius.value = radius; object.visible = false;
      object.frustumCulled = false; root.add(object);
    }
    halo.renderOrder = 998; mesh.renderOrder = 999;
    conduits.push({...route, mesh, halo, reading: flowReading(0)});
  }
  function restorePanels() {
    for (const [material, original] of panels) {
      material.emissive.copy(original.color); material.emissiveIntensity = original.intensity;
    }
  }
  function drawRibbons(anchors) {
    const topology = energyTopology(anchors,mapping), fans = flowFans(topology, flowReading(4000).width);
    for(const row of topology)ribbon(row.id,row.from,row.to,FLOW_COLORS[row.source],fans.get(row.id));
    for(const [i,at] of anchors.chargers.entries())if(at)for(const spot of anchors.parking){
      const from=[at[0],at[1],spot.at[2]],to=[...spot.at];
      ribbon(`link:${i}:${spot.building}:${spot.id}`,from,to,FLOW_COLORS.car,null,{charger:i,spot});
    }
  }
  function rebuild(anchors) {
    const serial = ++rebuildSerial;
    clear(); conduitSolar = null; if (!anchors) return;
    drawRibbons(anchors);
    conduitPending = true;
    conduitTask = conduitRouter.run(view.plan, anchors).then(routes => {
      if (stopped || serial !== rebuildSerial || routes === null) return;
      conduitPending = false;
      if (!routes.length) return;
      // A weighted source centre on opposite slopes can be below the roof:
      // the ribbons start from the same centre lifted onto the main solar roof.
      conduitSolar = routes[0].source || anchors.solar;
      if (JSON.stringify(conduitSolar) !== JSON.stringify(anchors.solar)) {
        clear(); drawRibbons({...anchors, solar: conduitSolar});
      }
      for (const route of routes) conduit(route);
      effects.update(currentMode); warm?.(); view.render?.();
    });
    warm?.();
  }
  const effects = {
    legend:()=>energyPlacementLegend(anchors || energyAnchors(view,layout,mapping),mapping) || 'Yellow: Solar | Green: Battery | Blue: Grid | Purple: Charger | Flow below 50 W hidden',
    legendContent:()=>checkControls,
    warmObjects: () => {const objects = []; root.traverse(o => {objects.push(o);}); return objects;},
    ready: () => conduitTask,
    update(mode) {
      currentMode = mode;
      const states = live.peek(); mapping = guessEnergy(states, view.energySources?.mapping, view.energySources?.cars, view.plan);
      anchors = energyAnchors(view, layout, mapping, states);
      const shown = mode === 'energy' || mode === 'all';
      const total = live.stale() ? 0 : Math.max(0, watts(mapping.solar_power, states) ?? energyBalance(mapping, states, anchors?.zoneEntities).totals.solar ?? 0);
      view.scene.traverse(o => {for (const m of o.material ? [].concat(o.material) : []) if (m.name === 'solar_panel') {
        m.visible = mapping.panels.visible !== false;
        if (!m.emissive) continue;
        if (!panels.has(m)) panels.set(m, {color: m.emissive.clone(), intensity: m.emissiveIntensity});
        if (shown) {m.emissive.set(FLOW_COLORS.solar); m.emissiveIntensity = Math.min(.25, total / 4000 * .25);}
        else {const original = panels.get(m); m.emissive.copy(original.color); m.emissiveIntensity = original.intensity;}
      }});
      // Power, signs, names and panel visibility never rebuild a curve. Only
      // changed anchors, solar surfaces or a newly added source/car changes meshes.
      const {spots,homeCars,...physical}=anchors;
      const next = JSON.stringify([physical, ['solar_power', 'battery_power', 'grid_power', 'house_power'].map(k => !!mapping[k]),
        mapping.chargers.map(c => [c.id, !!c.power]),
        view.plan?.solar_source_building, (view.plan?.buildings || []).map(b =>
          [b.id, b.position, b.rotation, b.base, b.foundation, b.roof, b.solar_zones, b.levels, b.rooms, b.walls]), view.plan?.site?.terraces]);
      if (key !== next) {key = next; rebuild(anchors);}
      if (conduitSolar) anchors.solar = conduitSolar;
      check = energyCheck(view, layout, mapping, states, live.stale(), anchors);
      renderEnergyCheck(checkPanel, check);
      const flows = new Map(check.flows.map(row => [row.id, row]));
      for (const row of conduits) {
        const power = live.stale() ? 0 : Math.max(0, watts(row.entity, states) ?? total);
        row.reading = {...flowReading(power), watts: power};
        row.mesh.visible = row.halo.visible = shown;
        for (const object of [row.mesh, row.halo]) {
          object.material.uniforms.pulseGain.value = row.reading.visible ? 1 : 0;
          object.material.uniforms.brightness.value = row.reading.visible ? 1 : .15;
          if (!row.reading.visible) object.material.uniforms.phase.value = 0;
        }
      }
      for (const row of ribbons) {
        const chargerIndex = row.link?.charger ?? (row.id.startsWith('charger:') ? Number(row.id.split(':')[1]) : null);
        const charger=chargerIndex===null?null:mapping.chargers[chargerIndex];
        const car=charger?chargingCar({...charger,at:anchors.chargers[chargerIndex]},mapping.cars,states,anchors.spots):null;
        const flow = flows.get(row.link?'charger:'+chargerIndex:row.id);
        row.reading = {...flowReading(flow?.watts || 0), watts: flow?.watts || 0};
        if(row.link)row.reading.width=.25*.3048;
        row.halo.visible = row.mesh.visible = (mode === 'energy' || mode === 'all') && (row.link
          ? !live.stale() && row.reading.visible && !!car && anchors.spots.some(s=>s.car===car.id && s.building===row.link.spot.building && s.id===row.link.spot.id)
          : !!flow?.shown);
        row.mesh.material.uniforms.radius.value = row.reading.width / 2;
        row.halo.material.uniforms.radius.value = row.reading.width;
        // Keep the full physical diameter in the mesh itself. Updating the
        // shared buffer preserves its identity and all prewarmed materials.
        if (row.width !== row.reading.width) {
          row.width = row.reading.width;
          const geometry = row.mesh.geometry, position = geometry.attributes.position;
          const centres = geometry.attributes.centerline, normal = geometry.attributes.normal;
          for (let i = 0; i < position.count; i++) position.setXYZ(i,
            centres.getX(i) + normal.getX(i) * row.width / 2,
            centres.getY(i) + normal.getY(i) * row.width / 2,
            centres.getZ(i) + normal.getZ(i) * row.width / 2);
          position.needsUpdate = true; geometry.computeBoundingSphere();
        }
        const names = {house:'home',grid:'grid',battery:'battery',solar:'solar'};
        const title = charger ? `panel to ${charger.name}` : row.id.split(':').map(role=>names[role]).join(' to ');
        row.mesh.userData.flow = {...row.reading}; row.label.textContent = `${title} ${row.reading.label}${charger && !car?' · car unknown':''}`;
      }
    },
    draw(mode) {
      labels.hidden = mode !== 'energy' && mode !== 'all';
      const rect = view.renderer3.domElement.getBoundingClientRect();
      const shown = [], entries = [];
      for (const row of ribbons) {
        row.label.hidden = !!row.link || !row.mesh.visible || mode !== 'energy' && mode !== 'all';
        if (!row.label.hidden) {
          const point = row.point.clone().project(view.camera);
          if (!row.label.hidden) {
            if (row.measuredText !== row.label.textContent) {
              row.measuredText = row.label.textContent;
              const size = row.label.getBoundingClientRect();
              row.labelWidth = size.width || row.label.textContent.length * 7 + 16;
              row.labelHeight = size.height || 24;
            }
            const project = p => ({x:rect.left+(p.x+1)*rect.width/2,y:rect.top+(1-p.y)*rect.height/2});
            const along = row.curve ? [.4,.6,.3,.7,.2,.8,.1,.9].map(t => row.curve.getPoint(t).project(view.camera))
              .filter(p => p.z >= -1 && p.z <= 1).map(project) : [];
            shown.push(row); entries.push({...project(point), along, width: row.labelWidth, height: row.labelHeight});
          }
        }
      }
      flowLabelPositions(entries, rect).forEach((p, i) => {
        const label = shown[i].label; label.dataset.energyLabelPlacement = p.placement;
        label.style.left = `${p.x}px`; label.style.top = `${p.y}px`;
      });
      const seconds = performance.now() / 1000;
      for (const r of conduits) r.halo.material.uniforms.phase.value = r.mesh.material.uniforms.phase.value = r.reading.visible ? seconds * r.reading.speed : 0;
      for (const r of ribbons) r.halo.material.uniforms.phase.value = r.mesh.material.uniforms.phase.value = seconds * r.reading.speed * r.reading.direction;
    },
    snapshot: () => ({mapping, check, anchors, conduitPending, conduits: conduits.map(r => ({id: r.id, entity: r.entity, points: r.points, source: r.source,
      ...r.reading, visible: r.mesh.visible})), ribbons: ribbons.map(r => ({id: r.id, link:!!r.link, ...r.reading, visible: r.mesh.visible,
      apex: r.point.toArray(), labelAnchor: r.point.toArray(), midpoint: r.curve.getPoint(.5).toArray(), from: r.route.from, to: r.route.to, hue: r.hue, path: r.curve.getPoints(15).map(p => p.toArray())})),
      cars: view.cars?.snapshot() || [], plane: anchors?.source || null, legend:energyPlacementLegend(anchors || {},mapping)}),
    stop() { stopped = true; rebuildSerial++; conduitRouter.stop(); restorePanels(); panels.clear(); clear(); root.removeFromParent(); labels.remove(); checkControls.remove(); }
  };
  return effects;
}
export function registerEnergy(registerMode) {
  registerMode({id: 'energy', label: 'Energy', foreground: (row, state) => ['car', 'power', 'energy', 'battery'].includes(row.kind) ||
    /^(w|kw|mw|wh|kwh|mwh)$/i.test(state?.attributes?.unit_of_measurement || '') || isEnergyEntity(row.entity_id || '', state),
    legend: 'Yellow · Solar   |   Green · Battery   |   Blue · Grid / house   |   Purple · Car   |   Flow below 50 W hidden', mount: mountEnergy});
}
