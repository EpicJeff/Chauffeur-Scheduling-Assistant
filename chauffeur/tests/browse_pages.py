"""A tiny site for the runner's tests, served on 127.0.0.1 by a thread. A
second hostname (localhost) plays the 'other domain'."""
import http.server
import threading

PAGES = {
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
}


class H(http.server.BaseHTTPRequestHandler):
    port = 0

    def do_GET(self):
        path = self.path.split('?')[0]
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
