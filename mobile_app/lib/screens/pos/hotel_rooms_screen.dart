import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../../models/hotel_room_model.dart';
import '../../services/api_service.dart';
import '../../services/hotel_service.dart';

/// Quản lý phòng Hotel — mirror hotel_rooms.html (web): lưới phòng theo trạng thái (Trống/Đang
/// ở/Đang dọn), bấm phòng trống để Check-in, bấm phòng đang ở để xem thông tin khách + Trả
/// phòng, bấm phòng đang dọn để đánh dấu Dọn xong.
class HotelRoomsScreen extends StatefulWidget {
  const HotelRoomsScreen({super.key});

  @override
  State<HotelRoomsScreen> createState() => _HotelRoomsScreenState();
}

class _HotelRoomsScreenState extends State<HotelRoomsScreen> {
  late final HotelService _hotelService;
  bool _isLoading = true;
  String? _loadError;
  List<HotelRoomModel> _rooms = [];

  final _currencyFormat = NumberFormat.currency(locale: 'vi_VN', symbol: 'đ', decimalDigits: 0);

  @override
  void initState() {
    super.initState();
    _hotelService = HotelService(context.read<ApiService>());
    _loadRooms();
  }

  Future<void> _loadRooms() async {
    setState(() {
      _isLoading = true;
      _loadError = null;
    });
    try {
      final rooms = await _hotelService.fetchRooms();
      if (!mounted) return;
      setState(() {
        _rooms = rooms;
        _isLoading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loadError = 'Không tải được danh sách phòng. Kéo xuống để thử lại.';
        _isLoading = false;
      });
    }
  }

  Future<void> _handleRoomTap(HotelRoomModel room) async {
    if (room.isEmpty) {
      await _showCheckinDialog(room);
    } else if (room.isOccupied) {
      await _showCheckoutDialog(room);
    } else if (room.isCleaning) {
      await _markClean(room);
    }
  }

  Future<void> _showCheckinDialog(HotelRoomModel room) async {
    final nameController = TextEditingController();
    final phoneController = TextEditingController();
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        backgroundColor: const Color(0xFF14192E),
        title: Text('Check-in — Phòng ${room.roomNumber}', style: const TextStyle(color: Colors.white)),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: nameController,
              style: const TextStyle(color: Colors.white),
              decoration: const InputDecoration(labelText: 'Tên khách', labelStyle: TextStyle(color: Colors.white54)),
            ),
            TextField(
              controller: phoneController,
              keyboardType: TextInputType.phone,
              style: const TextStyle(color: Colors.white),
              decoration: const InputDecoration(labelText: 'SĐT (tuỳ chọn)', labelStyle: TextStyle(color: Colors.white54)),
            ),
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(dialogContext, false), child: const Text('Huỷ')),
          ElevatedButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF06B6D4), foregroundColor: Colors.black),
            child: const Text('Check-in'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    final name = nameController.text.trim();
    if (name.isEmpty) return;
    try {
      await _hotelService.checkIn(room.id, guestName: name, guestPhone: phoneController.text.trim());
      await _loadRooms();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$e'), backgroundColor: Colors.redAccent));
    }
  }

  Future<void> _showCheckoutDialog(HotelRoomModel room) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        backgroundColor: const Color(0xFF14192E),
        title: Text('Trả phòng ${room.roomNumber}', style: const TextStyle(color: Colors.white)),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Khách: ${room.guestName ?? '-'}', style: const TextStyle(color: Colors.white70)),
            const SizedBox(height: 4),
            Text('${_currencyFormat.format(room.pricePerNight)}/đêm', style: const TextStyle(color: Colors.white70)),
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(dialogContext, false), child: const Text('Đóng')),
          ElevatedButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF06B6D4), foregroundColor: Colors.black),
            child: const Text('Trả phòng'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    final result = await _hotelService.checkOut(room.id);
    if (!mounted) return;
    if (result.success) {
      await _loadRooms();
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('${result.message} ${result.nights} đêm · ${_currencyFormat.format(result.totalAmount ?? 0)}'),
          backgroundColor: Colors.green,
        ),
      );
    } else {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(result.message), backgroundColor: Colors.redAccent));
    }
  }

  Future<void> _markClean(HotelRoomModel room) async {
    try {
      await _hotelService.markClean(room.id);
      await _loadRooms();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$e'), backgroundColor: Colors.redAccent));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Bán hàng — Phòng Khách sạn')),
      body: RefreshIndicator(onRefresh: _loadRooms, color: const Color(0xFF06B6D4), child: _buildBody()),
    );
  }

  Widget _buildBody() {
    if (_isLoading) {
      return const Center(child: CircularProgressIndicator(color: Color(0xFF06B6D4)));
    }
    if (_loadError != null) {
      return ListView(
        padding: const EdgeInsets.all(20),
        children: [
          const SizedBox(height: 80),
          Text(_loadError!, style: const TextStyle(color: Colors.redAccent), textAlign: TextAlign.center),
        ],
      );
    }
    if (_rooms.isEmpty) {
      return ListView(
        padding: const EdgeInsets.all(20),
        children: const [
          SizedBox(height: 80),
          Text('Chưa có phòng nào. Thêm phòng trên web (Quản lý Khách sạn) trước.', style: TextStyle(color: Colors.white54), textAlign: TextAlign.center),
        ],
      );
    }
    return GridView.builder(
      padding: const EdgeInsets.all(16),
      gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
        crossAxisCount: 2,
        mainAxisSpacing: 12,
        crossAxisSpacing: 12,
        childAspectRatio: 1.4,
      ),
      itemCount: _rooms.length,
      itemBuilder: (context, index) {
        final room = _rooms[index];
        final color = room.isEmpty
            ? Colors.greenAccent
            : room.isOccupied
                ? Colors.orangeAccent
                : Colors.blueAccent;
        return Material(
          color: color.withOpacity(0.12),
          borderRadius: BorderRadius.circular(14),
          child: InkWell(
            borderRadius: BorderRadius.circular(14),
            onTap: () => _handleRoomTap(room),
            child: Container(
              decoration: BoxDecoration(border: Border.all(color: color.withOpacity(0.4)), borderRadius: BorderRadius.circular(14)),
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Row(
                    children: [
                      Icon(Icons.hotel_rounded, color: color, size: 20),
                      const SizedBox(width: 6),
                      Expanded(child: Text('Phòng ${room.roomNumber}', style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w600))),
                    ],
                  ),
                  const SizedBox(height: 6),
                  Text(room.status, style: TextStyle(color: color, fontSize: 12)),
                  if (room.isOccupied && room.guestName != null)
                    Text(room.guestName!, style: const TextStyle(color: Colors.white54, fontSize: 11), overflow: TextOverflow.ellipsis),
                  Text('${_currencyFormat.format(room.pricePerNight)}/đêm', style: const TextStyle(color: Colors.white38, fontSize: 11)),
                ],
              ),
            ),
          ),
        );
      },
    );
  }
}
