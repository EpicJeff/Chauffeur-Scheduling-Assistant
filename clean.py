import sys

file_path = "e:/repositories/Chauffeur/chauffeur/templates/components/control_center.html"
with open(file_path, "r", encoding="utf-8") as f:
    lines = f.readlines()

new_lines = []
skip = False
for i, line in enumerate(lines):
    # lines 525 is around 'async function loadConversations'
    if 'async function loadConversations(preserveActive = false)' in line:
        skip = True
    
    if skip and 'async function submitChat(e)' in line:
        skip = False
        
    if not skip:
        new_lines.append(line)

with open(file_path, "w", encoding="utf-8") as f:
    f.writelines(new_lines)
