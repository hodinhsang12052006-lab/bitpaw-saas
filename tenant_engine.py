from flask import session

# Dùng LẠI đúng 1 MongoClient (connection pool đã cấu hình maxPoolSize/maxIdleTimeMS) từ
# mongo_client.py thay vì tự tạo MongoClient riêng ở đây — trước đây file này mở 1 pool
# connection HOÀN TOÀN TÁCH BIỆT với pool chính của app.py, nhân đôi số connection thật sự
# cần thiết tới Atlas cho mỗi instance serverless, góp phần vào rủi ro cạn kết nối lúc cao điểm.
from mongo_client import db

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
        """{'country': 'US'|'AU'|'VN'|'CA'|'NZ'|'GB'|'', 'currency': 'USD'|'AUD'|'VND'|...} của 1 tiệm.
        country: ai_packs.shop_country — 1 nguồn cho mọi module (nước trên hồ sơ -> múi giờ trang Nhắn tin -> tiền tệ); nước
        BitPaw chưa có luật ('OTHER', 'SG'...) hoặc chưa rõ -> '' (không còn mặc định 'VN': tiệm Mỹ/Úc/Singapore chưa lưu nước
        từng bị coi là tiệm Việt, hiện '₫').
        currency: currency_utils.shop_currency — businesses.currency; chưa lưu ('Theo quốc gia (tự động)') thì theo nước
        (US -> USD, AU -> AUD, VN -> VND, CA -> CAD, NZ -> NZD, GB -> GBP), không rõ nước -> USD. Cùng 1 quy tắc với
        customer_context (lễ tân AI) và app._shop_lang_currency; format_money định dạng đủ 6 tiền này, không bao giờ 'đ'
        cho tiền khác VND.
        Không có tiệm / không có dòng businesses / lỗi DB: {'country': '', 'currency': 'USD'}."""
        default = {"country": "", "currency": "USD"}
        
        if not business_id or db is None:
            return default
            
        try:
            # Chỉ query đúng 2 trường country và currency để tối ưu tốc độ
            row = db.businesses.find_one({'id': business_id}, {'country': 1, 'currency': 1, '_id': 0})
        except Exception as e:
            print(f"[!] get_region_config failed for business_id={business_id}: {str(e)}")
            return default
        if not row:
            return default
        try:
            import ai_packs
            country = ai_packs.shop_country(dict(row, id=business_id)) or ''
        except Exception as e:
            print(f"[!] get_region_config country failed for business_id={business_id}: {str(e)}")
            country = ''
        try:
            from currency_utils import shop_currency
            currency = shop_currency(row.get('currency'), country)
        except Exception as e:
            print(f"[!] get_region_config currency failed for business_id={business_id}: {str(e)}")
            currency = str(row.get('currency') or '').strip().upper() or 'USD'
        return {"country": country, "currency": currency}