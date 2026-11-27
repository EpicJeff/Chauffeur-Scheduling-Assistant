"""Shared public HTTP address check; resolver is replaceable for offline tests.

Known limit: DNS rebinding between this check and the connection is not prevented.
"""
import ipaddress
import socket
from urllib.parse import urlsplit

_resolve = socket.getaddrinfo

def check_public(url: str, error=ValueError, *, resolver=None) -> str:
    parts = urlsplit(url)
    if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password:
        raise error('That address must be a public HTTP or HTTPS address.')
    host = parts.hostname
    if host.lower().rstrip('.') == 'localhost':
        raise error('That address is not a public one.')
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    infos = [(None, None, None, None, (str(literal), 0))] if literal else (resolver or _resolve)(
        host, parts.port or (443 if parts.scheme == 'https' else 80), proto=socket.IPPROTO_TCP)
    if not infos:
        raise OSError(f'Could not resolve {host}')
    for info in infos:
        address = ipaddress.ip_address(str(info[4][0]).split('%')[0])
        mapped = getattr(address, 'ipv4_mapped', None)
        for ip in (address, mapped) if mapped else (address,):
            if not ip.is_global or ip.is_multicast:
                raise error('That address is not a public one.')
    return url
