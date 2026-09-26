import 'dart:async';

import 'package:flutter/material.dart';
import 'package:webview_flutter_android/webview_flutter_android.dart';
import 'package:webview_flutter_platform_interface/webview_flutter_platform_interface.dart';

/// Bọc thẳng web app (đã kiểm thử đầy đủ: POS Nails, Payroll, Booking, Lịch sử bill...) vào
/// khung app native — cách nhanh nhất để lên CH Play mà không cần viết lại UI native từng màn
/// hình (sẽ mất nhiều tuần). Đăng nhập/CSRF/session đều dùng NGUYÊN cookie phiên trình duyệt
/// của chính WebView này, không liên quan gì tới luồng JWT native (auth_provider.dart) —
/// người dùng đăng nhập ngay bên trong WebView bằng đúng form /login của web, y hệt trên máy tính.
class WebViewScreen extends StatefulWidget {
  const WebViewScreen({super.key});

  static const String homeUrl = 'https://bitpawsoftware.com/login';

  @override
  State<WebViewScreen> createState() => _WebViewScreenState();
}

class _WebViewScreenState extends State<WebViewScreen> {
  late final PlatformWebViewController _controller;
  bool _isLoading = true;
  bool _hasError = false;

  @override
  void initState() {
    super.initState();
    _controller = PlatformWebViewController(AndroidWebViewControllerCreationParams())
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      // User-Agent riêng cho bản app — cho phép app.py phân biệt traffic từ app mobile với
      // trình duyệt thường sau này nếu cần (vd ẩn banner "Tải app" bên trong WebView).
      ..setUserAgent('BitPawMobileApp/1.0 (Android; WebView)')
      ..setBackgroundColor(const Color(0xFF0F172A))
      ..setPlatformNavigationDelegate(
        PlatformNavigationDelegate(const PlatformNavigationDelegateCreationParams())
          ..setOnPageStarted((_) => setState(() {
                _isLoading = true;
                _hasError = false;
              }))
          ..setOnPageFinished((_) => setState(() => _isLoading = false))
          ..setOnWebResourceError((error) {
            // Chỉ coi là lỗi thật khi request CHÍNH của trang (main frame) thất bại — lỗi tải
            // 1 ảnh/font phụ trong trang không được phép làm sập cả màn hình xuống "Mất kết nối".
            if (error.isForMainFrame ?? true) {
              setState(() {
                _isLoading = false;
                _hasError = true;
              });
            }
          }),
      )
      ..loadRequest(LoadRequestParams(uri: Uri.parse(WebViewScreen.homeUrl)));
  }

  Future<void> _reload() async {
    setState(() {
      _isLoading = true;
      _hasError = false;
    });
    await _controller.loadRequest(LoadRequestParams(uri: Uri.parse(WebViewScreen.homeUrl)));
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      // Nút Back vật lý Android: quay lại trang trước TRONG WebView trước, chỉ thoát app khi
      // đã ở trang gốc (không còn lịch sử để lùi) — hành vi chuẩn mọi app bọc WebView.
      canPop: false,
      onPopInvokedWithResult: (didPop, result) async {
        if (didPop) return;
        if (await _controller.canGoBack()) {
          await _controller.goBack();
        } else if (context.mounted) {
          Navigator.of(context).maybePop();
        }
      },
      child: Scaffold(
        backgroundColor: const Color(0xFF0F172A),
        body: SafeArea(
          child: Stack(
            children: [
              if (!_hasError)
                PlatformWebViewWidget(
                  PlatformWebViewWidgetCreationParams(controller: _controller),
                ).build(context),
              if (_isLoading && !_hasError)
                const Center(
                  child: CircularProgressIndicator(color: Color(0xFF06B6D4)),
                ),
              if (_hasError) _buildErrorState(),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildErrorState() {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.wifi_off_rounded, size: 56, color: Colors.white38),
            const SizedBox(height: 16),
            const Text(
              'Không kết nối được tới BitPaw OS',
              style: TextStyle(color: Colors.white, fontSize: 17, fontWeight: FontWeight.w700),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 6),
            const Text(
              'Kiểm tra kết nối mạng rồi thử lại.',
              style: TextStyle(color: Colors.white60, fontSize: 13),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 20),
            FilledButton.icon(
              onPressed: _reload,
              icon: const Icon(Icons.refresh_rounded),
              label: const Text('Thử lại'),
              style: FilledButton.styleFrom(backgroundColor: const Color(0xFF06B6D4)),
            ),
          ],
        ),
      ),
    );
  }
}
