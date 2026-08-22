"""Supply intake A6 — order-by, and the way out to a cart.

The last slice, and mostly the smallest: A2's spine already did the deadline
arithmetic this was scoped to carry. What is left is making the lead a real
setting, showing the family what has already been chosen, and closing the
loop with the cart rails that shipped in W1.

The properties that matter, and why:

  1. **The deadline is BEFORE the party, never the day of it.** A pickup
     order placed the night before is a present that is not there.
  2. **The lead is the family's, and it lives on the page that owns it** —
     config decentralisation, not another row on config.html.
  3. **The cart is the last step and it is a PERSON'S tap.** Nothing in this
     arc ever buys anything; Add-To-Cart is a URL and the button says so.
  4. **Unmatched rows are named, never silently dropped** — a list of four
     becoming a cart of three with no explanation is the failure
     `cart_for_list` was already fixed for once.
  5. **The occasion carries its own rows**, so the panel can say what is
     chosen and when it is due without a second round-trip per list.

Run from chauffeur/:  python tests/test_gift_leadtime.py
"""
import datetime
from unittest import mock

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import storage
from services import occasions as _occ

TODAY = datetime.date.today()
SAT = TODAY + datetime.timedelta(days=10)


def _reset():
    with storage.db_lock:
        storage.occasions_table.truncate()
        storage.members_table.truncate()
        storage.shopping_lists_table.truncate()
        storage.shopping_items_table.truncate()
        storage.walmart_items_table.truncate()


def _household():
    from models.schemas import FamilyMember
    for mid, name, role in (('mum', 'Mum', 'parent'), ('ellie', 'Ellie', 'child')):
        storage.add_member(FamilyMember(id=mid, name=name, role=role).model_dump())


def _party():
    o = _occ.create("Jack's party", SAT.isoformat(), 'invited')
    storage.update_occasion(o['id'], {'answers': {'whose_party': 'Jack',
                                                  'their_age': 7,
                                                  'gift_budget': 25}})
    return storage.get_occasion(o['id'])


def scenario_the_lead_is_a_setting_and_it_moves_the_deadline():
    """Properties 1 and 2. Three days is a default, not a law — a family who
    orders online wants a week, and one who walks to a shop wants a day."""
    _reset(); _household()
    o = _party()

    with mock.patch('services.storage.get_settings', return_value={}):
        check(_occ.gift_lead_days() == 3, "three days when nobody has said")
    with mock.patch('services.storage.get_settings',
                    return_value={'gift_lead_days': 7}):
        check(_occ.gift_lead_days() == 7, "and the family's number when they have")
        res = _occ.add_gifts(o['id'], [{'item_id': '1', 'title': 'Art Case'}])
    check(res['needed_by'] == (SAT - datetime.timedelta(days=7)).isoformat(),
          f"the deadline moves with it: {res['needed_by']}")
    check(res['needed_by'] < SAT.isoformat(),
          "and it is BEFORE the party — a present that arrives on the day is late")

    # Nonsense in the setting must not throw a party away.
    with mock.patch('services.storage.get_settings',
                    return_value={'gift_lead_days': 'soon'}):
        check(_occ.gift_lead_days() == 3, "garbage falls back to the default")
    with mock.patch('services.storage.get_settings',
                    return_value={'gift_lead_days': -5}):
        check(_occ.gift_lead_days() == 0, "and a negative lead is clamped, not inverted")


def scenario_the_deadline_reaches_the_spine():
    """A6 exists to feed A2, not to duplicate it: once the row is written the
    machinery from two slices ago does the noticing."""
    from services import shopping as _shop
    _reset(); _household()
    o = _party()
    with mock.patch('services.storage.get_settings',
                    return_value={'gift_lead_days': 3}):
        res = _occ.add_gifts(o['id'], [{'item_id': '1', 'title': 'Art Case'}])
    due = res['needed_by']

    # A run after the deadline is late — the same verdict any school supply gets.
    rows = _shop.annotate_deadlines(
        storage.get_shopping_items(res['list']['id']), today=TODAY,
        run_date=(SAT - datetime.timedelta(days=1)).isoformat())
    check(rows[0]['deadline']['late'] is True and rows[0]['deadline']['needed_by'] == due,
          f"the gift is just a dated thing on a list now: {rows[0]['deadline']}")

    rows2 = _shop.annotate_deadlines(
        storage.get_shopping_items(res['list']['id']), today=TODAY,
        run_date=(SAT - datetime.timedelta(days=5)).isoformat())
    check(rows2[0]['deadline']['late'] is False,
          "and a run in time is not an alarm")


def scenario_the_occasion_carries_its_rows():
    """Property 5. The panel says what is chosen and when it is due from one
    fetch, rather than asking again per list."""
    _reset(); _household()
    o = _party()
    with mock.patch('services.storage.get_settings',
                    return_value={'gift_lead_days': 3}):
        _occ.add_gifts(o['id'], [{'item_id': '1', 'title': 'Art Case'},
                                 {'item_id': '5', 'title': 'Dino Set'}])
    c = _occ.contents(o['id'])
    gift = next(l for l in c['lists'] if l.get('occasion_key') == 'gift')
    check([i['name'] for i in gift['items']] == ['Art Case', 'Dino Set'],
          f"the rows ride the list: {[i.get('name') for i in gift['items']]}")
    check(all(i['needed_by'] for i in gift['items']),
          "each carrying its own deadline")
    check(gift['audience'] == 'private',
          "and the panel can see it is the closed one before it draws a lock")


def scenario_the_cart_is_a_persons_tap_and_hides_nothing():
    """Properties 3 and 4. Add-To-Cart is a URL: it builds a cart and cannot
    check out, hold a card, or spend anything."""
    from services import walmart
    _reset(); _household()
    o = _party()
    with mock.patch('services.storage.get_settings',
                    return_value={'gift_lead_days': 3}):
        res = _occ.add_gifts(o['id'], [{'item_id': '1', 'title': 'Art Case'}])
    lid = res['list']['id']

    # A hand-added row nobody has mapped must be REPORTED, not dropped.
    from models.schemas import ShoppingItem
    storage.add_shopping_item(
        ShoppingItem(list_id=lid, name='birthday card').model_dump())

    cart = walmart.cart_for_list(lid)
    check(cart['matched_count'] == 1 and cart['unmatched_count'] == 1,
          f"one carts, one cannot, and both are counted: {cart}")
    check([u['name'] for u in cart['unmatched']] == ['birthday card'],
          f"named, so the family knows what to add by hand: {cart['unmatched']}")
    check(cart['url'] and 'addToCart' in cart['url'],
          f"the URL is a CART, not an order: {cart['url']}")

    import os
    tpl = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'templates')
    occ = open(os.path.join(tpl, 'occasions.html'), encoding='utf-8').read()
    check('you check out' in occ,
          "and the button says who does the buying — never 'order it'")
    check('has no Walmart item behind it' in occ,
          "the unmatched count is shown, never a quietly shorter cart")


def scenario_the_page_owns_its_setting():
    """Property 2, and the standing rule: new settings go in the registry and
    on the feature's own page, never on config.html."""
    from services import settings_registry as reg
    entry = next((e for e in reg.ENTRIES if e['key'] == 'gift_lead_days'), None)
    check(entry, "declared in the registry")
    check(entry['page'] == 'occasions' and entry['anchor'] == 'gifts',
          f"pointing at the page that owns it: {entry}")

    import os
    tpl = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'templates')
    occ = open(os.path.join(tpl, 'occasions.html'), encoding='utf-8').read()
    check('id="gifts"' in occ, "the deep-link anchor exists")
    check('giftLeadDays' in occ and 'saveGiftLead' in occ,
          "and the control is real, not just an anchor")
    cfg = open(os.path.join(tpl, 'config.html'), encoding='utf-8').read()
    check('gift_lead_days' not in cfg, "and it did NOT land back on config.html")

    from models.schemas import Settings
    check(Settings().gift_lead_days == 3,
          "the model whitelists it — an unlisted key is dropped on every save")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} gift-leadtime scenarios passed")
