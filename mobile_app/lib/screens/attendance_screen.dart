import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';
import 'package:provider/provider.dart';

import '../models/staff_model.dart';
import '../services/api_service.dart';
import '../services/attendance_service.dart';

/// Chấm công GPS — thiết kế cho mô hình "1 thiết bị dùng chung tại quầy": chủ tiệm/quản lý
/// đăng nhập 1 lần, mỗi nhân viên tới lượt mình tự CHỌN TÊN MÌNH trong danh sách rồi bấm Vào ca/
/// Tan ca — khớp đúng cách app_nhanvien.html (web) hoạt động cho nhân viên dùng chung 1 kiosk.
class AttendanceScreen extends StatefulWidget {
  const AttendanceScreen({super.key});

  @override
  State<AttendanceScreen> createState() => _AttendanceScreenState();
}

class _AttendanceScreenState extends State<AttendanceScreen> {
  late final AttendanceService _attendanceService;

  List<StaffModel> _staffList = [];
  StaffModel? _selectedStaff;
  bool _isLoadingStaff = true;
  bool _isSubmitting = false;
  String? _loadError;
  final _noteController = TextEditingController();

  @override
  void initState() {
    super.initState();
    _attendanceService = AttendanceService(context.read<ApiService>());
    _loadStaffList();
  }

  @override
  void dispose() {
    _noteController.dispose();
    super.dispose();
  }

  Future<void> _loadStaffList() async {
    setState(() {
      _isLoadingStaff = true;
      _loadError = null;
    });
    try {
      final staff = await _attendanceService.fetchStaffList();
      if (!mounted) return;
      setState(() {
        _staffList = staff;
        _isLoadingStaff = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loadError = 'Không tải được danh sách nhân viên. Kéo xuống để thử lại.';
        _isLoadingStaff = false;
      });
    }
  }

  /// Xin quyền vị trí + lấy toạ độ hiện tại — TỪNG BƯỚC báo lỗi rõ ràng (dịch vụ vị trí tắt hẳn
  /// khác với người dùng từ chối quyền), vì backend cần TOẠ ĐỘ THẬT để geofence hoạt động đúng
  /// (xem _enforce_checkin_geofence, app.py) — thiếu bước nào cũng khiến check-in luôn bị 403.
  Future<Position?> _getCurrentPosition() async {
    final serviceEnabled = await Geolocator.isLocationServiceEnabled();
    if (!serviceEnabled) {
      _showSnackBar('Vui lòng bật Định vị (GPS) trên điện thoại rồi thử lại.', isError: true);
      return null;
    }

    LocationPermission permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied) {
      permission = await Geolocator.requestPermission();
      if (permission == LocationPermission.denied) {
        _showSnackBar('Cần quyền truy cập vị trí để chấm công.', isError: true);
        return null;
      }
    }
    if (permission == LocationPermission.deniedForever) {
      _showSnackBar('Quyền vị trí đã bị chặn vĩnh viễn — vào Cài đặt điện thoại để bật lại.', isError: true);
      return null;
    }

    try {
      return await Geolocator.getCurrentPosition(
        locationSettings: const LocationSettings(
          accuracy: LocationAccuracy.high,
          timeLimit: Duration(seconds: 20),
        ),
      );
    } catch (e) {
      _showSnackBar('Không lấy được vị trí GPS. Vui lòng thử lại ở nơi thoáng sóng hơn.', isError: true);
      return null;
    }
  }

  Future<void> _handleCheckAction(bool isCheckIn) async {
    if (_selectedStaff == null) {
      _showSnackBar('Vui lòng chọn tên nhân viên trước.', isError: true);
      return;
    }
    setState(() => _isSubmitting = true);

    final position = await _getCurrentPosition();
    if (position == null) {
      if (mounted) setState(() => _isSubmitting = false);
      return;
    }

    final result = isCheckIn
        ? await _attendanceService.checkIn(
            staffId: _selectedStaff!.id,
            latitude: position.latitude,
            longitude: position.longitude,
            note: _noteController.text.trim(),
          )
        : await _attendanceService.checkOut(
            staffId: _selectedStaff!.id,
            latitude: position.latitude,
            longitude: position.longitude,
          );

    if (!mounted) return;
    setState(() => _isSubmitting = false);
    _showSnackBar(result.message, isError: !result.success);
    if (result.success) {
      _noteController.clear();
    }
  }

  void _showSnackBar(String message, {required bool isError}) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(message),
        backgroundColor: isError ? Colors.redAccent : Colors.green,
        behavior: SnackBarBehavior.floating,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      onRefresh: _loadStaffList,
      color: const Color(0xFF06B6D4),
      backgroundColor: const Color(0xFF0F1424),
      child: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          const Text(
            'Chấm công GPS',
            style: TextStyle(color: Colors.white, fontSize: 22, fontWeight: FontWeight.bold),
          ),
          const SizedBox(height: 6),
          const Text(
            'Chọn tên nhân viên, hệ thống sẽ tự xác nhận bạn đang ở trong phạm vi cho phép của chi nhánh.',
            style: TextStyle(color: Colors.white54, fontSize: 13),
          ),
          const SizedBox(height: 24),

          if (_isLoadingStaff)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 40),
              child: Center(child: CircularProgressIndicator(color: Color(0xFF06B6D4))),
            )
          else if (_loadError != null)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 24),
              child: Column(
                children: [
                  Text(_loadError!, style: const TextStyle(color: Colors.redAccent), textAlign: TextAlign.center),
                  const SizedBox(height: 12),
                  OutlinedButton(onPressed: _loadStaffList, child: const Text('Thử lại')),
                ],
              ),
            )
          else if (_staffList.isEmpty)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 24),
              child: Text(
                'Chưa có nhân viên nào trong hệ thống. Thêm nhân viên trên web trước.',
                style: TextStyle(color: Colors.white54),
                textAlign: TextAlign.center,
              ),
            )
          else ...[
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              decoration: BoxDecoration(
                color: Colors.white.withOpacity(0.05),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: Colors.white.withOpacity(0.1)),
              ),
              child: DropdownButtonHideUnderline(
                child: DropdownButton<StaffModel>(
                  isExpanded: true,
                  value: _selectedStaff,
                  hint: const Text('-- Chọn tên nhân viên --', style: TextStyle(color: Colors.white54)),
                  dropdownColor: const Color(0xFF14192E),
                  icon: const Icon(Icons.keyboard_arrow_down_rounded, color: Colors.white54),
                  items: _staffList
                      .map((s) => DropdownMenuItem(
                            value: s,
                            child: Text(s.name, style: const TextStyle(color: Colors.white)),
                          ))
                      .toList(),
                  onChanged: (value) => setState(() => _selectedStaff = value),
                ),
              ),
            ),
            const SizedBox(height: 16),
            TextField(
              controller: _noteController,
              style: const TextStyle(color: Colors.white),
              decoration: InputDecoration(
                labelText: 'Ghi chú (tuỳ chọn)',
                labelStyle: const TextStyle(color: Colors.white54),
                filled: true,
                fillColor: Colors.white.withOpacity(0.05),
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(12),
                  borderSide: BorderSide.none,
                ),
              ),
            ),
            const SizedBox(height: 24),
            Row(
              children: [
                Expanded(
                  child: ElevatedButton.icon(
                    onPressed: _isSubmitting ? null : () => _handleCheckAction(true),
                    icon: const Icon(Icons.login_rounded),
                    label: const Text('VÀO CA'),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Colors.green,
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(vertical: 16),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                    ),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: ElevatedButton.icon(
                    onPressed: _isSubmitting ? null : () => _handleCheckAction(false),
                    icon: const Icon(Icons.logout_rounded),
                    label: const Text('TAN CA'),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Colors.orange,
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(vertical: 16),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                    ),
                  ),
                ),
              ],
            ),
            if (_isSubmitting) ...[
              const SizedBox(height: 20),
              const Center(child: CircularProgressIndicator(color: Color(0xFF06B6D4))),
            ],
          ],
        ],
      ),
    );
  }
}
