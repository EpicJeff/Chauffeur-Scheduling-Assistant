import re

filepath = r'e:\repositories\Chauffeur\chauffeur\templates\errands.html'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# Make sure all /api/errands are api/errands
content = content.replace("'/api/errands'", "'api/errands'")
content = content.replace("`/api/errands", "`api/errands")

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)
