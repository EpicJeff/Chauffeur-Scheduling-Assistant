"""One template, read as the page it actually becomes — includes and all.

Several tests read a template as TEXT and assert on the markup in it: that a
caption over a photograph carries the shared scrim class, that the tile picker
branches on whether Home Assistant is there, that every tile type the server
can build has something drawing it. Those are assertions about what the page
RENDERS, and a page assembled out of `{% include %}` renders its components too.

Reading the file alone stopped answering that question the moment the board's
tile body was pulled out into a partial so a card inside a group could be the
same drawing as the tile. Every one of those tests went green-to-red on a
refactor that changed nothing about the page — and the failure mode in the
other direction is worse: a test whose subject has quietly moved into a file it
does not read passes forever without checking anything.

A template included twice is inlined once; these tests scan for presence, and
two copies would only make a `.count()` lie.
"""
import os
import re

TPL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'templates')

_INCLUDE = re.compile(r"\{%-?\s*include\s+'([^']+)'\s*-?%\}")


def read(name, _seen=None):
    seen = set() if _seen is None else _seen
    path = os.path.join(TPL, name)
    if name in seen or not os.path.exists(path):
        return ''
    seen.add(name)
    with open(path, encoding='utf-8') as fh:
        src = fh.read()
    return _INCLUDE.sub(lambda m: read(m.group(1), seen), src)
