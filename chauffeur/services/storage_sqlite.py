"""SQLite document-store backend exposing the TinyDB table API surface.

Drop-in replacement for the TinyDB objects used by services/storage.py and
main.py: each table is `(doc_id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT)`
holding one JSON document per row, so every read path returns the same dicts
TinyDB returned. See docs/sqlite_migration_design.md.

Query handling: callers keep passing tinydb Query objects. Simple queries
(==/!=/</<=/>/>= on scalar values, AND/OR combinations) are translated to SQL
so hot lookups hit expression indexes; anything else (test() predicates, None
or list values) falls back to evaluating the Query as a Python predicate over
a full table scan — which is exactly what TinyDB did for every query.

Concurrency: WAL + busy_timeout, one connection per thread. The coarse
storage.db_lock in services/storage.py stays in place for v1; it is cheap now
because writes are single-row UPDATEs instead of whole-file rewrites.
"""
import json
import os
import re
import sqlite3
import threading
from contextlib import contextmanager

_VALID_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Expression indexes for hot lookups (design doc §3.1). The WHERE clauses
# produced by _translate() use the identical expression text, which is what
# lets SQLite match them to these indexes.
INDEX_SPEC = {
    "distance_cache": [["origin", "destination"]],
    "geocode_cache": [["address"]],
    "event_configs": [["google_id"]],
    "trip_metadata": [["event_id"]],
    "daily_schedules": [["date_str"]],
    "route_geometry": [["origin", "destination", "profile"]],
    "members": [["id"], ["driver_id"], ["passenger_id"]],
    "chat_channels": [["id"], ["dm_key"], ["event_id"], ["kind"]],
    "chat_messages": [["channel_id"]],
    "channel_reads": [["channel_id", "member_id"], ["member_id"]],
    "member_tokens": [["token"], ["member_id"]],
    "chores": [["id"], ["state"], ["claimed_by"]],
    "points_ledger": [["member_id"]],
    "routines": [["id"], ["member_id"]],
    "routine_checks": [["member_id", "date_str"], ["routine_id"]],
    "rewards": [["id"]],
    "redemptions": [["id"], ["member_id"], ["state"]],
    "pool_contributions": [["reward_id"], ["member_id"]],
    "agent_action_proposals": [["id"], ["status"]],
    "prep_status": [["event_id"]],
    "packing_claims": [["date_str"], ["outing_key"]],
    "shopping_lists": [["id"]],
    # list_id is the hot lookup (every read is "the items on this list"); id
    # indexed because per-item PATCH is the ONLY write path (design §M1).
    "shopping_items": [["id"], ["list_id"]],
    "meals": [["id"]],
    "leftovers": [["id"], ["date"]],
    "dishes": [["id"], ["type"]],
    "plates": [["date"]],
    # Looked up by normalized name on every list read that builds a cart.
    "walmart_items": [["name_key"]],
    "meal_rules": [["id"]],
    # Read by date window on every page that asks "is anything on?", so the
    # anchor is indexed alongside the id.
    "occasions": [["id"], ["anchor_date"]],
    "occasion_guests": [["id"], ["occasion_id"]],
    # Outside hands (load arc A1). The assignment map is rebuilt on every
    # solve and every board build, and it is looked up by event_id.
    "assist_contacts": [["id"]],
    "assist_assignments": [["id"], ["event_id"], ["contact_id"]],
    # Append-only and never read by a solve, so it is indexed for the LOOKUP
    # ("what has Emma's mom covered for us?"), not for the hot path.
    "assist_history": [["id"], ["contact_id"], ["event_id"]],
    # Household tasks (load arc A2). Read by owner ("what's on my plate") and
    # by status on every sweep.
    "household_tasks": [["id"], ["assigned_to"], ["status"]],
    # Requests (load arc A3): read by who owes an answer and by who is waiting.
    "requests": [["id"], ["to_member"], ["from_member"], ["status"]],
    "protected_commitments": [["id"], ["member_id"]],
    # Needs You findings: every sweep reads the open set and looks rows up by
    # identity, so both are indexed. State is indexed because the surfaces ask
    # for one state at a time ("what's open?").
    "findings": [["id"], ["identity"], ["state"]],
    # Coverage asks: the nudge sweep reads by state, the answer path by id.
    "coverage_asks": [["id"], ["state"], ["event_id"]],
    # Solve packs: written once per day per refresh, read by date when
    # somebody asks the negotiator a question. Date is the only lookup.
    "solve_packs": [["date"]],
    # Shift refusals: read whole on every negotiation, written once per no.
    "shift_refusals": [["series_key"]],
    # Deals: read by state on every sweep, and by the part a request answers.
    "deals": [["id"], ["state"], ["seed_event_id"]],
    # Protected exceptions: one lifted evening per commitment. Read whole by
    # the day loop on every refresh and by commitment when a lever needs to
    # know what it already gave up.
    "protected_exceptions": [["commitment_id"], ["date"]],
    # Programs: read by whose they are and by state on every sweep.
    "programs": [["id"], ["member_id"], ["state"]],
}

# '!=' is deliberately absent: TinyDB matches a stored null against `!= x`,
# but SQL NULL != x is NULL (no match), and json_extract cannot distinguish a
# stored null from a missing field. != queries take the Python fallback.
_SQL_OPS = {"==": "=", "<": "<", "<=": "<=", ">": ">", ">=": ">="}


class Document(dict):
    """A dict that also exposes .doc_id, mirroring tinydb.table.Document."""

    def __init__(self, value, doc_id):
        super().__init__(value)
        self.doc_id = doc_id


def _json_field(path):
    return "json_extract(data, '$." + ".".join(path) + "')"


def _translate_hash(h):
    """TinyDB QueryInstance._hash tuple -> (sql, params), or None if the query
    is not safely expressible in SQL with identical semantics."""
    if not isinstance(h, tuple) or not h:
        return None
    op = h[0]
    if op in _SQL_OPS and len(h) == 3:
        path, value = h[1], h[2]
        if not (isinstance(path, tuple) and path
                and all(isinstance(k, str) and _VALID_NAME.match(k) for k in path)):
            return None
        # None must fall back: SQL NULL comparisons can't distinguish a stored
        # null from a missing field the way TinyDB does. Lists/tuples/dicts
        # fall back too. bool is fine (JSON true/false -> 1/0 in json_extract).
        if value is None or not isinstance(value, (str, int, float)):
            return None
        if isinstance(value, bool):
            value = int(value)
        return f"{_json_field(path)} {_SQL_OPS[op]} ?", [value]
    if op in ("and", "or") and len(h) == 2 and isinstance(h[1], frozenset):
        parts, params = [], []
        for sub in h[1]:
            t = _translate_hash(sub)
            if t is None:
                return None
            parts.append(f"({t[0]})")
            params.extend(t[1])
        return (" AND " if op == "and" else " OR ").join(parts), params
    return None


def _translate(cond):
    try:
        return _translate_hash(getattr(cond, "_hash", None))
    except Exception:
        return None


class SqliteTable:
    """Implements the TinyDB Table methods storage.py and main.py use:
    all, search, get, insert, insert_multiple, upsert, update, remove, truncate.
    """

    def __init__(self, storage, name):
        self._storage = storage
        self.name = name

    def _conn(self):
        return self._storage.connection()

    def _rows_to_docs(self, rows):
        return [Document(json.loads(data), doc_id) for doc_id, data in rows]

    def all(self):
        rows = self._conn().execute(
            f'SELECT doc_id, data FROM "{self.name}" ORDER BY doc_id').fetchall()
        return self._rows_to_docs(rows)

    def search(self, cond):
        t = _translate(cond)
        if t is not None:
            sql, params = t
            rows = self._conn().execute(
                f'SELECT doc_id, data FROM "{self.name}" WHERE {sql} ORDER BY doc_id',
                params).fetchall()
            return self._rows_to_docs(rows)
        return [doc for doc in self.all() if cond(doc)]

    def get(self, cond=None, doc_id=None):
        if doc_id is not None:
            row = self._conn().execute(
                f'SELECT doc_id, data FROM "{self.name}" WHERE doc_id = ?',
                (doc_id,)).fetchone()
            return Document(json.loads(row[1]), row[0]) if row else None
        if cond is None:
            raise RuntimeError("You have to pass either cond or doc_id")
        res = self.search(cond)
        return res[0] if res else None

    def insert(self, document):
        with self._storage.transaction() as conn:
            if isinstance(document, Document):
                # explicit doc_id (parity with TinyDB inserting a Document;
                # also used by the migration to preserve ids)
                conn.execute(
                    f'INSERT INTO "{self.name}" (doc_id, data) VALUES (?, ?)',
                    (document.doc_id, json.dumps(dict(document))))
                return document.doc_id
            cur = conn.execute(
                f'INSERT INTO "{self.name}" (data) VALUES (?)',
                (json.dumps(document),))
            return cur.lastrowid

    def insert_multiple(self, documents):
        ids = []
        with self._storage.transaction() as conn:
            for document in documents:
                cur = conn.execute(
                    f'INSERT INTO "{self.name}" (data) VALUES (?)',
                    (json.dumps(document),))
                ids.append(cur.lastrowid)
        return ids

    def _matching_ids(self, conn, cond):
        t = _translate(cond)
        if t is not None:
            sql, params = t
            rows = conn.execute(
                f'SELECT doc_id FROM "{self.name}" WHERE {sql} ORDER BY doc_id',
                params).fetchall()
            return [r[0] for r in rows]
        rows = conn.execute(
            f'SELECT doc_id, data FROM "{self.name}" ORDER BY doc_id').fetchall()
        return [doc_id for doc_id, data in rows if cond(json.loads(data))]

    def update(self, fields, cond=None, doc_ids=None):
        updated = []
        with self._storage.transaction() as conn:
            if doc_ids is not None:
                target_ids = list(doc_ids)
                for doc_id in target_ids:
                    if conn.execute(
                            f'SELECT 1 FROM "{self.name}" WHERE doc_id = ?',
                            (doc_id,)).fetchone() is None:
                        raise KeyError(doc_id)
            elif cond is not None:
                target_ids = self._matching_ids(conn, cond)
            else:
                target_ids = [r[0] for r in conn.execute(
                    f'SELECT doc_id FROM "{self.name}" ORDER BY doc_id').fetchall()]
            for doc_id in target_ids:
                row = conn.execute(
                    f'SELECT data FROM "{self.name}" WHERE doc_id = ?',
                    (doc_id,)).fetchone()
                if row is None:
                    raise KeyError(doc_id)
                doc = json.loads(row[0])
                if callable(fields):
                    fields(doc)  # tinydb.operations style mutator
                else:
                    doc.update(fields)  # TinyDB merge semantics
                conn.execute(
                    f'UPDATE "{self.name}" SET data = ? WHERE doc_id = ?',
                    (json.dumps(doc), doc_id))
                updated.append(doc_id)
        return updated

    def upsert(self, document, cond):
        updated = self.update(document, cond)
        if updated:
            return updated
        return [self.insert(document)]

    def remove(self, cond=None, doc_ids=None):
        with self._storage.transaction() as conn:
            if doc_ids is not None:
                target_ids = list(doc_ids)
                for doc_id in target_ids:
                    if conn.execute(
                            f'SELECT 1 FROM "{self.name}" WHERE doc_id = ?',
                            (doc_id,)).fetchone() is None:
                        raise KeyError(doc_id)
            elif cond is not None:
                target_ids = self._matching_ids(conn, cond)
            else:
                raise RuntimeError("Use truncate() to remove all documents")
            for doc_id in target_ids:
                conn.execute(
                    f'DELETE FROM "{self.name}" WHERE doc_id = ?', (doc_id,))
        return target_ids

    def truncate(self):
        with self._storage.transaction() as conn:
            conn.execute(f'DELETE FROM "{self.name}"')
            # reset the AUTOINCREMENT counter: TinyDB restarts doc_ids at 1
            # after truncate, and the characterization suite pins that
            conn.execute('DELETE FROM sqlite_sequence WHERE name = ?', (self.name,))

    def __len__(self):
        return self._conn().execute(
            f'SELECT COUNT(*) FROM "{self.name}"').fetchone()[0]


class SqliteStorage:
    """One SQLite file holding every table; TinyDB-like .table() accessor."""

    def __init__(self, path):
        self.path = path
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._local = threading.local()
        self._tables = {}
        self._tables_lock = threading.Lock()
        self.connection()  # create file + WAL mode eagerly

    def connection(self):
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, timeout=5.0)
            conn.isolation_level = None  # autocommit; explicit txns below
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=5000")
            self._local.conn = conn
            self._local.txn_depth = 0
        return conn

    @contextmanager
    def transaction(self):
        """Reentrant per-thread write transaction (BEGIN IMMEDIATE)."""
        conn = self.connection()
        depth = getattr(self._local, "txn_depth", 0)
        if depth > 0:
            self._local.txn_depth = depth + 1
            try:
                yield conn
            finally:
                self._local.txn_depth -= 1
            return
        conn.execute("BEGIN IMMEDIATE")
        self._local.txn_depth = 1
        try:
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        finally:
            self._local.txn_depth = 0

    def table(self, name):
        if not _VALID_NAME.match(name):
            raise ValueError(f"invalid table name: {name!r}")
        with self._tables_lock:
            if name not in self._tables:
                self._ensure_schema(name)
                self._tables[name] = SqliteTable(self, name)
            return self._tables[name]

    def _ensure_schema(self, name):
        conn = self.connection()
        conn.execute(
            f'CREATE TABLE IF NOT EXISTS "{name}" '
            "(doc_id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL)")
        for fields in INDEX_SPEC.get(name, []):
            idx_name = f"idx_{name}_" + "_".join(fields)
            exprs = ", ".join(_json_field((f,)) for f in fields)
            conn.execute(
                f'CREATE INDEX IF NOT EXISTS "{idx_name}" ON "{name}" ({exprs})')

    def tables(self):
        rows = self.connection().execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'").fetchall()
        return {r[0] for r in rows}

    def close(self):
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None


# --- one-way TinyDB -> SQLite migration (design doc §4) ------------------------

def _dedup_keep_last(items, key_fields):
    """Keep only the newest (last-in-table-order) row per key. Matches the
    runtime winner: the distance mem-cache is rebuilt in table order with
    later rows overwriting earlier ones."""
    winners = {}
    for doc_id, doc in items:
        key = tuple(doc.get(f) for f in key_fields)
        winners[key] = (doc_id, doc)
    kept = sorted(winners.values(), key=lambda p: p[0])
    return kept, len(items) - len(kept)


def _dedup_keep_first(items, key_fields):
    """Keep only the first-in-table-order row per key. Matches the runtime
    winner for tables read via search(...)[0]."""
    winners = {}
    for doc_id, doc in items:
        key = tuple(doc.get(f) for f in key_fields)
        winners.setdefault(key, (doc_id, doc))
    kept = sorted(winners.values(), key=lambda p: p[0])
    return kept, len(items) - len(kept)


def _read_tinydb_json(path):
    """Read a TinyDB JSON file -> {table: [(doc_id, doc), ...]} in file order.
    Missing or empty file -> {} (same as TinyDB's empty-db handling)."""
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return {}
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return {
        table: [(int(doc_id), doc) for doc_id, doc in docs.items()]
        for table, docs in raw.items()
    }


def migrate_from_tinydb(sqlite_path, db_json_path, routes_json_path=None):
    """Copy every TinyDB table into a new SQLite file, preserving doc_ids.

    - Builds at a temp path and os.replace()s into place, so a crash mid-way
      never leaves a half-built file that would be mistaken for a good DB.
    - Dedups distance_cache (keep newest per origin+destination) and
      geocode_cache (keep first per address) — the rows runtime reads already
      won with. Everything else copies 1:1.
    - Merges routes_cache.json into the route_geometry table (fresh doc_ids;
      nothing persists route doc_ids across sessions).
    - Renames the originals to *.pre-sqlite.bak (never deleted by us).

    Returns a stats dict, or None if there was nothing to migrate.
    """
    tables = _read_tinydb_json(db_json_path)
    routes = _read_tinydb_json(routes_json_path) if routes_json_path else {}
    if not tables and not routes:
        return None

    stats = {"tables": {}, "deduped": {}}
    tmp_path = sqlite_path + ".migrating"
    if os.path.exists(tmp_path):
        os.remove(tmp_path)
    store = SqliteStorage(tmp_path)
    try:
        with store.transaction():
            for name, items in tables.items():
                dropped = 0
                if name == "distance_cache":
                    items, dropped = _dedup_keep_last(items, ("origin", "destination"))
                elif name == "geocode_cache":
                    items, dropped = _dedup_keep_first(items, ("address",))
                table = store.table(name)
                for doc_id, doc in items:
                    table.insert(Document(doc, doc_id))
                stats["tables"][name] = len(items)
                if dropped:
                    stats["deduped"][name] = dropped
            for name, items in routes.items():
                table = store.table(name)
                for _, doc in items:
                    table.insert(doc)
                stats["tables"][name] = stats["tables"].get(name, 0) + len(items)
        store.connection().execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        store.close()
    os.replace(tmp_path, sqlite_path)

    for src in (db_json_path, routes_json_path):
        if src and os.path.exists(src):
            try:
                os.replace(src, src + ".pre-sqlite.bak")
            except OSError as e:
                # e.g. the old app instance still holds the file on Windows;
                # not fatal — the sqlite file now exists, so the stale JSON
                # will simply be ignored (and never re-migrated) from now on.
                print(f"Migration: could not rename {src} to .bak: {e}")

    total = sum(stats["tables"].values())
    print(f"Migrated TinyDB -> SQLite: {total} docs across "
          f"{len(stats['tables'])} tables into {os.path.basename(sqlite_path)}; "
          f"deduped {stats['deduped'] or 'nothing'}")
    return stats
