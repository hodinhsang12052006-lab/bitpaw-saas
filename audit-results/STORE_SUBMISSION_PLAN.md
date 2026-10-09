# Kế hoạch đưa BitPaw Software lên CH Play + App Store

Cập nhật: 02/10/2026. App: `mobile_app/` (Flutter, bọc web app `https://bitpawsoftware.com` trong WebView).

## 1. Kiểm tra lại toàn bộ trước khi nộp

| Hạng mục | Kết quả |
|---|---|
| 20 script Playwright (9 ngành + Nails sâu + dùng chung + landing + bảo mật) | **0 FAIL**, 0 traceback server. Favicon 404 (WARN cũ ở cả 9 ngành) đã hết |
| Soát giao diện Nails (42 màn hình desktop + mobile) | 42/42 sạch |
| POS ở 12 kích thước (360×640 → 1920×1080) | 12/12: đủ 6 nút tác vụ, nút Pay Now luôn hiện |
| Kiểm tra yêu cầu store (`scripts/store_compliance_e2e.mjs`) | 21/21 PASS |
| App Flutter: `flutter analyze` / `flutter test` | Không lỗi / 3/3 PASS |

## 2. Lỗi chặn nộp store đã tìm thấy và đã sửa

| # | Lỗi | Ảnh hưởng | Đã sửa |
|---|---|---|---|
| 1 | App chỉ có WebView Android (`webview_flutter_android` + `AndroidWebViewControllerCreationParams`) | **Bản iOS crash ngay khi mở** | Dùng `webview_flutter` đa nền tảng (bản wkwebview 3.27 không còn kéo `objective_c` gây lỗi build Windows) |
| 2 | Thư mục `ios/` không có project Xcode (thiếu `Runner.xcodeproj`, `Info.plist`, icon) | Không build được bản iOS | Tạo project iOS: bundle ID `com.bitpawsoftware.bitpawMobile`, tên "BitPaw Software" (dưới icon: "BitPaw POS"), iPhone + iPad, iOS ≥ 15, icon từ logo thật (1024 không alpha) |
| 3 | Xoá tài khoản: có API nhưng **không màn hình nào gọi tới** | Apple 5.1.1(v) + Google Play từ chối | Trang `/account/delete` (xác nhận mật khẩu, khoá đăng nhập ngay) + link "Delete account" trong sidebar mọi trang. Khi chưa đăng nhập, trang hướng dẫn gửi yêu cầu xoá qua email (đúng yêu cầu "link web xoá tài khoản" của Google) |
| 4 | Không có URL chính sách bảo mật riêng; văn bản còn `[Email liên hệ]`, `[Ngày cập nhật]`, `[Tax ID]`... | 2 store bắt buộc URL Privacy Policy | `/privacy-policy`, `/terms`, `/payment-policy` (EN/VI), điền email `bitpawsoftware@gmail.com`, ngày 02/10/2026, pháp nhân "BitPaw Technology LLC"; thêm đoạn mở đầu nêu rõ áp dụng cho app Android/iOS + quyền camera/vị trí |
| 5 | Trong app vẫn vào được trang bán gói phần mềm (`/checkout`, bảng giá landing) | Apple 3.1.1 / Google Play Payments: bán gói số ngoài In-App Purchase bị từ chối | App gửi UA `BitPawMobileApp/1.0.0 (iOS\|Android; WebView)`; trong app `/checkout` hiện "không khả dụng trong ứng dụng" (không link mua ngoài), `/api/checkout/*` trả 403, landing/bảng giá chuyển về đăng nhập. Web thường không đổi |
| 6 | Chấm công nhân viên cần camera + GPS nhưng app không xin quyền | Chấm công trong app luôn thất bại; iOS crash nếu thiếu mô tả quyền | Android: quyền CAMERA/LOCATION + cấp quyền cho WebView; iOS: `NSCameraUsageDescription`, `NSLocationWhenInUseUsageDescription`, `NSPhotoLibraryUsageDescription` |
| 7 | `<input type="file">` (logo, ảnh đại diện, khôi phục backup) không làm gì trong Android WebView | Không tải ảnh lên được trong app | Bộ chọn file (`file_picker`) |
| 8 | Link `tel:`, `mailto:`, WhatsApp, Messenger báo lỗi `ERR_UNKNOWN_URL_SCHEME` | Nút liên hệ hỏng trong app | Mở bằng app tương ứng (`url_launcher`); chỉ domain `bitpawsoftware.com` mở trong app |
| 9 | Màn khởi động trắng loé trước giao diện tối | Trải nghiệm kém | Nền khởi động `#0F172A` cả Android + iOS |
| 10 | POS: ngôn ngữ mặc định bỏ qua lựa chọn của người dùng (cookie) | iPad tiệm AU mở POS bằng tiếng Việt | POS đọc cookie `bitpaw_lang` trước khi về mặc định |
| 11 | Bảng lương trên điện thoại thấp: danh sách nhân viên bị ép còn 0px | Không xem được lương trên điện thoại | Khung bảng tối thiểu 70vh |
| 12 | `ITSAppUsesNonExemptEncryption` chưa khai báo | Mỗi lần nộp build phải trả lời câu hỏi xuất khẩu mã hoá | Khai báo `false` (chỉ dùng HTTPS chuẩn) |
| 13 | File build máy local bị commit (`.dart_tool`, `local.properties`, `Generated.xcconfig`...) | Rác + đường dẫn máy cá nhân trong repo | Gỡ khỏi git (đã có trong `.gitignore`) |

## 3. Build: GitHub Actions (`.github/workflows/mobile-build.yml`)

Máy dev Windows này không build được (Gradle bị chặn kết nối loopback; iOS bắt buộc macOS) nên build trên GitHub Actions, tự chạy khi push thay đổi trong `mobile_app/`:
- **Android**: `flutter analyze` + `flutter test` + `flutter build appbundle` → tải file `.aab` ở tab Actions → Artifacts.
- **iOS**: `flutter build ios --release --no-codesign` để chắc chắn code iOS biên dịch được.

Lần chạy ngày 02/10/2026 (commit `480fb7e`): **cả 2 job xanh**, file Android `.aab` 44.7 MB + iOS `Runner.app` 9.1 MB tải được ở tab Actions → run "Mobile build" → Artifacts. Lần chạy đầu tiên (commit `33a5aaf`) lỗi Android vì `permission_handler_android` 14.x đòi compileSdk 37 trong khi Flutter 3.47 dùng 36 → đã ghim `permission_handler: ^12.0.1`. **Đừng nâng `permission_handler` lên 13.x** khi chưa nâng compileSdk app lên 37.

## 4. Việc CHỈ chủ dự án làm được (cần tài khoản/khoá bí mật của anh)

### CH Play
1. **Thêm 4 secret vào GitHub** (Settings → Secrets and variables → Actions) để file `.aab` được ký bằng khoá release thật:
   - `ANDROID_KEYSTORE_BASE64`: chạy `base64 -w0 mobile_app/android/app/bitpaw-release.jks` rồi dán kết quả
   - `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`, `ANDROID_KEY_PASSWORD`: lấy trong `mobile_app/android/key.properties`
   - **Sao lưu `bitpaw-release.jks` + `key.properties` ra nơi an toàn**: mất file này thì không cập nhật app trên CH Play được nữa.
2. Tạo tài khoản Google Play Console (25 USD, 1 lần) → Create app "BitPaw Software".
3. Bật Play App Signing, tải `.aab` (bản `release-signed`) lên track **Internal testing** trước, cài thử trên điện thoại thật.
4. Điền Store listing + các form theo mục 5.

### App Store
1. Tài khoản Apple Developer Program (99 USD/năm). Tạo App ID `com.bitpawsoftware.bitpawMobile`.
2. Ký + tải bản build lên App Store Connect: dùng máy Mac (Xcode → Product → Archive → Distribute) **hoặc** Codemagic/GitHub Actions với App Store Connect API key (đề xuất Codemagic: không cần máy Mac).
3. TestFlight thử trên iPhone/iPad thật, kiểm tra: đăng nhập, POS, chấm công (camera + GPS), tải ảnh logo, nút gọi điện/email, Xoá tài khoản.
4. Điền App Store Connect theo mục 5, nộp review.

## 5. Nội dung điền form

| Trường | Giá trị |
|---|---|
| Tên app | Tên trên store: **BitPaw Software** · tên dưới icon: **BitPaw POS** (không dùng "BitPaw OS" — đó là tên nền tảng việc làm bitpawos.com, trùng tên làm Google/người dùng nhầm 2 sản phẩm) |
| Mô tả ngắn (Play, ≤80 ký tự) | Salon POS, online booking, staff attendance & payroll in one app. |
| Danh mục | Business |
| Email hỗ trợ | bitpawsoftware@gmail.com |
| Privacy Policy URL | https://bitpawsoftware.com/privacy-policy |
| Link xoá tài khoản (Play → Data safety) | https://bitpawsoftware.com/account/delete |
| Ảnh chụp | `mobile_app/store_assets/`: `android_phone/` (1080×2160), `ios_iphone_6.9/` (1290×2796), `ios_ipad_13/` (2064×2752), `google_play_feature_graphic_1024x500.png`. Tạo lại: `node scripts/store_screenshots.mjs` |
| Độ tuổi (Content rating) | Ứng dụng doanh nghiệp, không có nội dung nhạy cảm → Everyone / 4+ |

**Data safety (Play) / App Privacy (Apple)**, khai báo đúng theo hành vi thật của app:
- Thu thập: email, tên, số điện thoại (tài khoản + khách hàng của tiệm); **vị trí chính xác** + **ảnh** (chỉ khi nhân viên chấm công); lịch sử giao dịch/đơn hàng; tin nhắn CSKH.
- Mục đích: vận hành chức năng app (App functionality), quản lý tài khoản. **Không** dùng cho quảng cáo, **không** bán dữ liệu, **không** tracking (Apple: "Data Not Used to Track You").
- Mã hoá khi truyền: Có (HTTPS). Người dùng yêu cầu xoá dữ liệu được: Có (`/account/delete`).

**Ghi chú cho người duyệt (App Review notes / Play app access)**: app dành cho chủ tiệm có tài khoản, cần cấp 1 tài khoản demo đăng nhập được, ví dụ tài khoản demo Nails AU đang dùng cho kiểm thử. Ghi thêm: "Subscriptions are sold to businesses outside the app; the app does not offer any purchase."

## 6. Rủi ro còn lại / việc làm sau

| Rủi ro | Mức | Kế hoạch |
|---|---|---|
| Apple 4.2 "Minimum functionality": app bọc web có thể bị từ chối nếu reviewer cho là "chỉ là website" | Trung bình | Đã có tính năng native thật: camera/GPS chấm công, chọn file, mở app gọi/email, màn hình mất mạng + thử lại, vuốt lùi. Nếu bị từ chối: thêm thông báo đẩy (push) cho lịch hẹn mới và nhấn mạnh điều này trong ghi chú review |
| Mã số đăng ký kinh doanh "888999777" + địa chỉ San Francisco trên footer website trông như dữ liệu mẫu | Cần xác nhận | Đã **không** đưa vào văn bản pháp lý. Anh kiểm tra lại footer + thông tin pháp nhân thật trước khi nộp (Apple đối chiếu tên nhà phát triển) |
| In hoá đơn (`window.print()`) và xuất Excel (tải file) không hoạt động bên trong WebView | Thấp | Tính năng phụ, vẫn dùng được trên web. Làm sau: cầu nối JS → chia sẻ/in native |
| Rate limiter chung đếm riêng từng instance Vercel (chưa có Redis) | Trung bình | Tạo Redis miễn phí (Upstash) rồi đặt `REDIS_URL` trên project Vercel `bitpaw-saas-web`. Chống dò mật khẩu đã chuyển sang MongoDB nên vẫn an toàn khi chưa làm việc này. Chi tiết: FINDINGS_LOG.md Pha 10 |
| Tài khoản nhân viên đăng nhập app (mã NV) chưa có luồng cấp quyền rõ ràng | Cần quyết định sản phẩm | Giữ nguyên như ghi nhận ở Pha 8 |
