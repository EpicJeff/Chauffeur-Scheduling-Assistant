/* Day/night sources keep their own versioned URLs; scenes commit decoded layers together. */
(function () {
  'use strict';
  var loads = new Map();
  function night() {
    return typeof window.chfHouseNight === 'boolean' ? window.chfHouseNight : window.HOUSE_COMPARE_NIGHT !== false;
  }
  window.ChauffeurSceneLight = {
    night: night,
    source: function (element, key, dark) {
      key = key || 'src';
      if (dark === undefined) dark = night();
      return element.dataset[key + (dark ? 'Night' : '')];
    },
    load: function (source) {
      if (!loads.has(source)) {
        var image = new Image(); image.src = source;
        loads.set(source, image.decode().catch(function (error) { loads.delete(source); throw error; }));
      }
      return loads.get(source);
    }
  };
})();
