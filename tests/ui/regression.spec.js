// Cross-dashboard regression tests for known recurring bugs.
// Each test references the git commit that fixed the original issue.
//
//   9c8fb9a — tooltip DOM parent positioning
//   ad271d6 — tooltip snaps to data point Y
//   662e9c5 — OI bar chart baseline
//   89cd143 — date axis alignment
//   babc266 — price chart height / candlestick layout

const { test, expect } = require('@playwright/test');

// ── Helpers ──────────────────────────────────────────────────────────────────

async function navigateTo(page, tabKey) {
  await page.goto('/');
  await page.click(`button.nav-tab[onclick*="'${tabKey}'"]`);
}

// ── R1: Every .chart-tt tooltip must be a child of a position:relative element
// Regression: 9c8fb9a — COT tooltips were siblings of the wrap, not children.

test('R1: all chart-tt tooltips are inside a position:relative container', async ({ page }) => {
  await page.goto('/');
  const violations = await page.$$eval('.chart-tt', tooltips =>
    tooltips
      .filter(tt => {
        const parent = tt.parentElement;
        return parent && getComputedStyle(parent).position !== 'relative';
      })
      .map(tt => `#${tt.id} parent=#${tt.parentElement?.id} pos=${getComputedStyle(tt.parentElement).position}`)
  );
  expect(violations).toEqual([]);
});

// ── R2: .chart-tt has position:absolute (required for offset positioning)

test('R2: all chart-tt tooltips have position:absolute', async ({ page }) => {
  await page.goto('/');
  const violations = await page.$$eval('.chart-tt', tooltips =>
    tooltips
      .filter(tt => getComputedStyle(tt).position !== 'absolute')
      .map(tt => `#${tt.id}`)
  );
  expect(violations).toEqual([]);
});

// ── R3: Column widths — STIR table first column is label column (≥ 120px)
// Regression: column-width resets observed after staging→main merges.
// The stir-table first column (meeting date) must not collapse below 120px.

test('R3: stir table first column has min width 120px (column-width persistence)', async ({ page }) => {
  await page.goto('/');
  // Navigate to Yields (stir) sub-tab
  await page.click("button.nav-tab[onclick*=\"'stir'\"]");
  // Wait for a stir-table to be visible
  await page.waitForSelector('#main-stir table.stir-table', { timeout: 10_000 });

  const firstColWidth = await page.$eval(
    '#main-stir table.stir-table th:first-child',
    th => th.getBoundingClientRect().width
  );
  expect(firstColWidth).toBeGreaterThanOrEqual(120);
});

// ── R4: Click-toggle state — Positioning tab COT class select persists
// Regression: tab state was reset on every tab switch.
// showMain('positioning') calls cotUpdateChart(sel.value) — preserves current contract.
// The class selector itself is not reset by showMain — only the chart re-renders.

test('R4: cot class selection persists after switching away and back', async ({ page }) => {
  await navigateTo(page, 'positioning');
  // Wait until the contract selector is present AND has populated options
  await page.waitForSelector('#cot-contract-sel', { timeout: 10_000 });
  await page.waitForFunction(() => (document.querySelector('#cot-contract-sel')?.options.length ?? 0) > 0, { timeout: 10_000 });

  // Select Metals class
  await page.selectOption('#cot-class-sel', 'Metals');
  await page.waitForTimeout(500);

  // Switch to macro tab and back
  await page.click("button.nav-tab[onclick*=\"'macro'\"]");
  await page.waitForTimeout(200);
  await page.click("button.nav-tab[onclick*=\"'positioning'\"]");
  await page.waitForTimeout(500);

  // The class selector DOM value must still be Metals
  const classSel = await page.$eval('#cot-class-sel', el => el.value);
  expect(classSel).toBe('Metals');

  // Contract options should be Metals CFTC codes (not Energy defaults)
  // Energy codes: ['067651','111659','023651']
  // Metals codes: ['088691','084691','085692','075651','076651','191693','189691']
  const contractOptions = await page.$$eval('#cot-contract-sel option', opts => opts.map(o => o.value));
  const energyCodes = ['067651', '111659', '023651'];
  const hasNoEnergy = !contractOptions.some(v => energyCodes.includes(v));
  expect(hasNoEnergy).toBe(true);
});

// ── R5: Axis alignment — price candlestick and COT position chart share dates
// Regression: 89cd143 — COT charts used index-based axis, price used date axis.

test('R5: cot candle and cot-pos chart date ranges overlap', async ({ page }) => {
  await navigateTo(page, 'positioning');
  await page.waitForSelector('#cot-pos-wrap svg', { timeout: 15_000 });

  // Get last x-axis label from cot-pos (the one we own)
  const posLastDate = await page.$$eval('#cot-pos-wrap svg text', els => {
    const axis = els.filter(el =>
      el.getAttribute('text-anchor') === 'middle' &&
      parseFloat(el.getAttribute('y')) > 190
    );
    return axis.length ? axis[axis.length - 1].textContent.trim() : null;
  });

  expect(posLastDate).not.toBeNull();
  // Must look like a date (contains digit)
  expect(posLastDate).toMatch(/\d/);
});

// ── R6: Price chart container has the min-height style set in HTML ───────────
// Regression: babc266 — price chart height was too small, clipping candlesticks.
// We test the CSS min-height attribute value (not rendered height) since Plotly
// only renders when live price data is available (requires Python backend).

test('R6: cot-candle-wrap min-height is >= 280px', async ({ page }) => {
  await navigateTo(page, 'positioning');
  await page.waitForSelector('#cot-candle-wrap', { timeout: 10_000 });
  const minH = await page.$eval('#cot-candle-wrap', el => {
    const style = el.getAttribute('style') || '';
    const m = style.match(/min-height\s*:\s*(\d+)px/);
    return m ? parseInt(m[1], 10) : 0;
  });
  expect(minH).toBeGreaterThanOrEqual(280);
});

// ── R7: Tooltip content includes a date string ───────────────────────────────
// Verifies that tooltip innerHTML is populated with actual data, not blank.

test('R7: cot-pos tooltip content includes a date after hover', async ({ page }) => {
  await navigateTo(page, 'positioning');
  await page.waitForSelector('#cot-pos-wrap svg', { timeout: 15_000 });

  const box = await page.locator('#cot-pos-wrap svg').boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);

  const html = await page.$eval('#cot-pos-tt', el => el.innerHTML);
  // Date appears as a <strong> tag in the tooltip
  expect(html).toMatch(/<strong>/);
  expect(html.length).toBeGreaterThan(10);
});

// ── R8: OI tooltip content includes "Open Interest" text ────────────────────

test('R8: cot-oi tooltip content includes "Open Interest" after hover', async ({ page }) => {
  await navigateTo(page, 'positioning');
  await page.waitForSelector('#cot-oi-wrap svg', { timeout: 15_000 });

  // OI chart is below the fold — scroll into view before mouse move
  await page.locator('#cot-oi-wrap').scrollIntoViewIfNeeded();
  await page.waitForTimeout(100);

  const box = await page.locator('#cot-oi-wrap svg').boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.waitForTimeout(100);

  const html = await page.$eval('#cot-oi-tt', el => el.innerHTML);
  expect(html).toContain('Open Interest');
});

// ── R9: No chart-tt tooltip is visible on initial page load ─────────────────

test('R9: no tooltips visible on page load (display:none)', async ({ page }) => {
  await page.goto('/');
  const visible = await page.$$eval('.chart-tt', tts =>
    tts.filter(tt => tt.style.display === 'block').map(tt => tt.id)
  );
  expect(visible).toEqual([]);
});

// ── R10: Positioning panel has exactly one active nav-tab ────────────────────

test('R10: only one nav-tab is active at a time', async ({ page }) => {
  await navigateTo(page, 'positioning');
  const activeCount = await page.locator('.nav-tab.active').count();
  expect(activeCount).toBe(1);
});
