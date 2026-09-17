/// 1 dòng món đã gọi cho 1 bàn — kết quả GET /api/pos/tables/<id>/orders (app.py, đã $lookup
/// sẵn tên/giá sản phẩm phía server, KHÔNG cần tự tra cứu products riêng ở mobile).
class TableOrderItemModel {
  final int id;
  final int productId;
  final String name;
  final double price;
  final int quantity;

  TableOrderItemModel({
    required this.id,
    required this.productId,
    required this.name,
    required this.price,
    required this.quantity,
  });

  double get lineTotal => price * quantity;

  factory TableOrderItemModel.fromJson(Map<String, dynamic> json) {
    return TableOrderItemModel(
      id: (json['id'] as num?)?.toInt() ?? 0,
      productId: (json['product_id'] as num?)?.toInt() ?? 0,
      name: json['name']?.toString() ?? '(Không tên)',
      price: (json['price'] as num?)?.toDouble() ?? 0,
      quantity: (json['quantity'] as num?)?.toInt() ?? 0,
    );
  }
}
