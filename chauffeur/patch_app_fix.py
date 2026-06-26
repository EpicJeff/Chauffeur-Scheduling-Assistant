import re

with open('e:/repositories/Chauffeur/chauffeur/templates/app.html', 'r', encoding='utf-8') as f:
    content = f.read()

correct_script = """    <script>
        const chatMessages = document.getElementById('chat-messages');
        const chatInput = document.getElementById('chat-input');
        const chatSubmitBtn = document.getElementById('chat-submit-btn');

        function toggleKioskChat() {
            const popup = document.getElementById('kiosk-chat-popup');
            if (popup) {
                popup.classList.toggle('hidden');
                popup.classList.toggle('flex');
                if (!popup.classList.contains('hidden')) {
                    if (chatInput) chatInput.focus();
                    scrollToBottom();
                }
            }
        }

        async function loadChatHistory() {
            if (!chatMessages) return;
            try {
                const apiBase = window.location.pathname.endsWith('/') ? '../' : '';
                const res = await fetch(`${apiBase}api/chat/history`);
                const data = await res.json();
                chatMessages.innerHTML = '';
                if (data.history && data.history.length > 0) {
                    data.history.forEach(msg => appendMessage(msg.role, msg.content));
                } else {
                    appendMessage('assistant', 'Hello! I am Argyle. Need help with your route today?');
                }
                scrollToBottom();
            } catch (err) {
                console.error('Failed to load chat history', err);
            }
        }

        function appendMessage(role, content) {
            if (!chatMessages) return;
            const div = document.createElement('div');
            div.className = `max-w-[85%] rounded-lg p-3 text-sm ${role === 'user' ? 'bg-blue-600 text-white self-end rounded-tr-none' : 'bg-gray-700 text-gray-100 self-start rounded-tl-none border border-gray-600'}`;
            let formatted = content.replace(/\\n/g, '<br/>').replace(/\\*\\*(.*?)\\*\\*/g, '<b>$1</b>');
            div.innerHTML = formatted;
            chatMessages.appendChild(div);
            scrollToBottom();
        }

        function scrollToBottom() {
            if (chatMessages) {
                chatMessages.scrollTop = chatMessages.scrollHeight;
            }
        }

        async function submitChat(e) {
            e.preventDefault();
            const text = chatInput.value.trim();
            if (!text) return;

            appendMessage('user', text);
            chatInput.value = '';
            chatInput.disabled = true;
            chatSubmitBtn.disabled = true;

            const typingDiv = document.createElement('div');
            typingDiv.className = 'text-gray-400 text-xs italic self-start mt-1 mb-2 animate-pulse';
            typingDiv.innerText = 'Argyle is thinking...';
            chatMessages.appendChild(typingDiv);
            scrollToBottom();

            try {
                const apiBase = window.location.pathname.endsWith('/') ? '../' : '';
                const res = await fetch(`${apiBase}api/chat`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: text, source: 'pwa' })
                });

                const data = await res.json();
                typingDiv.remove();

                if (data.error) {
                    appendMessage('assistant', `Error: ${data.error}`);
                } else {
                    appendMessage('assistant', data.reply);
                    // Refresh PWA UI silently to reflect LLM changes (errands or status)
                    fetchSchedule();
                }
            } catch (err) {
                typingDiv.remove();
                appendMessage('assistant', `Connection error: ${err.message}`);
            } finally {
                chatInput.disabled = false;
                chatSubmitBtn.disabled = false;
                chatInput.focus();
            }
        }

        document.addEventListener('DOMContentLoaded', () => {
            loadChatHistory();
        });
    </script>"""

# We need to replace everything from <script> to </script> at the end of the file.
# Since it's the last script block, we can find it by splitting on </button> of the FAB.
parts = content.split('</button>')
# The last part is the one with the script block and </body>
# Wait, there are multiple </button> tags.
# Let's use regex to find the script block containing 'chatMessages.scrollTop = chatMessages.scrollHeight'
pattern = re.compile(r'<script>\s*const chatMessages = document.getElementById.*?</script>', re.DOTALL)
new_content = pattern.sub(correct_script, content)

with open('e:/repositories/Chauffeur/chauffeur/templates/app.html', 'w', encoding='utf-8') as f:
    f.write(new_content)

print("Done")
