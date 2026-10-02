// Kiểm tra logic định tuyến link của WebView: trang BitPaw mở trong app, mọi domain khác
// (mạng xã hội, cổng ngoài...) mở bằng ứng dụng bên ngoài. Không pump cả BitPawApp vì
// WebViewWidget cần WebViewPlatform thật (Android/iOS), không có trong môi trường flutter test.

import 'package:flutter_test/flutter_test.dart';

import 'package:bitpaw_mobile/screens/webview_screen.dart';

void main() {
  test('Domain BitPaw (kể cả subdomain) mở ngay trong app', () {
    expect(WebViewScreen.isOwnHost('bitpawsoftware.com'), isTrue);
    expect(WebViewScreen.isOwnHost('www.bitpawsoftware.com'), isTrue);
  });

  test('Domain khác mở bằng ứng dụng bên ngoài', () {
    expect(WebViewScreen.isOwnHost('wa.me'), isFalse);
    expect(WebViewScreen.isOwnHost('m.me'), isFalse);
    expect(WebViewScreen.isOwnHost('www.facebook.com'), isFalse);
    // Chống giả mạo kiểu "bitpawsoftware.com.evil.com" / "evilbitpawsoftware.com"
    expect(WebViewScreen.isOwnHost('bitpawsoftware.com.evil.com'), isFalse);
    expect(WebViewScreen.isOwnHost('evilbitpawsoftware.com'), isFalse);
  });

  test('Trang mở đầu là trang đăng nhập HTTPS của web app', () {
    final uri = Uri.parse(WebViewScreen.homeUrl);
    expect(uri.scheme, 'https');
    expect(WebViewScreen.isOwnHost(uri.host), isTrue);
    expect(uri.path, '/login');
  });
}
