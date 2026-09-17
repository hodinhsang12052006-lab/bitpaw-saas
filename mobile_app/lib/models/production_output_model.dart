/// Model cho db.production_output (xem GET /api/production/output, app.py) — 1 lần ghi nhận
/// sản lượng của 1 công nhân cho 1 công đoạn/sản phẩm trong ngày.
class ProductionOutputModel {
  final int id;
  final String maNv;
  final String hoTen;
  final String congDoan;
  final int soLuong;
  final String ngay;
  final String? caLam;
  final String? ghiChu;

  ProductionOutputModel({
    required this.id,
    required this.maNv,
    required this.hoTen,
    required this.congDoan,
    required this.soLuong,
    required this.ngay,
    this.caLam,
    this.ghiChu,
  });

  factory ProductionOutputModel.fromJson(Map<String, dynamic> json) {
    return ProductionOutputModel(
      id: (json['id'] as num?)?.toInt() ?? 0,
      maNv: json['ma_nv']?.toString() ?? '',
      hoTen: json['ho_ten']?.toString() ?? '',
      congDoan: json['cong_doan']?.toString() ?? '',
      soLuong: (json['so_luong'] as num?)?.toInt() ?? 0,
      ngay: json['ngay']?.toString() ?? '',
      caLam: json['ca_lam']?.toString(),
      ghiChu: json['ghi_chu']?.toString(),
    );
  }
}
