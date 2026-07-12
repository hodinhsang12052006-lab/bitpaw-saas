import unittest
import json
import sqlite3
import os
import sys

# Đảm bảo in ra tiếng Việt đúng chuẩn trên Windows Console
sys.stdout.reconfigure(encoding='utf-8')

# ANSI Color codes for beautiful console reporting
GREEN = "\033[92m"
RED = "\033[91m"
CYAN = "\033[96m"
YELLOW = "\033[93m"
RESET = "\033[0m"
BOLD = "\033[1m"

class ColorTextTestResult(unittest.TextTestResult):
    def startTest(self, test):
        super().startTest(test)
        print(f"{CYAN}[CHẠY]{RESET} {test._testMethodName}: {test._testMethodDoc or ''}", end="", flush=True)

    def addSuccess(self, test):
        super().addSuccess(test)
        print(f"\r{GREEN}[PASSED]{RESET} {test._testMethodName} - Thành công! ✓")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        print(f"\r{RED}[FAILED]{RESET} {test._testMethodName} - Thất bại! ✗")
        print(f"  {YELLOW}Chi tiết lỗi:{RESET} {err[1]}")

    def addError(self, test, err):
        super().addError(test, err)
        print(f"\r{RED}[ERROR]{RESET} {test._testMethodName} - Lỗi hệ thống! ✗")
        print(f"  {YELLOW}Chi tiết lỗi:{RESET} {err[1]}")

class ColorTextTestRunner(unittest.TextTestRunner):
    resultclass = ColorTextTestResult

class TestBitPawSystem(unittest.TestCase):
    """Bộ kiểm thử tự động A-Z cho hệ thống BitPaw"""

    @classmethod
    def setUpClass(cls):
        print(f"\n{BOLD}{YELLOW}=== BẮT ĐẦU CHẠY THỬ NGHIỆM TỰ ĐỘNG HỆ THỐNG BITPAW ==={RESET}\n")
        # Thêm thư mục hiện tại vào sys.path để import app.py
        sys.path.append(os.path.dirname(os.path.abspath(__file__)))
        from app import app
        cls.flask_app = app
        cls.client = app.test_client()
        cls.client.testing = True

    def test_routing_frontend_views(self):
        """Kiểm tra các Route giao diện chính (Frontend Views)"""
        routes_to_test = [
            ('/login', [200]),
            ('/register', [200]),
            ('/app_nhanvien', [200]),
            ('/chamcong_spa', [200, 302]),
            ('/cauhinh_luong', [200, 302]),
            ('/setup', [200, 302])
        ]
        
        for route, expected_statuses in routes_to_test:
            response = self.client.get(route)
            self.assertIn(response.status_code, expected_statuses, 
                          f"Route {route} trả về mã trạng thái {response.status_code}, không khớp mong đợi {expected_statuses}")

    def test_qr_api_generation_and_validation(self):
        """Kiểm tra sinh mã QR Code động và xác thực (Auth QR)"""
        # 1. Sinh QR Token
        response = self.client.post('/api/workspace/generate-qr')
        self.assertEqual(response.status_code, 200)
        
        data = json.loads(response.data)
        self.assertEqual(data.get('status'), 'success')
        self.assertIn('qr_token', data)
        self.assertIn('expires_at', data)
        
        qr_token = data['qr_token']
        
        # 2. Kiểm tra token hợp lệ
        val_response = self.client.post(
            '/api/workspace/validate-qr',
            data=json.dumps({'qr_token': qr_token}),
            content_type='application/json'
        )
        self.assertEqual(val_response.status_code, 200)
        val_data = json.loads(val_response.data)
        self.assertEqual(val_data.get('status'), 'success')
        self.assertEqual(val_data.get('message'), 'Hợp lệ')

        # 3. Kiểm tra token sai
        fake_response = self.client.post(
            '/api/workspace/validate-qr',
            data=json.dumps({'qr_token': 'sai_token_999'}),
            content_type='application/json'
        )
        self.assertEqual(fake_response.status_code, 404)
        fake_data = json.loads(fake_response.data)
        self.assertEqual(fake_data.get('status'), 'error')

    def test_database_health_checks(self):
        """Kiểm tra sức khỏe kết nối SQLite Databases (Health Check)"""
        db_files = ['database.db', 'sales.db']
        for db in db_files:
            self.assertTrue(os.path.exists(db), f"Database file {db} không tồn tại!")
            try:
                conn = sqlite3.connect(db)
                c = conn.cursor()
                c.execute("SELECT name FROM sqlite_master WHERE type='table';")
                tables = c.fetchall()
                conn.close()
                self.assertIsNotNone(tables, f"Không thể lấy danh sách bảng từ {db}")
            except Exception as e:
                self.fail(f"Lỗi truy vấn Database {db}: {str(e)}")

    @classmethod
    def tearDownClass(cls):
        print(f"\n{BOLD}{YELLOW}=== HOÀN THÀNH CHƯƠNG TRÌNH THỬ NGHIỆM BITPAW ==={RESET}\n")

if __name__ == '__main__':
    # Chạy kiểm thử sử dụng custom runner để in màu sắc
    suite = unittest.TestLoader().loadTestsFromTestCase(TestBitPawSystem)
    runner = ColorTextTestRunner()
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
