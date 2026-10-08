/* 서비스 워커: 앱 껍데기를 저장해 두고, 네트워크가 안 될 때 마지막으로 본 기사 목록을 보여 준다.
 * 전략
 *  - 화면(/)        : 네트워크 우선 → 실패하면 저장본 (온라인이면 항상 최신 UI)
 *  - /api/news,summary: 네트워크 우선 → 실패하면 마지막 응답(헤더 x-from-cache: 1 을 붙여 화면이 알 수 있게 함)
 *  - 아이콘·매니페스트 : 저장본 우선, 뒤에서 갱신
 * 버전을 올리면(VERSION) 이전 저장본은 자동으로 지워진다.
 */
const VERSION = 'v1';
const SHELL = 'shell-' + VERSION;
const DATA = 'data-' + VERSION;
const SHELL_FILES = ['/', '/manifest.webmanifest', '/icons/icon-192.png', '/icons/icon-512.png', '/icons/favicon-64.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(SHELL).then(c => c.addAll(SHELL_FILES)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => ![SHELL, DATA].includes(k)).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

async function networkFirst(req, cacheName, fallbackKey) {
  const cache = await caches.open(cacheName);
  try {
    const res = await fetch(req);
    if (res.ok) cache.put(fallbackKey || req, res.clone());
    return res;
  } catch (err) {
    const hit = await cache.match(fallbackKey || req);
    if (!hit) throw err;
    const headers = new Headers(hit.headers);
    headers.set('x-from-cache', '1');
    return new Response(await hit.blob(), { status: hit.status, statusText: hit.statusText, headers });
  }
}

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return; // 외부 글꼴 등은 브라우저가 알아서

  if (url.pathname.startsWith('/api/')) {
    e.respondWith(networkFirst(req, DATA));
    return;
  }
  if (req.mode === 'navigate') {
    e.respondWith(networkFirst(req, SHELL, '/'));
    return;
  }
  if (url.pathname === '/sw.js') return;
  e.respondWith(
    caches.open(SHELL).then(async c => {
      const hit = await c.match(req);
      const net = fetch(req).then(res => { if (res.ok) c.put(req, res.clone()); return res; }).catch(() => hit);
      return hit || net;
    })
  );
});
