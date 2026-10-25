"""
Route của AI Social Manager (docs/AI_SUITE_SPEC.md §4.4): trang /social, nối tài khoản (Hộp thư chung / token / OAuth
Google + TikTok), soạn - duyệt - lên lịch - đăng bài, kế hoạch tuần AI, giờ đăng tốt nhất, số liệu thật, bộ đăng (pump) và
cron. Import SAU login_required/role_required trong app.py (cùng cách messaging_routes / ai_studio_bp).
Integrator: đăng ký blueprint, miễn CSRF cho 'social.cron_social_tick', gắn limiter + khoá gói 'marketing_pro'.

Lỗi trả dạng {"success": false, "code", "message", "detail", "platform"} — UI dịch theo `code`.
"""
import hmac
import os
import threading
import time
from functools import wraps
from urllib.parse import urlencode

from flask import Blueprint, jsonify, redirect, render_template, request, session

import social_accounts as sa
import social_planner
import social_publisher as sp
from social_accounts import SocialError
from app import login_required, role_required

social_bp = Blueprint('social', __name__)
ADMIN = ('admin', 'super_admin')
_PUMP_EVERY_SECONDS = 120
_pump_last = {}
_pump_lock = threading.Lock()
_HTTP = {'not_found': 404, 'busy': 409, 'not_editable': 409, 'not_cancelable': 409, 'not_pending': 409,
         'nothing_to_publish': 409, 'real_account_exists': 409, 'ai_unavailable': 502, 'unreachable': 502,
         'provider_busy': 502, 'app_not_configured': 503, 'forbidden': 403}


def _bid():
    return session.get('business_id') or session['user_id']


def _is_admin():
    return session.get('role', 'staff') in ADMIN


def _body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _api(f):
    """SocialError -> JSON có mã lỗi; thiếu khoá mã hoá token (RuntimeError của nurture_channel_tokens) -> 500 rõ ràng."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except SocialError as e:
            return jsonify(e.as_dict()), _HTTP.get(e.code, 400)
        except RuntimeError as e:
            return jsonify({'success': False, 'code': 'server_error', 'message': str(e)[:200], 'detail': None}), 500
    return wrapper


def _forbidden(msg='Only the owner/admin can do this.'):
    return jsonify({'success': False, 'code': 'forbidden', 'message': msg, 'detail': None}), 403


# ---------------------------------------------------------------- trang
@social_bp.route('/social')
@login_required
def social_page():
    bid = _bid()
    try:
        from app import _tenant_currency
        currency = _tenant_currency(bid)
    except Exception:
        currency = 'USD'
    return render_template('social.html', currency=currency, shop_timezone=str(sa.shop_tz(bid)), is_admin=_is_admin(),
                           test_mode=sa.test_mode())


# ---------------------------------------------------------------- tài khoản
@social_bp.route('/api/social/accounts', methods=['GET'])
@login_required
@_api
def accounts_list():
    return jsonify({'success': True, 'data': sa.public_status(_bid())})


@social_bp.route('/api/social/accounts/<platform>', methods=['POST'])
@login_required
@role_required(*ADMIN)
@_api
def accounts_action(platform):
    if platform not in sa.PLATFORMS:
        return jsonify(SocialError('bad_platform', 'Unknown platform.', platform).as_dict()), 404
    bid, data = _bid(), _body()
    action = data.get('action')
    if action == 'connect_inbox':
        row = sa.connect_from_inbox(bid, platform)
    elif action == 'connect_token':
        row = sa.connect_token(bid, platform, data.get('fields') if isinstance(data.get('fields'), dict) else {})
    elif action == 'disconnect':
        sa.disconnect(bid, platform)
        row = sa.public_status(bid)[platform]
    else:
        raise SocialError('bad_action', "action must be 'connect_inbox', 'connect_token' or 'disconnect'.")
    return jsonify({'success': True, 'data': row})


def _redirect_uri(platform):
    # local thử với máy giả: quay về chính máy local (PUBLIC_BASE_URL trong .env là địa chỉ production)
    base = request.host_url if sa.test_mode() else (os.environ.get('PUBLIC_BASE_URL') or request.host_url)
    return f"{base.rstrip('/')}/social/oauth/{platform}/callback"


def _back(**q):
    return redirect('/social?' + urlencode(q))


@social_bp.route('/social/oauth/<platform>/start')
@login_required
@role_required(*ADMIN)
def oauth_start(platform):
    bid = _bid()
    state = sa.new_state()
    try:
        url = sa.oauth_start_url(bid, platform, _redirect_uri(platform), state)
    except SocialError as e:
        return _back(error=e.code, platform=platform)
    session['social_oauth'] = {'platform': platform, 'state': state, 'ts': int(time.time()), 'bid': bid}
    return redirect(url)


@social_bp.route('/social/oauth/<platform>/callback')
@login_required
def oauth_callback(platform):
    pending = session.pop('social_oauth', None)
    if request.args.get('error'):
        return _back(error='oauth_denied', platform=platform)
    # state dùng 1 lần, đúng nền tảng, đúng tiệm, còn hạn 10 phút (chống CSRF đăng nhập / gắn nhầm tài khoản tiệm khác)
    if (not pending or pending.get('platform') != platform or pending.get('bid') != _bid()
            or not hmac.compare_digest(str(pending.get('state') or '').encode(), str(request.args.get('state') or '').encode())):
        return _back(error='oauth_state', platform=platform)
    if time.time() - int(pending.get('ts') or 0) > sa.STATE_TTL:
        return _back(error='oauth_expired', platform=platform)
    if not _is_admin():
        return _back(error='forbidden', platform=platform)
    try:
        sa.oauth_finish(_bid(), platform, request.args.get('code'), _redirect_uri(platform))
    except SocialError as e:
        return _back(error=e.code, platform=platform)
    except RuntimeError:
        return _back(error='server_error', platform=platform)
    return _back(connected=platform)


# ---------------------------------------------------------------- bài đăng
def _time_arg(name):
    v = request.args.get(name)
    if not v:
        return None
    try:
        return sa.parse_iso(v)
    except (ValueError, TypeError):
        raise SocialError('bad_time', f"'{name}' must be an ISO time with a time zone.", v[:40])


@social_bp.route('/api/social/posts', methods=['GET'])
@login_required
@_api
def posts_list():
    statuses = [s for s in (request.args.get('status') or '').split(',') if s]
    posts = sp.list_posts(_bid(), _time_arg('from'), _time_arg('to'), statuses)
    return jsonify({'success': True, 'data': [sp.public_post(p) for p in posts]})


@social_bp.route('/api/social/posts', methods=['POST'])
@login_required
@_api
def posts_create():
    data = _body()
    if not _is_admin() and data.get('status') == 'scheduled':
        data['status'] = 'pending_approval'   # nhân viên soạn bài -> chủ tiệm duyệt mới đăng
    post = sp.create_post(_bid(), session.get('user_id'), data)
    return jsonify({'success': True, 'post': sp.public_post(post)})


@social_bp.route('/api/social/posts/<int:post_id>', methods=['PUT'])
@login_required
@_api
def posts_update(post_id):
    data, bid = _body(), _bid()
    if not _is_admin():
        cur = sp.get_post(bid, post_id)['status']
        if data.get('status', cur) == 'scheduled':
            data['status'] = 'pending_approval'   # nhân viên sửa bài đã lên lịch -> quay lại chờ duyệt
    post = sp.update_post(bid, post_id, data, session.get('user_id'))
    return jsonify({'success': True, 'post': sp.public_post(post)})


@social_bp.route('/api/social/posts/<int:post_id>/approve', methods=['POST'])
@login_required
@role_required(*ADMIN)
@_api
def posts_approve(post_id):
    post = sp.approve(_bid(), post_id, session.get('user_id'))
    return jsonify({'success': True, 'post': sp.public_post(post)})


@social_bp.route('/api/social/posts/<int:post_id>/cancel', methods=['POST'])
@login_required
@role_required(*ADMIN)
@_api
def posts_cancel(post_id):
    post = sp.cancel(_bid(), post_id)
    return jsonify({'success': True, 'post': sp.public_post(post), 'warnings': post.get('warnings') or []})


@social_bp.route('/api/social/posts/<int:post_id>/publish_now', methods=['POST'])
@login_required
@role_required(*ADMIN)
@_api
def posts_publish_now(post_id):
    post, stats = sp.publish_now(_bid(), post_id, session.get('user_id'), deadline=25)
    return jsonify({'success': True, 'post': sp.public_post(post), 'run': stats})


@social_bp.route('/api/social/posts/<int:post_id>', methods=['DELETE'])
@login_required
@_api
def posts_delete(post_id):
    bid = _bid()
    if not _is_admin():
        post = sp.get_post(bid, post_id)
        if post['status'] not in ('draft', 'pending_approval') or post.get('author_id') != session.get('user_id'):
            return _forbidden('Staff can only delete their own drafts.')
    warnings = sp.delete(bid, post_id)
    return jsonify({'success': True, 'warnings': warnings})


# ---------------------------------------------------------------- AI
@social_bp.route('/api/social/plan/week', methods=['POST'])
@login_required
@_api
def plan_week():
    d = _body()
    plan, posts = social_planner.weekly_plan(_bid(), session.get('user_id'), d.get('start_date'), d.get('platforms') or [],
                                             d.get('posts_per_week'), d.get('lang') or 'en')
    return jsonify({'success': True, 'plan': sp._jsonable(plan), 'posts': [sp.public_post(p) for p in posts]})


@social_bp.route('/api/social/captions', methods=['POST'])
@login_required
@_api
def captions_route():
    d = _body()
    return jsonify({'success': True, 'captions': social_planner.captions(_bid(), d.get('text'), d.get('platforms') or [],
                                                                         d.get('lang') or 'en')})


@social_bp.route('/api/social/best_times', methods=['GET'])
@login_required
@_api
def best_times_route():
    try:
        n = int(request.args.get('n') or 3)
    except ValueError:
        n = 3
    return jsonify({'success': True, **social_planner.best_times(_bid(), request.args.get('platform') or 'facebook', n)})


@social_bp.route('/api/social/tiktok/creator_info', methods=['GET'])
@login_required
@_api
def tiktok_creator_info():
    """(Ngoài spec, tương thích) TikTok bắt màn soạn bài hiện tên tài khoản + lựa chọn quyền riêng tư lấy từ TikTok."""
    return jsonify({'success': True, 'data': sp.tiktok_creator_info(_bid())})


@social_bp.route('/api/social/insights', methods=['GET'])
@login_required
@_api
def insights_route():
    try:
        days = int(request.args.get('days') or 30)
    except ValueError:
        days = 30
    return jsonify({'success': True, **sp.insights(_bid(), days)})


@social_bp.route('/api/social/review', methods=['POST'])
@login_required
@_api
def review_route():
    return jsonify({'success': True, **social_planner.performance_review(_bid(), _body().get('lang') or 'en')})


# ---------------------------------------------------------------- bộ đăng + cron
@social_bp.route('/api/social/pump', methods=['POST'])
@login_required
def social_pump():
    """Gọi khi chủ tiệm đang mở app (tối đa 1 lần / 2 phút / tiệm): đăng bài tới giờ + đọc số liệu, không phải chờ cron."""
    bid = _bid()
    now = time.time()
    with _pump_lock:
        if now - _pump_last.get(bid, 0) < _PUMP_EVERY_SECONDS:
            return jsonify({'success': True, 'skipped': True})
        _pump_last[bid] = now
    try:
        stats = sp.run_due(bid, limit=5, deadline=20)
        stats['metrics'] = sp.sync_metrics(bid, 10, deadline=8)
    except Exception as e:
        return jsonify({'success': False, 'code': 'pump_failed', 'message': str(e)[:200]}), 500
    return jsonify({'success': True, **stats})


@social_bp.route('/api/cron/social_tick', methods=['GET', 'POST'])
def cron_social_tick():
    secret = os.environ.get('CRON_SECRET')
    auth = request.headers.get('Authorization', '')
    if not secret or not hmac.compare_digest(auth.encode('utf-8'), f'Bearer {secret}'.encode('utf-8')):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    if not sa.tick_allowed():
        # local dùng chung DB với production: không chạy cho mọi tiệm từ máy local (§0)
        return jsonify({'success': True, 'skipped': 'not_production'})
    try:
        stats = sp.run_due(None, limit=25, deadline=40)
        stats['metrics'] = sp.sync_metrics(None, 40, deadline=12)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)[:200]}), 500
    return jsonify({'success': True, 'test_mode': sa.test_mode(), **stats})
