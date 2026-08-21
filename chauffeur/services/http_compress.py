"""Gzip for the responses that are safe to gzip, and nothing else.

The app had NO compression at all — discovered while measuring why shipping
`hass.states` to hosted cards felt expensive. It never was: 25 media players
with realistic attribute bags is 29.5 KB of JSON that gzips to 1.0 KB. The
cost was polling that JSON uncompressed once a minute. State JSON is close to
the most compressible data there is — the same keys repeat for every entity.

Starlette's own GZipMiddleware is deliberately not used. It compresses
streaming responses too, and this app streams for a living: three
`text/event-stream` endpoints (messages, chat, schedule progress) and an
ndjson one. Gzip buffers output until a block fills, so an SSE message can sit
in the compressor while the client sees nothing — live messaging traded for a
bandwidth win nobody asked for.

So the rule here is structural rather than a content-type list to maintain:

  * a SINGLE-SHOT response (one body frame, `more_body` false — every
    JSONResponse and rendered template) is compressed when the client accepts
    gzip, the type is texty and the body clears the size floor;
  * a STREAMING response (anything sending more than one frame — SSE, ndjson,
    FileResponse chunks) passes through untouched, by construction rather
    than by allowlist.

Static files stream and therefore stay uncompressed; they are versioned and
cached by the browser, so they are paid for once, not once a minute.
"""
import gzip

# Compress these, leave images/audio/zips alone — recompressing a JPEG wastes
# CPU to make it bigger.
_TEXTY = ('application/json', 'text/html', 'text/plain', 'text/css',
          'application/javascript', 'text/javascript', 'image/svg+xml',
          'application/manifest+json', 'application/xml')

# Below this, the gzip header costs more than it saves.
MIN_SIZE = 500


class SelectiveGzipMiddleware:
    def __init__(self, app, minimum_size: int = MIN_SIZE, level: int = 6):
        self.app = app
        self.minimum_size = minimum_size
        self.level = level

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        accepts = b''
        for k, v in scope.get('headers') or []:
            if k == b'accept-encoding':
                accepts = v
                break
        if b'gzip' not in accepts:
            return await self.app(scope, receive, send)

        state = {'start': None, 'decided': False}

        async def wrapped_send(message):
            if message['type'] == 'http.response.start':
                # Held back until the first body frame tells us whether this
                # is single-shot; nothing is sent yet.
                state['start'] = message
                return
            if message['type'] != 'http.response.body' or state['decided']:
                return await send(message)

            if message.get('more_body'):
                # Streaming. Release the held start untouched and get out of
                # the way for the rest of the response.
                state['decided'] = True
                await send(state['start'])
                return await send(message)

            # Single-shot response: one body frame, more_body false.
            state['decided'] = True
            start = state['start']
            body = message.get('body', b'')
            headers = [(k, v) for k, v in start['headers']]
            ctype = next((v for k, v in headers if k == b'content-type'), b'')
            already = any(k == b'content-encoding' for k, v in headers)
            texty = any(ctype.startswith(t.encode()) for t in _TEXTY)
            if texty and not already and len(body) >= self.minimum_size:
                body = gzip.compress(body, self.level)
                headers = [(k, v) for k, v in headers
                           if k not in (b'content-length', b'content-encoding')]
                headers.append((b'content-encoding', b'gzip'))
                headers.append((b'content-length', str(len(body)).encode()))
                headers.append((b'vary', b'Accept-Encoding'))
                start = dict(start, headers=headers)
                message = dict(message, body=body)
            await send(start)
            await send(message)

        await self.app(scope, receive, wrapped_send)
