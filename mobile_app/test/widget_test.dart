// Smoke test tối thiểu — chỉ xác nhận app khởi động không crash và vào đúng SplashScreen
// (đúng route ban đầu trong main.dart), thay cho test "Counter" mặc định của Flutter template
// (không liên quan gì tới BitPaw OS).

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:bitpaw_mobile/main.dart';

void main() {
  testWidgets('App khởi động và hiển thị màn hình chờ ban đầu', (WidgetTester tester) async {
    await tester.pumpWidget(const BitPawApp());
    await tester.pump();

    expect(find.byType(CircularProgressIndicator), findsOneWidget);
  });
}
