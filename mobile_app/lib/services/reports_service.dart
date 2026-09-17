import '../models/dashboard_stats_model.dart';
import 'api_service.dart';

class ReportsService {
  final ApiService _apiService;

  ReportsService(this._apiService);

  /// GET /api/dashboard/stats — chỉ role admin/super_admin gọi được (backend tự chặn 403 với
  /// role khác, ReportsScreen không hiện tab này cho staff nhưng vẫn giữ chặn ở tầng API làm
  /// lớp bảo vệ thật sự, UI chỉ là tiện lợi hiển thị).
  Future<DashboardStats> fetchStats({int? month, int? year}) async {
    final now = DateTime.now();
    final response = await _apiService.dio.get(
      '/api/dashboard/stats',
      queryParameters: {
        'month': (month ?? now.month).toString().padLeft(2, '0'),
        'year': (year ?? now.year).toString(),
      },
    );
    final data = response.data as Map<String, dynamic>;
    if (data['success'] != true) {
      throw Exception(data['message']?.toString() ?? 'Không tải được báo cáo.');
    }
    return DashboardStats.fromJson(data);
  }
}
