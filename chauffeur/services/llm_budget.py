"""Persistent admission control at the Gemini HTTP boundary.

Reservations count attempts, not successful operations. No keys, prompts or
responses are logged. SQLite transactions serialize threads and worker processes.
Limits are conservative application allowances, not a claim about Google's quota.
"""
import contextlib
import contextvars
import datetime
import hashlib
import io
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

BACKGROUND_FLASH_LIMIT = 12  # shared across automated workflows/models per day
FLASH_MODEL_LIMIT = 20
_scope = contextvars.ContextVar('llm_request_scope', default=('direct', False))


class Deferred(RuntimeError):
    def __init__(self, reason, retry_at):
        super().__init__(reason)
        self.retry_at = retry_at


@contextlib.contextmanager
def request_scope(workflow, background=False):
    token = _scope.set((workflow, background))
    try:
        yield
    finally:
        _scope.reset(token)


def _connect():
    from services import storage
    path = Path(storage.DB_PATH).parent / 'llm_budget.sqlite3'
    connection = sqlite3.connect(path, timeout=10)
    connection.executescript('''
      CREATE TABLE IF NOT EXISTS attempts (
        id INTEGER PRIMARY KEY, account TEXT NOT NULL, day TEXT NOT NULL,
        model TEXT NOT NULL, workflow TEXT NOT NULL, background INTEGER NOT NULL,
        flash INTEGER NOT NULL, started REAL NOT NULL, outcome TEXT NOT NULL);
      CREATE INDEX IF NOT EXISTS budget_day ON attempts(account,day,model);
      CREATE TABLE IF NOT EXISTS pauses (
        account TEXT NOT NULL, scope TEXT NOT NULL, until REAL NOT NULL,
        failures INTEGER NOT NULL, PRIMARY KEY(account,scope));
    ''')
    return connection


def _account(key):
    return hashlib.sha256(key.encode()).hexdigest()[:24]


def _day(now):
    local = datetime.datetime.fromtimestamp(now, ZoneInfo('America/Los_Angeles'))
    tomorrow = datetime.datetime.combine(local.date() + datetime.timedelta(days=1),
                                        datetime.time(), tzinfo=local.tzinfo)
    return local.date().isoformat(), tomorrow.timestamp()


def is_flash(model):
    return 'flash' in model and 'lite' not in model


def _limit(model):
    if is_flash(model) or model.startswith('gemini-2.5-flash-lite'):
        return FLASH_MODEL_LIMIT
    if 'flash-lite' in model:
        return 500
    if model.startswith('gemma'):
        return 1000
    return None  # paid Pro and unknown model classes: record without guessing quota


def workflow_ready(key, workflow):
    with contextlib.closing(_connect()) as db:
        row = db.execute('SELECT until FROM pauses WHERE account=? AND scope=?',
                         (_account(key), 'workflow:' + workflow)).fetchone()
    return not row or row[0] <= time.time()


def _reserve(key, model):
    account = _account(key)
    workflow, background = _scope.get()
    now = time.time()
    day, midnight = _day(now)
    with contextlib.closing(_connect()) as db:
        db.execute('BEGIN IMMEDIATE')
        # Keep a small diagnostic history, not an indefinitely growing usage log.
        db.execute('DELETE FROM attempts WHERE started < ?', (now - 32 * 86400,))
        for scope in ('model:' + model, 'workflow:' + workflow if background else ''):
            row = db.execute('SELECT until FROM pauses WHERE account=? AND scope=?', (account, scope)).fetchone()
            if row and row[0] > now:
                raise Deferred('AI requests paused after provider failure', row[0])
        limit = _limit(model)
        count = db.execute('SELECT COUNT(*) FROM attempts WHERE account=? AND day=? AND model=?',
                           (account, day, model)).fetchone()[0]
        if limit is not None and count >= limit:
            raise Deferred('Local daily AI request allowance reached', midnight)
        if background and is_flash(model):
            used = db.execute('SELECT COUNT(*) FROM attempts WHERE account=? AND day=? AND background=1 AND flash=1',
                              (account, day)).fetchone()[0]
            if used >= BACKGROUND_FLASH_LIMIT:
                raise Deferred('Automated Flash allowance reached; remaining capacity reserved for user work', midnight)
        cursor = db.execute('INSERT INTO attempts(account,day,model,workflow,background,flash,started,outcome) VALUES(?,?,?,?,?,?,?,?)',
                            (account, day, model, workflow, int(background), int(is_flash(model)), now, 'started'))
        reservation = cursor.lastrowid
        db.commit()
    return reservation, account, workflow, background


def _finish(reservation, model, outcome, retry_at=0, failed=False):
    request_id, account, workflow, background = reservation
    now = time.time()
    with contextlib.closing(_connect()) as db, db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('UPDATE attempts SET outcome=? WHERE id=?', (outcome, request_id))
        if retry_at:
            db.execute('INSERT INTO pauses VALUES(?,?,?,1) ON CONFLICT(account,scope) DO UPDATE SET until=MAX(until,excluded.until)',
                       (account, 'model:' + model, retry_at))
        if background:
            scope = 'workflow:' + workflow
            if failed:
                row = db.execute('SELECT failures FROM pauses WHERE account=? AND scope=?', (account, scope)).fetchone()
                failures = min((row[0] if row else 0) + 1, 4)
                until = max(retry_at, now + min(7200, 900 * 2 ** (failures - 1)))
                db.execute('INSERT INTO pauses VALUES(?,?,?,?) ON CONFLICT(account,scope) DO UPDATE SET until=excluded.until,failures=excluded.failures',
                           (account, scope, until, failures))
            else:
                db.execute('DELETE FROM pauses WHERE account=? AND scope=?', (account, scope))


def urlopen(request, timeout=60):
    """Only Gemini model calls are admitted/metered; other HTTP is unchanged."""
    url = urllib.parse.urlsplit(request.full_url)
    if url.hostname != 'generativelanguage.googleapis.com' or '/models/' not in url.path:
        return urllib.request.urlopen(request, timeout=timeout)
    model = url.path.split('/models/', 1)[1].split(':', 1)[0]
    key = urllib.parse.parse_qs(url.query).get('key', [''])[0] or request.get_header('X-goog-api-key', '')
    reservation = _reserve(key, model)
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as error:
        body = error.read()
        now = time.time()
        until = 0
        if error.code == 429:
            text = body.decode('utf-8', errors='replace').lower()
            until = _day(now)[1] if any(s in text for s in ('perday', 'per day', 'daily')) else now + 120
        elif error.code == 404:
            until = now + 21600
        # 5xx background failures pause the workflow; foreground retries remain
        # possible and each reserves/counts another attempt before transmission.
        _finish(reservation, model, 'http_' + str(error.code), until, failed=True)
        raise urllib.error.HTTPError(error.url, error.code, error.msg, error.headers, io.BytesIO(body)) from None
    except Exception:
        _finish(reservation, model, 'transport_error', failed=True)
        raise
    _finish(reservation, model, 'http_200')
    return response
