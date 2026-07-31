// cloud_relay/api/ai-proxy.js — deploy trên Vercel.
// Desktop App KHÔNG bao giờ cầm DEEPSEEK_API_KEY thật (file .exe có thể bị giải nén đọc
// ngược). Nó gọi tới đây bằng 1 proxy_api_key riêng theo từng license; proxy này mới cầm
// DEEPSEEK_API_KEY thật (biến môi trường server, không nằm trong code) để gọi hộ.
import { Redis } from '@upstash/redis';
import { Ratelimit } from '@upstash/ratelimit';

const redis = Redis.fromEnv();

// Giới hạn 30 request/phút/tenant — chặn 1 license bị lộ/bị lạm dụng làm cháy quota DeepSeek
// dùng chung cho toàn bộ khách hàng qua Proxy này.
const ratelimit = new Ratelimit({
  redis,
  limiter: Ratelimit.slidingWindow(30, '1 m'),
  prefix: 'bitpaw:ai-proxy-ratelimit',
});

export default async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).end();

  try {
    const authHeader = req.headers['authorization'] || '';
    const proxyApiKey = authHeader.startsWith('Bearer ') ? authHeader.slice(7) : null;
    const { business_id, ...deepseekPayload } = req.body || {};

    if (!business_id || !proxyApiKey) {
      return res.status(401).json({ error: 'missing business_id/proxy api key' });
    }

    // proxy_api_key hợp lệ được ghi vào Redis bởi server License của bạn khi cấp/renew license
    // (key: bitpaw:proxy_key:<business_id> -> giá trị proxy key đã cấp cho tenant đó).
    const expectedKey = await redis.get(`bitpaw:proxy_key:${business_id}`);
    if (!expectedKey || expectedKey !== proxyApiKey) {
      return res.status(401).json({ error: 'invalid proxy api key for this business_id' });
    }

    const { success } = await ratelimit.limit(business_id);
    if (!success) {
      return res.status(429).json({ error: 'rate limit exceeded, try again shortly' });
    }

    const deepseekApiKey = process.env.DEEPSEEK_API_KEY; // key THẬT, chỉ tồn tại ở đây
    if (!deepseekApiKey) {
      return res.status(500).json({ error: 'proxy server misconfigured: missing DEEPSEEK_API_KEY' });
    }

    const upstreamResp = await fetch('https://api.deepseek.com/chat/completions', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${deepseekApiKey}`,
      },
      body: JSON.stringify(deepseekPayload),
      signal: AbortSignal.timeout(45000),
    });

    const data = await upstreamResp.json();
    return res.status(upstreamResp.status).json(data);
  } catch (err) {
    console.error('[ai-proxy] request failed:', err);
    return res.status(502).json({ error: 'ai-proxy internal error', detail: String(err) });
  }
}
