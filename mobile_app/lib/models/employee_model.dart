/// Model cho 1 bản ghi db.employees (xem GET /api/hr/employees, app.py) — hệ thống nhân sự
/// dùng ma_nv (chuỗi) làm khoá, KHÁC với StaffModel (db.staff, khoá id nguyên) dùng cho chấm
/// công GPS. Nail POS gán thợ theo TỪNG dòng dịch vụ bằng ma_nv của bảng này, lọc theo
/// linh_vuc để chỉ hiện đúng thợ thuộc ngành đang thao tác (vd chỉ thợ 'Nails' trong Nail POS).
class EmployeeModel {
  final String maNv;
  final String hoTen;
  final String? linhVuc;

  EmployeeModel({required this.maNv, required this.hoTen, this.linhVuc});

  factory EmployeeModel.fromJson(Map<String, dynamic> json) {
    return EmployeeModel(
      maNv: json['ma_nv']?.toString() ?? '',
      hoTen: json['ho_ten']?.toString() ?? '(Không tên)',
      linhVuc: json['linh_vuc']?.toString(),
    );
  }
}
