"""Windows development only: a bounded, retried socket.socketpair.

Windows loopback on the development machine intermittently loses TCP handshakes, and
CPython's socket._fallback_socketpair then blocks forever in accept(). asyncio's
proactor loop calls socket.socketpair() for its self-pipe, so every TestClient
request and every served test could hang (seen 2026-11-13 as "TestClient files hang
at exit or first request"). Imported by main.py; does nothing off Windows, so the
Home Assistant add-on (Linux) is unaffected.
"""
import socket
import sys


def install(tries=5, step_timeout=5.0):
    """Windows loopback here intermittently loses TCP handshakes, and CPython's
    socket._fallback_socketpair then blocks forever in accept(). asyncio's
    proactor loop calls socket.socketpair() for its self-pipe, so replace it
    with the same construction but bounded and retried."""
    if sys.platform != 'win32' or getattr(socket.socketpair, '_chauffeur_bounded', False):
        return

    def socketpair(family=socket.AF_INET, type=socket.SOCK_STREAM, proto=0):
        if family != socket.AF_INET or type != socket.SOCK_STREAM or proto != 0:
            raise ValueError("Only AF_INET, SOCK_STREAM, protocol zero are supported")
        last = None
        for _ in range(tries):
            lsock = socket.socket(family, type, proto)
            csock = ssock = None
            try:
                lsock.bind(('127.0.0.1', 0))
                lsock.listen()
                addr, port = lsock.getsockname()[:2]
                lsock.settimeout(step_timeout)
                csock = socket.socket(family, type, proto)
                csock.settimeout(step_timeout)
                csock.connect((addr, port))
                ssock, _ = lsock.accept()
                if (ssock.getsockname() != csock.getpeername()
                        or csock.getsockname() != ssock.getpeername()):
                    raise ConnectionError("Unexpected peer connection")
                ssock.setblocking(True)
                csock.setblocking(True)
                lsock.close()
                return ssock, csock
            except (socket.timeout, OSError) as e:
                last = e
                for x in (ssock, csock):
                    if x is not None:
                        x.close()
            finally:
                lsock.close()
        raise last

    socketpair._chauffeur_bounded = True
    socket.socketpair = socketpair


install()
