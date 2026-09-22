"""Current observations and the existing sun clock drive the outdoor scene."""
import unittest
import subprocess
from pathlib import Path
from unittest.mock import patch
import harness
from services import kitchen_room


class OutdoorWeatherTests(unittest.TestCase):
    def test_effect_buffers_motion_and_disposal(self):
        base=Path(__file__).parents[1]/'static'
        script=r'''
global.window=global;
const T=require(process.argv[1]);require(process.argv[2]);
const assert=require('node:assert/strict'),scene=new T.Scene();
const effect=HouseWeather.build(T,scene,3), group=scene.children[0];
const buffers=group.children.map(m=>m.geometry.attributes.position.array);
let disposed=0;
group.children.forEach(m=>{m.geometry.addEventListener('dispose',()=>disposed++);m.material.addEventListener('dispose',()=>disposed++);});
effect.set({cond:'rainy'},false);assert(effect.update(1,true,false));
assert.equal(effect.stats().particles,300);
effect.update(2,true,false);group.children.forEach((m,i)=>assert.equal(m.geometry.attributes.position.array,buffers[i]));
assert(!effect.update(3,true,true));assert.equal(effect.stats().particles,300);
assert(!effect.update(4,false,false));assert.equal(effect.stats().particles,0);
effect.set({cond:'fog'},true);effect.update(5,true,false);assert(effect.stats().fog);
effect.update(6,false,false);assert.equal(scene.fog,null);
effect.dispose();assert.equal(disposed,4);assert.equal(scene.children.length,0);
const low=HouseWeather.build(T,scene,1);low.set({cond:'snowy'},false);
assert(!low.update(7,true,false));assert.equal(low.stats().particles,0);low.dispose();
'''
        subprocess.run(['node','-e',script,str(base/'vendor/three.min.js'),str(base/'house_weather.js')],check=True)

    def test_selected_current_entity_and_real_sun_ignore_theme_offsets(self):
        def state(entity):
            if entity=='sun.sun':return {'state':'below_horizon','attributes':{}}
            self.assertEqual(entity,'weather.selected')
            return {'state':'snowy','attributes':{'temperature':28}}
        with patch('services.storage.get_settings',return_value={'weather_entity':'weather.selected','panel_theme_sunset_offset_minutes':120}), \
             patch('services.ha_api.get_state',side_effect=state), \
             patch('services.ha_api.get_weather_forecast',side_effect=AssertionError('forecast must not be used')):
            result=kitchen_room._window()
        self.assertTrue(result['night'])
        self.assertEqual(result['cond'],'snowy')
        self.assertEqual(result['temp'],28)
        self.assertFalse(result['calm'])

    def test_missing_weather_does_not_erase_daylight(self):
        with patch('services.storage.get_settings',return_value={}), \
             patch('services.ha_api.get_entities',return_value=[]), \
             patch('services.ha_api.get_state',return_value={'state':'above_horizon','attributes':{}}):
            result=kitchen_room._window()
        self.assertFalse(result['night'])
        self.assertEqual(result['cond'],'')

    def test_sun_transition_timestamp_is_forwarded(self):
        with patch('services.home_board.sun_theme',return_value={'theme':'dark','next_flip':'2026-09-23T11:02:00+00:00'}) as sun, \
             patch('services.storage.get_settings',return_value={}), \
             patch('services.ha_api.get_entities',return_value=[]):
            result=kitchen_room._window()
        sun.assert_called_once_with({})
        self.assertEqual(result['next_sun_change'],'2026-09-23T11:02:00+00:00')


if __name__=='__main__':unittest.main()
