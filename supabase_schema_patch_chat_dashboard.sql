-- ==================================================================================
-- BITPAW OS - CHAT DASHBOARD PATCH (Super Admin: Quản lý khách hàng & Chat)
-- Chạy thủ công trong Supabase Dashboard -> SQL Editor (không tự động chạy).
--
-- KHÔNG tạo bảng `messages` mới: bảng `bot_customers` (1 dòng = 1 cuộc hội thoại) và
-- `bot_messages` (1 dòng = 1 tin nhắn, sender_type IN customer/staff/ai) đã tồn tại sẵn
-- (xem supabase_schema_full.sql) và ĐANG được app.py ghi dữ liệu thật vào mỗi khi khách
-- chat qua widget AI trên Landing Page (_persist_chat_turn(), gọi từ /api/ai/studio/generate).
-- Patch này chỉ bổ sung 2 cột còn thiếu để dựng Tab "Quản lý khách hàng & Chat":
--   1. bot_messages.is_read  — trạng thái đã đọc/chưa đọc cho từng tin nhắn (yêu cầu #2).
--   2. bot_customers.email  — cho phép hiển thị email khách khi có (hiện tại khách vãng
--      lai trên landing page chỉ được định danh bằng SĐT, không phải lúc nào cũng có email).
-- An toàn: chỉ ADD COLUMN IF NOT EXISTS, không đổi/xóa dữ liệu cũ nào.
-- ==================================================================================

ALTER TABLE bot_messages ADD COLUMN IF NOT EXISTS is_read BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE bot_customers ADD COLUMN IF NOT EXISTS email TEXT;

-- Index hỗ trợ đếm nhanh số tin nhắn chưa đọc theo cuộc hội thoại (dùng bởi
-- /api/superadmin/chat/conversations mỗi lần load danh sách).
CREATE INDEX IF NOT EXISTS idx_bot_messages_unread
    ON bot_messages (customer_id)
    WHERE is_read = FALSE AND sender_type = 'customer';
