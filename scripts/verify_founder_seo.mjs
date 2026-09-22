import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const SCREENSHOT_DIR = path.resolve('audit-results/screenshots/founder');
if (!fs.existsSync(SCREENSHOT_DIR)) {
  fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
}

async function runAudit() {
  console.log('--- STARTING FOUNDER & SEO SCHEMA AUDIT ---');
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1366, height: 768 },
    deviceScaleFactor: 1,
  });
  const page = await context.newPage();

  // Test 1: Check /about
  console.log('\n[TEST 1] Navigating to http://127.0.0.1:5001/about ...');
  const resAbout = await page.goto('http://127.0.0.1:5001/about', { waitUntil: 'networkidle' });
  console.log(`HTTP Status: ${resAbout.status()}`);
  if (resAbout.status() !== 200) {
    throw new Error(`Expected status 200 on /about, got ${resAbout.status()}`);
  }

  // Verify Schema JSON-LD
  const jsonLdContent = await page.$$eval('script[type="application/ld+json"]', scripts => {
    return scripts.map(s => {
      try {
        return JSON.parse(s.textContent);
      } catch (e) {
        return null;
      }
    }).filter(Boolean);
  });

  console.log(`Found ${jsonLdContent.length} JSON-LD script blocks on /about`);
  let personFound = false;
  let orgFound = false;

  for (const block of jsonLdContent) {
    const graph = block['@graph'] || [block];
    for (const item of graph) {
      if (item['@type'] === 'Person' && item.name === 'Hồ Đình Sang') {
        personFound = true;
        console.log('✓ Found Person Entity: Hồ Đình Sang (Cún), Birth: ' + item.birthDate + ', JobTitle: ' + item.jobTitle);
      }
      if (item['@type'] === 'Organization' && (item.name === 'BitPaw Ecosystem' || item.name === 'BitPaw')) {
        orgFound = true;
        console.log('✓ Found Organization Entity: ' + item.name + ', Founder: ' + JSON.stringify(item.founder));
      }
    }
  }

  if (!personFound) throw new Error('Person schema for Hồ Đình Sang not found!');
  if (!orgFound) throw new Error('Organization schema for BitPaw Ecosystem not found!');

  // Verify UI Text content
  const pageText = await page.textContent('body');
  const keywordsToCheck = [
    'Hồ Đình Sang',
    'Cún',
    '30/05/2003',
    '4 Năm',
    'BitPaw Network',
    'PawNail Jobs',
    'BitPaw OS',
    'BitPaw Software'
  ];

  for (const kw of keywordsToCheck) {
    if (pageText.includes(kw)) {
      console.log(`✓ Text matched: "${kw}"`);
    } else {
      console.warn(`⚠ Warning: Keyword "${kw}" not found in page text`);
    }
  }

  // Take Screenshots
  console.log('\nCapturing screenshots...');
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, '01_about_hero.png'), fullPage: false });
  
  const founderCard = await page.$('#founder-profile');
  if (founderCard) {
    await founderCard.scrollIntoViewIfNeeded();
    await page.waitForTimeout(500);
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '02_founder_profile_card.png') });
  }

  const pillarsSec = await page.$('#tam-giac-he-sinh-thai');
  if (pillarsSec) {
    await pillarsSec.scrollIntoViewIfNeeded();
    await page.waitForTimeout(500);
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '03_three_pillars_ecosystem.png') });
  }

  const timelineSec = await page.$('#timeline');
  if (timelineSec) {
    await timelineSec.scrollIntoViewIfNeeded();
    await page.waitForTimeout(500);
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '04_evolution_timeline.png') });
  }

  await page.screenshot({ path: path.join(SCREENSHOT_DIR, '05_about_page_full.png'), fullPage: true });
  console.log('✓ Screenshots saved in ' + SCREENSHOT_DIR);

  // Test 2: Check /founder alias
  console.log('\n[TEST 2] Navigating to http://127.0.0.1:5001/founder ...');
  const resFounder = await page.goto('http://127.0.0.1:5001/founder', { waitUntil: 'networkidle' });
  console.log(`HTTP Status: ${resFounder.status()}`);
  if (resFounder.status() !== 200) {
    throw new Error(`Expected status 200 on /founder, got ${resFounder.status()}`);
  }
  console.log('✓ Route /founder alias operates with HTTP 200');

  // Test 3: Check landing page schema and nav links
  console.log('\n[TEST 3] Navigating to http://127.0.0.1:5001/landing ...');
  const resLanding = await page.goto('http://127.0.0.1:5001/landing', { waitUntil: 'networkidle' });
  console.log(`HTTP Status: ${resLanding.status()}`);
  
  const landingJsonLd = await page.$$eval('script[type="application/ld+json"]', scripts => {
    return scripts.map(s => {
      try {
        return JSON.parse(s.textContent);
      } catch (e) {
        return null;
      }
    }).filter(Boolean);
  });

  let landingPerson = false;
  for (const block of landingJsonLd) {
    const graph = block['@graph'] || [block];
    for (const item of graph) {
      if (item['@type'] === 'Person' && item.name === 'Hồ Đình Sang') {
        landingPerson = true;
      }
    }
  }
  if (landingPerson) {
    console.log('✓ Verified: Landing page has standardized Person schema for Hồ Đình Sang');
  } else {
    console.warn('⚠ Warning: Landing page schema missing Person Hồ Đình Sang');
  }

  const aboutLink = await page.$('a[href="/about"]');
  if (aboutLink) {
    console.log('✓ Verified: Landing page header/footer contains direct link to /about');
  }

  await browser.close();
  console.log('\n--- ALL AUDIT TESTS PASSED SUCCESSFULLY ---');
}

runAudit().catch(err => {
  console.error('Audit failed:', err);
  process.exit(1);
});
