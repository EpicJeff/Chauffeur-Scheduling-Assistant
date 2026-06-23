with open("chauffeur/templates/config.html", "r", encoding="utf-8") as f:
    lines = f.readlines()

def get_routing_form_bounds(lines):
    start = -1
    for i, l in enumerate(lines):
        if "'Create Routing Rule'" in l:
            for j in range(i, -1, -1):
                if '<div class="bg-gray-700/30' in lines[j]:
                    start = j
                    break
            break
            
    for i in range(start, len(lines)):
        if 'cancelEditRule()' in lines[i]:
            for j in range(i, len(lines)):
                if lines[j].strip() == '</div>':
                    if lines[j+1].strip() == '</div>':
                        return start, j+2
    return -1, -1

r_s, r_e = get_routing_form_bounds(lines)
form_lines = lines[r_s:r_e]

for i in range(270, 276):
    if i < len(form_lines):
        print(f"Form Line {i+1}:", form_lines[i].strip())
