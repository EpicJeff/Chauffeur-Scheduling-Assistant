"""The Windows-only bounded socketpair that main.py installs (services/win_loopback.py)."""
import os
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services import win_loopback  # noqa: E402


def main():
    win_loopback.install()
    win_loopback.install()  # idempotent
    if sys.platform == 'win32':
        assert getattr(socket.socketpair, '_chauffeur_bounded', False), 'installed on Windows'
    a, b = socket.socketpair()
    try:
        a.sendall(b'ping')
        assert b.recv(4) == b'ping'
    finally:
        a.close(); b.close()
    import asyncio
    loop = asyncio.new_event_loop()  # the proactor self-pipe uses socketpair
    try:
        assert loop.run_until_complete(asyncio.sleep(0, result=7)) == 7
    finally:
        loop.close()
    print('ok   bounded socketpair works and asyncio loops start')
    print('1/1 passed')


if __name__ == '__main__':
    main()
