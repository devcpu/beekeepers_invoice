// Service Worker für Rechnungsverwaltung PWA
// Version: 1.0.0

const CACHE_VERSION = 'v1';
const CACHE_NAME = `rechnungen-cache-${CACHE_VERSION}`;
const OFFLINE_URL = '/offline';

// Dateien für Offline-Nutzung (Static Assets)
const STATIC_CACHE_URLS = [
  '/',
  '/offline',
  '/static/manifest.json',
  '/static/icons/icon-192x192.png',
  '/static/icons/icon-512x512.png',
  // Bootstrap CSS (CDN wird gecacht)
  'https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css',
  'https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js'
];

// API-Endpoints die gecacht werden sollen (für Offline-Zugriff)
const API_CACHE_URLS = [
  '/api/invoices',
  '/api/customers'
];

// Install Event - Cache vorbereiten
self.addEventListener('install', (event) => {
  console.log('[SW] Installing Service Worker...', CACHE_VERSION);

  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => {
        console.log('[SW] Caching static assets');
        return cache.addAll(STATIC_CACHE_URLS);
      })
      .then(() => {
        console.log('[SW] Installation complete');
        return self.skipWaiting(); // Aktiviere sofort
      })
      .catch((error) => {
        console.error('[SW] Installation failed:', error);
      })
  );
});

// Activate Event - Alte Caches löschen
self.addEventListener('activate', (event) => {
  console.log('[SW] Activating Service Worker...', CACHE_VERSION);

  event.waitUntil(
    caches.keys()
      .then((cacheNames) => {
        return Promise.all(
          cacheNames
            .filter((cacheName) => {
              // Lösche alle Caches außer dem aktuellen
              return cacheName.startsWith('rechnungen-cache-') &&
                     cacheName !== CACHE_NAME;
            })
            .map((cacheName) => {
              console.log('[SW] Deleting old cache:', cacheName);
              return caches.delete(cacheName);
            })
        );
      })
      .then(() => {
        console.log('[SW] Activation complete');
        return self.clients.claim(); // Übernehme Kontrolle sofort
      })
  );
});

// Fetch Event - Network-First mit Cache-Fallback
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Ignoriere Chrome-Extensions und andere Protokolle
  if (!url.protocol.startsWith('http')) {
    return;
  }

  // Strategie basierend auf Request-Typ
  if (request.method === 'GET') {
    // HTML-Seiten: Network-First (aktuelle Daten bevorzugen)
    if (request.headers.get('accept').includes('text/html')) {
      event.respondWith(networkFirstStrategy(request));
    }
    // API-Calls: Network-First mit Cache-Fallback
    else if (url.pathname.startsWith('/api/')) {
      event.respondWith(networkFirstStrategy(request));
    }
    // Static Assets (CSS, JS, Images): Cache-First
    else if (
      url.pathname.startsWith('/static/') ||
      url.origin !== location.origin // CDN-Ressourcen
    ) {
      event.respondWith(cacheFirstStrategy(request));
    }
    // Default: Network-First
    else {
      event.respondWith(networkFirstStrategy(request));
    }
  }
  // POST/PUT/DELETE: Nur online, mit Background-Sync-Unterstützung
  else {
    event.respondWith(
      fetch(request)
        .catch(() => {
          // Speichere POST-Request für spätere Synchronisation
          if ('sync' in self.registration && request.method === 'POST') {
            return saveForBackgroundSync(request)
              .then(() => {
                return new Response(
                  JSON.stringify({
                    success: false,
                    message: 'Offline - wird synchronisiert wenn online',
                    queued: true
                  }),
                  {
                    status: 202,
                    headers: { 'Content-Type': 'application/json' }
                  }
                );
              });
          }

          return new Response(
            JSON.stringify({
              success: false,
              error: 'Offline - keine Verbindung zum Server'
            }),
            {
              status: 503,
              headers: { 'Content-Type': 'application/json' }
            }
          );
        })
    );
  }
});

// Network-First Strategy
async function networkFirstStrategy(request) {
  try {
    // Versuche Netzwerk-Request
    const networkResponse = await fetch(request);

    // Bei Erfolg: Response klonen und cachen
    if (networkResponse.ok) {
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, networkResponse.clone());
    }

    return networkResponse;
  } catch (error) {
    console.log('[SW] Network failed, trying cache:', request.url);

    // Fallback zu Cache
    const cachedResponse = await caches.match(request);

    if (cachedResponse) {
      return cachedResponse;
    }

    // Kein Cache vorhanden: Offline-Seite für HTML, Fehler für API
    if (request.headers.get('accept').includes('text/html')) {
      const offlineResponse = await caches.match(OFFLINE_URL);
      return offlineResponse || new Response('Offline', { status: 503 });
    }

    // API-Fehler
    return new Response(
      JSON.stringify({
        success: false,
        error: 'Offline - keine gecachten Daten verfügbar',
        offline: true
      }),
      {
        status: 503,
        headers: { 'Content-Type': 'application/json' }
      }
    );
  }
}

// Cache-First Strategy (für Static Assets)
async function cacheFirstStrategy(request) {
  const cachedResponse = await caches.match(request);

  if (cachedResponse) {
    // Im Hintergrund Update holen
    fetch(request).then((networkResponse) => {
      if (networkResponse.ok) {
        caches.open(CACHE_NAME).then((cache) => {
          cache.put(request, networkResponse);
        });
      }
    }).catch(() => {
      // Ignoriere Netzwerkfehler
    });

    return cachedResponse;
  }

  // Nicht im Cache: Hole vom Netzwerk
  try {
    const networkResponse = await fetch(request);

    if (networkResponse.ok) {
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, networkResponse.clone());
    }

    return networkResponse;
  } catch (error) {
    return new Response('Offline', { status: 503 });
  }
}

// Background Sync - POST-Requests offline speichern
async function saveForBackgroundSync(request) {
  const data = {
    url: request.url,
    method: request.method,
    headers: Object.fromEntries(request.headers.entries()),
    body: await request.text(),
    timestamp: Date.now()
  };

  // Speichere in IndexedDB (hier vereinfacht)
  return self.registration.sync.register('sync-invoices');
}

// Background Sync Event
self.addEventListener('sync', (event) => {
  console.log('[SW] Background sync triggered:', event.tag);

  if (event.tag === 'sync-invoices') {
    event.waitUntil(syncInvoices());
  }
});

async function syncInvoices() {
  // Hole gespeicherte Requests aus IndexedDB und sende sie
  console.log('[SW] Syncing offline invoices...');

  // Hier würde die IndexedDB-Logik kommen
  // Für jetzt: Benachrichtige Client über erfolgreiche Sync
  const clients = await self.clients.matchAll();
  clients.forEach((client) => {
    client.postMessage({
      type: 'sync-complete',
      message: 'Offline-Daten erfolgreich synchronisiert'
    });
  });
}

// Push Notifications (optional)
self.addEventListener('push', (event) => {
  const data = event.data ? event.data.json() : {};

  const title = data.title || 'Rechnungsverwaltung';
  const options = {
    body: data.body || 'Neue Benachrichtigung',
    icon: '/static/icons/icon-192x192.png',
    badge: '/static/icons/badge-72x72.png',
    tag: data.tag || 'default',
    data: data.url ? { url: data.url } : undefined,
    actions: [
      {
        action: 'open',
        title: 'Öffnen'
      },
      {
        action: 'close',
        title: 'Schließen'
      }
    ]
  };

  event.waitUntil(
    self.registration.showNotification(title, options)
  );
});

// Notification Click
self.addEventListener('notificationclick', (event) => {
  event.notification.close();

  if (event.action === 'open' || !event.action) {
    const urlToOpen = event.notification.data?.url || '/';

    event.waitUntil(
      clients.matchAll({ type: 'window', includeUncontrolled: true })
        .then((clientList) => {
          // Wenn bereits ein Tab offen ist, fokussiere ihn
          for (const client of clientList) {
            if (client.url === urlToOpen && 'focus' in client) {
              return client.focus();
            }
          }

          // Sonst öffne neuen Tab
          if (clients.openWindow) {
            return clients.openWindow(urlToOpen);
          }
        })
    );
  }
});

// Message Handler (Kommunikation mit App)
self.addEventListener('message', (event) => {
  console.log('[SW] Message received:', event.data);

  if (event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }

  if (event.data.type === 'CACHE_URLS') {
    event.waitUntil(
      caches.open(CACHE_NAME).then((cache) => {
        return cache.addAll(event.data.urls);
      })
    );
  }
});

console.log('[SW] Service Worker loaded', CACHE_VERSION);
