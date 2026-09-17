import '../models/production_output_model.dart';
import '../models/raw_material_model.dart';
import 'api_service.dart';

class SubmitOutputResult {
  final bool success;
  final String message;
  final List<String> materialWarnings;

  SubmitOutputResult({required this.success, required this.message, this.materialWarnings = const []});
}

/// Service cho ngành Sản xuất — mirror /api/production/output + /api/production/materials
/// (app.py). Ghi nhận sản lượng TỰ ĐỘNG trừ nguyên vật liệu theo công thức khớp tên công đoạn
/// (nếu có) — mobile chỉ gửi input thô, mọi tính toán/trừ kho là phía backend.
class ProductionService {
  final ApiService _apiService;

  ProductionService(this._apiService);

  Future<List<RawMaterialModel>> fetchMaterials() async {
    final response = await _apiService.dio.get('/api/production/materials');
    final data = response.data as Map<String, dynamic>;
    if (data['success'] != true) {
      throw Exception(data['message']?.toString() ?? 'Không tải được tồn kho nguyên vật liệu.');
    }
    return (data['data'] as List<dynamic>? ?? [])
        .map((e) => RawMaterialModel.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<List<ProductionOutputModel>> fetchRecentOutput({String? ngay}) async {
    final response = await _apiService.dio.get(
      '/api/production/output',
      queryParameters: {if (ngay != null) 'ngay': ngay},
    );
    final data = response.data as Map<String, dynamic>;
    if (data['success'] != true) {
      throw Exception(data['message']?.toString() ?? 'Không tải được lịch sử sản lượng.');
    }
    return (data['data'] as List<dynamic>? ?? [])
        .map((e) => ProductionOutputModel.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<SubmitOutputResult> submitOutput({
    required String maNv,
    required String congDoan,
    required int soLuong,
    String? caLam,
    String? ghiChu,
  }) async {
    try {
      final response = await _apiService.dio.post('/api/production/output', data: {
        'ma_nv': maNv,
        'cong_doan': congDoan,
        'so_luong': soLuong,
        if (caLam != null && caLam.isNotEmpty) 'ca_lam': caLam,
        if (ghiChu != null && ghiChu.isNotEmpty) 'ghi_chu': ghiChu,
      });
      final data = response.data as Map<String, dynamic>;
      if (data['success'] == true) {
        return SubmitOutputResult(
          success: true,
          message: 'Đã ghi nhận sản lượng!',
          materialWarnings: (data['material_warnings'] as List<dynamic>? ?? []).map((e) => e.toString()).toList(),
        );
      }
      return SubmitOutputResult(success: false, message: data['message']?.toString() ?? 'Ghi nhận thất bại.');
    } catch (e) {
      return SubmitOutputResult(success: false, message: 'Đã xảy ra lỗi. Vui lòng thử lại.');
    }
  }
}
