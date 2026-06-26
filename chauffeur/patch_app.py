import json
import re

with open('e:/repositories/Chauffeur/chauffeur/templates/app.html', 'r', encoding='utf-8') as f:
    content = f.read()

chat_html = '''
    <!-- Argyle Chat Popup -->
    <div id="kiosk-chat-popup" class="hidden fixed bottom-24 right-4 w-80 h-[30rem] max-h-[70vh] bg-gray-900 border border-gray-700 rounded-xl shadow-2xl flex-col z-50 overflow-hidden">
        <div class="bg-indigo-600 px-4 py-3 flex justify-between items-center text-white shrink-0 shadow-sm border-b border-indigo-700">
            <span class="font-bold flex items-center gap-2">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z"></path>
                </svg>
                Argyle
            </span>
            <button onclick="toggleKioskChat()" class="text-white hover:text-gray-200 focus:outline-none transition-colors">
                <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                </svg>
            </button>
        </div>
        <div id="kiosk-chat-popup-body" class="flex-1 flex flex-col min-h-0 bg-gray-900">
            <div id="chat-content" class="flex-1 flex flex-col bg-gray-900 overflow-hidden">
                <div id="chat-messages" class="flex-1 p-4 overflow-y-auto flex flex-col gap-3">
                    <div class="text-center text-gray-500 text-sm mt-4">Loading chat history...</div>
                </div>
                <div class="p-3 bg-gray-800 border-t border-gray-700 shrink-0">
                    <form id="chat-form" onsubmit="submitChat(event)" class="flex gap-2">
                        <input type="text" id="chat-input" autocomplete="off" placeholder="Message Argyle..." class="flex-1 bg-gray-900 border border-gray-600 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500">
                        <button type="submit" id="chat-submit-btn" class="bg-blue-600 hover:bg-blue-500 text-white px-3 py-2 rounded-lg font-bold text-sm transition-colors">Send</button>
                    </form>
                </div>
            </div>
        </div>
    </div>

    <!-- Floating Action Button -->
    <button id="kiosk-chat-fab" onclick="toggleKioskChat()" class="fixed bottom-6 right-6 w-14 h-14 bg-indigo-600 hover:bg-indigo-500 text-white rounded-full shadow-lg flex items-center justify-center transition-transform hover:scale-110 z-50 focus:outline-none">
        <svg class="w-7 h-7" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z"></path>
        </svg>
    </button>

    <script>
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
                const res = await fetch(${apiBase}api/chat/history);
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
            div.className = max-w-[85%] rounded-lg p-3 text-sm ;
            let formatted = content.replace(/\\n/g, '<br/>').replace(/\\*\\*(.*?)\\*\\*/g, '<b></b>');
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
                const res = await fetch(${apiBase}api/chat, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: text, source: 'pwa' })
                });

                const data = await res.json();
                typingDiv.remove();

                if (data.error) {
                    appendMessage('assistant', Error: );
                } else {
                    appendMessage('assistant', data.reply);
                    // Refresh PWA UI silently to reflect LLM changes (errands or status)
                    fetchSchedule();
                }
            } catch (err) {
                typingDiv.remove();
                appendMessage('assistant', Connection error: );
            } finally {
                chatInput.disabled = false;
                chatSubmitBtn.disabled = false;
                chatInput.focus();
            }
        }

        document.addEventListener('DOMContentLoaded', () => {
            loadChatHistory();
        });
    </script>
</body>
'''

content = content.replace('</body>', chat_html)

with open('e:/repositories/Chauffeur/chauffeur/templates/app.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("Done")
