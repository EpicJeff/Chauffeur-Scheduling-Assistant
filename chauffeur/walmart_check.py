"""Does the Walmart wiring actually work? Run this before trusting anything.

    python walmart_check.py                 # credentials + a live search
    python walmart_check.py "chicken thighs"
    python walmart_check.py --cart 10450114 10315643_2

Reports exactly what came back, including the failure. A 401 here means the
signature or the key version is wrong; an empty result with a 200 means the
credentials are fine but the account has no access to that API yet — those are
very different problems and the difference is the whole reason this exists.

The CART half needs no credentials, so `--cart` works even if everything else
in here fails.
"""
import sys

from services import walmart


def check_credentials():
    creds = walmart.get_credentials()
    print("credentials")
    print(f"  consumer id : {'set (' + creds['consumer_id'][:8] + '…)' if creds['consumer_id'] else 'MISSING'}")
    print(f"  key version : {creds['key_version']}")
    print(f"  private key : {'set' if creds['private_key'] else 'MISSING'}")
    if not creds['configured']:
        print("\n  Put them in the add-on options (walmart_consumer_id,")
        print("  walmart_key_version, walmart_private_key), or drop")
        print("  walmart_consumer_id.txt and walmart_private_key.pem beside main.py.")
        return False
    try:
        h = walmart.sign_headers(creds)
        print(f"  signature   : ok ({h['WM_SEC.AUTH_SIGNATURE'][:24]}…)")
        return True
    except Exception as e:
        print(f"  signature   : FAILED — {type(e).__name__}: {e}")
        print("  The private key must be the PEM whose PUBLIC half you uploaded.")
        return False


def live_search(query):
    print(f"\nsearch {query!r}")
    try:
        items = walmart.search(query, 5)
    except PermissionError as pe:
        print(f"  REJECTED — {pe}")
        print("  Credentials reached Walmart and were refused. Check the key")
        print("  version matches the uploaded key, and that the consumer id is")
        print("  the one for THIS environment (sandbox ids do not work in prod).")
        return
    except Exception as e:
        print(f"  FAILED — {type(e).__name__}: {e}")
        return
    if not items:
        print("  200 OK but nothing came back. The signature is fine; this")
        print("  account probably has no access to the product API yet")
        print("  (the 'Request Access' step on walmart.io).")
        return
    for it in items:
        price = f" ${it['price']}" if it.get('price') else ""
        print(f"  {it['item_id']:>12}  {(it['title'] or '')[:56]}{price}")
    print("\n  Any of those ids can be mapped to a list item.")


def show_cart(specs):
    pairs = []
    for s in specs:
        item_id, _, qty = s.partition('_')
        pairs.append((item_id, int(qty) if qty.isdigit() else 1))
    url = walmart.cart_url(pairs)
    print("\ncart (no credentials needed)")
    print(f"  {url}")
    print("\n  Open it while signed in to Walmart. Then check the cart contents")
    print("  against what you asked for — the thing worth knowing is whether a")
    print("  BAD id fails loudly or just silently goes missing. Try one.")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:]]
    if args and args[0] == '--cart':
        show_cart(args[1:] or ['10450114'])
        raise SystemExit(0)
    ok = check_credentials()
    if ok:
        live_search(args[0] if args else "milk")
    else:
        print("\nSkipping the live search. `--cart` still works without credentials.")
