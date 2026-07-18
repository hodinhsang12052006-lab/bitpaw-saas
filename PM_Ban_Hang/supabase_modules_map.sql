-- ==================================================================================
-- BITPAW OS - TEMPLATE REGISTRY & MODULE CORRELATION MAPPINGS
-- Target Engine: PostgreSQL 15+ / Supabase compatible
-- ==================================================================================

-- ----------------------------------------------------------------------------------
-- 1. SEED MODULE FEATURES MAPPINGS (Mục lục các tính năng chi tiết)
-- ----------------------------------------------------------------------------------
INSERT INTO feature_registry (code, name, module_code, is_active, description) VALUES
('pos_fnb', 'Màn hình Gọi món POS', 'ordering', true, 'POS gọi món sơ đồ bàn cho nhà hàng'),
('qr_dining', 'Gọi món tại bàn QR', 'ordering', true, 'Khách quét mã đặt món tự động'),
('KT_checkin', 'Điểm danh hiện trường KTV', 'attendance', true, 'KTV check-in GPS ngoài thực địa'),
('cc_vanphong', 'Điểm danh hành chính', 'attendance', true, 'Chấm công văn phòng vân tay thẻ từ'),
('ktv_alloc', 'Điều phối KTV Spa', 'spa_services', true, 'Phân bổ thợ phục vụ liệu trình theo thứ tự'),
('timing_auto', 'Bắt đầu tính giờ tự động', 'room_timing', true, 'Tính tiền giờ tự động cho phòng Karaoke'),
('ds_generate', 'Đúc kịch bản DeepSeek', 'ai_studio', true, 'Trình tạo kịch bản video viral DeepSeek AI'),
('cskh_live', 'Zalo Live Chat hỗ trợ', 'cskh', true, 'Khung chat hỗ trợ 24/7 trực tuyến')
ON CONFLICT (code) DO UPDATE SET 
    name = EXCLUDED.name, module_code = EXCLUDED.module_code, is_active = EXCLUDED.is_active, description = EXCLUDED.description;

-- ----------------------------------------------------------------------------------
-- 2. SEED TEMPLATE VIEW METADATA REGISTRY (Chi tiết cấu trúc file HTML)
-- ----------------------------------------------------------------------------------
INSERT INTO template_registry (template_name, file_path, display_name, description, module_code, required_permission, is_active, sort_order) VALUES
('dashboard.html', 'templates/dashboard.html', 'Bảng Tổng Quan Bán Lẻ', 'Báo cáo doanh số bán lẻ, chi phí vận hành và lợi nhuận', 'dashboard', 'view_dashboard', true, 1),
('pos.html', 'templates/pos.html', 'Smart POS Ăn Uống', 'Màn hình POS sơ đồ bàn phục vụ nhà hàng & cafe F&B', 'ordering', 'view_pos', true, 2),
('qr_menu.html', 'templates/qr_menu.html', 'Thực Đơn QR Tự Phục Vụ', 'Menu tự gọi món quét QR cho thực khách tại bàn', 'ordering', 'view_pos', true, 3),
('booking.html', 'templates/booking.html', 'Cổng Đặt Lịch Làm Đẹp', 'Cổng khách hàng tự đặt chỗ làm liệu trình Spa trực tuyến', 'online_booking', 'manage_bookings', true, 4),
('spa.html', 'templates/spa.html', 'Trạm Bán Liệu Trình Spa', 'Màn hình bán hàng liệu trình spa, chỉ định KTV phục vụ', 'spa_services', 'view_spa', true, 5),
('karaoke.html', 'templates/karaoke.html', 'Trạm Quản Lý Phòng Hát', 'Bảng tính tiền giờ tự động phòng hát bida bida karaoke', 'room_timing', 'view_karaoke', true, 6),
('chamcong_fnb.html', 'templates/chamcong_fnb.html', 'Điểm Danh Nhân Viên F&B', 'Check-in chấm ca làm việc cho thợ bếp phục vụ nhà hàng', 'attendance', 'clock_in', true, 10),
('chamcong_spa.html', 'templates/chamcong_spa.html', 'Điểm Danh KTV Spa', 'Check-in ca làm việc của kỹ thuật viên massage trị liệu', 'attendance', 'clock_in', true, 11),
('chamcong_nail.html', 'templates/chamcong_nail.html', 'Điểm Danh Thợ Nails', 'Check-in ca làm việc cho thợ làm móng nails salon', 'attendance', 'clock_in', true, 12),
('chamcong_khachsan.html', 'templates/chamcong_khachsan.html', 'Điểm Danh Lễ Tân Khách Sạn', 'Check-in điểm danh ca buồng phòng khách sạn homestay', 'attendance', 'clock_in', true, 13),
('chamcong_congnhan.html', 'templates/chamcong_congnhan.html', 'Điểm Danh Xưởng Sản Xuất', 'Chấm công check-in và khai báo sản lượng công nhân', 'attendance', 'clock_in', true, 14),
('chamcong_kythuat.html', 'templates/chamcong_kythuat.html', 'Điểm Danh GPS Hiện Trường', 'Chấm công định vị tọa độ GPS KTV bảo trì thực địa', 'attendance', 'clock_in', true, 15),
('chamcong_vanphong.html', 'templates/chamcong_vanphong.html', 'Điểm Danh Văn Phòng', 'Chấm công hành chính giờ giấc khối văn phòng doanh nghiệp', 'attendance', 'clock_in', true, 16),
('nhanvien.html', 'templates/nhanvien.html', 'Danh Sách Hồ Sơ Thợ', 'Lưu trữ thông tin liên hệ và tỷ lệ ăn chia hoa hồng', 'payroll', 'view_office', true, 20),
('bangluong.html', 'templates/bangluong.html', 'Bảng Kết Toán Tính Lương', 'Tính lương tự động cộng hoa hồng trừ phạt chuyên cần', 'payroll', 'view_office', true, 21),
('ai_bot.html', 'templates/ai_bot.html', 'AI Copilot Assistant', 'Trợ lý ảo AI tư vấn kịch bản tăng số chat realtime', 'ai_bot', 'view_dashboard', true, 30),
('ai-studio.html', 'templates/ai-studio.html', 'AI Marketing Content Studio', 'Xưởng sản xuất kịch bản TikTok Hook A/B tiêu đề viral', 'ai_studio', 'view_dashboard', true, 31)
ON CONFLICT (template_name) DO UPDATE SET 
    display_name = EXCLUDED.display_name, description = EXCLUDED.description, module_code = EXCLUDED.module_code, required_permission = EXCLUDED.required_permission, sort_order = EXCLUDED.sort_order;
