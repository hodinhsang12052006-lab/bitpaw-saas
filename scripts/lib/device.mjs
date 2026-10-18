// Chọn thiết bị cho các bộ test: DEVICE=mobile -> giả lập iPhone 13 thật (khung 390x664, UA Safari iOS, cảm ứng,
// isMobile) trên Chrome; mặc định máy tính 1440x900. Dùng chung để chạy LẠI ĐÚNG 1 kịch bản trên cả 2 loại máy.
import { devices } from 'playwright';

export const DEVICE = (process.env.DEVICE || 'desktop').toLowerCase();
export const IS_MOBILE = DEVICE === 'mobile';

export function ownerContextOptions(extra = {}) {
  if (IS_MOBILE) {
    const { defaultBrowserType, ...iphone } = devices['iPhone 13'];
    return { ...iphone, deviceScaleFactor: 2, ...extra };
  }
  return { viewport: { width: 1440, height: 900 }, ...extra };
}
