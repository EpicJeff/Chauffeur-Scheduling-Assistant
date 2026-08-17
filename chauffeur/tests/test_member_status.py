"""Member status: active | disabled | archived.

Two facts on one ladder, and the tests are grouped that way:

  * DISABLED revokes ACCESS. Every door refuses — password, PIN, an
    outstanding invite link, a live token — and the sessions and vouched
    devices die immediately, because access that ends at the next token
    expiry is not revoked, it is deprecated.
  * ARCHIVED additionally HIDES. Out of every roster, off the rota, while
    `get_member(id)` still answers so a message from three years ago keeps
    its author. That asymmetry — the LIST forgets you, the RECORD does not —
    is the whole design and most of what is pinned here.

The security property that is easy to get wrong and expensive to miss:
`_any_parent_has_password` must count archived parents, or archiving the
parent who claimed the house reopens the first-run bootstrap to anyone
arriving through ingress.

Run from chauffeur/:  python tests/test_member_status.py
"""
import uuid

from harness import check  # noqa: F401  (isolates CHAUFFEUR_DATA_DIR)

from services import storage


def _member(name='Vovo', role='adult', **extra):
    mid = uuid.uuid4().hex
    storage.add_member({'id': mid, 'name': name, 'role': role, **extra})
    return mid


def _reset():
    import main  # noqa: F401
    for t in (storage.members_table, storage.member_tokens_table,
              storage.trusted_devices_table, storage.drivers_table):
        t.truncate()


def scenario_absent_status_means_active():
    """Every member predating the field — which is all of them — must read
    as normal rather than as locked out."""
    _reset()
    m = storage.get_member(_member('Legacy'))
    check('status' not in m or m.get('status') is None or m['status'] == 'active',
          f"the fixture wrote a status it should not have: {m.get('status')}")
    check(storage.member_status(m) == 'active' and storage.member_has_access(m),
          "a member with no status field read as anything but active")
    check(storage.member_status({'status': 'nonsense'}) == 'active',
          "an unrecognised status must fail toward access, not away from it")


def scenario_archived_leaves_the_list_but_not_the_record():
    _reset()
    kept, gone = _member('Here'), _member('Gone')
    storage.set_member_status(gone, 'archived')
    ids = {m['id'] for m in storage.get_all_members()}
    check(kept in ids and gone not in ids,
          f"archived member still on the default roster: {ids}")
    ids_all = {m['id'] for m in storage.get_all_members(include_archived=True)}
    check(gone in ids_all, "include_archived=True did not bring them back")
    row = storage.get_member(gone)
    check(row and row['name'] == 'Gone',
          "get_member stopped answering for an archived person — every "
          "message and chore they are named on now renders Unknown")


def scenario_disabled_stays_visible():
    """Disabling is 'you cannot get in', never 'you do not exist'. They keep
    their place on the schedule, in history, on the map."""
    _reset()
    m = _member('Grounded')
    storage.set_member_status(m, 'disabled')
    check(m in {x['id'] for x in storage.get_all_members()},
          "a disabled member vanished from the family — that is archiving, "
          "which is a different act with a different button")
    check(not storage.member_has_access(storage.get_member(m)),
          "a disabled member kept access")


def scenario_a_live_token_stops_working_the_moment_access_goes():
    _reset()
    m = _member('Revoked')
    token = storage.create_member_token(m)
    check(storage.get_member_by_token(token) is not None, "fresh token failed")
    storage.set_member_status(m, 'disabled')
    check(storage.get_member_by_token(token) is None,
          "a disabled member's token still resolved — the chokepoint every "
          "authenticated request passes through has to be the backstop")


def scenario_losing_access_ends_sessions_and_untrusts_their_devices():
    """Both halves, for the same reason the stolen-phone lever needs both:
    killing sessions alone leaves the phone as trusted ground their PIN
    reopens thirty seconds later."""
    _reset()
    import main
    from fastapi import Header  # noqa: F401
    m = _member('Departing')
    parent = _member('Boss', role='parent')
    ptoken = storage.create_member_token(parent)
    storage.create_member_token(m)
    storage.create_member_token(m)
    storage.trust_device('their-phone', 'Their phone', by_member=m, kind='personal')
    storage.trust_device('kitchen', 'Kitchen', by_member=m, kind='panel')
    out = main.set_member_status_endpoint(
        m, main.MemberStatusRequest(status='disabled'), ptoken)
    check(out['sessions'] == 2 and out['devices'] == 1,
          f"expected 2 sessions and 1 personal device gone: {out}")
    check(storage.get_trusted_device('their-phone') is None,
          "their phone stayed trusted ground, so their PIN reopens it")
    check(storage.get_trusted_device('kitchen') is not None,
          "the wall panel lost its enrolment — a panel is the room's "
          "credential, not this person's")


def scenario_every_door_refuses_a_disabled_member():
    _reset()
    import main
    from fastapi import HTTPException
    m = _member('Shutout', email='shut@example.com')
    storage.set_member_password(m, 'correct horse battery')
    storage.set_member_pin(m, '1234')
    link = storage.create_auth_link(m, 'invite')
    storage.set_member_status(m, 'disabled')

    # 1. Password login — refused AFTER the password verifies, so the
    #    refusal never becomes a probe for which addresses exist.
    try:
        main.account_login(main.LoginRequest(email='shut@example.com',
                                             password='correct horse battery'), None)
        check(False, "a disabled member signed in with their password")
    except HTTPException as e:
        check(e.status_code == 403 and 'turned off' in str(e.detail),
              f"the refusal should name the state and the fix: {e.detail}")
    # ...and a WRONG password on that same account still gets the generic
    # answer, or the refusal is itself the leak.
    try:
        main.account_login(main.LoginRequest(email='shut@example.com',
                                             password='wrong'), None)
        check(False, "a wrong password was accepted")
    except HTTPException as e:
        check('turned off' not in str(e.detail),
              "a wrong password revealed that the account exists and is off")

    # 2. The PIN — refused before it is even read.
    try:
        main.member_auth(m, main.MemberAuthRequest(pin='1234'), None)
        check(False, "a disabled member's PIN still opened the app")
    except HTTPException as e:
        check(e.status_code == 403, f"expected 403 on the PIN door: {e}")

    # 3. An outstanding invite/reset link must not resurrect access.
    try:
        main.set_password_from_link(
            main.AcceptRequest(token=link, password='another good one'), None)
        check(False, "an old invite link brought a disabled account back")
    except HTTPException as e:
        check(e.status_code == 403, f"expected 403 on the link door: {e}")

    # 4. Forgot-password stays silent rather than becoming the one endpoint
    #    that behaves differently for a disabled address.
    sent = []
    from services import mailer
    real_send = mailer.send
    mailer.send = lambda *a, **k: sent.append(a)
    try:
        out = main.account_forgot(main.ForgotRequest(email='shut@example.com'), None)
    finally:
        mailer.send = real_send
    check(out.get('status') == 'ok' and not sent,
          f"forgot-password must answer identically and send nothing: {sent}")


def scenario_archiving_takes_them_off_the_rota_and_restoring_puts_them_back():
    _reset()
    import main
    parent = _member('Boss', role='parent')
    ptoken = storage.create_member_token(parent)
    storage.add_driver({'id': 'drv_x', 'name': 'Leaver', 'is_disabled': False})
    m = _member('Leaver', driver_id='drv_x')
    main.set_member_status_endpoint(m, main.MemberStatusRequest(status='archived'), ptoken)
    drv = next(d for d in storage.get_all_drivers() if d['id'] == 'drv_x')
    check(drv.get('is_disabled') is True,
          "an archived person stayed on the rota — the solver keeps handing "
          "them Tuesday's pickup, which is the archive meaning nothing")
    main.set_member_status_endpoint(m, main.MemberStatusRequest(status='active'), ptoken)
    drv = next(d for d in storage.get_all_drivers() if d['id'] == 'drv_x')
    check(drv.get('is_disabled') is False,
          "bringing somebody back left them off the rota")


def scenario_archiving_the_owner_does_not_reopen_the_house():
    """The security property. `_any_parent_has_password` asks 'has anybody
    ever claimed this house' — archiving the parent who did must not answer
    'no', or /api/account/claim reopens to anyone arriving via ingress."""
    _reset()
    import main
    owner = _member('Owner', role='parent')
    storage.set_member_password(owner, 'correct horse battery')
    check(main._any_parent_has_password(), "the household did not read as claimed")
    storage.set_member_status(owner, 'archived')
    check(main._any_parent_has_password(),
          "archiving the owning parent reopened the first-run bootstrap — "
          "the house became claimable again by hiding one person")


def scenario_one_list_two_questions_gets_two_answers():
    """The shape that makes a blanket `include_archived=True` wrong, found
    while sweeping the history sites: `get_pool_status` uses one member index
    for BOTH naming past contributions (history — keep the departed) and
    listing who is still short (a live roster — drop them). A departed
    child's pledge keeps their name; nobody chases them for the rest."""
    _reset()
    kid_gone = _member('Departed', role='child')
    kid_here = _member('Present', role='child')
    reward = {'id': 'rw1', 'cost': 100, 'min_share': 10}
    # The pledge is seeded directly: what is under test is how the STATUS
    # reads a stored contribution, not the spend path that wrote it.
    with storage.db_lock:
        storage.pool_contributions_table.truncate()
        storage.pool_contributions_table.insert(
            {'id': 'pc1', 'reward_id': 'rw1', 'member_id': kid_gone,
             'amount': 20, 'ts': 0})
    storage.set_member_status(kid_gone, 'archived')
    st = storage.get_pool_status(reward)
    named = [c for c in st['contributions'] if c['member_id'] == kid_gone]
    check(named and named[0]['member_name'] == 'Departed',
          f"the departed child's pledge lost its name: {st['contributions']}")
    check('Departed' not in st['short'],
          f"a child who left is still being chased for points: {st['short']}")
    check('Present' in st['short'],
          f"the child who is still here dropped off the chase list: {st['short']}")


def scenario_permanent_delete_no_longer_needs_a_password_of_its_own():
    """The 409-unless-force gate is gone: it refused anyone holding a driver
    or passenger profile, and you walked around it by deleting the profiles
    first. Friction that protects nothing."""
    _reset()
    import main
    m = _member('Typo', driver_id='drv_typo', passenger_id='pax_typo')
    out = main.delete_member_endpoint(m)
    check(out['status'] == 'deleted', f"the delete refused: {out}")
    check(storage.get_member(m) is None, "the member survived a delete")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} member-status scenarios passed")
