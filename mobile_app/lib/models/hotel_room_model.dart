/// Model cho db.hotel_rooms (xem GET /api/hotel/rooms, app.py). Vòng đời phòng: 'Trống' ->
/// (check-in) 'Đang ở' -> (check-out, đã tính tiền theo đêm) 'Đang dọn' -> (dọn xong) 'Trống'.
/// Khác Karaoke (tính theo phút) — Hotel tính theo ĐÊM (ngày check-in tới ngày hiện tại).
class HotelRoomModel {
  final int id;
  final String roomNumber;
  final String roomType;
  final double pricePerNight;
  final int capacity;
  final String status;
  final String? guestName;
  final String? guestPhone;
  final String? checkinDate;

  HotelRoomModel({
    required this.id,
    required this.roomNumber,
    required this.roomType,
    required this.pricePerNight,
    required this.capacity,
    required this.status,
    this.guestName,
    this.guestPhone,
    this.checkinDate,
  });

  bool get isOccupied => status == 'Đang ở';
  bool get isCleaning => status == 'Đang dọn';
  bool get isEmpty => status == 'Trống';

  factory HotelRoomModel.fromJson(Map<String, dynamic> json) {
    return HotelRoomModel(
      id: (json['id'] as num?)?.toInt() ?? 0,
      roomNumber: json['room_number']?.toString() ?? '?',
      roomType: json['room_type']?.toString() ?? 'Standard',
      pricePerNight: (json['price_per_night'] as num?)?.toDouble() ?? 0,
      capacity: (json['capacity'] as num?)?.toInt() ?? 2,
      status: json['status']?.toString() ?? 'Trống',
      guestName: json['guest_name']?.toString(),
      guestPhone: json['guest_phone']?.toString(),
      checkinDate: json['checkin_date']?.toString(),
    );
  }
}
