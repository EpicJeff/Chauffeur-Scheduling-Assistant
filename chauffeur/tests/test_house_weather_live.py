"""Actual sky state, outdoor particles, fog, motion preference and room isolation."""
import json
import os
import sys
import tempfile
from pathlib import Path
sys.path[:0]=[str(Path(__file__).parents[1]),str(Path(__file__).parent)]
os.environ.setdefault('CHAUFFEUR_DATA_DIR',tempfile.mkdtemp(prefix='house_weather_'))
from services import ha_api, house_room
from house_live_common import _seed
from live_app import live_app


def main():
    ha_api.get_states=lambda *a,**k:[]
    ha_api.get_state=lambda *a,**k:None
    app=live_app(_seed)
    if not app:raise RuntimeError('Browser required')
    payload=house_room.state(since_ts=0)
    payload['window']={'cond':'rainy','night':False,'calm':False,'temp':60,'next_sun_change':None}
    try:
        with app.browser() as page:
            page.add_init_script('Date.prototype.getHours = function () { return 23; };')
            page.route('**/api/house/state*',lambda r:r.fulfill(json=payload))
            page.route('**/api/v2/chat/stream*',lambda r:r.fulfill(status=200,body=''))
            page.goto(app.url('house')+'?quality=high')
            page.wait_for_function('window.chfHouseWeather && window.chfHouseWeather()?.animated',timeout=120000)
            assert page.evaluate('chfHouseWeather().particles')==300
            assert not page.evaluate('chfHouseWeather().night')
            page.emulate_media(reduced_motion='reduce')
            page.wait_for_function('!chfHouseWeather().animated')
            assert page.evaluate('chfHouseWeather().particles')==300
            page.emulate_media(reduced_motion='no-preference')
            page.wait_for_function('chfHouseWeather().animated')
            for condition in ('snowy','fog','sunny'):
                payload['window']['cond']=condition
                payload['window']['night']=True
                page.evaluate('chfHouseRefresh()')
                page.wait_for_function('(c)=>chfHouseWeather().condition===c',arg=condition)
                assert page.evaluate('chfHouseWeather().night')
                if condition=='snowy':assert page.evaluate('chfHouseWeather().animated')
                if condition=='fog':assert page.evaluate('chfHouseWeather().fog && !chfHouseWeather().animated')
                if condition=='sunny':assert page.evaluate('!chfHouseWeather().fog && chfHouseWeather().particles===0')
                if os.environ.get('HOUSE_SHOTS'):
                    out=Path(os.environ['HOUSE_SHOTS']);out.mkdir(parents=True,exist_ok=True)
                    page.emulate_media(reduced_motion='reduce')
                    page.wait_for_function('!chfHouseWeather().animated')
                    page.screenshot(path=str(out/(condition+'.png')))
                    page.emulate_media(reduced_motion='no-preference')
            payload['window'].update(cond='rainy',night=True,next_sun_change='2000-01-01T00:00:00Z')
            page.evaluate('chfHouseRefresh()')
            page.wait_for_function('chfHouseWeather().condition==="rainy" && !chfHouseWeather().night')
            page.evaluate("chfHouseEnterRoom('living')")
            page.wait_for_function('chfNavProbe({settled:true})')
            assert page.evaluate('!chfHouseWeather().animated && chfHouseWeather().particles===0 && !chfHouseWeather().fog')
            payload['window'].update(night=True,next_sun_change=None)
            page.goto(app.url('house')+'?quality=low&day=1')
            page.wait_for_function('window.chfHouseWeather && chfHouseState()',timeout=120000)
            assert page.evaluate('chfHouseWeather().particles===0 && !chfHouseWeather().animated && !chfHouseWeather().night')
            print('PASS outdoor weather, sun transition, reduced motion, room isolation, low tier')
    finally:app.stop()


if __name__=='__main__':main()
