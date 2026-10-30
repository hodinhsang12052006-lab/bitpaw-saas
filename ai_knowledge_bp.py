"""Trang + API "Kiến thức cho trợ lý AI" (/ai/knowledge) — kho câu hỏi/trả lời + chính sách do CHỦ TIỆM viết (ai_knowledge.py).

Lễ tân AI (chat trang đặt lịch, Messenger, Instagram, WhatsApp, Zalo, Viber, SMS) đọc đúng các mục đang bật ở đây
(customer_context -> ai_knowledge.prompt_block) và chỉ trả lời từ đó + thông tin tiệm; câu không có thì chuyển nhân viên
(ask_team) và hiện lại ở trang này thành "câu khách hỏi mà AI chưa trả lời được".
Chỉ chủ tiệm / quản trị sửa được (AI nói thay mặt tiệm).
"""
from flask import Blueprint, jsonify, render_template, request, session

import ai_knowledge
from app import limiter, login_required, role_required

ai_knowledge_bp = Blueprint('ai_knowledge', __name__)


def _bid():
    return session.get('business_id') or session.get('user_id')


def _who():
    return session.get('username') or session.get('email') or session.get('user_id')


def _payload(business_id):
    """Mọi thứ trang cần trong 1 lần gọi: các mục, bản xem trước đúng chữ AI đọc, câu AI chưa trả lời được, thông tin tiệm
    AI đã dùng sẵn (từ Cài đặt đặt lịch + hồ sơ tiệm)."""
    info = []
    try:
        import customer_context
        info = [[k, v] for k, v in customer_context.info_items(business_id)]
    except Exception as e:
        print(f"[ai knowledge] info: {e}")
    return {
        'success': True,
        'entries': ai_knowledge.list_entries(business_id),
        'preview': ai_knowledge.prompt_block(business_id),
        'gaps': ai_knowledge.unanswered_questions(business_id),
        'info': info,
        'topics': [{'key': t, 'en': ai_knowledge.TOPIC_LABELS[t][0], 'vi': ai_knowledge.TOPIC_LABELS[t][1]} for t in ai_knowledge.TOPICS],
        'limits': {'entries': ai_knowledge.MAX_ENTRIES, 'question': ai_knowledge.MAX_QUESTION, 'answer': ai_knowledge.MAX_ANSWER},
    }


def _error(e, status=400):
    return jsonify({'success': False, 'message': str(e)}), status


@ai_knowledge_bp.route('/ai/knowledge')
@login_required
@role_required('admin', 'super_admin')
def ai_knowledge_page():
    return render_template('ai_knowledge.html')


@ai_knowledge_bp.route('/api/ai/knowledge', methods=['GET', 'POST'])
@login_required
@role_required('admin', 'super_admin')
@limiter.limit("240 per hour")
def ai_knowledge_api():
    bid = _bid()
    if not bid:
        return _error('No business. / Không xác định được tiệm.')
    if request.method == 'POST':
        try:
            entry = ai_knowledge.create(bid, request.get_json(silent=True) or {}, _who())
        except ai_knowledge.KnowledgeError as e:
            return _error(e)
        out = _payload(bid)
        out['entry'] = entry
        return jsonify(out)
    return jsonify(_payload(bid))


@ai_knowledge_bp.route('/api/ai/knowledge/<entry_id>', methods=['PUT', 'DELETE'])
@login_required
@role_required('admin', 'super_admin')
@limiter.limit("240 per hour")
def ai_knowledge_entry_api(entry_id):
    bid = _bid()
    if not bid:
        return _error('No business. / Không xác định được tiệm.')
    try:
        if request.method == 'DELETE':
            ai_knowledge.delete(bid, entry_id)
            return jsonify(_payload(bid))
        entry = ai_knowledge.update(bid, entry_id, request.get_json(silent=True) or {}, _who())
    except ai_knowledge.KnowledgeError as e:
        return _error(e)
    except LookupError as e:
        return _error(e, 404)
    out = _payload(bid)
    out['entry'] = entry
    return jsonify(out)
