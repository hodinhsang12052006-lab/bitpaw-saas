/// Model tương ứng field "user" trong response của POST /api/auth/token
/// (xem app.py::api_auth_token) — {id, email, role, business_id, business_mode}.
class UserModel {
  final String id;
  final String email;
  final String role;
  final String businessId;
  final String businessMode;

  UserModel({
    required this.id,
    required this.email,
    required this.role,
    required this.businessId,
    required this.businessMode,
  });

  factory UserModel.fromJson(Map<String, dynamic> json) {
    return UserModel(
      // .toString() phòng trường hợp backend trả id dạng số (int) thay vì chuỗi —
      // không để app crash vì kiểu dữ liệu lệch giữa các phiên bản API.
      id: json['id']?.toString() ?? '',
      email: json['email']?.toString() ?? '',
      role: json['role']?.toString() ?? '',
      businessId: json['business_id']?.toString() ?? '',
      businessMode: json['business_mode']?.toString() ?? '',
    );
  }
}
