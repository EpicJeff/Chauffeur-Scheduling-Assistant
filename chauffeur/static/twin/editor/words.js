export function sentence(text, fallback = '') {
  const words = String(text || fallback).trim().replace(/[.!?]+$/, '');
  return words ? words[0].toUpperCase() + words.slice(1) + '.' : '';
}

export function confidenceWords(value) {
  return Number(value) >= .8 ? 'I am sure' : Number(value) >= .5 ? 'I am fairly sure' : 'I am unsure';
}

export function pauseWords(pause) {
  return `${sentence(pause.why, 'This is the outline I read from your drawing')} ${sentence(confidenceWords(pause.confidence))}`;
}

export function sheetMaster(sheets, source, page) {
  return sheets.pages?.find(p => p.source === source && p.page === page)?.master_size
    || sheets.registrations?.find(p => p.source === source && p.page === page)?.master_size
    || sheets.page_roles?.find(p => p.source === source && p.page === page)?.master_size || null;
}

export function localCentre(building) {
  const points = building.walls.flatMap(w => [w.from, w.to]);
  if (!points.length) points.push(...building.levels.flatMap(l => l.outline || []));
  return points.length ? [0, 1].map(i => (Math.min(...points.map(p => p[i])) + Math.max(...points.map(p => p[i]))) / 2) : [0, 0];
}

// Same fixed local point and position compensation as twin_edit's rotate/about.
export function turnPlacement(building, to, about = localCentre(building)) {
  const rotated = degrees => {
    const a = degrees * Math.PI / 180;
    return [Math.cos(a) * about[0] - Math.sin(a) * about[1], Math.sin(a) * about[0] + Math.cos(a) * about[1]];
  };
  const before = rotated(building.rotation || 0), after = rotated(to);
  return { rotation: to, position: (building.position || [0, 0]).map((v, i) => v + before[i] - after[i]) };
}
