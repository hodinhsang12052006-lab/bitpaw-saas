/// Model cho 1 bản ghi db.dining_tables (xem GET /api/pos/tables, app.py) — bàn mới seed
/// KHÔNG có field 'status' cho tới khi có đơn gọi món đầu tiên, coi thiếu field này là "Còn
/// trống" để khớp đúng mặc định ngầm định phía backend ($set status chỉ chạy khi có order).
class DiningTableModel {
  final int id;
  final String name;
  final String status;

  DiningTableModel({required this.id, required this.name, required this.status});

  bool get isAvailable => status == 'Còn trống';

  factory DiningTableModel.fromJson(Map<String, dynamic> json) {
    return DiningTableModel(
      id: (json['id'] as num?)?.toInt() ?? 0,
      name: json['name']?.toString() ?? '(Không tên)',
      status: json['status']?.toString() ?? 'Còn trống',
    );
  }
}
