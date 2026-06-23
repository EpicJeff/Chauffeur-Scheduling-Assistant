from bs4 import BeautifulSoup

html = """
<div x-data="{ open: false }">
    <template x-if="open">
        <div>Inner content</div>
    </template>
</div>
"""

soup = BeautifulSoup(html, 'html.parser')
print(str(soup))
