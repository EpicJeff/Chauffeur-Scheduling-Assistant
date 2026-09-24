"""Vehicle artwork survives config upload, save/re-edit and shared fleet state."""
import base64
import io
from pathlib import Path
from PIL import Image
from test_house_hybrid_live import seed, live_app, ha_api


def main():
    ha_api.get_states = lambda *a, **kw: []
    ha_api.get_state = lambda *a, **kw: None
    import main as app_module
    app_module.refresh_schedule_logic = lambda *a, **kw: None
    served = live_app(seed)
    try:
        with served.browser() as page:
            page.goto(served.url('config'))
            page.wait_for_function('window.Alpine && Alpine.$data(document.body).cars.length > 0')
            page.evaluate("const app=Alpine.$data(document.body); app.activeTab='family'; app.editCar(app.cars[0]);")
            artwork = Path(__file__).resolve().parents[1]/'static/house_hybrid/vehicles/mercedes-gls-2022-white.png'
            page.get_by_label('House driveway artwork', exact=True).set_input_files(str(artwork))
            page.wait_for_function("Alpine.$data(document.body).newCar.exterior_image?.startsWith('data:image/png;base64,')")
            before = page.evaluate('Alpine.$data(document.body).newCar.exterior_image')
            im = Image.open(io.BytesIO(base64.b64decode(before.split(',', 1)[1])))
            assert im.size == (512, 512) and im.mode == 'RGBA'
            alpha_min, alpha_max = im.getextrema()[-1]
            assert alpha_min == 0 and alpha_max >= 250, 'Upload must retain transparency and solid body panels'
            car_id = page.evaluate('Alpine.$data(document.body).newCar.id')
            await_save = "async()=>{const app=Alpine.$data(document.body); app.newCar.allowed_driver_ids=[app.drivers[0].id]; await app.submitCar();}"
            page.evaluate(await_save)
            saved = next(c for c in page.request.get(served.url('api/cars')).json() if c['id'] == car_id)
            assert saved['exterior_image'] == before
            page.evaluate('(car)=>Alpine.$data(document.body).editCar(car)', saved)
            assert page.evaluate('Alpine.$data(document.body).newCar.exterior_image') == before
            state = page.request.get(served.url('api/house/state')).json()
            row = next(c for c in state['garage']['cars'] if c['id'] == car_id)
            assert row['exterior_image'] == before
            print('PASS: vehicle artwork upload retains alpha and survives config/API/fleet round trip')
    finally:
        served.stop()


if __name__ == '__main__':
    main()
