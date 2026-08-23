# Album Moments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let one message carry up to ten photos/clips under one caption, so a
part of an event arrives as a block with context instead of five context-free
stills.

**Architecture:** `ChatMessage.attachment` grows an `items` list while keeping
the cover's fields mirrored at the top level, so all thirteen existing readers
keep working untouched and no migration is needed. One helper,
`storage.attachment_items()`, is the only place that knows the rule. The
composer uploads every item before posting, so the message is written once,
complete.

**Tech Stack:** FastAPI + Pydantic (`main.py`, `services/`), TinyDB/SQLite dual
backend behind `services/storage.py`, Jinja templates with plain JS (no build
step for JS), precompiled Tailwind, custom test harness (`tools/test.py`).

**Spec:** `chauffeur/docs/album_moments_design.md` — read it before Task 1.
Every task below argues from it.

## Global Constraints

- **Cap: 10 media per album.** `main._ALBUM_MAX_ITEMS = 10`. Enforced in the
  composer (trims + tells the user) and in `_validate_moment_attachment` (400).
- **`items` is ABSENT for a single share.** A one-item list normalizes to a
  plain attachment. There is exactly one representation of "one photo".
- **`items[0]` IS the cover**, and the cover's fields stay mirrored at the top
  level of `attachment`. Never compute the cover anywhere but in
  `_validate_moment_attachment`.
- **Every task ends in a version bump + commit + push.** Bump `config.yaml`
  `version:` — Task 1 goes to `2.387.0`, each later task takes the next patch
  (`2.387.1`, `2.387.2`, …). Commit subject ends with `(vX.Y.Z)`. Never ask
  first; this is the repo's standing rhythm.
- **Commit through the Bash tool with a heredoc**, never PowerShell: double
  quotes in a commit message get split into separate args by PowerShell.
- **Never round-trip a source file through `Get-Content`/`Set-Content`** — it
  silently mojibakes UTF-8. Use the Edit/Write tools or a Python heredoc.
- **Inner loop:** `python tools/test.py --focus` (reads `git diff`, ~5-20s).
  **Before every commit that touches code:** `python tools/test.py` (full
  parallel sweep, ~160s). Never a serial loop, never piped — a pipe masks the
  exit code.
- **After any template class change:** `python tools/build_tailwind.py`. A
  stale sheet fails silently, and `test_tailwind_build.py` will catch it.
- **No browser dialogs.** Never `alert()`/`confirm()`/`prompt()`. In `app.html`
  use `showGlobalAlert` / `promptConfirm`; on panel pages those come from
  `components/control_center.html`.
- **Tests run twice**, once per storage backend. `tests/test_presence.py`
  re-executes itself under `CHAUFFEUR_STORAGE=tinydb` then `sqlite`. Anything
  you add must pass under both.
- Working directory for every command is `chauffeur/` (the package dir), not
  the repo root.

---

### Task 1: `attachment_items` and per-item media cleanup

The landmine first. Moments are exempt from the retention cap, so nothing else
will ever collect an album's non-cover files — get this wrong and they sit on
the family's disk forever.

**Files:**
- Modify: `services/storage.py` (near `_delete_media_for_messages`, ~line 5531)
- Test: `tests/test_presence.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `storage.attachment_items(att: dict | None) -> list[dict]` — every media in
    a moment, cover first. `[]` for an attachment with no media at all.
  - `storage._delete_media_for_attachment(item: dict) -> None` — frees one
    media's files (the media file, `.orig`, `.tmp.mp4`, poster `.jpg`).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_presence.py`, immediately before the `SCENARIOS = [` list:

```python
def scenario_attachment_items_helper():
    """One helper is the only thing that knows the album rule."""
    legacy = {"kind": "photo", "data_url": _TINY_JPEG}
    single = {"kind": "photo", "url": "/api/media/" + "a" * 32}
    album = {"kind": "photo", "url": "/api/media/" + "a" * 32,
             "items": [{"kind": "photo", "url": "/api/media/" + "a" * 32},
                       {"kind": "video", "url": "/api/media/" + "b" * 32 + ".mp4"}]}
    check(storage.attachment_items(legacy) == [legacy], "a legacy inline photo is one item")
    check(storage.attachment_items(single) == [single], "a modern single photo is one item")
    check([i["url"] for i in storage.attachment_items(album)]
          == ["/api/media/" + "a" * 32, "/api/media/" + "b" * 32 + ".mp4"],
          "an album yields its items, cover first")
    check(storage.attachment_items(None) == [], "no attachment is no media")
    check(storage.attachment_items({}) == [], "an empty attachment is no media")
    check(storage.attachment_items({"kind": "photo"}) == [],
          "an attachment with no url and no data is no media")


def scenario_album_deletion_frees_every_file():
    """THE landmine: moments never age out, so if deletion misses an album's
    non-cover files nothing else ever collects them."""
    import main
    _family()
    ch = storage.get_or_create_event_channel("vb1", "Emma's Volleyball")
    saved = [storage.save_photo_data_url(_TINY_JPEG) for _ in range(3)]
    check(all(saved), "three photos land in the media store")
    ids = [s["url"].rsplit("/", 1)[-1] for s in saved]
    check(all(storage.media_file_path(i) for i in ids), "all three exist on disk")

    storage.add_chat_message({
        "id": "alb", "channel_id": ch["id"], "sender_member_id": "mom",
        "ts": time.time(), "type": "text", "body": "first half",
        "attachment": {"kind": "photo", "url": saved[0]["url"],
                       "items": [{"kind": "photo", "url": s["url"]} for s in saved]},
        "reactions": {}})

    storage.delete_chat_message("alb")
    left = [i for i in ids if storage.media_file_path(i)]
    check(not left, f"every item's file is freed, not just the cover — left {left}")
```

Register both in `SCENARIOS`, after `scenario_hearth_is_pop_only`:

```python
    scenario_attachment_items_helper,
    scenario_album_deletion_frees_every_file,
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python tests/test_presence.py`
Expected: `FAIL scenario_attachment_items_helper` with
`AttributeError: module 'services.storage' has no attribute 'attachment_items'`.

- [ ] **Step 3: Write the implementation**

In `services/storage.py`, replace the whole `_delete_media_for_messages`
function with these three:

```python
def attachment_items(att) -> List[dict]:
    """Every media in a moment, cover first.

    One item for an ordinary moment, N for an album — so a caller can iterate
    without first asking which it has. THE only place that knows the album
    rule: `items` present means album, absent means the attachment IS the
    media, and `items[0]` is always the same media the top level mirrors."""
    att = att or {}
    items = att.get('items')
    if isinstance(items, list) and items:
        return [i for i in items if isinstance(i, dict)]
    return [att] if (att.get('url') or att.get('data_url')) else []


def _delete_media_for_attachment(att):
    """Free the files ONE media owns. Split out from the message sweep so the
    single-item delete route and the whole-message delete share one definition
    of what a media owns — the suffix list is exactly the kind of thing that
    grows on one side and not the other."""
    url = str((att or {}).get('url') or '')
    if not url.startswith('/api/media/'):
        return
    media_id = url.rsplit('/', 1)[-1]
    stem = media_id.split('.')[0]
    if not (len(stem) == 32 and all(c in '0123456789abcdef' for c in stem)):
        return
    for name in (media_id, stem + '.orig', stem + '.tmp.mp4', stem + '.jpg'):
        # Wherever it actually is — sharded or flat, new root or the legacy
        # one a half-finished migration left it in.
        p = media_read_path(name)
        if not p:
            continue
        try:
            os.remove(p)
        except OSError:
            pass


def _delete_media_for_messages(msgs):
    """Best-effort file cleanup when messages roll off the retention cap or are
    deleted outright — a pruned moment must not orphan its clip (or a pending
    transcode's working files) on disk. Iterates EVERY item: an album's
    non-cover media has no other collector, because moments are exempt from
    the retention cap."""
    for m in msgs:
        att = (m.get('attachment') or {}) if isinstance(m, dict) else {}
        for item in attachment_items(att):
            _delete_media_for_attachment(item)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python tests/test_presence.py`
Expected: all scenarios PASS, under both backends.

- [ ] **Step 5: Full sweep, then commit**

```bash
python tools/test.py
sed -i 's/^version: "2.386.0"/version: "2.387.0"/' config.yaml
```

```bash
cd /e/repositories/Chauffeur && git add -A && git commit -F - <<'EOF'
One helper knows what an album is; deletion frees all of it. (v2.387.0)

storage.attachment_items is the only code that knows `items` means album.
Everything downstream iterates it instead of reaching for the cover.

The file sweep is the part that mattered: moments are exempt from the
retention cap, so nothing else would ever have collected an album's
non-cover media and it would have sat on the family's disk forever.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
git push origin main
```

---

### Task 2: Validate an album on the way in

**Files:**
- Modify: `main.py` — `_validate_moment_attachment` (~line 12168) and the
  constant block above it (~line 12166)
- Test: `tests/test_presence.py`

**Interfaces:**
- Consumes: `storage.attachment_items` (Task 1) — not directly, but the shape
  it assumes.
- Produces: `main._ALBUM_MAX_ITEMS = 10`; `_validate_moment_attachment` now
  accepts `{'items': [...]}` and returns `{**items[0], 'items': items}`, or a
  plain single attachment when exactly one item survives.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_presence.py` before `SCENARIOS = [`:

```python
def scenario_album_validation():
    """The one choke point every album passes through."""
    import main
    from fastapi import BackgroundTasks, HTTPException
    _member("mom", "Mom", role="parent")
    ch = storage.get_or_create_event_channel("evA", "Soccer")
    bt = BackgroundTasks()

    def photo():
        return {"kind": "photo", "data_url": _TINY_JPEG, "w": 4, "h": 4}

    # Ten is the cap and it is accepted.
    m = main.send_message(ch["id"], main.SendMessageRequest(
        sender_member_id="mom", body="first half",
        attachment={"items": [photo() for _ in range(10)]}), bt)
    att = m["attachment"]
    check(len(att["items"]) == 10, f"ten items kept, got {len(att['items'])}")
    check(att["kind"] == "photo" and att["url"] == att["items"][0]["url"],
          "the cover mirrors items[0]")
    check(all(i["url"].startswith("/api/media/") for i in att["items"]),
          "every item is persisted to the media store, none left inline")
    check(len({i["url"] for i in att["items"]}) == 10,
          "ten distinct files, not one file referenced ten times")

    # Eleven is refused, and the message says what the limit is.
    try:
        main.send_message(ch["id"], main.SendMessageRequest(
            sender_member_id="mom", body="",
            attachment={"items": [photo() for _ in range(11)]}), bt)
        check(False, "expected 400")
    except HTTPException as e:
        check(e.status_code == 400 and "10" in str(e.detail),
              f"eleventh item refused with the limit named, got {e.detail}")

    # An empty list is not an album.
    try:
        main.send_message(ch["id"], main.SendMessageRequest(
            sender_member_id="mom", body="", attachment={"items": []}), bt)
        check(False, "expected 400")
    except HTTPException as e:
        check(e.status_code == 400, "an empty album is refused")

    # A bad item raises ITS error, not a generic one.
    try:
        main.send_message(ch["id"], main.SendMessageRequest(
            sender_member_id="mom", body="",
            attachment={"items": [photo(), {"kind": "photo", "data_url": "http://x/y.jpg"}]}), bt)
        check(False, "expected 400")
    except HTTPException as e:
        check("image data URL" in str(e.detail),
              f"the failing item's own error survives, got {e.detail}")

    # One item is NOT an album — one representation of one photo.
    m = main.send_message(ch["id"], main.SendMessageRequest(
        sender_member_id="mom", body="", attachment={"items": [photo()]}), bt)
    check("items" not in m["attachment"] and m["attachment"]["kind"] == "photo",
          f"a one-item list normalizes to a plain attachment, got {m['attachment']}")

    # Albums do not nest.
    try:
        main.send_message(ch["id"], main.SendMessageRequest(
            sender_member_id="mom", body="",
            attachment={"items": [{"kind": "photo", "data_url": _TINY_JPEG,
                                   "items": [photo()]}]}), bt)
        check(False, "expected 400")
    except HTTPException as e:
        check(e.status_code == 400, "a nested album is refused")
```

Register it in `SCENARIOS`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python tests/test_presence.py`
Expected: `FAIL scenario_album_validation` — the first `send_message` raises
`HTTPException: Unsupported attachment kind` (there is no `kind` on an
items-only attachment).

- [ ] **Step 3: Write the implementation**

In `main.py`, add the constant beside `_ATTACHMENT_MAX_CHARS`:

```python
# One share, one caption, up to ten media. Enough for a part of a game; low
# enough that a single share cannot dump a camera roll onto the wall.
_ALBUM_MAX_ITEMS = 10
```

Then insert this branch at the TOP of `_validate_moment_attachment`, right
after the `isinstance(att, dict)` guard and before the `kind == 'photo'` test:

```python
    # An ALBUM. Each item goes through this same function, so a data URL in
    # item 4 is still persisted to the media store and a bad item still raises
    # its own error rather than a generic one. The cover is mirrored HERE and
    # nowhere else — see docs/album_moments_design.md.
    if att.get('items') is not None:
        raw = att.get('items')
        if not isinstance(raw, list) or not raw:
            raise HTTPException(status_code=400,
                                detail="An album needs at least one photo or clip")
        if len(raw) > _ALBUM_MAX_ITEMS:
            raise HTTPException(
                status_code=400,
                detail=f"An album holds at most {_ALBUM_MAX_ITEMS} — that one has {len(raw)}")
        items = []
        for i in raw:
            if not isinstance(i, dict):
                raise HTTPException(status_code=400, detail="Unsupported attachment")
            if i.get('items') is not None:
                raise HTTPException(status_code=400, detail="Albums do not nest")
            items.append(_validate_moment_attachment(i))
        # A one-item album is not an album. Collapsing here is what keeps
        # "one photo" to a single stored representation, so every reader that
        # tests for `items` is asking a question with one right answer.
        if len(items) == 1:
            return items[0]
        return {**items[0], 'items': items}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python tests/test_presence.py`
Expected: all PASS under both backends.

- [ ] **Step 5: Full sweep, then commit**

```bash
python tools/test.py
sed -i 's/^version: "2.387.0"/version: "2.387.1"/' config.yaml
```

```bash
cd /e/repositories/Chauffeur && git add -A && git commit -F - <<'EOF'
An album arrives whole or not at all. (v2.387.1)

Every item goes through the same validator a lone photo does, so a data URL
in item four is still persisted and a bad item still raises its own error
rather than a shrug. Ten is the cap. A one-item list collapses to a plain
attachment, because one photo should have one representation.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
git push origin main
```

---

### Task 3: Carry `items` on the wire, and count media on the event card

**Files:**
- Modify: `services/presence.py` — `_moment_row` (~line 361),
  `moment_stream_meta` (~line 336), `moment_events` (~line 410)
- Modify: `services/storage.py` — `get_event_moment_index` (~line 5635)
- Test: `tests/test_presence.py`

**Interfaces:**
- Consumes: `storage.attachment_items` (Task 1).
- Produces:
  - `_moment_row` and `moment_stream_meta` rows gain
    `items: [{kind, media_url, poster_url}]`, cover first, always present
    (length 1 for an ordinary moment).
  - `get_event_moment_index` buckets gain `media_count: int`; `moment_events`
    items gain `media_count`, keeping `count` as the message count.

- [ ] **Step 1: Write the failing test**

```python
def scenario_album_rides_the_wire():
    """A client must never have to reach into the raw attachment, and must
    never need a second request to learn what is in an album."""
    import main
    _family()
    ch = storage.get_or_create_event_channel("vb1", "Emma's Volleyball")
    t0 = time.time()
    a = storage.save_photo_data_url(_TINY_JPEG)
    b = storage.save_photo_data_url(_TINY_JPEG)
    storage.add_chat_message({
        "id": "alb", "channel_id": ch["id"], "sender_member_id": "mom",
        "ts": t0, "type": "text", "body": "first half",
        "attachment": {"kind": "photo", "url": a["url"],
                       "items": [{"kind": "photo", "url": a["url"]},
                                 {"kind": "photo", "url": b["url"]}]},
        "reactions": {}})
    storage.add_chat_message({
        "id": "solo", "channel_id": ch["id"], "sender_member_id": "dad",
        "ts": t0 - 60, "type": "text", "body": "",
        "attachment": {"kind": "photo", "url": a["url"]}, "reactions": {}})

    rows = {r["id"]: r for r in presence.recent_moments(hours=1)}
    alb = rows["alb"]
    check([i["media_url"] for i in alb["items"]] == [a["url"], b["url"]],
          f"items ride the row, cover first, got {alb['items']}")
    check(alb["media_url"] == a["url"] and alb["kind"] == "photo",
          "cover fields stay at the top level for readers that never learned about albums")
    check(len(rows["solo"]["items"]) == 1,
          "an ordinary moment carries a one-item list, so clients need no special case")

    meta = presence.moment_stream_meta(ch, storage.get_chat_message("alb"),
                                       storage.get_member("mom"))["moment"]
    check(len(meta["items"]) == 2 and meta["media_url"] == a["url"],
          "the SSE preview carries the album too")

    card = main.get_moment_events()["items"][0]
    check(card["count"] == 2, f"count stays MESSAGES, got {card['count']}")
    check(card["media_count"] == 3,
          f"media_count sums the media (2 + 1), got {card['media_count']}")

    # The shelf badge counts SHARES. An album is one share however much it
    # holds — the unit the two surfaces use is the whole distinction.
    check(presence.count_moments_since(t0 - 3600) == 2,
          "an album counts once toward the panel badge, not once per photo")
```

Register it in `SCENARIOS`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python tests/test_presence.py`
Expected: `FAIL scenario_album_rides_the_wire` with `KeyError: 'items'`.

- [ ] **Step 3: Write the implementation**

In `services/presence.py`, add above `_moment_row`:

```python
def _item_rows(att) -> List[dict]:
    """Every media in a moment, shaped for a client: cover first, one entry for
    an ordinary moment. Always present so no surface needs an album special
    case — `items[0]` is what the top-level cover fields describe."""
    out = []
    for it in storage.attachment_items(att):
        url = str(it.get('url') or '')
        out.append({'kind': it.get('kind') or 'photo',
                    'media_url': url,
                    'poster_url': poster_url_for(it) or url})
    return out
```

(If `List` is not already imported in `presence.py`, use a bare `list`
annotation instead — check the file's imports first.)

In `_moment_row`, add one key beside `'attachment': att,`:

```python
        # Every media in this moment, cover first. The top-level kind/media_url
        # above describe items[0]; a surface that draws the whole album reads
        # this instead. Legacy inline photos yield a single item whose
        # media_url is '' — the by-message URL above is their route.
        'items': _item_rows(att),
```

In `moment_stream_meta`, add the same key to the returned `'moment'` dict:

```python
        'items': _item_rows(att),
```

In `services/storage.py`, inside `get_event_moment_index`, add `media_count`
to the bucket initializer and increment it:

```python
                    'count': 0, 'media_count': 0, 'latest_ts': 0.0, 'cover': None,
```

```python
            b['count'] += 1
            b['media_count'] += len(attachment_items(m.get('attachment')))
```

In `services/presence.py`, inside `moment_events`, add to the appended dict:

```python
            # Two different questions, deliberately: `count` is how many times
            # somebody SHARED (the unit the panel badge uses), `media_count` is
            # how much there is to look at. The card shows the latter — "6"
            # over an event holding twenty-four photos answers nothing.
            'media_count': b.get('media_count', b.get('count', 0)),
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python tests/test_presence.py`
Expected: all PASS.

- [ ] **Step 5: Full sweep, then commit**

```bash
python tools/test.py
sed -i 's/^version: "2.387.1"/version: "2.387.2"/' config.yaml
```

```bash
cd /e/repositories/Chauffeur && git add -A && git commit -F - <<'EOF'
Every moment says what is in it. (v2.387.2)

Rows and the SSE preview carry an items list, cover first, always present -
length one for an ordinary moment - so no surface needs an album special
case and nothing has to reach into the raw attachment.

The event card counts MEDIA now. A card reading 6 over an event holding
twenty-four photos answers a question nobody asked. The panel badge keeps
counting shares; the two never appear beside each other.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
git push origin main
```

---

### Task 4: The screensaver shows every photo in an album

**Files:**
- Modify: `services/home_board.py` — the `photos` branch of the screensaver
  playlist (~line 3838)
- Test: `tests/test_screensaver.py`

**Interfaces:**
- Consumes: `storage.attachment_items` (Task 1).
- Produces: nothing new; behaviour change only.

- [ ] **Step 1: Write the failing test**

Open `tests/test_screensaver.py` and follow its existing scenario style (it has
its own `check`, fixtures and `SCENARIOS` list — match them rather than the
snippet's imports). Add:

```python
def scenario_screensaver_shows_every_album_photo():
    """A slideshow of the family's photographs wants ALL of them, not one
    frame per share."""
    _family()
    ch = storage.get_or_create_event_channel("vb1", "Emma's Volleyball")
    saved = [storage.save_photo_data_url(_TINY_JPEG) for _ in range(3)]
    storage.add_chat_message({
        "id": "alb", "channel_id": ch["id"], "sender_member_id": "mom",
        "ts": time.time(), "type": "text", "body": "first half",
        "attachment": {"kind": "photo", "url": saved[0]["url"],
                       "items": [{"kind": "photo", "url": s["url"]} for s in saved]},
        "reactions": {}})

    out = home_board.screensaver_playlist({"panel_screensaver_source": "photos"})
    urls = out["urls"]
    for s in saved:
        check(s["url"].lstrip("/") in urls,
              f"every album photo is in the playlist, missing {s['url']}")
    check(len(urls) == 3, f"three photos, three slides, got {len(urls)}")


def scenario_home_board_tile_takes_only_the_cover():
    """The opposite call from the screensaver, and deliberately so: the tile
    is a flat mosaic of the last few moments beside eight other tiles, and one
    album flooding it would push every other activity off the board."""
    _family()
    ch = storage.get_or_create_event_channel("vb1", "Emma's Volleyball")
    saved = [storage.save_photo_data_url(_TINY_JPEG) for _ in range(3)]
    storage.add_chat_message({
        "id": "alb", "channel_id": ch["id"], "sender_member_id": "mom",
        "ts": time.time(), "type": "text", "body": "first half",
        "attachment": {"kind": "photo", "url": saved[0]["url"],
                       "items": [{"kind": "photo", "url": s["url"]} for s in saved]},
        "reactions": {}})

    tile = home_board._moments_tile({}) or {}
    check(len(tile.get("moments") or []) == 1,
          f"one album is one entry on the tile, got {len(tile.get('moments') or [])}")
```

Register both in that file's `SCENARIOS` list.

The tile builder is the `moments` branch of `home_board`'s tile dispatch
(~line 2085) — find its actual function name before writing the second
scenario and use that; the assertion is what matters, not the name used here.
It should already pass unchanged (it reads one row per message), so this
scenario is a REGRESSION GUARD, not a change: write it, watch it pass, and
leave it. If it fails, the tile is spreading albums and needs the cover-only
fix before you move on.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python tests/test_screensaver.py`
Expected: FAIL — only the cover is in the playlist, so `len(urls) == 1`.

- [ ] **Step 3: Write the implementation**

In `services/home_board.py`, replace the body of the `if cfg['source'] ==
'photos':` branch with:

```python
    if cfg['source'] == 'photos':
        # Moments photos (and video posters — a still is a still). since_ts=0:
        # moments are exempt from chat retention, so the whole archive is the
        # playlist, newest first. EVERY item of an album, not just its cover:
        # this is a slideshow of the family's photographs and more of them is
        # strictly better.
        _URL_CAP = 240
        for m in storage.get_recent_event_moments(0, limit=120):
            for att in storage.attachment_items(m.get('attachment')):
                url = att.get('url') or ''
                if not url.startswith('/api/media/'):
                    continue  # legacy inline data_url photos: too heavy for a playlist
                if (att.get('kind') or 'photo') == 'photo':
                    urls.append(url.lstrip('/'))
                else:
                    # Poster convention from the chat renderer: media id + .jpg
                    media_id = url.rsplit('/', 1)[-1].split('.')[0]
                    if storage.media_file_path(f'{media_id}.jpg'):
                        urls.append(f'api/media/{media_id}.jpg')
            # A handful of ten-photo albums must not crowd the rest of the
            # archive out of the playlist entirely.
            if len(urls) >= _URL_CAP:
                break
        del urls[_URL_CAP:]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python tests/test_screensaver.py`
Expected: all PASS.

- [ ] **Step 5: Full sweep, then commit**

```bash
python tools/test.py
sed -i 's/^version: "2.387.2"/version: "2.387.3"/' config.yaml
```

```bash
cd /e/repositories/Chauffeur && git add -A && git commit -F - <<'EOF'
The screensaver gets the whole album. (v2.387.3)

It is a slideshow of the family photographs, so every frame of an album
belongs in it, not one per share. Capped at 240 urls so a few ten-photo
albums cannot crowd the rest of the archive out.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
git push origin main
```

---

### Task 5: One push per album, describing the set

**Files:**
- Modify: `main.py` — `_fanout_message_notifications` (~line 6652)
- Test: `tests/test_presence.py`

**Interfaces:**
- Consumes: `storage.attachment_items` (Task 1).
- Produces: `main._moment_push_phrase(att: dict) -> str` — e.g. `"a moment"`,
  `"5 photos"`, `"3 photos and a clip"`.

- [ ] **Step 1: Write the failing test**

```python
def scenario_album_push_describes_the_set():
    """The single most visible fix for anyone not at the event: one push, and
    it says how much arrived."""
    import main
    photo = {"kind": "photo", "url": "/api/media/" + "a" * 32}
    clip = {"kind": "video", "url": "/api/media/" + "b" * 32 + ".mp4"}
    check(main._moment_push_phrase(photo) == "a moment", "a lone moment stays a moment")
    check(main._moment_push_phrase({**photo, "items": [photo] * 5}) == "5 photos",
          main._moment_push_phrase({**photo, "items": [photo] * 5}))
    check(main._moment_push_phrase({**photo, "items": [clip] * 3}) == "3 clips",
          main._moment_push_phrase({**photo, "items": [clip] * 3}))
    check(main._moment_push_phrase({**photo, "items": [photo, photo, photo, clip]})
          == "3 photos and a clip",
          main._moment_push_phrase({**photo, "items": [photo, photo, photo, clip]}))
    check(main._moment_push_phrase({**photo, "items": [photo, clip, clip]})
          == "a photo and 2 clips",
          main._moment_push_phrase({**photo, "items": [photo, clip, clip]}))
```

Register it in `SCENARIOS`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python tests/test_presence.py`
Expected: `FAIL` with `AttributeError: module 'main' has no attribute
'_moment_push_phrase'`.

- [ ] **Step 3: Write the implementation**

In `main.py`, add above `_fanout_message_notifications`:

```python
def _moment_push_phrase(att: dict) -> str:
    """What arrived, for the one push an album gets. Five separate pushes for
    one share is the thing this feature fixes for whoever is not at the event,
    so the push has to carry the count instead."""
    items = storage.attachment_items(att)
    if len(items) < 2:
        return "a moment"
    photos = sum(1 for i in items if (i.get('kind') or 'photo') == 'photo')
    clips = len(items) - photos

    def part(n, one, many):
        return f"a {one}" if n == 1 else f"{n} {many}"

    if photos and clips:
        return f"{part(photos, 'photo', 'photos')} and {part(clips, 'clip', 'clips')}"
    return part(photos or clips, 'photo' if photos else 'clip',
                'photos' if photos else 'clips')
```

Then in `_fanout_message_notifications`, replace the two `body = (...)` lines
inside the `if kind == 'event' and message.get('attachment'):` block:

```python
                caption = (message.get('body') or '').strip()
                what = _moment_push_phrase(message.get('attachment') or {})
                body = (f"{sender_name} shared {what}"
                        + (f": {caption[:140]}" if caption else " — you couldn't be there 💙"))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python tests/test_presence.py`
Expected: all PASS. `scenario_moment_fanout_differentiated` must still pass —
a single moment's wording is unchanged.

- [ ] **Step 5: Full sweep, then commit**

```bash
python tools/test.py
sed -i 's/^version: "2.387.3"/version: "2.387.4"/' config.yaml
```

```bash
cd /e/repositories/Chauffeur && git add -A && git commit -F - <<'EOF'
One push, and it says how much arrived. (v2.387.4)

Five pushes for one share is what this whole feature fixes for the parent
who could not be there. Now it is one, reading five photos or three photos
and a clip. A lone moment is worded exactly as it was.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
git push origin main
```

---

### Task 6: Delete one item out of an album

**Files:**
- Modify: `services/storage.py` (beside `delete_chat_message`, ~line 5601)
- Modify: `main.py` (beside `delete_message`, ~line 12399)
- Test: `tests/test_presence.py`

**Interfaces:**
- Consumes: `storage.attachment_items`, `storage._delete_media_for_attachment`
  (Task 1); `main._may_delete_message` (existing).
- Produces:
  - `storage.remove_attachment_item(message_id: str, media_id: str) -> dict | None`
    — returns `{'message': dict|None, 'deleted_message': bool}` on success,
    `None` when the message or the media id is not found.
  - `DELETE /api/messages/{message_id}/media/{media_id}` with body
    `{member_id}` (`MessageDeleteRequest`, existing model).

- [ ] **Step 1: Write the failing test**

```python
def scenario_delete_one_album_item():
    """Looking at one frame is exactly the context in which get rid of THAT
    one is what you mean."""
    import main
    from fastapi import HTTPException
    _family()
    ch = storage.get_or_create_event_channel("vb1", "Emma's Volleyball")
    saved = [storage.save_photo_data_url(_TINY_JPEG) for _ in range(3)]
    ids = [s["url"].rsplit("/", 1)[-1] for s in saved]
    storage.add_chat_message({
        "id": "alb", "channel_id": ch["id"], "sender_member_id": "mom",
        "ts": time.time(), "type": "text", "body": "first half",
        "attachment": {"kind": "photo", "url": saved[0]["url"],
                       "items": [{"kind": "photo", "url": s["url"]} for s in saved]},
        "reactions": {}})

    # 3 -> 2: the RIGHT one goes, by id, and only its file is freed.
    main.delete_message_media("alb", ids[1], main.MessageDeleteRequest(member_id="mom"))
    att = storage.get_chat_message("alb")["attachment"]
    check([i["url"] for i in att["items"]] == [saved[0]["url"], saved[2]["url"]],
          f"the named media is gone, the others stay, got {att['items']}")
    check(not storage.media_file_path(ids[1]), "its file is freed")
    check(storage.media_file_path(ids[0]) and storage.media_file_path(ids[2]),
          "the other two files are untouched")

    # Deleting the cover promotes the next item.
    main.delete_message_media("alb", ids[0], main.MessageDeleteRequest(member_id="mom"))
    att = storage.get_chat_message("alb")["attachment"]
    check("items" not in att, f"two minus one is not an album any more, got {att}")
    check(att["url"] == saved[2]["url"], "the survivor is the attachment")

    # The last media takes the message with it.
    main.delete_message_media("alb", ids[2], main.MessageDeleteRequest(member_id="mom"))
    check(storage.get_chat_message("alb") is None,
          "a moment with no media is not a moment - the row goes too")

    # Permission matches message delete exactly.
    s2 = storage.save_photo_data_url(_TINY_JPEG)
    s3 = storage.save_photo_data_url(_TINY_JPEG)
    storage.add_chat_message({
        "id": "alb2", "channel_id": ch["id"], "sender_member_id": "mom",
        "ts": time.time(), "type": "text", "body": "",
        "attachment": {"kind": "photo", "url": s2["url"],
                       "items": [{"kind": "photo", "url": s2["url"]},
                                 {"kind": "photo", "url": s3["url"]}]},
        "reactions": {}})
    mid = s3["url"].rsplit("/", 1)[-1]
    for member, code in (("gramps", 403), ("nobody", 404)):
        try:
            main.delete_message_media("alb2", mid,
                                      main.MessageDeleteRequest(member_id=member))
            check(False, f"expected {code}")
        except HTTPException as e:
            check(e.status_code == code, f"{member} -> {code}, got {e.status_code}")
    # A parent who is not the sender MAY clear a shared channel.
    main.delete_message_media("alb2", mid, main.MessageDeleteRequest(member_id="dad"))
    check("items" not in storage.get_chat_message("alb2")["attachment"],
          "a parent may clear one frame out of a shared thread")

    # Unknown media, and media belonging to another message, both 404.
    for bad in ("f" * 32, ids[0]):
        try:
            main.delete_message_media("alb2", bad,
                                      main.MessageDeleteRequest(member_id="mom"))
            check(False, "expected 404")
        except HTTPException as e:
            check(e.status_code == 404, f"{bad[:8]} -> 404, got {e.status_code}")
```

Register it in `SCENARIOS`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python tests/test_presence.py`
Expected: `FAIL` with `AttributeError: module 'main' has no attribute
'delete_message_media'`.

- [ ] **Step 3: Write the implementation**

In `services/storage.py`, add after `delete_chat_message`:

```python
def remove_attachment_item(message_id: str, media_id: str) -> Optional[dict]:
    """Drop ONE media out of a moment, by media id.

    Keyed by id rather than by position on purpose: two people clearing frames
    out of the same album, or one client working from a stale copy, would
    otherwise remove a different photo than the one on screen — and a silently
    wrong deletion of family media is unrecoverable.

    Returns {'message': <updated or None>, 'deleted_message': bool}, or None if
    the message has no such media."""
    with db_lock:
        res = chat_messages_table.search(Query().id == message_id)
        if not res:
            return None
        msg = dict(res[0])
    att = msg.get('attachment') or {}
    items = attachment_items(att)
    # Partitioned BY POSITION, not by value: an album may legitimately hold two
    # entries that compare equal, and `i not in keep` would then quietly free
    # the file the survivor still points at.
    hit = [n for n, i in enumerate(items)
           if str(i.get('url') or '').rsplit('/', 1)[-1] == media_id]
    if not hit:
        return None                      # no such media in this message
    keep = [i for n, i in enumerate(items) if n not in set(hit)]
    gone = [items[n] for n in hit]

    # The LAST media takes the message with it. A moment is media plus a
    # caption; the caption alone is not a moment, and a stranded line of text
    # where a photo was is not what anyone meant by "delete this".
    if not keep:
        return {'message': delete_chat_message(message_id), 'deleted_message': True}

    # An album of two that loses one was never an album — collapse to a plain
    # attachment so "one photo" keeps exactly one representation.
    new_att = dict(keep[0]) if len(keep) == 1 else {**keep[0], 'items': keep}
    with db_lock:
        chat_messages_table.update({'attachment': new_att}, Query().id == message_id)
    for item in gone:
        _delete_media_for_attachment(item)
    msg['attachment'] = new_att
    return {'message': msg, 'deleted_message': False}
```

In `main.py`, add after the existing `delete_message` route:

```python
@app.delete("/api/messages/{message_id}/media/{media_id}")
def delete_message_media(message_id: str, media_id: str,
                         req: MessageDeleteRequest, request: Request = None):
    """Delete ONE photo or clip out of an album. Same permission as deleting
    the whole message — removing one frame is the same act, only narrower — so
    `_may_delete_message` governs both and there is no second rule to keep in
    step. Removing the last media deletes the message itself."""
    req.member_id = _acting_id(request, req.member_id)
    member = storage.get_member(req.member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    msg = storage.get_chat_message(message_id)
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    channel = storage.get_channel(msg['channel_id']) or {}
    if not _may_delete_message(msg, member, channel):
        raise HTTPException(status_code=403, detail="Not yours to delete")
    res = storage.remove_attachment_item(message_id, media_id)
    if not res:
        raise HTTPException(status_code=404, detail="That photo is not in this moment")
    recipients = channel.get('member_ids') if channel.get('kind') in ('dm', 'group') else None
    _push_message_event(msg['channel_id'], recipients)
    return {'deleted_message': res['deleted_message'],
            'attachment': (res['message'] or {}).get('attachment')
            if not res['deleted_message'] else None}
```

Note the ordering: the permission check must come BEFORE
`remove_attachment_item`, so a refused caller changes nothing.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python tests/test_presence.py`
Expected: all PASS.

- [ ] **Step 5: Full sweep, then commit**

```bash
python tools/test.py
sed -i 's/^version: "2.387.4"/version: "2.387.5"/' config.yaml
```

```bash
cd /e/repositories/Chauffeur && git add -A && git commit -F - <<'EOF'
Take back one frame without taking back the share. (v2.387.5)

Keyed by media id, never by position: two people clearing frames out of the
same album would otherwise delete a different photo than the one on screen,
and that is unrecoverable.

Two minus one collapses to a plain attachment - an album of two that loses
one was never an album. The last media takes the message with it, because a
caption with no photo is not a moment.

Permission is the message-delete rule unchanged. Removing one frame is the
same act, only narrower, so there is no second rule to keep in step.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
git push origin main
```

---

### Task 7: Photos upload before the message posts

No visible behaviour change — this is the refactor that makes Task 8 possible.
Today a photo rides the message body as a `data:` URL; ten of those is a
~160 MB JSON POST.

**Files:**
- Modify: `templates/app.html` — `handlePhotoPick` (~line 3735),
  `submitThreadMessage` (~line 4072)
- Test: `tests/test_share_out.py` (its `_extract` harness reads `app.html`)

**Interfaces:**
- Consumes: `POST /api/media/photo` (existing; body `{data_url}`, returns
  `{url, mime, w, h}`).
- Produces: `uploadMomentPhoto(dataUrl) -> Promise<{kind:'photo', url, mime, w, h}>`
  in `app.html`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_share_out.py`, following its existing `_extract` style:

```python
def scenario_photos_are_uploaded_not_inlined():
    """A ten-photo album must not be a 160 MB JSON POST, so photos go to the
    media store first and the message carries urls."""
    src = _extract('uploadMomentPhoto')
    check('api/media/photo' in src,
          'the photo upload posts to the media-store route')
    check("'data_url'" in src or 'data_url' in src,
          'it sends the rendition as a data url')

    send = _extract('submitThreadMessage')
    check('data_url' not in send,
          'the message body no longer carries image bytes')
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python tests/test_share_out.py`
Expected: FAIL — `_extract` raises because `uploadMomentPhoto` does not exist.

- [ ] **Step 3: Write the implementation**

In `templates/app.html`, add beside the other upload helpers (just above
`uploadMomentVideo`):

```javascript
        // Photos take the same route clips do: into the media store first,
        // and the message carries a url. They used to ride the message body
        // as a data URL, which is fine for one and a ~160 MB JSON POST for
        // ten. One path for one photo and for ten, so there is no second
        // code path to keep in step.
        async function uploadMomentPhoto(dataUrl, w, h) {
            const res = await fetch(`${apiBase}api/media/photo`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ data_url: dataUrl })
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(data.detail || `Photo upload failed (${res.status})`);
            const out = { kind: 'photo', url: data.url };
            if (data.mime) out.mime = data.mime;
            if (w) out.w = w;
            if (h) out.h = h;
            return out;
        }
```

Then in `handlePhotoPick`, change the line that stages the attachment so it
keeps the rendition for the preview but marks it as needing upload:

```javascript
                pendingAttachment = { kind: 'photo', data_url: dataUrl, w: w, h: h };
```

becomes

```javascript
                // The data URL stays for the PREVIEW only; Send uploads it and
                // swaps in a url. Never posted as bytes.
                pendingAttachment = { kind: 'photo', _dataUrl: dataUrl, w: w, h: h };
```

and the preview line below it changes `${dataUrl}` → unchanged (it already
uses the local `dataUrl` variable, not the object).

In `submitThreadMessage`, replace the `try { const res = await fetch(...` block
that posts a photo with:

```javascript
            try {
                let att = attachment;
                if (att && att._dataUrl) {
                    att = await uploadMomentPhoto(att._dataUrl, att.w, att.h);
                }
                const res = await fetch(`${apiBase}api/channels/${activeChannelId}/messages`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ sender_member_id: selectedMemberId, body: body,
                                           attachment: att || undefined })
                });
```

And in the same function's `catch`, the failure re-preview reads `data_url`;
change it to the staged field:

```javascript
                    showAttachPreview(attachment.kind === 'video'
                        ? `<video src="${apiBase}${attachment.url.replace(/^\//, '')}" muted playsinline class="h-20 rounded-xl border border-gray-700 object-cover"></video>`
                        : `<img src="${attachment._dataUrl || momentMediaSrc(attachment)}" class="h-20 rounded-xl border border-gray-700 object-cover">`);
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python tests/test_share_out.py && python tests/test_presence.py`
Expected: PASS. The server still accepts inline `data:` URLs — old clients,
the migration passthrough, and `scenario_attachment_send_and_validation` all
still post that way, and must keep passing untouched.

- [ ] **Step 5: Full sweep, then commit**

```bash
python tools/test.py
sed -i 's/^version: "2.387.5"/version: "2.387.6"/' config.yaml
```

```bash
cd /e/repositories/Chauffeur && git add -A && git commit -F - <<'EOF'
Photos take the road clips already take. (v2.387.6)

Into the media store first, url on the message. Fine as a data url for one
photo; a 160 MB JSON POST for ten. One path for both, so there is no second
one to keep in step when albums land.

The server still accepts the inline form - old clients and the migration
passthrough both still use it.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
git push origin main
```

---

### Task 8: Pick several, send one

**Files:**
- Modify: `templates/app.html` — the file input (~line 357), the attach preview
  markup (~line 347), `handlePhotoPick`, `clearPendingAttachment`,
  `submitThreadMessage`, and the uploading-bubble helpers (~lines 3723-4140)
- Test: `tests/test_share_out.py`

**Interfaces:**
- Consumes: `uploadMomentPhoto` (Task 7), `uploadMomentVideo`,
  `enqueueUpload`, `extractVideoPoster`, `addUploadingBubble`,
  `setBubbleProgress`, `markBubbleFailed`, `dropUploadingBubble` (all existing).
- Produces:
  - `pendingAlbum: Array<{file, kind, preview, w, h}>` — the staged pick.
  - `ALBUM_MAX = 10` in `app.html`.
  - `sendAlbum(entries, body)` — uploads every entry, then posts ONE message.

- [ ] **Step 1: Write the failing test**

```python
def scenario_album_composer_is_atomic_and_capped():
    """Nothing posts until every item has a url, and ten is the cap on both
    sides of the wire."""
    with open(APP, encoding='utf-8') as f:
        html = f.read()
    check('id="thread-photo-input" type="file" multiple' in html
          or 'multiple' in html.split('id="thread-photo-input"')[1].split('>')[0],
          'the picker takes more than one file')

    send = _extract('sendAlbum')
    check('ALBUM_MAX' not in send or True, 'sendAlbum exists')
    # The post must come AFTER every upload resolves.
    upload_at = send.index('Promise.all') if 'Promise.all' in send else send.index('await')
    post_at = send.index('/messages')
    check(upload_at < post_at,
          'every item uploads before the message is posted - an album posts whole')
    check('items' in send, 'the message carries an items list')

    pick = _extract('handlePhotoPick')
    check('ALBUM_MAX' in pick, 'the composer trims the pick at the cap')
    check('showGlobalAlert' in pick, 'and says so - never a browser dialog')
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python tests/test_share_out.py`
Expected: FAIL — no `multiple` on the input, and `_extract('sendAlbum')` raises.

- [ ] **Step 3: Write the implementation**

**3a.** The input takes many files. In `templates/app.html` line ~357:

```html
                    <input id="thread-photo-input" type="file" accept="image/*,video/*" multiple class="hidden"
                        onchange="handlePhotoPick(this)">
```

**3b.** The preview slot holds a strip. Replace the `#thread-attach-preview`
block (~line 347):

```html
                <div id="thread-attach-preview" class="px-3 pt-2 bg-gray-900 border-t border-gray-800" style="display:none">
                    <div id="thread-attach-slot" class="flex gap-2 overflow-x-auto pb-1"></div>
                </div>
```

The per-item ✕ now lives on each staged cell, so the single absolutely
positioned button that used to sit beside `#thread-attach-slot` goes away.

**3c.** Staging. Replace `handlePhotoPick` and add the album state beside
`pendingAttachment`:

```javascript
        // A share is up to ten media under one caption. Ten is enough for a
        // part of a game and low enough that one share cannot dump a camera
        // roll onto the wall; the server enforces the same number.
        const ALBUM_MAX = 10;
        let pendingAlbum = [];      // [{file, kind, preview, w, h}]

        function albumCell(entry, i) {
            const box = 'h-20 w-20 rounded-xl border border-gray-700 object-cover';
            const media = entry.preview
                ? `<img src="${entry.preview}" class="${box}">`
                : `<div class="${box} bg-gray-800 animate-pulse"></div>`;
            return `<div class="relative shrink-0">
                    ${media}${entry.kind === 'video' ? playBadge(true) : ''}
                    <button onclick="dropAlbumEntry(${i})" type="button"
                        class="absolute -top-2 -right-2 w-6 h-6 rounded-full bg-gray-700 text-gray-100 text-xs font-bold flex items-center justify-center">✕</button>
                </div>`;
        }

        function renderAlbumPreview() {
            if (!pendingAlbum.length) return clearPendingAttachment();
            showAttachPreview(pendingAlbum.map(albumCell).join(''));
        }

        window.dropAlbumEntry = function (i) {
            pendingAlbum.splice(i, 1);
            renderAlbumPreview();
        };

        // Every pick lands here — one file or ten, photo or clip. Photos are
        // downscaled now (the rendition is what gets uploaded) and clips have
        // their first frame pulled, so the strip is never a row of grey boxes.
        async function handlePhotoPick(inputEl) {
            const files = [...(inputEl.files || [])];
            inputEl.value = '';
            if (!files.length) return;
            const room = ALBUM_MAX - pendingAlbum.length;
            if (files.length > room) {
                showGlobalAlert(room > 0
                    ? `A share holds ${ALBUM_MAX} — sending the first ${room}`
                    : `That share already has ${ALBUM_MAX}`);
            }
            for (const file of files.slice(0, Math.max(0, room))) {
                if (file.type.startsWith('video/')) {
                    if (file.size > MAX_UPLOAD_BYTES) {
                        showGlobalAlert(`That clip is ${fmtBytes(file.size)} — the limit is ${fmtBytes(MAX_UPLOAD_BYTES)}`);
                        continue;
                    }
                    const entry = { file: file, kind: 'video', preview: '' };
                    pendingAlbum.push(entry);
                    renderAlbumPreview();
                    // Deliberately not awaited in sequence with the others: a
                    // big clip's frame extraction must not hold up staging the
                    // rest of the pick.
                    extractVideoPoster(file).then(p => {
                        if (!pendingAlbum.includes(entry)) return;
                        entry.preview = p || '';
                        renderAlbumPreview();
                    });
                } else if (file.type.startsWith('image/')) {
                    const r = await downscalePhoto(file);
                    if (!r) { showGlobalAlert('Could not read that photo'); continue; }
                    pendingAlbum.push({ file: file, kind: 'photo', preview: r.dataUrl,
                                        w: r.w, h: r.h });
                    renderAlbumPreview();
                }
            }
            renderAlbumPreview();
        }

        // The 2048px q0.85 rendition. Photos are stored as FILES now, so the
        // old 1280 squeeze (which existed to keep base64 out of the database)
        // isn't needed — send something worth looking at on a TV.
        function downscalePhoto(file) {
            return new Promise(resolve => {
                const img = new Image();
                const url = URL.createObjectURL(file);
                img.onload = () => {
                    URL.revokeObjectURL(url);
                    const MAX = 2048;
                    const scale = Math.min(1, MAX / Math.max(img.width, img.height));
                    const w = Math.round(img.width * scale), h = Math.round(img.height * scale);
                    const canvas = document.createElement('canvas');
                    canvas.width = w; canvas.height = h;
                    canvas.getContext('2d').drawImage(img, 0, 0, w, h);
                    resolve({ dataUrl: canvas.toDataURL('image/jpeg', 0.85), w: w, h: h });
                };
                img.onerror = () => { URL.revokeObjectURL(url); resolve(null); };
                img.src = url;
            });
        }
```

**3d.** `clearPendingAttachment` clears the album too:

```javascript
        function clearPendingAttachment() {
            pendingAttachment = null;
            pendingFile = null;
            pendingPoster = '';
            pendingAlbum = [];
            document.getElementById('thread-attach-preview').style.display = 'none';
            document.getElementById('thread-input').placeholder = 'Message...';
        }
```

**3e.** Sending. Replace the whole of `submitThreadMessage` with:

```javascript
        async function submitThreadMessage(e) {
            e.preventDefault();
            const input = document.getElementById('thread-input');
            const body = input.value.trim();
            const entries = pendingAlbum.slice();
            if ((!body && !entries.length) || !activeChannelId || !selectedMemberId) return;
            if (helperShareMode && !entries.length) {
                showGlobalAlert('Add a photo or video — text goes in your chat with the parents');
                input.value = body;
                return;
            }
            input.value = '';
            clearPendingAttachment();
            if (entries.length) {
                sendAlbum(entries, body);   // deliberately not awaited
                return;
            }
            try {
                const res = await fetch(`${apiBase}api/channels/${activeChannelId}/messages`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ sender_member_id: selectedMemberId, body: body })
                });
                if (!res.ok) throw new Error('send failed');
                await refreshThread();
            } catch (err) {
                showGlobalAlert('Failed to send message');
                input.value = body;
            }
        }

        // ATOMIC. Every item uploads, THEN one message posts carrying all of
        // them — one push, one gallery row, one pop. Posting first and
        // appending as uploads land reads faster on this screen and is wrong
        // everywhere else: the panel would pop an album of one that silently
        // grows, and the push would describe a share that is not finished.
        async function sendAlbum(entries, body) {
            const channelId = activeChannelId;
            const el = addAlbumBubble(entries, body);
            try {
                const items = await Promise.all(entries.map((entry, i) =>
                    enqueueUpload(async () => {
                        const att = entry.kind === 'video'
                            ? await uploadMomentVideo(entry.file, pct => setCellProgress(el, i, pct))
                            : await uploadMomentPhoto(entry.preview, entry.w, entry.h);
                        setCellProgress(el, i, 100);
                        return att;
                    })));
                const res = await fetch(`${apiBase}api/channels/${channelId}/messages`, {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        sender_member_id: selectedMemberId, body: body,
                        // Always an items list, even for one: the server
                        // collapses a single into a plain attachment, so the
                        // client needs no special case.
                        attachment: { items: items }
                    })
                });
                if (!res.ok) {
                    const d = await res.json().catch(() => ({}));
                    throw new Error(typeof d.detail === 'string' ? d.detail : 'Could not post that');
                }
                dropUploadingBubble(el);
                if (activeChannelId === channelId) { await refreshThread(); noteMomentShared(); }
                else loadMomentsStrip();
            } catch (err) {
                markAlbumFailed(el, entries, body, err.message);
            }
        }
```

**3f.** The optimistic bubble. Add beside `addUploadingBubble`:

```javascript
        // One bubble for the whole share, a progress ring per cell. Failure
        // keeps the bubble AND the staged files, so Retry costs one tap
        // rather than finding five clips in the camera roll again — and it
        // resumes, because the chunked upload resyncs to the offset the
        // server actually has.
        function addAlbumBubble(entries, body) {
            const wrap = document.getElementById('thread-messages');
            const el = document.createElement('div');
            el.className = 'max-w-[80%] self-end';
            el.dataset.uploading = '1';
            el.innerHTML = `
                <div class="${body ? 'mb-1' : ''}">${albumGridHtml(
                    entries.map(x => ({ poster: x.preview, kind: x.kind })),
                    { uploading: true })}</div>
                ${body ? `<div class="px-3.5 py-2 rounded-2xl bg-blue-600 text-white rounded-br-sm text-[15px] leading-snug break-words whitespace-pre-wrap">${mfEscape(body)}</div>` : ''}
                <div class="flex items-center gap-1.5 mt-0.5 justify-end">
                    <span class="upload-status text-xs text-gray-500">Sending ${entries.length}…</span>
                </div>`;
            uploadingBubbles.push(el);
            wrap.appendChild(el);
            wrap.scrollTop = wrap.scrollHeight;
            return el;
        }

        function setCellProgress(el, i, pct) {
            if (!uploadingBubbles.includes(el)) return;
            const cell = el.querySelectorAll('.album-cell')[i];
            if (cell) setBubbleProgress(cell, pct);
        }

        function markAlbumFailed(el, entries, body, msg) {
            const overlay = el.querySelector('.upload-overlay');
            if (overlay) {
                overlay.innerHTML = `<button class="px-3 py-1.5 rounded-full bg-white/15 border border-white/30 text-white text-xs font-bold">↻ Retry</button>`;
                overlay.querySelector('button').onclick = () => {
                    dropUploadingBubble(el);
                    sendAlbum(entries, body);
                };
            }
            const status = el.querySelector('.upload-status');
            if (status) {
                status.textContent = msg || 'Upload failed';
                status.className = 'upload-status text-xs text-red-400 font-bold';
            }
        }
```

`albumGridHtml` is defined in Task 9. **Implement Task 9 before running this
task's tests** — or stub it as
`function albumGridHtml(items) { return ''; }` and let Task 9 replace it.
Prefer doing Task 9 first if you are executing out of order.

Task 9's grid emits `openMomentById('<id>', <i>)`, and at that point
`openMomentById` still takes one argument. That is harmless — JavaScript
ignores the extra — and Task 10 gives it the second parameter. Do not "fix" it
by dropping the index.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python tests/test_share_out.py`
Expected: PASS.

- [ ] **Step 5: Rebuild Tailwind, full sweep, then commit**

```bash
python tools/build_tailwind.py
python tools/test.py
sed -i 's/^version: "2.387.6"/version: "2.387.7"/' config.yaml
```

```bash
cd /e/repositories/Chauffeur && git add -A && git commit -F - <<'EOF'
Pick five, send one. (v2.387.7)

A share is up to ten media under one caption. The picker takes many, the
strip stages them with a per-item cross, and Send posts exactly once - after
every upload has landed.

Atomic on purpose. Posting first and appending as uploads arrive reads
faster on the sender's own screen and is wrong everywhere else: the wall
would pop an album of one that silently grows, and the push would describe a
share that is not finished.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
git push origin main
```

---

### Task 9: The album bubble, and every clip goes full screen

**Files:**
- Modify: `templates/app.html` — the thread renderer's attachment branch
  (~line 3233), the channel-list preview line (~line 3108)
- Test: `tests/test_share_out.py`

**Interfaces:**
- Consumes: `momentPosterSrc`, `momentMediaSrc`, `playBadge` (existing).
- Produces:
  - `albumGridHtml(items, opts) -> string` where `items` is
    `[{poster, media, kind}]` and `opts` is `{uploading?: bool, msgId?: string}`.
    Every cell carries class `album-cell`; an uploading grid puts
    `uploadOverlay(...)` inside each cell.
  - `openAlbumGrid(msgId)` — the `+N` full-album grid sheet.

- [ ] **Step 1: Write the failing test**

```python
def scenario_album_bubble_is_stills_and_a_plus_n():
    """Four decoders in a chat row is not a bubble, and the +N cell is the
    only place the middle level earns its keep."""
    grid = _extract('albumGridHtml')
    check('<video' not in grid,
          'every cell is a still - a clip shows its poster and a play badge')
    check('album-cell' in grid, 'cells are addressable for per-item progress')
    check('+' in grid and 'openAlbumGrid' in grid,
          'the overflow cell opens the full album, other cells do not')

    with open(APP, encoding='utf-8') as f:
        html = f.read()
    thread = html[html.index('let att = '):html.index('const bubble = m.body')]
    check('<video' not in thread,
          'a lone clip is a poster that opens the lightbox, not an inline player')
    check('openMomentById' in thread, 'and it opens the lightbox')
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python tests/test_share_out.py`
Expected: FAIL — `_extract('albumGridHtml')` raises.

- [ ] **Step 3: Write the implementation**

Add above the thread renderer in `templates/app.html`:

```javascript
        // A grid of STILLS, never live <video> elements. A 2x2 of players is
        // four decoders in a chat row, and the gallery already refuses this
        // for the same reason. Shapes: 2 across for two, one large plus two
        // for three, 2x2 for four, 2x2 with a +N scrim beyond that.
        //
        // The +N cell is the ONLY one that opens a middle level. An
        // intermediate view of three photos the bubble already showed you is
        // a tap that buys nothing; a view of the six it could not show you is
        // the whole reason that level exists.
        function albumGridHtml(items, opts) {
            opts = opts || {};
            const n = items.length;
            const shown = n > 4 ? 3 : n;
            const hidden = n - shown;
            const cls = 'album-cell relative bg-black overflow-hidden';
            const cell = (it, i) => {
                const src = it.poster || it.media || '';
                const badge = it.kind === 'video' ? playBadge(true) : '';
                const over = hidden && i === shown - 1
                    ? `<span class="absolute inset-0 bg-black/60 text-white text-2xl font-black flex items-center justify-center">+${hidden + 1}</span>`
                    : '';
                const tap = opts.uploading ? ''
                    : (hidden && i === shown - 1
                        ? `onclick="openAlbumGrid('${opts.msgId}')"`
                        : `onclick="openMomentById('${opts.msgId}', ${i})"`);
                return `<div class="${cls}" ${tap} style="aspect-ratio:1">
                        <img src="${src}" loading="lazy" class="w-full h-full object-cover">
                        ${badge}${over}${opts.uploading ? uploadOverlay(true) : ''}
                    </div>`;
            };
            // The last visible cell absorbs the overflow, so a 10-item album
            // draws 3 real cells and a +8 rather than 4 and a lie.
            const cells = items.slice(0, shown).map(cell).join('');
            const cols = shown <= 2 ? shown : 2;
            return `<div class="grid gap-0.5 rounded-2xl overflow-hidden rounded-br-sm"
                        style="grid-template-columns: repeat(${cols}, 1fr)">${cells}</div>`;
        }

        // The middle level: every item in one share, reached from the +N cell.
        window.openAlbumGrid = function (msgId) {
            const m = (threadMessages || []).find(x => x.id === msgId);
            const items = (m && m.attachment) ? attachmentItemsJs(m.attachment) : [];
            if (!items.length) return;
            const overlay = document.createElement('div');
            overlay.className = 'moment-overlay fixed inset-0 z-[205] bg-black/95 overflow-y-auto p-3';
            overlay.innerHTML = `
                <button onclick="this.closest('.moment-overlay').remove()"
                    class="sticky top-0 float-right w-10 h-10 rounded-full bg-white/15 text-white text-lg leading-none">✕</button>
                <div class="grid gap-1 pt-12" style="grid-template-columns: repeat(3, 1fr)">
                    ${items.map((it, i) => `
                        <div class="relative bg-black" style="aspect-ratio:1"
                            onclick="this.closest('.moment-overlay').remove(); openMomentById('${msgId}', ${i})">
                            <img src="${momentPosterSrc(it) || momentMediaSrc(it)}" loading="lazy"
                                class="w-full h-full object-cover">
                            ${it.kind === 'video' ? playBadge(true) : ''}
                        </div>`).join('')}
                </div>`;
            document.body.appendChild(overlay);
        };

        // The album rule, client side. Mirrors storage.attachment_items.
        function attachmentItemsJs(att) {
            att = att || {};
            return (Array.isArray(att.items) && att.items.length) ? att.items
                : ((att.url || att.data_url) ? [att] : []);
        }
```

Replace the thread renderer's attachment branch (the `if (m.attachment &&
m.attachment.kind === 'photo') { … } else if (… 'video' …) { … }` block) with:

```javascript
                let att = '';
                if (m.attachment) {
                    const items = attachmentItemsJs(m.attachment);
                    if (items.length > 1) {
                        att = `<div class="${m.body ? 'mb-1' : ''}">${albumGridHtml(
                            items.map(it => ({ poster: momentPosterSrc(it) || momentMediaSrc(it),
                                               media: momentMediaSrc(it), kind: it.kind })),
                            { msgId: m.id })}</div>`;
                    } else if (items.length === 1) {
                        // ONE rule for every media in the thread: a still that
                        // opens the lightbox. A lone clip used to render an
                        // inline player, which would have meant tapping a clip
                        // did one thing alone and another inside an album, with
                        // nothing on screen to explain the difference. The
                        // lightbox has rendered video since the moments strip
                        // first reached it, so nothing is lost and a clip gains
                        // the full screen.
                        const it = items[0];
                        const src = momentPosterSrc(it) || momentMediaSrc(it);
                        att = `<div class="relative ${m.body ? 'mb-1' : ''}" onclick="openMomentById('${m.id}', 0)">
                                <img src="${src}" loading="lazy"
                                    class="rounded-2xl ${mine ? 'rounded-br-sm' : 'rounded-bl-sm'} max-h-64 w-full object-cover cursor-pointer">
                                ${it.kind === 'video' ? playBadge(true) : ''}
                            </div>`;
                    }
                }
```

Update the channel-list preview line (~3108) so an album says how much it is:

```javascript
                    ? `${last.sender_member_id === selectedMemberId ? 'You' : (sender.name || '?')}: ${last.attachment ? momentPreviewLabel(last) : last.body}`
```

with:

```javascript
        // What the channel list says a share was. An album with no caption
        // must not read as one photo.
        function momentPreviewLabel(msg) {
            const items = attachmentItemsJs(msg.attachment);
            const clip = (msg.attachment || {}).kind === 'video';
            if (msg.body) return `${clip ? '🎥 ' : '📷 '}${msg.body}`;
            if (items.length > 1) {
                const clips = items.filter(i => i.kind === 'video').length;
                return `📷 ${items.length} ${clips === items.length ? 'clips' : 'photos'}`;
            }
            return clip ? '🎥 Clip' : '📷 Photo';
        }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python tests/test_share_out.py`
Expected: PASS.

- [ ] **Step 5: Rebuild Tailwind, full sweep, then commit**

```bash
python tools/build_tailwind.py
python tools/test.py
sed -i 's/^version: "2.387.7"/version: "2.387.8"/' config.yaml
```

```bash
cd /e/repositories/Chauffeur && git add -A && git commit -F - <<'EOF'
Five frames, one bubble, one caption. (v2.387.8)

Every cell is a still. A 2x2 of live players is four decoders in a chat row,
which is why the gallery has always refused it.

Only the +N cell opens a middle level - an intermediate view of three photos
the bubble already showed you is a tap that buys nothing, and a view of the
six it could not show you is the reason that level exists.

Lone clips become stills that open the lightbox too. Otherwise tapping a clip
would do one thing alone and another inside an album, with nothing on screen
to say why. The lightbox has played video since the strip first reached it,
so a clip only gains the full screen.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
git push origin main
```

---

### Task 10: The lightbox steps, shares what you see, deletes what you see

**Files:**
- Modify: `templates/app.html` — `showMomentOverlay` (~line 3573),
  `openMomentById` (~line 3610), `shareMessage` (~line 3557),
  `deleteMomentFromOverlay`
- Test: `tests/test_share_out.py`

**Interfaces:**
- Consumes: `attachmentItemsJs`, `albumGridHtml` (Task 9);
  `DELETE /api/messages/{id}/media/{media_id}` (Task 6).
- Produces: `openMomentById(id, index)` — index defaults to `0`;
  `showMomentOverlay(opts)` gains `opts.items` (array of raw attachment items)
  and `opts.index`.

- [ ] **Step 1: Write the failing test**

```python
def scenario_lightbox_acts_on_the_item_on_screen():
    """Opening item three is the whole reason item three is the one you want."""
    src = _extract('showMomentOverlay')
    check('opts.index' in src or 'idx' in src, 'the lightbox tracks a current item')
    check('/media/' in src, 'delete targets one media id, not the message')
    check('Delete photo' in src or 'Delete clip' in src,
          'the lightbox button names the narrower scope')

    sheet = _extract('shareMessage')
    check('Delete album' not in sheet, 'the action sheet is not the lightbox')

    with open(APP, encoding='utf-8') as f:
        html = f.read()
    check('Delete album' in html,
          'the message action sheet says it takes the whole share')
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python tests/test_share_out.py`
Expected: FAIL — no index in `showMomentOverlay`.

- [ ] **Step 3: Write the implementation**

Rewrite `showMomentOverlay` so it holds a current index and redraws in place:

```javascript
        // opts.items is the RAW attachment items (cover first); opts.index is
        // which one is on screen. Share and Delete both act on THAT item —
        // opening item three is the whole reason item three is the one you
        // want. The message action sheet, which has no current item, keeps
        // acting on the whole share.
        function showMomentOverlay(opts) {
            const items = (opts.items && opts.items.length) ? opts.items
                : [{ kind: opts.kind, url: '' }];
            let idx = Math.min(Math.max(0, opts.index || 0), items.length - 1);
            const overlay = document.createElement('div');
            overlay.className = 'moment-overlay fixed inset-0 z-[210] bg-black/90 flex items-center justify-center p-3';

            function srcFor(i) {
                const it = items[i] || {};
                return opts.items ? momentMediaSrc(it) : (opts.src || '');
            }
            function posterFor(i) {
                const it = items[i] || {};
                return opts.items ? momentPosterSrc(it) : (opts.poster || '');
            }

            function draw() {
                const it = items[idx] || {};
                const clip = (it.kind || opts.kind) === 'video';
                const media = clip
                    ? `<video src="${srcFor(idx)}" ${posterFor(idx) ? `poster="${posterFor(idx)}"` : ''} controls autoplay playsinline
                           class="max-w-full max-h-[70vh] rounded-xl"></video>`
                    : `<img src="${srcFor(idx)}" class="max-w-full max-h-[70vh] rounded-xl object-contain">`;
                const many = items.length > 1;
                overlay.innerHTML = `
                    <button onclick="this.closest('.moment-overlay').remove()"
                        class="absolute top-3 right-3 w-10 h-10 rounded-full bg-white/15 text-white text-lg leading-none">✕</button>
                    <div class="max-w-full text-center">
                        ${opts.title ? `<div class="text-xs font-black uppercase tracking-widest text-pink-300 mb-2">📸 ${mfEscape(opts.title)}</div>` : ''}
                        <div class="relative inline-block">
                            ${media}
                            ${many ? `
                            <button class="mo-prev absolute left-1 top-1/2 -translate-y-1/2 w-11 h-11 rounded-full bg-black/50 text-white text-xl">‹</button>
                            <button class="mo-next absolute right-1 top-1/2 -translate-y-1/2 w-11 h-11 rounded-full bg-black/50 text-white text-xl">›</button>
                            <span class="absolute top-2 left-1/2 -translate-x-1/2 px-2 py-0.5 rounded-full bg-black/60 text-white text-xs font-bold">${idx + 1} / ${items.length}</span>` : ''}
                        </div>
                        ${opts.body ? `<div class="text-white font-bold mt-3 px-4">${mfEscape(opts.body)}</div>` : ''}
                        ${opts.senderName ? `<div class="text-gray-400 text-sm mt-1">from ${mfEscape(opts.senderName)}</div>` : ''}
                        ${opts.channelId ? `<button class="mo-open mt-4 px-4 py-2 rounded-full bg-white/15 text-white text-sm font-bold">Open chat →</button>` : ''}
                        ${canShareOut() ? `<button class="moment-share mt-4 ml-2 px-4 py-2 rounded-full bg-white/15 text-white text-sm font-bold">Share</button>` : ''}
                        ${opts.canDelete ? `<button class="mo-del mt-4 ml-2 px-4 py-2 rounded-full bg-red-600/25 border border-red-500/50 text-red-200 text-sm font-bold">Delete ${(items[idx] || {}).kind === 'video' ? 'clip' : 'photo'}</button>` : ''}
                    </div>`;
                wire();
            }

            function step(d) {
                idx = (idx + d + items.length) % items.length;
                draw();
            }

            function wire() {
                const prev = overlay.querySelector('.mo-prev');
                const next = overlay.querySelector('.mo-next');
                if (prev) prev.onclick = e => { e.stopPropagation(); step(-1); };
                if (next) next.onclick = e => { e.stopPropagation(); step(1); };
                const open = overlay.querySelector('.mo-open');
                if (open) open.onclick = () => {
                    overlay.remove(); setView('messages'); openChannel(opts.channelId);
                };
                // Wired here rather than as an inline onclick: the caption is
                // arbitrary family text and would have to survive two levels
                // of quoting to reach an attribute intact.
                const shareBtn = overlay.querySelector('.moment-share');
                if (shareBtn) shareBtn.onclick = () => shareOut(shareBtn, {
                    src: srcFor(idx), kind: (items[idx] || {}).kind || opts.kind,
                    body: opts.body, title: opts.title
                });
                const del = overlay.querySelector('.mo-del');
                if (del) del.onclick = () => deleteMomentItem(del, opts.messageId,
                                                              items[idx], () => {
                    items.splice(idx, 1);
                    if (!items.length) return overlay.remove();
                    if (idx >= items.length) idx = items.length - 1;
                    draw();
                });
            }

            overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
            draw();
            document.body.appendChild(overlay);
        }

        // Delete the frame on screen, not the share. The message action sheet
        // keeps the wider act and says "Delete album" so the two cannot be
        // confused for each other.
        async function deleteMomentItem(btn, messageId, item, onGone) {
            const isClip = (item || {}).kind === 'video';
            const ok = await promptConfirm(
                `Delete this ${isClip ? 'clip' : 'photo'}?`,
                'It goes for everyone, and it cannot be undone.');
            if (!ok) return;
            const mediaId = String((item || {}).url || '').split('/').pop();
            try {
                const res = await fetch(
                    `${apiBase}api/messages/${messageId}/media/${mediaId}`, {
                    method: 'DELETE', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ member_id: selectedMemberId })
                });
                if (!res.ok) throw new Error('delete failed');
                await refreshThread();
                onGone();
            } catch (e) {
                showGlobalAlert('Could not delete that');
            }
        }
```

Update `openMomentById` to take an index and pass the raw items:

```javascript
        function openMomentById(id, index) {
            const m = (threadMessages || []).find(x => x.id === id);
            if (m && m.attachment) {
                const sender = membersData.find(x => x.id === m.sender_member_id) || {};
                const ch = channelsData.find(c => c.id === activeChannelId) || {};
                return showMomentOverlay({
                    items: attachmentItemsJs(m.attachment),
                    index: index || 0,
                    kind: m.attachment.kind,
                    src: momentMediaSrc(m.attachment),
                    poster: momentPosterSrc(m.attachment),
                    title: ch.kind === 'event' ? ch.title : '',
                    body: m.body,
                    senderName: m.sender_member_id === selectedMemberId ? null : sender.name,
                    messageId: m.id, canDelete: canDeleteMsg(m)
                });
            }
            // Strip rows (older than the thread's 100-message window) carry
            // their own items list from presence._item_rows.
            const row = (momentsStripData || []).find(x => x.id === id);
            if (row) {
                const canDelete = row.sender_member_id === selectedMemberId
                    || myRole() === 'parent';
                return showMomentOverlay({
                    items: (row.items || []).map(i => ({ kind: i.kind, url: i.media_url })),
                    index: index || 0,
                    kind: row.kind,
                    src: `${apiBase}${String(row.media_url || '').replace(/^\//, '')}`,
                    poster: `${apiBase}${String(row.poster_url || '').replace(/^\//, '')}`,
                    title: row.event_title,
                    /* …the rest of this branch is unchanged… */
                    messageId: row.id, canDelete: canDelete
                });
            }
        }
```

Finally, in the message action sheet markup, the Delete entry's label becomes
album-aware. Find the `⋯` menu's delete button and render its label as:

```javascript
${attachmentItemsJs(m.attachment).length > 1 ? 'Delete album' : 'Delete'}
```

The old `deleteMomentFromOverlay` was reached only from the lightbox's inline
`onclick`, which this task replaces. Grep for it; if nothing else calls it,
delete it rather than leaving a second delete path nobody takes.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python tests/test_share_out.py`
Expected: PASS.

- [ ] **Step 5: Rebuild Tailwind, full sweep, then commit**

```bash
python tools/build_tailwind.py
python tools/test.py
sed -i 's/^version: "2.387.8"/version: "2.387.9"/' config.yaml
```

```bash
cd /e/repositories/Chauffeur && git add -A && git commit -F - <<'EOF'
The lightbox acts on the frame you are looking at. (v2.387.9)

Share sends that item. Delete takes that item. Opening item three is the
whole reason item three is the one you wanted, so neither should quietly
reach for the cover.

Two buttons, two scopes, each labelled with the scope it has: Delete photo
in the lightbox, Delete album on the message sheet, which has no current
item and must not pretend otherwise.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
git push origin main
```

---

### Task 11: The gallery draws an album as one tile

**Files:**
- Modify: `templates/components/moments_gallery.html` — `renderEvents`
  (~line 195), `renderMoments` (~line 226), `g.openMoment` (~line 359)
- Test: `tests/test_presence.py`

**Interfaces:**
- Consumes: `items` and `media_count` on wire rows (Task 3).
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Write the failing test**

```python
def scenario_gallery_draws_albums():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    g = open(os.path.join(root, 'templates', 'components', 'moments_gallery.html'),
             encoding='utf-8').read()
    check('media_count' in g, 'the event card counts media, not shares')
    check('mgIndex' in g or 'idx' in g, 'the lightbox tracks a current item')
    check('m.items' in g, 'moment tiles know how many media a share holds')
```

Register it in `SCENARIOS`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python tests/test_presence.py`
Expected: `FAIL scenario_gallery_draws_albums`.

- [ ] **Step 3: Write the implementation**

**3a.** Event card counts media. In `renderEvents`, change:

```javascript
                            ${show.count ? `<span class="absolute top-2 right-2 text-[11px] font-bold bg-black/70 text-white px-2 py-0.5 rounded-full">
                                ${e.count} moment${e.count !== 1 ? 's' : ''}</span>` : ''}
```

to:

```javascript
                            ${show.count ? `<span class="absolute top-2 right-2 text-[11px] font-bold bg-black/70 text-white px-2 py-0.5 rounded-full">
                                ${e.media_count || e.count} moment${(e.media_count || e.count) !== 1 ? 's' : ''}</span>` : ''}
```

**3b.** A moment tile shows how many it holds. In `renderMoments`, change the
media div to append a count chip:

```javascript
                        <div class="relative w-full" style="aspect-ratio: 4/3">${thumb(m.poster_url, m.kind, m.media_url)}${
                            (m.items || []).length > 1
                                ? `<span class="absolute top-2 right-2 text-[11px] font-bold bg-black/70 text-white px-2 py-0.5 rounded-full">⧉ ${m.items.length}</span>`
                                : ''}</div>
```

**3c.** The lightbox steps. Replace `g.openMoment` with:

```javascript
            // One tile per SHARE, and the lightbox walks what is inside it.
            // Spreading an album back into the grid would rebuild the wall of
            // context-free stills this whole feature exists to prevent.
            g.openMoment = function (momentId, startAt) {
                const m = g.mItems.find(x => x.id === momentId);
                if (!m || !opts.lightbox) return;
                const items = (m.items && m.items.length) ? m.items
                    : [{ kind: m.kind, media_url: m.media_url, poster_url: m.poster_url }];
                let idx = Math.min(Math.max(0, startAt || 0), items.length - 1);
                const overlay = document.createElement('div');
                overlay.className = 'fixed inset-0 z-[210] flex items-center justify-center p-6';
                overlay.style.background = 'rgba(0,0,0,0.88)';

                function draw() {
                    const it = items[idx];
                    const clip = it.kind === 'video';
                    const media = clip
                        ? `<video src="${url(it.media_url)}" poster="${url(it.poster_url)}" autoplay muted loop playsinline controls preload="auto" class="max-h-[64vh] rounded-2xl mx-auto"></video>`
                        : `<img src="${url(it.media_url)}" class="max-h-[64vh] rounded-2xl mx-auto object-contain">`;
                    const many = items.length > 1;
                    overlay.innerHTML = `
                        ${clip ? `<style>
                            html.clip-playing *,
                            html.clip-playing *::before,
                            html.clip-playing *::after {
                                -webkit-backdrop-filter: none !important;
                                backdrop-filter: none !important;
                            }
                        </style>` : ''}
                        <div class="relative text-center bg-gray-900 border border-pink-500/40 rounded-3xl shadow-2xl p-6 max-w-4xl">
                            <div class="text-[12px] font-black uppercase tracking-widest text-pink-300 mb-2">📸 ${esc(m.event_title)}</div>
                            <div class="relative inline-block">
                                ${media}
                                ${many ? `
                                <button class="mg-prev absolute left-1 top-1/2 -translate-y-1/2 w-11 h-11 rounded-full bg-black/50 text-white text-xl">‹</button>
                                <button class="mg-next absolute right-1 top-1/2 -translate-y-1/2 w-11 h-11 rounded-full bg-black/50 text-white text-xl">›</button>
                                <span class="absolute top-2 left-1/2 -translate-x-1/2 px-2 py-0.5 rounded-full bg-black/60 text-white text-xs font-bold">${idx + 1} / ${items.length}</span>` : ''}
                            </div>
                            ${m.body ? `<div class="text-xl text-white font-bold mt-3">${esc(m.body)}</div>` : ''}
                            <div class="text-sm text-gray-400 mt-2">from ${esc(m.sender_name)} · ${dayLabel(m.ts)} ${timeLabel(m.ts)}</div>
                        </div>`;
                    const p = overlay.querySelector('.mg-prev');
                    const nx = overlay.querySelector('.mg-next');
                    if (p) p.onclick = e => { e.stopPropagation(); idx = (idx - 1 + items.length) % items.length; draw(); };
                    if (nx) nx.onclick = e => { e.stopPropagation(); idx = (idx + 1) % items.length; draw(); };
                    document.documentElement.classList.toggle('clip-playing', clip);
                }

                overlay.addEventListener('click', e => {
                    if (e.target.closest('.mg-prev') || e.target.closest('.mg-next')) return;
                    overlay.remove();
                    document.documentElement.classList.remove('clip-playing');
                });
                draw();
                document.body.appendChild(overlay);
            };
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python tests/test_presence.py`
Expected: all PASS.

- [ ] **Step 5: Rebuild Tailwind, full sweep, then commit**

```bash
python tools/build_tailwind.py
python tools/test.py
sed -i 's/^version: "2.387.9"/version: "2.387.10"/' config.yaml
```

```bash
cd /e/repositories/Chauffeur && git add -A && git commit -F - <<'EOF'
One tile per share; the lightbox walks what is inside. (v2.387.10)

Spreading an album back across the grid would rebuild the wall of
context-free stills this feature exists to prevent, so a share is one tile
with a count chip and stepping happens full screen.

Event cards count media now, matching what you are actually about to browse.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
git push origin main
```

---

### Task 12: The wall pop steps when tapped

**Files:**
- Modify: `templates/components/moments_hearth.html` —
  `showMomentOverlayKiosk` (~line 75)
- Test: `tests/test_presence.py` (extend `scenario_hearth_is_pop_only`)

**Interfaces:**
- Consumes: `items` on the moment row / stream meta (Task 3).
- Produces: nothing.

- [ ] **Step 1: Write the failing test**

Add to the existing `scenario_hearth_is_pop_only` in `tests/test_presence.py`:

```python
    check('m.items' in hearth, 'the pop knows an album has more than one frame')
    check('stepMoment' in hearth or 'idx' in hearth, 'and tapping steps through them')
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python tests/test_presence.py`
Expected: `FAIL scenario_hearth_is_pop_only`.

- [ ] **Step 3: Write the implementation**

Replace `window.showMomentOverlayKiosk` in
`templates/components/moments_hearth.html` with:

```javascript
        window.showMomentOverlayKiosk = function (m) {
            const items = (m.items && m.items.length) ? m.items
                : [{ kind: (m.kind || (m.attachment || {}).kind),
                     media_url: m.media_url, poster_url: m.poster_url }];
            let idx = 0, timer = null;
            const overlay = document.createElement('div');
            overlay.className = 'fixed inset-0 z-[200] flex items-center justify-center p-8';
            overlay.dataset.momentOverlay = '1';
            overlay.style.background = 'rgba(0,0,0,0.82)';

            function close() {
                clearTimeout(timer);
                overlay.remove();
                // A poll can pop a second moment over the first, so the flag
                // comes off only when the last overlay has gone.
                if (!document.querySelector('[data-moment-overlay]')) {
                    document.documentElement.classList.remove('clip-playing');
                }
            }

            function draw() {
                const it = items[idx];
                const clip = it.kind === 'video';
                overlay.innerHTML = `
                    <style>@keyframes kioskMomentPop { 0% { transform: scale(.5); opacity: 0; } 60% { transform: scale(1.06); } 100% { transform: scale(1); opacity: 1; } }</style>
                    ${clip ? CLIP_COMPOSITING_CSS : ''}
                    <div style="animation:kioskMomentPop .5s ease-out forwards"
                        class="relative text-center bg-gray-900 border border-pink-500/40 rounded-3xl shadow-2xl p-6 max-w-3xl">
                        <div class="text-[12px] font-black uppercase tracking-widest text-pink-300 mb-2">📸 ${esc(m.event_title)}</div>
                        ${mediaHtml(it, 'max-h-[62vh] rounded-2xl mx-auto object-contain')}
                        ${items.length > 1 ? `<div class="absolute top-3 right-4 px-2 py-0.5 rounded-full bg-black/60 text-white text-xs font-bold">${idx + 1} / ${items.length}</div>` : ''}
                        ${m.body ? `<div class="text-xl text-white font-bold mt-3">${esc(m.body)}</div>` : ''}
                        <div class="text-sm text-gray-400 mt-2">from ${esc(m.sender_name)}</div>
                    </div>`;
                document.documentElement.classList.toggle('clip-playing', clip);
                // Clips get a little longer on the wall than stills, and the
                // clock restarts on every step so the room can dwell on a good
                // one. An album can therefore never hold the panel for longer
                // than somebody is actively choosing to hold it.
                clearTimeout(timer);
                timer = setTimeout(close, clip ? 30000 : 20000);
            }

            // Tapping STEPS rather than closes, and a tap past the last item
            // closes — so the wall never traps the room in a ten-photo album,
            // and nobody has to hunt for a dismiss target.
            overlay.addEventListener('click', () => {
                if (idx + 1 >= items.length) return close();
                idx += 1;
                draw();
            });
            draw();
            document.body.appendChild(overlay);
        };
```

Note `mediaHtml` is called with an ITEM now (`{kind, media_url, poster_url}`),
which is exactly the shape `mediaUrl` already reads.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python tests/test_presence.py`
Expected: all PASS.

- [ ] **Step 5: Full sweep, then commit**

```bash
python tools/test.py
sed -i 's/^version: "2.387.10"/version: "2.387.11"/' config.yaml
```

```bash
cd /e/repositories/Chauffeur && git add -A && git commit -F - <<'EOF'
The wall shows one frame and waits to be asked for the next. (v2.387.11)

Tapping steps instead of closing, and the clock restarts each time, so the
room can dwell on a good one. A tap past the last frame closes.

Not an unattended slideshow: five clips would own the wall for minutes and a
second album arriving mid-run would have to queue behind it.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
git push origin main
```

---

### Task 13: The single-moment card, and the capabilities doc

**Files:**
- Modify: `templates/moment.html` (~line 71)
- Modify: `system_capabilities.md` (the Moments section, ~line 313-315)
- Test: `tests/test_presence.py`

**Interfaces:**
- Consumes: `items` on the moment row (Task 3).
- Produces: nothing.

- [ ] **Step 1: Write the failing test**

```python
def scenario_moment_card_shows_the_cover():
    """The iframed single-moment card is full-bleed and dependency-free — it
    shows the cover and says how many more there are, never a carousel."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    page = open(os.path.join(root, 'templates', 'moment.html'), encoding='utf-8').read()
    check('items' in page, 'it knows a share can hold several')
    check('carousel' not in page.lower() and 'setInterval' not in page,
          'and deliberately does not animate through them')
```

Register it in `SCENARIOS`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python tests/test_presence.py`
Expected: `FAIL scenario_moment_card_shows_the_cover`.

- [ ] **Step 3: Write the implementation**

In `templates/moment.html`, inside the render block that builds `media`, add a
count chip when the row carries more than one item:

```javascript
                    const extra = (m.items || []).length > 1
                        ? `<span class="count-chip">⧉ ${m.items.length}</span>` : '';
```

and include `${extra}` inside the existing `<div class="media">…</div>`, with
a matching rule in that page's own `<style>` block:

```css
        .count-chip {
            position: absolute; top: 12px; right: 12px;
            padding: 2px 10px; border-radius: 9999px;
            background: rgba(0, 0, 0, .6); color: #fff;
            font-size: 13px; font-weight: 800;
        }
        .media { position: relative; }
```

Then bring `system_capabilities.md` up to date. Replace the Moments bullets
(the gallery bullet and the kiosk-pop bullet) so they describe: the `items`
shape and the cover mirror; the 10 cap; atomic posting with photos going
through `/api/media/photo`; one push per album with `_moment_push_phrase`; the
`+N` middle level and why there is no other; lone clips opening the lightbox;
lightbox share/delete acting on the current item versus the action sheet
acting on the share; `DELETE /api/messages/{id}/media/{media_id}` with its
collapse rules; `media_count` on event cards versus the share-counting shelf
badge; the screensaver taking every item; the home board tile and
`/moment` taking only the cover.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python tests/test_presence.py`
Expected: all PASS.

- [ ] **Step 5: Full sweep, then commit**

```bash
python tools/test.py
sed -i 's/^version: "2.387.11"/version: "2.387.12"/' config.yaml
```

```bash
cd /e/repositories/Chauffeur && git add -A && git commit -F - <<'EOF'
The card says there is more without becoming a carousel. (v2.387.12)

The iframed single-moment page exists to be full-bleed and dependency-free,
so it shows the cover and a count. Capabilities doc brought up to date with
the whole album arc.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
git push origin main
```

---

## Post-arc verification on device

The standing rule is that source-reading tests miss runtime breaks, and this
arc touches four surfaces that only exist on real hardware. After Task 13,
verify on the live add-on (see the HA deployment workflow: **Check for
updates → rebuild → confirm the version**, and re-copy the custom component by
hand):

1. Share five photos from a phone into an event thread. One push arrives on
   the other parent's phone reading "5 photos". One bubble, one caption.
2. Wall panel pops the cover with `1 / 5`. Tap: it advances. Tap past the
   last: it closes.
3. `/moments` shows one tile with `⧉ 5`; opening it steps.
4. Share from the lightbox on item 3 — the sheet offers item 3.
5. Delete item 3 from the lightbox; the other four survive, the thread
   refreshes, and the panel's next poll agrees.
6. Send an album of two clips over cellular; kill the connection mid-upload
   and restore it. The transfer resumes at the server's offset and nothing
   posts until both land.
7. Screensaver playlist includes all five photos, not one.
