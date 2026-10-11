"""A tiny site for the runner's tests, served on 127.0.0.1 by a thread. A
second hostname (localhost) plays the 'other domain'."""
import http.server
import threading

PAGES = {
    '/': '<h1>Home</h1><a href="/start">Service</a>',
    '/start': '<h1>Service</h1><a id="go" href="/form">Schedule service</a> <a id="away" href="http://localhost:{port}/other">Marketplace</a> <a id="redir" href="/redir">Partner</a>',
    '/form': ('<h1>Step 1</h1><form action="/form2" method="get">'
              '<label>First Name *<input name="first" required></label>'
              '<label>Email *<input name="email" type="email" required></label>'
              '<label>Zip *<input name="zip" required></label>'
              '<button type="submit" id="next">Next: Select Appliance</button></form>'),
    '/form2': '<h1>Step 2</h1><p>Earliest: Tue 8-noon. Trip charge $114.95</p><button id="book" type="button">Book appointment</button><button id="confirm" type="submit">Confirm</button>',
    '/pay': '<h1>Payment</h1><form><input name="cardnumber" autocomplete="cc-number"><input name="cvc" placeholder="CVC"></form>',
    '/captcha': '<h1>Check</h1><p>Please verify you are human</p><div id="recaptcha"><iframe src="/anchor?k=recaptcha" title="reCAPTCHA"></iframe></div>',
    '/anchor': '<input type="checkbox" id="recaptcha-anchor">',
    '/denied': '<h1>Access denied</h1><p>unusual traffic from your network</p>',
    '/other': '<h1>Other site</h1>',
    '/zip': '<h1>Where</h1><form><label>Zip *<input name="zip" required></label><button type="submit">Next</button></form>',
    '/confirmform': '<h1>Last step</h1><form action="/form2" method="get"><label>Zip *<input name="zip" required></label><button type="submit" id="c">Confirm</button></form>',
    '/withframe': '<h1>Framed</h1><iframe src="/redir" title="partner"></iframe><p>stay here</p>',
    '/topay': '<h1>Almost</h1><a id="cont" href="/pay">Continue</a>',
    '/locate': '<h1>Service areas</h1><label>ZIP Code<input name="postal"></label><button type="button">Find</button>',
    # A normal form with reCAPTCHA's invisible badge and its legal line, as most forms have: not a wall.
    '/zipdialog': ('<h1>Schedule service</h1><div role="dialog"><p>Enter your ZIP to see availability</p>'
                   '<label>ZIP Code<input name="postal"></label><button type="button">Continue</button></div>'
                   '<p class="small">This site is protected by reCAPTCHA and the Google Privacy Policy and Terms of Service apply.</p>'
                   '<iframe src="/anchor?k=recaptcha&size=invisible" title="reCAPTCHA" style="width:256px;height:60px"></iframe>'
                   '<p>Lots of other page content here. Why choose us. Certified technicians. Genuine parts. Reliable service. '
                   + 'More copy. ' * 120 + '</p>'),
    # A page whose HTML arrives at once but whose blocking script takes seconds: DOMContentLoaded is late.
    '/hang': '<h1>Slow site</h1><script src="/slowjs"></script><p>content</p>',
}


class H(http.server.BaseHTTPRequestHandler):
    port = 0

    def do_GET(self):
        path = self.path.split('?')[0]
        if path == '/slowjs':
            import time as _t
            _t.sleep(2.5)
            self.send_response(200)
            self.send_header('Content-Type', 'application/javascript')
            self.end_headers()
            self.wfile.write(b'window.slow = 1;')
            return
        if path == '/redir':
            self.send_response(302)
            self.send_header('Location', f'http://localhost:{self.port}/other')
            self.end_headers()
            return
        body = PAGES.get(path)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        body = body.replace('{port}', str(self.port))
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        self.wfile.write(f'<html><body>{body}</body></html>'.encode())

    def log_message(self, *a):
        pass


def serve():
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), H)
    H.port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]
