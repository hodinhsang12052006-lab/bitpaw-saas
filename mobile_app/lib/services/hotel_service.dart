import 'package:dio/dio.dart';

import '../models/hotel_room_model.dart';
import 'api_service.dart';

class HotelCheckoutResult {
  final bool success;
  final String message;
  final int? orderId;
  final double? totalAmount;
  final int? nights;

  HotelCheckoutResult({required this.success, required this.message, this.orderId, this.totalAmount, this.nights});
}

/// Service quản lý phòng Hotel — mirror /api/hotel/rooms* (app.py). Checkout tính SỐ ĐÊM
/// (không phải số giờ như Karaoke) từ checkin_date tới hiện tại, tối thiểu 1 đêm.
class HotelService {
  final ApiService _apiService;

  HotelService(this._apiService);

  Future<List<HotelRoomModel>> fetchRooms() async {
    final response = await _apiService.dio.get('/api/hotel/rooms');
    final data = response.data as Map<String, dynamic>;
    if (data['success'] != true) {
      throw Exception(data['message']?.toString() ?? 'Không tải được danh sách phòng.');
    }
    return (data['data'] as List<dynamic>? ?? [])
        .map((e) => HotelRoomModel.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<HotelRoomModel> checkIn(int roomId, {required String guestName, String? guestPhone}) async {
    try {
      final response = await _apiService.dio.post(
        '/api/hotel/rooms/$roomId/checkin',
        data: {'guest_name': guestName, if (guestPhone != null && guestPhone.isNotEmpty) 'guest_phone': guestPhone},
      );
      final data = response.data as Map<String, dynamic>;
      if (data['success'] != true) {
        throw Exception(data['message']?.toString() ?? 'Check-in thất bại.');
      }
      return HotelRoomModel.fromJson(data['data'] as Map<String, dynamic>);
    } on DioException catch (e) {
      final responseData = e.response?.data;
      if (responseData is Map && responseData['message'] != null) {
        throw Exception(responseData['message'].toString());
      }
      rethrow;
    }
  }

  Future<HotelCheckoutResult> checkOut(int roomId) async {
    try {
      final response = await _apiService.dio.post('/api/hotel/rooms/$roomId/checkout');
      final data = response.data as Map<String, dynamic>;
      if (data['success'] == true) {
        return HotelCheckoutResult(
          success: true,
          message: 'Trả phòng thành công!',
          orderId: (data['order_id'] as num?)?.toInt(),
          totalAmount: (data['total_amount'] as num?)?.toDouble(),
          nights: (data['nights'] as num?)?.toInt(),
        );
      }
      return HotelCheckoutResult(success: false, message: data['message']?.toString() ?? 'Trả phòng thất bại.');
    } on DioException catch (e) {
      final responseData = e.response?.data;
      if (responseData is Map && responseData['message'] != null) {
        return HotelCheckoutResult(success: false, message: responseData['message'].toString());
      }
      return HotelCheckoutResult(success: false, message: 'Không thể kết nối tới máy chủ.');
    }
  }

  Future<void> markClean(int roomId) async {
    final response = await _apiService.dio.post('/api/hotel/rooms/$roomId/mark_clean');
    final data = response.data as Map<String, dynamic>;
    if (data['success'] != true) {
      throw Exception(data['message']?.toString() ?? 'Đánh dấu dọn phòng thất bại.');
    }
  }
}
