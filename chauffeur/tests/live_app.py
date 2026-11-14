"""The app, actually SERVED, with a real browser pointed at it.

Some claims about this app only exist at runtime in a layout engine. Which
lists a page draws is decided by Alpine out of a fetch; whether a grid puts
three blocks across depends on the width of the box; and whether a click
actually removes a row depends on what `this` was bound to when the handler
ran. jsdom does no layout and a source assertion cannot see any of it — the
remove-an-item bug (v2.352.0) shipped past a template that read perfectly and
a payload contract that was correct, because the handler was invoked with the
wrong receiver, threw into Alpine's catch, and was logged rather than raised.

So: bind a port, run uvicorn on a thread, hand back a playwright factory. Every
caller SKIPS rather than fails when playwright is missing, the same bargain the
node probes make — a suite that cannot run without a browser download is a
suite people stop running.

    served = live_app(seed)          # None -> skipped, and it said so
    if served is None:
        return
    with served.browser() as page:
        page.goto(served.url('meals'))

`seed` is called before the server starts, with `storage` already pointed at
this process's temp data dir by whichever test module imported it first.
"""
import os
import socket
import sys
import threading
import time
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


from services.win_loopback import install as _install_bounded_socketpair  # noqa: E402

_install_bounded_socketpair()

_RETRY_NAV = ('ERR_CONNECTION_TIMED_OUT', 'ERR_CONNECTION_RESET', 'ERR_CONNECTION_REFUSED', 'Timeout')


def goto_retry(page, url, tries=3, **kw):
    """page.goto that retries only on transient loopback connection errors."""
    for i in range(tries):
        try:
            return page.goto(url, **kw)
        except Exception as e:  # playwright Error
            if i == tries - 1 or not any(m in str(e) for m in _RETRY_NAV):
                raise
            time.sleep(1.0 + i)


def _free_port():
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _patch_page_goto():
    """Make every Page.goto in the live suites retry transient loopback errors."""
    from playwright.sync_api import Page
    if getattr(Page.goto, '_chauffeur_retry', False):
        return
    orig = Page.goto

    def goto(self, url, **kw):
        # A page's later sub-resource can stall on this PC's loopback; tests wait for
        # their own readiness signal, so navigation only needs the document parsed.
        kw.setdefault('wait_until', 'domcontentloaded')
        for i in range(3):
            try:
                return orig(self, url, **kw)
            except Exception as e:
                if i == 2 or not any(m in str(e) for m in _RETRY_NAV):
                    raise
                time.sleep(1.0 + i)
    goto._chauffeur_retry = True
    Page.goto = goto


def live_app(seed=None, boot_timeout=50.0):
    """Serve the app on a free port. Returns None (having said why) when
    playwright is not installed."""
    try:
        from playwright.sync_api import sync_playwright
        _patch_page_goto()
    except ImportError:
        print("  skip  playwright not installed — the app was not served")
        return None

    if seed:
        seed()

    import uvicorn
    import main

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(
        main.app, host='127.0.0.1', port=port, log_level='error'))
    threading.Thread(target=server.run, daemon=True).start()
    deadline = time.time() + boot_timeout
    while not server.started and time.time() < deadline:
        time.sleep(0.2)
    if not server.started:
        raise AssertionError("the app never came up")

    class _Browser:
        """A chromium page, and a record of everything that went wrong in it.

        `errors` is the point. An Alpine handler that throws is CAUGHT by
        Alpine and logged, so a broken button looks exactly like a button
        nobody pressed — every scenario here asserts the list is empty.
        """
        def __init__(self, page_kw=None, launch_args=None):
            self._pw = None
            self._b = None
            self._page_kw = dict(page_kw or {})
            self._launch_args = launch_args
            self.errors = []

        def __enter__(self):
            self._pw = sync_playwright().start()
            self._b = self._pw.chromium.launch(args=self._launch_args)
            page = self._b.new_page(viewport={'width': 1400, 'height': 1000},
                                    **self._page_kw)
            page.on('pageerror', lambda e: self.errors.append(str(e)))
            page.on('console',
                    lambda m: m.type == 'error' and self.errors.append(m.text))
            self.page = page
            return page

        def __exit__(self, *exc):
            try:
                self._b.close()
            finally:
                self._pw.stop()
            return False

    handle = types.SimpleNamespace(
        port=port,
        url=lambda path='': f'http://127.0.0.1:{port}/{path.lstrip("/")}',
        stop=lambda: setattr(server, 'should_exit', True),
    )
    holder = {}

    def browser(*, launch_args: list[str] | None = None, **page_kw):
        """A page, plus its error record. Keywords ride straight through to
        Playwright's `new_page` (`has_touch=True` for a touch surface --
        the wall panel is one, and a gesture handler that only works under
        a mouse is a handler that does not ship)."""
        holder['b'] = _Browser(page_kw, launch_args)
        return holder['b']

    handle.browser = browser
    handle.errors = lambda: holder['b'].errors if 'b' in holder else []
    return handle
