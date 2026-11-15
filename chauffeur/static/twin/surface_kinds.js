import * as THREE from 'three';

// Code-side looks: these retain the generator and yard's existing defaults.
export const BUILTIN_LOOKS = {
  glass: { color: '#b9d7db', transparent: true, opacity: 0.26, roughness: 0.1, depthWrite: false },
  screen: { color: '#59615d', transparent: true, opacity: 0.3, depthWrite: false, doubleSide: true },
  water: { color: '#7fd0e6', transparent: true, opacity: 0.65, roughness: 0.12, depthWrite: false },
};

export function builtinMaterial(id, name = id) {
  const { doubleSide, ...params } = BUILTIN_LOOKS[id];
  const material = new THREE.MeshStandardMaterial({
    name, roughness: 0.8, ...params, side: doubleSide ? THREE.DoubleSide : THREE.FrontSide,
  });
  material.userData.alphaMode = 'blend';
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
    "door"
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
