import 'package:dio/dio.dart';

import '../models/cart_item_model.dart';
import 'api_service.dart';

class NailCheckoutResult {
  final bool success;
  final String message;
  final int? orderId;
  final double? totalAmount;

  NailCheckoutResult({required this.success, required this.message, this.orderId, this.totalAmount});
}

/// Checkout riêng cho Nail POS — mirror ĐÚNG payload của POST /api/nail_pos/checkout +
/// _compute_nail_pos_order (app.py): mỗi dòng giỏ hàng có thể gán ma_nv riêng để tính hoa hồng
/// theo thợ, hỗ trợ supply%/discount/tax/tip/split payment. Backend là nguồn tính tiền CHÍNH
/// THỨC (transaction, trừ kho, ghi chamcong) — app di động chỉ gửi input thô, không tự ý tính
/// rồi gửi số đã tính lên (tránh sai lệch làm gian lận/lỗi khó dò).
class NailPosService {
  final ApiService _apiService;

  NailPosService(this._apiService);

  Future<NailCheckoutResult> checkout({
    required List<CartItemModel> items,
    required String paymentMethod,
    double supplyPercent = 0,
    String discountType = 'none',
    double discountValue = 0,
    double taxPercent = 0,
    double cashTip = 0,
    double cardTip = 0,
    double ccFeePercent = 0,
    double? splitCashAmount,
    double? splitCardAmount,
    String? customerPhone,
  }) async {
    final payload = {
      'items': items
          .map((it) => {
                if (it.productId != null) 'product_id': it.productId,
                if (it.productId == null) 'custom_name': it.name,
                if (it.productId == null) 'custom_price': it.price,
                'quantity': it.quantity,
                if (it.assignedMaNv != null) 'ma_nv': it.assignedMaNv,
              })
          .toList(),
      'payment_method': paymentMethod,
      'supply_percent': supplyPercent,
      'discount_type': discountType,
      'discount_value': discountValue,
      'tax_percent': taxPercent,
      'cash_tip': cashTip,
      'card_tip': cardTip,
      'cc_fee_percent': ccFeePercent,
      if (splitCashAmount != null) 'cash_amount': splitCashAmount,
      if (splitCardAmount != null) 'card_amount': splitCardAmount,
      if (customerPhone != null && customerPhone.isNotEmpty) 'customer_phone': customerPhone,
    };

    try {
      final response = await _apiService.dio.post('/api/nail_pos/checkout', data: payload);
      final data = response.data as Map<String, dynamic>;
      if (data['success'] == true) {
        return NailCheckoutResult(
          success: true,
          message: 'Thanh toán thành công!',
          orderId: (data['order_id'] as num?)?.toInt(),
          totalAmount: (data['total_amount'] as num?)?.toDouble(),
        );
      }
      return NailCheckoutResult(success: false, message: data['message']?.toString() ?? 'Thanh toán thất bại.');
    } on DioException catch (e) {
      final responseData = e.response?.data;
      if (responseData is Map && responseData['message'] != null) {
        return NailCheckoutResult(success: false, message: responseData['message'].toString());
      }
      if (e.type == DioExceptionType.connectionError ||
          e.type == DioExceptionType.connectionTimeout ||
          e.type == DioExceptionType.receiveTimeout) {
        return NailCheckoutResult(success: false, message: 'Không thể kết nối tới máy chủ. Vui lòng kiểm tra Internet.');
      }
      return NailCheckoutResult(success: false, message: 'Đã xảy ra lỗi. Vui lòng thử lại.');
    } catch (e) {
      return NailCheckoutResult(success: false, message: 'Đã xảy ra lỗi không xác định.');
    }
  }
}
