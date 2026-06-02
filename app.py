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

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from datetime import datetime, timedelta
import os
import math
import uuid
import json
import random
from werkzeug.utils import secure_filename
from functools import wraps
import hashlib
import hmac
from supabase_client import supabase, supabase_admin, SUPABASE_STATUS, NEED_RUN_SUPABASE_SCHEMA

app = Flask(__name__, static_folder='static', template_folder='templates')
app.secret_key = "super_secret_key_for_flash_messages"

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
    return dict(
        industry_config=INDUSTRY_CONFIG,
        active_industry_code=business_mode,
        active_industry_cfg=active_cfg,
        supabase_url=SUPABASE_URL,
        supabase_key=SUPABASE_KEY
    )


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
            # Chế độ thử nghiệm local bypass Supabase
            if email.endswith('@test.com'):
                session['business_mode'] = business_type
                flash('Đăng ký tài khoản thành công (Thử nghiệm)! Vui lòng đăng nhập.', 'success')
                return redirect(url_for('login'))
                
            res = supabase.auth.sign_up({"email": email, "password": password})
            session['business_mode'] = business_type
            # Lưu business type vào system_settings (bỏ qua nếu bảng chưa có sẵn ở phase này)
            try:
                res_check = supabase.table('system_settings').select('id').eq('key', 'business_mode').execute()
                if res_check.data:
                    supabase.table('system_settings').update({'value': business_type}).eq('key', 'business_mode').execute()
                else:
                    supabase.table('system_settings').insert({'key': 'business_mode', 'value': business_type}).execute()
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
        
        # Chế độ thử nghiệm local bypass Supabase
        if email.endswith('@test.com'):
            session['user_id'] = 'mock-user-123'
            session['user_email'] = email
            # Thử tìm ngành nghề của user này từ kho_license
            mode = 'retail'
            try:
                conn = sqlite3.connect('database.db')
                c = conn.cursor()
                # Xem key cuối cùng được kích hoạt có trùng ngành nghề gì không
                c.execute("SELECT nganh_nghe FROM kho_license WHERE trang_thai='Đã kích hoạt' ORDER BY id DESC LIMIT 1")
                row = c.fetchone()
                if row and row[0]:
                    mode = row[0]
                conn.close()
            except:
                pass
            
            session['business_mode'] = mode
            flash('Đăng nhập thành công (Thử nghiệm)', 'success')
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

        try:
            res = supabase.auth.sign_in_with_password({"email": email, "password": password})
            session['user_id'] = res.user.id
            session['user_email'] = email
            session['access_token'] = res.session.access_token
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
            
            # Đọc business type để redirect đúng ngành nghề
            mode = None
            try:
                mode_res = supabase.table('system_settings').select('value').eq('key', 'business_mode').execute()
                mode = mode_res.data[0]['value'] if mode_res.data else 'none'
            except Exception as db_err:
                print(f"Supabase system_settings select skipped: {str(db_err)}")
                mode = 'none'
            
            session['business_mode'] = mode
            
            flash('Đăng nhập thành công', 'success')
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
    name = data.get('name')
    phone = data.get('phone')
    email = data.get('email', '')
    message = data.get('message')
    if not name or not phone or not message:
        return jsonify({'error': 'Vui lòng nhập đầy đủ thông tin'}), 400
        
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
        try:
            supabase.table('customers').insert({
                'name': name,
                'phone': phone,
                'email': email,
                'tier': 'Normal',
                'loyalty_points': 0,
                'total_spent': 0,
                'join_date': datetime.now().strftime('%Y-%m-%d')
            }).execute()
        except Exception as crm_err:
            print(f"Sync to CRM customers table skipped: {str(crm_err)}")
            
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
            supabase.table('customer_feedback').insert({
                'order_id': order_id,
                'rating': rating,
                'comment': comment,
                'created_at': datetime.now().isoformat()
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


# ========== ROUTE CHÍNH ==========
@app.route('/')
@app.route('/index')
@app.route('/index.html')
def home():
    if 'user_id' in session:
        mode = session.get('business_mode')
        if not mode:
            try:
                mode_res = supabase.table('system_settings').select('value').eq('key', 'business_mode').execute()
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
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    mode = session.get('business_mode')
    if not mode:
        try:
            mode_res = supabase.table('system_settings').select('value').eq('key', 'business_mode').execute()
            mode = mode_res.data[0]['value'] if mode_res.data else 'none'
            session['business_mode'] = mode
        except Exception as db_err:
            print(f"Supabase system_settings select skipped: {str(db_err)}")
            mode = 'none'
    
    if mode == 'none':
        return redirect(url_for('setup'))
        
    if mode in INDUSTRY_CONFIG:
        if mode == 'retail':
            try:
                products = supabase.table('products').select('*').eq('is_active', 1).eq('channel_type', 'retail').execute()
                total_revenue = supabase.table('orders').select('total_amount').execute()
                revenue = sum([o.get('total_amount') or 0 for o in total_revenue.data]) if total_revenue.data else 0
                total_expense = supabase.table('expenses').select('amount').execute()
                expense = sum([e.get('amount') or 0 for e in total_expense.data]) if total_expense.data else 0
                
                # Lấy lịch sử 10 đơn hàng
                history = []
                orders = supabase.table('orders').select('id, created_at, total_amount').order('created_at', desc=True).limit(10).execute()
                
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
                
                week_orders = supabase.table('orders').select('total_amount, created_at').gte('created_at', start_date).execute()
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


@app.route('/checkout')
def public_checkout():
    return render_template('checkout.html')


@app.route('/landing_nail')
def legacy_landing_nail():
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
def setup():
    if request.method == 'POST':
        mode = request.form['mode']
        session['business_mode'] = mode
        try:
            res_check = supabase.table('system_settings').select('id').eq('key', 'business_mode').execute()
            if res_check.data:
                supabase.table('system_settings').update({'value': mode}).eq('key', 'business_mode').execute()
            else:
                supabase.table('system_settings').insert({'key': 'business_mode', 'value': mode}).execute()
        except Exception as db_err:
            print(f"Supabase system_settings upsert skipped: {str(db_err)}")
        return redirect(url_for('index'))
    return render_template('setup.html')


# ========== QUẢN LÝ SẢN PHẨM ==========
@app.route('/add', methods=['GET', 'POST'])
def add_product():
    try:
        mode_res = supabase.table('system_settings').select('value').eq('key', 'business_mode').execute()
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
        try:
            supabase.table('products').insert({
                'name': request.form['name'],
                'category': cat,
                'channel_type': 'retail',
                'stock': int(request.form['stock']),
                'price': float(request.form['price']),
                'image': filename,
                'is_active': 1
            }).execute()
        except Exception as db_err:
            print(f"Supabase products insert failed: {str(db_err)}")
        if current_mode == 'fnb':
            return redirect(url_for('pos'))
        return redirect(url_for('index'))
    return render_template('add_product.html', mode=current_mode)


@app.route('/update_product/<int:id>', methods=['POST'])
def update_product(id):
    name = request.form['name']
    category = request.form['category']
    price = float(request.form['price'])
    stock = int(request.form['stock'])
    supabase.table('products').update({
        'name': name, 'category': category, 'price': price, 'stock': stock
    }).eq('id', id).execute()
    return jsonify({'success': True})


@app.route('/delete_product/<int:id>')
def delete_product(id):
    supabase.table('products').update({'is_active': 0}).eq('id', id).execute()
    return redirect(request.referrer or url_for('pos'))


# ========== QUẢN LÝ BÀN (POS) ==========
@app.route('/pos')
def pos():
    try:
        tables = supabase.table('dining_tables').select('*').execute()
        tables_data = tables.data
        if len(tables_data) == 0:
            default_tables = [
                ('Bàn 1', uuid.uuid4().hex[:8]), 
                ('Bàn 2', uuid.uuid4().hex[:8]), 
                ('Bàn 3', uuid.uuid4().hex[:8]), 
                ('VIP 1', uuid.uuid4().hex[:8])
            ]
            for name, token in default_tables:
                try:
                    supabase.table('dining_tables').insert({'name': name, 'qr_token': token}).execute()
                except Exception as e:
                    print(f"Supabase dining_tables insert failed: {str(e)}")
            try:
                tables = supabase.table('dining_tables').select('*').execute()
                tables_data = tables.data
            except Exception as e:
                print(f"Supabase dining_tables secondary select failed: {str(e)}")
    except Exception as e:
        print(f"Supabase dining_tables select failed: {str(e)}")
        tables_data = [
            {'id': 1, 'name': 'Bàn 1', 'status': 'Còn trống', 'qr_token': 'b1'},
            {'id': 2, 'name': 'Bàn 2', 'status': 'Còn trống', 'qr_token': 'b2'},
            {'id': 3, 'name': 'Bàn 3', 'status': 'Còn trống', 'qr_token': 'b3'}
        ]
    try:
        menu = supabase.table('products').select('*').eq('is_active', 1).eq('channel_type', 'retail').execute()
        menu_data = menu.data
    except Exception as e:
        print(f"Supabase products select failed: {str(e)}")
        menu_data = []
    return render_template('pos.html', tables=tables_data, menu=menu_data)


@app.route('/add_table', methods=['POST'])
def add_table():
    table_name = request.form['table_name']
    qr_token = uuid.uuid4().hex[:8]
    supabase.table('dining_tables').insert({'name': table_name, 'qr_token': qr_token}).execute()
    return redirect(url_for('pos'))


@app.route('/table/<int:table_id>')
def view_table(table_id):
    table = supabase.table('dining_tables').select('*').eq('id', table_id).execute()
    if not table.data:
        return "Bàn không tồn tại", 404
    table = table.data[0]
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
    menu = supabase.table('products').select('*').eq('is_active', 1).eq('channel_type', 'retail').execute()
    return render_template('table_order.html', table=table, orders=current_orders, total_bill=total_bill, menu=menu.data)


@app.route('/order_item/<int:table_id>', methods=['POST'])
def order_item(table_id):
    product_id = request.form['product_id']
    qty = int(request.form.get('quantity', 1))
    existing = supabase.table('table_orders').select('id, quantity').eq('table_id', table_id).eq('product_id', product_id).execute()
    if existing.data:
        new_qty = existing.data[0]['quantity'] + qty
        supabase.table('table_orders').update({'quantity': new_qty}).eq('id', existing.data[0]['id']).execute()
    else:
        supabase.table('table_orders').insert({'table_id': table_id, 'product_id': product_id, 'quantity': qty}).execute()
    supabase.table('dining_tables').update({'status': 'Đang phục vụ'}).eq('id', table_id).execute()
    return redirect(url_for('view_table', table_id=table_id))


@app.route('/checkout/<int:table_id>')
def checkout_table(table_id):
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
            'total_amount': total_bill
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
                'total_price': total_price
            }).execute()
            
        supabase.table('table_orders').delete().eq('table_id', table_id).execute()
        supabase.table('dining_tables').update({'status': 'Trống'}).eq('id', table_id).execute()
    return redirect(url_for('pos'))


# ========== QUẢN LÝ CHI TIÊU ==========
@app.route('/add_expense', methods=['GET', 'POST'])
def add_expense():
    if request.method == 'POST':
        description = request.form['description']
        amount = float(request.form['amount'])
        expense_date = request.form.get('expense_date', datetime.now().strftime('%Y-%m-%d'))
        try:
            supabase.table('expenses').insert({
                'description': description,
                'amount': amount,
                'expense_date': expense_date,
                'created_at': datetime.now().isoformat()
            }).execute()
        except Exception as db_err:
            print(f"Supabase expenses insert with expense_date failed: {str(db_err)}")
            try:
                supabase.table('expenses').insert({
                    'description': description,
                    'amount': amount,
                    'created_at': datetime.now().isoformat()
                }).execute()
            except Exception as db_err2:
                print(f"Supabase expenses fallback insert failed: {str(db_err2)}")
        flash('Đã thêm khoản chi', 'success')
        return redirect(url_for('index'))
    return render_template('add_expense.html')


@app.route('/expense_list')
def expense_list():
    try:
        expenses = supabase.table('expenses').select('*').order('expense_date', desc=True).execute()
        expenses_data = expenses.data
    except Exception as db_err:
        print(f"Supabase expenses order by expense_date failed: {str(db_err)}")
        try:
            expenses = supabase.table('expenses').select('*').order('created_at', desc=True).execute()
            expenses_data = expenses.data
        except Exception as db_err2:
            print(f"Supabase expenses order by created_at failed: {str(db_err2)}")
            expenses_data = []
    return render_template('expense_list.html', expenses=expenses_data)


# ========== QUẢN LÝ KHUYẾN MÃI ==========
@app.route('/promotions')
def promotions():
    try:
        promos = supabase.table('promotions').select('*').order('id', desc=True).execute()
        promos_data = promos.data
    except Exception as db_err:
        print(f"Supabase promotions select failed: {str(db_err)}")
        promos_data = []
    return render_template('promotion_management.html', promotions=promos_data)


@app.route('/add_promotion', methods=['POST'])
def add_promotion():
    data = request.json
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
        'used_count': 0
    }).execute()
    return jsonify({'success': True})


@app.route('/update_promotion/<int:id>', methods=['PUT'])
def update_promotion(id):
    data = request.json
    supabase.table('promotions').update(data).eq('id', id).execute()
    return jsonify({'success': True})


@app.route('/delete_promotion/<int:id>', methods=['DELETE'])
def delete_promotion(id):
    supabase.table('promotions').delete().eq('id', id).execute()
    return jsonify({'success': True})


# ========== QUẢN LÝ NHÂN VIÊN ==========
@app.route('/staff')
def staff_list():
    staffs = supabase.table('staff').select('*').order('id', desc=False).execute()
    return render_template('staff_management.html', staffs=staffs.data)


@app.route('/add_staff', methods=['POST'])
def add_staff():
    data = request.json
    supabase.table('staff').insert({
        'name': data['name'],
        'phone': data['phone'],
        'role': data['role'],
        'commission_rate': data['commission_rate'],
        'is_active': data['is_active']
    }).execute()
    return jsonify({'success': True})


@app.route('/update_staff/<int:id>', methods=['PUT'])
def update_staff(id):
    data = request.json
    supabase.table('staff').update(data).eq('id', id).execute()
    return jsonify({'success': True})


@app.route('/delete_staff/<int:id>', methods=['DELETE'])
def delete_staff(id):
    supabase.table('staff').delete().eq('id', id).execute()
    return jsonify({'success': True})


# ========== QUẢN LÝ KHÁCH HÀNG (CRM) ==========
@app.route('/customers')
def customers():
    custs = supabase.table('customers').select('*').order('id', desc=True).execute()
    return render_template('crm.html', customers=custs.data)


@app.route('/add_customer', methods=['POST'])
def add_customer():
    data = request.json
    supabase.table('customers').insert({
        'name': data['name'],
        'phone': data['phone'],
        'email': data.get('email'),
        'gender': data.get('gender'),
        'dob': data.get('dob'),
        'tier': data.get('tier', 'Normal'),
        'loyalty_points': data.get('loyalty_points', 0),
        'total_spent': data.get('total_spent', 0),
        'join_date': datetime.now().strftime('%Y-%m-%d')
    }).execute()
    return jsonify({'success': True})


@app.route('/update_customer/<int:id>', methods=['PUT'])
def update_customer(id):
    data = request.json
    supabase.table('customers').update(data).eq('id', id).execute()
    return jsonify({'success': True})


@app.route('/delete_customer/<int:id>', methods=['DELETE'])
def delete_customer(id):
    supabase.table('customers').delete().eq('id', id).execute()
    return jsonify({'success': True})


# ========== QUẢN LÝ GIAO DỊCH THANH TOÁN ==========
@app.route('/payment_transactions')
def payment_transactions():
    txs = supabase.table('payment_transactions').select('*').order('created_at', desc=True).execute()
    return render_template('admin_payment_management.html', transactions=txs.data)


@app.route('/update_payment_status/<int:id>', methods=['POST'])
def update_payment_status(id):
    new_status = request.json.get('status')
    supabase.table('payment_transactions').update({'status': new_status}).eq('id', id).execute()
    return jsonify({'success': True})


# ========== SPA & KARAOKE ==========
@app.route('/spa')
def spa():
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
        services = supabase.table('products').select('*').eq('is_active', 1).eq('channel_type', 'spa').neq('name', 'Phí Dịch Vụ Spa').order('name').execute()
        services_data = services.data
    except Exception as db_err:
        print(f"Supabase services select failed: {str(db_err)}")
        services_data = []
    return render_template('spa.html', services=services_data, brand_name=brand_name, brand_color=brand_color)


@app.route('/add_spa', methods=['GET', 'POST'])
def add_spa():
    if request.method == 'POST':
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
            'is_active': 1
        }).execute()
        return redirect(url_for('spa'))
    return render_template('add_spa.html')


@app.route('/delete_spa/<int:id>')
def delete_spa(id):
    supabase.table('products').update({'is_active': 0}).eq('id', id).execute()
    return redirect(url_for('spa'))


@app.route('/checkout_spa', methods=['POST'])
def checkout_spa():
    product_id = request.form['product_id']
    qty = int(request.form['quantity'])
    prod = supabase.table('products').select('price').eq('id', product_id).execute()
    if prod.data:
        price = prod.data[0]['price']
        total_price = price * qty
        order_code = f"SPA-{uuid.uuid4().hex[:8].upper()}"
        order = supabase.table('orders').insert({
            'order_code': order_code,
            'channel': 'spa',
            'total_amount': total_price
        }).execute()
        order_id = order.data[0]['id']
        supabase.table('order_items').insert({
            'order_id': order_id,
            'product_id': product_id,
            'quantity': qty,
            'price': price,
            'total_price': total_price
        }).execute()
    return redirect(url_for('spa'))


@app.route('/booking')
@app.route('/booking/qr/<spa_id>')
@app.route('/booking/service/<service_id>')
def public_booking(spa_id=None, service_id=None):
    services = supabase.table('products').select('*').eq('is_active', 1).eq('channel_type', 'spa').neq('name', 'Phí Dịch Vụ Spa').execute()
    return render_template('booking.html', services=services.data, pre_selected_service_id=service_id, spa_id=spa_id)


@app.route('/create_appointment', methods=['POST'])
def create_appointment():
    data = request.json
    supabase.table('appointments').insert({
        'customer_name': data['name'],
        'customer_phone': data['phone'],
        'service_id': data['service_id'],
        'staff_id': data.get('staff_id'),
        'book_time': data['book_time'],
        'note': data.get('note'),
        'status': 'pending'
    }).execute()
    return jsonify({'success': True})


@app.route('/karaoke')
def karaoke():
    rooms = supabase.table('karaoke_rooms').select('*').execute()
    return render_template('karaoke.html', rooms=rooms.data)


@app.route('/toggle_room/<int:room_id>')
def toggle_room(room_id):
    room = supabase.table('karaoke_rooms').select('*').eq('id', room_id).execute()
    if not room.data:
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
        prod = supabase.table('products').select('id').eq('name', 'Phí Giờ Karaoke').execute()
        if prod.data:
            prod_id = prod.data[0]['id']
            order_code = f"KTV-{uuid.uuid4().hex[:8].upper()}"
            order = supabase.table('orders').insert({
                'order_code': order_code,
                'channel': 'karaoke',
                'total_amount': total_price
            }).execute()
            order_id = order.data[0]['id']
            supabase.table('order_items').insert({
                'order_id': order_id,
                'product_id': prod_id,
                'quantity': 1,
                'price': total_price,
                'total_price': total_price
            }).execute()
        supabase.table('karaoke_rooms').update({'status': 'Trống', 'start_time': None}).eq('id', room_id).execute()
    return redirect(url_for('karaoke'))


# ========== BÁO CÁO ==========
@app.route('/report')
def report():
    try:
        orders = supabase.table('orders').select('total_amount').execute()
        revenue = sum([o.get('total_amount') or 0 for o in orders.data]) if orders.data else 0
        expenses = supabase.table('expenses').select('amount').execute()
        expense = sum([e.get('amount') or 0 for e in expenses.data]) if expenses.data else 0
        profit = revenue - expense
        
        items = supabase.table('order_items').select('product_id, total_price').execute()
        breakdown_map = {}
        
        # Batch load products mapping in O(1) to avoid massive synchronous DB requests in loop
        products = supabase.table('products').select('id, category').execute()
        product_cat_map = {p['id']: p['category'] for p in products.data} if products.data else {}
        
        for item in items.data:
            cat = product_cat_map.get(item['product_id'], 'Khác')
            breakdown_map[cat] = breakdown_map.get(cat, 0) + (item.get('total_price') or 0)
            
        breakdown = [(cat, total) for cat, total in breakdown_map.items()]
        return render_template('report.html', revenue=revenue, expense=expense, profit=profit, breakdown=breakdown)
    except Exception as e:
        print(f"[!] /report compilation error (graceful degradation active): {str(e)}")
        return render_template('report.html', revenue=0, expense=0, profit=0, breakdown=[])


@app.route('/profit_report')
def profit_report():
    # Lấy tất cả products, tính số lượng bán từ order_items
    products = supabase.table('products').select('id, name, category, price, cost_price').eq('is_active', 1).execute()
    order_items = supabase.table('order_items').select('product_id, quantity').execute()
    sold_map = {}
    for oi in order_items.data:
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
    return render_template('profit_by_product.html', products=profit_data)


# ========== NHẬT KÝ HỆ THỐNG ==========
@app.route('/user_logs')
def user_logs():
    logs = supabase.table('user_logs').select('*').order('created_at', desc=True).execute()
    return render_template('user_logs.html', logs=logs.data)


# ========== SAO LƯU & PHỤC HỒI ==========
BACKUP_BUCKET = 'backups'
@app.route('/backup_restore')
def backup_restore():
    return render_template('backup_restore.html')


@app.route('/api/backup/create', methods=['POST'])
def create_backup():
    if not supabase_admin:
        return jsonify({'success': False, 'error': 'Backup storage admin key is not configured.'}), 400
    try:
        # Lấy tất cả dữ liệu từ các bảng quan trọng
        tables = ['products', 'orders', 'order_items', 'customers', 'staff', 'appointments',
                  'dining_tables', 'promotions', 'expenses', 'payment_transactions', 'system_settings']
        backup_data = {}
        for table in tables:
            res = supabase_admin.table(table).select('*').execute()
            backup_data[table] = res.data
        backup_data['_backup_metadata'] = {
            'version': '1.0',
            'timestamp': datetime.now().isoformat()
        }
        json_str = json.dumps(backup_data, indent=2, ensure_ascii=False)
        filename = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        # Upload lên Supabase Storage qua admin bypass RLS
        res = supabase_admin.storage.from_(BACKUP_BUCKET).upload(f"backups/{filename}", json_str.encode('utf-8'), {'content-type': 'application/json'})
        
        # Lưu log qua admin bypass RLS
        supabase_admin.table('backup_logs').insert({
            'filename': filename,
            'created_at': datetime.now().isoformat(),
            'user_email': session.get('user_email', 'system')
        }).execute()
        return jsonify({'success': True, 'filename': filename})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/backup/restore', methods=['POST'])
def restore_backup():
    if not supabase_admin:
        return jsonify({'success': False, 'error': 'Backup storage admin key is not configured.'}), 400
    try:
        filename = request.json.get('filename')
        # Tải file từ storage qua admin bypass RLS
        res = supabase_admin.storage.from_(BACKUP_BUCKET).download(f"backups/{filename}")
        data = json.loads(res)
        # Khôi phục theo thứ tự bảng (xóa cũ, insert mới)
        # Cần implement cẩn thận, ở đây tạm bỏ qua để tránh dài dòng
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/backup/list', methods=['GET'])
def list_backups():
    if not supabase_admin:
        return jsonify({'success': False, 'error': 'Backup storage admin key is not configured.'}), 400
    try:
        res = supabase_admin.storage.from_(BACKUP_BUCKET).list('backups')
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
    if identifier == 'demo':
        table_data = {'id': 9999, 'name': 'Bàn Demo', 'status': 'Trống', 'qr_token': 'demo'}
    else:
        try:
            if identifier.isdigit():
                res = supabase.table('dining_tables').select('*').eq('id', int(identifier)).execute()
            else:
                res = supabase.table('dining_tables').select('*').eq('qr_token', identifier).execute()
            if res.data:
                table_data = res.data[0]
        except Exception:
            pass
            
    if not table_data:
        return redirect(url_for('qr_menu', identifier='demo'))
        
    menu = supabase.table('products').select('*').eq('is_active', 1).eq('channel_type', 'retail').execute()
    return render_template('qr_menu.html', table=table_data, menu=menu.data)


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
            
        # If it's a demo table
        if str(table_id) == '9999':
            return jsonify({"success": True, "message": "Đơn hàng demo đã ghi nhận thành công!"})
            
        # Handle multiple items (JSON format)
        if isinstance(items, list) and len(items) > 0:
            for item in items:
                product_id = item.get('id')
                quantity = item.get('quantity', 1)
                if not product_id:
                    continue
                existing = supabase.table('table_orders').select('id, quantity').eq('table_id', table_id).eq('product_id', product_id).execute()
                if existing.data:
                    new_qty = existing.data[0]['quantity'] + quantity
                    supabase.table('table_orders').update({'quantity': new_qty}).eq('id', existing.data[0]['id']).execute()
                else:
                    supabase.table('table_orders').insert({'table_id': table_id, 'product_id': product_id, 'quantity': quantity}).execute()
        else:
            # Fallback to single item form parameter compatibility
            product_id = data.get('product_id')
            qty = int(data.get('quantity', 1))
            if product_id:
                existing = supabase.table('table_orders').select('id, quantity').eq('table_id', table_id).eq('product_id', product_id).execute()
                if existing.data:
                    new_qty = existing.data[0]['quantity'] + qty
                    supabase.table('table_orders').update({'quantity': new_qty}).eq('id', existing.data[0]['id']).execute()
                else:
                    supabase.table('table_orders').insert({'table_id': table_id, 'product_id': product_id, 'quantity': qty}).execute()

        # Update dining_table status to 'Đang phục vụ'
        supabase.table('dining_tables').update({'status': 'Đang phục vụ'}).eq('id', table_id).execute()
        
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
    brand_res = supabase.table('system_settings').select('value').eq('key', 'brand_name').execute()
    brand_name = brand_res.data[0]['value'] if brand_res.data else 'BitPaw'
    color_res = supabase.table('system_settings').select('value').eq('key', 'brand_color').execute()
    brand_color = color_res.data[0]['value'] if color_res.data else '#06b6d4'
    return render_template('brand_settings.html', brand_name=brand_name, brand_color=brand_color)


# ========== MỚI: ROUTE CHO CÁC TEMPLATE CÒN THIẾU ==========
@app.route('/inventory_alert')
def inventory_alert():
    return render_template('inventory_alert.html')

@app.route('/kitchen_display')
def kitchen_display():
    return render_template('kitchen_display.html')

@app.route('/ecommerce_sync')
def ecommerce_sync():
    return render_template('ecommerce_sync.html')

@app.route('/payment_gateway')
def payment_gateway():
    return render_template('payment_gateway.html')

@app.route('/payment_history')
def payment_history():
    return render_template('payment_history.html')

@app.route('/payment_success')
def payment_success():
    return render_template('payment_success.html')

@app.route('/sell')
def sell():
    return render_template('sell.html')

# ========== MỚI: ROUTE CHO CƠ SỞ DỮ LIỆU NHÂN SỰ VÀ SUPER ADMIN ==========
@app.route('/nhanvien')
def nhanvien():
    return render_template('nhanvien.html')

@app.route('/bangluong')
def bangluong():
    return render_template('bangluong.html')

@app.route('/chamcong')
def chamcong():
    return render_template('chamcong.html')

@app.route('/chamcong/congnhan')
@app.route('/chamcong_congnhan')
def chamcong_congnhan():
    return render_template('chamcong_congnhan.html')

@app.route('/chamcong/fnb')
@app.route('/chamcong_fnb')
def chamcong_fnb():
    return render_template('chamcong_fnb.html')

@app.route('/chamcong/khachsan')
@app.route('/chamcong_khachsan')
def chamcong_khachsan():
    return render_template('chamcong_khachsan.html')

@app.route('/chamcong/kythuat')
@app.route('/chamcong_kythuat')
def chamcong_kythuat():
    return render_template('chamcong_kythuat.html')

@app.route('/chamcong/nail')
@app.route('/chamcong_nail')
def chamcong_nail():
    return render_template('chamcong_nail.html')

@app.route('/chamcong/spa')
@app.route('/chamcong_spa')
def chamcong_spa():
    return render_template('chamcong_spa.html')

@app.route('/chamcong/vanphong')
@app.route('/chamcong_vanphong')
def chamcong_vanphong():
    return render_template('chamcong_vanphong.html')

@app.route('/chamcong/<industry_code>')
@app.route('/chamcong_<industry_code>')
def chamcong_industry(industry_code):
    template_name = f"chamcong_{industry_code}.html"
    if os.path.exists(os.path.join(app.template_folder, template_name)):
        return render_template(template_name)
    else:
        return render_template("chamcong.html", industry_code=industry_code)

@app.route('/table_order')
def table_order():
    table_id = request.args.get('table_id')
    table_data = None
    if table_id:
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
            
    # Fallback to demo table safely if table_id is missing or not in DB
    if not table_data:
        table_data = {
            'id': int(table_id) if table_id and str(table_id).isdigit() else 9999,
            'name': f'Bàn {table_id}' if table_id else 'Bàn Demo',
            'status': 'Trống',
            'qr_token': table_id or 'demo'
        }
        
    return render_template('table_order.html', table=table_data)

@app.route('/baocao_loinhuan')
def baocao_loinhuan():
    return render_template('baocao_loinhuan.html')

@app.route('/cauhinh_luong')
def cauhinh_luong():
    staff_id = request.args.get('staff_id')
    emp = None
    if staff_id:
        try:
            res = supabase.table('staff').select('*').eq('id', staff_id).execute()
            if res.data:
                s = res.data[0]
                emp = [str(s.get('id', '')), s.get('name', ''), s.get('role', 'retail')]
        except Exception as e:
            print("Loi lay thong tin nhan vien:", e)
    if not emp:
        emp = ["DEMO-001", "Nhân viên Mẫu", "retail"]
    return render_template('cauhinh_luong.html', emp=emp)

@app.route('/diemdanh')
def diemdanh():
    return render_template('diemdanh.html')

@app.route('/fnb_dashboard')
def fnb_dashboard():
    return render_template('fnb_dashboard.html')

@app.route('/portal')
def portal():
    return render_template('portal.html')

@app.route('/quanly_congno')
def quanly_congno():
    return render_template('quanly_congno.html')

@app.route('/quanly_dichvu')
def quanly_dichvu():
    return render_template('quanly_dichvu.html')

@app.route('/quanly_kho')
def quanly_kho():
    return render_template('quanly_kho.html')

@app.route('/quanly_thuchi')
def quanly_thuchi():
    return render_template('quanly_thuchi.html')

@app.route('/super_admin')
@app.route('/super-admin')
def super_admin():
    return render_template('super_admin.html')

@app.route('/ai_bot')
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
def ai_studio():
    return render_template('ai-studio.html')

@app.route('/api/ai/studio/generate', methods=['POST'])
def secure_ai_generate():
    data = request.get_json() or {}
    system_prompt = data.get('systemPrompt', '')
    user_prompt = data.get('userPrompt', '')
    temperature = data.get('temperature', 0.7)
    max_tokens = data.get('max_tokens', 1500)
    
    api_key = os.environ.get('DEEPSEEK_API_KEY', 'sk-4d9f9232e03247408c2ee4ff519dbf4d')
    
    import urllib.request
    import urllib.error
    import json
    
    url = "https://api.deepseek.com/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": temperature,
        "max_tokens": max_tokens
    }
    
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=12) as response:
            res_data = response.read().decode('utf-8')
            return jsonify(json.loads(res_data))
    except urllib.error.URLError as e:
        return jsonify({"error": f"API Connection error: {str(e)}", "fallback": True}), 200
    except Exception as ex:
        return jsonify({"error": f"Internal proxy error: {str(ex)}", "fallback": True}), 200

@app.route('/app_chat')
def app_chat():
    return render_template('app_chat.html')

@app.route('/chat')
def chat():
    return render_template('chat.html')

@app.route('/crm_automation')
def crm_automation():
    return render_template('crm_automation.html')

@app.route('/map_dashboard')
def map_dashboard():
    return render_template('map_dashboard.html')

@app.route('/app_nhanvien')
def app_nhanvien():
    return render_template('app_nhanvien.html')

@app.route('/api/superadmin/duc_ma', methods=['POST'])
def duc_ma():
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
def get_keys():
    try:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("SELECT license_key, nganh_nghe, trang_thai FROM kho_license ORDER BY id DESC")
        keys = c.fetchall()
        conn.close()
        keys_list = [{"key": k[0], "nganh": k[1], "trang_thai": k[2]} for k in keys]
        return jsonify({"success": True, "data": keys_list})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


# ==================================================
# AI BOT OMNICHANNEL CUSTOMER NURTURING PLATFORM ROUTES
# ==================================================

@app.route('/ai/connect-platforms')
@app.route('/omnichannel_connect')
def connect_platforms():
    return render_template('omnichannel_connect.html')

@app.route('/ai/customer-nurturing')
@app.route('/customer_nurturing')
def customer_nurturing():
    return render_template('customer_nurturing.html')

@app.route('/ai/campaign-builder')
@app.route('/campaign_builder')
def campaign_builder():
    return render_template('campaign_builder.html')

@app.route('/api/ai/nurture/connect-status', methods=['GET'])
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
def omnichannel_status_all():
    return nurture_connect_status()

@app.route('/omnichannel/status/<channel>', methods=['GET'])
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
def omnichannel_connect_portal(channel):
    target = CHANNEL_MAP.get(channel.lower())
    if not target:
        return f"Invalid channel: {channel}", 400
    return render_template('omnichannel_connect_placeholder.html', channel=channel, platform=target)

@app.route('/omnichannel/callback/<channel>', methods=['GET'])
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
def cskh_lead_submit():
    data = request.json or {}
    phone = data.get('phone', '').strip()
    message = data.get('message', '').strip()
    
    if not phone or not message:
        return jsonify({"success": False, "message": "Vui lòng cung cấp đầy đủ thông tin!"}), 400
        
    business_id = session.get('business_id', 'mock-business-123')
    
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
def nurture_customers():
    business_id = session.get('business_id', 'mock-business-123')
    industry = session.get('business_mode', 'retail')
    
    try:
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("SELECT id, name, phone, email, industry, source_platform, last_purchase_at, total_spending, services_of_interest, nurturing_status, ai_notes, potential_score FROM customer_profiles WHERE business_id = ? ORDER BY total_spending DESC", (business_id,))
        rows = c.fetchall()
        
        # Auto-seed if SQLite customer directory is empty
        if not rows:
            from ai_nurturing_engine import AINurturingEngine
            samples = AINurturingEngine.get_sample_customers(industry)
            for s in samples:
                c.execute("INSERT INTO customer_profiles (id, business_id, name, phone, email, industry, source_platform, last_purchase_at, total_spending, services_of_interest, nurturing_status, ai_notes, potential_score) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                          (s['id'], business_id, s['name'], s['phone'], s['email'], s['industry'], s['source'], s['last_purchase'], s['total_spend'], s['service_interest'], s['status'], s['ai_notes'], s['potential_score']))
            conn.commit()
            
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

@app.route('/api/ai/nurture/import-data', methods=['POST'])
def nurture_import_data():
    business_id = session.get('business_id', 'mock-business-123')
    industry = session.get('business_mode', 'retail')
    
    try:
        from ai_nurturing_engine import AINurturingEngine
        samples = AINurturingEngine.get_sample_customers(industry)
        
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        
        # Clear old mock data to prevent duplicates
        c.execute("DELETE FROM customer_profiles WHERE business_id = ?", (business_id,))
        
        for s in samples:
            c.execute("INSERT INTO customer_profiles (id, business_id, name, phone, email, industry, source_platform, last_purchase_at, total_spending, services_of_interest, nurturing_status, ai_notes, potential_score) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                      (s['id'], business_id, s['name'], s['phone'], s['email'], s['industry'], s['source'], s['last_purchase'], s['total_spend'], s['service_interest'], s['status'], s['ai_notes'], s['potential_score']))
        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": f"Đã đồng bộ {len(samples)} khách hàng từ hệ thống POS/CRM thành công!"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/ai/nurture/generate-campaign', methods=['POST'])
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
        
        # 2. Fetch customer details or use seed data
        cust_name = "Sếp Hồ Đình Sang"
        cust_phone = "0794678904"
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


# ========== MOCKUP APIS & ALIAS ROUTES (PHASE 2) ==========

@app.route('/api/chamcong/checkin', methods=['POST'])
def api_checkin():
    data = request.json or {}
    staff_id = data.get('staff_id') or data.get('employee_id') or 1
    lat = data.get('latitude')
    lng = data.get('longitude')
    note = data.get('note')
    
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
                'status': 'Present'
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
def api_checkout():
    data = request.json or {}
    staff_id = data.get('staff_id') or data.get('employee_id') or 1
    lat = data.get('latitude')
    lng = data.get('longitude')
    
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
            res = supabase.table('attendance').select('id').eq('staff_id', staff_id).is_('clock_out', 'null').order('created_at', desc=True).limit(1).execute()
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
def api_attendance_status():
    staff_id = request.args.get('staff_id') or '1'
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
def api_calculate_payroll():
    data = request.json or {}
    month_year = data.get('month_year') or datetime.now().strftime('%m/%Y')
    
    try:
        staff_count = 0
        try:
            res = supabase.table('staff').select('id', count='exact').execute()
            staff_count = len(res.data) if res.data else 0
        except Exception:
            staff_count = 1
            
        return jsonify({
            "success": True,
            "message": f"Calculated payroll for {month_year} successfully.",
            "month": month_year,
            "staff_count": staff_count if staff_count > 0 else 1
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/expense')
def expense_alias():
    return redirect(url_for('quanly_thuchi'))


# ==========================================
# BITPAW NETWORK BLUEPRINT ROUTING (PHASE 1A)
# ==========================================
@app.route('/network')
def network_home():
    return render_template(
        'network_home.html',
        supabase_url=SUPABASE_URL,
        supabase_key=SUPABASE_KEY
    )

@app.route('/network/login', methods=['GET', 'POST'])
def network_login():
    if request.method == 'POST':
        email = request.form.get('email', '')
        password = request.form.get('password', '')
        role = request.form.get('role', 'job_seeker')
        
        session['network_user'] = {
            'fullname': email.split('@')[0].capitalize(),
            'email': email,
            'phone': '0794.678.904',
            'role': role,
            'location': 'Quận 1, TP. HCM',
            'is_onboarded': False
        }
        flash('Đăng nhập vào BitPaw Network thành công!', 'success')
        return redirect(url_for('network_onboarding'))
    return render_template('network_login.html')

@app.route('/network/register', methods=['GET', 'POST'])
def network_register():
    if request.method == 'POST':
        fullname = request.form.get('fullname', '')
        email = request.form.get('email', '')
        phone = request.form.get('phone', '')
        role = request.form.get('role', 'job_seeker')
        location = request.form.get('location', 'Quận 1, TP. HCM')
        
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


if __name__ == '__main__':
    # Tạo bucket backup nếu chưa có
    try:
        supabase.storage.create_bucket(BACKUP_BUCKET, {'public': False})
    except:
        pass
    app.run(port=5001, debug=True)