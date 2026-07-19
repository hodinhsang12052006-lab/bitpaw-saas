import os
from flask import session
from pymongo import MongoClient

# 1. Khởi tạo kết nối MongoDB từ biến môi trường (Chuẩn Vercel)
MONGO_URI = os.environ.get('MONGO_URI')
db = None

if MONGO_URI:
    try:
        # Cài đặt timeout ngắn để phù hợp với môi trường Serverless
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        # Tự động lấy database mặc định từ chuỗi kết nối
        db = client.get_default_database(default='bitpaw_db') 
    except Exception as e:
        print(f"[!] MongoDB Connection failed: {e}")

class TenantEngine:
    @staticmethod
    def resolve_tenant(user_id):
        """Resolves tenant business_id and details based on user_id."""
        if not user_id:
            return None
        
        # Test bypass
        if user_id == "mock-user-123":
            return {
                "business_id": "mock-business-123",
                "business_name": "BitPaw Demo Store",
                "industry_code": session.get('business_mode', 'retail')
            }

        # 2. Xử lý query bằng MongoDB thay cho Supabase
        if db is not None:
            try:
                # Tìm profile dựa trên user_id
                # Lưu ý: Giả định key trong collection là 'id' để khớp với code cũ
                prof = db.profiles.find_one({'id': user_id})
                if prof:
                    b_id = prof.get('business_id')
                    role = prof.get('role')
                    
                    # Tìm thông tin business
                    bus = db.businesses.find_one({'id': b_id})
                    if bus:
                        return {
                            "business_id": b_id,
                            "business_name": bus.get('name'),
                            "industry_code": bus.get('industry_code'),
                            "role": role
                        }
            except Exception as e:
                print(f"[!] Tenant resolving failed: {str(e)}")

        return None

    @staticmethod
    def get_region_config(business_id=None):
        """Returns {'country': 'VN'|'US', 'currency': 'VND'|'USD'} for a tenant."""
        default = {"country": "VN", "currency": "VND"}
        
        if not business_id or db is None:
            return default
            
        try:
            # Chỉ query đúng 2 trường country và currency để tối ưu tốc độ
            row = db.businesses.find_one({'id': business_id}, {'country': 1, 'currency': 1, '_id': 0})
            if row:
                return {
                    "country": row.get('country') or 'VN',
                    "currency": row.get('currency') or 'VND'
                }
        except Exception as e:
            print(f"[!] get_region_config failed for business_id={business_id}: {str(e)}")
            
        return default