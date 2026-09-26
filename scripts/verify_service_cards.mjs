import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const SCREENSHOT_DIR = path.resolve('audit-results/screenshots/service_cards');
if (!fs.existsSync(SCREENSHOT_DIR)) {
  fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
}

async function verifyServiceCards() {
  console.log('--- STARTING SERVICE CARDS & SEARCH BAR AUDIT ---');
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1366, height: 768 },
    deviceScaleFactor: 1,
  });
  const page = await context.newPage();

  // 1. Login
  console.log('Logging in as Nail Demo user...');
  await page.goto('http://127.0.0.1:5001/login', { waitUntil: 'networkidle' });
  await page.fill('input[name="email"]', 'demo.nails.au.006758@bitpawdemo.com');
  await page.fill('input[name="password"]', 'DemoNails2026!');
  await page.click('button[type="submit"]');
  await page.waitForLoadState('networkidle');

  // 2. Navigate to POS
  console.log('Navigating to /sell (Nail POS)...');
  await page.goto('http://127.0.0.1:5001/sell', { waitUntil: 'networkidle' });
  await page.waitForTimeout(1000);

  // 3. Verify Search Bar
  console.log('Verifying Search Bar...');
  const searchInput = await page.$('#serviceSearchInput');
  if (!searchInput) throw new Error('#serviceSearchInput not found!');

  const placeholder = await searchInput.getAttribute('placeholder');
  console.log(`Search Placeholder: "${placeholder}"`);
  if (!placeholder.includes('Tìm tên dịch vụ') && !placeholder.includes('Search services')) {
    console.warn(`Placeholder check note: got "${placeholder}"`);
  }

  // 4. Verify Service Cards Structure
  console.log('Verifying Service Cards structural layout...');
  const cardCount = await page.$$eval('.service-card', cards => cards.length);
  console.log(`Found ${cardCount} service cards in grid`);
  if (cardCount === 0) throw new Error('No service cards found in #serviceGrid!');

  const cardValidation = await page.$$eval('.service-card', cards => {
    return cards.slice(0, 5).map(card => {
      const thumb = card.querySelector('.card-thumb-wrap');
      const img = card.querySelector('.service-card-img');
      const badge = card.querySelector('.service-category-badge');
      const info = card.querySelector('.service-info-wrap');
      const name = card.querySelector('.service-name-text');
      const price = card.querySelector('.service-price-val');
      const currency = card.querySelector('.service-currency-label');

      return {
        hasThumb: !!thumb,
        hasImg: !!img,
        hasBadge: !!badge,
        hasInfo: !!info,
        hasName: !!name,
        hasPrice: !!price,
        hasCurrency: !!currency,
        thumbHeight: thumb ? thumb.clientHeight : 0,
        nameText: name ? name.innerText.trim() : '',
        priceText: price ? price.innerText.trim() : '',
        currencyText: currency ? currency.innerText.trim() : '',
      };
    });
  });

  console.log('Sample Card Verifications:');
  cardValidation.forEach((c, idx) => {
    console.log(`Card ${idx + 1}: Name="${c.nameText}", Price="${c.priceText} ${c.currencyText}", ThumbHeight=${c.thumbHeight}px, Badge=${c.hasBadge}`);
    if (!c.hasThumb || !c.hasInfo || !c.hasName || !c.hasPrice) {
      throw new Error(`Card ${idx + 1} failed structural validation!`);
    }
  });

  // Take Screenshots
  console.log('Capturing screenshots...');
  // Full POS Screen
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, '01_pos_service_matrix_redesign.png') });

  // Zoomed in on Service Grid & Search Bar — current markup has no #tabPanel-service (old tab
  // system was replaced by ticket-tab-btn/switchLeftTab()); use the service grid container itself.
  const catalogSection = await page.$('#serviceGrid') || await page.$('.service-card');
  if (catalogSection) {
    await catalogSection.screenshot({ path: path.join(SCREENSHOT_DIR, '02_service_catalog_and_search.png') });
  }

  // Hover on first card
  const firstCard = await page.$('.service-card');
  if (firstCard) {
    await firstCard.hover();
    await page.waitForTimeout(300);
    await firstCard.screenshot({ path: path.join(SCREENSHOT_DIR, '03_service_card_hover_amber.png') });
  }

  // Test Search Interaction
  console.log('Testing search query...');
  await page.fill('#serviceSearchInput', 'Gel');
  await page.waitForTimeout(400);
  const filteredCount = await page.$$eval('.service-card', cards => cards.length);
  console.log(`Filtered by "Gel": ${filteredCount} cards displayed`);
  await catalogSection.screenshot({ path: path.join(SCREENSHOT_DIR, '04_service_search_filtered.png') });

  // Clear search
  await page.fill('#serviceSearchInput', '');
  await page.waitForTimeout(400);

  await browser.close();
  console.log('--- ALL SERVICE CARD & SEARCH AUDITS PASSED ---');
}

verifyServiceCards().catch(err => {
  console.error('Audit failed:', err);
  process.exit(1);
});
