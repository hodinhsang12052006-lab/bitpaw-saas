/// 1 dòng trong giỏ hàng POS — hoặc gắn với 1 ProductModel có sẵn (productId != null), hoặc là
/// dòng "Thêm mục tuỳ chỉnh" cashier tự nhập tên/giá tại quầy (productId == null), khớp đúng 2
/// nhánh xử lý trong _compute_nail_pos_order (app.py). assignedMaNv chỉ dùng cho ngành có gán
/// thợ theo dòng (Nails) — ngành khác luôn để null.
class CartItemModel {
  final int? productId;
  final String name;
  final double price;
  int quantity;
  String? assignedMaNv;
  String? assignedTechName;

  CartItemModel({
    this.productId,
    required this.name,
    required this.price,
    this.quantity = 1,
    this.assignedMaNv,
    this.assignedTechName,
  });

  double get lineTotal => price * quantity;
}
