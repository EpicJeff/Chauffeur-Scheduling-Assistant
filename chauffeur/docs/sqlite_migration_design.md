# SQLite Migration — Design & Execution Plan

Status: **EXECUTED — sqlite is the live default on local and the HA add-on (shipped with v2.8.28, 2026-07-30)**
Companion: `docs/trip_scheduler_design.md` (same "tests first, seam-preserving swap" playbook)

Execution results (2026-07-16):
- Steps 1–5 of §7 done, one commit per step. 35-scenario characterization suite
  (`tests/test_storage.py`) green on both backends; backend unit + migration
  tests in `tests/test_storage_sqlite.py` (11 scenarios).
- Real-data verification: migrated a copy of production `db.json` +
  `routes_cache.json` (7,155 docs, 26 tables); dedup dropped exactly the 2,314
  measured distance_cache duplicates; a full read-surface dump (every public
  getter, effective distance/geocode caches, per-row route-geometry hashes)
  was byte-identical between backends.
- Deviations from plan: no restore endpoint exists (restore = place db.json,
  delete .sqlite3, restart — handled by the startup migration); the
  get_settings 5s memo cache (§3.1) was deferred to keep the swap
  zero-behavior-change; `/api/download_db` zips the data dir and now snapshots
  the .sqlite3 member via the backup API.
- Remaining: §8 cleanups only (drop TinyDB + toggle, db_lock audit). Local
  soak and the HA ship (v2.8.28) are done.

## 1. Why (measured, not vibes)

TinyDB rewrites the **entire JSON file on every write** and holds a single global
`db_lock` while doing it. Measurements from the 2026-07 performance investigation:

| Fact | Measurement |
|---|---|
| Single write cost (main DB) | ~275 ms (re-serialize whole file; fsync itself only ~21 ms) |
| Main DB size | `data/db.json` — 4.8 MB and growing |
| Route cache DB size | `data/routes_cache.json` — **15.8 MB**, rewritten per cached route |
| Regenerable cache share of main DB | ~66% (distance/geocode/schedule caches) |
| Duplicate rows from insert-not-upsert | 2,314 in `distance_cache` (38% of the table) |
| `with db_lock` sites in storage.py | 91 |
| SQLite speedup measured on this data | ~190× per write |

Symptoms traced directly to this (all user-reported): 30-second accommodation
delete (trivial DELETE queued behind background-refresh writes), schedule saves
taking tens of seconds (fixed by batching, but each remaining save still rewrites
the world), UI actions queueing behind cache writes. Recent fixes (dirty-marking
batch update, save throttling, optimistic UI) treat symptoms; the storage engine
is the disease.

## 2. Goals / non-goals

**Goals**
- Writes in single-digit milliseconds; no whole-file rewrites.
- Real concurrent reads (WAL) so UI reads never queue behind background writes.
- Zero behavior change visible to callers of `services/storage.py`.
- Works identically on local Windows dev and the HA add-on (aarch64/armv7/i386).

**Non-goals (v1)**
- No relational normalization of domain tables (drivers, rules, trips stay as
  JSON documents). Normalize later, per-table, only if a need appears.
- No ORM, no new dependency: Python stdlib `sqlite3` only. (HA base images need
  no wheels — SQLite ships with CPython; HA's own recorder uses it.)
- No API change to storage.py — its ~90 public functions keep their signatures.

## 3. Target architecture

One file: `chauffeur.sqlite3` (next to today's `db.json`: repo `data/` locally,
`/data/` in the HA add-on — path selection reuses the existing options.json
detection).

### 3.1 Schema: document store, not relational

Each TinyDB table becomes one SQLite table with the same name and shape:

```sql
CREATE TABLE IF NOT EXISTS <name> (
    doc_id INTEGER PRIMARY KEY AUTOINCREMENT,
    data   TEXT NOT NULL              -- the JSON document, exactly as TinyDB stored it
);
```

This is deliberate: storage.py's query patterns are almost all "scan table,
filter in Python" or "lookup by one key." A document schema means the migration
is a **transport change, not a data-model change** — every read path returns the
same dicts it returns today.

Hot lookups get indexes via JSON generated columns (no caller changes):

| Table | Generated column(s) + index | Serves |
|---|---|---|
| `distance_cache` | `origin`, `destination` | `get_cached_travel_time` |
| `geocode_cache` | `address` | geocoding lookups |
| `event_configs` | `google_event_id` | config-by-event joins |
| `trip_metadata` | `event_id` | every trip page load |
| `daily_schedules` | `date` | per-day schedule reads |
| `route_geometry` | `origin`, `destination`, `profile` | route pills |
| `settings` | (none — single row) | `get_settings` (called constantly; add a process-level 5s memo cache while here) |

`routes_cache.json` (15.8 MB) merges into the same SQLite file as the
`route_geometry` table — one database, one backup story.

### 3.2 Concurrency model

- `PRAGMA journal_mode=WAL`, `PRAGMA synchronous=NORMAL`, `busy_timeout=5000`.
- One connection per thread (`threading.local`), `check_same_thread=False` not
  needed with per-thread connections.
- **`db_lock` stays in place for v1.** All 91 sites keep working; the lock
  becomes cheap because the critical sections drop from ~275 ms to ~1 ms.
  Removing the lock is a separate, later cleanup — never bundled with the
  engine swap (two variables changed at once = undebuggable).
- WAL caveat honored: the DB lives on a local filesystem in both environments
  (HA add-on `/data` is local). Never point it at a network mount.

### 3.3 Backup endpoint

The existing backup endpoint currently copies the JSON file. It switches to
`sqlite3.Connection.backup()` (safe under WAL, no lock freeze). Restores accept
either format: a `.sqlite3` file is copied in; a legacy `.json` upload triggers
the migration path below.

## 4. Migration path (automatic, one-way with backup)

On startup, inside storage init:

1. If `chauffeur.sqlite3` exists → use it, done.
2. Else if `db.json` exists → migrate:
   - Create schema; copy every table's docs verbatim in one transaction.
   - **Dedup during copy**: `distance_cache` and `geocode_cache` keep only the
     newest row per key (kills the 2,314 duplicates); everything else copies 1:1.
   - Merge `routes_cache.json` into `route_geometry`.
   - Rename originals to `db.json.pre-sqlite.bak` / `routes_cache.json.pre-sqlite.bak`
     (never deleted by us; user can remove after a happy week).
3. Else → fresh empty SQLite DB.

Expected migration time: seconds (one transaction, ~21 MB of JSON total).
HA add-on: same code path — first boot of the new version migrates `/data`
files in place. Version bump required in `config.yaml` as usual.

## 5. Execution plan (order matters)

1. **Characterization tests first** (`tests/test_storage.py`, same offline
   harness as the trip scheduler tests): for every public storage.py function,
   round-trip against a temp DB — write, read back, assert dict equality;
   plus the known invariants (upsert-not-duplicate for caches, settings
   precedence, dirty-marking). Run them against **TinyDB first** to pin current
   behavior — these tests define "no behavior change."
2. **`storage_sqlite.py` backend**: a small class exposing TinyDB's table API
   surface as used by storage.py (`all`, `search`, `get`, `insert`,
   `insert_multiple`, `upsert`, `update`, `remove`, `truncate` — verify the
   exact set by grep before writing). storage.py swaps `db.table(x)` for the
   new backend behind a `CHAUFFEUR_STORAGE=sqlite|tinydb` env/setting toggle.
3. **Run the characterization suite against both backends.** Green on both =
   the swap is real.
4. **Flip the default to sqlite** locally; soak for a few days of normal use
   (the `[SLOW REQUEST]` middleware is the scoreboard — trip page loads and
   deletes should never appear in it again).
5. **Ship to HA** (version bump). Keep the `tinydb` toggle for one release as
   the escape hatch, then delete TinyDB, the toggle, and the 91-site lock
   audit begins as an independent cleanup.

## 6. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Subtle TinyDB query-semantics mismatch (e.g. `Query()` behaviors) | Characterization tests pinned on TinyDB first; both backends must pass the same suite |
| Doc-id reliance (`doc_id` used by rules UI) | Preserve TinyDB doc_ids during migration (`INSERT` with explicit `doc_id`) |
| Corrupt/partial legacy JSON on migration | Existing `fix_corrupted_db` runs before migration; originals kept as `.bak` |
| HA arch differences | None expected — stdlib sqlite3, no wheels; verify once on the add-on before flipping default |
| Two processes on one DB (dev server + scripts) | WAL + busy_timeout handles it; scripts should go through storage.py anyway |
| Backup/restore format change | Endpoint accepts both formats during transition |

## 7. Execution checklist (written for a fresh session with zero context)

Environment facts you'd otherwise have to rediscover:
- Working dir for all commands: `e:\repositories\Chauffeur\chauffeur` (run
  `python tests/test_trip_scheduler.py` from there — no pytest in this repo,
  tests are plain scripts with a PASS/FAIL runner in `__main__`).
- `tests/harness.py` shows the offline-mocking pattern (patch module attrs on
  `services.storage` / `services.maps`); follow it, don't import `main.py` in
  tests (it starts background threads).
- Storage init is inside a function in `services/storage.py` (~line 70); tables
  are module-level names like `drivers_table`. 23 tables in `db.json` + 1 in
  `routes_cache.json` (full list at storage.py:76-105).
- The user's local app is often RUNNING while you work — TinyDB files may be
  locked (you'll see WinError 5 noise on import); never write to `data/` in
  tests, use tempfile DBs.
- HA add-on deploys only on `config.yaml` version bump; DB path there is
  `/data/` (options.json detection already in storage.py).

Steps, each with a done-criterion; commit after each green step:

1. **Pin current behavior.** Grep the exact TinyDB API surface storage.py uses
   (`grep -oE "_table\.[a-z_]+\(" services/storage.py | sort -u`). Write
   `tests/test_storage.py`: temp-dir TinyDB, round-trip every public storage
   function a caller uses (grep main.py/services for `storage\.` to enumerate),
   assert returned dicts. DONE: suite green on TinyDB.
2. **Build `services/storage_sqlite.py`**: `SqliteTable` class implementing that
   grepped API surface over `(doc_id INTEGER PRIMARY KEY, data TEXT)` tables;
   WAL + busy_timeout + per-thread connections; generated-column indexes from
   §3.1. DONE: unit-tested standalone.
3. **Toggle in storage.py** (`CHAUFFEUR_STORAGE` env var or settings key,
   default `tinydb`): init picks the backend; nothing else in storage.py
   changes. DONE: characterization suite green on BOTH backends.
4. **Migration routine** (§4) inside storage init + restore-endpoint support.
   DONE: migrating a copy of the real `data/db.json` + `routes_cache.json`
   passes the suite and spot-checks (row counts per table, dedup counts logged).
5. **Flip default to sqlite locally.** Soak: watch `[SLOW REQUEST]` middleware
   output — storage-bound endpoints (trip GET, accommodation DELETE, event
   config save) must vanish from it. DONE: several days of normal use clean.
6. **Ship**: `config.yaml` version bump, system_capabilities.md note (storage
   engine + backup format), keep `tinydb` toggle one release as escape hatch.
7. **Afterwards (separate efforts)**: delete TinyDB dependency + toggle; audit
   the 91 `db_lock` sites; delete stray files (§8 list).

## 8. Explicitly out of scope, noted for later

- Removing `db_lock` (91 sites) — separate effort after the swap soaks.
- Normalizing hot tables (e.g. `daily_schedules` per-day rows) — only if a
  real query need appears.
- The per-instance `api_usage` counters that can't enforce the shared Mapbox
  quota — unrelated to the engine, still open.
- Stray files to delete alongside this work: empty `chauffeur.db` (root),
  `data/db_copy.json`, zero-byte `data/*.json` leftovers.
