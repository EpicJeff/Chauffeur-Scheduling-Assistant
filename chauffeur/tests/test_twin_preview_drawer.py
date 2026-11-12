"""Render the viewer's desk and wall preview drawers without launching Chromium."""
from test_settings_drawer import _elements, _render, check


def scenario_time_controls_are_inside_shared_drawer_on_desk_and_wall():
    for query in ('', 'panel=true', 'panel=true&kiosk=true', 'kiosk=true'):
        rows = _elements(_render('/house/twin', query))
        for time in ('now', 'day', 'night'):
            controls = [parents for attrs, parents in rows if attrs.get('data-time') == time]
            check(len(controls) == 1, (query, time, 'exactly one preview control'))
            check(any(a.get('role') == 'dialog' for a in controls[0]), (query, time, 'inside dialog'))
            check(any(a.get('data-settings-for') == 'twin' for a in controls[0]), (query, time, 'shared shell'))
        wall = bool(query)
        ids = {a.get('id') for a, _ in rows}
        check(('twin-preview-gear' in ids) == wall, (query, 'wall has a preview opener'))
        check(('twin-glance-settings' in ids) != wall, (query, 'persistent glance settings stay on desk'))
        check(('twin-energy-settings' in ids) != wall, (query, 'persistent energy settings stay on desk'))
        gate = any('adminGate()' == a.get('x-data') for a, _ in rows)
        check(gate != wall, (query, 'desk retains sign-in gate; panel remains a device'))


if __name__ == '__main__':
    scenario_time_controls_are_inside_shared_drawer_on_desk_and_wall()
    print('1/1 passed (desk and three wall variants)')
