import re

filepath = r'e:\repositories\Chauffeur\chauffeur\templates\nav.html'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

content = re.sub(r'href="/dashboard_v2"', r'href="{{ url_for(\'dashboard\') }}"', content)
content = re.sub(r'href="/config"', r'href="{{ url_for(\'config\') }}"', content)
content = re.sub(r'href="/errands"', r'href="{{ url_for(\'errands\') }}"', content)

# Also fix the active state logic to check request.url.path against the url_for
content = re.sub(r"request\.url\.path == '/dashboard_v2'", r"'dashboard_v2' in request.url.path", content)
content = re.sub(r"request\.url\.path == '/config'", r"'config' in request.url.path", content)
content = re.sub(r"request\.url\.path == '/errands'", r"'errands' in request.url.path", content)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)
