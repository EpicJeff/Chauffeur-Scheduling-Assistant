with open("chauffeur/templates/config.html", "r", encoding="utf-8") as f:
    lines = f.readlines()

def check_balance(start_line, end_line):
    balance = 0
    for i in range(start_line, end_line):
        line = lines[i]
        import re
        opens = len(re.findall(r'<div\b', line))
        closes = len(re.findall(r'</div>', line))
        balance += opens - closes
        if opens != closes:
            print(f"Line {i+1} ({opens} open, {closes} close): {line.strip()}")
    print(f"Final Balance: {balance}")

start = -1
end = -1
for i, line in enumerate(lines):
    if '<template x-for="rule in rules.filter(r => r.is_ai_generated)"' in line:
        start = i
    if start != -1 and '</template>' in line and i > start:
        end = i
        break

check_balance(start+1, end)
