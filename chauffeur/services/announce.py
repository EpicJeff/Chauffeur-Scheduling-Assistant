"""Room announcements — Argyle's voice pushed INTO a room.

"Hey Argyle, Lily is in the pool house. Tell her it's time for dinner."

The conversation-agent channel is inbound-only: HA calls us when somebody
speaks to a satellite, and the reply is spoken on the device that asked.
Reaching a DIFFERENT room is a service call — `assist_satellite.announce`
speaks through the target satellite's own pipeline (so it is Argyle's voice
there too), and rooms with only a Music Assistant speaker fall back to
`tts.speak`, which ducks whatever is playing and resumes it.

Room resolution leans on HA's area registry via the template API
(ha_api.get_area_map / resolve_area_id) and then fuzzily, because every
request arrives through speech-to-text and "pool house", "poolhouse" and
"pool hose" are the same room. The matching deliberately skews toward
finding SOME room: a wrong-room announcement is recoverable ("not there —
the garage"), a refused one just fails the dinner call.

An announcement is air. announce_and_echo leaves a written copy in the
recipient's DMs (dual delivery, the kid-arc rule) so headphones or a loud
pool pump don't silently eat the message.
"""
import difflib
import re
from typing import Optional

from services import ha_api


def _fold(s: str) -> str:
    """A room name reduced to how it sounds: lowercase, letters and digits
    only. 'Pool House' == 'poolhouse' == 'pool-house'."""
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


def match_area(spoken: str):
    """The area a spoken room name means, or None.

    Tiers, cheapest and most certain first:
      1. folded name equality ('the Pool House' said as 'poolhouse'),
      2. HA's own area_id() lookup — the only path that sees ALIASES,
         which the family curates in HA and we cannot enumerate over REST,
      3. containment either way ('the pool house please' ⊃ 'poolhouse'),
      4. edit distance for STT mangles ('pool hose'), cutoff 0.6 — chosen
         loose on purpose; see the module docstring for why we skew toward
         matching.
    """
    areas = ha_api.get_area_map()
    sp = _fold(spoken)
    if not areas or not sp:
        return None

    for a in areas:
        if _fold(a.get('name')) == sp:
            return a

    aid = ha_api.resolve_area_id(spoken)
    if aid:
        for a in areas:
            if a.get('id') == aid:
                return a

    best = None
    for a in areas:
        f = _fold(a.get('name'))
        if f and (f in sp or sp in f):
            if best is None or len(f) > len(_fold(best.get('name'))):
                best = a
    if best:
        return best

    by_fold = {_fold(a.get('name')): a for a in areas if _fold(a.get('name'))}
    hit = difflib.get_close_matches(sp, list(by_fold), n=1, cutoff=0.6)
    return by_fold[hit[0]] if hit else None


def _states_by_id():
    return {s.get('entity_id'): s for s in ha_api.get_states(ttl=10)}


def _usable(states: dict, entity_id: str) -> bool:
    st = (states.get(entity_id) or {}).get('state')
    return st is not None and st not in ('unavailable', 'unknown')


def pick_target(area: dict):
    """('satellite'|'media_player', entity_id) for an area, or None.

    A room can hold several players, and blasting all of them invites the
    one unavailable Chromecast to fail the whole call. One target, chosen:

      1. The family's pin (settings.announce_targets[area_id]) — membership
         in the HA area is NOT required, because the pin exists precisely
         for speakers the registry has wrong or missing.
      2. A voice satellite: it is the room's Argyle, made for announce.
      3. The media player already PLAYING — it is audibly on, somebody is
         near it, and tts.speak ducks and resumes it.
      4. Best remaining player: on/idle beats off, Music Assistant players
         beat bare cast targets (announce-with-resume works there), name
         order for determinism.
    """
    states = _states_by_id()

    from services import storage
    pinned = (storage.get_settings().get('announce_targets') or {}).get(area.get('id'))
    if pinned and _usable(states, pinned):
        kind = 'satellite' if pinned.startswith('assist_satellite.') else 'media_player'
        return kind, pinned

    entities = area.get('entities') or []
    sats = sorted(e for e in entities
                  if e.startswith('assist_satellite.') and _usable(states, e))
    if sats:
        return 'satellite', sats[0]

    players = [e for e in entities
               if e.startswith('media_player.') and _usable(states, e)]
    if not players:
        return None

    def rank(eid):
        s = states.get(eid) or {}
        st = s.get('state')
        playing = 2 if st == 'playing' else (1 if st in ('paused', 'idle', 'on', 'buffering') else 0)
        is_ma = 1 if 'mass_player_type' in (s.get('attributes') or {}) else 0
        return (-playing, -is_ma, eid)

    return 'media_player', sorted(players, key=rank)[0]


def _music_rank(states: dict, eid: str):
    """Playing beats idle, a Music Assistant player beats a bare cast target,
    then name order so a wall picks the same speaker twice running."""
    s = states.get(eid) or {}
    st = s.get('state')
    playing = 2 if st == 'playing' else (1 if st in ('paused', 'idle', 'on', 'buffering') else 0)
    is_ma = 1 if 'mass_player_type' in (s.get('attributes') or {}) else 0
    return (-playing, -is_ma, eid)


def pick_music_player(area: dict = None) -> Optional[str]:
    """The speaker a music surface in this room should start on, or None.

    Shares `pick_target`'s pin and its ranking on purpose: `announce_targets`
    already records "when you mean this room, you mean THIS speaker", and a
    house should not have to answer that question twice because one surface
    talks and the other plays. The one thing not shared is the satellite step
    — a voice satellite is the room's Argyle, not something you put an album
    on — so this walks straight to media players.

    With no area it answers for the house: whatever is already playing, else
    the best Music Assistant player anywhere. That is what a panel nobody has
    bound to a room should open on, rather than nothing.
    """
    states = _states_by_id()

    from services import storage
    if area:
        pinned = (storage.get_settings().get('announce_targets') or {}).get(area.get('id'))
        # A pinned SATELLITE is announce's answer, not music's — fall through
        # to the room's real players rather than trying to play into it.
        if pinned and pinned.startswith('media_player.') and _usable(states, pinned):
            return pinned
        candidates = [e for e in (area.get('entities') or [])
                      if e.startswith('media_player.') and _usable(states, e)]
    else:
        candidates = [eid for eid in states
                      if eid.startswith('media_player.') and _usable(states, eid)]
    if not candidates:
        return None
    return sorted(candidates, key=lambda e: _music_rank(states, e))[0]


def _tts_config():
    """(tts_entity_id, language, voice) for the media-player path.

    The satellite path speaks with its pipeline's voice for free; this is
    what keeps the fallback from sounding like a different house. The Argyle
    pipeline's own engine/voice (ha_api.get_pipeline_tts) wins whenever the
    engine is a real tts entity; a legacy engine name ('cloud') can't carry
    its voice over tts.speak, so it degrades to the first tts entity with
    that entity's default voice — same as no pipeline info at all."""
    pipe = ha_api.get_pipeline_tts() or {}
    engine = pipe.get('engine') or ''
    if engine.startswith('tts.'):
        return engine, pipe.get('language'), pipe.get('voice')
    ents = ha_api.get_entities('tts')
    return (ents[0]['entity_id'] if ents else None), None, None


def speak_on(entity_id: str, message: str) -> dict:
    """Say something on ONE named media player, skipping area matching.

    `announce()` below answers "which speaker serves this room"; this
    answers "say it on exactly that one", which is a different question
    and the only one some callers can ask. A browser that has registered
    itself as a Music Assistant player — the PWA as "<Name>'s phone", a
    wall board as its own screen — belongs to no Home Assistant AREA at
    all, so `match_area` can never find it however the room is spelled.
    The device IS the address.

    Deliberately the media-player half of `announce()` and nothing else:
    the same `_tts_config()` engine, language and voice, the same
    `tts.speak`, so a house cannot end up with two voices depending on
    which surface happened to ask. No satellite branch, because a
    satellite is a room's Argyle and is reached by naming its room.

    Same shape of answer as `announce()`, so a caller can treat the two
    interchangeably.
    """
    message = (message or '').strip()
    if not message:
        return {'status': 'error', 'message': "There's nothing to say."}
    if not (entity_id or '').startswith('media_player.'):
        return {'status': 'error',
                'message': f"{entity_id} is not a media player."}
    tts, language, voice = _tts_config()
    if not tts:
        return {'status': 'error',
                'message': "No text-to-speech engine is set up in Home Assistant."}
    data = {'entity_id': tts, 'media_player_entity_id': entity_id,
            'message': message}
    if language:
        data['language'] = language
    if voice:
        data['options'] = {'voice': voice}
    if ha_api.call_service('tts', 'speak', data) is None:
        return {'status': 'error',
                'message': f"{entity_id} didn't take the announcement."}
    return {'status': 'success', 'entity_id': entity_id, 'kind': 'media_player',
            'message': f"Said on {entity_id}: “{message}”"}


def announce(room: str, message: str) -> dict:
    """Resolve the room, pick the speaker, say the words. Returns
    {'status', 'message', ...} in the agent-tool shape; success carries
    area_id/area/entity_id/kind for callers and the UI."""
    message = (message or '').strip()
    if not message:
        return {'status': 'error', 'message': "There's nothing to say."}

    areas = ha_api.get_area_map()
    if not areas:
        return {'status': 'error',
                'message': "I can't reach Home Assistant's room registry right now."}

    area = match_area(room)
    if not area:
        names = ', '.join(a.get('name') for a in areas if a.get('name'))
        return {'status': 'error',
                'message': f"I don't know a room called '{room}'. Rooms I know: {names}."}

    target = pick_target(area)
    if not target:
        return {'status': 'error',
                'message': f"There's no speaker I can reach in the {area.get('name')}."}

    kind, entity_id = target
    if kind == 'satellite':
        # HA holds this call open until the satellite finishes speaking, so
        # the default 8s client timeout would report a played announcement
        # as failed. 30s covers any sentence a person would actually say.
        ok = ha_api.call_service('assist_satellite', 'announce',
                                 {'entity_id': entity_id, 'message': message},
                                 timeout=30) is not None
    else:
        tts, language, voice = _tts_config()
        if not tts:
            return {'status': 'error',
                    'message': "No text-to-speech engine is set up in Home Assistant."}
        data = {'entity_id': tts, 'media_player_entity_id': entity_id,
                'message': message}
        if language:
            data['language'] = language
        if voice:
            data['options'] = {'voice': voice}
        ok = ha_api.call_service('tts', 'speak', data) is not None
    if not ok:
        return {'status': 'error',
                'message': f"The speaker in the {area.get('name')} didn't take the announcement."}

    return {'status': 'success', 'area_id': area.get('id'), 'area': area.get('name'),
            'entity_id': entity_id, 'kind': kind,
            'message': f"Announced in the {area.get('name')}: “{message}”"}


def announce_and_echo(room: str, message: str, sender: dict = None,
                      recipient: dict = None) -> dict:
    """announce(), plus the written copy: when the message was FOR somebody,
    a DM lands in their thread so the words survive the air. Sender defaults
    to Argyle — the wall panel and the voice pipeline often don't know who is
    asking, and the assistant is already a valid DM peer."""
    res = announce(room, message)
    if res.get('status') != 'success' or not recipient or recipient.get('system'):
        return res
    try:
        from services import storage
        from services.agent_tools_v2 import _post_chat_message
        sender = sender or storage.ensure_argyle_member()
        if recipient.get('id') and recipient['id'] != sender.get('id'):
            dm = storage.get_or_create_dm(sender['id'], recipient['id'])
            _post_chat_message(dm, sender,
                               f"📢 (said in the {res.get('area')}): {message}")
            res['echoed'] = True
    except Exception as e:
        # The spoken half already happened; a failed echo must not turn the
        # tool result into an error the agent would retry (and re-announce).
        print(f"[announce] DM echo failed: {e}")
    return res
