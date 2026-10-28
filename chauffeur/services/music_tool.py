"""Music search and playback for Argyle's chat and voice surfaces."""
import difflib
import re

from services import announce, ha_api, music_search


_CONTROLS = {
    'pause': ('media_pause', 'Paused'),
    'resume': ('media_play', 'Resumed'),
    'next': ('media_next_track', 'Skipped to the next track on'),
    'previous': ('media_previous_track', 'Skipped to the previous track on'),
    'stop': ('media_stop', 'Stopped'),
}
_ACTIONS = ('play', *_CONTROLS, 'volume', 'now')


def _name(states, eid):
    return (states[eid].get('attributes') or {}).get('friendly_name') or eid


def _is_ma(states, eid):
    return 'mass_player_type' in ((states.get(eid) or {}).get('attributes') or {})


def _target(action, room, player, voice_context, source, states):
    """Resolve explicit names before rooms, then the satellite or house default."""
    area = None
    if player:
        # The model copies the words as spoken: "the office TV." carries an
        # article and a full stop that no entity name has. Strip them, and
        # treat every spoken word appearing in a name as a strong match, so
        # "the office TV" still reaches "Office TV Media Player".
        wanted = re.sub(r"^(the|my|our|a|an)\s+", '', str(player).strip().casefold())
        wanted = wanted.strip(' .,!?')
        wanted_tokens = set(wanted.split())
        players = [eid for eid in states if eid.startswith('media_player.')]

        def score(eid):
            name = _name(states, eid).casefold()
            if wanted in (name, eid.casefold()):
                return 1.0
            if wanted and (wanted in name or name in wanted):
                return 0.9
            if wanted_tokens and wanted_tokens <= set(name.split()):
                return 0.9
            return difflib.SequenceMatcher(None, wanted, name).ratio()

        players = [eid for eid in players if score(eid) >= 0.6]
        if not players:
            return None, None, f"I don't know a player called {player}."
        if action == 'play':
            # A TV is several entities with one name: the remote, the cast
            # target and Music Assistant's own player, whose friendly name
            # carries a suffix ("Office TV Media Player"). For PLAY the MA
            # twin is the one that can play, so among the strong matches it
            # wins over an exact-name twin that cannot.
            strong = [e for e in players if score(e) >= 0.9 and announce._usable(states, e)]
            ma_twins = [e for e in strong if _is_ma(states, e)]
            if ma_twins:
                players = ma_twins
        eid = min(players, key=lambda e: (
            -score(e), not announce._usable(states, e),
            not _is_ma(states, e) if action == 'play' else False,
            announce._music_rank(states, e)))
        area = next((a for a in ha_api.get_area_map()
                     if eid in (a.get('entities') or [])), None)
    else:
        if room:
            area = announce.match_area(room)
            if area is None:
                return None, None, f"I don't know a room called {room}."
        elif source == 'voice' and getattr(voice_context, 'satellite_id', None):
            area = next((a for a in ha_api.get_area_map()
                         if voice_context.satellite_id in (a.get('entities') or [])), None)
        eid = announce.pick_music_player(area)
        if area and action == 'play' and not _is_ma(states, eid):
            players = [e for e in (area.get('entities') or [])
                       if e.startswith('media_player.') and announce._usable(states, e)]
            ma_players = [e for e in players if _is_ma(states, e)]
            if not ma_players and players:
                # MA's twin may have no HA area; match it by the room's names.
                ma_players = _ma_twins(states, [_name(states, e) for e in players], area.get('name'))
            if ma_players:
                eid = min(ma_players, key=lambda e: announce._music_rank(states, e))
            elif players:
                names = ', '.join(dict.fromkeys(f'{_name(states, e)} ({e})' for e in players))
                return None, area, (f"{names} in {area.get('name') or room} is not a Music "
                                    f'Assistant player. {_ma_list(states)}')
    if not eid or not announce._usable(states, eid):
        where = f" in {area['name']}" if area else ''
        return None, area, f'No usable music player is available{where}.'
    if action != 'play' and (states.get(eid) or {}).get('state') != 'playing':
        # "What's playing on the office TV": the remote is on with no title,
        # the Music Assistant twin is the one actually playing. Controls and
        # now-playing follow the sound, whichever twin the words picked.
        playing = [e for e in _ma_twins(states, [_name(states, eid)], (area or {}).get('name'))
                   if (states.get(e) or {}).get('state') == 'playing']
        if playing:
            eid = min(playing, key=lambda e: announce._music_rank(states, e))
    if action == 'play' and not _is_ma(states, eid):
        # Whatever path chose a player that cannot play, its Music Assistant
        # twin by name can. Only when there is none do we refuse, and then
        # the refusal names the entity we chose and every player that could
        # have played, so the next report says which branch answered.
        twins = _ma_twins(states, [_name(states, eid)], (area or {}).get('name'))
        if twins:
            return min(twins, key=lambda e: announce._music_rank(states, e)), area, None
        where = f" in {area['name']}" if area else ''
        return None, area, (f'{_name(states, eid)} ({eid}){where} is not a Music Assistant player, '
                            f'and no Music Assistant player shares its name. {_ma_list(states)}')
    return eid, area, None


def _ma_twins(states, names, area_name=None):
    """Usable Music Assistant players whose friendly name carries one of the given
    names ("Office TV" within "Office TV Media Player") or starts with the area."""
    names = [str(n or '').casefold() for n in names if n]
    area_name = (area_name or '').casefold()
    return [e for e in states
            if e.startswith('media_player.') and _is_ma(states, e) and announce._usable(states, e)
            and (any(n and n in _name(states, e).casefold() for n in names)
                 or (area_name and _name(states, e).casefold().startswith(area_name + ' ')))]


def _ma_list(states):
    names = sorted({_name(states, e) for e in states
                    if e.startswith('media_player.') and _is_ma(states, e) and announce._usable(states, e)})
    if not names:
        return 'No Music Assistant player is available right now.'
    return 'Music Assistant players I can play on: ' + ', '.join(names) + '.'


def music(action='', query='', room='', player='', media_type='', mode='', level=None,
          acting_member=None, voice_context=None, source=None):
    """Return plain success/error dicts, including when HA or search fails."""
    try:
        if ha_api.mode() == 'unconfigured':
            return {'status': 'error', 'message': 'Home Assistant is not connected.'}
        if action not in _ACTIONS:
            return {'status': 'error', 'message': f"Unknown music action. Use {', '.join(_ACTIONS)}."}
        if action == 'play' and not str(query or '').strip():
            return {'status': 'error', 'message': 'What should I play?'}
        if action == 'volume':
            try:
                percent = float(level)
            except (TypeError, ValueError):
                percent = -1
            if not 0 <= percent <= 100:
                return {'status': 'error', 'message': 'Volume must be a percent from 0 to 100.'}

        states = announce._states_by_id()
        eid, area, error = _target(action, room, player, voice_context, source, states)
        if error:
            return {'status': 'error', 'message': error}
        name = _name(states, eid)
        room_name = (area or {}).get('name') or ''
        result = {'status': 'success', 'entity_id': eid, 'player': name, 'room': room_name}

        if action == 'play':
            types = [media_type] if media_type in music_search.MEDIA_TYPES else []
            groups = music_search.search(query, media_types=types).get('groups') or []
            item = next((g['items'][0] for mt in (types or music_search.MEDIA_TYPES)
                         for g in groups if g.get('type') == mt and g.get('items')), None)
            if item is None:
                return {'status': 'error', 'message': f'Nothing found for "{query}".'}
            payload = {'entity_id': eid, 'media_id': item['uri'], 'media_type': item['media_type']}
            if mode in ('next', 'add', 'replace', 'replace_next'):
                payload['enqueue'] = mode
            elif mode == 'radio':
                payload['radio_mode'] = True
            if ha_api.call_service('music_assistant', 'play_media', payload) is None:
                return {'status': 'error', 'message': 'Music Assistant refused to play that.'}
            artists = ', '.join(a['name'] for a in (item.get('artists') or []) if a.get('name'))
            by = f' by {artists}' if artists else ''
            where = f'in {room_name}' if room_name else f'on {name}'
            return {**result, 'item': item, 'message': f"Playing {item['name']}{by} {where}."}

        if action == 'now':
            state = states[eid].get('state')
            attrs = states[eid].get('attributes') or {}
            title, artist = attrs.get('media_title'), attrs.get('media_artist')
            by = f' by {artist}' if artist else ''
            return {**result, 'state': state, 'title': title, 'artist': artist,
                    'album': attrs.get('media_album_name'),
                    'volume': round(attrs['volume_level'] * 100) if attrs.get('volume_level') is not None else None,
                    'message': f'{title}{by} is {state} on {name}.' if title else f'Nothing is playing on {name}.'}

        payload = {'entity_id': eid}
        if action == 'volume':
            service = 'volume_set'
            payload['volume_level'] = round(percent / 100, 2)
            message = f'Set volume on {name} to {percent:g}%.'
        else:
            service, verb = _CONTROLS[action]
            message = f'{verb} {name}.'
        if ha_api.call_service('media_player', service, payload) is None:
            return {'status': 'error', 'message': f'Home Assistant could not control {name}.'}
        return {**result, 'message': message}
    except Exception:
        return {'status': 'error', 'message': 'Music could not complete that request.'}
