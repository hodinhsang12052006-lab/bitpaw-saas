/// Model tương ứng 1 bản ghi trong GET /api/staff (xem app.py) — db.staff, dùng bởi luồng
/// chấm công GPS (/api/chamcong/checkin|checkout nhận staff_id là id NGUYÊN của bảng này,
/// KHÔNG phải ma_nv chuỗi của db.employees — 2 hệ thống nhân sự khác nhau trong backend).
class StaffModel {
  final int id;
  final String name;
  final bool isActive;

  StaffModel({required this.id, required this.name, this.isActive = true});

  factory StaffModel.fromJson(Map<String, dynamic> json) {
    return StaffModel(
      id: json['id'] is int
          ? json['id'] as int
          : int.tryParse(json['id']?.toString() ?? '') ?? 0,
      name: json['name']?.toString() ?? '(Không tên)',
      isActive: json['is_active'] != false,
    );
  }
}
