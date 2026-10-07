"""Offline proof of wire-level budgets, persisted backoff and reserved capacity."""
import collections
import concurrent.futures
import datetime
import importlib
import io
import json
import urllib.error
import urllib.request
from unittest.mock import patch
from zoneinfo import ZoneInfo
from harness import check
from services import llm_budget as budget, model_pools


def request(model='gemini-3.8-flash', key='fixture'):
    return urllib.request.Request('https://generativelanguage.googleapis.com/v1beta/models/' + model +
                                  ':generateContent?key=' + key, data=b'{}')


def ok(*args, **kw):
    return io.BytesIO(b'{"candidates":[{"content":{"parts":[{"text":"{\\"insights\\":[]}"}]}}]}')


def scenario_retry_amplification():
    calls=[]
    def failing(req, **kw):
        calls.append(req.full_url.split('/models/')[1].split(':')[0])
        raise urllib.error.HTTPError('https://offline.invalid',503,'Unavailable',{},io.BytesIO(b'capacity'))
    with patch('urllib.request.urlopen',failing),patch('time.sleep',lambda _:None):
        with patch('time.time',return_value=1800000000):
            result=model_pools.call_pool_json('mind','amplification','s','u',settings={},workflow='mind.think')
            check(result.get('error') and len(calls)==1,'one failed deep think makes one wire attempt, not twelve')
        importlib.reload(budget)
        with patch('time.time',return_value=1800000030):
            result=model_pools.call_pool_json('mind','amplification','s','u',settings={},workflow='mind.think')
            check(result.get('deferred') and len(calls)==1,'a quick retry and a restart cannot bypass the backoff')
        with patch('time.time',return_value=1800000061):
            model_pools.call_pool_json('mind','amplification','s','u',settings={},workflow='mind.think')
            check(len(calls)==2,'one probe after the one-minute backoff')
        with patch('time.time',return_value=1800000122):
            model_pools.call_pool_json('mind','amplification','s','u',settings={},workflow='mind.think')
            check(len(calls)==2,'second failure expands the backoff to two minutes')
        with patch('time.time',return_value=1800000182):
            model_pools.call_pool_json('mind','amplification','s','u',settings={},workflow='mind.think')
            check(len(calls)==3,'and the probe after it goes out')
        with patch('time.time',return_value=1800000183+300+1),patch('urllib.request.urlopen',ok):
            result=model_pools.call_pool_json('mind','amplification','s','u',settings={},workflow='mind.think')
            check(result.get('insights')==[] and budget.workflow_ready('amplification','mind.think'),'success clears workflow failure streak')
    check(all('flash' in m and 'lite' not in m for m in model_pools.models_for('mind',{})), 'Mind never degrades to Lite/Gemma')


def scenario_shared_budget_and_reserve():
    calls=[]
    def counted(*a,**kw):calls.append(1);return ok()
    with patch('urllib.request.urlopen',counted):
        for i in range(12):
            with budget.request_scope('auto-'+str(i%2),True),budget.urlopen(request(
                    'gemini-3.8-flash' if i%2 else 'gemini-3.7-flash','reserve')):
                pass
        try:
            with budget.request_scope('another-auto',True):budget.urlopen(request('gemini-3.6-flash','reserve'))
            denied=False
        except budget.Deferred:denied=True
        check(denied and len(calls)==12,'automated allowance shared across models and workflows')
        for _ in range(14):
            with budget.request_scope('user-request',False),budget.urlopen(request(key='reserve')):pass
        try:budget.urlopen(request(key='reserve'));denied=False
        except budget.Deferred:denied=True
        check(denied and len(calls)==26,'manual work uses reserve; per-model hard limit remains twenty')
        with budget._connect() as db:
            rows=db.execute('SELECT outcome,COUNT(*) FROM attempts WHERE account=? GROUP BY outcome',
                            (budget._account('reserve'),)).fetchall()
        check(rows==[('http_200',26)],'admitted wire calls persisted; denied calls are not charged locally')


def scenario_concurrency_and_day_reset():
    calls=[]
    def counted(*a,**kw):calls.append(1);return ok()
    def worker(i):
        try:
            with budget.request_scope('concurrent',True),budget.urlopen(request(key='concurrent')):pass
            return True
        except budget.Deferred:return False
    before=datetime.datetime(2026,9,14,23,59,tzinfo=ZoneInfo('America/Los_Angeles')).timestamp()
    with patch('urllib.request.urlopen',counted),patch('time.time',return_value=before):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            admitted=list(pool.map(worker,range(24)))
        check(sum(admitted)==12 and len(calls)==12,'concurrent admission is atomic')
    with patch('urllib.request.urlopen',counted),patch('time.time',return_value=before+120):
        check(worker(0) and len(calls)==13,'allowance resets at Pacific midnight')


def scenario_daily_quota_survives_restart():
    calls=[]
    def quota(*a,**kw):
        calls.append(1)
        raise urllib.error.HTTPError('https://offline.invalid',429,'Quota',{},io.BytesIO(b'{"quotaId":"GenerateRequestsPerDay"}'))
    with patch('urllib.request.urlopen',quota):
        try:budget.urlopen(request(key='daily'))
        except urllib.error.HTTPError as e:check(b'GenerateRequestsPerDay' in e.read(),'error body remains available to callers')
        importlib.reload(budget)
        try:budget.urlopen(request(key='daily'))
        except budget.Deferred:pass
    check(len(calls)==1,'provider daily exhaustion persists across restarts')


def scenario_background_gemma_falls_through_once():
    """A Gemma 500 (Google's servers, common) used to pause a background
    workflow for 15 min-2 h after ONE attempt while the sibling Gemma model
    was healthy. Now a server failure on one Gemma model tries the other
    within the same call; the workflow pause lands only if the whole call
    fails; it never spills onto Lite (that allowance is chat's)."""
    def gemma_ok_body():
        return io.BytesIO(b'{"candidates":[{"content":{"parts":[{"text":"{\\"items\\":[]}"}]}}]}')

    def wire(fail_models, calls, code=500):
        def urlopen(req, **kw):
            m = req.full_url.split('/models/')[1].split(':')[0]
            calls.append(m)
            if m in fail_models:
                raise urllib.error.HTTPError('https://offline.invalid', code, 'Internal', {}, io.BytesIO(b'internal'))
            return gemma_ok_body()
        return urlopen

    model_pools.reset_cooldowns()
    calls = []
    with patch('urllib.request.urlopen', wire({'gemma-4-31b-it'}, calls)), patch('time.sleep', lambda _: None), \
         patch('time.time', return_value=1810000000):
        res = model_pools.call_pool_json('background', 'fallthrough', 's', 'u', settings={},
                                         workflow='intake.email')
        check(res.get('items') == [] and res.get('_model') == 'gemma-3-27b-it',
              f'a 500 on gemma-31b is answered by the sibling Gemma in the same call: {res}')
        check(calls == ['gemma-4-31b-it', 'gemma-3-27b-it'], f'exactly two wire attempts: {calls}')
        check(budget.workflow_ready('fallthrough', 'intake.email'),
              'a call that succeeded on the sibling leaves the workflow unpaused')

    model_pools.reset_cooldowns()
    calls = []
    with patch('urllib.request.urlopen', wire({'gemma-4-31b-it', 'gemma-3-27b-it'}, calls)), \
         patch('time.sleep', lambda _: None), patch('time.time', return_value=1810100000):
        res = model_pools.call_pool_json('background', 'bothfail', 's', 'u', settings={},
                                         workflow='intake.email')
        check(res.get('error') and res.get('transient'), f'both failing is a transient error: {res}')
        check(calls == ['gemma-4-31b-it', 'gemma-3-27b-it'],
              f'never spills past Gemma onto the Lite pool: {calls}')
        check(not budget.workflow_ready('bothfail', 'intake.email'),
              'when the whole call fails, the workflow pause is written')

    model_pools.reset_cooldowns()
    calls = []
    with patch('urllib.request.urlopen', wire({'gemma-4-31b-it'}, calls, code=400)), \
         patch('time.sleep', lambda _: None), patch('time.time', return_value=1810200000):
        model_pools.call_pool_json('background', 'badreq', 's', 'u', settings={}, workflow='intake.email')
        check(calls == ['gemma-4-31b-it'], f'a non-server failure does not try the sibling: {calls}')
    model_pools.reset_cooldowns()


def scenario_a_model_penalty_never_pauses_the_workflow():
    """Device 2026-10-05: gemma-31b 500'd, the sibling 404'd (withdrawn), and
    the workflow pause copied the 404's six-hour model penalty — email intake
    sat 'waiting' for six hours. The workflow pause is backoff only; the
    model's penalty stays on the model; an overlong stored pause is lifted."""
    import sqlite3
    def wire(calls):
        def urlopen(req, **kw):
            m = req.full_url.split('/models/')[1].split(':')[0]
            calls.append(m)
            code = 500 if m == 'gemma-4-31b-it' else 404
            raise urllib.error.HTTPError('https://offline.invalid', code, 'x', {}, io.BytesIO(b'x'))
        return urlopen
    model_pools.reset_cooldowns()
    calls = []
    t0 = 1820000000
    with patch('urllib.request.urlopen', wire(calls)), patch('time.sleep', lambda _: None), \
         patch('time.time', return_value=t0):
        model_pools.call_pool_json('background', 'penalty', 's', 'u', settings={}, workflow='intake.email')
    check(calls == ['gemma-4-31b-it', 'gemma-3-27b-it'], f'both tried: {calls}')
    with patch('time.time', return_value=t0 + 61):
        check(budget.workflow_ready('penalty', 'intake.email'),
              'the workflow is back after the one-minute backoff, not six hours')
    with contextlib_closing(budget._connect()) as db:
        until = db.execute("SELECT until FROM pauses WHERE account=? AND scope=?",
                           (budget._account('penalty'), 'model:gemma-3-27b-it')).fetchone()[0]
    check(until == t0 + 21600, "the withdrawn model keeps its own six-hour penalty")

    # A six-hour workflow pause already on disk (written by the old code) is lifted.
    with contextlib_closing(budget._connect()) as db, db:
        db.execute("INSERT OR REPLACE INTO pauses VALUES(?,?,?,?)",
                   (budget._account('stuck'), 'workflow:intake.email', t0 + 21600, 2))
    model_pools.reset_cooldowns()
    calls = []
    with patch('urllib.request.urlopen', ok), patch('time.sleep', lambda _: None), \
         patch('time.time', return_value=t0 + 60):
        res = model_pools.call_pool_json('background', 'stuck', 's', 'u', settings={}, workflow='intake.email')
    check(not res.get('deferred'), f'an overlong stored workflow pause no longer blocks: {res}')
    model_pools.reset_cooldowns()


def scenario_no_backoff_is_ever_longer_than_five_minutes():
    """User, 2026-10-07: there is no reason to ever wait more than five
    minutes to retry. Ten straight failures still land at five."""
    t0 = 1830000000
    with contextlib_closing(budget._connect()) as db, db:
        for i in range(10):
            budget._write_workflow_pause(db, budget._account('ladder'), 'workflow:intake.email', 0, t0)
        until = db.execute("SELECT until FROM pauses WHERE account=? AND scope=?",
                           (budget._account('ladder'), 'workflow:intake.email')).fetchone()[0]
    check(until - t0 == 300, f'the ladder tops out at five minutes, got {until - t0}s')


def scenario_a_person_asking_skips_the_backoff():
    """Check mailbox now must do what was asked: the workflow backoff yields
    to a manual run, and a success then clears it for the automatic poll."""
    t0 = 1840000000
    with contextlib_closing(budget._connect()) as db, db:
        db.execute("INSERT OR REPLACE INTO pauses VALUES(?,?,?,?)",
                   (budget._account('asked'), 'workflow:intake.email', t0 + 200, 2))
    model_pools.reset_cooldowns()
    gemma_ok = lambda *a, **k: io.BytesIO(b'{"candidates":[{"content":{"parts":[{"text":"{\\"items\\":[]}"}]}}]}')
    with patch('urllib.request.urlopen', gemma_ok), patch('time.sleep', lambda _: None), \
         patch('time.time', return_value=t0):
        res = model_pools.call_pool_json('background', 'asked', 's', 'u', settings={}, workflow='intake.email')
        check(res.get('deferred'), f'the automatic poll still waits out the backoff: {res}')
        with budget.manual_scope():
            res = model_pools.call_pool_json('background', 'asked', 's', 'u', settings={}, workflow='intake.email')
        check(res.get('items') == [], f'a manual run goes straight through: {res}')
        check(budget.workflow_ready('asked', 'intake.email'), 'and its success lifts the backoff')
    model_pools.reset_cooldowns()


def scenario_a_penalised_model_hands_over_to_its_sibling():
    """A model already under its own penalty (a withdrawn 404, a per-day
    429) is skipped for the next model; it no longer stalls the workflow."""
    t0 = 1850000000
    with contextlib_closing(budget._connect()) as db, db:
        db.execute("INSERT OR REPLACE INTO pauses VALUES(?,?,?,?)",
                   (budget._account('sibling'), 'model:gemma-4-31b-it', t0 + 21600, 1))
    model_pools.reset_cooldowns()
    calls = []
    def wire(req, **kw):
        calls.append(req.full_url.split('/models/')[1].split(':')[0])
        return io.BytesIO(b'{"candidates":[{"content":{"parts":[{"text":"{\\"items\\":[]}"}]}}]}')
    with patch('urllib.request.urlopen', wire), patch('time.sleep', lambda _: None), \
         patch('time.time', return_value=t0):
        res = model_pools.call_pool_json('background', 'sibling', 's', 'u', settings={}, workflow='intake.email')
    check(res.get('_model') == 'gemma-3-27b-it' and calls == ['gemma-3-27b-it'],
          f'the penalised model is skipped, the sibling answers: {res} {calls}')
    model_pools.reset_cooldowns()


from contextlib import closing as contextlib_closing


if __name__=='__main__':
    scenario_a_model_penalty_never_pauses_the_workflow()
    scenario_retry_amplification();scenario_shared_budget_and_reserve()
    scenario_concurrency_and_day_reset();scenario_daily_quota_survives_restart()
    scenario_background_gemma_falls_through_once()
    scenario_no_backoff_is_ever_longer_than_five_minutes()
    scenario_a_person_asking_skips_the_backoff()
    scenario_a_penalised_model_hands_over_to_its_sibling()
    print('LLM request budget passed (all provider calls mocked)')
