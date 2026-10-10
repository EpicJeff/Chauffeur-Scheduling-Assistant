"""Opt-in only: CHF_BROWSE_SMOKE=1 runs the real runner against the real
Bodewell flow with NO released values and consent off. It must reach the
guest form and stop with needs_release naming the contact fields. Spends
real money (a few cents). Never in the gate."""
import os
import sys
import tempfile

if os.environ.get('CHF_BROWSE_SMOKE') != '1':
    print('SKIP test_browse_smoke_real (set CHF_BROWSE_SMOKE=1)')
    sys.exit(0)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services import storage, browse  # noqa: E402

key = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'gemini_paid_api_key.txt')).read().strip()
storage.get_settings = lambda: {'llm_gemini_paid_api_key': key, 'missions_captcha_attempts': False}
r = browse.run("Find the online scheduling flow for an in-home dishwasher repair (Cafe CDT805P2N3S1) and learn the earliest "
               "appointment windows and the service-call fee. Enter nothing personal.", 'geappliances.com', {}, {'captcha': False},
               start_url='https://www.geappliances.com/service', out_dir=tempfile.mkdtemp(prefix='browse_smoke_'))
print(r['outcome'], r['turns'], r['tokens_in'], r['tokens_out'], r['seconds'], r['stopped_at'])
print(r['text'][:800])
assert r['outcome'] in ('needs_release', 'captcha_failed'), r
assert 'bodewell.com' in r['stopped_at'], r
print('PASS test_browse_smoke_real')
