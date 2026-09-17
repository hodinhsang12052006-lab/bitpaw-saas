import 'package:dio/dio.dart';

import '../models/staff_model.dart';
import 'api_service.dart';

/// Kết quả check-in/out — tách riêng khỏi việc throw exception vì lỗi geofence (đứng ngoài
/// bán kính cho phép) là lỗi NGHIỆP VỤ bình thường (khách quên đứng trong tiệm), không phải lỗi
/// hệ thống — màn hình cần hiển thị khác nhau cho 2 trường hợp.
class AttendanceResult {
  final bool success;
  final String message;

  AttendanceResult({required this.success, required this.message});
}

class AttendanceService {
  final ApiService _apiService;

  AttendanceService(this._apiService);

  /// GET /api/staff — danh sách nhân viên của ĐÚNG tenant đang đăng nhập (business_id lấy từ
  /// JWT ở backend, không cần tự truyền). Chỉ trả về nhân viên còn active để chọn chấm công.
  Future<List<StaffModel>> fetchStaffList() async {
    final response = await _apiService.dio.get('/api/staff');
    final data = response.data as Map<String, dynamic>;
    if (data['success'] != true) {
      throw Exception(data['message']?.toString() ?? 'Không tải được danh sách nhân viên.');
    }
    final list = (data['data'] as List<dynamic>? ?? [])
        .map((e) => StaffModel.fromJson(e as Map<String, dynamic>))
        .where((s) => s.isActive)
        .toList();
    return list;
  }

  /// POST /api/chamcong/checkin — backend TỰ so khoảng cách Haversine giữa (lat,lng) gửi lên và
  /// toạ độ chi nhánh đã cấu hình (_enforce_checkin_geofence, bán kính 50m); từ chối nếu vượt —
  /// đây KHÔNG phải lỗi hệ thống, hiển thị nguyên message backend trả về cho người dùng tự hiểu
  /// vì sao (vd "Bạn đang cách chi nhánh X mét, vượt quá phạm vi cho phép").
  Future<AttendanceResult> checkIn({
    required int staffId,
    required double latitude,
    required double longitude,
    String? note,
  }) async {
    return _submit('/api/chamcong/checkin', staffId, latitude, longitude, note: note);
  }

  Future<AttendanceResult> checkOut({
    required int staffId,
    required double latitude,
    required double longitude,
  }) async {
    return _submit('/api/chamcong/checkout', staffId, latitude, longitude);
  }

  Future<AttendanceResult> _submit(
    String path,
    int staffId,
    double latitude,
    double longitude, {
    String? note,
  }) async {
    try {
      final response = await _apiService.dio.post(
        path,
        data: {
          'staff_id': staffId,
          'latitude': latitude,
          'longitude': longitude,
          if (note != null && note.isNotEmpty) 'note': note,
        },
      );
      final data = response.data as Map<String, dynamic>;
      if (data['success'] == true) {
        return AttendanceResult(
          success: true,
          message: path.endsWith('checkin') ? 'Chấm công vào ca thành công!' : 'Chấm công tan ca thành công!',
        );
      }
      return AttendanceResult(success: false, message: data['error']?.toString() ?? 'Chấm công thất bại.');
    } on DioException catch (e) {
      final responseData = e.response?.data;
      if (responseData is Map && responseData['error'] != null) {
        // Lỗi geofence (403) hoặc lỗi nghiệp vụ khác — backend đã soạn sẵn message tiếng Việt
        // rõ ràng (vd "Bạn đang cách chi nhánh quá xa"), hiển thị NGUYÊN VĂN, không tự diễn giải
        // lại kẻo mất thông tin hữu ích cho người dùng.
        return AttendanceResult(success: false, message: responseData['error'].toString());
      }
      if (e.type == DioExceptionType.connectionTimeout ||
          e.type == DioExceptionType.receiveTimeout ||
          e.type == DioExceptionType.connectionError) {
        return AttendanceResult(success: false, message: 'Không thể kết nối tới máy chủ. Vui lòng kiểm tra Internet.');
      }
      return AttendanceResult(success: false, message: 'Đã xảy ra lỗi. Vui lòng thử lại.');
    } catch (e) {
      return AttendanceResult(success: false, message: 'Đã xảy ra lỗi không xác định.');
    }
  }
}
