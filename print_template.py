with open("chauffeur/templates/config.html", "r", encoding="utf-8") as f:
    lines = f.readlines()

start = -1
end = -1
for i, line in enumerate(lines):
    if '<template x-for="rule in rules.filter(r => r.is_ai_generated)"' in line:
        start = i
    if start != -1 and '</template>' in line and i > start:
        end = i
        break

for i in range(start, end+1):
    print(f"{i+1}: {lines[i].strip()}")
