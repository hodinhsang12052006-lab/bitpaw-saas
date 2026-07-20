# ========================================================================================
# Script hợp nhất dữ liệu SQLite `local_attendance` (database.db) vào MongoDB, dứt điểm tình
# trạng 2 hệ chấm công chạy song song (xem app.py: /api/chamcong/checkin, /checkout, /status).
#
# CHẠY THỬ TRƯỚC (không ghi gì cả, chỉ in ra):
#   python migrate_local_attendance_to_mongo.py
#
# GHI THẬT (sau khi đã xem kỹ output dry-run ở trên):
#   python migrate_local_attendance_to_mongo.py --apply
#
# AN TOÀN CHẠY LẶP LẠI (idempotent): mỗi bản ghi Mongo tạo ra được đánh dấu
# 'migrated_from': 'local_attendance' + 'source_sqlite_id': <id> — chạy lại script sẽ tự bỏ
# qua các dòng đã migrate rồi, không tạo trùng.
#
# GIỚI HẠN QUAN TRỌNG (đọc kỹ): local_attendance.staff_id và db.chamcong.ma_nv là 2 không gian
# khóa KHÁC NHAU (POS staff vs HR employee — xem ghi chú "2 hệ nhân sự riêng biệt" trong
# nhanvien.html). Script CHỈ ghi vào db.chamcong khi tìm được đúng 1 nhân viên khớp qua
# db.employees.staff_id (nếu có) hoặc trực tiếp qua ma_nv (nếu staff_id trong SQLite vốn đã là
# 1 mã ma_nv dạng chữ, ví dụ "NV_AUTO_001"). Dòng nào KHÔNG khớp được sẽ liệt kê riêng ở cuối,
# KHÔNG bịa ra liên kết — bạn cần tự đối chiếu thủ công rồi chạy lại nếu muốn.
# ========================================================================================

import sqlite3
import sys
from datetime import datetime

# Console Windows mặc định dùng code page cp1252/cp437, không in được tiếng Việt có dấu -> crash
# UnicodeEncodeError ngay khi print(). Ép stdout/stderr sang UTF-8 (Python 3.7+) để chạy được
# trên cmd/PowerShell mặc định, không cần người chạy tự đổi `chcp 65001` trước.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, 'reconfigure'):
        _stream.reconfigure(encoding='utf-8')

from mongo_client import db, MONGO_STATUS, next_mongo_id

APPLY = '--apply' in sys.argv


def parse_iso(value):
    """local_attendance lưu clock_in/clock_out dạng ISO (datetime.now().isoformat()) —
    tách ra ngày (DD/MM/YYYY, đúng format ngay_cham của db.chamcong) và giờ (HH:MM)."""
    if not value:
        return None, None
    try:
        dt = datetime.fromisoformat(value)
        return dt.strftime('%d/%m/%Y'), dt.strftime('%H:%M')
    except Exception:
        return None, None


def compute_hours(clock_in_iso, clock_out_iso):
    if not clock_in_iso or not clock_out_iso:
        return 0.0
    try:
        t_in = datetime.fromisoformat(clock_in_iso)
        t_out = datetime.fromisoformat(clock_out_iso)
        delta_hours = (t_out - t_in).total_seconds() / 3600
        return round(delta_hours, 2) if delta_hours > 0 else 0.0
    except Exception:
        return 0.0


def resolve_employee(staff_id_raw, business_id):
    """Trả về document db.employees khớp với giá trị staff_id thô đọc từ SQLite, hoặc None nếu
    không tìm được — KHÔNG suy đoán/fallback mù, chỉ thử 2 cách tra cứu hợp lý:
    1) staff_id là số -> tìm employees.staff_id đúng bằng số đó (link chính thức, dù hiện tại
       luôn None trong data thật — vẫn thử phòng khi đã được gán ở đâu đó).
    2) staff_id không phải số (vd "NV_AUTO_001") -> có thể CHÍNH LÀ 1 ma_nv -> tìm thẳng theo ma_nv.
    """
    if staff_id_raw.isdigit():
        try:
            return db.employees.find_one({'staff_id': int(staff_id_raw), 'business_id': business_id})
        except Exception:
            return None
    return db.employees.find_one({'ma_nv': staff_id_raw, 'business_id': business_id})


def main():
    if MONGO_STATUS != "CONNECTED":
        print(f"[!] MongoDB chưa kết nối (status={MONGO_STATUS}). Dừng script — không migrate khi chưa chắc DB đích sẵn sàng.")
        sys.exit(1)

    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    try:
        c.execute("SELECT id, staff_id, clock_in, clock_out, latitude, longitude, status, note FROM local_attendance ORDER BY id")
        rows = c.fetchall()
    except sqlite3.OperationalError as e:
        print(f"[!] Không đọc được bảng local_attendance: {e}")
        conn.close()
        sys.exit(1)
    conn.close()

    print(f"{'[DRY-RUN] ' if not APPLY else ''}Tìm thấy {len(rows)} bản ghi trong local_attendance.\n")

    migrated_attendance = 0
    skipped_attendance = 0
    migrated_chamcong = 0
    unmapped = []

    for row in rows:
        source_id = row['id']
        staff_id_raw = str(row['staff_id'])
        ngay_cham, gio_den = parse_iso(row['clock_in'])
        _, gio_ve = parse_iso(row['clock_out'])
        so_gio = compute_hours(row['clock_in'], row['clock_out'])

        # --- 1) Luôn mirror an toàn vào db.attendance (cùng không gian khóa staff_id) ---
        already = db.attendance.find_one({'migrated_from': 'local_attendance', 'source_sqlite_id': source_id})
        if already:
            skipped_attendance += 1
        else:
            doc = {
                'id': next_mongo_id('attendance') if APPLY else None,
                'staff_id': int(staff_id_raw) if staff_id_raw.isdigit() else staff_id_raw,
                'clock_in': row['clock_in'],
                'clock_out': row['clock_out'],
                'latitude_in': row['latitude'],
                'longitude_in': row['longitude'],
                'status': row['status'],
                'note': row['note'],
                'migrated_from': 'local_attendance',
                'source_sqlite_id': source_id,
            }
            print(f"[attendance] source_id={source_id} staff_id={staff_id_raw} clock_in={row['clock_in']} -> db.attendance")
            if APPLY:
                doc['id'] = next_mongo_id('attendance')
                db.attendance.insert_one(doc)
            migrated_attendance += 1

        # --- 2) Chỉ ghi vào db.chamcong nếu tìm được ĐÚNG nhân viên tương ứng ---
        # business_id: local_attendance không lưu business_id trực tiếp (route checkin cũ chỉ
        # dùng để validate quyền, không lưu vào bảng SQLite) — nên phải thử tra cứu nhân viên
        # KHÔNG lọc business_id trước, rồi tự suy ra business_id từ chính nhân viên tìm được.
        emp = None
        if staff_id_raw.isdigit():
            emp = db.employees.find_one({'staff_id': int(staff_id_raw)})
        if not emp:
            emp = db.employees.find_one({'ma_nv': staff_id_raw})

        if emp:
            exists = db.chamcong.find_one({'migrated_from': 'local_attendance', 'source_sqlite_id': source_id})
            if not exists:
                chamcong_doc = {
                    'ma_nv': emp['ma_nv'],
                    'business_id': emp['business_id'],
                    'ngay_cham': ngay_cham,
                    'gio_den': gio_den,
                    'gio_ve': gio_ve,
                    'so_gio': so_gio,
                    'trang_thai': 'Có mặt',
                    'tien_tua': 0, 'tien_tips': 0, 'phu_cap': 0, 'tang_ca': 0,
                    'ghi_chu': f"[Migrated from local_attendance #{source_id}]",
                    'migrated_from': 'local_attendance',
                    'source_sqlite_id': source_id,
                }
                print(f"    -> khớp nhân viên {emp['ma_nv']} ({emp.get('ho_ten', '?')}) -> ghi thêm vào db.chamcong")
                if APPLY:
                    chamcong_doc['id'] = next_mongo_id('chamcong')
                    db.chamcong.insert_one(chamcong_doc)
                migrated_chamcong += 1
        else:
            unmapped.append((source_id, staff_id_raw))

    print("\n" + "=" * 70)
    print(f"Tổng kết ({'ĐÃ GHI THẬT' if APPLY else 'DRY-RUN — CHƯA GHI GÌ, thêm --apply để ghi thật'}):")
    print(f"  - db.attendance: {migrated_attendance} mới, {skipped_attendance} đã tồn tại (bỏ qua)")
    print(f"  - db.chamcong:   {migrated_chamcong} bản ghi khớp được nhân viên thật")
    if unmapped:
        print(f"\n  ⚠ {len(unmapped)} bản ghi KHÔNG tìm được nhân viên tương ứng trong db.employees")
        print("    (không đưa vào db.chamcong — payroll sẽ KHÔNG thấy các dòng này):")
        for source_id, staff_id_raw in unmapped:
            print(f"      local_attendance.id={source_id}  staff_id='{staff_id_raw}'")
        print("\n    -> Muốn payroll thấy các dòng này: gán db.employees.staff_id hoặc ma_nv")
        print("       đúng với nhân viên thật tương ứng, rồi chạy lại script (an toàn, không trùng).")


if __name__ == '__main__':
    main()
