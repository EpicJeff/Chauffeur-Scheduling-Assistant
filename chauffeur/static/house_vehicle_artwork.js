/* Saved car identity is shared by the exterior and the interior garage. */
(function () {
  'use strict';
  var legacy = {
    'kia-ev9-2026-gray.png':'ev9-white-black-roof',
    'mercedes-gls-2022-white.png':'gls450-white-23',
    'nissan-murano-2021-blue.png':'murano-white'
  };
  var profiles = ['ev9-white-black-roof', 'gls450-white-23', 'murano-white'];
  function profile(car) {
    if (!car) return null;
    if (profiles.includes(car.house_artwork)) return car.house_artwork;
    // Existing explicitly assigned bundled artwork remains compatible.
    return legacy[String(car.exterior_image || '').split('?')[0].split('/').pop()] || null;
  }
  function assigned(cars, key) { return cars.find(car => profile(car) === key) || null; }
  function uploaded(car) {
    var source = car && car.exterior_image;
    return typeof source === 'string' && /^(data:image\/(png|webp);base64,|\/?static\/house_hybrid\/vehicles\/)/.test(source) ? source : null;
  }
  window.ChauffeurHouseVehicles = Object.freeze({profile:profile, assigned:assigned, uploaded:uploaded});
})();
