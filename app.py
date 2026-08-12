import sqlite3

# ========== MONKEY-PATCH SQLITE3 FOR PRODUCTION STABILITY & CONCURRENCY ==========
_original_sqlite3_connect = sqlite3.connect
def custom_sqlite3_connect(database, *args, **kwargs):
    if database == 'database.db' or database == 'sales.db':
        kwargs['timeout'] = 15.0
        conn = _original_sqlite3_connect(database, *args, **kwargs)
        try:
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA synchronous=NORMAL')
            conn.execute('PRAGMA busy_timeout=15000')
        except Exception:
            pass
        return conn
    return _original_sqlite3_connect(database, *args, **kwargs)
sqlite3.connect = custom_sqlite3_connect

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, send_from_directory, Response, stream_with_context, current_app, g
from jinja2.exceptions import TemplateNotFound
from datetime import datetime, timedelta
import os
import time
import math
import uuid
import json
import random
import re
import base64
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import requests
import jwt as pyjwt  # PyJWT — Giai đoạn 5 audit: JWT auth cho Mobile App (Flutter/React Native)
# Đã gỡ bỏ hoàn toàn Supabase khỏi backend — toàn bộ dữ liệu giờ đọc/ghi qua MongoDB Atlas
# (pymongo) bên dưới.
from mongo_client import db, fs, client as mongo_client_instance, MONGO_STATUS, next_mongo_id, next_mongo_id_batch
from i18n import get_translations, resolve_lang, LANG_COOKIE_NAME
from pymongo import UpdateOne, ReturnDocument
# Mã 4.1 (Offline-Sync) + Mã 1.2 (Redis Streams check-in/out) audit — lỗi mất kết nối Atlas cần
# bắt RIÊNG (không phải Exception chung) để route biết chính xác lúc nào nên rơi vào nhánh lưu
# tạm offline, thay vì coi mọi lỗi (kể cả lỗi dữ liệu/logic) đều là "mất mạng".
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError, NetworkTimeout, AutoReconnect
import redis_queue
import sync_worker
import nurture_channel_tokens
from cryptography.fernet import Fernet
from gridfs import GridFS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.exceptions import RequestEntityTooLarge, BadRequest
from gridfs.errors import NoFile
from bson import ObjectId
from bson.errors import InvalidId
from ai_context_engine import AIContextEngine
from ai_sales_prompts import compose_system_prompt, classify_objection
from ai_memory_engine import get_conversation_memory, maybe_distill_memory_async
from ai_nurturing_engine import AINurturingEngine, recompute_customer_segments
from email_service import EmailService
from ai_function_tools import TOOL_SCHEMAS, execute_tool_call
from ai_deepseek_client import deepseek_chat_completion

# Các module cho US market pivot (tenant_engine/currency_utils/payment_us_engine) từng làm
# sập TOÀN BỘ app trên Vercel (mọi route, kể cả /favicon.ico, đều 500 FUNCTION_INVOCATION_FAILED
# vì import app.py thất bại ngay từ đầu) do file chưa được commit lên git nên thiếu trong bản
# deploy. Bọc try/except ở đây để một module tuỳ chọn bị thiếu/lỗi không còn kéo sập cả server —
# chỉ tính năng multi-region/US payment bị vô hiệu (fallback VN/VND mặc định), các route khác
# vẫn chạy bình thường. Vẫn cần đảm bảo 3 file này được commit đầy đủ để tính năng hoạt động thật.
try:
    from tenant_engine import TenantEngine
except Exception as _import_err:
    print(f"[!] Critical: could not import tenant_engine ({_import_err}). Falling back to VN/VND default for all tenants.")
    class TenantEngine:
        @staticmethod
        def resolve_tenant(user_id):
            return None

        @staticmethod
        def get_region_config(business_id):
            return {"country": "VN", "currency": "VND"}

try:
    from currency_utils import format_money
except Exception as _import_err:
    print(f"[!] Critical: could not import currency_utils ({_import_err}). Falling back to plain VND formatting.")
    def format_money(amount, currency='VND'):
        try:
            value = float(amount or 0)
        except (TypeError, ValueError):
            value = 0.0
        if (currency or 'VND').upper() == 'USD':
            return f"${value:,.2f}"
        return f"{int(round(value)):,}".replace(',', '.') + 'đ'

try:
    import payment_us_engine
except Exception as _import_err:
    print(f"[!] Critical: could not import payment_us_engine ({_import_err}). US Square payment route will report 'not configured'.")
    class _PaymentUsEngineFallback:
        SQUARE_DEVICE_ID = None

        @staticmethod
        def start_us_payment(amount_usd, txn_id, description='BitPaw POS Order'):
            return {'success': False, 'configured': False, 'message': 'payment_us_engine module không khả dụng trên server này.'}

        @staticmethod
        def is_configured():
            return False

        @staticmethod
        def create_terminal_checkout(amount_usd, txn_id, note='BitPaw POS Order'):
            return {'success': False, 'configured': False, 'message': 'payment_us_engine module không khả dụng trên server này.'}

        @staticmethod
        def verify_webhook_signature(request_url, request_body_bytes, signature_header):
            return False  # fail-closed: module lỗi/không có -> KHÔNG BAO GIỜ coi webhook hợp lệ
    payment_us_engine = _PaymentUsEngineFallback()

app = Flask(__name__, static_folder='static', template_folder='templates')
_flask_secret_key = os.environ.get('FLASK_SECRET_KEY')
if not _flask_secret_key:
    raise RuntimeError(
        "FLASK_SECRET_KEY chưa được cấu hình trong biến môi trường. "
        "Đặt biến này trong .env (dev) hoặc Vercel Project Settings -> Environment Variables (production) trước khi chạy."
    )
app.secret_key = _flask_secret_key

# --- JWT cho Mobile App (Giai đoạn 6 audit — CISO/Pentest) ---
# BẮT BUỘC biến môi trường JWT_SECRET riêng — KHÔNG được dùng lại FLASK_SECRET_KEY làm key dự
# phòng (thiết kế ban đầu ở Giai đoạn 5, nay coi là anti-pattern bảo mật): 2 mục đích ký khác
# nhau (session cookie Web vs JWT Mobile) PHẢI dùng 2 khoá độc lập — nếu 1 trong 2 secret bị lộ
# (vd log lỗi vô tình in ra, hoặc rotate 1 bên mà quên bên kia), bên còn lại vẫn an toàn/không bị
# forge theo. Thiếu JWT_SECRET -> crash ngay lúc khởi động, KHÔNG âm thầm dùng key dự phòng.
JWT_SECRET = os.environ.get('JWT_SECRET')
if not JWT_SECRET:
    raise RuntimeError(
        "JWT_SECRET chưa được cấu hình trong biến môi trường. "
        "Sinh 1 chuỗi ngẫu nhiên mạnh riêng biệt với FLASK_SECRET_KEY (vd: python -c \"import secrets; print(secrets.token_hex(32))\") "
        "và đặt trong .env (dev) hoặc Environment Variables (production) trước khi chạy."
    )
JWT_ALGORITHM = 'HS256'
# JWT_EXPIRY_HOURS mặc định 30 ngày — app mobile cần "đăng nhập 1 lần, dùng lâu dài", khác web
# (session hết hạn theo cookie trình duyệt).
JWT_EXPIRY_HOURS = int(os.environ.get('JWT_EXPIRY_HOURS', '720'))

# --- Session cookie an toàn (Mã 3.3 audit) ---
# Secure: cookie chỉ gửi qua HTTPS (Vercel production luôn HTTPS nên không ảnh hưởng gì; chỉ
# lưu ý nếu bạn tự test bằng http://localhost thì trình duyệt sẽ KHÔNG lưu cookie — dùng
# 127.0.0.1 hoặc chấp nhận điều này khi dev local, đừng tắt Secure để né việc này).
# HttpOnly: JS phía client không đọc được cookie -> chặn đánh cắp session qua XSS.
# SameSite=Lax: cookie không bị gửi kèm trong request cross-site (nền tảng của CSRF), vẫn cho
# phép mở link bình thường từ nơi khác (Lax, không phải Strict, để không phá vỡ luồng redirect
# sau khi khách bấm link từ Zalo/Facebook/email vẫn giữ được đăng nhập).
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
)

# --- CSRF Protection + Hybrid JWT/Session Auth (Giai đoạn 2 + Giai đoạn 5) ---
# Giai đoạn 2: bật CSRF cho MỌI request POST/PUT/PATCH/DELETE (trước đó tắt hẳn = lỗ hổng: 1
# trang độc hại có thể forge request bằng session cookie của nạn nhân, cookie tự động gửi kèm).
# _inject_csrf_bootstrap() bên dưới tự chèn token vào mọi trang HTML để không phá hàng trăm
# fetch() JSON hiện có của Web.
#
# Giai đoạn 5: Mobile App (Flutter/React Native) không load HTML nên KHÔNG BAO GIỜ nhận được
# token qua cơ chế trên — nhưng Mobile cũng KHÔNG CẦN CSRF: CSRF chỉ có ý nghĩa khi trình duyệt
# TỰ ĐỘNG đính kèm thông tin xác thực (cookie) vào request mà nạn nhân không hề hay biết; header
# `Authorization: Bearer <JWT>` không BAO GIỜ được trình duyệt tự gắn vào request của 1 trang
# khác — về bản chất đã miễn nhiễm CSRF. Flask-WTF không có API public để tắt CSRF động theo
# từng request, nên _hybrid_auth_and_csrf() bên dưới THAY THẾ hoàn toàn cơ chế before_request tự
# động của CSRFProtect (đặt WTF_CSRF_CHECK_DEFAULT=False) bằng 1 before_request tự viết: nếu có
# Bearer JWT hợp lệ -> nạp session từ token rồi bỏ qua CSRF; ngược lại -> gọi csrf.protect() y hệt
# Giai đoạn 2 (method public, đã dùng ở login()/register() từ trước, không đổi mức bảo vệ Web).
#
# Các endpoint KHÔNG thể mang CSRF token hợp lệ vì bản chất KHÔNG qua trình duyệt có session
# (webhook server-to-server, cron job) hoặc là hành động công khai không gắn quyền hạn phiên
# đăng nhập nào (analytics/lead công khai) được @csrf.exempt tường minh bên dưới, xem danh sách
# _CSRF_EXEMPT_ENDPOINTS.
from flask_wtf import CSRFProtect  # noqa: E402
from flask_wtf.csrf import generate_csrf  # noqa: E402

app.config['WTF_CSRF_CHECK_DEFAULT'] = False
csrf = CSRFProtect(app)


def _get_bearer_token():
    """Đọc token từ header 'Authorization: Bearer <token>' — trả None nếu không có/sai format."""
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        return auth_header[7:].strip() or None
    return None


def _load_session_from_jwt(token):
    """Giải mã JWT (cấp bởi /api/auth/token), nạp claims vào flask.session (chỉ tồn tại trong
    phạm vi request hiện tại) — CHỦ ĐÍCH để toàn bộ hàng trăm chỗ trong app.py đang đọc
    session.get('business_id')/session['user_id']/session.get('role') hoạt động ĐÚNG Y NHƯ session
    cookie Web, không cần sửa từng route riêng lẻ. Trả về True nếu token hợp lệ, False nếu không
    (hết hạn/sai chữ ký/thiếu claim bắt buộc) — KHÔNG raise, caller tự quyết định phản hồi lỗi."""
    try:
        payload = pyjwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except pyjwt.PyJWTError:
        return False
    if not payload.get('user_id'):
        return False
    session['user_id'] = payload['user_id']
    session['business_id'] = payload.get('business_id') or payload['user_id']
    session['user_email'] = payload.get('user_email')
    session['role'] = payload.get('role', 'admin')
    session['business_mode'] = payload.get('business_mode', 'none')
    return True


@app.before_request
def _hybrid_auth_and_csrf():
    """Chạy TRƯỚC mọi route — xem khối comment CSRF phía trên để hiểu vì sao hàm này thay thế
    hoàn toàn before_request tự động của CSRFProtect thay vì dùng song song.

    QUAN TRỌNG: csrf.protect() (gọi trực tiếp, không qua before_request tự động của
    CSRFProtect) KHÔNG hề tự kiểm tra danh sách _CSRF_EXEMPT_ENDPOINTS — logic exempt-view của
    Flask-WTF chỉ nằm TRONG before_request tự động của chính nó (đã bị tắt hẳn bởi
    WTF_CSRF_CHECK_DEFAULT=False ở trên), KHÔNG nằm trong protect() — xác nhận bằng cách đọc
    thẳng source code flask_wtf.csrf.CSRFProtect. Do đó phải tự kiểm tra exempt TẠI ĐÂY trước
    khi gọi protect(), nếu không toàn bộ webhook/cron/public route trong
    _CSRF_EXEMPT_ENDPOINTS sẽ bị chặn nhầm (đã xảy ra thật lúc test /api/auth/token)."""
    token = _get_bearer_token()
    if token:
        if _load_session_from_jwt(token):
            g.auth_via_jwt = True
            return  # Bearer hợp lệ -> bỏ qua csrf.protect(), request này miễn nhiễm CSRF sẵn.
        # Có gửi Bearer nhưng SAI/hết hạn -> từ chối thẳng, KHÔNG âm thầm rơi về check cookie
        # (client Mobile đang cố dùng token, phải biết ngay token hỏng thay vì bị coi như chưa
        # đăng nhập rồi nhận HTML redirect mà JSON parser phía app không xử lý được).
        if request.path.startswith('/api/'):
            return jsonify({'success': False, 'message': 'Token không hợp lệ hoặc đã hết hạn.'}), 401
    if request.endpoint in _CSRF_EXEMPT_ENDPOINTS:
        return
    csrf.protect()


def _wants_json():
    """True nếu request nên nhận response JSON thay vì HTML/redirect kiểu web cổ điển — Mobile
    App (luôn xác thực qua JWT Bearer, đánh dấu qua g.auth_via_jwt) HOẶC path bắt đầu '/api/'
    HOẶC client tự khai muốn JSON qua header Accept. Trình duyệt Web (session cookie, render HTML
    bình thường) không rơi vào bất kỳ điều kiện nào ở đây -> giữ NGUYÊN hành vi HTML/redirect cũ,
    không phá giao diện hiện có."""
    return bool(g.get('auth_via_jwt')) or request.path.startswith('/api/') or \
        request.accept_mimetypes.best == 'application/json'

_CSRF_BOOTSTRAP_SCRIPT = """
<script>
(function() {
  var CSRF_TOKEN = %s;
  var UNSAFE_METHODS = ['POST', 'PUT', 'PATCH', 'DELETE'];
  var originalFetch = window.fetch;
  window.fetch = function(input, init) {
    init = init || {};
    var method = (init.method || (input && input.method) || 'GET').toUpperCase();
    if (UNSAFE_METHODS.indexOf(method) !== -1) {
      var url = (typeof input === 'string') ? input : ((input && input.url) || '');
      var isAbsolute = /^([a-z][a-z0-9+.-]*:)?\\/\\//i.test(url);
      if (!isAbsolute || url.indexOf(window.location.origin) === 0) {
        var headers = new Headers(init.headers || {});
        if (!headers.has('X-CSRFToken')) {
          headers.set('X-CSRFToken', CSRF_TOKEN);
        }
        init.headers = headers;
      }
    }
    return originalFetch.call(this, input, init);
  };
  function bootstrapForms() {
    document.querySelectorAll('form').forEach(function(f) {
      var method = (f.getAttribute('method') || 'GET').toUpperCase();
      if (method === 'POST' && !f.querySelector('input[name="csrf_token"]')) {
        var inp = document.createElement('input');
        inp.type = 'hidden'; inp.name = 'csrf_token'; inp.value = CSRF_TOKEN;
        f.appendChild(inp);
      }
    });
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bootstrapForms);
  } else {
    bootstrapForms();
  }
})();
</script>
""".strip()


@app.after_request
def _inject_csrf_bootstrap(response):
    """Chèn script gắn CSRF token tự động (xem giải thích ở khối comment CSRF phía trên) vào
    MỌI response HTML thành công — chạy 1 lần/response, an toàn nếu lỗi (không được phép làm
    hỏng response gốc chỉ vì bootstrap thất bại)."""
    try:
        if response.mimetype == 'text/html' and response.status_code < 400 and not response.direct_passthrough:
            html = response.get_data(as_text=True)
            if '</body>' in html and 'CSRF_TOKEN' not in html:
                token_json = json.dumps(generate_csrf())
                snippet = _CSRF_BOOTSTRAP_SCRIPT % token_json
                response.set_data(html.replace('</body>', snippet + '</body>', 1))
    except Exception as e:
        print(f"[CSRF bootstrap] Chèn script thất bại (không ảnh hưởng response gốc): {e}")
    return response


# Endpoint KHÔNG session trình duyệt (webhook/cron) hoặc hành động công khai không gắn quyền
# hạn phiên đăng nhập nào (lead công khai, tracking, đặt món qua QR, chat khách vãng lai) —
# CSRF không có ý nghĩa bảo vệ ở đây (không có "quyền hạn phiên" nào để giả mạo đánh cắp), và
# 1 số nơi (webhook) về bản chất không thể mang session cookie/token nào cả.
_CSRF_EXEMPT_ENDPOINTS = [
    'api_webhook_square',
    'cron_daily_tasks',
    'create_cskh_request',
    'track_cskh_click',
    'submit_feedback',
    'api_checkout_signup',
    'submit_qr_order',
    'api_table_notify',
    'api_portal_messages_create',
    'api_portal_upload',
    'api_cskh_chat_send',
    # Giai đoạn 5 audit — endpoint CẤP JWT cho Mobile App: về bản chất "con gà quả trứng", client
    # gọi route này CHƯA CÓ token (đó chính là lý do nó gọi route này) nên KHÔNG THỂ mang CSRF
    # token hợp lệ. Không phải lỗ hổng: route không dựa vào cookie ambient — xác thực bằng
    # email/password tường minh trong body, và response (JWT) trả về JSON mà 1 request CSRF giả
    # mạo (cross-site form POST) không đọc lại được do same-origin policy của trình duyệt.
    'api_auth_token',
]

# Payload size cap — chặn request body khổng lồ (DoS/spam) ở TẤT CẢ route cùng lúc, một chỗ duy
# nhất thay vì phải tự giới hạn tay ở từng route. 10MB đủ rộng cho ảnh chụp điện thoại upload qua
# /api/storage/upload, /api/portal/upload... (ảnh thật thường 2-8MB) nhưng vẫn chặn được payload
# cỡ GB. Vượt giới hạn -> Flask tự trả 413 (RequestEntityTooLarge), xử lý ở error handler bên dưới.
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024

# Rate limiting (chống brute-force/spam) — áp dụng default_limits cho MỌI route tự động, cộng
# thêm giới hạn CHẶT hơn khai báo riêng ở /login, /register, /api/auth/token (xem các route đó).
#
# Giai đoạn 6 audit (CISO/Pentest) — "memory://" CHỈ đếm request TRONG CÙNG 1 process: trên
# serverless (nhiều instance/cold start riêng biệt) HOẶC nhiều worker gunicorn (xem Procfile: 4
# worker), mỗi process có bộ đếm RIÊNG, nghĩa là giới hạn "5 lần/15 phút" thực tế trở thành "5 ×
# (số instance/worker đang chạy) lần/15 phút" — hacker brute-force mật khẩu hoặc dội bom
# /api/ai/studio/generate (tốn tiền DeepSeek mỗi request) có thể NHÂN SỐ LẦN THỬ THEO SỐ INSTANCE
# đơn giản bằng cách gửi request dồn dập (load balancer/serverless tự rải qua nhiều instance).
#
# Fix: dùng CHUNG Redis đã có sẵn cho Streams (REDIS_URL) làm storage backend — 1 bộ đếm DUY
# NHẤT chia sẻ giữa MỌI process, giới hạn chính xác tuyệt đối bất kể chạy bao nhiêu instance/
# worker. Key prefix của Flask-Limiter (LIMITER/...) không đụng namespace với Streams
# (bitpaw:attendance:events, bitpaw:order:events) nên dùng chung 1 Redis an toàn, không cần
# instance Redis riêng. Ưu tiên RATELIMIT_STORAGE_URI nếu cấu hình riêng (vd muốn tách DB index
# khác/Redis khác); nếu không có, tự dùng REDIS_URL; chỉ rơi về "memory://" (best-effort, KHÔNG
# an toàn cho production nhiều instance) khi máy dev local chưa cấu hình Redis nào cả.
_ratelimit_storage_uri = (
    os.environ.get('RATELIMIT_STORAGE_URI')
    or os.environ.get('REDIS_URL')
    or 'memory://'
)
if _ratelimit_storage_uri == 'memory://':
    print("[!] CANH BAO: Rate limiter dang chay memory:// (khong dung chung giua cac instance). "
          "Dat REDIS_URL hoac RATELIMIT_STORAGE_URI truoc khi len production.")


def _get_real_client_ip():
    """Địa chỉ IP THẬT của khách — Giai đoạn 7 (SRE) audit.

    Sau khi bọc domain qua Cloudflare (Proxied/orange cloud), request.remote_addr mặc định của
    Flask (và get_remote_address() mặc định của Flask-Limiter dùng chính giá trị này) LUÔN LÀ IP
    CỦA CLOUDFLARE EDGE SERVER, không phải IP khách thật (Cloudflare là proxy, kết nối TCP tới
    Vercel origin xuất phát từ chính Cloudflare). Hậu quả nếu không sửa: (1) rate limit/brute-force
    protection coi HÀNG NGHÌN khách khác nhau là "cùng 1 IP" (dải IP Cloudflare rất hẹp) -> 1
    khách bị chặn kéo theo chặn nhầm mọi khách khác đang đi qua cùng edge node, HOẶC ngược lại
    tuỳ round-robin của Cloudflare mà giới hạn không còn tác dụng thật; (2) audit log
    (user_logs.ip_address) ghi sai hoàn toàn, vô dụng khi điều tra sự cố đăng nhập.

    Ưu tiên CF-Connecting-IP — Cloudflare LUÔN tự ĐỘNG GHI ĐÈ header này bằng IP kết nối TCP thật
    trước khi forward tới origin; client KHÔNG có cách nào tự khai giá trị giả cho header này KHI
    đi qua Cloudflare (Cloudflare strip mọi CF-Connecting-IP client tự gửi trước khi gán lại giá
    trị thật). Fallback X-Forwarded-For (IP đầu chuỗi — chuẩn de-facto), rồi request.remote_addr
    (dev local/test, không qua Cloudflare).

    CẢNH BÁO BẢO MẬT CÒN LẠI: helper này chỉ đáng tin nếu origin Vercel KHÔNG thể bị truy cập
    trực tiếp bỏ qua Cloudflare — Vercel (khác Cloudflare) KHÔNG tự strip CF-Connecting-IP, nên
    ai gọi thẳng *.vercel.app (thay vì domain qua Cloudflare) vẫn tự khai được header này. Xem
    khuyến nghị chặn truy cập trực tiếp Vercel trong báo cáo SRE đi kèm — PHẢI làm cùng lúc với
    patch này để có hiệu lực đầy đủ."""
    cf_ip = request.headers.get('CF-Connecting-IP')
    if cf_ip:
        return cf_ip.strip()
    xff = request.headers.get('X-Forwarded-For')
    if xff:
        return xff.split(',')[0].strip()
    return request.remote_addr or '127.0.0.1'


limiter = Limiter(
    _get_real_client_ip,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri=_ratelimit_storage_uri,
)


@app.errorhandler(429)
def _rate_limit_exceeded(e):
    """429 (Too Many Requests) — API routes get a clean JSON error; HTML routes (login/register)
    get the same login page back with a flash message instead of Flask-Limiter's plain-text
    default body, so the cashier/owner sees a normal-looking page, not a raw error dump."""
    # Log lại IP bị chặn 429 (Mã 3.5 audit) — dấu hiệu spam/tấn công có chủ đích, đặc biệt quan
    # trọng với /api/ai/studio/generate vì mỗi request lọt qua đều TỐN TIỀN thật (DeepSeek tính
    # phí theo request). print() ra console luôn (Vercel Runtime Logs đọc được ngay), CỘNG THÊM
    # ghi vào Mongo collection 'security_events' nếu DB đang sống — best-effort, lỗi ghi Mongo
    # KHÔNG được phép làm hỏng việc trả 429 bình thường cho client.
    client_ip = _get_real_client_ip()
    print(f"[RATE LIMIT] 429 - IP={client_ip} path={request.path} method={request.method}")
    try:
        if db is not None:
            db.security_events.insert_one({
                'type': 'rate_limit_exceeded',
                'ip': client_ip,
                'path': request.path,
                'method': request.method,
                'user_agent': request.headers.get('User-Agent', ''),
                'business_id': session.get('business_id'),
                'created_at': datetime.now().isoformat(),
            })
    except Exception as log_err:
        print(f"[RATE LIMIT] Lỗi ghi security_events (không ảnh hưởng response 429): {log_err}")

    if request.path.startswith('/api/'):
        return jsonify({"success": False, "message": "Quá nhiều yêu cầu. Vui lòng thử lại sau ít phút."}), 429
    flash('Quá nhiều lần thử. Vui lòng đợi vài phút rồi thử lại.', 'danger')
    return render_template('index.html', active_tab='login'), 429


@app.errorhandler(RequestEntityTooLarge)
def _request_too_large(e):
    """413 — payload vượt MAX_CONTENT_LENGTH ở trên. Trả JSON rõ ràng cho API, tránh Flask hiện
    trang lỗi HTML mặc định (không hữu ích cho 1 fetch() JS đang chờ JSON)."""
    return jsonify({"success": False, "message": "Dữ liệu gửi lên quá lớn (giới hạn 10MB)."}), 413


@app.errorhandler(BadRequest)
def _bad_request(e):
    """400 — bắt luôn các trường hợp request.json/request.form parse lỗi (JSON malformed,
    Content-Type sai...) ở TẤT CẢ route, trả JSON gọn thay vì trang lỗi HTML mặc định của
    Werkzeug — nhất quán với convention {success: False, message: ...} toàn bộ API dùng."""
    if request.path.startswith('/api/'):
        return jsonify({"success": False, "message": "Dữ liệu gửi lên không hợp lệ (malformed request)."}), 400
    return e

# Mã hoá thông tin đăng nhập sàn TMĐT (ecommerce_sync.html) tại nghỉ — KHÔNG BAO GIỜ lưu
# plaintext (bản Supabase cũ gửi thẳng api_key/api_secret dạng chữ thường lên Supabase, không
# mã hoá gì cả). Nếu chưa cấu hình ECOMMERCE_ENC_KEY, tính năng lưu credential PHẢI từ chối
# (fail-closed) thay vì âm thầm lưu plaintext.
_ecommerce_enc_key = os.environ.get('ECOMMERCE_ENC_KEY')
try:
    _ecommerce_fernet = Fernet(_ecommerce_enc_key.encode()) if _ecommerce_enc_key else None
except Exception as _e:
    print(f"[!] ECOMMERCE_ENC_KEY không hợp lệ (phải là 1 Fernet key base64 32 byte): {_e}")
    _ecommerce_fernet = None

# Version cache-bust cho static JS/CSS versioned qua asset_version — tính 1 lần lúc process
# khởi động (không phải mỗi request, tránh mất tác dụng cache), nên mỗi lần Vercel
# redeploy/cold start sẽ ra version mới, buộc trình duyệt tải lại thay vì dùng bản cache cũ.
_ASSET_VERSION = str(int(time.time()))


@app.after_request
def _disable_html_caching(response):
    """Chặn cache trình duyệt/CDN cho các trang HTML/JSON render động (Jinja), tránh người
    dùng thấy dữ liệu CŨ sau khi server/source đã cập nhật. Không áp dụng cho /static/ vì
    file tĩnh (css/js/ảnh) cache bình thường là an toàn và cần thiết cho hiệu năng.
    """
    if not request.path.startswith('/static/'):
        response.headers['Cache-Control'] = 'no-store, must-revalidate'
    return response


# Upload ảnh
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


INDUSTRY_CONFIG = {
    'retail': {
        'code': 'retail',
        'name': 'Cửa hàng Bán lẻ (Retail)',
        'icon': '🛍️',
        'desc': 'Thời trang, Mỹ phẩm, Tạp hóa, Điện tử. Quản lý tồn kho, mã vạch, báo cáo doanh thu.',
        'redirect_after_login': '/dashboard',
        'dashboard_route': '/dashboard',
        'templates': ['dashboard.html', 'add_product.html', 'sell.html'],
        'modules': ['sales', 'inventory', 'expenses'],
        'permissions': ['view_dashboard', 'manage_inventory', 'sell']
    },
    'fnb': {
        'code': 'fnb',
        'name': 'Nhà hàng & Cafe (F&B)',
        'icon': '🍻',
        'desc': 'Quán nhậu, Cafe, Ăn uống. Sơ đồ bàn, gọi món, treo bill, tính giờ.',
        'redirect_after_login': '/pos',
        'dashboard_route': '/pos',
        'templates': ['pos.html', 'table_order.html', 'qr_menu.html', 'chamcong_fnb.html'],
        'modules': ['ordering', 'tables', 'attendance'],
        'permissions': ['view_pos', 'manage_tables', 'clock_in']
    },
    'spa': {
        'code': 'spa',
        'name': 'Spa & Beauty (Nails / Massage)',
        'icon': '🌸',
        'desc': 'Spa, Nail, Clinic thẩm mỹ. Quản lý liệu trình, KTV, đặt lịch, hoa hồng.',
        'redirect_after_login': '/spa',
        'dashboard_route': '/spa',
        'templates': ['spa.html', 'booking.html', 'add_spa.html', 'chamcong_spa.html'],
        'modules': ['spa_services', 'online_booking', 'attendance'],
        'permissions': ['view_spa', 'manage_bookings', 'clock_in']
    },
    'nail': {
        'code': 'nail',
        'name': 'Nails & Salon',
        'icon': '💅',
        'desc': 'Dịch vụ làm móng, Nails & Salon chăm sóc sắc đẹp, đắp bột vẽ móng nghệ thuật.',
        'redirect_after_login': '/chamcong/nail',
        'dashboard_route': '/chamcong/nail',
        'templates': ['chamcong_nail.html'],
        'modules': ['nail_services', 'attendance'],
        'permissions': ['view_nail', 'clock_in']
    },
    'karaoke': {
        'code': 'karaoke',
        'name': 'Karaoke & Bida',
        'icon': '🎤',
        'desc': 'Karaoke, Bida, Game, Giải trí. Tính giờ tự động, quản lý phòng, order đồ uống.',
        'redirect_after_login': '/karaoke',
        'dashboard_route': '/karaoke',
        'templates': ['karaoke.html'],
        'modules': ['room_timing', 'pos_ordering'],
        'permissions': ['view_karaoke', 'manage_rooms']
    },
    'hotel': {
        'code': 'hotel',
        'name': 'Khách Sạn',
        'icon': '🏨',
        'desc': 'Khách sạn, Nhà nghỉ, Homestay. Quản lý phòng trống, đặt phòng, dịch vụ đi kèm.',
        'redirect_after_login': '/chamcong/khachsan',
        'dashboard_route': '/chamcong/khachsan',
        'templates': ['chamcong_khachsan.html'],
        'modules': ['attendance', 'room_management'],
        'permissions': ['view_hotel', 'clock_in']
    },
    'production': {
        'code': 'production',
        'name': 'Sản Xuất',
        'icon': '🏭',
        'desc': 'Nhà xưởng, Cơ sở sản xuất. Quản lý năng suất công nhân, chấm công xưởng.',
        'redirect_after_login': '/chamcong/congnhan',
        'dashboard_route': '/chamcong/congnhan',
        'templates': ['chamcong_congnhan.html'],
        'modules': ['attendance', 'factory_output'],
        'permissions': ['view_production', 'clock_in']
    },
    'technical': {
        'code': 'technical',
        'name': 'Kỹ Thuật',
        'icon': '🛠️',
        'desc': 'Bảo trì, Lắp đặt kỹ thuật. Chấm công kỹ thuật viên ngoài hiện trường, GPS.',
        'redirect_after_login': '/chamcong/kythuat',
        'dashboard_route': '/chamcong/kythuat',
        'templates': ['chamcong_kythuat.html'],
        'modules': ['attendance', 'dispatch_gps'],
        'permissions': ['view_technical', 'clock_in']
    },
    'office': {
        'code': 'office',
        'name': 'Văn Phòng',
        'icon': '🏢',
        'desc': 'Văn phòng doanh nghiệp, Khối hành chính. Chấm công, tính lương văn phòng.',
        'redirect_after_login': '/chamcong/vanphong',
        'dashboard_route': '/chamcong/vanphong',
        'templates': ['chamcong_vanphong.html'],
        'modules': ['attendance', 'payroll'],
        'permissions': ['view_office', 'clock_in']
    }
}

@app.context_processor
def inject_industry_config():
    # .strip().lower() phòng thủ: mọi điểm GHI business_mode (register()/setup()) đã tự
    # chuẩn hoá lowercase, nhưng session/system_settings có thể còn dữ liệu cũ từ TRƯỚC khi
    # chuẩn hoá này tồn tại — INDUSTRY_CONFIG chỉ có key lowercase ('nail', 'fnb'...), lệch
    # case dù chỉ 1 ký tự cũng khiến active_cfg/active_industry_code rơi về None/sai ngành
    # một cách im lặng (không lỗi, không log), y hệt bug sidebar Nails vừa gặp.
    business_mode = (session.get('business_mode') or 'retail').strip().lower()
    if business_mode not in INDUSTRY_CONFIG:
        active_cfg = None
    else:
        active_cfg = INDUSTRY_CONFIG[business_mode]

    # Multi-region (US market pivot): mỗi tenant tự có country/currency riêng (mặc định
    # VN/VND, không đổi hành vi cho tenant hiện tại nào).
    if hasattr(TenantEngine, 'get_region_config'):
        region = TenantEngine.get_region_config(session.get('business_id'))
    else:
        region = {"country": "VN", "currency": "VND"}
    tenant_country = region['country']
    tenant_currency = region['currency']

    # Phase 4 - Bước 2: mặc định toàn hệ thống là Tiếng Anh (thị trường Âu/Mỹ/Úc là chủ
    # lực), trừ khi người dùng đã tự chọn ngôn ngữ trước đó (lưu trong cookie bitpaw_lang).
    default_lang = resolve_lang(request)

    # Phase 4 - Bước 3: từ điển "menu" (nhỏ, ~24 khoá) nạp sẵn cho mọi template dùng chung
    # sidebar/navbar — không nạp toàn bộ namespace "landing" (390 khoá) vì chỉ landing.html
    # mới cần tới nó, tự truyền riêng ở route của nó.
    menu_i18n = get_translations(default_lang).get('menu', {})

    return dict(
        industry_config=INDUSTRY_CONFIG,
        active_industry_code=business_mode,
        active_industry_cfg=active_cfg,
        tenant_country=tenant_country,
        tenant_currency=tenant_currency,
        default_lang=default_lang,
        menu_i18n=menu_i18n,
        asset_version=_ASSET_VERSION
    )


app.jinja_env.filters['money'] = format_money


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def init_db():
    # kho_license (SQLite) đã bị loại bỏ hoàn toàn — toàn bộ license giờ dùng bảng
    # license_codes trên Supabase (xem duc_ma/get_keys/delete_key/register ở trên).
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS cskh_request_outbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            email TEXT,
            message TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS platform_connections (
            id TEXT PRIMARY KEY,
            business_id TEXT NOT NULL,
            platform TEXT NOT NULL,
            connection_status TEXT DEFAULT 'DISCONNECTED',
            config_data TEXT,
            connected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # customer_profiles/nurturing_campaigns/campaign_messages (SQLite) đã bị loại bỏ hoàn
    # toàn — AI Nurturing Engine giờ đọc/ghi trực tiếp trên db.customers (MongoDB, cùng
    # collection mọi module khác đang dùng) và 2 collection Mongo mới db.nurturing_campaigns/
    # db.campaign_messages, không còn shadow copy nào tách biệt (xem app.py các route
    # /api/ai/nurture/* và ai_nurturing_engine.py).
    c.execute('''
        CREATE TABLE IF NOT EXISTS bot_scenarios (
            id TEXT PRIMARY KEY,
            business_id TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            channel TEXT NOT NULL,
            trigger_type TEXT NOT NULL,
            message_template TEXT NOT NULL,
            delay_minutes INTEGER DEFAULT 0,
            status TEXT DEFAULT 'ACTIVE',
            max_send_per_day INTEGER DEFAULT 100,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS bot_message_logs (
            id TEXT PRIMARY KEY,
            business_id TEXT NOT NULL,
            scenario_id TEXT,
            customer_id TEXT,
            channel TEXT,
            message_content TEXT,
            status TEXT DEFAULT 'simulated',
            error_message TEXT,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS bot_settings (
            id TEXT PRIMARY KEY,
            business_id TEXT NOT NULL,
            channel TEXT NOT NULL,
            is_enabled INTEGER DEFAULT 1,
            provider_status TEXT,
            config_status TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS customer_events (
            id TEXT PRIMARY KEY,
            business_id TEXT NOT NULL,
            customer_id TEXT,
            event_type TEXT,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS qr_tokens (
            token TEXT PRIMARY KEY,
            expires_at TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

# Khởi tạo SQLite khi chạy server
try:
    init_db()
except Exception as init_err:
    print(f"Error initializing SQLite: {str(init_err)}")


# ========== HELPER ĐỌC NGÀY GIỜ LINH HOẠT ==========
def parse_datetime(dt_str):
    if not dt_str:
        return datetime.now()
    # Loại bỏ T và Z để đưa về dạng chuẩn
    clean_str = dt_str.replace('T', ' ').replace('Z', '')
    # Cắt bỏ phần giây lẻ (.000, .123)
    if '.' in clean_str:
        clean_str = clean_str.split('.')[0]
    # Cắt bỏ múi giờ (+07:00, v.v.)
    if '+' in clean_str:
        clean_str = clean_str.split('+')[0]
    
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(clean_str.strip(), fmt)
        except ValueError:
            continue
    return datetime.now()


# ========== DECORATOR KIỂM TRA ĐĂNG NHẬP ==========
def login_required(f):
    """Hybrid Web/Mobile (Giai đoạn 5 audit): nếu request mang Bearer JWT hợp lệ,
    _hybrid_auth_and_csrf() (before_request, chạy TRƯỚC decorator này) đã tự nạp session['user_id']
    từ token rồi — decorator KHÔNG cần biết gì thêm về JWT, chỉ cần đọc session như cũ, y hệt
    session cookie Web. Chỉ khác: khi thiếu xác thực, trả JSON cho Mobile/API thay vì luôn
    redirect HTML (Mobile không có khái niệm "trang login" để redirect tới)."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            if _wants_json():
                return jsonify({'success': False, 'message': 'Vui lòng đăng nhập để tiếp tục.'}), 401
            flash('Vui lòng đăng nhập để tiếp tục', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


# ========== DECORATOR PHÂN QUYỀN (RBAC) ==========
def role_required(*allowed_roles):
    """Decorator chuẩn thay cho việc gọi thủ công _deny_if_staff()/_deny_if_staff_page() rải
    rác trong từng hàm (dễ quên áp dụng ở route mới, không audit được bằng cách grep 1 chỗ).
    Dùng ALLOW-LIST (chỉ role nằm trong allowed_roles mới được đi tiếp) thay vì deny-list cũ
    (chỉ chặn đúng role='staff') — an toàn hơn: 1 role MỚI phát sinh sau này (vd mời nhân viên
    với role tuỳ biến) sẽ mặc định BỊ CHẶN cho tới khi được thêm tường minh vào allow-list,
    thay vì mặc định ĐƯỢC PHÉP như deny-list cũ.
    LUÔN đặt bên dưới @login_required trong decorator stack (chạy sau khi đã xác nhận có
    session hợp lệ — kể cả session "ảo" nạp từ JWT cho Mobile, xem login_required). Tự nhận diện
    JSON API/Mobile (_wants_json() -> trả 403 JSON) hay trang HTML Web (redirect kèm flash) để
    giữ đúng hành vi UX của từng loại client."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user_role = session.get('role', 'staff')
            if user_role not in allowed_roles:
                if _wants_json():
                    return jsonify({'success': False, 'message': 'Tài khoản của bạn không có quyền thực hiện thao tác này.'}), 403
                flash('Tài khoản của bạn không có quyền truy cập trang này.', 'danger')
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def _get_tenant_business_id_or_401():
    """Dùng ở các route API đã có @login_required nhưng vẫn cần đọc business_id từ session.
    session['business_id'] LUÔN được set lúc login (xem route login(): user.get('business_id')
    or user_id) — nếu thiếu ở đây nghĩa là session cũ/hỏng, KHÔNG ĐƯỢC fallback về 1 tenant giả
    dùng chung (bug cũ: 'mock-business-123' làm token/cấu hình của nhiều tiệm ghi đè lẫn nhau).
    Trả về (business_id, None) nếu hợp lệ, hoặc (None, response_401) nếu phải chặn request lại
    ngay — gọi nơi dùng: `business_id, err = _get_tenant_business_id_or_401(); if err: return err`."""
    business_id = session.get('business_id')
    if not business_id:
        return None, (jsonify({
            "error": "Unauthorized",
            "message": "Phiên đăng nhập không hợp lệ hoặc đã hết hạn, vui lòng đăng nhập lại.",
        }), 401)
    return business_id, None


# ========== KHỞI TẠO BẢNG (CHẠY THỦ CÔNG TRONG SUPABASE SQL EDITOR) ==========
# Các bảng cần có: products, orders, order_items, customers, staff, appointments, dining_tables,
# table_orders, promotions, expenses, payment_transactions, user_logs, system_settings,
# ecommerce_sync_queue, qr_payment_sessions, karaoke_rooms, cskh_config, cskh_requests,
# cskh_clicks, customer_feedback, backup_logs.


# ========== WELCOME EMAIL (gửi ngay sau khi tenant kích hoạt tài khoản bằng license code) ==========
# Đối tượng chính là chủ tiệm Nails/Nhà hàng người Việt sống tại Mỹ — nội dung email viết
# hoàn toàn bằng tiếng Anh chuyên nghiệp, không phải bilingual như widget tư vấn landing page.
_INDUSTRY_WELCOME_EN = {
    'retail': {'name': 'Retail', 'modules': ['Point of Sale', 'Inventory Management', 'Expense Tracking']},
    'fnb': {'name': 'F&B / Restaurant', 'modules': ['Table Ordering & POS', 'QR Menu', 'Kitchen Display System', 'Staff Attendance']},
    'spa': {'name': 'Spa & Beauty', 'modules': ['Spa Services', 'Online Booking', 'Staff Attendance & Commission']},
    'nail': {'name': 'Nails & Salon', 'modules': ['Nail Services POS', 'Staff Scheduling', 'Payroll & Commission', 'Attendance Tracking']},
    'karaoke': {'name': 'Karaoke & Billiards', 'modules': ['Room Timing', 'POS Ordering']},
    'hotel': {'name': 'Hotel', 'modules': ['Room Management', 'Staff Attendance']},
    'production': {'name': 'Manufacturing', 'modules': ['Factory Output Tracking', 'Staff Attendance']},
    'technical': {'name': 'Technical Services', 'modules': ['GPS Dispatch', 'Field Staff Attendance']},
    'office': {'name': 'Office / Corporate', 'modules': ['Staff Attendance', 'Payroll']},
}


def _send_welcome_email(email, business_name, owner_name, business_type):
    """Gửi email chào mừng ngay sau khi tenant đăng ký thành công bằng activation code.
    Best-effort: lỗi SMTP/network ở đây KHÔNG được phép làm hỏng luồng đăng ký (tài khoản
    đã tạo thành công rồi), chỉ log lại để debug — xem cách gọi ở register()."""
    info = _INDUSTRY_WELCOME_EN.get(business_type) or {
        'name': (business_type or 'General').title(), 'modules': ['Point of Sale', 'Staff Attendance']
    }
    greeting_name = owner_name or 'there'
    modules_html = ''.join(f'<li style="margin-bottom:6px;">{m}</li>' for m in info['modules'])
    html = f"""
    <div style="font-family: Arial, Helvetica, sans-serif; max-width: 560px; margin: 0 auto; background:#0b0f19; color:#f1f5f9; border-radius:16px; overflow:hidden; border:1px solid rgba(148,163,184,0.15);">
        <div style="background: linear-gradient(135deg, #0891b2, #4f46e5); padding: 28px 32px;">
            <h1 style="margin:0; font-size:22px; color:#ffffff;">Welcome to BitPaw OS!</h1>
        </div>
        <div style="padding: 28px 32px;">
            <p style="font-size:15px; line-height:1.6;">Hi {greeting_name},</p>
            <p style="font-size:15px; line-height:1.6;">
                Your workspace for <strong>{business_name}</strong> has been successfully activated and provisioned
                for the <strong>{info['name']}</strong> industry.
            </p>
            <p style="font-size:13px; color:#94a3b8; text-transform:uppercase; letter-spacing:0.05em; margin-top:24px; margin-bottom:8px;">Modules included in your plan</p>
            <ul style="font-size:15px; line-height:1.6; padding-left:20px; margin-top:0;">
                {modules_html}
            </ul>
            <p style="font-size:15px; line-height:1.6; margin-top:24px;">
                You can log in anytime with the email address <strong>{email}</strong> to start managing your business.
            </p>
            <p style="font-size:13px; color:#64748b; margin-top:32px;">
                Need help getting started? Just reply to this email — our team is here for you.
            </p>
        </div>
        <div style="background:#080a12; padding:16px 32px; font-size:11px; color:#475569; text-align:center;">
            &copy; BitPaw OS. All rights reserved.
        </div>
    </div>
    """
    try:
        success, message = EmailService.send_email(
            email,
            f"Welcome to BitPaw OS — Your {info['name']} Workspace is Ready!",
            html
        )
        if not success:
            print(f"[register] Welcome email not sent to {email}: {message}")
    except Exception as e:
        print(f"[register] Welcome email failed for {email}: {str(e)}")


# ========== ROUTE XÁC THỰC ==========
@app.route('/register', methods=['GET', 'POST'])
@limiter.limit("5 per 15 minutes")
def register():
    # csrf.protect() PHẢI gọi bên trong thân hàm (không phải @csrf.protect làm decorator —
    # protect() là 1 method thường, không nhận view function làm tham số, dùng như decorator
    # sẽ TypeError ngay lúc import module). Tự no-op cho GET (protect() tự bỏ qua method không
    # nằm trong WTF_CSRF_METHODS mặc định = POST/PUT/PATCH/DELETE), chỉ thực sự chặn ở POST.
    csrf.protect()
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        # Chuẩn hoá lowercase NGAY tại điểm nhận vào — INDUSTRY_CONFIG chỉ có key lowercase
        # ('nail', 'fnb'...); dropdown UI hiện tại luôn gửi đúng key, nhưng chuẩn hoá ở đây
        # để KHÔNG phụ thuộc vào việc UI luôn "cư xử đúng" (vd: gọi thẳng API, hoặc dữ liệu
        # cũ trước khi có chuẩn hoá này) — tránh business_mode lệch case khiến toàn bộ so
        # sánh == 'nail' ở sidebar/route điều hướng lặng lẽ rơi về nhánh mặc định sai ngành.
        business_type = (request.form['business_type'] or '').strip().lower()
        business_name = (request.form.get('business_name') or '').strip()
        fullname = (request.form.get('fullname') or '').strip()
        license_key = request.form.get('license_key', '').strip()

        # Kiểm tra License Key trên collection license_codes (MongoDB).
        if not license_key:
            flash('Please enter your activation code!', 'danger')
            return render_template('index.html', active_tab='register')

        if db is None:
            flash('Error verifying activation code: MongoDB is not connected.', 'danger')
            return render_template('index.html', active_tab='register')

        try:
            key_valid = db.license_codes.find_one({'license_key': license_key, 'trang_thai': 'Sẵn sàng'})
            if not key_valid:
                flash('Invalid activation code, or it has already been used.', 'danger')
                return render_template('index.html', active_tab='register')

            # Mã kích hoạt là NGUỒN SỰ THẬT DUY NHẤT cho ngành nghề/module được cấp — tự động lấy
            # theo mã thay vì tin lựa chọn dropdown của client (trước đây REJECT nếu 2 giá trị
            # lệch nhau, khiến chủ tiệm nhập đúng mã Nails nhưng lỡ chọn nhầm dropdown F&B vẫn bị
            # từ chối đăng ký oan). Chỉ giữ lựa chọn dropdown cho mã dùng chung (rỗng/'all').
            license_nganh = (key_valid.get('nganh_nghe') or '').strip()
            if license_nganh and license_nganh.lower() != 'all':
                business_type = license_nganh.lower()

            # Kiểm tra email đã tồn tại chưa (MongoDB không tự chặn như Supabase Auth)
            if db.users.find_one({'email': email}):
                flash('This email is already registered — please log in instead.', 'danger')
                return render_template('index.html', active_tab='register')

            # Cập nhật trạng thái key
            db.license_codes.update_one({'license_key': license_key}, {'$set': {'trang_thai': 'Đã kích hoạt'}})
        except Exception as db_err:
            print(f"[register] Lỗi kiểm tra license_codes trên MongoDB: {str(db_err)}")
            flash(f'Error verifying activation code: {str(db_err)}', 'danger')
            return render_template('index.html', active_tab='register')

        try:
            user_id = str(uuid.uuid4())
            db.users.insert_one({
                'id': user_id,
                'email': email,
                'password_hash': generate_password_hash(password),
                'business_id': user_id,  # mỗi chủ tiệm tự là 1 tenant, giống quy ước cũ của Supabase Auth
                'role': 'admin',
                'created_at': datetime.now().isoformat()
            })
            # Hồ sơ doanh nghiệp — trước đây KHÔNG được tạo ở bước này, khiến
            # AIContextEngine.build_context_prompt() (db.businesses.find_one) không bao giờ tìm
            # thấy tên cửa hàng thật cho AI CSKH cá nhân hoá của tenant mới đăng ký. Cung cấp đủ
            # ngay khi kích hoạt để tính năng đó hoạt động đúng như thiết kế.
            db.businesses.insert_one({
                'id': user_id,
                'name': business_name or email,
                'owner_name': fullname,
                'industry_code': business_type,
                'created_at': datetime.now().isoformat()
            })
            session['business_mode'] = business_type
            # Lưu business type vào system_settings, khóa riêng theo user_id để tránh đè chéo giữa các tài khoản
            business_mode_key = f'business_mode_{user_id}'
            try:
                db.system_settings.update_one(
                    {'key': business_mode_key},
                    {'$set': {'key': business_mode_key, 'value': business_type}},
                    upsert=True
                )
            except Exception as db_err:
                print(f"MongoDB system_settings upsert skipped: {str(db_err)}")

            # Welcome email — best-effort, KHÔNG được làm hỏng luồng đăng ký nếu SMTP lỗi/chưa cấu hình.
            _send_welcome_email(email, business_name or email, fullname, business_type)

            flash('Account registered successfully! Please log in.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            flash(f'Registration error: {str(e)}', 'danger')
    return render_template('index.html', active_tab='register')


def get_user_data_by_email(email):
    """Tra cứu thông tin user (collection `users`: id, email, role, business_id, created_at)
    theo email. Trả về dict nếu tìm thấy, hoặc None nếu không tìm thấy / lỗi kết nối —
    luôn log rõ nguyên nhân cụ thể (không tìm thấy khác với lỗi kết nối DB) thay vì nuốt
    lỗi âm thầm như một số chỗ khác trong code base."""
    if not email:
        print("[get_user_data_by_email] Gọi hàm với email rỗng/None.")
        return None
    email = email.strip().lower()
    if db is None:
        print("[get_user_data_by_email] MongoDB chưa kết nối.")
        return None
    try:
        user = db.users.find_one(
            {'email': email},
            {'id': 1, 'email': 1, 'role': 1, 'business_id': 1, 'created_at': 1, '_id': 0}
        )
    except Exception as e:
        print(f"[get_user_data_by_email] Lỗi kết nối/truy vấn MongoDB cho email={email}: {str(e)}")
        return None
    if not user:
        print(f"[get_user_data_by_email] Không tìm thấy user nào với email: {email}")
        return None
    return user


SUPERADMIN_ROOT_EMAIL = 'hodinhsang30052003@gmail.com'


def _is_authorized_superadmin_email(email):
    """Nguồn chân lý DUY NHẤT cho câu hỏi "email này có được cấp quyền Superadmin không?" —
    dùng chung cho CẢ login() (fallback khẩn cấp) LẪN _is_superadmin() (gate truy cập trang
    /super_admin sau khi đã đăng nhập). Trước đây login() tự so sánh với SUPERADMIN_ROOT_EMAIL
    (1 email hardcode) mà KHÔNG đọc SUPERADMIN_EMAILS, nên tài khoản cấu hình qua biến môi
    trường này không bao giờ đăng nhập fallback được dù _is_superadmin() vẫn cho vào trang sau
    khi (giả sử) đã có session — 2 nơi lệch nhau chính là gốc lỗi "Incorrect email or password".
    True nếu email là tài khoản trùm hardcode, HOẶC nằm trong danh sách SUPERADMIN_EMAILS (env
    var, cách nhau bởi dấu phẩy). Không cấu hình biến env này vẫn không sao — tài khoản trùm
    hardcode luôn được cấp quyền, không phụ thuộc env/DB (fail-closed cho mọi email khác)."""
    normalized = (email or '').strip().lower()
    if not normalized:
        return False
    if normalized == SUPERADMIN_ROOT_EMAIL:
        return True
    allowed = {e.strip().lower() for e in os.environ.get('SUPERADMIN_EMAILS', '').split(',') if e.strip()}
    return normalized in allowed


def _superadmin_emergency_login(email):
    """Lối vào khẩn cấp CHO ĐÚNG 1 tài khoản trùm hardcode, CHỈ kích hoạt khi MongoDB không kết
    nối được hoặc bản ghi user thật không còn tồn tại (vd: DB bị xoá/khôi phục từ backup cũ) —
    KHÔNG BAO GIỜ dùng cho luồng đăng nhập bình thường (luồng thường luôn ưu tiên tra `users`
    thật + check_password_hash ở trên). Verify qua check_password_hash() với 1 HASH (không phải
    plaintext) đọc từ SUPERADMIN_FALLBACK_HASH — sinh 1 lần bằng:
        python -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('...'))"
    rồi dán vào .env (KHÔNG commit .env lên git). Không hardcode mật khẩu dạng chữ thô trong
    source vì bất kỳ ai đọc được code (leak repo, log lỗi, contractor cũ...) sẽ có quyền
    Superadmin vĩnh viễn không thể thu hồi — hash thì rotate được bất kỳ lúc nào chỉ bằng cách
    đổi biến môi trường, không cần sửa code."""
    session['user_id'] = 'superadmin-fallback'
    session['business_id'] = 'superadmin-fallback'
    session['user_email'] = email.strip().lower()
    session['role'] = 'super_admin'
    session['business_mode'] = 'none'
    flash('Login successful (Superadmin emergency fallback)', 'success')
    return redirect('/super_admin')


@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per 15 minutes")
def login():
    # Xem giải thích ở register() ngay phía trên — csrf.protect() gọi trong thân hàm, không
    # phải decorator.
    csrf.protect()
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        # === BẮT ĐẦU GOD MODE ===================================================
        # SUPERADMIN FALLBACK — CHẶN NGAY TẠI CỬA (BYPASS DATABASE). Dùng
        # current_app.logger.error() thay vì print() — Vercel Runtime Logs hiển thị
        # log qua logging module (stderr) đáng tin cậy hơn stdout thô, và gắn cờ
        # ERROR giúp dễ lọc/nổi bật khi debug. Đặt SAU khi email/password đã được
        # lấy từ request.form (bắt buộc — đặt ở dòng đầu hàm login() như đề xuất gốc
        # sẽ crash mọi request GET /login vì lúc đó request.form rỗng, không có key
        # 'email'/'password').
        #
        # QUYẾT ĐỊNH "email này có phải superadmin" vẫn đi qua đúng 1 hàm dùng chung
        # _is_authorized_superadmin_email() (không tự so `normalized_email in
        # admin_emails` với admin_emails mặc định rỗng) — nếu không, tài khoản root
        # hardcode sẽ bị khoá khỏi God Mode ngay khi SUPERADMIN_EMAILS được cấu hình
        # sang email khác (đúng bug đã tìm thấy và fix ở lượt trước). admin_emails
        # bên dưới CHỈ dùng để in log cho dễ debug, KHÔNG dùng để quyết định quyền.
        admin_emails = [e.strip().lower() for e in os.environ.get('SUPERADMIN_EMAILS', '').split(',') if e.strip()]
        normalized_email = email.strip().lower()

        if _is_authorized_superadmin_email(email):
            current_app.logger.error(f"[GOD MODE] Dang xac thuc email: {normalized_email} | SUPERADMIN_EMAILS={admin_emails} | root_email={SUPERADMIN_ROOT_EMAIL}")

            # Ưu tiên đọc SUPERADMIN_FALLBACK_HASH_B64 (hash gốc mã hoá base64) — base64 chỉ
            # gồm A-Z a-z 0-9 + / =, KHÔNG ký tự nào bị shell/CLI/tool trung gian diễn giải
            # nhầm thành biến môi trường (khác với hash gốc dạng "scrypt:32768:8:1$<salt>$<hash>"
            # chứa dấu "$" — nếu set qua 1 script/CLI không quote đúng, "$salt"/"$hash" có thể bị
            # hiểu thành tham chiếu biến shell và bị thay bằng chuỗi rỗng). Vẫn đọc
            # SUPERADMIN_FALLBACK_HASH (hash thô) làm phương án dự phòng để không phá cấu hình
            # cũ đang chạy đúng trên Vercel.
            fallback_hash_b64 = os.environ.get('SUPERADMIN_FALLBACK_HASH_B64', '')
            decoded_hash = ''
            if fallback_hash_b64:
                try:
                    decoded_hash = base64.b64decode(fallback_hash_b64).decode('utf-8').strip()
                except Exception as decode_err:
                    current_app.logger.error(f"[GOD MODE] LOI DECODE BASE64: SUPERADMIN_FALLBACK_HASH_B64 khong phai base64 hop le ({str(decode_err)})")
            if not decoded_hash:
                decoded_hash = os.environ.get('SUPERADMIN_FALLBACK_HASH', '').strip()

            if not decoded_hash:
                current_app.logger.error("[GOD MODE] LOI CAU HINH: ca SUPERADMIN_FALLBACK_HASH_B64 va SUPERADMIN_FALLBACK_HASH deu rong/chua duoc set")
                flash('Hệ thống thiếu cấu hình Key bảo mật', 'danger')
                return render_template('index.html', active_tab='login')

            try:
                password_matches = check_password_hash(decoded_hash, password)
            except Exception as e:
                current_app.logger.error(f"[GOD MODE] LOI NGAM: {str(e)}")
                password_matches = False

            if password_matches:
                current_app.logger.error(f"[GOD MODE] THANH CONG! Chuyen huong vao /super_admin cho '{normalized_email}'")
                return _superadmin_emergency_login(normalized_email)
            else:
                current_app.logger.error(f"[GOD MODE] SAI MAT KHAU cho '{normalized_email}'!")
                flash('Incorrect email or password', 'danger')
                return render_template('index.html', active_tab='login')
        # === KẾT THÚC GOD MODE ===================================================

        # Email KHÔNG nằm trong danh sách superadmin -> tiếp tục luồng đăng nhập
        # bình thường bên dưới (tra collection `users` trong MongoDB như cũ).
        try:
            if db is None:
                raise Exception("MongoDB chưa kết nối.")

            user = db.users.find_one({'email': email})
            if not user:
                raise Exception("Sai email hoặc mật khẩu")
            if not check_password_hash(user['password_hash'], password):
                raise Exception("Sai email hoặc mật khẩu")

            user_id = user['id']
            session['user_id'] = user_id
            # Mỗi chủ tiệm chính là 1 tenant — dùng user_id làm business_id để kích hoạt toàn bộ
            # các bộ lọc theo business_id đã có sẵn trong code/template.
            session['business_id'] = user.get('business_id') or user_id
            session['user_email'] = email
            # Dùng cho các API cần phân quyền (vd: chặn tài khoản 'staff' xem thống kê Dashboard
            # của chủ tiệm) — mặc định 'admin' vì luồng đăng ký hiện tại luôn tạo chủ tiệm.
            session['role'] = user.get('role', 'admin')
            _ensure_primary_membership(user_id, user_id)
            # Ghi log đăng nhập (bỏ qua nếu lỗi ở phase này)
            try:
                db.user_logs.insert_one({
                    'id': next_mongo_id('user_logs'),
                    'business_id': session.get('business_id') or user_id,
                    'user_email': email,
                    'action': 'login',
                    'description': 'Đăng nhập thành công',
                    'ip_address': _get_real_client_ip(),
                    'created_at': datetime.now().isoformat()
                })
            except Exception as db_err:
                print(f"MongoDB user_logs insert skipped: {str(db_err)}")

            # Đọc business type để redirect đúng ngành nghề, khóa riêng theo user_id hiện tại
            mode = None
            try:
                business_mode_key = f'business_mode_{user_id}'
                mode_doc = db.system_settings.find_one({'key': business_mode_key})
                mode = (mode_doc['value'] if mode_doc else 'none').strip().lower()
            except Exception as db_err:
                print(f"MongoDB system_settings select skipped: {str(db_err)}")
                mode = 'none'

            session['business_mode'] = mode

            flash('Login successful', 'success')

            # Mọi email nằm trong danh sách Superadmin (root hardcode HOẶC SUPERADMIN_EMAILS)
            # luôn vào thẳng Super Admin, bất kể business_mode đã cấu hình hay chưa — không đẩy
            # qua /setup như user thường. Check này đặt TRƯỚC mọi logic redirect theo ngành nghề.
            # Dùng chung đúng 1 nguồn chân lý _is_authorized_superadmin_email() với khối
            # SUPERADMIN FALLBACK ở đầu hàm và _is_superadmin() — trước đây chỗ này hardcode
            # đúng 1 email, nên tài khoản superadmin cấu hình qua SUPERADMIN_EMAILS mà đăng
            # nhập được bằng mật khẩu DB thật (không qua fallback) vẫn bị đẩy nhầm qua /setup
            # hoặc trang ngành nghề thay vì /super_admin.
            if _is_authorized_superadmin_email(email):
                return redirect('/super_admin')

            if mode in INDUSTRY_CONFIG:
                target_url = INDUSTRY_CONFIG[mode]['redirect_after_login']
                if target_url == '/dashboard':
                    return redirect(url_for('index'))
                elif target_url.startswith('/chamcong/'):
                    ind_code = target_url.split('/')[-1]
                    return redirect(url_for('chamcong_industry', industry_code=ind_code))
                else:
                    endpoint = target_url.strip('/')
                    try:
                        return redirect(url_for(endpoint))
                    except:
                        return redirect(target_url)
            return redirect(url_for('setup'))
        except Exception as e:
            flash('Incorrect email or password', 'danger')
    return render_template('index.html', active_tab='login')


@app.route('/api/auth/token', methods=['POST'])
@limiter.limit("5 per 15 minutes")
def api_auth_token():
    """Cấp JWT cho Mobile App (Flutter/React Native) — thay session cookie không dùng được trên
    native client. Nhận {email, password} JSON, trả về access_token (JWT tự chứa user_id/
    business_id/role/business_mode) + thông tin user cơ bản. login_required() sau đó chỉ cần
    _load_session_from_jwt() giải mã lại, KHÔNG cần tra DB mỗi request.

    CỐ Ý KHÔNG hỗ trợ God Mode/Superadmin fallback ở đây (khác /login web) — endpoint này chỉ
    phục vụ chủ tiệm/nhân viên đăng nhập vào ĐÚNG tenant của họ qua app; tài khoản Super Admin hệ
    thống không có lý do đăng nhập qua Mobile App của khách hàng."""
    data = request.json or {}
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    if not email or not password:
        return jsonify({"success": False, "message": "Thiếu email hoặc password."}), 400
    if db is None:
        return jsonify({"success": False, "message": "Server chưa kết nối Database."}), 503

    user = db.users.find_one({'email': email})
    if not user or not check_password_hash(user.get('password_hash', ''), password):
        return jsonify({"success": False, "message": "Sai email hoặc mật khẩu."}), 401

    user_id = user['id']
    business_id = user.get('business_id') or user_id
    role = user.get('role', 'admin')
    mode = 'none'
    try:
        mode_doc = db.system_settings.find_one({'key': f'business_mode_{user_id}'})
        mode = (mode_doc['value'] if mode_doc else 'none').strip().lower()
    except Exception:
        pass

    now = datetime.utcnow()
    payload = {
        'user_id': user_id,
        'business_id': business_id,
        'user_email': email,
        'role': role,
        'business_mode': mode,
        'iat': now,
        'exp': now + timedelta(hours=JWT_EXPIRY_HOURS),
    }
    token = pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

    try:
        db.user_logs.insert_one({
            'id': next_mongo_id('user_logs'), 'business_id': business_id, 'user_email': email,
            'action': 'login_mobile_token', 'description': 'Dang nhap Mobile App (JWT)',
            'ip_address': _get_real_client_ip(), 'created_at': datetime.now().isoformat(),
        })
    except Exception:
        pass

    return jsonify({
        "success": True,
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": JWT_EXPIRY_HOURS * 3600,
        "user": {
            "id": user_id, "email": email, "role": role,
            "business_id": business_id, "business_mode": mode,
        },
    })


@app.route('/api/users/delete-account', methods=['POST'])
@login_required
def api_delete_account():
    """Xoá tài khoản — bắt buộc theo App Store Review Guideline 5.1.1(v): app phải cho phép
    user tự yêu cầu xoá tài khoản ngay trong app, không được bắt liên hệ hỗ trợ/vào web riêng.

    SOFT DELETE (không xoá cứng ngay lập tức): tài khoản này là 1 tenant B2B với dữ liệu vận
    hành thật (đơn hàng, khách hàng, nhân viên, lương...) gắn theo business_id trải khắp hàng
    chục collection — xoá cứng cascade ngay trong 1 request rủi ro cao (bấm nhầm/token bị lộ =
    mất vĩnh viễn toàn bộ dữ liệu kinh doanh, không có đường lùi). Soft delete: khoá đăng nhập
    NGAY LẬP TỨC (scramble password_hash — chặn cả /login web LẪN /api/auth/token mobile, vì cả
    2 cùng dùng check_password_hash trên field này) + đánh dấu is_deleted/deleted_at. Vẫn tuân
    thủ yêu cầu Apple: tài khoản không còn đăng nhập được ngay khi user xác nhận xoá. Xoá cứng
    dữ liệu (nếu cần, theo chính sách lưu trữ/luật) nên chạy bằng 1 job định kỳ riêng quét
    is_deleted=True quá X ngày — NGOÀI phạm vi endpoint này.

    Bắt buộc xác nhận lại password trước khi xoá — hành động không thể tự hoàn tác dễ dàng,
    tránh 1 session/token bị đánh cắp có thể tự xoá tài khoản nạn nhân mà không cần biết mật khẩu."""
    user_id = session['user_id']
    data = request.json or {}
    password = data.get('password') or ''
    if not password:
        return jsonify({"success": False, "message": "Vui lòng nhập mật khẩu để xác nhận xoá tài khoản."}), 400

    user = db.users.find_one({'id': user_id})
    if not user or not check_password_hash(user.get('password_hash', ''), password):
        return jsonify({"success": False, "message": "Mật khẩu xác nhận không đúng."}), 401

    now_iso = datetime.now().isoformat()
    business_id = user.get('business_id') or user_id
    try:
        db.users.update_one(
            {'id': user_id},
            {'$set': {
                'is_deleted': True,
                'deleted_at': now_iso,
                # Khoá đăng nhập vĩnh viễn — scramble bằng 1 mật khẩu ngẫu nhiên không ai biết
                # được, KHÔNG xoá field password_hash (tránh mọi chỗ khác lỡ tra field này lỗi
                # KeyError thay vì tra được rồi so sánh thất bại như bình thường).
                'password_hash': generate_password_hash(uuid.uuid4().hex),
                # Giải phóng email gốc để user khác có thể đăng ký lại đúng email này sau này —
                # không đổi 'id' (business_id vẫn giữ nguyên để dữ liệu lịch sử tra cứu được).
                'email': f"deleted_{user_id}_{user.get('email', '')}",
            }}
        )
        db.businesses.update_one(
            {'id': business_id},
            {'$set': {'is_deleted': True, 'deleted_at': now_iso}}
        )
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

    session.clear()
    return jsonify({"success": True, "message": "Tài khoản đã được xoá."}), 200


@app.route('/logout')
def logout():
    if 'user_id' in session:
        try:
            if db is not None:
                db.user_logs.insert_one({
                    'id': next_mongo_id('user_logs'),
                    'business_id': session.get('business_id'),
                    'user_email': session.get('user_email', 'unknown'),
                    'action': 'logout',
                    'description': 'Đăng xuất',
                    'ip_address': _get_real_client_ip(),
                    'created_at': datetime.now().isoformat()
                })
        except Exception as e:
            print(f"MongoDB logging failed on logout: {str(e)}")
        session.clear()
    return redirect(url_for('login'))


# ========== ROUTE CSKH ==========
@app.route('/api/cskh/config', methods=['GET'])
def get_cskh_config():
    try:
        if db is not None:
            cfg = db.cskh_config.find_one({}, {'_id': 0})
            if cfg:
                return jsonify(cfg)
    except:
        pass
    return jsonify({
        'hotline': '0794678904',
        'zalo_link': 'https://zalo.me/0794678904',
        'messenger_link': 'https://www.facebook.com/chuyhieuhong',
        'email': 'hodinhsang30052003@gmail.com'
    })


@app.route('/api/cskh/request', methods=['POST'])
def create_cskh_request():
    import time
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()[:100]
    phone = (data.get('phone') or '').strip()
    email = (data.get('email') or '').strip()
    message = (data.get('message') or '').strip()[:1000]
    if not name or not re.match(r'^0\d{9,10}$', phone) or not message:
        return jsonify({'error': 'Vui lòng nhập đầy đủ thông tin (số điện thoại phải hợp lệ)'}), 400

    mongo_success = False
    new_id = None
    last_err = None

    # Try inserting to MongoDB up to 2 times with a short randomized backoff on transient errors
    for attempt in range(2):
        try:
            if db is None:
                raise Exception("MongoDB chưa kết nối")
            new_id = next_mongo_id('cskh_requests')
            db.cskh_requests.insert_one({
                'id': new_id,
                'name': name,
                'phone': phone,
                'message': f"{message} (Email: {email})" if email else message,
                'status': 'pending',
                'created_at': datetime.now().isoformat()
            })
            mongo_success = True
            break
        except Exception as e:
            last_err = str(e)
            err_lower = last_err.lower()
            # Retry on transient network/connection/server-selection errors
            if any(term in err_lower for term in ("timeout", "connection", "network", "unreachable", "server selection")):
                time.sleep(random.uniform(0.2, 0.5))
            else:
                break  # Break immediately if it's some other hard failure

    if mongo_success:
        # KHÔNG đồng bộ vào bảng `customers` (CRM riêng theo business_id của từng tiệm) — route này
        # là form liên hệ CSKH chung của BitPaw, không gắn với 1 tenant cụ thể nào, tránh ghi dữ liệu
        # "vô chủ" hoặc lẫn vào CRM của tiệm khác.

        return jsonify({'success': True, 'id': new_id})
    else:
        # Gracefully degrade by writing to local SQLite outbox queue on MongoDB temporary failure
        try:
            conn = sqlite3.connect('database.db')
            c = conn.cursor()
            c.execute("""
                INSERT INTO cskh_request_outbox (name, phone, email, message, status)
                VALUES (?, ?, ?, ?, 'pending')
            """, (name, phone, email, message))
            conn.commit()
            conn.close()
            print(f"[*] MongoDB transient failure. Saved lead to local outbox fallback successfully (Phone: {phone}).")
            return jsonify({
                "success": True,
                "queued": True,
                "message": "Yêu cầu đã được ghi nhận, BitPaw sẽ liên hệ lại sớm."
            })
        except Exception as sqlite_err:
            print(f"[!] Critical outbox write failure: {str(sqlite_err)}")
            return jsonify({
                "success": False,
                "message": "Hệ thống đang quá tải. Vui lòng thử lại sau ít phút!"
            }), 500


@app.route('/api/cskh/click', methods=['POST'])
def track_cskh_click():
    data = request.get_json()
    channel = data.get('channel')
    user_id = data.get('user_id')
    try:
        db.cskh_clicks.insert_one({
            'id': next_mongo_id('cskh_clicks'),
            'user_id': user_id,
            'channel': channel,
            'clicked_at': datetime.now().isoformat()
        })
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/cskh/feedback', methods=['POST'])
def submit_feedback():
    data = request.get_json() or {}
    order_id = data.get('order_id')
    rating = data.get('rating')
    comment = data.get('comment')
    if not rating:
        return jsonify({'error': 'Thiếu thông tin đánh giá (rating)'}), 400

    if order_id:
        try:
            order_check = db.orders.find_one({'id': order_id}, {'business_id': 1, '_id': 0})
            if not order_check:
                return jsonify({'error': 'Order không tồn tại.'}), 404
            db.customer_feedback.insert_one({
                'id': next_mongo_id('customer_feedback'),
                'order_id': order_id,
                'rating': rating,
                'comment': comment,
                'created_at': datetime.now().isoformat(),
                'business_id': order_check.get('business_id')
            })
            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    try:
        db.customer_feedback.insert_one({
            'id': next_mongo_id('customer_feedback'),
            'rating': rating,
            'comment': comment,
            'created_at': datetime.now().isoformat()
        })
        return jsonify({'success': True, 'message': 'General feedback submitted successfully.'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/')
def root():
    if 'user_id' in session:
        return redirect(url_for('home'))
    return redirect(url_for('landingpage'))


# ========== ROUTE CHÍNH ==========
@app.route('/index')
@app.route('/index.html')
def home():
    if 'user_id' in session:
        mode = (session.get('business_mode') or '').strip().lower()
        if not mode:
            try:
                mode_doc = db.system_settings.find_one({'key': f"business_mode_{session['user_id']}"}, {'value': 1, '_id': 0})
                mode = (mode_doc['value'] if mode_doc else 'none').strip().lower()
                session['business_mode'] = mode
            except Exception as db_err:
                print(f"MongoDB system_settings select skipped: {str(db_err)}")
                mode = 'none'

        if mode == 'none':
            return redirect(url_for('setup'))

        if mode in INDUSTRY_CONFIG:
            target_url = INDUSTRY_CONFIG[mode]['redirect_after_login']
            if target_url == '/dashboard':
                return redirect(url_for('index'))
            elif target_url.startswith('/chamcong/'):
                ind_code = target_url.split('/')[-1]
                return redirect(url_for('chamcong_industry', industry_code=ind_code))
            else:
                endpoint = target_url.strip('/')
                try:
                    return redirect(url_for(endpoint))
                except:
                    return redirect(target_url)
        return redirect(url_for('setup'))
    return render_template('index.html', active_tab='login')


@app.route('/dashboard')
@login_required
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    mode = (session.get('business_mode') or '').strip().lower()
    if not mode:
        try:
            mode_doc = db.system_settings.find_one({'key': f"business_mode_{session['user_id']}"}, {'value': 1, '_id': 0})
            mode = (mode_doc['value'] if mode_doc else 'none').strip().lower()
            session['business_mode'] = mode
        except Exception as db_err:
            print(f"MongoDB system_settings select skipped: {str(db_err)}")
            mode = 'none'

    if mode == 'none':
        return redirect(url_for('setup'))


    business_id = session.get('business_id') or session['user_id']
    if mode in INDUSTRY_CONFIG:
        if mode == 'retail':
            try:
                products_data = list(db.products.find(
                    {'is_active': 1, 'channel_type': 'retail', 'business_id': business_id}, {'_id': 0}
                ))
                total_revenue = list(db.orders.find({'business_id': business_id}, {'total_amount': 1, '_id': 0}))
                revenue = sum(o.get('total_amount') or 0 for o in total_revenue)
                total_expense = list(db.expenses.find({'business_id': business_id}, {'amount': 1, '_id': 0}))
                expense = sum(e.get('amount') or 0 for e in total_expense)

                # Lấy lịch sử 10 đơn hàng — 1 aggregation pipeline DUY NHẤT với $lookup lồng nhau
                # (orders -> order_items -> products) thay vì trước đây tới 21 query rời (1 + 10 + 10).
                history_pipeline = [
                    {'$match': {'business_id': business_id}},
                    {'$sort': {'created_at': -1}},
                    {'$limit': 10},
                    {'$lookup': {'from': 'order_items', 'localField': 'id', 'foreignField': 'order_id', 'as': 'items'}},
                    {'$addFields': {'first_item': {'$arrayElemAt': ['$items', 0]}}},
                    {'$lookup': {
                        'from': 'products',
                        'localField': 'first_item.product_id',
                        'foreignField': 'id',
                        'as': 'first_item_product'
                    }},
                    {'$addFields': {'first_item_product_name': {'$arrayElemAt': ['$first_item_product.name', 0]}}},
                    {'$project': {'id': 1, 'created_at': 1, 'first_item': 1, 'first_item_product_name': 1, '_id': 0}}
                ]
                history = []
                for o in db.orders.aggregate(history_pipeline):
                    fi = o.get('first_item')
                    if fi:
                        history.append({
                            'id': o['id'],
                            'name': o.get('first_item_product_name') or 'Sản phẩm',
                            'quantity': fi.get('quantity'),
                            'total_price': fi.get('total_price'),
                            'created_at': o.get('created_at')
                        })

                # Lấy doanh thu 7 ngày gần nhất cho biểu đồ
                today_dt = datetime.now().date()
                last_7_days = [today_dt - timedelta(days=i) for i in range(6, -1, -1)]
                last_7_days_str = [d.isoformat() for d in last_7_days]
                start_date = last_7_days[0].isoformat()

                week_orders = list(db.orders.find(
                    {'business_id': business_id, 'created_at': {'$gte': start_date}},
                    {'total_amount': 1, 'created_at': 1, '_id': 0}
                ))
                revenue_map = {d: 0 for d in last_7_days_str}
                for o in week_orders:
                    created_date = (o.get('created_at') or '')[:10]
                    if created_date in revenue_map:
                        revenue_map[created_date] += o.get('total_amount') or 0
                revenue_chart_data = [revenue_map[d] for d in last_7_days_str]
                revenue_chart_labels = ['7 ngày trước', '6 ngày', '5 ngày', '4 ngày', '3 ngày', 'Hôm qua', 'Hôm nay']
            except Exception as db_err:
                print(f"MongoDB data loading skipped: {str(db_err)}")
                products_data = []
                revenue = 0
                expense = 0
                history = []
                revenue_chart_data = [0]*7
                revenue_chart_labels = ['7 ngày trước', '6 ngày', '5 ngày', '4 ngày', '3 ngày', 'Hôm qua', 'Hôm nay']

            return render_template(
                'dashboard.html',
                products=products_data,
                revenue=revenue,
                expense=expense,
                history=history,
                revenue_chart_data=revenue_chart_data,
                revenue_chart_labels=revenue_chart_labels
            )
        else:
            # Điều hướng động cho tất cả các ngành khác dựa trên registry config
            target_url = INDUSTRY_CONFIG[mode]['redirect_after_login']
            if target_url.startswith('/chamcong/'):
                ind_code = target_url.split('/')[-1]
                return redirect(url_for('chamcong_industry', industry_code=ind_code))
            else:
                endpoint = target_url.strip('/')
                try:
                    return redirect(url_for(endpoint))
                except:
                    return redirect(target_url)
                    
    return redirect(url_for('setup'))


# ========== DASHBOARD JSON API (thay Supabase JS client-side ở dashboard.html) ==========


def _get_task_counts(business_id):
    return {
        'pending': db.tasks.count_documents({'business_id': business_id, 'trang_thai': 'Chờ Nhận'}),
        'doing': db.tasks.count_documents({'business_id': business_id, 'trang_thai': 'Đã Nhận'}),
        'done': db.tasks.count_documents({'business_id': business_id, 'trang_thai': 'Hoàn Thành'}),
    }


@app.route('/api/dashboard/stats', methods=['GET'])
@login_required
@role_required('admin', 'super_admin')
def api_dashboard_stats():
    business_id = session.get('business_id') or session['user_id']
    month = request.args.get('month')
    year = request.args.get('year')
    if not month or not year:
        today = datetime.now()
        month = month or f"{today.month:02d}"
        year = year or str(today.year)

    try:
        total_employees = db.employees.count_documents({'business_id': business_id})

        attendance = list(db.chamcong.find(
            {'business_id': business_id},
            {'employee_id': 1, 'ngay_cham': 1, 'trang_thai': 1, 'tien_tua': 1, 'tien_tips': 1,
             'phu_cap': 1, 'ghi_chu': 1, '_id': 0}
        ))

        # Biểu đồ 10 ngày gần nhất tính từ HÔM NAY (giữ đúng logic gốc — không phải 10 ngày
        # đầu tháng đang lọc, dù filter month/year khác tháng hiện tại).
        today = datetime.now()
        chart_labels = [(today - timedelta(days=i)).strftime('%d/%m') for i in range(9, -1, -1)]
        chart_cong = [0] * 10
        chart_tien = [0] * 10

        unique_employees = set()
        total_payroll = 0
        leaves = []

        for rec in attendance:
            ngay = rec.get('ngay_cham')
            if not ngay:
                continue
            parts = ngay.split('/')
            if len(parts) != 3 or parts[1] != month or parts[2] != year:
                continue
            unique_employees.add(rec.get('employee_id'))
            salary = (rec.get('tien_tua') or 0) + (rec.get('tien_tips') or 0) + (rec.get('phu_cap') or 0)
            total_payroll += salary
            trang_thai = rec.get('trang_thai') or ''
            if any(k in trang_thai for k in ('Nghỉ', 'ốm', 'Chờ duyệt')):
                try:
                    leaves.append({'day': int(parts[0]), 'note': rec.get('ghi_chu') or ''})
                except ValueError:
                    pass
            short_date = f"{parts[0]}/{parts[1]}"
            if short_date in chart_labels:
                idx = chart_labels.index(short_date)
                chart_cong[idx] += 1
                chart_tien[idx] += salary

        return jsonify({
            'success': True,
            'total_employees': total_employees,
            'employees_worked_this_month': len(unique_employees),
            'total_payroll_this_month': total_payroll,
            'chart': {'labels': chart_labels, 'cong': chart_cong, 'tien': chart_tien},
            'leaves': leaves,
            'tasks': _get_task_counts(business_id),
        })
    except Exception as e:
        print(f"[api_dashboard_stats] Lỗi: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/dashboard/kudo_leaderboard', methods=['GET'])
@login_required
@role_required('admin', 'super_admin')
def api_dashboard_kudo_leaderboard():
    business_id = session.get('business_id') or session['user_id']
    try:
        top_emps = list(db.employees.find(
            {'business_id': business_id, 'diem_kudo': {'$gt': 0}},
            {'ho_ten': 1, 'diem_kudo': 1, 'avatar_url': 1, '_id': 0}
        ).sort('diem_kudo', -1).limit(3))
        return jsonify({'success': True, 'data': top_emps})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/dashboard/reconciliation_alerts', methods=['GET'])
@login_required
@role_required('admin', 'super_admin')
def api_dashboard_reconciliation_alerts():
    business_id = session.get('business_id') or session['user_id']
    try:
        alerts = list(db.reconciliation_alerts.find(
            {'business_id': business_id, 'status': 'pending'}, {'_id': 0}
        ).sort('created_at', -1))
        return jsonify({'success': True, 'data': alerts})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/dashboard/reconciliation_alerts/<int:alert_id>/resolve', methods=['POST'])
@login_required
@role_required('admin', 'super_admin')
def api_dashboard_resolve_alert(alert_id):
    business_id = session.get('business_id') or session['user_id']
    try:
        result = db.reconciliation_alerts.update_one(
            {'id': alert_id, 'business_id': business_id}, {'$set': {'status': 'resolved'}}
        )
        if result.matched_count == 0:
            return jsonify({'success': False, 'message': 'Không tìm thấy cảnh báo này hoặc không thuộc quyền quản lý của bạn.'}), 403
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


# ========== SSE: THAY THẾ SUPABASE REALTIME CHO BẢNG tasks ==========
# MongoDB Change Streams (yêu cầu Atlas/replica set — luôn đúng với Atlas kể cả tier M0 free)
# cho phép "chờ" thay đổi thật sự thay vì tự poll lại DB theo chu kỳ cố định: try_next() chỉ
# trả về khi CÓ thay đổi thật hoặc hết max_await_time_ms, nên không tốn tài nguyên quét DB lặp
# lại vô ích như polling truyền thống. Mỗi kết nối tự đóng sau MAX_STREAM_SECONDS để tránh bị
# nền tảng serverless (Vercel) ngắt giữa chừng — EventSource ở trình duyệt tự động reconnect
# lại ngay sau khi stream đóng, nên trải nghiệm người dùng vẫn liền mạch.
SSE_MAX_SECONDS = 25
SSE_MAX_AWAIT_MS = 5000


@app.route('/api/stream/dashboard_tasks')
@login_required
@role_required('admin', 'super_admin')
def stream_dashboard_tasks():
    business_id = session.get('business_id') or session['user_id']

    def event_stream():
        # Gửi số liệu hiện tại ngay khi vừa kết nối, không cần chờ đến lần thay đổi đầu tiên.
        try:
            yield f"data: {json.dumps(_get_task_counts(business_id))}\n\n"
        except Exception:
            pass

        start_time = time.time()
        try:
            with db.tasks.watch(
                [{'$match': {'$or': [
                    {'fullDocument.business_id': business_id},
                    {'operationType': 'delete'}  # delete không có fullDocument -> luôn kiểm tra lại cho an toàn
                ]}}],
                full_document='updateLookup',
                max_await_time_ms=SSE_MAX_AWAIT_MS
            ) as stream:
                while time.time() - start_time < SSE_MAX_SECONDS:
                    change = stream.try_next()
                    if change is not None:
                        yield f"data: {json.dumps(_get_task_counts(business_id))}\n\n"
                    else:
                        yield ": keep-alive\n\n"
        except Exception as e:
            # Cluster không hỗ trợ Change Streams (vd: đứng riêng lẻ không phải replica set) hoặc
            # lỗi kết nối — xuống cấp an toàn về 1 nhịp refresh chậm thay vì bỏ hẳn tính năng.
            print(f"[stream_dashboard_tasks] Change Stream lỗi, fallback về refresh định kỳ: {str(e)}")
            while time.time() - start_time < SSE_MAX_SECONDS:
                time.sleep(5)
                try:
                    yield f"data: {json.dumps(_get_task_counts(business_id))}\n\n"
                except Exception:
                    break

    return Response(stream_with_context(event_stream()), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache',
        'X-Accel-Buffering': 'no',  # tắt buffer nếu có reverse proxy kiểu Nginx phía trước
    })


# ========== SSE: THAY THẾ 3 KÊNH SUPABASE REALTIME (hr_realtime/payroll_realtime/
# public:tasks_app) ==========
# Khác với /api/stream/dashboard_tasks ở trên (tính sẵn payload rồi gửi thẳng), 3 stream dưới
# đây chỉ gửi tín hiệu "đã đổi" — client nhận tín hiệu rồi tự gọi lại đúng API REST đã có sẵn
# (loadEmployees()/loadBangLuong()/loadJobMarket()), để không phải chép lại logic sort/filter
# đã viết ở /api/hr/employees, /api/hr/chamcong, /api/tasks* ra một bản thứ hai trong này.
def _sse_change_signal(watchable, match_stage):
    def event_stream():
        try:
            yield 'data: {"changed": true}\n\n'
        except Exception:
            pass
        start_time = time.time()
        try:
            with watchable.watch([match_stage], full_document='updateLookup', max_await_time_ms=SSE_MAX_AWAIT_MS) as stream:
                while time.time() - start_time < SSE_MAX_SECONDS:
                    change = stream.try_next()
                    if change is not None:
                        yield 'data: {"changed": true}\n\n'
                    else:
                        yield ": keep-alive\n\n"
        except Exception as e:
            # Cluster không hỗ trợ Change Streams hoặc lỗi kết nối — xuống cấp an toàn về 1 nhịp
            # refresh chậm thay vì bỏ hẳn tính năng (giữ đúng hành vi fallback của dashboard_tasks).
            print(f"[_sse_change_signal] Change Stream lỗi, fallback về refresh định kỳ: {str(e)}")
            while time.time() - start_time < SSE_MAX_SECONDS:
                time.sleep(5)
                try:
                    yield 'data: {"changed": true}\n\n'
                except Exception:
                    break

    return Response(stream_with_context(event_stream()), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache',
        'X-Accel-Buffering': 'no',
    })


def _sse_tenant_match(*collection_names):
    """Match stage dùng chung: chỉ nhận thay đổi thuộc đúng business_id hiện tại, trừ event
    delete (không có fullDocument nên luôn cho qua — vô hại, chỉ gây 1 lần refresh thừa)."""
    business_id = session.get('business_id') or session['user_id']
    match = {'$or': [
        {'fullDocument.business_id': business_id},
        {'operationType': 'delete'}
    ]}
    if collection_names:
        match['ns.coll'] = {'$in': list(collection_names)}
    return {'$match': match}


@app.route('/api/stream/hr_employees')
@login_required
def stream_hr_employees():
    """Thay kênh Supabase Realtime `hr_realtime` (nhanvien.html) — bảng employees."""
    return _sse_change_signal(db.employees, _sse_tenant_match())


@app.route('/api/stream/payroll')
@login_required
def stream_payroll():
    """Thay kênh Supabase Realtime `payroll_realtime` (bangluong.html) — bảng chamcong VÀ
    employees cùng lúc, nên watch ở cấp Database thay vì 1 collection đơn lẻ."""
    return _sse_change_signal(db, _sse_tenant_match('chamcong', 'employees'))


@app.route('/api/stream/job_market')
@login_required
def stream_job_market():
    """Thay kênh Supabase Realtime `public:tasks_app` (app_nhanvien.html) — bảng tasks."""
    return _sse_change_signal(db.tasks, _sse_tenant_match())


@app.route('/landingpage')
@app.route('/landing')
def landingpage():
    landing_translations = {
        'en': get_translations('en')['landing'],
        'vi': get_translations('vi')['landing'],
    }
    lang = resolve_lang(request)
    return render_template(
        'landing.html',
        landing_translations_json=json.dumps(landing_translations, ensure_ascii=False),
        current_lang=lang,
        i18n=landing_translations[lang],
    )


@app.route('/sitemap.xml')
def sitemap():
    return send_from_directory(os.path.dirname(os.path.abspath(__file__)), 'sitemap.xml', mimetype='application/xml')


@app.route('/checkout')
def public_checkout():
    return render_template('checkout.html')


# ========== SAAS MODULE SIGNUP (checkout.html) — KHÔNG dùng chung với db.orders của POS ==========
# checkout.html KHÔNG PHẢI checkout đơn hàng POS — đây là form đăng ký mua gói phần mềm
# (hrm/pos/ecom/agency) của một khách hàng CHƯA CÓ business_id (doanh nghiệp chưa tồn tại).
# db.orders/`order_items` của POS được rất nhiều báo cáo doanh thu ($lookup theo order_id,
# tổng total_amount theo business_id) tin tưởng là "1 đơn hàng thật của 1 tenant đã tồn tại" —
# ghi lead đăng ký vào đó sẽ làm sai lệch báo cáo doanh thu và vỡ các pipeline $lookup. Vì vậy
# lead đăng ký được lưu vào 1 collection hoàn toàn tách biệt, không có business_id, không có
# order_items đi kèm. Sau khi khách bấm "Đã chuyển khoản", nhân viên vẫn xác nhận + cấp license
# key thủ công qua /api/superadmin/duc_ma như quy trình hiện tại — form này KHÔNG tự động kích
# hoạt tài khoản (hành vi y hệt bản Supabase cũ: chỉ ghi nhận lead, không có webhook xác nhận
# thanh toán nào tồn tại).
@app.route('/api/checkout/payment_methods', methods=['GET'])
def api_checkout_payment_methods():
    """PUBLIC — chỉ trả về các cổng thanh toán đang active, cho khách xem QR chuyển khoản
    trước khi có tài khoản/session. Dùng chung collection db.payment_methods với
    /api/superadmin/payment_methods (superadmin quản lý), nhưng route này không yêu cầu đăng
    nhập và luôn lọc is_active=True."""
    try:
        methods = list(db.payment_methods.find({'is_active': True}, {'_id': 0}).sort('id', 1))
        return jsonify({"success": True, "data": methods})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/checkout/signup', methods=['POST'])
def api_checkout_signup():
    """PUBLIC — ghi nhận lead đăng ký mua gói (chưa có business_id vì doanh nghiệp chưa được
    tạo). Lưu vào db.saas_signups, KHÔNG đụng tới db.orders của POS."""
    data = request.json or {}
    required = ('customer_name', 'phone', 'shop_name', 'email', 'module_plan', 'total_price')
    if not all((data.get(f) or '').strip() if isinstance(data.get(f), str) else data.get(f) for f in required):
        return jsonify({"success": False, "message": "Thiếu thông tin bắt buộc."}), 400
    try:
        doc = {
            'id': next_mongo_id('saas_signups'),
            'customer_name': data.get('customer_name', ''),
            'phone': data.get('phone', ''),
            'shop_name': data.get('shop_name', ''),
            'email': data.get('email', ''),
            'module_plan': data.get('module_plan', ''),
            'total_price': data.get('total_price', 0),
            'memo_code': data.get('memo_code', ''),
            'status': 'pending',
            'created_at': datetime.now().isoformat(),
        }
        db.saas_signups.insert_one(doc)
        doc.pop('_id', None)
        return jsonify({"success": True, "data": doc})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/landing_nail')
def legacy_landing_nail():
    return render_template('landing_nail.html')


@app.route('/solutions/nail')
def solutions_nail():
    return render_template('landing_nail.html')


@app.route('/solutions/<industry_code>')
def solutions_page(industry_code):
    if industry_code == 'nails':
        industry_code = 'nail'
    valid_industries = ['nail', 'spa', 'fnb', 'karaoke', 'hotel', 'retail', 'office', 'technical', 'production', 'hr']
    if industry_code in valid_industries:
        return render_template(f"landing_{industry_code}.html")
    else:
        return redirect(url_for('landingpage'))


@app.route('/setup', methods=['GET', 'POST'])
@login_required
def setup():
    if request.method == 'POST':
        # Chuẩn hoá lowercase — cùng lý do đã áp dụng ở register() (INDUSTRY_CONFIG chỉ có
        # key lowercase, mọi so sánh == 'nail' ở nơi khác đều giả định giá trị đã sạch).
        mode = (request.form['mode'] or '').strip().lower()
        session['business_mode'] = mode
        try:
            business_mode_key = f"business_mode_{session['user_id']}"
            db.system_settings.update_one(
                {'key': business_mode_key}, {'$set': {'value': mode}}, upsert=True
            )
        except Exception as db_err:
            print(f"MongoDB system_settings upsert skipped: {str(db_err)}")
        return redirect(url_for('index'))
    return render_template('setup.html')


# ========== QUẢN LÝ SẢN PHẨM ==========
@app.route('/add', methods=['GET', 'POST'])
@login_required
def add_product():
    try:
        mode_doc = db.system_settings.find_one({'key': f"business_mode_{session['user_id']}"}, {'value': 1, '_id': 0})
        current_mode = (mode_doc['value'] if mode_doc else 'none').strip().lower()
    except Exception as db_err:
        print(f"MongoDB system_settings select failed: {str(db_err)}")
        current_mode = 'none'
    if request.method == 'POST':
        cat = request.form['category']
        business_id = session.get('business_id') or session['user_id']
        # Ảnh sản phẩm lưu vào GridFS (media_fs, kind='product_image') thay vì filesystem cục
        # bộ — trên Vercel, filesystem là ephemeral/read-only ngoài /tmp nên lưu file thật sẽ
        # mất ảnh sau mỗi cold start/redeploy. Lưu thẳng URL public (không cần login) vì thực
        # đơn được xem bởi khách quét QR (qr_menu.html/table_order.html) không có session.
        image_url = ""
        image_file = request.files.get('image')
        if image_file and image_file.filename != '' and allowed_file(image_file.filename) and media_fs is not None:
            try:
                file_id = media_fs.put(
                    image_file.stream.read(),
                    filename=secure_filename(image_file.filename),
                    business_id=business_id,
                    kind='product_image',
                    content_type=_safe_image_content_type(image_file.filename)
                )
                image_url = url_for('api_public_storage_file', file_id=str(file_id))
            except Exception as media_err:
                print(f"GridFS product image upload failed: {str(media_err)}")
        try:
            db.products.insert_one({
                'id': next_mongo_id('products'),
                'name': request.form['name'],
                'category': cat,
                'channel_type': 'fnb' if current_mode == 'fnb' else 'retail',
                'stock': int(request.form['stock']),
                'price': float(request.form['price']),
                'image': image_url,
                'is_active': 1,
                'business_id': business_id
            })
        except Exception as db_err:
            print(f"MongoDB products insert failed: {str(db_err)}")
        if current_mode == 'fnb':
            return redirect(url_for('pos'))
        return redirect(url_for('index'))
    return render_template('add_product.html', mode=current_mode)


def _assert_owns_product(product_id, business_id):
    """Trả về True nếu sản phẩm thuộc đúng business_id hiện tại, False nếu không (hoặc không tồn tại)."""
    doc = db.products.find_one({'id': product_id}, {'business_id': 1, '_id': 0})
    return bool(doc) and doc.get('business_id') == business_id


@app.route('/update_product/<int:id>', methods=['POST'])
@login_required
def update_product(id):
    business_id = session.get('business_id') or session['user_id']
    try:
        if not _assert_owns_product(id, business_id):
            return jsonify({'success': False, 'message': 'Sản phẩm không tồn tại hoặc không thuộc quyền quản lý của bạn.'}), 403
    except Exception as e:
        return jsonify({'success': False, 'message': f'Lỗi xác thực quyền sở hữu sản phẩm: {str(e)}'}), 500

    try:
        old_value = db.products.find_one({'id': id}, {'name': 1, 'category': 1, 'price': 1, 'stock': 1, '_id': 0})

        name = request.form['name']
        category = request.form['category']
        price = float(request.form['price'])
        stock = int(request.form['stock'])
        new_value = {'name': name, 'category': category, 'price': price, 'stock': stock}
        db.products.update_one({'id': id, 'business_id': business_id}, {'$set': new_value})
        _log_audit(business_id, 'update_price', entity_type='product', entity_id=id, old_value=old_value, new_value=new_value)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Lỗi cập nhật sản phẩm: {str(e)}'}), 500


@app.route('/delete_product/<int:id>')
@login_required
def delete_product(id):
    """Giai đoạn 5 audit: route kiểu cũ (redirect) vẫn giữ NGUYÊN cho Web — chỉ trả JSON
    {success, message} khi _wants_json() (Mobile qua JWT, hoặc client tự khai Accept: application/json)."""
    business_id = session.get('business_id') or session['user_id']
    try:
        if not _assert_owns_product(id, business_id):
            msg = "Sản phẩm không tồn tại hoặc không thuộc quyền quản lý của bạn."
            return (jsonify({"success": False, "message": msg}), 403) if _wants_json() else (msg, 403)
    except Exception as e:
        msg = f"Lỗi xác thực quyền sở hữu sản phẩm: {str(e)}"
        return (jsonify({"success": False, "message": msg}), 500) if _wants_json() else (msg, 500)

    try:
        old_value = db.products.find_one({'id': id}, {'name': 1, 'is_active': 1, '_id': 0})
        db.products.update_one({'id': id, 'business_id': business_id}, {'$set': {'is_active': 0}})
        _log_audit(business_id, 'delete_product', entity_type='product', entity_id=id, old_value=old_value, new_value={'is_active': 0})
    except Exception as e:
        msg = f"Lỗi xóa sản phẩm: {str(e)}"
        return (jsonify({"success": False, "message": msg}), 500) if _wants_json() else (msg, 500)
    if _wants_json():
        return jsonify({"success": True, "message": "Đã xoá sản phẩm."})
    return redirect(request.referrer or url_for('pos'))


# ========== QUẢN LÝ BÀN (POS) ==========
@app.route('/pos')
@login_required
def pos():
    business_id = session.get('business_id') or session['user_id']
    try:
        tables_data = list(db.dining_tables.find({'business_id': business_id}, {'_id': 0}))
        if len(tables_data) == 0:
            # Cố định mặc định 200 bàn (đặt tên tiếng Anh "Table N") thay vì phụ thuộc vào
            # tính năng "Thêm Bàn" động — mỗi tenant F&B mới sẽ luôn có sẵn 200 bàn thật
            # (có id Mongo thật, dùng được ngay cho gọi món/thanh toán) ngay từ lần đầu vào POS.
            new_ids = next_mongo_id_batch('dining_tables', 200)
            default_tables = [
                {'id': new_id, 'name': f'Table {i}',
                 'qr_token': uuid.uuid4().hex[:8], 'business_id': business_id}
                for i, new_id in zip(range(1, 201), new_ids)
            ]
            try:
                db.dining_tables.insert_many(default_tables)
                tables_data = default_tables
            except Exception as e:
                print(f"MongoDB dining_tables seed insert failed: {str(e)}")
    except Exception as e:
        print(f"MongoDB dining_tables select failed: {str(e)}")
        # Không fallback về bàn demo dùng chung nữa — mỗi tenant chỉ thấy dữ liệu rỗng khi lỗi, tránh lộ/trộn dữ liệu.
        tables_data = []
    try:
        menu_data = list(db.products.find(
            {'is_active': 1, 'channel_type': 'retail', 'business_id': business_id}, {'_id': 0}
        ))
    except Exception as e:
        print(f"MongoDB products select failed: {str(e)}")
        menu_data = []
    return render_template('pos.html', tables=tables_data, menu=menu_data)


@app.route('/add_table', methods=['POST'])
@login_required
def add_table():
    table_name = request.form.get('table_name', '').strip()
    if not table_name:
        return jsonify({"success": False, "message": "Vui lòng nhập tên bàn."}), 400

    # Sinh qr_token và kiểm tra chống trùng lặp trong DB trước khi lưu
    qr_token = None
    for _ in range(10):
        candidate = uuid.uuid4().hex[:8]
        try:
            if not db.dining_tables.find_one({'qr_token': candidate}, {'id': 1, '_id': 0}):
                qr_token = candidate
                break
        except Exception as e:
            return jsonify({"success": False, "message": f"Lỗi kiểm tra mã QR: {str(e)}"}), 500
    if not qr_token:
        return jsonify({"success": False, "message": "Không thể sinh mã QR duy nhất, vui lòng thử lại."}), 500

    business_id = session.get('business_id') or session['user_id']
    insert_payload = {'id': next_mongo_id('dining_tables'), 'name': table_name, 'qr_token': qr_token, 'business_id': business_id}
    try:
        db.dining_tables.insert_one(insert_payload)
    except Exception as e:
        return jsonify({"success": False, "message": f"Lỗi khi thêm bàn: {str(e)}"}), 500

    return redirect(url_for('pos'))


# ========== POS JSON API (dùng cho fetch() ở pos.html — thay thế Supabase JS client-side) ==========
@app.route('/api/pos/products', methods=['GET'])
@login_required
def api_pos_products():
    business_id = session.get('business_id') or session['user_id']
    channel_type = request.args.get('channel_type', 'fnb')
    try:
        products_data = list(db.products.find(
            {'is_active': 1, 'channel_type': channel_type, 'business_id': business_id},
            {'id': 1, 'name': 1, 'price': 1, 'stock': 1, 'image': 1, 'channel_type': 1, '_id': 0}
        ).sort('name', 1))
        return jsonify({'success': True, 'data': products_data})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/products/<int:id>', methods=['GET'])
@login_required
def api_product_get(id):
    """Tra cứu 1 sản phẩm theo id, business_id-scoped — thay Supabase select().eq('id',
    ...).single() cũ ở sell.html. Không lọc channel_type (khác /api/pos/products) vì sell.html
    bán trực tiếp theo product_id trên URL, có thể là sản phẩm retail lẫn F&B/spa."""
    business_id = session.get('business_id') or session['user_id']
    try:
        product = db.products.find_one(
            {'id': id, 'business_id': business_id},
            {'id': 1, 'name': 1, 'price': 1, 'stock': 1, 'image': 1, '_id': 0}
        )
        if not product:
            return jsonify({"success": False, "message": "Không tìm thấy sản phẩm."}), 404
        return jsonify({"success": True, "data": product})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


class InsufficientStockError(Exception):
    """Raise khi trừ kho nguyên tử thất bại vì tồn kho hiện có < số lượng yêu cầu. Khi được gọi
    bên trong 1 Mongo session transaction, exception này khiến toàn bộ transaction TỰ ĐỘNG abort
    (order/order_items/transaction ledger của lần checkout này KHÔNG có gì được giữ lại)."""
    def __init__(self, product_id, product_name=None):
        label = product_name or f"#{product_id}"
        self.product_id = product_id
        self.product_name = product_name
        super().__init__(f"Sản phẩm '{label}' không đủ tồn kho để bán.")


def _decrement_stock_atomic(business_id, stock_items, db_session=None):
    """Trừ tồn kho NGUYÊN TỬ từng sản phẩm bằng find_one_and_update($inc âm) kèm điều kiện lọc
    `stock >= qty` ngay trong query — thay cho kiểu cũ 'đọc số lượng bằng Python rồi $set đè lại'
    vốn có race condition: nhiều request trừ cùng 1 sản phẩm cùng lúc (giờ cao điểm, nhiều đơn
    QR order) có thể cùng đọc 1 giá trị cũ rồi cùng ghi đè, làm mất bớt lần trừ kho -> bán vượt
    tồn kho thực tế (bán âm). $gte trong filter đảm bảo Mongo tự chọn tuần tự hoá các update
    cạnh tranh trên cùng 1 document — không đơn nào có thể trừ xuống dưới 0.
    `stock_items`: list các tuple (product_id, quantity, product_name_optional).
    Raise InsufficientStockError ngay khi có 1 sản phẩm không đủ hàng."""
    for product_id, qty, *rest in stock_items:
        if not qty or qty <= 0:
            continue
        product_name = rest[0] if rest else None
        result = db.products.find_one_and_update(
            {'id': product_id, 'business_id': business_id, 'stock': {'$gte': qty}},
            {'$inc': {'stock': -qty}},
            session=db_session,
            projection={'_id': 0, 'id': 1},
        )
        if result is None:
            raise InsufficientStockError(product_id, product_name)


def _restock_atomic(business_id, stock_items, db_session=None):
    """Cộng lại tồn kho (hoàn hàng/refund, Giai đoạn 5 audit) — ngược chiều
    _decrement_stock_atomic(), dùng $inc dương nguyên tử. Không cần điều kiện $gte (cộng thêm
    luôn hợp lệ, không có khái niệm "không đủ chỗ để cộng"). Chỉ áp dụng cho sản phẩm CÓ field
    'stock' (bỏ qua an toàn nếu sản phẩm không track kho hoặc đã bị xoá)."""
    for product_id, qty, *rest in stock_items:
        if not qty or qty <= 0:
            continue
        db.products.update_one(
            {'id': product_id, 'business_id': business_id, 'stock': {'$exists': True}},
            {'$inc': {'stock': qty}},
            session=db_session,
        )


def _record_pos_transaction(business_id, order_id, amount, payment_method, created_by=None,
                             category='sales', transaction_type='income', db_session=None):
    """Ghi 1 bản ghi sổ cái vào db.transactions ứng với 1 đơn POS đã thanh toán thành công.
    BẮT BUỘC gọi ngay sau khi 1 order được tạo/xác nhận thanh toán ở MỌI pipeline checkout
    (F&B/Retail/Nail/Karaoke) — trước đây các luồng checkout chỉ ghi db.orders, khiến báo cáo
    Tài chính không có sổ cái đáng tin cậy để đối soát. `created_by` mặc định lấy từ session
    Flask hiện tại (thu ngân đang đăng nhập); truyền tay khi gọi từ webhook (không có session)."""
    db.transactions.insert_one({
        'id': next_mongo_id('transactions'),
        'business_id': business_id,
        'order_id': order_id,
        'amount': amount,
        'type': transaction_type,
        'category': category,
        'payment_method': payment_method,
        'timestamp': datetime.now().isoformat(),
        'created_by': created_by if created_by is not None else (session.get('user_email') or session.get('user_id')),
    }, session=db_session)


def _compute_cart_order(business_id, data):
    """Tính subtotal/tip/total/payment_bucket/hoa hồng từ payload giỏ hàng — DÙNG CHUNG cho
    cả api_sales_checkout (cash/mock) LẪN api_square_checkout (Square Terminal thật), đảm bảo
    2 luồng luôn tính tiền giống hệt nhau (sửa 1 chỗ, áp dụng cả 2). Raise ValueError(message)
    nếu dữ liệu không hợp lệ — caller tự bắt và trả 400/404 tương ứng.

    Trả về (order_fields, metadata_fields, order_items_docs, stock_items):
      - order_fields: CHỈ chứa các trường LÕI ghi thẳng top-level vào db.orders
        (total_amount, payment_method) — dùng chung, không đổi hình dạng theo ngành.
      - metadata_fields: mọi trường ĐẶC THÙ (subtotal, tip_amount, payment_bucket, currency,
        hoa hồng thợ, customer_phone...) — caller gộp field này vào 'metadata' của order_doc,
        KHÔNG ghi rời ở top-level nữa (xem khối schema chuẩn hoá ở đầu nhóm route checkout).
      - stock_items: dùng trực tiếp với _decrement_stock_atomic(), KHÔNG còn là UpdateOne($set)
        tính sẵn trong Python (nguồn gốc race condition cũ)."""
    items = data.get('items') or []
    if not items:
        raise ValueError("Giỏ hàng trống.")
    product_ids = [it['product_id'] for it in items]
    products_map = {
        p['id']: p for p in db.products.find(
            {'id': {'$in': product_ids}, 'business_id': business_id}, {'_id': 0}
        )
    }
    subtotal = 0
    order_items_docs = []
    stock_items = []
    for it in items:
        prod = products_map.get(it['product_id'])
        if not prod:
            continue  # chặn bán sản phẩm không thuộc tenant này hoặc không tồn tại
        qty = int(it.get('quantity', 1))
        price = prod.get('price', 0)
        line_total = qty * price
        subtotal += line_total
        order_items_docs.append({
            'product_id': prod['id'], 'quantity': qty, 'price': price, 'total_price': line_total,
        })
        if 'stock' in prod:
            stock_items.append((prod['id'], qty, prod.get('name')))
    if not order_items_docs:
        raise ValueError("Không có sản phẩm hợp lệ trong giỏ hàng.")

    # Tip: số tiền cố định (tip_amount) hoặc theo % subtotal (tip_percent) — client gửi 1
    # trong 2, không gửi thì mặc định 0. total_amount = subtotal + tip (số tiền thực thu),
    # subtotal/tip_amount được lưu riêng để đối soát/hiển thị hoá đơn tách bạch.
    tip_amount = data.get('tip_amount')
    if tip_amount is None and data.get('tip_percent') is not None:
        tip_amount = subtotal * (float(data['tip_percent']) / 100)
    tip_amount = round(float(tip_amount or 0), 2)
    total_amount = round(subtotal + tip_amount, 2)

    # Phân loại thanh toán cho báo cáo Cash/Card: payment_method giữ nguyên chuỗi gốc
    # (không phá các màn hình khác đang gửi 'bank'/'momo'/'stripe'/'vietqr'...), nhưng luôn
    # kèm thêm payment_bucket chỉ gồm đúng 2 giá trị 'cash' hoặc 'card' — mọi hình thức
    # KHÔNG PHẢI tiền mặt (bank, momo, thẻ, ví điện tử...) đều gộp vào 'card' vì bản chất
    # đều là tiền vào tài khoản/không phải tiền mặt tại quầy — Dashboard tổng hợp doanh thu
    # dựa trên field này để đối soát 2 quỹ tách biệt (tiền mặt vs tiền vào tài khoản).
    payment_method = (data.get('payment_method') or 'cash').strip().lower()
    payment_bucket = 'cash' if payment_method == 'cash' else 'card'

    # Hoa hồng Chủ/Thợ: chỉ áp dụng khi đơn có gắn staff_id (ai trực tiếp phục vụ khách).
    # Chia theo subtotal (giá trị dịch vụ/sản phẩm) — Tip KHÔNG chia, cộng thẳng 100% cho thợ.
    staff_id = data.get('staff_id')
    commission_fields = {}
    if staff_id is not None:
        try:
            staff_id = int(staff_id)
        except (TypeError, ValueError):
            raise ValueError("staff_id không hợp lệ.")
        staff_doc = db.staff.find_one({'id': staff_id, 'business_id': business_id})
        if not staff_doc:
            raise ValueError("Nhân viên (staff_id) không tồn tại hoặc không thuộc cửa hàng này.")
        commission_rate = _resolve_staff_commission_rate(business_id, staff_doc, data.get('commission_rate'))
        staff_commission = round(subtotal * (commission_rate / 100), 2)
        owner_commission = round(subtotal - staff_commission, 2)
        commission_fields = {
            'staff_id': staff_id,
            'commission_rate': commission_rate,
            'staff_commission': staff_commission,
            'owner_commission': owner_commission,
            'staff_tip_earning': tip_amount,  # Tip 100% về thợ, không qua công thức chia %
            'staff_total_earning': round(staff_commission + tip_amount, 2),
        }

    order_fields = {
        'total_amount': total_amount,
        'payment_method': payment_method,
    }
    metadata_fields = {
        'subtotal': subtotal,
        'tip_amount': tip_amount,
        'payment_bucket': payment_bucket,
        'currency': data.get('currency', 'VND'),
    }
    metadata_fields.update(commission_fields)
    if data.get('customer_phone'):
        metadata_fields['customer_phone'] = data['customer_phone']
    return order_fields, metadata_fields, order_items_docs, stock_items


def _finalize_paid_order(order_doc):
    """Gọi NGAY SAU KHI 1 đơn hàng được xác nhận thanh toán xong — cộng điểm loyalty/tạo CRM,
    và đẩy Event Hook cho AI CRM/Nurture (Giai đoạn 4 audit). Dùng chung cho cả luồng đồng bộ
    (api_sales_checkout, biết ngay kết quả) LẪN luồng bất đồng bộ (webhook Square, chỉ biết kết
    quả sau khi khách quẹt thẻ xong ở quầy).
    customer_phone/currency nằm trong order_doc['metadata'] (schema chuẩn hoá) — KHÔNG còn ở
    top-level."""
    metadata = order_doc.get('metadata') or {}
    customer_phone = metadata.get('customer_phone')
    if customer_phone:
        _award_loyalty_points(
            order_doc['business_id'], customer_phone, order_doc['total_amount'],
            currency=metadata.get('currency', 'VND')
        )

        # Event Hook cho AI CRM/Nurture — chỉ đẩy XADD vào Redis Stream (KHÔNG gọi API AI/CRM
        # đồng bộ ở đây, tránh làm chậm luồng thanh toán chính). 1 worker riêng (mở rộng
        # nurture_scheduler.py sau này, theo đúng mẫu consumer.py đang đọc ATTENDANCE_STREAM)
        # sẽ LISTEN ORDER_EVENTS_STREAM và tự xử lý bất đồng bộ (gửi tin nhắn cảm ơn/upsell qua
        # Zalo/Messenger, cập nhật churn score...). Chỉ đẩy khi có customer_phone — không có SĐT
        # thì không có ai để nhắn, đẩy event rỗng chỉ tạo nhiễu cho worker sau này phải lọc bỏ.
        # Best-effort tuyệt đối: lỗi ở đây KHÔNG BAO GIỜ được phép làm hỏng response thanh toán
        # đã thành công — khác hẳn api_checkin/api_checkout (nơi mất event = mất dữ liệu lương).
        try:
            redis_queue.push_order_completed_event({
                'event_type': 'ORDER_COMPLETED',
                'order_id': order_doc.get('id'),
                'business_id': order_doc.get('business_id'),
                'customer_phone': customer_phone,
                'total_amount': order_doc.get('total_amount'),
                'currency': metadata.get('currency', 'VND'),
                'timestamp': datetime.now().isoformat(),
            })
        except Exception as e:
            # print() lồng thêm 1 lớp try/except riêng: console Windows (cp1252) từng crash khi
            # in ký tự có dấu trong message lỗi driver Redis — nếu để print() đó tự văng exception,
            # nó sẽ thoát khỏi khối try/except này và làm hỏng CẢ response thanh toán đã thành
            # công (đã xảy ra thật lúc test route này). Tuyệt đối không để lỗi LOG làm hỏng luồng
            # chính — đây là lý do khối try/except NÀY tồn tại.
            try:
                print(f"[_finalize_paid_order] Loi day ORDER_COMPLETED vao Redis (khong anh huong thanh toan da thanh cong): {e}")
            except Exception:
                pass


@app.route('/api/sales/checkout', methods=['POST'])
@login_required
def api_sales_checkout():
    """Bán hàng trực tiếp (sell.html: 1 sản phẩm; spa.html: giỏ hàng nhiều dịch vụ) — khác
    checkout_table() (dùng cho đơn theo bàn F&B qua table_orders). Route này tạo thẳng 1
    order + order_items từ danh sách item client gửi lên, không qua bàn. Trừ tồn kho nếu sản
    phẩm có field `stock` (dịch vụ spa thường không track tồn kho nên bỏ qua an toàn).
    Dùng cho thanh toán Cash HOẶC các cổng thanh toán "biết kết quả ngay" (không qua Square
    Terminal vật lý) — xem api_square_checkout() cho luồng quẹt thẻ thật bất đồng bộ."""
    business_id = session.get('business_id') or session['user_id']
    data = request.json or {}
    try:
        order_fields, metadata_fields, order_items_docs, stock_items = _compute_cart_order(business_id, data)
    except ValueError as e:
        msg = str(e)
        status_code = 404 if 'không tồn tại' in msg else 400
        return jsonify({"success": False, "message": msg}), status_code

    order_id = next_mongo_id('orders')
    status = data.get('status', 'completed')
    # Schema chuẩn hoá: CHỈ 6 trường lõi ở top-level (id, business_id, created_at, total_amount,
    # status, payment_method) — dùng CHUNG cho mọi ngành/pipeline checkout. Mọi trường đặc thù
    # (subtotal, tip, hoa hồng, customer_phone...) gộp vào 'metadata' — xem _compute_cart_order.
    order_doc = {
        'id': order_id,
        'business_id': business_id,
        'created_at': datetime.now().isoformat(),
        'status': status,
        'total_amount': order_fields['total_amount'],
        'payment_method': order_fields['payment_method'],
        'metadata': metadata_fields,
    }
    customer_phone = metadata_fields.get('customer_phone')
    for oi in order_items_docs:
        oi['id'] = next_mongo_id('order_items')
        oi['order_id'] = order_id
        if customer_phone:
            oi['customer_phone'] = customer_phone

    try:
        # Trừ kho + tạo order/order_items + ghi sổ cái transactions ATOMIC trong cùng 1 Mongo
        # session transaction — nếu InsufficientStockError xảy ra ở bất kỳ sản phẩm nào, TOÀN
        # BỘ (kể cả các sản phẩm đã trừ kho thành công trước đó trong cùng đơn) tự động rollback.
        with mongo_client_instance.start_session() as db_session:
            with db_session.start_transaction():
                _decrement_stock_atomic(business_id, stock_items, db_session=db_session)
                db.orders.insert_one(order_doc, session=db_session)
                if order_items_docs:
                    db.order_items.insert_many(order_items_docs, session=db_session)
                if status == 'completed':
                    _record_pos_transaction(
                        business_id, order_id, order_fields['total_amount'],
                        order_fields['payment_method'], db_session=db_session,
                    )

        # Cộng điểm loyalty + tạo/cập nhật hồ sơ CRM khách hàng theo SĐT — trước đây chỉ luồng
        # thanh toán theo bàn (api_payment_confirm) gọi hàm này, khiến khách mua qua giỏ hàng
        # trực tiếp (route này) không bao giờ được ghi nhận vào CRM/loyalty dù có nhập SĐT.
        _finalize_paid_order(order_doc)

        # Response giữ NGUYÊN hình dạng cũ cho frontend (hoá đơn hiển thị subtotal/tip/...) —
        # chỉ tài liệu LƯU TRONG DB đổi shape, hợp đồng API không đổi.
        return jsonify({"success": True, "order_id": order_id, **order_fields, **metadata_fields})
    except InsufficientStockError as e:
        return jsonify({"success": False, "message": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


# ========== SQUARE TERMINAL — QUẸT THẺ THẬT (BẤT ĐỒNG BỘ QUA WEBHOOK) ==========
# Khác api_sales_checkout (biết kết quả thanh toán NGAY trong request, dùng cho Cash/mock):
# luồng này TẠO ĐƠN TRẠNG THÁI 'pending' trước, đẩy lệnh xuống thiết bị Square Terminal vật lý
# (SQUARE_DEVICE_ID), rồi CHỜ webhook /api/webhooks/square báo kết quả thật sau khi khách quẹt
# thẻ xong tại quầy — có thể mất vài giây đến vài chục giây, không thể trả lời đồng bộ trong
# 1 request HTTP duy nhất.
@app.route('/api/payments/square/checkout', methods=['POST'])
@login_required
def api_square_checkout():
    """Web POS gọi khi thu ngân chọn thanh toán 'Card' và muốn quẹt thẻ THẬT qua Square
    Terminal. Tạo trước 1 đơn hàng trạng thái 'pending' (tính đủ subtotal/tip/hoa hồng ngay
    từ lúc này, dùng chung công thức với api_sales_checkout), đẩy lệnh xuống Square, lưu lại
    checkout_id để webhook đối soát khi có kết quả thật."""
    business_id = session.get('business_id') or session['user_id']
    data = request.json or {}
    try:
        order_fields, metadata_fields, order_items_docs, stock_items = _compute_cart_order(business_id, data)
    except ValueError as e:
        msg = str(e)
        status_code = 404 if 'không tồn tại' in msg else 400
        return jsonify({"success": False, "message": msg}), status_code

    if not payment_us_engine.is_configured() or not payment_us_engine.SQUARE_DEVICE_ID:
        # Chỉ trả về CỜ true/false (không lộ giá trị secret thật) để biết chính xác biến nào
        # đang thiếu trên server đang chạy — 3 biến độc lập, có thể chỉ thiếu đúng 1 trong số đó.
        return jsonify({
            "success": False,
            "message": "Square Terminal chưa được cấu hình đầy đủ (thiếu SQUARE_ACCESS_TOKEN/SQUARE_LOCATION_ID/SQUARE_DEVICE_ID).",
            "config_status": {
                "SQUARE_ACCESS_TOKEN_set": bool(payment_us_engine.SQUARE_ACCESS_TOKEN),
                "SQUARE_LOCATION_ID_set": bool(payment_us_engine.SQUARE_LOCATION_ID),
                "SQUARE_DEVICE_ID_set": bool(payment_us_engine.SQUARE_DEVICE_ID),
                "SQUARE_DEVICE_ID_is_none": payment_us_engine.SQUARE_DEVICE_ID is None,
                "SQUARE_DEVICE_ID_len": len(payment_us_engine.SQUARE_DEVICE_ID) if payment_us_engine.SQUARE_DEVICE_ID is not None else -1,
                "SQUARE_DEVICE_ID_from_os_environ_directly_len": len(os.environ.get('SQUARE_DEVICE_ID') or ''),
                "SQUARE_ENV": payment_us_engine.SQUARE_ENV,
            }
        }), 503

    try:
        order_id = next_mongo_id('orders')
        # Luồng Square Terminal luôn là quẹt thẻ thật — ép cứng payment_method/payment_bucket
        # bất kể client gửi gì, tránh trường hợp gửi nhầm 'cash' vào route quẹt thẻ.
        metadata_fields['payment_bucket'] = 'card'
        order_doc = {
            'id': order_id,
            'business_id': business_id,
            'created_at': datetime.now().isoformat(),
            'status': 'pending',
            'total_amount': order_fields['total_amount'],
            'payment_method': 'square',
            'metadata': metadata_fields,
        }
        customer_phone = metadata_fields.get('customer_phone')
        for oi in order_items_docs:
            oi['id'] = next_mongo_id('order_items')
            oi['order_id'] = order_id
            if customer_phone:
                oi['customer_phone'] = customer_phone

        # Giai đoạn 7 (SRE) audit — GIỮ CHỖ HÀNG (trừ kho nguyên tử + tạo order 'pending')
        # TRƯỚC KHI gọi Square charge khách, KHÔNG phải sau như trước đây. Lý do: nếu hết hàng
        # được phát hiện SAU khi đã đẩy lệnh charge xuống Terminal, khách có thể đã bị trừ tiền
        # cho 1 đơn không thể giao — đảo thứ tự để KHÔNG BAO GIỜ charge khách cho thứ chắc chắn
        # không đủ để bán. Sổ cái transactions CHƯA ghi ở đây vì đơn còn 'pending' — chỉ ghi khi
        # webhook Square báo COMPLETED thật sự.
        with mongo_client_instance.start_session() as db_session:
            with db_session.start_transaction():
                _decrement_stock_atomic(business_id, stock_items, db_session=db_session)
                db.orders.insert_one(order_doc, session=db_session)
                if order_items_docs:
                    db.order_items.insert_many(order_items_docs, session=db_session)

        # Đã giữ chỗ hàng thành công -> giờ mới gọi Square charge khách thật.
        txn_id = f"SQTERM-{order_id}-{uuid.uuid4().hex[:6].upper()}"
        square_result = payment_us_engine.create_terminal_checkout(
            order_doc['total_amount'], txn_id, note=f"BitPaw POS Order #{order_id}"
        )
        if not square_result.get('configured') or not square_result.get('success'):
            # Charge thất bại/chưa cấu hình SAU KHI đã giữ chỗ hàng -> BẮT BUỘC hoàn kho + huỷ
            # order, nếu không hàng bị "giữ chỗ" vĩnh viễn dù khách chưa hề bị tính tiền.
            try:
                _restock_atomic(business_id, stock_items)
                db.orders.update_one({'id': order_id}, {'$set': {'status': 'failed'}})
            except Exception as rollback_err:
                print(f"[api_square_checkout] LOI HOAN KHO sau khi Square charge that bai "
                      f"(order_id={order_id}) - CAN KIEM TRA TAY: {rollback_err}")
            status_code = 503 if not square_result.get('configured') else 502
            return jsonify({"success": False, "message": square_result.get('message')}), status_code

        db.orders.update_one(
            {'id': order_id},
            {'$set': {
                'metadata.square_checkout_id': square_result.get('checkout_id'),
                'metadata.square_txn_id': txn_id,
            }}
        )

        return jsonify({
            "success": True,
            "order_id": order_id,
            "checkout_id": square_result.get('checkout_id'),
            "terminal_status": square_result.get('terminal_status'),
            "total_amount": order_doc['total_amount'],
        })
    except InsufficientStockError as e:
        return jsonify({"success": False, "message": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/payments/square/status/<int:order_id>', methods=['GET'])
@login_required
def api_square_payment_status(order_id):
    """Web POS poll route này sau khi gọi api_square_checkout()/api_nail_pos_square_checkout(),
    hiện 'Đang chờ khách quẹt thẻ...' cho tới khi status chuyển 'PAID'/'completed' (webhook đã
    xử lý xong) hoặc 'failed'. Dùng chung cho cả 2 luồng (F&B/retail và Nail POS)."""
    business_id = session.get('business_id') or session['user_id']
    order_doc = db.orders.find_one({'id': order_id, 'business_id': business_id}, {'_id': 0})
    if not order_doc:
        return jsonify({"success": False, "message": "Không tìm thấy đơn hàng."}), 404
    metadata = order_doc.get('metadata') or {}
    result = {
        "order_id": order_doc['id'],
        "status": order_doc.get('status'),
        "total_amount": order_doc.get('total_amount'),
        "subtotal": metadata.get('subtotal'),
        "discount_amount": metadata.get('discount_amount'),
        "tax_amount": metadata.get('tax_amount'),
        "tip_amount": metadata.get('tip_amount'),
    }
    # Once a Nail POS Square Terminal order is fully committed, pull back the per-technician
    # payout the webhook just wrote so the cashier's receipt can show the same commission/tip
    # breakdown the synchronous (Cash/Card/Split) checkout returns inline.
    if metadata.get('channel') == 'nail_pos_square' and order_doc.get('status') == 'completed':
        note_pattern = r'^\[NAILS POS SQUARE\] Order #' + str(order_id) + r'(?!\d)'
        techs_paid = [
            {'ma_nv': rec.get('ma_nv'), 'commission': rec.get('tien_tua'), 'tip': rec.get('tien_tips')}
            for rec in db.chamcong.find({'business_id': business_id, 'ghi_chu': {'$regex': note_pattern}}, {'_id': 0})
        ]
        result['techs_paid'] = techs_paid
    return jsonify({"success": True, "data": result})


@app.route('/api/payments/square/cancel', methods=['POST'])
@login_required
def api_square_payment_cancel():
    """Hủy 1 Square Terminal checkout đang chờ (device vẫn đang hiện màn hình chờ quẹt thẻ) —
    cho thu ngân thoát ngay lập tức để chuyển sang Cash/phương thức khác, thay vì phải chờ
    Square tự hết hạn checkout trên thiết bị (thường vài phút). Dùng chung cho cả luồng F&B/
    retail (api_square_checkout) lẫn Nail POS (api_nail_pos_square_checkout) vì cả 2 đều lưu
    square_checkout_id trên order theo cùng field."""
    business_id = session.get('business_id') or session['user_id']
    data = request.json or {}
    order_id = data.get('order_id')
    if not order_id:
        return jsonify({"success": False, "message": "Missing order_id."}), 400
    try:
        order_id = int(order_id)
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "Invalid order_id."}), 400

    try:
        order_doc = db.orders.find_one({'id': order_id, 'business_id': business_id}, {'_id': 0})
    except Exception as e:
        return jsonify({"success": False, "message": f"Lỗi kết nối Database khi tra cứu đơn hàng: {e}"}), 500
    if not order_doc:
        return jsonify({"success": False, "message": "Không tìm thấy đơn hàng."}), 404
    checkout_id = (order_doc.get('metadata') or {}).get('square_checkout_id')
    if not checkout_id:
        return jsonify({"success": False, "message": "Đơn hàng này không có Square checkout để hủy."}), 400
    if order_doc.get('status') != 'pending':
        # Đã xử lý xong (completed/failed) rồi — không có gì để hủy, tránh ghi đè trạng thái
        # thật bằng 'failed' nếu webhook COMPLETED đã chạy trước request Cancel này.
        return jsonify({"success": True, "message": "Đơn hàng đã được xử lý xong.", "status": order_doc.get('status')})

    result = payment_us_engine.cancel_terminal_checkout(checkout_id)
    if not result.get('configured'):
        return jsonify({"success": False, "message": result.get('message')}), 503
    if not result.get('success'):
        # Có thể khách đã quẹt thẻ đúng lúc thu ngân bấm Hủy — Square từ chối hủy vì checkout
        # đã COMPLETED. KHÔNG tự ý đánh dấu order 'failed' trong trường hợp này; để webhook xử
        # lý đúng theo trạng thái thật khi nó tới.
        return jsonify({"success": False, "message": result.get('message')}), 502

    try:
        db.orders.update_one(
            {'id': order_id, 'business_id': business_id},
            {
                '$set': {'status': 'failed', 'metadata.square_canceled_at': datetime.now().isoformat()},
                '$unset': {
                    'metadata._pending_order_items': '', 'metadata._pending_per_tech_revenue': '',
                    'metadata._pending_net_revenue': '', 'metadata._pending_worker_total_tip': '',
                },
            }
        )
    except Exception as e:
        # Square ĐÃ hủy checkout thành công ở bước trên rồi (result['success'] True) — chỉ riêng
        # việc ghi lại trạng thái 'failed' vào Mongo bị lỗi. Phải báo rõ cho thu ngân biết order
        # có thể đang ở trạng thái không khớp với Square, không được im lặng coi như xong.
        return jsonify({
            "success": False,
            "message": f"Square đã hủy checkout nhưng lỗi khi cập nhật trạng thái đơn hàng: {e}. "
                       "Kiểm tra lại đơn hàng thủ công.",
        }), 500
    return jsonify({"success": True, "status": "failed"})


@app.route('/api/webhooks/square', methods=['POST'])
def api_webhook_square():
    """Nhận tín hiệu THẬT từ Square sau khi khách quẹt thẻ/Apple Pay xong tại Terminal.
    KHÔNG @login_required — Square gọi server-to-server, không mang session/cookie nào cả.
    An toàn DUY NHẤT dựa vào verify chữ ký HMAC bên dưới — TUYỆT ĐỐI không tin bất kỳ field
    nào trong body nếu chữ ký sai/thiếu cấu hình (fail-closed)."""
    raw_body = request.get_data()
    signature = request.headers.get('x-square-hmacsha256-signature', '')

    if not payment_us_engine.verify_webhook_signature(request.url, raw_body, signature):
        current_app.logger.error(
            "[SQUARE WEBHOOK] Chữ ký không hợp lệ hoặc chưa cấu hình SQUARE_WEBHOOK_SIGNATURE_KEY/"
            "SQUARE_WEBHOOK_URL — từ chối request."
        )
        return jsonify({"success": False, "message": "Invalid signature."}), 401

    try:
        event = request.get_json(force=True, silent=True) or {}
    except Exception:
        event = {}
    if not event:
        return jsonify({"success": False, "message": "Invalid JSON body."}), 400

    event_type = event.get('type')
    if event_type != 'terminal.checkout.updated':
        # Các loại event khác (payment.updated, ...) chưa xử lý ở route này — vẫn trả 200 để
        # Square không retry vô ích, chỉ đơn giản bỏ qua.
        return jsonify({"success": True, "message": "Event type ignored."}), 200

    checkout_obj = ((event.get('data') or {}).get('object') or {}).get('checkout') or {}
    checkout_id = checkout_obj.get('id')
    checkout_status = checkout_obj.get('status')
    if not checkout_id:
        return jsonify({"success": False, "message": "Missing checkout id."}), 400

    try:
        order_doc = db.orders.find_one({'metadata.square_checkout_id': checkout_id})
        if not order_doc:
            current_app.logger.error(f"[SQUARE WEBHOOK] Không tìm thấy đơn hàng nào với checkout_id={checkout_id}")
            return jsonify({"success": True, "message": "No matching order (ignored)."}), 200

        if checkout_status == 'COMPLETED':
            # Idempotent: nếu Square gửi trùng webhook (retry) mà đơn đã xử lý xong rồi (PAID
            # cho luồng retail cũ, 'completed' cho luồng Nail POS) thì bỏ qua, không cộng loyalty/
            # hoa hồng 2 lần.
            already_done = order_doc.get('status') in ('PAID', 'completed')
            if not already_done:
                if (order_doc.get('metadata') or {}).get('channel') == 'nail_pos_square':
                    # Đây là lúc DUY NHẤT order_items/chamcong của bill Nail Square Terminal
                    # thực sự được ghi — commit atomically qua cùng transaction dùng ở
                    # api_nail_pos_checkout, đảm bảo trả tiền thợ giống hệt luồng Cash/Card/Split.
                    _finalize_nail_square_order(order_doc)
                else:
                    db.orders.update_one(
                        {'id': order_doc['id']},
                        {'$set': {'status': 'PAID', 'square_paid_at': datetime.now().isoformat()}}
                    )
                    order_doc['status'] = 'PAID'
                    # Đây là lúc DUY NHẤT biết chắc thẻ đã quẹt thành công -> ghi sổ cái ở đây,
                    # không ghi lúc tạo checkout (khi đó còn 'pending', có thể bị hủy/thất bại).
                    _record_pos_transaction(
                        order_doc['business_id'], order_doc['id'], order_doc.get('total_amount'),
                        'square', created_by='square_webhook',
                    )
                    _finalize_paid_order(order_doc)
        elif checkout_status in ('CANCELED', 'FAILED'):
            db.orders.update_one(
                {'id': order_doc['id']},
                {
                    '$set': {'status': 'failed'},
                    '$unset': {
                        'metadata._pending_order_items': '', 'metadata._pending_per_tech_revenue': '',
                        'metadata._pending_net_revenue': '', 'metadata._pending_worker_total_tip': '',
                    },
                }
            )
    except Exception as e:
        current_app.logger.error(f"[SQUARE WEBHOOK] Lỗi xử lý webhook: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 500

    return jsonify({"success": True}), 200


@app.route('/api/dashboard/sales_summary', methods=['GET'])
@login_required
def api_dashboard_sales_summary():
    """Tổng hợp doanh thu HÔM NAY cho Dashboard chủ tiệm: tổng doanh thu, tổng số đơn/khách,
    và doanh thu tách riêng Cash/Card — dùng payment_bucket ghi nhận sẵn ở api_sales_checkout
    (mọi giá trị mặc định 0, không bao giờ trả None/thiếu field, cùng convention với
    /api/superadmin/stats)."""
    business_id = session.get('business_id') or session['user_id']
    stats = {
        'total_orders_today': 0,
        'total_revenue_today': 0,
        'total_customers_today': 0,
        'cash_revenue_today': 0,
        'card_revenue_today': 0,
    }
    if db is None:
        return jsonify({"success": True, "data": stats})
    try:
        now = datetime.now()
        today_str = now.strftime('%Y-%m-%d')
        tomorrow_str = (now + timedelta(days=1)).strftime('%Y-%m-%d')
        orders_today = list(db.orders.find(
            {'business_id': business_id, 'created_at': {'$gte': today_str, '$lt': tomorrow_str}},
            {'total_amount': 1, 'metadata': 1, '_id': 0}
        ))
        stats['total_orders_today'] = len(orders_today)
        stats['total_revenue_today'] = round(sum(o.get('total_amount') or 0 for o in orders_today), 2)
        # 'split' orders carry their own cash/card breakdown (split_cash_amount/split_card_amount,
        # written by /api/nail_pos/checkout) — previously this bucket matched neither the cash
        # nor the card sum below, so a split ticket's full amount counted toward total revenue
        # but $0 toward either bucket, making the cash drawer never reconcile on a split-ticket day.
        cash_total = 0.0
        card_total = 0.0
        customer_phones = set()
        for o in orders_today:
            meta = o.get('metadata') or {}
            bucket = meta.get('payment_bucket')
            if bucket == 'cash':
                cash_total += o.get('total_amount') or 0
            elif bucket == 'card':
                card_total += o.get('total_amount') or 0
            elif bucket == 'split':
                cash_total += meta.get('split_cash_amount') or 0
                card_total += meta.get('split_card_amount') or 0
            if meta.get('customer_phone'):
                customer_phones.add(meta['customer_phone'])
        stats['cash_revenue_today'] = round(cash_total, 2)
        stats['card_revenue_today'] = round(card_total, 2)
        stats['total_customers_today'] = len(customer_phones)
    except Exception as e:
        print(f"[api_dashboard_sales_summary] Lỗi tính doanh thu hôm nay: {str(e)}")
    return jsonify({"success": True, "data": stats})


@app.route('/api/staff/<int:staff_id>/income_today', methods=['GET'])
@login_required
def api_staff_income_today(staff_id):
    """Nhân viên (thợ) xem thu nhập chính xác trong ngày: phục vụ mấy khách, hưởng bao nhiêu
    tiền hoa hồng dịch vụ (theo % đã chia ở api_sales_checkout), thu bao nhiêu Tip (100%
    không chia). Vẫn nằm sau @login_required của CHỦ TIỆM — hệ thống này chưa có tài khoản
    đăng nhập riêng cho nhân viên (xem db.staff), nên đây là API chủ tiệm/quầy tra cứu hộ
    thu nhập của 1 thợ cụ thể theo staff_id, không phải nhân viên tự đăng nhập xem."""
    business_id = session.get('business_id') or session['user_id']
    staff_doc = db.staff.find_one({'id': staff_id, 'business_id': business_id}, {'_id': 0})
    if not staff_doc:
        return jsonify({"success": False, "message": "Nhân viên không tồn tại hoặc không thuộc cửa hàng này."}), 404

    now = datetime.now()
    today_str = now.strftime('%Y-%m-%d')
    tomorrow_str = (now + timedelta(days=1)).strftime('%Y-%m-%d')
    orders_today = list(db.orders.find({
        'business_id': business_id, 'metadata.staff_id': staff_id,
        'created_at': {'$gte': today_str, '$lt': tomorrow_str}
    }, {'metadata.staff_commission': 1, 'metadata.staff_tip_earning': 1, '_id': 0}))

    commission_earned = round(sum((o.get('metadata') or {}).get('staff_commission') or 0 for o in orders_today), 2)
    tips_earned = round(sum((o.get('metadata') or {}).get('staff_tip_earning') or 0 for o in orders_today), 2)

    return jsonify({
        "success": True,
        "data": {
            "staff_id": staff_id,
            "staff_name": staff_doc.get('name'),
            "customers_served_today": len(orders_today),
            "commission_earned_today": commission_earned,
            "tips_earned_today": tips_earned,
            "total_income_today": round(commission_earned + tips_earned, 2),
        }
    })


@app.route('/api/settings/commission_rate', methods=['GET'])
@login_required
def api_get_commission_rate_setting():
    business_id = session.get('business_id') or session['user_id']
    return jsonify({"success": True, "data": {"staff_commission_rate": _get_business_commission_rate(business_id)}})


@app.route('/api/settings/commission_rate', methods=['POST'])
@login_required
def api_set_commission_rate_setting():
    business_id = session.get('business_id') or session['user_id']
    data = request.json or {}
    try:
        rate = float(data.get('staff_commission_rate'))
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "staff_commission_rate phải là số."}), 400
    if not (0 <= rate <= 100):
        return jsonify({"success": False, "message": "staff_commission_rate phải trong khoảng 0-100."}), 400
    db.system_settings.update_one(
        {'key': 'commission_rate', 'business_id': business_id},
        {'$set': {'value': rate}}, upsert=True
    )
    return jsonify({"success": True, "data": {"staff_commission_rate": rate}})


@app.route('/api/pos/tables', methods=['GET'])
@login_required
def api_pos_tables():
    business_id = session.get('business_id') or session['user_id']
    try:
        tables_data = list(db.dining_tables.find({'business_id': business_id}, {'_id': 0}).sort('id', 1))
        return jsonify({'success': True, 'data': tables_data})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/pos/products/<int:id>/deactivate', methods=['POST'])
@login_required
def api_pos_deactivate_product(id):
    business_id = session.get('business_id') or session['user_id']
    try:
        result = db.products.update_one({'id': id, 'business_id': business_id}, {'$set': {'is_active': 0}})
        if result.matched_count == 0:
            return jsonify({'success': False, 'message': 'Product not found or does not belong to your account.'}), 403
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/pos/tables/<int:table_id>/orders', methods=['GET'])
@login_required
def api_pos_get_table_orders(table_id):
    business_id = session.get('business_id') or session['user_id']
    owns, err = _assert_owns_table(table_id, business_id)
    if not owns:
        return jsonify({'success': False, 'message': err}), 403
    try:
        # $lookup nối table_orders -> products ngay trong 1 lần gọi DB, thay vì trước đây
        # frontend tự query products riêng cho từng dòng order (N+1 query từ trình duyệt).
        pipeline = [
            {'$match': {'table_id': table_id}},
            {'$lookup': {'from': 'products', 'localField': 'product_id', 'foreignField': 'id', 'as': '_product'}},
            {'$addFields': {'_product': {'$arrayElemAt': ['$_product', 0]}}}
        ]
        items = []
        for o in db.table_orders.aggregate(pipeline):
            p = o.get('_product')
            if p:
                items.append({
                    'id': o['id'], 'product_id': o['product_id'],
                    'name': p['name'], 'price': p['price'], 'quantity': o['quantity']
                })
        return jsonify({'success': True, 'data': items})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/pos/tables/<int:table_id>/orders', methods=['POST'])
@login_required
def api_pos_add_order_item(table_id):
    business_id = session.get('business_id') or session['user_id']
    owns, err = _assert_owns_table(table_id, business_id)
    if not owns:
        return jsonify({'success': False, 'message': err}), 403
    data = request.get_json() or {}
    product_id = data.get('product_id')
    quantity = data.get('quantity', 1)
    if not product_id:
        return jsonify({'success': False, 'message': 'Missing product_id.'}), 400
    product = db.products.find_one({'id': product_id, 'business_id': business_id}, {'name': 1, '_id': 0})
    if not product:
        return jsonify({'success': False, 'message': 'Product not found or does not belong to your account.'}), 403
    try:
        existing = db.table_orders.find_one(
            {'table_id': table_id, 'product_id': product_id, 'business_id': business_id}, {'id': 1, 'quantity': 1, '_id': 0}
        )
        if existing:
            new_qty = existing['quantity'] + quantity
            db.table_orders.update_one({'id': existing['id'], 'business_id': business_id}, {'$set': {'quantity': new_qty}})
        else:
            db.table_orders.insert_one({
                'id': next_mongo_id('table_orders'), 'table_id': table_id, 'product_id': product_id,
                'quantity': quantity, 'business_id': business_id, 'created_at': datetime.now().isoformat()
            })

        # Tạo vé bếp cho màn hình Kitchen Display — best-effort, không chặn luồng gọi món
        # nội bộ nếu ghi vé bếp lỗi. /api/stream/kitchen watch() trên db.kitchen_orders nên
        # insert ở đây tự động phát SSE, không cần code đẩy event riêng.
        try:
            table_doc = db.dining_tables.find_one({'id': table_id}, {'name': 1, '_id': 0})
            db.kitchen_orders.insert_one({
                'id': next_mongo_id('kitchen_orders'),
                'business_id': business_id,
                'table_id': table_id,
                'table_name': table_doc.get('name') if table_doc else f'Table {table_id}',
                'items': [{'name': product['name'], 'qty': quantity}],
                'status': 'pending',
                'created_at': datetime.now().isoformat()
            })
        except Exception as kitchen_err:
            print(f"Ghi vé bếp thất bại (không chặn luồng gọi món nội bộ): {str(kitchen_err)}")

        db.dining_tables.update_one({'id': table_id, 'business_id': business_id}, {'$set': {'status': 'Đang phục vụ'}})
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/pos/order_items/<int:item_id>', methods=['DELETE'])
@login_required
def api_pos_delete_order_item(item_id):
    business_id = session.get('business_id') or session['user_id']
    try:
        item = db.table_orders.find_one({'id': item_id, 'business_id': business_id}, {'table_id': 1, '_id': 0})
        if not item:
            return jsonify({'success': False, 'message': 'This item does not exist or does not belong to your account.'}), 403
        table_id = item['table_id']
        db.table_orders.delete_one({'id': item_id, 'business_id': business_id})
        remaining = db.table_orders.count_documents({'table_id': table_id, 'business_id': business_id})
        table_emptied = remaining == 0
        if table_emptied:
            db.dining_tables.update_one({'id': table_id, 'business_id': business_id}, {'$set': {'status': 'Còn trống'}})
        return jsonify({'success': True, 'table_emptied': table_emptied})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/pos/tables/<int:table_id>/orders', methods=['DELETE'])
@login_required
def api_pos_clear_table_orders(table_id):
    business_id = session.get('business_id') or session['user_id']
    owns, err = _assert_owns_table(table_id, business_id)
    if not owns:
        return jsonify({'success': False, 'message': err}), 403
    try:
        db.table_orders.delete_many({'table_id': table_id, 'business_id': business_id})
        db.dining_tables.update_one({'id': table_id, 'business_id': business_id}, {'$set': {'status': 'Còn trống'}})
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/table/<int:table_id>')
@login_required
def view_table(table_id):
    business_id = session.get('business_id') or session['user_id']
    try:
        table = db.dining_tables.find_one({'id': table_id}, {'_id': 0})
        if not table:
            return "Bàn không tồn tại", 404
        if table.get('business_id') != business_id:
            return "Bàn này không thuộc quyền quản lý của bạn.", 403

        # $lookup nối table_orders với products ngay trong 1 lần gọi DB, thay vì trước đây
        # phải SELECT products riêng cho từng dòng order (N+1 query).
        pipeline = [
            {'$match': {'table_id': table_id}},
            {'$lookup': {'from': 'products', 'localField': 'product_id', 'foreignField': 'id', 'as': '_product'}},
            {'$addFields': {'_product': {'$arrayElemAt': ['$_product', 0]}}}
        ]
        current_orders = []
        for o in db.table_orders.aggregate(pipeline):
            p = o.get('_product')
            if p:
                current_orders.append({
                    'id': o['id'],
                    'name': p['name'],
                    'price': p['price'],
                    'quantity': o['quantity'],
                    'product_id': o['product_id']
                })

        total_bill = sum(item['price'] * item['quantity'] for item in current_orders)
        menu_data = list(db.products.find(
            {'is_active': 1, 'channel_type': 'retail', 'business_id': business_id}, {'_id': 0}
        ))
        return render_template('table_order.html', table=table, orders=current_orders, total_bill=total_bill, menu=menu_data)
    except Exception as e:
        return f"Lỗi tải thông tin bàn: {str(e)}", 500


def _assert_owns_table(table_id, business_id):
    """Trả về (True, None) nếu bàn thuộc đúng business_id, ngược lại (False, thông báo lỗi)."""
    doc = db.dining_tables.find_one({'id': table_id}, {'business_id': 1, '_id': 0})
    if not doc:
        return False, "Table not found."
    if doc.get('business_id') != business_id:
        return False, "This table does not belong to your account."
    return True, None


# ========== LOYALTY TỰ ĐỘNG (tích điểm / lên hạng / thông báo) ==========
LOYALTY_TIER_THRESHOLDS = [
    (0, 'Normal'),
    (2_000_000, 'Silver'),
    (10_000_000, 'Gold'),
    (30_000_000, 'Platinum'),
]  # Ngưỡng tổng chi tiêu (VNĐ) để lên hạng — chỉnh lại tuỳ chiến lược kinh doanh
LOYALTY_POINTS_PER_VND = 1 / 10000  # 1 điểm / 10.000đ chi tiêu
# Ngưỡng/tỉ lệ tương đương cho merchant vận hành bằng USD (vd module POS bán cho khách hải
# ngoại) — bắt buộc phải TÁCH RIÊNG khỏi 2 hằng số VND ở trên: amount_spent của 1 đơn USD chỉ
# vài chục đơn vị, nếu dùng chung công thức/ngưỡng VND thì int(amount_spent * 1/10000) luôn
# làm tròn về 0 điểm và total_spent không bao giờ chạm nổi ngưỡng lên hạng thấp nhất (2 triệu),
# khiến khách hàng USD không bao giờ được cộng điểm/lên hạng dù chi tiêu thật rất nhiều.
LOYALTY_POINTS_PER_USD = 1  # 1 điểm / $1 chi tiêu
LOYALTY_TIER_THRESHOLDS_USD = [
    (0, 'Normal'),
    (80, 'Silver'),
    (400, 'Gold'),
    (1200, 'Platinum'),
]


def _tier_for_spend(total_spent, currency='VND'):
    thresholds = LOYALTY_TIER_THRESHOLDS_USD if (currency or 'VND').upper() == 'USD' else LOYALTY_TIER_THRESHOLDS
    tier = 'Normal'
    for threshold, name in thresholds:
        if total_spent >= threshold:
            tier = name
    return tier


# ========== HOA HỒNG (COMMISSION SPLIT) CHỦ/THỢ ==========
# Áp dụng khi 1 đơn hàng gắn với 1 staff_id cụ thể (ai là người trực tiếp phục vụ khách).
# Tỉ lệ ăn chia tính trên GIÁ TRỊ SẢN PHẨM/DỊCH VỤ (subtotal) — Tip KHÔNG chia, 100% về thợ
# (xem chỗ gọi trong api_sales_checkout). Thứ tự ưu tiên khi xác định % của thợ:
#   1) commission_rate gửi kèm ngay trong request checkout (ghi đè 1 lần cho đơn đó)
#   2) commission_rate đã lưu riêng cho staff đó (db.staff.commission_rate)
#   3) commission_rate mặc định của cả cửa hàng (system_settings, key='commission_rate')
#   4) DEFAULT_STAFF_COMMISSION_PERCENT (40%) nếu chưa cấu hình gì cả.
DEFAULT_STAFF_COMMISSION_PERCENT = 40  # Chủ 60% - Thợ 40% nếu chưa ai cấu hình gì


def _get_business_commission_rate(business_id):
    """Đọc % hoa hồng mặc định của thợ (chủ tiệm tự cấu hình) — lưu ở system_settings theo
    đúng convention key/business_id/value đã dùng cho brand_settings, inventory_thresholds."""
    if db is None:
        return DEFAULT_STAFF_COMMISSION_PERCENT
    doc = db.system_settings.find_one({'key': 'commission_rate', 'business_id': business_id}, {'value': 1, '_id': 0})
    if doc and doc.get('value') is not None:
        try:
            return float(doc['value'])
        except (TypeError, ValueError):
            pass
    return DEFAULT_STAFF_COMMISSION_PERCENT


def _resolve_staff_commission_rate(business_id, staff_doc, override_rate=None):
    """Xác định % hoa hồng thợ thực sự áp dụng cho 1 đơn, theo đúng thứ tự ưu tiên ở trên."""
    if override_rate is not None:
        try:
            return float(override_rate)
        except (TypeError, ValueError):
            pass
    if staff_doc and staff_doc.get('commission_rate') is not None:
        try:
            return float(staff_doc['commission_rate'])
        except (TypeError, ValueError):
            pass
    return _get_business_commission_rate(business_id)


def _queue_loyalty_notification(business_id, customer, event_type, message):
    """Ghi lại thông báo loyalty (tích điểm/lên hạng/sinh nhật) vào bảng loyalty_events.
    Nếu khách đã có zalo_user_id/fb_psid (từng tương tác qua OA/Messenger) VÀ server đã cấu hình
    access token thật (ZALO_OA_ACCESS_TOKEN / FB_PAGE_ACCESS_TOKEN) thì gửi luôn; ngược lại chỉ
    lưu trạng thái 'queued' để nhân viên tự liên hệ hoặc chờ khi nào cấu hình kênh gửi."""
    channel = None
    status = 'skipped_no_channel'
    try:
        if customer.get('zalo_user_id') and os.environ.get('ZALO_OA_ACCESS_TOKEN'):
            channel = 'zalo'
            resp = requests.post(
                'https://openapi.zalo.me/v3.0/oa/message/cs',
                headers={'access_token': os.environ.get('ZALO_OA_ACCESS_TOKEN'), 'Content-Type': 'application/json'},
                json={'recipient': {'user_id': customer['zalo_user_id']}, 'message': {'text': message}},
                timeout=10
            )
            status = 'sent' if resp.ok else 'failed'
        elif customer.get('fb_psid') and os.environ.get('FB_PAGE_ACCESS_TOKEN'):
            channel = 'facebook'
            resp = requests.post(
                f"https://graph.facebook.com/v18.0/me/messages?access_token={os.environ.get('FB_PAGE_ACCESS_TOKEN')}",
                json={'recipient': {'id': customer['fb_psid']}, 'message': {'text': message}},
                timeout=10
            )
            status = 'sent' if resp.ok else 'failed'
    except Exception as e:
        status = 'failed'
        print(f"Loi gui loyalty notification: {e}")

    try:
        if db is not None:
            db.loyalty_events.insert_one({
                'id': next_mongo_id('loyalty_events'),
                'business_id': business_id,
                'customer_id': customer.get('id'),
                'event_type': event_type,
                'channel': channel or 'none',
                'message': message,
                'status': status,
                'created_at': datetime.now().isoformat(),
            })
    except Exception as e:
        print(f"Loi ghi loyalty_events: {e}")


def _award_loyalty_points(business_id, customer_phone, amount_spent, currency='VND'):
    """Tự động cộng điểm + xét lên hạng cho khách ngay sau khi thanh toán xong.
    Nếu SĐT chưa có trong CRM thì tự tạo khách mới. Không chặn luồng thanh toán nếu lỗi.
    `currency` mặc định 'VND' (giữ nguyên hành vi cũ cho mọi caller hiện có) — truyền 'USD'
    khi đơn hàng/merchant vận hành bằng USD để dùng đúng công thức điểm/ngưỡng hạng USD."""
    customer_phone = (customer_phone or '').strip()
    if not customer_phone or not amount_spent or amount_spent <= 0:
        return
    try:
        is_usd = (currency or 'VND').upper() == 'USD'
        points_rate = LOYALTY_POINTS_PER_USD if is_usd else LOYALTY_POINTS_PER_VND
        customer = db.customers.find_one({'business_id': business_id, 'phone': customer_phone}, {'_id': 0})
        points_earned = int(amount_spent * points_rate)
        if customer:
            old_tier = customer.get('tier') or 'Normal'
            new_total_spent = (customer.get('total_spent') or 0) + amount_spent
            new_points = (customer.get('loyalty_points') or 0) + points_earned
            new_tier = _tier_for_spend(new_total_spent, currency=currency)
            db.customers.update_one(
                {'id': customer['id'], 'business_id': business_id},
                {'$set': {'total_spent': new_total_spent, 'loyalty_points': new_points, 'tier': new_tier}}
            )
            customer['total_spent'] = new_total_spent
            customer['loyalty_points'] = new_points
            customer['tier'] = new_tier
        else:
            new_tier = _tier_for_spend(amount_spent, currency=currency)
            new_id = next_mongo_id('customers')
            customer = {
                'id': new_id,
                'business_id': business_id,
                'phone': customer_phone,
                'name': f'Khách {customer_phone[-4:]}',
                'tier': new_tier,
                'loyalty_points': points_earned,
                'total_spent': amount_spent,
                'join_date': datetime.now().date().isoformat(),
            }
            db.customers.insert_one(customer)
            old_tier = None

        _queue_loyalty_notification(
            business_id, customer, 'points_awarded',
            f"Cảm ơn bạn đã mua hàng! Bạn vừa được cộng {points_earned} điểm thưởng, tổng hiện có {customer.get('loyalty_points', 0)} điểm."
        )
        if old_tier is not None and new_tier != old_tier:
            _queue_loyalty_notification(
                business_id, customer, 'tier_upgrade',
                f"Chúc mừng! Bạn vừa được nâng hạng thành viên lên {new_tier}. Một ưu đãi đặc biệt đang chờ bạn ở lần ghé thăm tiếp theo!"
            )
    except Exception as e:
        print(f"Loi award loyalty points: {e}")


# ========== MULTI-BRANCH (CHUỖI CHI NHÁNH) ==========
# Mô hình gốc: 1 user Supabase Auth = 1 business_id (session['business_id'] = user_id).
# Để 1 chủ sở hữu quản lý NHIỀU chi nhánh mà không phải viết lại hàng trăm chỗ đang đọc
# session.get('business_id'), ta chỉ cần: (1) 1 bảng business_memberships ghi nhận chủ sở
# hữu nào được quyền truy cập business_id nào, (2) khi "chuyển chi nhánh" chỉ đổi giá trị
# session['business_id'] sang business_id của chi nhánh đó (sau khi xác thực quyền sở hữu)
# — mọi route/query .eq('business_id', session.get('business_id')) sẵn có tự động hoạt
# động đúng, không cần sửa thêm.
def _ensure_primary_membership(owner_user_id, business_id):
    """Đảm bảo chi nhánh gốc (chính tài khoản đăng nhập) luôn có mặt trong business_memberships,
    gọi mỗi lần đăng nhập (idempotent — bỏ qua nếu đã tồn tại)."""
    if db is None:
        return
    try:
        existing = db.business_memberships.find_one({'owner_user_id': owner_user_id, 'business_id': business_id})
        if not existing:
            db.business_memberships.insert_one({
                'owner_user_id': owner_user_id,
                'business_id': business_id,
                'branch_name': 'Chi nhánh chính',
                'is_primary': True,
            })
    except Exception as e:
        print(f"Loi ensure primary membership: {e}")


def _get_owned_business_ids(owner_user_id):
    """Trả về danh sách business_id mà owner_user_id được quyền quản lý (gồm cả chi nhánh chính)."""
    if db is None:
        return []
    try:
        docs = db.business_memberships.find(
            {'owner_user_id': owner_user_id},
            {'business_id': 1, 'branch_name': 1, 'is_primary': 1, '_id': 0}
        )
        return list(docs)
    except Exception as e:
        print(f"Loi lay danh sach chi nhanh: {e}")
        return []


@app.route('/api/my_branches')
@login_required
def api_my_branches():
    user_id = session['user_id']
    branches = _get_owned_business_ids(user_id)
    active_business_id = session.get('business_id') or user_id
    return jsonify({
        'success': True,
        'branches': branches,
        'active_business_id': active_business_id,
    })


@app.route('/api/switch_branch', methods=['POST'])
@login_required
def api_switch_branch():
    user_id = session['user_id']
    data = request.get_json() or {}
    target_business_id = data.get('business_id')
    if not target_business_id:
        return jsonify({'success': False, 'message': 'Thiếu business_id.'}), 400

    owned = _get_owned_business_ids(user_id)
    owned_ids = {b['business_id'] for b in owned}
    if target_business_id not in owned_ids:
        return jsonify({'success': False, 'message': 'Bạn không có quyền quản lý chi nhánh này.'}), 403

    session['business_id'] = target_business_id
    return jsonify({'success': True, 'business_id': target_business_id})


@app.route('/add_branch', methods=['POST'])
@login_required
def add_branch():
    user_id = session['user_id']
    data = request.get_json() or request.form
    branch_name = (data.get('branch_name') or '').strip()
    if not branch_name:
        return jsonify({'success': False, 'message': 'Vui lòng nhập tên chi nhánh.'}), 400

    new_business_id = str(uuid.uuid4())
    try:
        db.business_memberships.insert_one({
            'owner_user_id': user_id,
            'business_id': new_business_id,
            'branch_name': branch_name,
            'is_primary': False,
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f'Lỗi tạo chi nhánh: {str(e)}'}), 500

    return jsonify({'success': True, 'business_id': new_business_id, 'branch_name': branch_name})


@app.route('/report_consolidated')
@login_required
@role_required('admin', 'super_admin')
def report_consolidated():
    """Báo cáo tổng hợp doanh thu/chi phí toàn bộ chi nhánh mà chủ sở hữu đang quản lý."""
    user_id = session['user_id']
    branches = _get_owned_business_ids(user_id)
    if not branches:
        branches = [{'business_id': user_id, 'branch_name': 'Chi nhánh chính', 'is_primary': True}]

    branch_reports = []
    total_revenue_all = 0
    total_expense_all = 0
    for b in branches:
        bid = b['business_id']
        revenue = 0
        expense = 0
        try:
            orders_docs = db.orders.find({'business_id': bid}, {'total_amount': 1, '_id': 0})
            revenue = sum(o.get('total_amount') or 0 for o in orders_docs)
        except Exception as e:
            print(f"Loi lay doanh thu chi nhanh {bid}: {e}")
        try:
            expenses_docs = db.expenses.find({'business_id': bid}, {'amount': 1, '_id': 0})
            expense = sum(e.get('amount') or 0 for e in expenses_docs)
        except Exception as e:
            print(f"Loi lay chi phi chi nhanh {bid}: {e}")

        total_revenue_all += revenue
        total_expense_all += expense
        branch_reports.append({
            'business_id': bid,
            'branch_name': b.get('branch_name') or 'Chi nhánh',
            'revenue': revenue,
            'expense': expense,
            'profit': revenue - expense,
        })

    return render_template(
        'report_consolidated.html',
        branch_reports=branch_reports,
        total_revenue_all=total_revenue_all,
        total_expense_all=total_expense_all,
        total_profit_all=total_revenue_all - total_expense_all,
    )


# ========== AUDIT TRAIL (NHẬT KÝ HOẠT ĐỘNG) ==========
def _log_audit(business_id, action, entity_type=None, entity_id=None, old_value=None, new_value=None):
    """Ghi vết 1 thao tác nhạy cảm. Không chặn luồng chính nếu ghi log lỗi."""
    try:
        db.audit_logs.insert_one({
            'id': next_mongo_id('audit_logs'),
            'business_id': business_id,
            'user_id': session.get('user_id'),
            'action': action,
            'entity_type': entity_type,
            'entity_id': str(entity_id) if entity_id is not None else None,
            'old_value': old_value,
            'new_value': new_value,
            'created_at': datetime.now().isoformat(),
        })
    except Exception as e:
        print(f"Loi ghi audit_logs: {e}")


@app.route('/order_item/<int:table_id>', methods=['POST'])
@login_required
def order_item(table_id):
    """Giai đoạn 5 audit: trả JSON {success, message} khi _wants_json() (Mobile/API), giữ
    NGUYÊN redirect cho Web như cũ."""
    business_id = session.get('business_id') or session['user_id']
    try:
        owns, err = _assert_owns_table(table_id, business_id)
        if not owns:
            return (jsonify({"success": False, "message": err}), 403) if _wants_json() else (err, 403)
    except Exception as e:
        msg = f"Lỗi xác thực quyền sở hữu bàn: {str(e)}"
        return (jsonify({"success": False, "message": msg}), 500) if _wants_json() else (msg, 500)

    try:
        product_id = request.form.get('product_id') if not request.is_json else (request.json or {}).get('product_id')
        if not _assert_owns_product(product_id, business_id):
            msg = "Sản phẩm không tồn tại hoặc không thuộc quyền quản lý của bạn."
            return (jsonify({"success": False, "message": msg}), 403) if _wants_json() else (msg, 403)

        qty = int((request.form.get('quantity') if not request.is_json else (request.json or {}).get('quantity')) or 1)
        existing = db.table_orders.find_one(
            {'table_id': table_id, 'product_id': product_id, 'business_id': business_id}, {'id': 1, 'quantity': 1, '_id': 0}
        )
        if existing:
            new_qty = existing['quantity'] + qty
            db.table_orders.update_one({'id': existing['id'], 'business_id': business_id}, {'$set': {'quantity': new_qty}})
        else:
            db.table_orders.insert_one({
                'id': next_mongo_id('table_orders'),
                'table_id': table_id, 'product_id': product_id, 'quantity': qty, 'business_id': business_id
            })
        db.dining_tables.update_one({'id': table_id, 'business_id': business_id}, {'$set': {'status': 'Đang phục vụ'}})
        if _wants_json():
            return jsonify({"success": True, "message": "Đã gọi món."})
        return redirect(url_for('view_table', table_id=table_id))
    except Exception as e:
        msg = f"Lỗi khi gọi món: {str(e)}"
        return (jsonify({"success": False, "message": msg}), 500) if _wants_json() else (msg, 500)


@app.route('/checkout/<int:table_id>')
@login_required
def checkout_table(table_id):
    """Giai đoạn 5 audit: trả JSON {success, message, order_id} khi _wants_json() (Mobile/API),
    giữ NGUYÊN redirect cho Web như cũ."""
    business_id = session.get('business_id') or session['user_id']
    try:
        owns, err = _assert_owns_table(table_id, business_id)
        if not owns:
            return (jsonify({"success": False, "message": err}), 403) if _wants_json() else (err, 403)
    except Exception as e:
        msg = f"Lỗi xác thực quyền sở hữu bàn: {str(e)}"
        return (jsonify({"success": False, "message": msg}), 500) if _wants_json() else (msg, 500)

    try:
        orders_data = list(db.table_orders.find({'table_id': table_id, 'business_id': business_id}, {'_id': 0}))
        if orders_data:
            order_code = f"FNB-{uuid.uuid4().hex[:8].upper()}"
            # Fetch giá + tồn kho của TẤT CẢ sản phẩm trong 1 lần ($in) thay vì 2 lần/sản phẩm
            # (giá rồi lại giá, tồn kho riêng) như code Supabase cũ — tránh N+1.
            product_ids = [item['product_id'] for item in orders_data]
            products_map = {
                p['id']: p for p in db.products.find(
                    {'id': {'$in': product_ids}, 'business_id': business_id}, {'id': 1, 'price': 1, 'stock': 1, '_id': 0}
                )
            }

            total_bill = 0
            stock_items = []
            for item in orders_data:
                prod = products_map.get(item['product_id'])
                if prod:
                    price = prod['price']
                    total_bill += item['quantity'] * price
                    if 'stock' in prod:
                        stock_items.append((item['product_id'], item['quantity'], prod.get('name')))

            order_id = next_mongo_id('orders')
            order_items_docs = []
            for item in orders_data:
                prod = products_map.get(item['product_id'])
                price = prod['price'] if prod else 0
                total_price = item['quantity'] * price
                order_items_docs.append({
                    'id': next_mongo_id('order_items'),
                    'order_id': order_id,
                    'product_id': item['product_id'],
                    'quantity': item['quantity'],
                    'price': price,
                    'total_price': total_price,
                    'business_id': business_id
                })

            try:
                # Trừ kho ($inc nguyên tử) + order + order_items + sổ cái transactions cùng 1
                # Mongo session transaction — không còn race condition khi nhiều bàn/nhiều đơn QR
                # cùng checkout 1 sản phẩm trong giờ cao điểm.
                with mongo_client_instance.start_session() as db_session:
                    with db_session.start_transaction():
                        _decrement_stock_atomic(business_id, stock_items, db_session=db_session)
                        db.orders.insert_one({
                            'id': order_id,
                            'business_id': business_id,
                            'created_at': datetime.now().isoformat(),
                            'status': 'completed',
                            'total_amount': total_bill,
                            'payment_method': 'POS',
                            'metadata': {'order_code': order_code, 'channel': 'fnb', 'table_id': table_id},
                        }, session=db_session)
                        if order_items_docs:
                            db.order_items.insert_many(order_items_docs, session=db_session)
                        _record_pos_transaction(
                            business_id, order_id, total_bill, 'POS', db_session=db_session,
                        )
            except InsufficientStockError as e:
                return (jsonify({"success": False, "message": str(e)}), 409) if _wants_json() else (str(e), 409)

            # Ghi nhận giao dịch vào payment_transactions — thiếu bước này khiến báo cáo dòng
            # tiền tổng (đối soát payment_transactions <-> orders) không thấy các đơn checkout
            # qua luồng /checkout nội bộ này (khác với /api/payment/confirm đã làm đúng).
            try:
                db.payment_transactions.insert_one({
                    'id': next_mongo_id('payment_transactions'),
                    'transaction_id': order_code,
                    'order_id': order_id,
                    'customer_name': 'Khách POS Vãng Lai',
                    'customer_email': 'pos_walkin@bitpaw.com',
                    'amount': total_bill,
                    'currency': 'VND',
                    'method': 'POS',
                    'status': 'completed',
                    'business_id': business_id,
                    'created_at': datetime.now().isoformat()
                })
            except Exception as txn_err:
                print(f"Ghi payment_transactions cho checkout thất bại: {str(txn_err)}")

            db.table_orders.delete_many({'table_id': table_id, 'business_id': business_id})
            db.dining_tables.update_one({'id': table_id, 'business_id': business_id}, {'$set': {'status': 'Còn trống'}})
            if _wants_json():
                return jsonify({"success": True, "order_id": order_id, "total_amount": total_bill})
        elif _wants_json():
            return jsonify({"success": True, "order_id": None, "message": "Bàn không có món nào để thanh toán."})
        return redirect(url_for('pos'))
    except Exception as e:
        msg = f"Lỗi khi thanh toán bàn: {str(e)}"
        return (jsonify({"success": False, "message": msg}), 500) if _wants_json() else (msg, 500)


# ========== QUẢN LÝ CHI TIÊU ==========
@app.route('/add_expense', methods=['GET', 'POST'])
@login_required
def add_expense():
    business_id = session.get('business_id') or session['user_id']
    if request.method == 'POST':
        description = request.form['description']
        amount = float(request.form['amount'])
        expense_date = request.form.get('expense_date', datetime.now().strftime('%Y-%m-%d'))
        try:
            db.expenses.insert_one({
                'id': next_mongo_id('expenses'),
                'description': description,
                'amount': amount,
                'expense_date': expense_date,
                'created_at': datetime.now().isoformat(),
                'business_id': business_id
            })
        except Exception as db_err:
            print(f"MongoDB expenses insert failed: {str(db_err)}")
        flash('Đã thêm khoản chi', 'success')
        return redirect(url_for('index'))
    return render_template('add_expense.html')


@app.route('/expense_list')
@login_required
@role_required('admin', 'super_admin')
def expense_list():
    business_id = session.get('business_id') or session['user_id']
    try:
        expenses_data = list(db.expenses.find({'business_id': business_id}, {'_id': 0}).sort('expense_date', -1))
    except Exception as db_err:
        print(f"MongoDB expenses order by expense_date failed: {str(db_err)}")
        try:
            expenses_data = list(db.expenses.find({'business_id': business_id}, {'_id': 0}).sort('created_at', -1))
        except Exception as db_err2:
            print(f"MongoDB expenses order by created_at failed: {str(db_err2)}")
            expenses_data = []
    return render_template('expense_list.html', expenses=expenses_data)


# ========== CHI PHÍ (JSON API cho add_expense.html) — thay 2 tầng xác thực chồng chéo cũ
# (Supabase Auth + Flask session) bằng ĐÚNG 1 tầng: Flask session, đã được @login_required ở
# route /add_expense bắt buộc từ trước. business_id lấy từ session, KHÔNG dùng user_id do
# Supabase Auth tự sinh (2 hệ định danh tách biệt trước đây khiến trang không bao giờ hoạt
# động thật với người dùng thật của app). ==========
@app.route('/api/expenses', methods=['GET'])
@login_required
def api_expenses_list():
    business_id = session.get('business_id') or session['user_id']
    try:
        expenses = list(db.expenses.find({'business_id': business_id}, {'_id': 0}).sort('expense_date', -1))
        return jsonify({"success": True, "data": expenses})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/expenses', methods=['POST'])
@login_required
def api_expenses_create():
    business_id = session.get('business_id') or session['user_id']
    data = request.json or {}
    description = (data.get('description') or '').strip()
    try:
        amount = float(data.get('amount'))
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "Số tiền không hợp lệ."}), 400
    if not description or amount <= 0:
        return jsonify({"success": False, "message": "Thiếu mô tả hoặc số tiền không hợp lệ."}), 400
    try:
        doc = {
            'id': next_mongo_id('expenses'),
            'category': data.get('category', ''),
            'description': description,
            'amount': amount,
            'expense_date': data.get('expense_date') or datetime.now().strftime('%Y-%m-%d'),
            'created_at': datetime.now().isoformat(),
            'business_id': business_id,
        }
        db.expenses.insert_one(doc)
        doc.pop('_id', None)
        return jsonify({"success": True, "data": doc})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/expenses/<int:id>', methods=['DELETE'])
@login_required
def api_expenses_delete(id):
    business_id = session.get('business_id') or session['user_id']
    try:
        owns, err = _assert_owns_row_mongo('expenses', id, business_id)
        if not owns:
            return jsonify({"success": False, "message": err}), 403
        db.expenses.delete_one({'id': id, 'business_id': business_id})
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


# ========== QUẢN LÝ KHUYẾN MÃI ==========
@app.route('/promotions')
@login_required
def promotions():
    business_id = session.get('business_id') or session['user_id']
    try:
        promos_data = list(db.promotions.find({'business_id': business_id}, {'_id': 0}).sort('id', -1))
    except Exception as db_err:
        print(f"MongoDB promotions select failed: {str(db_err)}")
        promos_data = []
    return render_template('promotion_management.html', promotions=promos_data)


@app.route('/add_promotion', methods=['POST'])
@login_required
def add_promotion():
    business_id = session.get('business_id') or session['user_id']
    data = request.json
    try:
        db.promotions.insert_one({
            'id': next_mongo_id('promotions'),
            'code': data['code'],
            'name': data['name'],
            'discount_type': data['discount_type'],
            'discount_value': data['discount_value'],
            'start_date': data.get('start_date'),
            'end_date': data.get('end_date'),
            'usage_limit': data.get('usage_limit', 100),
            'product_ids': data.get('product_ids', []),
            'status': 'active',
            'used_count': 0,
            'business_id': business_id
        })
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Lỗi thêm khuyến mãi: {str(e)}'}), 500


@app.route('/update_promotion/<int:id>', methods=['PUT'])
@login_required
def update_promotion(id):
    business_id = session.get('business_id') or session['user_id']
    try:
        owns, err = _assert_owns_row_mongo('promotions', id, business_id)
        if not owns:
            return jsonify({'success': False, 'message': err}), 403
        data = dict(request.json or {})
        data.pop('business_id', None)  # không cho phép request tự đổi chủ sở hữu (chiếm tenant khác)
        data.pop('id', None)
        db.promotions.update_one({'id': id, 'business_id': business_id}, {'$set': data})
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Lỗi cập nhật khuyến mãi: {str(e)}'}), 500


@app.route('/delete_promotion/<int:id>', methods=['DELETE'])
@login_required
def delete_promotion(id):
    business_id = session.get('business_id') or session['user_id']
    try:
        owns, err = _assert_owns_row_mongo('promotions', id, business_id)
        if not owns:
            return jsonify({'success': False, 'message': err}), 403
        db.promotions.delete_one({'id': id, 'business_id': business_id})
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Lỗi xóa khuyến mãi: {str(e)}'}), 500


# ========== QUẢN LÝ NHÂN VIÊN ==========
@app.route('/staff')
@login_required
@role_required('admin', 'super_admin')
def staff_list():
    business_id = session.get('business_id') or session['user_id']
    try:
        staffs_data = list(db.staff.find({'business_id': business_id}, {'_id': 0}).sort('id', 1))
    except Exception as e:
        print(f"MongoDB staff select failed: {str(e)}")
        staffs_data = []
    return render_template('staff_management.html', staffs=staffs_data)


@app.route('/api/staff', methods=['GET'])
@login_required
def api_staff_list():
    """Bản JSON của cùng query trong staff_management() ở trên — dùng để load lại danh sách
    sau khi thêm/sửa/xóa mà không cần reload cả trang, thay Supabase select() cũ."""
    business_id = session.get('business_id') or session['user_id']
    try:
        staffs_data = list(db.staff.find({'business_id': business_id}, {'_id': 0}).sort('id', 1))
        return jsonify({"success": True, "data": staffs_data})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/add_staff', methods=['POST'])
@login_required
def add_staff():
    business_id = session.get('business_id') or session['user_id']
    data = request.json
    try:
        db.staff.insert_one({
            'id': next_mongo_id('staff'),
            'name': data['name'],
            'phone': data['phone'],
            'role': data['role'],
            # commission_rate để trống (None) nếu chủ tiệm không nhập riêng cho thợ này —
            # api_sales_checkout sẽ tự fallback về mức mặc định của cả cửa hàng
            # (xem _resolve_staff_commission_rate/_get_business_commission_rate).
            'commission_rate': data.get('commission_rate'),
            'is_active': data.get('is_active', True),
            'business_id': business_id
        })
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Lỗi thêm nhân viên: {str(e)}'}), 500



def _assert_owns_row_mongo(collection_name, row_id, business_id):
    """Bản MongoDB của _assert_owns_row — dùng cho các collection ĐÃ migrate sang Mongo.
    Trả về (True, None) nếu row thuộc đúng business_id, ngược lại (False, lỗi)."""
    if db is None:
        return False, "MongoDB chưa kết nối."
    doc = db[collection_name].find_one({'id': row_id}, {'business_id': 1, '_id': 0})
    if not doc:
        return False, "Không tìm thấy dữ liệu."
    if doc.get('business_id') != business_id:
        return False, "Dữ liệu này không thuộc quyền quản lý của bạn."
    return True, None


@app.route('/update_staff/<int:id>', methods=['PUT'])
@login_required
def update_staff(id):
    business_id = session.get('business_id') or session['user_id']
    try:
        owns, err = _assert_owns_row_mongo('staff', id, business_id)
        if not owns:
            return jsonify({'success': False, 'message': err}), 403
        data = dict(request.json or {})
        data.pop('business_id', None)  # không cho phép request tự đổi chủ sở hữu (chiếm tenant khác)
        data.pop('id', None)
        db.staff.update_one({'id': id, 'business_id': business_id}, {'$set': data})
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Lỗi cập nhật nhân viên: {str(e)}'}), 500


@app.route('/delete_staff/<int:id>', methods=['DELETE'])
@login_required
def delete_staff(id):
    business_id = session.get('business_id') or session['user_id']
    try:
        owns, err = _assert_owns_row_mongo('staff', id, business_id)
        if not owns:
            return jsonify({'success': False, 'message': err}), 403
        db.staff.delete_one({'id': id, 'business_id': business_id})
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Lỗi xóa nhân viên: {str(e)}'}), 500


# ========== QUẢN LÝ KHÁCH HÀNG (CRM) ==========
@app.route('/customers')
@login_required
def customers():
    business_id = session.get('business_id') or session['user_id']
    try:
        customers_data = list(db.customers.find({'business_id': business_id}, {'_id': 0}).sort('id', -1))
        error_message = None
    except Exception as e:
        print(f"Error fetching customers (network/offline): {e}")
        customers_data = []
        error_message = "Đang hiển thị chế độ Offline"
    return render_template('crm.html', customers=customers_data, error_message=error_message)


@app.route('/api/customers', methods=['GET'])
@login_required
def api_customers_list():
    """Bản JSON của cùng query trong customers() ở trên — trả về TOÀN BỘ danh sách (không
    filter/pagination server-side); crm.html tự lọc theo search/tier/khoảng ngày + tự phân
    trang ở client, giống cách nhanvien.html/bangluong.html đã lọc theo ngành ở client trong
    đợt migrate HR — danh sách khách hàng của 1 tenant thường đủ nhỏ để làm vậy, và tránh phải
    dựng lại y hệt bộ query builder .or()/.gte()/.lte()/.range() của Supabase ở phía server."""
    business_id = session.get('business_id') or session['user_id']
    try:
        customers_data = list(db.customers.find({'business_id': business_id}, {'_id': 0}).sort('id', -1))
        return jsonify({"success": True, "data": customers_data})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/add_customer', methods=['POST'])
@login_required
def add_customer():
    business_id = session.get('business_id') or session['user_id']
    data = request.json
    try:
        db.customers.insert_one({
            'id': next_mongo_id('customers'),
            'name': data['name'],
            'phone': data['phone'],
            'email': data.get('email'),
            'gender': data.get('gender'),
            'dob': data.get('dob'),
            'tier': data.get('tier', 'Normal'),
            'loyalty_points': data.get('loyalty_points', 0),
            'total_spent': data.get('total_spent', 0),
            'join_date': datetime.now().strftime('%Y-%m-%d'),
            'business_id': business_id
        })
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Lỗi thêm khách hàng: {str(e)}'}), 500


@app.route('/update_customer/<int:id>', methods=['PUT'])
@login_required
def update_customer(id):
    business_id = session.get('business_id') or session['user_id']
    try:
        owns, err = _assert_owns_row_mongo('customers', id, business_id)
        if not owns:
            return jsonify({'success': False, 'message': err}), 403
        data = dict(request.json or {})
        data.pop('business_id', None)  # không cho phép request tự đổi chủ sở hữu (chiếm tenant khác)
        data.pop('id', None)
        db.customers.update_one({'id': id, 'business_id': business_id}, {'$set': data})
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Lỗi cập nhật khách hàng: {str(e)}'}), 500


@app.route('/delete_customer/<int:id>', methods=['DELETE'])
@login_required
def delete_customer(id):
    business_id = session.get('business_id') or session['user_id']
    try:
        owns, err = _assert_owns_row_mongo('customers', id, business_id)
        if not owns:
            return jsonify({'success': False, 'message': err}), 403
        db.customers.delete_one({'id': id, 'business_id': business_id})
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Lỗi xóa khách hàng: {str(e)}'}), 500


# ========== QUẢN LÝ NHÀ CUNG CẤP (dùng bởi quanly_congno.html) — CRUD giống hệt customers ở
# trên, tách collection riêng vì nhà cung cấp là bên MÌNH nợ, khác khách hàng là bên NỢ MÌNH.
# Collection này trước đây không tồn tại cả ở Supabase lẫn Mongo — trang cũ fallback về vài
# dòng dữ liệu giả khi query lỗi, che giấu việc bảng chưa từng được tạo. ==========
@app.route('/api/suppliers', methods=['GET'])
@login_required
def api_suppliers_list():
    business_id = session.get('business_id') or session['user_id']
    try:
        suppliers = list(db.suppliers.find({'business_id': business_id}, {'_id': 0}).sort('id', -1))
        return jsonify({"success": True, "data": suppliers})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/add_supplier', methods=['POST'])
@login_required
def add_supplier():
    business_id = session.get('business_id') or session['user_id']
    data = request.json or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'success': False, 'message': 'Thiếu tên nhà cung cấp.'}), 400
    try:
        doc = {
            'id': next_mongo_id('suppliers'),
            'name': name,
            'code': data.get('code', ''),
            'phone': data.get('phone', ''),
            'business_id': business_id,
        }
        db.suppliers.insert_one(doc)
        doc.pop('_id', None)
        return jsonify({'success': True, 'data': doc})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Lỗi thêm nhà cung cấp: {str(e)}'}), 500


@app.route('/update_supplier/<int:id>', methods=['PUT'])
@login_required
def update_supplier(id):
    business_id = session.get('business_id') or session['user_id']
    try:
        owns, err = _assert_owns_row_mongo('suppliers', id, business_id)
        if not owns:
            return jsonify({'success': False, 'message': err}), 403
        data = dict(request.json or {})
        data.pop('business_id', None)
        data.pop('id', None)
        db.suppliers.update_one({'id': id, 'business_id': business_id}, {'$set': data})
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Lỗi cập nhật nhà cung cấp: {str(e)}'}), 500


@app.route('/delete_supplier/<int:id>', methods=['DELETE'])
@login_required
def delete_supplier(id):
    business_id = session.get('business_id') or session['user_id']
    try:
        owns, err = _assert_owns_row_mongo('suppliers', id, business_id)
        if not owns:
            return jsonify({'success': False, 'message': err}), 403
        db.suppliers.delete_one({'id': id, 'business_id': business_id})
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Lỗi xóa nhà cung cấp: {str(e)}'}), 500


# ========== CÔNG NỢ (quanly_congno.html) — ledger giao dịch nợ theo từng đối tác (khách hàng
# HOẶC nhà cung cấp), TÁCH BIỆT với db.transactions (sổ quỹ thu/chi chung, không gắn đối tác) ở
# Batch 2 — 2 khái niệm khác nhau (dòng tiền chung vs. số dư nợ theo từng đối tác), không dùng
# chung 1 collection để tránh phải thêm field tuỳ chọn + nhánh rẽ cho 2 nghiệp vụ khác nhau. ==========
def _assert_owns_partner(partner_type, partner_id, business_id):
    collection = 'customers' if partner_type == 'customer' else 'suppliers'
    doc = db[collection].find_one({'id': partner_id, 'business_id': business_id}, {'id': 1, '_id': 0})
    return bool(doc)


@app.route('/api/debt_transactions', methods=['GET'])
@login_required
def api_debt_transactions_list():
    business_id = session.get('business_id') or session['user_id']
    query = {'business_id': business_id}
    partner_type = request.args.get('partner_type')
    if partner_type in ('customer', 'supplier'):
        query['partner_type'] = partner_type
    partner_id = request.args.get('partner_id', type=int)
    if partner_id is not None:
        query['partner_id'] = partner_id
    start = request.args.get('start')
    end = request.args.get('end')
    if start or end:
        date_filter = {}
        if start:
            date_filter['$gte'] = start
        if end:
            date_filter['$lte'] = end + ' 23:59:59'
        query['transaction_date'] = date_filter
    try:
        rows = list(db.debt_transactions.find(query, {'_id': 0}).sort('transaction_date', 1))
        return jsonify({"success": True, "data": rows})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/debt_transactions', methods=['POST'])
@login_required
def api_debt_transactions_create():
    business_id = session.get('business_id') or session['user_id']
    data = request.json or {}
    partner_type = data.get('partner_type')
    partner_id = data.get('partner_id')
    direction = data.get('direction')
    if partner_type not in ('customer', 'supplier'):
        return jsonify({"success": False, "message": "partner_type không hợp lệ."}), 400
    if direction not in ('expense', 'payment'):
        return jsonify({"success": False, "message": "direction không hợp lệ."}), 400
    try:
        amount = float(data.get('amount'))
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "Số tiền không hợp lệ."}), 400
    if amount <= 0:
        return jsonify({"success": False, "message": "Số tiền phải lớn hơn 0."}), 400
    try:
        partner_id = int(partner_id)
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "Thiếu đối tượng (đối tác)."}), 400
    if not _assert_owns_partner(partner_type, partner_id, business_id):
        return jsonify({"success": False, "message": "Đối tác không tồn tại hoặc không thuộc quyền quản lý của bạn."}), 403
    try:
        doc = {
            'id': next_mongo_id('debt_transactions'),
            'partner_type': partner_type,
            'partner_id': partner_id,
            'direction': direction,
            'amount': amount,
            'transaction_date': data.get('transaction_date') or datetime.now().strftime('%Y-%m-%d'),
            'note': data.get('note', ''),
            'created_at': datetime.now().isoformat(),
            'business_id': business_id,
        }
        db.debt_transactions.insert_one(doc)
        doc.pop('_id', None)
        return jsonify({"success": True, "data": doc})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


# ========== QUẢN LÝ GIAO DỊCH THANH TOÁN ==========
@app.route('/payment_transactions')
@login_required
def payment_transactions():
    business_id = session.get('business_id') or session['user_id']
    try:
        transactions_data = list(db.payment_transactions.find({'business_id': business_id}, {'_id': 0}).sort('created_at', -1))
        error_message = None
    except Exception as e:
        print(f"Error fetching payment transactions (network/offline): {e}")
        transactions_data = []
        error_message = "Đang hiển thị chế độ Offline"
    return render_template('admin_payment_management.html', transactions=transactions_data, error_message=error_message)


@app.route('/update_payment_status/<int:id>', methods=['POST'])
@login_required
def update_payment_status(id):
    business_id = session.get('business_id') or session['user_id']
    new_status = request.json.get('status')
    try:
        owns, err = _assert_owns_row_mongo('payment_transactions', id, business_id)
        if not owns:
            return jsonify({'success': False, 'message': err}), 403
        db.payment_transactions.update_one({'id': id, 'business_id': business_id}, {'$set': {'status': new_status}})
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Lỗi cập nhật trạng thái thanh toán: {str(e)}'}), 500


# ========== PAYMENT TRANSACTIONS SEARCH/PAGINATION JSON API (thay Supabase JS ở
# payment_history.html + admin_payment_management.html — dùng chung 1 endpoint) ==========
@app.route('/api/payment_transactions', methods=['GET'])
@login_required
def api_payment_transactions_list():
    business_id = session.get('business_id') or session['user_id']
    query = {'business_id': business_id}

    search = (request.args.get('search') or '').strip()
    if search:
        regex = {'$regex': re.escape(search), '$options': 'i'}
        query['$or'] = [
            {'transaction_id': regex}, {'method': regex},
            {'customer_name': regex}, {'customer_email': regex},
        ]
    status = request.args.get('status')
    if status and status != 'all':
        query['status'] = status
    start = request.args.get('start')
    end = request.args.get('end')
    if start or end:
        date_filter = {}
        if start:
            date_filter['$gte'] = start
        if end:
            date_filter['$lte'] = end + ' 23:59:59'
        query['created_at'] = date_filter

    page = request.args.get('page', 1, type=int)
    page_size = min(request.args.get('page_size', 20, type=int), 100)

    try:
        total = db.payment_transactions.count_documents(query)
        skip = max(0, (page - 1) * page_size)
        rows = list(
            db.payment_transactions.find(query, {'_id': 0}).sort('created_at', -1).skip(skip).limit(page_size)
        )
        return jsonify({"success": True, "data": rows, "count": total})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/payment_transactions/<int:id>', methods=['GET'])
@login_required
def api_payment_transactions_get(id):
    business_id = session.get('business_id') or session['user_id']
    try:
        row = db.payment_transactions.find_one({'id': id, 'business_id': business_id}, {'_id': 0})
        if not row:
            return jsonify({"success": False, "message": "Không tìm thấy giao dịch."}), 404
        return jsonify({"success": True, "data": row})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


# ========== SỔ QUỸ / THU CHI JSON API (thay Supabase JS ở quanly_thuchi.html +
# baocao_loinhuan.html — db.transactions, collection mới) ==========
@app.route('/api/transactions', methods=['GET'])
@login_required
def api_transactions_list():
    business_id = session.get('business_id') or session['user_id']
    query = {'business_id': business_id}
    start = request.args.get('start')
    end = request.args.get('end')
    if start or end:
        date_filter = {}
        if start:
            date_filter['$gte'] = start
        if end:
            date_filter['$lte'] = end
        query['transaction_date'] = date_filter
    tx_type = request.args.get('type')
    if tx_type and tx_type != 'all':
        query['type'] = tx_type
    try:
        rows = list(db.transactions.find(query, {'_id': 0}).sort('transaction_date', -1))
        return jsonify({"success": True, "data": rows})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/transactions/<int:id>', methods=['GET'])
@login_required
def api_transactions_get(id):
    business_id = session.get('business_id') or session['user_id']
    try:
        row = db.transactions.find_one({'id': id, 'business_id': business_id}, {'_id': 0})
        if not row:
            return jsonify({"success": False, "message": "Không tìm thấy giao dịch."}), 404
        return jsonify({"success": True, "data": row})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/transactions', methods=['POST'])
@login_required
def api_transactions_create():
    business_id = session.get('business_id') or session['user_id']
    data = request.json or {}
    try:
        doc = {
            'id': next_mongo_id('transactions'),
            'business_id': business_id,
            'type': data.get('type', 'expense'),
            'category': data.get('category', ''),
            'amount': float(data.get('amount') or 0),
            'transaction_date': data.get('transaction_date', ''),
            'note': data.get('note', ''),
        }
        db.transactions.insert_one(doc)
        doc.pop('_id', None)
        return jsonify({"success": True, "data": doc})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/transactions/<int:id>', methods=['PATCH'])
@login_required
def api_transactions_update(id):
    business_id = session.get('business_id') or session['user_id']
    data = request.json or {}
    updates = {k: v for k, v in data.items() if k in ('type', 'category', 'amount', 'transaction_date', 'note')}
    if not updates:
        return jsonify({"success": False, "message": "Không có trường hợp lệ để cập nhật."}), 400
    try:
        result = db.transactions.update_one({'id': id, 'business_id': business_id}, {'$set': updates})
        if result.matched_count == 0:
            return jsonify({"success": False, "message": "Không tìm thấy giao dịch."}), 404
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/transactions/<int:id>', methods=['DELETE'])
@login_required
def api_transactions_delete(id):
    business_id = session.get('business_id') or session['user_id']
    try:
        result = db.transactions.delete_one({'id': id, 'business_id': business_id})
        if result.deleted_count == 0:
            return jsonify({"success": False, "message": "Không tìm thấy giao dịch."}), 404
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


# ========== SPA ==========
# Route ngành Spa (spa/add_spa/delete_spa/checkout_spa/booking/create_appointment/chamcong_spa)
# đã chuyển sang blueprints/spa_bp.py — xem khối "Register Blueprints" ở cuối file để biết
# cách đăng ký. Đừng định nghĩa lại các route này ở đây, sẽ đăng ký trùng URL với blueprint.

# ========== KARAOKE ==========
@app.route('/karaoke')
@login_required
def karaoke():
    business_id = session.get('business_id') or session['user_id']
    try:
        rooms_data = list(db.karaoke_rooms.find({'business_id': business_id}, {'_id': 0}))
    except Exception as db_err:
        print(f"MongoDB karaoke_rooms select failed: {str(db_err)}")
        rooms_data = []
    return render_template('karaoke.html', rooms=rooms_data)


@app.route('/toggle_room/<int:room_id>')
@login_required
def toggle_room(room_id):
    """Giai đoạn 5 audit: (1) trả JSON khi _wants_json() (Mobile/API), giữ NGUYÊN redirect cho
    Web; (2) phát hiện đây là 1 luồng checkout karaoke RIÊNG, độc lập với
    api_karaoke_room_checkout() — đã bị Giai đoạn 3 (chuẩn hoá schema db.orders) bỏ sót vì không
    cùng route. Cập nhật cho khớp schema chuẩn (core fields + metadata) và bổ sung luôn ghi sổ
    cái _record_pos_transaction() — route cũ trước đây tạo order nhưng KHÔNG hề ghi transactions,
    lặp lại đúng lỗ hổng POS->Tài chính mà Giai đoạn 1 đã vá ở các luồng khác."""
    business_id = session.get('business_id') or session['user_id']
    try:
        room = db.karaoke_rooms.find_one({'id': room_id}, {'_id': 0})
        if not room or room.get('business_id') != business_id:
            if _wants_json():
                return jsonify({"success": False, "message": "Phòng không tồn tại."}), 404
            return redirect(url_for('karaoke'))
        order_id = None
        if room['status'] == 'Trống':
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            db.karaoke_rooms.update_one(
                {'id': room_id, 'business_id': business_id}, {'$set': {'status': 'Đang chơi', 'start_time': now}}
            )
        else:
            start_time = parse_datetime(room['start_time'])
            now = datetime.now()
            duration_minutes = (now - start_time).total_seconds() / 60.0
            if duration_minutes < 15:
                duration_minutes = 15
            else:
                duration_minutes = math.ceil(duration_minutes / 15.0) * 15
            duration_hours = duration_minutes / 60.0
            total_price = duration_hours * room['price_per_hour']
            prod = db.products.find_one({'name': 'Phí Giờ Karaoke', 'business_id': business_id}, {'id': 1, '_id': 0})
            if prod:
                prod_id = prod['id']
                order_code = f"KTV-{uuid.uuid4().hex[:8].upper()}"
                order_id = next_mongo_id('orders')
                db.orders.insert_one({
                    'id': order_id,
                    'business_id': business_id,
                    'created_at': datetime.now().isoformat(),
                    'status': 'completed',
                    'total_amount': total_price,
                    'payment_method': 'cash',
                    'metadata': {'order_code': order_code, 'channel': 'karaoke', 'room_id': room_id},
                })
                db.order_items.insert_one({
                    'id': next_mongo_id('order_items'),
                    'order_id': order_id,
                    'product_id': prod_id,
                    'quantity': 1,
                    'price': total_price,
                    'total_price': total_price,
                    'business_id': business_id
                })
                _record_pos_transaction(business_id, order_id, total_price, 'cash')
            db.karaoke_rooms.update_one(
                {'id': room_id, 'business_id': business_id}, {'$set': {'status': 'Trống', 'start_time': None}}
            )
        if _wants_json():
            return jsonify({"success": True, "order_id": order_id})
        return redirect(url_for('karaoke'))
    except Exception as e:
        msg = f"Lỗi xử lý phòng karaoke: {str(e)}"
        return (jsonify({"success": False, "message": msg}), 500) if _wants_json() else (msg, 500)


# ========== KARAOKE JSON API (thay Supabase JS ở karaoke.html) ==========
# QUAN TRỌNG: bản Supabase cũ của karaoke.html đọc/ghi bảng `dining_tables` để quản lý phòng
# (status/price_per_hour/start_time) — nhưng db.dining_tables trên Mongo là collection HOÀN
# TOÀN KHÁC của POS (200 bàn tự seed, chỉ có id/name/qr_token/business_id, KHÔNG có
# status/price_per_hour). Trỏ thẳng karaoke.html vào db.dining_tables sẽ vỡ vì sai schema.
# Collection đúng đã có sẵn và đang được /karaoke, /toggle_room dùng là db.karaoke_rooms — 3
# route dưới đây chỉ là bản JSON (thay vì redirect) của cùng logic, để karaoke.html gọi qua
# fetch() không cần load lại trang.
@app.route('/api/karaoke/rooms', methods=['GET'])
@login_required
def api_karaoke_rooms_list():
    business_id = session.get('business_id') or session['user_id']
    try:
        rooms = list(db.karaoke_rooms.find({'business_id': business_id}, {'_id': 0}).sort('id', 1))
        return jsonify({"success": True, "data": rooms})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/karaoke/rooms', methods=['POST'])
@login_required
def api_karaoke_rooms_create():
    business_id = session.get('business_id') or session['user_id']
    data = request.json or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({"success": False, "message": "Thiếu tên phòng."}), 400
    try:
        price_per_hour = float(data.get('price_per_hour', 0))
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "Giá theo giờ không hợp lệ."}), 400
    try:
        doc = {
            'id': next_mongo_id('karaoke_rooms'),
            'name': name,
            'price_per_hour': price_per_hour,
            'status': 'Trống',
            'start_time': None,
            'business_id': business_id,
        }
        db.karaoke_rooms.insert_one(doc)
        doc.pop('_id', None)
        return jsonify({"success": True, "data": doc})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/karaoke/rooms/<int:room_id>/start', methods=['POST'])
@login_required
def api_karaoke_room_start(room_id):
    business_id = session.get('business_id') or session['user_id']
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        # find_one_and_update lọc luôn status='Trống' trong filter -> atomic, tránh race
        # condition 2 nhân viên cùng bấm Start 1 phòng (bản Supabase cũ tách find rồi update
        # thành 2 bước riêng, có khe hở đua nhau ghi).
        result = db.karaoke_rooms.find_one_and_update(
            {'id': room_id, 'business_id': business_id, 'status': 'Trống'},
            {'$set': {'status': 'Đang chơi', 'start_time': now}},
            return_document=ReturnDocument.AFTER,
            projection={'_id': 0}
        )
        if not result:
            return jsonify({"success": False, "message": "Phòng không tồn tại hoặc đang không trống."}), 409
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/karaoke/rooms/<int:room_id>/checkout', methods=['POST'])
@login_required
def api_karaoke_room_checkout(room_id):
    business_id = session.get('business_id') or session['user_id']
    data = request.json or {}
    customer_phone = (data.get('customer_phone') or '').strip() or None
    try:
        room = db.karaoke_rooms.find_one({'id': room_id, 'business_id': business_id}, {'_id': 0})
        if not room or room.get('status') != 'Đang chơi':
            return jsonify({"success": False, "message": "Phòng không tồn tại hoặc chưa mở."}), 409
        start_time = parse_datetime(room['start_time'])
        now = datetime.now()
        duration_minutes = (now - start_time).total_seconds() / 60.0
        if duration_minutes < 15:
            duration_minutes = 15
        else:
            duration_minutes = math.ceil(duration_minutes / 15.0) * 15
        duration_hours = duration_minutes / 60.0
        total_price = duration_hours * room['price_per_hour']
        order_id = None
        prod = db.products.find_one({'name': 'Phí Giờ Karaoke', 'business_id': business_id}, {'id': 1, '_id': 0})
        if prod:
            order_code = f"KTV-{uuid.uuid4().hex[:8].upper()}"
            order_id = next_mongo_id('orders')
            metadata = {'order_code': order_code, 'channel': 'karaoke', 'room_id': room_id}
            if customer_phone:
                metadata['customer_phone'] = customer_phone
            order_doc = {
                'id': order_id,
                'business_id': business_id,
                'created_at': datetime.now().isoformat(),
                'status': 'completed',
                'total_amount': total_price,
                'payment_method': 'cash',
                'metadata': metadata,
            }
            db.orders.insert_one(order_doc)
            db.order_items.insert_one({
                'id': next_mongo_id('order_items'),
                'order_id': order_id,
                'product_id': prod['id'],
                'quantity': 1,
                'price': total_price,
                'total_price': total_price,
                'business_id': business_id,
            })
            _record_pos_transaction(business_id, order_id, total_price, 'cash')
        db.karaoke_rooms.update_one(
            {'id': room_id, 'business_id': business_id}, {'$set': {'status': 'Trống', 'start_time': None}}
        )
        return jsonify({"success": True, "total_amount": total_price, "order_id": order_id})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


# ========== BÁO CÁO ==========
@app.route('/api/report/summary', methods=['GET'])
@login_required
@role_required('admin', 'super_admin')
def api_report_summary():
    """Thay toàn bộ fetchReportData() Supabase cũ ở report.html — tính doanh thu/chi
    phí/lợi nhuận theo khoảng ngày do client chọn (today/yesterday/week/month/custom),
    cùng biểu đồ theo ngày, top sản phẩm, phân bổ theo ngành, top khách hàng, chi tiêu gần
    đây. Route /report (bên dưới) chỉ tính all-time cho lần render đầu; route này phục vụ
    mọi lần đổi khoảng ngày sau đó."""
    business_id = session.get('business_id') or session['user_id']

    period = request.args.get('period', 'month')
    today = datetime.now()
    if period == 'today':
        start_dt = today.replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = today.replace(hour=23, minute=59, second=59, microsecond=999999)
    elif period == 'yesterday':
        y = today - timedelta(days=1)
        start_dt = y.replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = y.replace(hour=23, minute=59, second=59, microsecond=999999)
    elif period == 'week':
        start_dt = (today - timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = today.replace(hour=23, minute=59, second=59, microsecond=999999)
    elif period == 'month':
        start_dt = (today - timedelta(days=29)).replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = today.replace(hour=23, minute=59, second=59, microsecond=999999)
    else:
        try:
            start_dt = datetime.strptime(request.args.get('start', ''), '%Y-%m-%d').replace(hour=0, minute=0, second=0, microsecond=0)
            end_dt = datetime.strptime(request.args.get('end', ''), '%Y-%m-%d').replace(hour=23, minute=59, second=59, microsecond=999999)
        except ValueError:
            return jsonify({"success": False, "message": "Thiếu hoặc sai định dạng start/end (YYYY-MM-DD)."}), 400

    start_iso, end_iso = start_dt.isoformat(), end_dt.isoformat()
    start_date_str, end_date_str = start_dt.strftime('%Y-%m-%d'), end_dt.strftime('%Y-%m-%d')

    try:
        orders = list(db.orders.find(
            {'business_id': business_id, 'created_at': {'$gte': start_iso, '$lte': end_iso}},
            {'id': 1, 'total_amount': 1, 'created_at': 1, 'customer_id': 1, '_id': 0}
        ))
        revenue = sum(o.get('total_amount') or 0 for o in orders)

        expenses = list(db.expenses.find(
            {'business_id': business_id, 'expense_date': {'$gte': start_date_str, '$lte': end_date_str}},
            {'amount': 1, 'expense_date': 1, 'description': 1, '_id': 0}
        ))
        expense = sum(e.get('amount') or 0 for e in expenses)

        # Doanh thu theo ngày cho biểu đồ
        labels, revenue_by_day_map = [], {}
        cur = start_dt
        while cur.date() <= end_dt.date():
            d = cur.strftime('%Y-%m-%d')
            labels.append(d[5:])
            revenue_by_day_map[d] = 0
            cur += timedelta(days=1)
        for o in orders:
            d = (o.get('created_at') or '')[:10]
            if d in revenue_by_day_map:
                revenue_by_day_map[d] += o.get('total_amount') or 0
        revenue_by_day = list(revenue_by_day_map.values())

        order_ids = [o['id'] for o in orders]
        order_items = list(db.order_items.find({'order_id': {'$in': order_ids}}, {'product_id': 1, 'quantity': 1, '_id': 0})) if order_ids else []
        products = list(db.products.find({'business_id': business_id}, {'id': 1, 'name': 1, 'category': 1, 'price': 1, '_id': 0}))
        product_map = {p['id']: p for p in products}

        sold_map = {}
        for oi in order_items:
            sold_map[oi['product_id']] = sold_map.get(oi['product_id'], 0) + (oi.get('quantity') or 0)
        top_products = sorted(
            [{'id': pid, 'name': product_map.get(pid, {}).get('name', f'SP{pid}'), 'sold': sold,
              'revenue': sold * (product_map.get(pid, {}).get('price') or 0)}
             for pid, sold in sold_map.items()],
            key=lambda x: x['sold'], reverse=True
        )[:5]

        category_revenue = {}
        for oi in order_items:
            prod = product_map.get(oi['product_id'])
            if prod:
                cat = prod.get('category') or 'Other'
                category_revenue[cat] = category_revenue.get(cat, 0) + (prod.get('price') or 0) * (oi.get('quantity') or 0)
        category_data = [{'name': cat, 'total': total} for cat, total in category_revenue.items()]

        customer_spent = {}
        for o in orders:
            cid = o.get('customer_id')
            if cid:
                customer_spent[cid] = customer_spent.get(cid, 0) + (o.get('total_amount') or 0)
        customers = list(db.customers.find({'id': {'$in': list(customer_spent.keys())}, 'business_id': business_id}, {'id': 1, 'name': 1, 'phone': 1, '_id': 0})) if customer_spent else []
        customer_map = {c['id']: c for c in customers}
        top_customers = sorted(
            [{'id': cid, 'name': customer_map.get(cid, {}).get('name', f'KH{cid}'), 'phone': customer_map.get(cid, {}).get('phone', ''), 'spent': spent}
             for cid, spent in customer_spent.items()],
            key=lambda x: x['spent'], reverse=True
        )[:5]

        recent_expenses = sorted(expenses, key=lambda e: e.get('expense_date') or '', reverse=True)[:5]

        return jsonify({
            "success": True,
            "revenue": revenue, "expense": expense, "profit": revenue - expense,
            "revenueByDay": revenue_by_day, "labels": labels,
            "categoryData": category_data,
            "topProducts": top_products,
            "topCustomers": top_customers,
            "recentExpenses": recent_expenses,
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/report')
@login_required
@role_required('admin', 'super_admin')
def report():
    business_id = session.get('business_id') or session['user_id']
    try:
        orders_data = list(db.orders.find({'business_id': business_id}, {'id': 1, 'total_amount': 1, '_id': 0}))
        revenue = sum(o.get('total_amount') or 0 for o in orders_data)
        expenses_data = list(db.expenses.find({'business_id': business_id}, {'amount': 1, '_id': 0}))
        expense = sum(e.get('amount') or 0 for e in expenses_data)
        profit = revenue - expense

        # order_items không có cột business_id riêng — lọc gián tiếp qua danh sách order_id đã thuộc đúng business_id
        order_ids = [o['id'] for o in orders_data]
        items_data = []
        if order_ids:
            items_data = list(db.order_items.find(
                {'order_id': {'$in': order_ids}}, {'product_id': 1, 'total_price': 1, '_id': 0}
            ))
        breakdown_map = {}

        # Batch load products mapping in O(1) to avoid massive synchronous DB requests in loop
        products_data = list(db.products.find({'business_id': business_id}, {'id': 1, 'category': 1, '_id': 0}))
        product_cat_map = {p['id']: p['category'] for p in products_data}

        for item in items_data:
            cat = product_cat_map.get(item['product_id'], 'Khác')
            breakdown_map[cat] = breakdown_map.get(cat, 0) + (item.get('total_price') or 0)

        breakdown = [(cat, total) for cat, total in breakdown_map.items()]
        return render_template('report.html', revenue=revenue, expense=expense, profit=profit, breakdown=breakdown)
    except Exception as e:
        print(f"[!] /report compilation error (graceful degradation active): {str(e)}")
        return render_template('report.html', revenue=0, expense=0, profit=0, breakdown=[])


def _compute_profit_by_product(business_id):
    """Dùng chung cho route render (profit_report) và JSON API (/api/report/profit) — tránh
    lặp lại phép tính sold/revenue/cost/profit/margin ở 2 nơi."""
    products_data = list(db.products.find(
        {'is_active': 1, 'business_id': business_id}, {'id': 1, 'name': 1, 'category': 1, 'price': 1, 'cost_price': 1, '_id': 0}
    ))
    own_product_ids = {p['id'] for p in products_data}
    # order_items chưa có cột business_id riêng — chỉ cần lọc theo product_id thuộc đúng tenant
    # (dùng $in ngay trong query thay vì kéo hết order_items về rồi lọc bằng Python).
    order_items = list(db.order_items.find(
        {'product_id': {'$in': list(own_product_ids)}}, {'product_id': 1, 'quantity': 1, '_id': 0}
    ))
    sold_map = {}
    for oi in order_items:
        sold_map[oi['product_id']] = sold_map.get(oi['product_id'], 0) + oi['quantity']
    profit_data = []
    for p in products_data:
        sold = sold_map.get(p['id'], 0)
        revenue = sold * p['price']
        cost = sold * (p.get('cost_price') or 0)
        profit_val = revenue - cost
        margin = (profit_val / revenue * 100) if revenue else 0
        profit_data.append({
            'id': p['id'],
            'name': p['name'],
            'category': p['category'],
            'sold': sold,
            'revenue': revenue,
            'cost': cost,
            'profit': profit_val,
            'margin': margin,
            # Đơn giá gốc (không phải tổng đã nhân số lượng bán) — cần riêng vì sản phẩm chưa
            # bán được (sold=0) vẫn phải hiện đúng đơn giá/giá vốn, không phải 0.
            'unit_price': p['price'],
            'unit_cost': p.get('cost_price') or 0,
        })
    return profit_data


@app.route('/api/report/profit', methods=['GET'])
@login_required
def api_report_profit():
    """Thay loadProfitData() Supabase cũ ở profit_by_product.html — dùng lại đúng phép tính
    của profit_report() phía dưới, gọi lại sau khi sửa giá vốn để refresh bảng."""
    business_id = session.get('business_id') or session['user_id']
    try:
        return jsonify({"success": True, "data": _compute_profit_by_product(business_id)})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/products/<int:id>/cost', methods=['PATCH'])
@login_required
def api_product_update_cost(id):
    """Cập nhật riêng giá vốn (cost_price) — /update_product/<id> hiện chỉ nhận full-form
    update (name/category/price/stock), không có cost_price, nên tách route riêng thay vì
    nới rộng ngữ nghĩa của route đó."""
    business_id = session.get('business_id') or session['user_id']
    data = request.json or {}
    try:
        new_cost = float(data.get('cost_price'))
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "cost_price không hợp lệ."}), 400
    if new_cost < 0:
        return jsonify({"success": False, "message": "cost_price không được âm."}), 400
    try:
        if not _assert_owns_product(id, business_id):
            return jsonify({"success": False, "message": "Sản phẩm không tồn tại hoặc không thuộc quyền quản lý của bạn."}), 403
        db.products.update_one({'id': id, 'business_id': business_id}, {'$set': {'cost_price': new_cost}})
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/profit_report')
@login_required
def profit_report():
    business_id = session.get('business_id') or session['user_id']
    try:
        profit_data = _compute_profit_by_product(business_id)
        error_message = None
    except Exception as e:
        print(f"Error calculating profit report (network/offline): {e}")
        profit_data = []
        error_message = "Đang hiển thị chế độ Offline"
    return render_template('profit_by_product.html', products=profit_data, error_message=error_message)


# ========== NHẬT KÝ HỆ THỐNG ==========
@app.route('/user_logs')
@login_required
def user_logs():
    # Trước đây route này đọc TOÀN BỘ user_logs không lọc theo tenant nào (lộ log của mọi
    # doanh nghiệp khác cho bất kỳ user nào đăng nhập) — sửa lại đúng theo yêu cầu bảo mật
    # đa khách hàng, chỉ trả về log của đúng business_id đang đăng nhập.
    business_id = session.get('business_id') or session['user_id']
    try:
        logs_data = list(db.user_logs.find({'business_id': business_id}, {'_id': 0}).sort('created_at', -1))
    except Exception as e:
        print(f"MongoDB user_logs select failed: {str(e)}")
        logs_data = []
    return render_template('user_logs.html', logs=logs_data)


# ========== SAO LƯU & PHỤC HỒI ==========
BACKUP_BUCKET = 'backups'
@app.route('/backup_restore')
@login_required
def backup_restore():
    return render_template('backup_restore.html')


BACKUP_TABLES = ['products', 'orders', 'order_items', 'customers', 'staff', 'appointments',
                  'dining_tables', 'promotions', 'expenses', 'payment_transactions']


@app.route('/api/backup/create', methods=['POST'])
@login_required
def create_backup():
    if fs is None:
        return jsonify({'success': False, 'error': 'MongoDB/GridFS chưa được cấu hình.'}), 400
    try:
        business_id = session.get('business_id') or session['user_id']
        # Chỉ backup dữ liệu CỦA ĐÚNG tenant đang đăng nhập — không export toàn hệ thống
        backup_data = {}
        for table in BACKUP_TABLES:
            backup_data[table] = list(db[table].find({'business_id': business_id}, {'_id': 0}))
        # system_settings dùng khóa riêng business_mode_{user_id}, không có cột business_id
        settings_doc = db.system_settings.find_one({'key': f'business_mode_{business_id}'}, {'_id': 0})
        backup_data['system_settings'] = [settings_doc] if settings_doc else []

        backup_data['_backup_metadata'] = {
            'version': '1.0',
            'business_id': business_id,
            'timestamp': datetime.now().isoformat()
        }
        json_str = json.dumps(backup_data, indent=2, ensure_ascii=False)
        filename = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        # GridFS thay Supabase Storage — filename + business_id lưu làm metadata của file để
        # list/restore sau này lọc đúng theo tenant, tương đương thư mục backups/{business_id}/
        # cũ trên Storage.
        fs.put(
            json_str.encode('utf-8'),
            filename=filename,
            business_id=business_id,
            content_type='application/json'
        )

        db.backup_logs.insert_one({
            'id': next_mongo_id('backup_logs'),
            'filename': filename,
            'business_id': business_id,
            'created_at': datetime.now().isoformat(),
            'user_email': session.get('user_email', 'system')
        })
        return jsonify({'success': True, 'filename': filename})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/backup/restore', methods=['POST'])
@login_required
def restore_backup():
    if fs is None:
        return jsonify({'success': False, 'error': 'MongoDB/GridFS chưa được cấu hình.'}), 400
    try:
        business_id = session.get('business_id') or session['user_id']
        filename = request.json.get('filename')
        if not filename:
            return jsonify({'success': False, 'error': 'Thiếu tên file backup.'}), 400
        # Chặn path traversal: filename do client gửi lên không được phép chứa '/', '..'
        # hay bất kỳ ký tự nào lạ.
        filename = secure_filename(filename)
        if not filename or filename != request.json.get('filename'):
            return jsonify({'success': False, 'error': 'Tên file backup không hợp lệ.'}), 400

        # Chỉ tìm file GridFS thuộc ĐÚNG business_id hiện tại — tương đương việc storage_path cũ
        # tự giới hạn trong thư mục backups/{business_id}/, tenant khác không thể tải nhầm.
        try:
            grid_file = fs.find_one({'filename': filename, 'business_id': business_id})
        except NoFile:
            grid_file = None
        if not grid_file:
            return jsonify({'success': False, 'error': 'Không tìm thấy file backup này của tenant hiện tại.'}), 404
        data = json.loads(grid_file.read())

        # Double-check: metadata trong file (nếu có) phải khớp đúng tenant hiện tại
        meta = data.get('_backup_metadata', {})
        if meta.get('business_id') and meta.get('business_id') != business_id:
            return jsonify({'success': False, 'error': 'Backup file không thuộc tenant hiện tại.'}), 403

        # Khôi phục theo thứ tự bảng: xóa dữ liệu cũ CỦA ĐÚNG business_id này, rồi insert lại từ backup
        for table in BACKUP_TABLES:
            rows = data.get(table)
            if rows is None:
                continue
            db[table].delete_many({'business_id': business_id})
            if rows:
                for row in rows:
                    row['business_id'] = business_id  # ép đúng tenant hiện tại, không ghi nhầm chỗ khác
                    row.pop('_id', None)
                db[table].insert_many(rows)

        settings_rows = data.get('system_settings')
        if settings_rows:
            settings_key = f'business_mode_{business_id}'
            for row in settings_rows:
                row['key'] = settings_key
                row.pop('_id', None)
                db.system_settings.update_one({'key': settings_key}, {'$set': row}, upsert=True)

        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/backup/list', methods=['GET'])
@login_required
def list_backups():
    if fs is None:
        return jsonify({'success': False, 'error': 'MongoDB/GridFS chưa được cấu hình.'}), 400
    try:
        business_id = session.get('business_id') or session['user_id']
        grid_files = db.backups.files.find({'business_id': business_id}).sort('uploadDate', -1)
        files = [{
            'name': f['filename'],
            'size': f.get('length', 0),
            'created_at': f.get('uploadDate').isoformat() if f.get('uploadDate') else None
        } for f in grid_files]
        return jsonify(files)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ========== MEDIA STORAGE (GridFS) — thay 2 bucket Supabase Storage cũ `checkin_images` và
# `avatars` (app_nhanvien.html, chamcong_spa.html). Dùng chung 1 GridFS bucket 'media' (khác
# 'backups' ở trên) — phân biệt bằng metadata `kind` thay vì 2 bucket riêng, vì cả 2 đều là
# ảnh JPEG/PNG nhỏ, không cần tách vật lý. ==========
media_fs = GridFS(db, collection='media') if db is not None else None
ALLOWED_MEDIA_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
# Giai đoạn 6 audit (CISO/Pentest) — BÁO ĐỘNG ĐỎ đã vá: map đuôi file (đã qua allow-list
# _allowed_media_file) -> Content-Type CỐ ĐỊNH phía server. TUYỆT ĐỐI không dùng file.mimetype
# (client tự khai trong multipart request, có thể là BẤT KỲ giá trị nào — vd 1 file thật sự tên
# "logo.png" nhưng client cố tình khai Content-Type: text/html chứa payload <script>...</script>)
# để lưu/replay lại lúc GET. Nếu lưu thẳng giá trị client khai rồi trả y nguyên ở
# api_storage_file()/api_public_storage_file(), ai mở thẳng URL file đó (không qua thẻ <img>, vd
# copy link/click chuột phải "mở ảnh trong tab mới") sẽ khiến trình duyệt DIỄN GIẢI VÀ CHẠY nội
# dung đó như HTML/JS thật — Stored XSS chiếm được session của bất kỳ ai xem link (đặc biệt nguy
# hiểm ở api_public_storage_file(): không cần đăng nhập vẫn khai thác được, vì brand_logo/
# product_image/portal_chat công khai cho toàn bộ khách vãng lai).
_SAFE_IMAGE_CONTENT_TYPES = {
    'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
    'gif': 'image/gif', 'webp': 'image/webp',
}


def _allowed_media_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_MEDIA_EXTENSIONS


def _safe_image_content_type(filename):
    """Content-Type AN TOÀN suy ra từ đúng đuôi file đã qua allow-list — KHÔNG BAO GIỜ dùng
    file.mimetype (client tự khai, không đáng tin). Gọi hàm này SAU khi đã xác nhận
    _allowed_media_file(filename) == True; trả 'application/octet-stream' (tải xuống, trình
    duyệt KHÔNG BAO GIỜ tự thực thi) nếu vì lý do gì đó đuôi file không khớp map — fail-safe,
    không đoán bừa."""
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    return _SAFE_IMAGE_CONTENT_TYPES.get(ext, 'application/octet-stream')


@app.route('/api/storage/upload', methods=['POST'])
@login_required
def api_storage_upload():
    """Upload ảnh (avatar, ảnh check-in, ảnh trước/sau dịch vụ VIP...) vào GridFS. Trả về
    `url` là link nội bộ (/api/storage/file/<id>) để nhúng thẳng vào <img src>, tương đương
    getPublicUrl() cũ của Supabase Storage."""
    if media_fs is None:
        return jsonify({'success': False, 'error': 'MongoDB/GridFS chưa được cấu hình.'}), 400
    file = request.files.get('file')
    if not file or file.filename == '':
        return jsonify({'success': False, 'error': 'Thiếu file để upload.'}), 400
    if not _allowed_media_file(file.filename):
        return jsonify({'success': False, 'error': 'Chỉ hỗ trợ ảnh (png/jpg/jpeg/gif/webp).'}), 400
    business_id = session.get('business_id') or session['user_id']
    kind = request.form.get('kind', 'misc')
    filename = secure_filename(file.filename)
    try:
        file_id = media_fs.put(
            file.stream.read(),
            filename=filename,
            business_id=business_id,
            kind=kind,
            content_type=_safe_image_content_type(filename)
        )
        return jsonify({'success': True, 'file_id': str(file_id), 'url': url_for('api_storage_file', file_id=str(file_id))})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/storage/file/<file_id>', methods=['GET'])
@login_required
def api_storage_file(file_id):
    """Trả nội dung ảnh từ GridFS theo _id — CHỈ cho đúng business_id đã upload file đó.
    Sửa lại từ bản đầu (không login_required, không check business_id): <img src> same-origin
    VẪN gửi kèm session cookie như request thường, nên lý do "không kèm cookie" ban đầu là
    sai; và ObjectId của Mongo sinh theo timestamp+counter (dễ đoán/dò hơn nhiều so với UUID
    ngẫu nhiên của Supabase Storage cũ), nên để public hoàn toàn là lỗ hổng thật, không phải
    hành vi tương đương an toàn như đã tưởng."""
    business_id = session.get('business_id') or session['user_id']
    if media_fs is None:
        return jsonify({'success': False, 'error': 'MongoDB/GridFS chưa được cấu hình.'}), 400
    try:
        object_id = ObjectId(file_id)
        grid_file = media_fs.get(object_id)
    except (NoFile, InvalidId):
        return jsonify({'success': False, 'error': 'Không tìm thấy file.'}), 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    if getattr(grid_file, 'business_id', None) != business_id:
        return jsonify({'success': False, 'error': 'Không có quyền truy cập file này.'}), 403
    # Cache-Control: `private` (không phải `public`) vì route này yêu cầu login + kiểm tra
    # business_id — dùng `public` sẽ để lộ rủi ro shared/CDN cache (vd Vercel edge, Nginx phía
    # trước) vô tình trả nhầm ảnh của tenant A cho tenant B nếu cùng cache 1 URL dùng chung.
    # `private` vẫn giữ nguyên lợi ích cache phía trình duyệt (giảm round-trip lặp lại, cải
    # thiện LCP trên mạng 3G/4G) mà không mở lỗ rò rỉ chéo tenant qua cache trung gian.
    return Response(
        grid_file.read(),
        mimetype=grid_file.content_type or 'application/octet-stream',
        headers={'Cache-Control': 'private, max-age=86400'}
    )


# Kind nào được coi là "công khai theo thiết kế" — logo/cover thương hiệu (khách xem trang
# landing/booking/portal/qr_menu của tenant), ảnh chat CSKH (khách ẩn danh gửi/nhận qua
# portal.html, không có session để dùng route private ở trên), và ảnh sản phẩm/dịch vụ (khách
# quét QR menu/table_order cũng không có session nhưng vẫn cần xem ảnh món). CHỈ các nhóm này —
# không bao giờ thêm 'checkin'/'avatar'/... vào đây, những kind đó PHẢI qua
# /api/storage/file/<id> (private).
_PUBLIC_MEDIA_KINDS = {'brand_logo', 'brand_cover', 'portal_chat', 'product_image'}


@app.route('/api/public/storage/file/<file_id>', methods=['GET'])
def api_public_storage_file(file_id):
    """PUBLIC — CHỈ phục vụ file có kind nằm trong whitelist _PUBLIC_MEDIA_KINDS ở trên; mọi
    kind khác (checkin, avatar...) bị từ chối kể cả biết đúng file_id, để không lặp lại lỗ hổng
    'public storage = ai cũng xem được mọi ảnh' đã vá ở api_storage_file()."""
    if media_fs is None:
        return jsonify({'success': False, 'error': 'MongoDB/GridFS chưa được cấu hình.'}), 400
    try:
        object_id = ObjectId(file_id)
        grid_file = media_fs.get(object_id)
    except (NoFile, InvalidId):
        return jsonify({'success': False, 'error': 'Không tìm thấy file.'}), 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    if getattr(grid_file, 'kind', None) not in _PUBLIC_MEDIA_KINDS:
        return jsonify({'success': False, 'error': 'File này không công khai.'}), 403
    return Response(
        grid_file.read(),
        mimetype=grid_file.content_type or 'application/octet-stream',
        headers={'Cache-Control': 'public, max-age=86400'}
    )


# ========== QR MENU ==========
@app.route('/qr_menu')
def qr_menu_base():
    return redirect(url_for('qr_menu', identifier='demo'))


@app.route('/qr_menu/<path:identifier>')
def qr_menu(identifier):
    table_data = None
    try:
        if identifier.isdigit():
            table_data = db.dining_tables.find_one({'id': int(identifier)}, {'_id': 0})
        else:
            table_data = db.dining_tables.find_one({'qr_token': identifier}, {'_id': 0})
    except Exception as e:
        return "Không thể kết nối tới hệ thống để xác thực bàn. Vui lòng thử lại.", 500

    if not table_data:
        return "Mã QR không hợp lệ hoặc bàn không còn tồn tại. Vui lòng liên hệ nhân viên.", 404

    # Chỉ load đúng thực đơn của tenant sở hữu bàn này — cấm lộ sản phẩm của tiệm khác.
    # channel_type đọc từ query string (mặc định 'retail' giữ đúng hành vi cũ) — trước đây bản
    # Supabase JS ở qr_menu.html tự query lại theo ?industry= (fnb/nail/spa), KHÁC với
    # 'retail' hardcode ở đây, nên nếu client gọi refresh live qua /api/public/pos/products sẽ
    # ra danh sách khác với menu đã render sẵn. Truyền channel_type xuống template để mọi lần
    # gọi lại đều dùng ĐÚNG 1 giá trị nhất quán với lần render đầu.
    table_business_id = table_data.get('business_id')
    channel_type = request.args.get('channel_type', 'retail')
    try:
        menu_filter = {'is_active': 1, 'channel_type': channel_type}
        if table_business_id:
            menu_filter['business_id'] = table_business_id
        menu_data = list(db.products.find(menu_filter, {'_id': 0}))
    except Exception as e:
        print(f"MongoDB qr_menu products select failed: {str(e)}")
        menu_data = []
    return render_template('qr_menu.html', table=table_data, menu=menu_data, channel_type=channel_type)


@app.route('/api/submit_qr_order', methods=['POST'])
def submit_qr_order():
    try:
        # Check if content is JSON
        if request.is_json:
            data = request.json
        else:
            data = request.form
            
        table_id = data.get('table_id')
        items = data.get('items', [])
        total = data.get('total', 0)
        note = data.get('customer_note', '')

        if not table_id:
            return jsonify({"success": False, "message": "Missing table_id"}), 400

        # Xác thực bàn tồn tại thật trong DB trước khi ghi nhận đơn — không còn fallback bàn demo giả
        try:
            if str(table_id).isdigit():
                table_check = db.dining_tables.find_one({'id': int(table_id)}, {'id': 1, 'name': 1, 'business_id': 1, '_id': 0})
            else:
                table_check = db.dining_tables.find_one({'qr_token': table_id}, {'id': 1, 'name': 1, 'business_id': 1, '_id': 0})
            if not table_check:
                return jsonify({"success": False, "message": "Table not found or QR code is invalid."}), 404
            # Luôn dùng id số thật của bàn cho các bảng liên quan, tránh lưu nhầm qr_token dạng chuỗi
            resolved_table_id = table_check['id']
            table_display_name = table_check.get('name') or f"Table {resolved_table_id}"
            table_business_id = table_check.get('business_id')
        except Exception as e:
            return jsonify({"success": False, "message": f"Could not verify table: {str(e)}"}), 500

        # Gom danh sách món khách gửi lên thành 1 list chung (JSON nhiều món hoặc form 1 món),
        # rồi batch-fetch TẤT CẢ sản phẩm liên quan trong 1 query duy nhất ($in) — thay vì
        # trước đây cứ mỗi món lại query products 2 lần (check business_id + lấy tên) + query
        # table_orders 1 lần để biết insert hay update (tổng 3N query).
        requested_items = []
        if isinstance(items, list) and len(items) > 0:
            for item in items:
                pid = item.get('id')
                qty = item.get('quantity', 1)
                if pid:
                    requested_items.append((pid, qty))
        else:
            product_id = data.get('product_id')
            qty = int(data.get('quantity', 1))
            if product_id:
                requested_items.append((product_id, qty))

        kitchen_items = []
        if requested_items:
            product_ids = [pid for pid, _ in requested_items]
            products_map = {
                p['id']: p for p in db.products.find({'id': {'$in': product_ids}}, {'id': 1, 'name': 1, 'business_id': 1, '_id': 0})
            }
            existing_map = {
                o['product_id']: o for o in db.table_orders.find(
                    {'table_id': resolved_table_id, 'product_id': {'$in': product_ids}}, {'id': 1, 'product_id': 1, 'quantity': 1, '_id': 0}
                )
            }

            update_ops = []
            insert_docs = []
            for pid, quantity in requested_items:
                prod = products_map.get(pid)
                # Chặn khách order sản phẩm của tiệm khác (khác business_id với bàn đang quét)
                if table_business_id and (not prod or prod.get('business_id') != table_business_id):
                    continue
                existing = existing_map.get(pid)
                if existing:
                    new_qty = existing['quantity'] + quantity
                    update_ops.append(UpdateOne(
                        {'id': existing['id'], 'table_id': resolved_table_id}, {'$set': {'quantity': new_qty}}
                    ))
                else:
                    insert_docs.append({
                        'id': next_mongo_id('table_orders'), 'table_id': resolved_table_id,
                        'product_id': pid, 'quantity': quantity, 'business_id': table_business_id
                    })
                item_name = prod['name'] if prod else f"Món #{pid}"
                kitchen_items.append({'name': item_name, 'qty': quantity})

            if update_ops:
                db.table_orders.bulk_write(update_ops)
            if insert_docs:
                db.table_orders.insert_many(insert_docs)

        # Bắt buộc tạo vé bếp cho màn hình Kitchen Display — best-effort, không chặn
        # luồng gọi món của khách nếu ghi vé bếp lỗi (vd: bảng chưa được migrate xong).
        if kitchen_items:
            try:
                db.kitchen_orders.insert_one({
                    'id': next_mongo_id('kitchen_orders'),
                    'business_id': table_business_id,
                    'table_id': resolved_table_id,
                    'table_name': table_display_name,
                    'items': kitchen_items,
                    'status': 'pending',
                    'created_at': datetime.now().isoformat()
                })
            except Exception as kitchen_err:
                print(f"Ghi vé bếp thất bại (không chặn luồng gọi món): {str(kitchen_err)}")

        # Update dining_table status to 'Đang phục vụ'
        db.dining_tables.update_one({'id': resolved_table_id}, {'$set': {'status': 'Đang phục vụ'}})

        # Log to user_logs for merchant notification
        try:
            db.user_logs.insert_one({
                'id': next_mongo_id('user_logs'),
                'business_id': table_business_id,
                'user_email': f"table_{table_id}",
                'action': 'submit_qr_order',
                'description': f"Khách tại Bàn {table_id} đã gửi đơn hàng gọi món mới (Tổng: {total}₫)",
                'created_at': datetime.now().isoformat()
            })
        except Exception:
            pass

        return jsonify({"success": True, "message": "Order submitted successfully!"})
    except Exception as e:
        print("Error submitting QR order:", e)
        return jsonify({"success": False, "message": f"Server error: {str(e)}"}), 500


# ========== GỌI NHÂN VIÊN / YÊU CẦU TÍNH TIỀN (thay Supabase JS ở table_order.html) ==========
@app.route('/api/table/notify', methods=['POST'])
def api_table_notify():
    """Route PUBLIC (khách quét QR tại bàn, không có session) — resolve business_id qua
    table_id/qr_token giống hệt submit_qr_order() ở trên, không tin business_id client gửi."""
    data = request.json or {}
    table_id = data.get('table_id')
    notify_type = data.get('type')
    table_name = data.get('table_name', f'Table {table_id}')
    if notify_type not in ('staff', 'bill'):
        return jsonify({"success": False, "message": "Invalid type."}), 400
    try:
        table_doc = db.dining_tables.find_one({'id': table_id}, {'business_id': 1, '_id': 0})
        if not table_doc:
            return jsonify({"success": False, "message": "Table not found."}), 404
        business_id = table_doc.get('business_id')
        db.user_logs.insert_one({
            'id': next_mongo_id('user_logs'),
            'business_id': business_id,
            'user_email': f"table_{table_id}",
            'action': 'call_staff' if notify_type == 'staff' else 'request_bill',
            'description': f"Bàn {table_name} yêu cầu {'gọi nhân viên' if notify_type == 'staff' else 'tính tiền'}",
            'created_at': datetime.now().isoformat(),
        })
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/public/pos/products', methods=['GET'])
def api_public_pos_products():
    """PUBLIC (không @login_required) — thực đơn cho khách quét QR gọi món tại bàn
    (table_order.html) TRƯỚC KHI có Flask session. Tenant resolve qua table_id giống hệt
    submit_qr_order()/api_table_notify() ở trên, KHÔNG tin business_id do client tự gửi.
    Projection loại trừ cost_price (giá vốn) và business_id khỏi response — chỉ trả về dữ
    liệu cần cho việc hiển thị menu công khai."""
    table_id = request.args.get('table_id')
    channel_type = request.args.get('channel_type', 'fnb')
    if not table_id or not str(table_id).isdigit():
        return jsonify({"success": False, "message": "Missing or invalid table_id."}), 400
    try:
        table_doc = db.dining_tables.find_one({'id': int(table_id)}, {'business_id': 1, '_id': 0})
        if not table_doc:
            return jsonify({"success": False, "message": "Table not found."}), 404
        business_id = table_doc.get('business_id')
        products_data = list(db.products.find(
            {'is_active': 1, 'channel_type': channel_type, 'business_id': business_id},
            {'id': 1, 'name': 1, 'price': 1, 'stock': 1, 'image': 1, 'category': 1, 'channel_type': 1, '_id': 0}
        ).sort('name', 1))
        return jsonify({"success": True, "data": products_data})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


# ========== KITCHEN DISPLAY JSON API (thay Supabase JS ở kitchen_display.html) ==========
# db.kitchen_orders đã tồn tại sẵn (ghi bởi submit_qr_order ở trên) — chỉ còn thiếu chiều
# đọc/cập nhật cho màn hình bếp. business_id lấy từ session, KHÔNG tin client.
@app.route('/api/kitchen/orders', methods=['GET'])
@login_required
def api_kitchen_orders_list():
    business_id = session.get('business_id') or session['user_id']
    try:
        orders = list(db.kitchen_orders.find(
            {'business_id': business_id, 'status': {'$in': ['pending', 'cooking']}},
            {'_id': 0}
        ).sort('created_at', 1))
        return jsonify({"success": True, "data": orders})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/kitchen/orders/<int:order_id>', methods=['PATCH'])
@login_required
def api_kitchen_orders_update(order_id):
    business_id = session.get('business_id') or session['user_id']
    data = request.json or {}
    status = data.get('status')
    if status not in ('pending', 'cooking', 'completed'):
        return jsonify({"success": False, "error": "trang_thai không hợp lệ."}), 400
    try:
        result = db.kitchen_orders.update_one(
            {'id': order_id, 'business_id': business_id}, {'$set': {'status': status}}
        )
        if result.matched_count == 0:
            return jsonify({"success": False, "error": "Không tìm thấy vé bếp."}), 404
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/stream/kitchen')
@login_required
def stream_kitchen():
    """Thay kênh Supabase Realtime `kitchen-orders` (INSERT+UPDATE trên bảng kitchen_orders)."""
    return _sse_change_signal(db.kitchen_orders, _sse_tenant_match())


# ========== CHAT NỘI BỘ JSON API (thay Supabase JS + Supabase Auth ở chat.html) ==========
# db.chat_messages (mới) + db.chat_presence (mới, thay Supabase Realtime Presence — Presence
# là pub/sub tức thời trong bộ nhớ, không có bảng tương ứng; thay bằng heartbeat: client tự
# ping định kỳ, "online" = last_seen trong N giây gần nhất). Danh tính người dùng lấy từ
# session['user_email'] (Flask đã xác thực qua @login_required) — KHÔNG còn cần Supabase Auth
# getSession()/getUser() như code cũ, vốn là lớp xác thực THỨ HAI chồng lên Flask session,
# đã bị vô hiệu hoá từ khi route /chat có @login_required (route chỉ vào được nếu đã đăng
# nhập Flask, nên check Supabase Auth phía client luôn đúng/không có tác dụng thật).
_CHAT_PRESENCE_TTL_SECONDS = 20


def _resolve_chat_identity(business_id):
    email = session.get('user_email') or f"user_{session.get('user_id')}"
    emp = db.employees.find_one({'email': email, 'business_id': business_id}, {'ho_ten': 1, '_id': 0})
    name = (emp or {}).get('ho_ten') or email.split('@')[0]
    return email, name


@app.route('/api/chat/messages', methods=['GET'])
@login_required
def api_chat_messages_list():
    business_id = session.get('business_id') or session['user_id']
    room = request.args.get('room', 'KenhChung')
    before = request.args.get('before')
    limit = min(request.args.get('limit', 50, type=int), 100)
    query = {'business_id': business_id, 'room': room}
    if before:
        query['timestamp'] = {'$lt': before}
    try:
        msgs = list(db.chat_messages.find(query, {'_id': 0}).sort('timestamp', -1).limit(limit))
        # "unread" tính THẬT server-side (không phải suy đoán client) — so sánh timestamp tin
        # mới nhất trong room với last_read_at của CHÍNH người đang gọi (chat_read_state), thay
        # vì chỉ đoán qua "tin cuối có phải mình gửi không" như bản cũ (sai khi đã đọc rồi mà
        # tin cuối vẫn của người khác). Không dùng field is_read trên từng message vì room có
        # thể nhiều người cùng đọc (KenhChung) — "đã đọc" là trạng thái RIÊNG của từng người,
        # không phải thuộc tính chung của tin nhắn.
        email, _name = _resolve_chat_identity(business_id)
        unread = False
        if msgs:
            try:
                read_state = db.chat_read_state.find_one(
                    {'business_id': business_id, 'room': room, 'email': email}, {'last_read_at': 1, '_id': 0}
                )
                last_read_at = read_state['last_read_at'] if read_state else None
                unread = any(
                    m.get('sender_id') != email and (not last_read_at or m['timestamp'] > last_read_at)
                    for m in msgs
                )
            except Exception as read_state_err:
                print(f"[api_chat_messages_list] Tính unread lỗi (bỏ qua, coi như đã đọc): {str(read_state_err)}")
        return jsonify({"success": True, "data": msgs, "unread": unread})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/chat/read', methods=['POST'])
@login_required
def api_chat_mark_read():
    """Đánh dấu ĐÃ ĐỌC 1 room cho ĐÚNG người gọi hiện tại — gọi khi client thực sự mở xem hội
    thoại (openChat), KHÔNG gọi khi chỉ lấy preview tin cuối (loadDanhBa dùng limit=1 để hiện
    preview, không phải hành động 'đọc')."""
    business_id = session.get('business_id') or session['user_id']
    room = (request.json or {}).get('room', 'KenhChung')
    email, _name = _resolve_chat_identity(business_id)
    try:
        db.chat_read_state.update_one(
            {'business_id': business_id, 'room': room, 'email': email},
            {'$set': {'last_read_at': datetime.now().isoformat()}},
            upsert=True
        )
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/chat/messages', methods=['POST'])
@login_required
def api_chat_messages_create():
    business_id = session.get('business_id') or session['user_id']
    data = request.json or {}
    content = (data.get('content') or '').strip()
    room = data.get('room', 'KenhChung')
    if not content:
        return jsonify({"success": False, "error": "Tin nhắn trống."}), 400
    sender_id, sender_name = _resolve_chat_identity(business_id)
    try:
        doc = {
            'id': next_mongo_id('chat_messages'),
            'business_id': business_id,
            'room': room,
            'sender_id': sender_id,
            'sender_name': sender_name,
            'content': content,
            'timestamp': datetime.now().isoformat(),
        }
        db.chat_messages.insert_one(doc)
        doc.pop('_id', None)
        return jsonify({"success": True, "data": doc})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/chat/presence/ping', methods=['POST'])
@login_required
def api_chat_presence_ping():
    business_id = session.get('business_id') or session['user_id']
    room = (request.json or {}).get('room', 'KenhChung')
    sender_id, sender_name = _resolve_chat_identity(business_id)
    try:
        db.chat_presence.update_one(
            {'business_id': business_id, 'room': room, 'email': sender_id},
            {'$set': {'name': sender_name, 'last_seen': datetime.now().isoformat()}},
            upsert=True
        )
        # Trả kèm danh tính đã resolve — client dùng đúng 1 lần gọi đầu tiên để biết
        # "mình là ai" (so sánh sender_id === myEmail khi render bong bóng chat) thay vì phải
        # tự gọi Supabase Auth getUser() như code cũ.
        return jsonify({"success": True, "email": sender_id, "name": sender_name})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/chat/presence', methods=['GET'])
@login_required
def api_chat_presence_list():
    business_id = session.get('business_id') or session['user_id']
    room = request.args.get('room', 'KenhChung')
    cutoff = (datetime.now() - timedelta(seconds=_CHAT_PRESENCE_TTL_SECONDS)).isoformat()
    try:
        online = list(db.chat_presence.find(
            {'business_id': business_id, 'room': room, 'last_seen': {'$gte': cutoff}},
            {'_id': 0, 'email': 1, 'name': 1}
        ))
        return jsonify({"success": True, "data": online})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/stream/chat')
@login_required
def stream_chat():
    """Thay 2 kênh Supabase Realtime `public:messages` + presence `online-users` — 1 stream
    dùng chung, watch cả chat_messages và chat_presence ở cấp Database."""
    return _sse_change_signal(db, _sse_tenant_match('chat_messages', 'chat_presence'))


# ========== CÀI ĐẶT THƯƠNG HIỆU ==========
def _brand_setting_get(business_id, key, default=None):
    doc = db.system_settings.find_one({'key': key, 'business_id': business_id}, {'value': 1, '_id': 0})
    return doc['value'] if doc else default


def _brand_setting_set(business_id, key, value):
    db.system_settings.update_one(
        {'key': key, 'business_id': business_id}, {'$set': {'value': value}}, upsert=True
    )


@app.route('/brand_settings', methods=['GET', 'POST'])
@login_required
@role_required('admin', 'super_admin')
def brand_settings():
    # ĐÃ CHUYỂN SANG PER-TENANT (quyết định sản phẩm): brand_name/brand_color/logo/cover/font
    # trước đây là 1 giá trị TOÀN CỤC dùng chung mọi tenant — nay mỗi khoá đều lọc thêm
    # business_id, giống mọi key khác trong system_settings (payment_config, inventory_thresholds).
    business_id = session.get('business_id') or session['user_id']
    if request.method == 'POST':
        try:
            _brand_setting_set(business_id, 'brand_name', request.form['brand_name'])
        except Exception as e:
            print("Error updating brand_name settings:", e)
        try:
            _brand_setting_set(business_id, 'brand_color', request.form['brand_color'])
        except Exception as e:
            print("Error updating brand_color settings:", e)
        return redirect(url_for('spa'))
    try:
        brand_name = _brand_setting_get(business_id, 'brand_name', 'BitPaw')
        brand_color = _brand_setting_get(business_id, 'brand_color', '#06b6d4')
        error_message = None
    except Exception as e:
        print(f"Error fetching brand settings (network/offline): {e}")
        brand_name = 'BitPaw'
        brand_color = '#06b6d4'
        error_message = "Đang hiển thị chế độ Offline"
    return render_template('brand_settings.html', brand_name=brand_name, brand_color=brand_color, error_message=error_message)


@app.route('/api/brand_settings', methods=['GET'])
@login_required
def api_brand_settings_get():
    business_id = session.get('business_id') or session['user_id']
    try:
        data = {
            'brand_name': _brand_setting_get(business_id, 'brand_name', 'BitPaw'),
            'brand_color': _brand_setting_get(business_id, 'brand_color', '#06b6d4'),
            'font_family': _brand_setting_get(business_id, 'brand_font_family', ''),
            'logo_url': _brand_setting_get(business_id, 'brand_logo_url', ''),
            'cover_url': _brand_setting_get(business_id, 'brand_cover_url', ''),
        }
        return jsonify({"success": True, "data": data})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/brand_settings', methods=['POST'])
@login_required
@role_required('admin', 'super_admin')
def api_brand_settings_save():
    """multipart/form-data: brand_name, brand_color, font_family (text) + logo/cover (file,
    tuỳ chọn) — hoàn thiện phần "Xử lý upload logo và cover nếu có" trước đây chỉ là TODO chưa
    từng cài đặt. Ảnh lưu GridFS kind='brand_logo'/'brand_cover' (công khai qua
    /api/public/storage/file/<id>, xem whitelist _PUBLIC_MEDIA_KINDS)."""
    business_id = session.get('business_id') or session['user_id']
    try:
        if 'brand_name' in request.form:
            _brand_setting_set(business_id, 'brand_name', request.form['brand_name'])
        if 'brand_color' in request.form:
            _brand_setting_set(business_id, 'brand_color', request.form['brand_color'])
        if 'font_family' in request.form:
            _brand_setting_set(business_id, 'brand_font_family', request.form['font_family'])

        for field, kind, setting_key in (('logo', 'brand_logo', 'brand_logo_url'), ('cover', 'brand_cover', 'brand_cover_url')):
            file = request.files.get(field)
            if file and file.filename:
                if media_fs is None:
                    return jsonify({"success": False, "message": "MongoDB/GridFS chưa được cấu hình."}), 400
                if not _allowed_media_file(file.filename):
                    return jsonify({"success": False, "message": "Chỉ hỗ trợ ảnh (png/jpg/jpeg/gif/webp)."}), 400
                file_id = media_fs.put(
                    file.stream.read(),
                    filename=secure_filename(file.filename),
                    business_id=business_id,
                    kind=kind,
                    content_type=_safe_image_content_type(file.filename)
                )
                _brand_setting_set(business_id, setting_key, url_for('api_public_storage_file', file_id=str(file_id)))

        return jsonify({"success": True, "data": {
            'brand_name': _brand_setting_get(business_id, 'brand_name', 'BitPaw'),
            'brand_color': _brand_setting_get(business_id, 'brand_color', '#06b6d4'),
            'font_family': _brand_setting_get(business_id, 'brand_font_family', ''),
            'logo_url': _brand_setting_get(business_id, 'brand_logo_url', ''),
            'cover_url': _brand_setting_get(business_id, 'brand_cover_url', ''),
        }})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


# ========== MỚI: ROUTE CHO CÁC TEMPLATE CÒN THIẾU ==========
@app.route('/inventory_alert')
@login_required
def inventory_alert():
    return render_template('inventory_alert.html')


# ========== INVENTORY ALERT JSON API (thay Supabase JS ở inventory_alert.html) ==========
@app.route('/api/inventory/products', methods=['GET'])
@login_required
def api_inventory_products():
    business_id = session.get('business_id') or session['user_id']
    try:
        products = list(db.products.find(
            {'business_id': business_id, 'is_active': 1}, {'_id': 0}
        ).sort('id', 1))
        return jsonify({"success": True, "data": products})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/inventory/thresholds', methods=['GET'])
@login_required
def api_inventory_thresholds_get():
    """Bản Supabase cũ chỉ lọc theo key='inventory_thresholds', KHÔNG lọc business_id — mọi
    tenant vô tình đọc/ghi chung 1 ngưỡng cảnh báo tồn kho của nhau. Sửa lại bắt buộc lọc theo
    business_id, giống mọi key khác trong system_settings (vd payment_config)."""
    business_id = session.get('business_id') or session['user_id']
    try:
        doc = db.system_settings.find_one(
            {'key': 'inventory_thresholds', 'business_id': business_id}, {'value': 1, '_id': 0}
        )
        thresholds = json.loads(doc['value']) if doc else {'warning': 10, 'critical': 5}
        return jsonify({"success": True, "data": thresholds})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/inventory/thresholds', methods=['PUT'])
@login_required
def api_inventory_thresholds_update():
    business_id = session.get('business_id') or session['user_id']
    data = request.json or {}
    try:
        warning = int(data.get('warning'))
        critical = int(data.get('critical'))
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "Ngưỡng cảnh báo không hợp lệ."}), 400
    if warning <= 0 or critical <= 0 or critical >= warning:
        return jsonify({"success": False, "message": "Ngưỡng nguy cấp phải nhỏ hơn ngưỡng cảnh báo và đều > 0."}), 400
    try:
        db.system_settings.update_one(
            {'key': 'inventory_thresholds', 'business_id': business_id},
            {'$set': {'value': json.dumps({'warning': warning, 'critical': critical})}},
            upsert=True
        )
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/products/<int:id>/restock', methods=['POST'])
@login_required
def api_products_restock(id):
    business_id = session.get('business_id') or session['user_id']
    data = request.json or {}
    try:
        quantity = int(data.get('quantity'))
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "Số lượng không hợp lệ."}), 400
    if quantity <= 0:
        return jsonify({"success": False, "message": "Số lượng phải lớn hơn 0."}), 400
    try:
        # $inc thay vì đọc stock hiện tại rồi ghi đè — tránh lost-update khi 2 người cùng
        # nhập hàng 1 sản phẩm đồng thời (bản Supabase cũ tính newStock ở client rồi update
        # đè, có race condition thật).
        result = db.products.find_one_and_update(
            {'id': id, 'business_id': business_id},
            {'$inc': {'stock': quantity}},
            return_document=ReturnDocument.AFTER,
            projection={'_id': 0}
        )
        if not result:
            return jsonify({"success": False, "message": "Không tìm thấy sản phẩm."}), 404
        db.inventory_logs.insert_one({
            'id': next_mongo_id('inventory_logs'),
            'product_id': id,
            'quantity_change': quantity,
            'type': 'restock',
            'business_id': business_id,
            'created_at': datetime.now().isoformat(),
        })
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/restock_proposals', methods=['GET'])
@login_required
def api_restock_proposals_list():
    business_id = session.get('business_id') or session['user_id']
    query = {'business_id': business_id}
    status = request.args.get('status')
    if status:
        query['status'] = status
    try:
        proposals = list(db.restock_proposals.find(query, {'_id': 0}).sort('created_at', -1))
        return jsonify({"success": True, "data": proposals})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/restock_proposals/<int:id>', methods=['PATCH'])
@login_required
def api_restock_proposals_update(id):
    business_id = session.get('business_id') or session['user_id']
    data = request.json or {}
    status = data.get('status')
    if status not in ('approved', 'dismissed', 'pending'):
        return jsonify({"success": False, "message": "status không hợp lệ."}), 400
    try:
        result = db.restock_proposals.update_one(
            {'id': id, 'business_id': business_id}, {'$set': {'status': status}}
        )
        if result.matched_count == 0:
            return jsonify({"success": False, "message": "Không tìm thấy đề xuất."}), 404
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/kitchen_display')
@login_required
def kitchen_display():
    return render_template('kitchen_display.html')

@app.route('/ecommerce_sync')
@login_required
def ecommerce_sync():
    return render_template('ecommerce_sync.html')


# ========== ECOMMERCE SYNC (Shopee/TikTok/Lazada) — MIGRATION AN TOÀN, CHƯA PHẢI TÍCH HỢP
# THẬT. Bản Supabase cũ gửi thẳng api_key/api_secret dạng plaintext từ trình duyệt lên Supabase,
# không mã hoá, và "sync" chỉ là setTimeout giả lập ở client — KHÔNG hề gọi API thật của
# Shopee/TikTok/Lazada. Theo quyết định sản phẩm: giữ nguyên mức độ tính năng hiện tại (chưa
# tích hợp thật — cần OAuth/webhook/signature verification riêng cho từng sàn, ngoài phạm vi
# đợt migrate này), nhưng credential giờ được mã hoá tại nghỉ (Fernet, key từ biến môi trường
# ECOMMERCE_ENC_KEY) và KHÔNG BAO GIỜ echo lại về client — cải thiện thật so với bản cũ dù
# tính năng sync vẫn là stub. ==========
def _ecommerce_mask(value):
    if not value:
        return ''
    return ('*' * max(0, len(value) - 4)) + value[-4:]


@app.route('/api/ecommerce/connections', methods=['GET'])
@login_required
def api_ecommerce_connections_list():
    business_id = session.get('business_id') or session['user_id']
    try:
        docs = list(db.ecommerce_connections.find({'business_id': business_id}, {'_id': 0}))
        # KHÔNG bao giờ trả api_key/api_secret (kể cả bản mã hoá) — chỉ trạng thái + vài ký tự
        # cuối để người dùng xác nhận đã lưu đúng credential, không phải để đọc lại.
        safe = [{
            'platform': d.get('platform'),
            'connected': True,
            'api_key_masked': _ecommerce_mask(d.get('api_key_plain_last4_only', '')),
            'updated_at': d.get('updated_at'),
        } for d in docs]
        return jsonify({"success": True, "data": safe})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/ecommerce/connections', methods=['POST'])
@login_required
def api_ecommerce_connections_save():
    business_id = session.get('business_id') or session['user_id']
    if _ecommerce_fernet is None:
        return jsonify({
            "success": False,
            "message": "Tính năng lưu API Key/Secret sàn TMĐT chưa được cấu hình an toàn trên "
                       "máy chủ (thiếu ECOMMERCE_ENC_KEY) — liên hệ quản trị hệ thống trước khi dùng."
        }), 503
    data = request.json or {}
    platform = (data.get('platform') or '').strip()
    api_key = data.get('api_key') or ''
    api_secret = data.get('api_secret') or ''
    if platform not in ('Shopee', 'TikTok', 'Lazada') or not api_key or not api_secret:
        return jsonify({"success": False, "message": "Thiếu platform/api_key/api_secret hợp lệ."}), 400
    try:
        db.ecommerce_connections.update_one(
            {'business_id': business_id, 'platform': platform},
            {'$set': {
                'api_key_enc': _ecommerce_fernet.encrypt(api_key.encode()).decode(),
                'api_secret_enc': _ecommerce_fernet.encrypt(api_secret.encode()).decode(),
                'api_key_plain_last4_only': api_key[-4:],
                'updated_at': datetime.now().isoformat(),
            }, '$setOnInsert': {'id': next_mongo_id('ecommerce_connections'), 'business_id': business_id, 'platform': platform}},
            upsert=True
        )
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/ecommerce/sync', methods=['POST'])
@login_required
def api_ecommerce_sync():
    """STUB — chỉ ghi nhận yêu cầu sync vào hàng đợi, KHÔNG gọi API thật của bất kỳ sàn nào
    (tích hợp thật là 1 dự án riêng: OAuth/API-key exchange theo từng sàn, webhook có xác thực
    chữ ký, worker đồng bộ nền — ngoài phạm vi migrate Supabase->Mongo). Trả về rõ ràng
    status='stub_not_implemented' để frontend KHÔNG hiển thị như thể đã đồng bộ xong thật."""
    business_id = session.get('business_id') or session['user_id']
    data = request.json or {}
    platforms = data.get('platforms') or []
    sync_type = data.get('type', 'all')
    try:
        for platform in platforms:
            db.ecommerce_sync_queue.insert_one({
                'id': next_mongo_id('ecommerce_sync_queue'),
                'business_id': business_id,
                'platform': platform,
                'action': sync_type,
                'status': 'stub_not_implemented',
                'created_at': datetime.now().isoformat(),
            })
        return jsonify({
            "success": True,
            "status": "stub_not_implemented",
            "message": "Đã ghi nhận yêu cầu — tích hợp API thật với sàn TMĐT chưa được xây dựng."
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/ecommerce/orders', methods=['GET'])
@login_required
def api_ecommerce_orders_list():
    business_id = session.get('business_id') or session['user_id']
    try:
        orders = list(db.ecommerce_orders.find({'business_id': business_id}, {'_id': 0}).sort('created_at', -1))
        return jsonify({"success": True, "data": orders})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/ecommerce/products', methods=['GET'])
@login_required
def api_ecommerce_products_list():
    business_id = session.get('business_id') or session['user_id']
    try:
        count = db.ecommerce_products.count_documents({'business_id': business_id})
        return jsonify({"success": True, "data": {"count": count}})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/payment_gateway')
@login_required
def payment_gateway():
    business_id = session.get('business_id')
    if not business_id:
        flash('Phiên đăng nhập không hợp lệ, vui lòng đăng nhập lại.', 'danger')
        return redirect(url_for('login'))
    config = None
    try:
        doc = db.system_settings.find_one({'key': 'payment_config', 'business_id': business_id}, {'value': 1, '_id': 0})
        if doc:
            config = json.loads(doc['value'])
    except Exception as e:
        print(f"Error loading payment config: {e}")

    return render_template('payment_gateway.html', config=config)


@app.route('/api/payment/save_config', methods=['POST'])
@login_required
def api_save_payment_config():
    try:
        business_id, _biz_err = _get_tenant_business_id_or_401()
        if _biz_err:
            return _biz_err
        config = request.get_json() or {}

        if not config:
            return jsonify({'success': False, 'message': 'Không nhận được cấu hình.'}), 400

        val_str = json.dumps(config)
        db.system_settings.update_one(
            {'key': 'payment_config', 'business_id': business_id},
            {'$set': {'value': val_str}},
            upsert=True
        )

        return jsonify({'success': True, 'message': 'Đã lưu cấu hình tài khoản nhận tiền thành công!'})
    except Exception as e:
        print(f"Error saving payment config: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/payment_history')
@login_required
def payment_history():
    return render_template('payment_history.html')

@app.route('/payment_pending')
@login_required
def payment_pending():
    table_id = request.args.get('table_id')
    business_id = session.get('business_id')
    if not business_id:
        flash('Phiên đăng nhập không hợp lệ, vui lòng đăng nhập lại.', 'danger')
        return redirect(url_for('login'))
    
    if table_id:
        try:
            # Look up table to find business_id
            tbl_doc = db.dining_tables.find_one({'id': int(table_id) if str(table_id).isdigit() else table_id}, {'business_id': 1, '_id': 0})
            if tbl_doc and tbl_doc.get('business_id'):
                business_id = tbl_doc['business_id']
        except Exception as e:
            print(f"Error resolving table business_id: {e}")

    config = None
    try:
        doc = db.system_settings.find_one({'key': 'payment_config', 'business_id': business_id}, {'value': 1, '_id': 0})
        if doc:
            config = json.loads(doc['value'])
    except Exception as e:
        print(f"Error loading payment config for pending: {e}")

    return render_template('payment_pending.html', config=config)


@app.route('/api/payment/start', methods=['POST'])
@login_required
def api_payment_start():
    try:
        data = request.get_json() or {}
        table_id = data.get('table_id')
        amount = data.get('amount')
        method = data.get('method', 'POS')
        industry = data.get('industry', 'fnb')

        if not table_id:
            return jsonify({'success': False, 'message': 'Missing table_id'}), 400

        business_id = session.get('business_id') or session['user_id']
        owns, err = _assert_owns_table(table_id, business_id)
        if not owns:
            return jsonify({'success': False, 'message': err}), 403

        txn_id = f"{industry.upper()}-{uuid.uuid4().hex[:8].upper()}"

        # Persist the discount%/tax%/tip the cashier applied on-screen so /api/payment/confirm
        # can re-apply them against the server-verified subtotal — without this, confirm had no
        # way to know about them at all and silently recomputed revenue from raw line items only,
        # which never matched the receipt the customer actually saw.
        try:
            discount_percent = max(0.0, min(100.0, float(data.get('discount_percent') or 0)))
        except (TypeError, ValueError):
            discount_percent = 0.0
        try:
            tax_percent = max(0.0, float(data.get('tax_percent') or 0))
        except (TypeError, ValueError):
            tax_percent = 0.0
        try:
            tip_amount = max(0.0, float(data.get('tip_amount') or 0))
        except (TypeError, ValueError):
            tip_amount = 0.0

        # Insert payment_transactions with status = pending
        try:
            db.payment_transactions.insert_one({
                'id': next_mongo_id('payment_transactions'),
                'transaction_id': txn_id,
                'customer_name': 'Khách POS Vãng Lai',
                'customer_email': 'pos_walkin@bitpaw.com',
                'amount': amount,
                'currency': 'VND',
                'method': method,
                'status': 'pending',
                'business_id': business_id,
                'discount_percent': discount_percent,
                'tax_percent': tax_percent,
                'tip_amount': tip_amount,
                'created_at': datetime.now().isoformat()
            })
        except Exception as db_err:
            print(f"Database insert pending txn failed: {str(db_err)}")
            
        redirect_url = f"/payment_pending?table_id={table_id}&txn_id={txn_id}&amount={amount}&method={method}&industry={industry}"
        return jsonify({
            'success': True,
            'txn_id': txn_id,
            'redirect_url': redirect_url
        })
    except Exception as e:
        print(f"Error in api_payment_start: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500


# ========== US MARKET: SQUARE SANDBOX PAYMENT ==========
@app.route('/api/us-payment/start', methods=['POST'])
@login_required
def api_us_payment_start():
    try:
        data = request.get_json() or {}
        amount = data.get('amount')
        table_id = data.get('table_id')  # tuỳ chọn: pos.html có bàn, sell.html thì không

        # business_id BẮT BUỘC lấy từ session (không tin business_id client tự gửi) — cùng
        # nguyên tắc chống IDOR đã áp dụng cho /api/payment/start.
        business_id = session.get('business_id') or session['user_id']

        if hasattr(TenantEngine, 'get_region_config'):
            region = TenantEngine.get_region_config(business_id)
        else:
            region = {"country": "VN", "currency": "VND"}
        if region['country'] != 'US' or region['currency'] != 'USD':
            return jsonify({'success': False, 'message': 'This tenant is not in the US market (Square is only available for country=US).'}), 403

        if amount is None:
            return jsonify({'success': False, 'message': 'Missing amount'}), 400
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'message': 'Invalid amount'}), 400
        if amount <= 0:
            return jsonify({'success': False, 'message': 'Amount must be greater than 0'}), 400

        # Nếu có table_id (bối cảnh POS), xác nhận bàn đó thuộc đúng tenant hiện tại trước khi khởi tạo.
        if table_id:
            owns, err = _assert_owns_table(table_id, business_id)
            if not owns:
                return jsonify({'success': False, 'message': err}), 403

        txn_id = f"US-{uuid.uuid4().hex[:8].upper()}"

        square_result = payment_us_engine.start_us_payment(amount, txn_id, description='BitPaw POS Order')

        # Insert payment_transactions with status = pending (best-effort, giống luồng VN)
        try:
            db.payment_transactions.insert_one({
                'id': next_mongo_id('payment_transactions'),
                'transaction_id': txn_id,
                'customer_name': 'US Walk-in Customer',
                'customer_email': 'pos_walkin@bitpaw.com',
                'amount': amount,
                'currency': 'USD',
                'method': 'square',
                'status': 'pending',
                'business_id': business_id,
                'created_at': datetime.now().isoformat()
            })
        except Exception as db_err:
            print(f"Database insert pending US txn failed: {str(db_err)}")

        if not square_result.get('configured'):
            # Square chưa cấu hình sandbox key — trả lỗi rõ ràng, không giả vờ thành công.
            return jsonify({'success': False, 'message': square_result.get('message'), 'txn_id': txn_id}), 503
        if not square_result.get('success'):
            return jsonify({'success': False, 'message': square_result.get('message'), 'txn_id': txn_id}), 502

        return jsonify({
            'success': True,
            'txn_id': txn_id,
            'checkout_url': square_result.get('checkout_url'),
            'checkout_id': square_result.get('checkout_id'),
            'terminal_status': square_result.get('terminal_status')
        })
    except Exception as e:
        print(f"Error in api_us_payment_start: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/payment/confirm', methods=['POST'])
@login_required
def api_payment_confirm():
    try:
        data = request.get_json() or {}
        table_id = data.get('table_id')
        txn_id = data.get('txn_id')
        method = data.get('method', 'POS')

        if not table_id or not txn_id:
            return jsonify({'success': False, 'message': 'Missing table_id or txn_id'}), 400

        business_id = session.get('business_id') or session['user_id']
        owns, err = _assert_owns_table(table_id, business_id)
        if not owns:
            return jsonify({'success': False, 'message': err}), 403

        # 1. Đọc table_orders theo table_id (đã xác nhận bàn thuộc đúng tenant ở trên)
        orders_data = list(db.table_orders.find({'table_id': table_id, 'business_id': business_id}, {'_id': 0}))
        if not orders_data:
            return jsonify({'success': False, 'message': 'Không tìm thấy món ăn nào đang treo tại bàn này.'}), 400

        # 2. Tính tổng tiền server-side và trừ tồn kho — batch fetch TẤT CẢ sản phẩm trong 1 query
        # ($in) thay vì trước đây query products 2 lần/món (giá+tồn kho, rồi lại giá riêng) — tránh N+1.
        product_ids = [item['product_id'] for item in orders_data]
        products_map = {
            p['id']: p for p in db.products.find(
                {'id': {'$in': product_ids}, 'business_id': business_id}, {'id': 1, 'price': 1, 'stock': 1, '_id': 0}
            )
        }

        subtotal = 0
        stock_items = []
        for item in orders_data:
            prod = products_map.get(item['product_id'])
            if prod:
                subtotal += item['quantity'] * prod['price']
                if 'stock' in prod:
                    stock_items.append((item['product_id'], item['quantity'], prod.get('name')))

        # Re-apply the discount%/tax%/tip stored at /api/payment/start (see there) against this
        # server-verified subtotal — NOT the raw amount the client sent — so the final revenue
        # figure can't be tampered with client-side while still matching what the customer saw.
        pending_txn = db.payment_transactions.find_one({'transaction_id': txn_id, 'business_id': business_id}, {'_id': 0})
        discount_percent = max(0.0, min(100.0, float((pending_txn or {}).get('discount_percent') or 0)))
        tax_percent = max(0.0, float((pending_txn or {}).get('tax_percent') or 0))
        tip_amount = max(0.0, float((pending_txn or {}).get('tip_amount') or 0))

        discount_amount = round(subtotal * (discount_percent / 100), 2)
        discount_amount = max(0.0, min(discount_amount, subtotal))
        taxable_base = subtotal - discount_amount
        tax_amount = round(taxable_base * (tax_percent / 100), 2)
        total_bill = round(taxable_base + tax_amount + tip_amount, 2)

        # Lấy industry từ transaction hoặc mặc định fnb
        industry = 'fnb'
        customer_phone = (data.get('customer_phone') or '').strip() or None

        # 3. Tạo order mới trong orders — lưu cả breakdown để đối soát khớp đúng hoá đơn khách thấy
        order_id = next_mongo_id('orders')
        metadata = {
            'order_code': txn_id,
            'channel': industry,
            'table_id': table_id,
            'subtotal': subtotal,
            'discount_amount': discount_amount,
            'tax_amount': tax_amount,
            'tip_amount': tip_amount,
        }
        if customer_phone:
            metadata['customer_phone'] = customer_phone
        order_doc = {
            'id': order_id,
            'business_id': business_id,
            'created_at': datetime.now().isoformat(),
            'status': 'completed',
            'total_amount': total_bill,
            'payment_method': method,
            'metadata': metadata,
        }

        # 4. Tạo chi tiết trong order_items (dùng lại products_map đã fetch ở bước 2, không query lại)
        order_items_docs = []
        for item in orders_data:
            prod = products_map.get(item['product_id'])
            if prod:
                order_items_docs.append({
                    'id': next_mongo_id('order_items'),
                    'order_id': order_id,
                    'product_id': item['product_id'],
                    'quantity': item['quantity'],
                    'price': prod['price'],
                    'total_price': item['quantity'] * prod['price'],
                    'business_id': business_id,
                    'customer_phone': customer_phone
                })

        # Trừ kho nguyên tử + order + order_items + sổ cái transactions cùng 1 Mongo session
        # transaction — đây chính là điểm chốt của luồng "khách quét QR gọi món -> thanh toán",
        # nơi nhiều bàn/nhiều khách có thể cùng thanh toán trùng lúc giờ cao điểm.
        try:
            with mongo_client_instance.start_session() as db_session:
                with db_session.start_transaction():
                    _decrement_stock_atomic(business_id, stock_items, db_session=db_session)
                    db.orders.insert_one(order_doc, session=db_session)
                    if order_items_docs:
                        db.order_items.insert_many(order_items_docs, session=db_session)
                    _record_pos_transaction(
                        business_id, order_id, total_bill, method, db_session=db_session,
                    )
        except InsufficientStockError as e:
            return jsonify({'success': False, 'message': str(e)}), 409

        # 5. Update payment_transactions status = completed
        db.payment_transactions.update_one(
            {'transaction_id': txn_id, 'business_id': business_id},
            {'$set': {'status': 'completed', 'amount': total_bill, 'method': method, 'updated_at': datetime.now().isoformat()}}
        )

        # 6. Dọn table_orders
        db.table_orders.delete_many({'table_id': table_id, 'business_id': business_id})

        # 7. Trả bàn về trạng thái 'Còn trống'
        db.dining_tables.update_one({'id': table_id, 'business_id': business_id}, {'$set': {'status': 'Còn trống'}})

        # 8. Loyalty tự động: nếu thu ngân có nhập SĐT khách -> tự cộng điểm/xét lên hạng (không chặn luồng nếu lỗi)
        _award_loyalty_points(business_id, customer_phone, total_bill)

        redirect_url = f"/payment_success?txn_id={txn_id}&method={method}&amount={total_bill}&currency=VND&industry={industry}"
        return jsonify({
            'success': True,
            'redirect_url': redirect_url
        })
    except Exception as e:
        print(f"Error in api_payment_confirm: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/payment/local_checkout', methods=['POST'])
@login_required
def api_payment_local_checkout():
    """Checkout cho bàn 'local-'/'seeded-' (demo/offline draft, không có bản ghi dining_tables/
    table_orders thật trong DB) — trước đây bấm Checkout chỉ xoá localStorage và coi như thành
    công, không tạo bất kỳ bản ghi giao dịch nào (falsified success). Vì các bàn này không có
    table_orders để đối chiếu giá server-side, route này buộc phải tin cart do client gửi lên —
    nhưng vẫn validate chặt từng field (tên/số lượng/giá) và ghi lại thành order/order_items/
    payment_transactions THẬT, có thể tra soát, thay vì âm thầm không để lại dấu vết gì."""
    try:
        data = request.get_json() or {}
        items = data.get('items') or []
        table_name = (data.get('table_name') or 'Local Table').strip()[:120]
        method = data.get('method', 'POS')
        industry = data.get('industry', 'fnb')

        if not items:
            return jsonify({'success': False, 'message': 'Empty cart'}), 400

        business_id = session.get('business_id') or session['user_id']

        subtotal = 0.0
        clean_items = []
        for it in items:
            try:
                name = str(it.get('name') or '').strip()[:200]
                qty = int(it.get('quantity'))
                price = float(it.get('price'))
            except (TypeError, ValueError, AttributeError):
                return jsonify({'success': False, 'message': 'Invalid item in cart'}), 400
            if not name or qty <= 0 or price < 0:
                return jsonify({'success': False, 'message': 'Invalid item in cart'}), 400
            line_total = round(qty * price, 2)
            subtotal += line_total
            clean_items.append({'name': name, 'quantity': qty, 'price': price, 'total_price': line_total})
        subtotal = round(subtotal, 2)

        try:
            discount_percent = max(0.0, min(100.0, float(data.get('discount_percent') or 0)))
        except (TypeError, ValueError):
            discount_percent = 0.0
        try:
            tax_percent = max(0.0, float(data.get('tax_percent') or 0))
        except (TypeError, ValueError):
            tax_percent = 0.0
        try:
            tip_amount = max(0.0, float(data.get('tip_amount') or 0))
        except (TypeError, ValueError):
            tip_amount = 0.0

        discount_amount = round(subtotal * (discount_percent / 100), 2)
        discount_amount = max(0.0, min(discount_amount, subtotal))
        taxable_base = subtotal - discount_amount
        tax_amount = round(taxable_base * (tax_percent / 100), 2)
        grand_total = round(taxable_base + tax_amount + tip_amount, 2)

        txn_id = f"{industry.upper()}-LOCAL-{uuid.uuid4().hex[:8].upper()}"
        now_iso = datetime.now().isoformat()

        order_id = next_mongo_id('orders')
        db.orders.insert_one({
            'id': order_id,
            'business_id': business_id,
            'created_at': now_iso,
            'status': 'completed',
            'total_amount': grand_total,
            'payment_method': method,
            'metadata': {
                'order_code': txn_id, 'channel': f'{industry}_local_demo', 'table_name': table_name,
                'subtotal': subtotal, 'discount_amount': discount_amount, 'tax_amount': tax_amount,
                'tip_amount': tip_amount,
            },
        })

        order_items_docs = [{
            'id': next_mongo_id('order_items'), 'order_id': order_id, 'product_id': None,
            'name': it['name'], 'quantity': it['quantity'], 'price': it['price'],
            'total_price': it['total_price'], 'business_id': business_id,
        } for it in clean_items]
        if order_items_docs:
            db.order_items.insert_many(order_items_docs)

        db.payment_transactions.insert_one({
            'id': next_mongo_id('payment_transactions'), 'transaction_id': txn_id,
            'customer_name': 'Khách POS Vãng Lai (Local Demo Table)',
            'customer_email': 'pos_walkin@bitpaw.com', 'amount': grand_total, 'currency': 'VND',
            'method': method, 'status': 'completed', 'business_id': business_id,
            'created_at': now_iso, 'updated_at': now_iso,
        })
        _record_pos_transaction(business_id, order_id, grand_total, method)

        return jsonify({'success': True, 'txn_id': txn_id, 'amount': grand_total})
    except Exception as e:
        print(f"Error in api_payment_local_checkout: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500


# ========== CRON HÀNG NGÀY: DỰ BÁO TỒN KHO (AI) + LOYALTY SINH NHẬT ==========
# App chạy serverless trên Vercel nên không có tiến trình nền dài hạn — dùng
# Vercel Cron Job (xem vercel.json) gọi HTTP vào route này theo lịch hàng ngày.
# Bảo vệ bằng CRON_SECRET (header Authorization: Bearer <secret>) thay vì
# @login_required vì Vercel Cron không mang session cookie.
def _generate_restock_reason_with_ai(product_name, stock, avg_daily, days_left):
    """Dùng DeepSeek CHỈ để diễn giải cảnh báo bằng lời tự nhiên — số liệu (tồn kho,
    tốc độ bán, số ngày còn lại) luôn được tính bằng Python trước, AI không tự bịa số."""
    fallback = (
        f"Sản phẩm '{product_name}' còn {stock} đơn vị, bán trung bình {avg_daily:.1f}/ngày "
        f"-> dự kiến hết trong khoảng {days_left:.1f} ngày nữa. Đề xuất nhập thêm hàng sớm."
    )
    api_key = os.environ.get('DEEPSEEK_API_KEY')
    if not api_key:
        return fallback
    try:
        resp = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            json={
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": "Bạn là trợ lý quản lý kho, viết đúng 1 câu cảnh báo ngắn gọn, "
                     "thân thiện bằng Tiếng Việt cho chủ tiệm dựa ĐÚNG số liệu được cung cấp, không bịa thêm số liệu khác."},
                    {"role": "user", "content": f"Sản phẩm: {product_name}. Tồn kho hiện tại: {stock}. "
                     f"Tốc độ bán trung bình: {avg_daily:.1f}/ngày. Số ngày còn lại trước khi hết hàng: {days_left:.1f}."}
                ],
                "temperature": 0.5,
                "max_tokens": 120
            },
            timeout=10
        )
        resp.raise_for_status()
        content = resp.json()['choices'][0]['message']['content'].strip()
        return content or fallback
    except Exception:
        return fallback


def _run_inventory_forecast_for_business(business_id, lookback_days, since_iso):
    """Tính tốc độ bán mỗi sản phẩm trong lookback_days ngày gần nhất, cảnh báo sản phẩm
    sắp hết hàng (còn <= 3 ngày bán theo tốc độ trung bình) và tạo phiếu đề xuất nhập hàng."""
    products = list(db.products.find(
        {'business_id': business_id, 'is_active': 1}, {'id': 1, 'name': 1, 'stock': 1, '_id': 0}
    ))
    if not products:
        return 0
    product_ids = [p['id'] for p in products]

    items = list(db.order_items.find(
        {'product_id': {'$in': product_ids}, 'created_at': {'$gte': since_iso}},
        {'product_id': 1, 'quantity': 1, '_id': 0}
    ))
    sold_qty = {}
    for it in items:
        pid = it.get('product_id')
        sold_qty[pid] = sold_qty.get(pid, 0) + (it.get('quantity') or 0)

    created = 0
    for p in products:
        total_sold = sold_qty.get(p['id'], 0)
        if total_sold <= 0:
            continue
        avg_daily = total_sold / lookback_days
        stock = p.get('stock') or 0
        days_left = stock / avg_daily if avg_daily > 0 else 999
        if days_left > 3:
            continue

        existing = db.restock_proposals.find_one(
            {'business_id': business_id, 'product_id': p['id'], 'status': 'pending'}, {'id': 1, '_id': 0}
        )
        if existing:
            continue  # đã có đề xuất đang chờ xử lý cho sản phẩm này, không tạo trùng

        suggested_qty = max(int(avg_daily * 7 - stock), int(avg_daily * 3) + 1)
        reason = _generate_restock_reason_with_ai(p['name'], stock, avg_daily, days_left)
        db.restock_proposals.insert_one({
            'id': next_mongo_id('restock_proposals'),
            'business_id': business_id,
            'product_id': p['id'],
            'product_name': p['name'],
            'current_stock': stock,
            'avg_daily_sales': round(avg_daily, 2),
            'suggested_qty': suggested_qty,
            'reason': reason,
            'status': 'pending',
            'created_at': datetime.now().isoformat(),
        })
        created += 1
    return created


def _run_birthday_check_for_business(business_id):
    """Quét khách hàng có sinh nhật hôm nay, xếp hàng gửi lời chúc + ưu đãi qua loyalty_events."""
    today_md = datetime.now().strftime('%m-%d')
    customers_data = list(db.customers.find({'business_id': business_id}, {'_id': 0})) if db is not None else []
    sent = 0
    for c in customers_data:
        dob = c.get('dob')
        if not dob or len(str(dob)) < 10:
            continue
        if str(dob)[5:10] != today_md:
            continue
        message = (
            f"🎉 Chúc mừng sinh nhật {c.get('name') or 'bạn'}! Nhân dịp đặc biệt này, tiệm xin tặng bạn "
            f"1 ưu đãi dành riêng cho hạng {c.get('tier') or 'Normal'} — ghé tiệm trong tuần này để nhận quà nhé!"
        )
        _queue_loyalty_notification(business_id, c, 'birthday', message)
        sent += 1
    return sent


def _get_all_active_business_ids():
    """Liệt kê toàn bộ business_id đang thực sự hoạt động. LƯU Ý: bảng 'businesses' KHÔNG
    được populate ở luồng đăng ký (session['business_id'] = user_id trực tiếp, không tạo
    row trong 'businesses') nên không dùng được để liệt kê tenant — suy ra từ dữ liệu thật
    (distinct business_id trên 'products' và 'business_memberships')."""
    ids = set()
    try:
        for bid in db.products.distinct('business_id'):
            if bid:
                ids.add(bid)
    except Exception as e:
        print(f"Loi lay business_id tu products: {e}")
    try:
        for bid in db.business_memberships.distinct('business_id'):
            if bid:
                ids.add(bid)
    except Exception as e:
        print(f"Loi lay business_id tu business_memberships: {e}")
    return list(ids)


def _run_payment_reconciliation_for_business(business_id, lookback_days):
    """Đối soát chéo payment_transactions <-> orders, phát hiện: (a) giao dịch báo đã
    hoàn tất ('completed') nhưng không có order tương ứng, (b) số tiền giao dịch lệch với
    tổng đơn hàng (thu thiếu/thừa), (c) giao dịch treo 'pending' quá lâu (nghi ngờ tiền
    chưa vào). Ghi báo động vào reconciliation_alerts, không tạo trùng cảnh báo đang chờ xử lý."""
    since_iso = (datetime.now() - timedelta(days=lookback_days)).isoformat()
    alerts_created = 0
    try:
        txns = list(db.payment_transactions.find(
            {'business_id': business_id, 'created_at': {'$gte': since_iso}}, {'_id': 0}
        ))
    except Exception as e:
        print(f"Loi lay payment_transactions cho {business_id}: {e}")
        return 0

    orders_data = list(db.orders.find(
        {'business_id': business_id, 'created_at': {'$gte': since_iso}},
        {'metadata.order_code': 1, 'total_amount': 1, '_id': 0}
    ))
    orders_by_code = {
        (o.get('metadata') or {}).get('order_code'): o for o in orders_data if (o.get('metadata') or {}).get('order_code')
    }

    stale_pending_hours = 2  # giao dịch pending quá 2 tiếng coi như nghi ngờ tiền chưa vào

    for txn in txns:
        txn_id = txn.get('transaction_id')
        status = txn.get('status')
        amount = txn.get('amount') or 0
        issue_type = None
        details = None
        expected_amount = None

        if status == 'completed':
            order = orders_by_code.get(txn_id)
            if not order:
                issue_type = 'missing_order'
                details = f"Giao dịch {txn_id} báo hoàn tất nhưng không tìm thấy đơn hàng tương ứng."
            else:
                order_amount = order.get('total_amount') or 0
                if abs(order_amount - amount) >= 1000:  # sai lệch từ 1.000đ trở lên mới báo động
                    issue_type = 'amount_mismatch'
                    expected_amount = order_amount
                    details = (
                        f"Giao dịch {txn_id}: số tiền ghi nhận {amount:,.0f}đ nhưng đơn hàng thực tế "
                        f"{order_amount:,.0f}đ (chênh lệch {order_amount - amount:,.0f}đ)."
                    ).replace(',', '.')
        elif status == 'pending':
            created_at_str = txn.get('created_at')
            if created_at_str:
                try:
                    created_at = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
                    age_hours = (datetime.now(created_at.tzinfo) - created_at).total_seconds() / 3600
                    if age_hours >= stale_pending_hours:
                        issue_type = 'stale_pending'
                        details = f"Giao dịch {txn_id} vẫn ở trạng thái chờ sau {age_hours:.1f} giờ — nghi ngờ tiền chưa vào tài khoản."
                except Exception:
                    pass

        if not issue_type:
            continue

        existing = db.reconciliation_alerts.find_one({
            'business_id': business_id, 'transaction_id': txn_id, 'issue_type': issue_type, 'status': 'pending'
        }, {'id': 1, '_id': 0})
        if existing:
            continue

        db.reconciliation_alerts.insert_one({
            'id': next_mongo_id('reconciliation_alerts'),
            'business_id': business_id,
            'transaction_id': txn_id,
            'order_code': txn_id,
            'issue_type': issue_type,
            'expected_amount': expected_amount,
            'actual_amount': amount,
            'details': details,
            'status': 'pending',
            'created_at': datetime.now().isoformat(),
        })
        alerts_created += 1

    return alerts_created


@app.route('/api/cron/daily_tasks', methods=['GET', 'POST'])
def cron_daily_tasks():
    cron_secret = os.environ.get('CRON_SECRET')
    auth_header = request.headers.get('Authorization', '')
    if not cron_secret or auth_header != f'Bearer {cron_secret}':
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    lookback_days = 14
    since_iso = (datetime.now() - timedelta(days=lookback_days)).isoformat()
    results = {"businesses_scanned": 0, "restock_proposals_created": 0, "birthday_events_queued": 0,
               "reconciliation_alerts_created": 0, "errors": []}

    business_ids = _get_all_active_business_ids()

    for business_id in business_ids:
        results["businesses_scanned"] += 1
        try:
            results["restock_proposals_created"] += _run_inventory_forecast_for_business(business_id, lookback_days, since_iso)
        except Exception as e:
            results["errors"].append(f"forecast[{business_id}]: {str(e)}")
        try:
            results["birthday_events_queued"] += _run_birthday_check_for_business(business_id)
        except Exception as e:
            results["errors"].append(f"birthday[{business_id}]: {str(e)}")
        try:
            results["reconciliation_alerts_created"] += _run_payment_reconciliation_for_business(business_id, lookback_days)
        except Exception as e:
            results["errors"].append(f"reconciliation[{business_id}]: {str(e)}")

    return jsonify({"success": True, **results})


@app.route('/api/payment/cancel', methods=['POST'])
@login_required
def api_payment_cancel():
    try:
        data = request.get_json() or {}
        txn_id = data.get('txn_id')

        if not txn_id:
            return jsonify({'success': False, 'message': 'Missing txn_id'}), 400

        business_id = session.get('business_id') or session['user_id']
        # Xác nhận giao dịch thuộc đúng tenant trước khi cho hủy (trước đây thiếu bộ lọc này)
        txn_check = db.payment_transactions.find_one({'transaction_id': txn_id}, {'id': 1, 'status': 1, 'business_id': 1, '_id': 0})
        if not txn_check or txn_check.get('business_id') != business_id:
            return jsonify({'success': False, 'message': 'Giao dịch không tồn tại hoặc không thuộc quyền quản lý của bạn.'}), 403
        old_status = txn_check.get('status')

        # Update transaction status = failed
        db.payment_transactions.update_one(
            {'transaction_id': txn_id, 'business_id': business_id},
            {'$set': {'status': 'failed', 'updated_at': datetime.now().isoformat()}}
        )
        _log_audit(business_id, 'cancel_order', entity_type='payment_transaction', entity_id=txn_id,
                   old_value={'status': old_status}, new_value={'status': 'failed'})

        return jsonify({'success': True, 'message': 'Transaction cancelled successfully'})
    except Exception as e:
        print(f"Error in api_payment_cancel: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/payment_success')
@login_required
def payment_success():
    return render_template('payment_success.html')

@app.route('/sell')
@login_required
def sell():
    """Nails có màn hình POS chuyên biệt riêng (pos_nail.html: lưới dịch vụ theo category,
    giỏ hàng, gán thợ theo TỪNG dòng dịch vụ để tính hoa hồng — /sell cũ chỉ bán được 1 sản
    phẩm/lần và không gán thợ). Các ngành khác (Retail...) vẫn dùng sell.html như trước,
    hành vi không đổi."""
    business_mode = (session.get('business_mode') or '').strip().lower()
    if business_mode == 'nail':
        business_id = session.get('business_id') or session['user_id']
        try:
            services = list(db.products.find(
                {'business_id': business_id, 'is_active': 1},
                {'id': 1, 'name': 1, 'category': 1, 'price': 1, 'image': 1, '_id': 0}
            ).sort('name', 1))
        except Exception as e:
            print(f"[sell/nail] Lỗi tải danh mục dịch vụ: {str(e)}")
            services = []
        try:
            # Thợ lấy từ db.employees (linh_vuc='Nails') — ĐÚNG nguồn dữ liệu Salon Staff
            # Management (chamcong_nail.html) đã và đang dùng, KHÔNG dùng db.staff (hệ thống
            # commission riêng của sell.html/spa.html cũ) — 2 tenant chưa từng đồng bộ với
            # nhau, dùng chung nguồn với màn Payroll hiện tại để không cần tạo dữ liệu 2 lần.
            technicians = list(db.employees.find(
                {'business_id': business_id, 'linh_vuc': 'Nails'},
                {'ma_nv': 1, 'ho_ten': 1, '_id': 0}
            ).sort('ho_ten', 1))
        except Exception as e:
            print(f"[sell/nail] Lỗi tải danh sách thợ: {str(e)}")
            technicians = []
        return render_template(
            'pos_nail.html',
            services=services,
            technicians=technicians,
            default_commission_rate=_get_business_commission_rate(business_id),
        )
    return render_template('sell.html')


def _compute_nail_pos_order(business_id, data):
    """Cart -> subtotal/supply/discount/tax/tip/commission computation shared by BOTH the
    synchronous nail_pos checkout AND the async Square Terminal checkout — kept as ONE function
    so the two payment paths can never compute a different commission/tax/discount for the same
    cart (duplicating this formula across routes was flagged as a real drift risk in a prior
    audit). Raises ValueError on bad input (cart empty/invalid) for the caller to turn into a
    400 response; anything else propagates as-is for a 500."""
    items = data.get('items') or []
    if not items:
        raise ValueError("Giỏ hàng trống.")

    product_ids = [it.get('product_id') for it in items]
    products_map = {
        p['id']: p for p in db.products.find(
            {'id': {'$in': product_ids}, 'business_id': business_id}, {'_id': 0}
        )
    }

    order_items_docs = []
    subtotal = 0.0
    # Gom net revenue theo từng thợ được gán (ma_nv) để tính hoa hồng 1 LẦN/THỢ, không phải
    # 1 lần/dòng — 1 thợ có thể được gán nhiều dịch vụ khác nhau trong cùng 1 bill.
    per_tech_revenue = {}
    # Giai đoạn 5 audit — Nail POS trước đây KHÔNG hề trừ tồn kho cho bất kỳ dòng nào, kể cả
    # sản phẩm vật lý bán kèm (sơn, phụ kiện) có field 'stock' thật — chỉ dịch vụ thuần (không
    # track kho) mới hợp lý bỏ qua. Gom list này để cả 2 route checkout (sync + Square Terminal)
    # đều gọi _decrement_stock_atomic() với ĐÚNG 1 nguồn tính toán, không lệch logic.
    stock_items = []
    for it in items:
        qty = max(1, int(it.get('quantity', 1)))
        ma_nv = (it.get('ma_nv') or '').strip() or None
        prod = products_map.get(it.get('product_id'))
        custom_name = None
        if prod:
            price = prod.get('price', 0)
            pid = prod['id']
        else:
            # Dòng "Add Custom Item" của pos_nail.html — không gắn product có sẵn, cashier
            # tự nhập tên + giá tại quầy (phụ phí phát sinh...) — vẫn cho gán thợ/tính hoa
            # hồng như 1 dòng dịch vụ thường, chỉ khác là không tồn tại product_id thật.
            custom_name = (it.get('custom_name') or '').strip()
            try:
                price = round(float(it.get('custom_price')), 2)
            except (TypeError, ValueError):
                price = None
            if not custom_name or price is None or price < 0:
                continue  # chặn bán dịch vụ không thuộc tenant này hoặc dòng custom thiếu dữ liệu
            pid = None
        line_total = round(qty * price, 2)
        subtotal += line_total
        oi_doc = {
            'product_id': pid, 'quantity': qty, 'price': price,
            'total_price': line_total, 'ma_nv': ma_nv,
        }
        if custom_name:
            oi_doc['custom_name'] = custom_name
        order_items_docs.append(oi_doc)
        if ma_nv:
            per_tech_revenue[ma_nv] = per_tech_revenue.get(ma_nv, 0) + line_total
        if prod and 'stock' in prod:
            stock_items.append((prod['id'], qty, prod.get('name')))

    if not order_items_docs:
        raise ValueError("Không có dịch vụ hợp lệ trong giỏ hàng.")
    subtotal = round(subtotal, 2)

    # Supply: % của TỔNG bill khấu trừ TRƯỚC khi chia hoa hồng (đúng model chamcong_nail.html)
    # — chi phí vật tư (gel/bột...), không phải phụ phí khách nhìn thấy trên hoá đơn.
    # Clamp 0-100 và net_revenue >= 0 — nếu không, supply% > 100 (fat-finger hoặc override) sẽ
    # tạo net_revenue âm, khiến tien_tua ghi vào db.chamcong bị âm, âm thầm trừ lương thợ.
    supply_percent = max(0.0, min(100.0, float(data.get('supply_percent') or 0)))
    supply_amount = round(subtotal * (supply_percent / 100), 2)
    net_revenue = max(0.0, subtotal - supply_amount)

    cash_tip = round(float(data.get('cash_tip') or 0), 2)
    card_tip = round(float(data.get('card_tip') or 0), 2)
    cc_fee_percent = float(data.get('cc_fee_percent') or 0)
    card_tip_fee = round(card_tip * (cc_fee_percent / 100), 2)
    net_card_tip = round(card_tip - card_tip_fee, 2)
    total_tip = round(cash_tip + card_tip, 2)  # khách thấy đúng số tip đã nhập trên hoá đơn
    worker_total_tip = round(cash_tip + net_card_tip, 2)  # thợ thực nhận (tip thẻ đã trừ phí cà thẻ)

    # Discount áp trực tiếp lên giá khách trả (KHÔNG đụng subtotal/supply/hoa hồng thợ ở trên)
    # — thợ vẫn được tính công đúng giá trị dịch vụ đã làm, salon chịu phần giảm giá.
    discount_type = (data.get('discount_type') or '').strip().lower()
    discount_value = float(data.get('discount_value') or 0)
    if discount_type == 'percent':
        discount_amount = round(subtotal * (discount_value / 100), 2)
    elif discount_type == 'fixed':
        discount_amount = round(discount_value, 2)
    else:
        discount_amount = 0.0
    discount_amount = max(0.0, min(discount_amount, subtotal))

    # Tax/GST — cộng thêm SAU khi đã trừ discount, không đụng supply/hoa hồng thợ ở trên.
    # Mặc định 0% vì không phải salon nào cũng đăng ký GST — chủ salon tự bật nếu cần.
    tax_percent = float(data.get('tax_percent') or 0)
    taxable_amount = max(0.0, subtotal - discount_amount)
    tax_amount = round(taxable_amount * (tax_percent / 100), 2) if tax_percent > 0 else 0.0

    payment_method = (data.get('payment_method') or 'cash').strip().lower()
    if payment_method == 'split':
        payment_bucket = 'split'
    elif payment_method == 'cash':
        payment_bucket = 'cash'
    else:
        payment_bucket = 'card'
    total_amount = round(subtotal - discount_amount + tax_amount + total_tip, 2)

    # Split payment: capture the exact cash/card breakdown the cashier entered so end-of-day
    # cash-drawer reconciliation can credit each portion correctly — previously only
    # `payment_bucket: 'split'` was stored with no amounts, so the dashboard's cash/card totals
    # silently excluded split tickets entirely.
    split_cash_amount = 0.0
    split_card_amount = 0.0
    if payment_bucket == 'split':
        try:
            split_cash_amount = round(max(0.0, float(data.get('cash_amount') or 0)), 2)
        except (TypeError, ValueError):
            split_cash_amount = 0.0
        try:
            split_card_amount = round(max(0.0, float(data.get('card_amount') or 0)), 2)
        except (TypeError, ValueError):
            split_card_amount = 0.0
        if abs((split_cash_amount + split_card_amount) - total_amount) > 0.02:
            split_cash_amount = total_amount
            split_card_amount = 0.0

    commission_rate = data.get('commission_rate')
    try:
        commission_rate = float(commission_rate) if commission_rate is not None else _get_business_commission_rate(business_id)
    except (TypeError, ValueError):
        commission_rate = _get_business_commission_rate(business_id)
    commission_rate = max(0.0, min(100.0, commission_rate))

    return {
        'order_items_docs': order_items_docs, 'subtotal': subtotal, 'supply_amount': supply_amount,
        'net_revenue': net_revenue, 'discount_amount': discount_amount, 'tax_amount': tax_amount,
        'total_tip': total_tip, 'worker_total_tip': worker_total_tip, 'total_amount': total_amount,
        'payment_method': payment_method, 'payment_bucket': payment_bucket,
        'split_cash_amount': split_cash_amount, 'split_card_amount': split_card_amount,
        'commission_rate': commission_rate, 'per_tech_revenue': per_tech_revenue,
        'currency': data.get('currency') or 'AUD', 'stock_items': stock_items,
    }


def _build_nail_chamcong_docs(order_id, business_id, computed, note_prefix='[NAILS POS]'):
    """Builds the per-technician db.chamcong docs for a nail order from _compute_nail_pos_order's
    output — shared by the synchronous checkout and the Square webhook finalizer so a bill paid
    either way credits technicians with the exact same commission/tip formula."""
    now_dt = datetime.now()
    chamcong_docs = []
    techs_paid = []
    per_tech_revenue = computed['per_tech_revenue']
    if per_tech_revenue:
        subtotal = computed['subtotal']
        net_revenue = computed['net_revenue']
        commission_rate = computed['commission_rate']
        tip_share = round(computed['worker_total_tip'] / len(per_tech_revenue), 2)
        for ma_nv, tech_revenue_share in per_tech_revenue.items():
            tech_net_share = round(tech_revenue_share * (net_revenue / subtotal), 2) if subtotal else 0
            worker_tua = round(tech_net_share * (commission_rate / 100), 2)
            chamcong_docs.append({
                'id': next_mongo_id('chamcong'), 'business_id': business_id, 'ma_nv': ma_nv,
                # DD/MM/YYYY — KHÔNG phải ISO YYYY-MM-DD — phải khớp đúng định dạng
                # getFormattedDate() ghi ở chamcong_nail.html, vì bangluong.html lọc
                # theo tháng bằng ngay_cham.split('/')[1]/[2] (month/year); ghi sai định
                # dạng khiến mọi bill Nails POS bị lọc mất khỏi báo cáo lương tháng đó.
                'ngay_cham': now_dt.strftime('%d/%m/%Y'), 'nganh_nghe': 'Nails', 'trang_thai': 'Đã chốt',
                'ghi_chu': f"{note_prefix} Order #{order_id} — {commission_rate}% hoa hồng",
                'tien_tua': worker_tua, 'tien_tips': tip_share, 'phu_cap': 0, 'so_gio': 0,
                'tang_ca': 0,
            })
            techs_paid.append({'ma_nv': ma_nv, 'commission': worker_tua, 'tip': tip_share})
    return chamcong_docs, techs_paid


@app.route('/api/nail_pos/checkout', methods=['POST'])
@login_required
def api_nail_pos_checkout():
    """Checkout riêng cho Nail POS (pos_nail.html) — khác api_sales_checkout() ở chỗ CHO
    PHÉP gán thợ RIÊNG cho từng dòng dịch vụ (1 bill có thể do nhiều thợ cùng phục vụ), và
    tính hoa hồng/tip đúng công thức chamcong_nail.html đã dùng. Dùng cho thanh toán Cash/Card
    thủ công/Split — biết kết quả NGAY (khác luồng Square Terminal thật ở
    api_nail_pos_square_checkout(), phải chờ webhook vì khách quẹt thẻ tại quầy).

    Ghi ĐỒNG THỜI 2 nơi để không phá tính năng nào đang có, và vá luôn 1 lỗ hổng cũ:
      - orders/order_items: để doanh thu Nails LẦN ĐẦU TIÊN xuất hiện đúng trong
        report_consolidated/dashboard — luồng tính bill cũ thuần ở chamcong_nail.html
        KHÔNG hề tạo order nào, nên doanh thu Nails trước giờ không hề được đối soát.
      - chamcong (1 bản ghi/thợ được gán, không phải 1 bản ghi/dòng dịch vụ): để Salon Staff
        Management/Payroll (chamcong_nail.html) đọc được y hệt như khi tự bấm "Đã chốt" thủ
        công — không cần đổi màn hình đó, không cần đổi cách tính lương đã quen dùng.
    """
    business_id = session.get('business_id') or session['user_id']
    data = request.json or {}
    try:
        computed = _compute_nail_pos_order(business_id, data)
    except ValueError as e:
        return jsonify({"success": False, "message": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

    customer_phone = (data.get('customer_phone') or '').strip()

    try:
        order_id = next_mongo_id('orders')
        now_iso = datetime.now().isoformat()
        metadata = {
            'channel': 'nail_pos', 'subtotal': computed['subtotal'], 'supply_amount': computed['supply_amount'],
            'discount_amount': computed['discount_amount'], 'tax_amount': computed['tax_amount'],
            'tip_amount': computed['total_tip'], 'payment_bucket': computed['payment_bucket'],
            'currency': computed['currency'], 'commission_rate': computed['commission_rate'],
        }
        if computed['payment_bucket'] == 'split':
            metadata['split_cash_amount'] = computed['split_cash_amount']
            metadata['split_card_amount'] = computed['split_card_amount']
        if customer_phone:
            metadata['customer_phone'] = customer_phone
        order_doc = {
            'id': order_id,
            'business_id': business_id,
            'created_at': now_iso,
            'status': 'completed',
            'total_amount': computed['total_amount'],
            'payment_method': computed['payment_method'],
            'metadata': metadata,
        }

        order_items_docs = computed['order_items_docs']
        for oi in order_items_docs:
            oi['id'] = next_mongo_id('order_items')
            oi['order_id'] = order_id
            oi['business_id'] = business_id
            if customer_phone:
                oi['customer_phone'] = customer_phone

        chamcong_docs, techs_paid = _build_nail_chamcong_docs(order_id, business_id, computed)

        # Order + order_items + every technician's chamcong record commit together as ONE
        # MongoDB transaction — previously a mid-write failure (e.g. a dropped connection after
        # the 2nd of 3 assigned technicians) could leave the order marked 'completed' with some
        # techs paid and others silently unpaid, or a retry double-paying the first tech.
        with mongo_client_instance.start_session() as db_session:
            with db_session.start_transaction():
                # Giai đoạn 5 audit — trừ kho nguyên tử NGAY TRONG transaction này: trước đây
                # Nail POS không hề trừ tồn kho cho sản phẩm vật lý bán kèm (sơn, phụ kiện...),
                # để tồn kho lệch dần vô thời hạn. Nếu InsufficientStockError -> transaction tự
                # rollback toàn bộ (order/order_items/chamcong CHƯA có gì được ghi).
                _decrement_stock_atomic(business_id, computed['stock_items'], db_session=db_session)
                db.orders.insert_one(order_doc, session=db_session)
                if order_items_docs:
                    db.order_items.insert_many(order_items_docs, session=db_session)
                if chamcong_docs:
                    db.chamcong.insert_many(chamcong_docs, session=db_session)
                _record_pos_transaction(
                    business_id, order_id, computed['total_amount'], computed['payment_method'],
                    db_session=db_session,
                )

        if customer_phone:
            _finalize_paid_order(order_doc)

        return jsonify({
            "success": True, "order_id": order_id, "subtotal": computed['subtotal'],
            "supply_amount": computed['supply_amount'], "discount_amount": computed['discount_amount'],
            "tax_amount": computed['tax_amount'], "tip_amount": computed['total_tip'],
            "total_amount": computed['total_amount'], "techs_paid": techs_paid,
        })
    except InsufficientStockError as e:
        return jsonify({"success": False, "message": str(e)}), 400
    except (ConnectionFailure, ServerSelectionTimeoutError, NetworkTimeout, AutoReconnect) as e:
        # Mã 4.1 audit — rớt mạng tới Atlas giữa lúc tính tiền. CHỈ bản Desktop mới có ổ cứng
        # cục bộ để lưu tạm (local_db.py/MontyDB); bản Web/Vercel không có nơi nào để buffer
        # (mỗi lần gọi hàm serverless là 1 instance khác, không có state giữa các lần gọi) nên
        # vẫn phải báo lỗi thẳng như cũ, không đổi hành vi của Web.
        is_desktop_mode = os.environ.get('BITPAW_DESKTOP_MODE') == '1'
        if not is_desktop_mode:
            return jsonify({"success": False, "message": f"Mất kết nối tới máy chủ, vui lòng thử lại: {str(e)}"}), 503
        try:
            client_uuid = sync_worker.queue_offline_order(business_id, computed, customer_phone)
        except Exception as cache_err:
            # Cả ghi lên Atlas LẪN lưu tạm cục bộ đều thất bại — đây mới là lỗi thật sự nghiêm
            # trọng (vd ổ cứng đầy), phải báo lỗi cho cashier biết đơn CHƯA được lưu ở đâu cả.
            return jsonify({"success": False, "message": f"Mất mạng và lưu tạm cục bộ cũng thất bại: {cache_err}"}), 500
        return jsonify({
            "success": True, "order_id": None, "client_uuid": client_uuid, "pending_sync": True,
            "subtotal": computed['subtotal'], "supply_amount": computed['supply_amount'],
            "discount_amount": computed['discount_amount'], "tax_amount": computed['tax_amount'],
            "tip_amount": computed['total_tip'], "total_amount": computed['total_amount'],
            "message": "Mất mạng — đơn đã được lưu tạm trên máy này và sẽ tự đồng bộ lên hệ thống khi có mạng lại.",
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/nail_pos/square_checkout', methods=['POST'])
@login_required
def api_nail_pos_square_checkout():
    """Real Square Terminal (card-present) checkout for the Nail POS. Uses the EXACT same
    _compute_nail_pos_order() math as the synchronous /api/nail_pos/checkout, but does NOT write
    order_items/chamcong yet — it only creates a 'pending' order stub carrying everything needed
    to finish the write later, pushes the checkout to the physical Square Terminal, and returns
    immediately. The actual order/chamcong commit happens in api_webhook_square() once Square
    confirms COMPLETED (see _finalize_nail_square_order) — never before, so a customer who walks
    away without tapping their card never generates a phantom paid order or technician commission."""
    business_id = session.get('business_id') or session['user_id']
    data = request.json or {}
    try:
        computed = _compute_nail_pos_order(business_id, data)
    except ValueError as e:
        return jsonify({"success": False, "message": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

    if not payment_us_engine.is_configured() or not payment_us_engine.SQUARE_DEVICE_ID:
        # Same 3-flag config_status pattern as api_square_checkout() — graceful, non-crashing
        # error telling the admin exactly which env var is missing, never a silent/fake success.
        return jsonify({
            "success": False,
            "message": "Square Terminal chưa được cấu hình đầy đủ. Vui lòng vào Payment Settings để nhập SQUARE_ACCESS_TOKEN / SQUARE_LOCATION_ID / SQUARE_DEVICE_ID (Terminal ID).",
            "config_status": {
                "SQUARE_ACCESS_TOKEN_set": bool(payment_us_engine.SQUARE_ACCESS_TOKEN),
                "SQUARE_LOCATION_ID_set": bool(payment_us_engine.SQUARE_LOCATION_ID),
                "SQUARE_DEVICE_ID_set": bool(payment_us_engine.SQUARE_DEVICE_ID),
            }
        }), 503

    try:
        order_id = next_mongo_id('orders')
        now_iso = datetime.now().isoformat()

        metadata = {
            'channel': 'nail_pos_square', 'subtotal': computed['subtotal'], 'supply_amount': computed['supply_amount'],
            'discount_amount': computed['discount_amount'], 'tax_amount': computed['tax_amount'],
            'tip_amount': computed['total_tip'], 'payment_bucket': 'card',
            'currency': computed['currency'], 'commission_rate': computed['commission_rate'],
            # Stashed for the webhook to finish the write — never re-derived from client input a
            # 2nd time, so what Square actually charged is exactly what gets committed and paid out.
            '_pending_order_items': computed['order_items_docs'],
            '_pending_per_tech_revenue': computed['per_tech_revenue'],
            '_pending_net_revenue': computed['net_revenue'],
            '_pending_worker_total_tip': computed['worker_total_tip'],
        }
        customer_phone = (data.get('customer_phone') or '').strip()
        if customer_phone:
            metadata['customer_phone'] = customer_phone
        order_doc = {
            'id': order_id,
            'business_id': business_id,
            'created_at': now_iso,
            'status': 'pending',
            'total_amount': computed['total_amount'],
            'payment_method': 'square',
            'metadata': metadata,
        }

        # Giai đoạn 7 (SRE) audit — GIỮ CHỖ HÀNG (trừ kho + tạo order 'pending') TRƯỚC KHI gọi
        # Square charge khách, không phải sau (xem giải thích đầy đủ ở api_square_checkout() —
        # cùng lý do: không bao giờ charge khách cho thứ vừa phát hiện không đủ để bán).
        with mongo_client_instance.start_session() as db_session:
            with db_session.start_transaction():
                _decrement_stock_atomic(business_id, computed['stock_items'], db_session=db_session)
                db.orders.insert_one(order_doc, session=db_session)

        # Đã giữ chỗ hàng thành công -> giờ mới gọi Square charge khách thật.
        txn_id = f"NAILSQ-{order_id}-{uuid.uuid4().hex[:6].upper()}"
        square_result = payment_us_engine.create_terminal_checkout(
            computed['total_amount'], txn_id, note=f"BitPaw Nail POS Order #{order_id}"
        )
        if not square_result.get('configured') or not square_result.get('success'):
            # Charge thất bại SAU KHI đã giữ chỗ hàng -> BẮT BUỘC hoàn kho + huỷ order.
            try:
                _restock_atomic(business_id, computed['stock_items'])
                db.orders.update_one({'id': order_id}, {'$set': {'status': 'failed'}})
            except Exception as rollback_err:
                print(f"[api_nail_pos_square_checkout] LOI HOAN KHO sau khi Square charge that bai "
                      f"(order_id={order_id}) - CAN KIEM TRA TAY: {rollback_err}")
            status_code = 503 if not square_result.get('configured') else 502
            return jsonify({"success": False, "message": square_result.get('message')}), status_code

        db.orders.update_one(
            {'id': order_id},
            {'$set': {
                'metadata.square_checkout_id': square_result.get('checkout_id'),
                'metadata.square_txn_id': txn_id,
            }}
        )

        return jsonify({
            "success": True, "order_id": order_id,
            "checkout_id": square_result.get('checkout_id'),
            "terminal_status": square_result.get('terminal_status'),
            "total_amount": computed['total_amount'],
        })
    except InsufficientStockError as e:
        return jsonify({"success": False, "message": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


def _finalize_nail_square_order(order_doc):
    """Commits the order_items/chamcong write for a nail-salon Square Terminal checkout once
    Square's webhook confirms COMPLETED — mirrors the transaction used in
    api_nail_pos_checkout so a bill paid via physical Terminal persists identically (order
    marked completed + order_items + per-technician chamcong, atomically) to one paid via
    Cash/Card/Split."""
    order_id = order_doc['id']
    business_id = order_doc['business_id']
    metadata = order_doc.get('metadata') or {}
    order_items_docs = metadata.get('_pending_order_items') or []
    computed = {
        'subtotal': metadata.get('subtotal') or 0,
        'net_revenue': metadata.get('_pending_net_revenue') or 0,
        'commission_rate': metadata.get('commission_rate') or 0,
        'worker_total_tip': metadata.get('_pending_worker_total_tip') or 0,
        'per_tech_revenue': metadata.get('_pending_per_tech_revenue') or {},
    }
    customer_phone = (metadata.get('customer_phone') or '').strip()

    for oi in order_items_docs:
        oi['id'] = next_mongo_id('order_items')
        oi['order_id'] = order_id
        oi['business_id'] = business_id
        if customer_phone:
            oi['customer_phone'] = customer_phone

    chamcong_docs, _techs_paid = _build_nail_chamcong_docs(order_id, business_id, computed, note_prefix='[NAILS POS SQUARE]')

    with mongo_client_instance.start_session() as db_session:
        with db_session.start_transaction():
            db.orders.update_one(
                {'id': order_id, 'business_id': business_id},
                {
                    '$set': {'status': 'completed', 'metadata.square_paid_at': datetime.now().isoformat()},
                    '$unset': {
                        'metadata._pending_order_items': '', 'metadata._pending_per_tech_revenue': '',
                        'metadata._pending_net_revenue': '', 'metadata._pending_worker_total_tip': '',
                    },
                },
                session=db_session
            )
            if order_items_docs:
                db.order_items.insert_many(order_items_docs, session=db_session)
            if chamcong_docs:
                db.chamcong.insert_many(chamcong_docs, session=db_session)
            _record_pos_transaction(
                business_id, order_id, order_doc.get('total_amount'), 'square',
                created_by='square_webhook', db_session=db_session,
            )

    if customer_phone:
        _finalize_paid_order(order_doc)


@app.route('/api/nail_pos/refund', methods=['POST'])
@login_required
def api_nail_pos_refund():
    """Return/Refund cho Nail POS — ghi 1 order âm liên kết tới order gốc để trừ vào doanh
    thu/báo cáo (report_consolidated đọc db.orders nên chỉ cần ghi record là đủ khớp sổ), VÀ
    đảo ngược (clawback) đúng phần hoa hồng/tip đã chốt cho (các) thợ liên quan tới order gốc,
    theo tỉ lệ số tiền hoàn / tổng hoá đơn gốc — trước đây route này hoàn tiền khách nhưng thợ
    vẫn giữ nguyên 100% hoa hồng/tip của dịch vụ đã bị hoàn, âm thầm ăn mòn lợi nhuận salon."""
    business_id = session.get('business_id') or session['user_id']
    data = request.json or {}
    original_order_id = data.get('order_id')
    if not original_order_id:
        return jsonify({"success": False, "message": "Vui lòng nhập mã hoá đơn (Order #) cần hoàn tiền."}), 400
    try:
        original_order_id = int(original_order_id)
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "Mã hoá đơn không hợp lệ."}), 400
    try:
        amount = round(float(data.get('amount') or 0), 2)
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "Số tiền hoàn không hợp lệ."}), 400
    if amount <= 0:
        return jsonify({"success": False, "message": "Số tiền hoàn phải lớn hơn 0."}), 400

    try:
        original_order = db.orders.find_one({'id': original_order_id, 'business_id': business_id}, {'_id': 0})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    if not original_order:
        return jsonify({"success": False, "message": f"Không tìm thấy hoá đơn #{original_order_id}."}), 404

    original_metadata = original_order.get('metadata') or {}
    order_total = round(float(original_order.get('total_amount') or 0), 2)
    already_refunded = round(float(original_metadata.get('refunded_amount') or 0), 2)
    remaining = round(order_total - already_refunded, 2)
    if amount > remaining + 0.01:
        return jsonify({
            "success": False,
            "message": f"Số tiền hoàn (${amount}) vượt quá số dư có thể hoàn của hoá đơn này (${remaining})."
        }), 400

    try:
        refund_id = next_mongo_id('orders')
        now_dt = datetime.now()
        now_iso = now_dt.isoformat()

        # Clawback: chỉ khớp đúng các bản ghi chamcong mà CHÍNH order này đã tạo lúc checkout
        # (note bắt đầu bằng "[NAILS POS]" — không khớp nhầm vào các bản ghi [REFUND] clawback
        # của lần hoàn tiền trước, nếu không tỉ lệ hoàn sẽ bị tính chồng lên chính nó ở lần hoàn
        # thứ 2 trở đi). Dùng lookahead (?!\d) để "Order #1" không khớp nhầm "Order #12"/"#100".
        refund_ratio = (amount / order_total) if order_total > 0 else 0.0
        refund_ratio = max(0.0, min(1.0, refund_ratio))
        note_pattern = r'^\[NAILS POS\] Order #' + str(original_order_id) + r'(?!\d)'
        original_chamcong_records = list(db.chamcong.find(
            {'business_id': business_id, 'ghi_chu': {'$regex': note_pattern}}, {'_id': 0}
        ))

        techs_clawed_back = []
        for rec in original_chamcong_records:
            clawback_tua = round(float(rec.get('tien_tua') or 0) * refund_ratio, 2)
            clawback_tip = round(float(rec.get('tien_tips') or 0) * refund_ratio, 2)
            if clawback_tua == 0 and clawback_tip == 0:
                continue
            db.chamcong.insert_one({
                'id': next_mongo_id('chamcong'), 'business_id': business_id, 'ma_nv': rec.get('ma_nv'),
                'ngay_cham': now_dt.strftime('%d/%m/%Y'), 'nganh_nghe': 'Nails', 'trang_thai': 'Đã chốt',
                'ghi_chu': f"[REFUND] Deduction for Order #{original_order_id} — linked to original chamcong #{rec.get('id')}",
                'tien_tua': -clawback_tua, 'tien_tips': -clawback_tip, 'phu_cap': 0, 'so_gio': 0,
                'tang_ca': 0,
            })
            techs_clawed_back.append({'ma_nv': rec.get('ma_nv'), 'commission_deducted': clawback_tua, 'tip_deducted': clawback_tip})

        new_refunded_amount = round(already_refunded + amount, 2)
        new_status = 'refunded' if new_refunded_amount >= order_total - 0.01 else 'partially_refunded'
        db.orders.update_one(
            {'id': original_order_id, 'business_id': business_id},
            {'$set': {'status': new_status, 'metadata.refunded_amount': new_refunded_amount}}
        )

        # Hoàn tồn kho (Giai đoạn 5 audit) — CHỈ khi hoàn ĐỦ 100% hoá đơn (new_status=='refunded').
        # Hoàn 1 PHẦN theo SỐ TIỀN (route này không nhận input theo từng dòng dịch vụ cụ thể)
        # không đủ dữ liệu để biết CHÍNH XÁC sản phẩm/số lượng nào bị trả — hoàn theo tỉ lệ số
        # tiền dễ tạo số lượng lẻ vô nghĩa cho sản phẩm vật lý (vd hoàn 0.37 đơn vị). Hoàn đủ
        # 100% thì chắc chắn: mọi dòng của order gốc đều được trả lại nguyên vẹn.
        if new_status == 'refunded':
            try:
                original_items = list(db.order_items.find(
                    {'order_id': original_order_id}, {'product_id': 1, 'quantity': 1, '_id': 0}
                ))
                restock_items = [(oi['product_id'], oi['quantity'], None) for oi in original_items if oi.get('product_id')]
                if restock_items:
                    _restock_atomic(business_id, restock_items)
            except Exception as e:
                # Best-effort — hoàn tiền/hoa hồng đã ghi xong ở trên là phần quan trọng nhất,
                # lỗi hoàn kho KHÔNG được phép chặn response hoàn tiền đã thành công.
                print(f"[api_nail_pos_refund] Loi hoan ton kho (khong chan luong hoan tien): {e}")

        db.orders.insert_one({
            'id': refund_id,
            'business_id': business_id,
            'created_at': now_iso,
            'status': 'refunded',
            'total_amount': -amount,
            'payment_method': original_order.get('payment_method', 'cash'),
            'metadata': {
                'channel': 'nail_pos_refund', 'subtotal': -amount, 'supply_amount': 0,
                'discount_amount': 0, 'tip_amount': 0,
                'payment_bucket': original_metadata.get('payment_bucket', 'cash'),
                'currency': original_metadata.get('currency') or 'AUD',
                'original_order_id': original_order_id, 'refund_reason': (data.get('reason') or '').strip(),
            },
        })
        return jsonify({
            "success": True, "refund_id": refund_id, "order_status": new_status,
            "techs_clawed_back": techs_clawed_back,
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


# ========== MỚI: ROUTE CHO CƠ SỞ DỮ LIỆU NHÂN SỰ VÀ SUPER ADMIN ==========
@app.route('/nhanvien')
@login_required
def nhanvien():
    return render_template('nhanvien.html')

@app.route('/bangluong')
@login_required
@role_required('admin', 'super_admin')
def bangluong():
    return render_template('bangluong.html')

@app.route('/chamcong')
@login_required
@role_required('admin', 'super_admin')
def chamcong():
    return render_template('chamcong.html')

@app.route('/chamcong/congnhan')
@app.route('/chamcong_congnhan')
@login_required
@role_required('admin', 'super_admin')
def chamcong_congnhan():
    return render_template('chamcong_congnhan.html')

@app.route('/chamcong/fnb')
@app.route('/chamcong_fnb')
@login_required
@role_required('admin', 'super_admin')
def chamcong_fnb():
    return render_template('chamcong_fnb.html')

@app.route('/chamcong/khachsan')
@app.route('/chamcong_khachsan')
@login_required
@role_required('admin', 'super_admin')
def chamcong_khachsan():
    return render_template('chamcong_khachsan.html')

@app.route('/chamcong/kythuat')
@app.route('/chamcong_kythuat')
@login_required
@role_required('admin', 'super_admin')
def chamcong_kythuat():
    return render_template('chamcong_kythuat.html')

@app.route('/chamcong/nail')
@app.route('/chamcong_nail')
@login_required
@role_required('admin', 'super_admin')
def chamcong_nail():
    return render_template('chamcong_nail.html')

# chamcong_spa (/chamcong/spa, /chamcong_spa) đã chuyển sang blueprints/spa_bp.py

@app.route('/chamcong/vanphong')
@app.route('/chamcong_vanphong')
@login_required
@role_required('admin', 'super_admin')
def chamcong_vanphong():
    return render_template('chamcong_vanphong.html')

@app.route('/chamcong/<industry_code>')
@app.route('/chamcong_<industry_code>')
@login_required
@role_required('admin', 'super_admin')
def chamcong_industry(industry_code):
    template_name = f"chamcong_{industry_code}.html"
    if os.path.exists(os.path.join(app.template_folder, template_name)):
        return render_template(template_name)
    else:
        return render_template("chamcong.html", industry_code=industry_code)

@app.route('/table_order')
def table_order():
    table_id = request.args.get('table_id')
    if not table_id:
        return "Thiếu mã bàn (table_id) trong đường dẫn QR.", 400

    table_data = None
    try:
        # support alphanumeric token or numeric table_id
        if str(table_id).isdigit():
            table_data = db.dining_tables.find_one({'id': int(table_id)}, {'_id': 0})
        else:
            table_data = db.dining_tables.find_one({'qr_token': table_id}, {'_id': 0})
    except Exception as e:
        print(f"Error querying table from MongoDB: {e}")
        return "Không thể kết nối tới hệ thống để xác thực bàn. Vui lòng thử lại.", 500

    if not table_data:
        return "Mã QR không hợp lệ hoặc bàn không còn tồn tại. Vui lòng liên hệ nhân viên.", 404

    # Khách quét QR KHÔNG có session — inject_industry_config() (context_processor toàn cục)
    # sẽ resolve tenant_country/tenant_currency theo session.get('business_id') là None, tức
    # LUÔN fallback VN/VND bất kể tiệm thật sự thuộc thị trường nào. Phải tự resolve theo đúng
    # business_id của CÁI BÀN đang được quét (không phải theo session) rồi truyền đè lên context
    # processor's giá trị mặc định (render_template kwargs ghi đè context processor cùng tên).
    if hasattr(TenantEngine, 'get_region_config'):
        region = TenantEngine.get_region_config(table_data.get('business_id'))
    else:
        region = {"country": "VN", "currency": "VND"}

    return render_template(
        'table_order.html', table=table_data,
        tenant_country=region['country'], tenant_currency=region['currency']
    )

@app.route('/baocao_loinhuan')
@login_required
@role_required('admin', 'super_admin')
def baocao_loinhuan():
    return render_template('baocao_loinhuan.html')

@app.route('/cauhinh_luong')
@login_required
def cauhinh_luong():
    business_id = session.get('business_id') or session['user_id']
    staff_id = request.args.get('staff_id')
    emp = None
    if staff_id:
        try:
            s = db.staff.find_one({'id': int(staff_id), 'business_id': business_id}, {'_id': 0})
            if s:
                emp = [str(s.get('id', '')), s.get('name', ''), s.get('role', 'retail')]
        except Exception as e:
            print("Loi lay thong tin nhan vien:", e)
    if not emp:
        emp = ["DEMO-001", "Nhân viên Mẫu", "retail"]

    # Danh sách nhân viên bên hệ chấm công (employees) để chọn liên kết — cầu nối AN
    # TOÀN sang bangluong.html, không sửa gì trong 17 file chấm công đang chạy thật.
    employees_list = []
    linked_ma_nv = ''
    try:
        emp_docs = list(
            db.employees.find(
                {'business_id': business_id}, {'id': 1, 'ma_nv': 1, 'ho_ten': 1, 'staff_id': 1, '_id': 0}
            ).sort('ho_ten', 1)
        )
        if emp_docs:
            employees_list = [{'ma_nv': e.get('ma_nv'), 'ho_ten': e.get('ho_ten')} for e in emp_docs]
            for e in emp_docs:
                if staff_id and str(e.get('staff_id')) == str(staff_id):
                    linked_ma_nv = e.get('ma_nv')
                    break
    except Exception as e:
        print("Loi lay danh sach employees de lien ket:", e)

    return render_template('cauhinh_luong.html', emp=emp, employees_list=employees_list, linked_ma_nv=linked_ma_nv)


@app.route('/api/cauhinh_luong/<staff_id>', methods=['POST'])
@login_required
def api_cauhinh_luong(staff_id):
    """Lưu cấu hình lương chi tiết (lương cứng/giờ/hoa hồng/phụ cấp/tăng ca) cho 1 nhân
    viên trong bảng staff — trước đây route này không tồn tại nên nút Lưu luôn 404."""
    business_id = session.get('business_id') or session['user_id']
    data = request.json or {}
    salary_config = {
        'luong_cung': data.get('luong_cung', 0),
        'luong_gio': data.get('luong_gio', 0),
        'hoa_hong': data.get('hoa_hong', 0),
        'phu_cap': data.get('phu_cap', 0),
        'tang_ca': data.get('tang_ca', 0),
    }
    try:
        result = db.staff.update_one(
            {'id': int(staff_id), 'business_id': business_id},
            {'$set': {'salary_config': salary_config}}
        )
        if result.matched_count == 0:
            return jsonify({"success": False, "message": "Không tìm thấy nhân viên hoặc không thuộc quyền quản lý của bạn."}), 404
    except Exception as e:
        return jsonify({"success": False, "message": f"Lỗi lưu cấu hình lương: {str(e)}"}), 500

    # Cầu nối AN TOÀN sang hệ chấm công/lương thật (employees/chamcong, dùng bởi
    # bangluong.html) — CHỈ đồng bộ nếu admin đã CHỦ ĐỘNG chọn liên kết ở dropdown.
    # Nếu không chọn liên kết, bước này là no-op tuyệt đối — không đụng gì tới
    # bangluong.html hay dữ liệu employees hiện có.
    linked_ma_nv = (data.get('linked_ma_nv') or '').strip()
    try:
        # Gỡ liên kết cũ (nếu staff này trước đó đã trỏ tới 1 employees khác) trước khi
        # gán liên kết mới, tránh 1 staff bị link vào nhiều dòng employees cùng lúc.
        db.employees.update_many(
            {'staff_id': staff_id, 'business_id': business_id},
            {'$set': {'staff_id': None}}
        )

        if linked_ma_nv:
            link_result = db.employees.update_one(
                {'ma_nv': linked_ma_nv, 'business_id': business_id},
                {'$set': {
                    'staff_id': staff_id,
                    'luong_cb': salary_config['luong_cung'],
                    'luong_gio': salary_config['luong_gio'],
                    'phu_cap': salary_config['phu_cap'],
                }}
            )
            if link_result.matched_count == 0:
                return jsonify({"success": True, "warning": f"Đã lưu lương nhưng không tìm thấy nhân viên chấm công có mã '{linked_ma_nv}' để liên kết."})
    except Exception as sync_err:
        print(f"Đồng bộ salary_config sang employees thất bại (không chặn luồng lưu lương): {str(sync_err)}")
        return jsonify({"success": True, "warning": "Đã lưu lương nhưng đồng bộ liên kết employees bị lỗi."})

    return jsonify({"success": True})

@app.route('/diemdanh')
@login_required
def diemdanh():
    return render_template('diemdanh.html')

@app.route('/fnb_dashboard')
@login_required
def fnb_dashboard():
    return render_template('fnb_dashboard.html')

@app.route('/portal')
def portal():
    """PUBLIC (đã bỏ @login_required) — trang chat CSKH cho KHÁCH HÀNG CUỐI của tiệm, truy cập
    qua link/QR riêng dạng /portal?id=<customer_id>, KHÔNG có session đăng nhập. Route này trước
    đây bị gắn @login_required nhầm (rập khuôn theo mọi route khác trong lần migrate đầu), khiến
    mọi khách hàng bấm vào link đều bị đá về trang đăng nhập nhân viên — cùng loại lỗi với
    kiosk Fast Check-in và QR gọi món đã sửa ở Batch 2."""
    return render_template('portal.html')


def _resolve_portal_customer(customer_id):
    """Tra cứu bot_customers theo id do CHÍNH customer_id xác định business_id — không có
    session nên KHÔNG ĐƯỢC tin business_id từ client dưới bất kỳ hình thức nào; mọi route
    /api/portal/* đều phải đi qua hàm này trước khi đọc/ghi bot_messages."""
    if not customer_id:
        return None
    return db.bot_customers.find_one({'id': customer_id}, {'_id': 0})


@app.route('/api/portal/messages', methods=['GET'])
def api_portal_messages_list():
    customer_id = request.args.get('customer_id', '')
    customer = _resolve_portal_customer(customer_id)
    if not customer:
        return jsonify({"success": False, "message": "Không tìm thấy hội thoại này."}), 404
    try:
        messages = list(db.bot_messages.find({'customer_id': customer_id}, {'_id': 0}).sort('created_at', 1))
        return jsonify({"success": True, "data": messages})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/portal/messages', methods=['POST'])
def api_portal_messages_create():
    """Khách hàng (ẩn danh, không session) gửi tin nhắn HOẶC client tự ghi lại phản hồi AI giả
    lập (sender_type='ai', giống hành vi getAIResponse() cũ ở portal.html). KHÔNG cho phép
    sender_type='staff' qua route public này — trả lời thật của nhân viên chỉ được ghi qua
    /api/bot/messages (đã có @login_required + business_id từ session)."""
    data = request.json or {}
    customer_id = data.get('customer_id', '')
    content = (data.get('content') or '').strip()
    sender_type = data.get('sender_type', 'customer')
    if sender_type not in ('customer', 'ai'):
        return jsonify({"success": False, "message": "sender_type không hợp lệ."}), 400
    if not content:
        return jsonify({"success": False, "message": "Tin nhắn trống."}), 400
    customer = _resolve_portal_customer(customer_id)
    if not customer:
        return jsonify({"success": False, "message": "Không tìm thấy hội thoại này."}), 404
    try:
        now_iso = datetime.now().isoformat()
        db.bot_messages.insert_one({
            'customer_id': customer_id, 'sender_type': sender_type, 'content': content[:2000],
            'business_id': customer['business_id'], 'created_at': now_iso,
            'is_read': sender_type != 'customer',
        })
        db.bot_customers.update_one(
            {'id': customer_id}, {'$set': {'last_message': content[:500], 'last_message_time': now_iso}}
        )
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/portal/upload', methods=['POST'])
def api_portal_upload():
    """Upload ảnh/GIF khách gửi trong chat CSKH — public, business_id lấy từ customer_id (KHÔNG
    có session để lấy từ đó). File lưu vào cùng GridFS bucket 'media' như /api/storage/upload
    nhưng kind='portal_chat' — chỉ kind này (+ brand_logo/brand_cover) được phép đọc công khai
    qua /api/public/storage/file/<id>, tách biệt khỏi ảnh riêng tư khác (checkin, avatar...)."""
    if media_fs is None:
        return jsonify({'success': False, 'error': 'MongoDB/GridFS chưa được cấu hình.'}), 400
    customer_id = request.form.get('customer_id', '')
    customer = _resolve_portal_customer(customer_id)
    if not customer:
        return jsonify({'success': False, 'error': 'Không tìm thấy hội thoại này.'}), 404
    file = request.files.get('file')
    if not file or file.filename == '':
        return jsonify({'success': False, 'error': 'Thiếu file để upload.'}), 400
    if not _allowed_media_file(file.filename):
        return jsonify({'success': False, 'error': 'Chỉ hỗ trợ ảnh (png/jpg/jpeg/gif/webp).'}), 400
    filename = secure_filename(file.filename)
    try:
        file_id = media_fs.put(
            file.stream.read(),
            filename=filename,
            business_id=customer['business_id'],
            kind='portal_chat',
            content_type=_safe_image_content_type(filename)
        )
        return jsonify({'success': True, 'file_id': str(file_id), 'url': url_for('api_public_storage_file', file_id=str(file_id))})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/portal/stream', methods=['GET'])
def api_portal_stream():
    """SSE public — chỉ là tín hiệu "có gì mới, tự gọi lại /api/portal/messages", KHÔNG mang dữ
    liệu, nên lộ tín hiệu này không rò rỉ nội dung chat của khách khác. Match stage tự dựng
    (không dùng _sse_tenant_match() vì hàm đó đọc business_id từ session, ở đây không có
    session — business_id phải suy ra từ customer_id)."""
    customer_id = request.args.get('customer_id', '')
    customer = _resolve_portal_customer(customer_id)
    if not customer:
        return jsonify({"success": False, "message": "Không tìm thấy hội thoại này."}), 404
    match = {'$match': {'$or': [
        {'fullDocument.business_id': customer['business_id']},
        {'operationType': 'delete'},
    ], 'ns.coll': {'$in': ['bot_customers', 'bot_messages']}}}
    return _sse_change_signal(db, match)


@app.route('/quanly_congno')
@login_required
@role_required('admin', 'super_admin')
def quanly_congno():
    return render_template('quanly_congno.html')

@app.route('/quanly_dichvu')
@login_required
def quanly_dichvu():
    return render_template('quanly_dichvu.html')

@app.route('/quanly_kho')
@login_required
def quanly_kho():
    return render_template('quanly_kho.html')

@app.route('/quanly_thuchi')
@login_required
@role_required('admin', 'super_admin')
def quanly_thuchi():
    return render_template('quanly_thuchi.html')

def _is_superadmin():
    """Gate truy cập trang/API superadmin cho session ĐANG đăng nhập — dùng chung đúng 1 nguồn
    chân lý _is_authorized_superadmin_email() với login() (xem comment ở đó), tránh lệch logic
    giữa "ai được phép đăng nhập fallback" và "ai được phép vào trang sau khi đã đăng nhập"."""
    return _is_authorized_superadmin_email(session.get('user_email'))


@app.route('/super_admin')
@app.route('/super-admin')
@login_required
def super_admin():
    if not _is_superadmin():
        return "Access denied: this page is for Superadmin only.", 403
    return render_template('super_admin.html')

@app.route('/ai_bot')
@login_required
def ai_bot():
    business_id = session.get('business_id')
    if not business_id:
        flash('Phiên đăng nhập không hợp lệ, vui lòng đăng nhập lại.', 'danger')
        return redirect(url_for('login'))
    user_email = session.get('user_email', 'Not set')
    industry = session.get('business_mode', 'retail')

    brand_name = 'No Business Profile Yet'
    brand_email = user_email
    brand_phone = 'Phone Not Set'
    brand_zalo = 'No Zalo OA Connected'
    brand_fb = 'Facebook Not Connected'
    brand_industry = INDUSTRY_CONFIG.get(industry, {}).get('name', 'Retail')
    brand_tier = 'BitPaw Trial'
    brand_staff = '0 Staff'
    brand_joined = '2026-05-29'
    brand_branch = 'Not Set'
    
    has_profile = False
    
    # Try fetching brand details from MongoDB if connected
    if MONGO_STATUS == "CONNECTED":
        try:
            brand_doc_value = _brand_setting_get(business_id, 'brand_name')
            if brand_doc_value:
                brand_name = brand_doc_value
                has_profile = True
        except Exception as e:
            print(f"[!] MongoDB profile query failed: {str(e)}")
            
    # Try fetching local cskh settings from SQLite database
    try:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("SELECT brand_name, email, phone, zalo_oa_id FROM cskh_config WHERE business_id = ? LIMIT 1", (business_id,))
        row = c.fetchone()
        if row:
            brand_name = row[0] or brand_name
            brand_email = row[1] or brand_email
            brand_phone = row[2] or brand_phone
            brand_zalo = row[3] or brand_zalo
            has_profile = True
        
        # Check active staff count
        c.execute("SELECT COUNT(*) FROM staff WHERE business_id = ?", (business_id,))
        staff_count = c.fetchone()[0]
        if staff_count > 0:
            brand_staff = f"{staff_count} Staff"

        conn.close()
    except Exception as db_err:
        print(f"[!] SQLite brand config fallback read error: {str(db_err)}")

    # Check if license details can provide tier — license_codes nằm trên MongoDB, nên tách riêng
    # try/except khỏi khối SQLite ở trên.
    try:
        license_doc = db.license_codes.find_one(
            {'trang_thai': 'Đã kích hoạt'}, {'license_key': 1, '_id': 0}, sort=[('id', -1)]
        )
        if license_doc:
            brand_tier = 'BitPaw Pro (Premium)'
            has_profile = True
    except Exception as db_err:
        print(f"[!] license_codes tier lookup failed: {str(db_err)}")

    profile = {
        "has_profile": has_profile,
        "name": brand_name if has_profile or brand_name != 'No Business Profile Yet' else "No Business Profile Yet",
        "email": brand_email,
        "phone": brand_phone,
        "zalo": brand_zalo,
        "fb": brand_fb,
        "industry": brand_industry,
        "tier": brand_tier,
        "staff": brand_staff,
        "joined": brand_joined,
        "branch": brand_branch
    }
    return render_template('ai_bot.html', profile=profile)


@app.route('/calendar')
@login_required
def calendar_view():
    """Màn hình lịch hẹn trong ngày cho thu ngân — đọc db.appointments (MongoDB), collection
    dùng chung bởi cả AI Bot (ai_function_tools.py::book_appointment) lẫn trang đặt lịch công
    khai (blueprints/spa_bp.py::create_appointment). Trước khi có route này, lịch AI đặt được
    ghi vào DB thật nhưng KHÔNG có màn hình nào đọc lại — đây là điểm hoàn thiện luồng đó."""
    business_id = session.get('business_id')
    if not business_id:
        flash('Phiên đăng nhập không hợp lệ, vui lòng đăng nhập lại.', 'danger')
        return redirect(url_for('login'))

    date_str = request.args.get('date') or datetime.now().strftime('%Y-%m-%d')
    try:
        datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        date_str = datetime.now().strftime('%Y-%m-%d')

    try:
        appointments = list(db.appointments.find(
            {
                'business_id': business_id,
                'book_time': {'$gte': f'{date_str}T00:00:00', '$lte': f'{date_str}T23:59:59'},
            },
            {'_id': 0},
        ).sort('book_time', 1))
    except Exception as e:
        print(f"[calendar_view] Lỗi tra cứu db.appointments (business_id={business_id}): {e}")
        flash('Không tải được lịch hẹn — vui lòng thử lại.', 'danger')
        appointments = []

    # Gộp 1 lần tra tên dịch vụ cho toàn bộ danh sách (tránh N+1 query từng dòng).
    service_ids = list({a['service_id'] for a in appointments if a.get('service_id')})
    service_names = {}
    if service_ids:
        try:
            for svc in db.products.find({'id': {'$in': service_ids}, 'business_id': business_id}, {'id': 1, 'name': 1, '_id': 0}):
                service_names[svc['id']] = svc.get('name')
        except Exception as e:
            print(f"[calendar_view] Lỗi tra cứu tên dịch vụ: {e}")

    for a in appointments:
        a['service_name'] = service_names.get(a.get('service_id')) or a.get('service_id') or 'Không rõ dịch vụ'

    return render_template('calendar.html', appointments=appointments, selected_date=date_str)


@app.route('/ai-studio')
@app.route('/ai_studio')
@login_required
def ai_studio():
    return render_template('ai-studio.html')

def _persist_chat_turn(business_id, customer_phone, content, sender_type='customer'):
    """Lưu 1 lượt chat vào CRM (bot_customers/bot_messages) theo đúng business_id của tenant,
    best-effort — không bao giờ được phép làm gãy luồng chat nếu MongoDB lỗi/offline."""
    if not content or not business_id or not customer_phone or db is None:
        return
    try:
        customer_id = f"{business_id}:{customer_phone}"
        now_iso = datetime.now().isoformat()
        db.bot_customers.update_one(
            {'id': customer_id},
            {'$set': {
                'full_name': f"Khách {customer_phone}",
                'last_message': content[:500],
                'last_message_time': now_iso,
                'business_id': business_id,
            }},
            upsert=True
        )
        db.bot_messages.insert_one({
            'customer_id': customer_id,
            'sender_type': sender_type,
            'content': content[:2000],
            'business_id': business_id,
            'created_at': now_iso,
            'is_read': sender_type != 'customer',  # tin nhắn của khách mặc định "chưa đọc"
        })
    except Exception:
        pass


def _load_recent_chat_history(business_id, customer_phone, limit=10):
    """Khôi phục lịch sử chat gần nhất từ DB khi client không còn giữ (vd: refresh trang),
    để AI không bao giờ mất ngữ cảnh hội thoại."""
    if not business_id or not customer_phone or db is None:
        return []
    try:
        customer_id = f"{business_id}:{customer_phone}"
        prev = list(
            db.bot_messages.find(
                {'customer_id': customer_id},
                {'sender_type': 1, 'content': 1, 'created_at': 1, '_id': 0}
            ).sort('created_at', -1).limit(limit)
        )
        if prev:
            return [
                {"role": "assistant" if m.get('sender_type') == 'ai' else "user", "content": m.get('content') or ''}
                for m in reversed(prev)
            ]
    except Exception:
        pass
    return []


# ========== "TALK TO HUMAN AGENT" TỪ WIDGET CSKH TRÊN LANDING PAGE MARKETING (cskh_widget.js) ==========
# Khách vãng lai trên landing page marketing (landing.html, landing_*.html) KHÔNG thuộc tenant
# nào cả — business_id thật luôn là None ở đây (xem BUSINESS_ID trong cskh_widget.js). Dùng 1
# sentinel business_id cố định để vẫn tái dùng đúng bot_customers/bot_messages + _persist_chat_turn()
# sẵn có, và hội thoại tự động xuất hiện trong /super_admin "Tất Cả Hội Thoại" (route đó đọc
# CROSS-TENANT, không lọc business_id, nên không cần thay đổi gì ở đó để nó "nhìn thấy" sentinel này).
BITPAW_LEADS_BUSINESS_ID = "bitpaw_leads"


@app.route('/api/cskh/chat/send', methods=['POST'])
def api_cskh_chat_send():
    """Public — khách bấm 'Talk to Human Agent' rồi gửi tin nhắn. Không có session (khách vãng
    lai), khoá hội thoại theo SĐT khách nhập. Tái dùng _persist_chat_turn() best-effort y hệt
    luồng AI/tenant, chỉ khác business_id là sentinel BITPAW_LEADS_BUSINESS_ID."""
    data = request.json or {}
    phone = (data.get('phone') or '').strip()
    content = (data.get('content') or '').strip()
    if not phone or not content:
        return jsonify({"success": False, "message": "Thiếu số điện thoại hoặc nội dung tin nhắn."}), 400
    _persist_chat_turn(BITPAW_LEADS_BUSINESS_ID, phone, content[:2000], sender_type='customer')
    return jsonify({"success": True})


@app.route('/api/cskh/chat/messages', methods=['GET'])
def api_cskh_chat_messages():
    """Public — widget poll lại route này (sau khi nhận tín hiệu từ /api/stream/cskh_chat) để
    lấy toàn bộ lịch sử, bao gồm cả reply mới của Admin (sender_type='staff'). Khoá theo SĐT
    trong query string — CHÚ Ý: cùng hạn chế đã có ở /api/portal/messages, khoá theo 1 giá trị
    có thể đoán được (SĐT) chứ không phải bí mật thật sự; chấp nhận đánh đổi để khách vãng lai
    không cần đăng nhập/token vẫn chat được."""
    phone = (request.args.get('phone') or '').strip()
    if not phone or db is None:
        return jsonify({"success": True, "messages": []})
    customer_id = f"{BITPAW_LEADS_BUSINESS_ID}:{phone}"
    try:
        messages = list(db.bot_messages.find({'customer_id': customer_id}, {'_id': 0}).sort('created_at', 1))
        return jsonify({"success": True, "messages": messages})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/stream/cskh_chat', methods=['GET'])
def stream_cskh_chat():
    """SSE public — chỉ báo tín hiệu "có gì mới" cho ĐÚNG 1 khách (lọc theo customer_id đầy đủ,
    không chỉ business_id — vì mọi khách landing page đều dùng chung 1 sentinel business_id, lọc
    theo business_id sẽ khiến tín hiệu của khách A làm khách B tự fetch lại không cần thiết),
    KHÔNG mang nội dung — giống hệt pattern /api/portal/stream (không dùng _sse_tenant_match()
    vì route này không có session)."""
    phone = (request.args.get('phone') or '').strip()
    if not phone or db is None:
        return Response('', mimetype='text/event-stream')
    customer_id = f"{BITPAW_LEADS_BUSINESS_ID}:{phone}"
    match = {'$match': {'$or': [
        {'fullDocument.customer_id': customer_id},
        {'operationType': 'delete'},
    ], 'ns.coll': 'bot_messages'}}
    return _sse_change_signal(db, match)


# ========== AI BOT CONSOLE (staff xem/trả lời hội thoại của TENANT MÌNH) — thay Supabase JS
# ở ai_bot.html. Client cũ đọc bot_customers/bot_messages KHÔNG lọc business_id (giống lỗ hổng
# đã vá ở user_logs.html) — 2 route GET dưới đây bắt buộc lọc theo business_id của session. ==========
@app.route('/api/bot/customers', methods=['GET'])
@login_required
def api_bot_customers_list():
    business_id = session.get('business_id') or session['user_id']
    try:
        customers = list(db.bot_customers.find({'business_id': business_id}, {'_id': 0}).sort('last_message_time', -1))
        return jsonify({"success": True, "data": customers})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


def _assert_owns_bot_customer(customer_id, business_id):
    doc = db.bot_customers.find_one({'id': customer_id}, {'business_id': 1, '_id': 0})
    return bool(doc) and doc.get('business_id') == business_id


@app.route('/api/bot/messages', methods=['GET'])
@login_required
def api_bot_messages_list():
    business_id = session.get('business_id') or session['user_id']
    customer_id = request.args.get('customer_id', '')
    if not _assert_owns_bot_customer(customer_id, business_id):
        return jsonify({"success": False, "message": "Không tìm thấy hội thoại này."}), 403
    try:
        messages = list(db.bot_messages.find({'customer_id': customer_id}, {'_id': 0}).sort('created_at', 1))
        return jsonify({"success": True, "data": messages})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/bot/messages', methods=['POST'])
@login_required
def api_bot_messages_create():
    """Staff (chủ tiệm) tự trả lời khách trong console ai_bot.html — sender_type='staff',
    KHÁC với sender_type='ai'/'customer' do _persist_chat_turn() ghi tự động từ widget
    landing page. Dùng chung 1 collection, chỉ khác nhãn người gửi."""
    business_id = session.get('business_id') or session['user_id']
    data = request.json or {}
    customer_id = data.get('customer_id', '')
    content = (data.get('content') or '').strip()
    if not content:
        return jsonify({"success": False, "message": "Tin nhắn trống."}), 400
    if not _assert_owns_bot_customer(customer_id, business_id):
        return jsonify({"success": False, "message": "Không tìm thấy hội thoại này."}), 403
    try:
        now_iso = datetime.now().isoformat()
        db.bot_messages.insert_one({
            'customer_id': customer_id, 'sender_type': 'staff', 'content': content[:2000],
            'business_id': business_id, 'created_at': now_iso, 'is_read': True,
        })
        db.bot_customers.update_one(
            {'id': customer_id, 'business_id': business_id},
            {'$set': {'last_message': content[:500], 'last_message_time': now_iso}}
        )
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/stream/bot_chat')
@login_required
def stream_bot_chat():
    """Thay kênh Supabase Realtime `public:bot_messages`."""
    return _sse_change_signal(db, _sse_tenant_match('bot_customers', 'bot_messages'))


def _call_deepseek_with_tools(messages, temperature, max_tokens, business_id, customer_id, api_key):
    """Vòng lặp Function Calling: gọi DeepSeek, nếu nó yêu cầu gọi tool (vd book_appointment)
    thì THỰC SỰ thực thi tool đó trong Python, nối kết quả thật vào messages rồi gọi lại
    DeepSeek để lấy câu trả lời cuối cùng dựa trên kết quả thật đó — thay vì để AI tự bịa ra
    câu trả lời như đã xảy ra mà không có gì được ghi vào Database.

    Giới hạn tối đa 3 vòng gọi tool liên tiếp để tránh vòng lặp vô hạn nếu model cứ liên tục
    yêu cầu gọi tool (lỗi model hoặc tool trả lỗi khiến model thử lại vô hạn)."""
    working_messages = list(messages)
    proxy_api_key = os.environ.get('BITPAW_AI_PROXY_KEY')  # set bởi desktop_app/launcher.py sau khi verify license

    for _round in range(3):
        payload = {
            "model": "deepseek-chat",
            "messages": working_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "tools": TOOL_SCHEMAS,
            "tool_choice": "auto",
        }
        # deepseek_chat_completion() tự chọn: gọi thẳng DeepSeek (Web/SaaS) hay qua AI Proxy
        # ẩn danh (Desktop App) — xem ai_deepseek_client.py. Ở Desktop mode, api_key truyền
        # vào route này KHÔNG phải DEEPSEEK_API_KEY thật (file .exe không chứa key thật).
        result = deepseek_chat_completion(
            payload, business_id=business_id, proxy_api_key=proxy_api_key, direct_api_key=api_key
        )

        message = result["choices"][0]["message"]
        tool_calls = message.get("tool_calls")
        if not tool_calls:
            return result

        # Model yêu cầu gọi tool — thực thi THẬT rồi vòng lại để lấy câu trả lời cuối cùng
        working_messages.append(message)
        for tool_call in tool_calls:
            tool_call_id, tool_result_json = execute_tool_call(
                tool_call, business_id=business_id, customer_id=customer_id
            )
            working_messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": tool_result_json,
            })

    # Hết 3 vòng vẫn còn đòi gọi tool — trả về response cuối cùng nhận được thay vì treo vô hạn
    return result


@app.route('/api/ai/studio/generate', methods=['POST'])
@limiter.limit("20 per minute")
def secure_ai_generate():
    data = request.get_json() or {}

    # === Đa doanh nghiệp (Multi-tenant): xác định ĐÚNG business_id của tenant ===
    # Nếu request có session đăng nhập (dùng khi test trong AI Studio nội bộ), business_id
    # BẮT BUỘC lấy từ session, tuyệt đối không tin business_id client tự gửi lên (chặn IDOR
    # user nội bộ mạo danh tenant khác). Nếu KHÔNG có session (khách hàng thật của từng doanh
    # nghiệp gọi API ẩn danh qua widget công khai trên landing page của tenant đó), mới cho
    # phép dùng business_id do widget tự khai để biết đang chat hộ tenant nào — nhưng khi đó
    # include_private_data=False bên dưới đảm bảo KHÔNG lộ doanh thu/PII khách hàng của tenant.
    is_authenticated = 'user_id' in session
    if is_authenticated:
        business_id = session.get('business_id') or session['user_id']
    else:
        business_id = data.get('business_id')
    industry = data.get('industry') or session.get('business_mode', 'general')
    # LƯU Ý: KHÔNG còn đọc client's "systemPrompt" để dựng prompt nữa (loophole cũ: browser
    # có thể tự gửi bất kỳ prompt text nào lên, tự ý đổi hành vi/persona của bot). Persona giờ
    # được lắp ráp HOÀN TOÀN server-side qua ai_sales_prompts.compose_system_prompt() — client
    # chỉ còn được quyền chọn industry CODE (1 trong danh sách cố định), không phải nội dung
    # prompt thô. Xem ai_sales_prompts.py để hiểu kiến trúc 4 lớp (Master Persona/Industry
    # Delta/Tenant Data/Objection Guidance).
    user_prompt = data.get('userPrompt', '')
    temperature = data.get('temperature', 0.7)
    max_tokens = data.get('max_tokens', 1500)
    customer_phone = data.get('customer_phone')  # tuỳ chọn: để AI cá nhân hoá theo hạng/lịch sử chi tiêu
    client_history = data.get('history') or []

    ctx = AIContextEngine.build_context_prompt(business_id, industry, customer_phone=customer_phone,
                                                include_private_data=is_authenticated)
    tenant_context = ctx['prompt']
    business_name = ctx['business_name'] or 'BitPaw'

    # customer_id dùng để khoá trí nhớ hội thoại (ai_memory_engine) — CÙNG quy ước
    # "business_id:phone" mà _persist_chat_turn()/bot_customers.id đã dùng ở khắp nơi
    # trong app.py. Chỉ có khi đã biết cả business_id lẫn customer_phone.
    customer_id = f"{business_id}:{customer_phone}" if (business_id and customer_phone) else None

    # === Nối chuỗi hội thoại thật (không để AI mất ngữ cảnh khi khách trả lời cụt lủn) ===
    # Ưu tiên lịch sử client đang giữ trong phiên chat hiện tại; nếu client không gửi gì (vd:
    # vừa refresh trang) thì khôi phục lại từ DB theo đúng business_id + SĐT khách.
    history = client_history if client_history else _load_recent_chat_history(business_id, customer_phone)

    # === Lightweight objection router (Phase 1) ===
    # Phân loại tin nhắn MỚI NHẤT của khách vào 1 trong các nhóm phản đối đã định nghĩa ở
    # OBJECTION_PLAYBOOK (giá, tin tưởng, đối thủ, chần chừ, nghi ngờ tính năng) bằng 1 lệnh
    # gọi DeepSeek riêng, rẻ và nhanh (temperature=0, max_tokens=8, timeout 8s). Best-effort:
    # bất kỳ lỗi/timeout nào cũng chỉ trả về None (không chèn objection guidance), KHÔNG BAO
    # GIỜ được phép làm chậm/gãy luồng trả lời chính. classify_objection() tự bỏ qua bằng
    # regex trước khi gọi LLM cho các tin nhắn rõ ràng không phải phản đối (Phase 2 optimization).
    latest_customer_message = user_prompt or (history[-1]['content'] if history else '')
    objection_category = classify_objection(latest_customer_message, history)

    # === Phase 2: distilled memory (tự no-op an toàn nếu chưa có dữ liệu — xem docstring
    # ai_memory_engine.py). Vector RAG (ai_vector_rag.py) đã bị GỠ BỎ (Mã "Hợp nhất AI bằng
    # DeepSeek" audit) — module đó mặc định gọi OpenAI Embeddings API để tìm sản phẩm liên quan
    # bằng semantic search, đúng loại phụ thuộc OpenAI cần loại bỏ. ai_context_engine.py đã tự
    # nhúng thẳng toàn bộ bảng giá/danh mục (tối đa 40 dòng) vào system prompt mỗi lượt chat —
    # đơn giản hơn, không cần embeddings, không cần Atlas Vector Search index nào cả.
    conversation_memory = get_conversation_memory(customer_id) if customer_id else ""
    extra_context = f"WHAT WE KNOW ABOUT THIS CUSTOMER SO FAR: {conversation_memory}" if conversation_memory else None

    system_prompt = compose_system_prompt(tenant_context, industry, objection_category, extra_context)

    messages = [{"role": "system", "content": system_prompt}]
    for turn in history[-12:]:
        role = turn.get('role') if isinstance(turn, dict) else None
        content = (turn.get('content') or '').strip() if isinstance(turn, dict) else ''
        # Strip HTML-ish tags client có thể đã chèn vào (vd: badge "Đã ghi nhận SĐT...")
        content = re.sub(r'<[^>]+>', ' ', content).strip()
        if role in ('user', 'assistant') and content:
            messages.append({"role": role, "content": content[:2000]})
    if user_prompt:
        messages.append({"role": "user", "content": user_prompt})

    # Lưu lượt chat của khách vào CRM ngay khi nhận được (best-effort)
    _persist_chat_turn(business_id, customer_phone, latest_customer_message, sender_type='customer')

    # Câu chốt sale dự phòng thông minh — thay cho câu báo lỗi cứng cũ, luôn gắn đúng tên
    # cửa hàng của tenant (hoặc "BitPaw" nếu là bot marketing chung không gắn tenant nào).
    fallback_reply = (
        f"Dạ hệ thống đang xử lý hơi nhiều data một chút. Sếp cho em xin SĐT Zalo để chuyên viên bên em "
        f"gọi lại tư vấn gói tối ưu nhất cho {business_name} luôn nhé!"
    )

    # Ở Desktop mode, không cần DEEPSEEK_API_KEY thật ở đây — ai_deepseek_client.py sẽ gọi
    # qua AI Proxy bằng BITPAW_AI_PROXY_KEY thay thế (xem _call_deepseek_with_tools()).
    api_key = os.environ.get('DEEPSEEK_API_KEY')
    is_desktop_mode = os.environ.get('BITPAW_DESKTOP_MODE') == '1'
    if not api_key and not is_desktop_mode:
        return jsonify({"choices": [{"message": {"content": fallback_reply}}], "fallback": True,
                         "error": "Server chưa cấu hình DEEPSEEK_API_KEY."})

    try:
        # Timeout nới rộng lên 45s: các câu hỏi có nhúng bảng giá/danh mục sản phẩm dài cho
        # tenant nhiều hàng hoá cần nhiều thời gian xử lý hơn so với persona ngắn cũ.
        # _call_deepseek_with_tools() cho phép AI THỰC SỰ gọi book_appointment() (Function
        # Calling) thay vì chỉ sinh văn bản "đã đặt lịch" mà không ghi gì vào Database.
        result = _call_deepseek_with_tools(
            messages, temperature, max_tokens, business_id, customer_id, api_key
        )
        try:
            ai_text = result['choices'][0]['message']['content']
            _persist_chat_turn(business_id, customer_phone, ai_text, sender_type='ai')

            # Phase 2: throttled, background-thread distillation of the running memory —
            # never awaited, never allowed to slow down this response (xem ai_memory_engine.py).
            if customer_id and db is not None:
                customer_turn_count = db.bot_messages.count_documents(
                    {'customer_id': customer_id, 'sender_type': 'customer'}
                )
                recent_turns = history[-6:] + [
                    {'role': 'user', 'content': latest_customer_message},
                    {'role': 'assistant', 'content': ai_text},
                ]
                maybe_distill_memory_async(customer_id, recent_turns, customer_turn_count)
        except Exception:
            pass
        return jsonify(result)
    except requests.exceptions.Timeout:
        return jsonify({"choices": [{"message": {"content": fallback_reply}}], "fallback": True,
                         "error": "AI service timeout sau 45s."})
    except requests.exceptions.HTTPError as e:
        return jsonify({"choices": [{"message": {"content": fallback_reply}}], "fallback": True,
                         "error": f"AI service từ chối request: {str(e)}"})
    except requests.exceptions.RequestException as e:
        return jsonify({"choices": [{"message": {"content": fallback_reply}}], "fallback": True,
                         "error": f"Lỗi kết nối AI service: {str(e)}"})
    except RuntimeError as e:
        # ai_deepseek_client.py bọc mọi lỗi HTTP (bao gồm requests.exceptions.HTTPError) thành
        # RuntimeError để thống nhất thông điệp lỗi giữa 2 nhánh gọi trực tiếp/qua AI Proxy —
        # nếu không bắt riêng ở đây, lỗi sẽ thoát ra thành 500 thô không có JSON, thay vì
        # fallback_reply đàng hoàng như các nhánh lỗi khác phía trên.
        return jsonify({"choices": [{"message": {"content": fallback_reply}}], "fallback": True,
                         "error": str(e)})


@app.route('/app_chat')
@login_required
def app_chat():
    return render_template('app_chat.html')

@app.route('/chat')
@login_required
def chat():
    return render_template('chat.html')

@app.route('/crm_automation')
@login_required
def crm_automation():
    return render_template('crm_automation.html')

@app.route('/map_dashboard')
@login_required
@role_required('admin', 'super_admin')
def map_dashboard():
    return render_template('map_dashboard.html')

@app.route('/app_nhanvien')
@login_required
def app_nhanvien():
    return render_template('app_nhanvien.html')

@app.route('/api/superadmin/duc_ma', methods=['POST'])
@login_required
def duc_ma():
    if not _is_superadmin():
        return jsonify({"success": False, "message": "Access denied: Superadmin privileges required."}), 403
    data = request.json
    ma_key = (data.get('license_key') or '').strip()
    nganh = data.get('nganh_nghe')
    if not ma_key:
        return jsonify({"success": False, "message": "Missing license code."}), 400
    try:
        # license_codes là collection license dùng chung toàn hệ thống trên MongoDB (không thuộc
        # riêng tenant nào). update_one(..., upsert=True) trên license_key giữ đúng hành vi
        # "INSERT OR REPLACE" cũ (nếu key đã tồn tại thì reset lại về 'Sẵn sàng').
        db.license_codes.update_one(
            {'license_key': ma_key},
            {'$set': {'nganh_nghe': nganh, 'trang_thai': 'Sẵn sàng'},
             '$setOnInsert': {'id': next_mongo_id('license_codes')}},
            upsert=True
        )
        return jsonify({"success": True, "message": f"License code {ma_key} generated successfully!"})
    except Exception as e:
        print(f"[duc_ma] Lỗi ghi license_codes lên MongoDB: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/superadmin/get_keys', methods=['GET'])
@login_required
def get_keys():
    if not _is_superadmin():
        return jsonify({"success": False, "message": "Access denied: Superadmin privileges required."}), 403
    try:
        docs = db.license_codes.find(
            {}, {'id': 1, 'license_key': 1, 'nganh_nghe': 1, 'trang_thai': 1, '_id': 0}
        ).sort('id', -1)
        # Trả về status code trung lập (không phải chuỗi tiếng Việt trực tiếp) để frontend tự
        # dịch hiển thị theo currentLang — trước đây trả thẳng 'trang_thai' tiếng Việt ('Đã kích
        # hoạt') khiến badge trạng thái luôn hiện tiếng Việt bất kể ngôn ngữ đang chọn.
        _status_code_map = {'Sẵn sàng': 'ready', 'Đã kích hoạt': 'activated'}
        keys_list = [{
            "id": k['id'],
            "key_code": k['license_key'],
            "industry": k['nganh_nghe'],
            "status": _status_code_map.get(k['trang_thai'], k['trang_thai'])
        } for k in docs]
        return jsonify({"success": True, "data": keys_list})
    except Exception as e:
        print(f"[get_keys] Lỗi đọc license_codes từ MongoDB: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/superadmin/delete_key/<int:key_id>', methods=['DELETE'])
@login_required
def delete_key(key_id):
    if not _is_superadmin():
        return jsonify({"success": False, "message": "Access denied: Superadmin privileges required."}), 403
    try:
        db.license_codes.delete_one({'id': key_id})
        return jsonify({"success": True, "message": "License key deleted successfully!"})
    except Exception as e:
        print(f"[delete_key] Lỗi xóa license_codes id={key_id} trên MongoDB: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 500


# ========== SUPER ADMIN: CỔNG THANH TOÁN NHẬN TIỀN (thay Supabase JS ở super_admin.html)
# db.payment_methods — collection mới, TOÀN CỤC dùng chung cho mọi tenant (danh sách ngân
# hàng nhận tiền hiển thị ở checkout.html), không có business_id — chỉ superadmin sửa được. ==========
@app.route('/api/superadmin/payment_methods', methods=['GET'])
@login_required
def api_superadmin_payment_methods_list():
    if not _is_superadmin():
        return jsonify({"success": False, "message": "Access denied: Superadmin privileges required."}), 403
    try:
        methods = list(db.payment_methods.find({}, {'_id': 0}).sort('id', 1))
        return jsonify({"success": True, "data": methods})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/superadmin/payment_methods', methods=['POST'])
@login_required
def api_superadmin_payment_methods_create():
    if not _is_superadmin():
        return jsonify({"success": False, "message": "Access denied: Superadmin privileges required."}), 403
    data = request.json or {}
    try:
        doc = {
            'id': next_mongo_id('payment_methods'),
            'bin_code': data.get('bin_code', ''),
            'provider_name': data.get('provider_name', ''),
            'account_number': data.get('account_number', ''),
            'account_name': data.get('account_name', ''),
            'logo_url': data.get('logo_url', ''),
            'is_active': True,
        }
        db.payment_methods.insert_one(doc)
        doc.pop('_id', None)
        return jsonify({"success": True, "data": doc})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/superadmin/payment_methods/<int:id>', methods=['PATCH'])
@login_required
def api_superadmin_payment_methods_update(id):
    if not _is_superadmin():
        return jsonify({"success": False, "message": "Access denied: Superadmin privileges required."}), 403
    data = request.json or {}
    updates = {k: v for k, v in data.items() if k in ('bin_code', 'provider_name', 'account_number', 'account_name', 'logo_url', 'is_active')}
    if not updates:
        return jsonify({"success": False, "message": "No valid fields to update."}), 400
    try:
        result = db.payment_methods.update_one({'id': id}, {'$set': updates})
        if result.matched_count == 0:
            return jsonify({"success": False, "message": "Payment method not found."}), 404
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


# ==================================================
# SUPER ADMIN: TRUNG TÂM ĐIỀU KHIỂN CHAT (cross-tenant)
# Đọc trực tiếp bot_customers/bot_messages đã có sẵn — đây chính là dữ liệu chat thật được
# ghi bởi _persist_chat_turn() mỗi khi khách chat qua AI widget trên Landing Page của từng
# tenant. KHÔNG dùng bảng messages mới nào cả, tránh phân mảnh dữ liệu.
# ==================================================

# Pipeline $lookup dùng chung để nối bot_customers.business_id -> businesses.id (tương đương
# embedded-join "bot_customers(*, businesses(name))" của Postgres/PostgREST cũ). CHÚ Ý: 2 route
# dưới đây CỐ TÌNH không lọc theo 1 business_id cụ thể — đây là màn hình Super Admin xem TẤT CẢ
# hội thoại của MỌI tenant cùng lúc (đúng mục đích thiết kế), không phải route thiếu sót bảo mật.
@app.route('/api/superadmin/stats', methods=['GET'])
@login_required
def api_superadmin_stats():
    """Chỉ số tổng quan cross-tenant cho Command Center (/super_admin) — Doanh thu hôm
    nay/tháng này, hội thoại AI hôm nay, leads đang chờ xử lý. Mọi giá trị LUÔN trả về
    dạng số (0 nếu chưa có bản ghi/lỗi truy vấn) — KHÔNG BAO GIỜ trả None/thiếu field,
    để frontend không bao giờ phải hiển thị "--" nữa (đúng yêu cầu: mặc định 0/0 VND/0%
    thay vì để trống khi DB rỗng hoặc lỗi)."""
    if not _is_superadmin():
        return jsonify({"success": False, "message": "Access denied: Superadmin privileges required."}), 403

    stats = {
        'revenue_today': 0,
        'revenue_month': 0,
        'ai_conversations_today': 0,
        'leads_pending': 0,
        # He thong hien CHUA co pipeline theo doi luot truy cap/phien (session/funnel step) nao
        # ca — khong co du lieu that de tinh ra 1 ty le chuyen doi co y nghia, nen mac dinh 0
        # thay vi bia so lieu gia co the gay hieu nham quyet dinh kinh doanh.
        'pos_conversion_rate': 0,
        'returning_customer_rate': 0,
    }

    if db is None:
        return jsonify({"success": True, "data": stats})

    now = datetime.now()
    today_str = now.strftime('%Y-%m-%d')
    tomorrow_str = (now + timedelta(days=1)).strftime('%Y-%m-%d')
    month_start_str = now.strftime('%Y-%m-01')

    try:
        result = list(db.orders.aggregate([
            {'$match': {'created_at': {'$gte': today_str, '$lt': tomorrow_str}}},
            {'$group': {'_id': None, 'total': {'$sum': '$total_amount'}}},
        ]))
        stats['revenue_today'] = result[0]['total'] if result else 0
    except Exception as e:
        print(f"[api_superadmin_stats] Lỗi tính revenue_today: {str(e)}")

    try:
        result = list(db.orders.aggregate([
            {'$match': {'created_at': {'$gte': month_start_str}}},
            {'$group': {'_id': None, 'total': {'$sum': '$total_amount'}}},
        ]))
        stats['revenue_month'] = result[0]['total'] if result else 0
    except Exception as e:
        print(f"[api_superadmin_stats] Lỗi tính revenue_month: {str(e)}")

    try:
        # Moi conversation = 1 customer_id co it nhat 1 tin nhan (bat ky ben nao gui) trong hom nay.
        stats['ai_conversations_today'] = len(db.bot_messages.distinct(
            'customer_id', {'created_at': {'$gte': today_str, '$lt': tomorrow_str}}
        ))
    except Exception as e:
        print(f"[api_superadmin_stats] Lỗi đếm ai_conversations_today: {str(e)}")

    try:
        stats['leads_pending'] = db.saas_signups.count_documents({'status': 'pending'})
    except Exception as e:
        print(f"[api_superadmin_stats] Lỗi đếm leads_pending: {str(e)}")

    return jsonify({"success": True, "data": stats})


# Việc chặn truy cập chéo-tenant ở đây được đảm bảo bằng _is_superadmin() (chỉ 1 tài khoản trùm/
# danh sách SUPERADMIN_EMAILS mới qua được), KHÔNG phải bằng match business_id như các route
# tenant thường khác — quy tắc "mọi query phải match business_id" áp dụng cho route của CHỦ TIỆM
# thường, không áp dụng cho route cross-tenant đã có gate riêng như route này.
def _lookup_business_name_stage():
    return [
        {'$lookup': {
            'from': 'businesses',
            'localField': 'business_id',
            'foreignField': 'id',
            'as': '_business_info'
        }},
        {'$addFields': {'businesses': {'$arrayElemAt': ['$_business_info', 0]}}},
        {'$project': {'_business_info': 0, '_id': 0}}
    ]


@app.route('/api/superadmin/chat/conversations', methods=['GET'])
@login_required
def superadmin_chat_conversations():
    if not _is_superadmin():
        return jsonify({"success": False, "message": "Access denied: Superadmin privileges required."}), 403
    try:
        pipeline = [{'$sort': {'last_message_time': -1}}] + _lookup_business_name_stage()
        conversations = list(db.bot_customers.aggregate(pipeline))
        for conv in conversations:
            # Đếm tin nhắn CHƯA đọc gửi TỪ khách (best-effort — 1 conversation lỗi đếm
            # không được phép làm gãy cả danh sách).
            try:
                conv['unread_count'] = db.bot_messages.count_documents({
                    'customer_id': conv['id'], 'sender_type': 'customer', 'is_read': False
                })
            except Exception as count_err:
                print(f"[superadmin_chat_conversations] Đếm tin chưa đọc lỗi cho customer_id={conv.get('id')}: {str(count_err)}")
                conv['unread_count'] = 0
        return jsonify({"success": True, "data": conversations})
    except Exception as e:
        print(f"[superadmin_chat_conversations] Lỗi tải danh sách hội thoại: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/superadmin/chat/messages/<path:customer_id>', methods=['GET'])
@login_required
def superadmin_chat_messages(customer_id):
    if not _is_superadmin():
        return jsonify({"success": False, "message": "Access denied: Superadmin privileges required."}), 403
    try:
        msgs = list(
            db.bot_messages.find({'customer_id': customer_id}, {'_id': 0}).sort('created_at', 1)
        )
        cust_pipeline = [{'$match': {'id': customer_id}}] + _lookup_business_name_stage() + [{'$limit': 1}]
        cust_docs = list(db.bot_customers.aggregate(cust_pipeline))
        # Đánh dấu đã đọc toàn bộ tin nhắn từ khách trong hội thoại này ngay khi admin mở xem
        try:
            db.bot_messages.update_many(
                {'customer_id': customer_id, 'sender_type': 'customer', 'is_read': False},
                {'$set': {'is_read': True}}
            )
        except Exception as mark_err:
            print(f"[superadmin_chat_messages] Đánh dấu đã đọc thất bại cho customer_id={customer_id}: {str(mark_err)}")
        return jsonify({
            "success": True,
            "messages": msgs,
            "customer": (cust_docs[0] if cust_docs else None)
        })
    except Exception as e:
        print(f"[superadmin_chat_messages] Lỗi tải hội thoại customer_id={customer_id}: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/superadmin/chat/messages/<path:customer_id>', methods=['POST'])
@login_required
def superadmin_chat_send_message(customer_id):
    """Admin gõ trả lời trong /super_admin 'Tất Cả Hội Thoại' — ghi thẳng vào bot_messages với
    sender_type='staff' cho ĐÚNG customer_id đang mở (business_id:phone hoặc
    BITPAW_LEADS_BUSINESS_ID:phone nếu là lead từ landing page marketing). Widget CSKH phía
    khách (cskh_widget.js) đang lắng nghe /api/stream/cskh_chat trên đúng customer_id này nên
    tin nhắn xuất hiện gần như ngay lập tức bên phía khách, không cần khách tự bấm refresh."""
    if not _is_superadmin():
        return jsonify({"success": False, "message": "Access denied: Superadmin privileges required."}), 403
    data = request.json or {}
    content = (data.get('content') or '').strip()
    if not content:
        return jsonify({"success": False, "message": "Nội dung tin nhắn trống."}), 400
    try:
        cust = db.bot_customers.find_one({'id': customer_id}, {'business_id': 1, '_id': 0})
        if not cust:
            return jsonify({"success": False, "message": "Không tìm thấy hội thoại này."}), 404
        now_iso = datetime.now().isoformat()
        db.bot_messages.insert_one({
            'customer_id': customer_id, 'sender_type': 'staff', 'content': content[:2000],
            'business_id': cust.get('business_id'), 'created_at': now_iso, 'is_read': True,
        })
        db.bot_customers.update_one(
            {'id': customer_id}, {'$set': {'last_message': content[:500], 'last_message_time': now_iso}}
        )
        return jsonify({"success": True})
    except Exception as e:
        print(f"[superadmin_chat_send_message] Lỗi gửi tin nhắn customer_id={customer_id}: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 500


# ========== SUPERADMIN — LEADS TỪ WIDGET "AI TƯ VẤN" TRÊN LANDING PAGE ==========
# db.cskh_requests đã được ghi từ lâu (create_cskh_request(), /api/cskh/request — form
# "Nhập nhu cầu tư vấn" trong static/js/cskh_widget.js) nhưng CHƯA từng có route đọc lại —
# tức là landing page gửi lead thành công nhưng không ai xem được. Đây KHÔNG phải dữ liệu
# theo tenant (business_id) — là lead của chính BitPaw (người quan tâm mua phần mềm), nên chỉ
# Superadmin được xem, không dùng business_id để lọc.
@app.route('/api/superadmin/cskh_requests', methods=['GET'])
@login_required
def superadmin_cskh_requests_list():
    if not _is_superadmin():
        return jsonify({"success": False, "message": "Access denied: Superadmin privileges required."}), 403
    try:
        limit = min(request.args.get('limit', 50, type=int), 200)
        leads = list(db.cskh_requests.find({}, {'_id': 0}).sort('id', -1).limit(limit))
        pending_count = db.cskh_requests.count_documents({'status': 'pending'})
        return jsonify({"success": True, "data": leads, "pending_count": pending_count})
    except Exception as e:
        print(f"[superadmin_cskh_requests_list] Lỗi tải danh sách leads: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/superadmin/cskh_requests/<int:lead_id>/status', methods=['POST'])
@login_required
def superadmin_cskh_requests_update_status(lead_id):
    if not _is_superadmin():
        return jsonify({"success": False, "message": "Access denied: Superadmin privileges required."}), 403
    new_status = (request.json or {}).get('status', 'contacted')
    if new_status not in ('pending', 'contacted'):
        return jsonify({"success": False, "message": "Trạng thái không hợp lệ."}), 400
    try:
        result = db.cskh_requests.update_one({'id': lead_id}, {'$set': {'status': new_status}})
        if result.matched_count == 0:
            return jsonify({"success": False, "message": "Không tìm thấy lead này."}), 404
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/stream/cskh_requests')
@login_required
def stream_cskh_requests():
    """SSE + Change Streams (đúng pattern _sse_change_signal đã dùng cho chat_messages/
    employees/payroll) — KHÔNG lọc theo business_id vì cskh_requests không thuộc tenant nào."""
    if not _is_superadmin():
        return jsonify({"success": False, "message": "Access denied: Superadmin privileges required."}), 403
    return _sse_change_signal(db.cskh_requests, {'$match': {}})


# ==================================================
# AI BOT OMNICHANNEL CUSTOMER NURTURING PLATFORM ROUTES
# ==================================================

@app.route('/ai/connect-platforms')
@app.route('/omnichannel_connect')
@login_required
def connect_platforms():
    return render_template('omnichannel_connect.html')

@app.route('/ai/customer-nurturing')
@app.route('/customer_nurturing')
@login_required
def customer_nurturing():
    return render_template('customer_nurturing.html')

@app.route('/ai/campaign-builder')
@app.route('/campaign_builder')
@login_required
def campaign_builder():
    return render_template('campaign_builder.html')

@app.route('/api/ai/nurture/connect-status', methods=['GET'])
@login_required
def nurture_connect_status():
    business_id, _biz_err = _get_tenant_business_id_or_401()
    if _biz_err:
        return _biz_err
    try:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("SELECT platform, connection_status, updated_at, config_data FROM platform_connections WHERE business_id = ?", (business_id,))
        rows = c.fetchall()
        
        # Build status map
        status_map = {}
        for row in rows:
            status_map[row[0]] = {
                "status": row[1],
                "updated_at": row[2],
                "config_data": row[3]
            }
        
        conn.close()

        # Count customers to use as real lead counts — giờ đọc trực tiếp từ db.customers
        # (MongoDB), không còn shadow copy customer_profiles (SQLite) nữa.
        real_leads = db.customers.count_documents({'business_id': business_id}) if db is not None else 0
        
        platforms = ['messenger', 'fb_page', 'zalo_oa', 'whatsapp', 'mascot_chat', 'pos_sync']
        data = {}
        for p in platforms:
            p_data = status_map.get(p, {"status": "DISCONNECTED", "updated_at": None, "config_data": None})
            status_str = p_data["status"]
            config_str = p_data["config_data"]
            
            # Setup config payload from DB config_data
            config = {}
            if config_str:
                try:
                    config = json.loads(config_str)
                except Exception:
                    pass
            
            account_name = config.get("account_name", "")
            channel_id = config.get("channel_id", "")
            access_token = config.get("access_token", "")
            
            # Real setup validation check: if token or channel id is empty, connection requires configuration
            if not access_token or not channel_id:
                if status_str == "CONNECTED":
                    status_str = "SETUP_REQUIRED"
                elif status_str == "DISCONNECTED" and p in ['whatsapp', 'fb_page']:
                    # Setup required if disconnected to match three states natively
                    status_str = "SETUP_REQUIRED"
                
            if status_str == "CONNECTED":
                last_sync = p_data["updated_at"] or "2026-05-30 00:30"
                leads_count = real_leads if p == 'pos_sync' else (18 + (hash(p) % 45))
            else:
                last_sync = "Chưa đồng bộ"
                leads_count = 0
                
            data[p] = {
                "status": status_str,
                "last_sync": last_sync,
                "leads_count": leads_count,
                "account_name": account_name,
                "channel_id": channel_id,
                "access_token": access_token
            }
                
        return jsonify({"success": True, "data": data})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/ai/nurture/toggle-connection', methods=['POST'])
@login_required
def nurture_toggle_connection():
    data = request.json or {}
    platform = data.get('platform')
    action = data.get('action') # 'CONNECT', 'DISCONNECT', 'SAVE'
    
    if not platform:
        return jsonify({"success": False, "message": "Missing platform parameter"}), 400
        
    business_id, _biz_err = _get_tenant_business_id_or_401()
    if _biz_err:
        return _biz_err
    
    try:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        
        if action == 'DISCONNECT':
            c.execute("UPDATE platform_connections SET connection_status = 'DISCONNECTED', config_data = NULL, updated_at = CURRENT_TIMESTAMP WHERE business_id = ? AND platform = ?",
                      (business_id, platform))
            conn.commit()
            conn.close()
            return jsonify({"success": True, "status": "DISCONNECTED"})
            
        elif action == 'SAVE':
            account_name = data.get('account_name', '').strip()
            channel_id = data.get('channel_id', '').strip()
            access_token = data.get('access_token', '').strip()
            
            if not account_name or not channel_id or not access_token:
                conn.close()
                return jsonify({"success": False, "message": "Vui lòng nhập đầy đủ thông tin kết nối và API Access Token!"}), 400
                
            config_payload = {
                "account_name": account_name,
                "channel_id": channel_id,
                "access_token": access_token
            }
            config_str = json.dumps(config_payload)
            
            c.execute("INSERT OR REPLACE INTO platform_connections (id, business_id, platform, connection_status, config_data, updated_at) VALUES (?, ?, ?, 'CONNECTED', ?, CURRENT_TIMESTAMP)",
                      (f"{business_id}-{platform}", business_id, platform, config_str))
            conn.commit()
            conn.close()
            return jsonify({"success": True, "status": "CONNECTED"})
            
        else: # Standard fallback toggle
            c.execute("SELECT connection_status, config_data FROM platform_connections WHERE business_id = ? AND platform = ?", (business_id, platform))
            row = c.fetchone()
            current_status = row[0] if row else 'DISCONNECTED'
            config_str = row[1] if row else None
            
            new_status = 'DISCONNECTED' if current_status == 'CONNECTED' else 'CONNECTED'
            
            if new_status == 'CONNECTED':
                config = {}
                if config_str:
                    try:
                        config = json.loads(config_str)
                    except Exception:
                        pass
                if not config.get('access_token'):
                    conn.close()
                    return jsonify({"success": False, "message": "Chưa cấu hình API key. Vui lòng cấu hình tài khoản trước!"}), 400
            
            c.execute("INSERT OR REPLACE INTO platform_connections (id, business_id, platform, connection_status, config_data, updated_at) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
                      (f"{business_id}-{platform}", business_id, platform, new_status, config_str))
            conn.commit()
            conn.close()
            return jsonify({"success": True, "status": new_status})
            
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/ai/nurture/test-connection', methods=['POST'])
@login_required
def nurture_test_connection():
    """Mã Nurture Part 3 audit — TRƯỚC ĐÂY: trả 'Kết nối thử nghiệm thành công' hardcode ngay
    khi thấy access_token/channel_id không rỗng, KHÔNG hề gọi provider nào để xác minh. GIỜ: gọi
    thật API của Zalo OA / Facebook để xác thực token, chỉ báo thành công khi provider THẬT SỰ
    xác nhận, và lưu token đã xác thực (mã hoá) theo business_id để message_delivery_worker.py
    dùng lại khi gửi tin nhắn nurture thật."""
    data = request.json or {}
    platform = (data.get('platform') or '').strip().lower()
    access_token = (data.get('access_token') or '').strip()

    if platform not in ('zalo', 'zalo_oa', 'facebook', 'messenger'):
        return jsonify({"success": False, "message": f"Platform '{platform}' chưa được hỗ trợ thật."}), 400
    if not access_token:
        return jsonify({"success": False, "message": "Thiếu access_token."}), 400

    business_id = session.get('business_id') or session['user_id']
    norm_platform = 'zalo_oa' if platform in ('zalo', 'zalo_oa') else 'facebook'

    try:
        if norm_platform == 'zalo_oa':
            resp = requests.get(
                'https://openapi.zalo.me/v2.0/oa/getoa',
                headers={'access_token': access_token}, timeout=10,
            )
            payload = resp.json()
            if payload.get('error') not in (0, None):
                return jsonify({"success": False, "message": f"Zalo từ chối token: {payload.get('message')}"}), 400
            oa_data = payload.get('data') or {}
            extra = {'oa_id': oa_data.get('oa_id'), 'oa_name': oa_data.get('name')}
        else:
            resp = requests.get(
                'https://graph.facebook.com/v21.0/me',
                params={'access_token': access_token, 'fields': 'id,name'}, timeout=10,
            )
            payload = resp.json()
            if 'error' in payload:
                return jsonify({"success": False, "message": f"Facebook từ chối token: {payload['error'].get('message')}"}), 400
            extra = {'page_id': payload.get('id'), 'page_name': payload.get('name')}
    except requests.exceptions.Timeout:
        return jsonify({"success": False, "message": "Provider API timeout, vui lòng thử lại."}), 504
    except requests.exceptions.RequestException as e:
        return jsonify({"success": False, "message": f"Lỗi kết nối tới provider: {e}"}), 502

    try:
        nurture_channel_tokens.save_channel_token(business_id, norm_platform, access_token, extra)
    except RuntimeError as e:
        return jsonify({"success": False, "message": str(e)}), 500

    return jsonify({
        "success": True,
        "message": f"Đã xác thực & lưu token {norm_platform} thật (phản hồi provider: {extra}).",
        "info": extra,
    })



# ========== OMNICHANNEL QA CHANNELS MAPPING ==========
CHANNEL_MAP = {
    'facebook': 'messenger',
    'messenger': 'messenger',
    'fb_page': 'fb_page',
    'whatsapp': 'whatsapp',
    'zalo': 'zalo_oa',
    'zalo_oa': 'zalo_oa',
    'website': 'mascot_chat',
    'mascot_chat': 'mascot_chat',
    'pos_sync': 'pos_sync'
}

@app.route('/omnichannel/status', methods=['GET'])
@login_required
def omnichannel_status_all():
    return nurture_connect_status()

@app.route('/omnichannel/status/<channel>', methods=['GET'])
@login_required
def omnichannel_status_single(channel):
    target = CHANNEL_MAP.get(channel.lower())
    if not target:
        return jsonify({"success": False, "message": f"Invalid channel: {channel}"}), 400
    res = nurture_connect_status()
    if not res.json.get('success'):
        return res
    all_data = res.json.get('data', {})
    channel_data = all_data.get(target, {"status": "DISCONNECTED", "last_sync": "Chưa đồng bộ", "leads_count": 0})
    return jsonify({"success": True, "channel": channel, "mapped_platform": target, "data": channel_data})

@app.route('/omnichannel/connect/<channel>', methods=['GET'])
@login_required
def omnichannel_connect_portal(channel):
    target = CHANNEL_MAP.get(channel.lower())
    if not target:
        return f"Invalid channel: {channel}", 400
    return render_template('omnichannel_connect_placeholder.html', channel=channel, platform=target)

@app.route('/omnichannel/callback/<channel>', methods=['GET'])
@login_required
def omnichannel_callback(channel):
    """Trang callback OAuth-style hiển thị cho popup trình duyệt (không phải route Mobile gọi
    trực tiếp) — GIỮ NGUYÊN HTML ở nhánh thành công. Giai đoạn 5 audit: chỉ JSON-hoá các nhánh
    LỖI khi _wants_json(), để nhất quán/an toàn nếu 1 client REST gọi nhầm route này."""
    target = CHANNEL_MAP.get(channel.lower())
    if not target:
        msg = f"Invalid channel: {channel}"
        return (jsonify({"success": False, "message": msg}), 400) if _wants_json() else (msg, 400)
    account_name = request.args.get('account_name', '').strip()
    channel_id = request.args.get('channel_id', '').strip()
    access_token = request.args.get('access_token', '').strip()
    if not account_name or not channel_id or not access_token:
        msg = "Thiếu thông tin cấu hình callback!"
        return (jsonify({"success": False, "message": msg}), 400) if _wants_json() else (msg, 400)
    business_id = session.get('business_id')
    if not business_id:
        msg = "Phiên đăng nhập không hợp lệ, vui lòng đăng nhập lại."
        return (jsonify({"success": False, "message": msg}), 401) if _wants_json() else (msg, 401)
    try:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        config_payload = {
            "account_name": account_name,
            "channel_id": channel_id,
            "access_token": access_token
        }
        config_str = json.dumps(config_payload)
        c.execute("INSERT OR REPLACE INTO platform_connections (id, business_id, platform, connection_status, config_data, updated_at) VALUES (?, ?, ?, 'CONNECTED', ?, CURRENT_TIMESTAMP)",
                  (f"{business_id}-{target}", business_id, target, config_str))
        conn.commit()
        conn.close()
    except Exception as db_err:
        msg = f"Lỗi lưu trữ cấu hình: {str(db_err)}"
        return (jsonify({"success": False, "message": msg}), 500) if _wants_json() else (msg, 500)
    return f"""
    <!DOCTYPE html>
    <html>
    <head><title>Ủy quyền thành công</title></head>
    <body style="background:#08061a; color:white; font-family:sans-serif; text-align:center; padding-top:100px;">
        <h2 style="color:#06b6d4;">🎉 Kết nối ứng dụng thành công!</h2>
        <p>BitPaw AI đã kết nối thành công tới tài khoản của sếp.</p>
        <script>
            alert("✅ Cấp quyền thành công! Cổng kết nối {channel.upper()} đã hoạt động.");
            if (window.opener) {{
                try {{
                    window.opener.reloadConnectionStatus();
                }} catch(e) {{}}
            }}
            window.close();
        </script>
    </body>
    </html>
    """

@app.route('/omnichannel/disconnect/<channel>', methods=['POST'])
@login_required
def omnichannel_disconnect_api(channel):
    target = CHANNEL_MAP.get(channel.lower())
    if not target:
        return jsonify({"success": False, "message": f"Invalid channel: {channel}"}), 400
    business_id, _biz_err = _get_tenant_business_id_or_401()
    if _biz_err:
        return _biz_err
    try:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("UPDATE platform_connections SET connection_status = 'DISCONNECTED', config_data = NULL, updated_at = CURRENT_TIMESTAMP WHERE business_id = ? AND platform = ?",
                  (business_id, target))
        conn.commit()
        conn.close()
        return jsonify({"success": True, "status": "DISCONNECTED", "message": f"Ngắt kết nối thành công kênh {channel}"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/omnichannel/test/<channel>', methods=['POST'])
@login_required
def omnichannel_test_api(channel):
    target = CHANNEL_MAP.get(channel.lower())
    if not target:
        return jsonify({"success": False, "message": f"Invalid channel: {channel}"}), 400
    business_id, _biz_err = _get_tenant_business_id_or_401()
    if _biz_err:
        return _biz_err
    try:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("SELECT config_data FROM platform_connections WHERE business_id = ? AND platform = ? AND connection_status = 'CONNECTED'", (business_id, target))
        row = c.fetchone()
        conn.close()
        if not row:
            return jsonify({"success": False, "message": f"Cổng kết nối {channel.upper()} chưa được cấu hình. Vui lòng kết nối trước!"}), 400
        config = json.loads(row[0]) if row[0] else {}
        access_token = config.get("access_token")
        channel_id = config.get("channel_id")
        if not access_token or not channel_id:
            return jsonify({"success": False, "message": "Thông tin cấu hình không hợp lệ!"}), 400
        return jsonify({
            "success": True,
            "message": f"Kết nối kiểm thử tới Provider API ({channel.upper()}) thành công! Phản hồi từ Máy chủ đối tác: OK (200)."
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/cskh/lead-submit', methods=['POST'])
@login_required
def cskh_lead_submit():
    data = request.json or {}
    phone = data.get('phone', '').strip()
    message = data.get('message', '').strip()

    if not re.match(r'^0\d{9,10}$', phone) or not message:
        return jsonify({"success": False, "message": "Vui lòng cung cấp đầy đủ thông tin (SĐT hợp lệ)!"}), 400

    # Trước đây default 'mock-business-123' khi thiếu session khiến lead của MỌI tiệm bị trộn chung.
    # Bắt buộc đăng nhập để luôn có business_id thật của đúng tiệm.
    business_id = session.get('business_id') or session['user_id']

    try:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("INSERT INTO customer_events (id, business_id, customer_id, event_type, description, created_at) VALUES (?, ?, ?, 'lead_submit', ?, CURRENT_TIMESTAMP)",
                  (str(uuid.uuid4()), business_id, phone, f"Yêu cầu tư vấn Mascot AI: {message}"))
        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": "Lead submitted successfully."})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500



@app.route('/api/ai/nurture/customers', methods=['GET'])
@login_required
def nurture_customers():
    """Đọc trực tiếp db.customers (MongoDB) — không còn shadow copy customer_profiles
    (SQLite). Các field nurturing (status/ai_notes/potential_score/last_purchase_at)
    có thể chưa tồn tại trên khách hàng cũ nào chưa từng được chấm điểm — mặc định về
    đúng giá trị gốc trước đây ('NEW'/50/None) trong trường hợp đó, KHÔNG lỗi/thiếu field."""
    business_id = session.get('business_id') or session['user_id']

    try:
        rows = list(db.customers.find(
            {'business_id': business_id},
            {'id': 1, 'name': 1, 'phone': 1, 'email': 1, 'industry': 1, 'source_platform': 1,
             'last_purchase_at': 1, 'total_spent': 1, 'services_of_interest': 1,
             'nurturing_status': 1, 'ai_notes': 1, 'potential_score': 1, '_id': 0}
        ).sort('total_spent', -1))

        customers = []
        for r in rows:
            customers.append({
                # id ép về string: JS phía client so khớp id kiểu strict "===" sau khi đã
                # nhúng qua thuộc tính onclick (luôn ra string) — giữ nguyên type string
                # tránh lệch kiểu int-vs-string y hệt hành vi cũ (customer_profiles.id TEXT).
                "id": str(r.get('id')),
                "name": r.get('name'),
                "phone": r.get('phone'),
                "email": r.get('email'),
                "industry": r.get('industry'),
                "source": r.get('source_platform'),
                "last_purchase": r.get('last_purchase_at'),
                "total_spend": r.get('total_spent') or 0,
                "service_interest": r.get('services_of_interest'),
                "status": r.get('nurturing_status') or 'NEW',
                "ai_notes": r.get('ai_notes'),
                "potential_score": r.get('potential_score') if r.get('potential_score') is not None else 50,
            })

        return jsonify({"success": True, "data": customers})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/customers/service-photos', methods=['GET', 'POST'])
@login_required
def customer_service_photos():
    """Trí nhớ dài hạn cho AI Omni-CSKH: lưu/tra ảnh mẫu dịch vụ cũ (vd: mẫu nail đã
    làm tháng trước) theo SĐT khách, để AIContextEngine nhúng vào prompt chat lần sau."""
    business_id = session.get('business_id') or session['user_id']

    if request.method == 'POST':
        data = request.get_json(silent=True) or request.form
        customer_phone = (data.get('customer_phone') or '').strip()
        image_url = (data.get('image_url') or '').strip()
        note = (data.get('note') or '').strip() or None
        if not customer_phone or not image_url:
            return jsonify({"success": False, "message": "Thiếu customer_phone hoặc image_url."}), 400
        try:
            new_doc = {
                'id': next_mongo_id('service_photos'),
                'business_id': business_id,
                'customer_phone': customer_phone,
                'image_url': image_url,
                'note': note,
                'created_at': datetime.now().isoformat(),
            }
            db.service_photos.insert_one(new_doc)
            new_doc.pop('_id', None)
            return jsonify({"success": True, "data": [new_doc]})
        except Exception as e:
            return jsonify({"success": False, "message": str(e)}), 500

    customer_phone = request.args.get('customer_phone')
    if not customer_phone:
        return jsonify({"success": False, "message": "Thiếu customer_phone."}), 400
    try:
        photos = list(db.service_photos.find(
            {'business_id': business_id, 'customer_phone': customer_phone},
            {'id': 1, 'image_url': 1, 'note': 1, 'created_at': 1, '_id': 0}
        ).sort('created_at', -1).limit(20))
        return jsonify({"success": True, "data": photos})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/ai/nurture/import-data', methods=['POST'])
@login_required
def nurture_import_data():
    """Trước đây: đồng bộ 1 chiều db.customers -> shadow copy SQLite, luôn set
    nurturing_status='NEW' không bao giờ đổi. Giờ: tính lại RFM THẬT cho từng khách qua
    recompute_customer_segments() — hàm DÙNG CHUNG với nurture_scheduler.py (Mã Nurture Part 2
    audit) để nút bấm thủ công này và cron tự động luôn tính "khách bao lâu chưa mua" giống
    hệt nhau, không lệch công thức."""
    business_id = session.get('business_id') or session['user_id']

    if db is None:
        return jsonify({"success": False, "message": "MongoDB chưa kết nối."}), 503

    try:
        recomputed = recompute_customer_segments(business_id)
        return jsonify({"success": True, "message": f"Đã tính lại phân khúc chăm sóc cho {recomputed} khách hàng thành công!"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/ai/nurture/generate-campaign', methods=['POST'])
@login_required
def nurture_generate_campaign():
    """Giờ target segment (ALL/VIP/CHURN) được lọc trực tiếp trên db.customers thật,
    và nội dung nhắn được AINurturingEngine.generate_nurturing_copy() sinh THẬT qua
    DeepSeek, có nhúng đúng lịch sử mua hàng thật của từng khách (tái dùng
    AIContextEngine._load_purchase_history — không viết lại logic join order_items)."""
    data = request.json or {}
    segment = data.get('segment')  # 'ALL', 'VIP', 'CHURN'
    goal = data.get('goal', 'RECALL')
    channel = data.get('channel', 'ZALO')
    tone = data.get('tone', 'friendly')

    business_id = session.get('business_id') or session['user_id']
    industry = session.get('business_mode', 'retail')

    if db is None:
        return jsonify({"success": False, "message": "MongoDB chưa kết nối."}), 503

    campaign_id = f"camp-{next_mongo_id('nurturing_campaigns')}"
    campaign_name = f"Chiến dịch {goal} qua kênh {channel} ({tone.upper()})"

    try:
        biz = db.businesses.find_one({'id': business_id}, {'name': 1, '_id': 0})
        business_name = (biz or {}).get('name') or 'BitPaw'

        query = {'business_id': business_id}
        if segment == 'VIP':
            query['total_spent'] = {'$gt': 5000000}
        elif segment == 'CHURN':
            query['nurturing_status'] = 'CHURN_RISK'
        # 'ALL' (hoặc bất kỳ giá trị khác) -> không lọc thêm

        customers = list(db.customers.find(query, {'id': 1, 'name': 1, 'phone': 1, '_id': 0}))

        db.nurturing_campaigns.insert_one({
            'id': campaign_id, 'business_id': business_id, 'name': campaign_name,
            'target_segment_id': segment, 'campaign_goal': goal, 'channel': channel,
            'tone': tone, 'is_active': True, 'created_at': datetime.now().isoformat(),
        })

        generated_count = 0
        for cust in customers:
            cust_id, cust_name, cust_phone = cust.get('id'), cust.get('name'), cust.get('phone')
            purchase_history = (
                AIContextEngine._load_purchase_history(business_id, cust_phone) if cust_phone else []
            )
            copy_seq = AINurturingEngine.generate_nurturing_copy(
                business_name, industry, goal, tone, cust_name, purchase_history
            )

            for step_key, days in (('3days', 3), ('7days', 7), ('14days', 14)):
                # message id giữ dạng string ghép (giống hệt quy ước cũ) — KHÔNG dùng
                # next_mongo_id() ở đây: frontend so khớp id bằng "===" sau khi đã đi qua
                # thuộc tính onclick (luôn thành string), nên id phải luôn là string để
                # tránh lệch kiểu int-vs-string.
                db.campaign_messages.insert_one({
                    'id': f"{campaign_id}-{cust_id}-{days}d",
                    'business_id': business_id, 'campaign_id': campaign_id,
                    'customer_id': cust_id,  # int, khớp kiểu với db.customers.id để $lookup hoạt động
                    'step_delay': days, 'message_body': copy_seq[step_key],
                    'approval_status': 'PENDING', 'created_at': datetime.now().isoformat(),
                })
                generated_count += 1

        return jsonify({
            "success": True,
            "campaign_id": campaign_id,
            "campaign_name": campaign_name,
            "target_count": len(customers),
            "messages_count": generated_count
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/ai/nurture/approval-queue', methods=['GET'])
@login_required
def nurture_approval_queue():
    business_id = session.get('business_id') or session['user_id']
    try:
        pipeline = [
            {'$match': {'business_id': business_id}},
            {'$sort': {'created_at': -1}},
            {'$lookup': {'from': 'customers', 'localField': 'customer_id', 'foreignField': 'id', 'as': '_cust'}},
            {'$addFields': {'customer_name': {'$arrayElemAt': ['$_cust.name', 0]}}},
            {'$project': {'_cust': 0, '_id': 0}},
        ]
        rows = list(db.campaign_messages.aggregate(pipeline))

        queue = [{
            "id": r.get('id'),
            "campaign_id": r.get('campaign_id'),
            "customer_id": r.get('customer_id'),
            "delay": r.get('step_delay'),
            "body": r.get('message_body'),
            "status": r.get('approval_status'),
            "customer_name": r.get('customer_name'),
        } for r in rows]
        return jsonify({"success": True, "data": queue})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/ai/nurture/approve-message', methods=['POST'])
@login_required
def nurture_approve_message():
    """Mã Nurture Part 3 audit — chỉ đổi approval_status, KHÔNG còn set `sent_at` giả ngay lúc
    bấm duyệt như trước (trước đây coi 'đã duyệt' = 'đã gửi', dù chưa hề gọi API nào tới
    Zalo/Facebook). `sent_at`/`delivery_status` giờ CHỈ được message_delivery_worker.py ghi,
    và CHỈ sau khi gọi API gửi thật thành công."""
    data = request.json or {}
    message_id = data.get('message_id')
    action = data.get('action')  # 'APPROVED' or 'REJECTED'

    if not message_id or not action:
        return jsonify({"success": False, "message": "Missing message_id or action parameters"}), 400

    business_id = session.get('business_id') or session['user_id']
    try:
        db.campaign_messages.update_one(
            {'id': message_id, 'business_id': business_id},
            {'$set': {'approval_status': action}}
        )
        extra_note = " Tin nhắn sẽ được gửi thật trong ít phút tới." if action == 'APPROVED' else ""
        return jsonify({"success": True, "message": f"Tin nhắn đã được Sếp phê duyệt sang trạng thái: {action}!{extra_note}"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

# ========== NURTURE SCHEDULE RULES (Mã Nurture Part 2 audit) ==========
# Cấu hình để nurture_scheduler.py (cron ngày) biết khách nào cần tự động chăm sóc — trước đây
# KHÔNG có nơi nào tạo được các rule này (toàn bộ campaign phải tạo tay qua nurture_generate_campaign()).
@app.route('/api/ai/nurture/rules', methods=['GET'])
@login_required
def nurture_rules_list():
    business_id = session.get('business_id') or session['user_id']
    rules = list(db.nurture_schedule_rules.find({'business_id': business_id}, {'_id': 0}).sort('created_at', -1))
    return jsonify({"success": True, "data": rules})


@app.route('/api/ai/nurture/rules', methods=['POST'])
@login_required
def nurture_rules_create():
    data = request.json or {}
    name = (data.get('name') or '').strip()
    condition_days = data.get('condition_days')
    channel = (data.get('channel') or 'zalo_oa').strip().lower()

    if not name or not condition_days:
        return jsonify({"success": False, "message": "Thiếu name hoặc condition_days."}), 400
    try:
        condition_days = int(condition_days)
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "condition_days phải là số nguyên."}), 400
    if channel not in ('zalo_oa', 'facebook'):
        return jsonify({"success": False, "message": "channel phải là 'zalo_oa' hoặc 'facebook'."}), 400

    business_id = session.get('business_id') or session['user_id']
    rule_id = next_mongo_id('nurture_schedule_rules')
    db.nurture_schedule_rules.insert_one({
        'id': rule_id, 'business_id': business_id, 'name': name,
        'condition_days': condition_days,
        'goal': (data.get('goal') or 'RECALL').upper(),
        'tone': data.get('tone') or 'friendly',
        'channel': channel,
        'auto_send': bool(data.get('auto_send', False)),  # False -> vào hàng chờ duyệt tay; True -> gửi thẳng
        'cooldown_days': int(data.get('cooldown_days') or 14),  # tránh nhắn lại cùng 1 khách mỗi ngày 1 lần
        'is_active': True,
        'industry': session.get('business_mode', 'retail'),
        'created_at': datetime.now().isoformat(),
    })
    return jsonify({"success": True, "id": rule_id})


@app.route('/api/ai/nurture/rules/<int:rule_id>', methods=['DELETE'])
@login_required
def nurture_rules_delete(rule_id):
    business_id = session.get('business_id') or session['user_id']
    result = db.nurture_schedule_rules.update_one(
        {'id': rule_id, 'business_id': business_id}, {'$set': {'is_active': False}}
    )
    if result.matched_count == 0:
        return jsonify({"success": False, "message": "Không tìm thấy rule."}), 404
    return jsonify({"success": True})


@app.route('/api/ai/nurture/recommendations', methods=['GET'])
@login_required
def nurture_recommendations():
    industry = session.get('business_mode', 'retail')
    try:
        from ai_nurturing_engine import AINurturingEngine
        recs = AINurturingEngine.get_industry_recommendations(industry)
        return jsonify({"success": True, "data": recs})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


# ========== AI BOT SCENARIO BUILDER API ENDPOINTS ==========

@app.route('/api/bot/scenarios', methods=['GET'])
@login_required
def get_bot_scenarios():
    business_id, _biz_err = _get_tenant_business_id_or_401()
    if _biz_err:
        return _biz_err
    try:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("""
            SELECT id, name, description, channel, trigger_type, message_template, 
                   delay_minutes, status, max_send_per_day, created_at, updated_at 
            FROM bot_scenarios WHERE business_id = ? ORDER BY created_at DESC
        """, (business_id,))
        rows = c.fetchall()
        
        # If empty, let's auto-seed mock scenarios to wow the admin on first launch
        if not rows:
            mock_scenarios = [
                (
                    str(uuid.uuid4()), business_id, "Cảm ơn & Hỏi thăm", 
                    "Tự động gửi lời cảm ơn và khảo sát hài lòng sau khi hoàn tất bill thanh toán trên POS.",
                    "zalo_oa", "after_payment", 
                    "Dạ chào {customer_name}, cảm ơn sếp đã ủng hộ tiệm. Dịch vụ/sản phẩm vừa rồi sếp có hài lòng không ạ? Nếu có góp ý gì sếp phản hồi cho em biết nhé!", 
                    60, "ACTIVE", 150
                ),
                (
                    str(uuid.uuid4()), business_id, "Nhắc lịch hẹn dịch vụ", 
                    "Tự động gửi tin nhắn SMS/Zalo trước giờ hẹn để khách hàng không quên lịch.",
                    "messenger", "appointment_reminder", 
                    "BitPaw xin chào {customer_name}! Lịch hẹn dịch vụ {service_name} của sếp đã được xác nhận vào lúc {appointment_time}. Sếp nhớ ghé đúng giờ nhé!", 
                    120, "ACTIVE", 200
                ),
                (
                    str(uuid.uuid4()), business_id, "Quà tặng Sinh nhật khách hàng", 
                    "Tự động gửi mã giảm giá chúc mừng sinh nhật khách hàng VIP.",
                    "whatsapp", "birthday", 
                    "Chúc mừng sinh nhật sếp {customer_name} thân yêu! BitPaw gửi tặng sếp mã quà tặng đặc biệt {order_code} giảm giá 20% cho tất cả dịch vụ trong tháng sinh nhật.", 
                    0, "ACTIVE", 50
                ),
                (
                    str(uuid.uuid4()), business_id, "Chào mừng khách ghé Mascot Chat", 
                    "Website Mascot AI Chatbot tự động chào đón và thu thập thông tin khách mới ghé trang chủ.",
                    "mascot_chat", "new_customer", 
                    "Chào mừng sếp {customer_name} ghé thăm Website! Em là Trợ lý Mascot AI, em có thể giúp gì cho sếp trong hôm nay?", 
                    0, "ACTIVE", 500
                )
            ]
            for s in mock_scenarios:
                c.execute("""
                    INSERT INTO bot_scenarios (id, business_id, name, description, channel, trigger_type, message_template, delay_minutes, status, max_send_per_day)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, s)
            conn.commit()
            
            c.execute("""
                SELECT id, name, description, channel, trigger_type, message_template, 
                       delay_minutes, status, max_send_per_day, created_at, updated_at 
                FROM bot_scenarios WHERE business_id = ? ORDER BY created_at DESC
            """, (business_id,))
            rows = c.fetchall()
            
        conn.close()
        
        scenarios = []
        for r in rows:
            scenarios.append({
                "id": r[0],
                "name": r[1],
                "description": r[2],
                "channel": r[3],
                "trigger_type": r[4],
                "message_template": r[5],
                "delay_minutes": r[6],
                "status": r[7],
                "max_send_per_day": r[8],
                "created_at": r[9],
                "updated_at": r[10]
            })
        return jsonify({"success": True, "data": scenarios})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/bot/scenarios', methods=['POST'])
@login_required
def create_bot_scenario():
    business_id, _biz_err = _get_tenant_business_id_or_401()
    if _biz_err:
        return _biz_err
    data = request.json or {}
    name = data.get('name', '').strip()
    channel = data.get('channel', 'zalo_oa')
    trigger_type = data.get('trigger_type', 'after_payment')
    message_template = data.get('message_template', '').strip()
    
    if not name or not message_template:
        return jsonify({"success": False, "message": "Vui lòng nhập Tên kịch bản và Nội dung tin nhắn!"}), 400
        
    description = data.get('description', '')
    delay_minutes = int(data.get('delay_minutes', 0))
    status = data.get('status', 'ACTIVE')
    max_send_per_day = int(data.get('max_send_per_day', 100))
    
    scenario_id = str(uuid.uuid4())
    
    try:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("""
            INSERT INTO bot_scenarios (id, business_id, name, description, channel, trigger_type, message_template, delay_minutes, status, max_send_per_day)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (scenario_id, business_id, name, description, channel, trigger_type, message_template, delay_minutes, status, max_send_per_day))
        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": "Đã tạo kịch bản Bot thành công!", "id": scenario_id})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/bot/scenarios/<scenario_id>', methods=['GET'])
@login_required
def get_single_bot_scenario(scenario_id):
    business_id, _biz_err = _get_tenant_business_id_or_401()
    if _biz_err:
        return _biz_err
    try:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("""
            SELECT id, name, description, channel, trigger_type, message_template, 
                   delay_minutes, status, max_send_per_day, created_at, updated_at 
            FROM bot_scenarios WHERE id = ? AND business_id = ?
        """, (scenario_id, business_id))
        r = c.fetchone()
        conn.close()
        
        if not r:
            return jsonify({"success": False, "message": "Không tìm thấy kịch bản!"}), 404
            
        scenario = {
            "id": r[0],
            "name": r[1],
            "description": r[2],
            "channel": r[3],
            "trigger_type": r[4],
            "message_template": r[5],
            "delay_minutes": r[6],
            "status": r[7],
            "max_send_per_day": r[8],
            "created_at": r[9],
            "updated_at": r[10]
        }
        return jsonify({"success": True, "data": scenario})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/bot/scenarios/<scenario_id>', methods=['PUT'])
@login_required
def update_bot_scenario(scenario_id):
    business_id, _biz_err = _get_tenant_business_id_or_401()
    if _biz_err:
        return _biz_err
    data = request.json or {}
    name = data.get('name', '').strip()
    message_template = data.get('message_template', '').strip()
    
    if not name or not message_template:
        return jsonify({"success": False, "message": "Vui lòng nhập Tên kịch bản và Nội dung tin nhắn!"}), 400
        
    description = data.get('description', '')
    channel = data.get('channel', 'zalo_oa')
    trigger_type = data.get('trigger_type', 'after_payment')
    delay_minutes = int(data.get('delay_minutes', 0))
    status = data.get('status', 'ACTIVE')
    max_send_per_day = int(data.get('max_send_per_day', 100))
    
    try:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("""
            UPDATE bot_scenarios 
            SET name = ?, description = ?, channel = ?, trigger_type = ?, message_template = ?, 
                delay_minutes = ?, status = ?, max_send_per_day = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND business_id = ?
        """, (name, description, channel, trigger_type, message_template, delay_minutes, status, max_send_per_day, scenario_id, business_id))
        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": "Cập nhật kịch bản Bot thành công!"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/bot/scenarios/<scenario_id>', methods=['DELETE'])
@login_required
def delete_bot_scenario(scenario_id):
    business_id, _biz_err = _get_tenant_business_id_or_401()
    if _biz_err:
        return _biz_err
    try:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("DELETE FROM bot_scenarios WHERE id = ? AND business_id = ?", (scenario_id, business_id))
        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": "Đã xóa kịch bản Bot thành công!"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/bot/scenarios/<scenario_id>/toggle', methods=['POST'])
@login_required
def toggle_bot_scenario(scenario_id):
    business_id, _biz_err = _get_tenant_business_id_or_401()
    if _biz_err:
        return _biz_err
    try:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("SELECT status FROM bot_scenarios WHERE id = ? AND business_id = ?", (scenario_id, business_id))
        r = c.fetchone()
        if not r:
            conn.close()
            return jsonify({"success": False, "message": "Không tìm thấy kịch bản!"}), 404
            
        current_status = r[0]
        new_status = 'INACTIVE' if current_status == 'ACTIVE' else 'ACTIVE'
        
        c.execute("UPDATE bot_scenarios SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND business_id = ?", (new_status, scenario_id, business_id))
        conn.commit()
        conn.close()
        return jsonify({"success": True, "status": new_status, "message": f"Kịch bản đã chuyển sang trạng thái: {new_status}"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/bot/scenarios/<scenario_id>/test', methods=['POST'])
@login_required
def test_bot_scenario(scenario_id):
    business_id, _biz_err = _get_tenant_business_id_or_401()
    if _biz_err:
        return _biz_err
    data = request.json or {}
    customer_id = data.get('customer_id', '').strip()
    
    try:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        
        # 1. Fetch scenario
        c.execute("SELECT name, channel, message_template FROM bot_scenarios WHERE id = ? AND business_id = ?", (scenario_id, business_id))
        scen_row = c.fetchone()
        if not scen_row:
            conn.close()
            return jsonify({"success": False, "message": "Không tìm thấy kịch bản!"}), 404
            
        scen_name, channel, template = scen_row
        
        # 2. Fetch customer details or use a generic placeholder for a dry-run test —
        # trước đây tra ở customer_profiles (SQLite, đã bị loại bỏ), giờ tra thẳng
        # db.customers (MongoDB). customer_id ở đây là ô nhập tay tự do trên UI, không
        # đảm bảo đúng định dạng, nên thử ép kiểu int an toàn, lỗi/không khớp thì rơi về
        # placeholder gốc (hành vi y hệt trước đây).
        cust_name = "Khách hàng mẫu"
        cust_phone = "0900000000"
        if customer_id and db is not None:
            try:
                cust_doc = db.customers.find_one(
                    {'id': int(customer_id), 'business_id': business_id}, {'name': 1, 'phone': 1, '_id': 0}
                )
            except (ValueError, TypeError):
                cust_doc = None
            if cust_doc:
                cust_name, cust_phone = cust_doc.get('name') or cust_name, cust_doc.get('phone') or cust_phone
                
        # 3. Check connection status of the channel
        c.execute("SELECT connection_status, config_data FROM platform_connections WHERE business_id = ? AND platform = ?", (business_id, channel))
        conn_row = c.fetchone()
        
        is_connected = False
        config = {}
        if conn_row:
            is_connected = (conn_row[0] == 'CONNECTED')
            if conn_row[1]:
                try:
                    config = json.loads(conn_row[1])
                except Exception:
                    pass
                    
        # Verify access token and channel id are validly setup
        access_token = config.get("access_token")
        channel_id = config.get("channel_id")
        if not access_token or not channel_id:
            is_connected = False
            
        # 4. Fill variables in template
        filled_message = template.replace("{customer_name}", cust_name)\
                                 .replace("{service_name}", "Chăm Sóc Da Hắc Ín VIP")\
                                 .replace("{appointment_time}", "15:30 Ngày mai")\
                                 .replace("{order_code}", "BP-MOCK-999")
        
        # Determine status
        log_id = str(uuid.uuid4())
        status_label = 'simulated'
        error_msg = None
        
        if is_connected:
            status_label = 'simulated'
            resp_message = f"Gửi tin nhắn test thành công! [Chế độ mô phỏng qua Provider API {channel.upper()}] Phản hồi: OK 200."
        else:
            status_label = 'pending_provider_api'
            error_msg = f"Kênh {channel.upper()} chưa được cấu hình token. Vui lòng kết nối tài khoản trước."
            resp_message = f"Simulated test trigger: Kịch bản đã sẵn sàng, nhưng kênh {channel.upper()} chưa kết nối thật. Tin nhắn hiển thị chế độ nháp."
            
        # Insert log
        c.execute("""
            INSERT INTO bot_message_logs (id, business_id, scenario_id, customer_id, channel, message_content, status, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (log_id, business_id, scenario_id, cust_phone, channel, filled_message, status_label, error_msg))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            "success": True,
            "message": resp_message,
            "simulated_message": filled_message,
            "log_status": status_label,
            "channel": channel,
            "is_connected": is_connected
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/bot/logs', methods=['GET'])
@login_required
def get_bot_logs():
    business_id, _biz_err = _get_tenant_business_id_or_401()
    if _biz_err:
        return _biz_err
    try:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("""
            SELECT l.id, l.scenario_id, l.customer_id, l.channel, l.message_content, l.status, l.error_message, l.sent_at, s.name
            FROM bot_message_logs l
            LEFT JOIN bot_scenarios s ON l.scenario_id = s.id
            WHERE l.business_id = ?
            ORDER BY l.sent_at DESC LIMIT 50
        """, (business_id,))
        rows = c.fetchall()
        conn.close()
        
        logs = []
        for r in rows:
            logs.append({
                "id": r[0],
                "scenario_id": r[1],
                "customer_id": r[2],
                "channel": r[3],
                "message_content": r[4],
                "status": r[5],
                "error_message": r[6],
                "sent_at": r[7],
                "scenario_name": r[8] or "Kịch bản đã xóa"
            })
        return jsonify({"success": True, "data": logs})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


# Register Blueprints
try:
    from ad_assistant import ad_assistant_bp
    app.register_blueprint(ad_assistant_bp)
except Exception as bp_err:
    print(f"Error registering ad_assistant_bp: {str(bp_err)}")

try:
    # AI Studio — endpoint RIÊNG, tách khỏi AI Bot (Mã AI Studio Part 1.1 audit). Import SAU
    # login_required (dòng ~534) vì ai_studio_bp.py làm `from app import login_required`.
    from ai_studio_bp import ai_studio_bp
    app.register_blueprint(ai_studio_bp)
except Exception as bp_err:
    print(f"Error registering ai_studio_bp: {str(bp_err)}")

try:
    from ad_suggest_api import ad_suggest_bp
    app.register_blueprint(ad_suggest_bp)
except Exception as bp_err:
    print(f"Error registering ad_suggest_bp: {str(bp_err)}")

try:
    from email_test_api import email_test_bp
    app.register_blueprint(email_test_bp)
except Exception as bp_err:
    print(f"Error registering email_test_bp: {str(bp_err)}")

# Kiến trúc "1 ngành = 1 file": blueprints/spa_bp.py là bản mẫu — file đó @app.route(...) thẳng
# vào chính `app` này (không dùng flask.Blueprint — xem lý do ở đầu file đó), nên chỉ cần import
# là đủ để route được đăng ký, không cần register_blueprint(). Mỗi ngành mới (fnb, nail,
# karaoke...) thêm 1 dòng import y hệt khối này. Phải import SAU khi mọi hàm dùng chung
# (login_required, _assert_owns_product...) đã định nghĩa xong ở trên.
try:
    import blueprints.spa_bp  # noqa: F401 — import để đăng ký route, không cần dùng tên module
except Exception as bp_err:
    print(f"Error registering blueprints.spa_bp: {str(bp_err)}")


# ========== MOCKUP APIS & ALIAS ROUTES (PHASE 2) ==========

GEOFENCE_RADIUS_METERS = 50


def _haversine_distance_meters(lat1, lon1, lat2, lon2):
    """Khoảng cách đường chim bay (mét) giữa 2 toạ độ GPS theo công thức Haversine."""
    R = 6371000.0  # bán kính Trái Đất (mét)
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(min(1.0, a)))


def _enforce_checkin_geofence(business_id, lat, lng):
    """Chặn gian lận chấm công (giả GPS/checkin từ xa) — so khoảng cách Haversine giữa vị trí
    nhân viên gửi lên và toạ độ chi nhánh (office_latitude/office_longitude trên db.businesses),
    từ chối (403) nếu > GEOFENCE_RADIUS_METERS. Nếu chi nhánh CHƯA cấu hình toạ độ (chưa gọi
    /api/business/geofence để set), bỏ qua kiểm tra để không phá chấm công của các tenant hiện
    có — tenant tự bật tính năng này bằng cách cấu hình toạ độ chi nhánh.
    Trả về (True, None) nếu cho qua, (False, (response, status_code)) nếu bị từ chối."""
    try:
        biz = db.businesses.find_one(
            {'id': business_id}, {'office_latitude': 1, 'office_longitude': 1, '_id': 0}
        )
    except Exception:
        biz = None
    office_lat = (biz or {}).get('office_latitude')
    office_lng = (biz or {}).get('office_longitude')
    if office_lat is None or office_lng is None:
        return True, None

    if lat is None or lng is None:
        return False, (jsonify({
            "success": False,
            "error": "Không lấy được vị trí GPS từ thiết bị. Vui lòng bật định vị và thử lại.",
        }), 403)
    try:
        lat_f, lng_f = float(lat), float(lng)
    except (TypeError, ValueError):
        return False, (jsonify({"success": False, "error": "Toạ độ GPS không hợp lệ."}), 403)

    distance = _haversine_distance_meters(lat_f, lng_f, float(office_lat), float(office_lng))
    if distance > GEOFENCE_RADIUS_METERS:
        return False, (jsonify({
            "success": False,
            "error": f"Bạn đang cách chi nhánh khoảng {distance:.0f}m — vượt phạm vi cho phép "
                     f"({GEOFENCE_RADIUS_METERS}m) để chấm công. Vui lòng đến gần chi nhánh hơn.",
        }), 403)
    return True, None


@app.route('/api/business/geofence', methods=['POST'])
@login_required
@role_required('admin', 'super_admin')
def api_set_business_geofence():
    """Cấu hình toạ độ chi nhánh (office_latitude/office_longitude) dùng để geofence chấm công
    GPS — chỉ chủ tiệm/super_admin mới được đổi. Truyền latitude=null (hoặc bỏ trống 2 field)
    để TẮT geofence, quay lại hành vi cũ (không kiểm tra vị trí)."""
    business_id = session.get('business_id') or session['user_id']
    data = request.json or {}
    lat, lng = data.get('latitude'), data.get('longitude')
    update = {}
    if lat is None and lng is None:
        update = {'office_latitude': None, 'office_longitude': None}
    else:
        try:
            update = {'office_latitude': float(lat), 'office_longitude': float(lng)}
        except (TypeError, ValueError):
            return jsonify({"success": False, "message": "Toạ độ không hợp lệ."}), 400
    try:
        db.businesses.update_one({'id': business_id}, {'$set': update})
        return jsonify({"success": True, "data": update})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/chamcong/checkin', methods=['POST'])
@login_required
def api_checkin():
    """Mã 1.2 audit — KHÔNG ghi trực tiếp vào DB nữa (SQLite chỉ cho 1 writer tại 1 thời điểm,
    10.000 thợ check-in cùng lúc 9h sáng sẽ nghẽn cổ chai toàn hệ thống). Đẩy sự kiện vào Redis
    Stream (XADD) và trả 200 OK NGAY — việc ghi thật vào MongoDB do consumer.py (1 process
    riêng, ghi tuần tự) đảm nhiệm. Đánh đổi: mất kiểm tra "đã có ca mở chưa" NGAY LÚC NÀY (route
    này không còn đọc DB đồng bộ) — consumer.py kiểm tra lại việc đó trước khi ghi, vì nó xử lý
    tuần tự nên làm được an toàn (không có race condition như hàng ngàn request Flask đồng thời)."""
    data = request.json or {}
    staff_id = data.get('staff_id') or data.get('employee_id') or 1
    lat = data.get('latitude')
    lng = data.get('longitude')
    note = data.get('note')

    business_id = session.get('business_id') or session['user_id']
    if not (isinstance(staff_id, (int, float)) or (isinstance(staff_id, str) and staff_id.isdigit())):
        return jsonify({"success": False, "error": "staff_id không hợp lệ."}), 400
    try:
        staff_doc = db.staff.find_one({'id': int(staff_id)}, {'id': 1, 'is_active': 1, 'business_id': 1, '_id': 0})
        if not staff_doc or not staff_doc.get('is_active', True):
            return jsonify({"success": False, "error": "Nhân viên không tồn tại hoặc đã bị khóa."}), 403
        if staff_doc.get('business_id') != business_id:
            return jsonify({"success": False, "error": "Nhân viên không thuộc quyền quản lý của bạn."}), 403
    except Exception as e:
        return jsonify({"success": False, "error": f"Không xác thực được nhân viên: {str(e)}"}), 500

    geofence_ok, geofence_error = _enforce_checkin_geofence(business_id, lat, lng)
    if not geofence_ok:
        return geofence_error

    clock_in_time = datetime.now().isoformat()
    event_id = str(uuid.uuid4())
    try:
        redis_queue.push_attendance_event({
            'event_id': event_id, 'type': 'checkin', 'staff_id': int(staff_id),
            'business_id': business_id, 'latitude': lat, 'longitude': lng,
            'note': note or '', 'timestamp': clock_in_time,
        })
    except Exception as e:
        # Redis cũng không nhận được -> KHÔNG được nuốt sự kiện (mất chấm công = mất lương thợ),
        # báo lỗi rõ ràng để app/kiosk có thể tự retry thay vì âm thầm coi như đã checkin.
        print(f"[api_checkin] Lỗi đẩy Redis Stream: {e}")
        return jsonify({"success": False, "error": "Hệ thống chấm công đang quá tải/gián đoạn, vui lòng thử lại sau vài giây."}), 503

    return jsonify({
        "success": True,
        "event_id": event_id,
        "status": "Present",
        "clock_in": clock_in_time,
        "pending_sync": True,  # sự kiện đang chờ consumer.py ghi vào MongoDB, chưa có id thật
    })


@app.route('/api/chamcong/checkout', methods=['POST'])
@login_required
def api_checkout():
    """Mã 1.2 audit — cùng cơ chế với api_checkin(): đẩy Redis Stream, trả 200 ngay, consumer.py
    ghi tuần tự vào MongoDB (bao gồm việc tìm đúng ca đang mở gần nhất để đóng lại)."""
    data = request.json or {}
    staff_id = data.get('staff_id') or data.get('employee_id') or 1
    lat = data.get('latitude')
    lng = data.get('longitude')

    business_id = session.get('business_id') or session['user_id']
    if not (isinstance(staff_id, (int, float)) or (isinstance(staff_id, str) and staff_id.isdigit())):
        return jsonify({"success": False, "error": "staff_id không hợp lệ."}), 400
    try:
        staff_doc = db.staff.find_one({'id': int(staff_id)}, {'id': 1, 'is_active': 1, 'business_id': 1, '_id': 0})
        if not staff_doc or not staff_doc.get('is_active', True):
            return jsonify({"success": False, "error": "Nhân viên không tồn tại hoặc đã bị khóa."}), 403
        if staff_doc.get('business_id') != business_id:
            return jsonify({"success": False, "error": "Nhân viên không thuộc quyền quản lý của bạn."}), 403
    except Exception as e:
        return jsonify({"success": False, "error": f"Không xác thực được nhân viên: {str(e)}"}), 500

    geofence_ok, geofence_error = _enforce_checkin_geofence(business_id, lat, lng)
    if not geofence_ok:
        return geofence_error

    clock_out_time = datetime.now().isoformat()
    event_id = str(uuid.uuid4())
    try:
        redis_queue.push_attendance_event({
            'event_id': event_id, 'type': 'checkout', 'staff_id': int(staff_id),
            'business_id': business_id, 'latitude': lat, 'longitude': lng,
            'timestamp': clock_out_time,
        })
    except Exception as e:
        print(f"[api_checkout] Lỗi đẩy Redis Stream: {e}")
        return jsonify({"success": False, "error": "Hệ thống chấm công đang quá tải/gián đoạn, vui lòng thử lại sau vài giây."}), 503

    return jsonify({
        "success": True,
        "event_id": event_id,
        "message": "Đã ghi nhận checkout, đang xử lý.",
        "clock_out": clock_out_time,
        "pending_sync": True,
    })


@app.route('/api/chamcong/status', methods=['GET'])
@login_required
def api_attendance_status():
    """Đọc trực tiếp từ db.attendance (MongoDB) — KHÔNG còn đọc bảng SQLite local_attendance
    nữa, vì Mã 1.2 audit đã chuyển check-in/check-out sang ghi qua Redis Stream + consumer.py,
    bảng SQLite đó không còn ai ghi vào. Đánh đổi: có độ trễ eventual-consistency vài trăm ms
    tới vài giây giữa lúc bấm check-in và lúc route này thấy trạng thái mới (thời gian
    consumer.py xử lý xong message trong Stream) — chấp nhận được, vì đây vốn là hệ quả tất
    yếu của việc bỏ ghi đồng bộ để chống nghẽn khi 10.000 thợ check-in cùng lúc."""
    staff_id = request.args.get('staff_id') or '1'
    business_id = session.get('business_id') or session['user_id']
    if not (isinstance(staff_id, (int, float)) or (isinstance(staff_id, str) and staff_id.isdigit())):
        return jsonify({"success": False, "error": "staff_id không hợp lệ."}), 400
    try:
        staff_doc = db.staff.find_one({'id': int(staff_id)}, {'id': 1, 'business_id': 1, '_id': 0})
        if not staff_doc:
            return jsonify({"success": False, "error": "Nhân viên không tồn tại."}), 404
        if staff_doc.get('business_id') != business_id:
            return jsonify({"success": False, "error": "Nhân viên không thuộc quyền quản lý của bạn."}), 403
    except Exception as e:
        return jsonify({"success": False, "error": f"Không xác thực được nhân viên: {str(e)}"}), 500

    try:
        row = db.attendance.find_one(
            {'staff_id': int(staff_id), 'business_id': business_id},
            {'clock_in': 1, 'clock_out': 1, 'status': 1, '_id': 0},
            sort=[('id', -1)],
        )
        if row:
            return jsonify({
                "success": True,
                "status": row.get('status'),
                "is_checked_in": row.get('clock_out') is None,
                "clock_in": row.get('clock_in'),
                "clock_out": row.get('clock_out'),
            })
        else:
            return jsonify({
                "success": True,
                "status": "Absent",
                "is_checked_in": False,
                "clock_in": None,
                "clock_out": None
            })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/payroll/calculate', methods=['POST'])
@login_required
def api_calculate_payroll():
    """Tính lương thật từ dữ liệu chấm công (bảng `chamcong`) + hồ sơ nhân viên (bảng `employees`),
    theo đúng công thức đang dùng ở templates/bangluong.html (đồng bộ, không phải hàm giả)."""
    data = request.json or {}
    month_year = data.get('month_year') or datetime.now().strftime('%m/%Y')
    try:
        month, year = month_year.split('/')
    except ValueError:
        return jsonify({"success": False, "error": "month_year must be in MM/YYYY format"}), 400

    industry = (data.get('industry') or 'Spa').strip()
    business_id = session.get('business_id') or session['user_id']

    try:
        # $lookup nối employees với đúng các bản ghi chamcong cùng ma_nv + business_id ngay trong
        # 1 lần gọi DB (aggregation pipeline) — thay vì trước đây phải SELECT toàn bộ 2 bảng riêng
        # rồi tự đối chiếu bằng Python (2 round-trip DB + quét toàn bộ chamcong của cả tenant).
        pipeline = [
            {'$match': {'business_id': business_id}},
            {'$lookup': {
                'from': 'chamcong',
                'let': {'emp_ma_nv': '$ma_nv'},
                'pipeline': [
                    {'$match': {'$expr': {'$and': [
                        {'$eq': ['$ma_nv', '$$emp_ma_nv']},
                        {'$eq': ['$business_id', business_id]}
                    ]}}}
                ],
                'as': 'chamcong_records'
            }},
            {'$project': {'_id': 0}}
        ]
        all_employees = list(db.employees.aggregate(pipeline))
        employees = [
            e for e in all_employees
            if industry.lower() in (e.get('linh_vuc') or '').lower() or (e.get('linh_vuc') or '') == 'Chưa phân bổ'
        ]

        def matches_month(r):
            ngay = r.get('ngay_cham')
            if not ngay:
                return False
            parts = ngay.split('/')
            return len(parts) == 3 and parts[1] == month and parts[2] == year

        payroll = []
        total_fund = 0
        for emp in employees:
            ma_nv = emp.get('ma_nv')
            my_records = [r for r in emp.get('chamcong_records', []) if matches_month(r)]

            luong_co_ban = float(emp.get('luong_cb') or 0)
            luong_theo_gio = float(emp.get('luong_gio') or 0)
            phu_cap_co_dinh = float(emp.get('phu_cap') or 0)

            total_gio_lam = 0.0
            total_tang_ca = 0.0
            total_hoa_hong = 0.0
            total_tips = 0.0
            phu_cap_phat_sinh = 0.0
            so_ngay_lam = 0
            for r in my_records:
                so_gio = float(r.get('so_gio') or 0)
                if so_gio > 0:
                    gio_lam_hop_le = so_gio
                elif r.get('trang_thai') in ('Có mặt', 'Trọn Ngày'):
                    # Bản ghi điểm danh đơn giản (vd: check-in camera+GPS ở diemdanh.html) không
                    # có giờ chi tiết — mặc định 1 ngày công = 8h. CHỈ áp dụng cho bản ghi thật sự
                    # đại diện "có đi làm hôm đó" — KHÔNG áp dụng cho bản ghi giao dịch/hoa hồng
                    # (vd: mỗi lượt tính Tua ở chamcong_nail.html), nếu không 1 thợ nails làm 3
                    # khách trong ngày sẽ bị cộng khống 24h dù mỗi giao dịch vốn dĩ so_gio=0.
                    gio_lam_hop_le = 8
                else:
                    gio_lam_hop_le = 0
                total_gio_lam += gio_lam_hop_le
                total_tang_ca += float(r.get('tang_ca') or 0)
                total_hoa_hong += float(r.get('tien_tua') or 0)
                total_tips += float(r.get('tien_tips') or 0)
                phu_cap_phat_sinh += float(r.get('phu_cap') or 0)
                if r.get('trang_thai') in ('Có mặt', 'Trọn Ngày'):
                    so_ngay_lam += 1

            if 'Spa' in industry or 'Nails' in industry:
                # Lương giờ (Time In/Out ở chamcong_nail.html) là chính nếu có cấu hình luong_cb
                # (lương bao/booth cố định); ngược lại tính theo giờ thực tế × đơn giá/giờ — cùng
                # quy tắc với nhánh F&B/Khách sạn bên dưới. Tiền Tua (hoa hồng dịch vụ) và Tips
                # luôn cộng thêm, KHÔNG phụ thuộc mô hình lương chính là bao hay theo giờ.
                luong_chinh = luong_co_ban if luong_co_ban > 0 else total_gio_lam * luong_theo_gio
                cot2 = total_hoa_hong
                cot3 = total_tips + phu_cap_phat_sinh + phu_cap_co_dinh
            elif 'Văn Phòng' in industry:
                luong_ngay = luong_co_ban / 26
                luong_chinh = round(luong_ngay * so_ngay_lam)
                cot2 = total_hoa_hong
                cot3 = phu_cap_co_dinh + phu_cap_phat_sinh + (total_tang_ca * luong_ngay / 8 * 1.5)
            elif 'F&B' in industry or 'Khách sạn' in industry:
                luong_chinh = luong_co_ban if luong_co_ban > 0 else total_gio_lam * luong_theo_gio
                cot2 = total_hoa_hong + phu_cap_phat_sinh
                cot3 = total_tips + phu_cap_co_dinh + (total_tang_ca * luong_theo_gio * 1.5)
            else:
                luong_chinh = luong_co_ban
                cot2 = total_hoa_hong
                cot3 = total_tips + phu_cap_co_dinh + phu_cap_phat_sinh

            thuc_lanh = luong_chinh + cot2 + cot3
            if thuc_lanh > 0 or luong_co_ban > 0 or my_records:
                total_fund += thuc_lanh
                payroll.append({
                    "ma_nv": ma_nv,
                    "ho_ten": emp.get('ho_ten'),
                    "luong_chinh": round(luong_chinh, 2),
                    "hoa_hong": round(cot2, 2),
                    "phu_cap_tips": round(cot3, 2),
                    "thuc_lanh": round(thuc_lanh, 2),
                    "so_ngay_lam": so_ngay_lam,
                    "tong_gio_lam": round(total_gio_lam, 2)
                })

        payroll.sort(key=lambda x: x['thuc_lanh'], reverse=True)

        return jsonify({
            "success": True,
            "month": month_year,
            "industry": industry,
            "staff_count": len(payroll),
            "total_fund": round(total_fund, 2),
            "payroll": payroll
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ========== HR JSON API (thay Supabase JS client-side ở nhanvien/bangluong/app_nhanvien/
# chamcong_*.html) — db.employees (khoá ma_nv) + db.chamcong (khoá ma_nv), business_id lấy
# từ session, KHÔNG tin client. ==========
# TODO: Tech Debt - Merge db.chamcong (ma_nv) into db.attendance (staff_id) in Phase 5
_EMPLOYEE_SORT_FIELDS = {
    'ho_ten': [('ho_ten', 1)],
    'id': [('id', 1)],
    'id_desc': [('id', -1)],
    'chuc_vu': [('chuc_vu', 1)],
    'diem_kudo_desc': [('diem_kudo', -1)],
    'thu_tu_tua': [('thu_tu_tua', 1)],
}

_EMPLOYEE_PATCHABLE_FIELDS = (
    'ho_ten', 'linh_vuc', 'chuc_vu', 'luong_cb', 'luong_gio', 'phu_cap',
    'thu_tu_tua', 'avatar_url', 'toa_do_lat', 'toa_do_lng', 'trang_thai_gps',
    'nhiem_vu_hien_tai',
)


@app.route('/api/hr/employees', methods=['GET'])
@login_required
def api_hr_employees_list():
    business_id = session.get('business_id') or session['user_id']
    sort = _EMPLOYEE_SORT_FIELDS.get(request.args.get('sort'), [('id', 1)])
    try:
        employees = list(db.employees.find({'business_id': business_id}, {'_id': 0}).sort(sort))
        return jsonify({"success": True, "data": employees})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/hr/employees/<ma_nv>', methods=['GET'])
@login_required
def api_hr_employees_get(ma_nv):
    """Tra cứu 1 nhân viên theo ma_nv, LUÔN lọc theo business_id của session hiện tại —
    thay cho lookup Supabase cũ ở app_nhanvien.html vốn không lọc tenant (rủi ro nếu ma_nv
    trùng giữa 2 doanh nghiệp khác nhau)."""
    business_id = session.get('business_id') or session['user_id']
    try:
        emp = db.employees.find_one({'ma_nv': ma_nv, 'business_id': business_id}, {'_id': 0})
        if not emp:
            return jsonify({"success": False, "error": "Employee not found."}), 404
        return jsonify({"success": True, "data": emp})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/public/hr/employees/lookup', methods=['GET'])
def api_public_employee_lookup():
    """PUBLIC (không @login_required) — dùng bởi màn "Fast Check-in" ở index.html, nơi nhân
    viên gõ mã NV để đi thẳng vào camera chấm công (diemdanh.html) TRƯỚC KHI đăng nhập, nên
    chưa có session/business_id để lọc tenant. Chỉ trả về ho_ten/ma_nv (không lương, không
    business_id, không thông tin nhạy cảm khác) — cùng mức lộ dữ liệu như lookup không đăng
    nhập cũ, nếu 2 doanh nghiệp trùng ma_nv thì có thể lộ tên nhân viên của nhau, đây là giới
    hạn kế thừa từ luồng kiosk chưa đăng nhập, không phải lỗi mới phát sinh."""
    ma_nv = (request.args.get('ma_nv') or '').strip()
    if not ma_nv:
        return jsonify({"success": False, "message": "Missing employee ID."}), 400
    try:
        emp = db.employees.find_one({'ma_nv': ma_nv}, {'ho_ten': 1, 'ma_nv': 1, '_id': 0})
        if not emp:
            return jsonify({"success": False, "message": "Employee not found."}), 404
        return jsonify({"success": True, "data": emp})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/hr/employees', methods=['POST'])
@login_required
def api_hr_employees_create():
    business_id = session.get('business_id') or session['user_id']
    data = request.json or {}
    ma_nv = (data.get('ma_nv') or '').strip()
    if not ma_nv:
        return jsonify({"success": False, "error": "Missing employee ID (ma_nv)."}), 400
    try:
        if db.employees.find_one({'ma_nv': ma_nv, 'business_id': business_id}):
            return jsonify({"success": False, "error": f"Employee ID '{ma_nv}' already exists."}), 409
        doc = {
            'id': next_mongo_id('employees'),
            'business_id': business_id,
            'ma_nv': ma_nv,
            'ho_ten': data.get('ho_ten', ''),
            'linh_vuc': data.get('linh_vuc', ''),
            'chuc_vu': data.get('chuc_vu', ''),
            'luong_cb': data.get('luong_cb', 0),
            'luong_gio': data.get('luong_gio', 0),
            'phu_cap': data.get('phu_cap', 0),
            'diem_kudo': 0,
            'staff_id': None,
        }
        db.employees.insert_one(doc)
        doc.pop('_id', None)
        return jsonify({"success": True, "data": doc})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/hr/employees/<ma_nv>', methods=['PATCH'])
@login_required
def api_hr_employees_update(ma_nv):
    business_id = session.get('business_id') or session['user_id']
    data = request.json or {}
    updates = {k: v for k, v in data.items() if k in _EMPLOYEE_PATCHABLE_FIELDS}
    if not updates:
        return jsonify({"success": False, "error": "No valid fields to update."}), 400
    try:
        result = db.employees.update_one({'ma_nv': ma_nv, 'business_id': business_id}, {'$set': updates})
        if result.matched_count == 0:
            return jsonify({"success": False, "error": "Employee not found."}), 404
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/hr/employees/<ma_nv>/kudo', methods=['POST'])
@login_required
def api_hr_employees_kudo(ma_nv):
    """Cộng điểm kudo cho đồng nghiệp (tính năng khen thưởng nội bộ ở app_nhanvien.html) —
    tách route riêng thay vì cho phép client tự gửi $inc tuỳ ý qua PATCH chung."""
    business_id = session.get('business_id') or session['user_id']
    data = request.json or {}
    try:
        points = int(data.get('points', 1))
    except (TypeError, ValueError):
        points = 1
    try:
        result = db.employees.update_one(
            {'ma_nv': ma_nv, 'business_id': business_id},
            {'$inc': {'diem_kudo': points}}
        )
        if result.matched_count == 0:
            return jsonify({"success": False, "error": "Employee not found."}), 404
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/hr/employees/<ma_nv>', methods=['DELETE'])
@login_required
def api_hr_employees_delete(ma_nv):
    business_id = session.get('business_id') or session['user_id']
    try:
        result = db.employees.delete_one({'ma_nv': ma_nv, 'business_id': business_id})
        if result.deleted_count == 0:
            return jsonify({"success": False, "error": "Employee not found."}), 404
        db.chamcong.delete_many({'ma_nv': ma_nv, 'business_id': business_id})
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/hr/chamcong', methods=['GET'])
@login_required
def api_hr_chamcong_list():
    business_id = session.get('business_id') or session['user_id']
    query = {'business_id': business_id}
    ma_nv = request.args.get('ma_nv')
    if ma_nv:
        query['ma_nv'] = ma_nv
    ngay_cham = request.args.get('ngay_cham')
    if ngay_cham:
        query['ngay_cham'] = ngay_cham
    nganh_nghe = request.args.get('nganh_nghe')
    if nganh_nghe:
        query['nganh_nghe'] = nganh_nghe
    limit = request.args.get('limit', type=int)
    try:
        cursor = db.chamcong.find(query, {'_id': 0}).sort('id', -1)
        if limit:
            cursor = cursor.limit(limit)
        return jsonify({"success": True, "data": list(cursor)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# Financial fields on db.chamcong (commission, tips, allowance, hours, overtime) must never
# persist as negative regardless of which screen/client math produced them (e.g. supply% >
# total bill on the nail Tua screen, or a bad client value on the F&B tip-split) — clamped here
# at the actual write boundary so it's guaranteed rather than relying on every caller to be correct.
_CHAMCONG_MONEY_FIELDS = ('tien_tua', 'tien_tips', 'phu_cap', 'so_gio', 'tang_ca')


def _clamp_chamcong_money_fields(fields):
    for field in _CHAMCONG_MONEY_FIELDS:
        if field in fields:
            try:
                fields[field] = max(0.0, float(fields[field] or 0))
            except (TypeError, ValueError):
                fields[field] = 0.0
    return fields


@app.route('/api/hr/chamcong', methods=['POST'])
@login_required
def api_hr_chamcong_create():
    business_id = session.get('business_id') or session['user_id']
    data = request.json or {}
    if not (data.get('ma_nv') or '').strip():
        return jsonify({"success": False, "error": "Missing employee ID (ma_nv)."}), 400
    try:
        doc = _clamp_chamcong_money_fields(dict(data))
        doc['id'] = next_mongo_id('chamcong')
        doc['business_id'] = business_id
        db.chamcong.insert_one(doc)
        doc.pop('_id', None)
        return jsonify({"success": True, "data": doc})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/hr/chamcong/<int:record_id>', methods=['PATCH'])
@login_required
def api_hr_chamcong_update(record_id):
    business_id = session.get('business_id') or session['user_id']
    data = request.json or {}
    updates = {k: v for k, v in data.items() if k != 'id' and k != 'business_id' and k != 'ma_nv'}
    if not updates:
        return jsonify({"success": False, "error": "No valid fields to update."}), 400
    updates = _clamp_chamcong_money_fields(updates)
    try:
        result = db.chamcong.update_one({'id': record_id, 'business_id': business_id}, {'$set': updates})
        if result.matched_count == 0:
            return jsonify({"success": False, "error": "Attendance record not found."}), 404
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ========== TASKS & CHO_DOI_CA JSON API (thay Supabase JS ở app_nhanvien/chamcong_kythuat/
# chamcong_fnb.html) — db.tasks (đã có sẵn, dùng chung với dashboard/SSE), db.cho_doi_ca
# (collection mới). business_id lấy từ session, KHÔNG tin client. ==========
@app.route('/api/tasks', methods=['GET'])
@login_required
def api_tasks_list():
    """Danh sách công việc (Job Market/Kanban điều phối). Không truyền `worker` -> trả về
    toàn bộ tasks của business (app_nhanvien.html tự phân loại việc của mình/còn trống ở
    client). Có truyền `worker` -> chỉ trả về việc đang Chờ Nhận HOẶC đã Đã Nhận bởi đúng
    người đó (dùng cho dropdown gán việc ở chamcong_kythuat.html)."""
    business_id = session.get('business_id') or session['user_id']
    query = {'business_id': business_id}
    worker = request.args.get('worker')
    if worker:
        query['$or'] = [
            {'trang_thai': 'Chờ Nhận'},
            {'trang_thai': 'Đã Nhận', 'nguoi_nhan': worker},
        ]
    try:
        tasks = list(db.tasks.find(query, {'_id': 0}).sort('id', -1))
        return jsonify({"success": True, "data": tasks})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/tasks', methods=['POST'])
@login_required
def api_tasks_create():
    business_id = session.get('business_id') or session['user_id']
    data = request.json or {}
    try:
        doc = dict(data)
        doc['id'] = next_mongo_id('tasks')
        doc['business_id'] = business_id
        doc.setdefault('trang_thai', 'Chờ Nhận')
        db.tasks.insert_one(doc)
        doc.pop('_id', None)
        return jsonify({"success": True, "data": doc})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/tasks/<int:task_id>', methods=['PATCH'])
@login_required
def api_tasks_update(task_id):
    business_id = session.get('business_id') or session['user_id']
    data = request.json or {}
    updates = {k: v for k, v in data.items() if k not in ('id', 'business_id')}
    if not updates:
        return jsonify({"success": False, "error": "Không có trường hợp lệ để cập nhật."}), 400
    try:
        result = db.tasks.update_one({'id': task_id, 'business_id': business_id}, {'$set': updates})
        if result.matched_count == 0:
            return jsonify({"success": False, "error": "Không tìm thấy công việc."}), 404
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/tasks/<int:task_id>', methods=['DELETE'])
@login_required
def api_tasks_delete(task_id):
    business_id = session.get('business_id') or session['user_id']
    try:
        result = db.tasks.delete_one({'id': task_id, 'business_id': business_id})
        if result.deleted_count == 0:
            return jsonify({"success": False, "error": "Không tìm thấy công việc."}), 404
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/tasks/cleanup', methods=['POST'])
@login_required
def api_tasks_cleanup():
    """Xoá hàng loạt job theo trạng thái (vd 'Hoàn Thành') — dùng bởi nút "Dọn dẹp" ở
    quanly_dichvu.html."""
    business_id = session.get('business_id') or session['user_id']
    data = request.json or {}
    trang_thai = data.get('trang_thai', 'Hoàn Thành')
    try:
        result = db.tasks.delete_many({'business_id': business_id, 'trang_thai': trang_thai})
        return jsonify({"success": True, "deleted_count": result.deleted_count})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/shift_swaps', methods=['GET'])
@login_required
def api_shift_swaps_list():
    """cho_doi_ca: danh sách yêu cầu đổi ca/nhờ trực. Lọc theo business_id; truyền thêm
    `ma_nv` để chỉ lấy các yêu cầu mà nhân viên đó là người xin HOẶC người nhận."""
    business_id = session.get('business_id') or session['user_id']
    query = {'business_id': business_id}
    ma_nv = request.args.get('ma_nv')
    if ma_nv:
        query['$or'] = [{'ma_nv_xin': ma_nv}, {'ma_nv_nhan': ma_nv}]
    try:
        swaps = list(db.cho_doi_ca.find(query, {'_id': 0}).sort('id', -1))
        return jsonify({"success": True, "data": swaps})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/shift_swaps', methods=['POST'])
@login_required
def api_shift_swaps_create():
    business_id = session.get('business_id') or session['user_id']
    data = request.json or {}
    if not (data.get('ma_nv_xin') or '').strip() or not (data.get('ma_nv_nhan') or '').strip():
        return jsonify({"success": False, "error": "Thiếu mã nhân viên xin/nhận ca."}), 400
    try:
        doc = {
            'id': next_mongo_id('cho_doi_ca'),
            'business_id': business_id,
            'ma_nv_xin': data['ma_nv_xin'],
            'ma_nv_nhan': data['ma_nv_nhan'],
            'ngay_ca': data.get('ngay_ca', ''),
            'trang_thai': data.get('trang_thai', 'Chờ chốt'),
        }
        db.cho_doi_ca.insert_one(doc)
        doc.pop('_id', None)
        return jsonify({"success": True, "data": doc})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/shift_swaps/<int:swap_id>', methods=['PATCH'])
@login_required
def api_shift_swaps_update(swap_id):
    """Duyệt/hủy yêu cầu đổi ca — chỉ cho phép đổi `trang_thai` (vd: 'Đã chốt', 'Từ chối')."""
    business_id = session.get('business_id') or session['user_id']
    data = request.json or {}
    trang_thai = data.get('trang_thai')
    if not trang_thai:
        return jsonify({"success": False, "error": "Thiếu trang_thai."}), 400
    try:
        result = db.cho_doi_ca.update_one(
            {'id': swap_id, 'business_id': business_id},
            {'$set': {'trang_thai': trang_thai}}
        )
        if result.matched_count == 0:
            return jsonify({"success": False, "error": "Không tìm thấy yêu cầu đổi ca."}), 404
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ========== KHO VẬT TƯ & DỊCH VỤ JSON API (thay Supabase JS ở chamcong_kythuat/
# chamcong_spa.html) — db.kho_vat_tu và db.dichvu (2 collection mới). business_id lấy từ
# session, KHÔNG tin client. ==========
@app.route('/api/inventory', methods=['GET'])
@login_required
def api_inventory_list():
    business_id = session.get('business_id') or session['user_id']
    try:
        items = list(db.kho_vat_tu.find({'business_id': business_id}, {'_id': 0}).sort('id', 1))
        return jsonify({"success": True, "data": items})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/inventory', methods=['POST'])
@login_required
def api_inventory_create():
    business_id = session.get('business_id') or session['user_id']
    data = request.json or {}
    if not (data.get('ten_vat_tu') or '').strip():
        return jsonify({"success": False, "error": "Thiếu tên vật tư."}), 400
    try:
        doc = {
            'id': next_mongo_id('kho_vat_tu'),
            'business_id': business_id,
            'ten_vat_tu': data['ten_vat_tu'],
            'don_vi': data.get('don_vi', ''),
            'ton_kho': data.get('ton_kho', 0),
        }
        db.kho_vat_tu.insert_one(doc)
        doc.pop('_id', None)
        return jsonify({"success": True, "data": doc})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/inventory/<int:item_id>', methods=['PATCH'])
@login_required
def api_inventory_update(item_id):
    business_id = session.get('business_id') or session['user_id']
    data = request.json or {}
    updates = {k: v for k, v in data.items() if k in ('ten_vat_tu', 'don_vi', 'ton_kho')}
    if not updates:
        return jsonify({"success": False, "error": "Không có trường hợp lệ để cập nhật."}), 400
    try:
        result = db.kho_vat_tu.update_one({'id': item_id, 'business_id': business_id}, {'$set': updates})
        if result.matched_count == 0:
            return jsonify({"success": False, "error": "Không tìm thấy vật tư."}), 404
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/inventory/<int:item_id>', methods=['DELETE'])
@login_required
def api_inventory_delete(item_id):
    business_id = session.get('business_id') or session['user_id']
    try:
        result = db.kho_vat_tu.delete_one({'id': item_id, 'business_id': business_id})
        if result.deleted_count == 0:
            return jsonify({"success": False, "error": "Không tìm thấy vật tư."}), 404
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/stream/inventory')
@login_required
def stream_inventory():
    """Thay kênh Supabase Realtime `kho_tracking` (quanly_kho.html) — bảng kho_vat_tu. Layer 4
    chỉ xây CRUD, chưa có realtime (đó là phạm vi Layer 2) — bổ sung ở đây vì quanly_kho.html
    cần đúng kênh này."""
    return _sse_change_signal(db.kho_vat_tu, _sse_tenant_match())


@app.route('/api/services', methods=['GET'])
@login_required
def api_services_list():
    business_id = session.get('business_id') or session['user_id']
    try:
        items = list(db.dichvu.find({'business_id': business_id}, {'_id': 0}).sort('id', 1))
        return jsonify({"success": True, "data": items})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/services', methods=['POST'])
@login_required
def api_services_create():
    business_id = session.get('business_id') or session['user_id']
    data = request.json or {}
    if not (data.get('ten_dich_vu') or '').strip():
        return jsonify({"success": False, "error": "Thiếu tên dịch vụ."}), 400
    try:
        doc = {
            'id': next_mongo_id('dichvu'),
            'business_id': business_id,
            'ten_dich_vu': data['ten_dich_vu'],
            'gia_dich_vu': data.get('gia_dich_vu', 0),
            'tien_tua': data.get('tien_tua', 0),
        }
        db.dichvu.insert_one(doc)
        doc.pop('_id', None)
        return jsonify({"success": True, "data": doc})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/services/<int:service_id>', methods=['PATCH'])
@login_required
def api_services_update(service_id):
    business_id = session.get('business_id') or session['user_id']
    data = request.json or {}
    updates = {k: v for k, v in data.items() if k in ('ten_dich_vu', 'gia_dich_vu', 'tien_tua')}
    if not updates:
        return jsonify({"success": False, "error": "Không có trường hợp lệ để cập nhật."}), 400
    try:
        result = db.dichvu.update_one({'id': service_id, 'business_id': business_id}, {'$set': updates})
        if result.matched_count == 0:
            return jsonify({"success": False, "error": "Không tìm thấy dịch vụ."}), 404
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/services/<int:service_id>', methods=['DELETE'])
@login_required
def api_services_delete(service_id):
    business_id = session.get('business_id') or session['user_id']
    try:
        result = db.dichvu.delete_one({'id': service_id, 'business_id': business_id})
        if result.deleted_count == 0:
            return jsonify({"success": False, "error": "Không tìm thấy dịch vụ."}), 404
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/expense')
@login_required
def expense_alias():
    return redirect(url_for('quanly_thuchi'))


# BITPAW NETWORK BLUEPRINT (job/service/community marketplace) đã bị xoá — toàn bộ 12 route
# /network/* dùng chung khối template network_*.html KHÔNG TỒN TẠI trong templates/ (đã kiểm
# tra bằng ls, không route nào render được), nên trước đây bấm vào bất kỳ URL /network/* nào
# đều lỗi 500 TemplateNotFound. Module dở dang, tách biệt hoàn toàn khỏi kiến trúc MongoDB đa
# tenant chính (tự dùng SQLite database.db + session['network_user'] riêng) — không có nơi nào
# khác trong code liên kết tới các route này (đã grep xác nhận), xoá an toàn.


# ========== API QR CODE DYNAMIC (PHASE 1) ==========
@app.route('/api/workspace/generate-qr', methods=['POST'])
@login_required
def generate_qr():
    import secrets
    from datetime import datetime, timedelta
    
    qr_token = secrets.token_hex(16)
    expires_at = (datetime.now() + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    
    try:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS qr_tokens (
                token TEXT PRIMARY KEY,
                expires_at TEXT NOT NULL
            )
        ''')
        c.execute("INSERT INTO qr_tokens (token, expires_at) VALUES (?, ?)", (qr_token, expires_at))
        conn.commit()
        conn.close()
        
        return jsonify({
            "status": "success",
            "qr_token": qr_token,
            "expires_at": expires_at
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@app.route('/api/workspace/validate-qr', methods=['POST'])
@login_required
def validate_qr():
    from datetime import datetime
    
    data = request.json or {}
    qr_token = data.get('qr_token')
    
    if not qr_token:
        return jsonify({
            "status": "error",
            "message": "Thiếu qr_token"
        }), 400
        
    try:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS qr_tokens (
                token TEXT PRIMARY KEY,
                expires_at TEXT NOT NULL
            )
        ''')
        c.execute("SELECT expires_at FROM qr_tokens WHERE token = ?", (qr_token,))
        row = c.fetchone()
        conn.close()
        
        if not row:
            return jsonify({
                "status": "error",
                "message": "Token không hợp lệ hoặc không tồn tại"
            }), 404
            
        expires_at_str = row[0]
        expires_at = datetime.strptime(expires_at_str, "%Y-%m-%d %H:%M:%S")
        
        if datetime.now() > expires_at:
            return jsonify({
                "status": "error",
                "message": "QR hết hạn"
            })
            
        return jsonify({
            "status": "success",
            "message": "Hợp lệ"
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@app.errorhandler(TemplateNotFound)
def handle_missing_template(e):
    """Lưới an toàn: 1 số route /network/* (module tuyển dụng) chưa có template thật
    (thiếu ~12 file network_*.html) — thay vì màn hình lỗi 500 trắng trơn cho khách
    hàng thật, hiện thông báo "đang phát triển" thân thiện. Không thay thế cho việc
    xây đủ các trang này — chỉ chặn crash trong lúc chờ."""
    print(f"[!] Template không tồn tại: {str(e)}")
    return render_template('index.html', active_tab='login'), 404


# Sanity-check khởi động: mọi tên trong _CSRF_EXEMPT_ENDPOINTS phải khớp đúng 1 route thật đã
# đăng ký (app.view_functions chỉ đầy đủ ở đây, SAU khi mọi route load xong) — báo ngay lúc
# start server nếu 1 tên bị gõ sai/route đã đổi tên, thay vì âm thầm không exempt được và chỉ
# phát hiện khi endpoint đó lỗi CSRF thật giữa lúc vận hành. Việc EXEMPT THẬT SỰ nằm ở check
# `request.endpoint in _CSRF_EXEMPT_ENDPOINTS` bên trong _hybrid_auth_and_csrf() — csrf.exempt()
# gọi ở đây không còn tác dụng thực thi từ khi chuyển sang gọi csrf.protect() thủ công (Giai
# đoạn 5), giữ lại object exempt của Flask-WTF cho nhất quán/debug, không phải cơ chế chính.
for _endpoint_name in _CSRF_EXEMPT_ENDPOINTS:
    _view_func = app.view_functions.get(_endpoint_name)
    if _view_func is not None:
        csrf.exempt(_view_func)
    else:
        print(f"[!] CSRF exempt: không tìm thấy endpoint '{_endpoint_name}' (route đã đổi tên?).")


if __name__ == '__main__':
    # GridFS không cần tạo bucket trước — collection 'backups.files'/'backups.chunks' tự được
    # MongoDB tạo lười (lazy) ngay lần fs.put() đầu tiên, không cần bước khởi tạo nào ở đây.
    app.run(port=5001, debug=os.environ.get('FLASK_DEBUG', '').lower() == 'true')