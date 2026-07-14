-- =========================================================================
-- FIX RANH GIỚI DỮ LIỆU MULTI-TENANT CHO MODULE NHÂN SỰ / CHẤM CÔNG / LƯƠNG
-- Chạy thủ công trong Supabase Dashboard -> SQL Editor (không tự động chạy).
--
-- Bối cảnh: database thật trên Supabase của bạn lệch so với các file schema
-- trong repo (2 lần chạy trước đã báo lỗi vì bảng/cột được liệt kê cứng
-- không khớp thực tế: có bảng thì thiếu cột, có bảng thì không tồn tại).
-- Thay vì tiếp tục đoán tên bảng, file này TỰ KIỂM TRA từng bảng có tồn tại
-- hay không (qua information_schema) rồi mới áp dụng — bảng nào không có
-- thì tự động BỎ QUA (có NOTICE báo rõ), không còn báo lỗi 42P01/42703 nữa.
--
-- Với mỗi bảng tồn tại, khối DO bên dưới sẽ:
--   1. Thêm cột business_id (kiểu text, không FK) nếu chưa có.
--   2. Bật Row Level Security.
--   3. Xóa policy permissive cũ "USING (true)" (nếu có, dù đặt tên kiểu nào).
--   4. Tạo policy mới: chỉ đọc/ghi được dòng có business_id trùng claim
--      "business_id" trong JWT — JWT này do endpoint Flask mới
--      /api/session/supabase_token ký riêng cho tenant đang đăng nhập.
-- =========================================================================

-- LƯU Ý: 'tasks' KHÔNG nằm trong danh sách này nữa — bảng này còn được
-- booking.html (khách vãng lai đặt lịch qua QR, token scope='qr_public')
-- dùng để tạo yêu cầu đặt lịch, nên cần policy riêng (chỉ cho INSERT với
-- scope công khai, còn SELECT/UPDATE/DELETE vẫn chỉ dành cho nhân viên).
-- Xem phần "Bảng dùng chung staff + khách vãng lai" ở supabase_rls_full_tenant_fix.sql.
DO $$
DECLARE
    tbl text;
    hr_tables text[] := ARRAY[
        'staff', 'attendance', 'payroll', 'salary_configs',
        'employees', 'chamcong', 'cho_doi_ca'
    ];
BEGIN
    FOREACH tbl IN ARRAY hr_tables LOOP
        IF EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = tbl
        ) THEN
            -- 1) Đảm bảo có cột business_id (không phá dữ liệu cũ; dòng cũ sẽ là NULL)
            EXECUTE format('ALTER TABLE public.%I ADD COLUMN IF NOT EXISTS business_id text', tbl);

            -- 2) Bật RLS
            EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', tbl);

            -- 3) Xóa mọi policy permissive cũ có thể tồn tại trên bảng này
            EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', 'Allow all access to ' || tbl || ' for tenant', tbl);
            EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', 'Tenant isolation for ' || tbl, tbl);

            -- 4) Tạo policy: chỉ nhân viên (scope khác 'qr_public') của đúng tenant mới đọc/ghi được.
            -- Dữ liệu nhân sự/lương tuyệt đối không được lộ qua token công khai của khách quét QR,
            -- kể cả khi (giả sử) business_id trùng khớp.
            EXECUTE format(
                'CREATE POLICY %I ON public.%I FOR ALL TO authenticated USING (business_id = (auth.jwt() ->> ''business_id'') AND COALESCE(auth.jwt() ->> ''scope'', ''staff'') <> ''qr_public'') WITH CHECK (business_id = (auth.jwt() ->> ''business_id'') AND COALESCE(auth.jwt() ->> ''scope'', ''staff'') <> ''qr_public'')',
                'Tenant isolation for ' || tbl, tbl
            );

            RAISE NOTICE '[OK] Đã áp dụng RLS tenant cho bảng: %', tbl;
        ELSE
            RAISE NOTICE '[BỎ QUA] Bảng không tồn tại trong database này: %', tbl;
        END IF;
    END LOOP;
END $$;

-- -------------------------------------------------------------------------
-- Storage bucket 'checkin_images' (dùng bởi diemdanh.html / app_nhanvien.html)
-- hiện không có policy riêng -> mặc định public bucket policy (thường là
-- đọc/ghi tự do). Khuyến nghị kiểm tra Storage -> Policies cho bucket này
-- và giới hạn theo (auth.jwt() ->> 'business_id') tương tự nếu cần.
-- -------------------------------------------------------------------------

-- LƯU Ý QUAN TRỌNG (đọc kỹ trước khi chạy):
--
-- 1. Sau khi chạy, hãy đọc phần "Messages"/"NOTICE" trong kết quả SQL Editor
--    để biết chính xác bảng nào ĐÃ áp dụng và bảng nào BỊ BỎ QUA (không tồn
--    tại) — đó là danh sách bảng thật trong database của bạn, không cần
--    đoán nữa.
--
-- 2. Các dòng dữ liệu CŨ trong mỗi bảng sẽ có business_id = NULL sau khi
--    thêm cột -> sẽ KHÔNG hiển thị được cho ai (kể cả chủ đúng của nó) cho
--    tới khi bạn tự backfill business_id cho từng dòng cũ. Không thể tự
--    động backfill an toàn từ đây vì không có cách nào xác định dòng nào
--    thuộc tenant nào.
--
-- 3. Các policy này chỉ có tác dụng khi request mang JWT có claim
--    "business_id" và role "authenticated" — JWT này do endpoint Flask
--       GET /api/session/supabase_token   (xem app.py)
--    ký, và endpoint đó cần biến môi trường SUPABASE_JWT_SECRET (Supabase
--    Dashboard -> Settings -> API -> JWT Secret) mới hoạt động. Chưa điền
--    biến này vào .env production thì sau khi chạy file này, các trang
--    nhanvien/bangluong/chamcong_*/app_nhanvien sẽ NGỪNG TẢI được dữ liệu
--    (bị policy từ chối) cho tới khi bạn điền và deploy lại.
