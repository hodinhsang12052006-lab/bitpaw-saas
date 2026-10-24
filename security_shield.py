"""Lá chắn bảo mật tầng ứng dụng (Pha 28) — chặn công cụ tấn công/dò quét, cấm IP tạm thời, bẫy bot, nhật ký sự kiện.

Bối cảnh: rate-limit theo route (Flask-Limiter) + khoá đăng nhập theo email/IP đã có. Cái còn thiếu là phản ứng với KẺ DÒ:
  - Công cụ quét/khai thác tự động (sqlmap, nikto, nuclei, gobuster…) tự khai User-Agent -> chặn ngay, ghi lỗi nặng.
  - Dò đường dẫn nhạy cảm không tồn tại trong BitPaw (/.env, /.git, /wp-admin, *.php…) — người dùng thật không bao giờ
    gõ những đường này -> mỗi lần là 1 "strike"; đủ STRIKES_TO_BAN trong STRIKE_WINDOW -> cấm IP BAN_SECONDS
    (tái phạm -> REPEAT_BAN_SECONDS). Lưu MongoDB (TTL) nên mọi instance serverless cùng thấy.
  - Bẫy bot (honeypot): form công khai có 1 ô ẩn, người thật không thấy; bot điền tự động -> nhận "thành công" giả.
  - Đoán mã kích hoạt: đếm mã sai theo IP, quá ngưỡng thì khoá.
Không bao giờ cấm IP trong SECURITY_ALLOWLIST_IPS (phân tách bằng dấu phẩy).
"""
import ipaddress
import os
import re
import time
from datetime import datetime, timedelta

STRIKE_WINDOW = 600            # giây
STRIKES_TO_BAN = 3
BAN_SECONDS = 3600
REPEAT_BAN_SECONDS = 24 * 3600
CODE_FAIL_WINDOW = 3600
CODE_FAIL_MAX = 8              # mã kích hoạt sai / IP / giờ
CACHE_SECONDS = 60

ATTACK_UA = re.compile(
    r'(sqlmap|nikto|nmap|masscan|zgrab|nuclei|acunetix|wpscan|dirbuster|dirb/|gobuster|feroxbuster|ffuf|wfuzz|'
    r'hydra|medusa|havij|netsparker|appscan|w3af|whatweb|jaeles|commix|openvas|nessus|arachni|skipfish|'
    r'zap/|owasp|metasploit|morfeus|zmeu|masscan|xsstrike|dalfox|joomscan|droopescan|fimap|bbqsql|'
    r'interactsh|burpcollaborator|censysinspect|l9explore|l9tcpid)', re.I)
# Đường dẫn chỉ kẻ dò mới gõ (BitPaw là Flask, không có PHP/ASP/WordPress, không lộ file cấu hình)
PROBE_PATH = re.compile(
    r'(^/\.(env|git|svn|hg|bzr|aws|ssh|docker|npmrc|htaccess|htpasswd|DS_Store)(/|$|\.)'
    r'|^/(wp-admin|wp-login|wp-content|wp-includes|wp-json|xmlrpc|phpmyadmin|pma|myadmin|adminer|mysql|'
    r'server-status|server-info|actuator|cgi-bin|vendor/phpunit|boaform|hnap1|owa/|solr/|jenkins|'
    r'console/|manager/html|telescope|_ignition|laravel|debug/default|backup\.(zip|tar|gz|sql)|dump\.sql|db\.sql|database\.sql|'
    r'config\.(json|yml|yaml|php|bak)|web\.config|appsettings\.json|id_rsa|etc/passwd)'
    r'|\.(php\d?|asp|aspx|jsp|cgi|pl|sql|bak|old|swp|tar|tgz|rar|7z)$'
    r'|\.\./|%2e%2e)', re.I)

CF_NETS = [ipaddress.ip_network(n) for n in (
    '173.245.48.0/20', '103.21.244.0/22', '103.22.200.0/22', '103.31.4.0/22', '141.101.64.0/18', '108.162.192.0/18',
    '190.93.240.0/20', '188.114.96.0/20', '197.234.240.0/22', '198.41.128.0/17', '162.158.0.0/15', '104.16.0.0/13',
    '104.24.0.0/14', '172.64.0.0/13', '131.0.72.0/22',
    '2400:cb00::/32', '2606:4700::/32', '2803:f800::/32', '2405:b500::/32', '2405:8100::/32', '2a06:98c0::/29',
    '2c0f:f248::/32')]

HONEYPOT_FIELD = 'company_website'

_db = None
_ban_cache = {}               # ip -> (banned_until_ts, checked_at)
_indexes_ready = False


def is_cloudflare(ip):
    try:
        a = ipaddress.ip_address((ip or '').strip())
    except ValueError:
        return False
    return any(a in n for n in CF_NETS)


def client_ip(req):
    """IP thật của khách.
    Trên Vercel: X-Real-IP / X-Forwarded-For do Vercel GHI ĐÈ (khách không tự khai được) = IP đang kết nối tới Vercel.
    Nếu IP đó thuộc dải Cloudflare -> request đi qua Cloudflare -> dùng CF-Connecting-IP (Cloudflare ghi đè).
    Nếu không (ai đó gọi thẳng *.vercel.app) -> KHÔNG tin CF-Connecting-IP — trước đây kẻ tấn công tự khai header này
    để đổi IP mỗi lần gửi, né mọi giới hạn đăng nhập/AI.
    Máy dev/test (không có VERCEL): giữ cách cũ (cho phép giả lập IP bằng header khi kiểm thử)."""
    if os.environ.get('VERCEL'):
        conn = (req.headers.get('X-Real-IP') or (req.headers.get('X-Forwarded-For') or '').split(',')[0]
                or req.remote_addr or '').strip()
        cf_ip = (req.headers.get('CF-Connecting-IP') or '').strip()
        if cf_ip and is_cloudflare(conn):
            return cf_ip
        return conn or '0.0.0.0'
    cf_ip = req.headers.get('CF-Connecting-IP')
    if cf_ip:
        return cf_ip.strip()
    xff = req.headers.get('X-Forwarded-For')
    if xff:
        return xff.split(',')[0].strip()
    return req.remote_addr or '127.0.0.1'


def _allowlisted(ip):
    allow = {x.strip() for x in (os.environ.get('SECURITY_ALLOWLIST_IPS') or '').split(',') if x.strip()}
    return ip in allow


def _ensure_indexes():
    global _indexes_ready
    if _indexes_ready or _db is None:
        return
    try:
        _db.security_strikes.create_index('at', expireAfterSeconds=STRIKE_WINDOW)
        _db.security_strikes.create_index([('ip', 1), ('at', 1)])
        _db.security_bans.create_index('until', expireAfterSeconds=0)
        _db.security_bans.create_index('ip')
        _db.security_events.create_index('at', expireAfterSeconds=90 * 24 * 3600)
        _db.security_events.create_index([('kind', 1), ('at', -1)])
        _db.code_failures.create_index('at', expireAfterSeconds=CODE_FAIL_WINDOW)
        _db.code_failures.create_index([('ip', 1), ('at', 1)])
        _indexes_ready = True
    except Exception as e:
        print(f"[shield] index: {e}")


def log_event(kind, ip, detail='', path='', ua='', user=None):
    """Nhật ký sự kiện bảo mật (90 ngày) — super admin xem ở trang quản trị."""
    if _db is None:
        return
    try:
        _ensure_indexes()
        _db.security_events.insert_one({'kind': kind, 'ip': ip, 'detail': str(detail)[:300], 'path': str(path)[:200],
                                        'ua': str(ua)[:200], 'user': user, 'at': datetime.utcnow()})
    except Exception as e:
        print(f"[shield] log: {e}")


def is_banned(ip):
    if not ip or _allowlisted(ip) or _db is None:
        return 0
    now = time.time()
    hit = _ban_cache.get(ip)
    if hit and now - hit[1] < CACHE_SECONDS:
        return hit[0] if hit[0] > now else 0
    until = 0
    try:
        doc = _db.security_bans.find_one({'ip': ip, 'until': {'$gt': datetime.utcnow()}}, {'_id': 0, 'until': 1})
        if doc:
            until = (doc['until'] - datetime.utcnow()).total_seconds() + now
    except Exception as e:
        print(f"[shield] ban check: {e}")
    _ban_cache[ip] = (until, now)
    return until if until > now else 0


def ban(ip, reason, seconds=None):
    if _db is None or _allowlisted(ip):
        return
    try:
        _ensure_indexes()
        prior = _db.security_events.count_documents({'kind': 'ban', 'ip': ip, 'at': {'$gte': datetime.utcnow() - timedelta(days=7)}})
        secs = seconds or (REPEAT_BAN_SECONDS if prior else BAN_SECONDS)
        until = datetime.utcnow() + timedelta(seconds=secs)
        _db.security_bans.update_one({'ip': ip}, {'$set': {'ip': ip, 'until': until, 'reason': reason}}, upsert=True)
        _ban_cache[ip] = (time.time() + secs, time.time())
        log_event('ban', ip, f"{reason} ({secs // 60} min)")
    except Exception as e:
        print(f"[shield] ban: {e}")


def strike(ip, reason, weight=1, path='', ua=''):
    """+weight lượt vi phạm trong STRIKE_WINDOW; đủ STRIKES_TO_BAN -> cấm IP."""
    if _db is None or not ip or _allowlisted(ip):
        return
    try:
        _ensure_indexes()
        now = datetime.utcnow()
        _db.security_strikes.insert_many([{'ip': ip, 'reason': reason, 'at': now} for _ in range(max(1, weight))])
        log_event('strike', ip, reason, path, ua)
        n = _db.security_strikes.count_documents({'ip': ip, 'at': {'$gte': now - timedelta(seconds=STRIKE_WINDOW)}})
        if n >= STRIKES_TO_BAN:
            ban(ip, reason)
    except Exception as e:
        print(f"[shield] strike: {e}")


def honeypot_tripped(data):
    """True nếu ô ẩn chống bot có giá trị (người thật không thấy ô này)."""
    try:
        v = data.get(HONEYPOT_FIELD) if data is not None else None
    except Exception:
        return False
    return bool(v and str(v).strip())


def code_attempts_blocked(ip):
    if _db is None or _allowlisted(ip):
        return False
    try:
        since = datetime.utcnow() - timedelta(seconds=CODE_FAIL_WINDOW)
        return _db.code_failures.count_documents({'ip': ip, 'at': {'$gte': since}}, limit=CODE_FAIL_MAX) >= CODE_FAIL_MAX
    except Exception:
        return False


def record_code_failure(ip, code=''):
    if _db is None:
        return
    try:
        _ensure_indexes()
        _db.code_failures.insert_one({'ip': ip, 'at': datetime.utcnow()})
        log_event('bad_activation_code', ip, (code or '')[:4] + '…')
    except Exception as e:
        print(f"[shield] code fail: {e}")


def init(app, db, get_ip, wants_json):
    """Gắn lá chắn vào app: chặn IP đang bị cấm, công cụ tấn công, đường dẫn dò."""
    global _db
    _db = db
    from flask import jsonify, make_response, request

    def _blocked_response(status, retry=None):
        if wants_json():
            resp = jsonify({'success': False, 'message': 'Request blocked for security reasons.' if status == 403 else 'Not found.'})
        else:
            resp = make_response(
                '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
                '<title>BitPaw</title><body style="font-family:system-ui,sans-serif;background:#0b0f17;color:#e5e7eb;'
                'display:grid;place-items:center;min-height:100vh;margin:0"><div style="max-width:420px;padding:24px;text-align:center">'
                '<h1 style="font-size:20px;margin:0 0 8px">' + ('Access temporarily blocked' if status == 403 else 'Page not found') +
                '</h1><p style="color:#9ca3af;font-size:14px;line-height:1.6">' +
                ('Unusual activity was detected from your network. Please try again later.' if status == 403 else
                 'The page you are looking for does not exist.') + '</p></div></body>')
        resp.status_code = status
        if retry:
            resp.headers['Retry-After'] = str(int(retry))
        return resp

    @app.before_request
    def _shield():
        if request.path.startswith('/static/'):
            return None
        ip = get_ip()
        if _allowlisted(ip):
            return None
        until = is_banned(ip)
        if until:
            return _blocked_response(403, until - time.time())
        ua = request.headers.get('User-Agent', '')
        if ATTACK_UA.search(ua):
            strike(ip, 'attack tool user-agent', weight=STRIKES_TO_BAN, path=request.path, ua=ua)
            return _blocked_response(403)
        raw_path = request.environ.get('RAW_URI') or request.environ.get('REQUEST_URI') or request.full_path or request.path
        if PROBE_PATH.search(request.path) or PROBE_PATH.search(raw_path.split('?')[0]):
            strike(ip, 'probe ' + request.path[:80], weight=1, path=request.path, ua=ua)
            return _blocked_response(404)
        return None
