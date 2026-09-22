"""Default outdoor framing, visible controls, weather and eight-stop access."""
import sys,os,tempfile
from pathlib import Path
sys.path[:0]=[str(Path(__file__).parents[1]),str(Path(__file__).parent)]
os.environ.setdefault('CHAUFFEUR_DATA_DIR',tempfile.mkdtemp(prefix='exterior_review_'))
from services import ha_api,house_room
from live_app import live_app
from house_live_common import _seed
def main():
    ha_api.get_states=lambda *a,**k:[]
    ha_api.get_state=lambda *a,**k:None
    app=live_app(_seed)
    if not app:raise RuntimeError('Browser required')
    payload=house_room.state(since_ts=0)
    payload['window']={'cond':'sunny','night':False,'temp':72,'calm':True,'next_sun_change':None}
    out=Path(os.environ.get('HOUSE_SHOTS','scratch/exterior-view-final'));out.mkdir(parents=True,exist_ok=True)
    try:
        with app.browser() as page:
            page.emulate_media(reduced_motion='reduce')
            page.route('**/api/house/state*',lambda r:r.fulfill(json=payload))
            page.route('**/api/v2/chat/stream*',lambda r:r.fulfill(status=200,body=''))
            page.goto(app.url('house')+'?quality=high',wait_until='domcontentloaded',timeout=120000)
            page.wait_for_function('window.chfHouseState && chfHouseState() && chfNavProbe({settled:true})',timeout=120000)
            page.screenshot(path=str(out/'after.png'),timeout=60000)
            print('captured exterior',flush=True)
            page.wait_for_function("document.querySelectorAll('#house-hints button[data-room]').length===5")
            boxes=page.locator('#house-hints button[data-room]').evaluate_all('(els)=>els.map(e=>{const r=e.getBoundingClientRect();return [r.x,r.y,r.width,r.height];})')
            for x,y,w,h in boxes:assert x>=0 and y>=0 and x+w<=1400 and y+h<=1000,boxes

            for cond,night in [('rainy',False),('clear-night',True)]:
                payload['window'].update(cond=cond,night=night)
                page.evaluate('chfHouseRefresh()')
                page.wait_for_function('(c)=>chfHouseWeather().condition===c',arg=cond)
                page.screenshot(path=str(out/(cond+'.png')),timeout=60000)
            page.evaluate("chfHouseEnterRoom('living')")
            page.wait_for_function('chfNavProbe({settled:true})')
            assert page.evaluate("chfMaskLeak('living')")==0
            page.evaluate('chfHouseExit()')
            page.wait_for_function('chfNavProbe({settled:true})')
            assert page.evaluate('chfMaskLeak(null)')==0
            print('PASS entry/exit masks',flush=True)
            payload['window'].update(cond='sunny',night=False)
            page.evaluate('chfHouseRefresh()')
            page.set_viewport_size({'width':390,'height':844})
            page.wait_for_timeout(1800)  # hints deliberately settle after resizing
            assert page.evaluate('chfCamPose().fov')>24
            for box in page.locator('#house-hints button[data-room]').evaluate_all('(els)=>els.map(e=>{const r=e.getBoundingClientRect();return [r.x,r.y,r.right,r.bottom];})'):
                assert box[0]>=0 and box[1]>=65 and box[2]<=390 and box[3]<750,box
            page.screenshot(path=str(out/'mobile.png'),timeout=60000)
            page.set_viewport_size({'width':1400,'height':1000})
            page.wait_for_timeout(1800)
            seen=set()
            for stop in range(8):
                page.evaluate('(s)=>chfOrbitTo(s)',stop)
                page.wait_for_function('chfNavProbe({settled:true})')
                page.wait_for_function("document.querySelectorAll('#house-hints:not([hidden]) .house-hint').length>=1",timeout=10000)
                for target in ("{entry:'front_door'}","{entry:'back_door'}","{piece:'mudroom_front'}","{front:'garage'}"):
                    if page.evaluate('chfNavProbe('+target+')'):seen.add(target)
            assert len(seen)==4,seen
            print('PASS eight orbit stops and all entrances',flush=True)
    finally:app.stop()


if __name__=='__main__':main()
