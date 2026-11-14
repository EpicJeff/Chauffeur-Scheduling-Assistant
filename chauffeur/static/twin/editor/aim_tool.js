import * as THREE from 'three';

const FT = .3048;
const point = p => new THREE.Vector3(p[0] * FT, p[2] * FT, -p[1] * FT);

export function conePreview(at, aim, cone_deg = 90) {
  const root = new THREE.Group(), origin = point(at), end = point(aim), axis = end.clone().sub(origin);
  const length = axis.length(); axis.normalize();
  const u = new THREE.Vector3().crossVectors(axis, Math.abs(axis.y) < .95 ? new THREE.Vector3(0, 1, 0) : new THREE.Vector3(1, 0, 0)).normalize();
  const v = new THREE.Vector3().crossVectors(axis, u), radius = length * Math.tan(cone_deg * Math.PI / 360), vertices = [];
  const ring = Array.from({ length: 32 }, (_, i) => end.clone().addScaledVector(u, radius * Math.cos(i * Math.PI / 16)).addScaledVector(v, radius * Math.sin(i * Math.PI / 16)));
  for (let i = 0; i < ring.length; i++) {
    vertices.push(...ring[i].toArray(), ...ring[(i + 1) % ring.length].toArray());
    if (i % 8 === 0) vertices.push(...origin.toArray(), ...ring[i].toArray());
  }
  const line = new THREE.LineSegments(new THREE.BufferGeometry().setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3)),
    new THREE.LineBasicMaterial({ color: '#9abfe5', transparent: true, opacity: .65, depthTest: false, toneMapped: false }));
  line.renderOrder = 20; root.add(line); return root;
}
const dispose = root => { root.traverse(o => { o.geometry?.dispose(); o.material?.dispose(); }); root.removeFromParent(); };

export function aimTool({ at, aim, cone_deg = 90, onCommit }) {
  const preview = new THREE.Group();
  let current = { aim: [...aim], cone_deg }, saved = structuredClone(current), dragging = false, stopped = false;
  function draw() {
    for (const child of [...preview.children]) dispose(child);
    preview.add(conePreview(at, current.aim, current.cone_deg));
    const target = new THREE.Mesh(new THREE.SphereGeometry(.2, 12, 8), new THREE.MeshBasicMaterial({ color: '#9abfe5', depthTest: false, toneMapped: false }));
    target.position.copy(point(current.aim)); target.userData.aimHandle = true; target.renderOrder = 21; preview.add(target);
  }
  function restore() { current = structuredClone(saved); draw(); }
  async function commit() {
    if (stopped || JSON.stringify(current) === JSON.stringify(saved)) return;
    const next = structuredClone(current);
    try { await onCommit(next); saved = next; } catch (error) { restore(); throw error; }
  }
  draw();
  return { preview, begin() { if (!stopped) dragging = true; },
    move(value) { if (dragging && !stopped && value?.every(Number.isFinite) && Math.hypot(...value.map((v, i) => v - at[i])) > 1e-8) { current.aim = [...value]; draw(); } },
    cone(value) { if (!stopped && Number.isFinite(value) && value >= 10 && value <= 160) { current.cone_deg = value; draw(); } },
    async end(cancel = false) { if (!dragging) return; dragging = false; if (cancel) restore(); else await commit(); },
    commit, stop() { stopped = true; dragging = false; dispose(preview); } };
}
