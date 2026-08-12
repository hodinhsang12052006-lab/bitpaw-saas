import 'package:dio/dio.dart';
import 'package:flutter/material.dart';

import 'storage_service.dart';

/// Cấu hình Dio DUY NHẤT cho toàn app — mọi service gọi API khác (products, orders...) sau này
/// đều dùng lại instance `dio` của class này, không tự tạo Dio() riêng, để Interceptor bên dưới
/// LUÔN áp dụng nhất quán cho mọi request, không sót chỗ nào.
class ApiService {
  /// Chỉ trỏ domain chính đã qua Cloudflare — KHÔNG bao giờ trỏ thẳng *.vercel.app (xem audit
  /// SRE: origin Vercel trần không có Cloudflare WAF/DDoS protection phía trước).
  static const String baseUrl = 'https://bitpawsoftware.com';

  /// GlobalKey điều hướng dùng RIÊNG cho Interceptor — nơi không có BuildContext của 1 màn hình
  /// cụ thể nào cả (lỗi 401 có thể xảy ra khi đang ở BẤT KỲ màn hình nào trong app, không chỉ
  /// LoginScreen), nên phải điều hướng qua NavigatorState toàn cục thay vì Navigator.of(context).
  /// Gán navigatorKey này cho MaterialApp trong main.dart.
  static final GlobalKey<NavigatorState> navigatorKey =
      GlobalKey<NavigatorState>();

  late final Dio dio;
  final StorageService _storage = StorageService();

  ApiService() {
    dio = Dio(
      BaseOptions(
        baseUrl: baseUrl,
        connectTimeout: const Duration(seconds: 15),
        receiveTimeout: const Duration(seconds: 15),
        sendTimeout: const Duration(seconds: 15),
        headers: {'Content-Type': 'application/json'},
      ),
    );

    dio.interceptors.add(
      InterceptorsWrapper(
        // Tự động đính kèm "Authorization: Bearer <JWT>" vào MỌI request gửi đi — không cần mỗi
        // màn hình/service tự nhớ set header này, tránh sót 1 chỗ nào đó quên đính token.
        onRequest: (options, handler) async {
          final token = await _storage.getToken();
          if (token != null && token.isNotEmpty) {
            options.headers['Authorization'] = 'Bearer $token';
          }
          return handler.next(options);
        },

        // Bắt lỗi 401 (token hết hạn / bị thu hồi / sai) TOÀN CỤC — không phải màn hình nào cũng
        // tự check UnauthorizedException, xử lý 1 chỗ duy nhất ở đây là đủ cho mọi API call.
        onError: (DioException error, handler) async {
          final isAuthEndpoint =
              error.requestOptions.path.contains('/api/auth/token');
          final isUnauthorized = error.response?.statusCode == 401;

          // Loại trừ chính endpoint đăng nhập: 401 ở ĐÓ nghĩa là "sai email/mật khẩu" (lỗi
          // nghiệp vụ bình thường, LoginScreen tự hiển thị Snackbar) — KHÔNG phải "phiên hết
          // hạn". Nếu không loại trừ, sẽ tự đá về /login ngay cả khi đang ĐỨNG ở /login gõ sai
          // mật khẩu, gây vòng lặp điều hướng vô nghĩa.
          if (isUnauthorized && !isAuthEndpoint) {
            await _storage.deleteToken();
            navigatorKey.currentState?.pushNamedAndRemoveUntil(
              '/login',
              (route) => false,
            );
          }

          return handler.next(error);
        },
      ),
    );
  }
}
