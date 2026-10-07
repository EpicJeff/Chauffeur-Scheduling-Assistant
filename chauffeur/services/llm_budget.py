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
_wire_attempts = contextvars.ContextVar('llm_wire_attempts', default=None)
# While set (a list), a background failure's WORKFLOW pause is collected here
# instead of written: a pool call that falls through to a sibling model must
# not be paused by its own first attempt. The caller applies it only when the
# whole call failed (apply_held_pauses).
_held_pauses = contextvars.ContextVar('llm_held_pauses', default=None)
# Set while a person has explicitly asked for the work (Intake's "Check
# mailbox now"): the WORKFLOW backoff is skipped, because they asked. A
# model's own penalty (a 429 or a withdrawn 404) still stands - that model
# would only fail again - and the pool moves on to the next model instead.
_manual = contextvars.ContextVar('llm_manual', default=False)


class Deferred(RuntimeError):
    """`scope` says what is blocking: 'workflow' (this workflow's failure
    backoff - nothing else will be tried), 'model' (this one model is
    penalised) or 'allowance' (a local daily allowance for this model or
    class). Only 'workflow' should stop a pool from trying another model."""
    def __init__(self, reason, retry_at, scope='workflow'):
        super().__init__(reason)
        self.retry_at = retry_at
        self.scope = scope


@contextlib.contextmanager
def manual_scope():
    token = _manual.set(True)
    try:
        yield
    finally:
        _manual.reset(token)


@contextlib.contextmanager
def request_scope(workflow, background=False):
    token = _scope.set((workflow, background))
    try:
        yield
    finally:
        _scope.reset(token)


@contextlib.contextmanager
def record_attempts(attempts):
    token = _wire_attempts.set(attempts)
    try:
        yield
    finally:
        _wire_attempts.reset(token)


@contextlib.contextmanager
def hold_workflow_pauses():
    held = []
    token = _held_pauses.set(held)
    try:
        yield held
    finally:
        _held_pauses.reset(token)


def apply_held_pauses(held):
    """Write the workflow pause the last failed attempt would have written."""
    if not held:
        return
    account, scope, retry_at = held[-1]
    now = time.time()
    with contextlib.closing(_connect()) as db, db:
        db.execute('BEGIN IMMEDIATE')
        _write_workflow_pause(db, account, scope, retry_at, now)


# Backoff for a background workflow after a whole call fails: 1 min, 2, then
# 5 and never longer. Google's Gemma endpoints fail in short bursts, and the
# old 15 min-2 h ladder left email sitting unread for no reason a family could
# see (user, 2026-10-07: no reason to ever wait more than 5 minutes). Spend is
# still bounded by the daily allowances below, not by the backoff.
WORKFLOW_PAUSE_STEPS = (60, 120, 300)
WORKFLOW_PAUSE_CAP = WORKFLOW_PAUSE_STEPS[-1]


def _write_workflow_pause(db, account, scope, retry_at, now):
    """Backoff for a background WORKFLOW (WORKFLOW_PAUSE_STEPS). It never
    inherits a model's own retry_at — a 404 (6 h) or a per-day 429 (until
    midnight) is that MODEL's penalty, already written under its 'model:'
    scope. Copying it here paused all of email intake for six hours because
    one withdrawn Gemma id answered 404 (device, 2026-10-05) while other
    models were fine."""
    row = db.execute('SELECT failures FROM pauses WHERE account=? AND scope=?', (account, scope)).fetchone()
    failures = min((row[0] if row else 0) + 1, len(WORKFLOW_PAUSE_STEPS))
    until = now + WORKFLOW_PAUSE_STEPS[failures - 1]
    db.execute('INSERT INTO pauses VALUES(?,?,?,?) ON CONFLICT(account,scope) DO UPDATE SET until=excluded.until,failures=excluded.failures',
               (account, scope, until, failures))


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
        return 14400   # Google's published per-model free-tier day for Gemma
    return None  # paid Pro and unknown model classes: record without guessing quota


def workflow_ready(key, workflow):
    with contextlib.closing(_connect()) as db:
        row = db.execute('SELECT until FROM pauses WHERE account=? AND scope=?',
                         (_account(key), 'workflow:' + workflow)).fetchone()
    return not row or row[0] <= time.time()


def workflow_pause(key, workflow):
    """When this workflow's failure backoff ends (epoch seconds), or None
    when it is not paused - so a page can say when it will try again."""
    with contextlib.closing(_connect()) as db:
        row = db.execute('SELECT until FROM pauses WHERE account=? AND scope=?',
                         (_account(key), 'workflow:' + workflow)).fetchone()
    return row[0] if row and row[0] > time.time() else None


def workflow_attempts_today(key, workflow):
    """Provider requests this workflow has sent today (Pacific day), failed
    ones included - each one was a request against the quota."""
    day, _ = _day(time.time())
    with contextlib.closing(_connect()) as db:
        return db.execute('SELECT COUNT(*) FROM attempts WHERE account=? AND day=? AND workflow=?',
                          (_account(key), day, workflow)).fetchone()[0]


def next_midnight():
    """When today's allowances reset (Pacific midnight, epoch seconds)."""
    return _day(time.time())[1]


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
            if row and scope.startswith('workflow:') and row[0] > now + WORKFLOW_PAUSE_CAP + 60:
                # Longer than any backoff can be: a pause written before the
                # cap held (a model's 6 h / midnight penalty copied onto the
                # workflow). Lift it; the model's own pause still stands.
                db.execute('UPDATE pauses SET until=? WHERE account=? AND scope=?', (now, account, scope))
                row = None
            if row and row[0] > now:
                if scope.startswith('workflow:'):
                    if _manual.get():
                        continue          # a person asked; the backoff yields
                    raise Deferred('AI requests paused after provider failure', row[0])
                raise Deferred(f'{model} is paused after a provider failure', row[0], 'model')
        limit = _limit(model)
        count = db.execute('SELECT COUNT(*) FROM attempts WHERE account=? AND day=? AND model=?',
                           (account, day, model)).fetchone()[0]
        if limit is not None and count >= limit:
            raise Deferred(f"{model}'s daily request allowance ({limit}) is used up", midnight, 'allowance')
        if background and is_flash(model):
            used = db.execute('SELECT COUNT(*) FROM attempts WHERE account=? AND day=? AND background=1 AND flash=1',
                              (account, day)).fetchone()[0]
            if used >= BACKGROUND_FLASH_LIMIT:
                raise Deferred('Automated Flash allowance reached; remaining capacity reserved for user work',
                               midnight, 'allowance')
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
                held = _held_pauses.get()
                if held is not None:
                    held.append((account, scope, retry_at))
                else:
                    _write_workflow_pause(db, account, scope, retry_at, now)
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
    attempts = _wire_attempts.get()
    if attempts is not None:
        attempts.append(model)
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
