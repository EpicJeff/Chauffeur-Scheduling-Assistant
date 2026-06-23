with open("avoid_diff.txt", "r", encoding="utf-8") as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if "avoid" in line.lower():
        print("".join(lines[max(0, i-5):min(len(lines), i+6)]))
        print("-" * 40)
