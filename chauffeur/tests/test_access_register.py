"""Every reader of piece words is classified (spec §5).

Run from chauffeur/: python tests/test_access_register.py
"""
import ast
import re
import traceback
from pathlib import Path

from harness import check
from services import access_readers as reg
from services import agent_tools_v2 as tools
import main

ROOT = Path(__file__).resolve().parents[1]
KEYWORDS = re.compile(r'thread|mission|program|situation|asks?\b|action-proposal|project|practice|lesson|'
                      r'study|house|schedule|calendar|subjects|chat|commitments|findings|overview|'
                      r'summary|history|converse|packing')
TOOL_KEYWORDS = re.compile(r'thread|mission|program|project|situation|_ask|ask_|lesson|practice|finding|'
                           r'summar|overview|history')
GETTERS = re.compile(r'\b(get_thread|get_threads|get_mission|get_missions|get_mission_steps|get_program|'
                     r'get_programs|get_protected_commitments|get_findings|get_open_findings|'
                     r'get_cached_schedule|get_conversation|get_all_conversations)\(')


def scenario_every_keyword_route_is_classified():
    missing = []
    for route in main.app.routes:
        path = getattr(route, 'path', '')
        for method in sorted(getattr(route, 'methods', None) or []):
            if method in ('HEAD', 'OPTIONS') or not KEYWORDS.search(path):
                continue
            if not path.startswith('/api/'):
                continue          # page shells read no record (spec Appendix A)
            if reg.resolve_route(method, path) is None:
                missing.append(f'{method} {path}')
    check(not missing, 'unclassified routes:\n' + '\n'.join(missing))


def scenario_every_keyword_tool_is_classified():
    names = sorted(getattr(tools, 'TOOL_HANDLERS', {}).keys())
    check(names, 'the registry is enumerable')
    missing = [n for n in names if TOOL_KEYWORDS.search(n) and reg.resolve_tool(n) is None]
    check(not missing, 'unclassified tools:\n' + '\n'.join(missing))


def _functions_calling_getters(path, module):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            src = ast.get_source_segment(path.read_text(encoding='utf-8'), node) or ''
            if GETTERS.search(src):
                out.add(f'{module}.{node.name}')
    return out


def _route_handlers():
    """main.<endpoint> for every route the register classifies (a handler is its route's row)."""
    out = set()
    for route in main.app.routes:
        fn = getattr(route, 'endpoint', None)
        for method in getattr(route, 'methods', None) or []:
            if fn and reg.resolve_route(method, getattr(route, 'path', '')) is not None:
                out.add('main.' + fn.__name__)
    return out


def scenario_every_function_reader_is_classified():
    known = {r[0][1] for r in reg.READERS if r[0][0] == 'reader'} | _route_handlers()
    routes = {r[0][2] for r in reg.READERS if r[0][0] in ('route', 'route-prefix')}
    missing = []
    for path in [ROOT / 'main.py'] + sorted((ROOT / 'services').glob('*.py')):
        module = 'main' if path.name == 'main.py' else 'services.' + path.stem
        if module in ('services.storage', 'services.access', 'services.access_readers'):
            continue
        for fn in _functions_calling_getters(path, module):
            if fn not in known and module not in known:
                missing.append(fn)
    check(not missing, 'unclassified function readers (add a READERS row or INTERNAL):\n' + '\n'.join(sorted(missing)))
    check(routes, 'route rows exist')


def scenario_classes_are_known():
    bad = [r for r in reg.READERS if r[1] not in reg.CLASSES]
    check(not bad, f'unknown classes: {bad}')


SCENARIOS = [v for k, v in list(globals().items()) if k.startswith('scenario_')]
if __name__ == '__main__':
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print('PASS', fn.__name__)
        except Exception:
            failed += 1
            print('FAIL', fn.__name__)
            traceback.print_exc()
    raise SystemExit(bool(failed))
