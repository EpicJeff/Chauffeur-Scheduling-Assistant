"""A photo on a thread: stored beside moments, read once by the vision tier,
answers a waiting mission on that thread. Spec 2026-10-10 browse missions §3.

The endpoint scenarios call the FastAPI handler directly with `request=None`
and an explicit `member_id`, the same pattern as tests/test_threads_endpoints.py
(the repo's convention: no TestClient)."""
import asyncio
import base64
import io

from harness import check  # noqa: F401
from services import storage, threads, situations

MOM = {'id': 'mom', 'name': 'Mom', 'role': 'parent'}
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==')
CALLS = []


def _reset():
    CALLS.clear()
    for t in (storage.threads_table, storage.members_table, storage.app_state_table, storage.missions_table,
              storage.mission_steps_table):
        t.truncate()
    storage.get_settings = lambda: {'llm_gemini_api_key': 'k', 'thread_stall_days': 7}
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    storage.add_member({'id': 'kid', 'name': 'Kate', 'role': 'child', 'is_child': True})
    situations.REFRESH_DELAY_S = 0
    situations._pool_call = lambda *a, **k: {}


def _fake_pool(reply):
    def f(tier, key, system, prompt, **kw):
        CALLS.append({'tier': tier, 'kw': kw})
        return reply
    return f


def _post_photo(thread_id, data, mime, member_id, filename='label.png'):
    """Drive main.thread_photo the way the page does: multipart file + member_id.
    Returns (status_code, body)."""
    import main
    from fastapi import HTTPException
    from starlette.datastructures import UploadFile, Headers
    up = UploadFile(io.BytesIO(data), filename=filename, headers=Headers({'content-type': mime}))
    try:
        res = asyncio.run(main.thread_photo(thread_id, file=up, caption='', member_id=member_id, request=None))
        return 200, res
    except HTTPException as e:
        return e.status_code, {'detail': e.detail}


def scenario_photo_is_stored_read_and_logged():
    _reset()
    threads._pool_call = _fake_pool({'text': 'Model CDT805P2N3S1\nSerial LS758759B'})
    tid = threads.create('Pest control', owner_member_id='mom', created_by='mom')
    res = threads.add_photo(tid, PNG, 'image/png', 'mom', caption='the label')
    check(res['status'] == 'ok' and res['read'] is True, f"stored and read: {res}")
    h = storage.get_thread(tid)['history'][-1]
    check(h['kind'] == 'photo' and h['url'].startswith('/api/media/') and h['media_id'] and 'CDT805P2N3S1' in h['text'],
          f"the entry carries the url and the transcription: {h}")
    check(h['caption'] == 'the label' and h['who'] == 'mom', "caption and who")
    check(len(CALLS) == 1 and CALLS[0]['tier'] == 'vision' and CALLS[0]['kw'].get('images'), f"one vision call with the image: {CALLS}")
    check(storage.media_file_path(h['media_id']), "the file exists under the media root")
    check(threads.is_stalled(storage.get_thread(tid)) is None, "a photo is movement")


def scenario_cap_failure_and_no_key_leave_not_read():
    _reset()
    tid = threads.create('T', owner_member_id='mom', created_by='mom')
    storage.get_settings = lambda: {'thread_stall_days': 7}
    threads._pool_call = _fake_pool({'text': 'x'})
    res = threads.add_photo(tid, PNG, 'image/png', 'mom')
    check(res['read'] is False and storage.get_thread(tid)['history'][-1]['text'] == 'photo added (not read)' and not CALLS, "no key: stored, not read")
    storage.get_settings = lambda: {'llm_gemini_api_key': 'k', 'thread_stall_days': 7, 'thread_cap_photo_reads': 1}
    threads.add_photo(tid, PNG, 'image/png', 'mom')
    check(len(CALLS) == 1, "under the cap: read")
    res = threads.add_photo(tid, PNG, 'image/png', 'mom')
    check(len(CALLS) == 1 and res['read'] is False, "over the cap: stored, not read")

    def boom(*a, **k):
        raise RuntimeError('timeout')
    threads._pool_call = boom
    storage.get_settings = lambda: {'llm_gemini_api_key': 'k', 'thread_stall_days': 7}
    res = threads.add_photo(tid, PNG, 'image/png', 'mom')
    check(res['status'] == 'ok' and res['read'] is False, "a failed read is still a stored photo")


def scenario_photo_answers_only_its_own_mission():
    _reset()
    threads._pool_call = _fake_pool({'text': 'Serial LS758759B'})
    a = threads.create('A', owner_member_id='mom', created_by='mom')
    b = threads.create('B', owner_member_id='mom', created_by='mom')
    ma = storage.add_mission({'goal': 'fix A', 'origin_kind': 'thread', 'origin_ref': a, 'created_by': 'mom', 'status': 'waiting_user'})
    storage.add_mission_step(ma, {'kind': 'ask', 'name': 'question', 'result_json': {'question': 'Send me a photo of the label'}})
    mb = storage.add_mission({'goal': 'fix B', 'origin_kind': 'thread', 'origin_ref': b, 'created_by': 'mom', 'status': 'waiting_user'})
    storage.add_mission_step(mb, {'kind': 'ask', 'name': 'question', 'result_json': {'question': 'Which Friday?'}})
    threads.add_photo(a, PNG, 'image/png', 'mom')
    check(storage.get_mission(ma)['status'] == 'running', "the mission on A resumes")
    last = storage.get_mission_steps(ma)[-1]
    check(last['kind'] == 'note' and last['name'] == 'user_answer' and 'LS758759B' in last['result_json']['text'], f"the transcription is the answer: {last}")
    check(storage.get_mission(mb)['status'] == 'waiting_user', "the mission on B is untouched")


def scenario_photo_gates():
    """Through the handler: a parent may; the owner child may; another child may not."""
    _reset()
    threads._pool_call = _fake_pool({'text': 'ok'})
    tid = threads.create('Kate thread', owner_member_id='kid', created_by='mom')
    other = threads.create('Mom thread', owner_member_id='mom', created_by='mom')
    code, body = _post_photo(tid, PNG, 'image/png', 'mom')
    check(code == 200 and body.get('status') == 'ok', f"a parent may: {code} {body}")
    code, body = _post_photo(tid, PNG, 'image/png', 'kid')
    check(code == 200, f"the owner child may: {code} {body}")
    code, body = _post_photo(other, PNG, 'image/png', 'kid')
    check(code == 403, f"another child may not: {code}")
    code, body = _post_photo('nope', PNG, 'image/png', 'mom')
    check(code == 404, f"a missing thread is 404: {code}")


def scenario_non_image_is_refused():
    _reset()
    threads._pool_call = _fake_pool({'text': 'ok'})
    tid = threads.create('T', owner_member_id='mom', created_by='mom')
    code, body = _post_photo(tid, b'%PDF-1.4', 'application/pdf', 'mom', filename='x.pdf')
    check(code == 400 and not [h for h in storage.get_thread(tid)['history'] if h['kind'] == 'photo'] and not CALLS,
          f"a PDF is refused before storage and before any vision call: {code}")
    code, body = _post_photo(tid, b'', 'image/png', 'mom')
    check(code == 400, f"an empty image is refused: {code}")


SCENARIOS = [scenario_photo_is_stored_read_and_logged, scenario_cap_failure_and_no_key_leave_not_read,
             scenario_photo_answers_only_its_own_mission, scenario_photo_gates, scenario_non_image_is_refused]

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
