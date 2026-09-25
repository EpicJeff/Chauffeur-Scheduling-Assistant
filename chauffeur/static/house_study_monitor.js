/* Family constellations: calendar counts are data; orbiting and light trails are ambient. */
(function(){
  'use strict';
  var motionPaused=false;
  function hash(s){var n=2166136261;for(var i=0;i<s.length;i++)n=Math.imul(n^s.charCodeAt(i),16777619);n=Math.imul(n^(n>>>16),0x7feb352d);n=Math.imul(n^(n>>>15),0x846ca68b);return((n^(n>>>16))>>>0)/4294967296;}
  function element(tag,text,parent,cls){var n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;parent.appendChild(n);return n;}
  window.chfStudyMonitor={mount:function(panel,data){
    panel.replaceChildren();panel.classList.add('study-constellations');
    var header=element('header',null,panel,'constellation-heading');element('h2','Family constellations',header);
    var toggle=element('button','Pause motion',header,'constellation-toggle');toggle.type='button';toggle.setAttribute('aria-pressed','false');
    var sky=element('div',null,panel,'constellation-sky'),canvas=element('canvas',null,sky);canvas.setAttribute('aria-hidden','true');
    var targets=element('div',null,sky,'constellation-targets');targets.setAttribute('role','group');targets.setAttribute('aria-label','Household members');
    var readout=element('div',null,panel,'constellation-readout');readout.setAttribute('role','status');readout.setAttribute('aria-live','polite');
    var person=element('strong','Your household, this week',readout),value=element('span','Hover, focus or tap a constellation to explore.',readout);
    element('p','Fuller constellations reflect busier calendars. Light trails are ambient.',panel,'constellation-caption');
    var hues=[40,177,213,315,95,262,18,145],selected=-1,w=0,h=0,time=0,last=0,raf=0,disposed=false,paused=motionPaused,frames=0;
    var motion=matchMedia('(prefers-reduced-motion: reduce)'),ctx=canvas.getContext('2d');
    var rows=(Array.isArray(data.clusters)?data.clusters:[]).slice(0,8).map(function(row,i){
      var name=String(row.name||'Household member'),count=Number.isFinite(row.count)?Math.max(0,Math.floor(row.count)):null;
      var c={name,count,hue:hues[i%hues.length],seed:hash(name+':'+i),nodes:[],x:0,y:0,r:0};
      for(var j=0;j<4+Math.min((count||0)*3,36);j++)c.nodes.push({a:hash(name+':angle:'+j)*Math.PI*2,r:Math.sqrt(hash(name+':radius:'+j)),speed:.045+hash(name+':speed:'+j)*.035});
      var b=element('button',null,targets,'constellation-person');b.type='button';b.setAttribute('aria-label',name+': '+(count==null?'calendar activity unavailable':count+' calendar '+(count===1?'item':'items')+' this week'));b.setAttribute('aria-pressed','false');
      b.style.setProperty('--star-color','hsl('+c.hue+' 75% 75%)');element('span',name,b);c.button=b;
      function select(){if(disposed)return;selected=i;person.textContent=name;value.textContent=count==null?'Calendar activity is unavailable.':count+' calendar '+(count===1?'item':'items')+' this week';rows.forEach((c,n)=>c.button.setAttribute('aria-pressed',String(n===i)));draw();}
      b.addEventListener('pointerenter',select);b.addEventListener('focus',select);b.addEventListener('click',select);return c;
    });
    if(!rows.length){person.textContent='A quiet sky';value.textContent='No household members to show yet.';toggle.hidden=true;}
    function glow(x,y,r,color,alpha){var g=ctx.createRadialGradient(x,y,0,x,y,r);g.addColorStop(0,'hsla('+color+',85%,72%,'+alpha+')');g.addColorStop(1,'hsla('+color+',80%,50%,0)');ctx.fillStyle=g;ctx.fillRect(x-r,y-r,r*2,r*2);}
    function star(x,y,r,color,alpha){ctx.fillStyle='hsla('+color+',80%,82%,'+alpha+')';ctx.beginPath();ctx.arc(x,y,r,0,Math.PI*2);ctx.fill();}
    function draw(){
      if(disposed||!ctx||!w||!h)return;frames++;canvas.dataset.frames=String(frames);
      ctx.clearRect(0,0,w,h);
      // A sparse starfield gives depth without carrying invented household facts.
      for(var n=0;n<55;n++)star(hash('x'+n)*w,hash('y'+n)*h,.5+hash('size'+n)*.6,205,.12+hash('light'+n)*.22);
      rows.forEach(function(a,i){
        if(rows.length<2)return;var b=rows[(i+1)%rows.length];if(rows.length===2&&i===1)return;
        var cx=(a.x+b.x)/2,cy=(a.y+b.y)/2-Math.min(36,h*.12);
        ctx.strokeStyle='rgba(165,193,197,.13)';ctx.lineWidth=.8;ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.quadraticCurveTo(cx,cy,b.x,b.y);ctx.stroke();
        var u=(time*.13+i/rows.length)%1;
        for(var k=0;k<9;k++){var t=u-k*.008;if(t<0)continue;var x=(1-t)*(1-t)*a.x+2*(1-t)*t*cx+t*t*b.x,y=(1-t)*(1-t)*a.y+2*(1-t)*t*cy+t*t*b.y;star(x,y,k?1:2.1,a.hue,(1-k/9)*.8);if(!k)glow(x,y,10,a.hue,.38);}
      });
      rows.forEach(function(c,index){
        var breathing=.9+Math.sin(time*.8+c.seed*6)*.1;glow(c.x,c.y,c.r*1.6,c.hue,(selected===index?.3:.2)*breathing);
        var points=c.nodes.map(n=>({x:c.x+Math.cos(n.a+time*n.speed)*n.r*c.r,y:c.y+Math.sin(n.a+time*n.speed)*n.r*c.r*.7}));
        ctx.strokeStyle='hsla('+c.hue+',55%,72%,.23)';ctx.lineWidth=.7;ctx.beginPath();
        points.forEach(function(p,i){var next=points[(i+1)%points.length];if(Math.hypot(p.x-next.x,p.y-next.y)<c.r*.85){ctx.moveTo(p.x,p.y);ctx.lineTo(next.x,next.y);}});ctx.stroke();
        points.forEach((p,i)=>star(p.x,p.y,i%5?1.25:1.9,c.hue,.65+.25*Math.sin(time*.7+i)));
        glow(c.x,c.y,16,c.hue,.65);star(c.x,c.y,3.2,c.hue,1);
        ctx.strokeStyle='hsla('+c.hue+',80%,85%,.55)';ctx.beginPath();ctx.moveTo(c.x-8,c.y);ctx.lineTo(c.x+8,c.y);ctx.moveTo(c.x,c.y-8);ctx.lineTo(c.x,c.y+8);ctx.stroke();
        if(selected===index){ctx.strokeStyle='hsla('+c.hue+',60%,75%,.35)';ctx.beginPath();ctx.ellipse(c.x,c.y,c.r+9,c.r*.7+9,0,0,Math.PI*2);ctx.stroke();}
      });
    }
    function resize(){
      if(disposed)return;w=sky.clientWidth;
      var cols=w<430?Math.min(2,rows.length):Math.min(rows.length,4),lines=Math.ceil(rows.length/(cols||1));
      h=Math.max(sky.clientHeight,lines*100);canvas.style.height=targets.style.height=h+'px';
      var dpr=Math.min(devicePixelRatio||1,2);canvas.width=Math.round(w*dpr);canvas.height=Math.round(h*dpr);if(ctx)ctx.setTransform(dpr,0,0,dpr,0,0);
      rows.forEach(function(c,i){var col=i%cols,line=Math.floor(i/cols),inLine=Math.min(cols,rows.length-line*cols),cellW=w/inLine,cellH=h/lines;
        c.x=(col+.5)*cellW;c.y=(line+.43)*cellH+(lines===1?Math.sin(i*2)*h*.08:0);
        var limit=Math.max(12,Math.min(cellW*.34,cellH*.37));c.r=Math.min(limit,limit*(.38+Math.sqrt(Math.min(c.count||0,30)/30)*.62));
        Object.assign(c.button.style,{left:c.x/w*100+'%',top:c.y/h*100+'%',width:Math.max(44,c.r*2+22)+'px',height:Math.max(44,c.r*1.4+28)+'px'});
      });draw();
    }
    function running(){return !disposed&&!document.hidden&&!motion.matches&&!paused&&rows.length>0&&panel.isConnected;}
    function tick(now){raf=0;if(!running())return;if(!last)last=now;if(now-last>=40){time+=Math.min((now-last)/1000,.1);last=now;draw();}raf=requestAnimationFrame(tick);}
    function sync(){if(raf)cancelAnimationFrame(raf);raf=0;last=0;panel.dataset.motion=running()?'running':'paused';toggle.textContent=paused?'Resume motion':'Pause motion';toggle.disabled=motion.matches;toggle.setAttribute('aria-pressed',String(paused||motion.matches));if(motion.matches)toggle.textContent='Motion reduced';if(running())raf=requestAnimationFrame(tick);else draw();}
    toggle.addEventListener('click',function(){paused=!paused;motionPaused=paused;sync();});document.addEventListener('visibilitychange',sync);motion.addEventListener('change',sync);
    var observer=new ResizeObserver(resize);observer.observe(sky);resize();sync();
    return function(){disposed=true;if(raf)cancelAnimationFrame(raf);observer.disconnect();document.removeEventListener('visibilitychange',sync);motion.removeEventListener('change',sync);ctx?.clearRect(0,0,w,h);rows=[];};
  }};
})();
