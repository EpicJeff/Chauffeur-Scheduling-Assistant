import * as THREE from 'three';
import { isEnergyEntity } from './glance.js';
import { guessEnergy, carHome, flowReading } from './energy_mapping.js';
import { energyCheck, renderEnergyCheck } from './energy_check.js';
import { energyTopology, energyPlacementLegend, energyAnchors, worldPoint, flowCurve, flowRoute, flowApex, flowFans } from './energy_geometry.js';

export const FLOW_COLORS = {solar: '#efbd24', battery: '#31ae62', grid: '#338bd9', house: '#57a8da', car: '#9957d2'};

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
  let key = '', mapping = {}, ribbons = [], cars = [], anchors = null, check = null;
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
  const resources = new Set();
  const own = value => { resources.add(value); return value; };
  const label = () => {const node = document.createElement('span'); node.hidden = true; labels.append(node); return node;};
  function clear() { root.clear(); labels.replaceChildren(); for (const r of resources) r.dispose(); resources.clear(); ribbons = []; cars = []; }
  function ribbon(id, from, to, color, fan) {
    const route = flowRoute(from, to), curve = flowCurve(route.from, route.to, fan);
    const geometry = own(new THREE.TubeGeometry(curve, 64, flowReading(0).width / 2, 8, false));
    const centres = new Float32Array(geometry.attributes.position.count * 3);
    for (let ring = 0; ring <= 64; ring++) {
      const p = curve.getPointAt(ring / 64);
      for (let side = 0; side <= 8; side++) p.toArray(centres, (ring * 9 + side) * 3);
    }
    geometry.setAttribute('centerline', new THREE.BufferAttribute(centres, 3));
    const material = glow => own(new THREE.ShaderMaterial({transparent: true, depthTest: false, depthWrite: false, toneMapped: false,
      blending: glow ? THREE.AdditiveBlending : THREE.NormalBlending,
      uniforms: {color: {value: new THREE.Color(color)}, phase: {value: 0}, radius: {value: .1}, glow: {value: glow ? 1 : 0},
        coreGain: {value: .7}, edgeAlpha: {value: .35}},
      vertexShader: `uniform float radius; uniform float glow; varying vec2 tex; varying vec3 viewNormal; varying vec3 viewRay;
        void main(){tex=uv;vec4 p=modelViewMatrix*vec4(position+normal*(radius*.5*glow),1.0);
          viewNormal=normalMatrix*normal;viewRay=-p.xyz;gl_Position=projectionMatrix*p;}`,
      fragmentShader: `uniform vec3 color; uniform float phase; uniform float glow; uniform float coreGain; uniform float edgeAlpha;
        varying vec2 tex; varying vec3 viewNormal; varying vec3 viewRay;
        void main(){float pulse=pow(max(0.0,cos((tex.x*3.0-phase)*6.2831853)),8.0);
          float edge=pow(abs(dot(normalize(viewNormal),normalize(viewRay))),2.0);
          vec3 core=color*(coreGain+(1.0-coreGain)*pulse);
          gl_FragColor=vec4(mix(core,color*.7,glow),mix(1.0,edgeAlpha*(.5+.5*pulse)*edge,glow));
          #include <colorspace_fragment>
        }`}));
    const halo = new THREE.Mesh(geometry, material(true)), mesh = new THREE.Mesh(geometry, material(false));
    // Overlay all WebGL geometry, including roofs and marker sprites. HTML
    // markers and the collision-separated kW labels remain above the canvas.
    halo.renderOrder = 1000; mesh.renderOrder = 1001;
    halo.frustumCulled = mesh.frustumCulled = false; // The halo expands beyond the core's bounds.
    mesh.userData.energyRibbon = id; halo.userData.energyRibbonHalo = id;
    mesh.visible = halo.visible = false; root.add(halo, mesh);
    const node = label(); node.dataset.energyLabel = id;
    ribbons.push({id, mesh, halo, curve, route, hue: new THREE.Color(color).convertLinearToSRGB().toArray(), label: node, point: flowApex(curve), reading: flowReading(0)});
  }
  function rebuild(anchors) {
    clear(); if (!anchors) return;
    const topology = energyTopology(anchors,mapping), fans = flowFans(topology, flowReading(4000).width);
    for(const row of topology)ribbon(row.id,row.from,row.to,FLOW_COLORS[row.source],fans.get(row.id));
    for (const [i, car] of mapping.cars.entries()) {
      if(!anchors.cars[i])continue;
      const body = new THREE.Group(), at = worldPoint(anchors.cars[i]); body.position.copy(at);
      // The existing placed HA marker is the charger; no invented parked car.
      body.userData.energyCar = car.id; root.add(body);
      cars.push({car, index: i, mesh: body, label: label(), point: at.clone().add(new THREE.Vector3(0, 1.3, 0))});
    }
    warm?.();
  }
  const effects = {
    legend:()=>energyPlacementLegend(anchors || energyAnchors(view,layout,mapping),mapping) || 'Yellow: Solar | Green: Battery | Blue: Grid | Purple: Charger | Flow below 50 W hidden',
    legendContent:()=>checkControls,
    warmObjects: () => {const objects = []; root.traverse(o => {objects.push(o);}); return objects;},
    update(mode) {
      const states = live.peek(); mapping = guessEnergy(states, view.energySources?.mapping, view.energySources?.cars);
      view.scene.traverse(o=>{for(const m of o.material?[].concat(o.material):[])if(m.name==='solar_panel')m.visible=mapping.panels.visible!==false;});
      anchors = energyAnchors(view, layout, mapping);
      // Power, signs, names and panel visibility never rebuild a curve. Only
      // changed anchors or a newly added source/car changes meshes.
      const next = JSON.stringify([anchors, ['solar_power', 'battery_power', 'grid_power', 'house_power'].map(k => !!mapping[k]),
        mapping.cars.map(c => [c.id, !!c.charge_power])]);
      if (key !== next) {key = next; rebuild(anchors);}
      check = energyCheck(view, layout, mapping, states, live.stale(), anchors);
      renderEnergyCheck(checkPanel, check);
      const flows = new Map(check.flows.map(row => [row.id, row]));
      for (const row of ribbons) {
        const car = row.id.startsWith('car:') ? mapping.cars[Number(row.id.split(':')[1])] : null;
        const flow = flows.get(row.id);
        row.reading = {...flowReading(flow?.watts || 0), watts: flow?.watts || 0};
        row.halo.visible = row.mesh.visible = mode === 'energy' && !!flow?.shown;
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
        const title = car ? `panel to ${car.name}` : row.id.split(':').map(role=>names[role]).join(' to ');
        row.mesh.userData.flow = {...row.reading}; row.label.textContent = `${title} ${row.reading.label}`;
      }
      for (const row of cars) {
        row.car = mapping.cars[row.index];
        row.mesh.visible = !live.stale() && carHome(row.car, states);
        const level = states[row.car.battery_level]?.state;
        row.label.textContent = `${row.car.name} · ${level != null && level !== '' && Number.isFinite(Number(level)) ? level + '%' : '—'}`;
      }
    },
    draw(mode) {
      labels.hidden = mode !== 'energy';
      const rect = view.renderer3.domElement.getBoundingClientRect();
      const shown = [], entries = [];
      for (const row of [...ribbons, ...cars]) {
        row.label.hidden = !row.mesh.visible || mode !== 'energy';
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
      for (const r of ribbons) r.halo.material.uniforms.phase.value = r.mesh.material.uniforms.phase.value = seconds * r.reading.speed * r.reading.direction;
    },
    snapshot: () => ({mapping, check, anchors: energyAnchors(view, layout, mapping), ribbons: ribbons.map(r => ({id: r.id, ...r.reading, visible: r.mesh.visible,
      apex: r.point.toArray(), labelAnchor: r.point.toArray(), midpoint: r.curve.getPoint(.5).toArray(), from: r.route.from, to: r.route.to, hue: r.hue, path: r.curve.getPoints(15).map(p => p.toArray())})),
      cars: cars.map(r => ({id: r.car.id, visible: r.mesh.visible})), plane: anchors?.source || null, legend:energyPlacementLegend(anchors || {},mapping)}),
    stop() { clear(); root.removeFromParent(); labels.remove(); checkControls.remove(); }
  };
  return effects;
}
export function registerEnergy(registerMode) {
  registerMode({id: 'energy', label: 'Energy', foreground: (row, state) => ['car', 'power', 'energy', 'battery'].includes(row.kind) ||
    /^(w|kw|mw|wh|kwh|mwh)$/i.test(state?.attributes?.unit_of_measurement || '') || isEnergyEntity(row.entity_id || '', state),
    legend: 'Yellow · Solar   |   Green · Battery   |   Blue · Grid / house   |   Purple · Car   |   Flow below 50 W hidden', mount: mountEnergy});
}
