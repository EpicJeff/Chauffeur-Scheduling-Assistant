// A bake has its own, material-independent receiving topology. These providers
// are lazy for the house and prepared with the yard's asynchronous build. They
// never join the drawn scene or add a draw call/material program.
import * as THREE from '../../vendor/three-r187/three.module.js';
import { filterAlphaSource } from './alpha_source.js';
const providers = new WeakMap(), sources = new WeakMap();
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
export function cloneBakeGeometry(root,children=root.children) {
  const group=new THREE.Group();
  for(const child of new Set(children))if(child.parent===root){const copy=child.clone(true);
    copy.traverse(o=>{if(o.geometry)o.geometry=o.geometry.clone();});group.add(copy);}
  return group;
}
export function registerBakeSource(root, make, {extras=true,children=root.children}={}) { providers.set(root, {make,extras,children:new Set(children)}); }
export function bakeSource(root) {
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
    source.add(geometry);
    // Optional receiver meshes added by a caller after generation are part of
    // the bake too (for example a separately generated structural extension).
    for(const child of node.children) if(provider.extras && !provider.children.has(child) && !providers.has(child)) {
      const copy=child.clone(true);copy.traverse(o=>{if(o.geometry)o.geometry=o.geometry.clone();});
      copy.matrixAutoUpdate=false;copy.matrix.copy(child.matrixWorld);source.add(copy);
    }
  }
  source.updateMatrixWorld(true);filterAlphaSource(source,root);sources.set(root, {source,signature});
  return source;
}

export function releaseBakeSource(root) {
  const saved=sources.get(root);if(!saved)return;
  sources.delete(root);
  const retained=new Set();root.traverse(o=>{for(const m of o.material?[].concat(o.material):[])retained.add(m);});
  const materials=new Set(),geometries=new Set();
  saved.source.traverse(o=>{
    if(o.geometry)geometries.add(o.geometry);
    for(const m of o.material?[].concat(o.material):[])if(!retained.has(m))materials.add(m);
  });
  geometries.forEach(g=>g.dispose());materials.forEach(m=>m.dispose());
}
