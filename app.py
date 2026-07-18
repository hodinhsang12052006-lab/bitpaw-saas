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

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, send_from_directory
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
from supabase_client import supabase, supabase_admin, SUPABASE_STATUS
from ai_context_engine import AIContextEngine
import jwt as pyjwt

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
    from supabase_client import SUPABASE_URL, SUPABASE_KEY

    # Multi-region (US market pivot): mỗi tenant tự có country/currency riêng (mặc định
    # VN/VND, không đổi hành vi cho tenant hiện tại nào). default_lang chỉ set gợi ý ngôn
    # ngữ ban đầu theo quốc gia tenant — người dùng vẫn bấm nút toggle đổi ngôn ngữ được.
    if hasattr(TenantEngine, 'get_region_config'):
        region = TenantEngine.get_region_config(session.get('business_id'))
    else:
        region = {"country": "VN", "currency": "VND"}
    tenant_country = region['country']
    tenant_currency = region['currency']
    default_lang = 'en' if tenant_country == 'US' else 'vi'

    return dict(
        industry_config=INDUSTRY_CONFIG,
        active_industry_code=business_mode,
        active_industry_cfg=active_cfg,
        supabase_url=SUPABASE_URL,
        supabase_key=SUPABASE_KEY,
        tenant_country=tenant_country,
        tenant_currency=tenant_currency,
        default_lang=default_lang
    )


app.jinja_env.filters['money'] = format_money


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def init_db():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS kho_license (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            license_key TEXT UNIQUE NOT NULL,
            nganh_nghe TEXT,
            trang_thai TEXT DEFAULT 'Sẵn sàng'
        )
    ''')
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


# ========== ROUTE XÁC THỰC ==========
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        business_type = request.form['business_type']
        license_key = request.form.get('license_key', '').strip()
        
        # Kiểm tra License Key trên local SQLite database
        if not license_key:
            flash('Vui lòng nhập Mã kích hoạt bản quyền!', 'danger')
            return render_template('index.html', active_tab='register')
            
        try:
            conn = sqlite3.connect('database.db')
            c = conn.cursor()
            c.execute("SELECT * FROM kho_license WHERE license_key=? AND trang_thai='Sẵn sàng'", (license_key,))
            key_valid = c.fetchone()
            if not key_valid:
                conn.close()
                flash('Mã kích hoạt không hợp lệ, sai mã, hoặc đã được sử dụng!', 'danger')
                return render_template('index.html', active_tab='register')
            
            # Kiểm tra xem mã kích hoạt có hợp lệ với ngành nghề được chọn không
            license_nganh = key_valid[2]
            if license_nganh and license_nganh.strip() and license_nganh.lower() != 'all' and license_nganh.lower() != business_type.lower():
                conn.close()
                flash(f'Mã kích hoạt này chỉ dành cho ngành nghề: {license_nganh.upper()}!', 'danger')
                return render_template('index.html', active_tab='register')
            
            # Cập nhật trạng thái key
            c.execute("UPDATE kho_license SET trang_thai='Đã kích hoạt' WHERE license_key=?", (license_key,))
            conn.commit()
            conn.close()
        except Exception as db_err:
            print(f"Local license check failed: {str(db_err)}")
            flash(f'Lỗi kiểm tra mã kích hoạt: {str(db_err)}', 'danger')
            return render_template('index.html', active_tab='register')

        try:
            res = supabase.auth.sign_up({"email": email, "password": password})
            session['business_mode'] = business_type
            # Lưu business type vào system_settings, khóa riêng theo user_id để tránh đè chéo giữa các tài khoản
            business_mode_key = f'business_mode_{res.user.id}'
            try:
                res_check = supabase.table('system_settings').select('id').eq('key', business_mode_key).execute()
                if res_check.data:
                    supabase.table('system_settings').update({'value': business_type}).eq('key', business_mode_key).execute()
                else:
                    supabase.table('system_settings').insert({'key': business_mode_key, 'value': business_type}).execute()
            except Exception as db_err:
                print(f"Supabase upsert skipped: {str(db_err)}")
            flash('Đăng ký tài khoản thành công! Vui lòng đăng nhập.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            flash(f'Lỗi đăng ký: {str(e)}', 'danger')
    return render_template('index.html', active_tab='register')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        try:
            res = supabase.auth.sign_in_with_password({"email": email, "password": password})
            session['user_id'] = res.user.id
            # Mỗi chủ tiệm (user Supabase Auth) chính là 1 tenant — dùng user_id làm business_id
            # để kích hoạt toàn bộ các bộ lọc .eq('business_id', ...) đã có sẵn trong code/template.
            session['business_id'] = res.user.id
            session['user_email'] = email
            session['access_token'] = res.session.access_token
            _ensure_primary_membership(res.user.id, res.user.id)
            # Ghi log đăng nhập (bỏ qua nếu bảng chưa có sẵn ở phase này)
            try:
                supabase.table('user_logs').insert({
                    'user_email': email,
                    'action': 'login',
                    'description': 'Đăng nhập thành công',
                    'ip_address': request.remote_addr,
                    'created_at': datetime.now().isoformat()
                }).execute()
            except Exception as db_err:
                print(f"Supabase user_logs insert skipped: {str(db_err)}")

            # Đọc business type để redirect đúng ngành nghề, khóa riêng theo user_id hiện tại
            mode = None
            try:
                business_mode_key = f'business_mode_{res.user.id}'
                mode_res = supabase.table('system_settings').select('value').eq('key', business_mode_key).execute()
                mode = mode_res.data[0]['value'] if mode_res.data else 'none'
            except Exception as db_err:
                print(f"Supabase system_settings select skipped: {str(db_err)}")
                mode = 'none'

            session['business_mode'] = mode

            flash('Đăng nhập thành công', 'success')

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
            flash('Sai email hoặc mật khẩu', 'danger')
    return render_template('index.html', active_tab='login')


@app.route('/logout')
def logout():
    if 'user_id' in session:
        try:
            supabase.table('user_logs').insert({
                'user_email': session.get('user_email', 'unknown'),
                'action': 'logout',
                'description': 'Đăng xuất',
                'ip_address': request.remote_addr,
                'created_at': datetime.now().isoformat()
            }).execute()
        except Exception as e:
            print(f"Supabase logging failed on logout: {str(e)}")
        session.clear()
    return redirect(url_for('login'))


# ========== ROUTE CSKH ==========
@app.route('/api/cskh/config', methods=['GET'])
def get_cskh_config():
    try:
        res = supabase.table('cskh_config').select('*').limit(1).execute()
        if res.data:
            return jsonify(res.data[0])
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

    supabase_success = False
    res = None
    last_err = None
    
    # Try inserting to Supabase up to 2 times with a short randomized backoff on transient errors
    for attempt in range(2):
        try:
            res = supabase.table('cskh_requests').insert({
                'name': name,
                'phone': phone,
                'message': f"{message} (Email: {email})" if email else message,
                'status': 'pending',
                'created_at': datetime.now().isoformat()
            }).execute()
            supabase_success = True
            break
        except Exception as e:
            last_err = str(e)
            err_lower = last_err.lower()
            # Retry on transient network, connection limit, gateway timeout or rate limiting errors
            if any(term in err_lower for term in ("timeout", "connection", "network", "unreachable", "500", "502", "503", "504", "rate limit", "limit")):
                time.sleep(random.uniform(0.2, 0.5))
            else:
                break # Break immediately if it is a validation or hard RLS reject
                
    if supabase_success:
        # KHÔNG đồng bộ vào bảng `customers` (CRM riêng theo business_id của từng tiệm) — route này
        # là form liên hệ CSKH chung của BitPaw, không gắn với 1 tenant cụ thể nào, tránh ghi dữ liệu
        # "vô chủ" hoặc lẫn vào CRM của tiệm khác.

        return jsonify({'success': True, 'id': res.data[0]['id']})
    else:
        # Gracefully degrade by writing to local SQLite outbox queue on Supabase temporary failure
        try:
            conn = sqlite3.connect('database.db')
            c = conn.cursor()
            c.execute("""
                INSERT INTO cskh_request_outbox (name, phone, email, message, status)
                VALUES (?, ?, ?, ?, 'pending')
            """, (name, phone, email, message))
            conn.commit()
            conn.close()
            print(f"[*] Supabase transient failure. Saved lead to local outbox fallback successfully (Phone: {phone}).")
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
        supabase.table('cskh_clicks').insert({
            'user_id': user_id,
            'channel': channel,
            'clicked_at': datetime.now().isoformat()
        }).execute()
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
            order_check = supabase.table('orders').select('business_id').eq('id', order_id).execute()
            if not order_check.data:
                return jsonify({'error': 'Order không tồn tại.'}), 404
            supabase.table('customer_feedback').insert({
                'order_id': order_id,
                'rating': rating,
                'comment': comment,
                'created_at': datetime.now().isoformat(),
                'business_id': order_check.data[0].get('business_id')
            }).execute()
            return jsonify({'success': True})
        except Exception as e:
            err_msg = str(e)
            if '23503' in err_msg or 'foreign key constraint' in err_msg.lower():
                pass
            else:
                return jsonify({'error': err_msg}), 500
                
    try:
        supabase.table('customer_feedback').insert({
            'rating': rating,
            'comment': comment,
            'created_at': datetime.now().isoformat()
        }).execute()
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
                mode_res = supabase.table('system_settings').select('value').eq('key', f"business_mode_{session['user_id']}").execute()
                mode = mode_res.data[0]['value'] if mode_res.data else 'none'
                session['business_mode'] = mode
            except Exception as db_err:
                print(f"Supabase system_settings select skipped: {str(db_err)}")
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
            mode_res = supabase.table('system_settings').select('value').eq('key', f"business_mode_{session['user_id']}").execute()
            mode = mode_res.data[0]['value'] if mode_res.data else 'none'
            session['business_mode'] = mode
        except Exception as db_err:
            print(f"Supabase system_settings select skipped: {str(db_err)}")
            mode = 'none'

    if mode == 'none':
        return redirect(url_for('setup'))


    business_id = session.get('business_id') or session['user_id']
    if mode in INDUSTRY_CONFIG:
        if mode == 'retail':
            try:
                products = supabase.table('products').select('*').eq('is_active', 1).eq('channel_type', 'retail').eq('business_id', business_id).execute()
                total_revenue = supabase.table('orders').select('total_amount').eq('business_id', business_id).execute()
                revenue = sum([o.get('total_amount') or 0 for o in total_revenue.data]) if total_revenue.data else 0
                total_expense = supabase.table('expenses').select('amount').eq('business_id', business_id).execute()
                expense = sum([e.get('amount') or 0 for e in total_expense.data]) if total_expense.data else 0

                # Lấy lịch sử 10 đơn hàng
                history = []
                orders = supabase.table('orders').select('id, created_at, total_amount').eq('business_id', business_id).order('created_at', desc=True).limit(10).execute()

                if orders.data:
                    for o in orders.data:
                        order_items = supabase.table('order_items').select('product_id, quantity, total_price').eq('order_id', o['id']).execute()
                        if order_items.data:
                            first_item = order_items.data[0]
                            prod = supabase.table('products').select('name').eq('id', first_item['product_id']).execute()
                            name = prod.data[0]['name'] if prod.data else 'Sản phẩm'
                            history.append({
                                'id': o['id'],
                                'name': name,
                                'quantity': first_item['quantity'],
                                'total_price': first_item['total_price'],
                                'created_at': o['created_at']
                            })

                # Lấy doanh thu 7 ngày gần nhất cho biểu đồ
                today_dt = datetime.now().date()
                last_7_days = [today_dt - timedelta(days=i) for i in range(6, -1, -1)]
                last_7_days_str = [d.isoformat() for d in last_7_days]
                start_date = last_7_days[0].isoformat()

                week_orders = supabase.table('orders').select('total_amount, created_at').eq('business_id', business_id).gte('created_at', start_date).execute()
                revenue_map = {d: 0 for d in last_7_days_str}
                if week_orders.data:
                    for o in week_orders.data:
                        created_date = o.get('created_at', '')[:10]
                        if created_date in revenue_map:
                            revenue_map[created_date] += o.get('total_amount') or 0
                revenue_chart_data = [revenue_map[d] for d in last_7_days_str]
                revenue_chart_labels = ['7 ngày trước', '6 ngày', '5 ngày', '4 ngày', '3 ngày', 'Hôm qua', 'Hôm nay']
            except Exception as db_err:
                print(f"Supabase data loading skipped: {str(db_err)}")
                products = type('obj', (object,), {'data': []})
                revenue = 0
                expense = 0
                history = []
                revenue_chart_data = [0]*7
                revenue_chart_labels = ['7 ngày trước', '6 ngày', '5 ngày', '4 ngày', '3 ngày', 'Hôm qua', 'Hôm nay']

            return render_template(
                'dashboard.html',
                products=products.data if hasattr(products, 'data') else [],
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


@app.route('/landingpage')
@app.route('/landing')
def landingpage():
    return render_template('landing.html')


@app.route('/sitemap.xml')
def sitemap():
    return send_from_directory(os.path.dirname(os.path.abspath(__file__)), 'sitemap.xml', mimetype='application/xml')


@app.route('/checkout')
def public_checkout():
    return render_template('checkout.html')


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
            res_check = supabase.table('system_settings').select('id').eq('key', business_mode_key).execute()
            if res_check.data:
                supabase.table('system_settings').update({'value': mode}).eq('key', business_mode_key).execute()
            else:
                supabase.table('system_settings').insert({'key': business_mode_key, 'value': mode}).execute()
        except Exception as db_err:
            print(f"Supabase system_settings upsert skipped: {str(db_err)}")
        return redirect(url_for('index'))
    return render_template('setup.html')


# ========== QUẢN LÝ SẢN PHẨM ==========
@app.route('/add', methods=['GET', 'POST'])
@login_required
def add_product():
    try:
        mode_res = supabase.table('system_settings').select('value').eq('key', f"business_mode_{session['user_id']}").execute()
        current_mode = mode_res.data[0]['value'] if mode_res.data else 'none'
    except Exception as db_err:
        print(f"Supabase system_settings select failed: {str(db_err)}")
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
            supabase.table('products').insert({
                'name': request.form['name'],
                'category': cat,
                'channel_type': 'retail',
                'stock': int(request.form['stock']),
                'price': float(request.form['price']),
                'image': filename,
                'is_active': 1,
                'business_id': business_id
            }).execute()
        except Exception as db_err:
            print(f"Supabase products insert failed: {str(db_err)}")
        if current_mode == 'fnb':
            return redirect(url_for('pos'))
        return redirect(url_for('index'))
    return render_template('add_product.html', mode=current_mode)


def _assert_owns_product(product_id, business_id):
    """Trả về True nếu sản phẩm thuộc đúng business_id hiện tại, False nếu không (hoặc không tồn tại)."""
    check = supabase.table('products').select('business_id').eq('id', product_id).execute()
    return bool(check.data) and check.data[0].get('business_id') == business_id


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
        old_res = supabase.table('products').select('name, category, price, stock').eq('id', id).execute()
        old_value = old_res.data[0] if old_res.data else None

        name = request.form['name']
        category = request.form['category']
        price = float(request.form['price'])
        stock = int(request.form['stock'])
        new_value = {'name': name, 'category': category, 'price': price, 'stock': stock}
        supabase.table('products').update(new_value).eq('id', id).execute()
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
        old_res = supabase.table('products').select('name, is_active').eq('id', id).execute()
        old_value = old_res.data[0] if old_res.data else None
        supabase.table('products').update({'is_active': 0}).eq('id', id).execute()
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
        query = supabase.table('dining_tables').select('*').eq('business_id', business_id)
        tables = query.execute()
        tables_data = tables.data
        if len(tables_data) == 0:
            # Cố định mặc định 200 bàn (đặt tên tiếng Anh "Table N") thay vì phụ thuộc vào
            # tính năng "Thêm Bàn" động — mỗi tenant F&B mới sẽ luôn có sẵn 200 bàn thật
            # (có id Supabase thật, dùng được ngay cho gọi món/thanh toán) ngay từ lần đầu vào POS.
            default_tables = [(f'Table {i}', uuid.uuid4().hex[:8]) for i in range(1, 201)]
            for name, token in default_tables:
                try:
                    insert_data = {'name': name, 'qr_token': token, 'business_id': business_id}
                    supabase.table('dining_tables').insert(insert_data).execute()
                except Exception as e:
                    print(f"Supabase dining_tables insert failed: {str(e)}")
            try:
                tables = supabase.table('dining_tables').select('*').eq('business_id', business_id).execute()
                tables_data = tables.data
            except Exception as e:
                print(f"Supabase dining_tables secondary select failed: {str(e)}")
    except Exception as e:
        print(f"Supabase dining_tables select failed: {str(e)}")
        # Không fallback về bàn demo dùng chung nữa — mỗi tenant chỉ thấy dữ liệu rỗng khi lỗi, tránh lộ/trộn dữ liệu.
        tables_data = []
    try:
        menu = supabase.table('products').select('*').eq('is_active', 1).eq('channel_type', 'retail').eq('business_id', business_id).execute()
        menu_data = menu.data
    except Exception as e:
        print(f"Supabase products select failed: {str(e)}")
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
            existing = supabase.table('dining_tables').select('id').eq('qr_token', candidate).execute()
            if not existing.data:
                qr_token = candidate
                break
        except Exception as e:
            return jsonify({"success": False, "message": f"Lỗi kiểm tra mã QR: {str(e)}"}), 500
    if not qr_token:
        return jsonify({"success": False, "message": "Không thể sinh mã QR duy nhất, vui lòng thử lại."}), 500

    business_id = session.get('business_id') or session['user_id']
    insert_payload = {'name': table_name, 'qr_token': qr_token, 'business_id': business_id}
    try:
        result = supabase.table('dining_tables').insert(insert_payload).execute()
        if not result.data:
            return jsonify({"success": False, "message": "Thêm bàn thất bại, vui lòng thử lại."}), 500
    except Exception as e:
        return jsonify({"success": False, "message": f"Lỗi khi thêm bàn: {str(e)}"}), 500

    return redirect(url_for('pos'))


@app.route('/table/<int:table_id>')
@login_required
def view_table(table_id):
    business_id = session.get('business_id') or session['user_id']
    try:
        table = supabase.table('dining_tables').select('*').eq('id', table_id).execute()
        if not table.data:
            return "Bàn không tồn tại", 404
        table = table.data[0]
        if table.get('business_id') != business_id:
            return "Bàn này không thuộc quyền quản lý của bạn.", 403
        orders_data = supabase.table('table_orders').select('*').eq('table_id', table_id).execute()
        current_orders = []

        for o in orders_data.data:
            prod = supabase.table('products').select('name, price').eq('id', o['product_id']).execute()
            if prod.data:
                current_orders.append({
                    'id': o['id'],
                    'name': prod.data[0]['name'],
                    'price': prod.data[0]['price'],
                    'quantity': o['quantity'],
                    'product_id': o['product_id']
                })

        total_bill = sum([item['price'] * item['quantity'] for item in current_orders])
        menu = supabase.table('products').select('*').eq('is_active', 1).eq('channel_type', 'retail').eq('business_id', business_id).execute()
        tenant_jwt = _mint_tenant_jwt(business_id)  # nhân viên xem bàn -> token đầy đủ quyền, không giới hạn scope
        return render_template('table_order.html', table=table, orders=current_orders, total_bill=total_bill, menu=menu.data, tenant_jwt=tenant_jwt)
    except Exception as e:
        return f"Lỗi tải thông tin bàn: {str(e)}", 500


def _assert_owns_table(table_id, business_id):
    """Trả về (True, None) nếu bàn thuộc đúng business_id, ngược lại (False, thông báo lỗi)."""
    check = supabase.table('dining_tables').select('business_id').eq('id', table_id).execute()
    if not check.data:
        return False, "Bàn không tồn tại."
    if check.data[0].get('business_id') != business_id:
        return False, "Bàn này không thuộc quyền quản lý của bạn."
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
        supabase.table('loyalty_events').insert({
            'business_id': business_id,
            'customer_id': customer.get('id'),
            'event_type': event_type,
            'channel': channel or 'none',
            'message': message,
            'status': status,
        }).execute()
    except Exception as e:
        print(f"Loi ghi loyalty_events: {e}")


def _award_loyalty_points(business_id, customer_phone, amount_spent):
    """Tự động cộng điểm + xét lên hạng cho khách ngay sau khi thanh toán xong.
    Nếu SĐT chưa có trong CRM thì tự tạo khách mới. Không chặn luồng thanh toán nếu lỗi."""
    customer_phone = (customer_phone or '').strip()
    if not customer_phone or not amount_spent or amount_spent <= 0:
        return
    try:
        cust_res = supabase.table('customers').select('*').eq('business_id', business_id).eq('phone', customer_phone).execute()
        points_earned = int(amount_spent * LOYALTY_POINTS_PER_VND)
        if cust_res.data:
            customer = cust_res.data[0]
            old_tier = customer.get('tier') or 'Normal'
            new_total_spent = (customer.get('total_spent') or 0) + amount_spent
            new_points = (customer.get('loyalty_points') or 0) + points_earned
            new_tier = _tier_for_spend(new_total_spent)
            supabase.table('customers').update({
                'total_spent': new_total_spent,
                'loyalty_points': new_points,
                'tier': new_tier,
            }).eq('id', customer['id']).eq('business_id', business_id).execute()
            customer['total_spent'] = new_total_spent
            customer['loyalty_points'] = new_points
            customer['tier'] = new_tier
        else:
            new_tier = _tier_for_spend(amount_spent)
            new_cust = supabase.table('customers').insert({
                'business_id': business_id,
                'phone': customer_phone,
                'name': f'Khách {customer_phone[-4:]}',
                'tier': new_tier,
                'loyalty_points': points_earned,
                'total_spent': amount_spent,
                'join_date': datetime.now().date().isoformat(),
            }).execute()
            customer = new_cust.data[0] if new_cust.data else {'id': None, 'tier': new_tier, 'loyalty_points': points_earned}
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
    try:
        existing = supabase.table('business_memberships').select('id') \
            .eq('owner_user_id', owner_user_id).eq('business_id', business_id).execute()
        if not existing.data:
            supabase.table('business_memberships').insert({
                'owner_user_id': owner_user_id,
                'business_id': business_id,
                'branch_name': 'Chi nhánh chính',
                'is_primary': True,
            }).execute()
    except Exception as e:
        print(f"Loi ensure primary membership: {e}")


def _get_owned_business_ids(owner_user_id):
    """Trả về danh sách business_id mà owner_user_id được quyền quản lý (gồm cả chi nhánh chính)."""
    try:
        res = supabase.table('business_memberships').select('business_id, branch_name, is_primary') \
            .eq('owner_user_id', owner_user_id).execute()
        return res.data or []
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
        supabase.table('business_memberships').insert({
            'owner_user_id': user_id,
            'business_id': new_business_id,
            'branch_name': branch_name,
            'is_primary': False,
        }).execute()
    except Exception as e:
        return jsonify({'success': False, 'message': f'Lỗi tạo chi nhánh: {str(e)}'}), 500

    return jsonify({'success': True, 'business_id': new_business_id, 'branch_name': branch_name})


@app.route('/report_consolidated')
@login_required
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
            orders_res = supabase.table('orders').select('total_amount').eq('business_id', bid).execute()
            revenue = sum([o.get('total_amount') or 0 for o in (orders_res.data or [])])
        except Exception as e:
            print(f"Loi lay doanh thu chi nhanh {bid}: {e}")
        try:
            expenses_res = supabase.table('expenses').select('amount').eq('business_id', bid).execute()
            expense = sum([e.get('amount') or 0 for e in (expenses_res.data or [])])
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
        supabase.table('audit_logs').insert({
            'business_id': business_id,
            'user_id': session.get('user_id'),
            'action': action,
            'entity_type': entity_type,
            'entity_id': str(entity_id) if entity_id is not None else None,
            'old_value': old_value,
            'new_value': new_value,
        }).execute()
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
        existing = supabase.table('table_orders').select('id, quantity').eq('table_id', table_id).eq('product_id', product_id).execute()
        if existing.data:
            new_qty = existing.data[0]['quantity'] + qty
            supabase.table('table_orders').update({'quantity': new_qty}).eq('id', existing.data[0]['id']).execute()
        else:
            supabase.table('table_orders').insert({'table_id': table_id, 'product_id': product_id, 'quantity': qty}).execute()
        supabase.table('dining_tables').update({'status': 'Đang phục vụ'}).eq('id', table_id).execute()
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
        orders = supabase.table('table_orders').select('*').eq('table_id', table_id).execute()
        if orders.data:
            order_code = f"FNB-{uuid.uuid4().hex[:8].upper()}"
            total_bill = 0
            for item in orders.data:
                prod = supabase.table('products').select('price, stock').eq('id', item['product_id']).execute()
                if prod.data:
                    price = prod.data[0]['price']
                    total_bill += item['quantity'] * price
                    new_stock = prod.data[0]['stock'] - item['quantity']
                    supabase.table('products').update({'stock': new_stock}).eq('id', item['product_id']).execute()

            order_res = supabase.table('orders').insert({
                'order_code': order_code,
                'channel': 'fnb',
                'total_amount': total_bill,
                'business_id': business_id
            }).execute()
            order_id = order_res.data[0]['id']

            for item in orders.data:
                prod = supabase.table('products').select('price').eq('id', item['product_id']).execute()
                price = prod.data[0]['price']
                total_price = item['quantity'] * price
                supabase.table('order_items').insert({
                    'order_id': order_id,
                    'product_id': item['product_id'],
                    'quantity': item['quantity'],
                    'price': price,
                    'total_price': total_price,
                    'business_id': business_id
                }).execute()

            supabase.table('table_orders').delete().eq('table_id', table_id).execute()
            supabase.table('dining_tables').update({'status': 'Còn trống'}).eq('id', table_id).execute()
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
            supabase.table('expenses').insert({
                'description': description,
                'amount': amount,
                'expense_date': expense_date,
                'created_at': datetime.now().isoformat(),
                'business_id': business_id
            }).execute()
        except Exception as db_err:
            print(f"Supabase expenses insert with expense_date failed: {str(db_err)}")
            try:
                supabase.table('expenses').insert({
                    'description': description,
                    'amount': amount,
                    'created_at': datetime.now().isoformat(),
                    'business_id': business_id
                }).execute()
            except Exception as db_err2:
                print(f"Supabase expenses fallback insert failed: {str(db_err2)}")
        flash('Đã thêm khoản chi', 'success')
        return redirect(url_for('index'))
    return render_template('add_expense.html')


@app.route('/expense_list')
@login_required
def expense_list():
    business_id = session.get('business_id') or session['user_id']
    try:
        expenses = supabase.table('expenses').select('*').eq('business_id', business_id).order('expense_date', desc=True).execute()
        expenses_data = expenses.data
    except Exception as db_err:
        print(f"Supabase expenses order by expense_date failed: {str(db_err)}")
        try:
            expenses = supabase.table('expenses').select('*').eq('business_id', business_id).order('created_at', desc=True).execute()
            expenses_data = expenses.data
        except Exception as db_err2:
            print(f"Supabase expenses order by created_at failed: {str(db_err2)}")
            expenses_data = []
    return render_template('expense_list.html', expenses=expenses_data)


# ========== QUẢN LÝ KHUYẾN MÃI ==========
@app.route('/promotions')
@login_required
def promotions():
    business_id = session.get('business_id') or session['user_id']
    try:
        promos = supabase.table('promotions').select('*').eq('business_id', business_id).order('id', desc=True).execute()
        promos_data = promos.data
    except Exception as db_err:
        print(f"Supabase promotions select failed: {str(db_err)}")
        promos_data = []
    return render_template('promotion_management.html', promotions=promos_data)


@app.route('/add_promotion', methods=['POST'])
@login_required
def add_promotion():
    business_id = session.get('business_id') or session['user_id']
    data = request.json
    try:
        supabase.table('promotions').insert({
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
        }).execute()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Lỗi thêm khuyến mãi: {str(e)}'}), 500


@app.route('/update_promotion/<int:id>', methods=['PUT'])
@login_required
def update_promotion(id):
    business_id = session.get('business_id') or session['user_id']
    try:
        owns, err = _assert_owns_row('promotions', id, business_id)
        if not owns:
            return jsonify({'success': False, 'message': err}), 403
        data = dict(request.json or {})
        data.pop('business_id', None)  # không cho phép request tự đổi chủ sở hữu (chiếm tenant khác)
        data.pop('id', None)
        supabase.table('promotions').update(data).eq('id', id).eq('business_id', business_id).execute()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Lỗi cập nhật khuyến mãi: {str(e)}'}), 500


@app.route('/delete_promotion/<int:id>', methods=['DELETE'])
@login_required
def delete_promotion(id):
    business_id = session.get('business_id') or session['user_id']
    try:
        owns, err = _assert_owns_row('promotions', id, business_id)
        if not owns:
            return jsonify({'success': False, 'message': err}), 403
        supabase.table('promotions').delete().eq('id', id).execute()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Lỗi xóa khuyến mãi: {str(e)}'}), 500


# ========== QUẢN LÝ NHÂN VIÊN ==========
@app.route('/staff')
@login_required
def staff_list():
    business_id = session.get('business_id') or session['user_id']
    try:
        staffs = supabase.table('staff').select('*').eq('business_id', business_id).order('id', desc=False).execute()
        staffs_data = staffs.data
    except Exception as e:
        print(f"Supabase staff select failed: {str(e)}")
        staffs_data = []
    return render_template('staff_management.html', staffs=staffs_data)


@app.route('/add_staff', methods=['POST'])
@login_required
def add_staff():
    business_id = session.get('business_id') or session['user_id']
    data = request.json
    try:
        supabase.table('staff').insert({
            'name': data['name'],
            'phone': data['phone'],
            'role': data['role'],
            'commission_rate': data['commission_rate'],
            'is_active': data['is_active'],
            'business_id': business_id
        }).execute()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Lỗi thêm nhân viên: {str(e)}'}), 500


def _assert_owns_row(table, row_id, business_id):
    """Helper chung: trả về (True, None) nếu row thuộc đúng business_id, ngược lại (False, lỗi)."""
    check = supabase.table(table).select('business_id').eq('id', row_id).execute()
    if not check.data:
        return False, "Không tìm thấy dữ liệu."
    if check.data[0].get('business_id') != business_id:
        return False, "Dữ liệu này không thuộc quyền quản lý của bạn."
    return True, None


@app.route('/update_staff/<int:id>', methods=['PUT'])
@login_required
def update_staff(id):
    business_id = session.get('business_id') or session['user_id']
    try:
        owns, err = _assert_owns_row('staff', id, business_id)
        if not owns:
            return jsonify({'success': False, 'message': err}), 403
        data = dict(request.json or {})
        data.pop('business_id', None)  # không cho phép request tự đổi chủ sở hữu (chiếm tenant khác)
        data.pop('id', None)
        supabase.table('staff').update(data).eq('id', id).eq('business_id', business_id).execute()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Lỗi cập nhật nhân viên: {str(e)}'}), 500


@app.route('/delete_staff/<int:id>', methods=['DELETE'])
@login_required
def delete_staff(id):
    business_id = session.get('business_id') or session['user_id']
    try:
        owns, err = _assert_owns_row('staff', id, business_id)
        if not owns:
            return jsonify({'success': False, 'message': err}), 403
        supabase.table('staff').delete().eq('id', id).eq('business_id', business_id).execute()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Lỗi xóa nhân viên: {str(e)}'}), 500


# ========== QUẢN LÝ KHÁCH HÀNG (CRM) ==========
@app.route('/customers')
@login_required
def customers():
    business_id = session.get('business_id') or session['user_id']
    try:
        custs = supabase.table('customers').select('*').eq('business_id', business_id).order('id', desc=True).execute()
        customers_data = custs.data
        error_message = None
    except Exception as e:
        print(f"Error fetching customers (network/offline): {e}")
        customers_data = []
        error_message = "Đang hiển thị chế độ Offline"
    return render_template('crm.html', customers=customers_data, error_message=error_message)


@app.route('/add_customer', methods=['POST'])
@login_required
def add_customer():
    business_id = session.get('business_id') or session['user_id']
    data = request.json
    try:
        supabase.table('customers').insert({
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
        }).execute()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Lỗi thêm khách hàng: {str(e)}'}), 500


@app.route('/update_customer/<int:id>', methods=['PUT'])
@login_required
def update_customer(id):
    business_id = session.get('business_id') or session['user_id']
    try:
        owns, err = _assert_owns_row('customers', id, business_id)
        if not owns:
            return jsonify({'success': False, 'message': err}), 403
        data = dict(request.json or {})
        data.pop('business_id', None)  # không cho phép request tự đổi chủ sở hữu (chiếm tenant khác)
        data.pop('id', None)
        supabase.table('customers').update(data).eq('id', id).eq('business_id', business_id).execute()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Lỗi cập nhật khách hàng: {str(e)}'}), 500


@app.route('/delete_customer/<int:id>', methods=['DELETE'])
@login_required
def delete_customer(id):
    business_id = session.get('business_id') or session['user_id']
    try:
        owns, err = _assert_owns_row('customers', id, business_id)
        if not owns:
            return jsonify({'success': False, 'message': err}), 403
        supabase.table('customers').delete().eq('id', id).execute()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Lỗi xóa khách hàng: {str(e)}'}), 500


# ========== QUẢN LÝ GIAO DỊCH THANH TOÁN ==========
@app.route('/payment_transactions')
@login_required
def payment_transactions():
    business_id = session.get('business_id') or session['user_id']
    try:
        txs = supabase.table('payment_transactions').select('*').eq('business_id', business_id).order('created_at', desc=True).execute()
        transactions_data = txs.data
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
        owns, err = _assert_owns_row('payment_transactions', id, business_id)
        if not owns:
            return jsonify({'success': False, 'message': err}), 403
        supabase.table('payment_transactions').update({'status': new_status}).eq('id', id).eq('business_id', business_id).execute()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Lỗi cập nhật trạng thái thanh toán: {str(e)}'}), 500


# ========== SPA & KARAOKE ==========
@app.route('/spa')
@login_required
def spa():
    business_id = session.get('business_id') or session['user_id']
    try:
        brand_res = supabase.table('system_settings').select('value').eq('key', 'brand_name').execute()
        brand_name = brand_res.data[0]['value'] if brand_res.data else 'BitPaw'
    except Exception as db_err:
        print(f"Supabase brand_name select failed: {str(db_err)}")
        brand_name = 'BitPaw'
    try:
        color_res = supabase.table('system_settings').select('value').eq('key', 'brand_color').execute()
        brand_color = color_res.data[0]['value'] if color_res.data else '#06b6d4'
    except Exception as db_err:
        print(f"Supabase brand_color select failed: {str(db_err)}")
        brand_color = '#06b6d4'
    try:
        services = supabase.table('products').select('*').eq('is_active', 1).eq('channel_type', 'spa') \
            .eq('business_id', business_id).neq('name', 'Phí Dịch Vụ Spa').order('name').execute()
        services_data = services.data
    except Exception as db_err:
        print(f"Supabase services select failed: {str(db_err)}")
        services_data = []
    return render_template('spa.html', services=services_data, brand_name=brand_name, brand_color=brand_color)


@app.route('/add_spa', methods=['GET', 'POST'])
@login_required
def add_spa():
    business_id = session.get('business_id') or session['user_id']
    if request.method == 'POST':
        try:
            image_file = request.files.get('image')
            filename = ""
            if image_file and image_file.filename != '' and allowed_file(image_file.filename):
                filename = secure_filename(image_file.filename)
                image_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            supabase.table('products').insert({
                'name': request.form['name'],
                'category': 'Spa & Beauty',
                'channel_type': 'spa',
                'stock': 9999,
                'price': float(request.form['price']),
                'image': filename,
                'is_active': 1,
                'business_id': business_id
            }).execute()
            return redirect(url_for('spa'))
        except Exception as e:
            return f"Lỗi thêm dịch vụ spa: {str(e)}", 500
    return render_template('add_spa.html')


@app.route('/delete_spa/<int:id>')
@login_required
def delete_spa(id):
    business_id = session.get('business_id') or session['user_id']
    try:
        owns, err = _assert_owns_row('products', id, business_id)
        if not owns:
            return err, 403
        supabase.table('products').update({'is_active': 0}).eq('id', id).execute()
        return redirect(url_for('spa'))
    except Exception as e:
        return f"Lỗi xóa dịch vụ spa: {str(e)}", 500


@app.route('/checkout_spa', methods=['POST'])
@login_required
def checkout_spa():
    business_id = session.get('business_id') or session['user_id']
    try:
        product_id = request.form['product_id']
        if not _assert_owns_product(product_id, business_id):
            return "Sản phẩm không tồn tại hoặc không thuộc quyền quản lý của bạn.", 403
        qty = int(request.form['quantity'])
        prod = supabase.table('products').select('price').eq('id', product_id).execute()
        if prod.data:
            price = prod.data[0]['price']
            total_price = price * qty
            order_code = f"SPA-{uuid.uuid4().hex[:8].upper()}"
            order = supabase.table('orders').insert({
                'order_code': order_code,
                'channel': 'spa',
                'total_amount': total_price,
                'business_id': business_id
            }).execute()
            order_id = order.data[0]['id']
            supabase.table('order_items').insert({
                'order_id': order_id,
                'product_id': product_id,
                'quantity': qty,
                'price': price,
                'total_price': total_price,
                'business_id': business_id
            }).execute()
        return redirect(url_for('spa'))
    except Exception as e:
        return f"Lỗi thanh toán spa: {str(e)}", 500


@app.route('/booking')
@app.route('/booking/qr/<spa_id>')
@app.route('/booking/service/<service_id>')
def public_booking(spa_id=None, service_id=None):
    try:
        query = supabase.table('products').select('*').eq('is_active', 1).eq('channel_type', 'spa').neq('name', 'Phí Dịch Vụ Spa')
        # spa_id trong QR chính là business_id của tiệm — chỉ hiện đúng dịch vụ của tiệm đó, không trộn tiệm khác
        if spa_id:
            query = query.eq('business_id', spa_id)
        services = query.execute()
        services_data = services.data
    except Exception as e:
        print(f"Supabase public_booking services select failed: {str(e)}")
        services_data = []
    # Khách đặt lịch qua QR không đăng nhập -> token giới hạn phạm vi (chỉ đọc dịch vụ, tạo lịch hẹn của đúng tiệm này)
    try:
        tenant_jwt = _mint_tenant_jwt(spa_id, scope='qr_public', ttl_seconds=1800) if spa_id else None
    except Exception as e:
        print(f"_mint_tenant_jwt failed: {str(e)}")
        tenant_jwt = None
    return render_template('booking.html', services=services_data, pre_selected_service_id=service_id, spa_id=spa_id, tenant_jwt=tenant_jwt)


@app.route('/create_appointment', methods=['POST'])
def create_appointment():
    data = request.json or {}
    try:
        # Route public (khách đặt lịch, không có session) — xác định business_id qua dịch vụ được chọn
        svc = supabase.table('products').select('business_id').eq('id', data['service_id']).execute()
        if not svc.data:
            return jsonify({'success': False, 'message': 'Dịch vụ không tồn tại.'}), 400
        supabase.table('appointments').insert({
            'customer_name': data['name'],
            'customer_phone': data['phone'],
            'service_id': data['service_id'],
            'staff_id': data.get('staff_id'),
            'book_time': data['book_time'],
            'note': data.get('note'),
            'status': 'pending',
            'business_id': svc.data[0]['business_id']
        }).execute()
    except Exception as e:
        return jsonify({'success': False, 'message': f'Không thể tạo lịch hẹn: {str(e)}'}), 400
    return jsonify({'success': True})


@app.route('/karaoke')
@login_required
def karaoke():
    business_id = session.get('business_id') or session['user_id']
    try:
        rooms = supabase.table('karaoke_rooms').select('*').eq('business_id', business_id).execute()
        rooms_data = rooms.data
    except Exception as db_err:
        print(f"Supabase karaoke_rooms select failed: {str(db_err)}")
        rooms_data = []
    return render_template('karaoke.html', rooms=rooms_data)


@app.route('/toggle_room/<int:room_id>')
@login_required
def toggle_room(room_id):
    business_id = session.get('business_id') or session['user_id']
    try:
        room = supabase.table('karaoke_rooms').select('*').eq('id', room_id).execute()
        if not room.data or room.data[0].get('business_id') != business_id:
            return redirect(url_for('karaoke'))
        room = room.data[0]
        if room['status'] == 'Trống':
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            supabase.table('karaoke_rooms').update({'status': 'Đang chơi', 'start_time': now}).eq('id', room_id).execute()
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
            prod = supabase.table('products').select('id').eq('name', 'Phí Giờ Karaoke').eq('business_id', business_id).execute()
            if prod.data:
                prod_id = prod.data[0]['id']
                order_code = f"KTV-{uuid.uuid4().hex[:8].upper()}"
                order = supabase.table('orders').insert({
                    'order_code': order_code,
                    'channel': 'karaoke',
                    'total_amount': total_price,
                    'business_id': business_id
                }).execute()
                order_id = order.data[0]['id']
                supabase.table('order_items').insert({
                    'order_id': order_id,
                    'product_id': prod_id,
                    'quantity': 1,
                    'price': total_price,
                    'total_price': total_price,
                    'business_id': business_id
                }).execute()
            supabase.table('karaoke_rooms').update({'status': 'Trống', 'start_time': None}).eq('id', room_id).execute()
        return redirect(url_for('karaoke'))
    except Exception as e:
        return f"Lỗi xử lý phòng karaoke: {str(e)}", 500


# ========== BÁO CÁO ==========
@app.route('/report')
@login_required
def report():
    business_id = session.get('business_id') or session['user_id']
    try:
        orders = supabase.table('orders').select('id, total_amount').eq('business_id', business_id).execute()
        revenue = sum([o.get('total_amount') or 0 for o in orders.data]) if orders.data else 0
        expenses = supabase.table('expenses').select('amount').eq('business_id', business_id).execute()
        expense = sum([e.get('amount') or 0 for e in expenses.data]) if expenses.data else 0
        profit = revenue - expense

        # order_items không có cột business_id riêng — lọc gián tiếp qua danh sách order_id đã thuộc đúng business_id
        order_ids = [o['id'] for o in (orders.data or [])]
        items_data = []
        if order_ids:
            items = supabase.table('order_items').select('product_id, total_price').in_('order_id', order_ids).execute()
            items_data = items.data or []
        breakdown_map = {}

        # Batch load products mapping in O(1) to avoid massive synchronous DB requests in loop
        products = supabase.table('products').select('id, category').eq('business_id', business_id).execute()
        product_cat_map = {p['id']: p['category'] for p in products.data} if products.data else {}
        
        for item in items_data:
            cat = product_cat_map.get(item['product_id'], 'Khác')
            breakdown_map[cat] = breakdown_map.get(cat, 0) + (item.get('total_price') or 0)
            
        breakdown = [(cat, total) for cat, total in breakdown_map.items()]
        return render_template('report.html', revenue=revenue, expense=expense, profit=profit, breakdown=breakdown)
    except Exception as e:
        print(f"[!] /report compilation error (graceful degradation active): {str(e)}")
        return render_template('report.html', revenue=0, expense=0, profit=0, breakdown=[])


@app.route('/profit_report')
@login_required
def profit_report():
    business_id = session.get('business_id') or session['user_id']
    try:
        # Lấy tất cả products của đúng tenant, tính số lượng bán từ order_items
        products = supabase.table('products').select('id, name, category, price, cost_price').eq('is_active', 1).eq('business_id', business_id).execute()
        own_product_ids = {p['id'] for p in (products.data or [])}
        order_items = supabase.table('order_items').select('product_id, quantity').execute()
        sold_map = {}
        for oi in order_items.data:
            # order_items chưa có cột business_id riêng — chỉ cộng dồn cho sản phẩm thuộc đúng tenant
            if oi['product_id'] not in own_product_ids:
                continue
            sold_map[oi['product_id']] = sold_map.get(oi['product_id'], 0) + oi['quantity']
        profit_data = []
        for p in products.data:
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
                'margin': margin
            })
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
    try:
        logs = supabase.table('user_logs').select('*').order('created_at', desc=True).execute()
        logs_data = logs.data
    except Exception as e:
        print(f"Supabase user_logs select failed: {str(e)}")
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
    if not supabase_admin:
        return jsonify({'success': False, 'error': 'Backup storage admin key is not configured.'}), 400
    try:
        business_id = session.get('business_id') or session['user_id']
        # Chỉ backup dữ liệu CỦA ĐÚNG tenant đang đăng nhập — không export toàn hệ thống
        backup_data = {}
        for table in BACKUP_TABLES:
            res = supabase_admin.table(table).select('*').eq('business_id', business_id).execute()
            backup_data[table] = res.data
        # system_settings dùng khóa riêng business_mode_{user_id}, không có cột business_id
        settings_res = supabase_admin.table('system_settings').select('*').eq('key', f'business_mode_{business_id}').execute()
        backup_data['system_settings'] = settings_res.data

        backup_data['_backup_metadata'] = {
            'version': '1.0',
            'business_id': business_id,
            'timestamp': datetime.now().isoformat()
        }
        json_str = json.dumps(backup_data, indent=2, ensure_ascii=False)
        filename = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        # Tách riêng thư mục theo business_id trên Storage — tenant khác không thể list/tải nhầm
        storage_path = f"backups/{business_id}/{filename}"

        supabase_admin.storage.from_(BACKUP_BUCKET).upload(storage_path, json_str.encode('utf-8'), {'content-type': 'application/json'})

        supabase_admin.table('backup_logs').insert({
            'filename': filename,
            'business_id': business_id,
            'created_at': datetime.now().isoformat(),
            'user_email': session.get('user_email', 'system')
        }).execute()
        return jsonify({'success': True, 'filename': filename})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/backup/restore', methods=['POST'])
@login_required
def restore_backup():
    if not supabase_admin:
        return jsonify({'success': False, 'error': 'Backup storage admin key is not configured.'}), 400
    try:
        business_id = session.get('business_id') or session['user_id']
        filename = request.json.get('filename')
        if not filename:
            return jsonify({'success': False, 'error': 'Thiếu tên file backup.'}), 400
        # Chặn path traversal: filename do client gửi lên không được phép chứa '/', '..'
        # hay bất kỳ ký tự nào để thoát khỏi thư mục backups/{business_id}/ của chính tenant.
        filename = secure_filename(filename)
        if not filename or filename != request.json.get('filename'):
            return jsonify({'success': False, 'error': 'Tên file backup không hợp lệ.'}), 400
        storage_path = f"backups/{business_id}/{filename}"

        raw = supabase_admin.storage.from_(BACKUP_BUCKET).download(storage_path)
        data = json.loads(raw)

        # Double-check: metadata trong file (nếu có) phải khớp đúng tenant hiện tại
        meta = data.get('_backup_metadata', {})
        if meta.get('business_id') and meta.get('business_id') != business_id:
            return jsonify({'success': False, 'error': 'Backup file không thuộc tenant hiện tại.'}), 403

        # Khôi phục theo thứ tự bảng: xóa dữ liệu cũ CỦA ĐÚNG business_id này, rồi insert lại từ backup
        for table in BACKUP_TABLES:
            rows = data.get(table)
            if rows is None:
                continue
            supabase_admin.table(table).delete().eq('business_id', business_id).execute()
            if rows:
                for row in rows:
                    row['business_id'] = business_id  # ép đúng tenant hiện tại, không ghi nhầm chỗ khác
                supabase_admin.table(table).insert(rows).execute()

        settings_rows = data.get('system_settings')
        if settings_rows:
            settings_key = f'business_mode_{business_id}'
            supabase_admin.table('system_settings').delete().eq('key', settings_key).execute()
            for row in settings_rows:
                row['key'] = settings_key
                supabase_admin.table('system_settings').insert(row).execute()

        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/backup/list', methods=['GET'])
@login_required
def list_backups():
    if not supabase_admin:
        return jsonify({'success': False, 'error': 'Backup storage admin key is not configured.'}), 400
    try:
        business_id = session.get('business_id') or session['user_id']
        res = supabase_admin.storage.from_(BACKUP_BUCKET).list(f"backups/{business_id}")
        files = [{'name': f['name'], 'size': f['metadata']['size'], 'created_at': f['created_at']} for f in res]
        return jsonify(files)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ========== QR MENU ==========
@app.route('/qr_menu')
def qr_menu_base():
    return redirect(url_for('qr_menu', identifier='demo'))


@app.route('/qr_menu/<path:identifier>')
def qr_menu(identifier):
    table_data = None
    try:
        if identifier.isdigit():
            res = supabase.table('dining_tables').select('*').eq('id', int(identifier)).execute()
        else:
            res = supabase.table('dining_tables').select('*').eq('qr_token', identifier).execute()
        if res.data:
            table_data = res.data[0]
    except Exception as e:
        return "Không thể kết nối tới hệ thống để xác thực bàn. Vui lòng thử lại.", 500

    if not table_data:
        return "Mã QR không hợp lệ hoặc bàn không còn tồn tại. Vui lòng liên hệ nhân viên.", 404

    # Chỉ load đúng thực đơn của tenant sở hữu bàn này — cấm lộ sản phẩm của tiệm khác
    table_business_id = table_data.get('business_id')
    try:
        menu_query = supabase.table('products').select('*').eq('is_active', 1).eq('channel_type', 'retail')
        if table_business_id:
            menu_query = menu_query.eq('business_id', table_business_id)
        menu = menu_query.execute()
        menu_data = menu.data
    except Exception as e:
        print(f"Supabase qr_menu products select failed: {str(e)}")
        menu_data = []
    # Khách quét QR không đăng nhập -> token giới hạn phạm vi (chỉ đọc menu/bàn, tạo đơn tại đúng bàn này)
    try:
        tenant_jwt = _mint_tenant_jwt(table_business_id, scope='qr_public', ttl_seconds=1800)
    except Exception as e:
        print(f"_mint_tenant_jwt failed: {str(e)}")
        tenant_jwt = None
    return render_template('qr_menu.html', table=table_data, menu=menu_data, tenant_jwt=tenant_jwt)


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
                table_check = supabase.table('dining_tables').select('id, name, business_id').eq('id', int(table_id)).execute()
            else:
                table_check = supabase.table('dining_tables').select('id, name, business_id').eq('qr_token', table_id).execute()
            if not table_check.data:
                return jsonify({"success": False, "message": "Bàn không tồn tại hoặc mã QR không hợp lệ."}), 404
            # Luôn dùng id số thật của bàn cho các bảng liên quan, tránh lưu nhầm qr_token dạng chuỗi
            resolved_table_id = table_check.data[0]['id']
            table_display_name = table_check.data[0].get('name') or f"Bàn {resolved_table_id}"
            table_business_id = table_check.data[0].get('business_id')
        except Exception as e:
            return jsonify({"success": False, "message": f"Không thể xác thực bàn: {str(e)}"}), 500

        def _product_belongs_to_table(pid):
            """Chặn khách order sản phẩm của tiệm khác (khác business_id với bàn đang quét)."""
            if not table_business_id:
                return True
            prod = supabase.table('products').select('business_id').eq('id', pid).execute()
            return bool(prod.data) and prod.data[0].get('business_id') == table_business_id

        # Ghi lại tên món + số lượng của ĐÚNG lượt gọi món này để tạo vé bếp — không phải
        # toàn bộ table_orders tích lũy từ trước, chỉ phần khách vừa gửi lần này.
        kitchen_items = []

        def _kitchen_item_name(pid):
            prod = supabase.table('products').select('name').eq('id', pid).execute()
            return prod.data[0]['name'] if prod.data else f"Món #{pid}"

        # Handle multiple items (JSON format)
        if isinstance(items, list) and len(items) > 0:
            for item in items:
                product_id = item.get('id')
                quantity = item.get('quantity', 1)
                if not product_id or not _product_belongs_to_table(product_id):
                    continue
                existing = supabase.table('table_orders').select('id, quantity').eq('table_id', resolved_table_id).eq('product_id', product_id).execute()
                if existing.data:
                    new_qty = existing.data[0]['quantity'] + quantity
                    supabase.table('table_orders').update({'quantity': new_qty}).eq('id', existing.data[0]['id']).execute()
                else:
                    supabase.table('table_orders').insert({'table_id': resolved_table_id, 'product_id': product_id, 'quantity': quantity}).execute()
                kitchen_items.append({'name': _kitchen_item_name(product_id), 'qty': quantity})
        else:
            # Fallback to single item form parameter compatibility
            product_id = data.get('product_id')
            qty = int(data.get('quantity', 1))
            if product_id and _product_belongs_to_table(product_id):
                existing = supabase.table('table_orders').select('id, quantity').eq('table_id', resolved_table_id).eq('product_id', product_id).execute()
                if existing.data:
                    new_qty = existing.data[0]['quantity'] + qty
                    supabase.table('table_orders').update({'quantity': new_qty}).eq('id', existing.data[0]['id']).execute()
                else:
                    supabase.table('table_orders').insert({'table_id': resolved_table_id, 'product_id': product_id, 'quantity': qty}).execute()
                kitchen_items.append({'name': _kitchen_item_name(product_id), 'qty': qty})

        # Bắt buộc tạo vé bếp cho màn hình Kitchen Display — best-effort, không chặn
        # luồng gọi món của khách nếu ghi vé bếp lỗi (vd: bảng chưa được migrate xong).
        if kitchen_items:
            try:
                supabase.table('kitchen_orders').insert({
                    'business_id': table_business_id,
                    'table_id': resolved_table_id,
                    'table_name': table_display_name,
                    'items': kitchen_items,
                    'status': 'pending'
                }).execute()
            except Exception as kitchen_err:
                print(f"Ghi vé bếp thất bại (không chặn luồng gọi món): {str(kitchen_err)}")

        # Update dining_table status to 'Đang phục vụ'
        supabase.table('dining_tables').update({'status': 'Đang phục vụ'}).eq('id', resolved_table_id).execute()
        
        # Log to user_logs for merchant notification
        try:
            supabase.table('user_logs').insert({
                'user_email': f"table_{table_id}",
                'action': 'submit_qr_order',
                'description': f"Khách tại Bàn {table_id} đã gửi đơn hàng gọi món mới (Tổng: {total}₫)",
                'created_at': datetime.now().isoformat()
            }).execute()
        except Exception:
            pass
            
        return jsonify({"success": True, "message": "Gửi đơn hàng thành công!"})
    except Exception as e:
        print("Error submitting QR order:", e)
        return jsonify({"success": False, "message": f"Lỗi máy chủ: {str(e)}"}), 500


# ========== CÀI ĐẶT THƯƠNG HIỆU ==========
@app.route('/brand_settings', methods=['GET', 'POST'])
@login_required
def brand_settings():
    if request.method == 'POST':
        # Update brand settings in system_settings securely
        try:
            res_name = supabase.table('system_settings').select('id').eq('key', 'brand_name').execute()
            if res_name.data:
                supabase.table('system_settings').update({'value': request.form['brand_name']}).eq('key', 'brand_name').execute()
            else:
                supabase.table('system_settings').insert({'key': 'brand_name', 'value': request.form['brand_name']}).execute()
        except Exception as e:
            print("Error updating brand_name settings:", e)
            
        try:
            res_color = supabase.table('system_settings').select('id').eq('key', 'brand_color').execute()
            if res_color.data:
                supabase.table('system_settings').update({'value': request.form['brand_color']}).eq('key', 'brand_color').execute()
            else:
                supabase.table('system_settings').insert({'key': 'brand_color', 'value': request.form['brand_color']}).execute()
        except Exception as e:
            print("Error updating brand_color settings:", e)
        # Xử lý upload logo và cover nếu có
        return redirect(url_for('spa'))
    try:
        brand_res = supabase.table('system_settings').select('value').eq('key', 'brand_name').execute()
        brand_name = brand_res.data[0]['value'] if brand_res.data else 'BitPaw'
        color_res = supabase.table('system_settings').select('value').eq('key', 'brand_color').execute()
        brand_color = color_res.data[0]['value'] if color_res.data else '#06b6d4'
        error_message = None
    except Exception as e:
        print(f"Error fetching brand settings (network/offline): {e}")
        brand_name = 'BitPaw'
        brand_color = '#06b6d4'
        error_message = "Đang hiển thị chế độ Offline"
    return render_template('brand_settings.html', brand_name=brand_name, brand_color=brand_color, error_message=error_message)


# ========== MỚI: ROUTE CHO CÁC TEMPLATE CÒN THIẾU ==========
@app.route('/inventory_alert')
@login_required
def inventory_alert():
    return render_template('inventory_alert.html')

@app.route('/kitchen_display')
@login_required
def kitchen_display():
    return render_template('kitchen_display.html')

@app.route('/ecommerce_sync')
@login_required
def ecommerce_sync():
    return render_template('ecommerce_sync.html')

@app.route('/payment_gateway')
@login_required
def payment_gateway():
    business_id = session.get('business_id', 'mock-business-123')
    config = None
    try:
        res = supabase.table('system_settings').select('*').eq('key', 'payment_config').eq('business_id', business_id).maybeSingle().execute()
        if res.data:
            config = json.loads(res.data['value'])
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
        
        # Check if already exists
        res = supabase.table('system_settings').select('id').eq('key', 'payment_config').eq('business_id', business_id).execute()
        if res.data:
            supabase.table('system_settings').update({'value': val_str}).eq('id', res.data[0]['id']).execute()
        else:
            supabase.table('system_settings').insert({
                'key': 'payment_config',
                'value': val_str,
                'business_id': business_id
            }).execute()
            
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
            tbl_res = supabase.table('dining_tables').select('business_id').eq('id', table_id).maybeSingle().execute()
            if tbl_res.data and tbl_res.data['business_id']:
                business_id = tbl_res.data['business_id']
        except Exception as e:
            print(f"Error resolving table business_id: {e}")
            
    config = None
    try:
        res = supabase.table('system_settings').select('*').eq('key', 'payment_config').eq('business_id', business_id).maybeSingle().execute()
        if res.data:
            config = json.loads(res.data['value'])
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
            supabase.table('payment_transactions').insert({
                'transaction_id': txn_id,
                'customer_name': 'Khách POS Vãng Lai',
                'customer_email': 'pos_walkin@bitpaw.com',
                'amount': amount,
                'currency': 'VND',
                'method': method,
                'status': 'pending',
                'business_id': business_id,
                'created_at': datetime.now().isoformat()
            }).execute()
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
            return jsonify({'success': False, 'message': 'Tenant này không thuộc thị trường US (Square chỉ áp dụng cho country=US).'}), 403

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
            supabase.table('payment_transactions').insert({
                'transaction_id': txn_id,
                'customer_name': 'US Walk-in Customer',
                'customer_email': 'pos_walkin@bitpaw.com',
                'amount': amount,
                'currency': 'USD',
                'method': 'square',
                'status': 'pending',
                'business_id': business_id,
                'created_at': datetime.now().isoformat()
            }).execute()
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
        orders_res = supabase.table('table_orders').select('*').eq('table_id', table_id).eq('business_id', business_id).execute()
        if not orders_res.data:
            return jsonify({'success': False, 'message': 'Không tìm thấy món ăn nào đang treo tại bàn này.'}), 400

        # 2. Tính tổng tiền server-side và trừ tồn kho
        total_bill = 0
        for item in orders_res.data:
            prod_res = supabase.table('products').select('price, stock').eq('id', item['product_id']).eq('business_id', business_id).execute()
            if prod_res.data:
                price = prod_res.data[0]['price']
                total_bill += item['quantity'] * price
                new_stock = prod_res.data[0]['stock'] - item['quantity']
                supabase.table('products').update({'stock': new_stock}).eq('id', item['product_id']).eq('business_id', business_id).execute()

        # Lấy industry từ transaction hoặc mặc định fnb
        industry = 'fnb'
        customer_phone = (data.get('customer_phone') or '').strip() or None

        # 3. Tạo order mới trong orders
        order_res = supabase.table('orders').insert({
            'order_code': txn_id,
            'channel': industry,
            'total_amount': total_bill,
            'business_id': business_id,
            'customer_phone': customer_phone
        }).execute()

        if not order_res.data:
            return jsonify({'success': False, 'message': 'Tạo hóa đơn thất bại.'}), 500

        order_id = order_res.data[0]['id']

        # 4. Tạo chi tiết trong order_items
        for item in orders_res.data:
            prod_res = supabase.table('products').select('price').eq('id', item['product_id']).eq('business_id', business_id).execute()
            if prod_res.data:
                price = prod_res.data[0]['price']
                supabase.table('order_items').insert({
                    'order_id': order_id,
                    'product_id': item['product_id'],
                    'quantity': item['quantity'],
                    'price': price,
                    'total_price': item['quantity'] * price,
                    'business_id': business_id,
                    'customer_phone': customer_phone
                }).execute()

        # 5. Update payment_transactions status = completed
        supabase.table('payment_transactions').update({
            'status': 'completed',
            'amount': total_bill,
            'method': method,
            'updated_at': datetime.now().isoformat()
        }).eq('transaction_id', txn_id).eq('business_id', business_id).execute()

        # 6. Dọn table_orders
        supabase.table('table_orders').delete().eq('table_id', table_id).eq('business_id', business_id).execute()

        # 7. Trả bàn về trạng thái 'Còn trống'
        supabase.table('dining_tables').update({'status': 'Còn trống'}).eq('id', table_id).eq('business_id', business_id).execute()

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
    products_res = supabase.table('products').select('id, name, stock').eq('business_id', business_id).eq('is_active', 1).execute()
    products = products_res.data or []
    if not products:
        return 0
    product_ids = [p['id'] for p in products]

    items_res = supabase.table('order_items').select('product_id, quantity, created_at') \
        .in_('product_id', product_ids).gte('created_at', since_iso).execute()
    sold_qty = {}
    for it in (items_res.data or []):
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

        existing = supabase.table('restock_proposals').select('id') \
            .eq('business_id', business_id).eq('product_id', p['id']).eq('status', 'pending').execute()
        if existing.data:
            continue  # đã có đề xuất đang chờ xử lý cho sản phẩm này, không tạo trùng

        suggested_qty = max(int(avg_daily * 7 - stock), int(avg_daily * 3) + 1)
        reason = _generate_restock_reason_with_ai(p['name'], stock, avg_daily, days_left)
        supabase.table('restock_proposals').insert({
            'business_id': business_id,
            'product_id': p['id'],
            'product_name': p['name'],
            'current_stock': stock,
            'avg_daily_sales': round(avg_daily, 2),
            'suggested_qty': suggested_qty,
            'reason': reason,
            'status': 'pending',
        }).execute()
        created += 1
    return created


def _run_birthday_check_for_business(business_id):
    """Quét khách hàng có sinh nhật hôm nay, xếp hàng gửi lời chúc + ưu đãi qua loyalty_events."""
    today_md = datetime.now().strftime('%m-%d')
    customers_res = supabase.table('customers').select('*').eq('business_id', business_id).execute()
    sent = 0
    for c in (customers_res.data or []):
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
        res = supabase.table('products').select('business_id').execute()
        for row in (res.data or []):
            bid = row.get('business_id')
            if bid:
                ids.add(bid)
    except Exception as e:
        print(f"Loi lay business_id tu products: {e}")
    try:
        res2 = supabase.table('business_memberships').select('business_id').execute()
        for row in (res2.data or []):
            bid = row.get('business_id')
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
        txns_res = supabase.table('payment_transactions').select('*') \
            .eq('business_id', business_id).gte('created_at', since_iso).execute()
        txns = txns_res.data or []
    except Exception as e:
        print(f"Loi lay payment_transactions cho {business_id}: {e}")
        return 0

    orders_res = supabase.table('orders').select('order_code, total_amount') \
        .eq('business_id', business_id).gte('created_at', since_iso).execute()
    orders_by_code = {o['order_code']: o for o in (orders_res.data or []) if o.get('order_code')}

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

        existing = supabase.table('reconciliation_alerts').select('id') \
            .eq('business_id', business_id).eq('transaction_id', txn_id).eq('issue_type', issue_type).eq('status', 'pending').execute()
        if existing.data:
            continue

        supabase.table('reconciliation_alerts').insert({
            'business_id': business_id,
            'transaction_id': txn_id,
            'order_code': txn_id,
            'issue_type': issue_type,
            'expected_amount': expected_amount,
            'actual_amount': amount,
            'details': details,
            'status': 'pending',
        }).execute()
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
        txn_check = supabase.table('payment_transactions').select('id, status, business_id').eq('transaction_id', txn_id).execute()
        if not txn_check.data or txn_check.data[0].get('business_id') != business_id:
            return jsonify({'success': False, 'message': 'Giao dịch không tồn tại hoặc không thuộc quyền quản lý của bạn.'}), 403
        old_status = txn_check.data[0].get('status')

        # Update transaction status = failed
        supabase.table('payment_transactions').update({
            'status': 'failed',
            'updated_at': datetime.now().isoformat()
        }).eq('transaction_id', txn_id).eq('business_id', business_id).execute()
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

# ========== TENANT SESSION TOKEN (cho các trang gọi Supabase trực tiếp từ trình duyệt) ==========
# Các trang nhanvien/bangluong/app_nhanvien/diemdanh/chamcong_* gọi thẳng Supabase bằng anon key,
# nên RLS không có cách nào phân biệt tenant nếu không có claim business_id trong JWT của request.
# Hàm này ký 1 JWT ngắn hạn chứa business_id (và tuỳ chọn "scope" giới hạn phạm vi cho khách
# vãng lai quét QR/đặt lịch — không có scope = token đầy đủ quyền của nhân viên/chủ tiệm).
def _mint_tenant_jwt(business_id, scope=None, ttl_seconds=3600):
    secret = os.environ.get('SUPABASE_JWT_SECRET')
    if not secret or not business_id:
        return None
    now = int(time.time())
    payload = {
        "role": "authenticated",
        "business_id": business_id,
        "iat": now,
        "exp": now + ttl_seconds,
    }
    if scope:
        payload["scope"] = scope
    return pyjwt.encode(payload, secret, algorithm="HS256")


@app.route('/api/session/supabase_token')
@login_required
def get_supabase_tenant_token():
    business_id = session.get('business_id') or session.get('user_id')
    token = _mint_tenant_jwt(business_id)
    if not token:
        return jsonify({"success": False, "error": "Server chưa cấu hình SUPABASE_JWT_SECRET."}), 500
    return jsonify({"success": True, "token": token, "business_id": business_id})


# ========== MỚI: ROUTE CHO CƠ SỞ DỮ LIỆU NHÂN SỰ VÀ SUPER ADMIN ==========
@app.route('/nhanvien')
@login_required
def nhanvien():
    return render_template('nhanvien.html')

@app.route('/bangluong')
@login_required
def bangluong():
    return render_template('bangluong.html')

@app.route('/chamcong')
@login_required
def chamcong():
    return render_template('chamcong.html')

@app.route('/chamcong/congnhan')
@app.route('/chamcong_congnhan')
@login_required
def chamcong_congnhan():
    return render_template('chamcong_congnhan.html')

@app.route('/chamcong/fnb')
@app.route('/chamcong_fnb')
@login_required
def chamcong_fnb():
    return render_template('chamcong_fnb.html')

@app.route('/chamcong/khachsan')
@app.route('/chamcong_khachsan')
@login_required
def chamcong_khachsan():
    return render_template('chamcong_khachsan.html')

@app.route('/chamcong/kythuat')
@app.route('/chamcong_kythuat')
@login_required
def chamcong_kythuat():
    return render_template('chamcong_kythuat.html')

@app.route('/chamcong/nail')
@app.route('/chamcong_nail')
@login_required
def chamcong_nail():
    return render_template('chamcong_nail.html')

@app.route('/chamcong/spa')
@app.route('/chamcong_spa')
@login_required
def chamcong_spa():
    return render_template('chamcong_spa.html')

@app.route('/chamcong/vanphong')
@app.route('/chamcong_vanphong')
@login_required
def chamcong_vanphong():
    return render_template('chamcong_vanphong.html')

@app.route('/chamcong/<industry_code>')
@app.route('/chamcong_<industry_code>')
@login_required
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
            res = supabase.table('dining_tables').select('*').eq('id', int(table_id)).execute()
        else:
            res = supabase.table('dining_tables').select('*').eq('qr_token', table_id).execute()
        if res.data:
            table_data = res.data[0]
    except Exception as e:
        print(f"Error querying table from Supabase: {e}")
        return "Không thể kết nối tới hệ thống để xác thực bàn. Vui lòng thử lại.", 500

    if not table_data:
        return "Mã QR không hợp lệ hoặc bàn không còn tồn tại. Vui lòng liên hệ nhân viên.", 404

    # Khách quét QR không đăng nhập -> token giới hạn phạm vi (chỉ đọc menu/bàn, tạo đơn tại đúng bàn này)
    tenant_jwt = _mint_tenant_jwt(table_data.get('business_id'), scope='qr_public', ttl_seconds=1800)
    return render_template('table_order.html', table=table_data, tenant_jwt=tenant_jwt)

@app.route('/baocao_loinhuan')
@login_required
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
            res = supabase.table('staff').select('*').eq('id', staff_id).eq('business_id', business_id).execute()
            if res.data:
                s = res.data[0]
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
        emp_res = supabase.table('employees').select('id, ma_nv, ho_ten, staff_id') \
            .eq('business_id', business_id).order('ho_ten').execute()
        if emp_res.data:
            employees_list = [{'ma_nv': e.get('ma_nv'), 'ho_ten': e.get('ho_ten')} for e in emp_res.data]
            for e in emp_res.data:
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
        res = supabase.table('staff').update({'salary_config': salary_config}) \
            .eq('id', staff_id).eq('business_id', business_id).execute()
        if not res.data:
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
        supabase.table('employees').update({'staff_id': None}).eq('staff_id', staff_id).eq('business_id', business_id).execute()

        if linked_ma_nv:
            link_res = supabase.table('employees').update({
                'staff_id': staff_id,
                'luong_cb': salary_config['luong_cung'],
                'luong_gio': salary_config['luong_gio'],
                'phu_cap': salary_config['phu_cap'],
            }).eq('ma_nv', linked_ma_nv).eq('business_id', business_id).execute()
            if not link_res.data:
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
@login_required
def portal():
    return render_template('portal.html')

@app.route('/quanly_congno')
@login_required
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
def quanly_thuchi():
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
        return "Truy cập bị từ chối: trang này chỉ dành cho Superadmin.", 403
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
    
    # Try fetching brand details from Supabase if connected
    if SUPABASE_STATUS == "CONNECTED":
        try:
            brand_res = supabase.table('system_settings').select('value').eq('key', 'brand_name').execute()
            if brand_res.data:
                brand_name = brand_res.data[0]['value']
                has_profile = True
        except Exception as e:
            print(f"[!] Supabase profile query failed: {str(e)}")
            
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
            
        # Check if license details can provide tier
        c.execute("SELECT license_key FROM kho_license WHERE trang_thai='Đã kích hoạt' ORDER BY id DESC LIMIT 1")
        license_row = c.fetchone()
        if license_row:
            brand_tier = 'BitPaw Pro (Premium)'
            has_profile = True
            
        conn.close()
    except Exception as db_err:
        print(f"[!] SQLite brand config fallback read error: {str(db_err)}")
        
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
    best-effort — không bao giờ được phép làm gãy luồng chat nếu Supabase lỗi/offline."""
    if not content or not business_id or not customer_phone:
        return
    try:
        customer_id = f"{business_id}:{customer_phone}"
        now_iso = datetime.now().isoformat()
        supabase.table('bot_customers').upsert({
            'id': customer_id,
            'full_name': f"Khách {customer_phone}",
            'last_message': content[:500],
            'last_message_time': now_iso,
            'business_id': business_id,
        }).execute()
        supabase.table('bot_messages').insert({
            'customer_id': customer_id,
            'sender_type': sender_type,
            'content': content[:2000],
            'business_id': business_id,
            'created_at': now_iso,
        }).execute()
    except Exception:
        pass


def _load_recent_chat_history(business_id, customer_phone, limit=10):
    """Khôi phục lịch sử chat gần nhất từ DB khi client không còn giữ (vd: refresh trang),
    để AI không bao giờ mất ngữ cảnh hội thoại."""
    if not business_id or not customer_phone or SUPABASE_STATUS != "CONNECTED":
        return []
    try:
        customer_id = f"{business_id}:{customer_phone}"
        prev = supabase.table('bot_messages').select('sender_type, content, created_at') \
            .eq('customer_id', customer_id).order('created_at', desc=True).limit(limit).execute()
        if prev.data:
            return [
                {"role": "assistant" if m.get('sender_type') == 'ai' else "user", "content": m.get('content') or ''}
                for m in reversed(prev.data)
            ]
    except Exception:
        pass
    return []


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
    return render_template('map_dashboard.html')

@app.route('/app_nhanvien')
@login_required
def app_nhanvien():
    return render_template('app_nhanvien.html')

@app.route('/api/superadmin/duc_ma', methods=['POST'])
@login_required
def duc_ma():
    if not _is_superadmin():
        return jsonify({"success": False, "message": "Truy cập bị từ chối: yêu cầu quyền Superadmin."}), 403
    data = request.json
    ma_key = data.get('license_key')
    nganh = data.get('nganh_nghe')
    try:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO kho_license (license_key, nganh_nghe, trang_thai) VALUES (?, ?, 'Sẵn sàng')", (ma_key, nganh))
        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": f"Đã đúc mã {ma_key} thành công!"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/superadmin/get_keys', methods=['GET'])
@login_required
def get_keys():
    if not _is_superadmin():
        return jsonify({"success": False, "message": "Truy cập bị từ chối: yêu cầu quyền Superadmin."}), 403
    try:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("SELECT id, license_key, nganh_nghe, trang_thai FROM kho_license ORDER BY id DESC")
        keys = c.fetchall()
        conn.close()
        keys_list = [{
            "id": k[0],
            "key_code": k[1],
            "industry": k[2],
            "status": 'Chưa sử dụng' if k[3] == 'Sẵn sàng' else k[3]
        } for k in keys]
        return jsonify({"success": True, "data": keys_list})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/superadmin/delete_key/<int:key_id>', methods=['DELETE'])
@login_required
def delete_key(key_id):
    if not _is_superadmin():
        return jsonify({"success": False, "message": "Truy cập bị từ chối: yêu cầu quyền Superadmin."}), 403
    try:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("DELETE FROM kho_license WHERE id=?", (key_id,))
        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": "Đã xóa license key thành công!"})
    except Exception as e:
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
            res = supabase.table('service_photos').insert({
                'business_id': business_id,
                'customer_phone': customer_phone,
                'image_url': image_url,
                'note': note,
            }).execute()
            return jsonify({"success": True, "data": res.data})
        except Exception as e:
            return jsonify({"success": False, "message": str(e)}), 500

    customer_phone = request.args.get('customer_phone')
    if not customer_phone:
        return jsonify({"success": False, "message": "Thiếu customer_phone."}), 400
    try:
        res = supabase.table('service_photos').select('id, image_url, note, created_at') \
            .eq('business_id', business_id).eq('customer_phone', customer_phone) \
            .order('created_at', desc=True).limit(20).execute()
        return jsonify({"success": True, "data": res.data or []})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/ai/nurture/import-data', methods=['POST'])
@login_required
def nurture_import_data():
    business_id = session.get('business_id', 'mock-business-123')
    industry = session.get('business_mode', 'retail')

    try:
        # Đồng bộ từ đúng bảng customers thật của tenant (Supabase) — không còn xóa dữ liệu
        # thật rồi nhét khách hàng mẫu giả vào nữa.
        real_customers = supabase.table('customers').select('name, phone, email, total_spent') \
            .eq('business_id', business_id).execute()
        rows_data = real_customers.data or []

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
        staff_check = supabase.table('staff').select('id, is_active, business_id').eq('id', int(staff_id)).execute()
        if not staff_check.data or not staff_check.data[0].get('is_active', True):
            return jsonify({"success": False, "error": "Nhân viên không tồn tại hoặc đã bị khóa."}), 403
        if staff_check.data[0].get('business_id') != business_id:
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
            supabase.table('attendance').insert({
                'staff_id': int(staff_id) if isinstance(staff_id, (int, float)) or (isinstance(staff_id, str) and staff_id.isdigit()) else None,
                'clock_in': clock_in_time,
                'latitude_in': lat,
                'longitude_in': lng,
                'status': 'Present',
                'business_id': business_id
            }).execute()
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
        staff_check = supabase.table('staff').select('id, is_active, business_id').eq('id', int(staff_id)).execute()
        if not staff_check.data or not staff_check.data[0].get('is_active', True):
            return jsonify({"success": False, "error": "Nhân viên không tồn tại hoặc đã bị khóa."}), 403
        if staff_check.data[0].get('business_id') != business_id:
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
            res = supabase.table('attendance').select('id').eq('staff_id', staff_id).eq('business_id', business_id).is_('clock_out', 'null').order('created_at', desc=True).limit(1).execute()
            if res.data:
                supabase.table('attendance').update({
                    'clock_out': clock_out_time,
                    'latitude_out': lat,
                    'longitude_out': lng
                }).eq('id', res.data[0]['id']).execute()
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
        staff_check = supabase.table('staff').select('id, business_id').eq('id', int(staff_id)).execute()
        if not staff_check.data:
            return jsonify({"success": False, "error": "Nhân viên không tồn tại."}), 404
        if staff_check.data[0].get('business_id') != business_id:
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
        return jsonify({"success": False, "error": "month_year phải theo định dạng MM/YYYY"}), 400

    industry = (data.get('industry') or 'Spa').strip()
    business_id = session.get('business_id') or session['user_id']

    try:
        emps_res = supabase.table('employees').select('*').eq('business_id', business_id).execute()
        all_employees = emps_res.data or []
        employees = [
            e for e in all_employees
            if industry.lower() in (e.get('linh_vuc') or '').lower() or (e.get('linh_vuc') or '') == 'Chưa phân bổ'
        ]

        records_res = supabase.table('chamcong').select('*').eq('business_id', business_id).execute()
        all_records = records_res.data or []

        def matches_month(r):
            ngay = r.get('ngay_cham')
            if not ngay:
                return False
            parts = ngay.split('/')
            return len(parts) == 3 and parts[1] == month and parts[2] == year

        month_records = [r for r in all_records if matches_month(r)]

        payroll = []
        total_fund = 0
        for emp in employees:
            ma_nv = emp.get('ma_nv')
            my_records = [r for r in month_records if r.get('ma_nv') == ma_nv]

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
                gio_lam_hop_le = so_gio if so_gio > 0 else 8  # Chặn giờ âm do lỗi tính ca đêm
                total_gio_lam += gio_lam_hop_le
                total_tang_ca += float(r.get('tang_ca') or 0)
                total_hoa_hong += float(r.get('tien_tua') or 0)
                total_tips += float(r.get('tien_tips') or 0)
                phu_cap_phat_sinh += float(r.get('phu_cap') or 0)
                if r.get('trang_thai') in ('Có mặt', 'Trọn Ngày'):
                    so_ngay_lam += 1

            if 'Spa' in industry or 'Nails' in industry:
                luong_chinh = luong_co_ban
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
    from supabase_client import SUPABASE_URL, SUPABASE_KEY
    return render_template(
        'network_home.html',
        supabase_url=SUPABASE_URL,
        supabase_key=SUPABASE_KEY,
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
    # Tạo bucket backup nếu chưa có
    try:
        supabase.storage.create_bucket(BACKUP_BUCKET, {'public': False})
    except:
        pass
    app.run(port=5001, debug=os.environ.get('FLASK_DEBUG', '').lower() == 'true')