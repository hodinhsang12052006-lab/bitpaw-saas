from functools import wraps
from flask import session, redirect, url_for, flash
from supabase_client import supabase, SUPABASE_STATUS

class AuthService:
    @staticmethod
    def login_required(f):
        """Decorator to restrict view access to authenticated user sessions."""
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                flash('Vui lòng đăng nhập để tiếp tục', 'danger')
                return redirect(url_for('login'))
            return f(*args, **kwargs)
        return decorated_function

    @staticmethod
    def role_required(required_roles):
        """Restricts view access to specific security roles (e.g. 'admin', 'superadmin')."""
        def decorator(f):
            @wraps(f)
            def decorated_function(*args, **kwargs):
                user_role = session.get('role', 'staff')
                if user_role not in required_roles:
                    flash('Quyền truy cập bị từ chối!', 'danger')
                    return redirect(url_for('index'))
                return f(*args, **kwargs)
            return decorated_function
        return decorator

    @staticmethod
    def verify_license_code(license_key, industry_code):
        """Verifies license code validity in Supabase or SQLite."""
        if not license_key:
            return False, "Vui lòng nhập mã kích hoạt!"

        if SUPABASE_STATUS == "CONNECTED":
            try:
                res = supabase.table('license_codes').select('*').eq('license_key', license_key).eq('trang_thai', 'Sẵn sàng').execute()
                if res.data:
                    lic = res.data[0]
                    if lic['nganh_nghe'].lower() != 'all' and lic['nganh_nghe'].lower() != industry_code.lower():
                        return False, f"Mã kích hoạt chỉ dành cho ngành nghề: {lic['nganh_nghe'].upper()}"
                    return True, lic
            except Exception as e:
                print(f"[!] License validation failed in Supabase: {str(e)}")
        
        return False, "Mã kích hoạt không hợp lệ hoặc đã qua sử dụng."
