/// Model cho db.tasks (xem GET /api/tasks, app.py) — job điều phối Kỹ Thuật. Backend KHÔNG ép
/// schema cố định (route create nhận thẳng bất kỳ field nào client gửi), nhưng chamcong_kythuat.html
/// dùng nhất quán các field dưới đây — model chỉ đọc đúng những field đó, field lạ khác bỏ qua an toàn.
class JobTaskModel {
  final int id;
  final String tenKhach;
  final String diaChi;
  final String noiDung;
  final String trangThai;
  final String? nguoiNhan;

  JobTaskModel({
    required this.id,
    required this.tenKhach,
    required this.diaChi,
    required this.noiDung,
    required this.trangThai,
    this.nguoiNhan,
  });

  factory JobTaskModel.fromJson(Map<String, dynamic> json) {
    return JobTaskModel(
      id: (json['id'] as num?)?.toInt() ?? 0,
      tenKhach: json['ten_khach']?.toString() ?? '(Không tên)',
      diaChi: json['dia_chi']?.toString() ?? '',
      noiDung: json['noi_dung']?.toString() ?? '',
      trangThai: json['trang_thai']?.toString() ?? 'Chờ Nhận',
      nguoiNhan: json['nguoi_nhan']?.toString(),
    );
  }
}
