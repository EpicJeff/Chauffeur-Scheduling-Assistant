import re

def fix_uuid(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    uuid_func = """function generateUUID() {
    if (typeof crypto !== 'undefined' && crypto.randomUUID) {
        return crypto.randomUUID();
    }
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
        var r = Math.random() * 16 | 0, v = c === 'x' ? r : (r & 0x3 | 0x8);
        return v.toString(16);
    });
}
"""
    # Only inject if not already present
    if "function generateUUID" not in content:
        content = content.replace("let currentSessionToken = null;", uuid_func + "\n        let currentSessionToken = null;")
    
    content = content.replace("crypto.randomUUID()", "generateUUID()")

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

fix_uuid(r'e:\repositories\Chauffeur\chauffeur\templates\dashboard.html')
fix_uuid(r'e:\repositories\Chauffeur\chauffeur\templates\errands.html')
