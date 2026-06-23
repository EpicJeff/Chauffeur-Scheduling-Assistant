with open("chauffeur/templates/config_fixed.html", "r", encoding="utf-8") as f:
    lines = f.readlines()

# The script block starts at 1816
# We want to remove the extra </div>s before it.
# They are lines 1813 and 1814. Let's find `<script>` and delete two `</div>`s above it.
for i, l in enumerate(lines):
    if "<script>" in l:
        # found it. let's go up and remove two </div>s
        removed = 0
        j = i - 1
        while j >= 0 and removed < 2:
            if "</div>" in lines[j]:
                del lines[j]
                removed += 1
                i -= 1 # adjust script index
            j -= 1
        break

with open("chauffeur/templates/config_fixed.html", "w", encoding="utf-8") as f:
    f.write("".join(lines))
