import re

with open('e:/repositories/Chauffeur/chauffeur/templates/app.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix the regex
# It is currently split across lines or has a literal newline.
# We want it to be: content.replace(/\n/g, '<br/>').replace(/\*\*(.*?)\*\*/g, '<b></b>');
content = re.sub(r'let formatted = content\.replace\(/.*?\n.*?/g', r'let formatted = content.replace(/\\n/g', content, flags=re.DOTALL)

with open('e:/repositories/Chauffeur/chauffeur/templates/app.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("Done")
