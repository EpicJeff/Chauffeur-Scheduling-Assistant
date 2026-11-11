// Compact ownership history. Delta chart indices and three slot bits per entry
// keep the full house well inside the existing 1 MiB manifest limit.
export function encodeSlots(slots, charts) {
  const lights=Object.create(null);
  for (const device of Object.keys(slots).sort()) {
    const assignments=slots[device].assignments;
    if (!assignments) continue;
    const bytes=[];let last=-1;
    for (const a of assignments) {
      let value=(a.chart-last)*8+a.bank*2+a.channel;last=a.chart;
      while (value>=128) {bytes.push(value%128+128);value=Math.floor(value/128);}
      bytes.push(value);
    }
    const parts=[];
    for(let i=0;i<bytes.length;i+=8192) parts.push(String.fromCharCode(...bytes.slice(i,i+8192)));
    lights[device]=btoa(parts.join(''));
  }
  return {version:1,charts,lights};
}

export function decodeSlots(history, charts) {
  const result=new Map();
  if (!history) return result;
  const invalid=()=>{throw new Error('Invalid lightmap ownership history.');};
  if(history.version!==1 || history.charts!==charts || !history.lights ||
    typeof history.lights!=='object' || Array.isArray(history.lights)) invalid();
  let encoded=0;
  for(const [device,text] of Object.entries(history.lights)) {
    if(typeof text!=='string' || (encoded+=text.length)>1024*1024) invalid();
    let bytes;try{bytes=atob(text);}catch{invalid();}
    let last=-1,value=0,multiplier=1;
    for(let i=0;i<bytes.length;i++) {
      const byte=bytes.charCodeAt(i);value+=(byte%128)*multiplier;
      if(byte>=128) {multiplier*=128;if(multiplier>2**28) invalid();continue;}
      const delta=Math.floor(value/8),slot=value%8,chart=last+delta;
      if(delta<1 || slot>5 || chart>=charts) invalid();
      if(!result.has(chart)) result.set(chart,new Map());
      const row=result.get(chart);
      if([...row.values()].includes(slot)) invalid();
      row.set(device,slot);last=chart;value=0;multiplier=1;
    }
    if(multiplier!==1) invalid();
  }
  return result;
}

export function sameSlots(a,b) {
  return JSON.stringify(a)===JSON.stringify(b);
}
