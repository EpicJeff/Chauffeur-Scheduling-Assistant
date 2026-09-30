"""Bump the add-on's patch version, reading it from config.yaml every time.

    python chauffeur/tools/bump_version.py        # 2.499.218 -> 2.499.219

Never bump against a remembered number: other sessions and the user commit
bumps too, and a sed/replace against a stale pattern "succeeds" while
changing nothing, so the change ships unbumped. This reads the file,
increments what it finds, writes it back, re-reads it to prove the write
landed, and prints the new version for the commit message.
"""
import os
import re
import sys

CONFIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      'config.yaml')
PATTERN = re.compile(r'^version:\s*"(\d+)\.(\d+)\.(\d+)"\s*$', re.M)


def main():
    with open(CONFIG, encoding='utf-8', newline='') as fh:
        text = fh.read()
    found = PATTERN.findall(text)
    if len(found) != 1:
        sys.exit(f'expected exactly one version line in {CONFIG}, found {len(found)}')
    major, minor, patch = found[0]
    old = f'{major}.{minor}.{patch}'
    new = f'{major}.{minor}.{int(patch) + 1}'
    text = PATTERN.sub(f'version: "{new}"', text, count=1)
    with open(CONFIG, 'w', encoding='utf-8', newline='') as fh:
        fh.write(text)
    with open(CONFIG, encoding='utf-8') as fh:
        check = PATTERN.findall(fh.read())
    if check != [tuple(new.split('.'))]:
        sys.exit(f'bump did not land: file now says {check}')
    print(f'{old} -> {new}')


if __name__ == '__main__':
    main()
