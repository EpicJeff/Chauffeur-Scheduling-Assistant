"""Room announcements (services/announce.py).

The property under test: "Hey Argyle, Lily is in the pool house — tell her
it's time for dinner" must end with words coming out of the RIGHT speaker,
and with a written copy in Lily's DMs. Everything here runs offline against
stubbed ha_api calls; the shapes mirror what HA's template API and /states
actually return.
"""
from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import announce, ha_api, storage


AREAS = [
    {'id': 'pool_house', 'name': 'Pool House',
     'entities': ['assist_satellite.pool_house', 'media_player.pool_speaker',
                  'light.pool']},
    {'id': 'garage', 'name': 'Garage',
     'entities': ['media_player.garage_cast', 'media_player.garage_ma']},
    {'id': 'kitchen', 'name': 'Kitchen', 'entities': ['light.kitchen']},
]


def _states(**overrides):
    base = {
        'assist_satellite.pool_house': ('idle', {}),
        'media_player.pool_speaker': ('playing', {'mass_player_type': 'player'}),
        'media_player.garage_cast': ('idle', {}),
        'media_player.garage_ma': ('idle', {'mass_player_type': 'player'}),
    }
    base.update(overrides)
    return [{'entity_id': k, 'state': v[0], 'attributes': v[1]}
            for k, v in base.items()]


class _Stub:
    """Swap module attributes for a scenario, restore on exit."""
    def __init__(self, **kw):
        self.kw = kw
        self.orig = {}

    def __enter__(self):
        for dotted, val in self.kw.items():
            mod, attr = dotted.split('.')
            target = {'ha_api': ha_api, 'storage': storage, 'announce': announce}[mod]
            self.orig[dotted] = getattr(target, attr)
            setattr(target, attr, val)
        return self

    def __exit__(self, *a):
        for dotted, val in self.orig.items():
            mod, attr = dotted.split('.')
            target = {'ha_api': ha_api, 'storage': storage, 'announce': announce}[mod]
            setattr(target, attr, val)


def _base_stubs(**extra):
    stubs = {
        'ha_api.get_area_map': lambda ttl=60: AREAS,
        'ha_api.get_states': lambda ttl=5: _states(),
        'ha_api.resolve_area_id': lambda name: None,
        'ha_api.get_entities': lambda domain: (
            [{'entity_id': 'tts.piper', 'name': 'Piper', 'state': 'idle'}]
            if domain == 'tts' else []),
        'ha_api.get_pipeline_tts': lambda ttl=300: None,
        'storage.get_settings': lambda: {},
    }
    stubs.update(extra)
    return stubs


def scenario_a_room_is_found_however_speech_mangles_it():
    """Every request arrives through speech-to-text. 'Pool House',
    'poolhouse', 'the pool house please' and 'pool hose' are one room, and
    an alias the family taught HA ('cabana') resolves without us ever being
    able to enumerate it over REST."""
    with _Stub(**_base_stubs(**{
            'ha_api.resolve_area_id':
                lambda name: 'pool_house' if 'cabana' in name.lower() else None})):
        for spoken in ('Pool House', 'poolhouse', 'the pool house please',
                       'pool hose', 'cabana'):
            got = announce.match_area(spoken)
            check(got and got['id'] == 'pool_house',
                  f"'{spoken}' must find the pool house, got {got}")
        check(announce.match_area('attic') is None,
              "a room the registry has never heard of stays unmatched")
        check(announce.match_area('') is None, "empty spoken text matches nothing")


def scenario_the_satellite_is_the_rooms_argyle():
    """A voice satellite outranks every media player in its room — even one
    already playing. It speaks with the same pipeline voice Argyle answers
    in, which is what makes the announcement feel like Argyle at all."""
    with _Stub(**_base_stubs()):
        kind, eid = announce.pick_target(AREAS[0])
        check(kind == 'satellite' and eid == 'assist_satellite.pool_house',
              f"satellite first, got {kind} {eid}")


def scenario_the_garage_picks_the_speaker_somebody_can_hear():
    """No satellite in the garage. The player already PLAYING is audibly on
    and somebody is near it; among idle players the Music Assistant one wins
    (announce ducks and resumes there); an unavailable player is never the
    answer to anything."""
    garage = AREAS[1]
    playing = {'media_player.garage_cast': ('playing', {})}
    with _Stub(**_base_stubs(**{'ha_api.get_states': lambda ttl=5: _states(**playing)})):
        check(announce.pick_target(garage) == ('media_player', 'media_player.garage_cast'),
              "the playing player wins even against an idle MA player")
    with _Stub(**_base_stubs()):
        check(announce.pick_target(garage) == ('media_player', 'media_player.garage_ma'),
              "both idle: the MA player wins — its announce resumes the music")
    gone = {'media_player.garage_ma': ('unavailable', {})}
    with _Stub(**_base_stubs(**{'ha_api.get_states': lambda ttl=5: _states(**gone)})):
        check(announce.pick_target(garage) == ('media_player', 'media_player.garage_cast'),
              "an unavailable player is skipped, not blasted")


def scenario_a_pinned_speaker_beats_the_heuristic():
    """The family's pin (settings.announce_targets) is the last word — it
    exists precisely for the rooms where the automatic pick is wrong or the
    HA area registry is. A pin whose entity has gone unavailable falls back
    to automatic rather than announcing into a dead speaker."""
    pin = {'announce_targets': {'pool_house': 'media_player.pool_speaker'}}
    with _Stub(**_base_stubs(**{'storage.get_settings': lambda: pin})):
        check(announce.pick_target(AREAS[0]) == ('media_player', 'media_player.pool_speaker'),
              "the pin wins over the satellite")
    dead = {'media_player.pool_speaker': ('unavailable', {})}
    with _Stub(**_base_stubs(**{'storage.get_settings': lambda: pin,
                                'ha_api.get_states': lambda ttl=5: _states(**dead)})):
        kind, eid = announce.pick_target(AREAS[0])
        check(eid == 'assist_satellite.pool_house',
              f"a dead pin falls back to automatic, got {eid}")


def scenario_announce_speaks_on_the_right_channel():
    """Satellite rooms use assist_satellite.announce (with the long timeout —
    HA holds the call open while the words play); player-only rooms use
    tts.speak, which needs a TTS entity and says so honestly when there is
    none."""
    calls = []

    def record(domain, service, data=None, **kw):
        calls.append((domain, service, data, kw))
        return {}

    with _Stub(**_base_stubs(**{'ha_api.call_service': record})):
        res = announce.announce('pool house', 'Time for dinner!')
        check(res['status'] == 'success' and res['kind'] == 'satellite', f"got {res}")
        domain, service, data, kw = calls[-1]
        check((domain, service) == ('assist_satellite', 'announce') and
              data == {'entity_id': 'assist_satellite.pool_house',
                       'message': 'Time for dinner!'},
              f"satellite call shape, got {calls[-1]}")
        check(kw.get('timeout', 0) > ha_api._TIMEOUT,
              "announce blocks while speaking — the default timeout would "
              "report a played announcement as failed")

        res = announce.announce('garage', 'Car is leaving in five.')
        domain, service, data, _ = calls[-1]
        check(res['status'] == 'success' and (domain, service) == ('tts', 'speak') and
              data == {'entity_id': 'tts.piper',
                       'media_player_entity_id': 'media_player.garage_ma',
                       'message': 'Car is leaving in five.'},
              f"tts fallback call shape, got {calls[-1]}")

    with _Stub(**_base_stubs(**{'ha_api.call_service': record,
                                'ha_api.get_entities': lambda domain: []})):
        res = announce.announce('garage', 'hello')
        check(res['status'] == 'error' and 'text-to-speech' in res['message'],
              f"no TTS engine is named as the reason, got {res}")


def scenario_the_fallback_speaks_in_argyles_own_voice():
    """The satellite path uses its pipeline's voice for free; the tts.speak
    path used to grab the first tts entity's DEFAULT voice, so the pool house
    answered in a different voice than the kitchen. The Argyle pipeline's
    engine + voice + language now ride along whenever the pipeline names a
    real tts entity; a legacy engine name ('cloud') can't carry its voice
    over tts.speak and degrades to the old behaviour rather than erroring."""
    calls = []

    def record(domain, service, data=None, **kw):
        calls.append((domain, service, data, kw))
        return {}

    pipe = {'engine': 'tts.home_assistant_cloud', 'voice': 'JennyNeural',
            'language': 'en-US'}
    with _Stub(**_base_stubs(**{'ha_api.call_service': record,
                                'ha_api.get_pipeline_tts': lambda ttl=300: pipe})):
        res = announce.announce('garage', 'Dinner!')
        _, _, data, _ = calls[-1]
        check(res['status'] == 'success' and
              data == {'entity_id': 'tts.home_assistant_cloud',
                       'media_player_entity_id': 'media_player.garage_ma',
                       'message': 'Dinner!', 'language': 'en-US',
                       'options': {'voice': 'JennyNeural'}},
              f"the pipeline's engine, voice and language all travel, got {data}")

    legacy = {'engine': 'cloud', 'voice': 'JennyNeural', 'language': 'en-US'}
    with _Stub(**_base_stubs(**{'ha_api.call_service': record,
                                'ha_api.get_pipeline_tts': lambda ttl=300: legacy})):
        announce.announce('garage', 'Dinner!')
        _, _, data, _ = calls[-1]
        check(data.get('entity_id') == 'tts.piper' and 'options' not in data,
              "a legacy engine name degrades to the first tts entity and "
              f"never smuggles another engine's voice id onto it, got {data}")


def scenario_the_failure_sentences_are_honest():
    """Each way this can fail is a different sentence, because the fixes are
    different: an unknown room lists the rooms that exist, a speakerless room
    names itself, and an unreachable HA never pretends to be a room problem."""
    with _Stub(**_base_stubs()):
        res = announce.announce('attic', 'hello')
        check(res['status'] == 'error' and 'Pool House' in res['message'],
              f"the unknown-room error teaches the room names, got {res}")
        res = announce.announce('kitchen', 'hello')
        check(res['status'] == 'error' and 'Kitchen' in res['message'] and
              'speaker' in res['message'],
              f"a room with no speaker says so, got {res}")
        res = announce.announce('pool house', '   ')
        check(res['status'] == 'error', "empty message never reaches HA")
    with _Stub(**_base_stubs(**{'ha_api.get_area_map': lambda ttl=60: []})):
        res = announce.announce('pool house', 'hello')
        check(res['status'] == 'error' and 'reach' in res['message'],
              f"unreachable HA is its own claim, got {res}")


def scenario_the_echo_is_a_dm_and_never_a_retry_hazard():
    """An announcement is air; the DM copy is the record (dual delivery).
    And when the echo fails AFTER the words were spoken, the result stays a
    success — an error would send the agent around the loop to announce the
    same dinner twice."""
    from services import agent_tools_v2
    posted = []
    argyle = {'id': 'argyle', 'name': 'Argyle', 'system': True}
    lily = {'id': 'm_lily', 'name': 'Lily', 'role': 'child'}
    orig = (storage.ensure_argyle_member, storage.get_or_create_dm,
            agent_tools_v2._post_chat_message)
    try:
        storage.ensure_argyle_member = lambda: argyle
        storage.get_or_create_dm = lambda a, b: {'id': f'dm_{a}_{b}', 'kind': 'dm',
                                                 'member_ids': [a, b]}
        agent_tools_v2._post_chat_message = \
            lambda ch, sender, body, card=None: posted.append((ch['id'], sender['id'], body))
        with _Stub(**_base_stubs(**{'ha_api.call_service':
                                    lambda *a, **kw: {}})):
            res = announce.announce_and_echo('pool house', 'Dinner!', recipient=lily)
            check(res['status'] == 'success' and res.get('echoed'), f"got {res}")
            ch, sender, body = posted[-1]
            check(sender == 'argyle' and 'Pool House' in body and 'Dinner!' in body,
                  f"the copy names the room and carries the words, got {posted[-1]}")

            res = announce.announce_and_echo('pool house', 'Dinner!', recipient=argyle)
            check(res['status'] == 'success' and not res.get('echoed'),
                  "a system recipient gets no DM")

            def boom(*a, **kw):
                raise RuntimeError("push exploded")
            agent_tools_v2._post_chat_message = boom
            res = announce.announce_and_echo('pool house', 'Dinner!', recipient=lily)
            check(res['status'] == 'success' and not res.get('echoed'),
                  f"a failed echo must not fail (and re-run) the announcement, got {res}")
    finally:
        (storage.ensure_argyle_member, storage.get_or_create_dm,
         agent_tools_v2._post_chat_message) = orig


def scenario_changing_the_voice_writes_to_the_pipeline_not_a_copy():
    """The voice picker is a REMOTE CONTROL, not a setting: it writes
    tts_voice onto the Argyle pipeline in HA, which every mouth reads —
    a stored Chauffeur copy would split-brain the first time somebody
    edited the pipeline in HA's own UI. The update is a whole-object PUT
    in websocket clothing, so every pipeline field must travel back."""
    argyle = {'id': 'p2', 'name': 'Argyle', 'conversation_engine': 'conversation.argyle_assist',
              'conversation_language': 'en', 'language': 'en',
              'stt_engine': 'stt.whisper', 'stt_language': 'en',
              'tts_engine': 'tts.piper', 'tts_language': 'en_US',
              'tts_voice': 'lessac', 'wake_word_entity': 'wake_word.ok_nabu',
              'wake_word_id': 'hey_argyle'}
    listing = {'preferred_pipeline': 'p1', 'pipelines': [
        {'id': 'p1', 'name': 'Home Assistant',
         'conversation_engine': 'conversation.home_assistant'},
        argyle,
    ]}
    calls = []

    def fake_ws(command, timeout=8, **fields):
        calls.append((command, fields))
        if command == 'assist_pipeline/pipeline/list':
            return listing
        if command == 'assist_pipeline/pipeline/update':
            return {**argyle, **fields}
        return None

    check(announce.ha_api._pick_argyle_pipeline(listing)['id'] == 'p2',
          "our own pipeline outranks HA's preferred one")

    orig_ws, orig_cache = ha_api.ws_command, dict(ha_api._pipeline_cache)
    try:
        ha_api.ws_command = fake_ws
        ha_api._pipeline_cache.update(ts=9e12, data={'engine': 'stale'})
        check(ha_api.set_pipeline_voice('ryan') is True, "the write succeeds")
        cmd, fields = calls[-1]
        check(cmd == 'assist_pipeline/pipeline/update' and
              fields.get('pipeline_id') == 'p2' and fields.get('tts_voice') == 'ryan',
              f"the Argyle pipeline gets the new voice, got {calls[-1]}")
        missing = [k for k in ha_api._PIPELINE_FIELDS if k not in fields]
        check(not missing,
              f"a whole-object PUT: omitting a field nulls it on the pipeline — missing {missing}")
        check(ha_api._pipeline_cache['data'] is None,
              "the cache is busted so the next announcement reads the new voice")

        ha_api.ws_command = lambda command, timeout=8, **f: (
            listing if command.endswith('list') else None)
        check(ha_api.set_pipeline_voice('ryan') is False,
              "a refused update reports failure, not a silent shrug")
    finally:
        ha_api.ws_command = orig_ws
        ha_api._pipeline_cache.update(orig_cache)


def scenario_the_voice_tool_is_wired_into_the_agent():
    """The schema is offered, the router treats a completed announcement as
    terminal (its confirmation IS the spoken reply), and the tool tolerates
    an anonymous sender — the wall panel and a cold voice session don't know
    who is asking, and dinner must not be gated on introductions."""
    from services import agent_tools_v2, agent_router
    import inspect
    names = [t['name'] for t in agent_tools_v2.get_available_tools()]
    check('announce_to_room' in names, "the tool is offered to the model")
    src = inspect.getsource(agent_router)
    check('"announce_to_room"' in src.split('def ')[0] or "'announce_to_room'" in src
          or '"announce_to_room"' in src,
          "the router dispatches it")
    with _Stub(**_base_stubs(**{'ha_api.call_service': lambda *a, **kw: {}})):
        res = agent_tools_v2.announce_to_room('pool house', 'Dinner!')
        check(res['status'] == 'success',
              f"no sender, no recipient still announces, got {res}")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} announce scenarios passed")
