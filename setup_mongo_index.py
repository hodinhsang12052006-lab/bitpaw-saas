"""
setup_mongo_index.py — tạo index cho MongoDB Atlas. Chạy 1 lần (idempotent — chạy lại nhiều
lần không sao, create_index() không tạo trùng nếu index đã tồn tại với cùng spec).

    python setup_mongo_index.py

Vì sao cần: audit "Tổng duyệt Production Readiness" phát hiện TOÀN BỘ codebase không có bất
kỳ index nào ngoài `_id` mặc định — mọi query lọc theo business_id/phone/created_at đều
full collection scan. Ở quy mô nhỏ không thấy chậm, nhưng sẽ chậm dần rõ rệt khi dữ liệu và số
tenant tăng lên.

Index được chọn dựa theo ĐÚNG shape của các query thật đang chạy trong app.py (không phải suy
đoán chung chung) — mỗi dòng bên dưới có comment trỏ tới truy vấn cụ thể đang dùng field đó.
"""
import sys

from mongo_client import db, MONGO_STATUS

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')


# Mỗi phần tử: (tên collection, danh sách field index [1: tăng dần], kwargs cho create_index)
INDEX_PLAN = [
    # --- users: login tra theo email (app.py: db.users.find_one({'email': email})) ---
    ('users', [('email', 1)], {'unique': True, 'name': 'idx_email_unique'}),

    # --- orders: tra theo tenant+id (huỷ/refund), báo cáo theo khoảng ngày, webhook Square ---
    ('orders', [('business_id', 1), ('id', 1)], {'name': 'idx_business_id_id'}),
    ('orders', [('business_id', 1), ('created_at', -1)], {'name': 'idx_business_id_created_at'}),
    ('orders', [('square_checkout_id', 1)], {'sparse': True, 'name': 'idx_square_checkout_id'}),

    # --- order_items: forecast tồn kho theo product_id+created_at, tra theo order_id ---
    ('order_items', [('order_id', 1)], {'name': 'idx_order_id'}),
    ('order_items', [('product_id', 1), ('created_at', -1)], {'name': 'idx_product_id_created_at'}),

    # --- customers: tra theo SĐT lúc checkout (chỗ nóng nhất), danh sách theo tenant ---
    ('customers', [('business_id', 1), ('phone', 1)], {'name': 'idx_business_id_phone'}),
    ('customers', [('business_id', 1), ('id', 1)], {'name': 'idx_business_id_id'}),

    # --- staff / employees: tra theo tenant+id ở hầu hết mọi route chấm công/POS ---
    ('staff', [('business_id', 1), ('id', 1)], {'name': 'idx_business_id_id'}),
    ('employees', [('business_id', 1), ('id', 1)], {'name': 'idx_business_id_id'}),

    # --- attendance: tìm ca đang mở (staff_id + clock_out=None), sort theo created_at ---
    ('attendance', [('business_id', 1), ('staff_id', 1), ('clock_out', 1)], {'name': 'idx_business_staff_clockout'}),
    ('attendance', [('created_at', -1)], {'name': 'idx_created_at'}),

    # --- products: tra theo tenant, lọc is_active (forecast tồn kho, danh mục bán hàng) ---
    ('products', [('business_id', 1), ('id', 1)], {'name': 'idx_business_id_id'}),
    ('products', [('business_id', 1), ('is_active', 1)], {'name': 'idx_business_id_is_active'}),

    # --- payment_transactions: lịch sử giao dịch theo tenant, sort mới nhất trước ---
    ('payment_transactions', [('business_id', 1), ('created_at', -1)], {'name': 'idx_business_id_created_at'}),

    # --- bot_customers / bot_messages: inbox AI Copilot ---
    ('bot_customers', [('business_id', 1), ('id', 1)], {'name': 'idx_business_id_id'}),
    ('bot_messages', [('customer_id', 1), ('created_at', 1)], {'name': 'idx_customer_id_created_at'}),

    # --- appointments: dùng chung bởi blueprints/spa_bp.py (đặt lịch công khai) VÀ
    # ai_function_tools.py::book_appointment (AI Bot). Route /calendar (app.py) lọc theo
    # business_id + khoảng book_time trong ngày — đây là index thực sự phục vụ query đó. ---
    ('appointments', [('business_id', 1), ('book_time', 1)], {'name': 'idx_business_id_book_time'}),
    ('appointments', [('business_id', 1), ('created_at', -1)], {'name': 'idx_business_id_created_at'}),

    # --- dining_tables: tra bàn theo tenant (POS F&B) ---
    ('dining_tables', [('business_id', 1), ('id', 1)], {'name': 'idx_business_id_id'}),

    # --- system_settings: cấu hình theo tenant (payment_config, business_mode_<id>...) ---
    ('system_settings', [('business_id', 1), ('key', 1)], {'name': 'idx_business_id_key'}),
]


def main():
    if db is None:
        print(f"[setup_mongo_index] Không có kết nối MongoDB (MONGO_STATUS={MONGO_STATUS}). "
              "Kiểm tra lại MONGO_URI trong .env rồi chạy lại.", file=sys.stderr)
        sys.exit(1)

    print(f"[setup_mongo_index] Kết nối OK (MONGO_STATUS={MONGO_STATUS}). Bắt đầu tạo {len(INDEX_PLAN)} index...\n")

    ok, failed = 0, 0
    for collection_name, keys, kwargs in INDEX_PLAN:
        try:
            index_name = db[collection_name].create_index(keys, **kwargs)
            print(f"  [OK] {collection_name}.{index_name}  keys={keys}")
            ok += 1
        except Exception as e:
            # Lỗi thường gặp nhất: unique index (users.email) thất bại vì đã có email trùng
            # trong dữ liệu thật — KHÔNG dừng cả script, in rõ để tự dọn dữ liệu trùng rồi
            # chạy lại riêng dòng đó.
            print(f"  [LỖI] {collection_name} keys={keys}: {e}", file=sys.stderr)
            failed += 1

    print(f"\n[setup_mongo_index] Xong: {ok} index OK, {failed} lỗi.")
    if failed:
        sys.exit(1)


if __name__ == '__main__':
    main()
