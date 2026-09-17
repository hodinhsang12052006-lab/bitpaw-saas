import 'dart:async';

import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../../models/karaoke_room_model.dart';
import '../../services/api_service.dart';
import '../../services/karaoke_service.dart';

/// Quản lý phòng Karaoke — mirror karaoke.html (web): lưới phòng theo trạng thái, bấm phòng
/// trống để Mở phòng, bấm phòng đang chơi để xem giờ đã chơi + Chốt phòng (backend tự tính
/// tiền theo thời gian, làm tròn 15 phút).
class KaraokeRoomsScreen extends StatefulWidget {
  const KaraokeRoomsScreen({super.key});

  @override
  State<KaraokeRoomsScreen> createState() => _KaraokeRoomsScreenState();
}

class _KaraokeRoomsScreenState extends State<KaraokeRoomsScreen> {
  late final KaraokeService _karaokeService;
  bool _isLoading = true;
  String? _loadError;
  List<KaraokeRoomModel> _rooms = [];
  Timer? _tickTimer;

  final _currencyFormat = NumberFormat.currency(locale: 'vi_VN', symbol: 'đ', decimalDigits: 0);

  @override
  void initState() {
    super.initState();
    _karaokeService = KaraokeService(context.read<ApiService>());
    _loadRooms();
    // Cập nhật lại UI mỗi phút để đồng hồ "đã chơi X phút" tự nhảy số, không cần refresh tay.
    _tickTimer = Timer.periodic(const Duration(minutes: 1), (_) {
      if (mounted) setState(() {});
    });
  }

  @override
  void dispose() {
    _tickTimer?.cancel();
    super.dispose();
  }

  Future<void> _loadRooms() async {
    setState(() {
      _isLoading = true;
      _loadError = null;
    });
    try {
      final rooms = await _karaokeService.fetchRooms();
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

  Future<void> _handleRoomTap(KaraokeRoomModel room) async {
    if (!room.isPlaying) {
      await _startRoom(room);
    } else {
      await _showCheckoutDialog(room);
    }
  }

  Future<void> _startRoom(KaraokeRoomModel room) async {
    try {
      await _karaokeService.startRoom(room.id);
      await _loadRooms();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$e'), backgroundColor: Colors.redAccent));
    }
  }

  Duration _elapsed(KaraokeRoomModel room) {
    if (room.startTime == null) return Duration.zero;
    try {
      final start = DateFormat('yyyy-MM-dd HH:mm:ss').parse(room.startTime!);
      final diff = DateTime.now().difference(start);
      return diff.isNegative ? Duration.zero : diff;
    } catch (_) {
      return Duration.zero;
    }
  }

  Future<void> _showCheckoutDialog(KaraokeRoomModel room) async {
    final elapsed = _elapsed(room);
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        backgroundColor: const Color(0xFF14192E),
        title: Text(room.name, style: const TextStyle(color: Colors.white)),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Đã chơi: ${elapsed.inHours}h ${elapsed.inMinutes % 60}p', style: const TextStyle(color: Colors.white70)),
            const SizedBox(height: 4),
            Text('Giá: ${_currencyFormat.format(room.pricePerHour)}/giờ', style: const TextStyle(color: Colors.white70)),
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(dialogContext, false), child: const Text('Đóng')),
          ElevatedButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF06B6D4), foregroundColor: Colors.black),
            child: const Text('Chốt phòng'),
          ),
        ],
      ),
    );
    if (confirmed == true) {
      final result = await _karaokeService.checkoutRoom(room.id);
      if (!mounted) return;
      if (result.success) {
        await _loadRooms();
        if (!mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('${result.message} Tổng: ${_currencyFormat.format(result.totalAmount ?? 0)}'),
            backgroundColor: Colors.green,
          ),
        );
      } else {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(result.message), backgroundColor: Colors.redAccent));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Bán hàng — Phòng Karaoke')),
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
          Text('Chưa có phòng nào. Thêm phòng trên web (Quản lý Karaoke) trước.', style: TextStyle(color: Colors.white54), textAlign: TextAlign.center),
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
        final color = room.isPlaying ? Colors.orangeAccent : Colors.greenAccent;
        final elapsed = room.isPlaying ? _elapsed(room) : null;
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
                      Icon(Icons.mic_external_on_rounded, color: color, size: 20),
                      const SizedBox(width: 6),
                      Expanded(child: Text(room.name, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w600))),
                    ],
                  ),
                  const SizedBox(height: 6),
                  Text(room.status, style: TextStyle(color: color, fontSize: 12)),
                  if (elapsed != null) Text('${elapsed.inHours}h ${elapsed.inMinutes % 60}p', style: const TextStyle(color: Colors.white54, fontSize: 11)),
                  Text('${_currencyFormat.format(room.pricePerHour)}/giờ', style: const TextStyle(color: Colors.white38, fontSize: 11)),
                ],
              ),
            ),
          ),
        );
      },
    );
  }
}
