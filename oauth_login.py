"""
Đăng nhập / đăng ký bằng Google và Facebook (OAuth 2.0 / OpenID Connect) — Pha 27.

Luồng (chuẩn "Authorization Code" phía máy chủ, Google thêm PKCE):
  /auth/<google|facebook>/start  -> sinh state (+ PKCE, nonce) lưu trong session, chuyển sang trang đồng ý của Google/Facebook
  /auth/<provider>/callback      -> kiểm state (1 lần, hạn 10 phút), đổi code lấy token bằng secret ở MÁY CHỦ, lấy email/tên
      * đã liên kết tài khoản này          -> đăng nhập
      * email trùng 1 tài khoản BitPaw    -> liên kết + đăng nhập (chỉ khi nhà cung cấp xác nhận email đã xác minh)
      * người mới                          -> trang "Hoàn tất đăng ký" (mã kích hoạt + tên tiệm, không cần mật khẩu)
Nút chỉ hiện khi đã cấu hình khoá (GOOGLE_CLIENT_ID/SECRET, FACEBOOK_APP_ID/SECRET trên Vercel). Không lưu token của
nhà cung cấp — chỉ lưu id tài khoản (sub/id) để lần sau nhận ra người dùng.
"""
import base64
import hashlib
import os
import re
import secrets
import time
import uuid
from datetime import datetime
from urllib.parse import urlencode

import requests
from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from mongo_client import db

oauth_bp = Blueprint('oauth', __name__)

PROVIDERS = {
    'google': {
        'client_id': 'GOOGLE_CLIENT_ID', 'secret': 'GOOGLE_CLIENT_SECRET',
        'auth_url': 'https://accounts.google.com/o/oauth2/v2/auth', 'token_url': 'https://oauth2.googleapis.com/token',
        'userinfo_url': 'https://openidconnect.googleapis.com/v1/userinfo', 'scope': 'openid email profile',
    },
    'facebook': {
        'client_id': 'FACEBOOK_APP_ID', 'secret': 'FACEBOOK_APP_SECRET',
        'auth_url': 'https://www.facebook.com/v19.0/dialog/oauth', 'token_url': 'https://graph.facebook.com/v19.0/oauth/access_token',
        'userinfo_url': 'https://graph.facebook.com/me?fields=id,name,email', 'scope': 'email,public_profile',
    },
}
STATE_TTL = 600
INDUSTRY_EN = {'nail': 'Nail salon', 'spa': 'Spa / beauty', 'fnb': 'Restaurant / cafe', 'karaoke': 'Karaoke / billiards',
               'hotel': 'Hotel / homestay', 'retail': 'Retail shop', 'production': 'Production workshop',
               'technical': 'Field technical services', 'office': 'Office / HR'}


_IN_APP_UA = re.compile(r'BitPawMobileApp/', re.IGNORECASE)


@oauth_bp.app_context_processor
def _inject_oauth_providers():
    # Trong app di động (WebView): Google chặn đăng nhập OAuth trong WebView nhúng ("disallowed_useragent") và trang
    # đăng nhập Google/Facebook mở ra trình duyệt ngoài -> phiên đăng nhập nằm ở trình duyệt, không về app. Ẩn nút
    # trong app (đăng nhập email + mật khẩu); trên web vẫn có.
    try:
        if _IN_APP_UA.search(request.headers.get('User-Agent', '')):
            return {'oauth_providers': []}
        return {'oauth_providers': enabled_providers()}
    except Exception:
        return {'oauth_providers': []}


def _cfg(provider):
    """Cấu hình 1 nhà cung cấp, hoặc None nếu chưa có khoá. Trên máy local (KHÔNG BAO GIỜ trên Vercel) cho phép trỏ
    sang máy chủ OAuth giả lập để kiểm thử end-to-end: OAUTH_TEST_BASE=http://127.0.0.1:5098."""
    p = PROVIDERS.get(provider)
    if not p:
        return None
    cid, sec = os.environ.get(p['client_id']), os.environ.get(p['secret'])
    if not cid or not sec:
        return None
    c = dict(p, cid=cid, sec=sec)
    test_base = os.environ.get('OAUTH_TEST_BASE')
    if test_base and not os.environ.get('VERCEL') and test_base.startswith('http://127.0.0.1'):
        c.update(auth_url=f'{test_base}/{provider}/authorize', token_url=f'{test_base}/{provider}/token',
                 userinfo_url=f'{test_base}/{provider}/userinfo')
    return c


def enabled_providers():
    return [p for p in PROVIDERS if _cfg(p)]


def _redirect_uri(provider):
    base = (os.environ.get('PUBLIC_BASE_URL') or request.host_url).rstrip('/')
    return f'{base}/auth/{provider}/callback'


def _safe_next(nxt):
    """Chỉ cho quay về đường dẫn nội bộ (chặn open-redirect kiểu //evil.com hoặc https://evil.com)."""
    nxt = str(nxt or '')
    return nxt if nxt.startswith('/') and not nxt.startswith('//') and '\\' not in nxt else None


def _security_log(event, detail):
    try:
        db.security_events.insert_one({'type': event, 'detail': str(detail)[:300], 'ip': request.headers.get('X-Forwarded-For', request.remote_addr),
                                       'created_at': datetime.now().isoformat()})
    except Exception:
        pass


@oauth_bp.route('/auth/<provider>/start')
def oauth_start(provider):
    c = _cfg(provider)
    if not c:
        flash('This sign-in option is not available yet.', 'danger')
        return redirect(url_for('login'))
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(48)
    nonce = secrets.token_urlsafe(16)
    session['oauth'] = {'provider': provider, 'state': state, 'verifier': verifier, 'nonce': nonce, 'ts': int(time.time()),
                        'next': _safe_next(request.args.get('next'))}
    params = {'client_id': c['cid'], 'redirect_uri': _redirect_uri(provider), 'response_type': 'code', 'scope': c['scope'], 'state': state}
    if provider == 'google':
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        params.update(code_challenge=challenge, code_challenge_method='S256', nonce=nonce, prompt='select_account')
    return redirect(f"{c['auth_url']}?{urlencode(params)}")


def _fail(msg, log=None):
    if log:
        _security_log('oauth_failed', log)
    flash(msg, 'danger')
    return redirect(url_for('login'))


@oauth_bp.route('/auth/<provider>/callback')
def oauth_callback(provider):
    c = _cfg(provider)
    pending = session.pop('oauth', None)
    if not c:
        return _fail('This sign-in option is not available yet.')
    if request.args.get('error'):
        return _fail('Sign-in was cancelled.')
    if not pending or pending.get('provider') != provider or not secrets.compare_digest(str(pending.get('state')), str(request.args.get('state') or '')):
        return _fail('Sign-in link expired or was not started here — please try again.', f'{provider} state mismatch')
    if time.time() - int(pending.get('ts') or 0) > STATE_TTL:
        return _fail('Sign-in took too long — please try again.')
    code = request.args.get('code')
    if not code:
        return _fail('Sign-in failed — please try again.')
    try:
        data = {'client_id': c['cid'], 'client_secret': c['sec'], 'code': code, 'redirect_uri': _redirect_uri(provider)}
        if provider == 'google':
            data.update(grant_type='authorization_code', code_verifier=pending['verifier'])
            tok = requests.post(c['token_url'], data=data, timeout=15)
        else:
            tok = requests.get(c['token_url'], params=data, timeout=15)
        tok.raise_for_status()
        access = tok.json().get('access_token')
        if not access:
            raise ValueError('no access_token')
        info = requests.get(c['userinfo_url'], headers={'Authorization': f'Bearer {access}'}, timeout=15)
        info.raise_for_status()
        info = info.json()
    except Exception as e:
        return _fail('Could not reach the sign-in provider — please try again.', f'{provider} exchange: {e}')

    if provider == 'google':
        sub, email, name = info.get('sub'), (info.get('email') or '').strip().lower(), info.get('name') or ''
        verified = bool(info.get('email_verified'))
    else:
        sub, email, name = info.get('id'), (info.get('email') or '').strip().lower(), info.get('name') or ''
        verified = bool(email)  # Facebook chỉ trả email đã xác minh
    if not sub:
        return _fail('Sign-in failed — please try again.', f'{provider} no subject')

    user = db.users.find_one({f'oauth.{provider}': str(sub)})
    if not user and email:
        if not verified:
            return _fail(f'Your {provider.title()} email is not verified. Verify it with {provider.title()} or sign in with your password.')
        user = db.users.find_one({'email': {'$regex': f'^{email.replace(".", "[.]")}$', '$options': 'i'}})
        if user:  # liên kết tài khoản sẵn có (email đã được nhà cung cấp xác minh)
            db.users.update_one({'id': user['id']}, {'$set': {f'oauth.{provider}': str(sub), f'oauth_linked_at.{provider}': datetime.now().isoformat()}})
    if user:
        return _login(user, provider, pending.get('next'))
    if not email:
        return _fail('Facebook did not share an email address — please sign up with email instead.')
    session['oauth_signup'] = {'provider': provider, 'sub': str(sub), 'email': email, 'name': name[:100], 'ts': int(time.time())}
    return redirect(url_for('oauth.oauth_complete'))


def _login(user, provider, nxt=None):
    from app import _ensure_primary_membership, _get_real_client_ip
    session.clear()
    session['user_id'] = user['id']
    session['business_id'] = user.get('business_id') or user['id']
    session['user_email'] = user.get('email')
    session['role'] = user.get('role', 'admin')
    _ensure_primary_membership(user['id'], user['id'])
    mode_doc = db.system_settings.find_one({'key': f"business_mode_{user['id']}"}) or {}
    session['business_mode'] = (mode_doc.get('value') or 'none').strip().lower()
    try:
        from mongo_client import next_mongo_id
        db.user_logs.insert_one({'id': next_mongo_id('user_logs'), 'business_id': session['business_id'], 'user_email': user.get('email'),
                                 'action': 'login', 'description': f'Đăng nhập bằng {provider.title()}', 'ip_address': _get_real_client_ip(),
                                 'created_at': datetime.now().isoformat()})
    except Exception:
        pass
    return redirect(nxt or url_for('index'))


@oauth_bp.route('/auth/complete', methods=['GET', 'POST'])
def oauth_complete():
    """Người mới đăng nhập Google/Facebook lần đầu: cần mã kích hoạt (BitPaw gửi sau khi mua gói) + tên tiệm."""
    from app import INDUSTRY_CONFIG, _send_welcome_email, csrf
    pend = session.get('oauth_signup')
    if not pend or time.time() - int(pend.get('ts') or 0) > 1800:
        session.pop('oauth_signup', None)
        flash('Please start again with Google or Facebook.', 'danger')
        return redirect(url_for('login'))
    if request.method == 'GET':
        return render_template('oauth_complete.html', pend=pend, industry_en=INDUSTRY_EN, industries=INDUSTRY_CONFIG)
    csrf.protect()
    license_key = (request.form.get('license_key') or '').strip()
    business_name = (request.form.get('business_name') or '').strip()[:120]
    business_type = (request.form.get('business_type') or '').strip().lower()
    err = None
    if not license_key or not business_name:
        err = 'Please enter your activation code and business name.'
    elif db.users.find_one({'email': {'$regex': f"^{pend['email'].replace('.', '[.]')}$", '$options': 'i'}}):
        err = 'An account with this email already exists — sign in instead.'
    key = None if err else db.license_codes.find_one({'license_key': license_key, 'trang_thai': 'Sẵn sàng'})
    if not err and not key:
        err = 'Invalid activation code, or it has already been used.'
    if err:
        return render_template('oauth_complete.html', pend=pend, industry_en=INDUSTRY_EN, industries=INDUSTRY_CONFIG, error=err,
                               form={'business_name': business_name, 'business_type': business_type}), 400
    lic = (key.get('nganh_nghe') or '').strip().lower()
    if lic and lic != 'all':
        business_type = lic
    if business_type not in INDUSTRY_CONFIG:
        business_type = 'nail'
    if db.license_codes.update_one({'license_key': license_key, 'trang_thai': 'Sẵn sàng'}, {'$set': {'trang_thai': 'Đã kích hoạt'}}).modified_count != 1:
        return render_template('oauth_complete.html', pend=pend, industry_en=INDUSTRY_EN, industries=INDUSTRY_CONFIG, error='Invalid activation code, or it has already been used.'), 400
    user_id = str(uuid.uuid4())
    user = {'id': user_id, 'email': pend['email'], 'password_hash': None, 'business_id': user_id, 'role': 'admin',
            'oauth': {pend['provider']: pend['sub']}, 'created_at': datetime.now().isoformat(), 'signup_method': pend['provider']}
    try:
        db.users.insert_one(dict(user))
        db.businesses.insert_one({'id': user_id, 'name': business_name, 'owner_name': pend.get('name') or '', 'industry_code': business_type,
                                  'created_at': datetime.now().isoformat()})
        db.system_settings.update_one({'key': f'business_mode_{user_id}'}, {'$set': {'key': f'business_mode_{user_id}', 'value': business_type}}, upsert=True)
    except Exception as e:
        db.license_codes.update_one({'license_key': license_key, 'trang_thai': 'Đã kích hoạt'}, {'$set': {'trang_thai': 'Sẵn sàng'}})
        return render_template('oauth_complete.html', pend=pend, industry_en=INDUSTRY_EN, industries=INDUSTRY_CONFIG, error=f'Could not create the account: {e}'), 500
    session.pop('oauth_signup', None)
    try:
        _send_welcome_email(pend['email'], business_name, pend.get('name') or '', business_type)
    except Exception:
        pass
    return _login(user, pend['provider'])
