"""
AI lên kế hoạch đăng bài cho AI Social Manager (docs/AI_SUITE_SPEC.md §4.3):
  - best_times: giờ đăng tốt nhất — HỌC từ số liệu THẬT của chính tiệm (≥ 10 bài có số liệu trên nền tảng đó), co về
    mặc định ngành (empirical Bayes, k=5) để vài bài may mắn không làm lệch; chưa đủ dữ liệu thì nói rõ là mặc định ngành.
  - captions: viết lại 1 nội dung cho từng nền tảng (DeepSeek), chỉ dùng dữ kiện thật của tiệm.
  - weekly_plan: kế hoạch tuần từ DỮ LIỆU THẬT (dịch vụ + giá, khuyến mãi đang chạy, ảnh sản phẩm thật, mẹo chăm sóc) ->
    bài 'pending_approval' (chủ tiệm duyệt mới đăng). Không tự sinh ảnh tốn tiền: bài không có ảnh thật chỉ kèm gợi ý.
  - performance_review: nhận xét hiệu quả từ số THẬT; < 3 bài có số liệu thì nói thẳng chưa đủ dữ liệu, không gọi AI.
"""
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, wait as _wait
from datetime import date, datetime, time as dtime, timedelta, timezone

from mongo_client import db, next_mongo_id
import social_accounts as sa
from social_accounts import SocialError, as_utc, iso_z, utcnow

# ---------------------------------------------------------------- MẶC ĐỊNH NGÀNH (có nguồn) — KHÔNG phải số đo của tiệm
# Nguồn tham khảo (báo cáo công khai, cập nhật hằng năm; dữ liệu tổng hợp nhiều ngành, theo giờ địa phương người xem):
#   - Sprout Social, "Best Times to Post on Social Media" — https://sproutsocial.com/insights/best-times-to-post-on-social-media/
#   - Hootsuite, "The best time to post on social media" — https://blog.hootsuite.com/best-time-to-post-on-social-media/
#   - Later, "Best Time to Post on Instagram" — https://later.com/blog/best-time-to-post-on-instagram/
#     và "Best Time to Post on TikTok" — https://later.com/blog/best-time-to-post-on-tiktok/
#   - Google Business Profile Help, "Create posts on your Business Profile" — https://support.google.com/business/answer/7662907
#     (Google KHÔNG công bố khung giờ — dùng sáng ngày thường, lúc khách tìm dịch vụ "gần đây").
# Các khung giờ dưới đây là ƯỚC LƯỢNG ĐÃ LÀM TRÒN từ phần tóm tắt công khai của các báo cáo trên (ngày thường buổi
# sáng–trưa cho Facebook, trưa–chiều cho Instagram, chiều–tối cho TikTok, chiều/cuối tuần cho YouTube), rồi chỉnh theo
# nhịp khách của từng ngành dịch vụ địa phương (nail/spa: trưa + tối, khách đặt lịch cho cuối tuần từ thứ Năm–Sáu;
# F&B: trước bữa trưa/tối; karaoke: tối cuối tuần). weight 0–1 = độ ưu tiên tương đối, KHÔNG phải tỷ lệ tương tác.
# Đây là MẶC ĐỊNH; tiệm có ≥ 10 bài có số liệu thật trên 1 nền tảng thì best_times học từ chính số của tiệm.
# (weekday 0 = thứ Hai, hour = giờ địa phương của tiệm)
_BASE = {
    'facebook': [(0, 9, 0.8), (1, 10, 0.9), (2, 10, 1.0), (3, 11, 0.9), (4, 9, 0.8), (2, 13, 0.7), (5, 10, 0.5)],
    'instagram': [(1, 11, 0.9), (2, 12, 1.0), (3, 11, 0.9), (4, 10, 0.8), (0, 12, 0.7), (2, 17, 0.7), (6, 10, 0.5)],
    'tiktok': [(1, 16, 0.9), (2, 17, 1.0), (3, 18, 0.9), (4, 17, 0.8), (5, 11, 0.6), (6, 19, 0.6), (0, 19, 0.6)],
    'youtube': [(3, 15, 0.9), (4, 15, 1.0), (5, 11, 0.9), (6, 11, 0.8), (2, 16, 0.7)],
    'google_business': [(0, 9, 0.9), (2, 9, 1.0), (3, 9, 0.9), (4, 8, 0.8)],
}
_BEAUTY = {   # nail / spa: khách lướt điện thoại giờ nghỉ trưa + tối, chốt lịch cuối tuần từ thứ Năm–Sáu
    'facebook': [(3, 12, 1.0), (4, 12, 0.9), (2, 19, 0.8), (6, 19, 0.8), (1, 12, 0.7), (5, 9, 0.6)],
    'instagram': [(3, 12, 1.0), (4, 18, 0.9), (2, 19, 0.8), (6, 19, 0.8), (1, 12, 0.7), (5, 10, 0.6)],
    'tiktok': [(3, 19, 1.0), (4, 18, 0.9), (2, 19, 0.8), (6, 20, 0.8), (5, 12, 0.6)],
}
INDUSTRY_PRIORS = {
    'default': _BASE,
    'nail': {**_BASE, **_BEAUTY},
    'spa': {**_BASE, **_BEAUTY},
    'fnb': {**_BASE,   # trước bữa trưa và trước bữa tối, cuối tuần nhiều hơn
            'facebook': [(4, 11, 1.0), (3, 11, 0.9), (4, 17, 0.9), (5, 10, 0.8), (2, 11, 0.7), (6, 10, 0.7)],
            'instagram': [(4, 11, 1.0), (5, 11, 0.9), (3, 17, 0.8), (4, 17, 0.8), (6, 10, 0.7)],
            'tiktok': [(4, 17, 1.0), (5, 12, 0.9), (3, 18, 0.8), (6, 17, 0.7)]},
    'retail': {**_BASE,   # tối ngày thường + sáng thứ Bảy (đi mua sắm)
               'facebook': [(2, 19, 1.0), (3, 19, 0.9), (5, 9, 0.9), (1, 12, 0.7), (6, 18, 0.7)],
               'instagram': [(2, 19, 1.0), (3, 20, 0.9), (5, 10, 0.9), (6, 18, 0.7), (1, 12, 0.7)]},
    'karaoke': {**_BASE,   # tối thứ Năm–Bảy (rủ nhau đi chơi)
                'facebook': [(3, 18, 1.0), (4, 17, 1.0), (5, 15, 0.8), (2, 19, 0.7)],
                'instagram': [(3, 19, 1.0), (4, 18, 1.0), (5, 16, 0.8), (2, 20, 0.7)],
                'tiktok': [(4, 20, 1.0), (5, 20, 0.9), (3, 20, 0.8)]},
    'hotel': {**_BASE,   # khách lên kế hoạch chuyến đi tối Chủ nhật–thứ Ba
              'facebook': [(6, 19, 1.0), (0, 20, 0.9), (1, 19, 0.8), (3, 12, 0.7)],
              'instagram': [(6, 19, 1.0), (0, 20, 0.9), (2, 12, 0.7), (4, 18, 0.7)]},
}
# Tần suất gợi ý cho tiệm địa phương (bài/tuần) — MẶC ĐỊNH, nguồn:
#   - Hootsuite, "How often to post on social media" — https://blog.hootsuite.com/how-often-to-post-on-social-media/
#   - HubSpot, "How Often Should You Post on Social Media" — https://blog.hubspot.com/marketing/social-media-posting-schedule
#   - Google Business Profile Help (link trên): Google không công bố tần suất; đăng đều ~1 bài/tuần để hồ sơ luôn mới.
# Đã hạ xuống mức 1 tiệm nhỏ làm đều được (các báo cáo trên viết cho thương hiệu có đội ngũ nội dung).
FREQUENCY = {
    'facebook': {'min': 3, 'max': 5, 'default': 3},
    'instagram': {'min': 3, 'max': 5, 'default': 3},
    'tiktok': {'min': 2, 'max': 5, 'default': 3},
    'youtube': {'min': 1, 'max': 3, 'default': 1},
    'google_business': {'min': 1, 'max': 2, 'default': 1},
}
LEARN_MIN_POSTS = 10
SHRINK_K = 5
# Kỳ vọng mặc định của 1 ô (thứ, khung 3 giờ) = tỷ lệ tương tác trung bình CỦA TIỆM × (0.85 + 0.4 × weight):
# mặc định ngành chỉ "nghiêng" quanh mức của tiệm (-15%..+25%) — đủ để xếp hạng khi chưa có dữ liệu ở ô đó, không lấn át
# số thật (ô có nhiều bài thật tốt hơn hẳn trung bình sẽ vượt lên).
PRIOR_BASE = 0.85
PRIOR_LIFT = 0.4
PLAN_PLATFORMS = ('facebook', 'instagram', 'google_business')   # TikTok không bao giờ tự đăng; YouTube cần video
# Kế hoạch tuần: mỗi bài cần caption + bản Instagram (≤2200) + bản Google (≤1500) + hashtag + gợi ý ảnh ≈ 400–700 token
# (tiếng Việt tốn hơn) -> chia lô 3 bài / lần gọi DeepSeek, các lô chạy song song để cả kế hoạch vẫn xong trong 1 request.
PLAN_BATCH = 3
PLAN_TOKENS_PER_ITEM = 700
PLAN_WAIT_SECONDS = 50


# ---------------------------------------------------------------- giờ đăng tốt nhất
def _priors(business_id, platform):
    ind = sa.business_industry(business_id)
    table = INDUSTRY_PRIORS.get(ind) or INDUSTRY_PRIORS['default']
    return table.get(platform) or _BASE.get(platform) or []


def engagement_rate(metrics):
    """(thích + bình luận + chia sẻ + lưu) / max(tiếp cận hoặc lượt xem, 1). None nếu nền tảng không trả đủ để tính."""
    m = metrics or {}
    base = m.get('reach') or m.get('views')
    inter = [m[k] for k in ('likes', 'comments', 'shares', 'saves') if isinstance(m.get(k), (int, float))]
    if not isinstance(base, (int, float)) or not inter:
        return None
    return sum(inter) / max(base, 1)


def _world():
    """Bài/số liệu tạo lúc thử (máy giả) và bài thật không bao giờ lẫn nhau (cùng bộ lọc social_publisher._world)."""
    return {'qa_test': True} if sa.test_mode() else {'qa_test': {'$ne': True}}


def _samples(business_id, platform, tz):
    """[(weekday, hour, rate)] theo giờ địa phương lúc bài THẬT SỰ lên, từ số liệu thật (chỉ bài cùng 'thế giới': số giả
    của lần chạy thử không bao giờ thành "giờ tốt nhất đã học" của tiệm thật)."""
    rows = list(db.social_post_metrics.find({'business_id': business_id, 'platform': platform}, {'_id': 0}).limit(500))
    if not rows:
        return []
    posts = {p['id']: p for p in db.social_posts.find({'business_id': business_id, **_world(),
                                                        'id': {'$in': [r['post_id'] for r in rows]}},
                                                       {'_id': 0, 'id': 1, 'targets': 1, 'scheduled_at': 1})}
    out = []
    for r in rows:
        rate = engagement_rate(r.get('metrics'))
        p = posts.get(r['post_id'])
        if rate is None or not p:
            continue
        t = next((x for x in p.get('targets') or [] if x.get('platform') == platform), {})
        when = as_utc(t.get('published_at')) or as_utc(p.get('scheduled_at'))
        if not when:
            continue
        local = when.astimezone(tz)
        out.append((local.weekday(), local.hour, rate))
    return out


def best_times(business_id, platform, n=3):
    if platform not in sa.PLATFORMS:
        raise SocialError('bad_platform', 'Unknown platform.', platform)
    n = max(1, min(int(n or 3), 10))
    tz = sa.shop_tz(business_id)
    prior = _priors(business_id, platform)
    samples = _samples(business_id, platform, tz)
    size = len(samples)
    if size < LEARN_MIN_POSTS:
        slots = sorted(prior, key=lambda s: (-s[2], s[0], s[1]))[:n]
        return {'source': 'default', 'slots': [{'weekday': d, 'hour': h, 'score': round(w, 4)} for d, h, w in slots],
                'sample_size': size, 'timezone': str(tz),
                'note': f"Industry default (published research) — switches to your own results after {LEARN_MIN_POSTS} posts "
                        f"with real numbers on {sa.LABELS[platform]} (you have {size}).",
                'note_vi': f"Mặc định theo ngành (từ các báo cáo công khai) — tự chuyển sang số thật của tiệm khi có "
                           f"{LEARN_MIN_POSTS} bài có số liệu trên {sa.LABELS[platform]} (hiện có {size})."}
    # ô = (thứ, khung 3 giờ). Mặc định ngành -> kỳ vọng tương đối của từng ô, quy về tỷ lệ tương tác trung bình của tiệm
    pw, phour = {}, {}
    for d, h, w in prior:
        cell = (d, h // 3)
        if w > pw.get(cell, 0):
            pw[cell], phour[cell] = w, h
    cells = [(d, b) for d in range(7) for b in range(8)]
    shop_mean = sum(r for _, _, r in samples) / size
    data, hours = {}, {}
    for d, h, r in samples:
        data.setdefault((d, h // 3), []).append(r)
        hours.setdefault((d, h // 3), []).append(h)
    scored = []
    for c in cells:
        prior_mean = shop_mean * (PRIOR_BASE + PRIOR_LIFT * pw.get(c, 0))
        xs = data.get(c, [])
        # empirical Bayes: (tổng quan sát + k × kỳ vọng mặc định) / (số quan sát + k)
        post = (sum(xs) + SHRINK_K * prior_mean) / (len(xs) + SHRINK_K)
        hour = phour.get(c)
        if hour is None:
            hs = sorted(hours.get(c, []))
            hour = hs[len(hs) // 2] if hs else c[1] * 3 + 1
        scored.append((post, len(xs), c[0], hour))
    scored.sort(key=lambda x: (-x[0], -x[1], x[2], x[3]))
    return {'source': 'learned', 'slots': [{'weekday': d, 'hour': h, 'score': round(s, 4), 'posts': k} for s, k, d, h in scored[:n]],
            'sample_size': size, 'timezone': str(tz),
            'note': f"Learned from {size} of your {sa.LABELS[platform]} posts with real numbers, blended with the industry "
                    f"default (k={SHRINK_K}) so a few lucky posts don't decide alone.",
            'note_vi': f"Học từ {size} bài {sa.LABELS[platform]} có số liệu thật của tiệm, pha với mặc định ngành (k={SHRINK_K}) "
                       f"để vài bài may mắn không quyết định một mình."}


def next_slot(business_id, platform, after_utc, _cache=None):
    """Khung giờ tốt kế tiếp (giờ tiệm) ≥ after + 30 phút, trả UTC. _cache (dict): dùng lại best_times + múi giờ khi gọi
    nhiều lần trong 1 kế hoạch tuần (mỗi lần tính lại = vài lượt đọc DB)."""
    cache = _cache if _cache is not None else {}
    if ('tz',) not in cache:
        cache[('tz',)] = sa.shop_tz(business_id)
    if platform not in cache:
        cache[platform] = best_times(business_id, platform, n=5)['slots']
    tz = cache[('tz',)]
    earliest = (as_utc(after_utc) or utcnow()) + timedelta(minutes=30)
    local = earliest.astimezone(tz)
    best = None
    for s in cache[platform]:
        day = local.date() + timedelta(days=(s['weekday'] - local.weekday()) % 7)
        cand = datetime.combine(day, dtime(int(s['hour']), 0), tzinfo=tz)
        if cand < local:
            cand = datetime.combine(day + timedelta(days=7), dtime(int(s['hour']), 0), tzinfo=tz)
        cu = cand.astimezone(timezone.utc)
        if best is None or cu < best:
            best = cu
    if best is None:
        best = (earliest + timedelta(minutes=59)).replace(minute=0, second=0, microsecond=0)
    return best


# ---------------------------------------------------------------- AI (DeepSeek qua ai_studio_bp)
def _ai(system, user, business_id, temperature=0.7, max_tokens=1800):
    from ai_studio_bp import _call_deepseek_text   # import muộn: ai_studio_bp import app (vòng import)
    try:
        return _call_deepseek_text(system, user, temperature, max_tokens, business_id)
    except Exception as e:
        raise SocialError('ai_unavailable', 'The AI writer is not available right now — try again in a minute.', str(e)[:200])


def _facts(business_id):
    try:
        from ai_studio_bp import _business_facts
        return _business_facts(business_id) or ''
    except Exception:
        return ''


def _brand(business_id):
    b = db.ai_brand_profiles.find_one({'business_id': business_id}, {'_id': 0}) or {}
    lines = []
    for k, label in (('name', 'Brand name'), ('usp', 'What makes us different'), ('audience', 'Target customers'),
                     ('blacklist', 'Never use these words/claims')):
        if b.get(k):
            lines.append(f"{label}: {str(b[k])[:400]}")
    return ('BRAND DNA:\n' + '\n'.join(lines)) if lines else ''


def _parse_json(text):
    s = (text or '').strip()
    s = re.sub(r'^```(?:json)?\s*|\s*```$', '', s)
    i, j = s.find('{'), s.rfind('}')
    if i < 0 or j <= i:
        raise SocialError('ai_bad_output', 'The AI answer could not be read — try again.')
    try:
        out = json.loads(s[i:j + 1])
    except ValueError:
        raise SocialError('ai_bad_output', 'The AI answer could not be read — try again.')
    if not isinstance(out, dict):
        raise SocialError('ai_bad_output', 'The AI answer could not be read — try again.')
    return out


def _ai_json(system, user, business_id, max_tokens, temperature=0.7):
    """DeepSeek ở chế độ JSON (response_format json_object). Trả (text, cut): cut=True khi DeepSeek dừng vì hết max_tokens
    (JSON có thể dở dang). Gọi thẳng ai_deepseek_client (điểm gọi DeepSeek duy nhất) để đọc được finish_reason."""
    try:
        from ai_deepseek_client import deepseek_chat_completion
        desktop = os.environ.get('BITPAW_DESKTOP_MODE') == '1'
        res = deepseek_chat_completion(
            {'model': 'deepseek-chat', 'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}],
             'temperature': temperature, 'max_tokens': max_tokens, 'response_format': {'type': 'json_object'}},
            business_id=business_id, proxy_api_key=os.environ.get('BITPAW_AI_PROXY_KEY') if desktop else None,
            direct_api_key=None if desktop else os.environ.get('DEEPSEEK_API_KEY'))
        ch = (res.get('choices') or [{}])[0] or {}
        return (ch.get('message') or {}).get('content') or '', ch.get('finish_reason') == 'length'
    except Exception as e:
        raise SocialError('ai_unavailable', 'The AI writer is not available right now — try again in a minute.', str(e)[:200])


def _plan_posts(text):
    """Các bài AI viết trong 1 lô {"posts": [...]}. JSON bị cắt giữa chừng (hết max_tokens) thì vẫn giữ các bài đã viết trọn
    vẹn thay vì bỏ cả lô."""
    s = re.sub(r'^```(?:json)?\s*|\s*```$', '', (text or '').strip())
    i, j = s.find('{'), s.rfind('}')
    if 0 <= i < j:
        try:
            out = json.loads(s[i:j + 1])
            if isinstance(out, dict) and isinstance(out.get('posts'), list):
                return [w for w in out['posts'] if isinstance(w, dict)]
        except ValueError:
            pass
    k = s.find('"posts"')
    k = s.find('[', k) if k >= 0 else -1
    if k < 0:
        return []
    dec, pos, got = json.JSONDecoder(), k + 1, []
    while True:
        while pos < len(s) and s[pos] in ' \t\r\n,':
            pos += 1
        if pos >= len(s) or s[pos] != '{':
            break
        try:
            obj, pos = dec.raw_decode(s, pos)
        except ValueError:
            break   # bài cuối bị cắt dở: bỏ riêng bài đó
        if isinstance(obj, dict):
            got.append(obj)
    return got


def _lang_name(lang):
    return 'Vietnamese' if (lang or '').lower().startswith('vi') else 'English'


_RULES = {
    'facebook': '"facebook": plain friendly text, 1–3 short paragraphs, no hashtag spam (0–2), include the link if one is given',
    'instagram': '"instagram": up to 2200 characters, engaging first line, then 3–8 relevant hashtags at the end',
    'tiktok': '"tiktok": at most 150 characters, punchy hook, 2–4 hashtags',
    'youtube': '"youtube_title": at most 90 characters (no < or >); "youtube": video description, 2–4 short sentences',
    'google_business': '"google_business": at most 1500 characters, NO hashtags, ends with a clear call to book/visit',
}
_HASHTAG = re.compile(r'#[\w\-]+')


def _fit(platform, text):
    """Ép đúng giới hạn từng nền tảng sau khi AI viết (AI hay viết dài/quá nhiều hashtag)."""
    t = (text or '').strip()
    if platform == 'google_business':
        import social_publisher
        return social_publisher.strip_hashtags(t)[:1500]
    if platform == 'instagram':
        seen = [0]

        def keep_first_8(m):   # giữ 8 hashtag đầu, bỏ phần thừa (theo vị trí — không đụng '#nails' khi bỏ '#nail')
            seen[0] += 1
            return m.group(0) if seen[0] <= 8 else ''
        t = _HASHTAG.sub(keep_first_8, t)
        return re.sub(r'[ \t]{2,}', ' ', t).strip()[:2200]
    if platform == 'tiktok':
        return t[:150].strip()
    if platform == 'youtube':
        import social_publisher   # mô tả YouTube giới hạn 5000 BYTE (chữ có dấu 2–3 byte), không phải 5000 ký tự
        return social_publisher._cut_bytes(re.sub(r'[<>]', '', t), social_publisher.YT_DESC_BYTES)
    return t[:5000]


def captions(business_id, base_text, platforms, lang='en'):
    base_text = (base_text or '').strip()[:3000]
    if not base_text:
        raise SocialError('empty_text', 'Write what the post is about first.')
    platforms = [p for p in dict.fromkeys(platforms or []) if p in sa.PLATFORMS]
    if not platforms:
        raise SocialError('no_platforms', 'Pick at least one platform.')
    system = ("You write social media posts for a local business. Rewrite the owner's text for each requested platform. "
              f"Write in {_lang_name(lang)}. Use ONLY facts from the owner's text and the BUSINESS FACTS / BRAND DNA below. "
              "Never invent prices, discounts, offers, reviews, awards, opening hours or claims that are not given. "
              "Return ONLY a JSON object with these keys: " + '; '.join(_RULES[p] for p in platforms) + '.')
    user = '\n\n'.join(x for x in (_facts(business_id), _brand(business_id), f"OWNER'S TEXT:\n{base_text}") if x)
    out = _parse_json(_ai(system, user, business_id, 0.7, 1800))
    res = {}
    for p in platforms:
        v = out.get(p)
        if isinstance(v, str) and v.strip():
            res[p] = _fit(p, v)
    if 'youtube' in platforms:
        title = out.get('youtube_title')
        res['youtube_title'] = re.sub(r'[<>]', '', title.strip())[:90] if isinstance(title, str) and title.strip() else base_text.split('\n')[0][:90]
    if not any(p in res for p in platforms):
        raise SocialError('ai_bad_output', 'The AI answer was empty — try again.')
    return res


# ---------------------------------------------------------------- kế hoạch tuần từ dữ liệu thật
_IMG_PATH = re.compile(r'/api/public/storage/file/([0-9a-fA-F]{24})')


def _money(business_id, amount):
    try:
        from currency_utils import format_money
        from app import _tenant_currency
        return format_money(amount, _tenant_currency(business_id))
    except Exception:
        return f"{amount:g}" if isinstance(amount, (int, float)) else str(amount)


def _photo(business_id, product):
    """Ảnh THẬT của sản phẩm/dịch vụ (GridFS kind product_image) nếu còn tồn tại."""
    m = _IMG_PATH.search(str(product.get('image') or ''))
    if not m:
        return None
    try:
        import media_store
        g = media_store.get(m.group(1), business_id)
    except Exception:
        return None
    if g is None:
        return None
    ct, size = '', 0
    try:
        ct = (getattr(g, 'content_type', None) or '').lower()
        size = int(getattr(g, 'length', 0) or 0)
    except (AttributeError, TypeError, ValueError):
        pass
    return {'file_id': m.group(1), 'content_type': ct, 'size': size}


def _photo_fits(platform, photo):
    """Nền tảng nhận được ảnh thật này không (Instagram: JPEG; Instagram/Google: không quá cỡ tải qua link; Facebook: ≤ 4 MB,
    không WebP)? Không có ảnh thì Instagram không đăng được."""
    import social_publisher as sp
    if not photo:
        return platform != 'instagram'
    code = sp._media_problem(platform, 'image', photo.get('content_type') or '', int(photo.get('size') or 0))
    return code is None or code in sp.NOTE_ONLY


def _content_items(business_id, n, now):
    """Chọn nội dung tuần từ dữ liệu thật: khuyến mãi đang chạy, dịch vụ có giá (ưu tiên có ảnh, xoay vòng không lặp
    trong 21 ngày), còn lại là mẹo/kiến thức ngành."""
    used = set()
    for p in db.social_posts.find({'business_id': business_id, 'created_by': 'ai', 'created_at': {'$gte': now - timedelta(days=21)}},
                                  {'_id': 0, 'source': 1}):
        s = p.get('source') or {}
        if s.get('id') is not None:
            used.add((s.get('type'), s.get('id')))
    today = now.date().isoformat()
    promos = []
    for pr in db.promotions.find({'business_id': business_id, 'status': 'active'}, {'_id': 0}).limit(20):
        end = str(pr.get('end_date') or '')[:10]
        start = str(pr.get('start_date') or '')[:10]
        if (end and end < today) or (start and start > (now + timedelta(days=7)).date().isoformat()):
            continue
        try:
            if pr.get('usage_limit') and int(pr.get('used_count') or 0) >= int(pr['usage_limit']):
                continue   # hết lượt dùng: quảng cáo nữa là hứa điều tiệm không còn giữ được
        except (TypeError, ValueError):
            pass
        promos.append(pr)
    products = list(db.products.find({'business_id': business_id, 'is_active': {'$in': [1, True]}, 'price': {'$gt': 0}},
                                     {'_id': 0, 'id': 1, 'name': 1, 'price': 1, 'image': 1, 'category': 1}).limit(80))
    items = []
    for pr in sorted(promos, key=lambda x: ('promo', x.get('id')) in used)[:max(1, n // 4)]:
        try:
            val = float(pr.get('discount_value'))
        except (TypeError, ValueError):
            val = None
        if val is None or val <= 0:
            disc = ''
        elif pr.get('discount_type') in ('percent', 'percentage'):
            disc = f": {val:g}% off"
        else:
            disc = f": {_money(business_id, val)} off"
        items.append({'type': 'promo', 'id': pr.get('id'),
                      'facts': f"Active promotion '{pr.get('name') or ''}' (code {pr.get('code') or '-'}){disc}"
                               + (f", valid until {str(pr.get('end_date'))[:10]}" if pr.get('end_date') else '')})
    fresh = [p for p in products if ('service', p.get('id')) not in used]
    # ưu tiên món/dịch vụ có ảnh (chỉ xem đường dẫn — kiểm tra file thật ở _photo cho món được chọn, đỡ 80 lần đọc GridFS)
    pool = sorted(fresh or products, key=lambda p: (_IMG_PATH.search(str(p.get('image') or '')) is None, -(p.get('price') or 0)))
    want_services = min(len(pool), max(1, round((n - len(items)) * 0.6)))
    for p in pool[:want_services]:
        photo = _photo(business_id, p)
        items.append({'type': 'service', 'id': p.get('id'), 'photo': photo,
                      'facts': f"Service/product '{p.get('name')}' — price {_money(business_id, p.get('price'))}"
                               + (f" (category {p['category']})" if p.get('category') else '')})
    k = 0
    while len(items) < n:
        k += 1
        items.append({'type': 'tip', 'id': None, 'facts': f"Helpful tip #{k} for customers of this kind of business "
                                                         "(care, aftercare, how to choose, what to expect). No prices, no offers."})
    return items[:n]


def weekly_plan(business_id, user_id, start_date_local, platforms, posts_per_week, lang='en'):
    import social_publisher
    req = [p for p in dict.fromkeys(platforms or []) if p in sa.PLATFORMS]
    if not req:
        raise SocialError('no_platforms', 'Pick at least one platform.')
    plat = [p for p in req if p in PLAN_PLATFORMS]
    if not plat:
        raise SocialError('plan_platforms', 'AI weekly plans post photos and text to Facebook, Instagram and Google Business '
                                            'Profile. TikTok and YouTube posts need a video you choose yourself.')
    try:
        n = int(posts_per_week or FREQUENCY[plat[0]]['default'])
    except (TypeError, ValueError):
        raise SocialError('bad_number', 'posts_per_week must be a number.')
    n = max(1, min(n, 14))
    tz = sa.shop_tz(business_id)
    now = utcnow()
    try:
        d = date.fromisoformat(str(start_date_local)[:10]) if start_date_local else now.astimezone(tz).date()
    except ValueError:
        raise SocialError('bad_date', 'start_date must look like 2026-11-02.')
    start = max(now, datetime.combine(d, dtime(0, 0), tzinfo=tz).astimezone(timezone.utc))
    items = _content_items(business_id, n, now)
    ai_items = [{'idx': i, 'type': it['type'], 'facts': it['facts'], 'has_photo': bool(it.get('photo'))} for i, it in enumerate(items)]
    keys = ['"caption" (Facebook-style base text, 1–3 short paragraphs, ends with a call to action)']
    if 'instagram' in plat:
        keys.append('"instagram" (≤2200 chars, ends with 3–8 relevant hashtags)')
    if 'google_business' in plat:
        keys.append('"google_business" (≤1500 chars, NO hashtags, ends with a call to book/visit)')
    keys += ['"hashtags" (list of 3–8 words without #)',
             '"image_prompt" (ONLY when has_photo is false: one English prompt for an AI image of the scene, no text in the image)']
    system = ("You are the social media manager of a local business and plan next week's posts. "
              f"Write in {_lang_name(lang)}. Use ONLY the BUSINESS FACTS, BRAND DNA and each item's facts. Quote a price only "
              "exactly as given. Never invent prices, discounts, offers, reviews, awards or results. Tips must be genuinely "
              "useful and general (no medical claims). Write one post for EVERY item. Return ONLY a json object: "
              "{\"posts\": [{\"idx\": <item idx>, " + ', '.join(keys) + "}]}.")
    head = [x for x in (_facts(business_id), _brand(business_id)) if x]
    batches = [ai_items[k:k + PLAN_BATCH] for k in range(0, len(ai_items), PLAN_BATCH)]
    written, errors = _write_plan(system, head, batches, business_id)
    plan_id = next_mongo_id('social_plans')
    posts, used_times, slot_cache = [], set(), {}
    for i, it in enumerate(items):
        w = written.get(i) or {}
        caption = (w.get('caption') or '').strip() if isinstance(w.get('caption'), str) else ''
        if not caption:
            continue
        photo = it.get('photo')
        tg = [p for p in plat if _photo_fits(p, photo)]
        if photo and not tg:
            photo = None   # ảnh thật không nền tảng nào nhận được (quá cỡ / sai định dạng): đăng chữ ở nơi nhận chữ
            tg = [p for p in plat if _photo_fits(p, None)]
        if not tg:
            continue
        caps = {}
        for p in ('instagram', 'google_business'):
            if p in tg and isinstance(w.get(p), str) and w[p].strip():
                caps[p] = _fit(p, w[p])
        when = next_slot(business_id, tg[0], start + timedelta(days=7) * i / n, slot_cache)
        for _ in range(12):   # 2 bài không trùng đúng 1 khung giờ
            if when not in used_times:
                break
            when = next_slot(business_id, tg[0], when + timedelta(minutes=31), slot_cache)
        used_times.add(when)
        data = {'caption': caption, 'captions': caps, 'hashtags': w.get('hashtags') if isinstance(w.get('hashtags'), list) else [],
                'media_file_ids': [photo['file_id']] if photo else [], 'targets': [{'platform': p} for p in tg],
                'scheduled_at': when, 'status': 'pending_approval',
                'image_prompt': (w.get('image_prompt') if not photo and isinstance(w.get('image_prompt'), str) else None)}
        try:
            post = social_publisher.create_post(business_id, user_id, data, created_by='ai', plan_id=plan_id)
        except SocialError as e:
            if e.code in ('media_not_found', 'media_not_shareable', 'bad_media') and photo:
                data['media_file_ids'], data['targets'] = [], [{'platform': p} for p in tg if _photo_fits(p, None)]
                if not data['targets']:
                    continue
                post = social_publisher.create_post(business_id, user_id, data, created_by='ai', plan_id=plan_id)
            else:
                raise
        db.social_posts.update_one({'id': post['id'], 'business_id': business_id},
                                   {'$set': {'source': {'type': it['type'], 'id': it.get('id')}}})
        post['source'] = {'type': it['type'], 'id': it.get('id')}
        posts.append(post)
    if not posts:
        if errors:
            raise errors[0]   # vd ai_unavailable: nói đúng lý do thay vì "AI trả lời hỏng"
        raise SocialError('ai_bad_output', 'The AI did not return usable posts — try again.')
    skipped = [p for p in req if p not in plat]
    unwritten = sum(1 for i in range(len(items)) if i not in written)
    plan = {'id': plan_id, 'business_id': business_id, 'created_by': user_id, 'start_date': d.isoformat(), 'platforms': plat,
            'skipped_platforms': skipped, 'posts_per_week': n, 'lang': lang, 'post_ids': [p['id'] for p in posts],
            'items': [{'type': it['type'], 'id': it.get('id'), 'has_photo': bool(it.get('photo'))} for it in items],
            'unwritten': unwritten, 'qa_test': sa.test_mode(), 'created_at': now}
    db.social_plans.insert_one(dict(plan))
    plan.pop('business_id', None)
    plan['created_at'] = iso_z(now)
    plan['note'] = ('Drafts wait for your approval — nothing is posted until you approve. Posts without a real photo include an '
                    'image idea you can generate in AI Studio.' + (' TikTok and YouTube were left out: they need a video you choose.'
                                                                    if skipped else '')
                    + (f" The AI wrote {len(items) - unwritten} of {len(items)} posts this time — make the plan again for the rest."
                       if unwritten else ''))
    plan['note_vi'] = ('Bài nháp chờ bạn duyệt — chưa duyệt thì không đăng gì. Bài chưa có ảnh thật kèm gợi ý ảnh để tạo trong AI '
                       'Studio.' + (' TikTok và YouTube không có trong kế hoạch: cần video do bạn chọn.' if skipped else '')
                       + (f" Lần này AI viết được {len(items) - unwritten}/{len(items)} bài — tạo kế hoạch lần nữa cho phần còn lại."
                          if unwritten else ''))
    return plan, posts


def _write_plan(system, head, batches, business_id):
    """DeepSeek viết từng lô (≤ PLAN_BATCH bài, chế độ JSON, ngân sách token theo số bài), các lô chạy song song và cùng
    chờ tối đa PLAN_WAIT_SECONDS. Lô lỗi / bị cắt không làm mất các bài đã viết xong. Trả ({idx: bài}, [SocialError])."""
    def one(batch):
        user = '\n\n'.join(head + ['ITEMS:\n' + json.dumps(batch, ensure_ascii=False)])
        text, cut = _ai_json(system, user, business_id, 300 + PLAN_TOKENS_PER_ITEM * len(batch))
        if cut:   # finish_reason 'length': JSON dở dang — _plan_posts vẫn giữ các bài đã viết trọn vẹn
            print(f"[social] weekly plan batch of {len(batch)} hit max_tokens — keeping the complete posts only")
        return _plan_posts(text)

    results, errors = [], []
    if len(batches) == 1:
        try:
            results.append(one(batches[0]))
        except SocialError as e:
            errors.append(e)
    elif batches:
        ex = ThreadPoolExecutor(max_workers=min(len(batches), 5))
        futs = [ex.submit(one, b) for b in batches]
        finished, _ = _wait(futs, timeout=PLAN_WAIT_SECONDS)
        ex.shutdown(wait=False, cancel_futures=True)
        for f in futs:
            if f not in finished:
                errors.append(SocialError('ai_unavailable', 'The AI writer took too long — try again in a minute.'))
                continue
            try:
                results.append(f.result())
            except SocialError as e:
                errors.append(e)
            except Exception as e:
                errors.append(SocialError('ai_unavailable', 'The AI writer is not available right now — try again in a minute.',
                                          str(e)[:200]))
    allowed = {it['idx'] for b in batches for it in b}
    written = {}
    for got in results:
        for w in got:
            try:
                idx = int(w.get('idx'))
            except (TypeError, ValueError):
                continue
            if idx in allowed:
                written.setdefault(idx, w)
    return written, errors


# ---------------------------------------------------------------- nhận xét hiệu quả
def performance_review(business_id, lang='en', days=90):
    vi = (lang or '').lower().startswith('vi')
    now = utcnow()
    since = now - timedelta(days=days)
    rows = list(db.social_post_metrics.find({'business_id': business_id}, {'_id': 0}).limit(600))
    posts = {p['id']: p for p in db.social_posts.find({'business_id': business_id, **_world(), 'id': {'$in': list({r['post_id'] for r in rows})}},
                                                       {'_id': 0})} if rows else {}
    tz = sa.shop_tz(business_id)
    entries = []
    for r in rows:
        p = posts.get(r['post_id'])
        if not p:
            continue
        t = next((x for x in p.get('targets') or [] if x.get('platform') == r['platform']), {})
        when = as_utc(t.get('published_at')) or as_utc(p.get('scheduled_at'))
        if not when or when < since:
            continue
        local = when.astimezone(tz)
        entries.append({'post_id': p['id'], 'platform': r['platform'], 'caption': (p.get('caption') or '')[:160],
                        'media_type': p.get('media_type'), 'weekday': local.weekday(), 'hour': local.hour,
                        'published_at': iso_z(when), 'metrics': r.get('metrics') or {}, 'permalink': t.get('permalink'),
                        'engagement_rate': (round(engagement_rate(r.get('metrics')), 4)
                                            if engagement_rate(r.get('metrics')) is not None else None)})
    window = {'from': iso_z(since), 'to': iso_z(now), 'posts': len({e['post_id'] for e in entries}), 'rows': len(entries)}
    if window['posts'] < 3:
        k = window['posts']
        return {'enough_data': False, 'top_posts': [], 'metrics_window': window,
                'text': (f"Chưa đủ dữ liệu: BitPaw mới có số liệu thật của {k} bài — cần ít nhất 3 bài để nhận xét. "
                         "Hãy đăng thêm vài bài rồi quay lại." if vi else
                         f"Not enough data yet: BitPaw has real numbers for {k} of your posts — the review needs at least 3. "
                         "Post a few more and check back.")}
    ranked = sorted(entries, key=lambda e: (e['engagement_rate'] is None, -(e['engagement_rate'] or 0)))
    top = ranked[:5]
    system = ("You are a social media analyst for a small local business. Review the owner's REAL post results below. "
              f"Write in {_lang_name(lang)}, plain words, max 180 words: 3 short findings and 3 concrete next steps. "
              "Use ONLY the numbers given; never invent numbers, benchmarks or percentages that are not in the data. "
              "If some platforms have few posts, say the signal is weak. weekday 0 = Monday; hours are shop local time.")
    user = json.dumps({'posts': entries[:60]}, ensure_ascii=False)
    text = _ai(system, user, business_id, 0.4, 700).strip()
    return {'enough_data': True, 'text': text, 'top_posts': top, 'metrics_window': window}
