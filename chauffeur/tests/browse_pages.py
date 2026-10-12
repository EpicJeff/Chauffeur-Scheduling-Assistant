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
    # Writes the browser's own location and timezone into the page.
    '/where': ('<h1>Where am I</h1><div id="pos">pending</div><div id="tz"></div><script>'
               'document.getElementById("tz").textContent = Intl.DateTimeFormat().resolvedOptions().timeZone;'
               'navigator.geolocation.getCurrentPosition(p => { document.getElementById("pos").textContent = p.coords.latitude.toFixed(2) + "," + p.coords.longitude.toFixed(2); },'
               ' e => { document.getElementById("pos").textContent = "denied:" + e.code; });</script>'),
    # A normal form with reCAPTCHA's invisible badge and its legal line, as most forms have: not a wall.
    '/zipdialog': ('<h1>Schedule service</h1><div role="dialog"><p>Enter your ZIP to see availability</p>'
                   '<label>ZIP Code<input name="postal"></label><button type="button">Continue</button></div>'
                   '<p class="small">This site is protected by reCAPTCHA and the Google Privacy Policy and Terms of Service apply.</p>'
                   '<iframe src="/anchor?k=recaptcha&size=invisible" title="reCAPTCHA" style="width:256px;height:60px"></iframe>'
                   '<p>Lots of other page content here. Why choose us. Certified technicians. Genuine parts. Reliable service. '
                   + 'More copy. ' * 120 + '</p>'),
    # A page whose HTML arrives at once but whose blocking script takes seconds: DOMContentLoaded is late.
    '/hang': '<h1>Slow site</h1><script src="/slowjs"></script><p>content</p>',
    # --- submit gate fixtures (spec 2026-10-11) ---
    # A booking form: slot radios, a price line, Book appointment (type=submit, POSTs to /booked), Pay now.
    '/booking': ('<h1>Choose a slot</h1><form id="bf" action="/booked" method="post">'
                 '<p>Trip charge $114.95. Parts and labor not included.</p>'
                 '<label><input type="radio" name="slot" value="tue" checked> Tue, Oct 20 8AM-12PM</label>'
                 '<label><input type="radio" name="slot" value="thu"> Thu, Oct 22 8AM-12PM</label>'
                 '<label>Notes<input name="notes" value=""></label>'
                 '<button type="submit" id="book">Book appointment</button>'
                 '<button type="button" id="pay">Pay now</button></form>'),
    # The same form with Thursday checked and the price moved: the "page changed" fixture.
    '/booking2': ('<h1>Choose a slot</h1><form id="bf" action="/booked" method="post">'
                  '<p>Trip charge $124.95. Parts and labor not included.</p>'
                  '<label><input type="radio" name="slot" value="tue"> Tue, Oct 20 8AM-12PM</label>'
                  '<label><input type="radio" name="slot" value="thu" checked> Thu, Oct 22 8AM-12PM</label>'
                  '<label>Notes<input name="notes" value=""></label>'
                  '<button type="submit" id="book">Book appointment</button></form>'),
    # An unfamiliar final label on a form holding the person's data.
    '/sendapp': ('<h1>Application</h1><form action="/booked" method="post"><label>Zip *<input name="zip" value="27519"></label>'
                 '<button type="submit" id="send">Send application</button></form>'),
    # An agreement form whose submit control reads Accept: commitment text in the scope.
    '/agree': ('<h1>Terms</h1><form action="/booked" method="post"><p>By clicking Accept you authorize the service visit. I agree to the terms.</p>'
               '<label><input type="checkbox" name="ok" checked> I agree</label><button type="submit" id="accept">Accept</button></form>'),
    # A cookie banner: Accept as a type=button outside any form, no state in its scope.
    '/cookie': ('<h1>Welcome</h1><div role="dialog"><p>We use cookies.</p><button type="button" id="accept">Accept</button></div>'
                '<p>Page content. <a href="/start">Service</a></p>'),
    # A JS button outside any form beside a custom aria-checked slot picker: the only button in its scope.
    '/lockin': ('<h1>Pick a slot</h1><section id="picker"><p>Trip charge $114.95</p>'
                '<div role="radiogroup"><div role="radio" aria-checked="false" id="s1">Tue, Oct 20 8AM-12PM</div>'
                '<div role="radio" aria-checked="true" id="s2">Thu, Oct 22 8AM-12PM</div></div>'
                '<div role="button" id="lock" tabindex="0">Lock it in</div></section>'
                '<script>document.getElementById("lock").addEventListener("click", () => { location.href = "/thanks"; });</script>'),
    # The appliance-tile form the device run saw: eight sibling buttons inside a form with filled fields.
    '/tiles': ('<h1>Select appliance</h1><form action="/slots" method="get"><input type="hidden" name="first" value="Jeff">'
               '<label>Zip<input name="zip" value="27519"></label><div class="tiles">'
               + ''.join(f'<button type="submit" name="appliance" value="{a}" id="t{i}">{a}</button>'
                         for i, a in enumerate(['Refrigerator', 'Dishwasher', 'Range', 'Oven', 'Washer', 'Dryer', 'Microwave', 'Other']))
               + '</div></form>'),
    '/slots': '<h1>Slots</h1><a id="tobook" href="/booking">Choose a slot</a>',
    # A long form whose price line sits past 1,500 characters of text.
    '/longform': ('<h1>Review</h1><form action="/booked" method="post"><p>' + 'Lots of copy about the visit. ' * 70
                  + '</p><p>Total due at visit: $114.95</p><label><input type="radio" name="slot" value="tue" checked> Tue</label>'
                  '<button type="submit" id="book">Book appointment</button></form>'),
    # Continue as the last button under a total: a review-and-commit shape.
    '/pricedcontinue': ('<h1>Review your request</h1><form action="/booked" method="post"><p>Total: $114.95</p>'
                        '<label><input type="radio" name="slot" value="tue" checked> Tue</label><button type="submit" id="cont">Continue</button></form>'),
    # A multi-step Continue on a slot page with no price: runs.
    '/stepcontinue': ('<h1>Step 2 of 3</h1><form action="/booking" method="get"><label><input type="radio" name="slot" value="tue" checked> Tue</label>'
                      '<button type="submit" id="cont">Continue</button></form>'),
    '/thanks': '<h1>Thank you for your booking</h1><p>Confirmation number 12345. Tue, Oct 20 8AM-12PM.</p>',
    '/rejected': '<h1>Sorry</h1><p class="error">That slot was just taken. Pick another.</p><a href="/booking">Back</a>',
    # A payment page after the press.
    '/payafter': '<h1>Payment</h1><form><input name="cardnumber" autocomplete="cc-number"><input name="cvc" placeholder="CVC"><button type="submit">Pay now</button></form>',
    # A saved-card Buy now: no card field, pay word on the control.
    '/buynow': '<h1>Order</h1><form action="/booked" method="post"><p>Card ending 4242</p><button type="submit" id="buy">Buy now</button></form>',
    # An icon-only submit control (aria-label only).
    '/iconbtn': ('<h1>Request</h1><form action="/booked" method="post"><label>Zip<input name="zip" value="27519"></label>'
                 '<button type="submit" id="icon" aria-label="Submit request"><svg width="16" height="16"></svg></button></form>'),
    # A disabled Book button: nothing happens on a click.
    '/disabledbook': ('<h1>Choose a slot</h1><form action="/booked" method="post"><p>$114.95</p>'
                      '<button type="submit" id="book" disabled>Book appointment</button></form>'),
    # A third-party widget in an iframe.
    '/framedbook': '<h1>Schedule</h1><iframe id="w" src="/booking" style="width:600px;height:400px"></iframe>',
    # The device sequence, start to finish: contact form -> tiles -> slots -> booking.
    '/fulltrip': ('<h1>Step 1</h1><form action="/tiles" method="get">'
                  '<label>First Name *<input name="first" required></label>'
                  '<label>Email *<input name="email" type="email" required></label>'
                  '<label>Zip *<input name="zip" required></label>'
                  '<button type="submit" id="next">Next: Select Appliance</button></form>'),
}


class H(http.server.BaseHTTPRequestHandler):
    port = 0
    posts = []

    def do_POST(self):
        path = self.path.split('?')[0]
        length = int(self.headers.get('Content-Length') or 0)
        self.rfile.read(length)
        if path == '/booked':
            H.posts.append(path)
            self.send_response(303)
            self.send_header('Location', '/thanks' if len(H.posts) % 7 != 0 else '/rejected')
            self.end_headers()
            return
        self.send_response(404)
        self.end_headers()

    def do_GET(self):
        path = self.path.split('?')[0]
        if path == '/posts':
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(str(len(H.posts)).encode())
            return
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
