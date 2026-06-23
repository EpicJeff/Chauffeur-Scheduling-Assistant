with open("chauffeur/templates/config_fixed.html", "r", encoding="utf-8") as f:
    lines = f.readlines()

for i, l in enumerate(lines):
    if "Manual Event Priorities" in l:
        print(f"Manual Event Priorities is at line {i+1}")
