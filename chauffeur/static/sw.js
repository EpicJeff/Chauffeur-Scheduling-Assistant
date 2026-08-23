// The auth shelf. A service worker cannot read localStorage — that API does
// not exist in a worker — and the notification actions below run with NO page
// open, so there is nobody to ask for the token either. The Cache API is the
// one store both the window and the worker can reach, so the app MIRRORS the
// member token into it (see `mirrorTokenToServiceWorker` in app.html) and the
// worker reads it here.
//
// This is not a nicety. Until v2.383.0 the "Mark Completed" action posted the
// drive with no credential at all, which worked only because the app was
// serving every request to anybody. The moment auth enforcement is switched
// on, `/api/drive_status` requires a signed-in member, and a lock-screen tap
// could never have proved it was one.
const AUTH_CACHE = 'chauffeur-auth-v1';
const AUTH_KEY = '/__sw/member-token';

self.addEventListener('install', event => {
    self.skipWaiting();
});

self.addEventListener('activate', event => {
    event.waitUntil(clients.claim());
});

async function memberToken() {
    try {
        const cache = await caches.open(AUTH_CACHE);
        const res = await cache.match(AUTH_KEY);
        return res ? (await res.text()).trim() : '';
    } catch (e) {
        return '';
    }
}

// Focus the app if it is already open, else launch it. Was written out twice
// below, identically apart from where the url came from.
async function openApp(url) {
    const windowClients = await clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (let i = 0; i < windowClients.length; i++) {
        const client = windowClients[i];
        if (client.url.includes('/app') && 'focus' in client) {
            client.navigate(url);
            return client.focus();
        }
    }
    if (clients.openWindow) {
        return clients.openWindow(url);
    }
}

// Check a drive off from the lock screen. Two failure modes, both of which
// used to be indistinguishable from success because the old code fired the
// request and never looked at the answer: this device holds no token (nobody
// signed in on it, or the stored one belongs to somebody else), and the
// server refused. Neither is allowed to look like a completed drive.
async function completeLeg(legId, fallbackUrl) {
    const token = await memberToken();
    // Unprovable taps go to the app rather than to a request that will be
    // turned away — the driver finishes the job in one more tap instead of
    // watching the notification vanish and nothing happen.
    if (!token) {
        return openApp(fallbackUrl);
    }
    let ok = false;
    try {
        const res = await fetch('/api/drive_status', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Member-Token': token },
            body: JSON.stringify({ leg_id: legId, status: 'completed' })
        });
        ok = res.ok;
    } catch (e) {
        ok = false;
    }
    if (!ok) {
        // Say so. A drive the driver believes is checked off, and isn't, is
        // worse than one they know they still have to check off.
        await self.registration.showNotification('Could not check that drive off', {
            body: 'Tap to open Chauffeur and finish it.',
            icon: '/static/icon.png',
            badge: '/static/icon.png',
            data: { navigate_url: fallbackUrl }
        });
    }
}

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
            event.waitUntil(completeLeg(legId, event.notification.data.navigate_url || '/app'));
        }
    } else if (event.action === 'navigate') {
        const navigateUrl = event.notification.data.navigate_url;
        if (navigateUrl) {
            event.waitUntil(openApp(navigateUrl));
        }
    } else {
        // Just open the app if they clicked the notification body
        event.waitUntil(openApp(event.notification.data.navigate_url || '/app'));
    }
});
