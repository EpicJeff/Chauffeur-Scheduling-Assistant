with open("chauffeur/templates/config.html", "r", encoding="utf-8") as f:
    html = f.read()

import re
html = html.replace("""                                            </button>
                                        </div>
                                    </div>
                                </template>
                                <template x-if="rules.filter(r => r.is_ai_generated).length === 0">""", """                                            </button>
                                        </div>
                                    </div>
                                    </div>
                                </template>
                                <template x-if="rules.filter(r => r.is_ai_generated).length === 0">""")

html = html.replace("""                                                </button>
                                            </div>
                                        </div>
                                </template>
                                <template x-if="priorityRules.filter(r => r.is_ai_generated).length === 0">""", """                                                </button>
                                            </div>
                                        </div>
                                        </div>
                                </template>
                                <template x-if="priorityRules.filter(r => r.is_ai_generated).length === 0">""")

with open("chauffeur/templates/config.html", "w", encoding="utf-8") as f:
    f.write(html)
