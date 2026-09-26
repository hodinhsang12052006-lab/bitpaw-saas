// Đã gỡ (không còn dùng): luồng JWT native (đăng nhập trong app native, lưu token bằng
// flutter_secure_storage) bị thay bởi bản WebView (xem lib/screens/webview_screen.dart) —
// đăng nhập nay dùng thẳng session cookie của WebView, giống hệt trình duyệt.
// File giữ lại rỗng (không xoá được do quyền công cụ) thay vì import flutter_secure_storage,
// vì flutter_secure_storage kéo theo package objective_c làm vỡ build Windows khi đường dẫn
// project/user chứa dấu cách (dart-lang/native#2993, chưa có bản vá tính đến 2026-09-25).
