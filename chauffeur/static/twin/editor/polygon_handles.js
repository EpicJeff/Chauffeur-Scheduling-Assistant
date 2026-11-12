// One vertex editor for terrace pads, authored yard polygons and open fences.
export function vertexHandles(points, closed = true) {
  return points.flatMap((at, index) => {
    const next = points[(index + 1) % points.length];
    return [{ at, index }, ...(closed || index < points.length - 1
      ? [{ at: at.map((v, i) => (v + next[i]) / 2), index, insert: true }] : [])];
  });
}

export function editVertex(points, handle, point, { remove = false, closed = true } = {}) {
  const result = points.map(p => [...p]);
  if (remove) {
    if (handle.insert || result.length <= (closed ? 3 : 2)) return result;
    result.splice(handle.index, 1);
  } else if (handle.insert) result.splice(handle.index + 1, 0, [...point]);
  else result[handle.index] = [...point];
  return result;
}
