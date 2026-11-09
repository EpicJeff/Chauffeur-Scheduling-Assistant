"""One rulebook for Home Assistant device control on every Chauffeur surface.

Places are not people, and knowing a person's role is not proof of identity.
Keep those decisions here so tiles, cards and Argyle can give the same answer.
The legacy panel switch supplies defaults only until a household saves a grid.
Classification and decisions are pure; request expansion reads Home Assistant.
"""
from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass
import secrets
from threading import Lock
import time


KINDS: tuple[str, ...] = (
    'lights', 'switches', 'media', 'climate', 'blinds',
    'garage', 'locks', 'alarm', 'other',
)
ROLES = ('parent', 'adult', 'child', 'helper', 'guest')
PLACES = ('panel', 'unknown_voice')
NEVER_DOMAINS: frozenset[str] = frozenset({
    'homeassistant', 'hassio', 'automation', 'system_log', 'recorder',
    'logger', 'notify', 'tts', 'persistent_notification', 'conversation',
    'frontend', 'backup', 'update', 'zone', 'person',
})

_DOMAIN_KINDS = {
    'light': 'lights',
    'switch': 'switches', 'fan': 'switches', 'input_boolean': 'switches',
    'media_player': 'media', 'remote': 'media',
    'climate': 'climate', 'water_heater': 'climate',
    'lock': 'locks', 'alarm_control_panel': 'alarm',
    'valve': 'other', 'vacuum': 'other', 'siren': 'other', 'button': 'other',
    'number': 'other', 'select': 'other', 'text': 'other',
    'date': 'other', 'time': 'other', 'datetime': 'other',
    'input_button': 'other', 'input_number': 'other', 'input_select': 'other',
    'input_text': 'other', 'input_datetime': 'other',
    'lawn_mower': 'other', 'humidifier': 'other', 'camera': 'other',
}
_SENSITIVE = frozenset({'garage', 'locks', 'alarm'})


def kind_of(entity_id: str, attributes: dict | None) -> str | None:
    """Classify device targets; script/scene markers need expansion by callers.

    An unread cover might be a garage door. A successfully read cover with no
    device class follows HA's ordinary cover behaviour instead.
    """
    domain, separator, name = entity_id.partition('.')
    if not separator or not name or domain in NEVER_DOMAINS:
        return None
    if domain in ('script', 'scene'):
        return domain
    if domain == 'cover':
        if attributes is None or attributes.get('device_class') in ('garage', 'door', 'gate'):
            return 'garage'
        return 'blinds'
    return _DOMAIN_KINDS.get(domain)


def default_rules(settings: dict) -> dict:
    """Reproduce the old permissions without sharing mutable rows."""
    panel = {kind: 'no' for kind in KINDS}
    for kind in ('lights', 'switches', 'media', 'climate', 'blinds', 'other'):
        panel[kind] = 'yes'
    if settings.get('panel_allow_unsafe_controls'):
        panel.update(garage='ask', locks='ask')
    return {
        'enabled': True,
        'proof': {kind: kind in _SENSITIVE for kind in KINDS},
        'people': {
            role: {kind: 'no' if role not in ('parent', 'adult') and kind in _SENSITIVE
                   else 'yes' for kind in KINDS}
            for role in ROLES
        },
        'places': {
            'panel': panel,
            'unknown_voice': {kind: 'ask' if kind in _SENSITIVE else 'yes' for kind in KINDS},
        },
    }


def rules(settings: dict | None = None) -> dict:
    """Copy a valid saved grid; missing or malformed grids get fresh defaults."""
    if settings is None:
        from services import storage
        settings = storage.get_settings() or {}
    if 'ha_control' in settings:
        try:
            return deepcopy(validate_rules(settings['ha_control']))
        except ValueError:
            pass
    return default_rules(settings)


def _check_keys(value, expected, label: str) -> None:
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError(f'{label} must contain exactly: {", ".join(expected)}.')


def validate_rules(raw: dict) -> dict:
    """Reject incomplete grids and invalid cells rather than silently widening."""
    _check_keys(raw, ('enabled', 'proof', 'people', 'places'), 'Home Assistant control rules')
    if not isinstance(raw['enabled'], bool):
        raise ValueError('Home Assistant control enabled must be true or false.')
    _check_keys(raw['proof'], KINDS, 'Proof requirements')
    for kind in KINDS:
        if not isinstance(raw['proof'][kind], bool):
            raise ValueError(f'The proof requirement for {kind} must be true or false.')
    for section, rows, choices in (
        ('people', ROLES, ('yes', 'no')),
        ('places', PLACES, ('yes', 'no', 'ask')),
    ):
        _check_keys(raw[section], rows, section.capitalize())
        for row in rows:
            _check_keys(raw[section][row], KINDS, f'The {row} card')
            for kind in KINDS:
                if raw[section][row][kind] not in choices:
                    raise ValueError(f'The {row} card for {kind} must be {" or ".join(choices)}.')
    return raw


@dataclass(frozen=True)
class Who:
    role: str | None
    member_id: str | None
    place: str | None
    proven: bool
    admin: bool = False
    voice_id: bool = True


_grants: dict[str, dict] = {}
_held: dict[str, dict] = {}
_identity_lock = Lock()


def _prune_expired(rows: dict, now: float) -> None:
    for token in [token for token, row in rows.items() if row['expires_at'] <= now]:
        del rows[token]


def mint_grant(member_id: str, device_id: str) -> str:
    """A panel PIN proves one action on that panel for sixty seconds."""
    token = secrets.token_urlsafe(32)
    with _identity_lock:
        now = time.time()
        _prune_expired(_grants, now)
        _grants[token] = {'member_id': member_id, 'device_id': device_id,
                          'expires_at': now + 60}
    return token


def consume_grant(token: str, device_id: str) -> dict | None:
    from services import storage

    with _identity_lock:
        _prune_expired(_grants, time.time())
        row = _grants.pop(token, None)
    if not row or not device_id or row['device_id'] != device_id:
        return None
    member = storage.get_member(row['member_id'])
    return member if member and storage.member_has_access(member) else None


def hold(tool: str, args: dict) -> str:
    """Keep a copy of the requested tool call until the person identifies."""
    if tool not in ('house', 'music'):
        raise ValueError('Only house and music actions can be held.')
    held_id = secrets.token_urlsafe(32)
    with _identity_lock:
        now = time.time()
        _prune_expired(_held, now)
        _held[held_id] = {'tool': tool, 'args': deepcopy(args), 'expires_at': now + 120}
    return held_id


def take_held(held_id: str) -> dict | None:
    with _identity_lock:
        _prune_expired(_held, time.time())
        row = _held.pop(held_id, None)
    return {'tool': row['tool'], 'args': row['args']} if row else None


def who_from_request(headers, query) -> Who:
    """Only personal sign-ins or a consumed panel grant prove a person."""
    from services import storage
    from tinydb import Query

    panel = Who(None, None, 'panel', False)
    headers = {key.lower(): value for key, value in headers.items()}
    try:
        device_token = headers.get('x-device-token') or query.get('device_token')
        device = storage.get_device_by_token(device_token) if device_token else None
        is_panel = bool(device and device.get('kind') == 'panel')
        grant = headers.get('x-control-grant')
        if grant and is_panel:
            member = consume_grant(grant, device['device_id'])
            if member:
                return Who(member.get('role'), member['id'], None, True)

        token = headers.get('x-member-token') or query.get('member_token')
        if token:
            member = storage.get_member_by_token(token)
            if not member or is_panel:
                return panel
            with storage.db_lock:
                row = storage.member_tokens_table.get(Query().token == token)
            if not row or row.get('house_session'):
                return panel
            # Only rows with NEITHER field predate provenance. Incomplete new
            # rows must not accidentally become personal password sign-ins.
            legacy = 'proof' not in row and 'minted_on' not in row
            proof = 'password' if legacy else row.get('proof')
            minted_on = 'personal' if legacy else row.get('minted_on')
            if proof in ('password', 'pin') and minted_on and minted_on != 'panel':
                return Who(member.get('role'), member['id'], None, True)
            return panel
        if device or grant:
            return panel
    except Exception:
        # A failed identity read is never evidence of an admin or a person.
        return panel
    return panel


def who_from_agent(acting_member: dict | None, voice_context, source: str | None) -> Who:
    from services import access, storage

    if source == 'voice':
        if voice_context is not None:
            if voice_context.level == 'verified':
                member = voice_context.verified_member()
                if member and storage.member_has_access(member):
                    return Who(member.get('role'), member['id'], None, True)
            if voice_context.recognized_this_turn and voice_context.member_id:
                member = storage.get_member(voice_context.member_id)
                if member and storage.member_has_access(member):
                    return Who(member.get('role'), member['id'], None, False)
        return Who(None, None, 'unknown_voice', False,
                   voice_id=bool(voice_context and voice_context.paired))
    if access.is_house(acting_member):
        return Who(None, None, 'panel', False)
    if acting_member is None and source == 'admin':
        return Who(None, None, None, False, admin=True)
    if acting_member and storage.member_has_access(acting_member):
        return Who(acting_member.get('role'), acting_member['id'], None, True)
    return Who(None, None, 'panel', False)


@dataclass
class Decision:
    allowed: bool
    needs: str | None
    kinds: tuple[str, ...]
    message: str


def decide(who: Who, kinds: Iterable[str], rules: dict) -> Decision:
    """All kinds must pass; a refusal beats identification, which beats a PIN."""
    kinds = tuple(kinds)
    if rules.get('enabled') is not True:
        return Decision(False, None, kinds, 'Home Assistant control is turned off for this household.')
    if any(kind not in KINDS for kind in kinds):
        return Decision(False, None, kinds, 'This kind of Home Assistant control is not supported.')
    if who.admin:
        return Decision(True, None, kinds, '')

    needs = None
    for kind in kinds:
        proof = rules['proof'][kind]
        if who.place is not None:
            cell = rules['places'].get(who.place, {}).get(kind)
            if cell not in ('yes', 'ask'):
                return Decision(False, None, kinds,
                                f'The household does not allow {kind} control from this place.')
            if cell == 'ask' or proof:
                if who.place == 'unknown_voice' and not who.voice_id:
                    return Decision(False, None, kinds,
                                    "Voice ID isn't on for this speaker; use your phone.")
                needs = 'identify'
        else:
            cell = rules['people'].get(who.role, {}).get(kind)
            if cell != 'yes':
                return Decision(False, None, kinds,
                                f'The household does not allow your role to control {kind}; ask a parent.')
            if proof and not who.proven and needs != 'identify':
                needs = 'pin'

    if needs == 'identify':
        return Decision(False, needs, kinds, "Who's asking? Identify yourself and enter your PIN.")
    if needs == 'pin':
        return Decision(False, needs, kinds, 'Enter your PIN to confirm who you are.')
    return Decision(True, None, kinds, '')


def _entity_ids(value: str | Iterable[str] | None) -> tuple[str, ...]:
    """Match HA's comma-separated entity selectors, including list members."""
    values = (value,) if isinstance(value, str) else value if value is not None else ()
    return tuple(part.strip().lower() for item in values for part in item.split(',')
                 if part.strip())


def targets(data: dict, domain: str | None = None) -> set[str]:
    """Expand selectors, filtering device/area membership to the service domain."""
    from services import ha_api

    def validate(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in ('floor_id', 'label_id'):
                    raise ValueError(f'The {key} target could not be read.')
                validate(item)
        elif isinstance(value, list):
            for item in value:
                validate(item)

    validate(data)

    def ids(value, entity=False):
        if entity:
            return set(_entity_ids(value))
        if isinstance(value, str):
            return {value}
        return set(value or [])

    def eligible(entity_id):
        if domain is not None:
            return entity_id.startswith(domain + '.')
        return kind_of(entity_id, None) is not None

    entities, devices, areas = set(), set(), set()
    for source in (data, data.get('target') or {}):
        entities.update(ids(source.get('entity_id'), entity=True))
        devices.update(ids(source.get('device_id')))
        areas.update(ids(source.get('area_id')))
    if 'all' in entities:
        entities.remove('all')
        entities.update(row['entity_id'] for row in ha_api.get_states()
                        if eligible(row['entity_id']))
    if devices or areas:
        registry = ha_api.get_entity_registry()
        device_areas = {row['id']: row.get('area_id')
                        for row in ha_api.get_device_registry()} if areas else {}
        by_device = {device: set() for device in devices}
        by_area = {area: set() for area in areas}
        for row in registry:
            eid = row['entity_id']
            if not eligible(eid):
                continue
            area = row.get('area_id') or device_areas.get(row.get('device_id'))
            if row.get('device_id') in devices:
                by_device[row['device_id']].add(eid)
            if area in areas:
                by_area[area].add(eid)
        if areas:
            for area in ha_api.get_area_map():
                if area.get('id') in areas:
                    by_area[area['id']].update(eid for eid in area.get('entities') or []
                                               if eligible(eid))
        for selector, members in (*by_device.items(), *by_area.items()):
            if not members:
                raise ValueError(f'The target {selector} could not be expanded to any entities.')
            entities.update(members)
    return set(_entity_ids(entities))


def call_targets(domain: str, service: str, data: dict) -> set[str]:
    """Named script services always include the script, even with forged variables."""
    entity_ids = targets(data, domain)
    if domain == 'script' and service not in ('turn_on', 'turn_off', 'toggle'):
        entity_ids.add(f'script.{service}')
    return entity_ids


def kinds_for(entity_ids: Iterable[str]) -> tuple[str, ...]:
    """Use live attributes and recursively judge scripts/scenes by their effects."""
    from services import control_scripts, ha_api

    states = {row['entity_id']: row for row in ha_api.get_states()}
    kinds = set()

    def classify(entity_id, direct=False):
        state = states.get(entity_id)
        kind = kind_of(entity_id, (state.get('attributes') or {}) if state else None)
        if kind is not None:
            kinds.add(kind)
        elif direct:
            kinds.add('unsupported')

    for entity_id in _entity_ids(entity_ids):
        if entity_id.partition('.')[0] in ('script', 'scene'):
            touched, reasons = control_scripts.touched(entity_id)
            if reasons:
                kinds.update(KINDS)
            for target in _entity_ids(touched):
                # Script analysis already marks directly named, unclassifiable
                # effects unreadable; kind-less search/expansion leaves can drop.
                classify(target)
        else:
            classify(entity_id, direct=True)
    return tuple(kind for kind in (*KINDS, 'unsupported') if kind in kinds)


def _check_kinds(who: Who, kinds: Iterable[str], settings: dict | None) -> Decision:
    from services import scope, storage

    kinds = tuple(kinds)
    decision = decide(who, kinds, rules(settings))
    if not decision.allowed and decision.needs is None:
        return decision
    if 'media' in kinds and who.member_id:
        member = storage.get_member(who.member_id)
        if not member or not scope.can_see(member, 'music'):
            return Decision(False, None, kinds, 'Your access does not include music control; ask a parent.')
    return decision


def check_kind(who: Who, kind: str, settings: dict | None = None) -> Decision:
    """Authorize an entity-less control frame against the current household grid."""
    try:
        return _check_kinds(who, (kind,), settings)
    except Exception:
        return Decision(False, None, (kind,), 'Home Assistant could not answer that request.')


def check(who: Who, entity_ids: Iterable[str], settings: dict | None = None) -> Decision:
    """A failed HA or settings read must never grant control or escape to callers."""
    try:
        entity_ids = _entity_ids(entity_ids)
        if not entity_ids:
            return Decision(False, None, (), 'Name the device to control.')
        return _check_kinds(who, kinds_for(entity_ids), settings)
    except Exception:
        return Decision(False, None, (), 'Home Assistant could not answer that request.')


def guard(request, entity_ids: Iterable[str]) -> None:
    """Consume identity only for an action, returning the shared HTTP refusal."""
    from fastapi import HTTPException

    decision = check(who_from_request(request.headers, request.query_params), entity_ids)
    if not decision.allowed:
        raise HTTPException(status_code=403, detail={
            'message': decision.message, 'needs': decision.needs, 'kinds': decision.kinds,
        })


def offered(who: Who, entity_id: str, settings: dict | None = None) -> bool:
    """A tile offers an action when allowed now or available after identification."""
    decision = check(who, (entity_id,), settings)
    return decision.allowed or decision.needs is not None
