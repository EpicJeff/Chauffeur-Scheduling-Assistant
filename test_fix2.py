with open("chauffeur/templates/config_fixed.html", "r", encoding="utf-8") as f:
    lines = f.readlines()

lines.insert(1516, "                                </div>\n")

with open("chauffeur/templates/config_fixed.html", "w", encoding="utf-8") as f:
    f.write("".join(lines))
