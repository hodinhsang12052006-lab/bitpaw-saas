# -*- coding: utf-8 -*-
"""
Trang + API cho NHÂN VIÊN / CHỦ TIỆM xem và xử lý các YÊU CẦU mà lễ tân AI tạo (Phase 2 — gói ai_packs không đặt khung
giờ). Trước đây AI không có chỗ nào ghi yêu cầu của 3 ngành này; giờ mỗi yêu cầu là 1 dòng THẬT, nhân viên xác nhận ở đây:

  /retail/holds            Giữ hàng chờ lấy (ngành retail, db.retail_holds — ai_packs/retail.py).
                           Mọi tài khoản của cửa hàng: "Xác nhận đã để riêng" (pending -> ready), "Khách đã lấy" (bán qua POS
                           như mọi đơn, POS trừ kho; nút này trả số đang giữ), "Huỷ". Hết hạn tự trả hàng (lười, khi mở trang).
  /requests/quotes         Yêu cầu báo giá B2B (ngành production, db.quote_requests — ai_packs/production.py).
                           Chỉ chủ / quản lý (có ngân sách + thông tin khách sỉ): new -> contacted / quoted / won / lost.
  /requests/consultations  Yêu cầu tư vấn (ngành office, db.consultation_requests — ai_packs/office.py).
                           Mọi tài khoản của văn phòng (lễ tân gọi lại chốt giờ): pending -> confirmed / done / declined / cancelled.

API JSON: GET /api/retail/holds?view=active|all, POST /api/retail/holds/<id>/status {status},
          GET /api/requests/<quotes|consultations>?view=open|all, POST /api/requests/<kind>/<id>/status {status, staff_note?}
business_id luôn lấy từ session (không tin client). Ngành sai -> 403 (API) / về trang chủ (trang): industry_access chưa có
dòng cho các endpoint này nên tự chặn ở đây (giống nail_turns.py). Không gửi tin cho khách tự động: thẻ có nút gọi / nhắn
SMS từ máy của nhân viên.
Đăng ký (integrator): app.py `from retail_holds_bp import retail_holds_bp; app.register_blueprint(retail_holds_bp)`.
"""
import re
from datetime import datetime
from functools import wraps

from flask import Blueprint, jsonify, redirect, render_template_string, request, session

from app import login_required
from mongo_client import db

retail_holds_bp = Blueprint('ai_requests', __name__)

ADMIN_ROLES = ('admin', 'super_admin')
LIST_LIMIT = 200

# kind -> cấu hình: ngành được dùng, collection, trạng thái "còn mở", trạng thái nhân viên đặt được, ai được dùng
KINDS = {
    'holds': {'industry': 'retail', 'coll': 'retail_holds', 'open': ('pending', 'ready'), 'admin_only': False},
    'quotes': {'industry': 'production', 'coll': 'quote_requests', 'open': ('new', 'contacted', 'quoted'),
               'set': ('new', 'contacted', 'quoted', 'won', 'lost'), 'admin_only': True,
               # luật chuyển trạng thái (server kiểm): trạng thái hiện tại -> được đổi sang. Khớp nút PAGE_TEXT[...]['actions']
               'next': {'new': ('contacted', 'quoted', 'lost'), 'contacted': ('quoted', 'lost'), 'quoted': ('won', 'lost'),
                        'won': ('quoted',), 'lost': ('new',)}},
    'consultations': {'industry': 'office', 'coll': 'consultation_requests', 'open': ('pending', 'confirmed'),
                      'set': ('pending', 'confirmed', 'done', 'declined', 'cancelled'), 'admin_only': False,
                      'next': {'pending': ('confirmed', 'declined', 'cancelled'), 'confirmed': ('done', 'cancelled')}},
}
VI_DOW = ('T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'CN')


# ------------------------------------------------------------------ phiên / quyền / ngôn ngữ
def _bid():
    return session.get('business_id') or session.get('user_id')


def _role():
    return session.get('role') or 'staff'


def _vi():
    try:
        from i18n import resolve_lang
        return resolve_lang(request) == 'vi'
    except Exception:
        return (request.cookies.get('bitpaw_lang') or '') == 'vi'


def _t(vi, en):
    return vi if _vi() else en


def _err(status, vi, en, **extra):
    return jsonify({'success': False, 'message': _t(vi, en), **extra}), status


def _wants_json():
    return request.path.startswith('/api/') or 'application/json' in (request.headers.get('Accept') or '')


def for_kind(kind):
    """Chặn sai ngành / sai quyền cho 1 loại danh sách. super_admin (hỗ trợ) xem được mọi ngành."""
    cfg = KINDS[kind]

    def deco(f):
        @wraps(f)
        def inner(*args, **kwargs):
            if not _bid():
                return _err(401, 'Phiên đăng nhập không hợp lệ, vui lòng đăng nhập lại.', 'Your session has ended. Please sign in again.')
            mode = (session.get('business_mode') or '').strip().lower()
            if _role() != 'super_admin' and mode != cfg['industry']:
                if _wants_json():
                    return _err(403, 'Trang này không thuộc ngành của cửa hàng bạn.', "This page isn't part of your business type.")
                return redirect('/')
            if cfg['admin_only'] and _role() not in ADMIN_ROLES:
                if _wants_json():
                    return _err(403, 'Chỉ chủ / quản lý xem được yêu cầu báo giá.', 'Only the owner or a manager can see quote requests.')
                return redirect('/')
            return f(*args, **kwargs)
        return inner
    return deco


def _body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


# ------------------------------------------------------------------ định dạng
def _when(s, vi):
    """'2026-10-30T17:00' (giờ tiệm) -> 'T6 30/10 17:00' / 'Fri 30 Oct, 17:00'. Chuỗi lạ trả nguyên."""
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s)[:16])
    except ValueError:
        return str(s)
    return f"{VI_DOW[dt.weekday()]} {dt:%d/%m} {dt:%H:%M}" if vi else dt.strftime('%a %d %b, %H:%M')


def _day(s, vi):
    if not s:
        return None
    try:
        d = datetime.strptime(str(s)[:10], '%Y-%m-%d')
    except ValueError:
        return str(s)
    return f"{VI_DOW[d.weekday()]} {d:%d/%m/%Y}" if vi else d.strftime('%a %d %b %Y')


def _shop_currency(business_id):
    from ai_packs import retail as rp
    return rp.currency_of(business_id)


def _hold_row(h, vi, cur):
    from ai_packs import retail as rp
    c = h.get('currency') or cur
    qty = int(h.get('quantity') or 0)
    return {'id': h.get('id'), 'status': h.get('status'), 'product': h.get('product_name'), 'quantity': qty,
            'unit_price': rp.money(h.get('unit_price'), c), 'total': rp.money(rp._num(h.get('unit_price')) * qty, c),
            'customer_name': h.get('customer_name') or '', 'customer_phone': h.get('customer_phone') or '',
            'note': h.get('note') or '', 'pickup_by': _when(h.get('expires_at_local'), vi),
            'created': _when(h.get('created_at_local'), vi), 'source': h.get('source') or '', 'channel': h.get('channel') or ''}


def _quote_row(q, vi):
    qty = q.get('quantity')
    return {'id': q.get('id'), 'status': q.get('status'), 'product': q.get('product'), 'quantity': qty,
            'unit': q.get('unit') or '', 'deadline': _day(q.get('deadline'), vi), 'specs': q.get('specs') or '',
            'material': q.get('material') or '', 'budget': q.get('budget') or '', 'company': q.get('company') or '',
            'customer_name': q.get('customer_name') or '', 'customer_phone': q.get('customer_phone') or '',
            'email': q.get('email') or '', 'staff_note': q.get('staff_note') or '', 'created': _when(q.get('created_at_local'), vi),
            'source': q.get('source') or '', 'channel': q.get('channel') or ''}


def _consult_row(c, vi):
    when = _day(c.get('preferred_date'), vi)
    if when and c.get('preferred_time'):
        when = f"{when} {c['preferred_time']}"
    return {'id': c.get('id'), 'status': c.get('status'), 'topic': c.get('topic') or '', 'preferred': when,
            'mode': c.get('mode') or '', 'note': c.get('note') or '', 'customer_name': c.get('customer_name') or '',
            'customer_phone': c.get('customer_phone') or '', 'email': c.get('email') or '',
            'staff_note': c.get('staff_note') or '', 'created': _when(c.get('created_at_local'), vi),
            'source': c.get('source') or '', 'channel': c.get('channel') or ''}


def _counts(coll, business_id, open_statuses):
    try:
        return {'open': db[coll].count_documents({'business_id': business_id, 'status': {'$in': list(open_statuses)}})}
    except Exception:
        return {'open': None}


# ------------------------------------------------------------------ giữ hàng (bán lẻ)
@retail_holds_bp.route('/api/retail/holds', methods=['GET'])
@login_required
@for_kind('holds')
def api_holds_list():
    from ai_packs import retail as rp
    bid, vi = _bid(), _vi()
    try:
        rp.release_expired_holds(bid)   # hết hạn lấy -> 'expired' + trả số đang giữ (không cần cron)
    except Exception as e:
        print(f"[retail_holds] expire: {e}")
    view = request.args.get('view') or 'active'
    flt = {'business_id': bid}
    if view != 'all':
        flt['status'] = {'$in': list(rp.ACTIVE)}
    rows = list(db.retail_holds.find(flt, {'_id': 0}).sort('id', -1).limit(LIST_LIMIT))
    cur = _shop_currency(bid)
    return jsonify({'success': True, 'view': 'all' if view == 'all' else 'active', 'currency': cur,
                    'items': [_hold_row(h, vi, cur) for h in rows], **_counts('retail_holds', bid, rp.ACTIVE)})


@retail_holds_bp.route('/api/retail/holds/<int:hold_id>/status', methods=['POST'])
@login_required
@for_kind('holds')
def api_hold_status(hold_id):
    from ai_packs import retail as rp
    bid = _bid()
    new = str(_body().get('status') or '').strip()
    if new not in ('ready', 'picked_up', 'cancelled'):
        return _err(400, 'Trạng thái không hợp lệ.', 'Unknown status.')
    by = f"staff:{session.get('user_id') or ''}"[:80]
    hold, err = rp.staff_set_status(bid, hold_id, new, by=by)
    if err == 'bad_status':
        return _err(400, 'Trạng thái không hợp lệ.', 'Unknown status.')
    if err:
        cur = db.retail_holds.find_one({'id': hold_id, 'business_id': bid}, {'_id': 0, 'status': 1})
        if not cur:
            return _err(404, 'Không tìm thấy yêu cầu giữ hàng này.', 'Hold not found.')
        st = cur.get('status')
        lab_vi, lab_en = PAGE_TEXT['holds']['vi']['status'].get(st, st), PAGE_TEXT['holds']['en']['status'].get(st, st)
        return _err(409, f"Yêu cầu này đã ở trạng thái \"{lab_vi}\", không đổi được nữa.",
                    f"This hold is already \"{lab_en}\" and can't be changed.", current_status=st)
    return jsonify({'success': True, 'item': _hold_row(hold, _vi(), _shop_currency(bid))})


# ------------------------------------------------------------------ báo giá (sản xuất) + tư vấn (văn phòng)
def _list_requests(kind):
    cfg = KINDS[kind]
    bid, vi = _bid(), _vi()
    view = request.args.get('view') or 'open'
    flt = {'business_id': bid}
    if view != 'all':
        flt['status'] = {'$in': list(cfg['open'])}
    rows = list(db[cfg['coll']].find(flt, {'_id': 0}).sort('id', -1).limit(LIST_LIMIT))
    fmt = _quote_row if kind == 'quotes' else _consult_row
    return jsonify({'success': True, 'view': 'all' if view == 'all' else 'open', 'items': [fmt(r, vi) for r in rows],
                    **_counts(cfg['coll'], bid, cfg['open'])})


def _set_request_status(kind, rid):
    cfg = KINDS[kind]
    bid = _bid()
    body = _body()
    new = str(body.get('status') or '').strip()
    if new not in cfg['set']:
        return _err(400, 'Trạng thái không hợp lệ.', 'Unknown status.')
    now = datetime.now().isoformat()
    upd = {'status': new, f'{new}_at': now, 'updated_at': now, 'updated_by': f"staff:{session.get('user_id') or ''}"[:80]}
    if 'staff_note' in body:
        upd['staff_note'] = re.sub(r'\s+', ' ', str(body.get('staff_note') or '')).strip()[:300]
    # nguyên tử: chỉ đổi khi trạng thái HIỆN TẠI cho phép -> trang cũ (người khác vừa đổi) bấm sau bị 409, không đè
    allowed_from = [s for s, nxt in cfg['next'].items() if new in nxt]
    res = db[cfg['coll']].update_one({'id': rid, 'business_id': bid, 'status': {'$in': allowed_from}}, {'$set': upd})
    if not res.matched_count:
        cur = db[cfg['coll']].find_one({'id': rid, 'business_id': bid}, {'_id': 0, 'status': 1})
        if not cur:
            return _err(404, 'Không tìm thấy yêu cầu này.', 'Request not found.')
        st = cur.get('status')
        vi_lab, en_lab = PAGE_TEXT[kind]['vi']['status'], PAGE_TEXT[kind]['en']['status']
        return _err(409, f"Yêu cầu này đang ở trạng thái \"{vi_lab.get(st, st)}\", không chuyển sang \"{vi_lab.get(new, new)}\" được.",
                    f"This request is already \"{en_lab.get(st, st)}\" and can't be changed to \"{en_lab.get(new, new)}\".",
                    current_status=st)
    row = db[cfg['coll']].find_one({'id': rid, 'business_id': bid}, {'_id': 0})
    fmt = _quote_row if kind == 'quotes' else _consult_row
    return jsonify({'success': True, 'item': fmt(row or {}, _vi())})


@retail_holds_bp.route('/api/requests/quotes', methods=['GET'])
@login_required
@for_kind('quotes')
def api_quotes_list():
    return _list_requests('quotes')


@retail_holds_bp.route('/api/requests/quotes/<int:rid>/status', methods=['POST'])
@login_required
@for_kind('quotes')
def api_quote_status(rid):
    return _set_request_status('quotes', rid)


@retail_holds_bp.route('/api/requests/consultations', methods=['GET'])
@login_required
@for_kind('consultations')
def api_consultations_list():
    return _list_requests('consultations')


@retail_holds_bp.route('/api/requests/consultations/<int:rid>/status', methods=['POST'])
@login_required
@for_kind('consultations')
def api_consultation_status(rid):
    return _set_request_status('consultations', rid)


# ------------------------------------------------------------------ trang
def _page(kind):
    vi = _vi()
    return render_template_string(PAGE_HTML, kind=kind, vi=vi, txt=PAGE_TEXT[kind]['vi' if vi else 'en'])


@retail_holds_bp.route('/retail/holds')
@login_required
@for_kind('holds')
def holds_page():
    return _page('holds')


@retail_holds_bp.route('/requests/quotes')
@login_required
@for_kind('quotes')
def quotes_page():
    return _page('quotes')


@retail_holds_bp.route('/requests/consultations')
@login_required
@for_kind('consultations')
def consultations_page():
    return _page('consultations')


# Chữ trên trang (VI + EN). status_label / actions theo từng loại; JS chỉ hiển thị, mọi luật chuyển trạng thái ở server.
_COMMON = {
    'vi': {'loading': 'Đang tải…', 'retry': 'Thử lại', 'load_err': 'Không tải được danh sách.', 'call': 'Gọi', 'sms': 'Nhắn SMS',
           'save_err': 'Không lưu được, thử lại.', 'saved': 'Đã cập nhật', 'ai': 'AI lễ tân', 'created': 'Gửi lúc',
           'open_count': 'đang chờ xử lý', 'confirm_cancel': 'Huỷ yêu cầu này? Nhớ báo khách nếu cần.'},
    'en': {'loading': 'Loading…', 'retry': 'Try again', 'load_err': "Couldn't load the list.", 'call': 'Call', 'sms': 'Text',
           'save_err': "Couldn't save — try again.", 'saved': 'Updated', 'ai': 'AI receptionist', 'created': 'Sent',
           'open_count': 'to handle', 'confirm_cancel': 'Cancel this request? Let the customer know if needed.'},
}
PAGE_TEXT = {
    'holds': {
        'vi': {**_COMMON['vi'], 'title': 'Giữ hàng chờ lấy', 'api': '/api/retail/holds', 'views': [['active', 'Đang giữ'], ['all', 'Tất cả']],
               'sub': 'Khách nhờ giữ hàng qua chat. Khách chỉ được báo "đã giữ" khi bạn bấm xác nhận. Khách trả tiền khi tới lấy — bán qua POS như mọi đơn, rồi bấm "Khách đã lấy".',
               'empty': 'Chưa có yêu cầu giữ hàng nào. Khi khách nhắn "giữ giúp mình 2 hộp…", lễ tân AI kiểm tồn kho thật rồi gửi yêu cầu vào đây.',
               'status': {'pending': 'Chờ xác nhận', 'ready': 'Đã để riêng', 'picked_up': 'Đã lấy', 'cancelled': 'Đã huỷ', 'expired': 'Hết hạn'},
               'actions': {'pending': [['ready', 'Xác nhận đã để riêng', 'primary'], ['picked_up', 'Khách đã lấy', ''], ['cancelled', 'Huỷ', 'quiet']],
                           'ready': [['picked_up', 'Khách đã lấy', 'primary'], ['cancelled', 'Huỷ', 'quiet']]},
               'pickup_by': 'Giữ tới', 'each': 'mỗi cái'},
        'en': {**_COMMON['en'], 'title': 'Pickup holds', 'api': '/api/retail/holds', 'views': [['active', 'Active'], ['all', 'All']],
               'sub': "Customers asked in chat to have items set aside. They're only told it's held once you confirm. They pay at pickup — ring it up in POS as usual, then tap \"Picked up\".",
               'empty': 'No pickup holds yet. When a customer asks the AI receptionist to hold something, it checks live stock and the request lands here.',
               'status': {'pending': 'To confirm', 'ready': 'Set aside', 'picked_up': 'Picked up', 'cancelled': 'Cancelled', 'expired': 'Expired'},
               'actions': {'pending': [['ready', 'Confirm — set aside', 'primary'], ['picked_up', 'Picked up', ''], ['cancelled', 'Cancel', 'quiet']],
                           'ready': [['picked_up', 'Picked up', 'primary'], ['cancelled', 'Cancel', 'quiet']]},
               'pickup_by': 'Hold until', 'each': 'each'},
    },
    'quotes': {
        'vi': {**_COMMON['vi'], 'title': 'Yêu cầu báo giá', 'api': '/api/requests/quotes', 'views': [['open', 'Đang mở'], ['all', 'Tất cả']],
               'sub': 'Khách sỉ / doanh nghiệp gửi qua chat. AI không báo giá — bạn liên hệ và gửi báo giá, rồi cập nhật trạng thái.',
               'empty': 'Chưa có yêu cầu báo giá nào. Khi khách hỏi đặt hàng số lượng lớn, lễ tân AI hỏi đủ sản phẩm, số lượng, hạn cần và liên hệ rồi gửi vào đây.',
               'status': {'new': 'Mới', 'contacted': 'Đã liên hệ', 'quoted': 'Đã gửi báo giá', 'won': 'Chốt đơn', 'lost': 'Không chốt'},
               'actions': {'new': [['contacted', 'Đã liên hệ', 'primary'], ['quoted', 'Đã gửi báo giá', ''], ['lost', 'Không chốt', 'quiet']],
                           'contacted': [['quoted', 'Đã gửi báo giá', 'primary'], ['lost', 'Không chốt', 'quiet']],
                           'quoted': [['won', 'Chốt đơn', 'primary'], ['lost', 'Không chốt', 'quiet']],
                           'won': [['quoted', 'Mở lại', 'quiet']], 'lost': [['new', 'Mở lại', 'quiet']]},
               'deadline': 'Cần trước', 'specs': 'Quy cách', 'material': 'Chất liệu', 'budget': 'Ngân sách', 'qty': 'Số lượng'},
        'en': {**_COMMON['en'], 'title': 'Quote requests', 'api': '/api/requests/quotes', 'views': [['open', 'Open'], ['all', 'All']],
               'sub': "Bulk / business buyers who asked in chat. The AI never gives prices — you contact them with a quote, then update the status.",
               'empty': 'No quote requests yet. When a buyer asks about a bulk or custom order, the AI receptionist collects product, quantity, needed-by date and contact, and sends it here.',
               'status': {'new': 'New', 'contacted': 'Contacted', 'quoted': 'Quote sent', 'won': 'Won', 'lost': 'Lost'},
               'actions': {'new': [['contacted', 'Contacted', 'primary'], ['quoted', 'Quote sent', ''], ['lost', 'Lost', 'quiet']],
                           'contacted': [['quoted', 'Quote sent', 'primary'], ['lost', 'Lost', 'quiet']],
                           'quoted': [['won', 'Won', 'primary'], ['lost', 'Lost', 'quiet']],
                           'won': [['quoted', 'Reopen', 'quiet']], 'lost': [['new', 'Reopen', 'quiet']]},
               'deadline': 'Needed by', 'specs': 'Specs', 'material': 'Material', 'budget': 'Budget', 'qty': 'Quantity'},
    },
    'consultations': {
        'vi': {**_COMMON['vi'], 'title': 'Yêu cầu tư vấn', 'api': '/api/requests/consultations', 'views': [['open', 'Đang mở'], ['all', 'Tất cả']],
               'sub': 'Khách xin hẹn tư vấn qua chat. Chưa có lịch nào cho tới khi bạn gọi lại chốt giờ — AI đã nói rõ với khách như vậy.',
               'empty': 'Chưa có yêu cầu tư vấn nào. Lễ tân AI hỏi chủ đề, giờ mong muốn, hình thức và liên hệ rồi gửi vào đây.',
               'status': {'pending': 'Chờ gọi lại', 'confirmed': 'Đã chốt giờ', 'done': 'Đã tư vấn', 'declined': 'Từ chối', 'cancelled': 'Đã huỷ'},
               'actions': {'pending': [['confirmed', 'Đã gọi, chốt giờ', 'primary'], ['declined', 'Từ chối', 'quiet'], ['cancelled', 'Huỷ', 'quiet']],
                           'confirmed': [['done', 'Đã tư vấn xong', 'primary'], ['cancelled', 'Huỷ', 'quiet']]},
               'preferred': 'Khách muốn', 'modes': {'in_person': 'gặp trực tiếp', 'phone': 'gọi điện', 'video': 'gọi video'}},
        'en': {**_COMMON['en'], 'title': 'Consultation requests', 'api': '/api/requests/consultations', 'views': [['open', 'Open'], ['all', 'All']],
               'sub': "People who asked in chat for a consultation. Nothing is booked until you call them to set a time — the AI told them so.",
               'empty': 'No consultation requests yet. The AI receptionist asks for the topic, preferred time, meeting type and contact, then sends it here.',
               'status': {'pending': 'To call back', 'confirmed': 'Time set', 'done': 'Done', 'declined': 'Declined', 'cancelled': 'Cancelled'},
               'actions': {'pending': [['confirmed', 'Called — time set', 'primary'], ['declined', 'Decline', 'quiet'], ['cancelled', 'Cancel', 'quiet']],
                           'confirmed': [['done', 'Mark done', 'primary'], ['cancelled', 'Cancel', 'quiet']]},
               'preferred': 'Preferred', 'modes': {'in_person': 'in person', 'phone': 'phone call', 'video': 'video call'}},
    },
}

PAGE_HTML = r"""<!DOCTYPE html>
<html lang="{{ 'vi' if vi else 'en' }}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ txt.title }} - BitPaw Software</title>
    <link rel="icon" type="image/jpeg" href="{{ url_for('static', filename='logo_b.jpg') }}">
    <link href="{{ url_for('static', filename='css/tailwind.output.css') }}" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        /* Danh sách yêu cầu do lễ tân AI tạo (retail_holds_bp.py). Cùng bộ màu/kích thước nút với bảng xoay tua (nail_turns.html). */
        :root {
            --bg: #0b0d10; --surface: #13161b; --surface2: #191d23; --line: #262b33; --line2: #333a44;
            --ink: #eef0f3; --muted: #a3acb8; --dim: #7d8794;
            --accent: #5eead4; --accent-ink: #042f2a;
            --wait: #fbbf24; --wait-soft: rgba(251,191,36,.13); --ok: #34d399; --ok-soft: rgba(52,211,153,.12);
            --err: #fca5a5; --err-soft: rgba(248,113,113,.12);
        }
        html { color-scheme: dark; }
        [hidden] { display: none !important; }
        body { font-family: 'Inter', system-ui, sans-serif; background: var(--bg); color: var(--ink); margin: 0; font-size: 15px; }
        main.rq { flex: 1; min-width: 0; padding: 24px 28px 96px; max-width: 980px; box-sizing: border-box; }
        .num { font-variant-numeric: tabular-nums; }
        h1 { font-size: 24px; font-weight: 700; margin: 0; letter-spacing: -.01em; }
        .head { display: flex; flex-wrap: wrap; gap: 12px 16px; align-items: flex-end; justify-content: space-between; margin-bottom: 14px; }
        .sub { color: var(--muted); font-size: 14px; line-height: 1.55; margin: 6px 0 0; max-width: 64ch; }
        .seg { display: inline-flex; background: var(--surface); border: 1px solid var(--line); border-radius: 12px; padding: 3px; gap: 2px; }
        .seg button { min-height: 42px; padding: 0 14px; border: 0; border-radius: 9px; background: transparent; color: var(--muted); font: inherit; font-weight: 600; font-size: 14px; cursor: pointer; }
        .seg button[aria-pressed="true"] { background: var(--surface2); color: var(--ink); box-shadow: inset 0 0 0 1px var(--line2); }
        .btn { min-height: 44px; border: 1px solid var(--line2); border-radius: 12px; padding: 0 14px; font: inherit; font-weight: 600; font-size: 14px; cursor: pointer;
               background: var(--surface2); color: var(--ink); display: inline-flex; align-items: center; justify-content: center; gap: 8px; text-decoration: none; touch-action: manipulation; transition: transform .12s ease-out, background .15s; }
        .btn:active { transform: scale(.97); }
        .btn:focus-visible, .seg button:focus-visible { outline: 2px solid #fff; outline-offset: 2px; }
        .btn.primary { background: var(--accent); color: var(--accent-ink); border-color: var(--accent); font-weight: 700; }
        .btn.quiet { background: transparent; }
        .btn[disabled] { opacity: .5; cursor: not-allowed; }
        @media (hover: hover) { .btn:hover { background: #20252d; } .btn.primary:hover { background: #99f6e4; } .btn.quiet:hover { background: var(--surface2); } }
        .msg { border-radius: 12px; padding: 12px 14px; margin-bottom: 14px; font-size: 14px; line-height: 1.5; background: var(--surface); border: 1px solid var(--line); color: var(--muted); }
        .msg.err { background: var(--err-soft); border-color: rgba(248,113,113,.35); color: var(--err); display: flex; gap: 12px; align-items: center; justify-content: space-between; flex-wrap: wrap; }
        .count { color: var(--muted); font-size: 13.5px; margin-bottom: 10px; }
        .list { display: flex; flex-direction: column; gap: 12px; }
        .card { background: var(--surface); border: 1px solid var(--line); border-radius: 16px; padding: 16px; display: grid; gap: 10px; }
        .card.is-open { border-color: #3a4250; }
        .top { display: flex; gap: 10px; align-items: flex-start; justify-content: space-between; flex-wrap: wrap; }
        .what { font-weight: 700; font-size: 16.5px; line-height: 1.35; overflow-wrap: anywhere; }
        .what small { display: block; color: var(--muted); font-weight: 500; font-size: 13.5px; margin-top: 3px; }
        .chip { display: inline-flex; align-items: center; gap: 6px; border-radius: 999px; padding: 4px 10px; font-size: 12.5px; font-weight: 700; white-space: nowrap; background: var(--surface2); color: var(--muted); border: 1px solid var(--line2); }
        .chip.wait { background: var(--wait-soft); color: #fde68a; border-color: rgba(251,191,36,.4); }
        .chip.ok { background: var(--ok-soft); color: #a7f3d0; border-color: rgba(52,211,153,.35); }
        .meta { display: flex; flex-wrap: wrap; gap: 4px 16px; color: var(--muted); font-size: 13.5px; }
        .meta b { color: var(--ink); font-weight: 600; }
        .who { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
        .who .nm { font-weight: 600; margin-right: 4px; overflow-wrap: anywhere; }
        .note { background: #0f1216; border: 1px solid var(--line); border-radius: 10px; padding: 9px 11px; font-size: 13.5px; color: var(--muted); line-height: 1.5; white-space: pre-wrap; overflow-wrap: anywhere; }
        .acts { display: flex; flex-wrap: wrap; gap: 8px; }
        .tag-ai { font-size: 11.5px; font-weight: 700; letter-spacing: .02em; color: var(--accent); border: 1px solid rgba(94,234,212,.35); border-radius: 6px; padding: 1px 6px; }
        .empty { background: var(--surface); border: 1px dashed var(--line2); border-radius: 16px; padding: 22px; color: var(--muted); line-height: 1.6; }
        .toast { position: fixed; left: 50%; bottom: 24px; transform: translateX(-50%); background: #1f252d; border: 1px solid var(--line2); color: var(--ink); padding: 10px 16px; border-radius: 12px; font-size: 14px; z-index: 50; }
        .skel { height: 112px; border-radius: 16px; background: linear-gradient(90deg, var(--surface) 0%, var(--surface2) 50%, var(--surface) 100%); background-size: 200% 100%; animation: sk 1.4s ease-in-out infinite; }
        @keyframes sk { from { background-position: 200% 0; } to { background-position: -200% 0; } }
        @media (max-width: 640px) { main.rq { padding: 18px 16px 96px; } .acts .btn { flex: 1 1 auto; } }
        @media (prefers-reduced-motion: reduce) { .btn { transition: none; } .btn:active { transform: none; } .skel { animation: none; } }
    </style>
</head>
<body class="flex min-h-screen relative antialiased overflow-x-hidden">
{% include 'components/app_sidebar.html' %}
<main class="rq">
    <div class="head">
        <div>
            <h1>{{ txt.title }}</h1>
            <p class="sub">{{ txt.sub }}</p>
        </div>
        <div class="seg" role="group" aria-label="{{ txt.title }}" id="seg">
            {% for v in txt.views %}<button type="button" data-view="{{ v[0] }}" aria-pressed="{{ 'true' if loop.first else 'false' }}">{{ v[1] }}</button>{% endfor %}
        </div>
    </div>
    <div class="msg err" id="err" role="alert" hidden><span id="errTxt"></span><button class="btn" type="button" id="retry">{{ txt.retry }}</button></div>
    <div class="count num" id="count" aria-live="polite"></div>
    <div class="list" id="list" aria-busy="true"><div class="skel"></div><div class="skel"></div></div>
    <div class="toast" id="toast" role="status" hidden></div>
</main>
<script>
(function () {
    var KIND = {{ kind|tojson }};
    var T = {{ txt|tojson }};
    var view = T.views[0][0];
    var listEl = document.getElementById('list'), errEl = document.getElementById('err'), countEl = document.getElementById('count');
    var busy = false, toastTimer = null;

    function esc(v) {
        return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
        });
    }
    function telHref(p) { return String(p || '').replace(/[^\d+]/g, ''); }
    function toast(msg) {
        var el = document.getElementById('toast');
        el.textContent = msg; el.hidden = false;
        clearTimeout(toastTimer); toastTimer = setTimeout(function () { el.hidden = true; }, 2600);
    }
    function chipClass(st) {
        if (st === 'pending' || st === 'new') return 'chip wait';
        if (st === 'ready' || st === 'confirmed' || st === 'won' || st === 'quoted' || st === 'contacted') return 'chip ok';
        return 'chip';
    }
    function contact(it) {
        var h = '<div class="who"><span class="nm">' + esc(it.customer_name) + '</span>';
        var tel = telHref(it.customer_phone);
        if (tel) {
            h += '<a class="btn" href="tel:' + esc(tel) + '"><i class="fas fa-phone" aria-hidden="true"></i> ' + esc(T.call) + ' <span class="num">' + esc(it.customer_phone) + '</span></a>';
            h += '<a class="btn quiet" href="sms:' + esc(tel) + '"><i class="fas fa-comment-sms" aria-hidden="true"></i> ' + esc(T.sms) + '</a>';
        }
        if (it.email) h += '<a class="btn quiet" href="mailto:' + esc(it.email) + '"><i class="fas fa-envelope" aria-hidden="true"></i> ' + esc(it.email) + '</a>';
        return h + '</div>';
    }
    function body(it) {
        var h = '', meta = [];
        if (KIND === 'holds') {
            h += '<div class="what num">' + esc(it.quantity) + ' × ' + esc(it.product) + '<small>' + esc(it.total) + (it.quantity > 1 ? ' · ' + esc(it.unit_price) + ' ' + esc(T.each) : '') + '</small></div>';
            if (it.pickup_by && (it.status === 'pending' || it.status === 'ready')) meta.push(esc(T.pickup_by) + ' <b>' + esc(it.pickup_by) + '</b>');
        } else if (KIND === 'quotes') {
            h += '<div class="what">' + esc(it.product) + '<small class="num">' + esc(T.qty) + ': ' + esc(it.quantity) + (it.unit ? ' ' + esc(it.unit) : '') + (it.company ? ' · ' + esc(it.company) : '') + '</small></div>';
            if (it.deadline) meta.push(esc(T.deadline) + ' <b>' + esc(it.deadline) + '</b>');
            if (it.material) meta.push(esc(T.material) + ': <b>' + esc(it.material) + '</b>');
            if (it.budget) meta.push(esc(T.budget) + ': <b>' + esc(it.budget) + '</b>');
        } else {
            h += '<div class="what">' + esc(it.topic) + '</div>';
            if (it.preferred) meta.push(esc(T.preferred) + ' <b>' + esc(it.preferred) + '</b>' + (it.mode && T.modes[it.mode] ? ' · ' + esc(T.modes[it.mode]) : ''));
            else if (it.mode && T.modes[it.mode]) meta.push(esc(T.modes[it.mode]));
        }
        if (it.created) meta.push(esc(T.created) + ' ' + esc(it.created));
        return { what: h, meta: meta };
    }
    function card(it) {
        var b = body(it), acts = (T.actions[it.status] || []);
        var open = !!acts.length && (it.status === 'pending' || it.status === 'new' || it.status === 'ready' || it.status === 'contacted' || it.status === 'quoted' || it.status === 'confirmed');
        var h = '<article class="card' + (open ? ' is-open' : '') + '" data-id="' + esc(it.id) + '">';
        h += '<div class="top">' + b.what + '<span class="' + chipClass(it.status) + '">' + esc(T.status[it.status] || it.status) + '</span></div>';
        h += '<div class="meta num"><span>#' + esc(it.id) + '</span>' + (it.source === 'ai_bot' ? '<span class="tag-ai">' + esc(T.ai) + '</span>' : '');
        b.meta.forEach(function (m) { h += '<span>' + m + '</span>'; });
        h += '</div>';
        h += contact(it);
        var notes = [it.specs, it.note, it.staff_note].filter(function (x) { return x; });
        if (notes.length) h += '<div class="note">' + notes.map(esc).join('\n') + '</div>';
        if (acts.length) {
            h += '<div class="acts">';
            acts.forEach(function (a) { h += '<button type="button" class="btn ' + esc(a[2]) + '" data-act="' + esc(a[0]) + '">' + esc(a[1]) + '</button>'; });
            h += '</div>';
        }
        return h + '</article>';
    }
    function render(data) {
        var items = data.items || [];
        countEl.textContent = (data.open != null) ? (data.open + ' ' + T.open_count) : '';
        if (!items.length) { listEl.innerHTML = '<div class="empty">' + esc(T.empty) + '</div>'; return; }
        listEl.innerHTML = items.map(card).join('');
    }
    function showErr(msg) {
        document.getElementById('errTxt').textContent = msg || T.load_err;
        errEl.hidden = false;
    }
    async function load() {
        listEl.setAttribute('aria-busy', 'true');
        try {
            var r = await fetch(T.api + '?view=' + encodeURIComponent(view), { headers: { 'Accept': 'application/json' }, credentials: 'same-origin' });
            var d = await r.json().catch(function () { return {}; });
            if (!r.ok || !d.success) throw new Error(d.message || T.load_err);
            errEl.hidden = true;
            render(d);
        } catch (e) {
            showErr(e && e.message);
            if (listEl.querySelector('.skel')) listEl.innerHTML = '';
        } finally {
            listEl.setAttribute('aria-busy', 'false');
        }
    }
    async function act(id, status, btn) {
        if (busy) return;
        if (status === 'cancelled' && !window.confirm(T.confirm_cancel)) return;
        busy = true;
        var btns = btn.parentNode.querySelectorAll('button');
        btns.forEach(function (x) { x.disabled = true; });
        try {
            var r = await fetch(T.api + '/' + encodeURIComponent(id) + '/status', {
                method: 'POST', credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
                body: JSON.stringify({ status: status })
            });
            var d = await r.json().catch(function () { return {}; });
            if (!r.ok || !d.success) throw new Error(d.message || T.save_err);
            toast(T.saved);
            await load();
        } catch (e) {
            toast((e && e.message) || T.save_err);
            btns.forEach(function (x) { x.disabled = false; });
            load();   // 409: người khác vừa đổi -> hiện trạng thái mới
        } finally {
            busy = false;
        }
    }
    document.getElementById('seg').addEventListener('click', function (e) {
        var b = e.target.closest('button[data-view]');
        if (!b || b.dataset.view === view) return;
        view = b.dataset.view;
        this.querySelectorAll('button').forEach(function (x) { x.setAttribute('aria-pressed', x === b ? 'true' : 'false'); });
        load();
    });
    listEl.addEventListener('click', function (e) {
        var b = e.target.closest('button[data-act]');
        if (!b) return;
        var c = b.closest('.card');
        act(c.dataset.id, b.dataset.act, b);
    });
    document.getElementById('retry').addEventListener('click', load);
    document.addEventListener('visibilitychange', function () { if (!document.hidden) load(); });
    setInterval(function () { if (!document.hidden && !busy) load(); }, 60000);
    load();
})();
</script>
</body>
</html>
"""
