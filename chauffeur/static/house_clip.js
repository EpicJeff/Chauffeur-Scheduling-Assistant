/* House clipper (spec 2026-09-16 view-volume masking §3). Pure functions on
   triangle soups: a tri is {a,b,c,slot}, a vertex {p:[x,y,z], uv:[u,v]}, a
   plane {n:[x,y,z], d} whose KEPT side is n·p - d >= 0. No scene state. */
(function () {
  'use strict';
  var EPS = 1e-7;
  function dot(a, b) { return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]; }
  function sub(a, b) { return [a[0]-b[0], a[1]-b[1], a[2]-b[2]]; }
  function cross(a, b) { return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]; }
  function norm(a) { var l = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0]/l, a[1]/l, a[2]/l]; }
  function side(pl, v) { return dot(pl.n, v.p) - pl.d; }
  function lerp(v0, v1, t) {
    return { p: [v0.p[0]+(v1.p[0]-v0.p[0])*t, v0.p[1]+(v1.p[1]-v0.p[1])*t, v0.p[2]+(v1.p[2]-v0.p[2])*t],
             uv: [v0.uv[0]+(v1.uv[0]-v0.uv[0])*t, v0.uv[1]+(v1.uv[1]-v0.uv[1])*t] };
  }
  /* Sutherland–Hodgman on one polygon; returns the kept polygon and the
     (at most one) edge where the plane crossed it. */
  function clipPoly(poly, pl) {
    var out = [], crossings = [];
    for (var i = 0; i < poly.length; i++) {
      var cur = poly[i], nxt = poly[(i + 1) % poly.length];
      var sc = side(pl, cur), sn = side(pl, nxt);
      if (sc >= -EPS) out.push(cur);
      if ((sc >= -EPS) !== (sn >= -EPS)) {
        var t = sc / (sc - sn);
        var x = lerp(cur, nxt, t);
        out.push(x); crossings.push(x);
      }
    }
    return { poly: out, crossings: crossings };
  }
  function fan(poly, slot) {
    var tris = [];
    for (var i = 1; i + 1 < poly.length; i++) tris.push({ a: poly[0], b: poly[i], c: poly[i + 1], slot: slot });
    return tris;
  }
  /* The cut of a CONVEX solid by a plane is a convex polygon: collect every
     crossing point, order them around their centroid in the plane, fan. */
  function cap(points, pl, capSlot) {
    if (points.length < 3) return [];
    var c = [0, 0, 0];
    points.forEach(function (v) { c[0] += v.p[0]; c[1] += v.p[1]; c[2] += v.p[2]; });
    c = [c[0]/points.length, c[1]/points.length, c[2]/points.length];
    var ax = norm(sub(points[0].p, c)), ay = cross(pl.n, ax);
    var ordered = points.slice().sort(function (u, v) {
      var du = sub(u.p, c), dv = sub(v.p, c);
      return Math.atan2(dot(du, ay), dot(du, ax)) - Math.atan2(dot(dv, ay), dot(dv, ax));
    });
    /* de-duplicate coincident crossings (shared edges produce pairs) */
    var uniq = [];
    ordered.forEach(function (v) {
      var last = uniq[uniq.length - 1];
      if (!last || Math.hypot(last.p[0]-v.p[0], last.p[1]-v.p[1], last.p[2]-v.p[2]) > 1e-6) uniq.push(v);
    });
    if (uniq.length < 3) return [];
    /* the cap faces OUT of the kept solid, i.e. along -n */
    var t = fan(uniq.map(function (v) { return { p: v.p, uv: [0, 0] }; }), capSlot);
    var n0 = cross(sub(t[0].b.p, t[0].a.p), sub(t[0].c.p, t[0].a.p));
    if (dot(n0, pl.n) > 0) t = t.map(function (x) { return { a: x.a, b: x.c, c: x.b, slot: x.slot }; });
    return t;
  }
  function clipTris(tris, pl, capSlot) {
    var kept = [], crossings = [];
    tris.forEach(function (t) {
      var r = clipPoly([t.a, t.b, t.c], pl);
      if (r.poly.length >= 3) kept = kept.concat(fan(r.poly, t.slot));
      crossings = crossings.concat(r.crossings);
    });
    if (capSlot !== undefined && capSlot !== null) kept = kept.concat(cap(crossings, pl, capSlot));
    return kept;
  }
  function flip(pl) { return { n: [-pl.n[0], -pl.n[1], -pl.n[2]], d: -pl.d }; }
  /* Everything OUTSIDE the convex region bounded by `planes`, as disjoint
     pieces: outside plane 1; then (inside 1) outside 2; and so on. */
  function subtractTris(tris, planes, capSlot) {
    var out = [], rest = tris;
    planes.forEach(function (pl) {
      out = out.concat(clipTris(rest, flip(pl), capSlot));
      rest = clipTris(rest, pl, capSlot);
    });
    return out;
  }
  function triArea(tris, slot) {
    var s = 0;
    tris.forEach(function (t) {
      if (slot !== undefined && t.slot !== slot) return;
      var c = cross(sub(t.b.p, t.a.p), sub(t.c.p, t.a.p));
      s += 0.5 * Math.hypot(c[0], c[1], c[2]);
    });
    return s;
  }
  /* Mask planes (spec §2). box = [minx,maxx,miny,maxy,minz,maxz]. */
  function maskPlanes(cam, box) {
    var mn = [box[0], box[2], box[4]], mx = [box[1], box[3], box[5]];
    var ctr = [(mn[0]+mx[0])/2, (mn[1]+mx[1])/2, (mn[2]+mx[2])/2];
    var corner = function (i) { return [(i & 1) ? mx[0] : mn[0], (i & 2) ? mx[1] : mn[1], (i & 4) ? mx[2] : mn[2]]; };
    /* faces: axis, sign, corner indices in a ring, CCW seen from outside
       (each ring verified by hand: (p1-p0)x(p2-p1) == the face normal) */
    var faces = [
      { n: [-1,0,0], ring: [0,4,6,2] }, { n: [1,0,0], ring: [1,3,7,5] },
      { n: [0,-1,0], ring: [0,1,5,4] }, { n: [0,1,0], ring: [2,6,7,3] },
      { n: [0,0,-1], ring: [0,2,3,1] }, { n: [0,0,1], ring: [4,5,7,6] }];
    var front = faces.map(function (f) {
      var fc = corner(f.ring[0]);
      return dot(f.n, sub(cam, fc)) > 0;
    });
    var W = [];
    faces.forEach(function (f, i) {
      if (!front[i]) return;
      var fc = corner(f.ring[0]);
      /* keep side = behind the face (box side): -n·p + n·fc >= 0 */
      W.push({ n: [-f.n[0], -f.n[1], -f.n[2]], d: -dot(f.n, fc) });
    });
    /* silhouette edges: shared by one front and one back face */
    var P = [], seen = {};
    faces.forEach(function (f, i) {
      for (var k = 0; k < 4; k++) {
        var a = f.ring[k], b = f.ring[(k + 1) % 4];
        var key = Math.min(a, b) + '-' + Math.max(a, b);
        if (seen[key] !== undefined) {
          if (front[seen[key]] !== front[i]) {
            var pa = corner(a), pb = corner(b);
            var n = norm(cross(sub(pa, cam), sub(pb, cam)));
            var d = dot(n, cam);
            if (dot(n, ctr) - d < 0) { n = [-n[0], -n[1], -n[2]]; d = -d; }
            P.push({ n: n, d: d });
          }
        } else seen[key] = i;
      }
    });
    return { P: P, W: W };
  }
  function pointMasked(p, m) {
    var v = { p: p };
    for (var i = 0; i < m.P.length; i++) if (side(m.P[i], v) < -EPS) return false;
    for (var j = 0; j < m.W.length; j++) if (side(m.W[j], v) < -EPS) return true;
    return false;
  }
  window.HouseClip = { clipTris: clipTris, subtractTris: subtractTris, triArea: triArea,
                       maskPlanes: maskPlanes, pointMasked: pointMasked, flip: flip };
})();
