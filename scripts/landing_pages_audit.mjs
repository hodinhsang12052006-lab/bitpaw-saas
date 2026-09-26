/**
 * scripts/landing_pages_audit.mjs
 *
 * Pha 1 của kế hoạch audit toàn bộ codebase — kiểm tra cả 11 trang landing (marketing, công
 * khai, không cần đăng nhập): landing.html (chính) + 10 trang landing_<industry>.html qua route
 * động /solutions/<industry_code> (app.py:2161).
 *
 * Landing page không có business logic phức tạp như POS/booking, nên audit tập trung vào:
 * nội dung đúng/không lỗi, ảnh không vỡ, không link chết, toggle EN/VI hoạt động, không dính
 * copy chéo ngách khác, tiêu đề/meta hợp lý.
 *
 * Chạy:  node scripts/landing_pages_audit.mjs
 * Yêu cầu: server Flask đã chạy tại http://127.0.0.1:5001
 */

import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const BASE = 'http://127.0.0.1:5001';
const SCREEN_DIR = path.resolve('audit-results/screenshots/landing_pages_audit');
fs.mkdirSync(SCREEN_DIR, { recursive: true });

const PAGES = [
  { url: '/landing', file: 'landing.html', label: 'Landing chính', keywords: [] },
  { url: '/solutions/nail', file: 'landing_nail.html', label: 'Nails', keywords: ['nail', 'móng'] },
  { url: '/solutions/spa', file: 'landing_spa.html', label: 'Spa', keywords: ['spa', 'massage'] },
  { url: '/solutions/fnb', file: 'landing_fnb.html', label: 'F&B', keywords: ['nhà hàng', 'thực đơn', 'restaurant'] },
  { url: '/solutions/karaoke', file: 'landing_karaoke.html', label: 'Karaoke', keywords: ['karaoke', 'phòng hát'] },
  { url: '/solutions/hotel', file: 'landing_hotel.html', label: 'Hotel', keywords: ['khách sạn', 'hotel'] },
  { url: '/solutions/retail', file: 'landing_retail.html', label: 'Retail', keywords: ['bán lẻ', 'retail'] },
  { url: '/solutions/office', file: 'landing_office.html', label: 'Office', keywords: ['văn phòng', 'office'] },
  { url: '/solutions/technical', file: 'landing_technical.html', label: 'Technical', keywords: ['kỹ thuật', 'technical'] },
  { url: '/solutions/production', file: 'landing_production.html', label: 'Production', keywords: ['sản xuất', 'production', 'xưởng'] },
  { url: '/solutions/hr', file: 'landing_hr.html', label: 'HR', keywords: ['nhân sự', 'hr'] },
];

const OTHER_INDUSTRY_TERMS = {
  nail: ['manicure', 'pedicure', 'acrylic', 'nail salon', 'nail tech'],
  spa: ['liệu trình', 'trị liệu', 'massage'],
  fnb: ['thực đơn', 'nhà hàng', 'quán ăn', 'món ăn'],
  karaoke: ['phòng hát', 'karaoke', 'billiards', 'bida'],
  hotel: ['khách sạn', 'phòng nghỉ', 'check-in', 'homestay'],
  retail: ['bán lẻ', 'siêu thị', 'cửa hàng tạp hoá'],
  office: ['hành chính văn phòng'],
  technical: ['sửa chữa hiện trường', 'kỹ thuật viên'],
  production: ['xưởng sản xuất', 'công nhân', 'kíp xưởng'],
};

const steps = [];
function record(page_label, name, status, note = '') {
  steps.push({ page: page_label, name, status, note });
  const icon = status === 'PASS' ? '✅' : status === 'WARN' ? '⚠️' : '❌';
  console.log(`${icon} [${status}] [${page_label}] ${name}${note ? ' — ' + note : ''}`);
}

async function main() {
  console.log('=== LANDING PAGES AUDIT — bắt đầu (11 trang) ===\n');
  const browser = await chromium.launch({ channel: 'chrome', headless: true });

  for (const p of PAGES) {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await context.newPage();
    const consoleErrors = [];
    const failed404s = [];
    page.on('console', (msg) => { if (msg.type() === 'error') consoleErrors.push(msg.text()); });
    page.on('pageerror', (err) => consoleErrors.push(String(err)));
    page.on('response', (res) => {
      if (res.status() === 404 && /\.(png|jpg|jpeg|webp|svg|gif)(\?|$)/i.test(res.url())) failed404s.push(res.url());
    });

    try {
      const res = await page.goto(`${BASE}${p.url}`, { waitUntil: 'networkidle', timeout: 20000 });
      const httpOk = res && res.status() === 200;
      record(p.label, '1. Tải trang', httpOk ? 'PASS' : 'FAIL', `HTTP ${res ? res.status() : 'no response'}, url=${p.url}`);
      if (!httpOk) { await context.close(); continue; }

      const title = await page.title();
      record(p.label, '2. Title hợp lệ (không rỗng/generic)', title && title.trim().length > 5 ? 'PASS' : 'WARN', `title="${title}"`);

      await page.waitForTimeout(600); // cho ảnh lazy-load kịp bắn request
      record(p.label, '3. Ảnh không vỡ (404)', failed404s.length === 0 ? 'PASS' : 'FAIL', failed404s.length ? failed404s.slice(0, 5).join(', ') : 'không có ảnh 404');

      // Dead-link check: href="#" mà KHÔNG có onclick xử lý (thực sự chết, bấm không làm gì)
      const deadLinks = await page.evaluate(() => {
        return Array.from(document.querySelectorAll('a[href="#"]:not([onclick])')).map((a) => a.textContent.trim().slice(0, 40));
      });
      record(p.label, '4. Không có link chết (href="#" không xử lý)', deadLinks.length === 0 ? 'PASS' : 'WARN', deadLinks.length ? `${deadLinks.length} link: ${deadLinks.slice(0, 5).join(' | ')}` : 'sạch');

      // EN/VI toggle: trang có auto-detect navigator.language và tự chuyển EN nếu trình duyệt
      // không phải tiếng Việt — Playwright mặc định locale tiếng Anh nên trang có thể ĐÃ ở EN
      // trước khi test chạy. Phải ép về 'vi' làm baseline TRƯỚC, rồi mới đổi sang 'en' và so
      // sánh, không được lấy trạng thái ban đầu (không xác định ngôn ngữ nào) làm baseline.
      const hasChangeLanguage = await page.evaluate(() => typeof window.changeLanguage === 'function');
      let toggleWorks = false;
      if (hasChangeLanguage) {
        await page.evaluate(() => window.changeLanguage('vi'));
        await page.waitForTimeout(300);
        const bodyVi = await page.locator('body').innerText();
        await page.evaluate(() => window.changeLanguage('en'));
        await page.waitForTimeout(300);
        const bodyEn = await page.locator('body').innerText();
        toggleWorks = bodyEn !== bodyVi;
        await page.evaluate(() => window.changeLanguage('vi'));
      }
      record(p.label, '5. Toggle EN/VI hoạt động', hasChangeLanguage ? (toggleWorks ? 'PASS' : 'FAIL') : 'WARN',
        hasChangeLanguage ? `nội dung có đổi khi chuyển EN: ${toggleWorks}` : 'không tìm thấy hàm changeLanguage() trên trang này');

      // (Đã bỏ check "cross-contamination" theo từ khoá — false positive 100% các trang do
      // components/mobile_bottom_nav.html là menu chuyển-ngành dùng chung hợp lệ, tự nhiên
      // chứa tên MỌI ngách trên MỌI trang landing. Xác nhận qua grep trực tiếp, không phải bug.)

      await page.screenshot({ path: path.join(SCREEN_DIR, `${p.file.replace('.html', '')}.png`), fullPage: true });
      record(p.label, '6. Console errors', consoleErrors.length === 0 ? 'PASS' : 'WARN', consoleErrors.length ? `${consoleErrors.length} lỗi: ${consoleErrors.slice(0, 2).join(' | ')}` : 'sạch');

    } catch (e) {
      record(p.label, 'LỖI KHÔNG MONG MUỐN', 'FAIL', e.message);
    }
    await context.close();
  }

  await browser.close();

  console.log('\n=== TỔNG KẾT ===');
  console.table(steps.map((s) => ({ Page: s.page, Step: s.name, Status: s.status })));
  const pass = steps.filter((s) => s.status === 'PASS').length;
  const warn = steps.filter((s) => s.status === 'WARN').length;
  const fail = steps.filter((s) => s.status === 'FAIL').length;
  console.log(`\nTổng kết: ${pass} PASS · ${warn} WARN · ${fail} FAIL`);

  fs.writeFileSync(
    path.resolve('audit-results/landing_pages_audit_report.json'),
    JSON.stringify({ ranAt: new Date().toISOString(), steps }, null, 2),
  );
  process.exit(fail > 0 ? 1 : 0);
}

main();
