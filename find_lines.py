with open("chauffeur/templates/config.html", "r", encoding="utf-8") as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if "'Create Priority Rule'" in line:
        print(f"Priority Rule Editor starts around line {i+1}")
    if "Manual Routing" in line:
        print(f"Manual Routing list starts around line {i+1}")
    if "Manual Event Priorities" in line:
        print(f"Manual Priority Rules list starts around line {i+1}")
    if "Priority Rules" in line and "<!--" in line:
        print(f"Priority Rules comment around line {i+1}")
