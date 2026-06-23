from html.parser import HTMLParser

class MyHTMLParser(HTMLParser):
    def handle_starttag(self, tag, attrs):
        pass
    def handle_endtag(self, tag):
        pass
    def handle_data(self, data):
        if '>' in data and not data.isspace():
            print("Found literal > in text:", repr(data.strip()[:50]))

parser = MyHTMLParser()
with open("chauffeur/templates/config.html", "r", encoding="utf-8") as f:
    parser.feed(f.read())
