/// Model cho db.karaoke_rooms (xem GET /api/karaoke/rooms, app.py) — collection RIÊNG của
/// Karaoke, KHÔNG phải db.dining_tables (F&B) dù cùng khái niệm "phòng/bàn". Giá tính theo giờ,
/// làm tròn lên bội số 15 phút (tối thiểu 15 phút) khi checkout — xem
/// api_karaoke_room_checkout().
class KaraokeRoomModel {
  final int id;
  final String name;
  final double pricePerHour;
  final String status;
  final String? startTime;

  KaraokeRoomModel({
    required this.id,
    required this.name,
    required this.pricePerHour,
    required this.status,
    this.startTime,
  });

  bool get isPlaying => status == 'Đang chơi';

  factory KaraokeRoomModel.fromJson(Map<String, dynamic> json) {
    return KaraokeRoomModel(
      id: (json['id'] as num?)?.toInt() ?? 0,
      name: json['name']?.toString() ?? '(Không tên)',
      pricePerHour: (json['price_per_hour'] as num?)?.toDouble() ?? 0,
      status: json['status']?.toString() ?? 'Trống',
      startTime: json['start_time']?.toString(),
    );
  }
}
