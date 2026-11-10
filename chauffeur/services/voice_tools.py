"""Speech-safe projections and explicit household delegation on the agent rail."""
import re
from services import storage, scope, access
from services.voice_identity import VoiceContext, _revision, voice_names

TOOLS = frozenset({'get_calendar_events', 'get_travel_time', 'get_weather', 'assign_driver_to_event_fuzzy',
                   'remove_override_for_event_fuzzy', 'get_shopping_list_items',
                   'add_shopping_items', 'check_off_shopping_item', 'send_family_message', 'send_direct_message',
                   'find_in_chauffeur', 'start_project', 'prepare_voice_approval', 'house', 'music', 'memory',
                   'report_gap'})
MUTATIONS = frozenset({'assign_driver_to_event_fuzzy', 'remove_override_for_event_fuzzy',
                       'add_shopping_items', 'check_off_shopping_item'})

# Privacy follows the data: shared household reads and changes are speakable,
# as are confirmations that only repeat the speaker's request. Sensitive stores
# remain private, including errors that may name records. Calendar/list/driver
# rows still pass the checks below; house locate is checked per action.
SPEAKABLE = frozenset({
    'get_calendar_events', 'get_travel_time', 'get_weather', 'get_shopping_list_items',
    'assign_driver_to_event_fuzzy', 'remove_override_for_event_fuzzy',
    'house', 'music', 'memory', 'report_gap', 'prepare_voice_approval',
    'add_household_task', 'complete_household_task', 'claim_household_task',
    'add_kid_task', 'complete_kid_task', 'claim_chore', 'reopen_chore',
    'add_shopping_items', 'check_off_shopping_item', 'remove_shopping_item_by_name',
    'send_family_message', 'send_direct_message', 'announce_to_room',
    'create_list', 'create_trip', 'start_project', 'add_project_step', 'add_to_project',
    'set_project_state', 'set_step_state', 'make_request',
    'propose_family_action', 'dismiss_insight',
    'add_errand', 'update_errand', 'delete_errand', 'add_errand_rule', 'delete_errand_rule',
    'set_errand_habits', 'forget_errand_preference', 'update_memory',
    'add_routing_rule', 'delete_routing_rule', 'add_priority_rule', 'delete_priority_rule',
    'run_solver', 'set_household_status', 'decide_optional_event', 'set_event_optional',
    'cancel_event', 'restore_event', 'group_events_ride_together', 'ungroup_event',
    'add_trip_accommodation', 'edit_trip_accommodation', 'add_trip_poi', 'edit_trip_poi',
    'clear_trip_itinerary', 'auto_schedule_trip_itinerary', 'schedule_trip_itinerary',
    'contribute_to_family_goal', 'cover_with_assist', 'log_program_session',
    'add_dishes', 'add_meal_to_repertoire', 'add_meal_ingredients_to_list',
    'mark_meal_served', 'mark_leftovers', 'clear_leftovers', 'refine_meal_dish',
    'change_tonights_plate', 'approve_week_dinners', 'set_meal_rule', 'plan_specific_dinner',
    'unlock_dinner', 'pair_dishes', 'unpair_dishes', 'set_dish_scope', 'set_dish_categories',
    'set_hosting', 'set_dish_prep', 'clear_dish_prep', 'schedule_shopping_trip',
    'add_occasion', 'add_occasion_guests', 'set_occasion_attendance',
    'answer_occasion_question', 'stamp_occasion_template', 'add_occasion_dishes',
    'set_occasion_menu',
    'adjust_points', 'research_question', 'list_projects', 'get_project', 'list_programs',
    'list_chores', 'get_routine_status', 'get_drive_digest', 'get_household_status',
    'get_household_load', 'get_household_tasks', 'get_kid_tasks', 'get_assist_coverage',
    'get_family_goals', 'get_point_balances', 'get_errands', 'get_errand_habits',
    'get_errand_preferences', 'get_eating_plan', 'get_meal_rules', 'get_tonights_plate',
    'get_week_dinners', 'get_shopping_trip', 'get_prep_ahead', 'get_run_sheet',
    'suggest_dinner', 'search_places', 'generate_trip_plan', 'post_weekly_digest',
    'negotiate_day', 'program_progress', 'manage_car', 'manage_trip_rules', 'manage_trip_flights',
    # Registry-only household actions follow the same rule as the chat tools.
    'house_design', 'propose_program', 'start_drive', 'update_drive_status',
    'add_override', 'delete_override', 'generate_trip_flights', 'add_trip_flight',
    'edit_trip_flight', 'delete_trip_flight', 'challenge_pet_battle', 'award_pet_xp', 'get_pet_status',
})
PRIVATE = frozenset({
    'answer_request', 'start_ask', 'mark_ask_sent', 'answer_ask',
    'read_mail', 'search_mail', 'get_family_messages', 'list_threads',
    'add_thread_note', 'close_thread', 'update_thread_action', 'create_thread',
    'find_in_chauffeur', 'get_requests', 'start_mission_for',
    'launch_mission', 'act_on_situation', 'explain_situation', 'next_situation',
    'list_situations', 'list_insights', 'list_open_findings', 'get_current_state',
    'get_occasion', 'get_occasion_gaps', 'get_occasion_insights', 'suggest_gift_ideas',
    'add_occasion_gift_list', 'source_for_occasion', 'draft_thread_message', 'ask_deal',
})


def row_checks_before(name, args, member):
    """The phone's existing row-level audible checks, shared by satellites."""
    if name in ('assign_driver_to_event_fuzzy', 'remove_override_for_event_fuzzy'):
        from services.agent_tools_v2 import _find_event_fuzzy
        row, error = _find_event_fuzzy(args.get('event_name') or '', args.get('target_date') or 'today')
        if error or not row or not speech_safe(row):
            return False
    elif name in ('get_shopping_list_items', 'add_shopping_items', 'check_off_shopping_item'):
        from services.agent_tools_v2 import _resolve_shopping_list
        row, error = _resolve_shopping_list(args.get('list_name') or '', member)
        if error or not row or not scope.audience_allows(row, 'shopping_list', None) \
                or row.get('private') or row.get('sensitivity') == 'sensitive':
            return False
    elif name in ('start_mission_for', 'find_in_chauffeur'):
        return False  # goal/focus/mission results can contain private details
    return True


def row_checks_after(name, result):
    if name == 'get_calendar_events' and isinstance(result, dict):
        # Match the audible HOUSE projection, including hashed Busy ids.
        sources = {r.get('id'): r for r in access.cached_schedule().get('events', [])}
        for row in result.get('events', []):
            source = sources.get(row.get('id'))
            if not source or not speech_safe(source):
                return False
    return True


def speech_safe(row):
    return scope.audience_allows(row, 'calendar_event', None) \
        and row.get('sensitivity') != 'sensitive' and not row.get('private') \
        and str(row.get('visibility') or '').lower() not in ('private', 'confidential')


def record_action(ctx, name, principal=None, details=None, provenance=None):
    import time
    import uuid
    provenance = ctx.provenance() if provenance is None else provenance
    with storage.db_lock, storage.db.transaction():
        rows = storage.get_app_state('voice_action_history') or []
        rows.append({'id': uuid.uuid4().hex, 'at': time.time(), 'action': name, 'principal_member_id': (principal or {}).get('id'),
                     'action_label': {'assign_driver_to_event_fuzzy': 'Assigned a driver',
                                      'remove_override_for_event_fuzzy': 'Cleared a driver assignment',
                                      'add_shopping_items': 'Added shopping items',
                                      'check_off_shopping_item': 'Checked off a shopping item',
                                      'house': 'Controlled a device',
                                      'music': 'Played music'}.get(name, 'Household action'),
                     **provenance, 'details': details or {}})
        storage.set_app_state('voice_action_history', rows[-100:])


# Tools that take a person and answer "whose day": a first-person question
# from a known speaker is about them.
_PERSONAL = ('get_calendar_events', 'get_drive_digest')
_FIRST_PERSON = re.compile(r"(?i)(?<![\w'])(i|i'm|i’m|me|my|mine|myself)(?![\w'])")


def scope_to_speaker(name, args, asked, speaker_name, other_names=()):
    """The deterministic backstop under the model's 'me/my' reading (device
    2026-10-30: 'what time do I need to leave today' from a speaker greeted by
    name was answered with another driver's drive). When a personal read tool
    was called with no member_name, the speaker is known (named or verified)
    and the words are in the first person with no OTHER family member named,
    member_name becomes the speaker. It only ever narrows a read; the model's
    own member_name, a household question and an unknown speaker pass through."""
    args = dict(args or {})
    if name not in _PERSONAL or args.get('member_name') or not speaker_name:
        return args
    words = str(asked or '')
    if not _FIRST_PERSON.search(words):
        return args
    low = words.lower()
    for other in other_names or ():
        first = str(other or '').strip().lower().split(' ')[0]
        if first and first != speaker_name.strip().lower().split(' ')[0] and re.search(r"\b" + re.escape(first) + r"\b", low):
            return args
    args['member_name'] = speaker_name
    return args


def dispatch(name, args, ctx: VoiceContext, focus_key=None):
    from services import agent_tools_v2 as tools
    if name not in TOOLS:
        return {'status': 'refused', 'message': 'That needs your phone.'}
    args = args if isinstance(args, dict) else {}
    if ctx.ha_instance_id and ctx.service_revision != _revision():
        return {'status': 'refused', 'message': 'The satellite service token changed. Please try again.'}
    if not ctx.ha_instance_id and (name in MUTATIONS or name in ('send_family_message', 'send_direct_message')):
        return {'status': 'refused', 'message': 'This household action needs the configured satellite service token and metadata.'}
    # Without per-turn evidence, retain the verified household rail.
    principal = getattr(ctx, 'actor', ctx.verified_member)() or ctx.verified_member()
    if name in MUTATIONS and principal is None:
        from services.situations import parent_of_record
        principal = parent_of_record()
        if not principal or not storage.member_has_access(principal):
            return {'status': 'refused', 'message': 'A parent needs to set up household actions on their phone first.'}
    provenance = ctx.provenance()
    if name in MUTATIONS:
        with storage.db_lock, storage.db.transaction():
            if ctx.service_revision != _revision():
                return {'status': 'refused', 'message': 'The satellite service token changed. Please try again.'}
            result = _mutate(name, args, principal, provenance)
            if result.get('status') == 'success':
                record_action(ctx, name, principal, {'target_element_id': result.get('target_element_id')}, provenance)
            return result
    if name == 'prepare_voice_approval':
        from services.voice_approval import prepare
        return prepare(ctx, args.get('mission_ref') or '', args.get('kind') or 'submit')
    if name == 'get_calendar_events':
        result = tools.get_calendar_events(args.get('start_date'), args.get('end_date'), spoken=True,
                                           member_name=args.get('member_name') or '')
    elif name == 'get_travel_time':
        result = tools.get_travel_time(origin=args.get('origin') or '',
                                       destination=args.get('destination') or '')
    elif name == 'get_weather':
        result = tools.get_weather(days=args.get('days', 7))
    elif name == 'house':
        result = tools.house(**{k: v for k, v in args.items() if k in (
            'action', 'query', 'entity_id', 'domain', 'service', 'data', 'hours', 'app')},
            voice_context=ctx, source='voice')
        if args.get('action') in ('act', 'app') and result.get('status') == 'success':
            record_action(ctx, 'house', principal,
                          {'entity_id': result.get('entity_id'), 'service': result.get('service'),
                           'app': result.get('app')}, provenance)
    elif name == 'music':
        result = tools.music(**{k: v for k, v in args.items() if k in (
            'action', 'query', 'room', 'player', 'media_type', 'mode', 'level')},
            voice_context=ctx, source='voice')
        if args.get('action') == 'play' and result.get('status') == 'success':
            record_action(ctx, 'music', principal,
                          {'entity_id': result.get('entity_id'), 'item': result['item'].get('name')}, provenance)
    elif name == 'report_gap':
        # A gap is a gap whoever hit it; the voice need not be known.
        result = tools.report_gap(**{k: v for k, v in args.items() if k in (
            'kind', 'what_was_asked', 'what_was_missing', 'asked', 'prior')},
            acting_member=principal or ctx.member(), source='voice')
    elif name == 'memory':
        # Teaching uses the speaker's role; recognition does not supply PIN proof.
        result = tools.memory(**{k: v for k, v in args.items() if k in (
            'action', 'text', 'kind', 'phrase', 'entity_ids', 'memory_id')},
            acting_member=principal, source='voice')
        if args.get('action') in ('remember', 'forget') and result.get('status') == 'success':
            record_action(ctx, 'memory', principal,
                          {'action': args.get('action'), 'text': (result.get('memory') or {}).get('text')}, provenance)
    elif name == 'get_shopping_list_items':
        result = tools.get_shopping_list_items(args.get('list_name') or '', acting_member=None)
    elif name in ('send_family_message', 'send_direct_message'):
        body = str(args.get('message_text') or '').strip()
        if not body:
            return {'status': 'error', 'message': 'What should I send to the family?'}
        member = principal
        sender = member or storage.ensure_argyle_member()
        if name == 'send_direct_message':
            wanted = str(args.get('recipient_name') or '').strip().casefold()
            matches = [m for m in storage.get_all_members() if storage.member_has_access(m)
                       and wanted in voice_names(m)]
            if len(matches) != 1:
                return {'status': 'refused', 'message': 'Which active family member should get that message?'}
            recipient = matches[0]
            if recipient['id'] == sender['id']:
                return {'status': 'refused', 'message': 'That would go to yourself.'}
            if (recipient.get('role') == 'helper' and (member or {}).get('role') != 'parent') \
                    or ((member or {}).get('role') == 'helper' and recipient.get('role') != 'parent'):
                return {'status': 'refused', 'message': 'That message needs the permitted sender on their phone.'}
            channel = storage.get_or_create_dm(sender['id'], recipient['id'])
            destination = recipient.get('name') or 'that family member'
        else:
            if (member or {}).get('role') == 'helper':
                return {'status': 'refused', 'message': 'Helpers can message parents directly.'}
            storage.ensure_family_channel()
            channel = storage.get_family_channel()
            destination = 'the family'
        if not channel:
            return {'status': 'error', 'message': 'The family channel needs to be set up on your phone.'}
        tools._post_chat_message(channel, sender, body if member else f'Household voice: {body}', context=provenance)
        result = {'status': 'success', 'message': f'Sent to {destination}.'}
    elif name == 'find_in_chauffeur':
        return tools.find_in_chauffeur(args.get('query') or '', args.get('kind') or '',
                                       args.get('facet') or '', acting_member=access.HOUSE,
                                       spoken=True)
    else:
        result = tools.start_project(args.get('goal') or '', args.get('title'),
                                     acting_member=principal, focus_key=focus_key,
                                     voice_context=ctx, subject_kind=args.get('subject_kind'),
                                     subject_id=args.get('subject_id'))
    return result


def _mutate(name, args, principal, provenance):
    from services import agent_tools_v2 as tools
    if name in ('assign_driver_to_event_fuzzy', 'remove_override_for_event_fuzzy'):
        values = {'event_name': args.get('event_name') or '', 'target_date': args.get('target_date') or 'today',
                  'spoken': True, 'acting_member': principal, 'actor_provenance': provenance}
        if name == 'assign_driver_to_event_fuzzy':
            values['driver_name'] = args.get('driver_name') or ''
        result = getattr(tools, name)(**values)
        if result.get('status') == 'success':
            result['schedule_dirty'] = True
        return result
    field = 'items' if name == 'add_shopping_items' else 'item_name'
    return getattr(tools, name)(args.get(field) or '', list_name=args.get('list_name') or '',
                                acting_member=principal, spoken=True, actor_provenance=provenance)
