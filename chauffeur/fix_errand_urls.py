import re

filepath = r'e:\repositories\Chauffeur\chauffeur\templates\errands.html'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# Replace all instances of '/api/errands' with '{{ url_for('get_errands') }}'
content = content.replace("'/api/errands'", "'{{ url_for(\"get_errands\") }}'")
content = content.replace("`/api/errands/${", "`{{ url_for(\"get_errands\") }}/${")

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)
