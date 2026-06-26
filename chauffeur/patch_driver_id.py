with open('e:/repositories/Chauffeur/chauffeur/services/llm.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace(
    'def agentic_chat_loop(user_msg: str, source: str = "admin") -> str:',
    'def agentic_chat_loop(user_msg: str, source: str = "admin", driver_id: str = None) -> str:'
)

pwa_prompt = '''if source == "pwa":
        SYSTEM_PROMPT += "\\n\\nCRITICAL PWA DRIVER INSTRUCTIONS:\\nYou are speaking directly to a driver via the mobile app on the go. Be extremely polite, concise, and friendly. Focus purely on the driver\\'s immediate needs (routing, overrides, active errands, and live state tracking). DO NOT use technical jargon (e.g. \\'heuristic solver\\', \\'JSON payloads\\'). If the driver asks to change something, ALWAYS prefer using one-off overrides (`AddOverrideTool`) rather than global routing rules. Do NOT create global rules (`AddRoutingRuleTool`) unless the driver explicitly uses the word \\'permanently\\'."'''

new_pwa_prompt = '''if source == "pwa":
        SYSTEM_PROMPT += "\\n\\nCRITICAL PWA DRIVER INSTRUCTIONS:\\nYou are speaking directly to a driver via the mobile app on the go. Be extremely polite, concise, and friendly. Focus purely on the driver\\'s immediate needs (routing, overrides, active errands, and live state tracking). DO NOT use technical jargon (e.g. \\'heuristic solver\\', \\'JSON payloads\\'). If the driver asks to change something, ALWAYS prefer using one-off overrides (`AddOverrideTool`) rather than global routing rules. Do NOT create global rules (`AddRoutingRuleTool`) unless the driver explicitly uses the word \\'permanently\\'."
        if driver_id:
            SYSTEM_PROMPT += f"\\nIMPORTANT: You are currently talking to the driver with ID '{driver_id}'. Assume they are referring to their own schedule, their own routes, and their own errands. Do not ask who they are."'''

content = content.replace(pwa_prompt, new_pwa_prompt)

with open('e:/repositories/Chauffeur/chauffeur/services/llm.py', 'w', encoding='utf-8') as f:
    f.write(content)

with open('e:/repositories/Chauffeur/chauffeur/templates/app.html', 'r', encoding='utf-8') as f:
    app_html = f.read()

app_html = app_html.replace(
    "body: JSON.stringify({ message: text, source: 'pwa' })",
    "body: JSON.stringify({ message: text, source: 'pwa', driver_id: selectedDriverId })"
)

with open('e:/repositories/Chauffeur/chauffeur/templates/app.html', 'w', encoding='utf-8') as f:
    f.write(app_html)

print("Done")
