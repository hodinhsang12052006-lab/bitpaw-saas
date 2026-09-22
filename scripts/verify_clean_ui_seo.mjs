import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const SCREENSHOT_DIR = path.resolve('audit-results/screenshots/clean_ui');
if (!fs.existsSync(SCREENSHOT_DIR)) {
  fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
}

async function runCleanVerification() {
  console.log('--- STARTING CLEAN UI & INVISIBLE SEO AUDIT ---');
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1366, height: 768 } });

  // 1. Check /about -> MUST BE 404
  console.log('\n[CHECK 1] Verify /about is hidden (HTTP 404)...');
  const resAbout = await page.goto('http://127.0.0.1:5001/about');
  console.log(`/about Status: ${resAbout.status()}`);
  if (resAbout.status() !== 404) {
    throw new Error(`Expected 404 on /about, got ${resAbout.status()}`);
  }
  console.log('✓ /about is properly disabled (404 Not Found)');

  // 2. Check /founder -> MUST BE 404
  console.log('\n[CHECK 2] Verify /founder is hidden (HTTP 404)...');
  const resFounder = await page.goto('http://127.0.0.1:5001/founder');
  console.log(`/founder Status: ${resFounder.status()}`);
  if (resFounder.status() !== 404) {
    throw new Error(`Expected 404 on /founder, got ${resFounder.status()}`);
  }
  console.log('✓ /founder is properly disabled (404 Not Found)');

  // 3. Check /landing
  console.log('\n[CHECK 3] Navigating to http://127.0.0.1:5001/landing ...');
  const resLanding = await page.goto('http://127.0.0.1:5001/landing', { waitUntil: 'networkidle' });
  console.log(`/landing Status: ${resLanding.status()}`);

  // Check that NO link to /about exists
  const aboutLinks = await page.$$('a[href="/about"], a[href="/founder"]');
  if (aboutLinks.length > 0) {
    throw new Error(`Found ${aboutLinks.length} visible links to /about or /founder in DOM!`);
  }
  console.log('✓ Zero visible links to /about or /founder in DOM');

  // Check visible body text
  const bodyText = await page.evaluate(() => document.body.innerText);
  if (bodyText.includes('Hồ Đình Sang') || bodyText.includes('Sang Cún') || bodyText.includes('(Cún)')) {
    throw new Error('Founder personal name found in visible body text!');
  }
  console.log('✓ Visible UI is 100% clean: No personal names displayed');

  // Check copyright text
  const footerText = await page.evaluate(() => document.querySelector('footer')?.innerText || '');
  console.log('Footer text excerpt:', footerText.slice(-300).trim());
  if (!footerText.includes('© 2026 BitPaw Software. All rights reserved. Powered by BitPaw OS.')) {
    console.warn('Warning: Exact copyright line not matched in footer text');
  } else {
    console.log('✓ Enterprise copyright verified: "© 2026 BitPaw Software. All rights reserved. Powered by BitPaw OS."');
  }

  // 4. Verify Invisible Metadata in <head>
  console.log('\n[CHECK 4] Checking invisible metadata in <head> for Google AI Overview...');
  const authorMeta = await page.$eval('meta[name="author"]', el => el.getAttribute('content'));
  const creatorMeta = await page.$eval('meta[name="creator"]', el => el.getAttribute('content'));
  const publisherMeta = await page.$eval('meta[name="publisher"]', el => el.getAttribute('content'));

  console.log(`meta author: "${authorMeta}"`);
  console.log(`meta creator: "${creatorMeta}"`);
  console.log(`meta publisher: "${publisherMeta}"`);

  if (authorMeta !== 'Hồ Đình Sang (Cún)') throw new Error('meta author mismatch!');
  if (creatorMeta !== 'Hồ Đình Sang') throw new Error('meta creator mismatch!');
  if (publisherMeta !== 'BitPaw Ecosystem') throw new Error('meta publisher mismatch!');
  console.log('✓ All invisible meta tags verified perfectly in <head>');

  // Check Schema JSON-LD in <head>
  const jsonLdContent = await page.$$eval('script[type="application/ld+json"]', scripts => {
    return scripts.map(s => {
      try {
        return JSON.parse(s.textContent);
      } catch (e) {
        return null;
      }
    }).filter(Boolean);
  });

  let personFound = false;
  let orgFound = false;
  for (const block of jsonLdContent) {
    const graph = block['@graph'] || [block];
    for (const item of graph) {
      if (item['@type'] === 'Person' && item.name === 'Hồ Đình Sang') {
        personFound = true;
      }
      if (item['@type'] === 'Organization' && item.name === 'BitPaw Ecosystem') {
        orgFound = true;
      }
    }
  }

  if (!personFound || !orgFound) {
    throw new Error('Schema JSON-LD missing Person or Organization in <head>!');
  }
  console.log('✓ Schema JSON-LD with Person (Hồ Đình Sang) and Organization (BitPaw Ecosystem) verified in <head>');

  // Take Screenshots for proof
  const navEl = await page.$('header nav');
  if (navEl) {
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '01_clean_desktop_nav.png') });
  }

  const footerEl = await page.$('footer');
  if (footerEl) {
    await footerEl.scrollIntoViewIfNeeded();
    await page.waitForTimeout(500);
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '02_clean_enterprise_footer.png') });
  }

  await browser.close();
  console.log('\n--- ALL CLEAN UI & INVISIBLE SEO AUDIT TESTS PASSED ---');
}

runCleanVerification().catch(err => {
  console.error('Audit failed:', err);
  process.exit(1);
});
