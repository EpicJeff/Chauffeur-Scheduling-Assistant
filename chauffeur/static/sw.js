self.addEventListener('install', event => {
    self.skipWaiting();
});

self.addEventListener('activate', event => {
    event.waitUntil(clients.claim());
});

self.addEventListener('push', function(event) {
    if (event.data) {
        try {
            const data = event.data.json();
            const title = data.title || 'Chauffeur';
            const options = {
                body: data.body || '',
                icon: '/static/icon.png',
                badge: '/static/icon.png',
                data: data.data || {},
                actions: data.actions || []
            };
            event.waitUntil(self.registration.showNotification(title, options));
        } catch (e) {
            console.error('Push data is not JSON', e);
        }
    }
});

self.addEventListener('notificationclick', function(event) {
    event.notification.close();
    
    // If the user clicked a specific action button (e.g. "Mark Completed")
    if (event.action === 'complete') {
        const legId = event.notification.data.leg_id;
        if (legId) {
            event.waitUntil(
                fetch('/api/drive_status', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ leg_id: legId, status: 'completed' })
                })
            );
        }
    } else if (event.action === 'navigate') {
        const navigateUrl = event.notification.data.navigate_url;
        if (navigateUrl) {
            event.waitUntil(
                clients.matchAll({ type: 'window', includeUncontrolled: true }).then(windowClients => {
                    for (let i = 0; i < windowClients.length; i++) {
                        const client = windowClients[i];
                        if (client.url.includes('/app') && 'focus' in client) {
                            client.navigate(navigateUrl);
                            return client.focus();
                        }
                    }
                    if (clients.openWindow) {
                        return clients.openWindow(navigateUrl);
                    }
                })
            );
        }
    } else {
        // Just open the app if they clicked the notification body
        const navigateUrl = event.notification.data.navigate_url || '/app';
        event.waitUntil(
            clients.matchAll({ type: 'window', includeUncontrolled: true }).then(windowClients => {
                for (let i = 0; i < windowClients.length; i++) {
                    const client = windowClients[i];
                    if (client.url.includes('/app') && 'focus' in client) {
                        client.navigate(navigateUrl);
                        return client.focus();
                    }
                }
                if (clients.openWindow) {
                    return clients.openWindow(navigateUrl);
                }
            })
        );
    }
});
