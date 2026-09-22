/* Outdoor-only weather, using fixed buffers and the house's existing frame loop. */
(function () {
  'use strict';
  window.HouseWeather = {
    build: function (T, scene, detail) {
      var group = new T.Group(), count = detail >= 3 ? 300 : detail >= 2 ? 120 : 0;
      group.name = 'outdoor_weather'; scene.add(group);
      var rainPos = new Float32Array(count * 6), snowPos = new Float32Array(count * 3);
      var rg = new T.BufferGeometry(), sg = new T.BufferGeometry();
      rg.setAttribute('position', new T.BufferAttribute(rainPos, 3));
      sg.setAttribute('position', new T.BufferAttribute(snowPos, 3));
      var rain = new T.LineSegments(rg, new T.LineBasicMaterial({color:0xacc5db, transparent:true, opacity:.45, depthWrite:false}));
      var snow = new T.Points(sg, new T.PointsMaterial({color:0xf4f7ff, size:.20, transparent:true, opacity:.85, depthWrite:false}));
      rain.frustumCulled = snow.frustumCulled = false;
      rain.raycast = snow.raycast = function () {};
      group.add(rain, snow);
      var condition = '', night = false, active = false, oldFog = scene.fog;
      function update(t, exterior, reduced) {
        var wet = /rain|pouring/.test(condition), frozen = /snow|hail/.test(condition);
        group.visible = !!exterior && count > 0;
        rain.visible = wet; snow.visible = frozen;
        active = group.visible && (wet || frozen) && !reduced;
        scene.fog = exterior && condition === 'fog' ? fog : oldFog;
        if (!group.visible || (!wet && !frozen)) return false;
        t = reduced ? 0 : t;
        for (var i=0; i<count; i++) {
          // A yard ring leaves the house and its rooms dry; no particle allocations.
          var angle=i*2.399963, radius=36+(i*17%50);
          var x=Math.cos(angle)*radius, z=Math.sin(angle)*radius;
          var y=1+((i*7.13-(t*(frozen?2:24)))%38+38)%38;
          var r=i*6, s=i*3;
          rainPos[r]=x; rainPos[r+1]=y; rainPos[r+2]=z;
          rainPos[r+3]=x-.15; rainPos[r+4]=y+1.1; rainPos[r+5]=z;
          snowPos[s]=x+Math.sin(t+i)*.7; snowPos[s+1]=y; snowPos[s+2]=z;
        }
        rg.attributes.position.needsUpdate=true; sg.attributes.position.needsUpdate=true;
        return active;
      }
      var fog = new T.Fog(0xbac8d0, 55, 220);
      return {
        set: function (w, n) { condition=w.cond||''; night=n; fog.color.setHex(n?0x26334a:0xbac8d0); },
        update:update,
        stats:function(){return {condition:condition,night:night,particles:group.visible&&(rain.visible||snow.visible)?count:0,animated:active,fog:scene.fog===fog};},
        dispose:function(){scene.fog=oldFog;scene.remove(group);rg.dispose();sg.dispose();rain.material.dispose();snow.material.dispose();}
      };
    }
  };
})();
