import 'package:flutter/material.dart';

import 'screens/webview_screen.dart';

void main() {
  runApp(const BitPawApp());
}

class BitPawApp extends StatelessWidget {
  const BitPawApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'BitPaw OS',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        brightness: Brightness.dark,
        useMaterial3: true,
        colorSchemeSeed: const Color(0xFF06B6D4),
        scaffoldBackgroundColor: const Color(0xFF0F172A),
      ),
      // Bản "nhanh lên CH Play": mở thẳng WebView trỏ vào web app đã kiểm thử đầy đủ —
      // người dùng đăng nhập ngay TRONG WebView bằng đúng form /login của web (session
      // cookie thật). Luồng JWT native (auth_provider/api_service/storage_service) đã gỡ
      // bỏ — chỉ tồn tại như code chết và kéo theo dependency objective_c làm vỡ build
      // Windows; sẽ viết lại từ đầu nếu sau này thật sự cần màn hình native riêng.
      home: const WebViewScreen(),
    );
  }
}
