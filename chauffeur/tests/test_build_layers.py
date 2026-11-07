"""The add-on image keeps its heavy layers cached across updates.

The HA box builds the image itself, and its network has stalled mid-download
(2.499.763's first build died on a 15 s PyPI read timeout after changing
requirements.txt invalidated the pip and Chromium layers). New packages go in
requirements-twin.txt, installed in a layer AFTER Chromium with retries.

Run from chauffeur/:  python tests/test_build_layers.py
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _read(name):
    with open(os.path.join(ROOT, name), encoding='utf-8-sig') as f:
        return f.read()


def scenario_new_packages_sit_after_the_heavy_layers():
    docker = _read('Dockerfile')
    base = docker.index('RUN pip install --no-cache-dir -r requirements.txt')
    chromium = docker.index('playwright install')
    twin = docker.index('-r requirements-twin.txt')
    copy_all = docker.index('COPY . .')
    check(base < chromium < twin < copy_all, 'requirements.txt, then Chromium, then the twin packages, then the code')
    line = docker[docker.rindex('\n', 0, twin):docker.index('\n', twin)]
    check('--timeout' in line and '--retries' in line, f'the late layer retries a slow network: {line.strip()}')


def scenario_twin_packages_stay_out_of_the_base_requirements():
    base = _read('requirements.txt').lower()
    twin = _read('requirements-twin.txt').lower().split()
    check('pypdfium2' in twin and 'pillow' in twin, twin)
    check('pypdfium2' not in base and '\npillow' not in '\n' + base, 'base requirements unchanged since 2.499.762')


if __name__ == '__main__':
    for fn in (scenario_new_packages_sit_after_the_heavy_layers,
               scenario_twin_packages_stay_out_of_the_base_requirements):
        fn()
        print('  ok ', fn.__name__)
