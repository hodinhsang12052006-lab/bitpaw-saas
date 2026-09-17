import 'package:dio/dio.dart';

import '../models/cart_item_model.dart';
import 'api_service.dart';

class SalesCheckoutResult {
  final bool success;
  final String message;
  final int? orderId;
  final double? totalAmount;

  SalesCheckoutResult({required this.success, required this.message, this.orderId, this.totalAmount});
}

/// Checkout dùng chung cho ngành KHÔNG gán thợ theo từng dòng (Spa, Retail đơn giản) — mirror
/// POST /api/sales/checkout + _compute_cart_order (app.py). Khác Nail POS: staff_id (nếu có)
/// áp dụng cho CẢ đơn (1 thợ/1 bill), dùng db.staff (khoá id nguyên) chứ KHÔNG phải db.employees
/// (ma_nv) — 2 hệ thống nhân sự khác nhau trong backend, xem staff_model.dart.
class SalesCheckoutService {
  final ApiService _apiService;

  SalesCheckoutService(this._apiService);

  Future<SalesCheckoutResult> checkout({
    required List<CartItemModel> items,
    required String paymentMethod,
    int? staffId,
    double? commissionRate,
    double tipAmount = 0,
    String? customerPhone,
  }) async {
    final payload = {
      'items': items
          .map((it) => {
                'product_id': it.productId,
                'quantity': it.quantity,
              })
          .toList(),
      'payment_method': paymentMethod,
      'tip_amount': tipAmount,
      if (staffId != null) 'staff_id': staffId,
      if (commissionRate != null) 'commission_rate': commissionRate,
      if (customerPhone != null && customerPhone.isNotEmpty) 'customer_phone': customerPhone,
    };

    try {
      final response = await _apiService.dio.post('/api/sales/checkout', data: payload);
      final data = response.data as Map<String, dynamic>;
      if (data['success'] == true) {
        return SalesCheckoutResult(
          success: true,
          message: 'Thanh toán thành công!',
          orderId: (data['order_id'] as num?)?.toInt(),
          totalAmount: (data['total_amount'] as num?)?.toDouble(),
        );
      }
      return SalesCheckoutResult(success: false, message: data['message']?.toString() ?? 'Thanh toán thất bại.');
    } on DioException catch (e) {
      final responseData = e.response?.data;
      if (responseData is Map && responseData['message'] != null) {
        return SalesCheckoutResult(success: false, message: responseData['message'].toString());
      }
      if (e.type == DioExceptionType.connectionError ||
          e.type == DioExceptionType.connectionTimeout ||
          e.type == DioExceptionType.receiveTimeout) {
        return SalesCheckoutResult(success: false, message: 'Không thể kết nối tới máy chủ. Vui lòng kiểm tra Internet.');
      }
      return SalesCheckoutResult(success: false, message: 'Đã xảy ra lỗi. Vui lòng thử lại.');
    } catch (e) {
      return SalesCheckoutResult(success: false, message: 'Đã xảy ra lỗi không xác định.');
    }
  }
}
