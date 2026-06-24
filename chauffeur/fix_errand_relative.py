import re

filepath = r'e:\repositories\Chauffeur\chauffeur\templates\errands.html'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace('{{ url_for("get_errands") }}', 'api/errands')

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)
