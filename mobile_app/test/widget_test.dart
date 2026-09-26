// Smoke test: app khởi động không crash và render đúng widget gốc (BitPawApp), không phải
// bài test counter mặc định của `flutter create` (đã xoá, không khớp app thật của chúng ta).

import 'package:flutter_test/flutter_test.dart';

import 'package:bitpaw_mobile/main.dart';

void main() {
  testWidgets('App khởi động không crash', (WidgetTester tester) async {
    await tester.pumpWidget(const BitPawApp());
    await tester.pump();
    expect(find.byType(BitPawApp), findsOneWidget);
  });
}
