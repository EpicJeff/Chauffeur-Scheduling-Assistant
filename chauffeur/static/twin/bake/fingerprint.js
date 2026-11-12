// Streaming geometry identity, shared by atlas and local reach keys.
const encoder=new TextEncoder();
export function fingerprint() {
  let a=0x811c9dc5,b=0x9e3779b9,c=0x85ebca6b,d=0xc2b2ae35;
  return {
    add(value) {
      // Chart keys and numeric JSON are ASCII. Avoid a short-lived encoded
      // buffer for every chart contribution; keep UTF-8 for arbitrary text.
      if (typeof value==='string' && /^[\x00-\x7f]*$/.test(value)) {
        for (let i=0;i<value.length;i++) {
          const x=value.charCodeAt(i);
          a=Math.imul(a^x,0x01000193); b=Math.imul(b^x,0x01000195);
          c=Math.imul(c^x,0x01000197); d=Math.imul(d^x,0x01000199);
        }
        return;
      }
      const bytes=typeof value==='string' ? encoder.encode(value) : new Uint8Array(value.buffer,value.byteOffset,value.byteLength);
      for (let i=0;i<bytes.length;i++) {
        const x=bytes[i];
        a=Math.imul(a^x,0x01000193); b=Math.imul(b^x,0x01000195);
        c=Math.imul(c^x,0x01000197); d=Math.imul(d^x,0x01000199);
      }
    },
    key:()=>[a,b,c,d].map(x=>(x>>>0).toString(16).padStart(8,'0')).join(''),
  };
}
