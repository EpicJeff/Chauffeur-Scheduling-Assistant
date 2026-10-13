# chauffeur/tests/test_provider_preflights.py
"""A Claude-only household reaches the pool on every entry point that used to demand a Gemini key."""
import os, sys, tempfile
os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_preflight_'))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from harness import check  # noqa: E402
from services import storage, model_pools, llm  # noqa: E402

CLAUDE_ONLY = {'llm_provider': 'anthropic', 'llm_anthropic_api_key': 'A', 'mind_enabled': True, 'web_research_enabled': False}
SEEN = []


def _fake_pool(tier, api_key, system, prompt, **kw):
    SEEN.append((tier, api_key))
    return {'rows': [], 'items': [], 'insights': [], 'answer': '', 'summary': ''}


def setup():
    storage.get_settings = lambda: dict(CLAUDE_ONLY)
    model_pools.call_pool_json = _fake_pool
    SEEN.clear()


def scenario_intake_photo_reads_with_a_claude_key():
    setup()
    from services import planner_intake
    out = planner_intake.extract('m1', 'AAAA', 'image/png')
    check(not out.get('error'), f'photo intake must not demand a Gemini key: {out}')
    check(SEEN and SEEN[0][1] == 'A', f'the pool got the Claude key: {SEEN}')


def scenario_email_extract_and_mind_handle_reach_the_pool():
    setup()
    from services import email_ingest
    try:
        email_ingest.extract_items('subj', 'a@b', 'body', ['Jeff'])
    except RuntimeError as e:
        check(False, f'extract_items raised on a Claude-only household: {e}')
    check(SEEN[-1][1] == 'A', 'email extraction used the Claude key')
    from services import mind
    res = mind.deep_think(force=True)
    check(res.get('status') != 'no_key', f'the Mind sees a configured household: {res}')
    st = email_ingest.wait_status(CLAUDE_ONLY)
    check('used_today' in st, f'intake status computes on the Claude account: {st}')


def scenario_auto_name_stores_a_plain_title():
    setup()
    titles = []
    storage.update_conversation_title = lambda cid, t: titles.append((cid, t))
    real = llm.call_model
    llm.call_model = lambda model, key, s, u, text=False, **kw: {'text': 'Dishwasher repair appointment'}
    try:
        llm.auto_name_conversation('c1', 'my dishwasher is broken, who can fix it?')
    finally:
        llm.call_model = real
    check(titles == [('c1', 'Dishwasher repair appointment')], f'title stored: {titles}')


def scenario_switching_back_to_gemini_without_a_key_is_honest():
    storage.get_settings = lambda: {'llm_provider': 'gemini', 'llm_anthropic_api_key': 'A'}
    from services import email_ingest
    st = email_ingest.wait_status({'llm_provider': 'gemini', 'llm_anthropic_api_key': 'A'})
    check(st.get('used_today', 0) == 0, 'no key = nothing counted, no crash')
    check(not model_pools.has_credentials({'llm_provider': 'gemini', 'llm_anthropic_api_key': 'A'}), 'has_credentials says no')


if __name__ == '__main__':
    scenario_intake_photo_reads_with_a_claude_key()
    scenario_email_extract_and_mind_handle_reach_the_pool()
    scenario_auto_name_stores_a_plain_title()
    scenario_switching_back_to_gemini_without_a_key_is_honest()
    print('test_provider_preflights OK')
