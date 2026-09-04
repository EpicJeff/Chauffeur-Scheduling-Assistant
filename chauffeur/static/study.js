/* The Study — a living office. Read-only lens; see
   docs/superpowers/specs/2026-09-03-argyle-study-design.md.

   Structure:
   1. capability gate: no WebGL or viewport < 900px -> fallback list
   2. canvas textures (wood, floor planks, cork, plaster, rug, sky day/night)
   3. geometry helpers: M(color, opts), box(), rbox() rounded-extrude, put()
   4. static room build — every live mesh registered in ZONES
   5. FURNITURE: declarative state->scene mutations
   6. applyState(payload) — the ONLY place the scene reads data
   7. interaction: lean-in, DETAIL (the text a focused zone paints), life

   Two rules the whole file obeys: the room NEVER writes (no POST anywhere,
   ever), and every mesh a signal can touch is built once, up front, then
   only shown/hidden/coloured/moved. applyState allocates no geometry.

   A third rule, for the detail layer: text in this room is PAINTED into a
   canvas and uploaded as a texture, never marked up. A thread title, a
   proposal subject, a car's name — all of them are words somebody else
   typed, and none of them can do anything on a Post-it. Nothing in this
   file assigns innerHTML except the fallback list's fixed row template,
   which carries no model text (see the test that pins it).
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
  // Both floating chips this page raises have to clear the control centre's
  // Ask-Argyle bar, which is fixed to the bottom of every page in the app.
  // Measured rather than guessed: the bar grows when its placeholder wraps,
  // which is exactly what happens on the narrow viewports the fallback list
  // serves. Absent bar (it mounts with Alpine) = the plain 18px floor.
  function barBottom() {
    let bottom = 18;
    const bar = document.getElementById('chat-overlay-container');
    if (bar) {
      const r = bar.getBoundingClientRect();
      if (r.height > 0) bottom = Math.max(18, Math.round(innerHeight - r.top) + 12);
    }
    return bottom;
  }

  let outageEl = null, outageShown = false;
  function showOutage() {
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
    // Re-measured every time it is raised: the bar may not have mounted when
    // the first poll failed, and the viewport may have changed since.
    outageEl.style.bottom = barBottom() + 'px';
    if (outageShown) return;
    outageShown = true;
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
    // `strings` mirrors the server's own key, which is permanently empty:
    // nothing draws a line between two pins, because nothing stores a
    // relation between them. See FURNITURE.board.
    board: { pins: [], strings: [] },
    desk: [],
    tray: { count: 0, items: [] },
    stickies: { count: 0, worst: null, items: [] },
    calendar: { days: [] },
    window: { ready: false, worse: [], label: '', signs: [] },
    keys: [],
    contracts: { count: 0, items: [] },
    binders: [],
    gauges: { think: null, think_cap: null, research: null,
              research_cap: null, ingest_errors: 0 },
    monitor: { clusters: [] },
    map: { trips: [] }
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
    // The window: the week measured against the family's OWN baseline. Only
    // once there is a baseline to measure against (`ready`) — "early days"
    // is not a thing that needs you, so a young install stays silent here
    // rather than reporting a shortage of history as a problem.
    const worse = f.window.worse || [];
    if (f.window.ready && worse.length)
      rows.push(['/mind', 'This week', `${worse.join(', ')} worse than your baseline`, false]);
    // The gauges: the only three states where Argyle's own budget is the
    // thing that needs you. A dial merely part-way round is not news.
    const g = f.gauges, gb = [];
    if (g.ingest_errors > 0)
      gb.push(`${g.ingest_errors} ingest error${g.ingest_errors === 1 ? '' : 's'}`);
    if (g.think != null && g.think_cap && g.think >= g.think_cap)
      gb.push(`thinking capped (${g.think}/${g.think_cap})`);
    if (g.research != null && g.research_cap && g.research >= g.research_cap)
      gb.push(`research capped (${g.research}/${g.research_cap})`);
    if (gb.length) rows.push(['/mind', 'System', gb.join(' · '), false]);
    if (!rows.length) rows.push(['', 'All quiet', 'Nothing needs you right now.', true]);
    // The map's one line, and it comes AFTER the quiet check on purpose: the
    // next trip is news, not a thing that needs you, so a household whose
    // only row is a trip still gets told the room is quiet. A pin with no
    // date is a plan without a week in it and stays off the list entirely.
    const nextTrip = (f.map.trips || []).filter(t => t && t.upcoming)[0];
    if (nextTrip) rows.push(['/trips', 'Trip',
      nextTrip.location ? `${nextTrip.title} — ${nextTrip.location}` : (nextTrip.title || ''),
      true]);
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

  if (!useRoom) {
    fallback.style.display = 'block';
    // Paint the calm rows BEFORE the first poll is even in flight. A blank
    // list is indistinguishable from a broken page, and there are two ways
    // to stay blank for good: a slow first answer, and a 403 — a child who
    // followed the link gets the shell and never gets a payload. Law 2 says
    // an unanswered room is calm, so say so out loud rather than showing
    // nothing at all.
    renderFallback(null);
    poll(renderFallback);
    return;
  }

  // =====================================================================
  // 2. canvas textures
  // =====================================================================
  // Deterministic noise: the room is drawn the same way every load, so a
  // screenshot is reproducible and nothing shuffles under a poll.
  let _seed = 20260903;
  function rnd() { _seed = (_seed * 1664525 + 1013904223) % 4294967296; return _seed / 4294967296; }

  // A stable 0..1 from a name (FNV-1a). Where a person's cluster sits on the
  // screen and where a trip's pin sits on the map are DECORATION, and
  // decoration that reshuffles every 60s poll reads as data changing. This
  // keeps the same name in the same place for as long as it is the same name.
  function hash01(s, salt) {
    const str = String(salt || '') + '|' + String(s == null ? '' : s);
    let h = 2166136261;
    for (let i = 0; i < str.length; i++) {
      h ^= str.charCodeAt(i); h = Math.imul(h, 16777619);
    }
    return ((h >>> 0) % 1000003) / 1000003;
  }

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
    bg: 0x120f0c, paper: 0xf6efdd,
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
  // detail surfaces — the text a zone paints when somebody leans into it
  // =====================================================================
  // One `panel` is a hidden plane with a canvas behind it. The canvas is
  // minted on its FIRST paint, and a paint only ever happens because
  // somebody leaned in: an idle room allocates none of the forty of them,
  // and a visit that never leans anywhere allocates none at all.
  //
  // `TX` is texels per design pixel, so a 2x screen gets a sharp texture and
  // a 1x screen is not asked to carry four times the bytes for nothing —
  // the same device-pixel-ratio discipline the renderer itself is under.
  const TX = Math.min(devicePixelRatio || 1, 2) * 2;

  function panel(pw, ph, cw, ch, o) {
    o = o || {};
    const mat = new THREE.MeshBasicMaterial({
      transparent: true, depthWrite: false,
      side: o.side || THREE.FrontSide
    });
    const m = new THREE.Mesh(new THREE.PlaneGeometry(pw, ph), mat);
    m.visible = false;
    m.renderOrder = 4;                       // over the surface it sits on
    m.userData.pw = pw; m.userData.ph = ph;
    m.userData.paint = function (draw) {
      let g = m.userData.g;
      if (!g) {
        const c = document.createElement('canvas');
        c.width = Math.max(2, Math.round(cw * TX));
        c.height = Math.max(2, Math.round(ch * TX));
        g = c.getContext('2d');
        m.userData.g = g;
        const t = new THREE.CanvasTexture(c);
        t.encoding = THREE.sRGBEncoding;
        // No mipmaps: this texture is only ever read from close up, and a
        // mipmapped one is read soft exactly when somebody leaned in to
        // read it.
        t.generateMipmaps = false;
        t.minFilter = t.magFilter = THREE.LinearFilter;
        try { t.anisotropy = R.capabilities.getMaxAnisotropy(); } catch (e) { }
        mat.map = t; mat.needsUpdate = true;
      }
      g.setTransform(g.canvas.width / cw, 0, 0, g.canvas.height / ch, 0, 0);
      g.clearRect(0, 0, cw, ch);
      g.textAlign = 'left'; g.textBaseline = 'alphabetic';
      draw(g, cw, ch);
      mat.map.needsUpdate = true;
    };
    return m;
  }

  // Wrapping and truncation, both of which say when they ran out of room
  // rather than stopping mid-word and leaving the reader to guess.
  function wrapText(g, text, maxW, maxLines) {
    const words = String(text == null ? '' : text).split(/\s+/).filter(Boolean);
    const lines = [];
    let cur = '', over = false;
    for (let i = 0; i < words.length; i++) {
      const t = cur ? cur + ' ' + words[i] : words[i];
      if (cur && g.measureText(t).width > maxW) {
        lines.push(cur); cur = words[i];
        if (lines.length >= maxLines) { over = true; break; }
      } else cur = t;
    }
    if (!over && cur) lines.push(cur);
    if (over && lines.length) {
      let last = lines[lines.length - 1];
      while (last.length > 1 && g.measureText(last + '…').width > maxW)
        last = last.slice(0, -1);
      lines[lines.length - 1] = last + '…';
    }
    return lines.slice(0, maxLines);
  }

  function fitText(g, text, maxW) {
    let s = String(text == null ? '' : text);
    if (g.measureText(s).width <= maxW) return s;
    while (s.length > 1 && g.measureText(s + '…').width > maxW) s = s.slice(0, -1);
    return s + '…';
  }

  const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
               'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  function dayChip(ts) {                     // epoch seconds -> 'Sep 12', or ''
    const n = Number(ts);
    if (!isFinite(n) || n <= 0) return '';
    const d = new Date(n * 1000);
    return MON[d.getMonth()] + ' ' + d.getDate();
  }
  const F = px => `600 ${px}px system-ui, 'Segoe UI', sans-serif`;
  const FB = px => `700 ${px}px system-ui, 'Segoe UI', sans-serif`;
  const INK = '#2f2519', INK2 = '#6b5c46';

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
    stickies:  { meshes: [], url: null,           parts: {}, summary: '' },  // findings have no page yet (Needs-You tile unbuilt) — the focused stickies ARE the findings view; a false destination is worse than none
    calendar:  { meshes: [], url: '/dashboard',   parts: {}, summary: '' },
    window:    { meshes: [], url: '/mind',        parts: {}, summary: '' },
    keys:      { meshes: [], url: '/config#cars', parts: {}, summary: '' },
    contracts: { meshes: [], url: '/dashboard',   parts: {}, summary: '' },
    binders:   { meshes: [], url: '/programs',    parts: {}, summary: '' },
    gauges:    { meshes: [], url: '/mind',        parts: {}, summary: '' },
    // The screen is the one zone that opens no page. There is no "Argyle's
    // graph" page to send anybody to, and inventing a destination for a tap
    // is worse than the tap doing the obvious thing: it puts the cursor in
    // the bar you would ask him from. `act` instead of `url`, so nothing
    // navigates.
    monitor:   { meshes: [], url: '',             parts: {}, summary: '' },
    map:       { meshes: [], url: '/trips',       parts: {}, summary: '' }
  };
  // Every zone leans in now, and `focusFor` computes the preset from the
  // zone's own bounding box. The board keeps its hand-tuned one, which the
  // generic fit lands within a few centimetres of anyway: the whole corkboard
  // including its bottom row of pins, framed at 1440x900 by screenshot.
  //
  // The desk's used to be hand-tuned too, standing back far enough to hold
  // the whole desk. That was right when the desk had nothing to read on it
  // and wrong the moment its stacks started carrying their plan's own line —
  // from across the room the lines were marks, not words. It uses the
  // generic fit now, over `focusMeshes` (declared with the stacks) so the
  // legs and the drawer unit do not drag the camera back out again.
  ZONES.board.focus = { p: new THREE.Vector3(.5, 5.0, 1.25), l: new THREE.Vector3(.5, 4.66, -6.13) };
  ZONES.board.focusHand = true;

  // Tapping Argyle's screen puts the cursor where you would talk to him.
  // The pulse is one injected rule rather than a template edit, so the page
  // shell stays exactly as it was; both are removed again on their own.
  (function () {
    const s = document.createElement('style');
    s.textContent =
      '@keyframes study-ask-pulse{0%{box-shadow:0 0 0 0 rgba(232,179,106,.5)}' +
      '70%{box-shadow:0 0 0 16px rgba(232,179,106,0)}' +
      '100%{box-shadow:0 0 0 0 rgba(232,179,106,0)}}' +
      '.study-ask-glow{animation:study-ask-pulse 1s ease-out 2;border-radius:16px}';
    document.head.appendChild(s);
  })();
  let askTimer = 0;
  ZONES.monitor.act = function () {
    const i = document.getElementById('chat-input');
    if (i) { i.focus(); if (i.scrollIntoView) i.scrollIntoView({ block: 'nearest' }); }
    const bar = document.getElementById('chat-overlay-container');
    if (!bar) return;
    bar.classList.remove('study-ask-glow');
    void bar.offsetWidth;                     // restart the animation on a re-tap
    bar.classList.add('study-ask-glow');
    clearTimeout(askTimer);
    askTimer = setTimeout(() => bar.classList.remove('study-ask-glow'), 2100);
  };

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
  const SILL = { y: WIN.y - WIN.h / 2 - WIN.f, top: WIN.y - WIN.h / 2 - WIN.f + .06 };
  box(.42, .12, WIN.w + WIN.f * 2, 0x6a4c31, WIN.x + .1, SILL.y, WIN.z, { noCast: true });
  // The card that stands on the sill when somebody leans in: the week's own
  // signs, said as levels. Hidden the rest of the time — an idle window is
  // weather, not a readout — and standing ON the sill, never hovering.
  const winCard = new THREE.Group();
  winCard.position.set(WIN.x + .16, SILL.top + .40, WIN.z);
  winCard.rotation.y = Math.PI / 2;                  // face the room
  scene.add(winCard);
  const winBack = put(rbox(1.5, .8, .05, .04, M(0xf3ead2, { roughness: .95 })),
    0, 0, 0, { parent: winCard });
  winBack.visible = false;
  const winProp = box(.06, .3, .05, 0xb9a884, 0, -.2, -.12,
    { parent: winCard, rx: .38, noCast: true });
  winProp.visible = false;
  const winText = panel(1.4, .72, 320, 165);
  winText.position.set(0, 0, .05);
  winCard.add(winText);
  reg('window', winBack); reg('window', winText);
  ZONES.window.parts = { card: winBack, prop: winProp, text: winText };
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
  // The working surface, INCLUDING the rounded-extrude bevel: rbox adds
  // bevelThickness to each face, so the wood a mug actually rests on is
  // .02 above `DESK.y + DESK.t / 2`. Everything on this desk used to be set
  // down at that lower number and sank the same .02 into it.
  const TOP = DESK.y + DESK.t / 2 + .02;
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
  // The bezel and the glass are the MONITOR's zone; the sticky notes stuck
  // around them stay the findings' own. Two different things live on this
  // one piece of furniture and each answers for itself.
  reg('monitor', put(rbox(BEZ.w, BEZ.h, BEZ.d, .06, M(PAL.dark, { roughness: .55 })), 0, 0, 0, { parent: monHead }));
  // What is on the screen: a node graph, one cluster per person, drawn into
  // an offscreen canvas and uploaded as a texture. 256x150 is the plane's
  // own aspect (1.71) to the pixel, so nothing is stretched.
  const GR = { w: 256, h: 150 };
  const grCanvas = document.createElement('canvas');
  grCanvas.width = GR.w; grCanvas.height = GR.h;
  const grCtx = grCanvas.getContext('2d');
  grCtx.fillStyle = '#080b11'; grCtx.fillRect(0, 0, GR.w, GR.h);
  const grTex = new THREE.CanvasTexture(grCanvas);
  grTex.encoding = THREE.sRGBEncoding;
  const screen = put(new THREE.Mesh(new THREE.PlaneGeometry(BEZ.w - .34, BEZ.h - .3),
    new THREE.MeshBasicMaterial({ map: grTex, color: 0xffffff })),
    0, .02, BEZ.front + .008, { parent: monHead });
  reg('monitor', screen);
  // The labels a focused screen puts beside each cluster. Its own canvas
  // rather than the graph's, so the animation stays at 256x150 and ten
  // frames a second while the words are drawn once, sharp, at four times
  // the resolution.
  const monLabels = panel(BEZ.w - .34, BEZ.h - .3, 512, 300);
  monLabels.position.set(0, .02, BEZ.front + .016);
  monHead.add(monLabels);
  reg('monitor', monLabels);
  ZONES.monitor.parts = { screen: screen, labels: monLabels, key: '' };
  // The head was built facing the chair; a lean-in stands where it faces.
  ZONES.monitor.faceYaw = monHead.rotation.y;
  ZONES.stickies.faceYaw = monHead.rotation.y;

  // ---- the graph the screen is running --------------------------------
  // One cluster per person; the cluster's SIZE is the only thing here that
  // came from the house (that week's events). The orbiting, the webbing
  // between near dots and the pulse between two clusters are decoration and
  // claim nothing — the same line the evidence board's tails sit on.
  // Layout is rebuilt only when the payload changes; the redraw is capped at
  // ten frames a second and stops dead while the tab is hidden.
  const GR_HUE = [10, 202, 96, 44, 268, 168, 320, 134];
  const GR_STEP = .1, GR_LINK2 = 170, GR_PULSE = 1.1;
  let grClusters = [], grNext = 0, grDirty = true, grPulseT = -1, grPulseAt = 3, grPair = 0;

  function buildGraph(rows) {
    grClusters = [];
    const n = rows.length;
    rows.forEach((row, i) => {
      const name = String(row && row.name || i);
      const cnt = Math.min(Math.max((row && row.count) | 0, 0) * 3 + 4, CAPS.nodes);
      const a = (i / Math.max(n, 1)) * Math.PI * 2 + hash01(name, 'a') * .8;
      const rr = n < 2 ? 0 : .55 + hash01(name, 'r') * .38;
      const cl = { hue: GR_HUE[i % GR_HUE.length],
                   cx: GR.w * .5 + Math.cos(a) * GR.w * .32 * rr,
                   cy: GR.h * .5 + Math.sin(a) * GR.h * .31 * rr,
                   nodes: [] };
      // A busier week is a wider, denser cloud, not just more dots in the
      // same spot: the spread grows with the square root of the count.
      const spread = 4 + Math.sqrt(cnt) * 3.2;
      for (let j = 0; j < cnt; j++) {
        const t1 = hash01(name, 'n' + j), t2 = hash01(name, 'm' + j);
        cl.nodes.push({ a: t1 * Math.PI * 2, r: 2 + Math.sqrt(t2) * spread,
                        sp: .05 + t1 * .12, ph: t2 * 6.283, x: 0, y: 0 });
      }
      grClusters.push(cl);
    });
    grDirty = true;
  }

  function drawGraph(t) {
    const g = grCtx, w = GR.w, h = GR.h;
    g.fillStyle = '#080b11'; g.fillRect(0, 0, w, h);
    g.strokeStyle = 'rgba(120,160,220,.05)'; g.lineWidth = 1;
    g.beginPath();
    for (let x = 16; x < w; x += 32) { g.moveTo(x + .5, 0); g.lineTo(x + .5, h); }
    for (let y = 15; y < h; y += 30) { g.moveTo(0, y + .5); g.lineTo(w, y + .5); }
    g.stroke();
    // Two passes on purpose: every halo first, so a neighbour's glow never
    // washes over dots that were already drawn.
    for (let c = 0; c < grClusters.length; c++) {
      const cl = grClusters[c], N = cl.nodes;
      for (let i = 0; i < N.length; i++) {
        const nd = N[i];
        nd.x = cl.cx + Math.cos(nd.a + t * nd.sp) * nd.r + Math.sin(t * 1.3 + nd.ph) * 1.1;
        nd.y = cl.cy + Math.sin(nd.a + t * nd.sp) * nd.r * .88 + Math.cos(t * 1.1 + nd.ph) * 1.1;
      }
      const rad = 9 + N.length * .8;
      const halo = g.createRadialGradient(cl.cx, cl.cy, 1, cl.cx, cl.cy, rad);
      halo.addColorStop(0, `hsla(${cl.hue},80%,60%,.22)`);
      halo.addColorStop(1, `hsla(${cl.hue},80%,60%,0)`);
      g.fillStyle = halo;
      g.fillRect(cl.cx - rad, cl.cy - rad, rad * 2, rad * 2);
    }
    for (let c = 0; c < grClusters.length; c++) {
      const cl = grClusters[c], N = cl.nodes;
      g.strokeStyle = `hsla(${cl.hue},72%,66%,.22)`; g.lineWidth = .7;
      g.beginPath();
      for (let i = 0; i < N.length; i++)
        for (let j = i + 1; j < N.length; j++) {
          const dx = N[i].x - N[j].x, dy = N[i].y - N[j].y;
          if (dx * dx + dy * dy < GR_LINK2) { g.moveTo(N[i].x, N[i].y); g.lineTo(N[j].x, N[j].y); }
        }
      g.stroke();
      for (let i = 0; i < N.length; i++) {
        g.fillStyle = `hsl(${cl.hue},76%,${56 + (i % 3) * 7}%)`;
        g.beginPath(); g.arc(N[i].x, N[i].y, 1.4, 0, 6.283); g.fill();
      }
      g.fillStyle = `hsl(${cl.hue},84%,74%)`;
      g.beginPath(); g.arc(cl.cx, cl.cy, 2.5, 0, 6.283); g.fill();
    }
    // every few seconds one cluster says something to another
    const n = grClusters.length;
    if (n < 2) { grPulseT = -1; grPulseAt = t + 3; return; }
    if (grPulseT < 0 && t >= grPulseAt) { grPulseT = t; grPair++; }
    if (grPulseT < 0) return;
    const u = (t - grPulseT) / GR_PULSE;
    if (u >= 1) { grPulseT = -1; grPulseAt = t + 3.2 + (grPair % 3) * .6; return; }
    const A = grClusters[grPair % n];
    const B = grClusters[((grPair % n) + 1 + (grPair % (n - 1))) % n];
    // Drawn fat and bright on purpose: this canvas is MINIFIED onto a screen
    // a fifth of the room wide, and a hairline at .4 alpha averages away to
    // nothing by the time it is a monitor across the study.
    const fade = Math.sin(u * Math.PI);
    g.strokeStyle = `rgba(210,228,255,${(.30 * fade).toFixed(3)})`; g.lineWidth = 3.4;
    g.beginPath(); g.moveTo(A.cx, A.cy); g.lineTo(B.cx, B.cy); g.stroke();
    g.strokeStyle = `rgba(238,246,255,${(.85 * fade).toFixed(3)})`; g.lineWidth = 1.5;
    g.beginPath(); g.moveTo(A.cx, A.cy); g.lineTo(B.cx, B.cy); g.stroke();
    g.fillStyle = `rgba(255,255,255,${fade.toFixed(3)})`;
    g.beginPath();
    g.arc(A.cx + (B.cx - A.cx) * u, A.cy + (B.cy - A.cy) * u, 3.2, 0, 6.283);
    g.fill();
  }

  function stepGraph(t) {
    if (document.hidden) return;              // a hidden tab draws nothing
    if (!grDirty && (t < grNext || !grClusters.length)) return;
    grNext = t + GR_STEP; grDirty = false;
    drawGraph(t);
    grTex.needsUpdate = true;                 // a texture upload, not geometry
  }

  // ---- back to the monitor itself -------------------------------------
  // stand: post down to the desk surface, foot flat on it
  box(.2, .46, .13, PAL.dark, 0, -.88, -.02, { parent: monHead, mo: { roughness: .55 } });
  put(rbox(.9, .6, .06, .08, M(PAL.dark, { roughness: .55 })), 0, -1.06, .06,
    { parent: monHead, rx: Math.PI / 2 });
  // stickies: five slots around the bezel, the top one carries the worst sign
  const stickies = [], stickyFaces = [];
  [[-.93, .40, .09], [-.93, .02, -.06], [-.93, -.36, .05],
   [.93, .36, -.07], [.93, -.02, .06]].forEach(([x, y, rz]) => {
    const s = box(.34, .34, .025, PAL.pinWarn, x, y, BEZ.front + .02,
      { parent: monHead, rz: rz, mo: { roughness: 1 } });
    s.visible = false; stickies.push(reg('stickies', s));
    const f = panel(.30, .30, 150, 150);
    f.position.set(x, y, BEZ.front + .036);
    f.rotation.z = rz;
    monHead.add(f);
    stickyFaces.push(reg('stickies', f));
  });
  ZONES.stickies.parts = { notes: stickies, faces: stickyFaces };

  // keyboard + mouse + a cable. The turn is `rz`, NOT `ry`: with the default
  // XYZ Euler order a `ry` is composed BEFORE the `rx` that lays the slab
  // flat, so it comes out as a tilt about world X rather than a turn on the
  // desk — which is what buried one end of this keyboard in the wood and
  // lifted the other into the air. Applied after the flip, `rz` is the yaw.
  put(rbox(1.42, .48, .07, .03, M(0x3a352e, { roughness: .6 })),
    .45, TOP + .045, 1.92, { rx: Math.PI / 2, rz: .1 });
  put(rbox(.28, .42, .1, .12, M(0x3a352e, { roughness: .6 })),
    1.36, TOP + .055, 2.36, { rx: Math.PI / 2, rz: .1 });
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
    // the plan's own line, printed on the top sheet of its pile
    const label = panel(SHEET.w * .96, SHEET.d * .94, 240, 172);
    label.rotation.x = -Math.PI / 2;
    label.position.set(x, TOP + .1, z);
    scene.add(label);
    reg('desk', label);
    return { x: x, z: z, sheets: sheets, due: due, label: label };
  });
  ZONES.desk.parts = { stacks: stacks };
  // The desk's SIGNAL is the paper, not the furniture it is lying on. A
  // lean-in frames these; the desktop, the legs and the drawer unit stay
  // registered as hit targets and stay out of the framing.
  ZONES.desk.focusMeshes = stacks.reduce(
    (a, s) => a.concat(s.sheets, [s.due, s.label]), []);

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
  // What is waiting, printed on the top sheet of the pile. One surface
  // rather than one per sheet: in a real in-tray only the top sheet is
  // visible at all, and five titles half-hidden under each other would be
  // a drawing of text rather than text.
  const trayLabel = panel(1.0, .68, 260, 178);
  trayLabel.rotation.x = -Math.PI / 2;
  trayLabel.position.set(TRAY.x, TOP + .14, TRAY.z);
  scene.add(trayLabel);
  reg('tray', trayLabel);
  ZONES.tray.parts = { sheets: traySheets, label: trayLabel };

  // ---- contracts: signature slips fanned out beside the keyboard
  const slips = [];
  for (let i = 0; i < 4; i++) {
    const s = box(.8, .035, .58, 0xfaf3e2, -.55 + i * .015, TOP + .03 + i * .035, 2.35 + i * .02,
      { ry: .3 - i * .12, mo: { roughness: 1 } });
    s.visible = false; slips.push(reg('contracts', s));
  }
  const seal = box(.1, .012, .1, 0xb03a2e, -.14, TOP + .18, 2.22, { mo: { roughness: .8 } });
  seal.visible = false; reg('contracts', seal);
  put(rbox(.46, .055, .055, .025, M(0x8a5a25, { roughness: .4 })), -.75, TOP + .05, 2.62, { ry: .95 });
  const slipLabel = panel(.64, .48, 200, 150);
  slipLabel.rotation.x = -Math.PI / 2;
  slipLabel.position.set(-.55, TOP + .1, 2.35);
  scene.add(slipLabel);
  reg('contracts', slipLabel);
  ZONES.contracts.parts = { slips: slips, seal: seal, label: slipLabel };

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
  // The numbers the needles are pointing at, painted over the whole face.
  // Transparent everywhere it does not say something, so the needles and
  // the lamp behind it are as visible as they ever were.
  const gaugeFace = panel(GAU.w, GAU.h, 340, 186);
  gaugeFace.position.set(0, 0, GAU.front + .03);
  gaugeBody.add(gaugeFace);
  reg('gauges', gaugeFace);
  ZONES.gauges.parts = { needles: needles, lamp: lamp, face: gaugeFace };
  ZONES.gauges.faceYaw = gaugeBody.rotation.y;

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
  //
  // The base is built as five GROUPS, each yawed to its own leg's direction
  // and everything inside authored along that group's +z. The point is that
  // the spoke and the caster cannot then disagree about where the leg points,
  // which is exactly what went wrong before: the spoke was turned by
  // `-a + PI/2` while its caster was placed along `a`, two directions that
  // coincide only where cos a is zero. Four legs out of five aimed somewhere
  // their caster was not, and the casters read as loose pucks on the rug.
  //
  // The floor under the chair is the RUG, not the boards, so the legs stand
  // on the rug's own top face — a spoke set down at y = 0 is a spoke sunk
  // through the pile.
  const chairMat = M(0x413a32, { roughness: .72 });
  const CHAIR = { x: .3, z: 3.62, floor: .055 };
  put(rbox(1.3, 1.25, .18, .26, chairMat), CHAIR.x, 1.18, 3.55, { rx: Math.PI / 2 });
  put(rbox(1.2, 1.45, .16, .3, chairMat), CHAIR.x, 2.1, 4.22, { rx: .17 });
  const baseMat = M(0x2c2823, { roughness: .5, metalness: .3 });
  const casterMat = M(0x1e1b18, { roughness: .6 });
  cyl(.1, .1, .98, 12, baseMat, CHAIR.x, CHAIR.floor + .65, CHAIR.z, {});   // gas column
  cyl(.17, .21, .18, 12, baseMat, CHAIR.x, CHAIR.floor + .09, CHAIR.z, {}); // hub
  for (let i = 0; i < 5; i++) {
    const leg = new THREE.Group();
    leg.position.set(CHAIR.x, CHAIR.floor, CHAIR.z);
    leg.rotation.y = i * Math.PI * 2 / 5 + .3;      // the leg's own direction
    scene.add(leg);
    // the spoke, running out from under the hub with its underside ON the rug
    put(rbox(.22, .13, .52, .05, baseMat), 0, .085, .30, { parent: leg });
    // the caster: a wheel on the spoke's own end, on a tangential axle, its
    // tyre touching the rug rather than hovering a centimetre over it
    cyl(.075, .075, .05, 10, casterMat, 0, .075, .565,
      { parent: leg, rz: Math.PI / 2 });
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
  // The length of thread a stalled card comes apart into. Short enough to
  // clear the card in the row below (rows are 1.02 apart, cards .44 tall),
  // long enough to read as unravelling from across the room. One shared
  // material: nothing ever recolours a tail, so all 14 can hold the same one.
  const TAIL_H = .34;
  const tailMat = M(PAL.string, { roughness: .95 });
  const pins = [], boardRules = [];
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
        boardRules.push(box(CARD.w * .62, .016, .008, 0x9a8f7a, 0,
          -CARD.h / 2 + .06 - i * .1, .022, { parent: g, noCast: true }));
      // and what the card actually says, once somebody is near enough to
      // read it. The two ruled bars stand down while it is up: a card does
      // not carry a scribble and a sentence at the same time.
      const note = panel(CARD.w * .92, CARD.h * .84, 200, 128);
      note.position.set(0, -CARD.h / 2, .026);
      g.add(note);
      reg('board', note);
      // A stalled card comes apart a little: a short length of thread hangs
      // off the bottom of it. This is DECORATION and says so — it connects
      // to nothing and claims no relation, unlike a string drawn between two
      // pins, which would assert a link the app does not store. It is
      // parented to the pin group, so it sags and sways with the card it
      // belongs to for free.
      const tail = cyl(.011, .006, TAIL_H, 5, tailMat, 0,
        -CARD.h - TAIL_H / 2 + .01, .03,
        { parent: g, rz: (r % 2 ? .17 : -.13) + (rnd() - .5) * .1 });
      tail.visible = false;
      const rest = (rnd() - .5) * .05;
      g.rotation.z = rest;
      g.visible = false;
      pins.push({ group: g, card: card, tail: tail, rest: rest, note: note });
    }
  }
  ZONES.board.parts = { pins: pins, face: pinFace };
  ZONES.board.detail = { on: pins.map(p => p.note), off: boardRules };

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
  const calRules = [];
  for (let i = 0; i < 2; i++)                            // ruled lines under the week
    calRules.push(box(CAL.w - .3, .02, .02, 0xcfc3a6, CAL.x, CAL.y - .82 - i * .22,
      CAL.z + .04, { noCast: true }));
  // The page a leaned-in reader gets: the same seven days, drawn as a real
  // grid with the dates on them and what is on each one. It covers the
  // seven blocks below the header, so those stand down while it is up —
  // the red they carry is redrawn here, so no signal goes with them.
  const calFace = panel(CAL.w - .1, 1.62, 420, 348);
  calFace.position.set(CAL.x, CAL.y - .12, CAL.z + .07);
  scene.add(calFace);
  reg('calendar', calFace);
  ZONES.calendar.parts = { cells: cells, face: calFace };
  ZONES.calendar.detail = { on: [calFace], off: cells.concat(calRules) };

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
    // The readout, on the wall UNDER its own key rather than on the key: a
    // key is 6cm of brass and a level bar drawn on one is a level bar
    // nobody can read. Clear of the lowest thing that hangs off the hook
    // (the tag, which stops around 3.55) so the two never overlap.
    const cardMat = M(0xefe4c8, { roughness: .95 });
    const readCard = put(rbox(.43, .36, .03, .03, cardMat), x, 3.28, KEY.z + .04, {});
    readCard.visible = false;
    const readout = panel(.40, .33, 200, 165);
    readout.position.set(x, 3.28, KEY.z + .11);
    scene.add(readout);
    reg('keys', readCard); reg('keys', readout);
    keySlots.push({ group: g, tag: tag, card: tagCard, hook: hook,
                    readCard: readCard, readout: readout });
    reg('keys', tagCard);
  }
  ZONES.keys.parts = { slots: keySlots };
  ZONES.keys.detail = {
    on: keySlots.map(k => k.readCard).concat(keySlots.map(k => k.readout)), off: []
  };

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
    // The spine, read the way a spine is read: bottom to top, title first
    // and the week under it. Parented to the binder, so a pulled-out one
    // carries its own label out with it.
    const spine = panel(.34, .90, 120, 318);
    spine.position.set(0, 0, .40);
    b.add(spine);
    b.userData.spine = spine;
    reg('binders', spine);
  }
  ZONES.binders.parts = { binders: binders };
  ZONES.binders.detail = { on: binders.map(b => b.userData.spine), off: [] };
  // plant on the shelf's free end
  cyl(.26, .2, .42, 12, M(PAL.pot, { roughness: .9 }), SHELF.x + 1.3, SHELF.y + .3, SHELF.z, {});
  for (let i = 0; i < 6; i++)
    box(.09, .72 + rnd() * .4, .09, PAL.plant, SHELF.x + 1.3 + (rnd() - .5) * .34,
      SHELF.y + .82 + rnd() * .2, SHELF.z + (rnd() - .5) * .3,
      { rz: (rnd() - .5) * .55, rx: (rnd() - .5) * .35 });
  // photo frames: the free stretch of wall between the keys and the board,
  // plus one standing on the shelf beside the plant (the room is somebody's).
  //
  // The second one used to stand on the desk's far-left corner. It was
  // grounded there in the arithmetic — its foot was on the wood — but the
  // desk behind it is edge-on from the room's own camera, so what a person
  // saw was a picture frame hanging in mid-air against the baseboard. The
  // shelf gives it a surface that reads AS a surface from where the room is
  // actually looked at.
  box(.55, .66, .05, 0x5a4029, -3.9, 5.3, -6.14, { noCast: true });
  box(.42, .53, .02, 0xd8a05a, -3.9, 5.3, -6.1, { noCast: true });
  const frameGrp = new THREE.Group();
  frameGrp.position.set(SHELF.x + .80, SHELF.y + .08 + .25, SHELF.z + .04);
  frameGrp.rotation.y = .22;
  scene.add(frameGrp);
  put(rbox(.38, .46, .05, .03, M(0x5a4029, { roughness: .7 })), 0, 0, 0, { parent: frameGrp });
  put(new THREE.Mesh(new THREE.PlaneGeometry(.26, .34), M(0x6f9ad0, { roughness: .8 })),
    0, 0, .046, { parent: frameGrp });
  box(.06, .26, .05, 0x5a4029, 0, -.16, -.12, { parent: frameGrp, rx: -.4 });
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

  // =====================================================================
  // wall map — where the family is going, on a string from home
  // =====================================================================
  // The back wall is full (keys, photograph, board, calendar, clock) and the
  // side wall carries only the window, so the map hangs on the free stretch
  // between that window and the corner. Everything below lives in the map's
  // own group: its ry puts local +x along the wall and local +z out into the
  // room, so the map is authored flat and hung once.
  //
  // The one relation drawn here is one the app STORES — a trip has a
  // destination, and the family leaves from home to reach it. Where a pin
  // lands is decoration (a hash of the trip's own name, so it stays put),
  // and the drawing underneath is abstract on purpose: it is a map of
  // nowhere, and claims to be nothing else.
  const MAP = { x: -7.05, y: 4.45, z: -3.95, w: 2.6, h: 1.9, rail: .15 };
  const mapTex = canvasTex((g, w, h) => {
    g.fillStyle = '#c9b489'; g.fillRect(0, 0, w, h);
    const blob = (cx, cy, rx, ry, ph, fill, edge) => {
      g.beginPath();
      for (let a = 0; a <= 40; a++) {
        const th = a / 40 * Math.PI * 2;
        const rr = .82 + Math.sin(th * 3 + ph) * .15 + Math.sin(th * 5 + ph * 2) * .07;
        const x = cx + Math.cos(th) * rx * rr, y = cy + Math.sin(th) * ry * rr;
        if (a === 0) g.moveTo(x, y); else g.lineTo(x, y);
      }
      g.closePath(); g.fillStyle = fill; g.fill();
      g.strokeStyle = edge; g.lineWidth = 1.6; g.stroke();
    };
    blob(w * .30, h * .44, w * .26, h * .30, .6, '#a8ab7c', 'rgba(86,74,44,.5)');
    blob(w * .74, h * .34, w * .19, h * .22, 2.4, '#b0a878', 'rgba(86,74,44,.5)');
    blob(w * .62, h * .80, w * .21, h * .16, 4.1, '#9fa677', 'rgba(86,74,44,.45)');
    g.strokeStyle = 'rgba(96,78,48,.16)'; g.lineWidth = 1;
    for (let x = 24; x < w; x += 26) { g.beginPath(); g.moveTo(x, 0); g.lineTo(x, h); g.stroke(); }
    for (let y = 20; y < h; y += 26) { g.beginPath(); g.moveTo(0, y); g.lineTo(w, y); g.stroke(); }
    for (let i = 0; i < 500; i++) {                       // paper tooth
      g.fillStyle = `rgba(70,54,30,${rnd() * .07})`;
      g.fillRect(rnd() * w, rnd() * h, 1.6, 1.6);
    }
    g.strokeStyle = 'rgba(74,58,32,.45)'; g.lineWidth = 2;
    g.strokeRect(5, 5, w - 10, h - 10);
  }, 256, 188);
  const mapGrp = new THREE.Group();
  mapGrp.position.set(MAP.x, MAP.y, MAP.z);
  mapGrp.rotation.y = Math.PI / 2;
  scene.add(mapGrp);
  // The sun comes IN this wall, so its inner face is never lit by it: the
  // sheet carries its own faint emissive so the map is readable at night as
  // well as at noon, without becoming a lightbox in a warm room.
  const mapMat = new THREE.MeshStandardMaterial({
    map: mapTex, roughness: .95, metalness: 0,
    emissive: 0xffffff, emissiveMap: mapTex, emissiveIntensity: .34 });
  reg('map', box(MAP.w, MAP.h, .05, 0, 0, 0, 0,
    { parent: mapGrp, mat: mapMat, noCast: true }));
  const mapRail = M(0x5a4029, { roughness: .8 });
  [1, -1].forEach(s => {
    box(MAP.w + MAP.rail * 2, MAP.rail, MAP.rail * 1.2, 0, 0,
      s * (MAP.h / 2 + MAP.rail / 2), 0, { parent: mapGrp, mat: mapRail, noCast: true });
    box(MAP.rail, MAP.h + MAP.rail * 2, MAP.rail * 1.2, 0,
      s * (MAP.w / 2 + MAP.rail / 2), 0, 0, { parent: mapGrp, mat: mapRail, noCast: true });
  });
  // home: every string starts here, and it is the only fixed point on the map
  const HOME = { x: -.10, y: -.12 };
  put(new THREE.Mesh(new THREE.TorusGeometry(.075, .016, 6, 16),
    M(0x3c3630, { roughness: .5 })), HOME.x, HOME.y, .035, { parent: mapGrp });
  put(new THREE.Mesh(new THREE.SphereGeometry(.042, 10, 8),
    M(0xf2e6c8, { roughness: .6 })), HOME.x, HOME.y, .045, { parent: mapGrp });
  // Six pins and six strings, built ONCE. FURNITURE.map only ever moves,
  // aims, scales, colours and hides them — applyState allocates no geometry.
  const strMat = M(PAL.string, { roughness: .95, side: THREE.DoubleSide });
  const strCurve = new THREE.QuadraticBezierCurve3(
    new THREE.Vector3(0, 0, 0), new THREE.Vector3(.5, -.15, 0), new THREE.Vector3(1, 0, 0));
  const strGeo = new THREE.TubeGeometry(strCurve, 12, .012, 5, false);
  const mapPins = [];
  for (let i = 0; i < 6; i++) {
    // The string is authored once, from (0,0,0) to (1,0,0) with a sag in
    // it; a pin is reached by aiming it and stretching x to the distance,
    // and flipping y when the pin is to the left so the sag always hangs
    // DOWN rather than bowing back over itself.
    const str = new THREE.Mesh(strGeo, strMat);
    str.visible = false; mapGrp.add(str);
    const g = new THREE.Group();
    g.position.set(0, 0, .055); g.visible = false; mapGrp.add(g);
    const head = new THREE.Mesh(new THREE.SphereGeometry(.062, 12, 10),
      M(PAL.pinBad, { roughness: .45 }));
    g.add(head);
    const stalk = new THREE.Mesh(new THREE.CylinderGeometry(.013, .013, .08, 6),
      M(0xb9b0a0, { roughness: .4, metalness: .5 }));
    stalk.rotation.x = Math.PI / 2; stalk.position.z = -.045; g.add(stalk);
    reg('map', head);
    mapPins.push({ group: g, head: head, string: str });
  }
  // Names and dates beside the pins, drawn onto the paper rather than onto
  // little labels in the air: behind the pin heads, in front of the map.
  const mapLabels = panel(MAP.w - .1, MAP.h - .1, 520, 374);
  mapLabels.position.set(0, 0, .034);
  mapGrp.add(mapLabels);
  reg('map', mapLabels);
  ZONES.map.parts = { pins: mapPins, home: HOME, labels: mapLabels };
  ZONES.map.detail = { on: [mapLabels], off: [] };

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
  const CAPS = { pins: 14, sheets: 8, tray: 6, keys: 4, binders: 5, stickies: 5,
                 slips: 4, clusters: 8, nodes: 40, trips: 6 };

  // The rest of the detail registers: `on` is shown while the zone is
  // focused (each mesh may still veto with userData.want === false, which
  // is how an empty slot stays empty), `off` stands down while it is.
  // Board, calendar, keys, binders and map declared theirs where they were
  // built, because those two lists are the meshes they had to collect
  // anyway.
  ZONES.desk.detail = { on: stacks.map(s => s.label), off: [] };
  ZONES.tray.detail = { on: [trayLabel], off: [] };
  ZONES.stickies.detail = { on: stickyFaces, off: [] };
  ZONES.window.detail = { on: [winBack, winProp, winText], off: [] };
  ZONES.contracts.detail = { on: [slipLabel], off: [] };
  ZONES.gauges.detail = { on: [gaugeFace], off: [] };
  ZONES.monitor.detail = { on: [monLabels], off: [] };

  const FURNITURE = {
    // one pinned card per insight/thread; stalled ones yellow and sag,
    // overdue ones go red, and a stalled card grows the dangling thread tail
    // that reads as coming apart.
    //
    // What is deliberately NOT here: a string drawn between two pins. The
    // spec pictured one, and it survived a round of review as an "honest
    // by-index join" — which it was not. A line between an insight and a
    // thread is a claim that they are related, and nothing in this app
    // stores such a relation, so every line drawn would have been invented.
    // The payload still carries `strings` (permanently empty) so the shape
    // does not shift under an older client; when a real insight->thread link
    // is stored, THAT is what earns an edge here.
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
        p.tail.visible = !!(row.warn || row.bad);
        p.card.userData.pin = row;
        p.note.userData.want = true;
        glowIf(p.card.material, row.changed_ts);
      });
      P.forEach((p, i) => { if (!data[i]) p.note.userData.want = false; });
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
        // the printed sheet rides the top of whatever pile is actually there
        st.label.position.y = TOP + .035 + Math.max(n, 1) * .05;
        st.label.userData.want = !!p;
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
      z.parts.label.position.y = TOP + .09 + Math.max(n, 1) * .05;
      z.parts.label.userData.want = n > 0;
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
        z.parts.faces[i].userData.want = i < n;
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
      const has = (d.signs || []).length > 0;
      z.parts.card.userData.want = has;
      z.parts.prop.userData.want = has;
      z.parts.text.userData.want = has;
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
        k.readCard.userData.want = !!car;
        k.readout.userData.want = !!car;
      });
      const low = cars.filter(c => c.low).map(c => c.name);
      z.summary = low.length ? `${low.join(', ')} low` : (cars.length ? 'Cars fuelled' : '');
    },

    contracts: (d, z) => {
      const n = clamp(d.count | 0, 0, CAPS.slips);
      z.parts.slips.forEach((s, i) => { s.visible = i < n; });
      z.parts.seal.visible = n > 0;
      // printed on whichever slip ended up on top of the fan, nudged clear
      // of the mug handle that reaches over the slips' left edge
      const top = z.parts.slips[Math.max(n - 1, 0)];
      z.parts.label.position.set(top.position.x + .06, top.position.y + .028,
        top.position.z);
      z.parts.label.rotation.z = top.rotation.y;
      z.parts.label.userData.want = n > 0;
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
        b.userData.spine.userData.want = !!row;
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
    },

    // Argyle's screen. One cluster per person, sized by the week they are
    // walking into; the layout is rebuilt only when those numbers actually
    // change, and the animation that runs on it after that is decoration.
    monitor: (d, z) => {
      const rows = (d.clusters || []).slice(0, CAPS.clusters);
      const key = JSON.stringify(rows);
      if (key !== z.parts.key) { z.parts.key = key; buildGraph(rows); }
      const busy = rows.filter(r => r && (r.count | 0) > 0)
        .sort((a, b) => (b.count | 0) - (a.count | 0));
      let bits = busy.slice(0, 4).map(r => `${r.name} ${r.count}`).join(' · ');
      if (busy.length > 4) bits += ' · …';
      z.summary = bits ? `This week: ${bits}`
        : (rows.length ? 'A quiet week' : '');
    },

    // A pin per planned trip, each on its string home. The soonest one is
    // bigger and lit; a trip with no date yet is a pin like any other,
    // because a plan without a week in it is still a plan.
    map: (d, z) => {
      const trips = (d.trips || []).slice(0, CAPS.trips);
      const home = z.parts.home;
      z.parts.pins.forEach((p, i) => {
        const t = trips[i];
        p.group.visible = !!t;
        p.string.visible = !!t;
        if (!t) { p.group.userData.trip = null; return; }
        const seed = `${t.id || ''}|${t.title || ''}|${t.location || ''}`;
        const a = hash01(seed, 'pa') * Math.PI * 2;
        const rr = .45 + hash01(seed, 'pr') * .5;
        const px = home.x + Math.cos(a) * MAP.w * .32 * rr;
        const py = home.y + Math.sin(a) * MAP.h * .30 * rr;
        p.group.position.set(px, py, .055);
        p.group.scale.setScalar(t.upcoming ? 1.45 : 1);
        p.head.material.color.setHex(t.upcoming ? PAL.pinWarn : PAL.pinBad);
        p.head.material.emissive.setHex(t.upcoming ? 0x5a3204 : 0x000000);
        const dx = px - home.x, dy = py - home.y;
        p.string.position.set(home.x, home.y, .04);
        p.string.rotation.z = Math.atan2(dy, dx);
        p.string.scale.set(Math.max(Math.sqrt(dx * dx + dy * dy), .02),
                           dx < 0 ? -1 : 1, 1);
        p.group.userData.trip = t;
      });
      // Law 2: an empty map is a framed empty map, not an apology. It says
      // nothing beyond its own name until there is a trip to name.
      const titles = trips.map(t => t.title).filter(Boolean);
      let line = titles.join(', ');
      if (line.length > 64) line = line.slice(0, 63).trimEnd() + '…';
      z.summary = line ? `Trips: ${line}` : '';
    }
  };

  // =====================================================================
  // 5b. DETAIL — what a zone SAYS once somebody has leaned in
  // =====================================================================
  // One row per zone, and every one of them draws into a canvas: no DOM, no
  // markup, no innerHTML. A row runs at most once per payload — the paint is
  // cached and only invalidated when applyState sees that zone's own slice
  // of the payload change — so an idle room is exactly as quiet as it was.
  const DETAIL = {
    board: (d, z) => {
      const rows = (d.pins || []).slice(0, CAPS.pins);
      z.parts.pins.forEach((p, i) => {
        const row = rows[i];
        if (!row) return;
        p.note.userData.paint((g, w, h) => {
          g.fillStyle = INK; g.textBaseline = 'top'; g.font = F(19);
          wrapText(g, row.label, w - 16, 3)
            .forEach((L, k) => g.fillText(L, 8, 14 + k * 23));
        });
      });
    },

    desk: (d, z) => {
      const plans = (d || []).slice(0, z.parts.stacks.length);
      z.parts.stacks.forEach((st, i) => {
        const p = plans[i];
        if (!p) return;
        st.label.userData.paint((g, w, h) => {
          g.textBaseline = 'top';
          const n = p.open_steps | 0;
          g.font = F(19); g.fillStyle = p.due ? '#a05a18' : INK2;
          g.fillText(`${n} step${n === 1 ? '' : 's'} open${p.due ? ' · one due' : ''}`,
            10, 12);
          g.fillStyle = INK; g.font = F(23);
          wrapText(g, p.line || '', w - 20, 3)
            .forEach((L, k) => g.fillText(L, 10, 44 + k * 27));
        });
      });
    },

    tray: (d, z) => {
      const items = (d.items || []).slice(0, 5);
      z.parts.label.userData.paint((g, w, h) => {
        g.textBaseline = 'top';
        g.fillStyle = INK2; g.font = F(14);
        g.fillText('waiting', 12, 18);
        g.fillStyle = INK; g.font = F(17);
        items.forEach((it, k) =>
          g.fillText(fitText(g, it.title || '', w - 24), 12, 44 + k * 25));
      });
    },

    stickies: (d, z) => {
      const items = (d.items || []).slice(0, CAPS.stickies);
      z.parts.faces.forEach((f, i) => {
        const it = items[i];
        if (!it) return;
        f.userData.paint((g, w, h) => {
          g.fillStyle = '#463612'; g.textBaseline = 'top'; g.font = F(18);
          wrapText(g, it.line || '', w - 14, 6)
            .forEach((L, k) => g.fillText(L, 7, 12 + k * 21));
        });
      });
    },

    // The wall calendar, drawn as the page it actually is: seven dated
    // cells, what is on each one in whoever is driving it's own colour, and
    // the same red on a day nobody is covering.
    calendar: (d, z) => {
      const days = (d.days || []).slice(0, 7);
      z.parts.face.userData.paint((g, w, h) => {
        const pad = 7, cols = 4;
        const cw = (w - pad * 2) / cols, ch = (h - pad * 2) / 2;
        g.fillStyle = '#efe6cd'; g.fillRect(0, 0, w, h);
        for (let i = 0; i < 7; i++) {
          const cx = pad + (i % cols) * cw, cy = pad + ((i / cols) | 0) * ch;
          const day = days[i];
          g.fillStyle = (day && day.unassigned > 0) ? '#f0cbc0' : '#f8f2e0';
          g.fillRect(cx + 1, cy + 1, cw - 2, ch - 2);
          g.strokeStyle = '#cbbc98'; g.lineWidth = 1.2;
          g.strokeRect(cx + 1.5, cy + 1.5, cw - 3, ch - 3);
          if (!day) continue;
          g.textBaseline = 'top';
          g.fillStyle = day.unassigned > 0 ? '#a8452e' : '#8a7a5c';
          g.font = FB(19);
          g.fillText(String(day.date || '').slice(8), cx + 8, cy + 6);
          const evs = (day.events || []);
          const shown = evs.slice(0, 3);
          g.font = F(13);
          shown.forEach((e, k) => {
            g.fillStyle = e.color || '#4a4034';
            g.fillText(fitText(g, e.title || '', cw - 16), cx + 8, cy + 34 + k * 17);
          });
          // `more` is what the payload could not carry PLUS what this cell
          // could not show, so the number is the real remainder of the day
          // rather than the remainder of the four rows that were sent.
          const extra = (evs.length - shown.length) + ((day.more | 0) || 0);
          if (extra > 0) {
            g.fillStyle = '#8a7a5c';
            g.fillText('+' + extra, cx + 8, cy + 34 + shown.length * 17);
          }
        }
      });
    },

    window: (d, z) => {
      const signs = (d.signs || []).slice(0, 6);
      const nBad = d.ready ? Math.min((d.worse || []).length, signs.length) : 0;
      z.parts.text.userData.paint((g, w, h) => {
        g.textBaseline = 'top';
        g.fillStyle = INK; g.font = FB(18);
        g.fillText(fitText(g, d.label || 'outside', w - 24), 12, 10);
        g.font = F(15);
        signs.forEach((s, k) => {
          g.fillStyle = k < nBad ? '#a8452e' : '#5b4c37';
          g.fillText(fitText(g, s, w - 24), 12, 38 + k * 20);
        });
      });
    },

    keys: (d, z) => {
      const cars = (d || []).slice(0, CAPS.keys);
      z.parts.slots.forEach((k, i) => {
        const car = cars[i];
        if (!car) return;
        k.readout.userData.paint((g, w, h) => {
          g.textBaseline = 'top';
          g.fillStyle = INK; g.font = FB(23);
          g.fillText(fitText(g, car.name || '', w - 16), 8, 10);
          const pct = car.pct == null ? null : clamp(car.pct | 0, 0, 100);
          g.font = F(20); g.fillStyle = car.low ? '#a8452e' : INK2;
          g.fillText(pct == null ? 'no reading'
            : `${pct}% ${car.kind === 'fuel' ? 'fuel' : 'charge'}`, 8, 44);
          const bx = 8, by = h - 34, bw = w - 16, bh = 16;
          g.fillStyle = '#dcd2b8'; g.fillRect(bx, by, bw, bh);
          if (pct != null) {
            g.fillStyle = car.low ? '#c4553a' : '#5c8f52';
            g.fillRect(bx, by, bw * pct / 100, bh);
          }
          g.strokeStyle = '#8d7d5f'; g.lineWidth = 1.2;
          g.strokeRect(bx + .6, by + .6, bw - 1.2, bh - 1.2);
        });
      });
    },

    contracts: (d, z) => {
      const items = (d.items || []).slice(0, 3);
      z.parts.label.userData.paint((g, w, h) => {
        g.textBaseline = 'top';
        g.fillStyle = INK2; g.font = F(14);
        g.fillText('awaiting answers', 10, 10);
        g.fillStyle = INK; g.font = F(15);
        items.forEach((it, k) =>
          g.fillText(fitText(g, it.title || '', w - 20), 10, 36 + k * 22));
      });
    },

    binders: (d, z) => {
      const rows = (d || []).slice(0, CAPS.binders);
      z.parts.binders.forEach((b, i) => {
        const row = rows[i];
        if (!row) return;
        b.userData.spine.userData.paint((g, w, h) => {
          g.save();
          g.translate(w / 2, h);
          g.rotate(-Math.PI / 2);            // read it the way a spine is read
          g.textBaseline = 'middle';
          g.fillStyle = '#fdf6e6'; g.font = FB(23);
          g.fillText(fitText(g, row.title || '', h - 56), 16, -7);
          if (row.detail) {
            g.font = F(15); g.fillStyle = 'rgba(253,246,230,.8)';
            g.fillText(fitText(g, row.detail, h - 56), 16, 18);
          }
          g.restore();
        });
      });
    },

    gauges: (d, z) => {
      z.parts.face.userData.paint((g, w, h) => {
        // The dial centres are GAU's own: x = -.3 and +.3 of a 1.24-wide
        // face, pivot at y = +.02 — the same numbers the needles are drawn
        // from, so a number always sits under the needle it belongs to.
        const cx = k => (k * .3 / GAU.w + .5) * w;
        const cy = (.5 - .02 / GAU.h) * h;
        g.textAlign = 'center';
        const dial = (k, label, v, cap) => {
          g.textBaseline = 'middle';
          g.fillStyle = '#332d24'; g.font = FB(21);
          g.fillText(v == null ? '—' : (cap ? v + '/' + cap : String(v)), cx(k), cy + 24);
          g.font = F(15); g.fillStyle = '#c0b4a0';
          g.fillText(label, cx(k), cy + 62);
        };
        dial(-1, 'think', d.think, d.think_cap);
        dial(1, 'research', d.research, d.research_cap);
        const errs = d.ingest_errors | 0;
        g.fillStyle = errs > 0 ? '#b8452c' : '#4f7346';
        g.font = FB(19); g.fillText(String(errs), w / 2, cy + 14);
        g.font = F(14); g.fillStyle = '#c0b4a0';
        g.fillText('ingest', w / 2, cy + 36);
        g.textAlign = 'left';
      });
    },

    // One label per cluster, at the cluster's own centre. Those centres are
    // fixed for as long as the numbers are — only the dots orbit — so the
    // words never chase anything around the glass.
    monitor: (d, z) => {
      const rows = (d.clusters || []).slice(0, CAPS.clusters);
      z.parts.labels.userData.paint((g, w, h) => {
        const sx = w / GR.w, sy = h / GR.h, placed = [];
        g.textBaseline = 'middle'; g.font = FB(17);
        grClusters.forEach((cl, i) => {
          const row = rows[i];
          if (!row) return;
          const x = cl.cx * sx, y = cl.cy * sy;
          const rad = (9 + cl.nodes.length * .8) * sx;
          const text = `${row.name || ''} ${row.count | 0}`;
          const tw = g.measureText(text).width;
          let tx = x + rad + 8;
          if (tx + tw > w - 6) tx = x - rad - 8 - tw;
          tx = Math.max(6, Math.min(tx, w - tw - 6));
          // Two people whose weeks landed near each other on the glass get
          // two labels, not one on top of the other.
          let ty = y;
          for (let n = 0; n < 8; n++) {
            const clash = placed.some(r => tx < r.x + r.w && tx + tw > r.x &&
              ty - 13 < r.y + r.h && ty + 13 > r.y);
            if (!clash) break;
            ty += 29;
            if (ty > h - 16) ty = y - (n + 1) * 29;
          }
          placed.push({ x: tx - 6, y: ty - 13, w: tw + 12, h: 26 });
          g.fillStyle = 'rgba(6,10,18,.74)';
          g.fillRect(tx - 6, ty - 13, tw + 12, 26);
          g.fillStyle = `hsl(${cl.hue},82%,76%)`;
          g.fillText(text, tx, ty);
        });
      });
    },

    map: (d, z) => {
      const trips = (d.trips || []).slice(0, CAPS.trips);
      z.parts.labels.userData.paint((g, w, h) => {
        const pw = z.parts.labels.userData.pw, ph = z.parts.labels.userData.ph;
        const toX = lx => (lx / pw + .5) * w, toY = ly => (.5 - ly / ph) * h;
        g.textBaseline = 'middle';
        // Where a pin SITS is a hash of its own name, so two of them can
        // land close enough that their labels sit on top of each other.
        // A label that has nowhere clear beside its pin steps down until it
        // finds room — it is a label being moved, never a pin.
        // The pins themselves are obstacles too: a label routed around a
        // neighbour's WORDS could still land under a neighbour's pin head,
        // which is what buried a trip's date under the home marker.
        const placed = [];
        const mark = (x, y, r) => placed.push({ x: x - r, y: y - r, w: r * 2, h: r * 2 });
        mark(toX(z.parts.home.x), toY(z.parts.home.y), 22);
        z.parts.pins.forEach((p, i) => {
          if (trips[i]) mark(toX(p.group.position.x), toY(p.group.position.y),
            trips[i].upcoming ? 25 : 18);
        });
        const chip = (x, y, text, colour, size, gap) => {
          g.font = FB(size);
          const tw = g.measureText(text).width, th = size + 8;
          const off = gap == null ? 32 : gap;
          let tx = x + off;
          if (tx + tw > w - 6) tx = x - off - tw;
          tx = Math.max(6, Math.min(tx, w - tw - 6));
          let ty = y;
          for (let n = 0; n < 8; n++) {
            const clash = placed.some(r => tx < r.x + r.w && tx + tw > r.x &&
              ty - th / 2 < r.y + r.h && ty + th / 2 > r.y);
            if (!clash) break;
            ty += th + 3;
            if (ty > h - th) { ty = y - (n + 1) * (th + 3); }
          }
          placed.push({ x: tx - 5, y: ty - th / 2, w: tw + 10, h: th });
          // A label that had to step away from its pin says which pin it
          // came from, or it is a name floating over somebody else's trip.
          if (Math.abs(ty - y) > 4) {
            g.strokeStyle = 'rgba(74,58,32,.55)'; g.lineWidth = 1.4;
            g.beginPath();
            g.moveTo(tx > x ? tx - 5 : tx + tw + 5, ty);
            g.lineTo(x, y);
            g.stroke();
          }
          g.fillStyle = 'rgba(250,244,226,.88)';
          g.fillRect(tx - 5, ty - th / 2, tw + 10, th);
          g.fillStyle = colour;
          g.fillText(text, tx, ty);
        };
        chip(toX(z.parts.home.x), toY(z.parts.home.y), 'home', '#4a3a1e', 14, 28);
        z.parts.pins.forEach((p, i) => {
          const t = trips[i];
          if (!t) return;
          const when = dayChip(t.start_ts);
          chip(toX(p.group.position.x), toY(p.group.position.y),
            (t.title || '') + (when ? '  ' + when : ''),
            t.upcoming ? '#8a4a12' : '#3d3324', 15);
        });
      });
    }
  };

  // Painting is cached per zone and re-run only when that zone's own slice
  // of the payload has changed under it — a poll that moved nothing repaints
  // nothing, and a zone nobody has leaned into is never painted at all.
  function detailPaint(name) {
    const z = ZONES[name], fn = DETAIL[name];
    if (!fn || z.painted) return;
    try { fn((LAST || CALM)[name], z); z.painted = true; }
    catch (e) { /* a zone that cannot draw its detail still leans in */ }
  }

  function detailShow(name, on) {
    const z = ZONES[name];
    if (!z || !z.detail) return;
    (z.detail.on || []).forEach(m => {
      m.visible = !!on && m.userData.want !== false;
    });
    (z.detail.off || []).forEach(m => { m.visible = !on; });
  }

  // =====================================================================
  // 6. applyState — the only place in this file that reads the payload
  // =====================================================================
  function applyState(payload) {
    // If the GPU took the context away, the scene can no longer answer and
    // the list can: every later poll lands there instead, unchanged.
    if (contextLost) { renderFallback(payload); return; }
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
    // A zone whose own slice of the payload moved owes a fresh detail paint
    // the next time somebody is standing in front of it; every other zone
    // keeps the canvas it already has.
    Object.keys(ZONES).forEach(k => {
      let key;
      try { key = JSON.stringify(f[k]); } catch (e) { key = undefined; }
      const z = ZONES[k];
      if (key === undefined || key !== z.dataKey) { z.dataKey = key; z.painted = false; }
    });
    // Whatever the pointer is already resting on now says the new number.
    if (hoverZone) updateTip(hoverZone);
    if (leaned) {
      chipEl.textContent = chipText(leaned);
      detailPaint(leaned);
      detailShow(leaned, true);
    }
  }

  // ---- WebGL context loss -> the honest list, in place -------------------
  // The GPU can take the context away with no warning: a driver reset, a
  // laptop waking from sleep, one browser tab too many holding contexts.
  // Without preventDefault the context is never even a candidate for
  // restoration and the room becomes a permanent black rectangle — the page
  // still polling, still "working", showing nothing. The spec's error
  // handling asks for the fallback list instead, so swap to it in place,
  // wearing the last payload this page actually held (or the calm rows, if
  // the first poll never answered). Every later poll keeps the list fed.
  let contextLost = false;
  R.domElement.addEventListener('webglcontextlost', e => {
    if (contextLost) return;
    e.preventDefault();
    contextLost = true;
    room.style.display = 'none';
    fallback.style.display = 'block';
    try { renderFallback(LAST); }
    catch (err) { /* a dead room never takes the page down with it */ }
  }, false);

  // =====================================================================
  // 7. interaction + life — the room answers the pointer, and breathes
  // =====================================================================
  const LABEL = {
    board: 'The board', desk: 'The desk', tray: 'Intake', stickies: 'Findings',
    calendar: 'This week', window: 'Outside', keys: 'Cars',
    contracts: 'Deals', binders: 'Programs', gauges: "Argyle's budget",
    monitor: "Argyle's screen", map: 'The map'
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
  // The second tap does what the zone has: a page to open, or \u2014 for the one
  // zone with no page behind it \u2014 the thing it does here instead.
  function chipText(name) {
    const z = ZONES[name] || {};
    return signal(name) + (z.url ? ' \u00b7 tap again to open'
      : (z.act ? ' \u00b7 tap again to ask him' : ''));
  }

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
  // EVERY zone leans in. The first click frames the thing face-on and says
  // what it is; the second click does whatever the zone has behind it (a
  // page, or — the monitor — a thing to do here). Escape or empty space
  // stands back up. You should be able to get a good look at anything in
  // this room without leaving it.
  const camAt = CAM0.clone(), lookNow = LOOK0.clone();
  let camTo = CAM0, lookTo = LOOK0;

  // The preset a zone gets when nobody hand-tuned one, computed from the
  // zone's OWN world-space bounding box: stand off along the face it
  // presents, and back away until the box fits with room to spare for the
  // drift and parallax the camera never stops doing.
  //
  // Which way a thing faces is read off where it is. The back wall is at
  // z = -6.3 and the side wall at x = -7.3, so anything hung on one of them
  // is looked at straight on. Everything else is on or around the desk and
  // gets the angle a desk is actually read from — its own yaw where it was
  // built with one (the monitor head, the gauge block), and the room's
  // reading angle where it was not.
  // The page is not all viewport: the nav bar sits across the top and the
  // chip and the Ask-Argyle bar across the bottom. A preset that fits its
  // subject to the whole frame puts the bottom row of it under the chip, so
  // the fit is against the band that is actually free, and the subject is
  // centred in THAT band rather than in the window.
  const UPV = new THREE.Vector3(0, 1, 0);
  const FRAME_TOP = .085, FRAME_BOT = .855;
  const BAND = FRAME_BOT - FRAME_TOP, BAND_MID = (FRAME_TOP + FRAME_BOT) / 2;
  const DRIFT = 1.06, SIDE = .94, DESK_YAW = .42, READ_EL = .46;

  function focusFor(name) {
    const z = ZONES[name];
    if (!z) return null;
    if (z.focus && (z.focusHand || z.focusAspect === cam.aspect)) return z.focus;
    // A zone may name the meshes that are its SIGNAL, when its full set is
    // wider than the thing you leaned in to read: the desk's registry holds
    // its legs and its drawers, and framing those puts the paper stacks too
    // far away to make out a word of.
    const meshes = z.focusMeshes || z.meshes;
    if (!meshes.length) return null;
    scene.updateMatrixWorld(true);
    const box = new THREE.Box3();
    meshes.forEach(m => box.expandByObject(m));
    if (box.isEmpty()) return null;
    const c = box.getCenter(new THREE.Vector3());
    let dir;
    if (c.z < -5.0) dir = new THREE.Vector3(0, 0, 1);
    else if (c.x < -6.2) dir = new THREE.Vector3(1, 0, 0);
    else {
      const yaw = z.faceYaw == null ? DESK_YAW : z.faceYaw;
      dir = new THREE.Vector3(Math.sin(yaw) * Math.cos(READ_EL), Math.sin(READ_EL),
        Math.cos(yaw) * Math.cos(READ_EL));
    }
    // The box measured in the camera's OWN frame, so a long thin thing is
    // not backed away from as though it were a sphere.
    const right = new THREE.Vector3().crossVectors(dir, UPV);
    if (right.lengthSq() < 1e-8) right.set(1, 0, 0);
    right.normalize();
    const up = new THREE.Vector3().crossVectors(right, dir).normalize();
    const v = new THREE.Vector3();
    let hw = 0, hh = 0, hd = 0;
    for (let i = 0; i < 8; i++) {
      v.set(i & 1 ? box.max.x : box.min.x, i & 2 ? box.max.y : box.min.y,
        i & 4 ? box.max.z : box.min.z).sub(c);
      hw = Math.max(hw, Math.abs(v.dot(right)));
      hh = Math.max(hh, Math.abs(v.dot(up)));
      hd = Math.max(hd, Math.abs(v.dot(dir)));
    }
    const vf = cam.fov * Math.PI / 180;
    const hf = 2 * Math.atan(Math.tan(vf / 2) * cam.aspect);
    const dist = hd + Math.max(DRIFT * hh / (Math.tan(vf / 2) * BAND),
      DRIFT * hw / (Math.tan(hf / 2) * SIDE));
    // Centre it in the free band, not in the window. Moving the camera and
    // its target the same way moves the subject in frame without turning it.
    const l = c.clone().addScaledVector(up,
      dist * Math.tan(vf / 2) * 2 * (BAND_MID - .5));
    z.focus = { p: l.clone().addScaledVector(dir, dist), l: l };
    z.focusAspect = cam.aspect;
    return z.focus;
  }

  // The template parks #chip 18px off the bottom, but this page also carries
  // the Ask-Argyle bar (#chat-overlay-container, fixed along the bottom at
  // z-80), which would sit on top of it. Lift the chip clear of whatever
  // height that bar actually has rather than hard-coding one; with no bar in
  // the page the template's own 18px stands.
  function placeChip() { chipEl.style.bottom = barBottom() + 'px'; }

  function leanInto(name) {
    const f = focusFor(name);
    if (!f) return false;
    if (leaned && leaned !== name) detailShow(leaned, false);
    leaned = name;
    camTo = f.p; lookTo = f.l;
    detailPaint(name);
    detailShow(name, true);
    chipEl.textContent = chipText(name);
    placeChip();
    chipEl.style.opacity = '1';
    return true;
  }
  function leanBack() {
    if (!leaned) return;
    detailShow(leaned, false);
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
    if (leaned !== zone && leanInto(zone)) return;
    // A zone with something to DO here does it; only then does a zone with
    // a page behind it navigate. Nothing in either branch writes, and a
    // zone with neither simply stays leaned in.
    if (z.act) { z.act(); return; }
    if (z.url) go(z.url);
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
  // The screen carries a texture now, so the breathing multiplies WHITE:
  // the graph brightens and dims like a real display rather than being
  // tinted by a palette colour it no longer has.
  const SCREEN0 = new THREE.Color(0xffffff);
  const MOTE_TOP = 7.6, MOTE_BOT = .4;
  const T0 = performance.now();
  let lastMs = T0, T = 0;

  function frame(nowMs) {
    if (contextLost) return;        // no context, no loop — the list has it now
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
    // and the graph on it moves — a canvas redraw and one texture upload,
    // ten times a second at most, never while the tab is hidden. Driven off
    // the WALL clock like the flying sheet, not off T: every dot's place is
    // a function of the time, never an integration, so a slow renderer owes
    // it no smoothing — and on T a software renderer would run the whole
    // graph at a quarter speed and pulse once a minute.
    stepGraph((ms - T0) / 1000);

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

  window.STUDY = { applyState: applyState, scene: scene, camera: cam, zones: ZONES,
                   renderer: R, focusFor: focusFor,
                   leanedZone: () => leaned };
  poll(applyState);
})();
