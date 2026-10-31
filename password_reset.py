"""Quên mật khẩu — đặt lại qua link email dùng 1 lần (Pha 28).

Trước đây nút "Quên mật khẩu" ở trang đăng nhập chỉ hiện "đang gửi…" rồi báo chưa khả dụng: chủ tiệm quên mật khẩu là mất
tài khoản. Chuẩn OWASP:
  - Token ngẫu nhiên 256 bit, CHỈ lưu bản băm SHA-256 (lộ DB cũng không dùng được link), hết hạn sau 30 phút, dùng 1 lần.
  - Trả CÙNG một câu dù email có tài khoản hay không (không dò được email nào là khách BitPaw).
  - Giới hạn: 5 yêu cầu/giờ/IP (limiter) + 3 email/giờ/địa chỉ.
  - Đặt lại xong: mọi phiên đang đăng nhập (web, app điện thoại, app Windows) bị đăng xuất + email báo "mật khẩu vừa đổi".
"""
import hashlib
import os
import re
import secrets
from datetime import datetime, timedelta

from flask import Blueprint, flash, jsonify, redirect, render_template, request
from werkzeug.security import generate_password_hash

import security_shield
from app import bump_session_version, csrf, limiter, _email_query
from email_service import EmailService
from mongo_client import db

reset_bp = Blueprint('password_reset', __name__)
TOKEN_MINUTES = 30
PER_EMAIL_PER_HOUR = 3
GENERIC_MSG = {'en': "If an account exists for that email, we've sent a link to reset the password. Check your inbox (and spam) — the link works for 30 minutes.",
               'vi': 'Nếu email này có tài khoản, BitPaw đã gửi link đặt lại mật khẩu. Kiểm tra hộp thư (cả mục spam) — link dùng được trong 30 phút.'}


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _lang_of(user):
    try:
        import messaging
        return messaging.get_settings(user.get('business_id') or user['id'])['language']
    except Exception:
        return 'en'


def _base_url():
    return (os.environ.get('PUBLIC_BASE_URL') or request.host_url).rstrip('/')


def _ensure_indexes():
    try:
        db.password_resets.create_index('expires_at', expireAfterSeconds=0)
        db.password_resets.create_index('token_hash', unique=True)
    except Exception:
        pass


@reset_bp.route('/api/auth/forgot_password', methods=['POST'])
@limiter.limit("5 per hour")
def forgot_password():
    data = request.get_json(silent=True) or {}
    lang = 'vi' if data.get('lang') == 'vi' else 'en'
    email = str(data.get('email') or '').strip().lower()[:160]
    ip = security_shield.client_ip(request)
    if security_shield.honeypot_tripped(data):
        return jsonify({'success': True, 'message': GENERIC_MSG[lang]})
    if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
        return jsonify({'success': False, 'message': 'Please enter a valid email.' if lang == 'en' else 'Vui lòng nhập email hợp lệ.'}), 400
    _ensure_indexes()
    since = datetime.utcnow() - timedelta(hours=1)
    recent = db.password_resets.count_documents({'email': email, 'created_at': {'$gte': since}})
    user = db.users.find_one(_email_query(email), {'_id': 0, 'id': 1, 'email': 1, 'business_id': 1, 'full_name': 1})
    if user and recent < PER_EMAIL_PER_HOUR:
        token = secrets.token_urlsafe(32)
        db.password_resets.insert_one({'token_hash': _hash(token), 'user_id': user['id'], 'email': email, 'ip': ip, 'used': False,
                                       'created_at': datetime.utcnow(), 'expires_at': datetime.utcnow() + timedelta(minutes=TOKEN_MINUTES)})
        ulang = _lang_of(user)
        link = f"{_base_url()}/reset-password/{token}"
        if ulang == 'vi':
            subject = 'Đặt lại mật khẩu BitPaw'
            html = (f"<p>Chào {user.get('full_name') or ''},</p><p>Có yêu cầu đặt lại mật khẩu cho tài khoản BitPaw <b>{user['email']}</b>.</p>"
                    f"<p><a href=\"{link}\" style=\"display:inline-block;background:#0891b2;color:#fff;padding:12px 20px;border-radius:10px;"
                    f"text-decoration:none;font-weight:700\">Đặt mật khẩu mới</a></p><p>Link dùng 1 lần, hết hạn sau {TOKEN_MINUTES} phút. "
                    "Nếu bạn không yêu cầu, hãy bỏ qua email này — mật khẩu hiện tại vẫn giữ nguyên.</p>")
        else:
            subject = 'Reset your BitPaw password'
            html = (f"<p>Hi {user.get('full_name') or ''},</p><p>Someone asked to reset the password for the BitPaw account <b>{user['email']}</b>.</p>"
                    f"<p><a href=\"{link}\" style=\"display:inline-block;background:#0891b2;color:#fff;padding:12px 20px;border-radius:10px;"
                    f"text-decoration:none;font-weight:700\">Choose a new password</a></p><p>The link works once and expires in {TOKEN_MINUTES} minutes. "
                    "If you didn't ask for this, ignore this email — your password stays the same.</p>")
        EmailService.send_email(user['email'], subject, html)
        security_shield.log_event('password_reset_requested', ip, '', request.path, request.headers.get('User-Agent', ''), email)
    elif user:
        security_shield.log_event('password_reset_throttled', ip, '', request.path, request.headers.get('User-Agent', ''), email)
    return jsonify({'success': True, 'message': GENERIC_MSG[lang]})


def _valid_reset(token):
    if not token or len(token) > 100:
        return None
    return db.password_resets.find_one({'token_hash': _hash(token), 'used': False, 'expires_at': {'$gt': datetime.utcnow()}}, {'_id': 0})


@reset_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
@limiter.limit("20 per hour", methods=['POST'])
def reset_password(token):
    doc = _valid_reset(token)
    if request.method == 'GET':
        return render_template('reset_password.html', valid=bool(doc), email=(doc or {}).get('email', ''))
    csrf.protect()
    if not doc:
        return render_template('reset_password.html', valid=False), 400
    pw, pw2 = request.form.get('password') or '', request.form.get('password2') or ''
    err = None
    if len(pw) < 8:
        err = 'Use at least 8 characters.'
    elif pw != pw2:
        err = "The two passwords don't match."
    elif pw.strip().lower() == (doc.get('email') or '').lower() or pw.lower() in ('password', '12345678', 'bitpaw123', 'qwerty123'):
        err = 'That password is too easy to guess — choose another.'
    if err:
        return render_template('reset_password.html', valid=True, email=doc.get('email'), error=err), 400
    # dùng đúng 1 lần (2 tab bấm cùng lúc chỉ 1 tab được)
    claim = db.password_resets.update_one({'token_hash': _hash(token), 'used': False}, {'$set': {'used': True, 'used_at': datetime.utcnow()}})
    if claim.modified_count != 1:
        return render_template('reset_password.html', valid=False), 400
    db.users.update_one({'id': doc['user_id']}, {'$set': {'password_hash': generate_password_hash(pw), 'password_changed_at': datetime.utcnow().isoformat()}})
    db.password_resets.update_many({'user_id': doc['user_id'], 'used': False}, {'$set': {'used': True}})
    bump_session_version(doc['user_id'])
    ip = security_shield.client_ip(request)
    security_shield.log_event('password_reset_done', ip, 'all sessions signed out', request.path, request.headers.get('User-Agent', ''), doc.get('email'))
    EmailService.send_email(doc['email'], 'Your BitPaw password was changed',
                            '<p>Your BitPaw password was just changed and every device was signed out.</p>'
                            "<p>If this wasn't you, reset it again right away from the sign-in page and contact BitPaw.</p>")
    flash('Password updated. Please sign in with your new password.', 'success')
    return redirect('/login')


@reset_bp.route('/api/account/logout_all', methods=['POST'])
def logout_all():
    """Đăng xuất tài khoản này khỏi MỌI thiết bị (nghi bị lộ mật khẩu / mất điện thoại).
    Super Admin (phiên God Mode, uid 'superadmin-fallback' — _session_guard đã kiểm phiên hợp lệ trước route này): tăng
    system_settings.superadmin_session_ver -> mọi phiên God Mode khác bị đăng xuất (trước đây trả 401, không cắt được phiên nào)."""
    from flask import session
    uid = session.get('user_id')
    if not uid:
        return jsonify({'success': False, 'message': 'Not signed in.'}), 401
    bump_session_version(uid)
    security_shield.log_event('logout_all', security_shield.client_ip(request), '', request.path,
                              request.headers.get('User-Agent', ''), session.get('user_email'))
    session.clear()
    return jsonify({'success': True})
