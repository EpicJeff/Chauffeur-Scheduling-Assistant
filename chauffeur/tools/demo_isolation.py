"""Demo-only, stdlib isolation shared by live capture and decoy regressions.

Install before service imports. Denials contain no paths or credential values.
Audit counters record attempted operations, including those refused before I/O.
"""
from collections import Counter
from contextlib import contextmanager
import datetime as dt
import errno
import importlib.machinery
import ipaddress
import os
from pathlib import Path
import socket
import sys
import tempfile
import time
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DEMO_TIMEZONE = 'America/New_York'
DEMO_IDS = frozenset(('avery', 'jordan', 'pip', 'milo'))
# No wildcard prefixes: future integration variables must remain absent.
ENV_ALLOWLIST = frozenset(('SYSTEMROOT', 'WINDIR', 'SYSTEMDRIVE', 'COMSPEC',
    'PATH', 'PATHEXT', 'PROCESSOR_ARCHITECTURE', 'PROCESSOR_IDENTIFIER',
    'NUMBER_OF_PROCESSORS', 'LANG', 'LC_ALL'))


def worker_environment(data, inherited=None):
    inherited = os.environ if inherited is None else inherited
    source = {key.upper(): value for key, value in inherited.items()}
    env = {key: source[key] for key in ENV_ALLOWLIST if key in source}
    # Keep the installed browser cache, but give Python/Node/Chromium an empty
    # profile rather than credential-bearing OS home/config directories.
    cache = source.get('PLAYWRIGHT_BROWSERS_PATH')
    if not cache:
        cache = str(Path(source.get('LOCALAPPDATA', str(Path.home() / '.cache'))) /
                    ('ms-playwright' if os.name == 'nt' else 'ms-playwright'))
    profile = str(Path(data) / 'profile')
    env.update(CHAUFFEUR_DATA_DIR=str(data), CHAUFFEUR_STORAGE='sqlite',
        TEMP=str(data), TMP=str(data), TMPDIR=str(data), HOME=profile, USERPROFILE=profile,
        APPDATA=str(Path(profile) / 'Roaming'), LOCALAPPDATA=str(Path(profile) / 'Local'),
        XDG_CONFIG_HOME=str(Path(profile) / 'config'), XDG_CACHE_HOME=str(Path(profile) / 'cache'),
        PLAYWRIGHT_BROWSERS_PATH=cache, PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1',
        # Windows CRT accepts POSIX TZ syntax, not an IANA zone name.
        TZ='EST5EDT' if os.name == 'nt' else DEMO_TIMEZONE)
    return env


def fresh_data_folder():
    """Reject before importing storage, scanning or writing a normal data dir."""
    value = os.environ.get('CHAUFFEUR_DATA_DIR')
    if not value:
        raise RuntimeError('demo seed requires a fresh chauffeur_demo_ folder')
    folder = Path(value).absolute()
    if (not folder.name.startswith('chauffeur_demo_') or not folder.is_dir()
            or folder.is_symlink() or getattr(folder, 'is_junction', lambda: False)()
            or folder != folder.resolve()):
        raise RuntimeError('demo seed requires a fresh chauffeur_demo_ folder')
    if any(folder.iterdir()):
        raise RuntimeError('demo seed requires an empty chauffeur_demo_ folder')
    return folder


def assert_household(storage, directory):
    root = Path(directory).resolve()
    paths = [storage.DB_PATH, storage.SQLITE_PATH, getattr(storage.db, 'path', storage.DB_PATH)]
    if any(not Path(path).resolve().is_relative_to(root) for path in paths):
        raise RuntimeError('storage is outside this demo run')
    if storage.BACKEND == 'sqlite':
        files = storage.db.connection().execute('PRAGMA database_list').fetchall()
        if any(not file or not Path(file).resolve().is_relative_to(root) for _seq, _name, file in files):
            raise RuntimeError('database connection is outside this demo run')
    members = storage.get_all_members(include_system=True, include_archived=True)
    if len(members) != 4 or {member.get('id') for member in members} != DEMO_IDS:
        raise RuntimeError('household is not exactly the four demo members')
    if any(member.get('name') != member['id'].title() for member in members):
        raise RuntimeError('household names are not invented demo names')


@contextmanager
def fixed_clock(moment):
    """Freeze app wall clocks; leave monotonic/process/network timers alone."""
    original_datetime, original_date = dt.datetime, dt.date
    original_localtime = time.localtime
    zone = ZoneInfo(DEMO_TIMEZONE)
    class DateTimeMeta(type):
        def __instancecheck__(cls, value):
            return isinstance(value, original_datetime)
    class DateMeta(type):
        def __instancecheck__(cls, value):
            return isinstance(value, original_date)
    class DemoDateTime(original_datetime, metaclass=DateTimeMeta):
        @classmethod
        def fromtimestamp(cls, timestamp, tz=None):
            value = original_datetime.fromtimestamp(timestamp, tz or zone)
            return cls(value.year, value.month, value.day, value.hour, value.minute,
                       value.second, value.microsecond, tzinfo=tz, fold=value.fold)
        def astimezone(self, tz=None):
            source = self if self.tzinfo is not None else self.replace(tzinfo=zone)
            return original_datetime.astimezone(source, tz or zone)
        @classmethod
        def now(cls, tz=None):
            value = cls.fromtimestamp(moment.timestamp(), tz or moment.tzinfo)
            return value if tz is not None else value.replace(tzinfo=None)
        @classmethod
        def utcnow(cls):
            return cls.now(dt.timezone.utc).replace(tzinfo=None)
    class DemoDate(original_date, metaclass=DateMeta):
        @classmethod
        def today(cls):
            return cls(moment.year, moment.month, moment.day)
    bindings = []
    for name, module in list(sys.modules.items()):
        if module is None or not (name == 'main' or name.startswith('services.') or name == 'tools.demo_seed'):
            continue
        for key, value in list(vars(module).items()):
            replacement = DemoDateTime if value is original_datetime else DemoDate if value is original_date else None
            if replacement is not None:
                bindings.append((module, key, value))
                setattr(module, key, replacement)
    dt.datetime, dt.date = DemoDateTime, DemoDate
    time.localtime = lambda seconds=None: original_localtime(moment.timestamp() if seconds is None else seconds)
    try:
        yield
    finally:
        dt.datetime, dt.date = original_datetime, original_date
        time.localtime = original_localtime
        for module, key, value in bindings:
            setattr(module, key, value)


def _nothing(*args, **kwargs):
    return None


def _demo_option(key, default=None):
    if any(word in key.lower() for word in ('key', 'token', 'secret', 'password', 'credential')):
        return None
    from services import storage
    return storage.get_settings().get(key, default)


# Import-time overrides ensure `from service import resolver` also receives
# the empty resolver. The audit hook independently prevents fallback reads.
CREDENTIAL_RESOLVERS = {
    'services.calendar': dict(get_calendar_service=_nothing),
    'services.maps': dict(get_mapbox_api_key=_nothing, get_map_option=_demo_option,
                         get_home_location=lambda: 'Demo home'),
    'services.travel_api': dict(get_serpapi_key=_nothing),
    'services.ha_api': dict(_base_and_token=lambda *a, **k: (None, None), _request=_nothing),
    'services.walmart': dict(_option=_nothing, _local_file=_nothing,
        get_credentials=lambda: dict(consumer_id='', key_version='', private_key=None, configured=False)),
    'services.model_pools': dict(api_key_for=lambda *a, **k: '', api_key_for_pool=lambda *a, **k: '',
        credentials=lambda *a, **k: ('', ''), has_credentials=lambda *a, **k: False),
    'services.web': dict(_serpapi_key=lambda: '', _brave_key=lambda: ''),
    'services.meals': dict(unsplash_key=lambda: ''),
    'google.auth': dict(default=lambda *a, **k: (None, None),
                        load_credentials_from_file=lambda *a, **k: (None, None)),
    'google.oauth2.service_account': {'Credentials.from_service_account_file': classmethod(_nothing),
                                     'Credentials.from_service_account_info': classmethod(_nothing)},
}


def _replace_credentials(module, replacements):
    for key, replacement in replacements.items():
        target = module
        parts = key.split('.')
        for part in parts[:-1]:
            if not hasattr(target, part):
                raise RuntimeError(f'demo credential resolver missing: {module.__name__}.{key}')
            target = getattr(target, part)
        if not hasattr(target, parts[-1]):
            raise RuntimeError(f'demo credential resolver missing: {module.__name__}.{key}')
        setattr(target, parts[-1], replacement)


class CredentialImports:
    def find_spec(self, fullname, path=None, target=None):
        replacements = CREDENTIAL_RESOLVERS.get(fullname)
        if replacements is None:
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is None or spec.loader is None:
            raise RuntimeError('demo credential isolation could not install')
        loader = spec.loader
        class Loader:
            def create_module(self, spec):
                return loader.create_module(spec)
            def exec_module(self, module):
                loader.exec_module(module)
                _replace_credentials(module, replacements)
        spec.loader = Loader()
        return spec


class IsolationGuard:
    def __init__(self, data, stage):
        self.data, self.stage = Path(data).resolve(), Path(stage).resolve()
        self.counts, self.blocked = Counter(), Counter()
        self.active = True
        self.runtime = tuple({Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve()})
        self.public = tuple(ROOT / name for name in ('static', 'templates', 'twin_kits', 'twin_library'))
        self.code = tuple(ROOT / name for name in ('services', 'models', 'solver', 'tools', 'tests'))

    def refuse(self, event):
        self.blocked[event] += 1
        raise PermissionError(errno.EACCES, 'demo isolation refused ' + event)

    def path(self, value, event):
        if isinstance(value, int):  # an already-open pipe/descriptor
            return None
        value = os.fsdecode(value if value is not None else os.curdir)
        if value.startswith(('\\\\', '//')):
            self.refuse(event)  # do not resolve a UNC path over the network
        return Path(value).resolve()

    def file_allowed(self, path, writing=False, directory=False):
        if path is None or path == Path(os.devnull).resolve():
            return True
        if path.is_relative_to(self.data) or path.is_relative_to(self.stage):
            return True
        if writing:
            return False
        if (any(path.is_relative_to(root) for root in self.runtime)
                and path.suffix.lower() in ('.py', '.pyc', '.pyd', '.dll')):
            return True  # e.g. google/auth/credentials.py is code, not a credential
        name = path.name.lower()
        if (name in ('options.json', '.env') or name.startswith('.env.')
                or any(word in name for word in ('credential', 'api_key', 'private_key', 'token.json'))
                or path.suffix.lower() in ('.pem', '.key', '.sqlite3', '.sqlite', '.db')):
            return False
        if any(path.is_relative_to(root) for root in self.runtime):
            return True
        if any(path.is_relative_to(root) for root in self.public):
            return True
        if path == ROOT / 'services' / 'builtin_boards.json':
            return True
        if any(path.is_relative_to(root) for root in self.code):
            if path.is_relative_to(ROOT / 'tests' / 'fixtures'):
                return False
            return directory or path.suffix.lower() in ('.py', '.pyc', '.pyd', '.dll')
        return path == ROOT if directory else path == ROOT / 'config.yaml' or path == ROOT / 'main.py'

    @staticmethod
    def loopback(host):
        if isinstance(host, bytes):
            host = host.decode('ascii', errors='replace')
        if host == 'localhost':
            return True
        try:
            address = ipaddress.ip_address(host)
            return address.is_loopback or bool(getattr(address, 'ipv4_mapped', None)
                                               and address.ipv4_mapped.is_loopback)
        except (ValueError, TypeError):
            return False

    def audit(self, event, args):
        if not self.active or event not in ('open', 'sqlite3.connect', 'os.scandir', 'os.listdir',
                'socket.connect', 'socket.getaddrinfo', 'socket.getnameinfo', 'socket.gethostbyname',
                'socket.gethostbyaddr', 'socket.sendto', 'socket.bind'):
            return
        self.counts[event] += 1
        if event == 'open':
            path = self.path(args[0], event)
            writing = bool(args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            if not self.file_allowed(path, writing=writing):
                self.refuse(event)
        elif event == 'sqlite3.connect':
            if args[0] == ':memory:':
                return
            value = os.fsdecode(args[0])
            if value.startswith('file:'):
                from urllib.parse import unquote
                value = unquote(value[5:].split('?')[0])
            path = self.path(value, event)
            if path is None or not path.is_relative_to(self.data):
                self.refuse(event)
        elif event in ('os.scandir', 'os.listdir'):
            if not self.file_allowed(self.path(args[0], event), directory=True):
                self.refuse(event)
        else:
            address = args[1] if event in ('socket.connect', 'socket.sendto', 'socket.bind') else args[0]
            host = address[0] if isinstance(address, tuple) else address
            if not self.loopback(host):
                self.refuse(event)


def _async_connect_guards():
    """Guard before asyncio's native ConnectEx and selector socket machinery."""
    from asyncio.selector_events import BaseSelectorEventLoop
    methods = [(BaseSelectorEventLoop, 'sock_connect', True)]
    if os.name == 'nt':
        from asyncio.proactor_events import BaseProactorEventLoop
        from asyncio.windows_events import IocpProactor
        methods.extend(((BaseProactorEventLoop, 'sock_connect', True), (IocpProactor, 'connect', False)))
    originals = []
    for owner, name, asynchronous in methods:
        original = getattr(owner, name)
        def wrap(original, asynchronous):
            if asynchronous:
                async def connect(self, sock, address):
                    sys.audit('socket.connect', sock, address)
                    return await original(self, sock, address)
            else:
                def connect(self, sock, address):
                    sys.audit('socket.connect', sock, address)
                    return original(self, sock, address)
            return connect
        originals.append((owner, name, original))
        setattr(owner, name, wrap(original, asynchronous))
    return originals


@contextmanager
def worker_isolation(data, stage, *, permanent=False):
    """Use this very guard in live captures and in planted-decoy tests."""
    if any(name == 'main' or name == 'services' or name.startswith('services.') for name in sys.modules):
        raise RuntimeError('demo isolation must be installed before service imports')
    previous = dict(os.environ)
    previous_tempdir = tempfile.tempdir
    previous_bytecode = sys.dont_write_bytecode
    environment = worker_environment(data)
    guard = IsolationGuard(data, stage)
    finder = CredentialImports()
    originals = {name: getattr(socket, name) for name in
                 ('getaddrinfo', 'getnameinfo', 'gethostbyname', 'gethostbyname_ex', 'gethostbyaddr')}
    connects = {name: getattr(socket.socket, name) for name in ('connect', 'connect_ex', 'sendto')}
    def lookup(name):
        def call(host, *args, **kwargs):
            event = 'socket.' + ('gethostbyname' if name == 'gethostbyname_ex' else name)
            sys.audit(event, host, *args)
            # Never consult a resolver/hosts file for the localhost alias.
            if isinstance(host, tuple) and host[0] == 'localhost':
                host = ('127.0.0.1', *host[1:])
            return originals[name]('127.0.0.1' if host == 'localhost' else host, *args, **kwargs)
        return call
    def connect(name):
        def call(sock, *args, **kwargs):
            address = args[-1] if name == 'sendto' else args[0]
            event = 'socket.sendto' if name == 'sendto' else 'socket.connect'
            sys.audit(event, sock, address)
            if isinstance(address, tuple) and address[0] == 'localhost':
                address = (('::1' if sock.family == socket.AF_INET6 else '127.0.0.1'), *address[1:])
                args = (*args[:-1], address) if name == 'sendto' else (address, *args[1:])
            return connects[name](sock, *args, **kwargs)
        return call
    installed = False
    async_originals = []
    try:
        os.environ.clear()
        os.environ.update(environment)
        tempfile.tempdir = str(data)  # also override a cached gettempdir()
        sys.dont_write_bytecode = True
        sys.addaudithook(guard.audit)
        sys.meta_path.insert(0, finder)
        # Also cover a test caller that imported a resolver before this context.
        for name, replacements in CREDENTIAL_RESOLVERS.items():
            if name in sys.modules:
                _replace_credentials(sys.modules[name], replacements)
        for name in originals:
            setattr(socket, name, lookup(name))
        for name in connects:
            setattr(socket.socket, name, connect(name))
        async_originals = _async_connect_guards()
        installed = True
        yield guard
    finally:
        try:
            if not permanent or not installed:
                guard.active = False
                if finder in sys.meta_path:
                    sys.meta_path.remove(finder)
                for name, original in originals.items():
                    setattr(socket, name, original)
                for name, original in connects.items():
                    setattr(socket.socket, name, original)
                for owner, name, original in async_originals:
                    setattr(owner, name, original)
        finally:
            os.environ.clear()
            os.environ.update(previous)
            tempfile.tempdir = previous_tempdir
            sys.dont_write_bytecode = previous_bytecode
