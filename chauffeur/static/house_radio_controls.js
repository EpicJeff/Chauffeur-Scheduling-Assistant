/* Full music controls share the radio's selected speaker and command lifecycle. */
(function () {
  'use strict';
  var transport=document.getElementById('radio-transport');if(!transport)return;
  var panel=document.getElementById('radio-music-panel'), list=document.getElementById('radio-panel-items');
  var frame=document.getElementById('hybrid-room-frame');
  var owner=document.getElementById('radio-panel-member'), search=document.getElementById('radio-panel-search');
  var query=document.getElementById('radio-panel-query'), type=document.getElementById('radio-panel-type');
  var provider=document.getElementById('radio-panel-provider'), library=document.getElementById('radio-panel-library');
  var status=document.getElementById('radio-panel-status'), picker=document.getElementById('radio-panel-playlists');
  var heart=document.getElementById('radio-now-favorite'), opts={apiBase:window.chfBase || ''};
  var tab='favorites', revision=0, nowRevision=0, now=null, nowKey='', lastTarget='', timer=null;
  var favorites=[], playlists=[], writing=false, opener=null;
  function state(){return window.HouseRadio.state();}
  function element(tag,text,host){var e=document.createElement(tag);if(text)e.textContent=text;if(host)host.append(e);return e;}
  function button(text,label,host,run){var b=element('button',text,host);b.type='button';b.setAttribute('aria-label',label);b.addEventListener('click',run);return b;}
  function valid(ticket,member,target){return panel.open && ticket===revision && owner.value===member && state().selected===target;}
  function saved(item){return owner.value?favorites.some(f=>f.uri===item.uri):item.favorite===true;}
  function canHeart(item){return item?.uri && (owner.value || typeof item.favorite==='boolean');}
  async function readFavorites(){var member=owner.value;favorites=[];if(member){var shelf=await MusicLogic.myShelf(member,opts);if(panel.open && owner.value===member)favorites=shelf.favorites || [];}paintHeart();}
  function paintHeart(){
    heart.hidden=!canHeart(now);heart.disabled=writing;
    heart.textContent=now && saved(now)?'♥':'♡';
    heart.setAttribute('aria-label',now && saved(now)?'Remove current song from favorites':'Favorite current song');heart.title=heart.getAttribute('aria-label');
    heart.setAttribute('aria-pressed',String(!!now && saved(now)));
  }
  async function readNow(force){
    var s=state(), key=s.selected+':'+(s.player?.media_content_id || '')+':'+(s.player?.media_title || '');
    if(!panel.open || (!force && key===nowKey))return;
    nowKey=key;var ticket=++nowRevision,target=s.selected;now=null;paintHeart();
    var entity=target?await window.HouseRadio.target():null;
    var item=entity?await MusicLogic.nowPlayingItem(entity,opts):null;
    if(!item?.uri && s.player?.media_content_id)item={uri:s.player.media_content_id,name:s.player.media_title || '',subtitle:s.player.media_artist || '',favorite:null};
    if(panel.open && ticket===nowRevision && target===state().selected){now=item;paintHeart();}
  }
  function paint(){
    var s=state(), p=s.player || {};
    transport.hidden=!s.active;document.getElementById('radio-live-settings').textContent=(Number.isFinite(p.volume_level)?Math.round(p.volume_level*100)+'%':'')+(p.shuffle?' SHUFFLE':'')+(p.repeat && p.repeat!=='off'?' REPEAT '+p.repeat.toUpperCase():'');
    transport.querySelectorAll('[data-radio-command]').forEach(b=>b.disabled=!s.available || s.busy);
    transport.querySelector('[data-radio-command=shuffle]').setAttribute('aria-pressed',String(p.shuffle===true));
    var repeat=transport.querySelector('[data-radio-command=repeat]'), mode=p.repeat || 'off';
    repeat.textContent=mode==='one'?'↻₁':'↻';repeat.setAttribute('aria-label','Repeat: '+mode);repeat.setAttribute('aria-pressed',String(mode!=='off'));repeat.title='Repeat: '+mode;
    panel.querySelector('[data-radio-command=radio]').disabled=!s.available || s.busy || !p.media_content_id;
    if(!panel.open)return;
    document.getElementById('radio-panel-now-title').textContent=[p.media_title || 'Nothing playing',p.media_artist].filter(Boolean).join(' · ');
    list.querySelectorAll('[data-playback]').forEach(b=>b.disabled=!s.available || s.busy || writing);
    if(s.error)status.textContent=s.error;
    readNow(false);
    if(lastTarget!==s.selected){lastTarget=s.selected;load();}
  }
  async function commandClick(event){
    var b=event.target.closest('button');if(!b || b.disabled)return;
    if(!b.dataset.radioCommand && !b.dataset.radioPanel)return;
    if(b.dataset.radioPanel){open(b.dataset.radioPanel,b);return;}
    var command=b.dataset.radioCommand,p=state().player || {};
    if(command==='toggle')command=p.state==='playing'?'pause':'play';
    if(command==='radio')await window.HouseRadio.action(target=>MusicLogic.play(target,p.media_content_id,null,opts,{radioMode:true}));
    else if(command==='shuffle')await window.HouseRadio.command('shuffle_set',{shuffle:!p.shuffle});
    else if(command==='repeat')await window.HouseRadio.command('repeat_set',{repeat:{off:'all',all:'one',one:'off'}[p.repeat || 'off'] || 'off'});
    else await window.HouseRadio.command(command);
  }
  transport.addEventListener('click',commandClick);panel.addEventListener('click',commandClick);
  async function mutate(run,done){
    if(writing)return;writing=true;paint();paintHeart();
    var ticket=revision,member=owner.value,target=state().selected;
    status.textContent='Saving…';
    try{await run();if(valid(ticket,member,target)){status.textContent=done || 'Saved';await readFavorites();if(!valid(ticket,member,target))return;await load();await readNow(true);window.HouseRecords?.refresh();}}
    catch(e){if(valid(ticket,member,target))status.textContent=e.message || 'Could not save. Try again.';}
    finally{writing=false;paint();paintHeart();}
  }
  function favorite(item){
    var member=owner.value,on=saved(item);
    return mutate(async function(){
      if(member){if(on)await MusicLogic.removeFavorite(member,item.uri,opts);else await MusicLogic.addFavorite(member,item,opts);}
      else {if(on)await MusicLogic.houseUnfavorite(item.uri,item.media_type,opts);else await MusicLogic.houseFavorite(item.uri,opts);item.favorite=!on;}
    });
  }
  heart.addEventListener('click',()=>{if(now)favorite(now);});
  async function play(item,enqueue,radioMode){
    var member=owner.value;
    await window.HouseRadio.action(target=>MusicLogic.play(target,item.uri,item.media_type || 'track',opts,{enqueue:enqueue,radioMode:radioMode,memberId:member || null,item:item}));
    if(panel.open){status.textContent=state().error || (enqueue==='next'?'Playing next':enqueue?'Added to queue':'Playback requested');if(tab==='queue')load();}
    window.HouseRecords?.refresh();
  }
  function playlist(item){
    picker.replaceChildren();picker.hidden=false;
    element('p','Add “'+item.name+'” to a playlist',picker);
    playlists.forEach(p=>button(p.name,'Add to '+p.name,picker,()=>mutate(()=>MusicLogic.addToPlaylist(p.item_id,item.uri,opts),'Added to playlist')));
    var form=element('form','',picker), input=element('input','',form);input.required=true;input.maxLength=120;input.placeholder='New playlist name';input.setAttribute('aria-label','New playlist name');
    var create=element('button','Create playlist',form);create.type='submit';
    form.addEventListener('submit',event=>{event.preventDefault();var name=input.value.trim();if(name)mutate(()=>MusicLogic.createPlaylist(name,item.uri,opts),'Playlist created');});
    button('Cancel','Close playlist picker',picker,()=>{picker.hidden=true;});
  }
  function rows(items){
    list.replaceChildren();if(!items.length){element('p','Nothing here yet.',list);return;}
    items.forEach(function(item){
      var row=element('article','',list), art=MusicLogic.imageOf(item,opts);
      if(art){var img=element('img','',row);img.src=art;img.alt='';img.loading='lazy';img.addEventListener('error',()=>img.remove());}
      var name=button(item.name || 'Untitled','Play '+(item.name || 'music'),row,()=>play(item));name.dataset.playback='';
      element('small',MusicLogic.subtitleOf(item),row);
      var actions=element('div','',row);actions.className='radio-item-actions';
      if(canHeart(item)){var h=button(saved(item)?'♥ Saved':'♡ Favorite','Favorite '+item.name,actions,()=>favorite(item));h.setAttribute('aria-pressed',String(saved(item)));}
      [['Play next','next'],['Add to queue','add']].forEach(([label,enqueue])=>{button(label,label+' '+item.name,actions,()=>play(item,enqueue)).dataset.playback='';});
      button('Radio','Start radio from '+item.name,actions,()=>play(item,null,true)).dataset.playback='';
      if(item.media_type==='track' && playlists.length)button('Playlist','Add '+item.name+' to a playlist',actions,()=>playlist(item));
    });paint();
  }
  function queueRows(data){
    list.replaceChildren();
    if(!data){element('p','Queue unavailable. Try again.',list);return;}
    var editable=!!data.can_edit,items=data.items || [];
    if(!editable)element('p','Up next — this connection provides a read-only queue.',list);
    if(editable)button('Clear queue','Clear queue',list,()=>queueEdit('clear')).dataset.playback='';
    if(!items.length)element('p','The queue is empty.',list);
    items.forEach(function(item){
      var row=element('article','',list);row.classList.toggle('is-current',!!item.current);
      var b=button((item.current?'Playing: ':'')+item.name,'Play queued '+item.name,row,()=>queueEdit('play_index',null,item.index));
      if(editable && !item.current && item.index!=null)b.dataset.playback='';else b.disabled=true;
      element('small',item.subtitle,row);
      if(editable && !item.current && item.id){
        var actions=element('div','',row);actions.className='radio-item-actions';
        [['Move up','move_up'],['Move down','move_down'],['Remove','remove']].forEach(([label,command])=>{button(label,label+' '+item.name,actions,()=>queueEdit(command,item.id)).dataset.playback='';});
      }
    });paint();
  }
  async function queueEdit(command,id,index){
    await window.HouseRadio.action(target=>MusicLogic.queueCommand(target,command,{queue_item_id:id || null,index:index ?? null},opts));
    if(panel.open){await load();status.textContent=state().error || 'Queue updated';}
  }
  async function load(){
    if(!panel.open)return;
    var ticket=++revision,member=owner.value,target=state().selected;
    search.hidden=tab!=='search';picker.hidden=true;document.getElementById('radio-show-records').hidden=!owner.value || !['favorites','recent'].includes(tab);document.getElementById('radio-panel-title').textContent=tab.toUpperCase();
    document.getElementById('radio-panel-view').value=tab;
    status.textContent='Loading…';list.replaceChildren();
    try{
      var items=[];
      if(tab==='queue'){
        var entity=target?await window.HouseRadio.target():null;
        var queue=entity?await MusicLogic.queue(entity,opts):null;
        if(!valid(ticket,member,target))return;
        status.textContent=target?'':'Choose a speaker on the radio first.';queueRows(queue);return;
      }
      if(tab==='search'){
        if(!query.value.trim()){status.textContent='Search for an artist, album, song, playlist or station.';return;}
        var found=await MusicLogic.search(query.value.trim(),{types:type.value?[type.value]:[],provider:provider.value,libraryOnly:library.checked,limit:20},opts);
        if(!valid(ticket,member,target))return;
        if(found.providers?.length){var selected=provider.value;provider.replaceChildren(new Option('All providers',''));found.providers.forEach(p=>provider.add(new Option(p.name,p.domain)));provider.value=selected;}
        items=MusicLogic.flatten(found);
      }else if(member && tab!=='recommendations'){
        var shelf=await MusicLogic.myShelf(member,opts);if(!valid(ticket,member,target))return;
        favorites=shelf.favorites || [];items=shelf[tab] || [];
      }else if(tab==='favorites'){
        var groups=await Promise.all(['playlist','album','track','artist','radio'].map(t=>MusicLogic.favorites(t,50,opts)));
        items=groups.flat().map(item=>Object.assign({},item,{favorite:true}));
      }else{
        var shelves=await MusicLogic.shelves(opts);items=tab==='recent'?shelves.recently_played || []:(shelves.recommendations || []).flatMap(g=>g.items || []);
      }
      if(!valid(ticket,member,target))return;
      status.textContent=items.length+' items';rows(items);paintHeart();
    }catch(e){if(valid(ticket,member,target))status.textContent=e.message || 'Music could not load. Try again.';}
  }
  async function open(next,trigger){
    if(!state().active)return;opener=trigger || document.activeElement;tab=next || 'favorites';
    panel.open=true;panel.hidden=false;frame.classList.add('radio-controls-open');
    panel.querySelector('.radio-display-body').scrollTop=0;
    document.getElementById('radio-panel-close').focus({preventScroll:true});
    lastTarget=state().selected;nowKey='';
    var memberSelect=document.getElementById('radio-member');owner.replaceChildren(new Option('House',''));
    Array.from(memberSelect.options).filter(o=>o.value).forEach(o=>owner.add(new Option(o.text,o.value)));owner.value=memberSelect.value;
    paint();load();var ticket=revision;
    var results=await Promise.all([MusicLogic.editablePlaylists(opts),readFavorites()]);playlists=results[0];
    if(panel.open && ticket===revision)load();
    clearInterval(timer);if(panel.open)timer=setInterval(()=>{if(!document.hidden){if(tab==='queue')load();readNow(true);}},5000);
  }
  function close(){++revision;++nowRevision;clearInterval(timer);timer=null;panel.open=false;panel.hidden=true;frame.classList.remove('radio-controls-open');transport.hidden=!state().active;if(state().active && opener?.isConnected)opener.focus({preventScroll:true});}
  document.getElementById('radio-panel-close').addEventListener('click',close);
  document.getElementById('radio-show-records').addEventListener('click',function(){
    if(!owner.value || !['favorites','recent'].includes(tab))return;
    close();document.getElementById('radio-'+tab).click();
  });
  document.addEventListener('keydown',event=>{if(panel.open && event.key==='Escape'){event.preventDefault();event.stopImmediatePropagation();close();}},true);
  document.getElementById('radio-queue-open').addEventListener('click',event=>open('queue',event.currentTarget));
  document.getElementById('radio-panel-view').addEventListener('change',function(){tab=this.value;panel.querySelector('.radio-display-body').scrollTop=0;load();});
  owner.addEventListener('change',()=>{favorites=[];document.getElementById('radio-member').value=owner.value;document.getElementById('radio-member').dispatchEvent(new Event('change'));readFavorites();load();readNow(true);});
  search.addEventListener('submit',event=>{event.preventDefault();load();});
  [type,provider,library].forEach(e=>e.addEventListener('change',load));
  query.addEventListener('input',()=>{++revision;});
  window.addEventListener('radio-player-state',paint);
  window.addEventListener('pagehide',close);
  window.HouseRadioControls={open:open,close:close,openRecord:async function(item,trigger){await open('search',trigger);if(!panel.open)return;++revision;rows([item]);status.textContent=item.name;}};
})();
