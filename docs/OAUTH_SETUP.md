# Bật "Tiếp tục với Google / Facebook" trên www.bitpawsoftware.com

Code đã xong và đã test (scripts/oauth_login_e2e.mjs, 14/14 với máy chủ OAuth giả lập). Nút chỉ hiện khi có khoá của
nhà cung cấp tương ứng — chưa có khoá thì trang đăng nhập vẫn như cũ. Các bước dưới đây chủ tài khoản Google/Facebook phải
tự làm (cần đăng nhập + xác minh doanh nghiệp), rồi dán 5 biến môi trường vào Vercel.

## 1. Google (Google Cloud Console)

1. https://console.cloud.google.com → tạo project "BitPaw Software".
2. **APIs & Services → OAuth consent screen**: User type **External**; App name `BitPaw Software`; support email;
   App domain `https://www.bitpawsoftware.com`; Privacy policy `https://www.bitpawsoftware.com/privacy`;
   Terms `https://www.bitpawsoftware.com/terms`; Authorized domain `bitpawsoftware.com`.
   Scopes: chỉ `openid`, `.../auth/userinfo.email`, `.../auth/userinfo.profile` (không cần xác minh nâng cao).
   Bấm **Publish app** (không thì chỉ tài khoản test đăng nhập được).
3. **Credentials → Create credentials → OAuth client ID** → Web application.
   - Authorized JavaScript origins: `https://www.bitpawsoftware.com`
   - Authorized redirect URIs: `https://www.bitpawsoftware.com/auth/google/callback`
4. Lấy **Client ID** và **Client secret**.

## 2. Facebook (Meta for Developers)

1. https://developers.facebook.com → My Apps → Create app → loại **Consumer** (hoặc "Authenticate and request data from users with Facebook Login").
2. **Facebook Login → Settings**: Valid OAuth Redirect URIs = `https://www.bitpawsoftware.com/auth/facebook/callback`;
   bật "Client OAuth login", "Web OAuth login", "Enforce HTTPS".
3. **App settings → Basic**: Privacy Policy URL `https://www.bitpawsoftware.com/privacy`; Terms `https://www.bitpawsoftware.com/terms`;
   User data deletion → "Data deletion instructions URL" = `https://www.bitpawsoftware.com/privacy` (mục 9 đã ghi cách xoá);
   App domain `bitpawsoftware.com`; category Business; icon 1024×1024 (logo B).
4. Quyền cần: `email`, `public_profile` (mặc định có, không cần App Review).
5. Chuyển app sang **Live**. Lấy **App ID** và **App Secret**.

## 3. Vercel (project đang phục vụ domain — xem `vercel inspect`)

Settings → Environment Variables (Production):

| Biến | Giá trị |
|---|---|
| `GOOGLE_CLIENT_ID` | Client ID ở bước 1.4 |
| `GOOGLE_CLIENT_SECRET` | Client secret ở bước 1.4 |
| `FACEBOOK_APP_ID` | App ID ở bước 2.5 |
| `FACEBOOK_APP_SECRET` | App Secret ở bước 2.5 |
| `PUBLIC_BASE_URL` | `https://www.bitpawsoftware.com` |

Redeploy. Mở `/login` → thấy 2 nút. Không bao giờ dán secret vào code / GitHub.

## Hành vi đã test

- Người mới: đăng nhập Google/Facebook → trang "Hoàn tất đăng ký" (mã kích hoạt + tên tiệm + ngành), không cần mật khẩu.
- Email trùng tài khoản có sẵn → chỉ tự liên kết khi nhà cung cấp xác nhận email đã xác minh.
- Chống giả mạo: state + hạn 10 phút, PKCE (Google), nonce; đổi code lấy token ở máy chủ; `next=` chỉ nhận đường dẫn nội bộ.
- Facebook không trả email → báo dùng email để đăng ký.
- **Trong app di động (WebView) nút không hiện**: Google chặn đăng nhập trong WebView nhúng ("disallowed_useragent") và
  trang đăng nhập mở ra trình duyệt ngoài nên phiên không quay về app. Trong app dùng email + mật khẩu.
