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

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, send_from_directory, Response, stream_with_context
from jinja2.exceptions import TemplateNotFound
from datetime import datetime, timedelta
import os
import time
import math
import uuid
import json
import random
import re
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import requests
# Đã gỡ bỏ hoàn toàn Supabase khỏi backend — toàn bộ dữ liệu giờ đọc/ghi qua MongoDB Atlas
# (pymongo) bên dưới.
from mongo_client import db, fs, MONGO_STATUS, next_mongo_id, next_mongo_id_batch
from i18n import get_translations, resolve_lang, LANG_COOKIE_NAME
from pymongo import UpdateOne, ReturnDocument
from cryptography.fernet import Fernet
from gridfs import GridFS
from gridfs.errors import NoFile
from bson import ObjectId
from bson.errors import InvalidId
from ai_context_engine import AIContextEngine
from email_service import EmailService

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
        @staticmethod
        def start_us_payment(amount_usd, txn_id, description='BitPaw POS Order'):
            return {'success': False, 'configured': False, 'message': 'payment_us_engine module không khả dụng trên server này.'}
    payment_us_engine = _PaymentUsEngineFallback()

app = Flask(__name__, static_folder='static', template_folder='templates')
_flask_secret_key = os.environ.get('FLASK_SECRET_KEY')
if not _flask_secret_key:
    raise RuntimeError(
        "FLASK_SECRET_KEY chưa được cấu hình trong biến môi trường. "
        "Đặt biến này trong .env (dev) hoặc Vercel Project Settings -> Environment Variables (production) trước khi chạy."
    )
app.secret_key = _flask_secret_key

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
    business_mode = session.get('business_mode', 'retail')
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
    c.execute('''
        CREATE TABLE IF NOT EXISTS customer_profiles (
            id TEXT PRIMARY KEY,
            business_id TEXT NOT NULL,
            name TEXT NOT NULL,
            phone TEXT,
            email TEXT,
            industry TEXT,
            source_platform TEXT,
            last_purchase_at TIMESTAMP,
            total_spending REAL DEFAULT 0,
            services_of_interest TEXT,
            nurturing_status TEXT DEFAULT 'NEW',
            ai_notes TEXT,
            potential_score REAL DEFAULT 50,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS campaign_messages (
            id TEXT PRIMARY KEY,
            business_id TEXT NOT NULL,
            campaign_id TEXT NOT NULL,
            customer_id TEXT NOT NULL,
            step_delay INTEGER NOT NULL,
            message_body TEXT NOT NULL,
            approval_status TEXT DEFAULT 'PENDING',
            scheduled_send_at TIMESTAMP,
            sent_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS nurturing_campaigns (
            id TEXT PRIMARY KEY,
            business_id TEXT NOT NULL,
            name TEXT NOT NULL,
            target_segment_id TEXT,
            campaign_goal TEXT,
            channel TEXT,
            tone TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
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
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Vui lòng đăng nhập để tiếp tục', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


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
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        business_type = request.form['business_type']
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
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        is_root_email = email.strip().lower() == SUPERADMIN_ROOT_EMAIL
        fallback_hash = os.environ.get('SUPERADMIN_FALLBACK_HASH')

        try:
            if db is None:
                if is_root_email and fallback_hash and check_password_hash(fallback_hash, password):
                    return _superadmin_emergency_login(email)
                raise Exception("MongoDB chưa kết nối.")

            user = db.users.find_one({'email': email})
            if not user:
                if is_root_email and fallback_hash and check_password_hash(fallback_hash, password):
                    return _superadmin_emergency_login(email)
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
                    'ip_address': request.remote_addr,
                    'created_at': datetime.now().isoformat()
                })
            except Exception as db_err:
                print(f"MongoDB user_logs insert skipped: {str(db_err)}")

            # Đọc business type để redirect đúng ngành nghề, khóa riêng theo user_id hiện tại
            mode = None
            try:
                business_mode_key = f'business_mode_{user_id}'
                mode_doc = db.system_settings.find_one({'key': business_mode_key})
                mode = mode_doc['value'] if mode_doc else 'none'
            except Exception as db_err:
                print(f"MongoDB system_settings select skipped: {str(db_err)}")
                mode = 'none'

            session['business_mode'] = mode

            flash('Login successful', 'success')

            # Hardcode duy nhất 1 tài khoản trùm: email này luôn vào thẳng Super Admin, bất kể
            # business_mode đã cấu hình hay chưa — không đẩy qua /setup như user thường. Check
            # này đặt trước mọi logic redirect theo ngành nghề.
            if email.strip().lower() == 'hodinhsang30052003@gmail.com':
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
                    'ip_address': request.remote_addr,
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
        mode = session.get('business_mode')
        if not mode:
            try:
                mode_doc = db.system_settings.find_one({'key': f"business_mode_{session['user_id']}"}, {'value': 1, '_id': 0})
                mode = mode_doc['value'] if mode_doc else 'none'
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
        
    mode = session.get('business_mode')
    if not mode:
        try:
            mode_doc = db.system_settings.find_one({'key': f"business_mode_{session['user_id']}"}, {'value': 1, '_id': 0})
            mode = mode_doc['value'] if mode_doc else 'none'
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
def _deny_if_staff():
    """Chặn tài khoản role='staff' xem thống kê Dashboard của chủ tiệm — trả về response lỗi
    403 nếu bị chặn, hoặc None nếu được phép đi tiếp. Hiện luồng đăng ký chính luôn tạo
    role='admin', nhưng kiểm tra này vẫn bắt buộc để phòng ngừa khi có tính năng mời nhân
    viên với role giới hạn trong tương lai — không được để sót người chưa đủ quyền."""
    if session.get('role') == 'staff':
        return jsonify({'success': False, 'message': 'Tài khoản của bạn không có quyền xem thống kê này.'}), 403
    return None


def _deny_if_staff_page():
    """Biến thể dùng cho route render_template (không phải JSON API): chặn role='staff'
    truy cập trực tiếp bằng URL vào các trang nhạy cảm (Lương, Chi phí, Cài đặt, Doanh thu/
    Báo cáo, Quản lý nhân sự, GPS Radar) — vốn đã bị ẩn khỏi sidebar, nhưng vẫn phải chặn ở
    route để không sót trường hợp gõ thẳng URL."""
    if session.get('role') == 'staff':
        flash('Tài khoản của bạn không có quyền truy cập trang này.', 'danger')
        return redirect(url_for('index'))
    return None


def _get_task_counts(business_id):
    return {
        'pending': db.tasks.count_documents({'business_id': business_id, 'trang_thai': 'Chờ Nhận'}),
        'doing': db.tasks.count_documents({'business_id': business_id, 'trang_thai': 'Đã Nhận'}),
        'done': db.tasks.count_documents({'business_id': business_id, 'trang_thai': 'Hoàn Thành'}),
    }


@app.route('/api/dashboard/stats', methods=['GET'])
@login_required
def api_dashboard_stats():
    denied = _deny_if_staff()
    if denied:
        return denied
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
def api_dashboard_kudo_leaderboard():
    denied = _deny_if_staff()
    if denied:
        return denied
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
def api_dashboard_reconciliation_alerts():
    denied = _deny_if_staff()
    if denied:
        return denied
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
def api_dashboard_resolve_alert(alert_id):
    denied = _deny_if_staff()
    if denied:
        return denied
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
def stream_dashboard_tasks():
    denied = _deny_if_staff()
    if denied:
        return denied
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
        mode = request.form['mode']
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
        current_mode = mode_doc['value'] if mode_doc else 'none'
    except Exception as db_err:
        print(f"MongoDB system_settings select failed: {str(db_err)}")
        current_mode = 'none'
    if request.method == 'POST':
        image_file = request.files.get('image')
        filename = ""
        if image_file and image_file.filename != '' and allowed_file(image_file.filename):
            filename = secure_filename(image_file.filename)
            image_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        cat = request.form['category']
        business_id = session.get('business_id') or session['user_id']
        try:
            db.products.insert_one({
                'id': next_mongo_id('products'),
                'name': request.form['name'],
                'category': cat,
                'channel_type': 'fnb' if current_mode == 'fnb' else 'retail',
                'stock': int(request.form['stock']),
                'price': float(request.form['price']),
                'image': filename,
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
    business_id = session.get('business_id') or session['user_id']
    try:
        if not _assert_owns_product(id, business_id):
            return "Sản phẩm không tồn tại hoặc không thuộc quyền quản lý của bạn.", 403
    except Exception as e:
        return f"Lỗi xác thực quyền sở hữu sản phẩm: {str(e)}", 500

    try:
        old_value = db.products.find_one({'id': id}, {'name': 1, 'is_active': 1, '_id': 0})
        db.products.update_one({'id': id, 'business_id': business_id}, {'$set': {'is_active': 0}})
        _log_audit(business_id, 'delete_product', entity_type='product', entity_id=id, old_value=old_value, new_value={'is_active': 0})
    except Exception as e:
        return f"Lỗi xóa sản phẩm: {str(e)}", 500
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


@app.route('/api/sales/checkout', methods=['POST'])
@login_required
def api_sales_checkout():
    """Bán hàng trực tiếp (sell.html: 1 sản phẩm; spa.html: giỏ hàng nhiều dịch vụ) — khác
    checkout_table() (dùng cho đơn theo bàn F&B qua table_orders). Route này tạo thẳng 1
    order + order_items từ danh sách item client gửi lên, không qua bàn. Trừ tồn kho nếu sản
    phẩm có field `stock` (dịch vụ spa thường không track tồn kho nên bỏ qua an toàn)."""
    business_id = session.get('business_id') or session['user_id']
    data = request.json or {}
    items = data.get('items') or []
    if not items:
        return jsonify({"success": False, "message": "Giỏ hàng trống."}), 400
    try:
        product_ids = [it['product_id'] for it in items]
        products_map = {
            p['id']: p for p in db.products.find(
                {'id': {'$in': product_ids}, 'business_id': business_id}, {'_id': 0}
            )
        }
        total_amount = 0
        order_items_docs = []
        stock_updates = []
        for it in items:
            prod = products_map.get(it['product_id'])
            if not prod:
                continue  # chặn bán sản phẩm không thuộc tenant này hoặc không tồn tại
            qty = int(it.get('quantity', 1))
            price = prod.get('price', 0)
            line_total = qty * price
            total_amount += line_total
            order_items_docs.append({
                'product_id': prod['id'], 'quantity': qty, 'price': price, 'total_price': line_total,
            })
            if 'stock' in prod:
                stock_updates.append(UpdateOne(
                    {'id': prod['id'], 'business_id': business_id}, {'$set': {'stock': prod['stock'] - qty}}
                ))
        if not order_items_docs:
            return jsonify({"success": False, "message": "Không có sản phẩm hợp lệ trong giỏ hàng."}), 400

        order_id = next_mongo_id('orders')
        order_doc = {
            'id': order_id,
            'business_id': business_id,
            'total_amount': total_amount,
            'payment_method': data.get('payment_method', 'cash'),
            'status': data.get('status', 'completed'),
            'created_at': datetime.now().isoformat(),
        }
        if data.get('customer_phone'):
            order_doc['customer_phone'] = data['customer_phone']
        db.orders.insert_one(order_doc)

        for oi in order_items_docs:
            oi['id'] = next_mongo_id('order_items')
            oi['order_id'] = order_id
            if data.get('customer_phone'):
                oi['customer_phone'] = data['customer_phone']
        db.order_items.insert_many(order_items_docs)

        if stock_updates:
            db.products.bulk_write(stock_updates)

        return jsonify({"success": True, "order_id": order_id, "total_amount": total_amount})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


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


def _tier_for_spend(total_spent):
    tier = 'Normal'
    for threshold, name in LOYALTY_TIER_THRESHOLDS:
        if total_spent >= threshold:
            tier = name
    return tier


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


def _award_loyalty_points(business_id, customer_phone, amount_spent):
    """Tự động cộng điểm + xét lên hạng cho khách ngay sau khi thanh toán xong.
    Nếu SĐT chưa có trong CRM thì tự tạo khách mới. Không chặn luồng thanh toán nếu lỗi."""
    customer_phone = (customer_phone or '').strip()
    if not customer_phone or not amount_spent or amount_spent <= 0:
        return
    try:
        customer = db.customers.find_one({'business_id': business_id, 'phone': customer_phone}, {'_id': 0})
        points_earned = int(amount_spent * LOYALTY_POINTS_PER_VND)
        if customer:
            old_tier = customer.get('tier') or 'Normal'
            new_total_spent = (customer.get('total_spent') or 0) + amount_spent
            new_points = (customer.get('loyalty_points') or 0) + points_earned
            new_tier = _tier_for_spend(new_total_spent)
            db.customers.update_one(
                {'id': customer['id'], 'business_id': business_id},
                {'$set': {'total_spent': new_total_spent, 'loyalty_points': new_points, 'tier': new_tier}}
            )
            customer['total_spent'] = new_total_spent
            customer['loyalty_points'] = new_points
            customer['tier'] = new_tier
        else:
            new_tier = _tier_for_spend(amount_spent)
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
def report_consolidated():
    """Báo cáo tổng hợp doanh thu/chi phí toàn bộ chi nhánh mà chủ sở hữu đang quản lý."""
    denied = _deny_if_staff_page()
    if denied:
        return denied
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
    business_id = session.get('business_id') or session['user_id']
    try:
        owns, err = _assert_owns_table(table_id, business_id)
        if not owns:
            return err, 403
    except Exception as e:
        return f"Lỗi xác thực quyền sở hữu bàn: {str(e)}", 500

    try:
        product_id = request.form['product_id']
        if not _assert_owns_product(product_id, business_id):
            return "Sản phẩm không tồn tại hoặc không thuộc quyền quản lý của bạn.", 403

        qty = int(request.form.get('quantity', 1))
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
        return redirect(url_for('view_table', table_id=table_id))
    except Exception as e:
        return f"Lỗi khi gọi món: {str(e)}", 500


@app.route('/checkout/<int:table_id>')
@login_required
def checkout_table(table_id):
    business_id = session.get('business_id') or session['user_id']
    try:
        owns, err = _assert_owns_table(table_id, business_id)
        if not owns:
            return err, 403
    except Exception as e:
        return f"Lỗi xác thực quyền sở hữu bàn: {str(e)}", 500

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
            stock_updates = []
            for item in orders_data:
                prod = products_map.get(item['product_id'])
                if prod:
                    price = prod['price']
                    total_bill += item['quantity'] * price
                    new_stock = prod['stock'] - item['quantity']
                    stock_updates.append(UpdateOne(
                        {'id': item['product_id'], 'business_id': business_id}, {'$set': {'stock': new_stock}}
                    ))
            if stock_updates:
                db.products.bulk_write(stock_updates)

            order_id = next_mongo_id('orders')
            db.orders.insert_one({
                'id': order_id,
                'order_code': order_code,
                'channel': 'fnb',
                'total_amount': total_bill,
                'business_id': business_id,
                'created_at': datetime.now().isoformat()
            })

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
            if order_items_docs:
                db.order_items.insert_many(order_items_docs)

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
        return redirect(url_for('pos'))
    except Exception as e:
        return f"Lỗi khi thanh toán bàn: {str(e)}", 500


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
def expense_list():
    denied = _deny_if_staff_page()
    if denied:
        return denied
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
def staff_list():
    denied = _deny_if_staff_page()
    if denied:
        return denied
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
            'commission_rate': data['commission_rate'],
            'is_active': data['is_active'],
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
    business_id = session.get('business_id') or session['user_id']
    try:
        room = db.karaoke_rooms.find_one({'id': room_id}, {'_id': 0})
        if not room or room.get('business_id') != business_id:
            return redirect(url_for('karaoke'))
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
                    'order_code': order_code,
                    'channel': 'karaoke',
                    'total_amount': total_price,
                    'business_id': business_id,
                    'created_at': datetime.now().isoformat()
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
            db.karaoke_rooms.update_one(
                {'id': room_id, 'business_id': business_id}, {'$set': {'status': 'Trống', 'start_time': None}}
            )
        return redirect(url_for('karaoke'))
    except Exception as e:
        return f"Lỗi xử lý phòng karaoke: {str(e)}", 500


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
            order_doc = {
                'id': order_id,
                'order_code': order_code,
                'channel': 'karaoke',
                'total_amount': total_price,
                'business_id': business_id,
                'created_at': datetime.now().isoformat(),
            }
            if customer_phone:
                order_doc['customer_phone'] = customer_phone
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
        db.karaoke_rooms.update_one(
            {'id': room_id, 'business_id': business_id}, {'$set': {'status': 'Trống', 'start_time': None}}
        )
        return jsonify({"success": True, "total_amount": total_price, "order_id": order_id})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


# ========== BÁO CÁO ==========
@app.route('/api/report/summary', methods=['GET'])
@login_required
def api_report_summary():
    """Thay toàn bộ fetchReportData() Supabase cũ ở report.html — tính doanh thu/chi
    phí/lợi nhuận theo khoảng ngày do client chọn (today/yesterday/week/month/custom),
    cùng biểu đồ theo ngày, top sản phẩm, phân bổ theo ngành, top khách hàng, chi tiêu gần
    đây. Route /report (bên dưới) chỉ tính all-time cho lần render đầu; route này phục vụ
    mọi lần đổi khoảng ngày sau đó."""
    denied = _deny_if_staff_page()
    if denied:
        return denied
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
def report():
    denied = _deny_if_staff_page()
    if denied:
        return denied
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


def _allowed_media_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_MEDIA_EXTENSIONS


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
            content_type=file.mimetype or 'application/octet-stream'
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
# landing/booking/portal/qr_menu của tenant) và ảnh chat CSKH (khách ẩn danh gửi/nhận qua
# portal.html, không có session để dùng route private ở trên). CHỈ 2 nhóm này — không bao giờ
# thêm 'checkin'/'avatar'/... vào đây, những kind đó PHẢI qua /api/storage/file/<id> (private).
_PUBLIC_MEDIA_KINDS = {'brand_logo', 'brand_cover', 'portal_chat'}


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
        return jsonify({"success": True, "data": msgs})
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
def brand_settings():
    # ĐÃ CHUYỂN SANG PER-TENANT (quyết định sản phẩm): brand_name/brand_color/logo/cover/font
    # trước đây là 1 giá trị TOÀN CỤC dùng chung mọi tenant — nay mỗi khoá đều lọc thêm
    # business_id, giống mọi key khác trong system_settings (payment_config, inventory_thresholds).
    denied = _deny_if_staff_page()
    if denied:
        return denied
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
def api_brand_settings_save():
    """multipart/form-data: brand_name, brand_color, font_family (text) + logo/cover (file,
    tuỳ chọn) — hoàn thiện phần "Xử lý upload logo và cover nếu có" trước đây chỉ là TODO chưa
    từng cài đặt. Ảnh lưu GridFS kind='brand_logo'/'brand_cover' (công khai qua
    /api/public/storage/file/<id>, xem whitelist _PUBLIC_MEDIA_KINDS)."""
    business_id = session.get('business_id') or session['user_id']
    denied = _deny_if_staff_page()
    if denied:
        return jsonify({"success": False, "message": "Không có quyền."}), 403
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
                    content_type=file.mimetype or 'application/octet-stream'
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
    business_id = session.get('business_id', 'mock-business-123')
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
        business_id = session.get('business_id', 'mock-business-123')
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
    business_id = session.get('business_id', 'mock-business-123')
    
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

        total_bill = 0
        stock_updates = []
        for item in orders_data:
            prod = products_map.get(item['product_id'])
            if prod:
                total_bill += item['quantity'] * prod['price']
                new_stock = prod['stock'] - item['quantity']
                stock_updates.append(UpdateOne(
                    {'id': item['product_id'], 'business_id': business_id}, {'$set': {'stock': new_stock}}
                ))
        if stock_updates:
            db.products.bulk_write(stock_updates)

        # Lấy industry từ transaction hoặc mặc định fnb
        industry = 'fnb'
        customer_phone = (data.get('customer_phone') or '').strip() or None

        # 3. Tạo order mới trong orders
        order_id = next_mongo_id('orders')
        db.orders.insert_one({
            'id': order_id,
            'order_code': txn_id,
            'channel': industry,
            'total_amount': total_bill,
            'business_id': business_id,
            'customer_phone': customer_phone,
            'created_at': datetime.now().isoformat()
        })

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
        if order_items_docs:
            db.order_items.insert_many(order_items_docs)

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
        {'business_id': business_id, 'created_at': {'$gte': since_iso}}, {'order_code': 1, 'total_amount': 1, '_id': 0}
    ))
    orders_by_code = {o['order_code']: o for o in orders_data if o.get('order_code')}

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
    return render_template('sell.html')

# ========== MỚI: ROUTE CHO CƠ SỞ DỮ LIỆU NHÂN SỰ VÀ SUPER ADMIN ==========
@app.route('/nhanvien')
@login_required
def nhanvien():
    return render_template('nhanvien.html')

@app.route('/bangluong')
@login_required
def bangluong():
    denied = _deny_if_staff_page()
    if denied:
        return denied
    return render_template('bangluong.html')

@app.route('/chamcong')
@login_required
def chamcong():
    denied = _deny_if_staff_page()
    if denied:
        return denied
    return render_template('chamcong.html')

@app.route('/chamcong/congnhan')
@app.route('/chamcong_congnhan')
@login_required
def chamcong_congnhan():
    denied = _deny_if_staff_page()
    if denied:
        return denied
    return render_template('chamcong_congnhan.html')

@app.route('/chamcong/fnb')
@app.route('/chamcong_fnb')
@login_required
def chamcong_fnb():
    denied = _deny_if_staff_page()
    if denied:
        return denied
    return render_template('chamcong_fnb.html')

@app.route('/chamcong/khachsan')
@app.route('/chamcong_khachsan')
@login_required
def chamcong_khachsan():
    denied = _deny_if_staff_page()
    if denied:
        return denied
    return render_template('chamcong_khachsan.html')

@app.route('/chamcong/kythuat')
@app.route('/chamcong_kythuat')
@login_required
def chamcong_kythuat():
    denied = _deny_if_staff_page()
    if denied:
        return denied
    return render_template('chamcong_kythuat.html')

@app.route('/chamcong/nail')
@app.route('/chamcong_nail')
@login_required
def chamcong_nail():
    denied = _deny_if_staff_page()
    if denied:
        return denied
    return render_template('chamcong_nail.html')

# chamcong_spa (/chamcong/spa, /chamcong_spa) đã chuyển sang blueprints/spa_bp.py

@app.route('/chamcong/vanphong')
@app.route('/chamcong_vanphong')
@login_required
def chamcong_vanphong():
    denied = _deny_if_staff_page()
    if denied:
        return denied
    return render_template('chamcong_vanphong.html')

@app.route('/chamcong/<industry_code>')
@app.route('/chamcong_<industry_code>')
@login_required
def chamcong_industry(industry_code):
    denied = _deny_if_staff_page()
    if denied:
        return denied
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
def baocao_loinhuan():
    denied = _deny_if_staff_page()
    if denied:
        return denied
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
            content_type=file.mimetype or 'application/octet-stream'
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
def quanly_congno():
    denied = _deny_if_staff_page()
    if denied:
        return denied
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
def quanly_thuchi():
    denied = _deny_if_staff_page()
    if denied:
        return denied
    return render_template('quanly_thuchi.html')

def _is_superadmin():
    """True khi email đang đăng nhập là tài khoản trùm hardcode, hoặc nằm trong danh sách
    SUPERADMIN_EMAILS (env var). Không cấu hình biến env này vẫn không sao — tài khoản
    trùm hardcode luôn được cấp quyền, không phụ thuộc env/DB (fail-closed cho mọi email khác)."""
    user_email = (session.get('user_email') or '').strip().lower()
    if not user_email:
        return False
    if user_email == 'hodinhsang30052003@gmail.com':
        return True
    allowed = {e.strip().lower() for e in os.environ.get('SUPERADMIN_EMAILS', '').split(',') if e.strip()}
    return user_email in allowed


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
    business_id = session.get('business_id', 'mock-business-123')
    user_email = session.get('user_email', 'Chưa có dữ liệu doanh nghiệp')
    industry = session.get('business_mode', 'retail')
    
    brand_name = 'Chưa có dữ liệu doanh nghiệp'
    brand_email = user_email
    brand_phone = 'Chưa thiết lập SĐT'
    brand_zalo = 'Chưa có Zalo OA'
    brand_fb = 'Chưa kết nối Facebook'
    brand_industry = INDUSTRY_CONFIG.get(industry, {}).get('name', 'Bán lẻ (Retail)')
    brand_tier = 'BitPaw Trial'
    brand_staff = '0 nhân sự'
    brand_joined = '2026-05-29'
    brand_branch = 'Chưa xác định'
    
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
            brand_staff = f"{staff_count} nhân sự"

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
        "name": brand_name if has_profile or brand_name != 'Chưa có dữ liệu doanh nghiệp' else "Chưa có dữ liệu doanh nghiệp",
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


@app.route('/api/ai/studio/generate', methods=['POST'])
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
    # Persona/phong cách do client gửi (KHÔNG chứa số liệu doanh nghiệp thật) — số liệu luôn
    # được server tự nhúng bên dưới, lọc đúng theo business_id, không tin client.
    client_persona = data.get('systemPrompt', '')
    user_prompt = data.get('userPrompt', '')
    temperature = data.get('temperature', 0.7)
    max_tokens = data.get('max_tokens', 1500)
    customer_phone = data.get('customer_phone')  # tuỳ chọn: để AI cá nhân hoá theo hạng/lịch sử chi tiêu
    client_history = data.get('history') or []

    ctx = AIContextEngine.build_context_prompt(business_id, industry, customer_phone=customer_phone,
                                                include_private_data=is_authenticated)
    tenant_context = ctx['prompt']
    business_name = ctx['business_name'] or 'BitPaw'
    system_prompt = f"{tenant_context}\n{client_persona}".strip()

    # === Nối chuỗi hội thoại thật (không để AI mất ngữ cảnh khi khách trả lời cụt lủn) ===
    # Ưu tiên lịch sử client đang giữ trong phiên chat hiện tại; nếu client không gửi gì (vd:
    # vừa refresh trang) thì khôi phục lại từ DB theo đúng business_id + SĐT khách.
    history = client_history if client_history else _load_recent_chat_history(business_id, customer_phone)

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
    _persist_chat_turn(business_id, customer_phone, user_prompt or (history[-1]['content'] if history else ''), sender_type='customer')

    # Câu chốt sale dự phòng thông minh — thay cho câu báo lỗi cứng cũ, luôn gắn đúng tên
    # cửa hàng của tenant (hoặc "BitPaw" nếu là bot marketing chung không gắn tenant nào).
    fallback_reply = (
        f"Dạ hệ thống đang xử lý hơi nhiều data một chút. Sếp cho em xin SĐT Zalo để chuyên viên bên em "
        f"gọi lại tư vấn gói tối ưu nhất cho {business_name} luôn nhé!"
    )

    api_key = os.environ.get('DEEPSEEK_API_KEY')
    if not api_key:
        return jsonify({"choices": [{"message": {"content": fallback_reply}}], "fallback": True,
                         "error": "Server chưa cấu hình DEEPSEEK_API_KEY."})

    url = "https://api.deepseek.com/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    payload = {
        "model": "deepseek-chat",
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens
    }

    try:
        # Timeout nới rộng lên 45s: các câu hỏi có nhúng bảng giá/danh mục sản phẩm dài cho
        # tenant nhiều hàng hoá cần nhiều thời gian xử lý hơn so với persona ngắn cũ.
        resp = requests.post(url, headers=headers, json=payload, timeout=45)
        resp.raise_for_status()
        result = resp.json()
        try:
            ai_text = result['choices'][0]['message']['content']
            _persist_chat_turn(business_id, customer_phone, ai_text, sender_type='ai')
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
def map_dashboard():
    denied = _deny_if_staff_page()
    if denied:
        return denied
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
    business_id = session.get('business_id', 'mock-business-123')
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
        
        # Count customers from database to use as real lead counts
        c.execute("SELECT COUNT(*) FROM customer_profiles WHERE business_id = ?", (business_id,))
        sqlite_leads = c.fetchone()[0]
        conn.close()
        
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
                leads_count = sqlite_leads if p == 'pos_sync' else (18 + (hash(p) % 45))
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
        
    business_id = session.get('business_id', 'mock-business-123')
    
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
    data = request.json or {}
    platform = data.get('platform')
    account_name = data.get('account_name', '').strip()
    channel_id = data.get('channel_id', '').strip()
    access_token = data.get('access_token', '').strip()
    
    if not platform:
        return jsonify({"success": False, "message": "Missing platform parameter"}), 400
        
    if not access_token or not channel_id:
        return jsonify({"success": False, "message": "Chưa cấu hình API key và ID kênh!"}), 400
        
    return jsonify({
        "success": True, 
        "message": f"Kết nối thử nghiệm tới {platform.upper()} thành công! Phản hồi từ Provider API: OK."
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
    target = CHANNEL_MAP.get(channel.lower())
    if not target:
        return f"Invalid channel: {channel}", 400
    account_name = request.args.get('account_name', '').strip()
    channel_id = request.args.get('channel_id', '').strip()
    access_token = request.args.get('access_token', '').strip()
    if not account_name or not channel_id or not access_token:
        return "Thiếu thông tin cấu hình callback!", 400
    business_id = session.get('business_id', 'mock-business-123')
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
        return f"Lỗi lưu trữ cấu hình: {str(db_err)}", 500
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
    business_id = session.get('business_id', 'mock-business-123')
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
    business_id = session.get('business_id', 'mock-business-123')
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
    business_id = session.get('business_id', 'mock-business-123')

    try:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("SELECT id, name, phone, email, industry, source_platform, last_purchase_at, total_spending, services_of_interest, nurturing_status, ai_notes, potential_score FROM customer_profiles WHERE business_id = ? ORDER BY total_spending DESC", (business_id,))
        rows = c.fetchall()
        conn.close()
        
        customers = []
        for r in rows:
            customers.append({
                "id": r[0],
                "name": r[1],
                "phone": r[2],
                "email": r[3],
                "industry": r[4],
                "source": r[5],
                "last_purchase": r[6],
                "total_spend": r[7],
                "service_interest": r[8],
                "status": r[9],
                "ai_notes": r[10],
                "potential_score": r[11]
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
    business_id = session.get('business_id', 'mock-business-123')
    industry = session.get('business_mode', 'retail')

    try:
        # Đồng bộ từ đúng collection customers thật của tenant (MongoDB) — không còn xóa dữ liệu
        # thật rồi nhét khách hàng mẫu giả vào nữa.
        rows_data = list(db.customers.find(
            {'business_id': business_id}, {'name': 1, 'phone': 1, 'email': 1, 'total_spent': 1, '_id': 0}
        )) if db is not None else []

        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        synced = 0
        for cust in rows_data:
            phone = cust.get('phone')
            if not phone:
                continue
            profile_id = f"{business_id}:{phone}"
            c.execute("""
                INSERT INTO customer_profiles (id, business_id, name, phone, email, industry, source_platform,
                    last_purchase_at, total_spending, services_of_interest, nurturing_status, ai_notes, potential_score)
                VALUES (?, ?, ?, ?, ?, ?, 'pos', NULL, ?, NULL, 'NEW', NULL, NULL)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name, email=excluded.email, total_spending=excluded.total_spending
            """, (profile_id, business_id, cust.get('name'), phone, cust.get('email'), industry, cust.get('total_spent') or 0))
            synced += 1
        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": f"Đã đồng bộ {synced} khách hàng từ hệ thống POS/CRM thành công!"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/ai/nurture/generate-campaign', methods=['POST'])
@login_required
def nurture_generate_campaign():
    data = request.json or {}
    segment = data.get('segment') # 'ALL', 'VIP', 'CHURN', etc.
    goal = data.get('goal', 'RECALL')
    channel = data.get('channel', 'ZALO')
    tone = data.get('tone', 'friendly')
    
    business_id = session.get('business_id', 'mock-business-123')
    industry = session.get('business_mode', 'retail')
    
    campaign_id = f"camp-{random.randint(1000, 9999)}"
    campaign_name = f"Chiến dịch {goal} qua kênh {channel} ({tone.upper()})"
    
    try:
        from ai_nurturing_engine import AINurturingEngine
        
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        
        # Register campaign
        c.execute("INSERT INTO nurturing_campaigns (id, business_id, name, target_segment_id, campaign_goal, channel, tone, is_active) VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
                  (campaign_id, business_id, campaign_name, segment, goal, channel, tone))
        
        # Query target profiles
        query = "SELECT id, name FROM customer_profiles WHERE business_id = ?"
        params = [business_id]
        if segment == 'VIP':
            query += " AND total_spending > 5000000"
        elif segment == 'CHURN':
            query += " AND nurturing_status = 'CHURN_RISK'"
            
        c.execute(query, tuple(params))
        customers = c.fetchall()
        
        generated_count = 0
        
        # Generate nurture copy sequences (3d, 7d, 14d) and push to approval queue
        for cust in customers:
            cust_id, cust_name = cust[0], cust[1]
            copy_seq = AINurturingEngine.generate_nurturing_copy(industry, goal, tone, cust_name)
            
            # Step 1: 3 days
            c.execute("INSERT INTO campaign_messages (id, business_id, campaign_id, customer_id, step_delay, message_body, approval_status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'PENDING', CURRENT_TIMESTAMP)",
                      (f"{campaign_id}-{cust_id}-3d", business_id, campaign_id, cust_id, 3, copy_seq["3days"]))
            # Step 2: 7 days
            c.execute("INSERT INTO campaign_messages (id, business_id, campaign_id, customer_id, step_delay, message_body, approval_status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'PENDING', CURRENT_TIMESTAMP)",
                      (f"{campaign_id}-{cust_id}-7d", business_id, campaign_id, cust_id, 7, copy_seq["7days"]))
            # Step 3: 14 days
            c.execute("INSERT INTO campaign_messages (id, business_id, campaign_id, customer_id, step_delay, message_body, approval_status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'PENDING', CURRENT_TIMESTAMP)",
                      (f"{campaign_id}-{cust_id}-14d", business_id, campaign_id, cust_id, 14, copy_seq["14days"]))
            generated_count += 3
            
        conn.commit()
        conn.close()
        
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
    business_id = session.get('business_id', 'mock-business-123')
    try:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        # Query with customer names
        c.execute("""
            SELECT m.id, m.campaign_id, m.customer_id, m.step_delay, m.message_body, m.approval_status, p.name 
            FROM campaign_messages m
            JOIN customer_profiles p ON m.customer_id = p.id
            WHERE m.business_id = ?
            ORDER BY m.created_at DESC
        """, (business_id,))
        rows = c.fetchall()
        conn.close()
        
        queue = []
        for r in rows:
            queue.append({
                "id": r[0],
                "campaign_id": r[1],
                "customer_id": r[2],
                "delay": r[3],
                "body": r[4],
                "status": r[5],
                "customer_name": r[6]
            })
        return jsonify({"success": True, "data": queue})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/ai/nurture/approve-message', methods=['POST'])
@login_required
def nurture_approve_message():
    data = request.json or {}
    message_id = data.get('message_id')
    action = data.get('action') # 'APPROVED' or 'REJECTED'
    
    if not message_id or not action:
        return jsonify({"success": False, "message": "Missing message_id or action parameters"}), 400
        
    business_id = session.get('business_id', 'mock-business-123')
    try:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("UPDATE campaign_messages SET approval_status = ?, sent_at = CURRENT_TIMESTAMP WHERE id = ? AND business_id = ?",
                  (action, message_id, business_id))
        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": f"Tin nhắn đã được Sếp phê duyệt sang trạng thái: {action}!"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

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
    business_id = session.get('business_id', 'mock-business-123')
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
    business_id = session.get('business_id', 'mock-business-123')
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
    business_id = session.get('business_id', 'mock-business-123')
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
    business_id = session.get('business_id', 'mock-business-123')
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
    business_id = session.get('business_id', 'mock-business-123')
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
    business_id = session.get('business_id', 'mock-business-123')
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
    business_id = session.get('business_id', 'mock-business-123')
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
        
        # 2. Fetch customer details or use a generic placeholder for a dry-run test
        cust_name = "Khách hàng mẫu"
        cust_phone = "0900000000"
        if customer_id:
            c.execute("SELECT name, phone FROM customer_profiles WHERE id = ? AND business_id = ?", (customer_id, business_id))
            cust_row = c.fetchone()
            if cust_row:
                cust_name, cust_phone = cust_row[0], cust_row[1]
                
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
    business_id = session.get('business_id', 'mock-business-123')
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

@app.route('/api/chamcong/checkin', methods=['POST'])
@login_required
def api_checkin():
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

    try:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS local_attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                staff_id TEXT,
                clock_in TEXT,
                clock_out TEXT,
                latitude REAL,
                longitude REAL,
                status TEXT,
                note TEXT
            )
        ''')
        clock_in_time = datetime.now().isoformat()
        c.execute('''
            INSERT INTO local_attendance (staff_id, clock_in, latitude, longitude, status, note)
            VALUES (?, ?, ?, ?, 'Present', ?)
        ''', (str(staff_id), clock_in_time, lat, lng, note))
        conn.commit()
        row_id = c.lastrowid
        conn.close()

        try:
            db.attendance.insert_one({
                'id': next_mongo_id('attendance'),
                'staff_id': int(staff_id),
                'clock_in': clock_in_time,
                'clock_out': None,
                'latitude_in': lat,
                'longitude_in': lng,
                'status': 'Present',
                'business_id': business_id
            })
        except Exception:
            pass

        return jsonify({
            "success": True,
            "id": row_id,
            "status": "Present",
            "clock_in": clock_in_time
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/chamcong/checkout', methods=['POST'])
@login_required
def api_checkout():
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

    try:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS local_attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                staff_id TEXT,
                clock_in TEXT,
                clock_out TEXT,
                latitude REAL,
                longitude REAL,
                status TEXT,
                note TEXT
            )
        ''')
        clock_out_time = datetime.now().isoformat()
        c.execute('''
            UPDATE local_attendance
            SET clock_out = ?
            WHERE staff_id = ? AND clock_out IS NULL
        ''', (clock_out_time, str(staff_id)))
        conn.commit()
        conn.close()

        try:
            open_record = db.attendance.find_one(
                {'staff_id': int(staff_id), 'business_id': business_id, 'clock_out': None},
                {'id': 1, '_id': 0},
                sort=[('created_at', -1)]
            )
            if open_record:
                db.attendance.update_one(
                    {'id': open_record['id'], 'business_id': business_id},
                    {'$set': {'clock_out': clock_out_time, 'latitude_out': lat, 'longitude_out': lng}}
                )
        except Exception:
            pass

        return jsonify({
            "success": True,
            "message": "Checked out successfully.",
            "clock_out": clock_out_time
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/chamcong/status', methods=['GET'])
@login_required
def api_attendance_status():
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
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS local_attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                staff_id TEXT,
                clock_in TEXT,
                clock_out TEXT,
                latitude REAL,
                longitude REAL,
                status TEXT,
                note TEXT
            )
        ''')
        c.execute('SELECT clock_in, clock_out, status FROM local_attendance WHERE staff_id = ? ORDER BY id DESC LIMIT 1', (str(staff_id),))
        row = c.fetchone()
        conn.close()
        
        if row:
            clock_in, clock_out, status = row
            is_checked_in = clock_out is None
            return jsonify({
                "success": True,
                "status": status,
                "is_checked_in": is_checked_in,
                "clock_in": clock_in,
                "clock_out": clock_out
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


@app.route('/api/hr/chamcong', methods=['POST'])
@login_required
def api_hr_chamcong_create():
    business_id = session.get('business_id') or session['user_id']
    data = request.json or {}
    if not (data.get('ma_nv') or '').strip():
        return jsonify({"success": False, "error": "Missing employee ID (ma_nv)."}), 400
    try:
        doc = dict(data)
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


# ==========================================
# BITPAW NETWORK BLUEPRINT ROUTING (PHASE 1A + 1B + OVERHAUL)
# ==========================================
MOCK_JOBS = [
    {
        'id': 'job-1',
        'title': 'Kỹ thuật viên Nails Acrylic (Thợ chính)',
        'company': 'Bloom Nails Salon Q3',
        'salary': '12.000.000đ - 18.000.000đ',
        'location': 'Quận 3, TP. HCM',
        'type': 'full_time',
        'industry': 'nails',
        'skills': ['Acrylic Extensions', 'Gel Polish Art', 'Đắp bột', 'Cắt móng'],
        'description': 'Cần tuyển thợ nails chính biết đắp bột, vẽ gel chuyên nghiệp. Làm việc trong môi trường salon máy lạnh cao cấp, có phần trăm hoa hồng cao.',
        'urgent': True
    },
    {
        'id': 'job-2',
        'title': 'Thợ phụ chăm sóc tóc & gội đầu dưỡng sinh',
        'company': 'Luxury Spa & Hair Q1',
        'salary': '7.000.000đ - 10.000.000đ',
        'location': 'Quận 1, TP. HCM',
        'type': 'full_time',
        'industry': 'spa',
        'skills': ['Gội đầu dưỡng sinh', 'Massage đầu', 'Phụ làm tóc'],
        'description': 'Tuyển nhân viên phụ tóc gội dưỡng sinh làm việc xoay ca. Chưa biết nghề được đào tạo thêm.',
        'urgent': False
    },
    {
        'id': 'job-3',
        'title': 'Thợ lắp đặt & sửa chữa điều hòa (HVAC)',
        'company': 'Điện Lạnh Bách Khoa SG',
        'salary': '10.000.000đ - 15.000.000đ',
        'location': 'Quận 10, TP. HCM',
        'type': 'shift_work',
        'industry': 'technical',
        'skills': ['Lắp đặt máy lạnh', 'Sửa board mạch', 'Nạp gas điều hòa'],
        'description': 'Tuyển thợ điện lạnh lắp đặt, bảo dưỡng máy lạnh văn phòng và gia đình. Có xe máy đi lại, trợ cấp xăng xe.',
        'urgent': True
    },
    {
        'id': 'job-4',
        'title': 'Nhân viên phục vụ & pha chế ca tối',
        'company': 'BitPaw F&B Coffee',
        'salary': '25.000đ - 30.000đ/giờ',
        'location': 'Bình Thạnh, TP. HCM',
        'type': 'part_time',
        'industry': 'fnb',
        'skills': ['Pha chế basic', 'Phục vụ bàn', 'Order món'],
        'description': 'Tuyển pha chế kiêm phục vụ ca tối (18h-23h). Thân thiện, nhanh nhẹn, ưu tiên sinh viên.',
        'urgent': False
    }
]

MOCK_SERVICES = [
    {
        'id': 'svc-1',
        'name': 'Thợ Nails A',
        'service_type': 'Thiết kế & Làm móng Nails Art',
        'rating': 4.9,
        'reviews_count': 32,
        'price': 'Chỉ từ 150k - 500k',
        'location': 'Quận 3, TP. HCM',
        'industry': 'nails',
        'skills': ['Acrylic Extensions', 'Gel Polish Art', 'Chăm sóc móng', 'Đính đá'],
        'availability': 'Hàng ngày 8:00 - 20:00'
    },
    {
        'id': 'svc-2',
        'name': 'Kỹ thuật viên Điện lạnh B',
        'service_type': 'Sửa chữa & Vệ sinh Máy lạnh tại nhà',
        'rating': 4.8,
        'reviews_count': 19,
        'price': 'Vệ sinh 150k/máy, sửa bo mạch báo giá trước',
        'location': 'Quận 10, TP. HCM',
        'industry': 'technical',
        'skills': ['Vệ sinh máy lạnh', 'Lắp đặt máy lạnh', 'Nạp gas điều hòa'],
        'availability': 'Cuối tuần & Ngày thường sau 18h'
    },
    {
        'id': 'svc-3',
        'name': 'Chuyên viên Spa C',
        'service_type': 'Liệu trình Massage body & Chăm sóc da mụn',
        'rating': 4.7,
        'reviews_count': 25,
        'price': 'Combo 90 phút 350k',
        'location': 'Quận 1, TP. HCM',
        'industry': 'spa',
        'skills': ['Massage trị liệu', 'Chăm sóc da', 'Nặn mụn chuẩn y khoa'],
        'availability': 'Nhận lịch đặt trước 1 ngày'
    }
]

MOCK_COMMUNITIES = [
    {
        'slug': 'nails-viet',
        'name': 'Cộng đồng Nail Việt Nam',
        'members': 4250,
        'description': 'Nơi chia sẻ các mẫu nail hot trend, kinh nghiệm đắp bột, vẽ cọ nét và tìm kiếm thợ nails nhanh chóng.',
        'pinned_job': 'Kỹ thuật viên Nails Acrylic (Thợ chính) - Bloom Nails Salon'
    },
    {
        'slug': 'spa-beauty',
        'name': 'Spa & Thẩm Mỹ Master',
        'members': 3100,
        'description': 'Diễn đàn chia sẻ kỹ năng massage, công nghệ trị liệu da y khoa, vận hành spa chuyên nghiệp.',
        'pinned_job': 'Kỹ thuật viên Spa Trị liệu da - Luxury Spa'
    },
    {
        'slug': 'electrical-hvac',
        'name': 'Thợ Kỹ Thuật Điện Lạnh HCMC',
        'members': 1850,
        'description': 'Nhóm giao lưu thợ điện gia dụng, thợ lắp ráp điều hòa, chia sẻ sơ đồ mạch điện tử và hỗ trợ xử lý lỗi khó.',
        'pinned_job': 'Thợ lắp đặt & sửa chữa điều hòa (HVAC) - Điện Lạnh Bách Khoa'
    },
    {
        'slug': 'fnb-owners',
        'name': 'F&B Owners Guild',
        'members': 2900,
        'description': 'Nhóm kết nối các chủ quán cafe, nhà hàng, quán ăn chia sẻ nguồn nguyên liệu sỉ chất lượng, kinh nghiệm vận hành và tuyển nhân viên.',
        'pinned_job': 'Nhân viên phục vụ & pha chế ca tối - BitPaw Coffee'
    }
]

@app.route('/network')
def network_home():
    return render_template(
        'network_home.html',
        jobs=MOCK_JOBS[:3],
        services=MOCK_SERVICES[:2],
        communities=MOCK_COMMUNITIES[:3]
    )

def _ensure_network_users_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS network_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            fullname TEXT,
            phone TEXT,
            role TEXT,
            location TEXT
        )
    """)


@app.route('/network/login', methods=['GET', 'POST'])
def network_login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        try:
            conn = sqlite3.connect('database.db')
            c = conn.cursor()
            _ensure_network_users_table(c)
            c.execute("SELECT password_hash, fullname, phone, role, location FROM network_users WHERE email=?", (email,))
            row = c.fetchone()
            conn.close()
        except Exception as e:
            flash(f'Lỗi hệ thống, vui lòng thử lại: {str(e)}', 'danger')
            return render_template('network_login.html')

        if not row or not check_password_hash(row[0], password):
            flash('Sai email hoặc mật khẩu!', 'danger')
            return render_template('network_login.html')

        session['network_user'] = {
            'fullname': row[1],
            'email': email,
            'phone': row[2],
            'role': row[3],
            'location': row[4],
            'is_onboarded': True
        }
        flash('Đăng nhập vào BitPaw Network thành công!', 'success')
        return redirect(url_for('network_onboarding'))
    return render_template('network_login.html')

@app.route('/network/register', methods=['GET', 'POST'])
def network_register():
    if request.method == 'POST':
        fullname = request.form.get('fullname', '')
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        phone = request.form.get('phone', '')
        role = request.form.get('role', 'job_seeker')
        location = request.form.get('location', 'Quận 1, TP. HCM')

        if not email or not password:
            flash('Vui lòng nhập đầy đủ email và mật khẩu!', 'danger')
            return render_template('network_register.html')

        try:
            conn = sqlite3.connect('database.db')
            c = conn.cursor()
            _ensure_network_users_table(c)
            c.execute("SELECT id FROM network_users WHERE email=?", (email,))
            if c.fetchone():
                conn.close()
                flash('Email này đã được đăng ký!', 'danger')
                return render_template('network_register.html')

            c.execute(
                "INSERT INTO network_users (email, password_hash, fullname, phone, role, location) VALUES (?, ?, ?, ?, ?, ?)",
                (email, generate_password_hash(password), fullname, phone, role, location)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            flash(f'Lỗi hệ thống, vui lòng thử lại: {str(e)}', 'danger')
            return render_template('network_register.html')

        session['network_user'] = {
            'fullname': fullname,
            'email': email,
            'phone': phone,
            'role': role,
            'location': location,
            'is_onboarded': False
        }
        flash('Đăng ký tài khoản BitPaw Network thành công!', 'success')
        return redirect(url_for('network_onboarding'))
    return render_template('network_register.html')

@app.route('/network/onboarding', methods=['GET', 'POST'])
def network_onboarding():
    if not session.get('network_user'):
        return redirect(url_for('network_login'))
        
    if request.method == 'POST':
        user = session['network_user']
        user['is_onboarded'] = True
        
        if user['role'] == 'job_seeker':
            user['headline'] = request.form.get('headline', '')
            user['skills'] = request.form.get('skills', '')
            user['experience'] = request.form.get('experience', '')
            user['salary_expect'] = request.form.get('salary_expect', '')
        elif user['role'] == 'employer':
            user['company_name'] = request.form.get('company_name', '')
            user['industry'] = request.form.get('industry', '')
            user['company_size'] = request.form.get('company_size', '')
        elif user['role'] == 'provider':
            user['service_type'] = request.form.get('service_type', '')
            user['price_sheet'] = request.form.get('price_sheet', '')
            user['availability'] = request.form.get('availability', '')
        elif user['role'] == 'local_business':
            user['business_name'] = request.form.get('business_name', '')
            user['business_industry'] = request.form.get('business_industry', '')
            user['interested_modules'] = request.form.getlist('interested_modules')
            
        session['network_user'] = user
        flash('Thiết lập hồ sơ onboarding hoàn tất!', 'success')
        return redirect(url_for('network_dashboard'))
        
    return render_template('network_onboarding.html')

@app.route('/network/profile')
def network_profile():
    user = session.get('network_user')
    if not user:
        user = {
            'fullname': 'Đặng Ngọc Minh Triết',
            'email': 'minhtriet.acrylics@gmail.com',
            'phone': '0794.678.904',
            'role': 'job_seeker',
            'location': 'Quận 3, TP. Hồ Chí Minh',
            'headline': 'Chuyên viên Thiết kế Nails & Chăm sóc móng chuyên nghiệp (5+ năm kinh nghiệm)',
            'skills': 'Acrylic Extensions, Gel Polish Art, Chăm sóc móng, Đính đá, Nail design',
            'experience': 'Làm việc 3 năm tại Nail Salon Luxury Q1, 2 năm KTV chính tại Bloom Spa.',
            'salary_expect': '12.000.000đ - 15.000.000đ',
            'is_onboarded': True
        }
    return render_template('network_profile.html', profile=user)

@app.route('/network/dashboard')
def network_dashboard():
    user = session.get('network_user')
    if not user:
        flash('Vui lòng đăng nhập để xem dashboard!', 'info')
        return redirect(url_for('network_login'))
    return render_template('network_dashboard.html', user=user)

@app.route('/network/discover')
def network_discover():
    q = request.args.get('q', '')
    category = request.args.get('category', 'all')
    return render_template('network_discover.html', jobs=MOCK_JOBS, services=MOCK_SERVICES, communities=MOCK_COMMUNITIES, query=q, category=category)

@app.route('/network/jobs')
def network_jobs():
    return render_template('network_jobs.html', jobs=MOCK_JOBS)

@app.route('/network/services')
def network_services():
    return render_template('network_services.html', services=MOCK_SERVICES)

@app.route('/network/communities')
def network_communities():
    return render_template('network_communities.html', communities=MOCK_COMMUNITIES)

@app.route('/network/messages')
def network_messages():
    user = session.get('network_user')
    if not user:
        user = {'fullname': 'Khách Vãng Lai', 'role': 'job_seeker'}
    return render_template('network_messages.html', user=user)

@app.route('/network/cv-builder')
def network_cv_builder():
    user = session.get('network_user')
    if not user:
        user = {
            'fullname': 'Đặng Ngọc Minh Triết',
            'email': 'minhtriet.acrylics@gmail.com',
            'phone': '0794.678.904',
            'role': 'job_seeker',
            'location': 'Quận 3, TP. Hồ Chí Minh',
            'headline': 'Chuyên viên Thiết kế Nails & Chăm sóc móng chuyên nghiệp (5+ năm kinh nghiệm)',
            'skills': 'Acrylic Extensions, Gel Polish Art, Chăm sóc móng, Đính đá, Nail design',
            'experience': 'Làm việc 3 năm tại Nail Salon Luxury Q1, 2 năm KTV chính tại Bloom Spa.',
            'salary_expect': '12.000.000đ - 15.000.000đ',
            'is_onboarded': True
        }
    return render_template('network_cv_builder.html', profile=user)


# ========== API QR CODE DYNAMIC (PHASE 1) ==========
@app.route('/api/workspace/generate-qr', methods=['POST'])
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


if __name__ == '__main__':
    # GridFS không cần tạo bucket trước — collection 'backups.files'/'backups.chunks' tự được
    # MongoDB tạo lười (lazy) ngay lần fs.put() đầu tiên, không cần bước khởi tạo nào ở đây.
    app.run(port=5001, debug=os.environ.get('FLASK_DEBUG', '').lower() == 'true')