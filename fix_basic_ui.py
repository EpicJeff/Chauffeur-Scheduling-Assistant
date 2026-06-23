import re

with open("chauffeur/templates/config.html", "r", encoding="utf-8") as f:
    html = f.read()

# 1. Update submitRule
old_submit = r"const payload = JSON\.parse\(JSON\.stringify\(this\.newRule\)\);"
new_submit = """const payload = JSON.parse(JSON.stringify(this.newRule));
                        if (payload.constraint_type === 'assignment') {
                            payload.constraint_type = payload.assignment_type;
                            delete payload.assignment_type;
                        }"""
html = re.sub(old_submit, new_submit, html)

# 2. Update editRule
old_edit = r"this\.newRule = JSON\.parse\(JSON\.stringify\(rule\)\);"
new_edit = """this.newRule = JSON.parse(JSON.stringify(rule));
                    if (['required', 'preferred', 'unavailable', 'avoid'].includes(this.newRule.constraint_type)) {
                        this.newRule.assignment_type = this.newRule.constraint_type;
                        this.newRule.constraint_type = 'assignment';
                    } else if (!this.newRule.assignment_type) {
                        this.newRule.assignment_type = 'required';
                    }"""
html = re.sub(old_edit, new_edit, html)

# 3. Update resetRule
old_reset = r"constraint_type: 'required',"
new_reset = "constraint_type: 'assignment',\n                        assignment_type: 'required',"
html = re.sub(old_reset, new_reset, html)

# 4. Modify Constraint Type Dropdown options
old_options = """<option value="required">Required Driver</option>
                                            <option value="preferred">Preferred Driver</option>
                                            <option value="unavailable">Unavailable Driver</option>"""
new_options = """<option value="assignment">Driver Assignment</option>"""
html = html.replace(old_options, new_options)

# 5. Add Assignment Type Dropdown
assignment_type_html = """</select>
                                    </div>
                                    <div class="w-full lg:w-48" x-show="newRule.constraint_type === 'assignment'">
                                        <label class="block text-gray-400 mb-1 text-sm">Assignment Type</label>
                                        <select x-model="newRule.assignment_type"
                                            class="w-full bg-gray-900 border border-gray-600 rounded p-3 text-white appearance-none">
                                            <option value="required">Required</option>
                                            <option value="preferred">Preferred</option>
                                            <option value="avoid">Avoid</option>
                                            <option value="unavailable">Unavailable</option>
                                        </select>"""
html = html.replace("""<option value="attendance">Event Attendance</option>
                                        </select>""", """<option value="attendance">Event Attendance</option>
                                        """ + assignment_type_html)

with open("chauffeur/templates/config.html", "w", encoding="utf-8") as f:
    f.write(html)
print("Logic applied successfully")
