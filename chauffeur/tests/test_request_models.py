"""A handler may only read fields its request can actually carry.

Written after `serves` stopped saving on a dish. v2.109.2 taught
`set_dish_fields` to read `req.whole_units` and added the field to
`MealPatch` — but not to `DishFieldsReq`, which is the model that endpoint
takes. Pydantic raises AttributeError for a field it was never given, the read
is unconditional, and so EVERY call to that endpoint 500'd: not just the
by-the-tray toggle, but `serves`, the whole-meal switch and the category chips,
all of which go through the same handler. The hand path for what a dish IS had
been dead for nine versions.

Nothing caught it. The model is valid, the module imports, the endpoint has a
route, and the agent writes the same fields through a different door — so the
capability looked alive from every angle except the one screen it is on.

The class of bug is "a handler reads a field its model does not declare", and
it is findable statically across all of main.py at once, which is what the
first scenario does. The second is the specific round trip, because a
correction that cannot be typed by hand is not a capability.

Run from chauffeur/:  python tests/test_request_models.py
"""
import ast
import atexit
import os
import shutil
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="chauffeur_reqmodel_test_")
os.environ["CHAUFFEUR_DATA_DIR"] = _TMP
atexit.register(lambda: shutil.rmtree(_TMP, ignore_errors=True))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'main.py')


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def scenario_every_field_a_handler_reads_is_one_the_request_can_carry():
    """The whole file in one pass. `req.something` where `something` is not on
    `req`'s model is an AttributeError the moment that line runs — a 500 on a
    working endpoint, with a request body that validated perfectly."""
    import main
    from pydantic import BaseModel

    tree = ast.parse(open(MAIN, encoding='utf-8').read())
    models = {n.name for n in ast.walk(tree)
              if isinstance(n, ast.ClassDef)
              and any(getattr(b, 'id', getattr(b, 'attr', '')) == 'BaseModel'
                      for b in n.bases)}
    check(len(models) > 20, f"only found {len(models)} request models — did they move?")

    # Pydantic's own surface (model_dump, model_copy, …) is not a field and is
    # perfectly legal to call on a request.
    inherited = set(dir(BaseModel))
    missing = set()
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        params = {a.arg: a.annotation.id
                  for a in list(fn.args.args) + list(fn.args.kwonlyargs)
                  if getattr(a.annotation, 'id', None) in models}
        if not params:
            continue
        for node in ast.walk(fn):
            if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                    and node.value.id in params):
                model = params[node.value.id]
                fields = getattr(main, model).model_fields
                if node.attr not in fields and node.attr not in inherited:
                    missing.add((fn.name, model, node.attr, node.lineno))

    check(not missing, "handlers read fields their request model does not declare "
                       "(AttributeError -> 500 on every call): "
          + '; '.join(f"main.py:{ln} {fn}() reads {m}.{attr}"
                      for fn, m, attr, ln in sorted(missing, key=lambda x: x[3])))


def scenario_a_dish_can_be_corrected_by_hand():
    """The round trip that was broken: what a dish IS, and how many it feeds,
    set from the dish row rather than by asking Argyle. All four corrections
    share one handler, so they are checked together — the bug took all of them
    down at once and a test for `serves` alone would have said so too quietly."""
    import main
    from services import storage

    cat = storage.save_dish_category({'id': 'cat-protein', 'name': 'Protein',
                                      'min_per_plate': 1, 'max_per_plate': 1})
    dish_id = storage.add_dish({'id': 'dish-chili', 'name': 'Chili', 'type': 'dish',
                                'serves': 4, 'category_ids': [], 'tags': []})

    main.set_dish_fields(dish_id, main.DishFieldsReq(serves=8))
    check(storage.get_dish(dish_id)['serves'] == 8,
          "serves did not save — the hand path for scaling is dead again")

    main.set_dish_fields(dish_id, main.DishFieldsReq(whole_units=True))
    check(storage.get_dish(dish_id)['whole_units'] is True, "whole_units did not save")

    main.set_dish_fields(dish_id, main.DishFieldsReq(type='meal'))
    check(storage.get_dish(dish_id)['type'] == 'meal', "type did not save")

    main.set_dish_fields(dish_id, main.DishFieldsReq(category_ids=[cat['id']]))
    check(storage.get_dish(dish_id)['category_ids'] == [cat['id']],
          "category_ids did not save")

    # One field at a time, and the others stay where they were: this endpoint
    # is a PATCH, and the dish row sends exactly one key per change.
    main.set_dish_fields(dish_id, main.DishFieldsReq(tags=['Beef', ' ']))
    d = storage.get_dish(dish_id)
    check(d['tags'] == ['beef'], f"tags did not normalise: {d['tags']}")
    check(d['serves'] == 8 and d['type'] == 'meal',
          "a one-field patch reset the fields it was not given")


def scenario_out_of_range_corrections_are_clamped_not_stored():
    """`serves` is a scaling input for every timing and shopping number
    downstream, and this endpoint is reachable from a browser."""
    import main
    from services import storage

    dish_id = storage.add_dish({'id': 'dish-rice', 'name': 'Rice', 'type': 'dish',
                                'serves': 4})
    for given, want in ((0, 1), (-3, 1), (999, 50)):
        main.set_dish_fields(dish_id, main.DishFieldsReq(serves=given))
        got = storage.get_dish(dish_id)['serves']
        check(got == want, f"serves={given} stored as {got}, wanted {want}")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} request-model scenarios passed")
