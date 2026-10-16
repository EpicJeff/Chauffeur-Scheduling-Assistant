"""Run every classified reader as every fixture viewer (spec §6, §7).

Run from chauffeur/: python tests/test_access_matrix.py [class-prefix]
"""
import sys
import traceback

from harness import check
import access_fixture
from test_access_core import TABLE, COLS, KIND
from services import access, access_readers as reg

F, K, X = 'full', 'keeper', None

# Reader rows whose task has not landed. Each task deletes its own rows; Task 11 asserts empty.
PENDING = {
    'task3': {r[0] for r in reg.READERS if r[1] == '4.1-signed-in'},
    'task4': {r[0] for r in reg.READERS if r[1] == '4.2-conversation'},
    'task5': {r[0] for r in reg.READERS if r[1] == '4.3-channel'},
    'task6': {r[0] for r in reg.READERS if r[1] == '4.4-engine'},
    'task7': {r[0] for r in reg.READERS if r[1] == '4.5-voice'},
    'task8': {r[0] for r in reg.READERS if r[1] == '4.6-shared-screen'},
    'task9': {r[0] for r in reg.READERS if r[1] == '4.7-calendar'},
    'task10': {r[0] for r in reg.READERS if r[1] == '4.8-signals'},
}

PROBES = {}     # reader id -> probe(fx, rkey, col) -> 'full' | 'keeper' | None


def probe(*reader_ids):
    def wrap(fn):
        for rid in reader_ids:
            PROBES[rid] = fn
        return fn
    return wrap


RANK = {None: 0, K: 1, F: 2}


def expect(cls, rkey, col):
    """Spec §7: the person's-own-surface table, then the per-class differences."""
    row = dict(zip(COLS, TABLE[rkey]))
    base, house = row[col], row['house']
    if KIND[rkey] == 'program':          # a program's keeper projection renders full (spec §3)
        base = F if base == K else base
    if cls == '4.5-voice':
        return house                      # a speaker has a room around it
    if cls == '4.6-shared-screen':
        return max((base, house), key=RANK.get)   # the house's view plus the person's own
    return base


def observed(text, fx, rkey):
    """Classify a reader's output: absent, keeper words only, or the full words.

    Secret words count as FULL even without the title: a leak is a leak."""
    if fx.secret(rkey) in text:
        return F
    return K if fx.title(rkey) in text else None


def pending_ids():
    return set().union(*PENDING.values())


def scenario_every_reader_has_a_probe_or_is_pending():
    missing = [r[0] for r in reg.READERS
               if r[1] not in ('INTERNAL', 'NONE') and r[0] not in PROBES and r[0] not in pending_ids()]
    check(not missing, 'readers with no probe:\n' + '\n'.join(map(str, missing)))


def scenario_every_probe_matches_the_table():
    only = sys.argv[1] if len(sys.argv) > 1 else ''
    fx = access_fixture.build()
    bad = []
    for rid, cls, kinds, _check in reg.READERS:
        if rid not in PROBES or rid in pending_ids() or not cls.startswith(only):
            continue
        for rkey in TABLE:
            if KIND[rkey] not in kinds:
                continue
            for col in COLS:
                want = expect(cls, rkey, col)
                got = PROBES[rid](fx, rkey, col)
                if got == 'skip':
                    continue
                if got != want:
                    bad.append(f'{rid} {rkey} {col}: want {want} got {got}')
    check(not bad, '\n'.join(bad))


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
    print('pending readers:', len(pending_ids()))
    raise SystemExit(bool(failed))
