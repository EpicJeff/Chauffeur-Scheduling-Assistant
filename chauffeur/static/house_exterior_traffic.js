/* Shared fleet/curb state, composed in fixed photograph coordinates. */
(function () {
  'use strict';
  var scene = document.getElementById('exterior-traffic');
  if (!scene) return;
  var photo = document.getElementById('exterior-photo');
  var shortcuts = document.getElementById('exterior-traffic-shortcuts');
  var payload = '', parked = [];
  var vehicles = window.ChauffeurHouseVehicles;
  // Both parking spaces are inside the same photographed double garage.
  // Never put an unrelated vehicle into an occupied bay just because it is home.
  var bays = [
    {key:'left',profile:'ev9-white-black-roof',box:[59.8,64.0,6.0,9.0]},
    {key:'right',profile:'gls450-white-23',box:[66.0,62.6,6.5,9.5]}
  ];
  function project() {
    if (!photo.naturalWidth) return;
    var scale = Math.max(innerWidth/photo.naturalWidth, innerHeight/photo.naturalHeight);
    scene.style.width = photo.naturalWidth*scale+'px';
    scene.style.height = photo.naturalHeight*scale+'px';
    scene.style.left = (innerWidth-photo.naturalWidth*scale)*(innerWidth<701?.8:.5)+'px';
    scene.style.top = (innerHeight-photo.naturalHeight*scale)+'px';
  }
  function open(key) {
    window.dispatchEvent(new CustomEvent('chf-house-open', {detail:key}));
  }
  function shortcut(text, key, id) {
    var button = document.createElement('button'); button.type = 'button'; button.id = id;
    button.textContent = text; button.addEventListener('click', function () { open(key); });
    shortcuts.appendChild(button);
  }
  function actor(index, point, label, key, id, warn, artwork) {
    var button = document.createElement('button'); button.type = 'button';
    button.className = 'exterior-vehicle'; button.dataset.vehicle = id;
    button.dataset.warn = String(!!warn); button.setAttribute('aria-label', label);
    button.title = label; button.style.left = point[0]*100+'%'; button.style.top = point[1]*100+'%';
    button.style.width = point[2]*100+'%'; button.style.zIndex = String(Math.round(point[1]*100));
    var art = document.createElement('span'); art.className = 'exterior-vehicle-art';
    art.setAttribute('aria-hidden','true');
    art.style.setProperty('--sprite-x', ((index%4)*100/3)+'%');
    art.style.setProperty('--sprite-y', (index < 4 ? 0 : 100)+'%');
    if (artwork && /^(data:image\/(png|webp);base64,|\/?static\/house_hybrid\/vehicles\/)/.test(artwork)) {
      var image = document.createElement('img'); image.alt = ''; image.draggable = false;
      image.src = artwork.startsWith('static/') ? (window.chfBase || '/') + artwork : artwork;
      image.onerror = function () { button.remove(); };
      art.style.background = 'none'; art.appendChild(image);
    }
    button.appendChild(art);
    var tag = document.createElement('span'); tag.className = 'exterior-vehicle-label'; tag.textContent = label;
    button.appendChild(tag); button.addEventListener('click', function () { open(key); });
    scene.appendChild(button);
  }
  var isPreview = document.body.dataset.housePreview === 'true';
  var query = new URL(location.href);
  var assigned = isPreview ? query.searchParams.get('driveway_car') : null;
  var preview = document.getElementById('exterior-driveway-preview');
  var busPreview = document.getElementById('exterior-bus-preview');
  if (isPreview && query.searchParams.get('traffic_demo') === '1') preview.value = 'home';
  var latest = {};
  function parkedBay(bay, item) {
    var button=document.createElement('button');button.type='button';button.className='exterior-patch-target exterior-garage-car';button.dataset.vehicle=item.id;button.dataset.bay=bay.key;button.dataset.warn=String(!!item.warn);
    var energy=Number.isFinite(item.battery_pct)?' · '+Math.round(item.battery_pct)+'% charge':Number.isFinite(item.fuel_pct)?' · '+Math.round(item.fuel_pct)+'% fuel':'';
    var label=(item.name||'Vehicle')+' · Home'+energy+(item.warn?' · Needs attention':'');
    button.setAttribute('aria-label',label);button.title=label;
    Object.assign(button.style,{left:bay.box[0]+'%',top:bay.box[1]+'%',width:bay.box[2]+'%',height:bay.box[3]+'%'});
    var tag=document.createElement('span');tag.className='exterior-vehicle-label';tag.textContent=label;button.appendChild(tag);
    button.addEventListener('click',function(){window.chfVehicleCluster(item.id);});scene.appendChild(button);
  }
  function garage(items) {
    var key=items[0]&&items[1]?'both':items[0]?'left':items[1]?'right':'empty';
    scene.dataset.garageState=key;
    if(key==='empty')return;
    var layer=document.createElement('div');layer.className='exterior-garage-layer';layer.setAttribute('aria-hidden','true');
    var image=document.createElement('img');image.src=scene.dataset['garage'+key[0].toUpperCase()+key.slice(1)];image.alt='';image.className='is-active';layer.appendChild(image);scene.appendChild(layer);
    items.forEach(function(item,i){if(item)parkedBay(bays[i],item);});
    image.onerror=function(){layer.remove();scene.querySelectorAll('.exterior-garage-car').forEach(b=>b.remove());};
  }
  function patch(name, label, key, id, box, vehicleId) {
    var shadow=document.createElement('div');shadow.className='exterior-driveway-shadow';shadow.setAttribute('aria-hidden','true');scene.appendChild(shadow);
    var img = document.createElement('img');
    img.src = scene.dataset[name]; img.alt = ''; img.className = 'is-active exterior-scene-patch';
    scene.appendChild(img);
    var button = document.createElement('button'); button.type = 'button';
    button.className = 'exterior-patch-target'; button.dataset.vehicle = id;
    button.setAttribute('aria-label',label); button.title = label;
    button.style.left = box[0]+'%'; button.style.top = box[1]+'%';
    button.style.width = box[2]+'%'; button.style.height = box[3]+'%';
    button.addEventListener('click',function () { if (vehicleId) window.chfVehicleCluster(vehicleId); else open(key); });
    img.onerror = function () { button.remove(); img.remove(); shadow.remove(); };
    scene.appendChild(button);
  }
  [preview,busPreview].forEach(function (input) {
    input.addEventListener('change',function () { payload = ''; accept(latest); });
  });
  function accept(state) {
    state = state || {}; latest = state;
    var drivewayMode = isPreview ? preview.value : 'live';
    var busMode = isPreview ? busPreview.value : 'live';
    var cars = Array.isArray(state.garage?.cars) ? state.garage.cars : [];
    var bus = busMode === 'home' || (busMode === 'live' && state.curb?.bus === true);
    var car = assigned ? cars.find(item => String(item.id) === assigned) : vehicles.assigned(cars, 'murano-white');
    var driveway = drivewayMode === 'home' || (drivewayMode === 'live' && car?.present === true);
    var next = JSON.stringify([cars,bus,driveway,!!state.curb?.demo,drivewayMode,busMode]);
    if (next === payload) return;
    payload = next; scene.replaceChildren(); shortcuts.replaceChildren();
    parked = cars.filter(function (car) { return car.present === true; });
    if (cars.length) shortcut('Vehicles · '+parked.length+' home', 'cars', 'exterior-cars-shortcut');
    garage(bays.map(function(bay){
      var item=vehicles.assigned(cars,bay.profile);
      return item?.present===true && item!==car?item:null;
    }));
    if (driveway) {
      patch('driveway', drivewayMode === 'home' ? 'Preview · White Nissan Murano' : car.name, 'cars', 'driveway-car', [46.7,71.5,16.3,14.3], car?.id);
    }
    // Uploaded cutouts are real vehicle artwork too, independent of built-in slots.
    cars.filter(item => item.present === true && item !== car && !vehicles.profile(item) && vehicles.uploaded(item)).forEach(function (item, index) {
      actor(0, [.39 + (index % 3)*.17, .91 + Math.floor(index/3)*.06, .17], item.name || 'Vehicle', 'cars', item.id, item.warn, vehicles.uploaded(item));
    });
    if (bus) {
      var busLabel = (state.curb?.demo || busMode === 'home') ? 'Demo · School bus nearby' : 'School bus nearby';
      actor(7,[.185,.99,.37], busLabel, 'schedule', 'school-bus', false);
      shortcut(busLabel, 'schedule', 'exterior-bus-shortcut');
    }
    project();
  }
  window.addEventListener('chf-house-state', function (event) { accept(event.detail); });
  window.addEventListener('chf-exterior-ready', project);
  window.addEventListener('resize', project);
  accept(window.chfHouseState?.());
})();
