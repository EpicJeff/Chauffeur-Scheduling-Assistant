import re

with open('e:/repositories/Chauffeur/chauffeur/templates/app.html', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add Bell Button
bell_btn = """<button onclick="enableNotifications()" class="text-blue-200/70 hover:text-white transition-colors bg-white/5 p-2 rounded-full border border-white/10 backdrop-blur-sm mr-2">
        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"></path></svg>
    </button>
    <button onclick="clearDriver()\""""
content = content.replace("<button onclick=\"clearDriver()\"", bell_btn)

# 2. Add Service Worker / Notification JS logic
sw_logic = """
        function urlB64ToUint8Array(base64String) {
            const padding = '='.repeat((4 - base64String.length % 4) % 4);
            const base64 = (base64String + padding).replace(/\-/g, '+').replace(/_/g, '/');
            const rawData = window.atob(base64);
            const outputArray = new Uint8Array(rawData.length);
            for (let i = 0; i < rawData.length; ++i) {
                outputArray[i] = rawData.charCodeAt(i);
            }
            return outputArray;
        }

        async function enableNotifications() {
            if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
                alert("Push notifications are not supported by your browser.");
                return;
            }
            const permission = await Notification.requestPermission();
            if (permission !== 'granted') {
                alert("Permission not granted.");
                return;
            }
            
            try {
                const reg = await navigator.serviceWorker.register('/sw.js');
                const response = await fetch('/api/vapid_public_key');
                const data = await response.json();
                
                const subscription = await reg.pushManager.subscribe({
                    userVisibleOnly: true,
                    applicationServerKey: urlB64ToUint8Array(data.public_key)
                });
                
                await fetch('/api/push_subscribe', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        driver_id: currentDriverId,
                        subscription: subscription
                    })
                });
                alert("Notifications enabled!");
            } catch (e) {
                console.error(e);
                alert("Failed to enable notifications: " + e.message);
            }
        }
"""
content = content.replace("function clearDriver() {", sw_logic + "\n        function clearDriver() {")

# 3. Modify renderLegPill
render_leg_old = "function renderLegPill(timeStr, title, mins, delayMins, actionArgs, colorTheme = 'blue', subtitleHtml = '') {"
render_leg_new = """function renderLegPill(timeStr, title, mins, delayMins, actionArgs, colorTheme = 'blue', subtitleHtml = '', legId = null) {
            const isCompleted = legId && scheduleData && scheduleData.completed_drives && scheduleData.completed_drives.includes(legId);
            if (isCompleted) {
                return `
                    <div class="flex items-start mb-2 relative z-10 opacity-60">
                        <div class="w-8 h-8 rounded-full bg-gray-800 border-2 border-gray-950 flex items-center justify-center shrink-0 shadow-sm text-green-400">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>
                        </div>
                        <div class="ml-4 flex-1 bg-gray-900 border border-gray-800 rounded-lg p-2 flex items-center justify-between">
                            <div class="text-gray-400 font-medium text-sm line-through">${title}</div>
                        </div>
                    </div>`;
            }
"""
content = content.replace(render_leg_old, render_leg_new)

with open('e:/repositories/Chauffeur/chauffeur/templates/app.html', 'w', encoding='utf-8') as f:
    f.write(content)
print("app.html patched")
