with open("chauffeur/templates/config.html", "r", encoding="utf-8") as f:
    lines = f.readlines()

# Fix Manual Routing Rule card
lines.insert(1052, "                                </div>\n")

# Re-read to adjust indices
html = "".join(lines)
lines = html.split("\n")
lines = [l + "\n" if i < len(lines)-1 else l for i, l in enumerate(lines)]

# Find where to fix Manual Priority Rule card
# Look for line 1449 originally, now it shifted by 1. So look for "Manual Event Priorities"
for i, l in enumerate(lines):
    if "Manual Event Priorities" in l:
        # Find the next </template> that ends the x-for
        for j in range(i, len(lines)):
            if '</template>' in lines[j] and 'No manual priority rules' not in lines[j+1] and 'rules.filter' not in lines[j]:
                lines.insert(j, "                                </div>\n")
                break
        break

with open("chauffeur/templates/config_fixed.html", "w", encoding="utf-8") as f:
    f.write("".join(lines))
