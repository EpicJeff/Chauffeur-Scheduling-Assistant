// Editor tools share one 24px, currentColor SVG vocabulary. No font or runtime package.
const paths = {
  menu: 'M4 6h16M4 12h16M4 18h16',
  select: 'm5 3 14 9-7 1-3 7Z',
  move: 'M12 3v18M3 12h18m-12-6 3-3 3 3m-6 12 3 3 3-3M6 9l-3 3 3 3m12-6 3 3-3 3',
  rotate: 'M4 10a8 8 0 1 1 1 8M4 4v6h6',
  scale: 'M4 14v6h6m4-16h6v6M4 20l7-7m2-2 7-7',
  'draw-wall': 'M4 4h16v16H4ZM4 12h16M12 4v8M8 12v8m8-8v8',
  'draw-room': 'M4 4h16v16H4ZM4 15h5v5',
  'split-room': 'M4 4h16v16H4ZM12 4v16',
  'add-door': 'M5 21V4l10-2v19Zm10-17h4v17M11 12h.01',
  'add-window': 'M4 4h16v16H4ZM12 4v16M4 12h16',
  'add-stair': 'M3 20h5v-5h5v-5h5V5h3',
  'add-level': 'm3 8 9-5 9 5-9 5Zm0 8 9 5 9-5M3 12l9 5 9-5',
  roof: 'm2 12 10-9 10 9M5 10v10h14V10',
  chevron: 'm6 9 6 6 6-6',
  'add-solar-zone': 'M5 4h14l3 14H2Zm7 0v14M4 11h16M8 22h8m-4-4v4',
  ground: 'm2 19 6-9 5 5 4-11 5 15ZM3 22h18',
  'add-effect': 'M12 3c0 6 7 7 7 12a7 7 0 0 1-14 0c0-3 2-5 4-6-1 4 3 4 3 1Z',
  'add-anchor': 'M9 3v6m6-6v6M6 9h12v4a6 6 0 0 1-12 0Zm6 10v3',
  equipment: 'M4 4h16v16H4ZM8 8h8M8 12h3m-3 4h8',
  'add-meter': 'M4 4h16v16H4ZM7 13a5 5 0 0 1 10 0m-5 0 3-4',
  'add-electric-panel': 'M5 2h14v20H5Zm8 4-4 6h6l-4 6',
  'add-charger': 'M5 3h10v18H5ZM8 7h4m3 2h3l3 3v6a2 2 0 0 1-4 0v-3h-2',
  'add-parking': 'M5 3h14v18H5Zm5 14V7h3a3 3 0 0 1 0 6h-3',
  measure: 'm3 16 13-13 5 5L8 21Zm4-4 3 3m1-7 3 3m1-7 3 3',
  delete: 'M3 6h18M8 6V3h8v3M5 6l1 15h12l1-15M10 10v7m4-7v7',
  undo: 'M3 10h11a6 6 0 0 1 0 12M3 10l6-6m-6 6 6 6',
  redo: 'M21 10H10a6 6 0 0 0 0 12m11-12-6-6m6 6-6 6',
  sheet: 'M5 2h10l4 4v16H5Zm10 0v5h4M8 11h8m-8 4h8m-8 4h5',
  library: 'M2 3h5v18H2Zm7 0h5v18H9Zm7 1 4-1 3 17-4 1Z',
  floor: 'm3 7 9-4 9 4-9 4Zm0 5 9 4 9-4M3 17l9 4 9-4',
  view: 'm12 2 9 5v10l-9 5-9-5V7Zm0 10 9-5m-9 5L3 7m9 5v10',
  eye: 'M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12ZM15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0',
};

export function icon(name) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  for (const [key, value] of Object.entries({ viewBox: '0 0 24 24', width: '20', height: '20', fill: 'none',
    stroke: 'currentColor', 'stroke-width': '1.75', 'stroke-linecap': 'round', 'stroke-linejoin': 'round',
    'aria-hidden': 'true', focusable: 'false' })) svg.setAttribute(key, value);
  const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  path.setAttribute('d', paths[name] || paths.select); svg.append(path); return svg;
}

export function mountIcons(host) {
  host?.querySelectorAll('[data-editor-icon]').forEach(node => {
    if (!node.querySelector('svg')) node.prepend(icon(node.dataset.editorIcon));
  });
}
