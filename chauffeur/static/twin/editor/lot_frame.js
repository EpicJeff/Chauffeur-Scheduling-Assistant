import { contains } from '../twin_generator.js';

const rotate = (p, degrees) => {
  const a = degrees * Math.PI / 180;
  return [p[0] * Math.cos(a) - p[1] * Math.sin(a), p[0] * Math.sin(a) + p[1] * Math.cos(a), ...p.slice(2)];
};

// The optional third coordinate retains the clipboard's existing behaviour.
// These transforms do not add a building's base or a level's floor height.
export const toLot = (b, p) => rotate(p, b?.rotation || 0).map((v, i) => v + (b?.position?.[i] || 0));
export const toLocal = (b, p) => rotate(p.map((v, i) => v - (b?.position?.[i] || 0)), -(b?.rotation || 0));

export function hostedAt(b, host, at) {
  if (host.ground) return { ...host, at: at.slice(0, 2) };
  if (host.wall || host.roof) {
    const w = b.walls.find(w => w.id === host.wall), roof = b.roofs?.find(r => r.id === host.roof);
    const a = w?.from || roof?.area?.[host.edge], z = w?.to || roof?.area?.[(host.edge + 1) % roof.area.length];
    if (!a || !z) throw new Error('The original host is gone. Choose a surface first.');
    const d = z.map((v, i) => v - a[i]), n = Math.hypot(...d);
    return { ...host, at: d.reduce((sum, v, i) => sum + v * (at[i] - a[i]) / n, 0) };
  }
  const room = b.rooms.find(r => r.id === (host.floor || host.ceiling));
  if (!room || !contains(room.polygon, at)) throw new Error('The copied piece does not fit on that floor.');
  const lo = [0, 1].map(i => Math.min(...room.polygon.map(p => p[i]))), hi = [0, 1].map(i => Math.max(...room.polygon.map(p => p[i])));
  return { ...host, u: (at[0] - lo[0]) / (hi[0] - lo[0]), v: (at[1] - lo[1]) / (hi[1] - lo[1]) };
}
