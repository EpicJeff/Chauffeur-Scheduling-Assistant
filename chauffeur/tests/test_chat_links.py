"""Shared chat/school link rendering, run under node without page globals.

Run from chauffeur/: python tests/test_chat_links.py
"""
import json
import re
from pwa_pure import STATIC, TEMPLATES, check, function_body, pure_source, read, run_node


def _linkify(text, link_class=None):
    args = [text] if link_class is None else [text, link_class]
    result = run_node(pure_source('chat_links.js', ['linkifyText']) +
                      '\nconsole.log(JSON.stringify(linkifyText(...' +
                      json.dumps(args) + ')));')
    check(result is not None, 'node is required to exercise linkifyText')
    return result


def scenario_wraps_url():
    anchor = ('<a href="https://a.com/x" target="_blank" rel="noopener noreferrer" '
              'class="underline break-all">https://a.com/x</a>')
    check(_linkify('see https://a.com/x') == 'see ' + anchor, 'URL must become a safe anchor')
    check('href="http://a.com/x"' in _linkify('http://a.com/x'), 'http must also link')


def scenario_bare_scheme_is_text():
    for text in ['see https://!', 'https://.']:
        out = _linkify(text)
        check('<a' not in out and out == text, f'bare scheme must stay text: {out}')
    check('href="https://a"' in _linkify('https://a'), 'a URL with a host must still link')


def scenario_trailing_punctuation_outside():
    for text, tail in [('go to https://a.com/x.', '.'),
                       ('(https://a.com/x)', ')'),
                       ('https://a.com/x, then', ', then')]:
        out = _linkify(text)
        check('href="https://a.com/x"' in out and out.endswith('</a>' + tail),
              f'punctuation must stay outside the anchor: {out}')
    out = _linkify('https://a.com/x.,;:!?)]}')
    check(out.endswith('</a>.,;:!?)]}'), 'all trailing punctuation must stay outside')


def scenario_keeps_balanced_paren():
    url = 'https://en.wikipedia.org/wiki/Foo_(bar)'
    check(f'href="{url}"' in _linkify(url), 'balanced URL parentheses must remain')
    check(_linkify('(' + url + ').').endswith('Foo_(bar)</a>).'),
          'only the extra closing parenthesis and period must be trimmed')


def scenario_escapes_before_matching():
    out = _linkify('<b>https://a.com/?q=1&y=2</b>')
    check('<b>' not in out and out.startswith('&lt;b&gt;<a '), 'markup must stay text')
    check('href="https://a.com/?q=1&amp;y=2"' in out, 'URL ampersand must be escaped')
    check(out.endswith('</a>&lt;/b&gt;'), 'closing markup must stay outside the URL')


def scenario_quote_ends_url():
    out = _linkify('x "https://a.com/y" z')
    check(out.startswith('x &quot;<a href="https://a.com/y"'), 'opening quote stays text')
    check(out.endswith('</a>&quot; z'), 'closing quote stays outside the URL')
    out = _linkify("'https://a.com/y' z")
    check(out.startswith('&#39;<a href="https://a.com/y"') and out.endswith('</a>&#39; z'),
          'single quotes must also terminate a URL and stay escaped')


def scenario_single_quote_escaped():
    check(_linkify("it's") == 'it&#39;s', 'single quotes must be escaped')


def scenario_no_other_schemes():
    check('<a' not in _linkify('javascript:alert(1) data:text/html,x'),
          'other schemes must remain text')


def scenario_null_safe():
    for value in [None, 42, False, {}, []]:
        check(_linkify(value) == '', f'non-string input must be empty: {value!r}')


def scenario_custom_class():
    check('class="text-indigo-300 underline break-all"' in
          _linkify('https://a.com/x', 'text-indigo-300 underline break-all'),
          'caller class must reach the anchor')
    check('class="x&quot; onmouseover=&quot;bad"' in
          _linkify('https://a.com/x', 'x" onmouseover="bad'),
          'class attribute must also be escaped')


def scenario_school_uses_shared_helper():
    src = read(STATIC, 'pwa_school.js')
    check('schoolLinkify' not in src, 'school must drop its private link helper')
    check("linkifyText(t.description, 'text-indigo-300 underline break-all')" in src,
          'school must call the shared helper with its existing style')


def scenario_bubble_uses_shared_helper():
    src = read(TEMPLATES, 'app.html')
    check('linkifyText(m.body)' in src, 'chat bubbles must call the shared helper')
    tag = '<script defer src="{{ \'static/chat_links.js\'|ver }}"></script>'
    check(tag in src and src.index(tag) < src.index('static/pwa_shell.js'),
          'shared helper must load before pwa_shell.js')


def scenario_bubble_renders_links():
    render = function_body(read(TEMPLATES, 'app.html'), 'renderThread')
    match = re.search(r"(?m)^[ \t]*const bubble =.*?^[ \t]*: '';", render, re.DOTALL)
    check(match is not None, 'renderThread must contain the bubble expression')
    bodies = ['see https://a.com/x.', '<b> & "q" it\'s']
    script = pure_source('chat_links.js', ['linkifyText']) + '\n'
    script += 'const bodies = ' + json.dumps(bodies) + ';\n'
    script += 'const results = bodies.map(body => { const m = {body}; const mine = true;\n'
    script += match.group(0) + '\nreturn bubble; });\n'
    script += 'console.log(JSON.stringify(results));'
    out = run_node(script)
    check(out is not None, 'node is required to exercise the chat bubble')
    check('<a href="https://a.com/x"' in out[0] and '</a>.' in out[0],
          f'bubble must link the URL with its period outside: {out[0]}')
    check('<b>' not in out[1] and '&lt;b&gt; &amp; &quot;q&quot; it&#39;s' in out[1],
          f'bubble must escape plain text: {out[1]}')


if __name__ == '__main__':
    scenarios = [v for k, v in list(globals().items()) if k.startswith('scenario_')]
    failed = 0
    for scenario in scenarios:
        try:
            scenario()
            print(f'PASS {scenario.__name__}')
        except Exception as exc:
            failed += 1
            print(f'FAIL {scenario.__name__}: {exc}')
    print(f'{len(scenarios) - failed}/{len(scenarios)} passed')
    raise SystemExit(1 if failed else 0)
