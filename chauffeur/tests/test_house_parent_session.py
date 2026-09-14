"""A parent PIN opens one short visit, without touching personal sessions."""
import time
from types import SimpleNamespace
from unittest.mock import patch
from harness import check
from services import storage
import main
from fastapi import HTTPException


def scenario_house_parent_sessions_are_bounded():
    storage.members_table.truncate()
    storage.member_tokens_table.truncate()
    for id, role in [('parent','parent'),('kid','child'),('no-pin','parent')]:
        storage.add_member({'id':id,'name':id,'role':role})
        if id != 'no-pin': storage.set_member_pin(id, '1234')
    normal = storage.create_member_token('parent')
    request = SimpleNamespace(headers={}, query_params={})
    for id, pin in [('kid','1234'),('no-pin',''),('parent','9999')]:
        try:
            main.member_auth(id, main.MemberAuthRequest(pin=pin, house_session=True), request)
        except HTTPException as e:
            check(e.status_code == 403, 'invalid parent proof is refused')
        else: raise AssertionError('house session accepted without parent PIN')
    result = main.member_auth('parent', main.MemberAuthRequest(pin='1234', house_session=True), request)
    token = result['token']
    check(result['expires_in'] == 900 and storage.get_member_by_token(token)['id'] == 'parent', 'valid PIN opens 15-minute session')
    with patch('time.time', return_value=time.time() + 901):
        check(storage.get_member_by_token(token) is None, 'server expires the house credential')
        check(storage.get_member_by_token(normal) is not None, 'personal credential keeps its normal lifetime')
    for _ in range(22): storage.create_member_token('parent', house_session=True)
    check(storage.get_member_by_token(normal) is not None, 'house visits cannot evict personal sessions')
    temp = storage.create_member_token('parent', house_session=True)
    main.end_house_session(temp)
    main.end_house_session(normal)
    check(storage.get_member_by_token(temp) is None, 'return revokes this visit')
    check(storage.get_member_by_token(normal) is not None, 'return cannot revoke a personal token')
    remote = SimpleNamespace(headers={'cf-connecting-ip':'203.0.113.12'}, query_params={})
    try:
        main.member_auth('parent', main.MemberAuthRequest(pin='1234', house_session=True), remote)
    except HTTPException as e:
        check(e.status_code == 403, 'untrusted device is refused even during auth observation')
    else: raise AssertionError('untrusted parent PIN opened Study')


if __name__ == '__main__':
    scenario_house_parent_sessions_are_bounded()
    print('House parent sessions passed')
