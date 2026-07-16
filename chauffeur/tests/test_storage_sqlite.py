"""Standalone unit tests for services/storage_sqlite.py (no services.storage import).

Covers what the characterization suite can't: SQL-vs-Python query agreement,
index usage on the hot lookups, explicit doc_id inserts (migration dependency),
and multi-thread access.

Run from chauffeur/:  python tests/test_storage_sqlite.py
"""
import os
import shutil
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tinydb import Query  # noqa: E402

from services import storage_sqlite  # noqa: E402
from services.storage_sqlite import Document, SqliteStorage, _translate  # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


_TMP = tempfile.mkdtemp(prefix="chauffeur_sqlite_test_")
_db_counter = [0]


def fresh_db():
    _db_counter[0] += 1
    return SqliteStorage(os.path.join(_TMP, f"t{_db_counter[0]}.sqlite3"))


DOCS = [
    {"origin": "home", "destination": "school", "duration_mins": 15, "timestamp": 100.5},
    {"origin": "home", "destination": "work", "duration_mins": 30, "timestamp": 200.0},
    {"origin": "gym", "destination": "school", "duration_mins": 5, "flag": True},
    {"origin": "gym", "destination": "school", "duration_mins": 8, "flag": False},
    {"destination": "school", "duration_mins": 99},          # missing origin
    {"origin": None, "destination": "school"},               # null origin
    {"origin": "home", "nested": {"a": 1}},
]


def scenario_sql_matches_python_fallback():
    """Every translatable query must return exactly what the Python predicate does."""
    db = fresh_db()
    t = db.table("distance_cache")
    for d in DOCS:
        t.insert(d)
    q = Query()
    cases = [
        q.origin == "home",
        q.origin == "nowhere",
        (q.origin == "home") & (q.destination == "school"),
        (q.origin == "home") | (q.origin == "gym"),
        q.duration_mins >= 15,
        q.duration_mins < 15,
        q.duration_mins <= 8,
        q.duration_mins > 98,
        q.flag == True,   # noqa: E712
        q.flag == False,  # noqa: E712
        q.nested.a == 1,
        q.timestamp >= 100.5,
        ((q.origin == "gym") & (q.duration_mins > 5)) | (q.destination == "work"),
    ]
    for cond in cases:
        check(_translate(cond) is not None, f"expected translatable: {cond}")
        sql_result = t.search(cond)
        py_result = [doc for doc in t.all() if cond(doc)]
        check(sql_result == py_result and
              [d.doc_id for d in sql_result] == [d.doc_id for d in py_result],
              f"SQL path diverged from Python predicate for {cond}: "
              f"{sql_result} vs {py_result}")


def scenario_untranslatable_fall_back():
    db = fresh_db()
    t = db.table("misc")
    for d in DOCS:
        t.insert(d)
    q = Query()
    # None values, list values, != and test() predicates must not be translated
    for cond in [q.origin == None,  # noqa: E711
                 q.origin == ["a"],
                 q.origin != "home",
                 q.origin.test(lambda v: v == "home")]:
        check(_translate(cond) is None, f"must not translate: {cond}")
    # and they still work via the fallback
    check(len(t.search(q.origin == None)) == 1, "None equality matches only stored null")  # noqa: E711
    check(len(t.search(q.origin.test(lambda v: v == "home"))) == 3, "test() predicate works")
    # TinyDB semantics: a stored null matches != 'home'; a missing field never matches
    check(len(t.search(q.origin != "home")) == 3,
          "!= matches stored null + other values, not missing fields")


def scenario_hot_queries_use_indexes():
    db = fresh_db()
    t = db.table("route_geometry")
    q = Query()
    t.insert({"origin": "a", "destination": "b", "profile": "driving", "data": {}})
    cond = (q.origin == "a") & (q.destination == "b") & (q.profile == "driving")
    sql, params = _translate(cond)
    plan = db.connection().execute(
        f'EXPLAIN QUERY PLAN SELECT doc_id, data FROM "route_geometry" WHERE {sql}',
        params).fetchall()
    plan_text = " ".join(str(row) for row in plan)
    check("idx_route_geometry_origin_destination_profile" in plan_text,
          f"route_geometry lookup must use the expression index, plan: {plan_text}")

    t2 = db.table("trip_metadata")
    t2.insert({"event_id": "ev1"})
    sql2, params2 = _translate(q.event_id == "ev1")
    plan2 = " ".join(str(r) for r in db.connection().execute(
        f'EXPLAIN QUERY PLAN SELECT doc_id, data FROM "trip_metadata" WHERE {sql2}',
        params2).fetchall())
    check("idx_trip_metadata_event_id" in plan2,
          f"trip_metadata lookup must use its index, plan: {plan2}")


def scenario_explicit_doc_id_insert():
    """The migration preserves TinyDB doc_ids by inserting Documents."""
    db = fresh_db()
    t = db.table("rules")
    rid = t.insert(Document({"name": "kept"}, 42))
    check(rid == 42, "explicit doc_id honored")
    check(t.get(doc_id=42) == {"name": "kept"}, "readable under preserved id")
    nxt = t.insert({"name": "auto"})
    check(nxt == 43, "autoincrement continues after the highest explicit id")


def scenario_json_type_fidelity():
    db = fresh_db()
    t = db.table("misc")
    doc = {"s": "text", "i": 7, "f": 3.25, "b": True, "n": None,
           "list": [1, "two", {"three": 3}], "nested": {"deep": [None, False]},
           "unicode": "école ✓ 日本語"}
    t.insert(doc)
    check(t.all()[0] == doc, "arbitrary JSON document survives roundtrip exactly")


def scenario_threaded_access():
    db = fresh_db()
    t = db.table("telemetry")
    errors = []

    def worker(n):
        try:
            for i in range(25):
                t.insert({"worker": n, "i": i})
                t.search(Query().worker == n)
        except Exception as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    check(not errors, f"thread errors: {errors}")
    check(len(t.all()) == 100, "all rows from all threads present")
    check(len({d.doc_id for d in t.all()}) == 100, "doc_ids unique across threads")


def scenario_transaction_rollback():
    db = fresh_db()
    t = db.table("rules")
    t.insert({"n": 1})
    try:
        with db.transaction() as conn:
            conn.execute('INSERT INTO "rules" (data) VALUES (?)', ('{"n": 2}',))
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    check(len(t.all()) == 1, "failed transaction rolled back")
    # connection still usable afterwards
    t.insert({"n": 3})
    check(len(t.all()) == 2, "connection usable after rollback")


def scenario_reentrant_transaction():
    db = fresh_db()
    t = db.table("rules")
    with db.transaction():
        t.insert({"n": 1})   # nested transaction via insert()
        t.update({"m": 2}, Query().n == 1)
    check(t.all()[0] == {"n": 1, "m": 2}, "nested writes inside outer txn commit once")


def scenario_persistence_across_reopen():
    path = os.path.join(_TMP, "persist.sqlite3")
    db1 = SqliteStorage(path)
    db1.table("drivers").insert({"name": "Alice"})
    db1.close()
    db2 = SqliteStorage(path)
    docs = db2.table("drivers").all()
    check(docs == [{"name": "Alice"}] and docs[0].doc_id == 1, "data persists across reopen")
    db2.close()


def scenario_migration_from_tinydb():
    import json
    from services.storage_sqlite import migrate_from_tinydb

    d = tempfile.mkdtemp(dir=_TMP)
    db_json = os.path.join(d, "db.json")
    routes_json = os.path.join(d, "routes_cache.json")
    sqlite_path = os.path.join(d, "chauffeur.sqlite3")

    with open(db_json, "w", encoding="utf-8") as f:
        json.dump({
            "drivers": {"1": {"name": "Alice"}, "7": {"name": "Bob"}},
            "rules": {"3": {"constraint_type": "required", "keywords": ["k"]}},
            "distance_cache": {
                "1": {"origin": "a", "destination": "b", "duration_mins": 10, "timestamp": 1},
                "2": {"origin": "a", "destination": "b", "duration_mins": 99, "timestamp": 2},
                "3": {"origin": "c", "destination": "d", "duration_mins": 5, "timestamp": 1},
            },
            "geocode_cache": {
                "1": {"address": "x", "lat": 1.0, "lon": 2.0},
                "2": {"address": "x", "lat": 9.0, "lon": 9.0},
                "3": {"address": "y", "lat": 3.0, "lon": 4.0},
            },
        }, f)
    with open(routes_json, "w", encoding="utf-8") as f:
        json.dump({"route_geometry": {
            "5": {"origin": "a", "destination": "b", "profile": "driving",
                  "data": {"coords": [[1, 2]]}, "timestamp": 1}}}, f)

    stats = migrate_from_tinydb(sqlite_path, db_json, routes_json)
    check(stats is not None, "migration ran")
    check(stats["deduped"] == {"distance_cache": 1, "geocode_cache": 1},
          f"dedup counts, got {stats['deduped']}")
    check(not os.path.exists(db_json) and os.path.exists(db_json + ".pre-sqlite.bak"),
          "db.json renamed to .bak")
    check(os.path.exists(routes_json + ".pre-sqlite.bak"), "routes_cache.json renamed to .bak")
    check(not os.path.exists(sqlite_path + ".migrating"), "temp build file cleaned up")

    db = SqliteStorage(sqlite_path)
    drivers = db.table("drivers").all()
    check([d_.doc_id for d_ in drivers] == [1, 7], "doc_ids preserved verbatim")
    check(drivers[1] == {"name": "Bob"}, "docs copied verbatim")
    check(db.table("drivers").insert({"name": "New"}) == 8,
          "autoincrement continues after preserved ids")
    check(db.table("rules").get(doc_id=3)["keywords"] == ["k"], "rules doc_id preserved")

    # distance: newest duplicate wins (the row the mem-cache rebuild would use)
    dist = db.table("distance_cache").all()
    ab = [r for r in dist if r["origin"] == "a"]
    check(len(dist) == 2 and len(ab) == 1 and ab[0]["duration_mins"] == 99,
          f"distance dedup keeps last row, got {dist}")
    # geocode: first duplicate wins (the row search(...)[0] returns today)
    geo = db.table("geocode_cache").all()
    x = [r for r in geo if r["address"] == "x"]
    check(len(geo) == 2 and len(x) == 1 and x[0]["lat"] == 1.0,
          f"geocode dedup keeps first row, got {geo}")

    routes = db.table("route_geometry").all()
    check(len(routes) == 1 and routes[0]["data"] == {"coords": [[1, 2]]},
          "routes_cache.json merged into route_geometry")
    db.close()

    # nothing to migrate -> None, no file created
    empty_dir = tempfile.mkdtemp(dir=_TMP)
    check(migrate_from_tinydb(os.path.join(empty_dir, "c.sqlite3"),
                              os.path.join(empty_dir, "db.json")) is None,
          "no legacy files -> no-op")
    check(not os.path.exists(os.path.join(empty_dir, "c.sqlite3")), "no empty DB left behind")


def scenario_table_name_validation():
    db = fresh_db()
    try:
        db.table('bad"; DROP TABLE x; --')
        raised = False
    except ValueError:
        raised = True
    check(raised, "invalid table names rejected")


SCENARIOS = [
    scenario_sql_matches_python_fallback,
    scenario_untranslatable_fall_back,
    scenario_hot_queries_use_indexes,
    scenario_explicit_doc_id_insert,
    scenario_json_type_fidelity,
    scenario_threaded_access,
    scenario_transaction_rollback,
    scenario_reentrant_transaction,
    scenario_persistence_across_reopen,
    scenario_migration_from_tinydb,
    scenario_table_name_validation,
]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    shutil.rmtree(_TMP, ignore_errors=True)
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)
