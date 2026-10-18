/* BitPaw — service worker tối giản để cài web app ra màn hình chính (iPhone/iPad/Android/POS).
   KHÔNG cache dữ liệu (tránh hiện số liệu cũ/sai tiền): chỉ khi mở trang mà mất mạng thì hiện trang báo + tự thử lại.
   Không chạm request API, SSE, POST hay file tải về. */
const OFFLINE_HTML = `<!doctype html><html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>BitPaw</title><style>body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:#0b0f17;color:#e5e7eb;
font-family:system-ui,-apple-system,Segoe UI,Arial,sans-serif;text-align:center}.c{max-width:420px;padding:28px}img{width:84px;height:84px;border-radius:20px}
h1{color:#fb923c;font-size:20px;margin:18px 0 8px}p{color:#9ca3af;line-height:1.6;font-size:14px}button{margin-top:14px;padding:12px 26px;border:0;border-radius:12px;
background:#f97316;color:#fff;font-weight:700;font-size:15px}</style></head><body><div class="c"><img src="/static/brand/icon-192.png" alt="BitPaw">
<h1>Không có kết nối mạng · No internet</h1><p>Kiểm tra Wi-Fi/4G rồi thử lại — tự thử lại mỗi 10 giây.<br>Check your connection — retrying every 10 seconds.</p>
<button onclick="location.reload()">Thử lại · Retry</button></div><script>setInterval(function(){fetch('/login',{method:'HEAD',cache:'no-store'}).then(function(){location.reload()}).catch(function(){})},10000)</script></body></html>`;

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.mode !== 'navigate' || req.method !== 'GET') return;
  const path = new URL(req.url).pathname;
  if (path.startsWith('/dl/') || path.startsWith('/download/') || path.startsWith('/static/')) return;
  event.respondWith(fetch(req).catch(() => new Response(OFFLINE_HTML, { headers: { 'Content-Type': 'text/html; charset=utf-8' } })));
});
