// MeuDocMed Service Worker
// Versão mínima — habilita instalação como PWA (sem cache offline por ora)

const CACHE_NAME = 'meudocmed-v1';

self.addEventListener('install', function(event) {
  self.skipWaiting();
});

self.addEventListener('activate', function(event) {
  event.waitUntil(clients.claim());
});

// Repassa todas as requests normalmente (sem cache offline)
self.addEventListener('fetch', function(event) {
  event.respondWith(fetch(event.request));
});
