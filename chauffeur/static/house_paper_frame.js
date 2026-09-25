/* Extend photographed paper and straight rails without stretching hardware. */
window.chfPaperFrame = function (plane, controls, img, frame, paper, raisedClip) {
  var host=plane.querySelector('.house-paper-frame');
  if(!img){
    if(host)host.hidden=true;
    plane.querySelectorAll(':scope > picture > img').forEach(function(el){el.style.cssText='';});
    return;
  }
  if(!host){
    host=document.createElement('div');host.className='house-paper-frame';
    host.setAttribute('aria-hidden','true');
    Object.assign(host.style,{position:'absolute',pointerEvents:'none'});
    for(var n=0;n<15;n++){
      var tile=document.createElement('div'),photo=document.createElement('img');
      Object.assign(tile.style,{position:'absolute',overflow:'hidden'});
      Object.assign(photo.style,{position:'absolute',maxWidth:'none',pointerEvents:'none'});
      photo.alt='';tile.appendChild(photo);host.appendChild(tile);
    }
    plane.insertBefore(host,controls);
  }
  host.hidden=false;
  host.style.clipPath=raisedClip?'polygon(0 35px,calc(50% - 92px) 35px,calc(50% - 30px) 0,calc(50% + 30px) 0,calc(50% + 92px) 35px,100% 35px,100% 100%,0 100%)':'none';
  var x=20,y=76,w=innerWidth-40,h=innerHeight-172;
  Object.assign(plane.style,{width:innerWidth+'px',height:innerHeight+'px'});
  plane.parentElement.scrollLeft=0;plane.parentElement.scrollTop=0;
  var cover=Math.max(innerWidth/1536,innerHeight/1024);
  plane.querySelectorAll(':scope > picture > img').forEach(function(el){
    Object.assign(el.style,{width:1536*cover+'px',height:1024*cover+'px',left:(innerWidth-1536*cover)/2+'px',top:(innerHeight-1024*cover)/2+'px'});
  });
  Object.assign(host.style,{left:x+'px',top:y+'px',width:w+'px',height:h+'px'});
  var left=paper[0]-frame[0],right=frame[0]+frame[2]-paper[0]-paper[2];
  var top=paper[1]-frame[1],bottom=frame[1]+frame[3]-paper[1]-paper[3];
  // A fixed center column also protects the clipboard's brass clip.
  var center=frame[0]+frame[2]/2;
  var sx=[frame[0],paper[0],center-110,center+110,paper[0]+paper[2],frame[0]+frame[2]];
  var sy=[frame[1],paper[1],paper[1]+paper[3],frame[1]+frame[3]];
  var dx=[0,left,w/2-110,w/2+110,w-right,w],dy=[0,top,h-bottom,h];
  var src=img.parentElement.querySelector('source').srcset;
  for(var row=0;row<3;row++)for(var col=0;col<5;col++){
    var tile=host.children[row*5+col],photo=tile.firstChild;
    // Keep the blank center continuous across its three tiles.
    var tx=row===1?[0,left,left+(sx[2]-paper[0])*(w-left-right)/paper[2],left+(sx[3]-paper[0])*(w-left-right)/paper[2],w-right,w]:dx;
    var width=tx[col+1]-tx[col],height=dy[row+1]-dy[row];
    var zx=width/(sx[col+1]-sx[col]),zy=height/(sy[row+1]-sy[row]);
    Object.assign(tile.style,{left:tx[col]+'px',top:dy[row]+'px',width:width+'px',height:height+'px'});
    Object.assign(photo.style,{width:1536*zx+'px',height:1024*zy+'px',left:-sx[col]*zx+'px',top:-sy[row]*zy+'px'});
    if(photo.getAttribute('src')!==src)photo.src=src;
  }
  Object.assign(controls.style,{left:x+left+'px',top:y+top+'px',width:w-left-right+'px',height:h-top-bottom+'px'});
  controls.style.setProperty('--read-width',w-left-right+'px');
  controls.style.setProperty('--read-height',h-top-bottom+'px');
};
