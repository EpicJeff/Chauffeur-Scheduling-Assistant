# Album Moments

**Status:** design approved 2026-08-23, unimplemented
**Related:** `docs/presence_status_design.md` (Slice 4, where moments came from),
`system_capabilities.md` §Moments

## The problem

An event has parts. A game has a first half, a huddle, a second half, a
trophy. Someone standing there shoots four or five frames of each part and
wants to hand the family *that part* — with a sentence saying what it was.

Today a moment is one message carrying one attachment, so five frames means
five messages. The result is a wall of unlabelled stills in the gallery, five
pushes on five phones, five separate pops on the panel, and no way to tell
which four belong together. The caption problem is the sharp end of it: a
caption belongs to the run, and there is nowhere to put one.

An album is one message carrying several media and one caption. That is the
whole feature.

## Shape

`ChatMessage.attachment` gains an `items` list. The cover's fields stay
mirrored at the top level, exactly where they are today:

```jsonc
{
  "kind": "photo",                 // the cover — unchanged, still item 0
  "url": "/api/media/ab12…",
  "mime": "image/jpeg", "w": 2048, "h": 1365,
  "items": [                       // present ONLY for albums (2+)
    {"kind": "photo", "url": "/api/media/ab12…", "mime": "…", "w": 0, "h": 0},
    {"kind": "video", "url": "/api/media/cd34.mp4", "mime": "video/mp4"}
    // … up to 10
  ]
}
```

Three properties are doing the work:

**Additive.** Every existing reader of `attachment` keeps working with no
edit at all — it sees a normal single-photo moment and gets the cover. Only
the surfaces that want to show the whole album learn about `items`. There is
no migration, and records written before this feature stay valid forever.

**`items` is absent for a single share.** A one-photo moment is written
exactly as it is written today. There is one representation of "one photo",
not two, and `items` being present is precisely the question "is this an
album" — no counting required.

**`items[0]` IS the cover, duplicated.** The duplication is deliberate: it is
what buys the first property. A reader that never learns about albums cannot
be wrong, because the field it reads is still populated with the same kind of
value it has always held.

One helper, in `services/storage.py`, is the only place that knows the rule:

```python
def attachment_items(att):
    """Every media in a moment, cover first. One item for an ordinary moment,
    N for an album — so a caller can iterate without asking which it has."""
    att = att or {}
    return att.get('items') or ([att] if att.get('url') or att.get('data_url') else [])
```

Rejected alternatives:

- *A sibling `attachments: []` field.* Two sources of truth about the cover,
  and every reader has to learn which one wins. Nothing is gained over
  `items`.
- *A separate media table keyed by `message_id`.* Correct in the abstract, but
  it turns every moment read — the gallery, the screensaver, the pop, the
  thread — into a join, for a family whose entire archive is a few thousand
  rows. The cost is paid on every read to normalize data that is only ever
  read with its message.

## Cap

**10 media per album.** Enough for a part of a game; low enough that one
share cannot dump a camera roll onto the wall. Enforced twice: the composer
trims the pick and says so, and `_validate_moment_attachment` refuses an
eleventh with a 400.

## Everything uploads before the message is posted

**Atomic.** Tap Send → an optimistic album bubble appears immediately with a
progress ring per cell → every item uploads → when the last one lands, ONE
message posts carrying the URLs. One push, one gallery row, one pop.

This changes how PHOTOS reach the server. Today a photo rides the message
body as a `data:` URL and `_validate_moment_attachment` persists it to the
media store on the way past. Ten of those in one request is a ~160 MB JSON
POST. Instead the composer uploads each photo to the existing
`POST /api/media/photo` first and the message carries `/api/media/…` URLs
only — which `_validate_moment_attachment` already accepts (the "already
stored, re-post / migration passthrough" branch). The message body stays a
few hundred bytes whether it carries one item or ten.

The composer takes that path for a single photo too, rather than keeping a
second code path for the one-item case. The server keeps accepting the inline
`data:` form regardless: old clients, the migration passthrough, and the
existing tests all still post that way, and nothing is gained by breaking
them.

Rejected: *post the message immediately and append items as uploads land.* It
reads faster on the sender's own screen, but the panel would pop an "album"
of one that silently grows, the push would fire describing a share that is
not finished, and it needs an append-attachment endpoint with its own
permission story. The optimistic bubble already provides the "it is sending"
feedback, locally, with none of that.

**Failure is per item.** If item 3 of 5 exhausts its retries, the bubble stays
failed and Retry resumes *only item 3* — the chunked upload already resyncs to
the offset the server actually has. Nothing is posted until the set is whole.
Discarding the bubble abandons the parts, and the existing 2-hour scratch
sweep (`_sweep_stale_uploads`) collects them.

## What each surface does

### The wall pop — `components/moments_hearth.html`

Cover full-screen, as today, with a `1 / 5` marker. It plays out its normal
20 s (photo) / 30 s (clip) and goes. **Tapping steps forward** instead of
closing, and the timeout restarts on each step, so the room can dwell on a
good one; a tap past the last item closes. An album can therefore never hold
the panel for longer than a person is actively choosing to hold it.

Rejected: auto-advancing the whole album unattended. Five clips would own the
wall for minutes, and a second album arriving mid-run would have to queue or
stack.

### The gallery — `components/moments_gallery.html`

An album is **one tile** in the event grid: the cover, with a count chip
where a clip would show its play badge. Tapping opens the lightbox at item 0;
the lightbox gains prev/next affordances and keyboard arrows, and closes at
either end the way it closes today.

One tile, not five, is the entire point of the feature — spreading an album
back into the grid would rebuild the wall of context-free stills it exists to
prevent.

**The event card's count becomes a MEDIA count.** `get_event_moment_index`
gains `media_count` (sum of `len(attachment_items(att))`) and the card renders
that. A card saying "6" over an event holding 24 photos answers a question
nobody asked. Note this is deliberately *not* the same unit as the shelf
badge, which counts SHARES (`count_event_moments_since`, one per message).
They answer different questions — "how much is in here" versus "how many
times did someone share" — and never appear beside each other.

### The PWA thread — `templates/app.html`

The bubble renders a grid, sized to the count: 2 across for two, one large
plus two for three, 2×2 for four, and 2×2 with a `+N` scrim on the last cell
beyond that. Any cell opens the existing full-screen lightbox at that index,
stepping with the same controls the gallery's uses. The caption sits below
the grid, once.

**Every cell is a still.** A clip in an album renders its poster frame with a
play badge, never a live `<video>` — the gallery already refuses this for the
same reason ("tiles ALWAYS render a still image"), and a 2×2 grid of live
players is four decoders in a chat row.

**Single clips move to the lightbox too, and that is a behaviour change.**
Today a lone video bubble renders an inline `<video controls>` with no click
handler, so the tap goes to the player; only photos carry
`onclick="openMomentById(…)"`. Once album cells route to the lightbox, leaving
single clips inline would mean two rules — tap a lone clip and it plays in
place, tap one inside an album and it goes full screen — with nothing on
screen to explain the difference. So a single clip becomes a poster with a
play badge that opens the lightbox, same as every other media in the thread.
Nothing is lost: `showMomentOverlay` already renders `<video controls
autoplay playsinline>` for `kind === 'video'` and the moments strip has been
reaching that path all along. Clips gain the full screen instead of a 256px
player.

The channel-list preview line reads "📷 5 photos" for an album with no
caption, and the caption itself when there is one.

### The lightbox — `showMomentOverlay`

Gains a current index. For an album it draws prev/next affordances and a
`3 / 5` marker; for a single moment it is exactly what it is today.

**Share shares the item you are looking at**, not the cover — the whole point
of opening item 3 is that item 3 is the one you want. It reads the current
index, so stepping the lightbox re-aims the Share button for free. This is
the one place the cover rule does not apply; the message action sheet, which
has no notion of a current item, still shares the cover.

**Delete stays message-scoped and must say so.** The button deletes the
MESSAGE, so on item 3 of 5 it takes all five. With `items` present it reads
**"Delete album"**. Per-item delete is out of scope: it would mean mutating a
stored attachment, reassigning the cover when item 0 goes, and collecting
exactly one file — real work for an action whose honest form ("take the whole
share back") is what the button already does.

### Share-out — `shareMessage` / `shareOut`

The message action sheet shares **the cover only**, with the same text rule
already locked in the share-out slice (body → event title → nothing). It has
no notion of a current item, so the cover is the only honest answer.

Sharing from the LIGHTBOX shares the item on screen instead (see above).

Neither shares the whole album as a multi-file sheet. Deliberate: `shareOut`'s
contract is one file plus text, `navigator.canShare` support for multi-file is
uneven across the devices this family actually holds, and a share sheet that
silently drops four of five files is worse than one that honestly sends the
frame you chose. Revisit when there is a native iOS app.

### The screensaver — `services/home_board.py`

Iterates `attachment_items` and contributes **every** photo and every clip
poster in an album, not just the cover. This is a slideshow of the family's
photographs; more of them is strictly better. The message pull stays at 120
and the assembled URL list is sliced to a URL cap so a few big albums cannot
crowd out the rest of the archive.

### The home board moments tile — `services/home_board.py`

Contributes **the cover only**. The tile is a flat mosaic of the last few
moments beside eight other tiles; one album flooding it would push every
other activity off the board.

### Media deletion — `storage._delete_media_for_messages`

Iterates `attachment_items`. This is the one place where getting it wrong is
silent and permanent: moments are exempt from the retention cap, so nothing
else will ever collect an album's non-cover files, and they would sit on the
family's disk forever. Same per-item cleanup as today (media file, `.orig`,
`.tmp.mp4`, poster `.jpg`).

### Push fan-out — `main._fanout_message_notifications`

One push per album, describing the set: "Mom shared 5 photos from Emma's
Volleyball", "…shared 3 photos and a clip…". Not five pushes, which is the
single most visible thing this feature fixes for anyone not at the event.

### Wire rows — `presence._moment_row`, `presence.moment_stream_meta`

Both gain `items: [{kind, media_url, poster_url}]`, cover first, so a client
never has to reach into the raw attachment or ask a second endpoint. Both
keep `kind` / `media_url` / `poster_url` at the top level, describing the
cover, for exactly the same back-compat reason the stored shape does.

### The standalone moment page — `templates/moment.html`

Shows **the cover only**, with the count chip. It exists to be iframed as a
single-moment HA card, and a card whose whole job is "the latest moment,
full-bleed, zero dependencies" should not grow a carousel.

### `/api/moments/{message_id}/media` — unchanged

It stays the cover's by-message URL. Albums carry direct `/api/media/…` URLs
on every item, so nothing needs an indexed variant of this route; it exists
to decode LEGACY inline photos, and no legacy record is an album. Adding
`/media/{i}` would be a route nothing calls.

## Validation

`main._validate_moment_attachment` grows one branch, ahead of the existing
`kind` dispatch:

- `items` present → must be a non-empty list, at most 10, each item validated
  by recursing into the SAME single-item logic (so a `data:` URL in item 4
  still gets persisted, and a bad item still raises its own 400/413).
- The normalized result is `{**items[0], 'items': items}` — cover mirrored,
  never computed anywhere else.
- A one-item list normalizes to a plain single attachment with no `items`
  key, so the client may send `items` uniformly without creating a second
  representation of a single photo.

The existing per-item `_ATTACHMENT_MAX_CHARS` guard is unchanged and now
applies to each item.

## Testing

`tests/test_presence.py`:

- `attachment_items` on a legacy inline photo, a modern single photo, an
  album, and junk.
- Validation: 10 accepted, 11 refused 400, empty list refused, a bad item
  refused with ITS error not a generic one, one-item list normalized to no
  `items` key.
- `_moment_row` / `moment_stream_meta` carry `items` cover-first, and still
  carry cover fields at the top level.
- **Deletion frees every item's files**, asserted on disk — the landmine.
- Screensaver playlist contains every album photo and every album clip poster.
- The home board moments tile contains the cover ONCE for an album.
- `count_event_moments_since` still counts an album as 1 (already asserted;
  extend it to an actual album once the shape exists).
- `media_count` on the event index sums media while `count` stays messages.

`tests/test_share_out.py`: the message action sheet shares an album's cover,
the lightbox shares the item at the current index, and the text rule is
unchanged in both.

Template/runtime tests, per the standing rule that entry points swallow
exceptions: the composer's staging and upload orchestration is extracted far
enough to be exercised by the `_extract`-style harness already in
`test_share_out.py`, covering the cap trim, per-item failure isolation, and
that nothing posts until every item has a URL.

## Out of scope

- Adding to an album after it is posted. A second part of the game is a
  second share with its own caption, which is the feature working.
- Reordering or choosing a cover. First file wins; on iOS the picker returns
  files in tap order, so the sender already controls it.
- Albums in DMs beyond what falls out for free. Moments are an event-channel
  idea; a DM attachment keeps working exactly as it does now.
- Deleting one item out of a posted album. The message is the unit; Delete
  takes the whole share and the button says "Delete album" so it cannot be
  mistaken for anything narrower.
- Sharing a whole album as one multi-file share sheet.
