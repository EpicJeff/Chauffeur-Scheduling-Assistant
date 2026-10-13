"""Speech-safe projections and explicit household delegation on the agent rail."""
from services import storage, scope
from services.voice_identity import VoiceContext, _revision, voice_names

TOOLS = frozenset({'get_calendar_events', 'get_travel_time', 'assign_driver_to_event_fuzzy',
                   'remove_override_for_event_fuzzy', 'get_shopping_list_items',
                   'add_shopping_items', 'check_off_shopping_item', 'send_family_message', 'send_direct_message',
                   'start_mission_for', 'prepare_voice_approval'})
MUTATIONS = frozenset({'assign_driver_to_event_fuzzy', 'remove_override_for_event_fuzzy',
                       'add_shopping_items', 'check_off_shopping_item'})


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
                                      'check_off_shopping_item': 'Checked off a shopping item'}.get(name, 'Household action'),
                     **provenance, 'details': details or {}})
        storage.set_app_state('voice_action_history', rows[-100:])


def dispatch(name, args, ctx: VoiceContext, focus_key=None):
    from services import agent_tools_v2 as tools
    if name not in TOOLS:
        return {'status': 'refused', 'message': 'That needs your phone.'}
    args = args if isinstance(args, dict) else {}
    if ctx.ha_instance_id and ctx.service_revision != _revision():
        return {'status': 'refused', 'message': 'The satellite service token changed. Please try again.'}
    if not ctx.ha_instance_id and (name in MUTATIONS or name in ('send_family_message', 'send_direct_message')):
        return {'status': 'refused', 'message': 'This household action needs the configured satellite service token and metadata.'}
    principal = ctx.verified_member()
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
        result = tools.get_calendar_events(args.get('start_date'), args.get('end_date'), spoken=True)
    elif name == 'get_travel_time':
        result = tools.get_travel_time(origin=args.get('origin') or '',
                                       destination=args.get('destination') or '')
    elif name == 'get_shopping_list_items':
        result = tools.get_shopping_list_items(args.get('list_name') or '', acting_member=None)
    elif name in ('send_family_message', 'send_direct_message'):
        body = str(args.get('message_text') or '').strip()
        if not body:
            return {'status': 'error', 'message': 'What should I send to the family?'}
        member = ctx.verified_member()
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
    else:
        result = tools.start_mission_for(args.get('goal') or '', args.get('title'),
                                         acting_member=ctx.verified_member(), focus_key=focus_key,
                                         voice_context=ctx)
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
