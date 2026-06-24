import re

filepath = r'e:\repositories\Chauffeur\chauffeur\templates\errands.html'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Inject the dropdown for `#new-errand-input` and add the onkeyup event
new_errand_input_regex = r'<input type="text" id="new-errand-input" (.*?)autocomplete="off">'
new_errand_input_replace = r'<input type="text" id="new-errand-input" onkeyup="handleNewErrandInput()" \1autocomplete="off">\n                <div id="new-errand-autocomplete-dropdown" class="hidden absolute w-full top-14 mt-2 bg-gray-700 border border-gray-600 rounded-lg shadow-2xl z-50 max-h-60 overflow-y-auto"></div>'
content = re.sub(new_errand_input_regex, new_errand_input_replace, content, flags=re.DOTALL)

# 2. Inject the dropdown for `#edit-location` and add the onkeyup event
edit_location_regex = r'<input type="text" id="edit-location" class="(.*?)"(.*?)>'
edit_location_replace = r'<div class="relative"><input type="text" id="edit-location" onkeyup="handleEditLocationInput()" autocomplete="off" class="\1"\2>\n                        <div id="edit-autocomplete-dropdown" class="hidden absolute w-full mt-1 bg-gray-700 border border-gray-600 rounded-lg shadow-2xl z-50 max-h-60 overflow-y-auto"></div></div>'
content = re.sub(edit_location_regex, edit_location_replace, content)

# 3. Inject JS
js_logic = """
        let autocompleteTimeout = null;
        let currentSessionToken = null;

        // Inbox Input Autocomplete
        function handleNewErrandInput() {
            const inputEl = document.getElementById('new-errand-input');
            const dropdown = document.getElementById('new-errand-autocomplete-dropdown');
            const text = inputEl.value;

            const locMatch = text.match(/(?:@| at )([^!]+)$/i);
            
            if (!locMatch || locMatch[1].trim().length < 3) {
                dropdown.classList.add('hidden');
                currentSessionToken = null;
                return;
            }

            const query = locMatch[1].trim();
            if (!currentSessionToken) {
                currentSessionToken = crypto.randomUUID();
            }

            clearTimeout(autocompleteTimeout);
            autocompleteTimeout = setTimeout(async () => {
                try {
                    const res = await fetch(`api/places/autocomplete?input=${encodeURIComponent(query)}&session_token=${currentSessionToken}`);
                    const data = await res.json();

                    if (data.suggestions && data.suggestions.length > 0) {
                        dropdown.innerHTML = data.suggestions.map(s => {
                            const escapedDesc = s.description.replace(/'/g, "\\\\'");
                            const mapboxId = s.mapbox_id ? `'${s.mapbox_id}'` : 'null';
                            return `<div onclick="selectNewErrandLocation('${escapedDesc}', ${mapboxId})" class="p-3 hover:bg-gray-600 cursor-pointer border-b border-gray-600 last:border-0 text-sm text-left">${s.description}</div>`;
                        }).join('');
                        dropdown.classList.remove('hidden');
                    } else {
                        dropdown.classList.add('hidden');
                    }
                } catch (e) {
                    console.error("Autocomplete failed", e);
                }
            }, 300);
        }

        async function selectNewErrandLocation(loc, mapboxId = null) {
            const inputEl = document.getElementById('new-errand-input');
            document.getElementById('new-errand-autocomplete-dropdown').classList.add('hidden');
            
            const text = inputEl.value;
            const locMatch = text.match(/(?:@| at )([^!]+)$/i);
            
            if (locMatch) {
                inputEl.value = text.replace(locMatch[0], locMatch[0].replace(locMatch[1], loc + ' '));
                inputEl.focus();
            }
            
            if (mapboxId && currentSessionToken) {
                try {
                    const res = await fetch(`api/places/retrieve?mapbox_id=${mapboxId}&session_token=${currentSessionToken}`);
                    if (res.ok) {
                        const data = await res.json();
                        if (data && data.name) {
                            const currentText = inputEl.value;
                            const currentLocMatch = currentText.match(/(?:@| at )([^!]+)$/i);
                            if (currentLocMatch) {
                                inputEl.value = currentText.replace(currentLocMatch[0], currentLocMatch[0].replace(currentLocMatch[1].trim(), data.name + ' '));
                            }
                        }
                    }
                } catch (e) {
                    console.error("Retrieve failed", e);
                }
            }
            currentSessionToken = null;
        }

        // Edit Modal Autocomplete
        function handleEditLocationInput() {
            const input = document.getElementById('edit-location').value;
            const dropdown = document.getElementById('edit-autocomplete-dropdown');

            if (input.length < 3) {
                dropdown.classList.add('hidden');
                currentSessionToken = null;
                return;
            }
            if (!currentSessionToken) {
                currentSessionToken = crypto.randomUUID();
            }

            clearTimeout(autocompleteTimeout);
            autocompleteTimeout = setTimeout(async () => {
                try {
                    const res = await fetch(`api/places/autocomplete?input=${encodeURIComponent(input)}&session_token=${currentSessionToken}`);
                    const data = await res.json();

                    if (data.suggestions && data.suggestions.length > 0) {
                        dropdown.innerHTML = data.suggestions.map(s => {
                            const escapedDesc = s.description.replace(/'/g, "\\\\'");
                            const mapboxId = s.mapbox_id ? `'${s.mapbox_id}'` : 'null';
                            return `<div onclick="selectEditLocation('${escapedDesc}', ${mapboxId})" class="p-3 hover:bg-gray-600 cursor-pointer border-b border-gray-600 last:border-0 text-sm text-left">${s.description}</div>`;
                        }).join('');
                        dropdown.classList.remove('hidden');
                    } else {
                        dropdown.classList.add('hidden');
                    }
                } catch (e) {
                    console.error("Autocomplete failed", e);
                }
            }, 300);
        }

        async function selectEditLocation(loc, mapboxId = null) {
            document.getElementById('edit-location').value = loc;
            document.getElementById('edit-autocomplete-dropdown').classList.add('hidden');
            
            if (mapboxId && currentSessionToken) {
                try {
                    const res = await fetch(`api/places/retrieve?mapbox_id=${mapboxId}&session_token=${currentSessionToken}`);
                    if (res.ok) {
                        const data = await res.json();
                        if (data && data.name) {
                            document.getElementById('edit-location').value = data.name;
                        }
                    }
                } catch (e) {
                    console.error("Retrieve failed", e);
                }
            }
            currentSessionToken = null;
        }
"""

content = content.replace('let errands = [];', js_logic + '\n        let errands = [];')

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)

