import os

filepath = 'solver/matcher.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

target = "pending_errands = [e for e in errands if not e.get('is_completed')]"
replacement = "pending_errands = [e for e in errands if not e.get('is_completed') and e.get('status') != 'past_due']"

content = content.replace(target, replacement)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)

print("Matcher updated")
