"""Optional House landing, device fallback and ingress-safe navigation."""
import subprocess
import unittest
from pathlib import Path
import harness
from models.schemas import Settings


class HouseHomeTests(unittest.TestCase):
    def test_setting_defaults_off_and_round_trips(self):
        self.assertFalse(Settings().panel_house_home)
        self.assertTrue(Settings.model_validate({'panel_house_home': True}).model_dump()['panel_house_home'])

    def test_browser_routing(self):
        script = r'''
const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(process.argv[1],'utf8');
function run({surface='home',query='',prefix='',supported=true,stored={},quality=null,blocked=false}={}){
 const redirects=[],calls=[];
 const storage={getItem:k=>{if(blocked)throw Error('disabled');return stored[k]||null;},
   setItem:(k,v)=>{if(blocked)throw Error('disabled');stored[k]=v;},removeItem:k=>delete stored[k]};
 const w={chfHouseExit:()=>calls.push('exit'),chfOrbitTo:k=>calls.push(k)};
 const context={URL,URLSearchParams,window:w,sessionStorage:storage,
  localStorage:{getItem:()=>quality},location:{search:query,href:'https://example.test'+prefix+'/'+surface+query,replace:u=>redirects.push(u)},
  document:{currentScript:{dataset:{surface}},createElement:()=>({getContext:()=>supported?{getExtension:()=>({loseContext:()=>calls.push('release')})}:null})}};
 vm.runInNewContext(source,context);return {w,redirects,calls,stored};
}
let r=run({prefix:'/api/hassio_ingress/abc',query:'?panel=true&tabs=home,meals'});
assert.equal(r.redirects[0],'https://example.test/api/hassio_ingress/abc/house?panel=true&tabs=home,meals');
assert.deepEqual(r.calls,['release']);
r=run({supported:false});assert.equal(r.redirects.length,0);assert.equal(r.stored.chauffeur_house_unavailable,'1');
assert.equal(run({stored:r.stored}).redirects.length,0,'failed device must not retry Home');
for(const args of [{query:'?home_view=board'},{quality:'2d'},{query:'?quality=2d'},{query:'?editor=1'},{query:'?draft=token'}]){
 assert.equal(run(args).redirects.length,0);
}
r=run({surface:'house',prefix:'/api/hassio_ingress/abc',query:'?panel=true',blocked:true});
assert(r.w.ChauffeurHome.fallback());
assert.equal(r.redirects[0],'https://example.test/api/hassio_ingress/abc/home?panel=true&home_view=board');
assert.equal(run({query:'?home_view=board',blocked:true}).redirects.length,0,'URL prevents loop even without storage');
r=run({surface:'house',stored:{chauffeur_house_unavailable:'1'}});
assert(r.w.ChauffeurHome.rest());assert.deepEqual(r.calls,['exit',0]);assert.equal(r.redirects.length,0);
r.w.ChauffeurHome.ready();assert.equal(r.stored.chauffeur_house_unavailable,undefined);
assert.equal(run({surface:'house',query:'?editor=1'}).w.ChauffeurHome,undefined);
assert.equal(run().w.ChauffeurHome.rest(),false);
'''
        subprocess.run(['node', '-e', script, str(Path(__file__).parents[1] / 'static/house_home.js')], check=True)


if __name__ == '__main__':
    unittest.main()
