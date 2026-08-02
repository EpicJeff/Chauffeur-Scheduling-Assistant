"""Tests for prep kits (services/prep_kits.py).

Keyword-matched packing lists: matching semantics (case-insensitive any-keyword
substring, disabled kits skipped), item dedup across kits, storage CRUD, and
the suggest normalization layer (ungrounded keywords dropped, already-covered
kits filtered — with the LLM call mocked).

Run from chauffeur/:  python tests/test_prep_kits.py
"""
from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import prep_kits, storage


SOCCER = {"id": "k1", "name": "Soccer", "keywords": ["soccer"],
          "items": ["Cleats", "Shin Guards", "Water Bottle"], "enabled": True}
SWIM = {"id": "k2", "name": "Swim", "keywords": ["swim", "pool"],
        "items": ["Goggles", "Towel", "Water Bottle"], "enabled": True}
DISABLED = {"id": "k3", "name": "Old", "keywords": ["soccer"],
            "items": ["Ancient Boots"], "enabled": False}


def scenario_matching():
    kits = [SOCCER, SWIM, DISABLED]
    check([k["id"] for k in prep_kits.match_kits("Addison Soccer Practice", kits)] == ["k1"],
          "case-insensitive substring match; disabled kit skipped")
    check(prep_kits.match_kits("Piano Lesson", kits) == [], "no keyword hit = no kits")
    check(prep_kits.match_kits("", kits) == [], "empty title matches nothing")
    check([k["id"] for k in prep_kits.match_kits("POOL PARTY", kits)] == ["k2"],
          "any-keyword (second keyword) matches, case folded both ways")


def scenario_items_dedupe_across_kits():
    both = {"id": "k4", "name": "SwimSoccer", "keywords": ["biathlon"], "items": [], "enabled": True}
    kits = [SOCCER, SWIM, both]
    items = prep_kits.items_for_title("Soccer then swim meet", kits)
    check(items == ["Cleats", "Shin Guards", "Water Bottle", "Goggles", "Towel"],
          f"items merge in kit order, 'Water Bottle' deduped case-insensitively, got {items}")


def scenario_storage_crud():
    storage.prep_kits_table.truncate()
    storage.add_prep_kit(dict(SOCCER))
    check(len(storage.get_prep_kits()) == 1, "add + get")
    check(storage.update_prep_kit("k1", {"enabled": False}), "update by id returns True")
    check(storage.get_prep_kits()[0]["enabled"] is False, "update persisted")
    check(not storage.update_prep_kit("nope", {"enabled": True}), "unknown id returns False")
    storage.delete_prep_kit("k1")
    check(storage.get_prep_kits() == [], "delete removes the kit")


def scenario_suggest_normalization():
    from services import llm
    orig_llm, orig_settings = llm._call_llm_json, storage.get_settings
    storage.get_settings = lambda: {"calendar_ids": ["p"], "llm_gemini_api_key": "test-key"}
    llm._call_llm_json = lambda *a, **kw: {"kits": [
        # valid: keyword grounded in a real title
        {"name": "Soccer", "keywords": ["soccer", "quidditch"], "items": ["Cleats", "  Ball  "]},
        # every keyword ungrounded -> dropped entirely
        {"name": "Fencing", "keywords": ["fencing"], "items": ["Foil"]},
        # keywords fully covered by an existing kit -> dropped as duplicate
        {"name": "Swimming", "keywords": ["swim"], "items": ["Goggles"]},
        # malformed entries never crash the pipeline
        {"name": "", "keywords": ["soccer"], "items": ["X"]},
        "not-a-dict",
    ]}
    try:
        out = prep_kits.suggest_kits(
            ["Addison Soccer Practice", "Ben Swim Meet"],
            existing_kits=[{"name": "Swim", "keywords": ["swim"], "items": ["Towel"]}])
        check(len(out) == 1 and out[0]["name"] == "Soccer", f"only the grounded, novel kit survives, got {out}")
        check(out[0]["keywords"] == ["soccer"], "ungrounded keyword pruned from a surviving kit")
        check(out[0]["items"] == ["Cleats", "Ball"], "items whitespace-trimmed")
    finally:
        llm._call_llm_json, storage.get_settings = orig_llm, orig_settings


def scenario_suggest_requires_key():
    orig = storage.get_settings
    storage.get_settings = lambda: {"calendar_ids": ["p"]}
    try:
        try:
            prep_kits.suggest_kits(["Soccer Practice"])
            check(False, "missing LLM key should raise")
        except RuntimeError:
            check(True, "missing LLM key raises RuntimeError")
    finally:
        storage.get_settings = orig


SCENARIOS = [
    scenario_matching,
    scenario_items_dedupe_across_kits,
    scenario_storage_crud,
    scenario_suggest_normalization,
    scenario_suggest_requires_key,
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
    raise SystemExit(1 if failed else 0)
