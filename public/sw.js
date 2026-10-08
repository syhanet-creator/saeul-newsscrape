/* 서비스 워커: 앱 껍데기를 저장해 두고, 네트워크가 안 될 때 마지막으로 본 기사 목록을 보여 준다.
 * 전략
 *  - 화면(/)            : 네트워크 우선 → 실패하면 저장본 (온라인이면 항상 최신 UI)
 *  - /api/news, summary : 네트워크 우선 → 실패하면 마지막 응답(헤더 x-from-cache: 1 을 붙여 화면이 알 수 있게 함). 최근 8개만 보관.
 *  - /api/author        : 저장하지 않는다(화면이 브라우저에 따로 저장한다)
 *  - 아이콘·매니페스트   : 저장본 우선, 뒤에서 갱신
 * 버전을 올리면(VERSION) 이전 저장본은 자동으로 지워진다.
 */
const VERSION = 'v2';
const SHELL = 'shell-' + VERSION;
const DATA = 'data-' + VERSION;
const SHELL_FILES = ['/', '/manifest.webmanifest', '/icons/icon-192.png', '/icons/icon-512.png', '/icons/maskable-512.png', '/icons/favicon-64.png'];
const MAX_DATA_ENTRIES = 8;

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

async function trim(cache, max) {
  const keys = await cache.keys();
  for (const k of keys.slice(0, Math.max(0, keys.length - max))) await cache.delete(k); // 오래된 것부터
}

async function networkFirst(req, cacheName, fallbackKey, max) {
  const cache = await caches.open(cacheName);
  try {
    const res = await fetch(req);
    if (res.ok) {
      await cache.put(fallbackKey || req, res.clone());
      if (max) trim(cache, max);
    }
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

  if (url.pathname === '/api/author') return; // 저장하지 않고 그대로 네트워크로
  if (url.pathname.startsWith('/api/')) {
    e.respondWith(networkFirst(req, DATA, null, MAX_DATA_ENTRIES));
    return;
  }
  if (req.mode === 'navigate') {
    e.respondWith(networkFirst(req, SHELL, '/'));
    return;
  }
  // 아이콘·매니페스트 같은 알려진 정적 파일만 저장본 우선(그 외는 브라우저가 알아서)
  if (!(SHELL_FILES.includes(url.pathname) || url.pathname.startsWith('/icons/'))) return;
  e.respondWith(
    caches.open(SHELL).then(async c => {
      const hit = await c.match(url.pathname);
      const net = fetch(req).then(res => { if (res.ok) c.put(url.pathname, res.clone()); return res; }).catch(() => hit);
      return hit || net;
    })
  );
});
