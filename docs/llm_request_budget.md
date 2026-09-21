# Gemini request accounting

**Living operational reference. Current through v2.499.4 (2026-09-14).**
These limits cover existing automated workflows and the Mind. Personalized
house authoring is still experimental and must use the same admission ledger;
it has no separate or unlimited request path.

Mind's existing `mind_cap_*` settings count high-level operations. They remain
in effect. Previously, one deep-think operation could issue twelve HTTP
attempts: four fallback models with three attempts each. The operation counter
did not see those retries.

`services/llm_budget.py` now reserves each actual Gemini HTTP attempt before
transmission. Failed attempts count too. SQLite transactions enforce admission
across workers and preserve counts and cooldowns across restarts. The ledger is
`llm_budget.sqlite3` beside the application database; it retains 32 days of
model, workflow, timestamp, and outcome data. It stores no raw API keys,
prompts, or responses.

Automated pool calls make at most one attempt per operation. Provider failures
pause that workflow for 15, 30, 60, then 120 minutes after repeated failures.
Mind's promoted requests cannot bypass that pause. Automated deep thinking
stays on Flash. Foreground pool calls can still try fallback models, with one
attempt per candidate; every attempt passes through admission.

Local daily allowances reset at Pacific midnight:

| Scope | Attempts |
| --- | ---: |
| Background Flash, shared across workflows and models | 12 |
| Each Flash model, all callers | 20 |
| Gemini 2.5 Flash Lite | 20 |
| Other Flash Lite models | 500 |
| Each Gemma model | 1,000 |

These are conservative application allowances, not authoritative provider
quota values. Manual work can use capacity beyond the shared background
allowance, subject to the per-model allowance. Existing Mind operation limits
still apply, including to forced thinking.

Accounting is local to this database and API-key fingerprint. It cannot recover
requests made before installation or see other deployments or API keys sharing
a provider project. Installation does not restore already exhausted provider
quota. Unknown model classes are recorded without guessing a daily allowance.

Verification uses mocked HTTP only: retry amplification, shared limits,
foreground reserve, concurrent admission, restart persistence, and day reset.


### House photo actions (v2.499.136)

Photo upload has one structure stage with at most three transmitted requests and a
120-second pool deadline. New drafts complete with one structural review request and
one detail request (two total, automatic or manual; shared 180-second deadline and
90-second maximum per request). Typical successful path: three requests; maximum for
one upload plus completion: five. A failed detail stage resumes without another review.
House matching uses a Flash-only pool chain, never automatic Lite fallback. Older draft
tokens retain their previous review limits (one automatic, three manual).
Compilation is local and has no provider cost. Pool request traces are recorded immediately before HTTP after
admission: local deferrals count zero and do not consume foreground fallback allowance.
Failed transmitted requests still count. Existing workflow pauses remain enforced.


As of v2.499.139, photo errors display the provided retry_at timestamp in UTC.
A generic pause message alone cannot distinguish short rate limits from daily quota
or another model cooldown. This display change does not clear or bypass admission.
