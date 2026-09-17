import 'dart:typed_data';

import 'package:dio/dio.dart';

import '../models/job_task_model.dart';
import 'api_service.dart';

class PartUsed {
  final String name;
  final double qty;
  final double unitPrice;

  PartUsed({required this.name, required this.qty, required this.unitPrice});

  Map<String, dynamic> toJson() => {'name': name, 'qty': qty, 'unit_price': unitPrice};
}

class CompleteJobResult {
  final bool success;
  final String message;
  final int? orderId;

  CompleteJobResult({required this.success, required this.message, this.orderId});
}

/// Service điều phối job Kỹ Thuật — mirror /api/tasks* + /api/storage/upload (app.py). `worker`
/// khớp CHÍNH XÁC field `nguoi_nhan`/tham số backend dùng, vốn là TÊN kỹ thuật viên (ho_ten),
/// KHÔNG phải ma_nv — khớp đúng cách chamcong_kythuat.html (web) đang gọi
/// `?worker=${workerName}`, không phải mã nhân viên.
class TechnicalJobService {
  final ApiService _apiService;

  TechnicalJobService(this._apiService);

  Future<List<JobTaskModel>> fetchJobsForWorker(String workerName) async {
    final response = await _apiService.dio.get('/api/tasks', queryParameters: {'worker': workerName});
    final data = response.data as Map<String, dynamic>;
    if (data['success'] != true) {
      throw Exception(data['error']?.toString() ?? 'Không tải được danh sách công việc.');
    }
    return (data['data'] as List<dynamic>? ?? [])
        .map((e) => JobTaskModel.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<void> acceptJob(int taskId, String workerName) async {
    final response = await _apiService.dio.patch(
      '/api/tasks/$taskId',
      data: {'trang_thai': 'Đã Nhận', 'nguoi_nhan': workerName},
    );
    final data = response.data as Map<String, dynamic>;
    if (data['success'] != true) {
      throw Exception(data['error']?.toString() ?? 'Nhận việc thất bại.');
    }
  }

  /// Upload ảnh/chữ ký lên GridFS qua multipart — trả về URL nội bộ (/api/storage/file/<id>)
  /// để nhúng vào photo_urls/signature_url khi gọi completeJob().
  Future<String> uploadImage(Uint8List bytes, String filename, String kind) async {
    final formData = FormData.fromMap({
      'file': MultipartFile.fromBytes(bytes, filename: filename),
      'kind': kind,
    });
    final response = await _apiService.dio.post('/api/storage/upload', data: formData);
    final data = response.data as Map<String, dynamic>;
    if (data['success'] != true) {
      throw Exception(data['error']?.toString() ?? 'Tải ảnh lên thất bại.');
    }
    return data['url'].toString();
  }

  Future<CompleteJobResult> completeJob(
    int taskId,
    String workerName, {
    required List<String> photoUrls,
    String? signatureUrl,
    required List<PartUsed> partsUsed,
  }) async {
    try {
      // PATCH trạng thái trước — theo đúng thiết kế backend, /complete CHỈ đính kèm bằng
      // chứng/phụ tùng, KHÔNG tự đổi trang_thai (xem docstring api_tasks_complete, app.py).
      await _apiService.dio.patch('/api/tasks/$taskId', data: {'trang_thai': 'Hoàn Thành', 'nguoi_nhan': workerName});
      final response = await _apiService.dio.post(
        '/api/tasks/$taskId/complete',
        data: {
          'photo_urls': photoUrls,
          if (signatureUrl != null) 'signature_url': signatureUrl,
          'parts_used': partsUsed.map((p) => p.toJson()).toList(),
        },
      );
      final data = response.data as Map<String, dynamic>;
      if (data['success'] == true) {
        return CompleteJobResult(success: true, message: 'Đã hoàn thành công việc!', orderId: (data['order_id'] as num?)?.toInt());
      }
      return CompleteJobResult(success: false, message: data['message']?.toString() ?? 'Hoàn thành công việc thất bại.');
    } on DioException catch (e) {
      final responseData = e.response?.data;
      if (responseData is Map && (responseData['message'] ?? responseData['error']) != null) {
        return CompleteJobResult(success: false, message: (responseData['message'] ?? responseData['error']).toString());
      }
      return CompleteJobResult(success: false, message: 'Không thể kết nối tới máy chủ.');
    }
  }
}
