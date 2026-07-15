import re
html = open('e:/repositories/Chauffeur/chauffeur/templates/components/control_center.html', encoding='utf-8').read()

old = """                if (data.ui_action === 'reload') {
                    // Small delay to let the chat bubble render before refreshing
                    setTimeout(() => window.location.reload(), 3000);
                }"""

new = """                if (data.ui_action === 'reload') {
                    // Small delay to let the chat bubble render before refreshing
                    setTimeout(() => window.location.reload(), 3000);
                } else if (data.ui_action === 'jump_and_reload') {
                    if (data.target_element_id && data.target_driver_id) {
                        const el = document.getElementById(data.target_element_id);
                        const targetCol = document.getElementById('col-' + data.target_driver_id);
                        if (el && targetCol) {
                            // Find the container inside the column to append to
                            const targetContainer = targetCol.querySelector('.relative.flex-1');
                            if (targetContainer) {
                                // Animate jump
                                el.style.transition = 'all 0.5s cubic-bezier(0.4, 0, 0.2, 1)';
                                el.style.opacity = '0.7';
                                targetContainer.appendChild(el);
                                // Optional: calculate position based on time, but simple append works for the jump effect
                            }
                        }
                    }
                    setTimeout(() => window.location.reload(), 2000);
                }"""

html = html.replace(old, new)
open('e:/repositories/Chauffeur/chauffeur/templates/components/control_center.html', 'w', encoding='utf-8').write(html)
print("Replaced control center!")
