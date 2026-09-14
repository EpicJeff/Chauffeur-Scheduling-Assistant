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
        with patch('time.time',return_value=1800000301):
            result=model_pools.call_pool_json('mind','amplification','s','u',settings={},workflow='mind.think')
            check(result.get('deferred') and len(calls)==1,'five-minute tick and restart cannot bypass cooldown')
        with patch('time.time',return_value=1800000901):
            model_pools.call_pool_json('mind','amplification','s','u',settings={},workflow='mind.think')
            check(len(calls)==2,'one probe after fifteen-minute backoff')
        with patch('time.time',return_value=1800001802):
            model_pools.call_pool_json('mind','amplification','s','u',settings={},workflow='mind.think')
            check(len(calls)==2,'second failure expands backoff to thirty minutes')
        with patch('time.time',return_value=1800002702),patch('urllib.request.urlopen',ok):
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


if __name__=='__main__':
    scenario_retry_amplification();scenario_shared_budget_and_reserve()
    scenario_concurrency_and_day_reset();scenario_daily_quota_survives_restart()
    print('LLM request budget passed (all provider calls mocked)')
