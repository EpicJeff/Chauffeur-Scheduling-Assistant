// Resolve flat-model hosts in building-local feet: x, y, then height.
// Keep these rules in step with services/twin_model_hosts.world_point.
// Outdoor parking follows the lot surface rather than the building platform.
import { buildingBase } from './twin_ground.js';
export function parkingPoint(building, piece, plan, offset = 0, groundAt = () => 0) {
  const point=hostPoint(building,piece.host,offset);
  if(piece.host.ground){
    const a=(building.rotation || 0)*Math.PI/180,p=building.position || [0,0];
    const x=p[0]+Math.cos(a)*point[0]-Math.sin(a)*point[1],y=p[1]+Math.sin(a)*point[0]+Math.cos(a)*point[1];
    point[2]+=groundAt(plan,x,y)-buildingBase(plan,building);
  }
  return point;
}
export function hostPoint(building, host, offset = 0) {
  if (host.ground === true) return [...host.at, offset];
  const wall = (building.walls || []).find(w => w.id === host.wall && w.state !== 'ghost');
  const room = (building.rooms || []).find(r => r.id === (host.floor ?? host.ceiling) && r.state !== 'ghost');
  const roof = (building.roofs || []).find(r => r.id === host.roof && r.state !== 'ghost');
  const surface = 'wall' in host ? wall : 'floor' in host || 'ceiling' in host ? room : roof;
  if (!surface) throw new Error('The host surface is missing.');
  const level = (building.levels || []).find(l => l.id === surface.level) || {};
  const elevation = level.elevation || 0;
  if (room && ('floor' in host || 'ceiling' in host)) {
    const xs = room.polygon.map(p => p[0]), ys = room.polygon.map(p => p[1]);
    const x0 = Math.min(...xs), y0 = Math.min(...ys);
    return [x0 + host.u * (Math.max(...xs) - x0), y0 + host.v * (Math.max(...ys) - y0),
      'ceiling' in host ? elevation + (level.ceiling || 0) - offset : elevation + offset];
  }
  let a, b;
  if (wall) [a, b] = [wall.from, wall.to];
  else if (Number.isInteger(host.edge) && host.edge >= 0 && host.edge < roof.area.length)
    [a, b] = [roof.area[host.edge], roof.area[(host.edge + 1) % roof.area.length]];
  if (!a || !b) throw new Error('The host surface has no length.');
  const length = Math.hypot(b[0] - a[0], b[1] - a[1]);
  if (!length) throw new Error('The host surface has no length.');
  const dx = (b[0] - a[0]) / length, dy = (b[1] - a[1]) / length;
  let x = a[0] + dx * host.at, y = a[1] + dy * host.at;
  if (wall) {
    if (['left', 'right'].includes(host.side)) {
      const distance = ((wall.thickness || 0) / 2 + offset) * (host.side === 'left' ? 1 : -1);
      x -= dy * distance; y += dx * distance;
    }
    return [x, y, elevation + (host.sill ?? host.z ?? 0)];
  }
  return [x, y, (roof.plate || 0) + (host.z || 0) + offset];
}
