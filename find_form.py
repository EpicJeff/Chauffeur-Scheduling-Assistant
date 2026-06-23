import re
with open("chauffeur/templates/config.html", "r", encoding="utf-8") as f:
    html = f.read()

# Let's find "Create Routing Rule"
idx = html.find("'Create Routing Rule'")
print(f"'Create Routing Rule' found at index {idx}")
start_idx = html.rfind('<div class="bg-gray-700/30', 0, idx)
print(f"Form starts at {start_idx}")

# Find where it ends
end_idx = html.find('<!-- Priority Rules -->', idx)
print(f"End of block should be before Priority Rules: {end_idx}")

# Also find where Manual Routing Rules list starts so we can insert the form before it
list_start = html.find('<div class="space-y-4 mb-8">')
print(f"List starts at {list_start}")
