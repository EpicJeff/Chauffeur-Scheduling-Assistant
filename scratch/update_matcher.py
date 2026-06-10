import re

with open('e:/repositories/Chauffeur/chauffeur/solver/matcher.py', 'r', encoding='utf-8') as f:
    content = f.read()

old_code = """    if passengers is None:
        passengers = []
        
    # Pre-calculate requires_attendance per event"""

new_code = """    if passengers is None:
        passengers = []
        
    # Default missing event locations to home_location to prevent 0-minute teleportation
    for e in events:
        if not getattr(e, 'location', None) or str(e.location).strip() == "":
            e.location = home_location

    # Pre-calculate requires_attendance per event"""

content = content.replace(old_code, new_code)

with open('e:/repositories/Chauffeur/chauffeur/solver/matcher.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Patched matcher.py")
