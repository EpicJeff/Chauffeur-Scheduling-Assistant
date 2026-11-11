"""Extract complete pieces from named arrays in a partial JSON reply."""
import json


class Pieces:
    def __init__(self, paths):
        self.paths = dict(paths)
        self._stack = []
        self._started = False
        self._ended = False
        self._in_string = False
        self._escaped = False
        self._key_text = None
        self._item = None
        self._item_depth = None

    @property
    def stage(self):
        return next((self.paths[f['path']] for f in self._stack if f.get('named')), None)

    @property
    def pending(self):
        return self._item is not None

    @property
    def complete(self):
        return self._ended

    def feed(self, text):
        result = []
        for char in text:
            if self._ended:
                break
            if not self._started:
                if char != '{':
                    continue
                self._started = True

            if self._item is not None:
                self._item.append(char)

            if self._in_string:
                if self._key_text is not None:
                    self._key_text.append(char)
                if self._escaped:
                    self._escaped = False
                elif char == '\\':
                    self._escaped = True
                elif char == '"':
                    self._in_string = False
                    if self._key_text is not None:
                        try:
                            self._stack[-1]['key'] = json.loads(''.join(self._key_text))
                        except ValueError:
                            self._stack[-1]['key'] = None
                        self._key_text = None
                continue

            parent = self._stack[-1] if self._stack else None
            if char == '"':
                self._in_string = True
                if parent and parent['type'] == '{' and parent['key_next']:
                    self._key_text = ['"']
                continue

            if char in '{[':
                # Paths never traverse array items. A key named "walls" in a
                # level or in an unrelated array is still part of that item.
                path = '' if parent is None else None
                if parent and parent['type'] == '{' and parent['path'] is not None:
                    path = '.'.join(filter(None, (parent['path'], parent.get('key'))))
                frame = {'type': char, 'path': path, 'key_next': True}
                frame['named'] = char == '[' and path in self.paths
                self._stack.append(frame)
                if char == '{' and parent and parent.get('named') and self._item is None:
                    self._item = ['{']
                    self._item_depth = len(self._stack)
            elif char in '}]':
                if not parent or (parent['type'], char) not in (('{', '}'), ('[', ']')):
                    continue
                if self._item is not None and len(self._stack) == self._item_depth:
                    array = self._stack[-2]
                    try:
                        item = json.loads(''.join(self._item))
                    except ValueError:
                        pass  # An invalid piece is never a complete piece.
                    else:
                        result.append((self.paths[array['path']], array['path'], item))
                    self._item = self._item_depth = None
                self._stack.pop()
                if not self._stack:
                    self._ended = True
            elif parent and parent['type'] == '{':
                if char == ':':
                    parent['key_next'] = False
                elif char == ',':
                    parent['key_next'] = True
                    parent['key'] = None
        return result
