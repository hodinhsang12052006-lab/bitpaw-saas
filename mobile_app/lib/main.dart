import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'providers/auth_provider.dart';
import 'screens/home_screen.dart';
import 'screens/login_screen.dart';
import 'services/api_service.dart';

void main() {
  runApp(const BitPawApp());
}

class BitPawApp extends StatelessWidget {
  const BitPawApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        // ApiService khởi tạo 1 LẦN DUY NHẤT cho cả app (giữ đúng 1 Dio instance + Interceptor)
        // — mọi provider/service khác gọi API đều lấy lại đúng instance này qua context.read().
        Provider<ApiService>(create: (_) => ApiService()),
        ChangeNotifierProvider<AuthProvider>(
          create: (context) => AuthProvider(context.read<ApiService>()),
        ),
      ],
      child: MaterialApp(
        title: 'BitPaw OS',
        debugShowCheckedModeBanner: false,
        // BẮT BUỘC gán đúng navigatorKey của ApiService — đây là cách Interceptor (nằm ngoài
        // widget tree, không có BuildContext riêng) tự điều hướng về /login khi gặp 401.
        navigatorKey: ApiService.navigatorKey,
        theme: ThemeData(
          brightness: Brightness.dark,
          useMaterial3: true,
          colorSchemeSeed: const Color(0xFF06B6D4),
          scaffoldBackgroundColor: const Color(0xFF08061A),
        ),
        initialRoute: '/splash',
        routes: {
          '/splash': (context) => const _SplashScreen(),
          '/login': (context) => const LoginScreen(),
          '/home': (context) => const HomeScreen(),
        },
      ),
    );
  }
}

/// Màn hình chờ ngắn lúc mở app — quyết định vào thẳng /home (đã có token lưu sẵn) hay /login
/// (chưa đăng nhập/token đã bị xoá) trước khi user thấy bất kỳ giao diện nào.
class _SplashScreen extends StatefulWidget {
  const _SplashScreen();

  @override
  State<_SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends State<_SplashScreen> {
  @override
  void initState() {
    super.initState();
    // Không gọi thẳng trong initState — chờ frame đầu tiên render xong để context.read() an
    // toàn tuyệt đối với mọi provider phía trên.
    WidgetsBinding.instance.addPostFrameCallback((_) => _decideInitialRoute());
  }

  Future<void> _decideInitialRoute() async {
    final authProvider = context.read<AuthProvider>();
    await authProvider.checkAuthStatus();
    if (!mounted) return;
    final route = authProvider.status == AuthStatus.authenticated
        ? '/home'
        : '/login';
    Navigator.of(context).pushReplacementNamed(route);
  }

  @override
  Widget build(BuildContext context) {
    return const Scaffold(
      backgroundColor: Color(0xFF08061A),
      body: Center(
        child: CircularProgressIndicator(color: Color(0xFF06B6D4)),
      ),
    );
  }
}
