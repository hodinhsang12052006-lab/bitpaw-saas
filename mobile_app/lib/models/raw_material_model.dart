/// Model cho db.raw_materials (xem GET /api/production/materials, app.py) — tồn kho nguyên vật
/// liệu, tự trừ theo công thức mỗi khi ghi nhận sản lượng (_consume_recipe_materials). Tồn kho
/// CHO PHÉP âm (khác sản phẩm bán ở POS) — âm nghĩa là cần nhập thêm gấp, không chặn ghi nhận.
class RawMaterialModel {
  final int id;
  final String name;
  final double stockQty;
  final String unit;

  RawMaterialModel({required this.id, required this.name, required this.stockQty, required this.unit});

  bool get isLow => stockQty < 0;

  factory RawMaterialModel.fromJson(Map<String, dynamic> json) {
    return RawMaterialModel(
      id: (json['id'] as num?)?.toInt() ?? 0,
      name: json['name']?.toString() ?? '(Không tên)',
      stockQty: (json['stock_qty'] as num?)?.toDouble() ?? 0,
      unit: json['unit']?.toString() ?? '',
    );
  }
}
