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
# Sau 1 lần rớt mạng, trong cửa sổ này mọi bill đi thẳng vào bộ nhớ máy (không thử Atlas nữa):
# mỗi lần thử Atlas khi mất mạng tốn tới serverSelectionTimeoutMS (5s) -> cashier phải chờ ~10s/bill.
# Thread nền đồng bộ thành công (hoặc 1 request online bình thường) sẽ xoá cờ này sớm hơn.
OFFLINE_WINDOW_SECONDS = 60
MONGO_CONNECTION_ERRORS = _MONGO_CONNECTION_ERRORS

_state_lock = threading.Lock()
_last_offline_at = 0.0
_last_sync_ok_at = None


def mark_offline():
    global _last_offline_at
    with _state_lock:
        _last_offline_at = time.time()


def mark_online():
    global _last_offline_at
    with _state_lock:
        _last_offline_at = 0.0


def is_offline_recently():
    with _state_lock:
        return bool(_last_offline_at) and (time.time() - _last_offline_at) < OFFLINE_WINDOW_SECONDS


def cache_catalog(business_id, services=None, technicians=None, products=None, commission_rate=None):
    """Lưu bảng giá dịch vụ + danh sách thợ + % hoa hồng của tiệm xuống máy (local_db) mỗi lần
    đọc được từ Atlas — để khi mất mạng vẫn tính tiền và mở lại màn POS được. `products`: dict
    id -> product doc, gộp thêm vào bản đã lưu (không xoá sản phẩm cũ)."""
    from local_db import db as local_db_conn

    doc = local_db_conn.catalog_cache.find_one({'business_id': business_id}) or {}
    update = {'business_id': business_id, 'cached_at': datetime.now().isoformat()}
    if services is not None:
        update['services'] = services
    if technicians is not None:
        update['technicians'] = technicians
    if commission_rate is not None:
        update['commission_rate'] = commission_rate
    merged = dict(doc.get('products') or {})
    for svc in services or []:
        if svc.get('id') is not None:
            merged[str(svc['id'])] = {**merged.get(str(svc['id']), {}), **svc}
    for pid, prod in (products or {}).items():
        merged[str(pid)] = prod
    if merged:
        update['products'] = merged
    local_db_conn.catalog_cache.update_one({'business_id': business_id}, {'$set': update}, upsert=True)


def get_cached_catalog(business_id):
    """Bảng giá đã lưu trên máy, hoặc None nếu máy chưa từng mở POS lúc có mạng. Khoá `products`
    trả về theo id gốc (int) để khớp product_id trong giỏ hàng."""
    from local_db import db as local_db_conn

    doc = local_db_conn.catalog_cache.find_one({'business_id': business_id}, {'_id': 0})
    if not doc:
        return None
    doc['products'] = {prod.get('id', key): prod for key, prod in (doc.get('products') or {}).items()}
    return doc


def sync_status(business_id):
    """Cho màn POS hiện "Offline · N bill chờ đồng bộ" (route /api/desktop/sync_status)."""
    from local_db import db as local_db_conn

    pending = local_db_conn.pending_sync_orders.count_documents({'business_id': business_id, '_pending_sync': True})
    failed = local_db_conn.pending_sync_orders.count_documents({'business_id': business_id, 'permanently_failed': True})
    return {'offline': is_offline_recently(), 'pending': pending, 'failed': failed, 'last_sync_ok_at': _last_sync_ok_at}


def queue_offline_order(business_id, computed, customer_phone, customer_name=None, created_by=None):
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
        'customer_name': customer_name or None,
        'created_by': created_by,
        # tuple (product_id, qty, name) -> list: MontyDB/BSON không lưu tuple
        'computed': {**computed, 'stock_items': [list(x) for x in computed.get('stock_items') or []]},
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
    from app import _build_nail_chamcong_docs, _finalize_paid_order, _record_pos_transaction
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
    customer_name = pending_doc.get('customer_name')

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
        'card_surcharge_amount': computed.get('card_surcharge_amount', 0),
        'offline_queued_at': pending_doc.get('queued_at'),
    }
    if computed['payment_bucket'] == 'split':
        metadata['split_cash_amount'] = computed['split_cash_amount']
        metadata['split_card_amount'] = computed['split_card_amount']
    if customer_phone:
        metadata['customer_phone'] = customer_phone
    if customer_name:
        metadata['customer_name'] = customer_name
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
            # Sổ cái (Sổ quỹ / Báo cáo lãi lỗ) — trước đây đơn đồng bộ offline không có bản ghi này,
            # nên doanh thu bán lúc mất mạng không bao giờ hiện trong báo cáo tài chính.
            _record_pos_transaction(
                business_id, order_id, computed['total_amount'], computed['payment_method'],
                created_by=pending_doc.get('created_by') or 'offline-sync', db_session=db_session,
            )
            # Trừ kho: hàng đã giao cho khách lúc mất mạng nên KHÔNG chặn khi tồn kho thiếu (khác
            # bán online) — trừ thẳng để số tồn khớp thực tế, kể cả xuống âm cho chủ tiệm thấy.
            for product_id, qty, *_rest in computed.get('stock_items') or []:
                if qty and qty > 0:
                    cloud_db.products.update_one(
                        {'id': product_id, 'business_id': business_id, 'stock': {'$exists': True}},
                        {'$inc': {'stock': -qty}}, session=db_session,
                    )

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

    global _last_sync_ok_at
    pending_list = list(local_db_conn.pending_sync_orders.find({'_pending_sync': True}))
    if not pending_list:
        return 0

    synced = 0
    for pending_doc in pending_list:
        client_uuid = pending_doc.get('client_uuid', '?')
        try:
            if _sync_one_pending(local_db_conn, pending_doc):
                synced += 1
                mark_online()
                _last_sync_ok_at = datetime.now().isoformat()
        except _MONGO_CONNECTION_ERRORS as e:
            mark_offline()
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
