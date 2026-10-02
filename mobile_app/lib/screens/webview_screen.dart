import 'dart:async';
import 'dart:io' show Platform;

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:webview_flutter/webview_flutter.dart';
import 'package:webview_flutter_android/webview_flutter_android.dart';
import 'package:webview_flutter_wkwebview/webview_flutter_wkwebview.dart';

/// Bọc thẳng web app (đã kiểm thử đầy đủ: POS Nails, Payroll, Booking, Lịch sử bill...) vào
/// khung app native cho CẢ Android (CH Play) lẫn iOS (App Store). Đăng nhập/CSRF/session dùng
/// NGUYÊN cookie phiên của chính WebView — người dùng đăng nhập bằng đúng form /login của web.
///
/// Trước đây chỉ có implementation Android (AndroidWebViewControllerCreationParams) nên bản iOS
/// không có WebView; đồng thời trong app Android KHÔNG dùng được: camera + GPS khi nhân viên
/// chấm công (/app_nhanvien), chọn ảnh tải lên (logo, ảnh đại diện...), và link ngoài
/// (tel:/mailto:/WhatsApp/Messenger báo ERR_UNKNOWN_URL_SCHEME). Màn hình này xử lý cả 3.
class WebViewScreen extends StatefulWidget {
  const WebViewScreen({super.key});

  static const String homeUrl = 'https://bitpawsoftware.com/login';

  /// Domain của web app — mở NGAY TRONG app. Mọi domain/scheme khác (mạng xã hội, gọi điện,
  /// email...) mở bằng ứng dụng tương ứng bên ngoài.
  static bool isOwnHost(String host) =>
      host == 'bitpawsoftware.com' || host.endsWith('.bitpawsoftware.com');

  @override
  State<WebViewScreen> createState() => _WebViewScreenState();
}

class _WebViewScreenState extends State<WebViewScreen> {
  late final WebViewController _controller;
  bool _isLoading = true;
  bool _hasError = false;

  @override
  void initState() {
    super.initState();

    final PlatformWebViewControllerCreationParams params;
    if (WebViewPlatform.instance is WebKitWebViewPlatform) {
      // iOS: cho phép <video> của camera chấm công phát ngay trong trang (không bật toàn màn hình).
      params = WebKitWebViewControllerCreationParams(
        allowsInlineMediaPlayback: true,
        mediaTypesRequiringUserAction: const <PlaybackMediaTypes>{},
      );
    } else {
      params = const PlatformWebViewControllerCreationParams();
    }

    final controller = WebViewController.fromPlatformCreationParams(
      params,
      onPermissionRequest: _onWebPermissionRequest,
    );

    controller
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      // User-Agent riêng cho bản app — app.py dựa vào đây để áp chính sách store (ẩn trang bán
      // gói phần mềm/bảng giá trong app). Định dạng phải khớp _MOBILE_APP_UA_RE trong app.py.
      ..setUserAgent('BitPawMobileApp/1.0.0 (${Platform.isIOS ? 'iOS' : 'Android'}; WebView)')
      ..setBackgroundColor(const Color(0xFF0F172A))
      ..setNavigationDelegate(
        NavigationDelegate(
          onPageStarted: (_) => setState(() {
            _isLoading = true;
            _hasError = false;
          }),
          onPageFinished: (_) => setState(() => _isLoading = false),
          onWebResourceError: (error) {
            // Chỉ coi là lỗi thật khi request CHÍNH của trang (main frame) thất bại — lỗi tải
            // 1 ảnh/font phụ trong trang không được phép làm sập cả màn hình xuống "Mất kết nối".
            if (error.isForMainFrame ?? true) {
              setState(() {
                _isLoading = false;
                _hasError = true;
              });
            }
          },
          onNavigationRequest: _onNavigationRequest,
        ),
      );

    final platform = controller.platform;
    if (platform is AndroidWebViewController) {
      platform
        ..setMediaPlaybackRequiresUserGesture(false)
        // <input type="file"> trong Android WebView không làm gì nếu app không tự mở bộ chọn file.
        ..setOnShowFileSelector(_androidFileSelector)
        // navigator.geolocation (chấm công GPS) — Android WebView hỏi app, app hỏi quyền hệ thống.
        ..setGeolocationPermissionsPromptCallbacks(
          onShowPrompt: (request) async => GeolocationPermissionsResponse(
            allow: await _ensurePermission(Permission.locationWhenInUse),
            retain: false,
          ),
        );
    } else if (platform is WebKitWebViewController) {
      // iOS: vuốt từ mép trái để quay lại trang trước, đúng thói quen người dùng iPhone.
      platform.setAllowsBackForwardNavigationGestures(true);
    }

    controller.loadRequest(Uri.parse(WebViewScreen.homeUrl));
    _controller = controller;
  }

  FutureOr<NavigationDecision> _onNavigationRequest(NavigationRequest request) async {
    final uri = Uri.tryParse(request.url);
    if (uri == null) return NavigationDecision.prevent;
    // iframe/khung con (vd form thẻ của cổng thanh toán) luôn được tải bình thường.
    if (!request.isMainFrame) return NavigationDecision.navigate;
    const inAppSchemes = {'about', 'data', 'blob', 'javascript'};
    if (inAppSchemes.contains(uri.scheme)) return NavigationDecision.navigate;
    if ((uri.scheme == 'https' || uri.scheme == 'http') && WebViewScreen.isOwnHost(uri.host)) {
      return NavigationDecision.navigate;
    }
    // tel:, mailto:, WhatsApp, Messenger, Facebook... -> mở bằng app tương ứng của máy.
    await launchUrl(uri, mode: LaunchMode.externalApplication).catchError((_) => false);
    return NavigationDecision.prevent;
  }

  Future<bool> _ensurePermission(Permission permission) async {
    // iOS: WKWebView tự hiện hộp thoại quyền hệ thống (theo NSCameraUsageDescription /
    // NSLocationWhenInUseUsageDescription trong Info.plist) khi trang gọi camera/GPS — không cần
    // permission_handler (vốn phải bật macro từng quyền trong Podfile mới hoạt động trên iOS).
    if (Platform.isIOS) return true;
    final status = await permission.request();
    return status.isGranted || status.isLimited;
  }

  /// getUserMedia (camera chụp ảnh chấm công) — chỉ cấp cho trang của chính BitPaw.
  Future<void> _onWebPermissionRequest(WebViewPermissionRequest request) async {
    final wantsCamera = request.types.contains(WebViewPermissionResourceType.camera);
    final wantsMic = request.types.contains(WebViewPermissionResourceType.microphone);
    var granted = true;
    if (wantsCamera) granted = granted && await _ensurePermission(Permission.camera);
    if (wantsMic) granted = granted && await _ensurePermission(Permission.microphone);
    if (granted) {
      await request.grant();
    } else {
      await request.deny();
    }
  }

  Future<List<String>> _androidFileSelector(FileSelectorParams params) async {
    final accepts = params.acceptTypes.where((t) => t.trim().isNotEmpty).toList();
    final onlyImages = accepts.isNotEmpty && accepts.every((t) => t.startsWith('image/'));
    final extensions = accepts
        .where((t) => t.startsWith('.'))
        .map((t) => t.substring(1).toLowerCase())
        .toList();
    final type = onlyImages
        ? FileType.image
        : (extensions.isNotEmpty ? FileType.custom : FileType.any);
    final allowed = (!onlyImages && extensions.isNotEmpty) ? extensions : null;
    // file_picker 13: API tĩnh; PlatformFile.uri (content:// hoặc file://) WebView đọc trực tiếp được.
    final List<PlatformFile> files;
    if (params.mode == FileSelectorMode.openMultiple) {
      files = await FilePicker.pickFiles(type: type, allowedExtensions: allowed);
    } else {
      final single = await FilePicker.pickFile(type: type, allowedExtensions: allowed);
      files = single == null ? <PlatformFile>[] : <PlatformFile>[single];
    }
    return files.map((f) => f.uri.toString()).toList();
  }

  Future<void> _reload() async {
    setState(() {
      _isLoading = true;
      _hasError = false;
    });
    await _controller.loadRequest(Uri.parse(WebViewScreen.homeUrl));
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
              if (!_hasError) WebViewWidget(controller: _controller),
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
              'Cannot reach BitPaw OS',
              style: TextStyle(color: Colors.white, fontSize: 17, fontWeight: FontWeight.w700),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 6),
            const Text(
              'Check your internet connection and try again.\nKiểm tra kết nối mạng rồi thử lại.',
              style: TextStyle(color: Colors.white60, fontSize: 13),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 20),
            FilledButton.icon(
              onPressed: _reload,
              icon: const Icon(Icons.refresh_rounded),
              label: const Text('Retry / Thử lại'),
              style: FilledButton.styleFrom(backgroundColor: const Color(0xFF06B6D4)),
            ),
          ],
        ),
      ),
    );
  }
}
