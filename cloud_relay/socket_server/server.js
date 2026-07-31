/**
 * Socket.io server THẬT — deploy lên Railway/Render/Fly.io (KHÔNG deploy lên Vercel, Vercel
 * Functions không giữ được tiến trình sống lâu dài nên không thể host WebSocket bền vững).
 *
 * Vai trò: nhận tin nhắn Zalo/FB do webhook.js (chạy trên Vercel) forward sang qua HTTP POST
 * nội bộ, rồi đẩy real-time xuống đúng Desktop app của tenant đang giữ kết nối socket.
 */
const http = require('http');
const express = require('express');
const { Server } = require('socket.io');

const app = express();
app.use(express.json());

const server = http.createServer(app);
const io = new Server(server, { cors: { origin: '*' } });

const INTERNAL_FORWARD_SECRET = process.env.INTERNAL_FORWARD_SECRET;
if (!INTERNAL_FORWARD_SECRET) {
  throw new Error('Thiếu biến môi trường INTERNAL_FORWARD_SECRET — không thể chạy an toàn.');
}

// business_id -> Set<socket.id> — 1 tiệm có thể mở nhiều máy/nhiều tab
const businessSockets = new Map();

io.use((socket, next) => {
  const { business_id, api_key } = socket.handshake.auth || {};
  if (!business_id || api_key !== process.env.DESKTOP_SOCKET_API_KEY) {
    return next(new Error('unauthorized'));
  }
  socket.businessId = business_id;
  next();
});

io.on('connection', (socket) => {
  const set = businessSockets.get(socket.businessId) || new Set();
  set.add(socket.id);
  businessSockets.set(socket.businessId, set);

  socket.on('disconnect', () => {
    const s = businessSockets.get(socket.businessId);
    if (s) {
      s.delete(socket.id);
      if (s.size === 0) businessSockets.delete(socket.businessId);
    }
  });
});

// webhook.js (Vercel) gọi endpoint nội bộ này ngay khi có tin nhắn mới từ Zalo/FB
app.post('/internal/forward', (req, res) => {
  try {
    const auth = req.headers['x-internal-secret'];
    if (auth !== INTERNAL_FORWARD_SECRET) {
      return res.status(401).json({ error: 'unauthorized' });
    }

    const { business_id, message } = req.body || {};
    if (!business_id || !message) {
      return res.status(400).json({ error: 'missing business_id/message' });
    }

    const socketIds = businessSockets.get(business_id);
    if (socketIds && socketIds.size > 0) {
      for (const id of socketIds) {
        io.to(id).emit('new-message', message);
      }
      return res.status(200).json({ delivered: true, sockets: socketIds.size });
    }

    // Desktop app đang offline — không có ai nhận real-time lúc này.
    // KHÔNG được coi đây là lỗi nghiêm trọng (bình thường khi tiệm đóng cửa/tắt máy), nhưng
    // vẫn phải trả tín hiệu rõ ràng để webhook.js biết mà lưu fallback (xem webhook.js).
    return res.status(202).json({ delivered: false, reason: 'desktop app offline' });
  } catch (err) {
    console.error('[socket_server] /internal/forward failed:', err);
    return res.status(500).json({ error: 'internal error', detail: String(err) });
  }
});

app.get('/health', (_req, res) => res.status(200).json({ ok: true, connected_businesses: businessSockets.size }));

const PORT = process.env.PORT || 4000;
server.listen(PORT, () => console.log(`[socket_server] listening on :${PORT}`));
