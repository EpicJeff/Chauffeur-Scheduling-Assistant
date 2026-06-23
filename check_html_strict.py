from html.parser import HTMLParser

class StrictParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []
        self.void_elements = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
        self.errors = []

    def handle_starttag(self, tag, attrs):
        if tag not in self.void_elements:
            self.stack.append((tag, self.getpos()[0]))

    def handle_endtag(self, tag):
        if tag in self.void_elements:
            return
        if not self.stack:
            self.errors.append(f"Error: End tag </{tag}> with no open tag at line {self.getpos()[0]}")
            return
        if self.stack[-1][0] != tag:
            found = False
            for i in range(len(self.stack)-1, -1, -1):
                if self.stack[i][0] == tag:
                    found = True
                    for j in range(len(self.stack)-1, i, -1):
                        self.errors.append(f"Warning: Missing end tag for <{self.stack[j][0]}> opened at line {self.stack[j][1]} (detected at {self.getpos()[0]})")
                    self.stack = self.stack[:i]
                    break
            if not found:
                self.errors.append(f"Error: End tag </{tag}> at line {self.getpos()[0]} does not match open tag <{self.stack[-1][0]}> at line {self.stack[-1][1]}")
        else:
            self.stack.pop()

parser = StrictParser()
with open("chauffeur/templates/config_new.html", "r", encoding="utf-8") as f:
    html = f.read()
    import re
    html = re.sub(r'<script.*?</script>', '', html, flags=re.DOTALL)
    parser.feed(html)

if parser.stack:
    print(f"Warning: Unclosed tags at end of file:")
    for tag, line in parser.stack:
        print(f"  <{tag}> at line {line}")
for err in parser.errors:
    print(err)
if not parser.stack and not parser.errors:
    print("HTML is perfectly balanced!")
