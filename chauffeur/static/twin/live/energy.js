import * as THREE from 'three';
import { isEnergyEntity } from './glance.js';
import { guessEnergy, energyFlows, carHome, flowReading } from './energy_mapping.js';
import { energyTopology, energyPlacementLegend, energyAnchors, worldPoint, roofPoints, flowCurve, flowRoute } from './energy_geometry.js';

export const FLOW_COLORS = {solar: '#efbd24', battery: '#31ae62', grid: '#338bd9', house: '#57a8da', car: '#9957d2'};

// Roof-only depth: trees never enter this small pass. Cache it while the camera
// is still; the ribbons fade behind nearer roofs without changing main materials.
export function createRoofFade(view) {
  const renderer = view.renderer3, scene = new THREE.Scene();
  const target = new THREE.WebGLRenderTarget(1, 1, {minFilter: THREE.NearestFilter, magFilter: THREE.NearestFilter});
  const material = new THREE.MeshDepthMaterial({depthPacking: THREE.RGBADepthPacking, side: THREE.DoubleSide});
  const mesh = new THREE.Mesh(new THREE.BufferGeometry(), material); mesh.frustumCulled = false; scene.add(mesh);
  const uniforms = {roofDepth: {value: target.texture}, screenSize: {value: new THREE.Vector2(1, 1)},
    cameraRange: {value: new THREE.Vector2(.1, 1000)}, orthographic: {value: 0}, roofFadeEnabled: {value: 0}};
  let key = '', revision = 0, count = 0;
  return {uniforms,
    setPoints(points) {
      mesh.geometry.dispose(); mesh.geometry = new THREE.BufferGeometry();
      mesh.geometry.setAttribute('position', new THREE.Float32BufferAttribute(points.flatMap(p => p.toArray()), 3));
      count = points.length; revision++;
    },
    warm() {
      if (!count || typeof renderer?.compileAsync !== 'function') return;
      const previous = renderer.getRenderTarget?.();
      try {
        // Offscreen output colour space is part of three's program key too.
        renderer.setRenderTarget?.(target);
        renderer.compileAsync(scene, view.camera).catch(() => {});
      } catch { /* Same fallback as modes warm(). */ }
      finally {renderer.setRenderTarget?.(previous || null);}
    },
    draw(active) {
      const capable = renderer && typeof renderer.getRenderTarget === 'function';
      uniforms.roofFadeEnabled.value = active && count && capable && view.groups.roof?.visible !== false ? 1 : 0;
      if (!uniforms.roofFadeEnabled.value) return;
      const camera = view.camera; camera.updateMatrixWorld(true);
      const size = renderer.getDrawingBufferSize(new THREE.Vector2());
      uniforms.screenSize.value.copy(size); uniforms.cameraRange.value.set(camera.near, camera.far);
      uniforms.orthographic.value = camera.isOrthographicCamera ? 1 : 0;
      const next = [revision, size.x, size.y, ...camera.matrixWorld.elements, ...camera.projectionMatrix.elements].join('|');
      if (next === key) return;
      // Half-resolution depth is sufficient for a soft edge, one merged roof draw.
      target.setSize(Math.max(1, Math.ceil(size.x / 2)), Math.max(1, Math.ceil(size.y / 2)));
      const previous = renderer.getRenderTarget(), color = renderer.getClearColor(new THREE.Color()).clone(), alpha = renderer.getClearAlpha(), autoClear = renderer.autoClear;
      try {renderer.autoClear = true; renderer.setRenderTarget(target); renderer.setClearColor(0xffffff, 1); renderer.render(scene, camera); key = next;}
      finally {renderer.setRenderTarget(previous); renderer.setClearColor(color, alpha); renderer.autoClear = autoClear;}
    },
    stop() {mesh.geometry.dispose(); material.dispose(); target.dispose();}
  };
}

// Labels remain anchored to their own crest, with collision offsets in CSS px.
export function flowLabelPositions(entries, rect) {
  const placed = [];
  for (const entry of entries) {
    let box;
    for (let attempt = 0; attempt < 200; attempt++) {
      const column = attempt % 3 - 1, row = Math.floor(attempt / 3);
      const x = Math.max(rect.left + entry.width / 2, Math.min(rect.right - entry.width / 2,
        entry.x + (attempt ? column * (entry.width + 12) : 0)));
      const y = entry.y - 18 - row * 30;
      box = {x, y, left: x - entry.width / 2, right: x + entry.width / 2, top: y - 12, bottom: y + 12};
      if (!placed.some(p => box.left < p.right + 6 && box.right + 6 > p.left && box.top < p.bottom + 4 && box.bottom + 4 > p.top)) break;
    }
    placed.push(box);
  }
  return placed;
}

export function mountEnergy({view, live, warm, overlays = view.scene}) {
  const root = new THREE.Group(); root.userData.twinMode = 'energy'; overlays.add(root);
  const labels = document.createElement('div'); labels.className = 'twin-mode-labels twin-energy-labels'; document.body.append(labels);
  let key = '', mapping = {}, ribbons = [], cars = [], anchors = null;
  const layout = live.layout();
  const roofFade = createRoofFade(view);
  let source = null, plan = null, highestRoof = 0, roofRevision = 0;
  const resources = new Set();
  const own = value => { resources.add(value); return value; };
  const label = () => {const node = document.createElement('span'); node.hidden = true; labels.append(node); return node;};
  function clear() { root.clear(); labels.replaceChildren(); for (const r of resources) r.dispose(); resources.clear(); ribbons = []; cars = []; }
  function ribbon(id, from, to, color) {
    const route = flowRoute(from, to), curve = flowCurve(route.from, route.to, highestRoof);
    const geometry = own(new THREE.TubeGeometry(curve, 64, 1, 8, false));
    const material = glow => own(new THREE.ShaderMaterial({transparent: true, depthTest: false, depthWrite: false, toneMapped: false,
      blending: glow ? THREE.AdditiveBlending : THREE.NormalBlending,
      uniforms: {...roofFade.uniforms, color: {value: new THREE.Color(color)}, phase: {value: 0}, radius: {value: .1}, glow: {value: glow ? 1 : 0},
        coreGain: {value: .7}, edgeAlpha: {value: .35}},
      vertexShader: `uniform float radius; varying vec2 tex; varying vec3 viewNormal; varying vec3 viewRay;
        void main(){tex=uv;vec4 p=modelViewMatrix*vec4(position+normal*(radius-1.0),1.0);
          viewNormal=normalMatrix*normal;viewRay=-p.xyz;gl_Position=projectionMatrix*p;}`,
      fragmentShader: `#include <packing>
        uniform vec3 color; uniform float phase; uniform float glow; uniform float coreGain; uniform float edgeAlpha;
        uniform sampler2D roofDepth; uniform vec2 screenSize; uniform vec2 cameraRange; uniform float orthographic; uniform float roofFadeEnabled;
        varying vec2 tex; varying vec3 viewNormal; varying vec3 viewRay;
        void main(){float pulse=pow(max(0.0,cos((tex.x*3.0-phase)*6.2831853)),8.0);
          float edge=pow(abs(dot(normalize(viewNormal),normalize(viewRay))),2.0);
          vec3 core=color*(coreGain+(1.0-coreGain)*pulse);
          float visibility=1.0;
          if(roofFadeEnabled>0.5){float depth=unpackRGBAToDepth(texture2D(roofDepth,gl_FragCoord.xy/screenSize));
            float roofZ=mix(perspectiveDepthToViewZ(depth,cameraRange.x,cameraRange.y),orthographicDepthToViewZ(depth,cameraRange.x,cameraRange.y),orthographic);
            visibility=smoothstep(-0.04572,0.04572,-roofZ-viewRay.z);}
          gl_FragColor=vec4(mix(core,color*.7,glow),mix(1.0,edgeAlpha*(.5+.5*pulse)*edge,glow)*visibility);
          #include <colorspace_fragment>
        }`}));
    const halo = new THREE.Mesh(geometry, material(true)), mesh = new THREE.Mesh(geometry, material(false));
    halo.renderOrder = 30; mesh.renderOrder = 31; // Above foliage, below the DOM labels.
    halo.frustumCulled = mesh.frustumCulled = false; // Shader contracts the unit-radius geometry.
    mesh.userData.energyRibbon = id; halo.userData.energyRibbonHalo = id;
    mesh.visible = halo.visible = false; root.add(halo, mesh);
    ribbons.push({id, mesh, halo, curve, route, hue: new THREE.Color(color).convertLinearToSRGB().toArray(), label: label(), point: curve.getPoint(.5), reading: flowReading(0)});
  }
  function rebuild(anchors) {
    clear(); if (!anchors) return;
    for(const row of energyTopology(anchors,mapping))ribbon(row.id,row.from,row.to,FLOW_COLORS[row.source]);
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
    warm: () => roofFade.warm(),
    warmObjects: () => {const objects = []; root.traverse(o => {objects.push(o);}); return objects;},
    update(mode) {
      const states = live.peek(); mapping = guessEnergy(states, view.energySources?.mapping, view.energySources?.cars);
      if (source !== view.roofSurfaces || plan !== view.plan) {
        source = view.roofSurfaces; plan = view.plan;
        const points = roofPoints(source, plan); highestRoof = Math.max(0, ...points.map(p => p.y)); roofFade.setPoints(points);
        roofRevision++;
      }
      view.scene.traverse(o=>{for(const m of o.material?[].concat(o.material):[])if(m.name==='solar_panel')m.visible=mapping.panels.visible!==false;});
      anchors = energyAnchors(view, layout, mapping);
      // Power, signs, names and panel visibility never rebuild a curve. Only
      // changed anchors/roof geometry or a newly added source/car changes meshes.
      const next = JSON.stringify([anchors, roofRevision, ['solar_power', 'battery_power', 'grid_power', 'house_power'].map(k => !!mapping[k]),
        mapping.cars.map(c => [c.id, !!c.charge_power])]);
      if (key !== next) {key = next; rebuild(anchors);}
      const flows = live.stale() ? {} : energyFlows(mapping, states, anchors.zoneEntities);
      for (const row of ribbons) {
        const car = row.id.startsWith('car:') ? mapping.cars[Number(row.id.split(':')[1])] : null;
        row.reading = {...flowReading(flows[row.id] || 0), watts: flows[row.id] || 0};
        row.halo.visible = row.mesh.visible = mode === 'energy' && row.reading.visible && (!car || carHome(car, states));
        row.mesh.material.uniforms.radius.value = row.reading.width / 2;
        row.halo.material.uniforms.radius.value = row.reading.width;
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
      roofFade.draw(mode === 'energy' && ribbons.some(r => r.mesh.visible));
      const rect = view.renderer3.domElement.getBoundingClientRect();
      const shown = [], entries = [];
      for (const row of [...ribbons, ...cars]) {
        row.label.hidden = !row.mesh.visible || mode !== 'energy';
        if (!row.label.hidden) {
          const point = row.point.clone().project(view.camera); row.label.hidden = point.z < -1 || point.z > 1;
          if (!row.label.hidden) {
            if (row.measuredText !== row.label.textContent) {
              row.measuredText = row.label.textContent;
              row.labelWidth = row.label.getBoundingClientRect().width || row.label.textContent.length * 7 + 16;
            }
            shown.push(row); entries.push({x: rect.left + (point.x + 1) * rect.width / 2, y: rect.top + (1 - point.y) * rect.height / 2,
              width: row.labelWidth});
          }
        }
      }
      flowLabelPositions(entries, rect).forEach((p, i) => {shown[i].label.style.left = `${p.x}px`; shown[i].label.style.top = `${p.y}px`;});
      const seconds = performance.now() / 1000;
      for (const r of ribbons) r.halo.material.uniforms.phase.value = r.mesh.material.uniforms.phase.value = seconds * r.reading.speed * r.reading.direction;
    },
    snapshot: () => ({mapping, anchors: energyAnchors(view, layout, mapping), ribbons: ribbons.map(r => ({id: r.id, ...r.reading, visible: r.mesh.visible,
      midpoint: r.point.toArray(), from: r.route.from, to: r.route.to, hue: r.hue, path: r.curve.getPoints(15).map(p => p.toArray())})),
      cars: cars.map(r => ({id: r.car.id, visible: r.mesh.visible})), plane: anchors?.source || null, legend:energyPlacementLegend(anchors || {},mapping)}),
    stop() { clear(); roofFade.stop(); root.removeFromParent(); labels.remove(); }
  };
  return effects;
}
export function registerEnergy(registerMode) {
  registerMode({id: 'energy', label: 'Energy', foreground: (row, state) => ['car', 'power', 'energy', 'battery'].includes(row.kind) ||
    /^(w|kw|mw|wh|kwh|mwh)$/i.test(state?.attributes?.unit_of_measurement || '') || isEnergyEntity(row.entity_id || '', state),
    legend: 'Yellow · Solar   |   Green · Battery   |   Blue · Grid / house   |   Purple · Car   |   Flow below 50 W hidden', mount: mountEnergy});
}
