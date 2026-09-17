import 'package:dio/dio.dart';

import '../models/karaoke_room_model.dart';
import 'api_service.dart';

class KaraokeCheckoutResult {
  final bool success;
  final String message;
  final int? orderId;
  final double? totalAmount;

  KaraokeCheckoutResult({required this.success, required this.message, this.orderId, this.totalAmount});
}

/// Service quản lý phòng Karaoke — mirror /api/karaoke/rooms* (app.py). Backend tự tính tiền
/// theo thời gian mở phòng (làm tròn lên bội 15 phút, tối thiểu 15 phút) khi checkout — mobile
/// KHÔNG tự tính, chỉ hiển thị lại con số backend trả về.
class KaraokeService {
  final ApiService _apiService;

  KaraokeService(this._apiService);

  Future<List<KaraokeRoomModel>> fetchRooms() async {
    final response = await _apiService.dio.get('/api/karaoke/rooms');
    final data = response.data as Map<String, dynamic>;
    if (data['success'] != true) {
      throw Exception(data['message']?.toString() ?? 'Không tải được danh sách phòng.');
    }
    return (data['data'] as List<dynamic>? ?? [])
        .map((e) => KaraokeRoomModel.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// POST .../start — backend lọc atomic theo status='Trống' trong chính update filter, trả
  /// 409 nếu phòng vừa bị người khác mở trước (2 nhân viên cùng bấm Start cùng lúc).
  Future<KaraokeRoomModel> startRoom(int roomId) async {
    try {
      final response = await _apiService.dio.post('/api/karaoke/rooms/$roomId/start');
      final data = response.data as Map<String, dynamic>;
      if (data['success'] != true) {
        throw Exception(data['message']?.toString() ?? 'Không mở được phòng.');
      }
      return KaraokeRoomModel.fromJson(data['data'] as Map<String, dynamic>);
    } on DioException catch (e) {
      final responseData = e.response?.data;
      if (responseData is Map && responseData['message'] != null) {
        throw Exception(responseData['message'].toString());
      }
      rethrow;
    }
  }

  Future<KaraokeCheckoutResult> checkoutRoom(int roomId, {String? customerPhone}) async {
    try {
      final response = await _apiService.dio.post(
        '/api/karaoke/rooms/$roomId/checkout',
        data: {if (customerPhone != null && customerPhone.isNotEmpty) 'customer_phone': customerPhone},
      );
      final data = response.data as Map<String, dynamic>;
      if (data['success'] == true) {
        return KaraokeCheckoutResult(
          success: true,
          message: 'Chốt phòng thành công!',
          orderId: (data['order_id'] as num?)?.toInt(),
          totalAmount: (data['total_amount'] as num?)?.toDouble(),
        );
      }
      return KaraokeCheckoutResult(success: false, message: data['message']?.toString() ?? 'Chốt phòng thất bại.');
    } on DioException catch (e) {
      final responseData = e.response?.data;
      if (responseData is Map && responseData['message'] != null) {
        return KaraokeCheckoutResult(success: false, message: responseData['message'].toString());
      }
      return KaraokeCheckoutResult(success: false, message: 'Không thể kết nối tới máy chủ.');
    }
  }
}
