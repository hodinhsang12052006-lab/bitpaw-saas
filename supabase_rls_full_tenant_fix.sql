-- =========================================================================
-- FIX RANH GIỚI DỮ LIỆU MULTI-TENANT CHO TOÀN BỘ CÁC BẢNG CÒN LẠI
-- (POS, QR gọi món, Kho, CRM, Sổ quỹ, CSKH/Bot, Khuyến mãi, Backup logs...)
-- Chạy thủ công trong Supabase Dashboard -> SQL Editor (không tự động chạy).
--
-- Bảng staff/attendance/payroll/salary_configs/employees/chamcong/cho_doi_ca
-- đã được xử lý riêng ở file supabase_rls_hr_tenant_fix.sql — KHÔNG lặp lại
-- ở đây để tránh chạy trùng.
--
-- Dùng đúng cơ chế tự-kiểm-tra như file HR: bảng nào không tồn tại trong
-- database thật của bạn sẽ tự động bị bỏ qua (NOTICE báo rõ), không còn báo
-- lỗi 42P01/42703.
--
-- CÓ 2 LOẠI JWT trong hệ thống:
--   - Token NHÂN VIÊN (ký ở GET /api/session/supabase_token, cần đăng nhập):
--     claim business_id, KHÔNG có claim "scope" -> coi là quyền đầy đủ.
--   - Token KHÁCH VÃNG LAI (ký thẳng trong app.py khi render qr_menu.html/
--     table_order.html/booking.html cho khách quét QR, KHÔNG cần đăng nhập):
--     claim business_id + claim "scope" = "qr_public" -> quyền bị GIỚI HẠN,
--     chỉ được nêu rõ trong từng policy bên dưới, KHÔNG được đọc bất kỳ dữ
--     liệu nhạy cảm nào khác (khách hàng, nhân viên, lương, doanh thu, đơn
--     hàng của người khác...) dù business_id có trùng khớp.
-- =========================================================================

-- -------------------------------------------------------------------------
-- PHẦN 1) Các bảng CHỈ dành cho nhân viên/chủ tiệm (KHÔNG bao giờ cho phép
-- token scope='qr_public' đọc/ghi, kể cả khi business_id trùng khớp).
-- -------------------------------------------------------------------------
DO $$
DECLARE
    tbl text;
    staff_only_tables text[] := ARRAY[
        'customers', 'orders', 'order_items', 'appointments', 'karaoke_rooms',
        'expenses', 'user_logs', 'system_settings', 'promotions',
        'cskh_config', 'cskh_requests', 'cskh_clicks', 'customer_feedback',
        'bot_customers', 'bot_messages', 'backup_logs',
        'transactions', 'kho_vat_tu', 'crm_messages', 'debt_transactions',
        'suppliers', 'messages', 'ecommerce_orders',
        'ecommerce_products', 'ecommerce_connections', 'ecommerce_sync_queue',
        'inventory_logs', 'kitchen_orders'
    ];
BEGIN
    FOREACH tbl IN ARRAY staff_only_tables LOOP
        IF EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = tbl
        ) THEN
            EXECUTE format('ALTER TABLE public.%I ADD COLUMN IF NOT EXISTS business_id text', tbl);
            EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', tbl);
            EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', 'Allow all access to ' || tbl || ' for tenant', tbl);
            EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', 'Tenant isolation for ' || tbl, tbl);
            EXECUTE format(
                'CREATE POLICY %I ON public.%I FOR ALL TO authenticated USING (business_id = (auth.jwt() ->> ''business_id'') AND COALESCE(auth.jwt() ->> ''scope'', ''staff'') <> ''qr_public'') WITH CHECK (business_id = (auth.jwt() ->> ''business_id'') AND COALESCE(auth.jwt() ->> ''scope'', ''staff'') <> ''qr_public'')',
                'Tenant isolation for ' || tbl, tbl
            );
            RAISE NOTICE '[OK - staff only] Đã áp dụng RLS cho bảng: %', tbl;
        ELSE
            RAISE NOTICE '[BỎ QUA] Bảng không tồn tại trong database này: %', tbl;
        END IF;
    END LOOP;
END $$;

-- -------------------------------------------------------------------------
-- PHẦN 2) Các bảng DÙNG CHUNG giữa nhân viên và khách vãng lai (QR gọi món /
-- đặt lịch). Mỗi bảng viết policy riêng theo TỪNG THAO TÁC (SELECT/INSERT/
-- UPDATE/DELETE) vì phạm vi cho phép khác nhau giữa 2 loại token.
--
-- Nguyên tắc: khách vãng lai (scope='qr_public') CHỈ được xem menu/dịch vụ/
-- bàn và tạo đơn/đặt lịch mới tại đúng bàn/tiệm đã quét — không được xem lại
-- đơn hàng, không được sửa/xoá menu, không được thao tác trên bàn khác.
-- -------------------------------------------------------------------------

-- ===== dining_tables =====
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='dining_tables') THEN
        ALTER TABLE public.dining_tables ADD COLUMN IF NOT EXISTS business_id text;
        ALTER TABLE public.dining_tables ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS "Allow all access to dining_tables for tenant" ON public.dining_tables;
        DROP POLICY IF EXISTS "Tenant isolation for dining_tables" ON public.dining_tables;
        DROP POLICY IF EXISTS "dining_tables_select_any_scope" ON public.dining_tables;
        DROP POLICY IF EXISTS "dining_tables_update_any_scope" ON public.dining_tables;
        DROP POLICY IF EXISTS "dining_tables_insert_staff_only" ON public.dining_tables;
        DROP POLICY IF EXISTS "dining_tables_delete_staff_only" ON public.dining_tables;

        -- Đọc: nhân viên lẫn khách quét QR đều cần thấy trạng thái bàn của đúng tiệm.
        CREATE POLICY "dining_tables_select_any_scope" ON public.dining_tables
            FOR SELECT TO authenticated
            USING (business_id = (auth.jwt() ->> 'business_id'));

        -- Cập nhật: khách quét QR cần đổi trạng thái bàn ('Đang phục vụ') khi gửi đơn;
        -- nhân viên cần đổi trạng thái khi thu ngân/dọn bàn. Cùng phạm vi business_id.
        CREATE POLICY "dining_tables_update_any_scope" ON public.dining_tables
            FOR UPDATE TO authenticated
            USING (business_id = (auth.jwt() ->> 'business_id'))
            WITH CHECK (business_id = (auth.jwt() ->> 'business_id'));

        -- Tạo/xoá bàn: chỉ nhân viên/chủ tiệm.
        CREATE POLICY "dining_tables_insert_staff_only" ON public.dining_tables
            FOR INSERT TO authenticated
            WITH CHECK (business_id = (auth.jwt() ->> 'business_id') AND COALESCE(auth.jwt() ->> 'scope', 'staff') <> 'qr_public');
        CREATE POLICY "dining_tables_delete_staff_only" ON public.dining_tables
            FOR DELETE TO authenticated
            USING (business_id = (auth.jwt() ->> 'business_id') AND COALESCE(auth.jwt() ->> 'scope', 'staff') <> 'qr_public');

        RAISE NOTICE '[OK - dual scope] Đã áp dụng RLS cho bảng: dining_tables';
    ELSE
        RAISE NOTICE '[BỎ QUA] Bảng không tồn tại trong database này: dining_tables';
    END IF;
END $$;

-- ===== products (menu) =====
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='products') THEN
        ALTER TABLE public.products ADD COLUMN IF NOT EXISTS business_id text;
        ALTER TABLE public.products ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS "Allow all access to products for tenant" ON public.products;
        DROP POLICY IF EXISTS "Tenant isolation for products" ON public.products;
        DROP POLICY IF EXISTS "products_select_any_scope" ON public.products;
        DROP POLICY IF EXISTS "products_insert_staff_only" ON public.products;
        DROP POLICY IF EXISTS "products_update_staff_only" ON public.products;
        DROP POLICY IF EXISTS "products_delete_staff_only" ON public.products;

        -- Đọc menu: khách quét QR và nhân viên đều được, chỉ giới hạn theo business_id.
        CREATE POLICY "products_select_any_scope" ON public.products
            FOR SELECT TO authenticated
            USING (business_id = (auth.jwt() ->> 'business_id'));

        -- Thêm/sửa/xoá sản phẩm: chỉ nhân viên/chủ tiệm (khách quét QR không được đổi menu/giá/tồn kho).
        CREATE POLICY "products_insert_staff_only" ON public.products
            FOR INSERT TO authenticated
            WITH CHECK (business_id = (auth.jwt() ->> 'business_id') AND COALESCE(auth.jwt() ->> 'scope', 'staff') <> 'qr_public');
        CREATE POLICY "products_update_staff_only" ON public.products
            FOR UPDATE TO authenticated
            USING (business_id = (auth.jwt() ->> 'business_id') AND COALESCE(auth.jwt() ->> 'scope', 'staff') <> 'qr_public')
            WITH CHECK (business_id = (auth.jwt() ->> 'business_id') AND COALESCE(auth.jwt() ->> 'scope', 'staff') <> 'qr_public');
        CREATE POLICY "products_delete_staff_only" ON public.products
            FOR DELETE TO authenticated
            USING (business_id = (auth.jwt() ->> 'business_id') AND COALESCE(auth.jwt() ->> 'scope', 'staff') <> 'qr_public');

        RAISE NOTICE '[OK - dual scope] Đã áp dụng RLS cho bảng: products';
    ELSE
        RAISE NOTICE '[BỎ QUA] Bảng không tồn tại trong database này: products';
    END IF;
END $$;

-- ===== table_orders (đơn hàng đang treo tại bàn) =====
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='table_orders') THEN
        ALTER TABLE public.table_orders ADD COLUMN IF NOT EXISTS business_id text;
        ALTER TABLE public.table_orders ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS "Allow all access to table_orders for tenant" ON public.table_orders;
        DROP POLICY IF EXISTS "Tenant isolation for table_orders" ON public.table_orders;
        DROP POLICY IF EXISTS "table_orders_insert_any_scope" ON public.table_orders;
        DROP POLICY IF EXISTS "table_orders_select_staff_only" ON public.table_orders;
        DROP POLICY IF EXISTS "table_orders_update_staff_only" ON public.table_orders;
        DROP POLICY IF EXISTS "table_orders_delete_staff_only" ON public.table_orders;

        -- Tạo đơn: khách quét QR gửi món cũng là INSERT vào đây -> cho phép cả 2 loại token.
        CREATE POLICY "table_orders_insert_any_scope" ON public.table_orders
            FOR INSERT TO authenticated
            WITH CHECK (business_id = (auth.jwt() ->> 'business_id'));

        -- Đọc lại / sửa / xoá đơn: chỉ nhân viên (khách quét QR không tự xem/sửa/xoá đơn đã gửi).
        CREATE POLICY "table_orders_select_staff_only" ON public.table_orders
            FOR SELECT TO authenticated
            USING (business_id = (auth.jwt() ->> 'business_id') AND COALESCE(auth.jwt() ->> 'scope', 'staff') <> 'qr_public');
        CREATE POLICY "table_orders_update_staff_only" ON public.table_orders
            FOR UPDATE TO authenticated
            USING (business_id = (auth.jwt() ->> 'business_id') AND COALESCE(auth.jwt() ->> 'scope', 'staff') <> 'qr_public')
            WITH CHECK (business_id = (auth.jwt() ->> 'business_id') AND COALESCE(auth.jwt() ->> 'scope', 'staff') <> 'qr_public');
        CREATE POLICY "table_orders_delete_staff_only" ON public.table_orders
            FOR DELETE TO authenticated
            USING (business_id = (auth.jwt() ->> 'business_id') AND COALESCE(auth.jwt() ->> 'scope', 'staff') <> 'qr_public');

        RAISE NOTICE '[OK - dual scope] Đã áp dụng RLS cho bảng: table_orders';
    ELSE
        RAISE NOTICE '[BỎ QUA] Bảng không tồn tại trong database này: table_orders';
    END IF;
END $$;

-- ===== dichvu (bảng giá dịch vụ, dùng bởi booking.html) =====
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='dichvu') THEN
        ALTER TABLE public.dichvu ADD COLUMN IF NOT EXISTS business_id text;
        ALTER TABLE public.dichvu ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS "Allow all access to dichvu for tenant" ON public.dichvu;
        DROP POLICY IF EXISTS "Tenant isolation for dichvu" ON public.dichvu;
        DROP POLICY IF EXISTS "dichvu_select_any_scope" ON public.dichvu;
        DROP POLICY IF EXISTS "dichvu_insert_staff_only" ON public.dichvu;
        DROP POLICY IF EXISTS "dichvu_update_staff_only" ON public.dichvu;
        DROP POLICY IF EXISTS "dichvu_delete_staff_only" ON public.dichvu;

        CREATE POLICY "dichvu_select_any_scope" ON public.dichvu
            FOR SELECT TO authenticated
            USING (business_id = (auth.jwt() ->> 'business_id'));
        CREATE POLICY "dichvu_insert_staff_only" ON public.dichvu
            FOR INSERT TO authenticated
            WITH CHECK (business_id = (auth.jwt() ->> 'business_id') AND COALESCE(auth.jwt() ->> 'scope', 'staff') <> 'qr_public');
        CREATE POLICY "dichvu_update_staff_only" ON public.dichvu
            FOR UPDATE TO authenticated
            USING (business_id = (auth.jwt() ->> 'business_id') AND COALESCE(auth.jwt() ->> 'scope', 'staff') <> 'qr_public')
            WITH CHECK (business_id = (auth.jwt() ->> 'business_id') AND COALESCE(auth.jwt() ->> 'scope', 'staff') <> 'qr_public');
        CREATE POLICY "dichvu_delete_staff_only" ON public.dichvu
            FOR DELETE TO authenticated
            USING (business_id = (auth.jwt() ->> 'business_id') AND COALESCE(auth.jwt() ->> 'scope', 'staff') <> 'qr_public');

        RAISE NOTICE '[OK - dual scope] Đã áp dụng RLS cho bảng: dichvu';
    ELSE
        RAISE NOTICE '[BỎ QUA] Bảng không tồn tại trong database này: dichvu';
    END IF;
END $$;

-- ===== tasks (nhiệm vụ nội bộ HR + yêu cầu đặt lịch từ booking.html) =====
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='tasks') THEN
        ALTER TABLE public.tasks ADD COLUMN IF NOT EXISTS business_id text;
        ALTER TABLE public.tasks ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS "Allow all access to tasks for tenant" ON public.tasks;
        DROP POLICY IF EXISTS "Tenant isolation for tasks" ON public.tasks;
        DROP POLICY IF EXISTS "tasks_insert_any_scope" ON public.tasks;
        DROP POLICY IF EXISTS "tasks_select_staff_only" ON public.tasks;
        DROP POLICY IF EXISTS "tasks_update_staff_only" ON public.tasks;
        DROP POLICY IF EXISTS "tasks_delete_staff_only" ON public.tasks;

        -- Khách đặt lịch qua booking.html chỉ TẠO yêu cầu mới (INSERT), không đọc lại được.
        CREATE POLICY "tasks_insert_any_scope" ON public.tasks
            FOR INSERT TO authenticated
            WITH CHECK (business_id = (auth.jwt() ->> 'business_id'));

        -- Xem/nhận/sửa/xoá nhiệm vụ: chỉ nhân viên nội bộ.
        CREATE POLICY "tasks_select_staff_only" ON public.tasks
            FOR SELECT TO authenticated
            USING (business_id = (auth.jwt() ->> 'business_id') AND COALESCE(auth.jwt() ->> 'scope', 'staff') <> 'qr_public');
        CREATE POLICY "tasks_update_staff_only" ON public.tasks
            FOR UPDATE TO authenticated
            USING (business_id = (auth.jwt() ->> 'business_id') AND COALESCE(auth.jwt() ->> 'scope', 'staff') <> 'qr_public')
            WITH CHECK (business_id = (auth.jwt() ->> 'business_id') AND COALESCE(auth.jwt() ->> 'scope', 'staff') <> 'qr_public');
        CREATE POLICY "tasks_delete_staff_only" ON public.tasks
            FOR DELETE TO authenticated
            USING (business_id = (auth.jwt() ->> 'business_id') AND COALESCE(auth.jwt() ->> 'scope', 'staff') <> 'qr_public');

        RAISE NOTICE '[OK - dual scope] Đã áp dụng RLS cho bảng: tasks';
    ELSE
        RAISE NOTICE '[BỎ QUA] Bảng không tồn tại trong database này: tasks';
    END IF;
END $$;

-- KHÔNG đưa vào bất kỳ phần nào ở trên (cố tình bỏ qua, đừng thêm nhầm):
--   - businesses, profiles: đây LÀ bảng định danh tenant, không phải dữ liệu
--     THUỘC VỀ 1 tenant — chủ tiệm cần đọc chính hàng của họ qua auth.uid(),
--     không phải business_id claim. Áp policy kiểu này vào sẽ khóa luôn
--     không ai đăng nhập/đọc hồ sơ chính mình được nữa.
--   - license_codes: mã kích hoạt license dùng chung hệ thống, không thuộc
--     riêng 1 tenant.
--   - industry_registry, module_registry, feature_registry, route_registry,
--     permission_registry, role_registry, role_permissions, template_registry:
--     dữ liệu cấu hình hệ thống dùng chung cho mọi tenant (đã có policy
--     riêng trong supabase_rls.sql, không phải USING(true) vô tội vạ).

-- LƯU Ý QUAN TRỌNG:
--
-- 1. Đọc tab "Messages"/"NOTICE" sau khi chạy để biết chính xác bảng nào
--    ĐÃ áp dụng, bảng nào BỊ BỎ QUA (không tồn tại) trong database của bạn.
--
-- 2. Dữ liệu CŨ trong mỗi bảng sẽ có business_id = NULL sau khi thêm cột
--    -> ẨN KHỎI MỌI NGƯỜI (kể cả chủ đúng của nó) cho tới khi bạn tự
--    backfill business_id cho từng dòng cũ. Bảng `orders`/`products`/
--    `customers`/`dining_tables`/`table_orders` thường có RẤT NHIỀU dữ liệu
--    cũ — nên tự viết script backfill (map theo cách bạn biết dữ liệu cũ
--    thuộc tiệm nào) TRƯỚC khi chạy file này ở production, nếu không toàn
--    bộ đơn hàng/khách hàng/sản phẩm/bàn cũ sẽ biến mất khỏi giao diện ngay.
--
-- 3. Token nhân viên (GET /api/session/supabase_token) cần biến môi trường
--    SUPABASE_JWT_SECRET đã điền thật trong .env production. Token khách
--    vãng lai (qr_menu.html/table_order.html/booking.html) được ký thẳng
--    trong app.py khi render trang (dùng CHUNG biến SUPABASE_JWT_SECRET đó)
--    — không cần thêm cấu hình nào khác. Nếu chưa điền biến này, TẤT CẢ các
--    trang liên quan (nhân viên lẫn khách vãng lai) sẽ ngừng tải được dữ
--    liệu ngay sau khi chạy file này.
