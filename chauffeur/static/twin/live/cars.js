import { twinAttention } from '../palette.js';
import * as THREE from 'three';
import { LUCIDE } from '../../vendor/lucide/icons.js';
import { markerSprite } from './markers.js';
import { guessEnergy, carHome, carCharging, chargingCar, watts } from './energy_mapping.js';
import { energyAnchors, worldPoint } from './energy_geometry.js';

export function carTexture(color, ring = '') {
  color = /^#[\da-f]{6}$/i.test(color || '') ? color : '#64748b';
  const rgb = [1,3,5].map(i=>parseInt(color.slice(i,i+2),16)/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4);
  const luminance=rgb[0]*.2126+rgb[1]*.7152+rgb[2]*.0722;
  const ink=luminance>.179?'#000000':'#ffffff';
  const canvas=document.createElement('canvas');canvas.width=canvas.height=96;
  const ctx=canvas.getContext('2d');
  ctx.fillStyle=color;ctx.beginPath();ctx.arc(48,48,42,0,Math.PI*2);ctx.fill();
  ctx.strokeStyle=ring || ink;ctx.lineWidth=ring?5:2;ctx.stroke();
  ctx.save();ctx.translate(19,19);ctx.scale(58/24,58/24);
  ctx.strokeStyle=ink;ctx.lineWidth=1.75;ctx.lineCap='round';ctx.lineJoin='round';
  for(const [tag,a] of LUCIDE.car){
    if(tag==='path' && typeof Path2D==='function')ctx.stroke(new Path2D(a.d));
    if(tag==='circle'){ctx.beginPath();ctx.arc(Number(a.cx),Number(a.cy),Number(a.r),0,Math.PI*2);ctx.stroke();}
  }
  ctx.restore();
  const texture=new THREE.CanvasTexture(canvas);texture.colorSpace=THREE.SRGBColorSpace;
  return texture;
}
const numeric = row => row?.state != null && String(row.state).trim()!=='' && Number.isFinite(Number(row.state))?Number(row.state):null;

// Mounted once by the live keeper, including a house with no HA. The live
// state is read at draw time, so pushes and layer recovery use the same path.
export function mountCars({view, live = () => view.live}) {
  const root=new THREE.Group();root.userData.twinCars=true;view.scene.add(root);
  const labels=document.createElement('div');labels.className='twin-car-labels';document.body.append(labels);
  const sheet=document.createElement('aside');sheet.className='twin-car-sheet';sheet.hidden=true;sheet.setAttribute('role','dialog');document.body.append(sheet);
  const events=new AbortController(),textures=new Map(),rows=new Map();let selected=null,stopped=false;
  let dirty=true,lastLive=null,lastPlan=null,lastSources=null,unsubscribe=null;
  const texture=(color,ring)=>{const key=JSON.stringify([color,ring]);if(!textures.has(key))textures.set(key,carTexture(color,ring));return textures.get(key);};
  let cardKey='';
  const close=()=>{selected=null;cardKey='';sheet.hidden=true;sheet.replaceChildren();};
  function card(row){
    if(!row?.sprite.visible){close();return;}
    selected=row.car.id;
    const next=JSON.stringify([selected,row.car.name,row.battery,row.range,row.rangeUnit,row.charging,row.power,row.charger?.name]);
    if(cardKey===next)return;cardKey=next;
    sheet.hidden=false;sheet.setAttribute('aria-label',row.car.name);sheet.dataset.carCard=row.car.id;sheet.replaceChildren();
    const title=document.createElement('h2');title.textContent=row.car.name;sheet.append(title);
    for(const text of [`Battery: ${row.battery===null?'—':row.battery+'%'}`,
      ...(!row.car.range_entity?[]:[`Range: ${row.range===null?'—':row.range+' '+row.rangeUnit}`]),
      row.charging?`Charging${row.power===null?'':` · ⚡ ${Number((row.power/1000).toFixed(2))} kW`}`:'Not charging',
      `Charger: ${row.charger?.name || (row.charging?'unknown':'—')}`]){
      const p=document.createElement('p');p.textContent=text;sheet.append(p);
    }
    const button=document.createElement('button');button.type='button';button.textContent='Close';button.addEventListener('click',close);sheet.append(button);
  }
  document.addEventListener('keydown',e=>{if(e.key==='Escape')close();},{signal:events.signal});
  function update(current){
    const states=current?.peek() || {};
    const mapping=guessEnergy(states,view.energySources?.mapping,view.energySources?.cars,view.plan);
    const anchors=energyAnchors(view,current?.layout?.(),mapping,states),present=new Set();let added=false;
    for(const car of mapping.cars){
      present.add(car.id);let row=rows.get(car.id);
      if(!row){
        const sprite=markerSprite(texture(car.color,''));sprite.userData.twinCar=car.id;root.add(sprite);
        const button=document.createElement('button');button.type='button';button.dataset.carIcon=car.id;
        Object.assign(button.style,{position:'fixed',width:'44px',height:'44px',padding:'0',border:'0',background:'transparent',pointerEvents:'auto',transform:'translate(-50%, -50%)'});
        const label=document.createElement('span');label.dataset.carLabel=car.id;labels.append(button,label);
        row={sprite,button,label};rows.set(car.id,row);
        added=true;
        button.addEventListener('click',event=>{event.stopPropagation();card(row);},{signal:events.signal});
      }
      row.car=car;
      const spot=anchors.spots.find(s=>s.car===car.id);
      row.sprite.visible=!!spot && carHome(car,states) && !current?.stale();
      row.button.hidden=row.label.hidden=!row.sprite.visible;
      if(!row.sprite.visible)continue;
      row.charger=mapping.chargers.find((c,i)=>watts(c.power,states)>=50 && chargingCar({...c,at:anchors.chargers[i]},mapping.cars,states,anchors.spots)?.id===car.id);
      row.charging=carCharging(car,states) || !!row.charger || watts(car.charge_power,states)>=50;
      row.power=row.charger?watts(row.charger.power,states):watts(car.charge_power,states);
      row.battery=numeric(states[car.battery_level]);row.range=numeric(states[car.range_entity]);row.rangeUnit=states[car.range_entity]?.attributes?.unit_of_measurement || '';
      const ring=row.charging?'#9957d2':row.battery!==null && car.battery_warn_pct!=null && row.battery<car.battery_warn_pct?twinAttention:'';
      row.sprite.material.map=texture(car.color,ring);
      row.sprite.position.copy(worldPoint([spot.at[0],spot.at[1],spot.at[2]+4]));
      row.button.setAttribute('aria-label',car.name);
      row.label.textContent=`${car.name} · ${row.battery===null?'—':row.battery+'%'}${row.charging && row.power!==null?` · ⚡ ${Number((row.power/1000).toFixed(2))} kW`:''}`;
    }
    for(const [id,row] of rows)if(!present.has(id)){row.sprite.removeFromParent();row.sprite.material.dispose();row.button.remove();row.label.remove();rows.delete(id);}
    if(added && typeof view.renderer3.compileAsync==='function'){
      const shown=[...rows.values()].map(r=>[r.sprite,r.sprite.visible]);
      try{shown.forEach(([sprite])=>{sprite.visible=true;});view.renderer3.compileAsync(view.scene,view.camera).catch(()=>{});}
      catch { /* Reuse the renderer's normal first draw if warm-up fails. */ }
      finally{shown.forEach(([sprite,visible])=>{sprite.visible=visible;});}
    }
  }
  function draw(){
    if(stopped)return;
    const current=typeof live==='function'?live():live;
    if(current!==lastLive){unsubscribe?.();lastLive=current;unsubscribe=current?.subscribe?.(()=>{dirty=true;});dirty=true;}
    if(lastPlan!==view.plan || lastSources!==view.energySources){lastPlan=view.plan;lastSources=view.energySources;dirty=true;}
    if(dirty){dirty=false;update(current);}
    const rect=view.renderer3.domElement.getBoundingClientRect(),camera=view.camera;camera.updateMatrixWorld(true);
    for(const row of rows.values()){
      row.button.hidden=row.label.hidden=!row.sprite.visible;
      if(!row.sprite.visible)continue;
      const depth=-row.sprite.position.clone().applyMatrix4(camera.matrixWorldInverse).z;
      const size=camera.isOrthographicCamera?(camera.top-camera.bottom)/camera.zoom/Math.max(1,rect.height):2*Math.max(.1,depth)*Math.tan(camera.fov*Math.PI/360)/camera.zoom/Math.max(1,rect.height);
      row.sprite.scale.setScalar(size*44);
      const p=row.sprite.position.clone().project(camera),x=rect.left+(p.x+1)*rect.width/2,y=rect.top+(1-p.y)*rect.height/2;
      row.button.hidden=row.label.hidden=p.z < -1 || p.z > 1;
      row.button.style.left=`${x}px`;row.button.style.top=`${y}px`;
      row.label.style.left=`${x}px`;row.label.style.top=`${y+36}px`;
    }
    if(selected)card(rows.get(selected));
  }
  return {draw,update(){dirty=true;draw();},snapshot:()=>[...rows.values()].map(r=>({id:r.car.id,color:r.car.color,visible:r.sprite.visible,charging:r.charging,at:r.sprite.position.toArray(),label:r.label.textContent})),
    stop(){stopped=true;unsubscribe?.();events.abort();close();for(const r of rows.values())r.sprite.material.dispose();textures.forEach(t=>t.dispose());root.removeFromParent();labels.remove();sheet.remove();}};
}
