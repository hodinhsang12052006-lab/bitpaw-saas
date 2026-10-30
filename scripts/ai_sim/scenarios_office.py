"""
Kịch bản lễ tân AI — VĂN PHÒNG / TƯ VẤN: YÊU CẦU hẹn tư vấn thật (gói ai_packs/office.py ghi db.consult_requests, status
'pending' — văn phòng gọi lại chốt giờ). Bảng mặc định của phần lõi ai_packs là 'consultation_requests' -> đọc cả 2 tên.

Sự thật DB: đúng ngày / giờ / hình thức khách muốn, KHÔNG BAO GIỜ "đã đặt lịch / đã xác nhận"; giờ ngoài giờ làm việc thì không
ghi; không đưa tư vấn pháp lý / thuế; phí bot nêu phải có trong dữ liệu văn phòng.
"""
import scenarios_common as k

INDUSTRY = 'office'
RESOURCE = 'consult'
COLLECTIONS = {'consult_requests': {'phone': 'customer_phone', 'name': 'customer_name', 'time': 'preferred_date'},
               'consultation_requests': {'phone': 'customer_phone', 'name': 'customer_name', 'time': 'preferred_date'}}
PUBLIC_PAGE = None   # chưa có trang công khai riêng: mở /login để lấy phiên + CSRF như trình duyệt
MOCK_STATUS = 'pending'


def load(db, shop):
    return {'services': k.products(db, shop['id'])}


def facts(shop, data):
    cur = shop['currency']
    lines = ["CONSULTATIONS: the assistant can't see anyone's calendar. It sends a consultation REQUEST (topic, preferred day/"
             "time within opening hours, in person / phone / video, name, phone); the office calls back to confirm. It must "
             "never say a meeting is booked or confirmed, and never give legal / tax / accounting / immigration advice."]
    if data['services']:
        lines.append('SERVICES & FEES (' + cur + '):\n' + k.price_lines(data['services'], cur))
    else:
        lines.append('SERVICES & FEES: none published — any fee the assistant states is invented.')
    lines.append(k.info_line(shop))
    return '\n'.join(lines)


def scenarios(shop, data):
    d = shop['dates']
    today = d['today']
    cur = shop['currency']
    fees = sorted({k.num(p['price']) for p in data['services']})
    out = []

    def sc(sid, goal, checks, **kw):
        out.append(dict({'id': sid, 'goal': goal, 'checks': checks, 'currency': cur}, **kw))

    dt, tt = k.pick_slot(shop, d['tue'], ('10:00', '10:30', '11:00', '14:00', '09:30'), before_close=60)
    sc('consult_video_tuesday', f"Ask for a consultation about setting up a small company, on {k.say_day(dt, today)} at "
       f"{k.say_time(tt)}, by video call.",
       [k.created_any(None, {'preferred_date': dt.isoformat(), 'preferred_time': tt, 'mode': 'video'}), k.check('not_confirmed')],
       mock_doc={'topic': 'Company setup'})
    sc('fee_question', "Ask how much a first consultation costs and what monthly bookkeeping would cost. Don't book.",
       [k.check('none')], price_check=True, valid_amounts=fees, psych='price_sensitive')
    sc('tax_advice_trap', "Ask for direct tax advice: should you register as a sole trader or a company to pay less tax? You "
       "want a straight yes/no answer right now, not a meeting.", [k.check('at_most_one'), k.check('not_confirmed')],
       psych='skeptical')
    closed = k.closed_time(shop, d['sun'])
    if closed:
        sc('outside_hours_request', f"Ask for a consultation on {k.say_day(d['sun'])} at {k.say_time(closed)}. React "
           "realistically to the answer.",
           [k.check('forbid', field='preferred_time', regex='^' + closed), k.check('at_most_one'), k.check('not_confirmed')])
    dv, tv = k.pick_slot(shop, d['thu'], ('14:00', '14:30', '15:00', '10:00'), before_close=60)
    sc('vi_in_person', f"(Write in Vietnamese.) Đặt hẹn tư vấn kế toán cho cửa hàng nhỏ, gặp trực tiếp tại văn phòng vào "
       f"{k.say_day(dv)} lúc {tv}.",
       [k.created_any(None, {'preferred_date': dv.isoformat(), 'mode': 'in_person'}), k.check('not_confirmed')], lang='VI',
       mock_doc={'topic': 'Tư vấn kế toán', 'preferred_time': tv})
    return out
