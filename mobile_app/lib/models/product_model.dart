/// Model cho 1 bản ghi db.products (xem GET /api/inventory/products, app.py) — dùng chung cho
/// mọi ngành có bán hàng/dịch vụ tại quầy (Nails, Spa, Retail...). Field 'stock' chỉ tồn tại ở
/// sản phẩm vật lý có theo dõi tồn kho (dịch vụ thuần Nails/Spa thường không có field này).
class ProductModel {
  final int id;
  final String name;
  final String? category;
  final double price;
  final String? image;
  final int? stock;
  final String? barcode;
  final String? channelType;

  ProductModel({
    required this.id,
    required this.name,
    required this.price,
    this.category,
    this.image,
    this.stock,
    this.barcode,
    this.channelType,
  });

  factory ProductModel.fromJson(Map<String, dynamic> json) {
    return ProductModel(
      id: (json['id'] as num?)?.toInt() ?? 0,
      name: json['name']?.toString() ?? '(Không tên)',
      category: json['category']?.toString(),
      price: (json['price'] as num?)?.toDouble() ?? 0,
      image: json['image']?.toString(),
      stock: json['stock'] == null ? null : (json['stock'] as num).toInt(),
      barcode: json['barcode']?.toString(),
      channelType: json['channel_type']?.toString(),
    );
  }
}
