const CACHE = 'adam-v1';
const ASSETS = ['/', '/index.html'];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  // API calls — zawsze sieć
  if (e.request.url.includes('/chat') || e.request.url.includes('/analyze')) {
    return;
  }
  // Reszta — cache first
  e.respondWith(
    caches.match(e.request).then(r => r || fetch(e.request))
  );
});