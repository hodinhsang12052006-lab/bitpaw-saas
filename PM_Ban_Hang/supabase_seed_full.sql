-- ==================================================================================
-- BITPAW OS - METADATA & COMPONENT SEED DATASET
-- Target Engine: PostgreSQL 15+ / Supabase compatible
-- ==================================================================================

-- ----------------------------------------------------------------------------------
-- 1. SEED INDUSTRIES (Danh mục ngành nghề)
-- ----------------------------------------------------------------------------------
INSERT INTO industry_registry (code, name, icon, description, redirect_after_login) VALUES
('retail', 'Cửa hàng Bán lẻ (Retail)', '🛍️', 'Fashion, Cosmetics, Grocery, Electronics. Inventory controls, barcode management, and profit analytics.', '/dashboard'),
('fnb', 'Nhà hàng & Cafe (F&B)', '🍻', 'Smart POS, Table floor grids, dynamic QR dining menu ordering, and kitchen timecards.', '/pos'),
('spa', 'Spa & Beauty (Nails / Massage)', '🌸', 'Spa, Clinics, Massages. Therapies schedules, KTV allocations, online booker, and commission rates.', '/spa'),
('nail', 'Nails & Salon', '💅', 'Manicure, hand skincare, art nails, and smart attendance controls.', '/chamcong/nail'),
('karaoke', 'Karaoke & Bida giải trí', '🎤', 'Karaoke rooms, game clubs, billiards. Automatic timing, room tracking, and drinks billing.', '/karaoke'),
('hotel', 'Khách Sạn & Homestay', '🏨', 'Homestay, hotels, booking rooms floor, and smart clock-in controls.', '/chamcong/khachsan'),
('production', 'Sản Xuất & Tổ Đội', '🏭', 'Factory floors, assembly lines. Worker attendance, productivity cards, and shift calculations.', '/chamcong/congnhan'),
('technical', 'Dịch Vụ Kỹ Thuật thợ', '🛠️', 'Field technicians, maintenance checkups, dispatching, and GPS check-in logs.', '/chamcong/kythuat'),
('office', 'Khành chính Văn Phòng', '🏢', 'Enterprise office work. Standard administrative timecards, payroll calculating, and salary metrics.', '/chamcong/vanphong')
ON CONFLICT (code) DO UPDATE SET 
    name = EXCLUDED.name, icon = EXCLUDED.icon, description = EXCLUDED.description, redirect_after_login = EXCLUDED.redirect_after_login;

-- ----------------------------------------------------------------------------------
-- 2. SEED BUSINESS MODULES (Các module nghiệp vụ)
-- ----------------------------------------------------------------------------------
INSERT INTO module_registry (code, name, description, category, is_active) VALUES
('dashboard', 'Tổng Quan & Doanh Số', 'Báo cáo tài chính doanh thu chi phí dòng tiền', 'core', true),
('sales', 'Màn Hình Bán Hàng', 'Giao diện thanh toán nhanh cho shop bán lẻ', 'pos', true),
('inventory', 'Quản Lý Kho Hàng', 'Quản lý kho hàng nhập xuất kiểm kê cận date', 'erp', true),
('expenses', 'Quản Lý Chi Tiêu', 'Sổ quỹ ghi nhận chi phí vận hành chiết khấu thợ', 'erp', true),
('ordering', 'Smart POS Gọi Món', 'Giao diện POS phục vụ ăn uống F&B bàn ăn', 'pos', true),
('tables', 'Sơ Đồ Bàn Ăn', 'Quản lý sơ đồ bàn trống, bàn đang ăn phục vụ', 'pos', true),
('attendance', 'Chấm Công Nhân Sự', 'Quản lý điểm danh ca làm việc thợ, KTV, văn phòng', 'hr', true),
('payroll', 'Bảng Tính Lương', 'Tính lương tự động theo chuyên cần và hoa hồng', 'hr', true),
('spa_services', 'POS Dịch Vụ Spa', 'Bảng điều phối kỹ thuật viên làm trị liệu massage', 'pos', true),
('online_booking', 'Đặt Lịch Trực Tuyến', 'Cổng tiếp nhận khách đặt chỗ làm đẹp tự động qua QR', 'pos', true),
('nail_services', 'Dịch Vụ Nails', 'Dịch vụ làm móng Nails & Salon chăm sóc tay chân', 'pos', true),
('room_timing', 'Bán Giờ Karaoke', 'Tính giờ phòng bida/karaoke tự động theo phút', 'pos', true),
('pos_ordering', 'Gọi Đồ Karaoke', 'Order nước hoa quả chèn bill phòng giải trí', 'pos', true),
('room_management', 'Quản Lý Phòng Homestay', 'Quản lý buồng phòng trống khách sạn homestay', 'pos', true),
('factory_output', 'Sản Lượng Tổ Đội', 'Ghi nhận năng suất sản lượng hoàn thành ca xưởng', 'erp', true),
('dispatch_gps', 'GPS Kỹ Thuật Viên', 'Định vị KTV thực địa ngoài hiện trường hiện trạng', 'hr', true),
('ai_bot', 'AI Copilot Assistant', 'Trợ lý ảo AI trực chat và đề xuất tăng doanh thu', 'ai', true),
('ai_studio', 'AI Content Studio', 'Xưởng chế tác content video viral bùng nổ marketing', 'ai', true),
('cskh', 'Kết Nối CSKH', 'Kênh Zalo Hotline Facebook Messenger liên kết 24/7', 'cskh', true),
('backup', 'Sao Lưu An Toàn', 'Hệ thống backup khôi phục dữ liệu lên cloud storage', 'core', true)
ON CONFLICT (code) DO UPDATE SET 
    name = EXCLUDED.name, description = EXCLUDED.description, category = EXCLUDED.category, is_active = EXCLUDED.is_active;

-- ----------------------------------------------------------------------------------
-- 3. SEED SYSTEM PERMISSIONS (Quyền hạn truy cập)
-- ----------------------------------------------------------------------------------
INSERT INTO permission_registry (code, name, description) VALUES
('view_dashboard', 'Quyền Xem Dashboard', 'Cho phép xem báo cáo tài chính doanh thu lợi nhuận'),
('manage_inventory', 'Quyền Quản Lý Kho', 'Cho phép thêm sửa xóa hàng hóa kiểm kê kho'),
('sell', 'Quyền Bán Hàng', 'Cho phép truy cập màn hình thanh toán bán lẻ'),
('view_pos', 'Quyền Mở POS Bán Hàng', 'Cho phép thao tác màn hình gọi món treo bill F&B'),
('manage_tables', 'Quyền Đổi Trạng Thái Bàn', 'Cho phép đổi trạng thái bàn phục vụ sơ đồ bàn ăn'),
('clock_in', 'Quyền Chấm Công Nhân Sự', 'Cho phép check-in check-out ca làm việc nhân viên'),
('view_spa', 'Quyền Xem Trạm Spa', 'Cho phép quản trị trạm spa hoa hồng thợ massage'),
('manage_bookings', 'Quyền Quản Lý Đặt Lịch', 'Cho phép xem xác nhận lịch hẹn đặt trước của khách'),
('view_nail', 'Quyền Xem Trạm Nails', 'Cho phép thao tác trạm dịch vụ nails salon'),
('view_karaoke', 'Quyền Xem Trạm Karaoke', 'Cho phép quản lý sơ đồ phòng hát bida tính giờ'),
('manage_rooms', 'Quyền Bắt Đầu Giờ Hát', 'Cho phép bắt đầu tắt phòng tính tiền giờ karaoke'),
('view_hotel', 'Quyền Xem Trạm Khách Sạn', 'Cho phép quản lý sơ đồ phòng buồng check-in khách sạn'),
('view_production', 'Quyền Xem Trạm Sản Xuất', 'Cho phép ghi nhận năng suất tổ đội công nhân'),
('view_technical', 'Quyền Xem Trạm Kỹ Thuật', 'Cho phép check-in định vị thợ GPS thực địa'),
('view_office', 'Quyền Xem Trạm Văn Phòng', 'Cho phép chấm công tính lương khối văn phòng')
ON CONFLICT (code) DO UPDATE SET 
    name = EXCLUDED.name, description = EXCLUDED.description;

-- ----------------------------------------------------------------------------------
-- 4. SEED ROLE REGISTRY (Bảo mật vai trò)
-- ----------------------------------------------------------------------------------
INSERT INTO role_registry (code, name, description) VALUES
('superadmin', 'Tối Cao Vô Thượng', 'Super Admin cấp mã kích hoạt đúc key bản quyền'),
('admin', 'Chủ Cửa Hàng / Chủ Tiệm', 'Quyền tối cao tại chi nhánh quản lý nhân sự dòng tiền'),
('ktv_truong', 'Kỹ Thuật Viên Trưởng / Tổ Trưởng', 'Quản lý trực ca thợ làm dịch vụ điều phối ca'),
('staff', 'Nhân Viên / Thợ', 'Chỉ được phép chấm công check-in và thực hiện order khách'),
('customer', 'Thành Viên / Khách Quét QR', 'Chỉ được xem menu tự phục vụ đặt món đặt lịch hẹn')
ON CONFLICT (code) DO UPDATE SET 
    name = EXCLUDED.name, description = EXCLUDED.description;

-- ----------------------------------------------------------------------------------
-- 5. SEED ROLE-PERMISSION CORRELATION
-- ----------------------------------------------------------------------------------
-- Admin has all permissions
INSERT INTO role_permissions (role_code, permission_code) VALUES
('admin', 'view_dashboard'),
('admin', 'manage_inventory'),
('admin', 'sell'),
('admin', 'view_pos'),
('admin', 'manage_tables'),
('admin', 'clock_in'),
('admin', 'view_spa'),
('admin', 'manage_bookings'),
('admin', 'view_nail'),
('admin', 'view_karaoke'),
('admin', 'manage_rooms'),
('admin', 'view_hotel'),
('admin', 'view_production'),
('admin', 'view_technical'),
('admin', 'view_office')
ON CONFLICT DO NOTHING;

-- Staff permissions (only sell & clock_in)
INSERT INTO role_permissions (role_code, permission_code) VALUES
('staff', 'sell'),
('staff', 'view_pos'),
('staff', 'clock_in')
ON CONFLICT DO NOTHING;

-- ----------------------------------------------------------------------------------
-- 6. SEED SYSTEM FLASK ROUTES (Sơ đồ route gateway)
-- ----------------------------------------------------------------------------------
INSERT INTO route_registry (endpoint, url_path, request_method, module_code) VALUES
('index', '/dashboard', 'GET', 'dashboard'),
('pos', '/pos', 'GET', 'ordering'),
('qr_menu', '/qr_menu/<path:identifier>', 'GET', 'ordering'),
('public_booking', '/booking', 'GET', 'online_booking'),
('spa', '/spa', 'GET', 'spa_services'),
('karaoke', '/karaoke', 'GET', 'room_timing'),
('ai_bot', '/ai_bot', 'GET', 'ai_bot'),
('ai_studio', '/ai-studio', 'GET', 'ai_studio'),
('bangluong', '/bangluong', 'GET', 'payroll'),
('nhanvien', '/nhanvien', 'GET', 'payroll'),
('cskh_config', '/api/cskh/config', 'GET', 'cskh'),
('backup_restore', '/backup_restore', 'GET', 'backup')
ON CONFLICT (endpoint) DO UPDATE SET 
    url_path = EXCLUDED.url_path, request_method = EXCLUDED.request_method, module_code = EXCLUDED.module_code;
