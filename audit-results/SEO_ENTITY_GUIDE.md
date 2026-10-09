# Cho Google hiểu đúng 3 thương hiệu + người sáng lập Hồ Đình Sang

Cập nhật: 09/10/2026.

## Vì sao Google AI đang hiểu sai

1. Website phần mềm (bitpawsoftware.com) tự gọi mình là **"BitPaw OS"**, trùng tên nền tảng việc làm ở bitpawos.com. Google thấy 2 site cùng tên nên gộp làm một.
2. Schema (JSON-LD) mô tả "hệ sinh thái" chung chung, chép 3 bản khác nhau ở 3 file. Không có trang công khai nào nói rõ Hồ Đình Sang là ai.

## Đã sửa trên bitpawsoftware.com (repo này)

| Việc | Chi tiết |
|---|---|
| Đổi tên thương hiệu | "BitPaw OS" → **"BitPaw Software"** trên toàn web, app mobile và ảnh store (292 chỗ). Tên dưới icon app: "BitPaw POS" |
| 1 nguồn schema duy nhất | `templates/components/entity_schema.html`: Person (Hồ Đình Sang) + 3 Organization, mỗi cái có `description` + `disambiguatingDescription` nói rõ "KHÔNG phải" 2 cái còn lại, cùng `founder` trỏ về 1 Person |
| Trang người sáng lập | `/ho-dinh-sang` (VI + EN, nội dung hiển thị thật, ProfilePage schema). `/founder`, `/about` → 301 về đây |
| Footer mọi trang landing | Dòng "BitPaw Software — phần mềm quản lý · Founded by Hồ Đình Sang" + link 2 thương hiệu anh em kèm mô tả |
| robots.txt + sitemap.xml | `/robots.txt` chặn trang nội bộ (POS, lương...), sitemap gồm 15 URL công khai + `/ho-dinh-sang` |

## VIỆC ANH CẦN LÀM trên 2 site còn lại (repo không có trên máy này)

Google chỉ hợp nhất thành 1 thực thể khi **cả 3 site nói cùng một câu chuyện, cùng `@id`**.

### A. bitpawos.com (project Vercel `pawbook-web`): dán vào `<head>` trang chủ

```html
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "Organization",
      "@id": "https://www.bitpawos.com/#organization",
      "name": "BitPaw OS",
      "alternateName": ["PawNail Jobs", "PawNail"],
      "url": "https://www.bitpawos.com",
      "description": "BitPaw OS (PawNail Jobs) là nền tảng việc làm và cộng đồng ngành nail: chủ tiệm đăng tin tìm thợ, thợ nail tìm việc, hồ sơ tay nghề, nhắn tin và gọi trực tiếp, và nơi thợ nail giới thiệu, bán sản phẩm của mình. BitPaw OS is a job marketplace and community for the nail industry.",
      "disambiguatingDescription": "BitPaw OS is a job marketplace for nail salon owners and nail technicians. It is NOT the BitPaw Software point-of-sale/management software (bitpawsoftware.com) and NOT the Bitpawnetwork marketing service (bitpawnetwork.com).",
      "founder": { "@id": "https://www.bitpawsoftware.com/#founder" }
    },
    {
      "@type": "Person",
      "@id": "https://www.bitpawsoftware.com/#founder",
      "name": "Hồ Đình Sang",
      "alternateName": ["Ho Dinh Sang"],
      "url": "https://www.bitpawsoftware.com/ho-dinh-sang",
      "jobTitle": "Founder"
    },
    {
      "@type": "WebSite",
      "@id": "https://www.bitpawos.com/#website",
      "name": "BitPaw OS",
      "url": "https://www.bitpawos.com",
      "publisher": { "@id": "https://www.bitpawos.com/#organization" }
    }
  ]
}
</script>
```

Thêm vào:
- **Title trang chủ**, ví dụ: `BitPaw OS (PawNail Jobs) | Việc làm ngành nail: chủ tiệm tìm thợ, thợ tìm việc`.
- **Meta description**, ví dụ: `Nền tảng việc làm ngành nail: chủ tiệm đăng tin tìm thợ, thợ nail tìm việc, hồ sơ tay nghề và bán sản phẩm của thợ.`
- **Footer**: `BitPaw OS — nền tảng việc làm ngành nail · Founded by <a href="https://www.bitpawsoftware.com/ho-dinh-sang">Hồ Đình Sang</a> · Thương hiệu anh em: <a href="https://www.bitpawsoftware.com">BitPaw Software</a> (phần mềm quản lý POS) · <a href="https://www.bitpawnetwork.com">Bitpawnetwork</a> (marketing)`
- Bỏ mọi câu trên bitpawos.com tự mô tả là "phần mềm POS / quản lý tiệm" (nếu có). Đó là BitPaw Software.

### B. bitpawnetwork.com (project `tang-tuong-tac`): dán vào `<head>` trang chủ

```html
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "Organization",
      "@id": "https://www.bitpawnetwork.com/#organization",
      "name": "Bitpawnetwork",
      "alternateName": "BitPaw Network",
      "url": "https://www.bitpawnetwork.com",
      "description": "Bitpawnetwork là dịch vụ marketing tự động cho tiệm nail tại Mỹ: SEO Google Maps, bot AI đặt lịch 24/7, quảng cáo mạng xã hội và xác minh tích xanh. Bitpawnetwork is an automated marketing and local SEO service for nail salons.",
      "disambiguatingDescription": "Bitpawnetwork is a marketing / local SEO service for nail salons. It is NOT the BitPaw Software management software (bitpawsoftware.com) and NOT the BitPaw OS job marketplace (bitpawos.com).",
      "founder": { "@id": "https://www.bitpawsoftware.com/#founder" }
    },
    {
      "@type": "Person",
      "@id": "https://www.bitpawsoftware.com/#founder",
      "name": "Hồ Đình Sang",
      "alternateName": ["Ho Dinh Sang"],
      "url": "https://www.bitpawsoftware.com/ho-dinh-sang",
      "jobTitle": "Founder"
    },
    {
      "@type": "WebSite",
      "@id": "https://www.bitpawnetwork.com/#website",
      "name": "Bitpawnetwork",
      "url": "https://www.bitpawnetwork.com",
      "publisher": { "@id": "https://www.bitpawnetwork.com/#organization" }
    }
  ]
}
</script>
```

Footer: `Bitpawnetwork — marketing cho tiệm nail · Founded by <a href="https://www.bitpawsoftware.com/ho-dinh-sang">Hồ Đình Sang</a> · Thương hiệu anh em: <a href="https://www.bitpawsoftware.com">BitPaw Software</a> (phần mềm quản lý POS) · <a href="https://www.bitpawos.com">BitPaw OS</a> (việc làm ngành nail)`

> Nếu 2 site này dùng Next.js: đặt khối trên trong `app/layout.tsx` bằng `<script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(data) }} />`.

## Việc ngoài website (quan trọng không kém)

1. **Google Search Console** (https://search.google.com/search-console): thêm cả 3 domain (Domain property, xác minh bằng DNS TXT trên Cloudflare).
   - bitpawsoftware.com: Sitemaps → gửi `https://www.bitpawsoftware.com/sitemap.xml`.
   - URL Inspection → **Request indexing** cho `https://www.bitpawsoftware.com/ho-dinh-sang`, `/landing`, và trang chủ bitpawos.com + bitpawnetwork.com sau khi dán schema.
2. **Kiểm tra schema**: dán từng URL vào https://search.google.com/test/rich-results và https://validator.schema.org → không được báo lỗi.
3. **Tên thống nhất ở mọi nơi**: Facebook page, Google Business Profile, TikTok, LinkedIn... của phần mềm đổi thành "BitPaw Software". Trang của nền tảng việc làm giữ "BitPaw OS". Mỗi trang ghi 1 câu mô tả giống trên site.
4. **Hồ sơ cá nhân của anh** (Facebook cá nhân, LinkedIn, TikTok, YouTube): phần giới thiệu ghi "Founder of BitPaw Software, BitPaw OS & Bitpawnetwork" + link `https://www.bitpawsoftware.com/ho-dinh-sang`. Gửi em các link này để thêm vào `sameAs` của Person trong `entity_schema.html`. Đây là tín hiệu mạnh nhất để Google tạo "Knowledge Panel" cho tên anh.
5. **(Tuỳ chọn) Wikidata**: tạo item cho Hồ Đình Sang + 3 tổ chức, liên kết "founded by". Google dùng Wikidata làm nguồn tham khảo.
6. **Thời gian**: Google cập nhật AI Overview / Knowledge Graph sau vài tuần tới vài tháng, không có nút "cập nhật ngay". Khi đã có 3 site nói cùng một câu chuyện, có thể bấm "Feedback" dưới AI Overview sai để báo.
