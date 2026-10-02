// Mở /sell và chờ lưới dịch vụ render. Trên máy dev Windows (Werkzeug + Avast quét loopback),
// thỉnh thoảng một response HTML lớn bị treo ~20s rồi ERR_CONNECTION_RESET — xảy ra ở cả /landing
// (trang tĩnh, không DB), không phải lỗi code /sell. Tải lại tối đa `attempts` lần để test không
// fail ngẫu nhiên; nếu vẫn hỏng sau đó thì ném lỗi thật kèm chẩn đoán.
export async function gotoSell(page, base, { attempts = 3, waitUntil = 'networkidle', query = '' } = {}) {
  let lastErr;
  for (let i = 1; i <= attempts; i++) {
    try {
      const resp = await page.goto(`${base}/sell${query}`, { waitUntil, timeout: 30000 });
      await page.waitForSelector('#serviceGrid .service-card', { timeout: 10000 });
      if (i > 1) console.log(`   ↻ /sell render OK sau ${i} lần tải (lần trước bị reset kết nối dev server)`);
      return resp;
    } catch (err) {
      lastErr = err;
    }
  }
  const diag = await page.evaluate(() => ({
    readyState: document.readyState, servicesType: typeof SERVICES,
    htmlLength: document.documentElement.outerHTML.length,
  })).catch((e) => ({ evalError: String(e) }));
  throw new Error(`/sell không render lưới dịch vụ sau ${attempts} lần: ${lastErr && lastErr.message.split('\n')[0]} diag=${JSON.stringify(diag)}`);
}

// Chụp ảnh không làm hỏng test: trên máy Windows này file PNG thỉnh thoảng bị khoá (Avast quét file
// mới ghi) -> page.screenshot ném "UNKNOWN: unknown error, open ...png" và làm FAIL cả bước test dù
// logic nghiệp vụ không hề lỗi. Thử lại 3 lần; vẫn không ghi được thì chỉ cảnh báo, không ném lỗi.
export async function safeScreenshot(page, options) {
  for (let i = 1; i <= 3; i++) {
    try { return await page.screenshot(options); }
    catch (err) {
      if (i === 3) { console.warn(`   ⚠ không ghi được ảnh ${options && options.path} (${err.message.split('\n')[0]}) — bỏ qua, không ảnh hưởng kết quả test`); return null; }
      await page.waitForTimeout(400 * i);
    }
  }
}
