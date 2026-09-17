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
}
