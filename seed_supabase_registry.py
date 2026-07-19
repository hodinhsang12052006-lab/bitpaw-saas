import sys
import os

# Bind workspace path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from mongo_client import db, MONGO_STATUS
from app import INDUSTRY_CONFIG

# --- STATIC REGISTRY DATA CONFIGURATIONS ---
DEFAULT_PERMISSIONS = [
    {"code": "view_dashboard", "name": "Xem Tổng Quan", "description": "Quyền xem báo cáo doanh thu, chi phí và lợi nhuận trên Dashboard"},
    {"code": "manage_inventory", "name": "Quản Lý Kho", "description": "Quyền thêm, sửa, xóa và kiểm kho sản phẩm hàng hóa"},
    {"code": "sell", "name": "Bán Hàng", "description": "Quyền thao tác màn hình bán hàng bán lẻ"},
    {"code": "view_pos", "name": "Xem POS Bán Hàng", "description": "Quyền mở màn hình POS gọi món và treo hóa đơn F&B"},
    {"code": "manage_tables", "name": "Quản Lý Sơ Đồ Bàn", "description": "Quyền thêm bàn ăn, đổi trạng thái bàn phục vụ"},
    {"code": "clock_in", "name": "Chấm Công Nhân Sự", "description": "Quyền check-in/check-out chấm công ca làm việc"},
    {"code": "view_spa", "name": "Xem Trạm Spa", "description": "Quyền thao tác bán liệu trình và điều phối KTV Spa"},
    {"code": "manage_bookings", "name": "Quản Lý Đặt Lịch", "description": "Quyền xem lịch hẹn, xác nhận đặt chỗ dịch vụ làm đẹp"},
    {"code": "view_nail", "name": "Xem Trạm Nails", "description": "Quyền quản lý dịch vụ làm móng Nails & Salon"},
    {"code": "view_karaoke", "name": "Xem Trạm Karaoke", "description": "Quyền quản lý danh sách phòng, bida và tính giờ giải trí"},
    {"code": "manage_rooms", "name": "Quản Lý Phòng Hát", "description": "Quyền bắt đầu giờ hát, tính tiền giờ tự động"},
    {"code": "view_hotel", "name": "Xem Trạm Khách Sạn", "description": "Quyền xem sơ đồ buồng phòng khách sạn, nhà nghỉ"},
    {"code": "view_production", "name": "Xem Trạm Sản Xuất", "description": "Quyền chấm công và ghi nhận năng suất ca xưởng sản xuất"},
    {"code": "view_technical", "name": "Xem Trạm Kỹ Thuật", "description": "Quyền chấm công KTV thực địa ngoài hiện trường qua GPS"},
    {"code": "view_office", "name": "Xem Trạm Văn Phòng", "description": "Quyền chấm công hành chính và tính lương văn phòng"}
]

DEFAULT_MODULES = [
    {"code": "dashboard", "name": "Tổng Quan & Báo Cáo", "description": "Xem phân tích doanh số bán hàng, chi phí, dòng tiền thu chi", "is_active": True},
    {"code": "sales", "name": "Bán Hàng Bán Lẻ", "description": "Giao diện thanh toán nhanh cho các shop bán lẻ", "is_active": True},
    {"code": "inventory", "name": "Quản Lý Kho Hàng", "description": "Kiểm kê hàng hóa tồn kho, cảnh báo vật tư cận date", "is_active": True},
    {"code": "expenses", "name": "Quản Lý Chi Tiêu", "description": "Sổ quỹ ghi nhận chi phí vận hành, nhập hàng", "is_active": True},
    {"code": "ordering", "name": "Smart POS & Gọi Món", "description": "Màn hình bán hàng dịch vụ ăn uống F&B, gọi món", "is_active": True},
    {"code": "tables", "name": "Sơ Đồ Bàn Ăn", "description": "Quản lý tình trạng bàn trống, bàn đang ăn, ghép bill", "is_active": True},
    {"code": "attendance", "name": "Chấm Công Nhân Sự", "description": "Hệ thống ghi nhận ca làm việc của thợ và nhân viên hành chính", "is_active": True},
    {"code": "payroll", "name": "Tính Lương & Payout", "description": "Bảng tính lương tự động dựa trên chuyên cần và hoa hồng", "is_active": True},
    {"code": "spa_services", "name": "Liệu Trình Spa", "description": "Quản lý danh sách dịch vụ spa chăm sóc da mặt, body", "is_active": True},
    {"code": "online_booking", "name": "Đặt Lịch Trực Tuyến", "description": "Cổng tiếp nhận khách đặt chỗ làm đẹp tự động qua QR", "is_active": True},
    {"code": "nail_services", "name": "Dịch Vụ Nails", "description": "Nails & Salon dịch vụ làm móng và chăm sóc tay chân", "is_active": True},
    {"code": "room_timing", "name": "Bán Giờ Karaoke", "description": "Tính giờ phòng hát bida tự động chính xác theo phút", "is_active": True},
    {"code": "pos_ordering", "name": "Gọi Đồ Karaoke", "description": "Order đồ uống hoa quả chèn trực tiếp vào bill phòng giải trí", "is_active": True},
    {"code": "room_management", "name": "Quản Lý Buồng Phòng", "description": "Sơ đồ buồng phòng, khách check-in và check-out homestay", "is_active": True},
    {"code": "factory_output", "name": "Năng Suất Tổ Đội", "description": "Báo cáo sản lượng hoàn thành ca kíp tại xưởng sản xuất", "is_active": True},
    {"code": "dispatch_gps", "name": "GPS Định Vị Thợ", "description": "Radar GPS giám sát nhân sự thực địa, kỹ thuật hiện trường", "is_active": True},
    {"code": "ai_bot", "name": "AI Copilot Assistant", "description": "Trợ lý ảo AI trực chat và tư vấn tăng trưởng doanh số", "is_active": True},
    {"code": "ai_studio", "name": "AI Content Studio", "description": "Phòng chế tác content video viral bùng nổ view marketing", "is_active": True},
    {"code": "cskh", "name": "Kết Nối CSKH", "description": "Kênh liên lạc hỗ trợ kỹ thuật trực tiếp 24/7", "is_active": True},
    {"code": "backup", "name": "Sao Lưu & Phục Hồi", "description": "Hệ thống backup dữ liệu an toàn lên MongoDB GridFS", "is_active": True}
]

TEMPLATE_METADATA_MAP = {
    "dashboard.html": {
        "display_name": "Bảng Điều Khiển Tổng Quan",
        "description": "Trung tâm phân tích doanh thu bán lẻ, chi phí vận hành và lợi nhuận dòng tiền.",
        "module_code": "dashboard",
        "route_name": "index",
        "url_path": "/dashboard",
        "required_permission": "view_dashboard",
        "sort_order": 1
    },
    "pos.html": {
        "display_name": "Smart POS Bán Hàng",
        "description": "Giao diện gọi món treo hóa đơn và sơ đồ bàn ăn thông minh cho F&B.",
        "module_code": "ordering",
        "route_name": "pos",
        "url_path": "/pos",
        "required_permission": "view_pos",
        "sort_order": 2
    },
    "qr_menu.html": {
        "display_name": "Cổng Đặt Món QR Menu",
        "description": "Cổng tự phục vụ dành cho khách quét QR gọi món tại bàn ăn không cần thu ngân.",
        "module_code": "ordering",
        "route_name": "qr_menu",
        "url_path": "/qr_menu/<path:identifier>",
        "required_permission": "view_pos",
        "sort_order": 3
    },
    "booking.html": {
        "display_name": "Cổng Đặt Lịch Hẹn Spa",
        "description": "Cổng tự phục vụ dành cho khách hàng đăng ký giờ làm liệu trình thẩm mỹ đặt chỗ KTV.",
        "module_code": "online_booking",
        "route_name": "public_booking",
        "url_path": "/booking",
        "required_permission": "manage_bookings",
        "sort_order": 4
    },
    "spa.html": {
        "display_name": "Trạm Quản Lý Spa",
        "description": "Bảng điều phối kỹ thuật viên làm liệu trình, chia hoa hồng thợ và doanh thu dịch vụ.",
        "module_code": "spa_services",
        "route_name": "spa",
        "url_path": "/spa",
        "required_permission": "view_spa",
        "sort_order": 5
    },
    "karaoke.html": {
        "display_name": "Trạm Tính Giờ Karaoke",
        "description": "Bảng điều khiển tính giờ phòng bida/karaoke tự động theo phút kèm gọi đồ giải khát.",
        "module_code": "room_timing",
        "route_name": "karaoke",
        "url_path": "/karaoke",
        "required_permission": "view_karaoke",
        "sort_order": 6
    },
    "chamcong_fnb.html": {
        "display_name": "Chấm Công - Nhà Hàng",
        "description": "Màn hình check-in chấm ca làm việc dành cho nhân viên phục vụ, bar và bếp.",
        "module_code": "attendance",
        "route_name": "chamcong_industry",
        "url_path": "/chamcong/fnb",
        "required_permission": "clock_in",
        "sort_order": 10
    },
    "chamcong_spa.html": {
        "display_name": "Chấm Công - Spa",
        "description": "Giao diện check-in ca làm việc của kỹ thuật viên massage, skincare trị liệu.",
        "module_code": "attendance",
        "route_name": "chamcong_industry",
        "url_path": "/chamcong/spa",
        "required_permission": "clock_in",
        "sort_order": 11
    },
    "chamcong_nail.html": {
        "display_name": "Chấm Công - Salon Nails",
        "description": "Bảng check-in điểm danh ca làm việc dành cho thợ nail nghệ thuật, thợ phụ.",
        "module_code": "attendance",
        "route_name": "chamcong_industry",
        "url_path": "/chamcong/nail",
        "required_permission": "clock_in",
        "sort_order": 12
    },
    "chamcong_khachsan.html": {
        "display_name": "Chấm Công - Khách Sạn",
        "description": "Giao diện điểm danh ca trực dành cho lễ tân, buồng phòng và bảo vệ khách sạn.",
        "module_code": "attendance",
        "route_name": "chamcong_industry",
        "url_path": "/chamcong/khachsan",
        "required_permission": "clock_in",
        "sort_order": 13
    },
    "chamcong_congnhan.html": {
        "display_name": "Chấm Công - Tổ Xưởng",
        "description": "Giao diện chấm sản lượng check-in dành cho công nhân, tổ trưởng xưởng sản xuất.",
        "module_code": "attendance",
        "route_name": "chamcong_industry",
        "url_path": "/chamcong/congnhan",
        "required_permission": "clock_in",
        "sort_order": 14
    },
    "chamcong_kythuat.html": {
        "display_name": "Chấm Công - Kỹ Thuật",
        "description": "Hệ thống check-in check-out định vị GPS hiện trường dành cho KTV lắp đặt, bảo trì.",
        "module_code": "attendance",
        "route_name": "chamcong_industry",
        "url_path": "/chamcong/kythuat",
        "required_permission": "clock_in",
        "sort_order": 15
    },
    "chamcong_vanphong.html": {
        "display_name": "Chấm Công - Văn Phòng",
        "description": "Bảng điểm danh check-in hành chính dành cho khối văn phòng doanh nghiệp.",
        "module_code": "attendance",
        "route_name": "chamcong_industry",
        "url_path": "/chamcong/vanphong",
        "required_permission": "clock_in",
        "sort_order": 16
    },
    "bangluong.html": {
        "display_name": "Quản Lý Bảng Lương",
        "description": "Bảng kết toán lương tổng hợp chi tiết dựa trên chấm công chuyên cần và hoa hồng.",
        "module_code": "payroll",
        "route_name": "bangluong",
        "url_path": "/bangluong",
        "required_permission": "view_office",
        "sort_order": 20
    },
    "nhanvien.html": {
        "display_name": "Danh Sách Nhân Sự",
        "description": "Hồ sơ lưu trữ thông tin liên hệ, ca kíp và tỷ lệ chia thưởng thợ.",
        "module_code": "payroll",
        "route_name": "nhanvien",
        "url_path": "/nhanvien",
        "required_permission": "view_office",
        "sort_order": 21
    },
    "ai_bot.html": {
        "display_name": "AI Copilot Assistant",
        "description": "Trung tâm trợ lý ảo AI trực chat và tự động phản hồi đề xuất kịch bản tăng trưởng.",
        "module_code": "ai_bot",
        "route_name": "ai_bot",
        "url_path": "/ai_bot",
        "required_permission": "view_dashboard",
        "sort_order": 30
    },
    "ai-studio.html": {
        "display_name": "AI Content Studio",
        "description": "Xưởng chế tác kịch bản video viral đa kênh TikTok/Facebook A/B Hook và Brief KOC.",
        "module_code": "ai_studio",
        "route_name": "ai_studio",
        "url_path": "/ai-studio",
        "required_permission": "view_dashboard",
        "sort_order": 31
    }
}

# --- SYSTEM SEED EXECUTION LOGIC ---
def seed_registry():
    print("=" * 60)
    print("STARTING DYNAMIC SAAS REGISTRY SEED")
    print(f"   -> Connection Status: {MONGO_STATUS}")
    print("=" * 60)

    if MONGO_STATUS != "CONNECTED":
        print("[!] Warning: MongoDB is offline or unconfigured. Skipping seed execution.")
        return

    try:
        # 1. Seed Permissions
        print("[*] Seeding System Permissions...")
        for p in DEFAULT_PERMISSIONS:
            try:
                db.permissions.update_one({'code': p['code']}, {'$set': p}, upsert=True)
            except Exception as e:
                print(f"    - Failed seeding permission '{p['code']}': {str(e)}")
        print("    -> Permissions seeded cleanly.")

        # 2. Seed Modules
        print("\n[*] Seeding Business Modules...")
        for m in DEFAULT_MODULES:
            try:
                db.business_modules.update_one({'code': m['code']}, {'$set': m}, upsert=True)
            except Exception as e:
                print(f"    - Failed seeding module '{m['code']}': {str(e)}")
        print("    -> Modules seeded cleanly.")

        # 3. Seed Industries from INDUSTRY_CONFIG
        print("\n[*] Seeding Merchant Industries (Dynamic)...")
        for code, cfg in INDUSTRY_CONFIG.items():
            ind = {
                "code": code,
                "name": cfg.get("name", "Ngành nghề"),
                "icon": cfg.get("icon", "💼"),
                "description": cfg.get("desc", ""),
                "redirect_after_login": cfg.get("redirect_after_login", "/dashboard")
            }
            try:
                db.industries.update_one({'code': code}, {'$set': ind}, upsert=True)
                print(f"    - Seeded Industry '{code}': {ind['name']}")

                # Seed Navigation items for this industry dynamically
                sort_ord = 1
                for mod_code in cfg.get("modules", []):
                    # Fetch matching module name
                    matched_mod = next((m for m in DEFAULT_MODULES if m['code'] == mod_code), None)
                    mod_name = matched_mod['name'] if matched_mod else "Tính năng"

                    nav = {
                        "module_code": mod_code,
                        "industry_code": code,
                        "label": mod_name,
                        "icon": cfg.get("icon", "⭐"),
                        "url_path": cfg.get("redirect_after_login", "/dashboard"),
                        "sort_order": sort_ord
                    }
                    try:
                        db.navigation_items.insert_one(nav)
                    except:
                        pass  # Ignore if duplicate entries exist in this log run
                    sort_ord += 1
            except Exception as e:
                print(f"    - Failed seeding industry '{code}': {str(e)}")

        # 4. Seed Templates Registry
        print("\n[*] Seeding Templates & Views Registry...")

        # Cleanup potential garbage/backup records in Templates Registry
        print("[*] Cleaning up potential backup/garbage records in Templates Registry...")
        for garbage_name in ['landing_nail.current_ai_bad_backup.html', 'transcript.jsonl']:
            try:
                db.templates_registry.delete_many({'template_name': garbage_name})
                print(f"    - Cleaned up registry record for '{garbage_name}' if existed.")
            except Exception as clean_err:
                print(f"    - Skip cleaning for '{garbage_name}': {str(clean_err)}")

        templates_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
        if os.path.exists(templates_dir):
            for file in os.listdir(templates_dir):
                # Only accept clean .html files and exclude any backup or bad backup logs
                if file.endswith('.html') and not any(x in file for x in ['.backup', '.bad_backup', '.current_ai_bad_backup', 'transcript.jsonl']):
                    meta = TEMPLATE_METADATA_MAP.get(file, {
                        "display_name": file.replace('.html', '').capitalize(),
                        "description": "File giao diện hệ thống",
                        "module_code": "dashboard",
                        "route_name": "index",
                        "url_path": "/dashboard",
                        "required_permission": "view_dashboard",
                        "sort_order": 99
                    })

                    reg = {
                        "template_name": file,
                        "file_path": f"templates/{file}",
                        "route_name": meta.get("route_name"),
                        "url_path": meta.get("url_path"),
                        "module_code": meta.get("module_code"),
                        "display_name": meta.get("display_name"),
                        "description": meta.get("description"),
                        "required_permission": meta.get("required_permission"),
                        "is_active": True,
                        "sort_order": meta.get("sort_order", 99)
                    }
                    try:
                        db.templates_registry.update_one({'template_name': file}, {'$set': reg}, upsert=True)
                        print(f"    - Mapped View '{file}': {reg['display_name']}")
                    except Exception as e:
                        print(f"    - Failed seeding template '{file}': {str(e)}")

        print("\n" + "=" * 60)
        print("DYNAMIC SAAS REGISTRY SEED COMPLETED SUCCESSFULLY!")
        print("=" * 60)

    except Exception as e:
        print(f"[!] Critical error during seed operation loop: {str(e)}")

if __name__ == '__main__':
    seed_registry()
