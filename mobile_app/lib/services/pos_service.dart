import 'package:dio/dio.dart';

import '../models/employee_model.dart';
import '../models/product_model.dart';
import 'api_service.dart';

/// Service dùng CHUNG cho mọi màn POS theo ngành (Nails/Spa/Retail...) — chỉ 2 việc đọc dữ liệu
/// nền tảng, logic tính tiền/checkout riêng cho từng ngành nằm ở service riêng (vd
/// nail_pos_service.dart) vì công thức khác nhau đáng kể giữa các ngành.
class PosService {
  final ApiService _apiService;

  PosService(this._apiService);

  /// GET /api/inventory/products — trả về TOÀN BỘ sản phẩm/dịch vụ đang active của tenant,
  /// đúng nguồn dữ liệu route /sell (web) dùng để render lưới dịch vụ Nail POS.
  Future<List<ProductModel>> fetchProducts() async {
    final response = await _apiService.dio.get('/api/inventory/products');
    final data = response.data as Map<String, dynamic>;
    if (data['success'] != true) {
      throw Exception(data['message']?.toString() ?? 'Không tải được danh sách sản phẩm/dịch vụ.');
    }
    return (data['data'] as List<dynamic>? ?? [])
        .map((e) => ProductModel.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// GET /api/hr/employees — trả về TOÀN BỘ nhân viên của tenant (mọi linh_vuc trộn lẫn) —
  /// caller tự lọc theo linh_vuc phù hợp (vd 'Nails') vì backend không hỗ trợ filter theo field
  /// này, giống hệt cách route /sell (web) lọc bằng Python trước khi render.
  Future<List<EmployeeModel>> fetchEmployees() async {
    final response = await _apiService.dio.get('/api/hr/employees');
    final data = response.data as Map<String, dynamic>;
    if (data['success'] != true) {
      throw Exception(data['error']?.toString() ?? 'Không tải được danh sách nhân viên.');
    }
    return (data['data'] as List<dynamic>? ?? [])
        .map((e) => EmployeeModel.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// GET /api/products/lookup_barcode — tra sản phẩm theo mã vạch quét được (màn Retail POS).
  /// Trả về null nếu không tìm thấy (404) — không phải lỗi hệ thống, caller tự hiển thị
  /// "Không tìm thấy sản phẩm" thay vì coi là exception.
  Future<ProductModel?> lookupBarcode(String barcode) async {
    try {
      final response = await _apiService.dio.get(
        '/api/products/lookup_barcode',
        queryParameters: {'barcode': barcode},
      );
      final data = response.data as Map<String, dynamic>;
      if (data['success'] == true) {
        return ProductModel.fromJson(data['data'] as Map<String, dynamic>);
      }
      return null;
    } on DioException catch (e) {
      if (e.response?.statusCode == 404) return null;
      rethrow;
    }
  }
}
