import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../providers/auth_provider.dart';
import 'attendance_screen.dart';
import 'reports_screen.dart';

/// Khung điều hướng chính — bottom nav 1 hoặc 2 tab tuỳ role: mọi người đều thấy "Chấm công",
/// riêng "Báo cáo" chỉ hiện cho admin/super_admin (khớp đúng @role_required('admin','super_admin')
/// trên GET /api/dashboard/stats ở backend — ẩn tab chỉ là tiện lợi UI, không thay cho chặn API).
class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  int _tabIndex = 0;

  @override
  Widget build(BuildContext context) {
    final role = context.watch<AuthProvider>().user?.role;
    final canViewReports = role == 'admin' || role == 'super_admin';

    final tabs = <_HomeTab>[
      const _HomeTab(title: 'Chấm công', icon: Icons.fingerprint_rounded, screen: AttendanceScreen()),
      if (canViewReports)
        const _HomeTab(title: 'Báo cáo', icon: Icons.bar_chart_rounded, screen: ReportsScreen()),
    ];

    final safeIndex = _tabIndex < tabs.length ? _tabIndex : 0;

    return Scaffold(
      appBar: AppBar(
        title: Text(tabs[safeIndex].title == 'Chấm công' ? 'BitPaw OS' : tabs[safeIndex].title),
        actions: [
          IconButton(
            icon: const Icon(Icons.logout_rounded),
            tooltip: 'Đăng xuất',
            onPressed: () => _handleLogout(context),
          ),
        ],
      ),
      body: tabs[safeIndex].screen,
      bottomNavigationBar: tabs.length > 1
          ? NavigationBar(
              selectedIndex: safeIndex,
              onDestinationSelected: (index) => setState(() => _tabIndex = index),
              backgroundColor: const Color(0xFF0F1424),
              destinations: tabs
                  .map((t) => NavigationDestination(icon: Icon(t.icon), label: t.title))
                  .toList(),
            )
          : null,
    );
  }

  Future<void> _handleLogout(BuildContext context) async {
    await context.read<AuthProvider>().logout();
    if (!context.mounted) return;
    Navigator.of(context).pushNamedAndRemoveUntil('/login', (route) => false);
  }
}

class _HomeTab {
  final String title;
  final IconData icon;
  final Widget screen;

  const _HomeTab({required this.title, required this.icon, required this.screen});
}
