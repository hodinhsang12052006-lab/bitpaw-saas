"""
Offline-Sync cho Desktop POS (Mã 4.1 audit) — CHỈ chạy trong bản Desktop (.exe), KHÔNG động tới
đường Web/Vercel (nơi này luôn có mạng ổn định tới Atlas, buffer cục bộ vô nghĩa vì mỗi lần gọi
hàm serverless là 1 instance khác nhau, không có "ổ cứng cục bộ" nào tồn tại giữa các lần gọi).

Luồng hoạt động:
    1. api_nail_pos_checkout() trong app.py thử ghi thẳng lên MongoDB Atlas như bình thường.
    2. Nếu bắt được lỗi mất kết nối (ConnectionFailure/ServerSelectionTimeoutError/...), route
       gọi queue_offline_order() ở đây để lưu TẠM đơn hàng vào local_db.py (MontyDB, ghi ra
       SQLite ngay trên ổ cứng máy khách) kèm 1 client_uuid sinh ngay tại máy — KHÔNG cần gọi
       Mongo nên hoạt động được dù mất mạng 100%. Cashier vẫn thấy "thanh toán thành công".
    3. start_background_sync() chạy 1 thread nền (do desktop_app/launcher.py khởi động cùng
       lúc mở Flask), định kỳ thử đẩy các đơn _pending_sync lên Atlas thật. Ghi bằng
       update_one(..., upsert=True) theo khoá client_uuid -> nếu 1 đơn đã lỡ đồng bộ xong ở
       lượt trước nhưng process crash trước khi xoá cache local, lượt sau gọi lại KHÔNG bị tạo
       đơn trùng / KHÔNG bị trả hoa hồng cho thợ 2 lần (Idempotency).
    4. Đồng bộ xong -> đơn có ID thật (do next_mongo_id() cấp lúc online), xoá bản ghi tạm khỏi
       local_db.py.
"""
import threading
import time
import uuid
from datetime import datetime

from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError, NetworkTimeout, AutoReconnect

SYNC_INTERVAL_SECONDS = 20
_MONGO_CONNECTION_ERRORS = (ConnectionFailure, ServerSelectionTimeoutError, NetworkTimeout, AutoReconnect)
# Mã "Go-Live Pentest" audit — 1 đơn hàng lỗi DỮ LIỆU (không phải mất mạng, vd sai format do
# bug tương lai) trước đây bị retry lại MỖI 20s VÔ THỜI HẠN, không bao giờ dừng, không có cách
# nào biết "đơn này cần người xem tay" ngoài đọc log console. Giới hạn số lần thử — quá số này,
# ngưng retry (đỡ log spam) và giữ nguyên bản ghi để cashier/admin tự kiểm tra thủ công.
MAX_SYNC_ATTEMPTS = 20


def queue_offline_order(business_id, computed, customer_phone):
    """Lưu 1 đơn hàng chưa kịp ghi lên Atlas vào local_db.py. `computed` là dict trả về từ
    _compute_nail_pos_order() trong app.py (đủ dữ liệu để dựng lại order/order_items/chamcong
    y hệt lúc online, KHÔNG cần next_mongo_id() — id thật chỉ cấp lúc đồng bộ thành công).

    Import local_db LAZY (trong hàm, không phải đầu file): local_db.py khởi tạo MontyClient +
    tạo thư mục %APPDATA%\\BitPawOS\\local_db ngay lúc import module -> chỉ nên trả giá đó khi
    THỰC SỰ cần (đang chạy Desktop và vừa rớt mạng), không phải mỗi lần app.py load module.
    """
    from local_db import db as local_db_conn

    client_uuid = str(uuid.uuid4())
    local_db_conn.pending_sync_orders.insert_one({
        'client_uuid': client_uuid,
        '_pending_sync': True,
        'business_id': business_id,
        'customer_phone': customer_phone or None,
        'computed': computed,
        'queued_at': datetime.now().isoformat(),
        'sync_attempts': 0,
        'last_error': None,
    })
    print(f"[sync_worker] Mất mạng — đã lưu tạm đơn hàng client_uuid={client_uuid} vào local_db.")
    return client_uuid


def _sync_one_pending(local_db_conn, pending_doc):
    """Đẩy ĐÚNG 1 đơn hàng đang chờ lên Atlas thật. Import từ app.py LAZY (bên trong hàm) để
    tránh vòng lặp import (app.py import sync_worker ở đầu file; nếu sync_worker import app ở
    đầu file luôn thì lúc app.py đang load dở sẽ đụng độ). Lúc thread nền này thực sự chạy,
    app.py chắc chắn đã load xong hoàn toàn (launcher.py chỉ start thread SAU khi tạo xong Flask
    app), nên import lazy ở đây an toàn tuyệt đối."""
    from app import _build_nail_chamcong_docs, _finalize_paid_order
    from mongo_client import db as cloud_db, client as cloud_client, next_mongo_id as cloud_next_id

    client_uuid = pending_doc['client_uuid']

    # Đã có đơn với client_uuid này trên Atlas rồi (ví dụ: worker lượt trước ghi xong Mongo
    # nhưng crash trước khi xoá cache local) -> chỉ cần dọn cache, KHÔNG ghi lại lần 2.
    existing = cloud_db.orders.find_one({'metadata.client_uuid': client_uuid}, {'_id': 0, 'id': 1})
    if existing:
        local_db_conn.pending_sync_orders.delete_one({'client_uuid': client_uuid})
        print(f"[sync_worker] client_uuid={client_uuid} đã tồn tại trên Atlas (id={existing['id']}) — chỉ dọn cache.")
        return True

    computed = pending_doc['computed']
    business_id = pending_doc['business_id']
    customer_phone = pending_doc.get('customer_phone')

    order_id = cloud_next_id('orders')  # ID THẬT — chỉ cấp lúc chắc chắn đang online
    now_iso = datetime.now().isoformat()
    # Schema chuẩn hoá (Giai đoạn 3 audit) — CHỈ 6 trường lõi ở top-level, mọi trường đặc thù
    # (kể cả client_uuid — khoá idempotency riêng của luồng offline-sync này) gộp vào 'metadata',
    # PHẢI khớp đúng shape mà api_nail_pos_checkout() ghi khi online, nếu không 1 đơn Nails được
    # đồng bộ offline sẽ có hình dạng khác đơn ghi trực tiếp, làm lệch mọi báo cáo đọc metadata.
    metadata = {
        'client_uuid': client_uuid, 'channel': 'nail_pos',
        'subtotal': computed['subtotal'], 'supply_amount': computed['supply_amount'],
        'discount_amount': computed['discount_amount'], 'tax_amount': computed['tax_amount'],
        'tip_amount': computed['total_tip'], 'payment_bucket': computed['payment_bucket'],
        'currency': computed['currency'], 'commission_rate': computed.get('commission_rate'),
    }
    if computed['payment_bucket'] == 'split':
        metadata['split_cash_amount'] = computed['split_cash_amount']
        metadata['split_card_amount'] = computed['split_card_amount']
    if customer_phone:
        metadata['customer_phone'] = customer_phone
    order_doc = {
        'id': order_id,
        'business_id': business_id,
        'created_at': now_iso,
        'status': 'completed',
        'total_amount': computed['total_amount'],
        'payment_method': computed['payment_method'],
        'metadata': metadata,
    }

    order_items_docs = []
    for oi in computed['order_items_docs']:
        oi = dict(oi)
        oi['id'] = cloud_next_id('order_items')
        oi['order_id'] = order_id
        oi['business_id'] = business_id
        if customer_phone:
            oi['customer_phone'] = customer_phone
        order_items_docs.append(oi)

    chamcong_docs, _techs_paid = _build_nail_chamcong_docs(order_id, business_id, computed, note_prefix='[NAILS POS - Offline Sync]')

    # upsert theo client_uuid (KHÔNG phải insert_one thẳng): nếu 2 lượt sync chạy chồng nhau
    # (không nên xảy ra vì chỉ 1 thread, nhưng phòng thủ thêm 1 lớp) thì lượt thứ 2 sẽ là no-op
    # thay vì tạo đơn/trả hoa hồng trùng lần thứ 2.
    with cloud_client.start_session() as db_session:
        with db_session.start_transaction():
            cloud_db.orders.update_one(
                {'metadata.client_uuid': client_uuid}, {'$setOnInsert': order_doc}, upsert=True, session=db_session,
            )
            if order_items_docs:
                cloud_db.order_items.insert_many(order_items_docs, session=db_session)
            if chamcong_docs:
                cloud_db.chamcong.insert_many(chamcong_docs, session=db_session)

    if customer_phone:
        try:
            _finalize_paid_order(order_doc)
        except Exception as e:
            print(f"[sync_worker] Lỗi _finalize_paid_order (không ảnh hưởng việc đơn đã đồng bộ) client_uuid={client_uuid}: {e}")

    local_db_conn.pending_sync_orders.delete_one({'client_uuid': client_uuid})
    print(f"[sync_worker] Đồng bộ thành công client_uuid={client_uuid} -> order_id thật={order_id}")
    return True


def sync_pending_orders_once():
    """Chạy đúng 1 lượt quét — quét toàn bộ đơn `_pending_sync=True` trong local_db.py và cố
    đẩy từng đơn lên Atlas. 1 đơn lỗi không được phép chặn các đơn còn lại trong cùng lượt quét."""
    from local_db import db as local_db_conn

    pending_list = list(local_db_conn.pending_sync_orders.find({'_pending_sync': True}))
    if not pending_list:
        return 0

    synced = 0
    for pending_doc in pending_list:
        client_uuid = pending_doc.get('client_uuid', '?')
        try:
            if _sync_one_pending(local_db_conn, pending_doc):
                synced += 1
        except _MONGO_CONNECTION_ERRORS as e:
            # Vẫn chưa có mạng — dừng cả lượt quét này luôn (các đơn còn lại chắc chắn cũng sẽ
            # lỗi y hệt), để lần quét SAU (SYNC_INTERVAL_SECONDS sau) thử lại toàn bộ.
            print(f"[sync_worker] Vẫn chưa có mạng, dừng lượt đồng bộ này: {e}")
            break
        except Exception as e:
            # Lỗi khác (không phải do mất mạng, vd dữ liệu hỏng) -> ghi nhận lỗi vào chính bản
            # ghi đó, KHÔNG xoá cache, KHÔNG chặn các đơn khác trong lượt quét này.
            attempts = int(pending_doc.get('sync_attempts', 0)) + 1
            update = {'$inc': {'sync_attempts': 1}, '$set': {'last_error': str(e)}}
            if attempts >= MAX_SYNC_ATTEMPTS:
                # Quá số lần thử — ngưng để _pending_sync=False loại nó khỏi lượt quét kế tiếp
                # (không xoá bản ghi: vẫn giữ lại để admin xem tay + biết KHÔNG được double-charge
                # khách nếu họ đến hỏi lại, vì đơn này CHƯA từng lên được Atlas).
                update['$set']['_pending_sync'] = False
                update['$set']['permanently_failed'] = True
                print(f"[sync_worker] Đơn client_uuid={client_uuid} lỗi {attempts} lần liên tiếp -> "
                      f"NGƯNG tự động retry, cần admin kiểm tra tay: {e}")
            else:
                print(f"[sync_worker] Lỗi đồng bộ đơn client_uuid={client_uuid} (lần {attempts}/{MAX_SYNC_ATTEMPTS}): {e}")
            local_db_conn.pending_sync_orders.update_one({'client_uuid': client_uuid}, update)
    return synced


def _run_forever():
    while True:
        try:
            sync_pending_orders_once()
        except Exception as e:
            print(f"[sync_worker] Lỗi vòng lặp nền (không crash worker): {e}")
        time.sleep(SYNC_INTERVAL_SECONDS)


def start_background_sync():
    """Gọi 1 LẦN từ desktop_app/launcher.py, ngay sau khi Flask app đã khởi động xong (để
    import app.py lazy ở trên chắc chắn không đụng độ). daemon=True: thread tự tắt theo khi
    người dùng đóng cửa sổ app, không cần shutdown thủ công."""
    thread = threading.Thread(target=_run_forever, daemon=True, name="bitpaw-offline-sync")
    thread.start()
    return thread
