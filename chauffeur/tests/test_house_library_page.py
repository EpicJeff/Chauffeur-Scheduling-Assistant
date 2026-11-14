"""Real route, shared parent gate, ingress navigation and module graph."""
from test_twin_ha_routes import Ctx, seed
from services import auth
from test_twin_import_maps import check_page


def test_page_renders_with_manifest_and_gate():
    seed()
    with Ctx() as c:
        response = c.client.get('/house/library')
        assert response.status_code == 200, response.text
        assert 'window.twinManifest' in response.text
        assert 'adminGate()' in response.text
        assert 'Changes here apply everywhere this material is used.' in response.text
        assert '../house/editor' in response.text
        assert c.client.get('/api/house/materials', headers=c.kid).status_code == 403
        assert c.client.get('/api/house/materials', headers=c.mum).status_code == 200


def test_page_auth_rule_and_materials_stay_parent_only():
    assert (auth.ANY, '/house/library', auth.ANYONE, None) in auth.RULES
    assert auth.resolve('PATCH', '/api/house/materials/{id}') == auth.PARENTS


def test_page_module_graph_and_navigation():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    check_page('house_library.html', ['twin/library_page/page.js'])
    nav = (root / 'templates/nav.html').read_text(encoding='utf-8')
    assert "'/house/library/'" in nav and "'/house/library'" in nav
    editor = (root / 'templates/house_editor.html').read_text(encoding='utf-8')
    assert '{{ _up }}house/library' in editor
    source = (root / 'static/twin/editor/library.js').read_text(encoding='utf-8')
    assert 'Edit in Library' in source and 'libraryMaterialHref(entry.id)' in source


if __name__ == '__main__':
    tests = [test_page_renders_with_manifest_and_gate, test_page_auth_rule_and_materials_stay_parent_only,
             test_page_module_graph_and_navigation]
    for test in tests:
        test()
        print('ok', test.__name__)
    print(f'{len(tests)}/{len(tests)} passed')
