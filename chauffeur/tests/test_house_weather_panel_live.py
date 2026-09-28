"""Panel themes must not paint paper behind the kitchen's dark weather board."""
from pathlib import Path
from test_house_kitchen_live import seed, surface_fixtures
from test_house_hybrid_live import live_app, ha_api

OUT = Path(__file__).resolve().parents[2] / 'scratch/weather-panel'


def main():
    ha_api.get_states = lambda *a, **kw: []
    ha_api.get_state = lambda *a, **kw: None
    served = live_app(seed)
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        with served.browser(reduced_motion='reduce') as page:
            page.route('**/api/v2/chat/stream*', lambda r:r.fulfill(status=204, body=''))
            page.route('**/api/house/state*', lambda r:r.fulfill(json={'window':{
                'night':False, 'cond':'sunny', 'temp':74, 'temp_unit':'°F'}}))
            surface_fixtures(page)
            page.goto(served.url('house?compare=exterior&panel=true&light=day'))
            page.wait_for_function('window.chfExteriorProbe?.().ready')
            assert page.locator('html').get_attribute('data-panel') is not None
            page.evaluate('async()=>{await chfHybridGo("kitchen");chfKitchenVisit("weather")}')
            page.wait_for_selector('#kitchen-controls .house-weather-days')
            for theme in ('light','dark'):
                page.evaluate('(theme)=>document.documentElement.dataset.panelTheme=theme', theme)
                for light in ('day','night'):
                    page.locator('#house-compare-light').evaluate('(el,value)=>{el.value=value;el.dispatchEvent(new Event("change"))}',light)
                    page.wait_for_function('(light)=>document.getElementById("hybrid-kitchen").dataset.light===light',arg=light)
                    page.screenshot(path=str(OUT/(theme+'-'+light+'.png')))
                    for selector in ('.house-life-panel','.house-life-panel>header','.house-life-body'):
                        background=page.locator('#kitchen-controls '+selector).evaluate('el=>getComputedStyle(el).backgroundColor')
                        assert background=='rgba(0, 0, 0, 0)', (theme,light,selector,background)
                    temperature=page.locator('#kitchen-controls .weather-temperature')
                    assert temperature.inner_text()=='74°F'
                    assert temperature.evaluate('el=>getComputedStyle(el).color')=='rgb(241, 242, 233)'
                    assert page.locator('#kitchen-controls .panel-dim').first.evaluate('el=>getComputedStyle(el).color')=='rgb(194, 202, 188)'
            # The standalone weather dialog still needs its normal opaque background.
            page.evaluate('chfHybridHome()')
            page.wait_for_function('chfHouseMode()==="exterior"')
            page.evaluate('window.dispatchEvent(new CustomEvent("chf-house-open",{detail:"weather"}))')
            page.wait_for_selector('.house-life-panel:visible')
            assert page.locator('.house-life-panel').evaluate('el=>getComputedStyle(el).backgroundColor')!='rgba(0, 0, 0, 0)'
            assert not served.errors(), served.errors()
            print('PASS transparent kitchen weather board in both panel themes and lighting modes; standalone dialog preserved')
    finally:
        served.stop()


if __name__=='__main__':main()
