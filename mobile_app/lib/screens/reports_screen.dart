import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../models/dashboard_stats_model.dart';
import '../services/api_service.dart';
import '../services/reports_service.dart';

/// Báo cáo tổng quan — nội dung khớp đúng field trả về của GET /api/dashboard/stats (chỉ
/// admin/super_admin thấy tab này, xem HomeScreen). Bản v1: hiển thị số liệu tháng hiện tại,
/// chưa có chọn tháng khác (để mở rộng sau nếu chủ tiệm cần xem lịch sử).
class ReportsScreen extends StatefulWidget {
  const ReportsScreen({super.key});

  @override
  State<ReportsScreen> createState() => _ReportsScreenState();
}

class _ReportsScreenState extends State<ReportsScreen> {
  late final ReportsService _reportsService;
  late Future<DashboardStats> _statsFuture;

  final _currencyFormat = NumberFormat.currency(locale: 'vi_VN', symbol: 'đ', decimalDigits: 0);

  @override
  void initState() {
    super.initState();
    _reportsService = ReportsService(context.read<ApiService>());
    _statsFuture = _reportsService.fetchStats();
  }

  Future<void> _reload() async {
    setState(() {
      _statsFuture = _reportsService.fetchStats();
    });
    await _statsFuture;
  }

  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      onRefresh: _reload,
      color: const Color(0xFF06B6D4),
      backgroundColor: const Color(0xFF0F1424),
      child: FutureBuilder<DashboardStats>(
        future: _statsFuture,
        builder: (context, snapshot) {
          if (snapshot.connectionState == ConnectionState.waiting) {
            return const Center(child: CircularProgressIndicator(color: Color(0xFF06B6D4)));
          }
          if (snapshot.hasError) {
            return ListView(
              padding: const EdgeInsets.all(20),
              children: const [
                SizedBox(height: 80),
                Icon(Icons.error_outline_rounded, color: Colors.redAccent, size: 40),
                SizedBox(height: 12),
                Text(
                  'Không tải được báo cáo. Kéo xuống để thử lại.',
                  style: TextStyle(color: Colors.white70),
                  textAlign: TextAlign.center,
                ),
              ],
            );
          }

          final stats = snapshot.data!;
          return ListView(
            padding: const EdgeInsets.all(20),
            children: [
              const Text(
                'Báo cáo tổng quan',
                style: TextStyle(color: Colors.white, fontSize: 22, fontWeight: FontWeight.bold),
              ),
              const SizedBox(height: 4),
              Text(
                DateFormat('MM/yyyy').format(DateTime.now()),
                style: const TextStyle(color: Colors.white54, fontSize: 13),
              ),
              const SizedBox(height: 20),
              Row(
                children: [
                  Expanded(
                    child: _StatCard(
                      icon: Icons.groups_rounded,
                      label: 'Tổng nhân viên',
                      value: '${stats.totalEmployees}',
                      color: const Color(0xFF06B6D4),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: _StatCard(
                      icon: Icons.event_available_rounded,
                      label: 'Đã đi làm tháng này',
                      value: '${stats.employeesWorkedThisMonth}',
                      color: Colors.greenAccent,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              _StatCard(
                icon: Icons.payments_rounded,
                label: 'Tổng lương tháng này',
                value: _currencyFormat.format(stats.totalPayrollThisMonth),
                color: Colors.amberAccent,
                fullWidth: true,
              ),
              const SizedBox(height: 24),
              const Text('Công việc', style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.w600)),
              const SizedBox(height: 12),
              Row(
                children: [
                  Expanded(child: _TaskCountChip(label: 'Chờ làm', count: stats.tasks.pending, color: Colors.orangeAccent)),
                  const SizedBox(width: 8),
                  Expanded(child: _TaskCountChip(label: 'Đang làm', count: stats.tasks.doing, color: Colors.blueAccent)),
                  const SizedBox(width: 8),
                  Expanded(child: _TaskCountChip(label: 'Hoàn thành', count: stats.tasks.done, color: Colors.greenAccent)),
                ],
              ),
              const SizedBox(height: 24),
              const Text('Nghỉ phép trong tháng', style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.w600)),
              const SizedBox(height: 12),
              if (stats.leaves.isEmpty)
                const Padding(
                  padding: EdgeInsets.symmetric(vertical: 12),
                  child: Text('Không có ai nghỉ phép tháng này.', style: TextStyle(color: Colors.white54)),
                )
              else
                Container(
                  decoration: BoxDecoration(
                    color: Colors.white.withOpacity(0.05),
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Column(
                    children: stats.leaves
                        .map(
                          (leave) => ListTile(
                            leading: CircleAvatar(
                              backgroundColor: const Color(0xFF06B6D4).withOpacity(0.2),
                              child: Text('${leave.day}', style: const TextStyle(color: Color(0xFF06B6D4), fontSize: 13)),
                            ),
                            title: Text(leave.note, style: const TextStyle(color: Colors.white)),
                          ),
                        )
                        .toList(),
                  ),
                ),
              const SizedBox(height: 20),
            ],
          );
        },
      ),
    );
  }
}

class _StatCard extends StatelessWidget {
  final IconData icon;
  final String label;
  final String value;
  final Color color;
  final bool fullWidth;

  const _StatCard({
    required this.icon,
    required this.label,
    required this.value,
    required this.color,
    this.fullWidth = false,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      width: fullWidth ? double.infinity : null,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white.withOpacity(0.05),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: Colors.white.withOpacity(0.08)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, color: color, size: 22),
          const SizedBox(height: 10),
          Text(value, style: const TextStyle(color: Colors.white, fontSize: 18, fontWeight: FontWeight.bold)),
          const SizedBox(height: 2),
          Text(label, style: const TextStyle(color: Colors.white54, fontSize: 12)),
        ],
      ),
    );
  }
}

class _TaskCountChip extends StatelessWidget {
  final String label;
  final int count;
  final Color color;

  const _TaskCountChip({required this.label, required this.count, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 14),
      decoration: BoxDecoration(
        color: color.withOpacity(0.12),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: color.withOpacity(0.3)),
      ),
      child: Column(
        children: [
          Text('$count', style: TextStyle(color: color, fontSize: 20, fontWeight: FontWeight.bold)),
          const SizedBox(height: 4),
          Text(label, style: const TextStyle(color: Colors.white70, fontSize: 11)),
        ],
      ),
    );
  }
}
