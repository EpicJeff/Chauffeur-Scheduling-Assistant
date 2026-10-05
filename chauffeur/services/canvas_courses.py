"""Canvas course names for a school feed's classes (K4d).

A Canvas calendar feed tags every item with the course's short code — at
some schools an SIS id like '502.Knox.30062Y0.6001.2027' — and nowhere
carries the name the family sees in Canvas. The REST API does: with an
access token generated in the child's Canvas account, GET /api/v1/courses
returns each course's id, name and course_code, and the id is the one the
feed's own URLs carry (`include_contexts=course_N`, our class key).

Security shape:
- The token is stored on the feed and is WRITE-ONLY: no API response ever
  returns it (`main._public_ics_feed`), only whether one is set.
- It is only ever sent to the feed's own Canvas host, over https, so a
  token pasted for one school cannot be steered anywhere else.
- Only one read endpoint is called. Nothing is written to Canvas.

The names land in `school_classes.canvas_name`, separate from the family's
own `name`, which always wins. Refreshed at most daily from the hourly sync,
and immediately when a token is saved.
"""
import datetime
from urllib.parse import urlparse

import requests

from services import storage

REFRESH_EVERY = datetime.timedelta(hours=20)
TIMEOUT = 15
MAX_PAGES = 5


def canvas_base(feed_url: str):
    """https://host of the feed, or None when the feed is not https/webcal."""
    url = (feed_url or '').strip()
    if url.lower().startswith('webcal://'):
        url = 'https://' + url[len('webcal://'):]
    p = urlparse(url)
    if p.scheme != 'https' or not p.hostname:
        return None
    return f"https://{p.netloc}"


def fetch_courses(base: str, token: str) -> list:
    """Every course on the token's account (all enrollment states, so last
    term's classes still resolve). Raises requests.HTTPError on refusal."""
    url = f"{base}/api/v1/courses"
    params = {'per_page': 100, 'state[]': ['available', 'completed']}
    headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json'}
    out = []
    for _ in range(MAX_PAGES):
        resp = requests.get(url, params=params, headers=headers, timeout=TIMEOUT)
        resp.raise_for_status()
        out += [c for c in resp.json() if isinstance(c, dict) and c.get('id')]
        nxt = resp.links.get('next', {}).get('url')
        # Pagination may only continue on the same host the token was sent to.
        if not nxt or urlparse(nxt).netloc != urlparse(base).netloc:
            break
        url, params = nxt, None
    return out


def refresh_class_names(feed: dict, force: bool = False) -> dict:
    """Fill canvas_name on this feed's child's classes. Returns
    {'status': str, 'named': int}; persists `canvas_status`/`canvas_synced`
    on the feed. Never raises."""
    token = (feed.get('canvas_token') or '').strip()
    if not token or feed.get('target_kind') != 'tasks':
        return {'status': 'no token', 'named': 0}
    now = datetime.datetime.now().astimezone()
    last = feed.get('canvas_synced')
    if not force and last:
        try:
            if now - datetime.datetime.fromisoformat(last) < REFRESH_EVERY:
                return {'status': 'fresh', 'named': 0}
        except ValueError:
            pass
    base = canvas_base(feed.get('url'))
    if not base:
        status = "error: the feed is not an https Canvas address"
        storage.update_ics_feed(feed['id'], {'canvas_status': status})
        return {'status': status, 'named': 0}
    try:
        courses = fetch_courses(base, token)
    except requests.HTTPError as e:
        code = getattr(e.response, 'status_code', None)
        status = ("error: Canvas refused the token — make a new one"
                  if code in (401, 403) else f"error: Canvas answered {code}")
        storage.update_ics_feed(feed['id'], {'canvas_status': status,
                                             'canvas_synced': now.isoformat()})
        return {'status': status, 'named': 0}
    except Exception as e:
        status = f"error: could not reach Canvas ({type(e).__name__})"
        storage.update_ics_feed(feed['id'], {'canvas_status': status})
        return {'status': status, 'named': 0}

    by_key = {}
    for c in courses:
        name = (c.get('name') or '').strip()
        if not name:
            continue
        by_key[f"course_{c['id']}"] = name
        if c.get('course_code'):
            by_key.setdefault(str(c['course_code']).strip(), name)
    named = 0
    for cls in storage.get_school_classes(feed.get('member_id')):
        name = by_key.get(cls.get('key')) or by_key.get(cls.get('label') or '')
        if name:
            named += 1
            if name[:60] != cls.get('canvas_name'):
                storage.update_school_class(cls['id'], {'canvas_name': name[:60]})
    status = f"ok: {len(courses)} Canvas courses"
    storage.update_ics_feed(feed['id'], {'canvas_status': status,
                                         'canvas_synced': now.isoformat()})
    return {'status': status, 'named': named}
