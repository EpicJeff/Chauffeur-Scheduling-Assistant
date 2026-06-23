from html.parser import HTMLParser

class BalanceParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []
        self.void_elements = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
        
    def handle_starttag(self, tag, attrs):
        if tag not in self.void_elements:
            self.stack.append((tag, self.getpos()[0]))
            
    def handle_endtag(self, tag):
        if tag in self.void_elements: return
        if self.stack and self.stack[-1][0] == tag:
            self.stack.pop()
        else:
            print(f"Mismatch at line {self.getpos()[0]}: </{tag}> doesn't match <{self.stack[-1][0]}> at {self.stack[-1][1]}")

with open("chauffeur/templates/config_fixed.html", "r", encoding="utf-8") as f:
    html = f.read()
import re
html = re.sub(r'<script.*?</script>', '', html, flags=re.DOTALL)
parser = BalanceParser()
parser.feed(html)
