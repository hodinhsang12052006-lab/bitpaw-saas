"""Gói & giá theo TỪNG NGÀNH (25/10/2026) — nguồn DUY NHẤT cho landing (components/pricing.html), /checkout, trang /plan,
super admin, bot bán hàng (ai_sales_prompts.bitpaw_facts) và việc KHOÁ tính năng theo gói.

Cách đặt giá (tham chiếu giá đối thủ ở Mỹ/Úc, 10/2026):
  Nails/Salon  — Square Appointments $0/49/149, Vagaro ~$30 + $10/nhân viên, GlossGenius $24/48/148, Fresha $15/nhân viên
  Spa          — Mangomint $120 + $10/nhân viên, Boulevard từ ~$176
  Nhà hàng     — Toast $0/69/110+, Square for Restaurants $0/60, Clover $79/149/189
  Bán lẻ       — Square $0/49/149, Lightspeed Retail $89/149/289
  Khách sạn    — Little Hotelier $29–109, Cloudbeds $200+
  Kỹ thuật     — Jobber $29–349, Housecall Pro $79/189/329
  Sản xuất     — MRPeasy $49/người dùng, Katana $299+
  Văn phòng/HR — Homebase $0/30/70/120, Deputy $5–9/người
BitPaw gộp sẵn những thứ đối thủ bán thêm (lương/hoa hồng, SMS, AI, CRM), nên giá ngang khoảng giữa của đối thủ:
  Essential  — tự cài, KHÔNG phí cài đặt, đủ để vận hành 1 tiệm nhỏ (rào cản thấp nhất).
  Pro Partner— "phổ biến nhất": BitPaw cài đặt + website riêng + máy Square Terminal cài sẵn; mở khoá tự động hoá & AI CSKH.
  Empire     — chuỗi/nhiều chi nhánh: AI Copilot, AI Studio, báo cáo gộp, app thương hiệu riêng, quản lý kỹ thuật riêng.
Trả theo năm: tặng 2 tháng (trả 10 tháng). AUD ≈ USD × 1,5 (làm tròn giá ...9).
Tiệm CŨ chưa có trường businesses.plan được coi là Empire (không ai bị mất tính năng đang dùng).
"""
import math
import time

PLAN_ORDER = ('essential', 'pro', 'empire')
PLAN_NAMES = {'essential': 'Essential', 'pro': 'Pro Partner', 'empire': 'Empire Scale'}
DEFAULT_PLAN_FOR_EXISTING = 'empire'

# (giá tháng USD, phí cài đặt một lần USD)
INDUSTRY_PRICES = {
    'nail':       {'essential': (59, 0), 'pro': (129, 499), 'empire': (249, 1499)},
    'spa':        {'essential': (69, 0), 'pro': (149, 499), 'empire': (279, 1499)},
    'fnb':        {'essential': (79, 0), 'pro': (159, 799), 'empire': (299, 1999)},
    'karaoke':    {'essential': (69, 0), 'pro': (139, 599), 'empire': (259, 1499)},
    'hotel':      {'essential': (79, 0), 'pro': (159, 799), 'empire': (299, 1999)},
    'retail':     {'essential': (59, 0), 'pro': (129, 499), 'empire': (249, 1499)},
    'production': {'essential': (89, 0), 'pro': (179, 799), 'empire': (329, 1999)},
    'technical':  {'essential': (59, 0), 'pro': (149, 599), 'empire': (279, 1499)},
    'office':     {'essential': (39, 0), 'pro': (89, 299), 'empire': (179, 999)},
}
INDUSTRY_LABELS = {
    'nail': ('Nails & Salon', 'Nails & Salon'), 'spa': ('Spa & Beauty', 'Spa & Beauty'), 'fnb': ('Nhà hàng & Cafe', 'Restaurant & Cafe'),
    'karaoke': ('Karaoke & Bida', 'Karaoke & Billiards'), 'hotel': ('Khách sạn & Homestay', 'Hotel & Homestay'),
    'retail': ('Bán lẻ', 'Retail'), 'production': ('Sản xuất', 'Production'), 'technical': ('Dịch vụ kỹ thuật', 'Field service'),
    'office': ('Văn phòng & Nhân sự', 'Office & HR'),
}
PAYMENT_INDUSTRIES = {'nail', 'spa', 'fnb', 'karaoke', 'hotel', 'retail'}   # có thu tiền tại quầy -> tặng Square Terminal
STAFF_LIMIT = {'essential': 5, 'pro': None, 'empire': None}                  # None = không giới hạn
STAFF_LIMIT_OFFICE = {'essential': 15, 'pro': None, 'empire': None}
# Hạn mức AI tạo ảnh/video MỖI THÁNG (Replicate tính tiền thật theo ảnh/giây video) — ai_media.quota_status đọc ở đây.
# Essential/Pro chưa có AI Studio nên = 0.
AI_MEDIA_QUOTA = {'essential': {'images': 0, 'video_seconds': 0}, 'pro': {'images': 0, 'video_seconds': 0},
                  'empire': {'images': 300, 'video_seconds': 300}}


def aud(usd, setup=False):
    if not usd:
        return 0
    if setup:
        return int(math.ceil(usd * 1.5))
    return int(math.ceil(usd * 1.5 / 10.0) * 10 - 1)


def price(industry, plan, currency='USD'):
    """(phí tháng, phí cài đặt) theo ngành + gói + tiền tệ."""
    ind = industry if industry in INDUSTRY_PRICES else 'nail'
    m, s = INDUSTRY_PRICES[ind][plan]
    if currency == 'AUD':
        return aud(m), aud(s, setup=True)
    return m, s


# ---- Tính năng & gói tối thiểu --------------------------------------------------------------------
FEATURE_MIN_PLAN = {
    'roster': 'pro', 'requests': 'pro', 'messaging': 'pro', 'packages': 'pro', 'inventory': 'pro', 'finance': 'pro',
    'kds': 'pro', 'qr_ordering': 'pro', 'reservations': 'pro', 'gps_radar': 'pro', 'parts': 'pro', 'materials': 'pro',
    'crm_ai': 'pro', 'ai_inbox': 'pro',
    'ai_copilot': 'empire', 'ai_studio': 'empire', 'marketing_pro': 'empire', 'multi_location': 'empire',
}
FEATURE_LABELS = {
    'roster': ('Lịch ca làm việc', 'Shift roster'), 'requests': ('Duyệt nghỉ phép & chi phí', 'Leave & expense approvals'),
    'messaging': ('SMS & email tự động', 'SMS & email automation'), 'packages': ('Gói liệu trình', 'Session packages'),
    'inventory': ('Cảnh báo tồn kho', 'Stock alerts'), 'finance': ('Báo cáo lãi lỗ & dòng tiền', 'Profit & cash-flow reports'),
    'kds': ('Màn hình bếp (KDS)', 'Kitchen display (KDS)'), 'qr_ordering': ('Gọi món QR tại bàn', 'QR table ordering'),
    'reservations': ('Đặt chỗ trước', 'Reservations'), 'gps_radar': ('Bản đồ thợ GPS & điều phối', 'Live GPS map & dispatch'),
    'parts': ('Kho phụ tùng', 'Parts inventory'), 'materials': ('Nguyên vật liệu', 'Raw materials'),
    'crm_ai': ('CRM + AI nhắc khách quay lại', 'CRM + AI win-back'), 'ai_copilot': ('AI Copilot', 'AI Copilot'),
    'ai_studio': ('AI Studio', 'AI Studio'), 'marketing_pro': ('Marketing đa kênh', 'Multi-channel marketing'),
    'ai_inbox': ('Hộp thư AI đa kênh', 'AI multi-channel inbox'),
    'multi_location': ('Nhiều chi nhánh & báo cáo gộp', 'Multiple locations & consolidated reports'),
}
# Trang/API của CHỦ TIỆM bị khoá khi gói chưa có tính năng (tiền tố đường dẫn). Trang công khai của khách không khoá.
ROUTE_FEATURES = [
    ('/roster', 'roster'), ('/api/roster', 'roster'),
    ('/leave_requests', 'requests'), ('/expense_requests', 'requests'),
    ('/settings/messaging', 'messaging'),
    ('/packages', 'packages'),
    ('/inventory_alert', 'inventory'),
    ('/baocao_loinhuan', 'finance'), ('/quanly_thuchi', 'finance'), ('/quanly_congno', 'finance'), ('/profit_report', 'finance'),
    ('/kitchen_display', 'kds'),
    ('=/qr_menu', 'qr_ordering'),   # chỉ trang của chủ quán; /qr_menu/<mã bàn> là trang của KHÁCH
    ('/reservations', 'reservations'), ('/hotel/reservations', 'reservations'), ('/karaoke/reservations', 'reservations'),
    ('/map_dashboard', 'gps_radar'), ('/technical/parts', 'parts'), ('/production/materials', 'materials'),
    ('/campaign_builder', 'crm_ai'), ('/ai/campaign-builder', 'crm_ai'), ('/customer_nurturing', 'crm_ai'),
    ('/ai/customer-nurturing', 'crm_ai'), ('/crm_automation', 'crm_ai'),
    ('/ai_bot', 'ai_inbox'), ('/inbox/channels', 'ai_inbox'), ('/api/inbox', 'ai_inbox'), ('/api/bot', 'ai_inbox'),
    ('/api/ai/copilot', 'ai_copilot'),
    ('/ai-studio', 'ai_studio'), ('/ai_studio', 'ai_studio'), ('/api/ai_studio', 'ai_studio'), ('/api/media', 'ai_studio'),
    ('/social', 'marketing_pro'), ('/api/social', 'marketing_pro'),
    ('/ad-assistant', 'marketing_pro'), ('/omnichannel', 'marketing_pro'), ('/omnichannel_connect', 'marketing_pro'), ('/ai/connect-platforms', 'marketing_pro'),
    ('/ecommerce_sync', 'marketing_pro'),
    ('/report_consolidated', 'multi_location'),
]


def feature_for_path(path):
    for prefix, feat in ROUTE_FEATURES:
        if prefix.startswith('='):
            if path == prefix[1:]:
                return feat
        elif path == prefix or path.startswith(prefix + '/'):
            return feat
    return None


def allows(plan, feature):
    need = FEATURE_MIN_PLAN.get(feature)
    if not need:
        return True
    p = plan if plan in PLAN_ORDER else DEFAULT_PLAN_FOR_EXISTING
    return PLAN_ORDER.index(p) >= PLAN_ORDER.index(need)


_PLAN_CACHE = {}


def business_plan(db, business_id, ttl=60):
    """Gói hiện tại của tiệm (cache 60 giây / tiến trình). Tiệm chưa có trường plan = Empire (tiệm cũ giữ nguyên quyền)."""
    if not business_id:
        return DEFAULT_PLAN_FOR_EXISTING
    hit = _PLAN_CACHE.get(business_id)
    now = time.time()
    if hit and now - hit[1] < ttl:
        return hit[0]
    plan = DEFAULT_PLAN_FOR_EXISTING
    try:
        doc = db.businesses.find_one({'id': business_id}, {'_id': 0, 'plan': 1}) or {}
        if doc.get('plan') in PLAN_ORDER:
            plan = doc['plan']
    except Exception:
        pass
    _PLAN_CACHE[business_id] = (plan, now)
    return plan


def forget(business_id):
    _PLAN_CACHE.pop(business_id, None)


# ---- Nội dung thẻ giá theo ngành (vi, en) ---------------------------------------------------------
_CORE = {  # 2–3 dòng "đúng nghề" cho Essential
    # Bảng xoay tua thợ đã có thật (Phase 1, nail_turns.py: /nail/turns) — tua đủ/nửa tua theo giá vé, khách request.
    'nail': [('fa-arrows-rotate', 'Bảng xoay tua thợ: tua đủ / nửa tua theo giá vé', 'Technician turn board: full & half turns by ticket price'),
             ('fa-hand-holding-dollar', 'Chia tip & hoa hồng thợ tự động', 'Automatic tip & commission split'),
             ('fa-calendar-check', 'Trang đặt lịch online + mã QR cho tiệm', 'Online booking page + QR code for your salon')],
    'spa': [('fa-spa', 'Menu liệu trình, hoa hồng kỹ thuật viên', 'Treatment menu, therapist commission'),
            ('fa-calendar-check', 'Trang đặt lịch online + mã QR', 'Online booking page + QR code')],
    'fnb': [('fa-chair', 'Sơ đồ bàn, tách bill, tip', 'Table map, split bills, tips'),
            ('fa-utensils', 'Menu, tuỳ chọn món, in hoá đơn', 'Menu, modifiers, receipts')],
    'karaoke': [('fa-stopwatch', 'Tính giờ phòng/bàn theo block 15 phút', 'Room & table timers billed per 15 minutes'),
                ('fa-martini-glass', 'Đồ uống, đồ ăn cộng thẳng vào bill', 'Food & drinks added straight to the bill')],
    'hotel': [('fa-bed', 'Sơ đồ phòng trống / có khách / đang dọn', 'Room board: vacant / occupied / cleaning'),
              ('fa-door-open', 'Nhận phòng, trả phòng, phụ thu minibar', 'Check-in, check-out, minibar charges')],
    'retail': [('fa-barcode', 'Bán hàng quét mã vạch, tồn kho theo từng bill', 'Barcode checkout, stock updated on every sale'),
               ('fa-star', 'Tích điểm & hạng thành viên', 'Loyalty points & member tiers')],
    'production': [('fa-industry', 'Sản lượng từng công nhân, lương khoán tự tính', 'Output per worker, automatic piece-rate pay'),
                   ('fa-clock', 'Chấm công ca xưởng trên điện thoại', 'Shift clock-in on the phone')],
    'technical': [('fa-clipboard-list', 'Bảng việc: giao, theo dõi, hoàn tất', 'Job board: assign, track, complete'),
                  ('fa-signature', 'Khách ký nghiệm thu ngay trên điện thoại', 'Customer e-signature sign-off on the phone')],
    'office': [('fa-location-dot', 'Chấm công GPS + ảnh, giới hạn bán kính văn phòng', 'GPS + photo clock-in within your office radius'),
               ('fa-file-invoice-dollar', 'Bảng lương tự cộng, xuất file', 'Automatic payroll totals, export')],
}
_PRO_EXTRA = {  # 1–2 dòng mở thêm ở Pro theo ngành
    'nail': [('fa-box-open', 'Gói dịch vụ trả trước, chấm công khuôn mặt cho thợ', 'Prepaid service packages, face check-in for techs')],
    'spa': [('fa-box-open', 'Gói liệu trình nhiều buổi (10 buổi…)', 'Multi-visit treatment packages (10-session…)')],
    'fnb': [('fa-fire-burner', 'Màn hình bếp (KDS) + gọi món QR tại bàn', 'Kitchen display (KDS) + QR table ordering'),
            ('fa-calendar-days', 'Đặt bàn trước, trừ kho theo định lượng', 'Table reservations, recipe-based stock deduction')],
    'karaoke': [('fa-qrcode', 'Khách gọi món bằng QR trong phòng, đặt phòng trước', 'QR ordering from the room, room reservations')],
    'hotel': [('fa-calendar-days', 'Lịch đặt phòng + trang đặt phòng công khai', 'Reservation calendar + public booking page')],
    'retail': [('fa-triangle-exclamation', 'Cảnh báo sắp hết hàng, gợi ý nhập hàng', 'Low-stock alerts & reorder suggestions'),
               ('fa-chart-pie', 'Lãi theo từng sản phẩm, sổ thu chi', 'Profit by product, cash-flow book')],
    'production': [('fa-boxes-stacked', 'Nguyên vật liệu & định mức tự trừ', 'Raw materials & BOM auto-deduction')],
    'technical': [('fa-map-location-dot', 'Bản đồ thợ GPS trực tiếp, điều phối thông minh', 'Live GPS map & smart dispatch'),
                  ('fa-screwdriver-wrench', 'Kho phụ tùng theo từng việc, nhắn "thợ đang đến"', 'Parts per job, "on my way" texts')],
    'office': [('fa-check-double', 'Duyệt nghỉ phép, đề xuất chi, KPI', 'Leave & expense approvals, KPI')],
}
# Ngành mà trợ lý AI ĐẶT LỊCH THẬT được (dịch vụ + thợ + giờ trống). Ngành khác AI chỉ trả lời câu hỏi và chuyển yêu cầu
# (đặt bàn/phòng/việc) cho đội của tiệm — thẻ giá Pro và bot bán hàng (ai_sales_prompts.bitpaw_facts) dùng CHUNG câu dưới đây.
AI_BOOKING_INDUSTRIES = ('nail', 'spa')


def ai_assistant_claim(industry):
    """(vi, en) — câu "trợ lý AI 24/7" đúng sự thật cho từng ngành."""
    if industry in AI_BOOKING_INDUSTRIES:
        return ('Trợ lý AI trả lời & đặt lịch 24/7', '24/7 AI assistant that answers & books')
    return ('Trợ lý AI trả lời khách 24/7 & chuyển yêu cầu cho đội của bạn',
            '24/7 AI assistant that answers questions & passes requests to your team')


def tier_cards(industry):
    """Thẻ giá 3 gói cho 1 ngành: [{key, name, monthly{USD,AUD}, setup{USD,AUD}, yearly_monthly{...}, items[(ico,vi,en)], bonus, hot}]."""
    ind = industry if industry in INDUSTRY_PRICES else 'nail'
    staff = STAFF_LIMIT_OFFICE if ind == 'office' else STAFF_LIMIT
    pay = ind in PAYMENT_INDUSTRIES
    cards = []
    for key in PLAN_ORDER:
        m_usd, s_usd = INDUSTRY_PRICES[ind][key]
        mon = {'USD': m_usd, 'AUD': aud(m_usd)}
        setup = {'USD': s_usd, 'AUD': aud(s_usd, setup=True)}
        # trả năm = 10 tháng; giá/tháng hiển thị làm tròn LÊN để không bao giờ thấp hơn số thực thu
        yearly = {c: int(math.ceil(v * 10 / 12.0)) for c, v in mon.items()}
        if key == 'essential':
            lim = staff[key]
            items = [('fa-cash-register', 'POS & thanh toán thẻ / tiền mặt', 'POS & card / cash payments')] if pay else []
            items += _CORE[ind]
            items += [('fa-user-clock', 'Chấm công, lương & tip của nhân viên', 'Time clock, staff pay & tips'),
                      ('fa-mobile-screen', 'App Windows, Android, iPhone/iPad', 'Apps for Windows, Android, iPhone/iPad'),
                      ('fa-store', f'1 chi nhánh · tối đa {lim} nhân viên', f'1 location · up to {lim} staff')]
            bonus = ('Tự cài trong 1 ngày, không phí cài đặt', 'Self-setup in a day — no setup fee')
        elif key == 'pro':
            ai_vi, ai_en = ai_assistant_claim(ind)
            items = [('fa-layer-group', 'Mọi thứ trong Essential, không giới hạn nhân viên', 'Everything in Essential, unlimited staff'),
                     ('fa-user-gear', 'BitPaw cài đặt giúp + website riêng cho tiệm', 'Done-for-you setup + your own website'),
                     ('fa-comment-sms', 'SMS nhắc lịch, nhắn lại cuộc gọi nhỡ, xin đánh giá 5 sao', 'SMS reminders, missed-call text back, 5-star review requests'),
                     ('fa-robot', f'{ai_vi}, CRM nhắc khách cũ quay lại', f'{ai_en}, CRM win-back')]
            items += _PRO_EXTRA[ind]
            items += [('fa-calendar-week', 'Lịch ca, duyệt nghỉ phép, báo cáo lãi lỗ', 'Shift roster, leave approvals, profit reports')]
            bonus = ('Tặng 1 máy Square Terminal cài sẵn', 'Includes 1 pre-configured Square Terminal') if pay else \
                ('Chuyển dữ liệu cũ sang miễn phí', 'Free migration of your existing data')
        else:
            items = [('fa-layer-group', 'Mọi thứ trong Pro Partner', 'Everything in Pro Partner'),
                     ('fa-wand-magic-sparkles', 'AI Copilot hỏi số liệu + AI Studio viết bài, quảng cáo', 'AI Copilot for your numbers + AI Studio for posts & ads'),
                     ('fa-building', 'Nhiều chi nhánh, báo cáo gộp', 'Multiple locations, consolidated reports'),
                     ('fa-bullhorn', 'Marketing đa kênh (Facebook, Zalo, web)', 'Multi-channel marketing (Facebook, web, messaging)'),
                     ('fa-mobile-button', 'App mang thương hiệu riêng', 'Your own branded app'),
                     ('fa-user-tie', 'Quản lý kỹ thuật riêng cho tiệm', 'Dedicated technology manager')]
            bonus = ('Tặng iPad + Square Terminal', 'Includes iPad + Square Terminal') if pay else \
                ('Đào tạo tận nơi cho cả đội', 'On-site training for your whole team')
        cards.append({'key': key, 'name': PLAN_NAMES[key], 'monthly': mon, 'setup': setup, 'yearly_monthly': yearly,
                      'items': items, 'bonus': bonus, 'hot': key == 'pro'})
    return cards


def catalog():
    """Toàn bộ bảng giá cho trình duyệt (pricing component + checkout)."""
    return {ind: {'label': INDUSTRY_LABELS[ind], 'cards': tier_cards(ind)} for ind in INDUSTRY_PRICES}


def facts_lines(industry=None):
    """Dòng giá cho bot bán hàng. Biết ngành của trang khách đang xem -> CHỈ dòng của ngành đó (nạp cả 9 dòng làm bot
    báo nhầm giá ngành khác); không biết ngành (landing chung) -> cả 9 dòng."""
    out = []
    for ind, tiers in INDUSTRY_PRICES.items():
        if industry in INDUSTRY_PRICES and ind != industry:
            continue
        parts = []
        for key in PLAN_ORDER:
            m, s = tiers[key]
            parts.append(f"{PLAN_NAMES[key]} ${m}/mo (A${aud(m)})" + (f" + ${s:,} setup (A${aud(s, True):,})" if s else ", no setup fee"))
        out.append(f"- {INDUSTRY_LABELS[ind][1]}: " + '; '.join(parts) + '.')
    return out
