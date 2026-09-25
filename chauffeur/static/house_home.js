/* Optional House home. /home stays the single landing/return destination. */
(function () {
  'use strict';
  var surface = document.currentScript.dataset.surface;
  var hybrid = document.currentScript.dataset.hybrid === 'true';
  var query = new URLSearchParams(location.search);
  // Preview/editor frames must never navigate away from their draft.
  if (query.has('draft') || query.get('editor') === '1') return;
  var key = 'chauffeur_house_unavailable';
  function unavailable() {
    try { return sessionStorage.getItem(key) === '1'; } catch (_) { return false; }
  }
  function remember() {
    try { sessionStorage.setItem(key, '1'); } catch (_) {}
  }
  function board() {
    remember();
    var url = new URL('home', location.href);
    url.search = location.search;
    url.searchParams.set('home_view', 'board');
    location.replace(url.href);
    return true;
  }
  window.ChauffeurHome = {
    fallback: board,
    ready: function () { try { sessionStorage.removeItem(key); } catch (_) {} },
    rest: function () {
      if (surface === 'house' && hybrid && window.chfHybridHome) return window.chfHybridHome();
      if (surface !== 'house' || !window.chfHouseExit || !window.chfOrbitTo) return false;
      window.chfHouseExit();
      window.chfOrbitTo(0);
      return true;
    }
  };
  if (surface !== 'home' || query.get('home_view') === 'board') return;
  if (hybrid && query.get('render') !== '3d') {
    var destination = new URL('house', location.href); destination.search = location.search;
    location.replace(destination.href); return;
  }
  if (unavailable()) return;
  // Honor this device's explicit 2D preference without loading the 3D scene.
  var quality = query.get('quality');
  try { quality = quality || localStorage.getItem('chf_kitchen_quality2'); } catch (_) {}
  if (quality === '2d') return;
  try {
    var canvas = document.createElement('canvas');
    var gl = canvas.getContext('webgl2') || canvas.getContext('webgl');
    if (!gl) { remember(); return; }
    var release = gl.getExtension('WEBGL_lose_context');
    if (release) release.loseContext();
  } catch (_) { remember(); return; }
  var house = new URL('house', location.href);
  house.search = location.search;
  location.replace(house.href);
})();
