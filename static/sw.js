const CACHE_NAME = 'gasapp-assets-v3';
const STATIC_ASSETS = [
  '/manifest.json',
  '/static/core/css/home.css',
  '/static/js/offline_sync.js',
  '/static/js/app_campo.js',
  '/static/css/app_campo.css',
  '/static/vendor/inter/inter.css',
  '/static/vendor/sweetalert2/sweetalert2.all.min.js',
  '/static/vendor/apexcharts/apexcharts.min.js',
  '/static/vendor/html2pdf/html2pdf.bundle.min.js',
  '/static/img/icon-192.png',
  '/static/img/icon-512.png',
  '/static/img/icon-192-maskable.png',
  '/static/img/icon-512-maskable.png'
];

// Instalação do Service Worker e cacheamento de assets estáticos (sem páginas autenticadas)
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      console.log('[ServiceWorker] Pré-cacheando shell estático e vendors');
      return cache.addAll(STATIC_ASSETS).catch((err) => {
        console.warn('[ServiceWorker] Aviso ao pré-cachear recursos estáticos:', err);
      });
    }).then(() => self.skipWaiting())
  );
});

// Ativação e limpeza de versões anteriores de cache
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((key) => {
          if (key !== CACHE_NAME) {
            console.log('[ServiceWorker] Removendo cache obsoleto:', key);
            return caches.delete(key);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

// Listener para comando de limpeza imediata no logout (D5)
self.addEventListener('message', (event) => {
  if (event.data && event.data.action === 'CLEAR_CACHES') {
    console.log('[ServiceWorker] Comando de limpeza de cache recebido no Logout.');
    caches.keys().then((keys) => {
      return Promise.all(keys.map((key) => caches.delete(key)));
    });
  }
});

// Interceptação de requisições: Cache estático apenas; páginas HTML e APIs não são salvas em cache autenticado
self.addEventListener('fetch', (event) => {
  const request = event.request;
  const url = new URL(request.url);

  // Não intercepta chamadas POST/PUT/DELETE
  if (request.method !== 'GET') {
    return;
  }

  // APIs: Network-Only com resposta amigável se offline
  if (url.pathname.startsWith('/api/') || url.pathname.includes('/api/')) {
    event.respondWith(
      fetch(request).catch(() => {
        return new Response(
          JSON.stringify({ offline: true, message: 'Operação offline. Registrado no dispositivo.' }),
          { headers: { 'Content-Type': 'application/json' } }
        );
      })
    );
    return;
  }

  // Recursos Estáticos (/static/ e manifest): Cache-First com atualização em background
  if (url.pathname.startsWith('/static/') || url.pathname === '/manifest.json') {
    event.respondWith(
      caches.match(request).then((cachedResponse) => {
        if (cachedResponse) {
          return cachedResponse;
        }
        return fetch(request).then((networkResponse) => {
          if (networkResponse && networkResponse.status === 200) {
            const responseToCache = networkResponse.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, responseToCache));
          }
          return networkResponse;
        });
      })
    );
    return;
  }

  // Navegação HTML: Network-Only para páginas dinâmicas/autenticadas.
  // Se estiver sem conexão, exibe fallback offline sem gravar dados de usuário em cache.
  if (request.mode === 'navigate' || request.headers.get('accept')?.includes('text/html')) {
    event.respondWith(
      fetch(request).catch(() => {
        return new Response(
          '<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8"><title>GasApp Offline</title>' +
          '<meta name="viewport" content="width=device-width, initial-scale=1.0">' +
          '<style>body{background:#0F172A;color:#F8FAFC;font-family:sans-serif;padding:3rem 1.5rem;text-align:center;}' +
          'h2{color:#38BDF8;}p{color:#94A3B8;max-width:480px;margin:1rem auto;line-height:1.6;}' +
          '.badge{background:#10B981;color:#fff;padding:6px 14px;border-radius:20px;font-size:12px;font-weight:600;display:inline-block;margin-top:1rem;}' +
          '</style></head><body><h2>GasApp - Modo Operacional Offline</h2>' +
          '<p>Você está temporariamente sem conexão com a internet. Suas bipagens locais continuam seguras no dispositivo e serão sincronizadas automaticamente assim que o sinal for restabelecido.</p>' +
          '<span class="badge">Operação Local Ativa</span></body></html>',
          { headers: { 'Content-Type': 'text/html; charset=utf-8' } }
        );
      })
    );
  }
});
