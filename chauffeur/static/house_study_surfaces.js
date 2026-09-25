/* Physical Study surfaces. All writes use the parent's existing bounded visit. */
(function(){
  'use strict';
  var base=window.chfBase||'',pages={},sort='date',busy=false,dirty=false,revision=0,stopMonitor=null;
  function el(tag,text,host,cls){var n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;host.appendChild(n);return n;}
  function button(text,host,fn){var b=el('button',text,host);b.type='button';b.addEventListener('click',fn);return b;}
  function text(value){return typeof value==='string'?value:'';}
  function field(label,value,host,type){var l=el('label',label,host,'study-field'),n=el(type==='textarea'?'textarea':'input',null,l);if(type&&type!=='textarea')n.type=type;n.value=value||'';return n;}
  function safeLink(label,url,host){try{var u=new URL(url,location.href);if(!['http:','https:'].includes(u.protocol))return;var a=el('a',label,host);a.href=u.href;return a;}catch(_){}}
  function render(host,key,data,refresh){
    if(key==='calendar')return false;
    if(busy)return true;
    var ticket=++revision,session=window.chfHouseParent?.();if(!session)return true;
    dirty=false;
    if(stopMonitor){stopMonitor();stopMonitor=null;}
    host.replaceChildren();
    var title={board:'Connections',desk:'Plans in hand',tray:'Intake',stickies:'Findings',window:'Family baseline',contracts:'Agreements',binders:'Programs',gauges:'Argyle gauges',monitor:'This week',map:'Family travels'}[key];
    var panel=el('section',null,host,'study-paper study-'+key);panel.setAttribute('aria-label',title);
    panel.addEventListener('input',()=>{dirty=true;});panel.addEventListener('change',()=>{dirty=true;});
    var heading=el('h2',title,panel),body=el('div',null,panel,'study-rows');
    var message=el('p','',panel,'study-feedback');message.setAttribute('role','status');
    function live(){return revision===ticket&&panel.isConnected&&window.chfHouseParent?.()?.token===session.token;}
    async function act(path,payload){
      if(busy||!live())return;
      var operation={};busy=operation;panel.querySelectorAll('button,input,select,textarea').forEach(n=>n.disabled=true);message.textContent='Saving…';
      try{
        var response=await fetch(base+'api/'+path,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-Member-Token':session.token},body:JSON.stringify(payload||{})});
        var result=await response.json();if(!live())return;
        if(!response.ok||result.status==='error')throw new Error(typeof result.detail==='string'?result.detail:result.message||'Could not save. Try again.');
        busy=false;dirty=false;
        try{await refresh();}catch(_){if(live())message.textContent='Saved. Reopen this object to refresh its information.';return;}
        var current=host.querySelector('.study-feedback');if(current&&window.chfHouseParent?.()?.token===session.token)current.textContent=result.message||result.note||(result.status==='no_move'?'Argyle could not prepare an action for this step.':'Saved.');
      }catch(err){if(live())message.textContent=err.message||'Could not save. Try again.';}
      finally{if(busy===operation)busy=false;if(live())panel.querySelectorAll('button,input,select,textarea').forEach(n=>n.disabled=false);}
    }
    function action(label,path,payload,where){return button(label,where||body,()=>act(path,typeof payload==='function'?payload():payload));}
    function paged(rows,label){
      if(!rows.length){el('p','No '+label+' waiting.',body,'study-empty');return null;}
      var at=Math.max(0,rows.findIndex(r=>r.id===pages[key]));pages[key]=rows[at].id;
      var nav=el('nav',null,panel,'study-pages');nav.setAttribute('aria-label',label+' pages');
      var prev=button('← Previous',nav,()=>{pages[key]=rows[(at+rows.length-1)%rows.length].id;render(host,key,data,refresh);});
      el('span',(at+1)+' / '+rows.length,nav);
      var next=button('Next →',nav,()=>{pages[key]=rows[(at+1)%rows.length].id;render(host,key,data,refresh);});
      prev.disabled=next.disabled=rows.length<2;
      return rows[at];
    }
    function article(title,detail,where){var a=el('article',null,where||body);el('h3',title||'Untitled',a);if(detail)el('p',detail,a);return a;}
    var d=data[key]||{};
    if(key==='tray'){
      var sortLabel=el('label','Sort papers ',panel,'study-sort'),select=el('select',null,sortLabel);
      [['date','Date'],['title','Title'],['sender','Sender']].forEach(([id,label])=>{var o=el('option',label,select);o.value=id;});select.value=sort;
      select.onchange=()=>{sort=select.value;pages.tray=null;render(host,key,data,refresh);};
      var rows=(d.items||[]).slice().sort((a,b)=>String(sort==='title'?a.title:sort==='sender'?a.source_from:a.start||'9999').localeCompare(String(sort==='title'?b.title:sort==='sender'?b.source_from:b.start||'9999')));
      var p=paged(rows,'intake items');if(!p)return true;
      var paper=article(p.title,[p.source_from,p.source_subject].filter(Boolean).join(' · '));
      el('p',p.notes||'No additional notes.',paper);
      if(p.duplicate_of)el('p','Already on the calendar: '+p.duplicate_of,paper);
      var name=field('Title',p.title,paper),start=field('Starts / due',p.start,paper),end=field('Ends',p.end,paper),loc=field('Location',p.location,paper),notes=field('Notes',p.notes,paper,'textarea');
      var targetLabel=el('label','File in',paper,'study-field'),target=el('select',null,targetLabel);el('option','Choose a destination',target).value='';
      (p.supplies_only?[{id:'supplies',label:'Shopping list supplies'}]:d.targets||[]).forEach(t=>{el('option',t.label,target).value=t.id;});target.value=p.supplies_only?'supplies':p.calendar_id||'';
      var supplyChecks=[];(p.supplies||[]).forEach(s=>{var label=el('label',null,paper,'study-supply'),check=el('input',null,label);check.type='checkbox';check.checked=true;el('span',s.name,label);supplyChecks.push({check,name:s.name});});
      var actions=el('div',null,paper,'study-actions');
      button('Approve & file',actions,()=>{
        if(!target.value){message.textContent='Choose where this paper should go.';target.focus();return;}
        if(target.value==='errand'&&!loc.value.trim()){message.textContent='Add the errand location.';loc.focus();return;}
        if(!start.value.trim()&&!p.supplies_only){message.textContent='Add a start or due date.';start.focus();return;}
        act('proposals/'+encodeURIComponent(p.id)+'/approve',{calendar_id:target.value,title:name.value,start:start.value,end:end.value,all_day:!!p.all_day,location:loc.value,description:notes.value,supplies:supplyChecks.filter(s=>s.check.checked).map(s=>s.name)});
      });
      action('Ignore this paper','proposals/'+encodeURIComponent(p.id)+'/ignore',{},actions);
    }else if(key==='desk'){
      var plan=paged(Array.isArray(d)?d:[],'plans');if(!plan)return true;
      article(plan.line,plan.detail);
      (plan.plan_json?.steps||[]).forEach(s=>{
        var a=article(s.text,[s.owner_name||(s.kind==='tool'?'Argyle':''),s.due?'By '+s.due:'',s.status].filter(Boolean).join(' · '));
        if(s.note)el('p',s.note,a);if(s.proposal_json?.summary)el('p','Proposed action: '+s.proposal_json.summary,a);
        if(s.status==='open'){
          var path='mind/insights/'+encodeURIComponent(plan.id)+'/step/'+encodeURIComponent(s.id)+'/',actions=el('div',null,a,'study-actions');
          if(s.kind==='tool')action(s.proposal_json?.proposal_id?'Approve this action':'Prepare action',path+(s.proposal_json?.proposal_id?'approve':'bind'),{},actions);
          else action('Mark done',path+'done',{},actions);
          action('Skip step',path+'skip',{},actions);
        }
      });
      var controls=el('div',null,body,'study-actions');
      action('Set aside for a week','mind/insights/'+encodeURIComponent(plan.id)+'/snooze',{days:7},controls);
      action('Mark plan handled','mind/insights/'+encodeURIComponent(plan.id)+'/clear',{},controls);
    }else if(key==='binders'){
      var p=paged(Array.isArray(d)?d:[],'programs');if(!p)return true;
      var a=article(p.title,[p.state,p.detail].filter(Boolean).join(' · ')),phase=p.progress?.phase||{},unit=p.current_unit||{};
      if(p.why)el('p',p.why,a);
      [['Current phase',phase.name],['Practice',phase.what],['Session',phase.session],['Next milestone',phase.milestone],['Progression',phase.progression],['Current lesson',unit.title||unit.name],['Lesson notes',unit.body]].forEach(([label,v])=>{if(text(v)){el('h4',label,a);el('p',v,a);}});
      (phase.rotation||[]).forEach(r=>article(r.label||r.name,r.body||r.session||r.what,a));
      if(unit.url)safeLink('Lesson source',unit.url,a);
      if(p.progress)el('p',(p.progress.sessions||0)+' sessions logged · '+(p.progress.minutes||0)+' minutes',a);
      var mins=field('Minutes practised',p.shape?.minutes,a,'number');mins.min='1';mins.max='600';
      var note=field('Session note','',a,'textarea'),controls=el('div',null,a,'study-actions'),path='programs/'+encodeURIComponent(p.id)+'/';
      button('Log practice',controls,()=>{var n=Number(mins.value);if(!Number.isInteger(n)||n<1||n>600){message.textContent='Enter 1–600 minutes.';return;}act(path+'session',{minutes:n,note:note.value});});
      action(p.state==='paused'?'Resume program':'Pause program',path+(p.state==='paused'?'resume':'pause'),{},controls);
      if(phase.name&&phase.milestone)action('Milestone reached',path+'milestone',{phase_name:phase.name},controls);
    }else if(key==='contracts'){
      var deal=paged(d.items||[],'agreements');if(!deal)return true;
      var spread=el('div',null,body,'study-book-spread'),left=el('div',null,spread,'study-agreement-page'),right=el('div',null,spread,'study-agreement-page');
      article(deal.title,[deal.date,deal.state==='asking'?'Waiting for replies':'Draft agreement'].filter(Boolean).join(' · '),left);el('p',deal.line||'',left);
      el('h3','The agreement',right);
      (deal.parts||[]).forEach(p=>article(p.ask_text||p.label||'Requested change',p.state||'Not yet asked',right));
      var controls=el('div',null,right,'study-actions');
      if(deal.state==='draft')action('Send these asks','negotiation/'+encodeURIComponent(deal.id)+'/ask',{},controls);
      action('Close agreement','negotiation/'+encodeURIComponent(deal.id)+'/kill',{},controls);
    }else if(key==='board'||key==='stickies'){
      var row=paged(key==='board'?d.pins||[]:d.items||[],key==='board'?'connections':'findings');if(!row)return true;
      var a=article(row.label||row.line,key==='board'?row.detail:row.severity);if(row.approach)el('p',row.approach,a);
      var controls=el('div',null,a,'study-actions');
      if(key==='stickies'){
        action('Mark handled','findings/'+encodeURIComponent(row.id)+'/resolve',{act:'tap'},controls);
        action('Dismiss','findings/'+encodeURIComponent(row.id)+'/resolve',{act:'dismiss'},controls);
      }else if(row.kind==='insight'){
        action('Make a plan','mind/insights/'+encodeURIComponent(row.id)+'/plan',{},controls);
        action('Set aside for a week','mind/insights/'+encodeURIComponent(row.id)+'/snooze',{days:7},controls);
      }else el('p',row.bad?'Overdue':row.warn?'Needs attention':'Open thread',a);
    }else if(key==='window'){
      panel.dataset.plantState=d.ready?(d.plant_state||((d.worse||[]).length>1?'wilting':d.worse?.length?'drooping':'thriving')):'unknown';
      article(d.ready?d.label||'Family baseline':'Baseline is still forming',d.ready?'Compared with your family’s usual week.':'The plant will reflect your family’s pattern once there is enough history.');
      (d.signs||[]).forEach(s=>el('p',s,body));
    }else if(key==='gauges'){
      heading.remove();body.className='study-dials';
      [['Thinking today',d.think,d.think_cap],['Research this month',d.research,d.research_cap]].forEach(([label,value,cap])=>{
        var g=el('div',null,body,'study-dial');g.setAttribute('role','img');g.setAttribute('aria-label',label+': '+(value==null?'Unavailable':value+' of '+cap));
        var valid=Number.isFinite(value)&&Number.isFinite(cap)&&cap>0,angle=-120+240*(valid?Math.max(0,Math.min(1,value/cap)):0);
        var svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 400 400');svg.setAttribute('aria-hidden','true');g.appendChild(svg);
        function shape(tag,attrs){var n=document.createElementNS(svg.namespaceURI,tag);Object.entries(attrs).forEach(([k,v])=>n.setAttribute(k,v));svg.appendChild(n);return n;}
        for(var i=0;i<=20;i++)shape('line',{x1:200,y1:36,x2:200,y2:i%5?47:59,stroke:'#75654d','stroke-width':i%5?2:4,transform:'rotate('+(-120+i*12)+' 200 200)'});
        if(valid){shape('line',{x1:200,y1:217,x2:200,y2:62,stroke:'#82402b','stroke-width':5,'stroke-linecap':'round',transform:'rotate('+angle+' 200 200)'});shape('circle',{cx:200,cy:200,r:10,fill:'#493c29'});}
        el('strong',label,g);el('span',value==null?'Unavailable':String(value)+(cap!=null?' / '+cap:''),g);
      });
      message.textContent=d.ingest_errors==null?'Ingest status unavailable':d.ingest_errors+' recent ingest errors';
    }else if(key==='map'){
      var map=el('div',null,body,'study-world-map');var img=el('img',null,map);img.src=base+'static/house_hybrid/world-map.svg';img.alt='World map, longitude −180 to 180 and latitude 90 to −90';
      var trips=d.trips||[];
      var home=d.home,hasHome=Number.isFinite(home?.lat)&&Number.isFinite(home?.lon);
      if(hasHome){
        var hx=(home.lon+180)/360*1000,hy=(90-home.lat)/180*500;
        var strings=document.createElementNS('http://www.w3.org/2000/svg','svg');strings.setAttribute('viewBox','0 0 1000 500');strings.setAttribute('aria-hidden','true');strings.classList.add('study-map-strings');map.appendChild(strings);
        trips.filter(t=>Number.isFinite(t.lat)&&Number.isFinite(t.lon)).forEach(t=>{
          var x=(t.lon+180)/360*1000,y=(90-t.lat)/180*500;
          var sag=Math.min(24,Math.hypot(x-hx,y-hy)*.055);
          var thread=document.createElementNS(strings.namespaceURI,'path');
          thread.setAttribute('d','M '+hx+' '+hy+' Q '+((hx+x)/2)+' '+((hy+y)/2+sag)+' '+x+' '+y);
          strings.appendChild(thread);
        });
        var homePin=el('span',null,map,'study-map-home');homePin.style.left=hx/10+'%';homePin.style.top=hy/5+'%';homePin.setAttribute('role','img');homePin.setAttribute('aria-label','Home');
        el('span','●',homePin,'study-home-tack');el('span','Home',homePin,'study-home-label');
      }
      trips.forEach(t=>{
        var located=Number.isFinite(t.lat)&&Number.isFinite(t.lon),a;
        if(located){a=el('a','●',map,'study-map-pin');a.style.left=(t.lon+180)/360*100+'%';a.style.top=(90-t.lat)/180*100+'%';a.title=t.title+' · '+t.location;a.setAttribute('aria-label',a.title);}
        else {var pending=el('div',null,body,'study-unlocated');a=el('a',t.title+' · '+(t.location||'No destination')+' — location needed',pending);if(t.location&&t.event_id)action('Locate destination','study/trips/'+encodeURIComponent(t.event_id)+'/locate',{},pending);}
        a.href=base+'trip?event_id='+encodeURIComponent(t.event_id||t.id)+'&panel=false';a.addEventListener('click',()=>window.chfHouseRemember?.());
      });
      var list=el('div',null,body,'study-trip-key');
      trips.filter(t=>Number.isFinite(t.lat)&&Number.isFinite(t.lon)).forEach(t=>{var a=el('a',t.title+' · '+t.location,list);a.href=base+'trip?event_id='+encodeURIComponent(t.event_id||t.id)+'&panel=false';a.addEventListener('click',()=>window.chfHouseRemember?.());});
      if(!trips.length)el('p','No trips planned.',body,'study-empty');
    }else if(key==='monitor'){
      stopMonitor=window.chfStudyMonitor.mount(panel,d);
    }
    return true;
  }
  window.chfStudySurfaces={render,clear(){++revision;pages={};busy=false;dirty=false;if(stopMonitor){stopMonitor();stopMonitor=null;}},editing(host){return busy||dirty||!!host.querySelector('input:focus,textarea:focus,select:focus');}};
})();
