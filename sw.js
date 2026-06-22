// Deco 巡查台 · 轻量 Service Worker（用于 PWA 安装）
// 不缓存 data/ 目录，保证周报和状态始终是最新的。
self.addEventListener('install', (e) => { self.skipWaiting(); });
self.addEventListener('activate', (e) => { self.clients.claim(); });
self.addEventListener('fetch', (e) => {
  // 直接走网络，不做激进缓存
  return;
});
