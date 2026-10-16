"""Run every classified reader as every fixture viewer (spec §6, §7).

Run from chauffeur/: python tests/test_access_matrix.py [class-prefix]
"""
import sys
import traceback
import re

from harness import check
import access_fixture
from test_access_core import TABLE, COLS, KIND
from services import access, access_readers as reg

F, K, X = 'full', 'keeper', None

# Reader rows whose task has not landed. Each task deletes its own rows; Task 11 asserts empty.
PENDING = {}

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
    return K if re.search(re.escape(fx.title(rkey)) + r'(?!\w)', text) else None


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
                want = signed_in.expected(rid, fx, rkey, col, expect(cls, rkey, col))
                try:
                    got = PROBES[rid](fx, rkey, col)
                except Exception as exc:
                    got = f'{type(exc).__name__}: {exc}'
                if got == 'skip':
                    continue
                if got != want:
                    bad.append(f'{rid} {rkey} {col}: want {want} got {got}')
                    print('MISMATCH', bad[-1], flush=True)
    check(not bad, '\n'.join(bad))


import access_signed_in as signed_in
signed_in.register(probe)

import access_channels as channels
channels.register(probe)

import access_conversations as conversations
conversations.register(probe)

import access_engine as engine
engine.register(probe)

import access_voice as voice
voice.register(probe)

import access_shared_signals as shared_signals
shared_signals.register(probe, expect, observed)

import access_calendar as calendar
calendar.register(probe)


def scenario_shared_contracts():
    if len(sys.argv) < 2 or '4.6-shared-screen'.startswith(sys.argv[1]):
        shared_signals.shared_contracts()


def scenario_signal_contracts():
    if len(sys.argv) < 2 or '4.8-signals'.startswith(sys.argv[1]):
        shared_signals.signal_contracts()


def scenario_engine_contracts():
    if len(sys.argv) < 2 or '4.4-engine'.startswith(sys.argv[1]):
        engine.extra_contracts()


def scenario_voice_contracts():
    if len(sys.argv) < 2 or '4.5-voice'.startswith(sys.argv[1]):
        voice.extra_contracts()


def scenario_conversation_contracts():
    if len(sys.argv) < 2 or '4.2-conversation'.startswith(sys.argv[1]):
        conversations.extra_contracts()


def scenario_channel_contracts():
    if len(sys.argv) < 2 or '4.3-channel'.startswith(sys.argv[1]):
        channels.extra_contracts()


def scenario_signed_in_contracts():
    if len(sys.argv) < 2 or '4.1-signed-in'.startswith(sys.argv[1]):
        signed_in.extra_contracts()

def scenario_nothing_pending():
    """Task 11: every surface class has landed; no reader may stay pending."""
    check(not pending_ids(), f'readers still pending: {sorted(map(str, pending_ids()))}')


SCENARIOS = [v for k, v in list(globals().items()) if k.startswith('scenario_')]
if len(sys.argv) < 2 or '4.1-signed-in'.startswith(sys.argv[1]):
    from test_access_round1 import SCENARIOS as ROUND1_SCENARIOS
    SCENARIOS += ROUND1_SCENARIOS
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
