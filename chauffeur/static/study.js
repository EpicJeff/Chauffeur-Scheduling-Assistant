/* The Study — a living office. Read-only lens; see
   docs/superpowers/specs/2026-09-03-argyle-study-design.md.

   Structure:
   1. capability gate: no WebGL or viewport < 900px -> fallback list
   2. canvas textures (wood, floor planks, cork, plaster, rug, sky day/night)
   3. geometry helpers: M(color, opts), box(), rbox() rounded-extrude, put()
   4. static room build — every live mesh registered in ZONES
   5. FURNITURE: declarative state->scene mutations
   6. applyState(payload) — the ONLY place the scene reads data

   Two rules the whole file obeys: the room NEVER writes (no POST anywhere,
   ever), and every mesh a signal can touch is built once, up front, then
   only shown/hidden/coloured/moved. applyState allocates no geometry.
*/
(function () {
  'use strict';
  const room = document.getElementById('room');
  const fallback = document.getElementById('fallback');

  function webglOk() {
    try { const c = document.createElement('canvas');
      return !!(c.getContext('webgl2') || c.getContext('webgl')); }
    catch (e) { return false; }
  }
  const useRoom = webglOk() && Math.min(innerWidth, innerHeight) >= 560 && innerWidth >= 900;

  // Every link this file follows is RELATIVE on purpose. Under Home Assistant
  // ingress the whole app is served beneath /api/hassio_ingress/<token>/, so
  // an absolute '/mind' walks straight out of the add-on -- the same reasoning
  // as nav.html's `_up`. /study is one path segment, so dropping the leading
  // slash is all the climbing this page ever needs.
  const rel = u => String(u || '').replace(/^\//, '');
  const go = u => { location.href = rel(u); };

  // The only chrome this file builds itself: a small fixed chip saying the
  // house is unreachable. Shown ONCE per outage (not once per retry) and
  // cleared the moment a poll answers. Never a dialog.
  let outageEl = null, outageShown = false;
  function showOutage() {
    if (outageShown) return;
    outageShown = true;
    if (!outageEl) {
      outageEl = document.createElement('div');
      outageEl.id = 'study-outage';
      outageEl.textContent = "can't reach the house right now";
      outageEl.style.cssText = 'position:fixed;right:14px;bottom:18px;z-index:50;' +
        'background:rgba(42,27,20,.94);color:#e8c9a8;border:1px solid #7a4a34;' +
        'border-radius:9px;padding:6px 11px;font:13px system-ui;opacity:0;' +
        'transition:opacity .25s;pointer-events:none';
      document.body.appendChild(outageEl);
    }
    requestAnimationFrame(() => { if (outageEl) outageEl.style.opacity = '1'; });
  }
  function clearOutage() {
    outageShown = false;
    if (outageEl) outageEl.style.opacity = '0';
  }

  // The calm form of every section, client side. A payload that is missing a
  // section (older server, half-written cache) renders that furniture tidy
  // rather than throwing and taking the whole room down with it — the same
  // Law 2 the aggregator keeps on the server.
  const CALM = {
    board: { pins: [], strings: [] },
    desk: [],
    tray: { count: 0 },
    stickies: { count: 0, worst: null },
    calendar: { days: [] },
    window: { ready: false, worse: [], label: '' },
    keys: [],
    contracts: { count: 0 },
    binders: [],
    gauges: { think: null, think_cap: null, research: null,
              research_cap: null, ingest_errors: 0 }
  };
  function normal(f) {
    const o = {};
    Object.keys(CALM).forEach(k => {
      o[k] = (f && f[k] !== undefined && f[k] !== null) ? f[k] : CALM[k];
    });
    return o;
  }

  // ---- fallback list: the same payload, ranked, honest ----
  function renderFallback(f) {
    f = normal(f);
    const rows = [];
    const cal = (f.calendar.days || []).filter(d => d.unassigned > 0);
    if (cal.length) rows.push(['/dashboard', 'This week',
      cal.map(d => `${d.date}: ${d.unassigned} uncovered`).join(' · '), false]);
    (f.board.pins || []).forEach(p => rows.push(
      ['/mind', p.kind === 'insight' ? 'Argyle noticed' : 'Thread',
       p.label, !p.warn && !p.bad]));
    f.desk.forEach(d => rows.push(['/mind', 'Plan in hand',
      `${d.open_steps} open step${d.open_steps === 1 ? '' : 's'}${d.due ? ' — one due' : ''}`, !d.due]));
    if (f.tray.count) rows.push(['/intake', 'Intake', `${f.tray.count} waiting`, false]);
    if (f.stickies.count) rows.push(['/dashboard', 'Findings',
      `${f.stickies.count} open (${f.stickies.worst || 'low'})`, false]);
    f.keys.filter(k => k.low).forEach(k => rows.push(['/config#cars', 'Car', `${k.name} low`, false]));
    if (f.contracts.count) rows.push(['/dashboard', 'Deals', `${f.contracts.count} awaiting answers`, false]);
    f.binders.filter(b => b.pulled).forEach(b => rows.push(['/programs', 'Program', `${b.title} needs a look`, false]));
    if (!rows.length) rows.push(['', 'All quiet', 'Nothing needs you right now.', true]);
    document.getElementById('fallback-rows').innerHTML = rows.map(([href, kind, sig, calm]) =>
      `<a class="frow${calm ? ' calm' : ''}" ${href ? `href="${rel(href)}"` : ''}>` +
      `<strong>${kind}</strong><div class="sig"></div></a>`).join('');
    [...document.querySelectorAll('#fallback-rows .sig')].forEach((el, i) => el.textContent = rows[i][2]);
  }

  async function poll(apply) {
    try {
      const r = await fetch(window.STUDY_STATE_URL);
      if (!r.ok) throw new Error(r.status);
      apply((await r.json()).furniture);
      clearOutage();
    } catch (e) { showOutage(); /* next poll retries; the room stays calm */ }
    setTimeout(() => poll(apply), 60000);
  }

  if (!useRoom) { fallback.style.display = 'block'; poll(renderFallback); return; }

  // =====================================================================
  // 2. canvas textures
  // =====================================================================
  // Deterministic noise: the room is drawn the same way every load, so a
  // screenshot is reproducible and nothing shuffles under a poll.
  let _seed = 20260903;
  function rnd() { _seed = (_seed * 1664525 + 1013904223) % 4294967296; return _seed / 4294967296; }

  function canvasTex(draw, w, h) {
    const c = document.createElement('canvas');
    c.width = w || 256; c.height = h || 256;
    draw(c.getContext('2d'), c.width, c.height);
    const t = new THREE.CanvasTexture(c);
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    // Colour maps are authored in sRGB. Without this the whole room renders
    // muddy — half the spike's washed-out grade was this one missing line.
    t.encoding = THREE.sRGBEncoding;
    return t;
  }

  const woodTex = canvasTex((g, w, h) => {
    g.fillStyle = '#b3814c'; g.fillRect(0, 0, w, h);
    for (let i = 0; i < 70; i++) {
      g.strokeStyle = `rgba(${90 + rnd() * 40 | 0},${52 + rnd() * 25 | 0},22,${.10 + rnd() * .14})`;
      g.lineWidth = 1 + rnd() * 2.5; g.beginPath(); const y = rnd() * h;
      g.moveTo(0, y); g.bezierCurveTo(w * .3, y + (rnd() - .5) * 14, w * .7, y + (rnd() - .5) * 14, w, y); g.stroke();
    }
    for (let i = 0; i < 7; i++) {
      const x = rnd() * w, y = rnd() * h, r = 2 + rnd() * 4;
      g.strokeStyle = 'rgba(96,58,24,.5)'; g.beginPath(); g.ellipse(x, y, r * 2.2, r, .3, 0, 7); g.stroke();
    }
  });

  const floorTex = canvasTex((g, w, h) => {
    g.fillStyle = '#8a6337'; g.fillRect(0, 0, w, h);
    const pw = w / 4;
    for (let p = 0; p < 4; p++) {
      g.fillStyle = `rgb(${142 + rnd() * 22 | 0},${100 + rnd() * 14 | 0},${58 + rnd() * 10 | 0})`;
      g.fillRect(p * pw + 1, 0, pw - 2, h);
      for (let i = 0; i < 18; i++) {
        g.strokeStyle = 'rgba(92,58,26,.25)'; g.lineWidth = 1; g.beginPath();
        const y = rnd() * h; g.moveTo(p * pw, y); g.lineTo((p + 1) * pw, y + (rnd() - .5) * 8); g.stroke();
      }
      g.fillStyle = 'rgba(58,36,16,.7)'; g.fillRect(p * pw, 0, 2, h);
    }
  });

  const corkTex = canvasTex((g, w, h) => {
    g.fillStyle = '#b8823f'; g.fillRect(0, 0, w, h);
    for (let i = 0; i < 1400; i++) {
      g.fillStyle = `rgba(${140 + rnd() * 70 | 0},${96 + rnd() * 50 | 0},${40 + rnd() * 26 | 0},${.25 + rnd() * .4})`;
      const r = .6 + rnd() * 1.8; g.beginPath(); g.arc(rnd() * w, rnd() * h, r, 0, 7); g.fill();
    }
  });

  const plasterTex = canvasTex((g, w, h) => {
    g.fillStyle = '#9b7b57'; g.fillRect(0, 0, w, h);
    for (let i = 0; i < 2600; i++) {
      g.fillStyle = `rgba(${rnd() > .5 ? 255 : 0},${rnd() > .5 ? 230 : 20},180,${.02 + rnd() * .035})`;
      g.fillRect(rnd() * w, rnd() * h, 1.4, 1.4);
    }
  });

  const rugTex = canvasTex((g, w, h) => {
    g.fillStyle = '#6d2f33'; g.fillRect(0, 0, w, h);
    g.fillStyle = '#833a36'; g.fillRect(w * .07, h * .07, w * .86, h * .86);
    g.fillStyle = '#57262c'; g.fillRect(w * .16, h * .16, w * .68, h * .68);
    g.strokeStyle = 'rgba(235,205,160,.42)'; g.lineWidth = 3;
    g.strokeRect(w * .11, h * .11, w * .78, h * .78);
    for (let i = 0; i < 900; i++) {
      g.fillStyle = `rgba(20,10,10,${rnd() * .12})`;
      g.fillRect(rnd() * w, rnd() * h, 2, 2);
    }
  });

  function skyTexture(night) {
    const top = night ? '#0c1a34' : '#4f9bdf', bot = night ? '#1e4166' : '#cfe8ff';
    return canvasTex((g, w, h) => {
      const gr = g.createLinearGradient(0, 0, 0, h);
      gr.addColorStop(0, top); gr.addColorStop(1, bot);
      g.fillStyle = gr; g.fillRect(0, 0, w, h);
      if (night) for (let i = 0; i < 40; i++) { g.fillStyle = '#e8ecf5'; g.fillRect(rnd() * w, rnd() * h * .5, 1.6, 1.6); }
      for (let i = 0; i < 12; i++) {
        const bw = 10 + rnd() * 16, bh = 30 + rnd() * 80, x = i * (w / 12);
        g.fillStyle = night ? '#0e1c31' : '#2f6ba0'; g.fillRect(x, h - bh, bw, bh);
        g.fillStyle = night ? 'rgba(255,214,120,.92)' : 'rgba(255,255,255,.55)';
        for (let j = 0; j < 6; j++)
          if (rnd() > .5) g.fillRect(x + 2 + rnd() * (bw - 6), h - bh + 3 + rnd() * (bh - 8), 2.4, 3);
      }
      g.fillStyle = night ? '#f4f0e0' : 'rgba(255,252,225,.98)';
      g.beginPath(); g.arc(w * .78, h * .2, night ? 14 : 18, 0, 7); g.fill();
    }, 256, 200);
  }
  const skyDay = skyTexture(false), skyNight = skyTexture(true);

  const cloudTex = canvasTex((g, w, h) => {
    g.clearRect(0, 0, w, h);
    for (let i = 0; i < 26; i++) {
      const x = rnd() * w, y = h * .3 + rnd() * h * .4, r = 14 + rnd() * 26;
      g.fillStyle = `rgba(226,224,220,${.5 + rnd() * .3})`;
      g.beginPath(); g.arc(x, y, r, 0, 7); g.fill();
    }
  }, 256, 128);

  // =====================================================================
  // 3. helpers + palette
  // =====================================================================
  const PAL = {
    bg: 0x120f0c, paper: 0xf6efdd, screen: 0x86c9f2,
    pin: 0xf0e4c6, pinWarn: 0xe8a94e, pinBad: 0xdc6a55,
    string: 0xc0392b, plant: 0x4f8a37, pot: 0xc25c37, key: 0xd8c05a,
    dark: 0x28241f, wood: 0x7a5636, metal: 0x38332c, cream: 0xece2ca,
    good: 0x86cf88, cell: 0xd8cbad
  };

  const M = (c, o) => new THREE.MeshStandardMaterial(
    Object.assign({ color: c, roughness: .85, metalness: .04 }, o || {}));

  function rbox(w, h, d, r, mat) {
    const s = new THREE.Shape(), x = -w / 2, y = -h / 2;
    s.moveTo(x + r, y); s.lineTo(x + w - r, y); s.quadraticCurveTo(x + w, y, x + w, y + r);
    s.lineTo(x + w, y + h - r); s.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    s.lineTo(x + r, y + h); s.quadraticCurveTo(x, y + h, x, y + h - r);
    s.lineTo(x, y + r); s.quadraticCurveTo(x, y, x + r, y);
    const g = new THREE.ExtrudeGeometry(s, {
      depth: d, bevelEnabled: true, bevelThickness: Math.min(.02, r),
      bevelSize: Math.min(.02, r), bevelSegments: 2, curveSegments: 5
    });
    g.translate(0, 0, -d / 2);
    const m = new THREE.Mesh(g, mat);
    m.castShadow = m.receiveShadow = true;
    return m;
  }

  function put(mesh, x, y, z, o) {
    o = o || {};
    mesh.position.set(x, y, z);
    if (o.rx) mesh.rotation.x = o.rx;
    if (o.ry) mesh.rotation.y = o.ry;
    if (o.rz) mesh.rotation.z = o.rz;
    (o.parent || scene).add(mesh);
    return mesh;
  }

  function box(w, h, d, c, x, y, z, o) {
    o = o || {};
    const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), o.mat || M(c, o.mo));
    m.castShadow = !o.noCast; m.receiveShadow = true;
    return put(m, x, y, z, o);
  }

  function cyl(rt, rb, h, seg, mat, x, y, z, o) {
    const m = new THREE.Mesh(new THREE.CylinderGeometry(rt, rb, h, seg), mat);
    m.castShadow = m.receiveShadow = true;
    return put(m, x, y, z, o);
  }

  // =====================================================================
  // scene / camera / renderer
  // =====================================================================
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(PAL.bg);
  scene.fog = new THREE.Fog(PAL.bg, 22, 46);

  const W = () => room.clientWidth || innerWidth, H = () => room.clientHeight || innerHeight;
  const cam = new THREE.PerspectiveCamera(36, W() / H(), .1, 100);
  const CAM0 = new THREE.Vector3(10.5, 7.4, 11.9), LOOK0 = new THREE.Vector3(-.1, 3.0, -1.3);
  cam.position.copy(CAM0); cam.lookAt(LOOK0);

  const R = new THREE.WebGLRenderer({ antialias: true });
  R.setSize(W(), H());
  R.setPixelRatio(Math.min(devicePixelRatio || 1, 2));   // perf law: never above 2
  R.shadowMap.enabled = true; R.shadowMap.type = THREE.PCFSoftShadowMap;
  R.toneMapping = THREE.ACESFilmicToneMapping;
  R.toneMappingExposure = .95;                            // the approved grade
  R.outputEncoding = THREE.sRGBEncoding;
  room.appendChild(R.domElement);

  // Warm hemisphere fill + one cool key light coming in the window (the only
  // shadow caster in the room — one 2048 map, per the perf law), plus two
  // warm point lights that cast nothing.
  scene.add(new THREE.HemisphereLight(0xffdca8, 0x3a2a1c, .52));
  const hour = new Date().getHours();
  let night = (hour < 7 || hour >= 19);
  const sun = new THREE.DirectionalLight(night ? 0x8fa8d8 : 0xdce9ff, night ? .8 : 1.15);
  sun.position.set(-8, 8.5, 4); sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  sun.shadow.camera.left = -11; sun.shadow.camera.right = 11;
  sun.shadow.camera.top = 11; sun.shadow.camera.bottom = -11;
  sun.shadow.bias = -0.0005; sun.shadow.radius = 4;
  scene.add(sun);
  const deskGlow = new THREE.PointLight(0xffb45a, 1.15, 9, 1.7);
  deskGlow.position.set(2.6, 3.4, .4); scene.add(deskGlow);

  // =====================================================================
  // 4. ZONES — the registry every live mesh belongs to. Names are a
  //    contract with the state payload and with Task 4's interaction layer.
  // =====================================================================
  const ZONES = {
    board:     { meshes: [], url: '/mind',        parts: {}, summary: '' },
    desk:      { meshes: [], url: '/mind',        parts: {}, summary: '' },
    tray:      { meshes: [], url: '/intake',      parts: {}, summary: '' },
    stickies:  { meshes: [], url: '/dashboard',   parts: {}, summary: '' },
    calendar:  { meshes: [], url: '/dashboard',   parts: {}, summary: '' },
    window:    { meshes: [], url: '/mind',        parts: {}, summary: '' },
    keys:      { meshes: [], url: '/config#cars', parts: {}, summary: '' },
    contracts: { meshes: [], url: '/dashboard',   parts: {}, summary: '' },
    binders:   { meshes: [], url: '/programs',    parts: {}, summary: '' },
    gauges:    { meshes: [], url: '/mind',        parts: {}, summary: '' }
  };
  // Exactly two lean-in presets in v1 (spec): the board and the desk. Both
  // are framed so the ZONE'S OWN SIGNAL fits: the whole corkboard including
  // its bottom row of pins, and the whole desk from the paper stacks at the
  // left to the gauges at the right. Standing any closer crops the thing you
  // leaned in to read -- checked by screenshot at 1440x900, where the nav bar
  // also eats the top 64px, so each preset sits its subject below that.
  ZONES.board.focus = { p: new THREE.Vector3(.5, 5.0, 1.25), l: new THREE.Vector3(.5, 4.66, -6.13) };
  ZONES.desk.focus  = { p: new THREE.Vector3(.9, 4.9, 8.4),  l: new THREE.Vector3(.3, 2.1, 1.3) };

  function reg(name, mesh) {                 // register a hit target
    ZONES[name].meshes.push(mesh);
    mesh.userData.zone = name;
    return mesh;
  }

  // =====================================================================
  // room shell
  // =====================================================================
  floorTex.repeat.set(3, 3);
  box(17, .3, 17, 0, 0, -.15, 0, { noCast: true, mat: M(0xffffff, { map: floorTex, roughness: .88 }) });
  plasterTex.repeat.set(4, 2);
  const wallMat = M(0xffffff, { map: plasterTex, roughness: .96 });
  box(17, 9.5, .3, 0, 0, 4.4, -6.3, { noCast: true, mat: wallMat });
  box(.3, 9.5, 17, 0, -7.3, 4.4, 0, { noCast: true, mat: wallMat.clone() });
  box(17, .38, .38, 0x5a4029, 0, .38, -6.11, { noCast: true });
  box(.38, .38, 17, 0x5a4029, -7.11, .38, 0, { noCast: true });
  rugTex.anisotropy = 4;
  box(7.8, .05, 5.6, 0, .6, .03, 2.2, { noCast: true, mat: M(0xffffff, { map: rugTex, roughness: 1 }) });

  // =====================================================================
  // window — frame computed from the glass, sky swapped day/night
  // =====================================================================
  const WIN = { x: -7.09, y: 4.35, z: .2, w: 4.8, h: 3.2, f: .24 };
  const skyMat = new THREE.MeshBasicMaterial({ map: night ? skyNight : skyDay });
  const sky = put(new THREE.Mesh(new THREE.PlaneGeometry(WIN.w, WIN.h), skyMat),
    WIN.x - .04, WIN.y, WIN.z, { ry: Math.PI / 2 });
  reg('window', sky);
  // Weather over the sky: one cloud bank per vitals sign that got worse.
  const clouds = [];
  for (let i = 0; i < 3; i++) {
    const c = put(new THREE.Mesh(new THREE.PlaneGeometry(WIN.w * .8, WIN.h * .42),
      new THREE.MeshBasicMaterial({ map: cloudTex, transparent: true, opacity: .8 })),
      WIN.x - .02 + i * .004, WIN.y + .75 - i * .5, WIN.z + (i - 1) * .5, { ry: Math.PI / 2 });
    c.visible = false; clouds.push(c); reg('window', c);
  }
  // The frame: rails derived from the glass rectangle, never hand-placed.
  const frameMat = M(0x5a4029, { roughness: .8 });
  [1, -1].forEach(s => {
    box(.22, WIN.f, WIN.w + WIN.f * 2, 0, WIN.x, WIN.y + s * (WIN.h / 2 + WIN.f / 2), WIN.z,
      { mat: frameMat, noCast: true });
    box(.22, WIN.h + WIN.f * 2, WIN.f, 0, WIN.x, WIN.y, WIN.z + s * (WIN.w / 2 + WIN.f / 2),
      { mat: frameMat, noCast: true });
  });
  box(.16, WIN.h, .14, 0, WIN.x + .01, WIN.y, WIN.z, { mat: frameMat, noCast: true });  // mullion
  box(.16, .14, WIN.w, 0, WIN.x + .01, WIN.y, WIN.z, { mat: frameMat, noCast: true });
  box(.42, .12, WIN.w + WIN.f * 2, 0x6a4c31, WIN.x + .1, WIN.y - WIN.h / 2 - WIN.f, WIN.z, { noCast: true });
  // the light the window throws into the room
  put(new THREE.Mesh(new THREE.PlaneGeometry(5.6, 3.6),
    new THREE.MeshBasicMaterial({
      color: night ? 0x4a6a9a : 0xfff0cc, transparent: true, opacity: .06,
      side: THREE.DoubleSide, depthWrite: false
    })), -4.5, 3.3, .6, { ry: Math.PI / 2.5, rz: .5 });

  // =====================================================================
  // desk
  // =====================================================================
  const DESK = { x: .4, y: 1.66, z: 1.2, w: 7.6, d: 3.0, t: .26 };
  const TOP = DESK.y + DESK.t / 2;                        // working surface height
  const deskMat = M(0xffffff, { map: woodTex, roughness: .68 });
  reg('desk', put(rbox(DESK.w, DESK.d, DESK.t, .1, deskMat), DESK.x, DESK.y, DESK.z, { rx: Math.PI / 2 }));
  [-1, 1].forEach(s => {
    const x = DESK.x + s * (DESK.w / 2 - .3);
    reg('desk', box(.18, 1.55, 2.4, 0, x, .8, DESK.z, { mat: M(0x8a6440, { roughness: .75 }) }));
    box(.52, .09, 2.5, 0x6b4c30, x, .1, DESK.z, {});
  });
  reg('desk', box(1.5, 1.35, 2.2, 0, 3.05, .93, DESK.z, { mat: M(0x8f6743, { roughness: .75 }) }));
  [1.2, .72].forEach(y => {
    box(1.32, .42, .06, 0x7c5836, 3.05, y, 2.32, {});
    box(.52, .06, .1, 0xd8c05a, 3.05, y + .11, 2.36, {});   // drawer pulls
  });

  // ---- monitor: bezel and screen are one group, so they are parallel by
  // construction and the whole head turns to face the chair (spike punch
  // list: the bezel used to point one way and the screen another).
  const monHead = new THREE.Group();
  monHead.position.set(0, 2.89, .45); monHead.rotation.y = .58;
  scene.add(monHead);
  // rbox bevels outward, so the bezel's real front face is d/2 + the bevel
  // thickness — the screen and the stickies sit in FRONT of that, not inside
  // it (the spike's monitor was a dark slab for exactly this reason).
  const BEZ = { w: 2.05, h: 1.3, d: .1, front: .1 / 2 + .02 };
  reg('stickies', put(rbox(BEZ.w, BEZ.h, BEZ.d, .06, M(PAL.dark, { roughness: .55 })), 0, 0, 0, { parent: monHead }));
  const screen = put(new THREE.Mesh(new THREE.PlaneGeometry(BEZ.w - .34, BEZ.h - .3),
    new THREE.MeshBasicMaterial({ color: PAL.screen })), 0, .02, BEZ.front + .008, { parent: monHead });
  reg('stickies', screen);
  // stand: post down to the desk surface, foot flat on it
  box(.2, .46, .13, PAL.dark, 0, -.88, -.02, { parent: monHead, mo: { roughness: .55 } });
  put(rbox(.9, .6, .06, .08, M(PAL.dark, { roughness: .55 })), 0, -1.06, .06,
    { parent: monHead, rx: Math.PI / 2 });
  // stickies: five slots around the bezel, the top one carries the worst sign
  const stickies = [];
  [[-.93, .40, .09], [-.93, .02, -.06], [-.93, -.36, .05],
   [.93, .36, -.07], [.93, -.02, .06]].forEach(([x, y, rz]) => {
    const s = box(.34, .34, .025, PAL.pinWarn, x, y, BEZ.front + .02,
      { parent: monHead, rz: rz, mo: { roughness: 1 } });
    s.visible = false; stickies.push(reg('stickies', s));
  });
  ZONES.stickies.parts = { notes: stickies, screen: screen };

  // keyboard + mouse + a cable
  put(rbox(1.55, .52, .07, .03, M(0x3a352e, { roughness: .6 })), .5, TOP + .04, 1.98, { rx: Math.PI / 2, ry: .1 });
  put(rbox(.3, .45, .1, .12, M(0x3a352e, { roughness: .6 })), 1.5, TOP + .05, 2.05, { rx: Math.PI / 2, ry: .1 });
  box(.05, 1.0, .05, 0x1a1714, .12, 1.25, -.2, { rz: .34, noCast: true });

  // ---- paper stacks: six plan slots, eight sheets each (the caps)
  const SHEET = { w: .92, h: .05, d: .66 };
  const stackSlots = [[-2.95, .55], [-1.95, .5], [-3.0, 1.5], [-2.0, 1.5], [-2.9, 2.4], [-1.9, 2.4]];
  const stacks = stackSlots.map(([x, z]) => {
    const sheets = [];
    for (let i = 0; i < 8; i++) {
      const s = box(SHEET.w, SHEET.h, SHEET.d, PAL.paper,
        x + (rnd() - .5) * .06, TOP + .028 + i * .05, z + (rnd() - .5) * .06,
        { ry: (rnd() - .5) * .26, mo: { roughness: .95 } });
      s.visible = false; sheets.push(reg('desk', s));
    }
    const due = box(SHEET.w, SHEET.h, SHEET.d, PAL.pinWarn, x + .17, TOP + .03, z + .27,
      { ry: .55, mo: { roughness: .95 } });
    due.visible = false; reg('desk', due);
    return { x: x, z: z, sheets: sheets, due: due };
  });
  ZONES.desk.parts = { stacks: stacks };

  // ---- in-tray
  const trayMat = M(0x3c352d, { roughness: .5, metalness: .3 });
  const TRAY = { x: 1.95, z: 1.62, w: 1.4, d: 1.0 };
  reg('tray', put(rbox(TRAY.w, TRAY.d, .06, .05, trayMat), TRAY.x, TOP + .03, TRAY.z, { rx: Math.PI / 2 }));
  [-1, 1].forEach(s => reg('tray', put(rbox(TRAY.d, .34, .05, .02, trayMat),
    TRAY.x + s * TRAY.w / 2, TOP + .17, TRAY.z, { ry: Math.PI / 2 })));
  reg('tray', put(rbox(TRAY.w, .34, .05, .02, trayMat), TRAY.x, TOP + .17, TRAY.z - TRAY.d / 2, {}));
  const traySheets = [];
  for (let i = 0; i < 6; i++) {
    const s = box(1.05, .05, .72, PAL.paper, TRAY.x + (rnd() - .5) * .07, TOP + .08 + i * .05,
      TRAY.z + (rnd() - .5) * .07, { ry: (rnd() - .5) * .2, mo: { roughness: .95 } });
    s.visible = false; traySheets.push(reg('tray', s));
  }
  ZONES.tray.parts = { sheets: traySheets };

  // ---- contracts: signature slips fanned out beside the keyboard
  const slips = [];
  for (let i = 0; i < 4; i++) {
    const s = box(.8, .035, .58, 0xfaf3e2, -.55 + i * .015, TOP + .03 + i * .035, 2.35 + i * .02,
      { ry: .3 - i * .12, mo: { roughness: 1 } });
    s.visible = false; slips.push(reg('contracts', s));
  }
  const seal = box(.1, .012, .1, 0xb03a2e, -.42, TOP + .18, 2.3, { mo: { roughness: .8 } });
  seal.visible = false; reg('contracts', seal);
  put(rbox(.46, .055, .055, .025, M(0x8a5a25, { roughness: .4 })), -.75, TOP + .05, 2.62, { ry: .95 });
  ZONES.contracts.parts = { slips: slips, seal: seal };

  // ---- gauges: two dials and an ingest lamp, angled at the chair
  const gaugeBody = new THREE.Group();
  gaugeBody.position.set(2.62, TOP + .28, .5); gaugeBody.rotation.y = .82;
  scene.add(gaugeBody);
  const GAU = { w: 1.24, h: .68, d: .34, front: .34 / 2 + .02 };   // bevel included
  reg('gauges', put(rbox(GAU.w, GAU.h, GAU.d, .06, M(0x3a352e, { roughness: .5 })), 0, 0, 0, { parent: gaugeBody }));
  const needles = [];
  [-.3, .3].forEach(x => {
    const face = new THREE.Mesh(new THREE.CircleGeometry(.21, 22), M(PAL.cream, { roughness: .5 }));
    put(face, x, .02, GAU.front + .006, { parent: gaugeBody });
    for (let i = 0; i < 5; i++) {                      // tick marks
      const a = -Math.PI * .75 + i * (Math.PI * 1.5 / 4);
      box(.02, .05, .006, 0x6a6258, x + Math.sin(a) * .16, .02 + Math.cos(a) * .16, GAU.front + .012,
        { parent: gaugeBody, rz: -a, noCast: true });
    }
    const g = new THREE.BoxGeometry(.03, .19, .014); g.translate(0, .09, 0);
    const n = new THREE.Mesh(g, M(0x8a2f22, { roughness: .5 }));
    put(n, x, .02, GAU.front + .022, { parent: gaugeBody });
    needles.push(n); reg('gauges', face);
  });
  const lamp = box(.11, .11, .04, PAL.good, 0, -.25, GAU.front + .005, { parent: gaugeBody, mo: { roughness: .4 } });
  reg('gauges', lamp);
  ZONES.gauges.parts = { needles: needles, lamp: lamp };

  // ---- mug + steam (decoration; the room is lived in)
  cyl(.15, .13, .32, 16, M(0xc4552f, { roughness: .45 }), -1.05, TOP + .16, 2.5, {});
  put(new THREE.Mesh(new THREE.TorusGeometry(.09, .026, 8, 14), M(0xc4552f, { roughness: .45 })),
    -.87, TOP + .18, 2.5, { rz: Math.PI / 2 });
  const steam = [];
  for (let i = 0; i < 3; i++)
    steam.push(put(new THREE.Mesh(new THREE.PlaneGeometry(.13, .38),
      new THREE.MeshBasicMaterial({
        color: 0xfff6e8, transparent: true, opacity: .12 - i * .035,
        side: THREE.DoubleSide, depthWrite: false
      })), -1.05, TOP + .48 + i * .22, 2.5, { ry: i * .8 }));

  // ---- chair: rounded seat and back on a real five-star base
  const chairMat = M(0x413a32, { roughness: .72 });
  put(rbox(1.3, 1.25, .18, .26, chairMat), .3, 1.18, 3.55, { rx: Math.PI / 2 });
  put(rbox(1.2, 1.45, .16, .3, chairMat), .3, 2.1, 4.22, { rx: .17 });
  cyl(.1, .1, 1.0, 12, M(0x2c2823, { roughness: .5, metalness: .3 }), .3, .62, 3.62, {});
  cyl(.16, .2, .1, 12, M(0x2c2823, { roughness: .5, metalness: .3 }), .3, .14, 3.62, {});
  for (let i = 0; i < 5; i++) {
    const a = i * Math.PI * 2 / 5 + .3;
    put(rbox(.62, .16, .1, .05, M(0x2c2823, { roughness: .5, metalness: .3 })),
      .3 + Math.sin(a) * .3, .14, 3.62 + Math.cos(a) * .3, { ry: -a + Math.PI / 2 });
    cyl(.07, .07, .1, 8, M(0x1e1b18, { roughness: .6 }), .3 + Math.sin(a) * .58, .07, 3.62 + Math.cos(a) * .58, {});
  }

  // =====================================================================
  // corkboard — frame rails computed from the board's own rectangle
  // =====================================================================
  const BD = { x: .5, y: 4.6, z: -6.13, w: 5.4, h: 3.3, d: .12, rail: .2 };
  corkTex.repeat.set(2, 1);
  reg('board', box(BD.w, BD.h, BD.d, 0, BD.x, BD.y, BD.z,
    { noCast: true, mat: M(0xffffff, { map: corkTex, roughness: 1 }) }));
  const railMat = M(0x5a4029, { roughness: .8 });
  const railZ = BD.z + BD.d / 2 + .02, railD = BD.rail * 1.2;
  [1, -1].forEach(s => {
    box(BD.w + BD.rail * 2, BD.rail, railD, 0, BD.x, BD.y + s * (BD.h / 2 + BD.rail / 2), railZ,
      { mat: railMat, noCast: true });
    box(BD.rail, BD.h + BD.rail * 2, railD, 0, BD.x + s * (BD.w / 2 + BD.rail / 2), BD.y, railZ,
      { mat: railMat, noCast: true });
  });

  // pins: 14 slots (the cap), each a group hanging from its pin head so a
  // stalled card can sag around the point it is actually pinned at.
  const CARD = { w: .6, h: .44 };
  const pinFace = BD.z + BD.d / 2 + .03;
  const pins = [];
  for (let r = 0; r < 3 && pins.length < 14; r++) {
    for (let c = 0; c < 5 && pins.length < 14; c++) {
      const g = new THREE.Group();
      g.position.set(BD.x - 2.02 + c * 1.01 + (rnd() - .5) * .1,
        BD.y + 1.06 - r * 1.02 + (rnd() - .5) * .07 + CARD.h / 2, pinFace);
      scene.add(g);
      const card = box(CARD.w, CARD.h, .035, PAL.pin, 0, -CARD.h / 2, 0,
        { parent: g, mo: { roughness: 1 } });
      reg('board', card);
      cyl(.035, .035, .07, 8, M(PAL.string, { roughness: .5 }), 0, 0, .05,
        { parent: g, rx: Math.PI / 2 });
      for (let i = 0; i < 2; i++)                      // a hint of handwriting
        box(CARD.w * .62, .016, .008, 0x9a8f7a, 0, -CARD.h / 2 + .06 - i * .1, .022,
          { parent: g, noCast: true });
      const rest = (rnd() - .5) * .05;
      g.rotation.z = rest;
      g.visible = false;
      pins.push({ group: g, card: card, rest: rest });
    }
  }
  // strings: one canonical sagging tube, re-aimed between pin heads. No
  // geometry is built when the state arrives — only position/scale/rotation.
  const stringCurve = new THREE.QuadraticBezierCurve3(
    new THREE.Vector3(-.5, 0, 0), new THREE.Vector3(0, -.17, 0), new THREE.Vector3(.5, 0, 0));
  const stringGeo = new THREE.TubeGeometry(stringCurve, 14, .015, 5);
  const strings = [];
  for (let i = 0; i < 10; i++) {
    const m = new THREE.Mesh(stringGeo, M(PAL.string, { roughness: .9 }));
    m.visible = false; scene.add(m); strings.push(m);
  }
  ZONES.board.parts = { pins: pins, strings: strings, face: pinFace };

  // =====================================================================
  // wall calendar — seven day cells, one per day the solver answered for
  // =====================================================================
  const CAL = { x: 5.2, y: 4.85, z: -6.14, w: 2.05, h: 2.35 };
  reg('calendar', box(CAL.w, CAL.h, .07, PAL.cream, CAL.x, CAL.y, CAL.z, { noCast: true }));
  box(CAL.w, .46, .09, 0xc25c37, CAL.x, CAL.y + CAL.h / 2 - .23, CAL.z + .01, { noCast: true });
  cyl(.05, .05, .12, 8, M(0x8a8478, { roughness: .5 }), CAL.x, CAL.y + CAL.h / 2 + .1, CAL.z + .02, { rx: Math.PI / 2 });
  const cells = [];
  for (let i = 0; i < 7; i++) {
    const row = i < 4 ? 0 : 1, col = i < 4 ? i : i - 4;
    const x = CAL.x + (row === 0 ? -.69 + col * .46 : -.46 + col * .46);
    const c = box(.4, .4, .03, PAL.cell, x, CAL.y + .28 - row * .5, CAL.z + .05,
      { noCast: true, mo: { roughness: .95 } });
    cells.push(reg('calendar', c));
  }
  for (let i = 0; i < 2; i++)                            // ruled lines under the week
    box(CAL.w - .3, .02, .02, 0xcfc3a6, CAL.x, CAL.y - .82 - i * .22, CAL.z + .04, { noCast: true });
  ZONES.calendar.parts = { cells: cells };

  // =====================================================================
  // key hooks — a real board, real hooks, keys with a readable silhouette
  // =====================================================================
  const KEY = { x: -5.3, y: 4.62, z: -6.13, w: 2.0, h: .8 };
  reg('keys', put(rbox(KEY.w, KEY.h, .1, .06, M(0x8a6440, { roughness: .8 })), KEY.x, KEY.y, KEY.z + .06, {}));
  box(KEY.w + .12, .07, .15, 0x6b4c30, KEY.x, KEY.y + KEY.h / 2 - .02, KEY.z + .08, { noCast: true });
  const keySlots = [];
  const keyMat = () => M(PAL.key, { roughness: .45, metalness: .4 });
  for (let i = 0; i < 4; i++) {
    const x = KEY.x - .69 + i * .46;
    const hook = put(new THREE.Mesh(new THREE.TorusGeometry(.06, .022, 6, 10, Math.PI),
      M(0xb9b0a0, { roughness: .4, metalness: .5 })), x, KEY.y - .12, KEY.z + .15, { rx: -.55 });
    const g = new THREE.Group();
    g.position.set(x, KEY.y - .16, KEY.z + .18);
    scene.add(g);
    // bow, shaft, two teeth: a key silhouette that reads at room distance
    put(new THREE.Mesh(new THREE.TorusGeometry(.1, .028, 6, 14), keyMat()), 0, -.12, 0, { parent: g });
    box(.06, .4, .028, 0, 0, -.42, 0, { parent: g, mat: keyMat() });
    box(.13, .055, .028, 0, .045, -.55, 0, { parent: g, mat: keyMat() });
    box(.13, .055, .028, 0, .045, -.45, 0, { parent: g, mat: keyMat() });
    reg('keys', g.children[0]);
    // the dangling tag: only a car that is low ever wears one
    const tag = new THREE.Group();
    tag.position.set(.03, -.68, .01);
    g.add(tag);
    box(.014, .18, .014, 0x9a8f7a, 0, .09, 0, { parent: tag, noCast: true });
    const tagCard = put(rbox(.32, .22, .025, .05, M(PAL.pinWarn, { roughness: 1 })), 0, -.09, 0, { parent: tag });
    tag.rotation.z = .18;
    tag.visible = false;
    g.visible = false;
    keySlots.push({ group: g, tag: tag, card: tagCard, hook: hook });
    reg('keys', tagCard);
  }
  ZONES.keys.parts = { slots: keySlots };

  // =====================================================================
  // shelf + binders (programs), plant, photos, clock, lamp
  // =====================================================================
  const SHELF = { x: -4.3, y: 5.95, z: -5.72, w: 3.8, d: .95 };
  box(SHELF.w, .16, SHELF.d, 0, SHELF.x, SHELF.y, SHELF.z,
    { mat: M(0x8a6440, { roughness: .8 }) });
  [-1, 1].forEach(s => box(.22, .55, .34, 0x6b4c30, SHELF.x + s * (SHELF.w / 2 - .2), SHELF.y - .35, -5.98, {}));
  const BINDER_C = [0xc25c37, 0x3f78c0, 0x4f9a4f, 0x8a5fa8, 0xd8a53a];
  const binders = [];
  for (let i = 0; i < 5; i++) {
    const b = put(rbox(.38, .98, .74, .05, M(BINDER_C[i], { roughness: .8 })),
      SHELF.x - 1.4 + i * .44, SHELF.y + .57, SHELF.z, {});
    b.userData.homeZ = SHELF.z;
    b.visible = false; binders.push(reg('binders', b));
  }
  ZONES.binders.parts = { binders: binders };
  // plant on the shelf's free end
  cyl(.26, .2, .42, 12, M(PAL.pot, { roughness: .9 }), SHELF.x + 1.3, SHELF.y + .3, SHELF.z, {});
  for (let i = 0; i < 6; i++)
    box(.09, .72 + rnd() * .4, .09, PAL.plant, SHELF.x + 1.3 + (rnd() - .5) * .34,
      SHELF.y + .82 + rnd() * .2, SHELF.z + (rnd() - .5) * .3,
      { rz: (rnd() - .5) * .55, rx: (rnd() - .5) * .35 });
  // photo frames: the free stretch of wall between the keys and the board,
  // plus one standing on the desk (the room is somebody's).
  box(.55, .66, .05, 0x5a4029, -3.9, 5.3, -6.14, { noCast: true });
  box(.42, .53, .02, 0xd8a05a, -3.9, 5.3, -6.1, { noCast: true });
  const frameGrp = new THREE.Group();
  frameGrp.position.set(-3.3, TOP + .3, .5); frameGrp.rotation.y = .82; frameGrp.rotation.x = .08;
  scene.add(frameGrp);
  put(rbox(.46, .56, .05, .03, M(0x5a4029, { roughness: .7 })), 0, 0, 0, { parent: frameGrp });
  put(new THREE.Mesh(new THREE.PlaneGeometry(.32, .42), M(0x6f9ad0, { roughness: .8 })),
    0, 0, .046, { parent: frameGrp });
  box(.07, .3, .05, 0x5a4029, 0, -.2, -.14, { parent: frameGrp, rx: -.4 });
  // clock — hands set from the wall clock's own time (Task 4 makes them tick)
  cyl(.52, .52, .09, 24, M(PAL.cream, { roughness: .4 }), 4.15, 6.8, -6.12, { rx: Math.PI / 2 });
  put(new THREE.Mesh(new THREE.TorusGeometry(.52, .05, 8, 24), M(0x5a4029, { roughness: .6 })),
    4.15, 6.8, -6.1, {});
  const nowClock = new Date();
  const clockHands = [[.055, .28, ((nowClock.getHours() % 12) / 12 + nowClock.getMinutes() / 720)],
   [.04, .42, nowClock.getMinutes() / 60]].map(([w, len, frac]) => {
    const g = new THREE.BoxGeometry(w, len, .02); g.translate(0, len / 2, 0);
    const m = new THREE.Mesh(g, M(PAL.dark, { roughness: .6 }));
    m.rotation.z = -frac * Math.PI * 2;
    return put(m, 4.15, 6.8, -6.06, {});
  });
  // floor lamp
  cyl(.42, .5, .07, 14, M(0x2c2823, { roughness: .5 }), 6.2, .05, -4.4, {});
  cyl(.06, .06, 3.5, 8, M(0x2c2823, { roughness: .5 }), 6.2, 1.8, -4.4, {});
  put(new THREE.Mesh(new THREE.CylinderGeometry(.36, .52, .6, 16, 1, true),
    M(0xf0d3a0, { roughness: .9, side: THREE.DoubleSide, emissive: 0x2a1c08 })), 6.2, 3.6, -4.4, {});
  const lampLight = new THREE.PointLight(0xffcf8a, .9, 7, 1.8);
  lampLight.position.set(6.2, 3.4, -4.4); scene.add(lampLight);

  // dust motes in the window light
  const motePos = [];
  for (let i = 0; i < 260; i++)
    motePos.push((rnd() - .5) * 13, rnd() * 7 + .5, (rnd() - .5) * 12);
  const moteGeo = new THREE.BufferGeometry().setAttribute('position',
    new THREE.Float32BufferAttribute(motePos, 3));
  scene.add(new THREE.Points(moteGeo,
    new THREE.PointsMaterial({ color: 0xffe9c0, size: .035, transparent: true, opacity: .4 })));
  const moteAttr = moteGeo.getAttribute('position');

  // =====================================================================
  // since you were here — the last visit, and the day turning over
  // =====================================================================
  // Storage can be absent, blocked (private mode), or full. EVERY touch is
  // guarded: a browser that refuses it shows no glows and throws nothing.
  const VISIT_KEY = 'study_last_visit';
  let LAST_VISIT = null;
  try {
    const raw = localStorage.getItem(VISIT_KEY);
    const n = raw == null ? NaN : Number(raw);
    if (isFinite(n) && n > 0) LAST_VISIT = n;
  } catch (e) { LAST_VISIT = null; }

  // A pin or a stack that arrived after your last visit wears a soft warm
  // emissive. The materials are per-mesh (box() mints one each), so this
  // only ever touches the things it lit, and clears them before a rebuild.
  const NEW_GLOW = 0xffcf7a;
  let glowMats = [];
  function glowReset() {
    glowMats.forEach(m => { m.emissive.setHex(0x000000); m.emissiveIntensity = 1; });
    glowMats = [];
  }
  function glowIf(mat, ts) {
    if (LAST_VISIT == null || !mat || !mat.emissive) return;
    const t = Number(ts);
    if (!isFinite(t) || t <= LAST_VISIT) return;
    mat.emissive.setHex(NEW_GLOW);
    glowMats.push(mat);
  }

  // The hour turns while the page is open: a poll that crosses 07:00 or
  // 19:00 swaps the sky map (both textures were built up front) and re-aims
  // the window light. Nothing is redrawn per frame.
  function syncSky() {
    const h = new Date().getHours();
    const isNight = (h < 7 || h >= 19);
    if (isNight === night) return;
    night = isNight;
    skyMat.map = night ? skyNight : skyDay;
    skyMat.needsUpdate = true;
    sun.color.setHex(night ? 0x8fa8d8 : 0xdce9ff);
    sun.intensity = night ? .8 : 1.15;
  }

  // The payload the room is currently wearing — what the flying sheet asks
  // before it decides whether there is anything honest to carry.
  let LAST = null, lastJson = '';

  // =====================================================================
  // 5. FURNITURE — the whole of the room's data behaviour, one row per
  //    section of the payload. Adding a signal is a row here, not surgery.
  // =====================================================================
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const CAPS = { pins: 14, sheets: 8, tray: 6, keys: 4, binders: 5, stickies: 5, slips: 4 };

  const FURNITURE = {
    // one pinned card per insight/thread; stalled ones yellow and sag,
    // overdue ones go red; strings join the pairs the payload names.
    board: (d, z) => {
      const data = (d.pins || []).slice(0, CAPS.pins);
      const P = z.parts.pins;
      P.forEach((p, i) => {
        const row = data[i];
        p.group.visible = !!row;
        if (!row) { p.sway = 0; return; }
        p.card.material.color.setHex(row.bad ? PAL.pinBad : row.warn ? PAL.pinWarn : PAL.pin);
        // The hang the card settles at; the life loop sways stalled ones
        // around this, so the state lives here and the motion lives there.
        p.base = row.bad ? -.16 : row.warn ? -.1 : p.rest;
        p.sway = row.bad ? 1 : row.warn ? .55 : 0;
        p.group.rotation.z = p.base;
        p.card.userData.pin = row;
        glowIf(p.card.material, row.changed_ts);
      });
      // ids are unique per table, not across them: a string is always
      // [insight id, thread id], so each end resolves in its own half first.
      const ins = {}, th = {}, any = {};
      data.forEach((row, i) => {
        (row.kind === 'insight' ? ins : th)[row.id] = i;
        if (any[row.id] === undefined) any[row.id] = i;
      });
      const at = (map, id) => (map[id] !== undefined ? map[id] : any[id]);
      const pairs = (d.strings || [])
        .map(s => [at(ins, s[0]), at(th, s[1])])
        .filter(s => s[0] !== undefined && s[1] !== undefined && s[0] !== s[1])
        .slice(0, z.parts.strings.length);
      z.parts.strings.forEach((m, i) => {
        const pair = pairs[i];
        m.visible = !!pair;
        if (!pair) return;
        const a = P[pair[0]].group.position, b = P[pair[1]].group.position;
        const dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy);
        m.position.set((a.x + b.x) / 2, (a.y + b.y) / 2, z.parts.face + .04);
        m.rotation.z = Math.atan2(dy, dx);
        m.scale.x = Math.max(len, .01);
      });
      const bad = data.filter(p => p.warn || p.bad).length;
      z.summary = data.length
        ? `${data.length} pinned${bad ? ` · ${bad} stalled` : ''}`
        : 'Board clear';
    },

    // one stack per in-hand plan, a sheet per open step, an amber sheet
    // pushed out of the pile when a step is due.
    desk: (d, z) => {
      const plans = (d || []).slice(0, z.parts.stacks.length);
      z.parts.stacks.forEach((st, i) => {
        const p = plans[i];
        const n = p ? clamp(p.open_steps | 0, 0, CAPS.sheets) : 0;
        st.sheets.forEach((s, j) => { s.visible = j < n; });
        st.due.visible = !!(p && p.due);
        st.due.position.y = TOP + .03 + Math.max(n - 1, 0) * .05;
        st.plan = p || null;
        if (p) for (let j = 0; j < n; j++) glowIf(st.sheets[j].material, p.changed_ts);
      });
      const due = plans.filter(p => p.due).length;
      z.summary = plans.length
        ? `${plans.length} plan${plans.length === 1 ? '' : 's'} in hand${due ? ` · ${due} with a step due` : ''}`
        : 'No plans in hand';
    },

    tray: (d, z) => {
      const n = clamp(d.count | 0, 0, CAPS.tray);
      z.parts.sheets.forEach((s, i) => { s.visible = i < n; });
      z.summary = d.count ? `${d.count} waiting` : 'Tray empty';
    },

    // count is how many notes are stuck up; the worst severity colours the
    // top one (decide is the loudest — findings.py's own ranking).
    stickies: (d, z) => {
      const n = clamp(d.count | 0, 0, CAPS.stickies);
      const worst = { decide: PAL.pinBad, approve: PAL.pinWarn, fyi: 0xf2e07a }[d.worst] || 0xf2e07a;
      z.parts.notes.forEach((s, i) => {
        s.visible = i < n;
        s.material.color.setHex(i === 0 ? worst : 0xf2e07a);
      });
      z.summary = d.count ? `${d.count} open finding${d.count === 1 ? '' : 's'}${d.worst ? ` · ${d.worst}` : ''}`
        : 'No open findings';
    },

    // seven cells, one per day the solver answered for; red is a day with
    // an uncovered driver event.
    calendar: (d, z) => {
      const days = d.days || [];
      z.parts.cells.forEach((c, i) => {
        const day = days[i];
        c.material.color.setHex(day && day.unassigned > 0 ? PAL.pinBad : PAL.cell);
        c.userData.day = day || null;
      });
      const holes = days.filter(x => x.unassigned > 0);
      z.summary = holes.length
        ? `${holes.length} day${holes.length === 1 ? '' : 's'} uncovered this week`
        : 'The week is covered';
    },

    // the weather outside is the family's own week: clear when steady, one
    // cloud bank per sign that got worse. Day/night is the wall clock's.
    window: (d, z) => {
      syncSky();
      const worse = (d.worse || []).length;
      clouds.forEach((c, i) => { c.visible = i < (d.ready ? worse : Math.max(worse, 1)); });
      z.summary = d.label || '';
    },

    // one key per car with telemetry; a low one wears a dangling tag.
    keys: (d, z) => {
      const cars = (d || []).slice(0, CAPS.keys);
      z.parts.slots.forEach((k, i) => {
        const car = cars[i];
        k.group.visible = !!car;
        k.tag.visible = !!(car && car.low);
        k.group.userData.car = car || null;
      });
      const low = cars.filter(c => c.low).map(c => c.name);
      z.summary = low.length ? `${low.join(', ')} low` : (cars.length ? 'Cars fuelled' : '');
    },

    contracts: (d, z) => {
      const n = clamp(d.count | 0, 0, CAPS.slips);
      z.parts.slips.forEach((s, i) => { s.visible = i < n; });
      z.parts.seal.visible = n > 0;
      z.summary = d.count ? `${d.count} deal${d.count === 1 ? '' : 's'} awaiting answers` : 'No open deals';
    },

    // a binder per active program; one pulled off the shelf is a program
    // that has gone quiet.
    binders: (d, z) => {
      const rows = (d || []).slice(0, CAPS.binders);
      z.parts.binders.forEach((b, i) => {
        const row = rows[i];
        b.visible = !!row;
        b.position.z = b.userData.homeZ + (row && row.pulled ? .44 : 0);
        b.rotation.z = row && row.pulled ? -.09 : 0;
        b.userData.program = row || null;
      });
      const pulled = rows.filter(r => r.pulled).map(r => r.title).filter(Boolean);
      z.summary = pulled.length ? `${pulled.join(', ')} needs a look`
        : (rows.length ? `${rows.length} program${rows.length === 1 ? '' : 's'} running` : '');
    },

    // two needles: thinking spent today, research spent this month. The
    // lamp goes red while the ingest log is erroring.
    gauges: (d, z) => {
      const sweep = (v, cap) => {
        const r = (v != null && cap) ? clamp(v / cap, 0, 1) : 0;
        return Math.PI * .75 - Math.PI * 1.5 * r;
      };
      z.parts.needles[0].rotation.z = sweep(d.think, d.think_cap);
      z.parts.needles[1].rotation.z = sweep(d.research, d.research_cap);
      z.parts.lamp.material.color.setHex(d.ingest_errors > 0 ? PAL.pinBad : PAL.good);
      const bits = [];
      if (d.think != null && d.think_cap) bits.push(`think ${d.think}/${d.think_cap}`);
      if (d.research != null && d.research_cap) bits.push(`research ${d.research}/${d.research_cap}`);
      if (d.ingest_errors) bits.push(`${d.ingest_errors} ingest errors`);
      z.summary = bits.join(' · ');
    }
  };

  // =====================================================================
  // 6. applyState — the only place in this file that reads the payload
  // =====================================================================
  function applyState(payload) {
    syncSky();                      // the hour turns even when nothing else does
    // Minimal diff: an unchanged payload touches nothing at all, so the
    // static room never flickers and the glows already lit stay lit. When
    // something HAS moved, the pin/sheet groups are rebuilt wholesale --
    // they are a few hundred visibility flags, not geometry.
    let json;
    try { json = JSON.stringify(payload); } catch (e) { json = undefined; }
    if (json !== undefined && json === lastJson) return;
    lastJson = json;
    const f = normal(payload);
    LAST = f;
    glowReset();
    Object.keys(FURNITURE).forEach(k => {
      try { FURNITURE[k](f[k], ZONES[k]); }
      catch (e) { /* one broken signal never empties the room */ }
    });
    // Whatever the pointer is already resting on now says the new number.
    if (hoverZone) updateTip(hoverZone);
    if (leaned) chipEl.textContent = chipText(leaned);
  }

  // =====================================================================
  // 7. interaction + life — the room answers the pointer, and breathes
  // =====================================================================
  const LABEL = {
    board: 'The board', desk: 'The desk', tray: 'Intake', stickies: 'Findings',
    calendar: 'This week', window: 'Outside', keys: 'Cars',
    contracts: 'Deals', binders: 'Programs', gauges: "Argyle's budget"
  };
  const tipEl = document.getElementById('tip');
  const chipEl = document.getElementById('chip');

  // Every registered mesh, flattened once. reg() already stamped
  // userData.zone on each, so a hit knows its own zone with no lookup.
  const HIT = [];
  Object.keys(ZONES).forEach(k => ZONES[k].meshes.forEach(m => HIT.push(m)));

  // r150's Raycaster does NOT test ancestor visibility, and a great deal of
  // this room is legitimately invisible in a quiet house (unpinned cards,
  // empty tray slots, cars with no telemetry). Walk up and check for real,
  // or the pointer finds furniture that is not there.
  function shown(o) {
    while (o) { if (!o.visible) return false; o = o.parent; }
    return true;
  }

  const ray = new THREE.Raycaster();
  const ndc = new THREE.Vector2();
  let ptrX = 0, ptrY = 0, ptrIn = false, needPick = false;
  let pnx = 0, pny = 0;                       // pointer in -1..1, for parallax
  let paraX = 0, paraY = 0;                   // the damped camera offset it feeds
  let hoverZone = null, leaned = null;

  function pick() {
    if (!ptrIn) return null;
    const b = R.domElement.getBoundingClientRect();
    if (!b.width || !b.height) return null;
    ndc.x = ((ptrX - b.left) / b.width) * 2 - 1;
    ndc.y = -((ptrY - b.top) / b.height) * 2 + 1;
    ray.setFromCamera(ndc, cam);
    const hits = ray.intersectObjects(HIT, false);
    for (let i = 0; i < hits.length; i++)
      if (shown(hits[i].object)) return hits[i].object.userData.zone || null;
    return null;
  }

  // The one line a zone is currently saying. Built from zone.summary, which
  // applyState is the only writer of -- no payload is read out here.
  function signal(name) {
    const s = (ZONES[name] && ZONES[name].summary) || '';
    return s ? LABEL[name] + ' \u2014 ' + s : LABEL[name];
  }
  const chipText = name => signal(name) + ' \u00b7 tap again to open';

  function updateTip(zone) {
    // The chip already says this zone's line (and more) while you are leaned
    // into it -- two labels saying the same thing is noise, so the tip yields.
    if (!zone || !ptrIn || zone === leaned) { tipEl.style.opacity = '0'; return; }
    tipEl.textContent = signal(zone);
    const w = tipEl.offsetWidth || 170, h = tipEl.offsetHeight || 28;
    tipEl.style.left = Math.max(8, Math.min(ptrX + 16, innerWidth - w - 10)) + 'px';
    tipEl.style.top = Math.max(8, ptrY - h - 12) + 'px';
    tipEl.style.opacity = '1';
  }

  // ---- lean-in ---------------------------------------------------------
  // Only the board and the desk carry a focus preset (the spec's two). A
  // click there leans the camera in and says what the zone is; a second
  // click opens the page. Every other zone is a link on the first click.
  const camAt = CAM0.clone(), lookNow = LOOK0.clone();
  let camTo = CAM0, lookTo = LOOK0;

  // The template parks #chip 18px off the bottom, but this page also carries
  // the Ask-Argyle bar (#chat-overlay-container, fixed along the bottom at
  // z-80), which would sit on top of it. Lift the chip clear of whatever
  // height that bar actually has rather than hard-coding one; with no bar in
  // the page the template's own 18px stands.
  function placeChip() {
    let bottom = 18;
    const bar = document.getElementById('chat-overlay-container');
    if (bar) {
      const r = bar.getBoundingClientRect();
      if (r.height > 0) bottom = Math.max(18, Math.round(innerHeight - r.top) + 12);
    }
    chipEl.style.bottom = bottom + 'px';
  }

  function leanInto(name) {
    leaned = name;
    camTo = ZONES[name].focus.p; lookTo = ZONES[name].focus.l;
    chipEl.textContent = chipText(name);
    placeChip();
    chipEl.style.opacity = '1';
  }
  function leanBack() {
    if (!leaned) return;
    leaned = null; camTo = CAM0; lookTo = LOOK0;
    chipEl.style.opacity = '0';
  }

  R.domElement.addEventListener('pointermove', e => {
    ptrX = e.clientX; ptrY = e.clientY; ptrIn = true; needPick = true;
    pnx = (ptrX / innerWidth) * 2 - 1;
    pny = -((ptrY / innerHeight) * 2 - 1);
  });
  R.domElement.addEventListener('pointerleave', () => {
    ptrIn = false; needPick = true; pnx = pny = 0;
  });
  R.domElement.addEventListener('click', e => {
    // A tap arrives with no preceding move, so take the position from the
    // click itself rather than trusting whatever the pointer last said.
    ptrX = e.clientX; ptrY = e.clientY; ptrIn = true; needPick = true;
    const zone = pick();
    if (!zone) { leanBack(); return; }
    const z = ZONES[zone];
    if (z.focus && leaned !== zone) { leanInto(zone); return; }
    go(z.url);
  });
  addEventListener('keydown', e => { if (e.key === 'Escape') leanBack(); });

  // ---- the flying sheet ------------------------------------------------
  // Every ~90s a sheet leaves the tray for the board -- but only when there
  // really is something in the tray AND something already pinned for it to
  // join. An empty room never animates just to look busy.
  const FLY_EVERY = 90, FLY_SECS = 2.4;
  const flyer = box(1.0, .04, .7, PAL.paper, 0, -20, 0, { mo: { roughness: .95 } });
  flyer.name = 'study-flyer';
  flyer.material.transparent = true;
  flyer.visible = false;
  const flyA = new THREE.Vector3(), flyB = new THREE.Vector3(), flyC = new THREE.Vector3();
  let flyT = -1, nextFly = FLY_EVERY;

  function maybeFly(t) {
    if (flyT >= 0 || t < nextFly) return;
    nextFly = t + FLY_EVERY;
    const waiting = (LAST && LAST.tray && LAST.tray.count) | 0;
    const insights = LAST && LAST.board
      ? (LAST.board.pins || []).filter(p => p && p.kind === 'insight').length : 0;
    if (waiting <= 0 || insights < 1) return;
    let target = null;
    const P = ZONES.board.parts.pins;
    for (let i = 0; i < P.length; i++) if (P[i].group.visible) { target = P[i].group.position; break; }
    flyA.set(TRAY.x, TOP + .3, TRAY.z);
    flyC.set(target ? target.x : BD.x, (target ? target.y : BD.y) - .25,
             ZONES.board.parts.face + .07);
    flyB.set((flyA.x + flyC.x) / 2, Math.max(flyA.y, flyC.y) + 1.4, (flyA.z + flyC.z) / 2);
    flyT = 0; flyer.material.opacity = 1; flyer.visible = true;
  }

  function stepFly(dt) {
    if (flyT < 0) return;
    flyT += dt / FLY_SECS;
    if (flyT >= 1) { flyT = -1; flyer.visible = false; flyer.material.opacity = 1; return; }
    const u = flyT, v = 1 - u, a = v * v, b = 2 * v * u, c = u * u;
    flyer.position.set(a * flyA.x + b * flyB.x + c * flyC.x,
                       a * flyA.y + b * flyB.y + c * flyC.y,
                       a * flyA.z + b * flyB.z + c * flyC.z);
    flyer.rotation.x = Math.PI / 2 * Math.min(u * 1.2, 1);   // flat in the tray, upright on the board
    flyer.rotation.z = Math.sin(u * Math.PI) * .22;
    flyer.material.opacity = u > .82 ? Math.max(0, (1 - u) / .18) : 1;
  }

  // ---- the loop --------------------------------------------------------
  const SCREEN0 = new THREE.Color(PAL.screen);
  const MOTE_TOP = 7.6, MOTE_BOT = .4;
  const T0 = performance.now();
  let lastMs = T0, T = 0;

  function frame(nowMs) {
    requestAnimationFrame(frame);
    // Two clocks on purpose. `el` is the real elapsed time and drives the
    // exponential eases, which are frame-rate independent by construction and
    // only ever land closer to the target after a stall. `dt` is capped so the
    // integrators (dust, the flying sheet, every phase) cannot leap forward
    // when a backgrounded tab hands back half a minute at once.
    const ms = nowMs || lastMs;
    const el = Math.min(Math.max((ms - lastMs) / 1000, 0), 1);
    const dt = Math.min(el, .05);
    lastMs = ms; T += dt;

    // hover: at most one raycast per frame, and only when something moved
    if (needPick) {
      needPick = false;
      const z = pick();
      if (z !== hoverZone) {
        hoverZone = z;
        R.domElement.style.cursor = z ? 'pointer' : 'default';
      }
      updateTip(z);
    }

    // camera: a slow idle drift and a damped cursor parallax, laid on top of
    // whichever pose the rig is lerping toward (home, or a lean-in preset).
    const k = 1 - Math.pow(.06, el), kp = 1 - Math.pow(.004, el);
    camAt.lerp(camTo, k); lookNow.lerp(lookTo, k);
    paraX += (pnx * .35 - paraX) * kp;
    paraY += (pny * .35 - paraY) * kp;
    const amp = leaned ? .35 : 1;
    cam.position.set(camAt.x + paraX + Math.sin(T * .17) * .16 * amp,
                     camAt.y + paraY + Math.sin(T * .11) * .11 * amp,
                     camAt.z + Math.cos(T * .13) * .13 * amp);
    cam.lookAt(lookNow);

    // the monitor breathes, and the desk lamp breathes with it
    screen.material.color.copy(SCREEN0).multiplyScalar(.9 + .1 * Math.sin(T * .9));
    deskGlow.intensity = 1.05 + .12 * Math.sin(T * .9);

    // dust turning over in the window light
    const ma = moteAttr.array;
    for (let i = 1; i < ma.length; i += 3) {
      ma[i] += dt * .055;
      if (ma[i] > MOTE_TOP) ma[i] = MOTE_BOT;
      ma[i - 1] += Math.sin(T * .3 + i) * dt * .03;
    }
    moteAttr.needsUpdate = true;

    // steam off the mug: each ribbon rises, fades, and starts again
    for (let i = 0; i < steam.length; i++) {
      const ph = (T * .32 + i * .34) % 1, sm = steam[i];
      sm.position.y = TOP + .4 + i * .18 + ph * .55;
      sm.material.opacity = (.14 - i * .03) * Math.sin(ph * Math.PI);
      sm.rotation.y = i * .8 + Math.sin(T * .4 + i) * .35;
      sm.scale.setScalar(.75 + ph * .5);
    }

    // the clock is the room's own, not a decoration
    const d = new Date(), mins = d.getMinutes() + d.getSeconds() / 60;
    clockHands[0].rotation.z = -((d.getHours() % 12) / 12 + mins / 720) * Math.PI * 2;
    clockHands[1].rotation.z = -(mins / 60) * Math.PI * 2;

    // a stalled card never hangs quite still
    const P = ZONES.board.parts.pins;
    for (let i = 0; i < P.length; i++) {
      const p = P[i];
      if (p.group.visible && p.sway)
        p.group.rotation.z = p.base + Math.sin(T * 1.05 + i * .7) * .024 * p.sway;
    }

    // what arrived since you were last in the room
    if (glowMats.length) {
      const gi = .32 + .16 * Math.sin(T * 1.4);
      for (let i = 0; i < glowMats.length; i++) glowMats[i].emissiveIntensity = gi;
    }

    // The flight is scheduled on the WALL clock, not on T: a slow renderer
    // makes the room breathe slower, but a sheet still files every ~90s.
    maybeFly((ms - T0) / 1000); stepFly(dt);
    R.render(scene, cam);
  }

  // Before the first poll answers, the room is simply tidy.
  applyState(null);
  requestAnimationFrame(frame);

  // Ten seconds after the room is up, this visit becomes the new "since".
  // The glows already on screen keep the OLD mark, so what was new when you
  // walked in stays marked for as long as you are standing here.
  setTimeout(() => {
    try { localStorage.setItem(VISIT_KEY, String(Date.now() / 1000)); }
    catch (e) { /* no storage: nothing to remember it with, and that is fine */ }
  }, 10000);

  addEventListener('resize', () => {
    cam.aspect = W() / H(); cam.updateProjectionMatrix(); R.setSize(W(), H());
    if (leaned) placeChip();
  });

  window.STUDY = { applyState: applyState, scene: scene, camera: cam, zones: ZONES, renderer: R };
  poll(applyState);
})();
