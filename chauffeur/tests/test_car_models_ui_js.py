"""Execute the actual Drive form and Energy drawer model assignment paths.

Run from chauffeur/: python tests/test_car_models_ui_js.py
No browser, source-string assertions, application data or persistent scratch.
"""
import sys

from twin_live_node_rig import run


DRIVER = r"""
window.chfBase='/ingress/';
const alerts=[];globalThis.showGlobalAlert=message=>alerts.push(message);
// Execute the template's real script, substituting its two server settings.
const template=readFileSync(root+'/templates/components/drive_setup_panel.html','utf8');
const script=template.split('<script>')[1].split('</script>')[0].replace(/{{[\s\S]*?}}/g,'false');
const driveSetup=new Function(script+';return driveSetup;')();
const checks=[],check=(name,fn)=>checks.push([name,fn]);
function form(){const state=driveSetup();state.$nextTick=fn=>fn();state.loadCarModels=async()=>{};state.loadCars=async()=>{};return state;}
const car={id:'ev',doc_id:4,name:'Family EV',allowed_driver_ids:['mum'],twin_model:'import-car',seat_capacity:6,ha_fuel_entity:'sensor.fuel'};
check('editing and saving round-trips the assigned model and neighbouring car fields',async()=>{
 const state=form();state.editCar(car);assert.equal(state.newCar.twin_model,'import-car');assert.equal(state.editCarId,4);
 let sent;globalThis.fetch=async(url,init)=>{sent={url,method:init.method,payload:JSON.parse(init.body)};return {ok:true};};
 await state.submitCar();assert.equal(sent.url,'/ingress/api/cars/4');assert.equal(sent.method,'PUT');
 assert.equal(sent.payload.twin_model,'import-car');assert.equal(sent.payload.seat_capacity,6);assert.equal(sent.payload.ha_fuel_entity,'sensor.fuel');
 assert.deepEqual(sent.payload.allowed_driver_ids,['mum']);assert.equal(state.newCar.twin_model,'');assert.equal(state.showCarForm,false);
});
check('None clears the assignment, and new and cancelled forms reset it',async()=>{
 const state=form();state.editCar(car);state.newCar.twin_model='';let sent;
 globalThis.fetch=async(url,init)=>{sent={url,method:init.method,payload:JSON.parse(init.body)};return {ok:true};};
 await state.submitCar();assert.equal(sent.payload.twin_model,null);
 state.editCar(car);state.cancelEditCar();assert.equal(state.newCar.twin_model,'');assert.equal(state.editCarId,null);
 state.openCarForm();state.newCar.name='New EV';state.newCar.allowed_driver_ids=['mum'];await state.submitCar();
 assert.equal(sent.method,'POST');assert.equal(sent.url,'/ingress/api/cars');assert.equal(sent.payload.twin_model,null);
});
check('human JSON refusals and network failures retain unsaved form state',async()=>{
 const state=form();state.editCar(car);
 globalThis.fetch=async()=>({ok:false,json:async()=>({detail:'Choose an imported car model.'})});
 await state.submitCar();assert.equal(alerts.at(-1),'Choose an imported car model.');assert.equal(state.showCarForm,true);assert.equal(state.saving,false);
 assert.equal(state.newCar.twin_model,'import-car');assert.equal(state.newCar.name,'Family EV');
 globalThis.fetch=async()=>{throw new Error('offline');};await state.submitCar();
 assert.match(alerts.at(-1),/Could not reach the house/);assert.equal(state.newCar.twin_model,'import-car');assert.equal(state.saving,false);
 globalThis.fetch=async()=>({ok:false,json:async()=>{throw new Error('HTML proxy reply');}});await state.submitCar();
 assert.equal(alerts.at(-1),'Could not save this car. Please try again.');assert.equal(state.showCarForm,true);
});
check('catalog picker filters car imports and builds authenticated ingress-relative thumbnail paths',async()=>{
 const state=driveSetup();let requested;
 globalThis.fetch=async url=>{requested=url;return {ok:true,json:async()=>[
  {id:'import-car',name:'Kia EV9',kind:'car',thumbnail:'preview image.png'},
  {id:'import-chair',name:'Chair',kind:'furniture'}]};};
 await state.loadCarModels();assert.equal(requested,'/ingress/api/house/twin/imports');assert.equal(state.carTwinModels.length,1);
 assert.equal(state.carModelThumbnail(state.carTwinModels[0]),'/ingress/api/house/twin/imports/import-car/preview%20image.png');
 window.chfAuthUrl=url=>url+'?token=parent-test';
 assert.equal(state.carModelThumbnail(state.carTwinModels[0]),'/ingress/api/house/twin/imports/import-car/preview%20image.png?token=parent-test');
 delete window.chfAuthUrl;
 assert.equal(state.carModelThumbnail({id:'import-empty'}),'');assert.equal(state.carModelsLoading,false);
 globalThis.fetch=async()=>({ok:false});await state.loadCarModels();assert.equal(state.carTwinModels.length,1);assert.match(state.carModelsError,/Could not load car models/);
 globalThis.fetch=async()=>({ok:true,json:async()=>[]});await state.loadCarModels();assert.equal(state.carTwinModels.length,0);assert.equal(state.carModelsError,'');
});
check('the Energy drawer names the authoritative chosen model and links to Drive setup',async()=>{
 const {mountEnergySettings}=await import(file('static/twin/live/energy_settings.js'));
 for(const id of ['twin-energy-fields','twin-energy-save','twin-energy-search']){const node=document.createElement(id.endsWith('save')?'button':'div');node.id=id;document.body.append(node);}
 const view={plan:{buildings:[]},render(){},live:{peek:()=>({}),layout:()=>({markers:[]}),stale:()=>false,subscribe:()=>()=>{},configureEnergy(){}}};
 const preferences={can_edit:true,mapping:{cars:[{id:'ev',name:'Family EV',twin_model:'old-model'}]},cars:[{id:'ev',name:'Family EV',twin_model:'import-car'}]};
 const paths=[],settings=mountEnergySettings(view,{api:async path=>{paths.push(path);return {ok:true,json:async()=>path.endsWith('/imports')?[{id:'import-car',kind:'car',name:'Kia EV9'}]:preferences};}});
 try{await settings.reload();await wait(30);const fields=document.getElementById('twin-energy-fields');
  assert.ok(fields.textContent.includes('3D model in the house: Kia EV9'));assert.ok(!fields.textContent.includes('old-model'));
  const link=fields.querySelectorAll('a').find(node=>node.textContent==='Set in Drive setup');assert.ok(link);assert.ok(link.href.endsWith('drive_setup#cars'));
  assert.ok(paths.includes('api/house/twin/imports'));
 }finally{settings.stop();for(const id of ['twin-energy-fields','twin-energy-save','twin-energy-search'])document.getElementById(id)?.remove();}
});
let failed=0;for(const [name,fn] of checks){try{await fn();console.log('  ok '+name);}catch(error){++failed;console.error('  FAIL '+name+'\n'+error.stack);}}
assert.deepEqual(domErrors,[]);assert.deepEqual(escaped,[]);console.log(`${checks.length-failed}/${checks.length} car model UI checks passed`);process.exitCode=failed?1:0;
"""


if __name__ == '__main__':
    sys.exit(run(DRIVER, prefix='chauffeur_car_models_ui_', timeout=300))
