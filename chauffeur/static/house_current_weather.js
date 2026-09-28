/* Current conditions share the house feed; no extra weather polling. */
(function () {
  'use strict';
  var readings = document.querySelectorAll('.house-current-weather');
  var exterior = document.getElementById('house-exterior');
  var conditions = {
    sunny:['Sunny','☀️','clear'], 'clear-night':['Clear','🌙','clear'],
    partlycloudy:['Partly cloudy','🌤️','cloudy'], cloudy:['Cloudy','☁️','cloudy'],
    windy:['Windy','🌬️','cloudy'], 'windy-variant':['Windy and cloudy','🌬️','cloudy'],
    rainy:['Rain','🌧️','rain'], pouring:['Heavy rain','🌧️','rain'],
    lightning:['Thunderstorms','⛈️','rain'], 'lightning-rainy':['Thunderstorms','⛈️','rain'],
    hail:['Hail','🌨️','snow'], snowy:['Snow','🌨️','snow'], 'snowy-rainy':['Rain and snow','🌨️','snow'],
    fog:['Fog','🌫️','fog'], exceptional:['Unusual weather','⚠️','unknown']
  };
  function accept(data) {
    var weather = data?.window || {};
    var code = String(weather.cond || '').toLowerCase();
    var condition = conditions[code];
    var hasTemp = condition && typeof weather.temp === 'number' && Number.isFinite(weather.temp);
    var unit = {'°F':'°F', F:'°F', '°C':'°C', C:'°C', K:' K'}[weather.temp_unit] || '°';
    var temperature = hasTemp ? Math.round(weather.temp)+unit : '—';
    var label = condition ? condition[0] : 'Weather unavailable';
    readings.forEach(function (el) {
      el.querySelector('.weather-icon').textContent = condition ? condition[1] : '';
      el.querySelector('.weather-temperature').textContent = temperature;
      el.querySelector('.weather-condition').textContent = label;
      el.setAttribute('aria-label', 'Now: '+(hasTemp ? temperature : 'temperature unavailable')+' · '+label);
    });
    var kind = condition ? condition[2] : 'unknown';
    if (exterior && exterior.dataset.weatherRequested !== kind) {
      exterior.dataset.weatherRequested = kind;
      window.dispatchEvent(new Event('chf-house-weather'));
    }
  }
  window.addEventListener('chf-house-state', function (event) { accept(event.detail); });
  accept(window.chfHouseState?.());
})();
