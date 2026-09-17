import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../providers/auth_provider.dart';
import 'attendance_screen.dart';
import 'pos/nail_pos_screen.dart';
import 'pos/spa_pos_screen.dart';
import 'reports_screen.dart';

/// Khung điều hướng chính — bottom nav ghép động theo role + business_mode: mọi người đều thấy
/// "Chấm công", "Báo cáo" chỉ hiện cho admin/super_admin (khớp @role_required('admin',
/// 'super_admin') trên GET /api/dashboard/stats), "Bán hàng" chỉ hiện đúng ngành có màn POS
/// tương ứng đã build cho di động (hiện tại: Nails, Spa — các ngành khác thêm dần ở bản cập
/// nhật sau, xem TaskList #42-47) để không hiện tab trống/lỗi cho ngành chưa có POS di động.
class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  int _tabIndex = 0;

  @override
  Widget build(BuildContext context) {
    final user = context.watch<AuthProvider>().user;
    final role = user?.role;
    final businessMode = user?.businessMode;
    final canViewReports = role == 'admin' || role == 'super_admin';
    final canViewNailPos = businessMode == 'nail';
    final canViewSpaPos = businessMode == 'spa';

    final tabs = <_HomeTab>[
      if (canViewNailPos)
        const _HomeTab(title: 'Bán hàng', icon: Icons.point_of_sale_rounded, screen: NailPosScreen(), ownsAppBar: true),
      if (canViewSpaPos)
        const _HomeTab(title: 'Bán hàng', icon: Icons.point_of_sale_rounded, screen: SpaPosScreen(), ownsAppBar: true),
      const _HomeTab(title: 'Chấm công', icon: Icons.fingerprint_rounded, screen: AttendanceScreen()),
      if (canViewReports)
        const _HomeTab(title: 'Báo cáo', icon: Icons.bar_chart_rounded, screen: ReportsScreen()),
    ];

    final safeIndex = _tabIndex < tabs.length ? _tabIndex : 0;
    final currentTab = tabs[safeIndex];

    return Scaffold(
      appBar: currentTab.ownsAppBar
          ? null
          : AppBar(
              title: const Text('BitPaw OS'),
              actions: [
                IconButton(
                  icon: const Icon(Icons.logout_rounded),
                  tooltip: 'Đăng xuất',
                  onPressed: () => _handleLogout(context),
                ),
              ],
            ),
      body: currentTab.screen,
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
  final bool ownsAppBar;

  const _HomeTab({required this.title, required this.icon, required this.screen, this.ownsAppBar = false});
}
