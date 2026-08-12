from functools import wraps
from flask import session, redirect, url_for, flash
from mongo_client import db, MONGO_STATUS

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
    def verify_license_code(license_key, industry_code):
        """Verifies license code validity in MongoDB (license_codes collection)."""
        if not license_key:
            return False, "Vui lòng nhập mã kích hoạt!"

        if MONGO_STATUS == "CONNECTED":
            try:
                lic = db.license_codes.find_one(
                    {'license_key': license_key, 'trang_thai': 'Sẵn sàng'}, {'_id': 0}
                )
                if lic:
                    if lic['nganh_nghe'].lower() != 'all' and lic['nganh_nghe'].lower() != industry_code.lower():
                        return False, f"Mã kích hoạt chỉ dành cho ngành nghề: {lic['nganh_nghe'].upper()}"
                    return True, lic
            except Exception as e:
                print(f"[!] License validation failed in MongoDB: {str(e)}")

        return False, "Mã kích hoạt không hợp lệ hoặc đã qua sử dụng."
