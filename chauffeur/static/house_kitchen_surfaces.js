/* Real household photographs and the current outdoor conditions live on the objects. */
(function () {
  'use strict';
  var room=document.getElementById('hybrid-kitchen');
  if(!room)return;
  var photos=document.getElementById('kitchen-moment-photos');
  var fridge=document.getElementById('kitchen-fridge-photos');
  var status=document.getElementById('kitchen-status');
  var outdoors=Array.from(room.querySelectorAll('[data-outdoors]'));
  var base=window.chfBase||'', pending=null, fetched=0, signature='', message='Loading photographs…';
  var weather='unknown', condition='', weatherRevision=0;
  var positions=[[355,190,270,205,-5],[715,175,245,225,4],[355,440,250,230,3],[710,460,265,195,-4],[390,725,255,180,-3],[725,720,245,170,5]];
  var mini=[[170,212,32,27,-5],[211,208,30,29,4],[170,254,30,30,3],[210,259,32,26,-4],[174,302,31,27,-3],[213,304,29,29,5]];
  function position(el,r) {
    Object.assign(el.style,{left:r[0]/1536*100+'%',top:r[1]/1024*100+'%',width:r[2]/1536*100+'%',height:r[3]/1024*100+'%',transform:'rotate('+r[4]+'deg)'});
  }
  function render(data) {
    var moments=(data?.moments||[]).slice(0,6), next=JSON.stringify(data||{});
    message=moments.length?'':'No family photographs yet.';
    if(next===signature)return;
    signature=next; photos.replaceChildren();fridge.replaceChildren();
    var helper=window.kitchenTileIsland();
    moments.forEach(function(m,i){
      [photos,fridge].forEach(function(host,index){
        var el=document.createElement(data.interactive===false?'span':'button');
        el.className='kitchen-photograph';
        var label=m.body||m.event_title||'Family moment '+(i+1);
        if(el.tagName==='BUTTON'){
          el.type='button';el.setAttribute('aria-label','Open moment: '+label);
          el.addEventListener('click',function(){window.showMomentOverlayKiosk?.(m,{manual:true});});
        }
        var img=document.createElement('img');img.src=helper.momentSrc(m);img.alt=label;img.draggable=false;
        img.addEventListener('error',function(){el.classList.add('is-unavailable');el.setAttribute('aria-label','Photograph unavailable: '+label);});
        el.appendChild(img);position(el,(index?mini:positions)[i]);host.appendChild(el);
      });
    });
  }
  async function refresh() {
    paintWeather();
    if(pending || Date.now()-fetched<45000)return pending;
    pending=(async function(){
      try{
        var response=await fetch(base+'api/home_board?widgets=moments');
        if(!response.ok)throw new Error('moments');
        var data=await response.json();render((data.tiles||[]).find(t=>t.type==='moments')?.data);
        fetched=Date.now();
      }catch(_){message='Photographs could not load. Reopen the fridge to try again.';}
      finally{pending=null;if(room.dataset.view==='moments')status.textContent=message;}
    })();
    return pending;
  }
  function weatherKind(cond){
    if(['sunny','clear-night'].includes(cond))return 'clear';
    if(['partlycloudy','cloudy','windy','windy-variant'].includes(cond))return 'cloudy';
    if(['rainy','pouring','lightning-rainy','lightning','hail'].includes(cond))return 'rain';
    if(['snowy','snowy-rainy'].includes(cond))return 'snow';
    if(cond==='fog')return 'fog';
    return 'unknown';
  }
  async function paintWeather(light){
    if(room.hidden)return;
    light=light || room.dataset.light || 'day';
    if(room.dataset.view==='weather' && room.dataset.phase==='detail')status.textContent=weather==='unknown'?'Current weather is unavailable.':'';
    var ticket=++weatherRevision, kind=weather;
    outdoors.forEach(el=>el.setAttribute('aria-label',kind==='unknown'?'Current weather unavailable':'Outside: '+condition.replace(/-/g,' ')));
    if(kind==='clear'){
      room.dataset.weather='clear';outdoors.forEach(el=>el.style.backgroundImage='none');return;
    }
    var asset=room.querySelector('[data-weather-asset="'+(kind==='unknown'?'cloudy':kind)+'"][data-weather-light="'+light+'"]');
    try{
      if(!asset.src)asset.src=asset.dataset.src;
      await asset.decode();
      if(ticket!==weatherRevision)return;
      room.dataset.weather=kind;
      outdoors.forEach(function(el){el.style.backgroundImage='url("'+asset.src+'")';el.dataset.light=light;});
    }catch(_){room.dataset.weather='unavailable';outdoors.forEach(el=>el.style.backgroundImage='none');}
  }
  function accept(data){condition=String(data?.window?.cond||'').toLowerCase();weather=weatherKind(condition);if(!room.hidden)refresh();}
  window.chfKitchenSurfaces={refresh:refresh,view:function(key){
    photos.hidden=key!=='moments';outdoors[1].hidden=key!=='weather';
    document.getElementById('kitchen-controls').hidden=key==='moments';
    if(key==='moments'){status.textContent=message;refresh();}
    if(key==='weather')paintWeather();
  }};
  window.addEventListener('chf-house-state',e=>accept(e.detail));
  window.addEventListener('chf-house-light',e=>paintWeather(e.detail?'night':'day'));
  accept(window.chfHouseState?.());
})();
