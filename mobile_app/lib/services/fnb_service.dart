import 'package:dio/dio.dart';

import '../models/dining_table_model.dart';
import '../models/table_order_item_model.dart';
import 'api_service.dart';

class CheckoutTableResult {
  final bool success;
  final String message;
  final int? orderId;
  final double? totalAmount;

  CheckoutTableResult({required this.success, required this.message, this.orderId, this.totalAmount});
}

/// Service cho luồng F&B: bàn -> gọi món -> thanh toán — mirror đúng /api/pos/tables/* +
/// GET /checkout/<table_id> (app.py). checkout_table() vốn là route web (redirect) nhưng backend
/// đã hỗ trợ sẵn trả JSON khi _wants_json() đúng, và request JWT Bearer từ mobile LUÔN thoả điều
/// kiện đó (g.auth_via_jwt) — không cần header Accept đặc biệt.
class FnbService {
  final ApiService _apiService;

  FnbService(this._apiService);

  Future<List<DiningTableModel>> fetchTables() async {
    final response = await _apiService.dio.get('/api/pos/tables');
    final data = response.data as Map<String, dynamic>;
    if (data['success'] != true) {
      throw Exception(data['message']?.toString() ?? 'Không tải được danh sách bàn.');
    }
    return (data['data'] as List<dynamic>? ?? [])
        .map((e) => DiningTableModel.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<List<TableOrderItemModel>> fetchTableOrders(int tableId) async {
    final response = await _apiService.dio.get('/api/pos/tables/$tableId/orders');
    final data = response.data as Map<String, dynamic>;
    if (data['success'] != true) {
      throw Exception(data['message']?.toString() ?? 'Không tải được món đã gọi.');
    }
    return (data['data'] as List<dynamic>? ?? [])
        .map((e) => TableOrderItemModel.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<void> addOrderItem(int tableId, int productId, {int quantity = 1}) async {
    final response = await _apiService.dio.post(
      '/api/pos/tables/$tableId/orders',
      data: {'product_id': productId, 'quantity': quantity},
    );
    final data = response.data as Map<String, dynamic>;
    if (data['success'] != true) {
      throw Exception(data['message']?.toString() ?? 'Gọi món thất bại.');
    }
  }

  Future<void> removeOrderItem(int itemId) async {
    final response = await _apiService.dio.delete('/api/pos/order_items/$itemId');
    final data = response.data as Map<String, dynamic>;
    if (data['success'] != true) {
      throw Exception(data['message']?.toString() ?? 'Xoá món thất bại.');
    }
  }

  Future<CheckoutTableResult> checkoutTable(int tableId) async {
    try {
      final response = await _apiService.dio.get('/checkout/$tableId');
      final data = response.data as Map<String, dynamic>;
      if (data['success'] == true) {
        return CheckoutTableResult(
          success: true,
          message: (data['order_id'] == null) ? (data['message']?.toString() ?? 'Bàn không có món nào.') : 'Thanh toán thành công!',
          orderId: (data['order_id'] as num?)?.toInt(),
          totalAmount: (data['total_amount'] as num?)?.toDouble(),
        );
      }
      return CheckoutTableResult(success: false, message: data['message']?.toString() ?? 'Thanh toán thất bại.');
    } on DioException catch (e) {
      final responseData = e.response?.data;
      if (responseData is Map && responseData['message'] != null) {
        return CheckoutTableResult(success: false, message: responseData['message'].toString());
      }
      return CheckoutTableResult(success: false, message: 'Không thể kết nối tới máy chủ.');
    }
  }
}
