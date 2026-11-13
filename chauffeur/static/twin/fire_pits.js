import { inPolygon } from './twin_ground.js';
import { simpleOutline } from './path_shapes.js';

export const roundPit = pit => (pit.shape || 'round') === 'round';
export function placedPit(shape, at, options = {}) {
  if (shape === 'round') return { shape, at, radius: options.radius ?? 2 };
  const width = shape === 'square' ? options.side ?? 4 : options.width ?? 4;
  const depth = shape === 'square' ? width : options.depth ?? 6;
  const [x, y] = at;
  return { shape, polygon: [[x-width/2, y-depth/2], [x+width/2, y-depth/2], [x+width/2, y+depth/2], [x-width/2, y+depth/2]] };
}
export function firePitOutline(pit) {
  return roundPit(pit) ? Array.from({ length: 24 }, (_, i) => {
    const angle = i * Math.PI / 12 + (pit.rotation || 0) * Math.PI / 180;
    return [pit.at[0] + (pit.radius ?? 2) * Math.cos(angle), pit.at[1] + (pit.radius ?? 2) * Math.sin(angle)];
  }) : pit.polygon;
}
export function firePitRings(pit) {
  let outer = firePitOutline(pit);
  const area = outer.reduce((s, p, i) => s + p[0]*outer[(i+1)%outer.length][1] - p[1]*outer[(i+1)%outer.length][0], 0);
  if (area < 0) outer = [...outer].reverse();
  const edge = (a, b) => { const x=b[0]-a[0], y=b[1]-a[1], l=Math.hypot(x,y); return [x/l,y/l]; };
  const inside = point => inPolygon(outer, ...point);
  // Keep the inset inside concave outlines too. Narrow necks reduce the wall
  // thickness rather than letting the bowl poke through a neighbouring wall.
  for (let width = .35, attempt = 0; attempt < 32; attempt++, width /= 2) {
    const inner = outer.map((p, i) => {
      const a=edge(outer[(i+outer.length-1)%outer.length],p), b=edge(p,outer[(i+1)%outer.length]);
      const den=1+a[0]*b[0]+a[1]*b[1];
      return den > 1e-10 ? [p[0]-(a[1]+b[1])*width/den,p[1]+(a[0]+b[0])*width/den] : [p[0]-b[1]*width,p[1]+b[0]*width];
    });
    if (simpleOutline(inner) && inner.every((p,i) => inside(p) && inside(p.map((v,k)=>(v+inner[(i+1)%inner.length][k])/2)))) return { outer, inner };
  }
  return { outer, inner: [] };
}
