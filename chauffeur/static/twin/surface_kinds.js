import * as THREE from 'three';

// Code-side looks: these retain the generator and yard's existing defaults.
export const BUILTIN_LOOKS = {
  glass: { color: '#b9d7db', transparent: true, opacity: 0.26, roughness: 0.1, depthWrite: false },
  screen: { color: '#59615d', transparent: true, opacity: 0.3, depthWrite: false, doubleSide: true },
  water: { color: '#7fd0e6', transparent: true, opacity: 0.65, roughness: 0.12, depthWrite: false },
  chain_link: { color: '#9da5a8', opacity: 1, roughness: 0.45, metalness: 0.65, alphaTest: 0.5, doubleSide: true },
  // Powder coat is a paint film over the metal, so it shades as a dielectric.
  black_metal: { color: '#1b1c1e', opacity: 1, roughness: 0.42, metalness: 0 },
};

export const builtinAlphaMode = id => BUILTIN_LOOKS[id].alphaTest > 0 ? 'cutout' : BUILTIN_LOOKS[id].transparent ? 'blend' : 'opaque';

export function builtinMaterial(id, name = id) {
  const { doubleSide, ...params } = BUILTIN_LOOKS[id];
  const material = new THREE.MeshStandardMaterial({
    name, roughness: 0.8, ...params, side: doubleSide ? THREE.DoubleSide : THREE.FrontSide,
  });
  material.userData.alphaMode = builtinAlphaMode(id);
  material.userData.bakeMaterialId = id;
  if (id === 'chain_link') {
    const size = 128, pixels = new Uint8Array(size * size * 4);
    for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
      const diagonal = Math.min((x + y) % size, size - (x + y) % size, Math.abs(x - y), size - Math.abs(x - y));
      const wire = diagonal < 3 ? 255 : 0, at = (y * size + x) * 4;
      pixels.set([wire, wire, wire, 255], at);
    }
    const mask = new THREE.DataTexture(pixels, size, size);
    mask.name = 'generated chain link: 2in diamonds';
    mask.wrapS = mask.wrapT = THREE.RepeatWrapping; mask.repeat.set(6, 6); mask.needsUpdate = true;
    mask.magFilter = THREE.LinearFilter; mask.minFilter = THREE.LinearMipmapLinearFilter; mask.generateMipmaps = true;
    material.alphaMap = mask;
    material.addEventListener('dispose', () => mask.dispose());
  }
  return material;
}

export const KINDS = [
  {
    "kind": "trim",
    "label": "Trim",
    "scope": "building",
    "fallback": {
      "role": "trim"
    },
    "item": null
  },
  {
    "kind": "fascia",
    "label": "Fascia",
    "scope": "building",
    "fallback": {
      "role": "trim"
    },
    "item": null
  },
  {
    "kind": "casing",
    "label": "Casing",
    "scope": "building",
    "fallback": {
      "role": "trim"
    },
    "item": "opening"
  },
  {
    "kind": "window_frame",
    "label": "Window frames",
    "scope": "building",
    "fallback": {
      "role": "window_frame"
    },
    "item": "opening"
  },
  {
    "kind": "pane",
    "label": "Panes",
    "scope": "building",
    "fallback": {
      "builtin": "glass"
    },
    "item": "opening"
  },
  {
    "kind": "door",
    "label": "Doors",
    "scope": "building",
    "fallback": {
      "role": "door"
    },
    "item": "opening"
  },
  {
    "kind": "garage_door",
    "label": "Garage door",
    "scope": "building",
    "fallback": { "role": "door" },
    "item": "opening"
  },
  {
    "kind": "column",
    "label": "Columns",
    "scope": "building",
    "fallback": {
      "role": "trim"
    },
    "item": "porch"
  },
  {
    "kind": "screen",
    "label": "Screens",
    "scope": "building",
    "fallback": {
      "builtin": "screen"
    },
    "item": "porch"
  },
  {
    "kind": "soffit",
    "label": "Soffit",
    "scope": "building",
    "fallback": {
      "role": "porch_ceiling"
    },
    "item": null
  },
  {
    "kind": "base",
    "label": "Foundation",
    "scope": "building",
    "fallback": {
      "role": "base"
    },
    "item": null
  },
  {
    "kind": "stair_tread",
    "label": "Stair treads",
    "scope": "building",
    "fallback": {
      "role": "floor"
    },
    "item": "stair"
  },
  {
    "kind": "stair_rail",
    "label": "Stair rails",
    "scope": "building",
    "fallback": {
      "role": "porch_ceiling"
    },
    "item": "stair"
  },
  {
    "kind": "ceiling",
    "label": "Ceilings",
    "scope": "building",
    "fallback": {
      "look": "ceiling"
    },
    "item": "room"
  },
  {
    "kind": "roof",
    "label": "Roof",
    "scope": "building",
    "fallback": {
      "role": "roof"
    },
    "item": "roof"
  },
  {
    "kind": "cabinet",
    "label": "Cabinets",
    "scope": "building",
    "fallback": {
      "look": "cabinet"
    },
    "item": "fixture"
  },
  {
    "kind": "counter",
    "label": "Counters",
    "scope": "building",
    "fallback": {
      "look": "counter"
    },
    "item": "fixture"
  },
  {
    "kind": "shower_tile",
    "label": "Shower tile",
    "scope": "building",
    "fallback": {
      "look": "ceramic"
    },
    "item": "fixture"
  },
  {
    "kind": "shower_glass",
    "label": "Shower glass",
    "scope": "building",
    "fallback": {
      "builtin": "glass"
    },
    "item": "fixture"
  },
  {
    "kind": "lawn",
    "label": "Lawn",
    "scope": "site",
    "fallback": {
      "role": "lawn"
    },
    "item": null
  },
  {
    "kind": "water",
    "label": "Water",
    "scope": "site",
    "fallback": {
      "builtin": "water"
    },
    "item": "pool"
  }
];

export const PANEL_ROLES = [
  "siding",
  "interior_wall",
  "floor"
];

export const ITEM_PARTS = {
  "opening": [
    "casing",
    "window_frame",
    "pane",
    "door",
    "garage_door"
  ],
  "porch": [
    "column",
    "screen"
  ],
  "stair": [
    "stair_tread",
    "stair_rail"
  ],
  "fixture": [
    "cabinet",
    "counter",
    "shower_tile",
    "shower_glass"
  ],
  "pool": [
    "water"
  ],
  "spa": [
    "water"
  ]
};

export const kindRow = kind => KINDS.find(row => row.kind === kind);

export function resolveSlot(kind, { item = null, building = null, level = null } = {}) {
  return item?.materials?.[kind] ?? level?.materials?.[kind] ?? building?.materials?.[kind] ?? null;
}
