"""The household contact card and the two browse switches: schema, registry,
drawer. Spec 2026-10-10 browse missions §1, §5."""
from harness import check  # noqa: F401
from services import storage, browse, settings_registry
from models.schemas import Settings


def scenario_contact_card_reads_only_filled_fields():
    storage.get_settings = lambda: {'contact_first_name': 'Jeff', 'contact_last_name': 'Wilson',
                                    'contact_email': 'ffejnosliw@gmail.com', 'contact_phone': '919-327-7497',
                                    'contact_street': '', 'contact_zip': '27519'}
    card = browse.contact_card()
    check(card == {'first_name': 'Jeff', 'last_name': 'Wilson', 'email': 'ffejnosliw@gmail.com',
                   'phone': '919-327-7497', 'zip': '27519'}, f"filled fields only: {card}")
    check(set(browse.CONTACT_FIELDS) == {'first_name', 'last_name', 'email', 'phone', 'street', 'apt', 'city', 'state', 'zip', 'preferred'}, "the ten fields")


def scenario_settings_schema_and_registry_know_every_key():
    s = Settings()
    for f in browse.CONTACT_FIELDS:
        check(hasattr(s, f'contact_{f}'), f"Settings has contact_{f}")
    check(s.missions_captcha_attempts is False and s.mission_cap_browse_turns == 400, "defaults: consent off, 400 turns")
    keys = {e['key'] for e in settings_registry.ENTRIES}
    for k in [f'contact_{f}' for f in browse.CONTACT_FIELDS] + ['missions_captcha_attempts', 'mission_cap_browse_turns']:
        check(k in keys, f"{k} is registered")
    src = open('templates/components/missions_page.html', encoding='utf-8').read()
    for k in ('contact_first_name', 'contact_zip', 'missions_captcha_attempts', 'mission_cap_browse_turns'):
        check(f's.{k}' in src, f"the drawer binds {k}")
    check("settings_section('contact-card'" in src, "the contact card is its own section")


SCENARIOS = [scenario_contact_card_reads_only_filled_fields, scenario_settings_schema_and_registry_know_every_key]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)
