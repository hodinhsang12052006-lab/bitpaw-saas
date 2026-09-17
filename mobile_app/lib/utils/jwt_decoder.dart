import 'dart:convert';

/// Giải mã (KHÔNG xác thực chữ ký) phần payload của JWT — chỉ dùng để đọc claim (role,
/// business_id...) cho mục đích HIỂN THỊ UI (vd ẩn/hiện tab Báo cáo). Việc xác thực chữ ký/hạn
/// dùng thật sự luôn nằm ở backend (mọi API vẫn tự kiểm tra qua @role_required), token giả mạo
/// tối đa chỉ đánh lừa được UI cục bộ, không gọi được API thật vì thiếu chữ ký hợp lệ.
Map<String, dynamic>? decodeJwtPayload(String token) {
  try {
    final parts = token.split('.');
    if (parts.length != 3) return null;
    var payloadSegment = parts[1];
    // base64Url yêu cầu độ dài chia hết cho 4 — JWT chuẩn bỏ padding '=', phải tự bù lại.
    payloadSegment += '=' * ((4 - payloadSegment.length % 4) % 4);
    final decoded = utf8.decode(base64Url.decode(payloadSegment));
    return jsonDecode(decoded) as Map<String, dynamic>;
  } catch (e) {
    return null;
  }
}
