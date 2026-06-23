with open("chauffeur/templates/config.html", "r", encoding="utf-8") as f:
    html = f.read()

import re

# We want exactly 3 </div>s before `<div class="flex space-x-2 mt-4 md:mt-0 shrink-0">`
# We can just replace ANY sequence of 1 or more `</div>` before it with exactly 3 `</div>`s!
html = re.sub(r'(</div>\s*)+(<div class="flex space-x-2 mt-4 md:mt-0 shrink-0">)', r'</div>\n                                            </div>\n                                            </div>\n                                            \2', html)

# And for the end of the AI templates:
# `<template x-if="rules.filter(r => r.is_ai_generated).length === 0">` is preceded by `</template>`.
# We want exactly ONE `</div>` before that `</template>`... Wait!
# Let's count how many `</div>`s we want at the end of the card container.
# Wait, the end of the card container is closed AFTER the buttons!
# <div class="flex space-x-2...">
#   <button>...</button>
# </div> (closes buttons container)
# </div> (closes header wrapper)
# </div> (closes card container)
# </template> (closes the loop)
# So we need EXACTLY THREE </div>s before the `</template>` that closes the AI generated loop.

# But wait, the manual rules also need 3 </div>s before the `</template>`!
# Let's just enforce exactly THREE </div>s before ANY `</template>` that has `<template x-if="` immediately after it!
# Wait, the `x-if` templates are empty-state messages!
html = re.sub(r'(</div>\s*)+(</template>\s*<template x-if="rules\.filter\(r => !r\.is_ai_generated\)\.length === 0">)', r'</div>\n                                        </div>\n                                    </div>\n                                \2', html)
html = re.sub(r'(</div>\s*)+(</template>\s*<template x-if="rules\.filter\(r => r\.is_ai_generated\)\.length === 0">)', r'</div>\n                                        </div>\n                                    </div>\n                                \2', html)
html = re.sub(r'(</div>\s*)+(</template>\s*<template x-if="priorityRules\.filter\(r => !r\.is_ai_generated\)\.length === 0">)', r'</div>\n                                        </div>\n                                    </div>\n                                \2', html)
html = re.sub(r'(</div>\s*)+(</template>\s*<template x-if="priorityRules\.filter\(r => r\.is_ai_generated\)\.length === 0">)', r'</div>\n                                        </div>\n                                    </div>\n                                \2', html)

with open("chauffeur/templates/config.html", "w", encoding="utf-8") as f:
    f.write(html)
