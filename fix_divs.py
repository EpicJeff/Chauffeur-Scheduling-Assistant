with open("chauffeur/templates/config.html", "r", encoding="utf-8") as f:
    html = f.read()

# We need to find occurrences of:
target = """                                                </div>
                                            </div>
                                            <div class="flex space-x-2 mt-4 md:mt-0 shrink-0">"""

replacement = """                                                </div>
                                            </div>
                                            </div>
                                            <div class="flex space-x-2 mt-4 md:mt-0 shrink-0">"""

html = html.replace(target, replacement)

# We also added </div> to the VERY END of the templates in the previous script by accident!
# Let's remove the extra </div> from the end of the AI templates.
# The end of the AI templates has:
target2 = """                                            </button>
                                        </div>
                                    </div>
                                    </div>
                                </template>"""

replacement2 = """                                            </button>
                                        </div>
                                    </div>
                                </template>"""
html = html.replace(target2, replacement2)

with open("chauffeur/templates/config.html", "w", encoding="utf-8") as f:
    f.write(html)
