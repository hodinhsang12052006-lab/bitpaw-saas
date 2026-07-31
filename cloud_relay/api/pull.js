// cloud_relay/api/pull.js
// Desktop app gọi endpoint này mỗi 2-3 giây (xem desktop_app/realtime_client.py) để lấy tin
// nhắn mới rồi xoá khỏi hàng đợi (at-most-once, đủ dùng cho 1 nhân viên/1 máy đọc).
import { Redis } from '@upstash/redis';

const redis = Redis.fromEnv();

export default async function handler(req, res) {
  const { business_id, api_key } = req.query;

  if (!business_id || api_key !== process.env.DESKTOP_PULL_API_KEY) {
    return res.status(401).json({ error: 'unauthorized' });
  }

  const queueKey = `bitpaw:inbox:${business_id}`;
  const items = await redis.lrange(queueKey, 0, -1);
  if (items.length > 0) {
    await redis.del(queueKey);
  }

  return res.status(200).json({
    messages: items.map((i) => (typeof i === 'string' ? JSON.parse(i) : i)),
    server_time: Date.now(),
  });
}
