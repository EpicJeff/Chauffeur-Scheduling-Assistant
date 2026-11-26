// A bake has its own, material-independent receiving topology. These providers
// are lazy for the house and prepared with the yard's asynchronous build. They
// never join the drawn scene or add a draw call/material program.
import * as THREE from '../../vendor/three-r187/three.module.js';
import { filterAlphaSource } from './alpha_source.js';
// The building's neutral material build uses the desk's existing defaults.
// Yard terrain keeps its viewer tier; only pool receiving batches are canonical.
export const BAKE_SOURCE_TIER = 'high';
const providers = new WeakMap(), sources = new WeakMap(), madeRoots = new WeakSet();
// Meshes can move intact between provider roots during building reuse.
const authoredByMesh = new WeakMap();
// A drawn provider root and the neutral root it made are the same place. Receiver
// matching names meshes relative to it (bindings.js domain), never by the drawn
// parents above it: the yard is drawn under the twin's 'site' group, while its
// neutral copy sits directly in the bake source.
export const isBakeRoot = node => providers.has(node) || madeRoots.has(node);
// The editor binds physical finishes against a detached, viewer-shaped house.
// Its focused/cut/selected scene is presentation, not a physical material input.
export function bakeReceiverRoots(root) {
  const receiverRoots = providers.get(root)?.receiverRoots;
  if (!receiverRoots) return [root];
  const roots = receiverRoots();
  for (const node of roots) { if (node !== root) madeRoots.add(node); node.updateMatrixWorld(true); }
  return roots;
}
// The neutral receiving topology deliberately has no kit models. The editor
// supplies its separate physical build, only after its imports have settled.
export const bakeModelRoot = root => providers.get(root)?.modelRoot?.() || null;
export const prepareBakeModels = async root => { await providers.get(root)?.modelReady?.(); };
// Default kit finishes already have the neutral topology. Reuse their buffers
// through detached clones instead of generating a second house on a cold bake.
export function defaultBuildingFinishes(plan,kit) {
  const sameDefaults=refs=>Object.entries(refs||{}).every(([role,ref])=>!ref?.id ||
    (kit.materials?.[ref.id]?.id||kit.materials?.[ref.id]?.asset||ref.id)===(kit.materials?.[role]?.id||kit.materials?.[role]?.asset||role));
  const populated=v=>v&&typeof v==='object'?Object.values(v).some(populated):!!v;
  const hasSlots=v=>Array.isArray(v)?v.some(hasSlots):v&&typeof v==='object'&&Object.entries(v).some(([k,x])=>
    (['materials','material','plane_materials','floor_material','ceiling_material','wall_material','faces'].includes(k)&&populated(x))||hasSlots(x));
  return sameDefaults(plan.materials)&&(plan.buildings||[]).every(b=>{
    const {materials,...geometry}=b;return sameDefaults(materials)&&!hasSlots(geometry);
  });
}
// Another provider inside the clone (the yard under the house's 'site' group) is
// left out: it brings its own neutral copy, and a second copy of its drawn meshes
// would chart the same surfaces twice.
function cloneWithoutProviders(node) {
  const copy=node.clone(false);if(copy.geometry)copy.geometry=copy.geometry.clone();
  for(const child of node.children)if(!providers.has(child))copy.add(cloneWithoutProviders(child));
  return copy;
}
export function cloneBakeGeometry(root,children=root.children) {
  const group=new THREE.Group();
  for(const child of new Set(children))if(child.parent===root && !providers.has(child))group.add(cloneWithoutProviders(child));
  return group;
}
export function captureBakeMaterials(root) {
  root.traverse(mesh => {
    if (mesh.isMesh && mesh.material && !authoredByMesh.has(mesh)) authoredByMesh.set(mesh, mesh.material);
  });
}
export function bakeAuthoredMaterial(root, mesh) { return authoredByMesh.get(mesh); }
export function registerBakeSource(root, make, {extras=true,children=root.children,receiverRoots=null,alphaRoots=null,modelRoot=null,modelReady=null,dispose=null}={}) {
  // Classify only captured model materials. Re-registering a provider after a
  // deform must never adopt selection, focus, faint or Unlit presentation.
  const alphaClasses = new WeakMap();
  root.traverse(mesh => {
    const m = authoredByMesh.get(mesh);
    if (!mesh.isMesh || !m || Array.isArray(m)) return;
    const mode = m.userData.alphaMode;
    alphaClasses.set(mesh, mode ? mode !== 'opaque' : !!(m.name === 'glass' || m.alphaTest > 0 || m.transparent && !m.userData.viewingOpaque));
  });
  providers.set(root, {make,extras,receiverRoots,alphaRoots,modelRoot,modelReady,dispose,alphaClasses,children:new Set(children)});
}
// Editor presentation may partition a batch into several material groups.
// Baking always sees the captured authored material and original group layout.
// This is synchronous: the displayed presentation is restored before returning.
export function withAuthoredMaterials(root, run) {
  const saved = new Map();
  root.traverse(mesh => {
    const material = authoredByMesh.get(mesh);
    if (!material || material === mesh.material) return;
    saved.set(mesh, mesh.material);
    mesh.dispatchEvent({ type: 'bakepresentationstart' });
    mesh.material = material;
  });
  try { return run(); }
  finally {
    for (const [mesh, material] of saved) {
      mesh.material = material;
      mesh.dispatchEvent({ type: 'bakepresentationend' });
    }
  }
}

export function bakeSource(root) {
  return withAuthoredMaterials(root, () => makeBakeSource(root));
}
function makeBakeSource(root) {
  const entries = [];
  root.updateMatrixWorld(true);
  root.traverse(node => { if (providers.has(node)) entries.push(node); });
  if (!entries.length) return root;
  const signature=entries.flatMap(node=>[node,...node.children.filter(child=>providers.get(node).extras && !providers.get(node).children.has(child) && !providers.has(child))]);
  const saved=sources.get(root);
  if(saved && saved.signature.length===signature.length && signature.every((node,i)=>saved.signature[i]===node))return saved.source;
  const source = new THREE.Group();
  for (const node of entries) {
    const provider=providers.get(node),geometry = provider.make();
    geometry.matrixAutoUpdate = false; geometry.matrix.copy(node.matrixWorld);
    madeRoots.add(geometry); source.add(geometry);
    // Optional receiver meshes added by a caller after generation are part of
    // the bake too (for example a separately generated structural extension).
    for(const child of node.children) if(provider.extras && !provider.children.has(child) && !providers.has(child)) {
      const copy=child.clone(true);copy.traverse(o=>{if(o.geometry)o.geometry=o.geometry.clone();});
      copy.matrixAutoUpdate=false;copy.matrix.copy(child.matrixWorld);source.add(copy);
    }
  }
  source.updateMatrixWorld(true);
  const authored = providers.get(root)?.alphaRoots;
  for (const receivers of authored?.() || bakeReceiverRoots(root))
    filterAlphaSource(source, receivers, authored ? providers.get(receivers)?.alphaClasses : null);
  sources.set(root, {source,signature});
  return source;
}

export function releaseBakeSource(root) {
  const saved=sources.get(root);
  if(!saved) { providers.get(root)?.dispose?.(); return; }
  sources.delete(root);
  const retained=new Set();root.traverse(o=>{for(const m of o.material?[].concat(o.material):[])retained.add(m);});
  const materials=new Set(),geometries=new Set();
  saved.source.traverse(o=>{
    if(o.geometry)geometries.add(o.geometry);
    for(const m of o.material?[].concat(o.material):[])if(!retained.has(m))materials.add(m);
  });
  geometries.forEach(g=>g.dispose());materials.forEach(m=>m.dispose());
  providers.get(root)?.dispose?.();
}
