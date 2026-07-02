import re
import json

path = r'e:\repositories\Chauffeur\chauffeur\data\db.json'
with open(path, 'r', encoding='utf-8') as f:
    text = f.read()

# Remove null bytes and trailing whitespace/braces
text = text.replace('\x00', '').rstrip('}\n\r\t ')

# Find the last record key pattern e.g., ,"123": { or "123": {
matches = list(re.finditer(r',?\s*"[0-9]+"\s*:\s*\{', text))

if matches:
    match = matches[-1]
    # Truncate string right before the last record starts
    clean = text[:match.start()]
    # Close the table and close the root dict
    clean += '}}'
    
    try:
        data = json.loads(clean)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f)
        print("Fixed db.json successfully!")
    except Exception as e:
        print("Still invalid JSON:", e)
else:
    print("No matches found.")
