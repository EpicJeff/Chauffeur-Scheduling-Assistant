/* Baked Mantaflow flames over logs in the still room image.
   Native video decoding; the photograph never deforms and no WebGL is used. */
(function () {
  'use strict';
  function attach(options) {
  var video = document.getElementById(options.video);
  if (!video) return;
  var frame = document.getElementById(options.frame);
  var toggle = document.getElementById(options.toggle);
  var motion = matchMedia('(prefers-reduced-motion: reduce)');
  var active = true, starting = false, failed = false;
  var preferenceWatch = 0, lastReduced = motion.matches;
  video.muted = true;
  function picture() {
    return document.getElementById(options.images[frame.dataset.light === 'night' ? 1 : 0]);
  }
  function eligible() {
    var scene = document.body.dataset.houseScene, img = picture();
    return active && toggle.checked && !motion.matches && !document.hidden &&
      (scene === options.scene || (!scene && options.scene === 'living')) && frame.dataset[options.viewKey] === 'room' &&
      img.complete && img.naturalWidth > 0;
  }
  function project() {
    var scale = Math.max(frame.clientWidth / 1536, frame.clientHeight / 1024);
    video.style.left = (options.rect[0] * scale + (frame.clientWidth - 1536 * scale) / 2) + 'px';
    video.style.top = (options.rect[1] * scale + (frame.clientHeight - 1024 * scale) / 2) + 'px';
    video.style.width = options.rect[2] * scale + 'px';
    video.style.height = options.rect[3] * scale + 'px';
  }
  function stop() { video.pause(); video.hidden = true; }
  function sync() {
    project();
    var scene = document.body.dataset.houseScene;
    var watching = active && toggle.checked && !document.hidden &&
      (scene === options.scene || (!scene && options.scene === 'living')) && frame.dataset[options.viewKey] === 'room';
    // Some embedded Chromium hosts update matches without delivering change.
    // This cheap preference check does no rendering or decoding, and is removed
    // when the effect is disabled, hidden, or outside the room overview.
    if (watching && !preferenceWatch) preferenceWatch = setInterval(function () {
      if (lastReduced !== motion.matches) sync();
    }, 500);
    if (!watching) { clearInterval(preferenceWatch); preferenceWatch = 0; }
    lastReduced = motion.matches;
    if (!eligible() || failed) { stop(); return; }
    if (!video.getAttribute('src')) video.src = video.dataset.src;
    if (!video.paused) { video.hidden = video.readyState < 2; return; }
    if (starting) return;
    starting = true;
    video.play().then(function () {
      starting = false;
      if (!eligible()) stop();
      else video.hidden = false;
    }).catch(function (error) {
      starting = false;
      video.hidden = true;
      // A quick leave/return can abort an in-flight play. Other failures leave
      // the unlit logs visible; the next user interaction may retry play.
      if (error.name === 'AbortError' && eligible() && !failed) sync();
    });
  }
  video.addEventListener('error', function () { failed = true; stop(); });
  // A seek or loop can briefly drop readyState while play continues. Restore
  // visibility once the decoded frame is ready, even without a scene change.
  video.addEventListener('canplay', sync);
  video.addEventListener('seeked', sync);
  toggle.addEventListener('change', sync);
  motion.addEventListener('change', sync);
  document.addEventListener('visibilitychange', sync);
  window.addEventListener('resize', project);
  options.images.forEach(function (id) {
    document.getElementById(id).addEventListener('load', sync);
  });
  var observer = new MutationObserver(sync);
  observer.observe(frame,{attributes:true,attributeFilter:['data-phase','data-view','data-light']});
  observer.observe(document.body,{attributes:true,attributeFilter:['data-house-scene']});
  window.addEventListener('pagehide', function () { active = false; sync(); });
  window.addEventListener('pageshow', function () { active = true; sync(); });
  window[options.probe] = function () {
    var quality = video.getVideoPlaybackQuality && video.getVideoPlaybackQuality();
    return {running:!video.paused && !video.hidden, frames:quality ? quality.totalVideoFrames : 0,
      reduced:motion.matches, effect:options.effect, time:video.currentTime, failed:failed,
      eligible:!!eligible(), active:active, enabled:toggle.checked};
  };
  sync();
  }
  attach({video:'hybrid-fire',frame:'hybrid-room-frame',toggle:'hybrid-effects-toggle',
    images:['hybrid-day','hybrid-night'],scene:'living',viewKey:'phase',rect:[508,294,200,240],
    probe:'chfEffectsProbe',effect:'simulated-fire'});
  attach({video:'kitchen-steam',frame:'hybrid-kitchen',toggle:'kitchen-effects-toggle',
    images:['kitchen-day','kitchen-night'],scene:'kitchen',viewKey:'view',rect:[649,244,96,144],
    probe:'chfKitchenEffectsProbe',effect:'simulated-steam'});
})();
