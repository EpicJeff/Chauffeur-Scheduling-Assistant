with open("chauffeur/templates/config.html", "r", encoding="utf-8") as f:
    html = f.read()

idx = html.find("'Create Routing Rule'")
start_idx = html.rfind('<div class="bg-gray-700/30 p-6 rounded-xl border border-gray-600 border-dashed space-y-4">', 0, idx)

import re
comments = re.findall(r'<!--(.*?)-->', html[start_idx:start_idx+15000], re.DOTALL)
for c in comments:
    if '<div' in c or '</div' in c:
        print(f"Comment contains div: {c}")

