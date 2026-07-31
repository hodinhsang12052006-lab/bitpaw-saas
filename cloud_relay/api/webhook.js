// cloud_relay/api/webhook.js — deploy trên Vercel (stateless, đúng sở trường của Vercel).
// Nhận Webhook Zalo OA / Facebook Messenger, forward NGAY sang Socket.io server thật
// (cloud_relay/socket_server/, chạy trên Railway/Render) để đẩy real-time xuống Desktop app.
// Nếu Desktop app đang offline, fallback lưu vào Upstash Redis để lấy bù sau (xem api/pull.js).
import { Redis } from '@upstash/redis';

const redis = Redis.fromEnv();
const FB_VERIFY_TOKEN = process.env.FB_VERIFY_TOKEN;
const SOCKET_SERVER_URL = process.env.SOCKET_SERVER_URL; // vd: https://bitpaw-relay.up.railway.app
const INTERNAL_FORWARD_SECRET = process.env.INTERNAL_FORWARD_SECRET;

export default async function handler(req, res) {
  if (req.method === 'GET') {
    const mode = req.query['hub.mode'];
    const token = req.query['hub.verify_token'];
    const challenge = req.query['hub.challenge'];
    if (mode === 'subscribe' && token === FB_VERIFY_TOKEN) {
      return res.status(200).send(challenge);
    }
    return res.status(403).send('Forbidden');
  }

  if (req.method !== 'POST') return res.status(405).end();

  const body = req.body;
  // BẮT BUỘC trước production thật: xác thực chữ ký request (X-Hub-Signature-256 của FB,
  // "mac" của Zalo) bằng App Secret tương ứng — bỏ qua ở bản scaffold để giữ ngắn gọn.

  const businessId = resolveBusinessId(body);
  const message = {
    platform: body.object === 'page' ? 'facebook' : 'zalo',
    payload: body,
    received_at: Date.now(),
  };

  let deliveredRealtime = false;
  try {
    const forwardResp = await fetch(`${SOCKET_SERVER_URL}/internal/forward`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Internal-Secret': INTERNAL_FORWARD_SECRET,
      },
      body: JSON.stringify({ business_id: businessId, message }),
      signal: AbortSignal.timeout(4000),
    });
    if (forwardResp.ok) {
      const result = await forwardResp.json();
      deliveredRealtime = Boolean(result.delivered);
    }
  } catch (err) {
    // Socket server tạm thời down hoặc timeout — KHÔNG được để mất tin nhắn, rơi xuống nhánh
    // lưu Redis bên dưới thay vì bỏ qua lỗi này.
    console.error('[webhook] forward to socket server failed:', err);
  }

  if (!deliveredRealtime) {
    // Desktop app offline hoặc socket server lỗi — lưu tạm để Desktop app tự bù lại qua
    // GET /api/pull khi mở lại (xem realtime_client.py bản polling dự phòng).
    const queueKey = `bitpaw:inbox:${businessId}`;
    await redis.rpush(queueKey, JSON.stringify(message));
    await redis.ltrim(queueKey, -500, -1);
  }

  return res.status(200).json({ ok: true, delivered_realtime: deliveredRealtime });
}

function resolveBusinessId(body) {
  return body?.entry?.[0]?.id || 'unknown';
}
