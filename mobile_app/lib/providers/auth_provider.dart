import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';

import '../models/user_model.dart';
import '../services/api_service.dart';
import '../services/storage_service.dart';

enum AuthStatus { unknown, authenticated, unauthenticated }

/// State quản lý toàn bộ luồng đăng nhập — UI (LoginScreen/SplashScreen) chỉ đọc
/// isLoading/errorMessage/status qua Provider, KHÔNG tự gọi Dio trực tiếp.
class AuthProvider extends ChangeNotifier {
  final ApiService _apiService;
  final StorageService _storage = StorageService();

  AuthProvider(this._apiService);

  AuthStatus _status = AuthStatus.unknown;
  UserModel? _user;
  bool _isLoading = false;
  String? _errorMessage;

  AuthStatus get status => _status;
  UserModel? get user => _user;
  bool get isLoading => _isLoading;
  String? get errorMessage => _errorMessage;

  /// Gọi lúc khởi động app (SplashScreen) — CHỈ kiểm tra có token lưu sẵn hay không, KHÔNG gọi
  /// API xác thực lại token đó (giữ splash screen nhanh, offline-friendly). Nếu token thực ra đã
  /// hết hạn, request API đầu tiên trong HomeScreen sẽ tự nhận 401 và Interceptor tự đá về Login.
  Future<void> checkAuthStatus() async {
    final hasToken = await _storage.hasToken();
    _status = hasToken ? AuthStatus.authenticated : AuthStatus.unauthenticated;
    notifyListeners();
  }

  Future<bool> login(String email, String password) async {
    _isLoading = true;
    _errorMessage = null;
    notifyListeners();

    try {
      final response = await _apiService.dio.post(
        '/api/auth/token',
        data: {'email': email, 'password': password},
      );

      final data = response.data as Map<String, dynamic>;
      if (data['success'] == true) {
        final token = data['access_token'] as String;
        await _storage.saveToken(token);
        _user = UserModel.fromJson(data['user'] as Map<String, dynamic>);
        _status = AuthStatus.authenticated;
        return true;
      }

      _errorMessage = data['message']?.toString() ?? 'Đăng nhập thất bại.';
      _status = AuthStatus.unauthenticated;
      return false;
    } on DioException catch (e) {
      _errorMessage = _messageFromDioException(e);
      _status = AuthStatus.unauthenticated;
      return false;
    } catch (e) {
      _errorMessage = 'Đã xảy ra lỗi không xác định. Vui lòng thử lại.';
      _status = AuthStatus.unauthenticated;
      return false;
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  Future<void> logout() async {
    await _storage.deleteToken();
    _user = null;
    _status = AuthStatus.unauthenticated;
    notifyListeners();
  }

  /// Gom mọi kiểu lỗi Dio (network chết, timeout, backend trả lỗi có message riêng...) thành 1
  /// câu tiếng Việt rõ ràng để hiển thị Snackbar — người dùng cuối không cần thấy
  /// "DioExceptionType.connectionError" hay stack trace kỹ thuật.
  String _messageFromDioException(DioException e) {
    final responseData = e.response?.data;
    if (responseData is Map && responseData['message'] != null) {
      return responseData['message'].toString();
    }
    switch (e.type) {
      case DioExceptionType.connectionTimeout:
      case DioExceptionType.sendTimeout:
      case DioExceptionType.receiveTimeout:
        return 'Kết nối tới máy chủ quá thời gian. Vui lòng kiểm tra mạng và thử lại.';
      case DioExceptionType.connectionError:
        return 'Không thể kết nối tới máy chủ. Vui lòng kiểm tra Internet.';
      case DioExceptionType.badCertificate:
        return 'Kết nối không an toàn bị từ chối. Vui lòng thử lại sau.';
      default:
        return 'Đã xảy ra lỗi. Vui lòng thử lại sau ít phút.';
    }
  }
}
